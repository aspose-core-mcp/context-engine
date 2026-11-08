"""Coordinator integration with the LLMJudgeAgent wire-up.

When an LLMJudgeAgent is injected, the Coordinator runs it on every
cycle, publishes its JudgeAgreementReport to the audit log, and counts
the emission in the CycleSummary. When not injected, the cycle is
unchanged — the wire-up is purely additive.

This is the A8 Reflective indicator end-to-end: the loop now
demonstrably reflects on its own judgment per cycle, not only has the
code shipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import (
    Coordinator,
    CoordinatorConfig,
    DiagnosisAgent,
    GuardAgent,
    JudgeAgent,
    LLMJudgeAgent,
    LLMJudgeAgentConfig,
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.judge_agent import make_sample_id


class _MirrorClient:
    """Stub LLMJudgeClient that mirrors the deterministic Judge.

    Returns a high score with empty per-dimension dict + 'mirror'
    rationale. Combined with the deterministic-judge fixture this
    produces a 100% agreement run for predictability.
    """

    def judge(
        self, *, sample: QueryResponseSample
    ) -> tuple[float, dict[str, float], str]:
        return 0.9, {}, "mirror-stub"


def _sample() -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=make_sample_id(),
        captured_at="2026-05-04T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version="25.1",
        strict_version=True,
        query="recognize image",
        candidates=(
            {
                "canonical_url": "https://docs.aspose.com/ocr/net/",
                "version": "25.1",
                "chunk_id": "c1",
                "symbol_fqn": "Aspose.OCR.Recognize",
            },
        ),
        confidence_score=0.85,
    )


def _samples():
    return tuple(_sample() for _ in range(3))


def _make_coordinator(tmp_path: Path, *, with_llm_judge: bool) -> Coordinator:
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
    )
    samples = _samples()
    llm_judge = (
        LLMJudgeAgent(
            client=_MirrorClient(),
            config=LLMJudgeAgentConfig(
                sampling_rate=1.0, max_samples_per_cycle=10
            ),
        )
        if with_llm_judge
        else None
    )
    return Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
        llm_judge=llm_judge,
    )


def _read_audit_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_coordinator_without_llm_judge_does_not_emit_agreement(
    tmp_path: Path,
) -> None:
    coord = _make_coordinator(tmp_path, with_llm_judge=False)
    summary = coord.run_cycle()
    assert summary.llm_judge_reports_emitted == 0
    log = _read_audit_log(coord.config.audit_log_path)
    types = {entry.get("message_type") for entry in log}
    assert "JudgeAgreementReport" not in types


def test_coordinator_with_llm_judge_emits_one_agreement_per_cycle(
    tmp_path: Path,
) -> None:
    coord = _make_coordinator(tmp_path, with_llm_judge=True)
    summary = coord.run_cycle()
    assert summary.llm_judge_reports_emitted == 1
    log = _read_audit_log(coord.config.audit_log_path)
    agreements = [
        e for e in log if e.get("message_type") == "JudgeAgreementReport"
    ]
    assert len(agreements) == 1
    # The single report carries the agreement metrics
    report = agreements[0]
    assert report["cycle_id"] == summary.cycle_id
    assert report["samples_compared"] >= 1


def test_coordinator_llm_judge_is_optional_backwards_compatible(
    tmp_path: Path,
) -> None:
    """Legacy callers (no llm_judge=) keep working — no kwarg required."""
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
    )
    coord = Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: _samples(),
    )
    summary = coord.run_cycle()
    assert summary.llm_judge_reports_emitted == 0
    assert coord.llm_judge is None


def test_coordinator_with_llm_judge_does_not_alter_verdicts(
    tmp_path: Path,
) -> None:
    """The shadow judge MUST NOT change the deterministic verdicts.

    Run two coordinators side by side over the same samples — one with
    llm_judge, one without. Their verdict-count and decision-count must
    be identical (the deterministic Judge is the authoritative scorer).
    """
    samples = _samples()

    cfg_a = CoordinatorConfig(
        audit_log_path=tmp_path / "a-audit.jsonl",
        summary_path=tmp_path / "a-summary.json",
    )
    cfg_b = CoordinatorConfig(
        audit_log_path=tmp_path / "b-audit.jsonl",
        summary_path=tmp_path / "b-summary.json",
    )

    coord_with = Coordinator(
        config=cfg_a,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
        llm_judge=LLMJudgeAgent(client=_MirrorClient()),
    )
    coord_without = Coordinator(
        config=cfg_b,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
    )

    sum_a = coord_with.run_cycle()
    sum_b = coord_without.run_cycle()

    assert sum_a.verdicts_emitted == sum_b.verdicts_emitted
    assert sum_a.decisions_emitted == sum_b.decisions_emitted
    assert sum_a.outcome_counts == sum_b.outcome_counts
