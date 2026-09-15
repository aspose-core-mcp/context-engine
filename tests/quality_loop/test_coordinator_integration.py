"""Integration test for the full quality-loop cycle.

Wires Coordinator with a fixture sample provider and verifies the
end-to-end flow: every published message is persisted to the audit log
in the right shape, the cycle summary is well-formed, and per-cycle
detail JSON is written when requested.
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
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.judge_agent import make_sample_id


def _good_sample() -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=make_sample_id(),
        captured_at="2026-05-04T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version="25.1",
        strict_version=True,
        query="how to ocr a pdf",
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


def _bad_sample(*, confidence: float = 0.95) -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=make_sample_id(),
        captured_at="2026-05-04T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version="25.1",
        strict_version=True,
        query="ocr",
        candidates=(),
        confidence_score=confidence,
    )


def _coord(tmp_path: Path) -> Coordinator:
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
        cycle_detail_dir=tmp_path / "cycles",
    )
    samples = (
        _good_sample(),
        _bad_sample(),
        _bad_sample(),
        _bad_sample(),
        _bad_sample(),
        _bad_sample(),
        _bad_sample(),
    )
    return Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
    )


def test_full_cycle_runs_end_to_end(tmp_path: Path) -> None:
    summary = _coord(tmp_path).run_cycle()

    assert summary.samples_processed == 7
    assert summary.verdicts_emitted == 7
    assert summary.diagnoses_emitted >= 1
    assert summary.proposals_emitted >= 1
    assert summary.decisions_emitted >= 1
    assert summary.duration_seconds >= 0


def test_audit_log_contains_every_message_type(tmp_path: Path) -> None:
    _coord(tmp_path).run_cycle()

    audit_path = tmp_path / "audit.jsonl"
    lines = [json.loads(line) for line in audit_path.read_text().splitlines()]
    types = {line.get("message_type") for line in lines}

    assert "QueryResponseSample" in types
    assert "QualityVerdict" in types
    assert "DiagnosisReport" in types
    assert "RemediationProposal" in types
    assert "GuardDecision" in types
    assert "CycleSummary" in types


def test_summary_file_is_machine_readable(tmp_path: Path) -> None:
    summary = _coord(tmp_path).run_cycle()

    summary_path = tmp_path / "summary.json"
    payload = json.loads(summary_path.read_text())
    assert payload["cycle_id"] == summary.cycle_id
    assert payload["samples_processed"] == 7
    assert isinstance(payload["outcome_counts"], dict)


def test_per_cycle_detail_json_is_written_when_configured(tmp_path: Path) -> None:
    summary = _coord(tmp_path).run_cycle()

    detail_path = tmp_path / "cycles" / summary.cycle_id / "detail.json"
    assert detail_path.exists()
    detail = json.loads(detail_path.read_text())
    assert "verdicts" in detail
    assert "diagnoses" in detail
    assert "proposals" in detail
    assert "decisions" in detail


def test_default_safe_mode_never_auto_executes_destructive_proposals(
    tmp_path: Path,
) -> None:
    """The hard-policy invariant: with default GuardAgentConfig, no proposal
    should ever come back AUTO_APPROVED for a destructive action.
    """
    _coord(tmp_path).run_cycle()

    audit_path = tmp_path / "audit.jsonl"
    lines = [json.loads(line) for line in audit_path.read_text().splitlines()]

    proposals_by_id = {
        line["proposal_id"]: line
        for line in lines
        if line.get("message_type") == "RemediationProposal"
    }
    decisions = [
        line for line in lines if line.get("message_type") == "GuardDecision"
    ]
    for decision in decisions:
        if decision["outcome"] != "auto_approved":
            continue
        proposal = proposals_by_id[decision["proposal_id"]]
        assert proposal["action"] in {"track_anomaly"}, (
            f"destructive action auto-approved in safe mode: {proposal['action']}"
        )


def test_audit_log_is_append_only_across_runs(tmp_path: Path) -> None:
    coord = _coord(tmp_path)
    coord.run_cycle()
    line_count_after_first = sum(
        1 for _ in (tmp_path / "audit.jsonl").open()
    )

    coord = _coord(tmp_path)
    coord.run_cycle()
    line_count_after_second = sum(
        1 for _ in (tmp_path / "audit.jsonl").open()
    )

    assert line_count_after_second > line_count_after_first
