"""Unit tests for AdaptiveAgent — bounded mutations driven by cycle outcomes."""

from __future__ import annotations

from adcs.quality_loop import (
    AdaptiveAgent,
    AdaptiveAgentConfig,
    CalibrationState,
    GuardDecision,
    GuardOutcome,
    QualityVerdict,
)
from adcs.quality_loop.models import AdaptationKind, VerdictDimension


def _verdict(*, sample_id: str, overall: float) -> QualityVerdict:
    return QualityVerdict(
        sample_id=sample_id,
        cycle_id="cycle-test",
        emitted_at="2026-05-05T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        overall_score=overall,
        per_dimension={
            VerdictDimension.CITATION_ACCURACY.value: overall,
            VerdictDimension.VERSION_MATCH.value: 1.0,
            VerdictDimension.SYMBOL_FQN_CONSISTENCY.value: 1.0,
            VerdictDimension.CONFIDENCE_CALIBRATION.value: 1.0,
        },
    )


def _decision(*, outcome: GuardOutcome, proposal_id: str = "p1") -> GuardDecision:
    return GuardDecision(
        decision_id=f"dec-{proposal_id}",
        cycle_id="cycle-test",
        emitted_at="2026-05-05T00:00:00Z",
        proposal_id=proposal_id,
        outcome=outcome,
        rationale="test",
    )


def test_rejection_triggers_guard_cap_tighten() -> None:
    state = CalibrationState(guard_auto_approve_blast_cap=200)
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(_decision(outcome=GuardOutcome.REJECTED),),
        cycle_id="cycle-test",
    )

    assert event is not None
    assert event.kind is AdaptationKind.GUARD_BLAST_CAP_TIGHTEN
    assert new_state.guard_auto_approve_blast_cap < state.guard_auto_approve_blast_cap


def test_clean_streak_relaxes_cap_after_threshold() -> None:
    state = CalibrationState(
        guard_auto_approve_blast_cap=100,
        cycles_since_last_rejection=5,
    )
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(_decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL),),
        cycle_id="cycle-test",
    )

    assert event is not None
    assert event.kind is AdaptationKind.GUARD_BLAST_CAP_RELAX
    assert new_state.guard_auto_approve_blast_cap > state.guard_auto_approve_blast_cap


def test_short_clean_streak_does_not_relax() -> None:
    state = CalibrationState(
        guard_auto_approve_blast_cap=100,
        cycles_since_last_rejection=2,
    )
    agent = AdaptiveAgent()
    _, event = agent.adapt(
        state=state,
        verdicts=(_verdict(sample_id="s1", overall=0.85),) * 5,
        decisions=(_decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL),),
        cycle_id="cycle-test",
    )

    # No mutation on this cycle (cap-relax not yet eligible, judge near target)
    assert event is None or event.kind is not AdaptationKind.GUARD_BLAST_CAP_RELAX


def test_high_low_score_fraction_lowers_judge_threshold() -> None:
    state = CalibrationState(
        judge_low_threshold=0.75,
        cycles_since_last_rejection=0,
    )
    # Many low-score verdicts -> judge is too strict
    verdicts = tuple(_verdict(sample_id=f"s{i}", overall=0.2) for i in range(8))
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state,
        verdicts=verdicts,
        decisions=(_decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL),),
        cycle_id="cycle-test",
    )

    assert event is not None
    assert event.kind is AdaptationKind.JUDGE_LOW_THRESHOLD_LOWER
    assert new_state.judge_low_threshold < state.judge_low_threshold


def test_low_low_score_fraction_raises_judge_threshold() -> None:
    state = CalibrationState(
        judge_low_threshold=0.65,
        cycles_since_last_rejection=0,
    )
    # All clean verdicts -> judge could be tighter
    verdicts = tuple(_verdict(sample_id=f"s{i}", overall=0.95) for i in range(8))
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state,
        verdicts=verdicts,
        decisions=(_decision(outcome=GuardOutcome.AUTO_APPROVED),),
        cycle_id="cycle-test",
    )

    # Either the threshold raises (judge tunable) OR proposal floor lowers
    # (auto-approval rate proxy). Both are valid per priority order; only
    # check that *some* mutation toward "fewer flags" was made.
    assert event is not None
    assert event.kind in {
        AdaptationKind.JUDGE_LOW_THRESHOLD_RAISE,
        AdaptationKind.PROPOSAL_HIGH_CONFIDENCE_FLOOR_LOWER,
    }


def test_low_auto_approval_rate_raises_proposal_floor() -> None:
    state = CalibrationState(
        proposal_high_confidence_floor=0.80,
        cycles_since_last_rejection=0,
    )
    # Verdicts with low-score fraction near target (0.30) so judge step
    # is NOT triggered. 3 low + 7 high -> fraction = 0.30 == target.
    verdicts = (
        tuple(_verdict(sample_id=f"low-{i}", overall=0.3) for i in range(3))
        + tuple(_verdict(sample_id=f"high-{i}", overall=0.9) for i in range(7))
    )
    decisions = tuple(
        _decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL, proposal_id=f"p{i}")
        for i in range(4)
    )
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state, verdicts=verdicts, decisions=decisions, cycle_id="cycle-test"
    )

    assert event is not None
    assert event.kind is AdaptationKind.PROPOSAL_HIGH_CONFIDENCE_FLOOR_RAISE
    assert (
        new_state.proposal_high_confidence_floor
        > state.proposal_high_confidence_floor
    )


def test_no_op_when_no_signal() -> None:
    """No verdicts, no decisions, no clean streak -> NO_OP."""
    state = CalibrationState(cycles_since_last_rejection=0)
    agent = AdaptiveAgent()
    new_state, event = agent.adapt(
        state=state, verdicts=(), decisions=(), cycle_id="cycle-test"
    )

    assert event is None
    assert new_state == state


def test_at_most_one_event_per_cycle() -> None:
    """Even with multiple eligible signals, only one event is emitted."""
    state = CalibrationState(
        guard_auto_approve_blast_cap=200,
        judge_low_threshold=0.75,
        proposal_high_confidence_floor=0.80,
        cycles_since_last_rejection=10,
    )
    verdicts = tuple(_verdict(sample_id=f"s{i}", overall=0.2) for i in range(8))
    decisions = (
        _decision(outcome=GuardOutcome.REJECTED),
        _decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL, proposal_id="p2"),
    )
    agent = AdaptiveAgent()
    _, event = agent.adapt(
        state=state, verdicts=verdicts, decisions=decisions, cycle_id="cycle-test"
    )

    # Rejection has highest priority -> guard cap tighten only
    assert event is not None
    assert event.kind is AdaptationKind.GUARD_BLAST_CAP_TIGHTEN


def test_event_serialises_to_json() -> None:
    state = CalibrationState(guard_auto_approve_blast_cap=200)
    _, event = AdaptiveAgent().adapt(
        state=state,
        verdicts=(),
        decisions=(_decision(outcome=GuardOutcome.REJECTED),),
        cycle_id="cycle-test",
    )

    assert event is not None
    payload = event.to_dict()
    assert payload["message_type"] == "AdaptationEvent"
    assert payload["kind"] == "guard_blast_cap_tighten"
    assert "delta" in payload


def test_custom_config_step_size_is_respected() -> None:
    state = CalibrationState(
        judge_low_threshold=0.75, cycles_since_last_rejection=0
    )
    agent = AdaptiveAgent(config=AdaptiveAgentConfig(judge_threshold_step=0.05))
    verdicts = tuple(_verdict(sample_id=f"s{i}", overall=0.2) for i in range(8))
    new_state, event = agent.adapt(
        state=state,
        verdicts=verdicts,
        decisions=(_decision(outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL),),
        cycle_id="cycle-test",
    )

    assert event is not None
    assert abs(state.judge_low_threshold - new_state.judge_low_threshold) >= 0.04
