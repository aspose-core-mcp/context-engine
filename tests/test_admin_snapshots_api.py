from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.indexing import SnapshotRollbackConflictError

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
                        "key_id": "operator-key",
                        "token": "operator-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion", "write:destructive"],
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


def test_admin_snapshots_endpoints_list_get_active() -> None:
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    first = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    second = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )

    with TestClient(app) as client:
        listed = client.get(
            "/admin/v1/snapshots?product_id=aspose.ocr&programming_language=net&version=25.1",
            headers=ADMIN_HEADERS,
        )
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert len(listed_payload) >= 2
        assert listed_payload[0]["snapshot_id"] == second.snapshot_id

        fetched = client.get(
            f"/admin/v1/snapshots/{first.snapshot_id}",
            headers=ADMIN_HEADERS,
        )
        assert fetched.status_code == 200
        assert fetched.json()["snapshot_id"] == first.snapshot_id
        assert fetched.json()["status"] == "inactive"

        active = client.get(
            "/admin/v1/snapshots/active"
            "?product_id=aspose.ocr&programming_language=net&version=25.1",
            headers=ADMIN_HEADERS,
        )
        assert active.status_code == 200
        assert active.json()["snapshot_id"] == second.snapshot_id
        assert active.json()["status"] == "active"


def test_admin_snapshots_active_returns_not_found_for_unknown_scope() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/admin/v1/snapshots/active"
            "?product_id=aspose.ocr&programming_language=java&version=99.9",
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "NOT_FOUND"


def test_admin_snapshots_compare_and_promote() -> None:
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    first = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    second = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )

    with TestClient(app) as client:
        compare = client.get(
            "/admin/v1/snapshots:compare"
            f"?base_snapshot_id={first.snapshot_id}&target_snapshot_id={second.snapshot_id}",
            headers=ADMIN_HEADERS,
        )
        assert compare.status_code == 200
        compare_payload = compare.json()
        assert compare_payload["same_scope"] is True
        assert compare_payload["indexed_chunks_delta"] == 2

        promote = client.post(
            f"/admin/v1/snapshots/{first.snapshot_id}:promote",
            headers=ADMIN_HEADERS,
        )
        assert promote.status_code == 200
        assert promote.json()["snapshot_id"] == first.snapshot_id
        assert promote.json()["status"] == "active"

        active = client.get(
            "/admin/v1/snapshots/active"
            "?product_id=aspose.ocr&programming_language=net&version=25.1",
            headers=ADMIN_HEADERS,
        )
        assert active.status_code == 200
        assert active.json()["snapshot_id"] == first.snapshot_id
        assert active.json()["status"] == "active"


def test_admin_snapshots_promote_enforces_product_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    snapshot = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )

    with TestClient(app) as client:
        forbidden = client.post(
            f"/admin/v1/snapshots/{snapshot.snapshot_id}:promote",
            headers={"x-api-key": "foreign-operator-token"},
        )
        assert forbidden.status_code == 403

        allowed = client.post(
            f"/admin/v1/snapshots/{snapshot.snapshot_id}:promote",
            headers={"x-api-key": "operator-token"},
        )
        assert allowed.status_code == 200


def test_admin_snapshot_rollback_execution_success(
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
            json={"reason": "rollback to previous stable revision"},
            headers={"x-api-key": "operator-token"},
        )
        assert confirmation.status_code == 200
        confirm_payload = confirmation.json()
        assert confirm_payload["snapshot_id"] == target.snapshot_id
        assert confirm_payload["confirm_token"].startswith("wmcp_cf_")

        rollback = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback",
            json={
                "reason": "rollback to previous stable revision",
                "confirm_token": confirm_payload["confirm_token"],
            },
            headers={"x-api-key": "operator-token"},
        )
        assert rollback.status_code == 200
        payload = rollback.json()
        assert payload["status"] == "completed"
        assert payload["can_execute"] is True
        assert payload["target_snapshot"]["snapshot_id"] == target.snapshot_id
        assert payload["active_snapshot_before"]["snapshot_id"] == active.snapshot_id
        assert payload["active_snapshot_after"]["snapshot_id"] == target.snapshot_id
        assert payload["history_preserved"] is True
        assert payload["operation_id"].startswith("rbk-op-")
        assert payload["preflight_diagnostics"]
        assert payload["consistency_checks"]

        current_active = client.get(
            "/admin/v1/snapshots/active"
            "?product_id=aspose.ocr&programming_language=net&version=25.1",
            headers={"x-api-key": "operator-token"},
        )
        assert current_active.status_code == 200
        assert current_active.json()["snapshot_id"] == target.snapshot_id


def test_admin_snapshot_rollback_records_audit_and_critical_event(
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
            json={"reason": "rollback with audit"},
            headers={"x-api-key": "operator-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        rollback = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback",
            json={
                "reason": "rollback with audit",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "operator-token"},
        )
        assert rollback.status_code == 200
        payload = rollback.json()
        audit_id = payload["audit_id"]
        assert payload["active_snapshot_before"]["snapshot_id"] == active.snapshot_id
        assert payload["active_snapshot_after"]["snapshot_id"] == target.snapshot_id

        audit_records = client.get(
            "/admin/v1/snapshots:rollback-audit?product_id=aspose.ocr&limit=10",
            headers={"x-api-key": "operator-token"},
        )
        assert audit_records.status_code == 200
        records = audit_records.json()
        assert records
        latest = records[0]
        assert latest["audit_id"] == audit_id
        assert latest["result_status"] == "completed"
        assert latest["actor_key_id"] == "operator-key"
        assert latest["target_snapshot_id"] == target.snapshot_id
        assert latest["active_snapshot_before_id"] == active.snapshot_id
        assert latest["active_snapshot_after_id"] == target.snapshot_id
        assert latest["request_id"] is not None

        rollback_events = client.get(
            "/admin/v1/events/critical?event_type=rollback_succeeded&limit=10",
            headers={"x-api-key": "operator-token"},
        )
        assert rollback_events.status_code == 200
        events = rollback_events.json()
        assert any(event["details"].get("audit_id") == audit_id for event in events)


def test_admin_snapshot_rollback_preflight_fails_for_active_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    snapshot_registry.create_snapshot(
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
            f"/admin/v1/snapshots/{active.snapshot_id}:rollback-confirmation",
            json={"reason": "attempt rollback to current active"},
            headers={"x-api-key": "operator-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        rollback = client.post(
            f"/admin/v1/snapshots/{active.snapshot_id}:rollback",
            json={
                "reason": "attempt rollback to current active",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "operator-token"},
        )
        assert rollback.status_code == 409
        payload = rollback.json()["detail"]["error"]
        assert payload["code"] == "ROLLBACK_PREFLIGHT_FAILED"
        assert payload["details"]["audit_id"].startswith("rbka-")
        assert payload["details"]["operation_id"].startswith("rbk-op-")
        diagnostics = payload["details"]["diagnostics"]
        assert any(
            item["code"] == "TARGET_IS_NOT_ACTIVE" and item["status"] == "fail"
            for item in diagnostics
        )

        audit_records = client.get(
            "/admin/v1/snapshots:rollback-audit?product_id=aspose.ocr&limit=10",
            headers={"x-api-key": "operator-token"},
        )
        assert audit_records.status_code == 200
        records = audit_records.json()
        assert records
        assert records[0]["audit_id"] == payload["details"]["audit_id"]
        assert records[0]["result_status"] == "preflight_failed"

        rollback_events = client.get(
            "/admin/v1/events/critical?event_type=rollback_failed&limit=10",
            headers={"x-api-key": "operator-token"},
        )
        assert rollback_events.status_code == 200
        events = rollback_events.json()
        assert any(
            event["details"].get("audit_id") == payload["details"]["audit_id"]
            for event in events
        )


def test_admin_snapshot_rollback_execution_fails_on_active_scope_conflict(
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

    def _raise_conflict(
        *,
        target_snapshot_id: str,
        expected_active_snapshot_id: str,
    ) -> None:
        raise SnapshotRollbackConflictError(
            code="ACTIVE_SNAPSHOT_CHANGED",
            message="simulated active snapshot race",
            expected_active_snapshot_id=expected_active_snapshot_id,
            current_active_snapshot_id="snap-override",
        )

    monkeypatch.setattr(snapshot_registry, "rollback_snapshot", _raise_conflict)

    with TestClient(app) as client:
        confirmation = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback-confirmation",
            json={"reason": "rollback with simulated conflict"},
            headers={"x-api-key": "operator-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        rollback = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback",
            json={
                "reason": "rollback with simulated conflict",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "operator-token"},
        )
        assert rollback.status_code == 409
        payload = rollback.json()["detail"]["error"]
        assert payload["code"] == "ACTIVE_SNAPSHOT_CHANGED"
        assert payload["details"]["status"] == "rollback_conflict"
        assert payload["details"]["expected_active_snapshot_id"] == active.snapshot_id
        assert payload["details"]["current_active_snapshot_id"] == "snap-override"


def test_admin_snapshot_rollback_confirmation_enforces_product_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    snapshot = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )

    with TestClient(app) as client:
        forbidden = client.post(
            f"/admin/v1/snapshots/{snapshot.snapshot_id}:rollback-confirmation",
            json={"reason": "out-of-scope rollback"},
            headers={"x-api-key": "foreign-operator-token"},
        )
        assert forbidden.status_code == 403


def test_admin_snapshot_rollback_preflight_requires_valid_confirmation(
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
    snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/admin/v1/snapshots/{target.snapshot_id}:rollback",
            json={
                "reason": "rollback with invalid token",
                "confirm_token": "invalid-token",
            },
            headers={"x-api-key": "operator-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error"]["code"] == "CONFIRMATION_INVALID"


def test_admin_snapshot_cleanup_preview_and_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot_registry = app.state.snapshot_registry
    app.state.index_topology_policy = replace(
        app.state.index_topology_policy,
        compaction=replace(
            app.state.index_topology_policy.compaction,
            enabled=True,
            max_inactive_snapshots_per_scope=1,
            stale_snapshot_retention_days=30,
        ),
    )
    active = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    stale = snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    snapshot_registry.promote_snapshot(snapshot_id=active.snapshot_id)
    stale_snapshot = snapshot_registry.get_snapshot(stale.snapshot_id)
    assert stale_snapshot is not None
    snapshot_registry._snapshots[stale.snapshot_id] = replace(  # type: ignore[attr-defined]
        stale_snapshot,
        created_at=datetime.now(tz=UTC) - timedelta(days=45),
    )

    with TestClient(app) as client:
        preview = client.post(
            "/admin/v1/snapshots:cleanup-preview",
            json={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "version": "25.1",
                "source_kind": "docs",
            },
            headers={"x-api-key": "operator-token"},
        )
        assert preview.status_code == 200
        preview_payload = preview.json()
        assert preview_payload["delete_candidates_count"] == 1
        assert preview_payload["delete_candidates"][0]["snapshot_id"] == stale.snapshot_id

        execute = client.post(
            "/admin/v1/snapshots:cleanup",
            json={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "version": "25.1",
                "source_kind": "docs",
                "reason": "cleanup stale inactive snapshots",
            },
            headers={"x-api-key": "operator-token"},
        )
        assert execute.status_code == 200
        execute_payload = execute.json()
        assert execute_payload["status"] == "completed"
        assert execute_payload["deleted_snapshots_count"] == 1
        assert execute_payload["deleted_snapshots"][0]["snapshot_id"] == stale.snapshot_id
        assert snapshot_registry.get_snapshot(stale.snapshot_id) is None
        assert snapshot_registry.get_snapshot(active.snapshot_id) is not None

        history = client.get(
            "/admin/v1/snapshots:cleanup-history?product_id=aspose.ocr&limit=10",
            headers={"x-api-key": "operator-token"},
        )
        assert history.status_code == 200
        history_payload = history.json()
        assert history_payload[0]["result_status"] == "completed"
        assert history_payload[0]["deleted_snapshot_ids"] == [stale.snapshot_id]


def test_admin_snapshot_cleanup_requires_destructive_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    keys_path = tmp_path / "admin_keys.json"
    payload = json.loads(keys_path.read_text(encoding="utf-8"))
    payload["keys"][0]["scopes"] = ["write:ingestion"]
    keys_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/snapshots:cleanup-preview",
            json={"product_id": "aspose.ocr"},
            headers={"x-api-key": "operator-token"},
        )
    assert response.status_code == 403
    assert (
        response.json()["detail"]["error"]["message"]
        == "Missing required scope: write:destructive."
    )
