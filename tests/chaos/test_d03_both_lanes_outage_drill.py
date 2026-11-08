"""Pytest wrapper for D-03 — Both lanes outage drill.

Catastrophic scenario: BOTH Qdrant and OpenSearch unavailable. The
contract is that the retriever returns an empty envelope without raising,
so the public API returns 200 with zero candidates instead of a 500.
This is the absolute floor of the degraded-mode contract.
"""

from __future__ import annotations

from scripts.chaos.drills import d03_both_lanes_outage as drill


def test_drill_passes_with_zero_failures() -> None:
    result = drill.run()

    assert result.outcome == "PASS", (
        f"D-03 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-03"
    assert result.drill_name == "both_lanes_outage"


def test_drill_no_exception_escapes() -> None:
    """The critical FAIL trigger: an exception escaping HybridRetriever
    would mean the public API returns 500. The drill flags this as FAIL,
    so simply asserting outcome != FAIL covers the contract.
    """
    result = drill.run()

    assert result.outcome != "FAIL"


def test_drill_returns_clean_empty_envelope() -> None:
    result = drill.run()

    empty_envelope_check = [
        entry for entry in result.verified
        if "len(candidates) == 0" in entry
        or "clean empty envelope" in entry.lower()
    ]
    assert empty_envelope_check, (
        f"expected empty-envelope verification; got {result.verified!r}"
    )


def test_drill_emits_two_warnings() -> None:
    """Both lane failures must surface in the operator's log feed."""
    result = drill.run()

    warning_verifications = [
        entry for entry in result.verified
        if "WARNING" in entry and "both lanes" in entry.lower()
    ]
    assert warning_verifications


def test_drill_telemetry_shape() -> None:
    result = drill.run()

    assert result.telemetry["dense_candidates_count"] == 0
    assert result.telemetry["lexical_candidates_count"] == 0
    assert result.telemetry["result_size"] == 0
    assert result.telemetry["warning_records"] >= 2
