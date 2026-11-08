"""AdaptiveAgent trend-aware adaptation tests.

The AdaptiveAgent now accepts an optional CorrelationReport. When the
report's recent-window rejection_rate exceeds the proactive threshold,
the agent halves the guard cap EVEN IF the current cycle had no
rejection. This is the A8-Reflective cross-cycle reflex: the loop
adapts to trajectory, not only to instant observations.
"""

from __future__ import annotations

from adcs.quality_loop.adaptive_agent import AdaptiveAgent, AdaptiveAgentConfig
from adcs.quality_loop.calibration import CalibrationState
from adcs.quality_loop.models import (
    AdaptationKind,
    CorrelationReport,
    CorrelationTrend,
)


def _make_correlation(
    *,
    rejection_rate: float,
    cycles_examined: int = 12,
) -> CorrelationReport:
    return CorrelationReport(
        report_id="corr-test",
        cycle_id="cycle-test",
        emitted_at="2026-06-01T00:00:00Z",
        cycles_examined=cycles_examined,
        earliest_cycle_started_at="2026-06-01T00:00:00Z",
        latest_cycle_started_at="2026-06-01T12:00:00Z",
        sample_volume_trend=CorrelationTrend.STABLE,
        duration_trend=CorrelationTrend.STABLE,
        rejection_rate=rejection_rate,
        rejection_velocity_cycles=0,
        adaptation_density=0.0,
        mean_duration_seconds=1.0,
        recommendations=(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_correlation_report_keeps_legacy_behaviour() -> None:
    """Without a correlation report, the agent must behave as before
    (NO_OP on a clean cycle with no clean-streak)."""
    agent = AdaptiveAgent()
    state = CalibrationState()
    new_state, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(),
        cycle_id="c1",
        correlation=None,
    )
    assert event is None
    assert new_state == state


def test_correlation_below_threshold_does_not_trigger_proactive_tighten() -> None:
    """Rejection rate under the threshold → no proactive tightening."""
    agent = AdaptiveAgent(
        AdaptiveAgentConfig(proactive_tighten_rejection_rate=0.20)
    )
    state = CalibrationState()
    correlation = _make_correlation(rejection_rate=0.15)
    _, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(),
        cycle_id="c1",
        correlation=correlation,
    )
    assert event is None


def test_correlation_above_threshold_triggers_proactive_tighten() -> None:
    """High recent rejection rate halves the guard cap proactively."""
    agent = AdaptiveAgent(
        AdaptiveAgentConfig(proactive_tighten_rejection_rate=0.20)
    )
    state = CalibrationState()
    correlation = _make_correlation(rejection_rate=0.30)
    new_state, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(),
        cycle_id="c1",
        correlation=correlation,
    )
    assert event is not None
    assert event.kind is AdaptationKind.GUARD_BLAST_CAP_TIGHTEN
    assert (
        new_state.guard_auto_approve_blast_cap
        < state.guard_auto_approve_blast_cap
    )
    # Rationale mentions the correlation-driven path
    assert "correlation" in event.rationale.lower()


def test_in_cycle_rejection_takes_priority_over_correlation() -> None:
    """If THIS cycle has a rejection, the priority-1 path fires first
    and the correlation-driven check does not run a second mutation."""
    from adcs.quality_loop.models import GuardDecision, GuardOutcome

    agent = AdaptiveAgent(
        AdaptiveAgentConfig(proactive_tighten_rejection_rate=0.20)
    )
    state = CalibrationState()
    correlation = _make_correlation(rejection_rate=0.50)  # well above threshold
    decisions = (
        GuardDecision(
            decision_id="d1",
            cycle_id="c1",
            emitted_at="2026-06-01T00:00:00Z",
            proposal_id="p1",
            outcome=GuardOutcome.REJECTED,
            rationale="test",
        ),
    )
    _, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=decisions,
        cycle_id="c1",
        correlation=correlation,
    )
    assert event is not None
    # The event rationale points at the IN-CYCLE rejection, not the
    # correlation — priority-1 fires first by design.
    assert "REJECTED" in event.rationale


def test_correlation_does_not_breach_lower_bound() -> None:
    """When the guard cap is already at its lower bound, proactive
    tightening becomes a NO_OP (the bound is the safety floor)."""
    agent = AdaptiveAgent(
        AdaptiveAgentConfig(proactive_tighten_rejection_rate=0.20)
    )
    state = CalibrationState(
        guard_auto_approve_blast_cap=25  # min bound
    )
    correlation = _make_correlation(rejection_rate=0.50)
    new_state, event = agent.adapt(
        state=state,
        verdicts=(),
        decisions=(),
        cycle_id="c1",
        correlation=correlation,
    )
    assert event is None
    assert (
        new_state.guard_auto_approve_blast_cap
        == state.guard_auto_approve_blast_cap
    )
