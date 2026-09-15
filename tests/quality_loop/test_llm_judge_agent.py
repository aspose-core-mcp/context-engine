"""Tests for the LLMJudgeAgent shadow-judge surface (A9 self-reflection).

The deterministic Judge stays authoritative. The LLMJudgeAgent runs on
a subset of samples per cycle, scores them via an injected
:class:`LLMJudgeClient`, and emits exactly one
:class:`JudgeAgreementReport` per cycle summarising agreement rate and
bounded disagreement details. This test surface uses a deterministic
stub client so the comparison logic is fully reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from adcs.quality_loop.judge_agent import QueryResponseSample
from adcs.quality_loop.llm_judge_agent import (
    LLMJudgeAgent,
    LLMJudgeAgentConfig,
    LLMJudgeClient,
)
from adcs.quality_loop.models import QualityVerdict


@dataclass
class _FixedScoreClient:
    """LLMJudgeClient stub: always returns the configured (score, dims, rationale)."""

    score: float
    dimensions: dict[str, float]
    rationale: str = "stub"

    def judge(
        self, *, sample: QueryResponseSample
    ) -> tuple[float, dict[str, float], str]:
        return self.score, dict(self.dimensions), self.rationale


@dataclass
class _MirrorClient:
    """LLMJudgeClient stub: returns the deterministic verdict score."""

    verdicts_by_sample: dict[str, QualityVerdict]

    def judge(
        self, *, sample: QueryResponseSample
    ) -> tuple[float, dict[str, float], str]:
        verdict = self.verdicts_by_sample[sample.sample_id]
        return (
            verdict.overall_score,
            dict(verdict.per_dimension),
            "agree-stub",
        )


def _make_sample(*, sample_id: str) -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=sample_id,
        captured_at="2026-06-01T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version="25.1",
        strict_version=True,
        query="how to recognize image",
        candidates=(),
        confidence_score=0.8,
    )


def _make_verdict(
    *, sample_id: str, score: float, dims: dict[str, float] | None = None
) -> QualityVerdict:
    return QualityVerdict(
        sample_id=sample_id,
        cycle_id="cycle-test",
        emitted_at="2026-06-01T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        overall_score=score,
        per_dimension=dict(dims or {"citation_accuracy": score}),
    )


# ---------------------------------------------------------------------------
# Protocol + empty-input behaviour
# ---------------------------------------------------------------------------


def test_llm_judge_client_is_a_protocol_satisfied_by_fixed_stub() -> None:
    """Stub satisfies the Protocol structurally."""
    client: LLMJudgeClient = _FixedScoreClient(score=0.9, dimensions={})
    sample = _make_sample(sample_id="s1")
    score, dims, rationale = client.judge(sample=sample)
    assert score == 0.9
    assert dims == {}
    assert rationale == "stub"


def test_empty_samples_yields_vacuous_report() -> None:
    """No samples → 0 compared, 100% agreement (vacuous), 0 disagreements."""
    agent = LLMJudgeAgent(client=_FixedScoreClient(score=0.0, dimensions={}))
    report = agent.compare(
        cycle_id="cycle-test",
        samples=(),
        deterministic_verdicts=(),
    )
    assert report.samples_compared == 0
    assert report.agreements == 0
    assert report.disagreements == 0
    assert report.agreement_rate == 1.0
    assert report.mean_absolute_delta == 0.0
    assert report.disagreement_details == ()


# ---------------------------------------------------------------------------
# Full-agreement / full-disagreement scenarios
# ---------------------------------------------------------------------------


def test_full_agreement_when_llm_mirrors_deterministic() -> None:
    """Mirror client returns det score → 100% agreement, 0 disagreements."""
    samples = tuple(_make_sample(sample_id=f"s{i}") for i in range(5))
    verdicts = tuple(
        _make_verdict(sample_id=s.sample_id, score=0.8) for s in samples
    )
    verdicts_by_sample = {v.sample_id: v for v in verdicts}
    agent = LLMJudgeAgent(
        client=_MirrorClient(verdicts_by_sample=verdicts_by_sample),
        config=LLMJudgeAgentConfig(sampling_rate=1.0, max_samples_per_cycle=5),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.samples_compared == 5
    assert report.agreements == 5
    assert report.disagreements == 0
    assert report.agreement_rate == 1.0
    assert report.mean_absolute_delta == 0.0


def test_full_disagreement_when_llm_returns_extreme_opposite() -> None:
    """Fixed client returns 0.0; det verdicts are 1.0 → all disagree."""
    samples = tuple(_make_sample(sample_id=f"s{i}") for i in range(5))
    verdicts = tuple(
        _make_verdict(sample_id=s.sample_id, score=1.0) for s in samples
    )
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.0, dimensions={"citation_accuracy": 0.0}),
        config=LLMJudgeAgentConfig(
            sampling_rate=1.0,
            max_samples_per_cycle=5,
            disagreement_tolerance=0.15,
            max_disagreements_recorded=3,
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.samples_compared == 5
    assert report.agreements == 0
    assert report.disagreements == 5
    assert report.agreement_rate == 0.0
    assert report.mean_absolute_delta == 1.0
    # max_disagreements_recorded = 3 caps the detail list
    assert len(report.disagreement_details) == 3


# ---------------------------------------------------------------------------
# Sampling controls
# ---------------------------------------------------------------------------


def test_sampling_rate_caps_subset_size() -> None:
    """sampling_rate=0.2 over 100 samples → 20 compared (subject to max cap)."""
    samples = tuple(_make_sample(sample_id=f"s{i:03}") for i in range(100))
    verdicts = tuple(
        _make_verdict(sample_id=s.sample_id, score=0.5) for s in samples
    )
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.5, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=0.2, max_samples_per_cycle=50
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.samples_compared == 20


def test_max_samples_per_cycle_caps_below_sampling_rate() -> None:
    """max_samples_per_cycle is the hard ceiling."""
    samples = tuple(_make_sample(sample_id=f"s{i:03}") for i in range(100))
    verdicts = tuple(
        _make_verdict(sample_id=s.sample_id, score=0.5) for s in samples
    )
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.5, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=1.0, max_samples_per_cycle=10
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.samples_compared == 10


def test_subset_selection_is_deterministic_across_two_calls() -> None:
    """Same input → same subset → same disagreements."""
    samples = tuple(_make_sample(sample_id=f"s{i:03}") for i in range(50))
    verdicts = tuple(
        _make_verdict(sample_id=s.sample_id, score=1.0) for s in samples
    )
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.0, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=0.2, max_samples_per_cycle=10
        ),
    )
    a = agent.compare(
        cycle_id="c1", samples=samples, deterministic_verdicts=verdicts
    )
    b = agent.compare(
        cycle_id="c1", samples=samples, deterministic_verdicts=verdicts
    )
    assert [d.sample_id for d in a.disagreement_details] == [
        d.sample_id for d in b.disagreement_details
    ]


# ---------------------------------------------------------------------------
# Tolerance band
# ---------------------------------------------------------------------------


def test_tolerance_classifies_small_deltas_as_agreement() -> None:
    """delta within tolerance → agreement."""
    samples = (_make_sample(sample_id="s1"),)
    verdicts = (_make_verdict(sample_id="s1", score=0.80),)
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.85, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=1.0,
            max_samples_per_cycle=1,
            disagreement_tolerance=0.10,
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.agreements == 1
    assert report.disagreements == 0


def test_tolerance_classifies_large_deltas_as_disagreement() -> None:
    """delta above tolerance → disagreement."""
    samples = (_make_sample(sample_id="s1"),)
    verdicts = (_make_verdict(sample_id="s1", score=0.80),)
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.50, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=1.0,
            max_samples_per_cycle=1,
            disagreement_tolerance=0.10,
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    assert report.agreements == 0
    assert report.disagreements == 1
    assert report.disagreement_details[0].sample_id == "s1"


# ---------------------------------------------------------------------------
# Robustness: missing deterministic verdict
# ---------------------------------------------------------------------------


def test_sample_without_deterministic_verdict_is_skipped() -> None:
    """If a sample has no matching deterministic verdict, it is skipped silently."""
    samples = (
        _make_sample(sample_id="s1"),
        _make_sample(sample_id="s2"),
    )
    # Only s1 has a verdict
    verdicts = (_make_verdict(sample_id="s1", score=0.7),)
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(score=0.7, dimensions={}),
        config=LLMJudgeAgentConfig(
            sampling_rate=1.0, max_samples_per_cycle=2
        ),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    # Only s1 contributed to the comparison
    assert report.samples_compared == 1


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_report_to_dict_is_json_serialisable() -> None:
    import json

    samples = (_make_sample(sample_id="s1"),)
    verdicts = (_make_verdict(sample_id="s1", score=0.9),)
    agent = LLMJudgeAgent(
        client=_FixedScoreClient(
            score=0.5, dimensions={"citation_accuracy": 0.5}
        ),
        config=LLMJudgeAgentConfig(sampling_rate=1.0, max_samples_per_cycle=1),
    )
    report = agent.compare(
        cycle_id="cycle-test",
        samples=samples,
        deterministic_verdicts=verdicts,
    )
    payload = report.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["samples_compared"] == 1
    assert payload["agreements"] == 0
    assert payload["disagreements"] == 1
    assert isinstance(payload["disagreement_details"], list)
