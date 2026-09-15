"""Pytest wrapper for D-01 — Dense lane (Qdrant) outage drill.

Guards the contract that ``HybridRetriever.retrieve`` continues to serve
lexical-only results when the dense lane raises. Originally verified by
``tests/test_hybrid_retriever.py::test_sync_retrieve_degrades_when_dense_lane_fails``
— this wrapper additionally checks the audit-trail emit path (the same
DrillResult JSON written to ``reports/chaos/drill-log.jsonl`` on every
monthly chaos run).
"""

from __future__ import annotations

from scripts.chaos.drills import d01_dense_lane_outage as drill


def test_drill_passes_with_zero_failures() -> None:
    """Top-level contract: drill must end PASS with no failures."""
    result = drill.run()

    assert result.outcome == "PASS", (
        f"D-01 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-01"
    assert result.drill_name == "dense_lane_outage"


def test_drill_recovers_within_rto_target() -> None:
    """Recovery must be inside the runbook-derived RTO target."""
    result = drill.run()

    assert result.rto_observed_seconds <= result.rto_target_seconds, (
        f"observed={result.rto_observed_seconds}s "
        f"exceeds target={result.rto_target_seconds}s"
    )
    assert result.rpo_observed_seconds == 0.0


def test_drill_verifies_lexical_lane_survives() -> None:
    """Survivor lane must contribute candidates to the result envelope."""
    result = drill.run()

    survivor_verifications = [
        entry for entry in result.verified
        if "lexical_candidates_count" in entry
    ]
    assert survivor_verifications, (
        "expected at least one verified entry mentioning lexical_candidates_count"
    )


def test_drill_verifies_warning_log_emitted() -> None:
    """A WARNING log must fire so the on-call sees the outage."""
    result = drill.run()

    warning_verifications = [
        entry for entry in result.verified
        if "WARNING" in entry and "Dense lane failed" in entry
    ]
    assert warning_verifications, (
        f"expected WARNING log verification; got {result.verified!r}"
    )


def test_drill_telemetry_shape() -> None:
    """Telemetry must include the keys downstream auditors will look for."""
    result = drill.run()

    assert result.telemetry["dense_candidates_count"] == 0
    assert result.telemetry["lexical_candidates_count"] > 0
    assert result.telemetry["dense_search_calls"] == 1
    assert result.telemetry["warning_records"] >= 1
