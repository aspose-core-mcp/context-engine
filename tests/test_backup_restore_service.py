from __future__ import annotations

from pathlib import Path

from adcs.ops import (
    BackupOperationStatus,
    DRSmokeStatus,
    FileBackedBackupRestoreService,
)


def _build_service(tmp_path: Path) -> FileBackedBackupRestoreService:
    return FileBackedBackupRestoreService(
        workspace_root=tmp_path,
        state_root=tmp_path / "artifacts" / "dr",
    )


def test_backup_restore_roundtrip_restores_artifact_content(tmp_path: Path) -> None:
    target_dir = tmp_path / "artifacts" / "semantic-review"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "payload.txt"
    target_file.write_text("baseline", encoding="utf-8")

    service = _build_service(tmp_path)
    backup_operation = service.trigger_backup(
        scope="full",
        product_id=None,
        reason="unit backup",
        requested_by="tester",
        request_id="req-1",
    )
    assert backup_operation.status is BackupOperationStatus.COMPLETED
    assert backup_operation.backup_id is not None

    target_file.write_text("mutated", encoding="utf-8")

    restore_operation = service.trigger_restore(
        backup_id=str(backup_operation.backup_id),
        validate_only=False,
        reason="unit restore",
        requested_by="tester",
        request_id="req-2",
    )
    assert restore_operation.status is BackupOperationStatus.COMPLETED
    assert target_file.read_text(encoding="utf-8") == "baseline"
    assert restore_operation.restored_files_count >= 1


def test_validate_only_restore_keeps_workspace_unchanged(tmp_path: Path) -> None:
    target_dir = tmp_path / "artifacts" / "semantic-review"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "payload.txt"
    target_file.write_text("baseline", encoding="utf-8")

    service = _build_service(tmp_path)
    backup_operation = service.trigger_backup(
        scope="full",
        product_id=None,
        reason="unit backup",
        requested_by="tester",
        request_id="req-1",
    )
    assert backup_operation.backup_id is not None

    target_file.write_text("mutated", encoding="utf-8")

    restore_operation = service.trigger_restore(
        backup_id=str(backup_operation.backup_id),
        validate_only=True,
        reason="unit restore validate",
        requested_by="tester",
        request_id="req-2",
    )
    assert restore_operation.status is BackupOperationStatus.COMPLETED
    assert restore_operation.validate_only is True
    assert target_file.read_text(encoding="utf-8") == "mutated"


def test_dr_recovery_smoke_passes(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    result = service.run_recovery_smoke(
        requested_by="tester",
        request_id="req-smoke",
        reason="unit dr smoke",
    )

    assert result.status is DRSmokeStatus.PASSED
    assert result.backup_operation_id is not None
    assert result.restore_operation_id is not None
    assert result.backup_id is not None
