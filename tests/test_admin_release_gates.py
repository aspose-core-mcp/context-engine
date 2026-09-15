from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.ops import CriticalEventSeverity, CriticalEventType


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
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion", "write:settings"],
                    },
                    {
                        "key_id": "foreign-owner-key",
                        "token": "foreign-owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["groupdocs.parser"],
                        "scopes": ["write:ingestion", "write:settings"],
                    },
                    {
                        "key_id": "superuser-key",
                        "token": "superuser-token",
                        "is_superuser": True,
                        "enabled": True,
                        "product_scopes": [],
                        "scopes": ["*"],
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


def test_admin_role_scope_and_audit_release_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    event = app.state.critical_event_store.emit(
        severity=CriticalEventSeverity.HIGH,
        event_type=CriticalEventType.PARTIAL_PUBLISH,
        message="release-gate event",
        details={"product_id": "aspose.ocr"},
    )

    with TestClient(app) as client:
        session_viewer = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": "viewer-token"},
        )
        assert session_viewer.status_code == 200
        assert session_viewer.json()["effective_role"] == "viewer"

        session_operator = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": "operator-token"},
        )
        assert session_operator.status_code == 200
        assert session_operator.json()["effective_role"] == "operator"

        session_owner = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": "owner-token"},
        )
        assert session_owner.status_code == 200
        assert session_owner.json()["effective_role"] == "product-owner"

        forbidden_viewer = client.post(
            f"/admin/v1/events/critical/{event.event_id}:acknowledge",
            json={"reason": "no write scope"},
            headers={"x-api-key": "viewer-token"},
        )
        assert forbidden_viewer.status_code == 403

        forbidden_scope = client.post(
            f"/admin/v1/events/critical/{event.event_id}:acknowledge",
            json={"reason": "wrong product"},
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert forbidden_scope.status_code == 403

        endpoints = [
            ("acknowledge", {"reason": "ok"}),
            ("mute", {"duration_minutes": 60, "reason": "quiet window"}),
            ("snooze", {"duration_minutes": 30, "reason": "temporary delay"}),
            ("assign", {"owner": "owner-a", "reason": "handoff"}),
            ("severity-override", {"severity": "warning", "reason": "adjusted"}),
            ("escalate", {"reason": "escalation"}),
            ("resolve", {"reason": "resolved"}),
        ]
        for action, payload in endpoints:
            response = client.post(
                f"/admin/v1/events/critical/{event.event_id}:{action}",
                json=payload,
                headers={"x-api-key": "operator-token"},
            )
            assert response.status_code == 200

        actions_response = client.get(
            f"/admin/v1/events/critical/actions?event_id={event.event_id}",
            headers={"x-api-key": "viewer-token"},
        )
        assert actions_response.status_code == 200
        actions = actions_response.json()
        action_names = {item["action"] for item in actions}
        assert action_names == {
            "acknowledge",
            "mute",
            "snooze",
            "assign_owner",
            "severity_override",
            "escalate",
            "resolved",
        }
        for item in actions:
            assert item["actor_key_id"] == "operator-key"
            assert item["request_id"]
            assert item["created_at"]


def test_admin_rollback_requires_product_scope_and_records_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        first = client.patch(
            "/admin/v1/settings/retrieval/aspose.ocr",
            json={
                "top_k": 10,
                "max_context_tokens": 4096,
                "excerpt_char_limit": 900,
                "low_confidence_threshold": 0.35,
                "clarification_policy": "always_prompt",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert first.status_code == 200

        second = client.patch(
            "/admin/v1/settings/retrieval/aspose.ocr",
            json={
                "top_k": 5,
                "max_context_tokens": 4096,
                "excerpt_char_limit": 700,
                "low_confidence_threshold": 0.25,
                "clarification_policy": "ask_user_followup",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert second.status_code == 200

        history_before = client.get(
            "/admin/v1/config/history?product_id=aspose.ocr&config_scope=retrieval_settings",
            headers={"x-api-key": "viewer-token"},
        )
        assert history_before.status_code == 200
        change_id = history_before.json()[0]["change_id"]

        forbidden = client.post(
            "/admin/v1/config/rollback",
            json={"change_id": change_id, "reason": "cross-scope rollback"},
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert forbidden.status_code == 403

        rollback = client.post(
            "/admin/v1/config/rollback",
            json={"change_id": change_id, "reason": "release gate rollback"},
            headers={"x-api-key": "owner-token"},
        )
        assert rollback.status_code == 200
        rollback_payload = rollback.json()
        assert rollback_payload["status"] == "rolled_back"

        history_after = client.get(
            "/admin/v1/config/history?product_id=aspose.ocr&config_scope=retrieval_settings",
            headers={"x-api-key": "viewer-token"},
        )
        assert history_after.status_code == 200
        latest = history_after.json()[0]
        assert latest["change_id"] == rollback_payload["rollback_change_id"]
        assert latest["action_type"] == "rollback"
        assert latest["actor_key_id"] == "owner-key"
        assert latest["reason"] == "release gate rollback"
        assert latest["request_id"]


def test_runtime_snapshot_rollback_release_gate_records_audit_and_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    target = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    active = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )

    with TestClient(app) as client:
        confirmation = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback-confirmation",
            json={"reason": "release gate runtime rollback"},
            headers={"x-api-key": "owner-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        rollback = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback",
            json={
                "reason": "release gate runtime rollback",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert rollback.status_code == 200
        rollback_payload = rollback.json()
        assert rollback_payload["status"] == "completed"
        assert rollback_payload["active_snapshot_before"]["snapshot_id"] == active.snapshot_id
        assert rollback_payload["active_snapshot_after"]["snapshot_id"] == target.snapshot_id
        assert rollback_payload["audit_id"].startswith("rbka-")

        audit_records = client.get(
            "/admin/v1/snapshots:rollback-audit?product_id=aspose.ocr&limit=10",
            headers={"x-api-key": "viewer-token"},
        )
        assert audit_records.status_code == 200
        records = audit_records.json()
        assert records
        assert records[0]["audit_id"] == rollback_payload["audit_id"]
        assert records[0]["result_status"] == "completed"
        assert records[0]["actor_key_id"] == "owner-key"

        events = client.get(
            "/admin/v1/events/critical?event_type=rollback_succeeded&limit=10",
            headers={"x-api-key": "viewer-token"},
        )
        assert events.status_code == 200
        payload = events.json()
        assert any(
            item["details"].get("audit_id") == rollback_payload["audit_id"]
            and item["details"].get("active_snapshot_before_id") == active.snapshot_id
            and item["details"].get("active_snapshot_after_id") == target.snapshot_id
            for item in payload
        )


def test_admin_observability_summary_is_available_for_read_only_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    metrics = app.state.metrics
    metrics.observe_mcp_negotiation(
        requested_revision="2025-06-18",
        negotiated_revision="2025-11-25",
        fallback_reason="unknown_revision",
        fallback_applied=True,
    )

    with TestClient(app) as client:
        response = client.get(
            "/admin/v1/observability/summary",
            headers={"x-api-key": "viewer-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp_negotiation_total"] >= 1
    assert "abuse_guard_decisions_by_mode" in payload
