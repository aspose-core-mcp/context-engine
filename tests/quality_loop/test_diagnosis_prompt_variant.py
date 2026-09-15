"""Tests for DiagnosisAgent prompt-variant under-performance detection.

This closes the wire between the prompt registry (where variants are
defined) and the AdaptiveAgent (which acts on diagnoses): without this
detector, no DiagnosisReport ever carries
``PROMPT_VARIANT_UNDERPERFORMING`` as its root cause, so the
``ADJUST_PROMPT_VARIANT`` ProposalAgent branch was unreachable.

The contract:

* When ≥ 2 distinct prompt-pack variants appear in the cycle's verdicts
  and one variant's mean overall_score lags the best variant by more
  than ``prompt_variant_min_mean_gap``, emit one diagnosis per
  under-performing variant.
* Scope keys must be exactly ``prompt_pack_version``,
  ``candidate_prompt_pack_version``, ``mean_gap``, and
  ``low_score_fraction`` — those are the names ProposalAgent reads.
* The detector must not fire when there is only one variant in the
  batch (no comparison possible) or when an under-performing variant
  has fewer than ``prompt_variant_min_samples`` observations.
"""

from __future__ import annotations

from adcs.quality_loop import DiagnosisAgent, ProposalAgent
from adcs.quality_loop.diagnosis_agent import DiagnosisAgentConfig
from adcs.quality_loop.models import (
    DiagnosisRootCause,
    ProposalAction,
    QualityVerdict,
    VerdictDimension,
)


def _verdict(
    *,
    sample_id: str,
    overall: float,
    prompt_pack_version: str | None,
    product: str = "aspose.ocr",
    language: str = "net",
    version: str | None = "25.1",
) -> QualityVerdict:
    per_dim = {
        VerdictDimension.CITATION_ACCURACY.value: overall,
        VerdictDimension.VERSION_MATCH.value: 1.0,
        VerdictDimension.SYMBOL_FQN_CONSISTENCY.value: 1.0,
        VerdictDimension.CONFIDENCE_CALIBRATION.value: 1.0,
    }
    return QualityVerdict(
        sample_id=sample_id,
        cycle_id="cycle-pv",
        emitted_at="2026-06-02T00:00:00Z",
        product_id=product,
        programming_language=language,
        version=version,
        overall_score=overall,
        per_dimension=per_dim,
        prompt_pack_version=prompt_pack_version,
    )


# ---------------------------------------------------------------------------
# Negative cases — detector must stay quiet
# ---------------------------------------------------------------------------


def test_no_prompt_pack_version_anywhere_yields_no_variant_diagnosis() -> None:
    """All verdicts have prompt_pack_version=None → detector skips."""
    verdicts = tuple(
        _verdict(sample_id=f"s{i}", overall=0.5, prompt_pack_version=None)
        for i in range(8)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-pv")
    assert not any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in reports
    )


def test_single_variant_only_yields_no_variant_diagnosis() -> None:
    """One variant only → no peer to compare → no diagnosis."""
    verdicts = tuple(
        _verdict(sample_id=f"s{i}", overall=0.5, prompt_pack_version="v-A")
        for i in range(8)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-pv")
    assert not any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in reports
    )


def test_gap_below_threshold_yields_no_variant_diagnosis() -> None:
    """Two variants but their mean scores differ by less than the threshold."""
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.92, prompt_pack_version="v-A")
        for i in range(5)
    )
    near_high = tuple(
        _verdict(sample_id=f"hi2-{i}", overall=0.88, prompt_pack_version="v-B")
        for i in range(5)
    )
    reports = DiagnosisAgent().diagnose_batch(
        verdicts=high + near_high, cycle_id="cycle-pv"
    )
    assert not any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in reports
    )


def test_underperforming_variant_below_min_samples_yields_no_diagnosis() -> None:
    """The lagging variant has only 1 sample (< min_samples=3) → skipped."""
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.95, prompt_pack_version="v-A")
        for i in range(5)
    )
    low_singleton = (
        _verdict(sample_id="low-1", overall=0.3, prompt_pack_version="v-B"),
    )
    reports = DiagnosisAgent().diagnose_batch(
        verdicts=high + low_singleton, cycle_id="cycle-pv"
    )
    assert not any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in reports
    )


# ---------------------------------------------------------------------------
# Positive cases — detector fires and scope matches ProposalAgent's contract
# ---------------------------------------------------------------------------


def test_clear_underperforming_variant_emits_exactly_one_diagnosis() -> None:
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.95, prompt_pack_version="v-A")
        for i in range(5)
    )
    low = tuple(
        _verdict(sample_id=f"lo-{i}", overall=0.5, prompt_pack_version="v-B")
        for i in range(5)
    )
    reports = DiagnosisAgent().diagnose_batch(
        verdicts=high + low, cycle_id="cycle-pv"
    )
    variant_reports = [
        r
        for r in reports
        if r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
    ]
    assert len(variant_reports) == 1
    report = variant_reports[0]
    # Scope MUST carry the keys that ProposalAgent reads.
    assert report.affected_scope["prompt_pack_version"] == "v-B"
    assert report.affected_scope["candidate_prompt_pack_version"] == "v-A"
    assert "mean_gap" in report.affected_scope
    assert "low_score_fraction" in report.affected_scope
    # Sanity: 5/5 of v-B samples are below 0.7 threshold.
    assert report.affected_scope["low_score_fraction"].startswith("1.0")
    assert report.sample_count == 5
    assert report.low_score_count == 5


def test_three_variants_two_lagging_emits_two_diagnoses() -> None:
    """Three variants — A is best, B and C both lag. Each laggard → 1 report."""
    high = tuple(
        _verdict(sample_id=f"a-{i}", overall=0.95, prompt_pack_version="v-A")
        for i in range(4)
    )
    mid = tuple(
        _verdict(sample_id=f"b-{i}", overall=0.65, prompt_pack_version="v-B")
        for i in range(4)
    )
    low = tuple(
        _verdict(sample_id=f"c-{i}", overall=0.40, prompt_pack_version="v-C")
        for i in range(4)
    )
    reports = DiagnosisAgent().diagnose_batch(
        verdicts=high + mid + low, cycle_id="cycle-pv"
    )
    variant_reports = [
        r
        for r in reports
        if r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
    ]
    assert len(variant_reports) == 2
    laggards = {r.affected_scope["prompt_pack_version"] for r in variant_reports}
    assert laggards == {"v-B", "v-C"}
    for report in variant_reports:
        assert report.affected_scope["candidate_prompt_pack_version"] == "v-A"


def test_tuneable_threshold_widens_or_tightens_emission() -> None:
    """A very-tight threshold turns a borderline gap into a fire."""
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.85, prompt_pack_version="v-A")
        for i in range(4)
    )
    near_high = tuple(
        _verdict(sample_id=f"nh-{i}", overall=0.78, prompt_pack_version="v-B")
        for i in range(4)
    )
    # Default config (gap >= 0.10) → no diagnosis.
    default = DiagnosisAgent().diagnose_batch(
        verdicts=high + near_high, cycle_id="cycle-pv"
    )
    assert not any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in default
    )
    # Tightened (gap >= 0.05) → diagnosis fires.
    tight = DiagnosisAgent(
        config=DiagnosisAgentConfig(prompt_variant_min_mean_gap=0.05)
    ).diagnose_batch(verdicts=high + near_high, cycle_id="cycle-pv")
    assert any(
        r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
        for r in tight
    )


# ---------------------------------------------------------------------------
# Wire-through to ProposalAgent — the path is no longer dead code
# ---------------------------------------------------------------------------


def test_diagnosis_drives_proposal_agent_to_adjust_prompt_variant() -> None:
    """End-to-end: laggard variant → diagnosis → ADJUST_PROMPT_VARIANT proposal."""
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.95, prompt_pack_version="v-stable")
        for i in range(5)
    )
    low = tuple(
        _verdict(
            sample_id=f"lo-{i}", overall=0.45, prompt_pack_version="v-experimental"
        )
        for i in range(5)
    )
    diagnoser = DiagnosisAgent()
    proposer = ProposalAgent()

    diagnoses = diagnoser.diagnose_batch(verdicts=high + low, cycle_id="cycle-pv")
    proposals = proposer.propose_batch(diagnoses=diagnoses, cycle_id="cycle-pv")

    adjust_prompt_proposals = [
        p for p in proposals if p.action is ProposalAction.ADJUST_PROMPT_VARIANT
    ]
    assert len(adjust_prompt_proposals) == 1
    payload = adjust_prompt_proposals[0].payload
    assert payload["underperforming_variant_id"] == "v-experimental"
    assert payload["candidate_variant_id"] == "v-stable"
    assert payload["low_score_fraction"] is not None


def test_diagnosis_includes_high_confidence_when_gap_is_severe() -> None:
    high = tuple(
        _verdict(sample_id=f"hi-{i}", overall=0.98, prompt_pack_version="v-stable")
        for i in range(10)
    )
    very_low = tuple(
        _verdict(sample_id=f"lo-{i}", overall=0.20, prompt_pack_version="v-broken")
        for i in range(10)
    )
    reports = DiagnosisAgent().diagnose_batch(
        verdicts=high + very_low, cycle_id="cycle-pv"
    )
    variant_reports = [
        r
        for r in reports
        if r.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING
    ]
    assert len(variant_reports) == 1
    # Very large gap (≥ 0.3) + plenty of samples → at confidence_strong cap.
    assert variant_reports[0].confidence >= 0.85
