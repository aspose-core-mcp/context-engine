"""Pytest wrapper for D-05 — Snapshot rollback drill.

Scenario: an active snapshot is corrupted; the on-call rolls back to
the previous known-good snapshot using the optimistic-concurrency
rollback API. This drill verifies the rollback contract end-to-end
against the in-memory registry, including the optimistic-concurrency
guard (``expected_active_snapshot_id``).
"""

from __future__ import annotations

from scripts.chaos.drills import d05_snapshot_rollback as drill


def test_drill_passes_with_zero_failures() -> None:
    result = drill.run()

    assert result.outcome == "PASS", (
        f"D-05 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-05"
    assert result.drill_name == "snapshot_rollback"


def test_drill_recovers_within_rto_target() -> None:
    result = drill.run()

    assert result.rto_observed_seconds <= result.rto_target_seconds


def test_drill_rolls_back_to_good_snapshot() -> None:
    result = drill.run()

    promoted_check = [
        entry for entry in result.verified
        if "promoted to ACTIVE" in entry
    ]
    demoted_check = [
        entry for entry in result.verified
        if "demoted to INACTIVE" in entry
    ]
    assert promoted_check, "expected target-promoted verification"
    assert demoted_check, "expected previous-active-demoted verification"


def test_drill_optimistic_concurrency_guard_fires() -> None:
    """A stale rollback request must be rejected with
    SnapshotRollbackConflictError — guards against double-rollback races.
    """
    result = drill.run()

    guard_check = [
        entry for entry in result.verified
        if "optimistic-concurrency guard fired" in entry
    ]
    assert guard_check, (
        f"expected optimistic-concurrency verification; got {result.verified!r}"
    )


def test_drill_telemetry_records_both_snapshot_ids() -> None:
    result = drill.run()

    assert result.telemetry["good_snapshot_id"]
    assert result.telemetry["bad_snapshot_id"]
    assert result.telemetry["good_snapshot_id"] != result.telemetry["bad_snapshot_id"]
    assert result.telemetry["concurrency_guard_fired"] is True
