from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api import admin_system
from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.ops import FileBackedBackupRestoreService

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_admin_system_session_returns_role_and_scope_context() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/system/session", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["key_id"] == "env-admin-key"
    assert payload["effective_role"] == "superuser"
    assert payload["is_superuser"] is True
    assert payload["source"] == "env"


def test_admin_system_health_returns_component_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_check_dependencies(
        *_: object,
        **__: object,
    ) -> admin_system.readiness.DependencyResults:
        return {
            "postgres": (True, "reachable"),
            "redis": (True, "reachable"),
            "qdrant": (False, "timeout"),
            "opensearch": (True, "reachable"),
        }

    monkeypatch.setattr(admin_system.readiness, "check_dependencies", _fake_check_dependencies)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/system/health", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["process"] == "ok"
    assert payload["dependencies"]["postgres"]["status"] == "ready"
    assert payload["dependencies"]["qdrant"]["status"] == "not_ready"
    assert payload["dependencies"]["qdrant"]["reason"] == "timeout"
    assert isinstance(payload["dependencies"]["qdrant"]["required"], bool)
    assert "qdrant" in payload["dependencies"]["qdrant"]["summary"].casefold()
    assert len(payload["dependencies"]["qdrant"]["fix_plan"]) >= 2


def test_admin_system_content_services_overview_returns_repo_health_rows() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/system/content-services", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_services"] >= 8
    assert payload["docs_services_total"] >= 4
    assert payload["apiref_services_total"] >= 4
    assert len(payload["services"]) == payload["total_services"]

    first = payload["services"][0]
    assert isinstance(first["repo_id"], str)
    assert first["source_kind"] in {"docs", "apiref"}
    assert first["service_status"] in {"healthy", "warning", "critical", "unknown"}
    assert first["indicator_color"] in {"green", "yellow", "red", "gray"}
    assert isinstance(first["service_status_summary"], str)
    assert isinstance(first["fix_plan"], list)


def test_admin_system_topology_policy_returns_runtime_profile() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/system/topology", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] in {"dev", "staging", "prod"}
    assert payload["persistence_backend"] in {"memory", "postgres"}
    assert payload["retrieval_backend"] in {"memory", "qdrant_opensearch"}
    assert payload["qdrant"]["shard_number"] >= 1
    assert payload["opensearch"]["number_of_shards"] >= 1
    assert isinstance(payload["summary"], str)


def test_admin_system_rejects_missing_api_key() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/system/session")

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_admin_backup_and_restore_endpoints(tmp_path: Path) -> None:
    app = create_app()
    app.state.backup_restore_service = FileBackedBackupRestoreService(
        workspace_root=tmp_path,
        state_root=tmp_path / "artifacts" / "dr",
    )
    source_dir = tmp_path / "artifacts" / "semantic-review"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "payload.txt").write_text("baseline", encoding="utf-8")

    with TestClient(app) as client:
        backup_response = client.post(
            "/admin/v1/system/backups:trigger",
            json={"scope": "full", "reason": "unit backup"},
            headers=ADMIN_HEADERS,
        )
        assert backup_response.status_code == 200
        backup_payload = backup_response.json()
        assert backup_payload["status"] == "completed"
        backup_id = backup_payload["backup_id"]
        assert isinstance(backup_id, str)
        assert backup_id.startswith("backup-")

        list_backups_response = client.get("/admin/v1/system/backups", headers=ADMIN_HEADERS)
        assert list_backups_response.status_code == 200
        backups_payload = list_backups_response.json()
        assert backups_payload
        assert backups_payload[0]["backup_id"] == backup_id

        (source_dir / "payload.txt").write_text("mutated", encoding="utf-8")

        restore_response = client.post(
            f"/admin/v1/system/backups/{backup_id}:restore",
            json={"validate_only": False, "reason": "unit restore"},
            headers=ADMIN_HEADERS,
        )
        assert restore_response.status_code == 200
        restore_payload = restore_response.json()
        assert restore_payload["status"] == "completed"
        assert (source_dir / "payload.txt").read_text(encoding="utf-8") == "baseline"

        operations_response = client.get(
            "/admin/v1/system/backup-operations",
            headers=ADMIN_HEADERS,
        )
        assert operations_response.status_code == 200
        operations_payload = operations_response.json()
        assert len(operations_payload) >= 2
        assert {item["operation_type"] for item in operations_payload}.issuperset(
            {"backup", "restore"}
        )


def test_admin_dr_recovery_smoke_endpoint(tmp_path: Path) -> None:
    app = create_app()
    app.state.backup_restore_service = FileBackedBackupRestoreService(
        workspace_root=tmp_path,
        state_root=tmp_path / "artifacts" / "dr",
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/system/dr:recovery-smoke",
            json={"reason": "unit dr smoke"},
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "passed"
    assert payload["backup_operation_id"]
    assert payload["restore_operation_id"]
