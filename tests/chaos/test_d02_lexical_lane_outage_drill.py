"""Pytest wrapper for D-02 — Lexical lane (OpenSearch) outage drill.

Symmetric counterpart to D-01: when OpenSearch is unavailable, the
hybrid retriever must continue serving vector-only results. Originally
verified by
``tests/test_hybrid_retriever.py::test_sync_retrieve_degrades_when_lexical_lane_fails``.
"""

from __future__ import annotations

from scripts.chaos.drills import d02_lexical_lane_outage as drill


def test_drill_passes_with_zero_failures() -> None:
    result = drill.run()

    assert result.outcome == "PASS", (
        f"D-02 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-02"
    assert result.drill_name == "lexical_lane_outage"


def test_drill_recovers_within_rto_target() -> None:
    result = drill.run()

    assert result.rto_observed_seconds <= result.rto_target_seconds
    assert result.rpo_observed_seconds == 0.0


def test_drill_verifies_dense_lane_survives() -> None:
    result = drill.run()

    survivor_verifications = [
        entry for entry in result.verified
        if "dense_candidates_count" in entry
    ]
    assert survivor_verifications


def test_drill_verifies_warning_log_emitted() -> None:
    result = drill.run()

    warning_verifications = [
        entry for entry in result.verified
        if "WARNING" in entry and "Lexical lane failed" in entry
    ]
    assert warning_verifications, (
        f"expected WARNING log verification; got {result.verified!r}"
    )


def test_drill_telemetry_shape() -> None:
    result = drill.run()

    assert result.telemetry["lexical_candidates_count"] == 0
    assert result.telemetry["dense_candidates_count"] > 0
    assert result.telemetry["lexical_search_calls"] == 1
    assert result.telemetry["warning_records"] >= 1
