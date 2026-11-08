"""Unit tests for the CrossCycleCorrelationAgent (the 6th quality-loop agent).

Asserts deterministic trend classification, recommendation rules, and
edge cases (empty history, single-cycle history, perfectly stable
series, monotone-rising / monotone-falling series).
"""

from __future__ import annotations

from adcs.quality_loop.correlation_agent import (
    CrossCycleCorrelationAgent,
    CrossCycleCorrelationAgentConfig,
)
from adcs.quality_loop.models import CorrelationTrend, CycleSummary


def _make_summary(
    *,
    cycle_id: str,
    started_at: str,
    samples: int = 10,
    duration: float = 1.0,
    rejected: int = 0,
    adaptations: int = 0,
) -> CycleSummary:
    outcome_counts: dict[str, int] = {}
    if rejected:
        outcome_counts["rejected"] = rejected
    return CycleSummary(
        cycle_id=cycle_id,
        started_at=started_at,
        completed_at=started_at,
        duration_seconds=duration,
        samples_processed=samples,
        verdicts_emitted=samples,
        diagnoses_emitted=0,
        proposals_emitted=0,
        decisions_emitted=0,
        adaptations_applied=adaptations,
        outcome_counts=outcome_counts,
    )


def test_empty_history_yields_insufficient_data_report() -> None:
    """With no past cycles the agent still emits a report, but trends are suppressed."""
    agent = CrossCycleCorrelationAgent()
    report = agent.correlate(cycle_id="cycle-1", recent_summaries=())
    assert report.cycles_examined == 0
    assert report.sample_volume_trend is CorrelationTrend.INSUFFICIENT_DATA
    assert report.duration_trend is CorrelationTrend.INSUFFICIENT_DATA
    assert report.rejection_rate == 0.0
    assert report.rejection_velocity_cycles == 0
    assert report.recommendations
    assert any("history below threshold" in r for r in report.recommendations)


def test_below_min_cycles_threshold_suppresses_trends() -> None:
    """3 cycles is below the default min_cycles_for_trend (4)."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z")
        for i in range(3)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.cycles_examined == 3
    assert report.sample_volume_trend is CorrelationTrend.INSUFFICIENT_DATA
    assert report.duration_trend is CorrelationTrend.INSUFFICIENT_DATA


def test_rising_sample_volume_trend_detected() -> None:
    """Strictly increasing sample counts → RISING trend."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(
            cycle_id=f"c{i}",
            started_at=f"2026-06-01T{i:02d}:00:00Z",
            samples=10 + i * 5,
        )
        for i in range(8)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.sample_volume_trend is CorrelationTrend.RISING


def test_falling_sample_volume_trend_detected_and_recommended() -> None:
    """Strictly decreasing sample counts → FALLING trend + recommendation."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(
            cycle_id=f"c{i}",
            started_at=f"2026-06-01T{i:02d}:00:00Z",
            samples=50 - i * 5,
        )
        for i in range(8)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.sample_volume_trend is CorrelationTrend.FALLING
    assert any("sample volume" in r.lower() for r in report.recommendations)


def test_stable_series_yields_stable_trend_and_nominal_recommendation() -> None:
    """Constant series → STABLE trend + 'nominal' recommendation."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(
            cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z", samples=20
        )
        for i in range(8)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.sample_volume_trend is CorrelationTrend.STABLE
    assert report.duration_trend is CorrelationTrend.STABLE
    assert report.recommendations == ("trends within nominal range; no action needed",)


def test_high_rejection_rate_triggers_recommendation() -> None:
    """Rejection rate > threshold → proactive-tighten recommendation."""
    agent = CrossCycleCorrelationAgent()
    history = []
    for i in range(8):
        history.append(
            _make_summary(
                cycle_id=f"c{i}",
                started_at=f"2026-06-01T{i:02d}:00:00Z",
                rejected=1 if i % 3 == 0 else 0,
            )
        )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=tuple(history))
    assert report.rejection_rate > 0.20
    assert any("rejection rate" in r.lower() for r in report.recommendations)


def test_rejection_velocity_counts_trailing_clean_cycles() -> None:
    """rejection_velocity_cycles = trailing clean run length."""
    agent = CrossCycleCorrelationAgent()
    # one rejection at the start, then 6 clean cycles
    history = [
        _make_summary(
            cycle_id="c0", started_at="2026-06-01T00:00:00Z", rejected=1
        )
    ]
    for i in range(1, 7):
        history.append(
            _make_summary(
                cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z"
            )
        )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=tuple(history))
    assert report.rejection_velocity_cycles == 6


def test_long_clean_streak_triggers_relax_recommendation() -> None:
    """≥10 clean cycles → relax-recommendation."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z")
        for i in range(12)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.rejection_velocity_cycles == 12
    assert any("safe window" in r for r in report.recommendations)


def test_high_adaptation_density_triggers_recommendation() -> None:
    """Adaptation density > 0.8 → 'unusually high' recommendation."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(
            cycle_id=f"c{i}",
            started_at=f"2026-06-01T{i:02d}:00:00Z",
            adaptations=1,
        )
        for i in range(8)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.adaptation_density == 1.0
    assert any("adaptation density" in r.lower() for r in report.recommendations)


def test_history_window_caps_examination() -> None:
    """History window caps examined cycles even if more are passed."""
    agent = CrossCycleCorrelationAgent(
        CrossCycleCorrelationAgentConfig(history_window=5)
    )
    history = tuple(
        _make_summary(cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z")
        for i in range(20)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    assert report.cycles_examined == 5
    # Should have kept the LATEST cycles, oldest dropped
    assert report.earliest_cycle_started_at == "2026-06-01T15:00:00Z"
    assert report.latest_cycle_started_at == "2026-06-01T19:00:00Z"


def test_report_is_deterministic_across_two_calls() -> None:
    """Two calls with the same input must produce equal reports
    (modulo the random report_id and emitted_at timestamp)."""
    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z")
        for i in range(8)
    )
    a = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    b = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    # Trend metrics + recommendations must match exactly.
    assert a.sample_volume_trend == b.sample_volume_trend
    assert a.duration_trend == b.duration_trend
    assert a.rejection_rate == b.rejection_rate
    assert a.rejection_velocity_cycles == b.rejection_velocity_cycles
    assert a.adaptation_density == b.adaptation_density
    assert a.mean_duration_seconds == b.mean_duration_seconds
    assert a.recommendations == b.recommendations


def test_report_to_dict_is_json_serialisable() -> None:
    """to_dict() must produce a JSON-serialisable structure with stable enum strings."""
    import json

    agent = CrossCycleCorrelationAgent()
    history = tuple(
        _make_summary(cycle_id=f"c{i}", started_at=f"2026-06-01T{i:02d}:00:00Z")
        for i in range(8)
    )
    report = agent.correlate(cycle_id="cycle-x", recent_summaries=history)
    payload = report.to_dict()
    # Must round-trip through JSON
    serialised = json.dumps(payload)
    assert isinstance(json.loads(serialised), dict)
    # Trend enums must be string values
    assert isinstance(payload["sample_volume_trend"], str)
    assert isinstance(payload["duration_trend"], str)
    assert payload["sample_volume_trend"] in {
        "rising",
        "falling",
        "stable",
        "insufficient_data",
    }
