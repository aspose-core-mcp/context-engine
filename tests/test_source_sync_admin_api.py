from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import adcs.ingestion.source_sync_orchestrator as source_sync_orchestrator
from adcs.api.main import create_app
from adcs.config import clear_settings_cache

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_source_sync_api_triggers_validate_sync_update_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_commands: list[list[str]] = []

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        assert cwd.exists()
        assert capture_output is True
        assert text is True
        assert check is False

        mode = command[command.index("--mode") + 1]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=f"[ok] Mode `{mode}` completed\n",
            stderr="",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        for mode in ("validate", "sync", "update"):
            response = client.post(
                "/admin/v1/source-repositories/sync",
                json={"mode": mode},
                headers=ADMIN_HEADERS,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == mode
            assert body["status"] == "completed"
            assert body["repo_ids"] == []
            assert body["started_at"] is not None
            assert body["finished_at"] is not None
            assert body["logs"]

    assert len(seen_commands) == 3


def test_source_sync_api_supports_single_repo_id_and_status_log_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_command: list[str] = []

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, capture_output, text, check
        captured_command[:] = command
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] selected repo\n",
            stderr="",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        trigger_response = client.post(
            "/admin/v1/source-repositories/sync",
            json={"mode": "validate", "repo_id": "aspose.ocr.apiref"},
            headers=ADMIN_HEADERS,
        )

        assert trigger_response.status_code == 200
        trigger_body = trigger_response.json()
        assert trigger_body["repo_ids"] == ["aspose.ocr.apiref"]
        assert "--repo-id" in captured_command
        assert "aspose.ocr.apiref" in captured_command

        operation_id = trigger_body["operation_id"]
        fetch_response = client.get(
            f"/admin/v1/source-repositories/sync/{operation_id}",
            headers=ADMIN_HEADERS,
        )

        assert fetch_response.status_code == 200
        fetch_body = fetch_response.json()
        assert fetch_body["operation_id"] == operation_id
        assert fetch_body["status"] == "completed"
        assert fetch_body["logs"] == trigger_body["logs"]


def test_source_sync_api_returns_failed_status_for_failed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, capture_output, text, check
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="[error] simulated failure\n",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        trigger_response = client.post(
            "/admin/v1/source-repositories/sync",
            json={"mode": "sync", "repo_ids": ["aspose.ocr.apiref"]},
            headers=ADMIN_HEADERS,
        )

        assert trigger_response.status_code == 200
        trigger_body = trigger_response.json()
        assert trigger_body["status"] == "failed"
        assert any(
            log["stream"] == "stderr" and "simulated failure" in log["line"]
            for log in trigger_body["logs"]
        )

        operation_id = trigger_body["operation_id"]
        fetch_response = client.get(
            f"/admin/v1/source-repositories/sync/{operation_id}",
            headers=ADMIN_HEADERS,
        )
        assert fetch_response.status_code == 200
        assert fetch_response.json()["status"] == "failed"
