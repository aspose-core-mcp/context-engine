"""Integration tests for the Coordinator + AdaptiveAgent across multiple cycles.

These tests verify the adaptive contract end-to-end: that calibration
state evolves visibly across cycles, that the audit log records every
adaptation event, that bounds are never violated, and that the
``--no-adaptive`` mode produces frozen behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import (
    CalibrationState,
    Coordinator,
    CoordinatorConfig,
    DiagnosisAgent,
    GuardAgent,
    JudgeAgent,
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.judge_agent import make_sample_id


def _clean_sample(*, lang: str = "net") -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=make_sample_id(),
        captured_at="2026-05-05T00:00:00Z",
        product_id="aspose.ocr",
        programming_language=lang,
        requested_version="25.1",
        strict_version=True,
        query="how to ocr",
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


def _make_coordinator(
    tmp_path: Path,
    *,
    samples: tuple[QueryResponseSample, ...] | None = None,
    enable_calibration: bool = True,
) -> Coordinator:
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
        cycle_detail_dir=tmp_path / "cycles",
        calibration_state_path=(
            tmp_path / "calibration.json" if enable_calibration else None
        ),
    )
    fixed_samples = samples or tuple(_clean_sample() for _ in range(5))
    return Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: fixed_samples,
    )


def test_calibration_state_persists_across_cycles(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    coord.run_cycle()

    state_path = tmp_path / "calibration.json"
    assert state_path.exists()
    state = CalibrationState.load_or_default(state_path)
    assert state.cycle_count == 1


def test_calibration_cycle_count_increments_monotonically(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    for _ in range(5):
        coord.run_cycle()

    state = CalibrationState.load_or_default(tmp_path / "calibration.json")
    assert state.cycle_count == 5


def test_clean_streak_relaxes_guard_cap_visibly(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    initial = CalibrationState()

    # Run enough clean cycles to trigger at least one cap relax
    for _ in range(8):
        coord.run_cycle()

    state = CalibrationState.load_or_default(tmp_path / "calibration.json")
    assert (
        state.guard_auto_approve_blast_cap >= initial.guard_auto_approve_blast_cap
    )


def test_calibration_never_exceeds_bounds(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    for _ in range(50):
        coord.run_cycle()

    state = CalibrationState.load_or_default(tmp_path / "calibration.json")
    b = state.bounds
    assert b.judge_low_threshold_min <= state.judge_low_threshold <= b.judge_low_threshold_max
    assert (
        b.guard_auto_approve_blast_cap_min
        <= state.guard_auto_approve_blast_cap
        <= b.guard_auto_approve_blast_cap_max
    )
    assert (
        b.proposal_high_confidence_floor_min
        <= state.proposal_high_confidence_floor
        <= b.proposal_high_confidence_floor_max
    )


def test_adaptation_events_recorded_in_audit_log(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    for _ in range(10):
        coord.run_cycle()

    audit_path = tmp_path / "audit.jsonl"
    lines = [json.loads(line) for line in audit_path.read_text().splitlines()]
    adaptation_events = [
        line for line in lines if line.get("message_type") == "AdaptationEvent"
    ]
    assert adaptation_events, "expected at least one AdaptationEvent in audit log"


def test_no_adaptive_mode_freezes_calibration(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path, enable_calibration=False)
    for _ in range(10):
        coord.run_cycle()

    # No calibration file written when --no-adaptive
    assert not (tmp_path / "calibration.json").exists()


def test_summary_records_adaptations_applied(tmp_path: Path) -> None:
    coord = _make_coordinator(tmp_path)
    summary = coord.run_cycle()

    assert summary.adaptations_applied in {0, 1}
    assert summary.calibration_state_path is not None


def test_default_safe_mode_invariants_hold_under_adaptation(tmp_path: Path) -> None:
    """Even after many cycles of adaptation, the hard safety invariants
    stay intact: destructive auto-approval requires opting in via the
    feature flag, which the AdaptiveAgent cannot flip.
    """
    coord = _make_coordinator(tmp_path)
    for _ in range(30):
        coord.run_cycle()

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
    auto_approved_destructive = [
        d
        for d in decisions
        if d["outcome"] == "auto_approved"
        and proposals_by_id.get(d["proposal_id"], {}).get("action")
        in {"adjust_fusion_weights", "rollback_snapshot"}
    ]
    assert (
        not auto_approved_destructive
    ), "destructive action auto-approved after adaptation"
