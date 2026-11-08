from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import adcs.ingestion.source_sync_orchestrator as source_sync_orchestrator
from adcs.api.main import create_app
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_admin_keys(path: Path) -> None:
    path.write_text(
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
                    {
                        "key_id": "disabled-key",
                        "token": "disabled-token",
                        "is_superuser": False,
                        "enabled": False,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion"],
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _configure_json_dev_keys(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    keys_path = tmp_path / "admin_keys.json"
    _write_admin_keys(keys_path)
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def test_admin_api_rejects_missing_and_invalid_key() -> None:
    app = create_app()
    with TestClient(app) as client:
        missing_key = client.get("/admin/v1/source-repositories/sync")
        assert missing_key.status_code == 401
        assert missing_key.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

        invalid_key = client.get(
            "/admin/v1/source-repositories/sync",
            headers={"x-api-key": "not-valid"},
        )
        assert invalid_key.status_code == 401
        assert invalid_key.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_admin_api_accepts_read_only_requests_for_any_valid_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/admin/v1/source-repositories/sync",
            headers={"x-api-key": "viewer-token"},
        )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_api_rejects_disabled_key_for_read_only_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/admin/v1/source-repositories/sync",
            headers={"x-api-key": "disabled-token"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_admin_api_enforces_write_scope_and_product_scope_for_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, text, check
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] validate completed\n",
            stderr="",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        missing_scope = client.post(
            "/admin/v1/source-repositories/sync",
            json={"mode": "validate", "repo_id": "aspose.ocr.apiref"},
            headers={"x-api-key": "viewer-token"},
        )
        assert missing_scope.status_code == 403
        assert "Missing required scope" in missing_scope.json()["detail"]["error"]["message"]

        product_scope_violation = client.post(
            "/admin/v1/source-repositories/sync",
            json={"mode": "validate", "repo_id": "aspose.ocr.apiref"},
            headers={"x-api-key": "foreign-operator-token"},
        )
        assert product_scope_violation.status_code == 403
        assert "Product scope violation" in product_scope_violation.json()["detail"]["error"][
            "message"
        ]

        allowed = client.post(
            "/admin/v1/source-repositories/sync",
            json={"mode": "validate", "repo_id": "aspose.ocr.apiref"},
            headers={"x-api-key": "operator-token"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "completed"
