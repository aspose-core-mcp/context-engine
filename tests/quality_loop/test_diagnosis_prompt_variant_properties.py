"""Property-based tests for the DiagnosisAgent prompt-variant detector.

The example-based suite in ``test_diagnosis_prompt_variant.py`` pins
specific shapes; this fuzzes the detector over wide
(variant_count, samples_per_variant, score_distribution) inputs and
asserts the contract invariants the ProposalAgent depends on:

* **Needs two variants** — with fewer than two *eligible* variants
  (a variant is eligible only with ≥ ``prompt_variant_min_samples``
  observations) the detector emits nothing.
* **Gap gate** — a report is emitted for a variant iff it is not the
  best eligible variant and its mean ``overall_score`` lags the best by
  at least ``prompt_variant_min_mean_gap``.
* **Scope contract** — every emitted report's ``affected_scope`` carries
  both ``prompt_pack_version`` and ``candidate_prompt_pack_version``,
  with the candidate equal to the best variant and distinct from the
  under-performer. (These exact keys are what ProposalAgent reads when
  it builds the ADJUST_PROMPT_VARIANT proposal.)
* **Determinism** — the same verdict batch yields the same set of
  (under-performer, candidate) pairs across runs.

Means are recomputed in the test with the *same* arithmetic the source
uses (``sum(scores) / len(scores)`` over the per-variant score list in
appearance order), so boundary comparisons are bit-identical and the
predicted report count matches exactly — no float-flakiness.
"""

from __future__ import annotations

from collections import defaultdict

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from adcs.quality_loop import DiagnosisAgent
from adcs.quality_loop.diagnosis_agent import DiagnosisAgentConfig
from adcs.quality_loop.models import (
    DiagnosisRootCause,
    QualityVerdict,
    VerdictDimension,
)

_VARIANT_NAMES = ("vA", "vB", "vC", "vD")
_CONFIG = DiagnosisAgentConfig()
_MIN_SAMPLES = _CONFIG.prompt_variant_min_samples  # 3
_MIN_GAP = _CONFIG.prompt_variant_min_mean_gap  # 0.10


def _make_verdict(idx: int, score: float, variant: str | None) -> QualityVerdict:
    return QualityVerdict(
        sample_id=f"s{idx}",
        cycle_id="cyc",
        emitted_at="2026-06-02T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        overall_score=score,
        per_dimension={
            VerdictDimension.CITATION_ACCURACY.value: 1.0,
            VerdictDimension.VERSION_MATCH.value: 1.0,
            VerdictDimension.SYMBOL_FQN_CONSISTENCY.value: 1.0,
            VerdictDimension.CONFIDENCE_CALIBRATION.value: 1.0,
        },
        prompt_pack_version=variant,
    )


_score = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def _verdict_batch(draw: st.DrawFn) -> tuple[QualityVerdict, ...]:
    n_variants = draw(st.integers(min_value=1, max_value=4))
    names = _VARIANT_NAMES[:n_variants]
    verdicts: list[QualityVerdict] = []
    idx = 0
    for name in names:
        count = draw(st.integers(min_value=1, max_value=6))
        for _ in range(count):
            verdicts.append(_make_verdict(idx, draw(_score), name))
            idx += 1
    # Optional None-variant noise — must never count toward eligibility.
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        verdicts.append(_make_verdict(idx, draw(_score), None))
        idx += 1
    return tuple(verdicts)


def _eligible_means(
    verdicts: tuple[QualityVerdict, ...],
) -> dict[str, float]:
    """Replicate the source's per-variant mean exactly (sum/len in order)."""
    by_variant: dict[str, list[float]] = defaultdict(list)
    for v in verdicts:
        if v.prompt_pack_version is not None:
            by_variant[v.prompt_pack_version].append(v.overall_score)
    eligible = {k: s for k, s in by_variant.items() if len(s) >= _MIN_SAMPLES}
    return {k: sum(s) / len(s) for k, s in eligible.items()}


def _variant_reports(agent: DiagnosisAgent, verdicts: tuple[QualityVerdict, ...]):
    reports = agent.diagnose_batch(verdicts=verdicts, cycle_id="cyc")
    return [
        r
        for r in reports
        if r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
    ]


@given(verdicts=_verdict_batch())
@settings(max_examples=300, deadline=None)
def test_fewer_than_two_eligible_variants_never_emits(
    verdicts: tuple[QualityVerdict, ...],
) -> None:
    assume(len(verdicts) >= _CONFIG.minimum_cluster_size)  # clear the batch gate
    means = _eligible_means(verdicts)
    assume(len(means) < 2)
    assert _variant_reports(DiagnosisAgent(), verdicts) == []


@given(verdicts=_verdict_batch())
@settings(max_examples=400, deadline=None)
def test_report_count_and_scope_match_the_gap_contract(
    verdicts: tuple[QualityVerdict, ...],
) -> None:
    assume(len(verdicts) >= _CONFIG.minimum_cluster_size)
    means = _eligible_means(verdicts)
    assume(len(means) >= 2)

    best = max(means, key=lambda k: means[k])
    best_mean = means[best]
    expected_underperformers = {
        variant
        for variant, mean in means.items()
        if variant != best and (best_mean - mean) >= _MIN_GAP
    }

    reports = _variant_reports(DiagnosisAgent(), verdicts)

    # Exact count — the gap gate is honoured, no over- or under-emission.
    assert len(reports) == len(expected_underperformers)

    seen_underperformers = set()
    for report in reports:
        scope = report.affected_scope
        # (c) scope contract — the exact keys ProposalAgent consumes
        assert "prompt_pack_version" in scope
        assert "candidate_prompt_pack_version" in scope
        under = scope["prompt_pack_version"]
        candidate = scope["candidate_prompt_pack_version"]
        assert candidate == best
        assert under != candidate
        # (b) the emitted under-performer really lags by >= threshold
        assert (best_mean - means[under]) >= _MIN_GAP
        seen_underperformers.add(under)

    assert seen_underperformers == expected_underperformers


@given(verdicts=_verdict_batch())
@settings(max_examples=200, deadline=None)
def test_detector_is_deterministic_over_pairs(
    verdicts: tuple[QualityVerdict, ...],
) -> None:
    assume(len(verdicts) >= _CONFIG.minimum_cluster_size)

    def pairs() -> set[tuple[str, str]]:
        return {
            (
                r.affected_scope["prompt_pack_version"],
                r.affected_scope["candidate_prompt_pack_version"],
            )
            for r in _variant_reports(DiagnosisAgent(), verdicts)
        }

    assert pairs() == pairs()


@given(verdicts=_verdict_batch())
@settings(max_examples=200, deadline=None)
def test_emitted_count_never_exceeds_eligible_minus_one(
    verdicts: tuple[QualityVerdict, ...],
) -> None:
    assume(len(verdicts) >= _CONFIG.minimum_cluster_size)
    means = _eligible_means(verdicts)
    reports = _variant_reports(DiagnosisAgent(), verdicts)
    # At most one report per non-best eligible variant.
    assert len(reports) <= max(0, len(means) - 1)
