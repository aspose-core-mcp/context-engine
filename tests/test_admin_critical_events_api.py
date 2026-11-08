from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.ops import (
    CriticalEventActionRecord,
    CriticalEventActionType,
    CriticalEventRecord,
    CriticalEventSeverity,
    CriticalEventType,
    InMemoryCriticalEventStore,
)

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _configure_json_dev_keys(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    keys_path = tmp_path / "admin_keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "viewer-key",
                        "token": "viewer-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": [],
                    },
                    {
                        "key_id": "operator-key",
                        "token": "operator-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion"],
                    },
                    {
                        "key_id": "foreign-operator-key",
                        "token": "foreign-operator-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["groupdocs.parser"],
                        "scopes": ["write:ingestion"],
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def test_admin_critical_events_list_requires_auth_and_returns_events() -> None:
    app = create_app()
    app.state.critical_event_store.emit(
        severity=CriticalEventSeverity.HIGH,
        event_type=CriticalEventType.PARTIAL_PUBLISH,
        message="Partial publish accepted.",
        details={"repo_id": "aspose.ocr.docs", "product_id": "aspose.ocr"},
    )

    with TestClient(app) as client:
        unauthorized = client.get("/admin/v1/events/critical")
        assert unauthorized.status_code == 401

        response = client.get("/admin/v1/events/critical", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_type"] == "partial_publish"
    assert payload[0]["product_ids"] == ["aspose.ocr"]


def test_admin_critical_event_actions_enforce_scope_and_product_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    event = app.state.critical_event_store.emit(
        severity=CriticalEventSeverity.CRITICAL,
        event_type=CriticalEventType.PUBLISH_BLOCKED,
        message="Publish blocked",
        details={"repo_id": "aspose.ocr.docs", "product_id": "aspose.ocr"},
    )

    with TestClient(app) as client:
        missing_scope = client.post(
            f"/admin/v1/events/critical/{event.event_id}:acknowledge",
            json={"reason": "investigating"},
            headers={"x-api-key": "viewer-token"},
        )
        assert missing_scope.status_code == 403
        assert "Missing required scope" in missing_scope.json()["detail"]["error"]["message"]

        product_scope_violation = client.post(
            f"/admin/v1/events/critical/{event.event_id}:acknowledge",
            json={"reason": "cross-product"},
            headers={"x-api-key": "foreign-operator-token"},
        )
        assert product_scope_violation.status_code == 403
        assert "Product scope violation" in product_scope_violation.json()["detail"]["error"][
            "message"
        ]

        acknowledged = client.post(
            f"/admin/v1/events/critical/{event.event_id}:acknowledge",
            json={"reason": "accepted"},
            headers={"x-api-key": "operator-token"},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["action"] == "acknowledge"

        actions = client.get(
            "/admin/v1/events/critical/actions",
            headers={"x-api-key": "viewer-token"},
        )
        assert actions.status_code == 200
        assert actions.json()[0]["event_id"] == event.event_id


def test_admin_critical_events_list_includes_derived_lifecycle_and_postmortem_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    event = app.state.critical_event_store.emit(
        severity=CriticalEventSeverity.CRITICAL,
        event_type=CriticalEventType.PUBLISH_BLOCKED,
        message="Publish blocked by quality gate.",
        details={"repo_id": "aspose.ocr.docs", "product_id": "aspose.ocr"},
    )

    with TestClient(app) as client:
        assign_response = client.post(
            f"/admin/v1/events/critical/{event.event_id}:assign",
            json={"owner": "product-owner", "reason": "handoff"},
            headers={"x-api-key": "operator-token"},
        )
        assert assign_response.status_code == 200

        escalate_response = client.post(
            f"/admin/v1/events/critical/{event.event_id}:escalate",
            json={"reason": "needs escalation"},
            headers={"x-api-key": "operator-token"},
        )
        assert escalate_response.status_code == 200

        override_response = client.post(
            f"/admin/v1/events/critical/{event.event_id}:severity-override",
            json={"severity": "warning", "reason": "impact reduced"},
            headers={"x-api-key": "operator-token"},
        )
        assert override_response.status_code == 200

        response = client.get(
            "/admin/v1/events/critical",
            headers={"x-api-key": "viewer-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["product_ids"] == ["aspose.ocr"]
    assert payload[0]["lifecycle"]["owner"] == "product-owner"
    assert payload[0]["lifecycle"]["status"] == "escalated"
    assert payload[0]["lifecycle"]["effective_severity"] == "warning"
    assert payload[0]["lifecycle"]["action_count"] == 3
    assert payload[0]["lifecycle"]["latest_action"] == "severity_override"
    assert payload[0]["postmortem"]["required"] is True
    assert payload[0]["postmortem"]["status"] == "pending_resolution"
    assert "## Incident Summary" in payload[0]["postmortem"]["template_markdown"]
    assert payload[0]["sla"]["target_minutes"] == 480


def test_admin_critical_events_list_marks_overdue_and_recommends_escalation() -> None:
    app = create_app()
    store = app.state.critical_event_store
    assert isinstance(store, InMemoryCriticalEventStore)

    overdue_event = CriticalEventRecord(
        event_id="evt-overdue",
        severity=CriticalEventSeverity.HIGH,
        event_type=CriticalEventType.INGESTION_CRITICAL_FAIL,
        message="Overdue ingestion failure.",
        details={"product_id": "aspose.ocr"},
        created_at=datetime.now(tz=UTC) - timedelta(minutes=180),
    )
    store._records.append(overdue_event)
    store._records_by_id[overdue_event.event_id] = overdue_event
    store._actions.append(
        CriticalEventActionRecord(
            action_id="evtact-overdue-1",
            event_id=overdue_event.event_id,
            action=CriticalEventActionType.ACKNOWLEDGE,
            actor_key_id="operator-key",
            request_id="req-overdue-1",
            payload={"reason": "seen"},
            created_at=overdue_event.created_at + timedelta(minutes=5),
        )
    )

    with TestClient(app) as client:
        response = client.get("/admin/v1/events/critical", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    overdue_item = next(item for item in payload if item["event_id"] == overdue_event.event_id)
    assert overdue_item["sla"]["overdue"] is True
    assert overdue_item["lifecycle"]["escalation_recommended"] is True
    assert overdue_item["lifecycle"]["escalation_reason"] == "sla_deadline_breached"
    assert overdue_item["lifecycle"]["status"] == "acknowledged"
