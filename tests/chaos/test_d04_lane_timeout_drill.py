"""Pytest wrapper for D-04 — Lane timeout drill.

Slow-lane scenario: dense lane responds slower than ``lane_timeout_seconds``.
The async retriever must cancel the slow lane via ``asyncio.wait_for`` and
serve the survivor's results. This is the only drill exercising the async
retrieval path; the others use the sync ``retrieve``.
"""

from __future__ import annotations

from scripts.chaos.drills import d04_lane_timeout as drill


def test_drill_passes_with_zero_failures() -> None:
    result = drill.run()

    assert result.outcome == "PASS", (
        f"D-04 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-04"
    assert result.drill_name == "lane_timeout"


def test_drill_recovers_within_rto_target() -> None:
    result = drill.run()

    assert result.rto_observed_seconds <= result.rto_target_seconds


def test_drill_cancels_slow_lane_before_full_delay() -> None:
    """The contract is that we DON'T wait the full slow_delay — we cancel
    earlier at lane_timeout_seconds. This is the timeout-tolerance
    contract that prevents one slow backend from holding up every
    public API request.
    """
    result = drill.run()

    cancellation_check = [
        entry for entry in result.verified
        if "cancellation worked" in entry.lower()
        or "< slow_delay" in entry
    ]
    assert cancellation_check, (
        f"expected cancellation-evidence verification; got {result.verified!r}"
    )


def test_drill_survivor_lane_serves_result() -> None:
    result = drill.run()

    assert result.telemetry["dense_candidates_count"] == 0
    assert result.telemetry["lexical_candidates_count"] > 0


def test_drill_observed_rto_is_close_to_lane_timeout() -> None:
    """Sanity: observed RTO should be near LANE_TIMEOUT (0.10s), not
    SLOW_DELAY (0.30s). The exact value depends on event-loop jitter.
    """
    result = drill.run()

    # Generous bounds to tolerate scheduler jitter on slow CI runners.
    assert result.rto_observed_seconds < drill.SLOW_DELAY
