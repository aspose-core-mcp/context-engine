"""Tests for the admin quality-loop calibration endpoint.

Asserts the endpoint:
* requires admin auth (no key → 401);
* returns sensible defaults when no calibration-state.json exists;
* parses an existing calibration-state.json into the response payload;
* picks AdaptationEvent rows out of a JSONL audit log;
* respects the `limit` query parameter and the [1, 500] range;
* skips malformed audit-log rows silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Each test runs against a tmpdir for the quality-loop artefacts so
    # the endpoint does not read the real (gitignored) reports/quality-loop/
    # directory shared with the live loop.
    monkeypatch.setenv(
        "ADCS_QUALITY_LOOP_REPORTS_DIR", str(tmp_path / "reports" / "quality-loop")
    )
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_artifacts(
    base: Path, *, state: dict | None = None, audit_events: list[dict] | None = None
) -> None:
    base.mkdir(parents=True, exist_ok=True)
    if state is not None:
        (base / "calibration-state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
    if audit_events is not None:
        log = base / "audit-log.jsonl"
        with log.open("w", encoding="utf-8") as fh:
            for event in audit_events:
                fh.write(json.dumps(event) + "\n")


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


def test_endpoint_requires_admin_auth() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/admin/quality-loop/calibration")
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Default response when no artefacts exist
# ---------------------------------------------------------------------------


def test_returns_default_state_when_no_artefacts() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/quality-loop/calibration", headers=ADMIN_HEADERS
        )
    assert response.status_code == 200
    payload = response.json()
    state = payload["state"]
    assert state["judge_low_threshold"] == 0.70
    assert state["diagnosis_min_low_ratio"] == 0.40
    assert state["proposal_high_confidence_floor"] == 0.85
    assert state["guard_auto_approve_blast_cap"] == 100
    assert state["cycle_count"] == 0
    assert payload["recent_adaptations"] == []
    assert payload["recent_adaptation_count"] == 0
    # Bounds default-on
    bounds = payload["bounds"]
    assert bounds["judge_low_threshold_min"] == 0.50
    assert bounds["judge_low_threshold_max"] == 0.85


# ---------------------------------------------------------------------------
# Reading committed artefacts
# ---------------------------------------------------------------------------


def test_returns_persisted_state_when_calibration_file_exists(tmp_path: Path) -> None:
    base = tmp_path / "reports" / "quality-loop"
    _write_artifacts(
        base,
        state={
            "judge_low_threshold": 0.72,
            "diagnosis_min_low_ratio": 0.45,
            "proposal_high_confidence_floor": 0.87,
            "guard_auto_approve_blast_cap": 75,
            "cycle_count": 12,
            "cycles_since_last_rejection": 5,
            "bounds": {
                "judge_low_threshold_min": 0.50,
                "judge_low_threshold_max": 0.85,
                "diagnosis_min_low_ratio_min": 0.20,
                "diagnosis_min_low_ratio_max": 0.70,
                "proposal_high_confidence_floor_min": 0.70,
                "proposal_high_confidence_floor_max": 0.95,
                "guard_auto_approve_blast_cap_min": 25,
                "guard_auto_approve_blast_cap_max": 500,
            },
        },
    )
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/quality-loop/calibration", headers=ADMIN_HEADERS
        )
    assert response.status_code == 200
    state = response.json()["state"]
    assert state["judge_low_threshold"] == 0.72
    assert state["cycle_count"] == 12
    assert state["cycles_since_last_rejection"] == 5


def test_picks_adaptation_events_out_of_audit_log(tmp_path: Path) -> None:
    base = tmp_path / "reports" / "quality-loop"
    _write_artifacts(
        base,
        state=None,
        audit_events=[
            {"message_type": "CycleSummary", "cycle_id": "c1"},  # not an adaptation
            {
                "message_type": "AdaptationEvent",
                "event_id": "adapt-aaa111",
                "cycle_id": "c1",
                "emitted_at": "2026-06-01T00:00:00Z",
                "kind": "guard_blast_cap_tighten",
                "parameter_name": "guard_auto_approve_blast_cap",
                "previous_value": 100,
                "new_value": 50,
                "delta": -50,
                "rationale": "REJECTED outcome observed",
            },
            {"message_type": "QualityVerdict", "sample_id": "s1"},  # not an adaptation
            {
                "message_type": "AdaptationEvent",
                "event_id": "adapt-bbb222",
                "cycle_id": "c2",
                "emitted_at": "2026-06-01T01:00:00Z",
                "kind": "judge_low_threshold_raise",
                "parameter_name": "judge_low_threshold",
                "previous_value": 0.70,
                "new_value": 0.71,
                "delta": 0.01,
                "rationale": "low-score fraction below target",
            },
        ],
    )
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/quality-loop/calibration", headers=ADMIN_HEADERS
        )
    payload = response.json()
    assert payload["recent_adaptation_count"] == 2
    assert payload["recent_adaptations"][0]["event_id"] == "adapt-aaa111"
    assert payload["recent_adaptations"][1]["kind"] == "judge_low_threshold_raise"


def test_limit_query_caps_returned_adaptations(tmp_path: Path) -> None:
    base = tmp_path / "reports" / "quality-loop"
    events = [
        {
            "message_type": "AdaptationEvent",
            "event_id": f"adapt-{i:03}",
            "cycle_id": f"c{i}",
            "emitted_at": f"2026-06-01T{i:02}:00:00Z",
            "kind": "guard_blast_cap_tighten",
            "parameter_name": "guard_auto_approve_blast_cap",
            "previous_value": 100 - i,
            "new_value": 99 - i,
            "delta": -1,
            "rationale": "test",
        }
        for i in range(20)
    ]
    _write_artifacts(base, audit_events=events)
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/quality-loop/calibration?limit=5", headers=ADMIN_HEADERS
        )
    payload = response.json()
    assert payload["recent_adaptation_count"] == 5
    # Should return the LAST 5 events (most recent at the tail of the file)
    returned_ids = [e["event_id"] for e in payload["recent_adaptations"]]
    assert returned_ids == [
        "adapt-015",
        "adapt-016",
        "adapt-017",
        "adapt-018",
        "adapt-019",
    ]


def test_limit_query_param_range_is_enforced() -> None:
    app = create_app()
    with TestClient(app) as client:
        # limit=0 is below the ge=1 floor and limit=1000 is above the le=500 cap.
        too_low = client.get(
            "/v1/admin/quality-loop/calibration?limit=0", headers=ADMIN_HEADERS
        )
        too_high = client.get(
            "/v1/admin/quality-loop/calibration?limit=1000", headers=ADMIN_HEADERS
        )
    # FastAPI emits 422 for query param validation errors; either way the
    # status must be a client error (4xx), not a 200 OK that silently
    # ignored the violation.
    assert 400 <= too_low.status_code < 500
    assert 400 <= too_high.status_code < 500


def test_malformed_audit_log_lines_are_skipped(tmp_path: Path) -> None:
    base = tmp_path / "reports" / "quality-loop"
    base.mkdir(parents=True, exist_ok=True)
    log = base / "audit-log.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        fh.write("not-json-at-all\n")
        fh.write("\n")  # blank line
        fh.write(
            json.dumps(
                {
                    "message_type": "AdaptationEvent",
                    "event_id": "adapt-ccc333",
                    "cycle_id": "c1",
                    "emitted_at": "2026-06-01T00:00:00Z",
                    "kind": "guard_blast_cap_tighten",
                    "parameter_name": "guard_auto_approve_blast_cap",
                    "previous_value": 100,
                    "new_value": 50,
                    "delta": -50,
                    "rationale": "test",
                }
            )
            + "\n"
        )
        fh.write("{not_complete_json: ")  # malformed
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/quality-loop/calibration", headers=ADMIN_HEADERS
        )
    assert response.status_code == 200
    payload = response.json()
    # Only the one valid AdaptationEvent should be returned
    assert payload["recent_adaptation_count"] == 1
    assert payload["recent_adaptations"][0]["event_id"] == "adapt-ccc333"
