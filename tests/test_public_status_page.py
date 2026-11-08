"""Tests for the public status-page extension endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.public_status_page import _CONFIG_PATH, router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_status_page_default_config_is_operational(tmp_path: Path) -> None:
    config = {"components": [{"id": "x", "name": "X", "description": "", "depends_on": []}]}
    cfg_file = tmp_path / "status-page-config.json"
    cfg_file.write_text(json.dumps(config))

    with patch.object(_CONFIG_PATH.__class__, "exists", return_value=True), patch(
        "adcs.api.public_status_page._CONFIG_PATH", cfg_file
    ):
        client = TestClient(_make_app())
        resp = client.get("/v1/status/page")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_state"] == "operational"
    assert body["overall_message"] == "All systems operational."
    assert body["components"] == [
        {
            "id": "x",
            "name": "X",
            "description": "",
            "depends_on": [],
            "state": "operational",
            "note": "",
        }
    ]
    assert body["active_incidents"] == []
    assert body["recent_incidents"] == []
    assert body["upcoming_maintenance"] == []
    assert body["active_maintenance"] == []
    assert body["announcements"] == []


def test_status_page_active_incident_drives_overall_state(tmp_path: Path) -> None:
    started = datetime.now(tz=UTC) - timedelta(minutes=10)
    config = {
        "components": [],
        "incidents": [
            {
                "id": "inc-1",
                "title": "API latency",
                "severity": "sev2",
                "affected_components": ["rest_api"],
                "started_at": started.isoformat(),
                "public_message": "We are investigating elevated latency.",
                "updates": [
                    {
                        "timestamp": started.isoformat(),
                        "state": "investigating",
                        "message": "Investigating",
                    }
                ],
            }
        ],
    }
    cfg_file = tmp_path / "status-page-config.json"
    cfg_file.write_text(json.dumps(config))

    with patch("adcs.api.public_status_page._CONFIG_PATH", cfg_file):
        client = TestClient(_make_app())
        resp = client.get("/v1/status/page")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_state"] == "partial_outage"
    assert len(body["active_incidents"]) == 1
    assert body["active_incidents"][0]["title"] == "API latency"


def test_status_page_resolved_incident_goes_to_recent(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    config = {
        "components": [],
        "incidents": [
            {
                "id": "inc-old",
                "title": "Past outage",
                "severity": "sev1",
                "started_at": (now - timedelta(days=1)).isoformat(),
                "resolved_at": (now - timedelta(hours=20)).isoformat(),
                "public_message": "Resolved.",
            }
        ],
    }
    cfg_file = tmp_path / "status-page-config.json"
    cfg_file.write_text(json.dumps(config))

    with patch("adcs.api.public_status_page._CONFIG_PATH", cfg_file):
        client = TestClient(_make_app())
        resp = client.get("/v1/status/page")
    body = resp.json()
    assert body["active_incidents"] == []
    assert len(body["recent_incidents"]) == 1
    assert body["overall_state"] == "operational"


def test_status_page_active_maintenance_in_window(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    config = {
        "components": [],
        "maintenance_windows": [
            {
                "id": "mw-1",
                "title": "Database migration",
                "scheduled_start": (now - timedelta(minutes=30)).isoformat(),
                "scheduled_end": (now + timedelta(minutes=30)).isoformat(),
                "public_message": "Scheduled DB migration in progress.",
            },
            {
                "id": "mw-2",
                "title": "Future window",
                "scheduled_start": (now + timedelta(days=2)).isoformat(),
                "scheduled_end": (now + timedelta(days=2, hours=1)).isoformat(),
            },
            {
                "id": "mw-3",
                "title": "Past window",
                "scheduled_start": (now - timedelta(days=2)).isoformat(),
                "scheduled_end": (now - timedelta(days=1)).isoformat(),
                "actual_end": (now - timedelta(days=1)).isoformat(),
            },
        ],
    }
    cfg_file = tmp_path / "status-page-config.json"
    cfg_file.write_text(json.dumps(config))

    with patch("adcs.api.public_status_page._CONFIG_PATH", cfg_file):
        client = TestClient(_make_app())
        resp = client.get("/v1/status/page")
    body = resp.json()
    assert [m["id"] for m in body["active_maintenance"]] == ["mw-1"]
    assert [m["id"] for m in body["upcoming_maintenance"]] == ["mw-2"]


def test_status_page_expired_announcements_are_dropped(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    config = {
        "components": [],
        "announcements": [
            {
                "id": "a-active",
                "title": "Active note",
                "severity": "info",
                "posted_at": (now - timedelta(days=1)).isoformat(),
                "expires_at": (now + timedelta(days=30)).isoformat(),
                "body": "...",
            },
            {
                "id": "a-expired",
                "title": "Expired note",
                "severity": "info",
                "posted_at": (now - timedelta(days=60)).isoformat(),
                "expires_at": (now - timedelta(days=1)).isoformat(),
                "body": "...",
            },
        ],
    }
    cfg_file = tmp_path / "status-page-config.json"
    cfg_file.write_text(json.dumps(config))

    with patch("adcs.api.public_status_page._CONFIG_PATH", cfg_file):
        client = TestClient(_make_app())
        resp = client.get("/v1/status/page")
    body = resp.json()
    assert [a["id"] for a in body["announcements"]] == ["a-active"]
