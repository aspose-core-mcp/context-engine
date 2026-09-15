from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import adcs.ingestion.source_sync_orchestrator as source_sync_orchestrator
from adcs.ingestion.source_sync_orchestrator import (
    SourceSyncMode,
    SourceSyncOrchestrationService,
    SourceSyncStatus,
)


def test_source_sync_orchestrator_run_success_records_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "registry" / "sync_source_repos.py"
    service = SourceSyncOrchestrationService(
        workspace_root=workspace_root,
        sync_script_path=script_path,
        python_executable="python3",
    )

    expected_command = [
        "python3",
        str(script_path),
        "--mode",
        "validate",
        "--repo-id",
        "aspose.ocr.apiref",
    ]

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == expected_command
        assert cwd == workspace_root
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] done\n[info] validated\n",
            stderr="",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    operation = service.run(mode=SourceSyncMode.VALIDATE, repo_ids=("aspose.ocr.apiref",))

    assert operation.status is SourceSyncStatus.COMPLETED
    assert operation.mode is SourceSyncMode.VALIDATE
    assert operation.repo_ids == ("aspose.ocr.apiref",)
    assert operation.started_at is not None
    assert operation.finished_at is not None
    assert operation.finished_at >= operation.started_at
    assert [(line.stream, line.line) for line in operation.logs] == [
        ("stdout", "[ok] done"),
        ("stdout", "[info] validated"),
    ]
    assert service.get_operation(operation.operation_id) == operation


def test_source_sync_orchestrator_run_failure_records_failed_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "registry" / "sync_source_repos.py"
    service = SourceSyncOrchestrationService(
        workspace_root=workspace_root,
        sync_script_path=script_path,
        python_executable="python3",
    )

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert "--mode" in command
        assert cwd == workspace_root
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=2,
            stdout="",
            stderr="[error] update failed\n",
        )

    monkeypatch.setattr(source_sync_orchestrator.subprocess, "run", _fake_run)

    operation = service.run(mode=SourceSyncMode.UPDATE, repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceSyncStatus.FAILED
    assert operation.mode is SourceSyncMode.UPDATE
    assert operation.repo_ids == ("aspose.ocr.docs",)
    assert operation.started_at is not None
    assert operation.finished_at is not None
    assert operation.finished_at >= operation.started_at
    assert [(line.stream, line.line) for line in operation.logs] == [
        ("stderr", "[error] update failed")
    ]
