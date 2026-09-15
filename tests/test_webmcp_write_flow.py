from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.indexing import IngestionRunMode
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationStatus,
)


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
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion"],
                    },
                    {
                        "key_id": "foreign-owner-key",
                        "token": "foreign-owner-token",
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
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def _patch_ingestion_run(app: object) -> None:
    orchestrator = app.state.source_hugo_normalization_orchestrator
    counter = {"value": 0}

    def _run(
        *,
        repo_ids: tuple[str, ...] | None = None,
        mode: IngestionRunMode = IngestionRunMode.PUBLISH,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        **_: object,
    ) -> SourceHugoNormalizationOperation:
        counter["value"] += 1
        now = datetime.now(tz=UTC)
        return SourceHugoNormalizationOperation(
            operation_id=f"op-{counter['value']:04d}",
            status=SourceHugoNormalizationStatus.COMPLETED,
            repo_ids=tuple(repo_ids or ()),
            logs=(),
            results=(),
            started_at=now,
            finished_at=now,
            mode=IngestionRunMode.VALIDATE_ONLY if dry_run else mode,
            requested_mode=mode,
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    orchestrator.run = _run  # type: ignore[method-assign]


def test_webmcp_write_requires_confirmation_and_logs_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        response = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={"repo_ids": ["aspose.ocr.docs"], "reason": "manual operation"},
            headers={"x-api-key": "owner-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error"]["code"] == "CONFIRMATION_REQUIRED"

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?limit=5",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        payload = audit.json()
        assert payload[0]["tool_name"] == "web_trigger_reindex"
        assert payload[0]["status"] == "rejected"
        assert payload[0]["error_code"] == "CONFIRMATION_REQUIRED"


def test_webmcp_trigger_ingestion_happy_path_with_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        confirmation = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "publish docs update",
                "intent": {"repo_ids": ["aspose.ocr.docs"], "dry_run": False},
            },
            headers={"x-api-key": "owner-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        response = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_ids": ["aspose.ocr.docs"],
                "reason": "publish docs update",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["tool_name"] == "web_trigger_ingestion"
        assert payload["status"] == "completed"
        assert payload["operation_id"] == "op-0001"
        assert payload["repo_ids"] == ["aspose.ocr.docs"]

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_ingestion&limit=5",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        assert audit.json()[0]["status"] == "succeeded"


def test_webmcp_write_replay_guard_and_audit_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        confirmation = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_reindex",
                "reason": "owner-approved",
                "intent": {
                    "repo_ids": ["aspose.ocr.docs"],
                    "force_full_reindex": True,
                },
            },
            headers={"x-api-key": "owner-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        first = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={
                "repo_ids": ["aspose.ocr.docs"],
                "reason": "owner-approved",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert first.status_code == 200
        assert first.json()["operation_id"] == "op-0001"

        replay = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={
                "repo_ids": ["aspose.ocr.docs"],
                "reason": "owner-approved",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert replay.status_code == 409
        assert replay.json()["detail"]["error"]["code"] == "CONFIRMATION_REPLAYED"

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_reindex&limit=10",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        payload = audit.json()
        statuses = [item["status"] for item in payload]
        assert "succeeded" in statuses
        assert "rejected" in statuses


def test_webmcp_write_scope_enforced_and_audited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        confirmation = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_reindex",
                "reason": "foreign-owner-attempt",
                "intent": {
                    "repo_ids": ["aspose.ocr.docs"],
                    "force_full_reindex": True,
                },
            },
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        forbidden = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={
                "repo_ids": ["aspose.ocr.docs"],
                "reason": "foreign-owner-attempt",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["error"]["code"] == "FORBIDDEN"

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_reindex&limit=5",
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert audit.status_code == 200
        assert audit.json()[0]["status"] == "forbidden"
        assert audit.json()[0]["error_code"] == "FORBIDDEN"


def test_webmcp_write_rejects_missing_repo_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        response = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={"reason": "explicit target is required"},
            headers={"x-api-key": "owner-token"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error"]["code"] == "VALIDATION_ERROR"

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_reindex&limit=5",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        assert audit.json()[0]["status"] == "rejected"
        assert audit.json()[0]["error_code"] == "VALIDATION_ERROR"


def test_webmcp_write_422_body_validation_is_audited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    _patch_ingestion_run(app)

    with TestClient(app) as client:
        invalid = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={"repo_ids": "aspose.ocr.docs", "reason": "invalid payload type"},
            headers={"x-api-key": "owner-token"},
        )
        assert invalid.status_code == 400

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_reindex&limit=5",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        payload = audit.json()
        assert payload[0]["status"] == "rejected"
        assert payload[0]["error_code"] == "VALIDATION_ERROR"
        assert payload[0]["actor_key_id"] == "owner-key"


def test_webmcp_promote_snapshot_with_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    snapshot = app.state.snapshot_registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=123,
    )

    with TestClient(app) as client:
        confirmation = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_promote_snapshot",
                "reason": "promote verified snapshot",
                "intent": {"snapshot_id": snapshot.snapshot_id},
            },
            headers={"x-api-key": "owner-token"},
        )
        assert confirmation.status_code == 200
        confirm_token = confirmation.json()["confirm_token"]

        promote = client.post(
            "/webmcp/v1/tools/web_promote_snapshot",
            json={
                "snapshot_id": snapshot.snapshot_id,
                "reason": "promote verified snapshot",
                "confirm_token": confirm_token,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert promote.status_code == 200
        payload = promote.json()
        assert payload["snapshot_id"] == snapshot.snapshot_id
        assert payload["status"] == "completed"

        audit = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_promote_snapshot&limit=5",
            headers={"x-api-key": "owner-token"},
        )
        assert audit.status_code == 200
        assert audit.json()[0]["status"] == "succeeded"
