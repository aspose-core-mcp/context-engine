"""Backup/restore operational service with DR smoke workflow."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, runtime_checkable


class BackupOperationStatus(StrEnum):
    """Lifecycle states for backup/restore operations."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


class BackupOperationType(StrEnum):
    """Operation type for one backup pipeline record."""

    BACKUP = "backup"
    RESTORE = "restore"


class DRSmokeStatus(StrEnum):
    """DR smoke status."""

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """One stored backup snapshot manifest entry."""

    backup_id: str
    scope: str
    product_id: str | None
    created_at: datetime
    snapshot_root: str
    manifest_path: str
    included_paths: tuple[str, ...]
    copied_files_count: int
    external_components: dict[str, str]


@dataclass(frozen=True, slots=True)
class BackupOperationRecord:
    """One backup/restore operation status record."""

    operation_id: str
    operation_type: BackupOperationType
    status: BackupOperationStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    requested_by: str | None
    request_id: str | None
    reason: str | None
    scope: str
    product_id: str | None
    backup_id: str | None
    target_backup_id: str | None
    validate_only: bool
    error_reason: str | None
    restored_files_count: int
    logs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DRSmokeResult:
    """DR smoke execution result."""

    status: DRSmokeStatus
    backup_operation_id: str | None
    restore_operation_id: str | None
    backup_id: str | None
    details: str


@runtime_checkable
class BackupRestoreService(Protocol):
    """Contract for backup/restore orchestration."""

    def trigger_backup(
        self,
        *,
        scope: str,
        product_id: str | None,
        reason: str | None,
        requested_by: str | None,
        request_id: str | None,
    ) -> BackupOperationRecord:
        """Create one backup operation and return final status."""

    def trigger_restore(
        self,
        *,
        backup_id: str,
        validate_only: bool,
        reason: str | None,
        requested_by: str | None,
        request_id: str | None,
    ) -> BackupOperationRecord:
        """Create one restore operation and return final status."""

    def get_operation(self, operation_id: str) -> BackupOperationRecord | None:
        """Return operation by id."""

    def list_operations(self, *, limit: int = 100) -> tuple[BackupOperationRecord, ...]:
        """List operations newest-first."""

    def get_backup(self, backup_id: str) -> BackupRecord | None:
        """Return backup by id."""

    def list_backups(self, *, limit: int = 100) -> tuple[BackupRecord, ...]:
        """List backups newest-first."""

    def run_recovery_smoke(
        self,
        *,
        requested_by: str | None,
        request_id: str | None,
        reason: str | None,
    ) -> DRSmokeResult:
        """Run deterministic backup->restore smoke workflow."""


class FileBackedBackupRestoreService:
    """File-backed backup/restore orchestration with workspace guardrails."""

    _DEFAULT_INCLUDE_PATHS = (
        "artifacts/config-history",
        "artifacts/semantic-review",
        "reports/quality-gates",
    )

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self._workspace_root = (
            workspace_root.resolve()
            if workspace_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self._state_root = (
            state_root.resolve()
            if state_root is not None
            else (self._workspace_root / "artifacts" / "dr").resolve()
        )
        self._operations_file = self._state_root / "operations.json"
        self._backups_file = self._state_root / "backups.json"
        self._backups_dir = self._state_root / "backups"
        self._restores_dir = self._state_root / "restores"
        self._lock = Lock()
        self._operations: dict[str, BackupOperationRecord] = {}
        self._backups: dict[str, BackupRecord] = {}
        self._operation_counter = 0
        self._backup_counter = 0

        self._state_root.mkdir(parents=True, exist_ok=True)
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        self._restores_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def trigger_backup(
        self,
        *,
        scope: str,
        product_id: str | None,
        reason: str | None,
        requested_by: str | None,
        request_id: str | None,
    ) -> BackupOperationRecord:
        operation = self._new_operation(
            operation_type=BackupOperationType.BACKUP,
            scope=scope,
            product_id=product_id,
            reason=reason,
            requested_by=requested_by,
            request_id=request_id,
            backup_id=None,
            target_backup_id=None,
            validate_only=False,
        )
        operation = self._update_operation(
            operation_id=operation.operation_id,
            status=BackupOperationStatus.RUNNING,
            append_log="backup pipeline started",
            started_at=datetime.now(tz=UTC),
        )
        try:
            backup = self._create_backup(scope=scope, product_id=product_id)
        except Exception as exc:  # pragma: no cover - defensive
            operation = self._update_operation(
                operation_id=operation.operation_id,
                status=BackupOperationStatus.FAILED,
                append_log=f"backup failed: {exc}",
                finished_at=datetime.now(tz=UTC),
                error_reason=str(exc),
            )
            return operation

        operation = self._update_operation(
            operation_id=operation.operation_id,
            status=BackupOperationStatus.COMPLETED,
            append_log=f"backup completed: {backup.backup_id}",
            finished_at=datetime.now(tz=UTC),
            backup_id=backup.backup_id,
        )
        return operation

    def trigger_restore(
        self,
        *,
        backup_id: str,
        validate_only: bool,
        reason: str | None,
        requested_by: str | None,
        request_id: str | None,
    ) -> BackupOperationRecord:
        operation = self._new_operation(
            operation_type=BackupOperationType.RESTORE,
            scope="full",
            product_id=None,
            reason=reason,
            requested_by=requested_by,
            request_id=request_id,
            backup_id=None,
            target_backup_id=backup_id,
            validate_only=validate_only,
        )
        operation = self._update_operation(
            operation_id=operation.operation_id,
            status=BackupOperationStatus.RUNNING,
            append_log=f"restore pipeline started: {backup_id}",
            started_at=datetime.now(tz=UTC),
        )

        backup = self.get_backup(backup_id)
        if backup is None:
            return self._update_operation(
                operation_id=operation.operation_id,
                status=BackupOperationStatus.FAILED,
                append_log=f"backup not found: {backup_id}",
                finished_at=datetime.now(tz=UTC),
                error_reason="backup_not_found",
            )

        try:
            restored_files_count = self._restore_backup(
                backup=backup,
                validate_only=validate_only,
                operation_id=operation.operation_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self._update_operation(
                operation_id=operation.operation_id,
                status=BackupOperationStatus.FAILED,
                append_log=f"restore failed: {exc}",
                finished_at=datetime.now(tz=UTC),
                error_reason=str(exc),
            )

        mode_note = "validate-only" if validate_only else "applied"
        return self._update_operation(
            operation_id=operation.operation_id,
            status=BackupOperationStatus.COMPLETED,
            append_log=f"restore completed ({mode_note})",
            finished_at=datetime.now(tz=UTC),
            backup_id=backup.backup_id,
            restored_files_count=restored_files_count,
        )

    def get_operation(self, operation_id: str) -> BackupOperationRecord | None:
        with self._lock:
            return self._operations.get(operation_id)

    def list_operations(self, *, limit: int = 100) -> tuple[BackupOperationRecord, ...]:
        normalized_limit = max(1, min(limit, 1000))
        with self._lock:
            ordered = sorted(
                self._operations.values(),
                key=lambda item: (item.created_at, item.operation_id),
                reverse=True,
            )
        return tuple(ordered[:normalized_limit])

    def get_backup(self, backup_id: str) -> BackupRecord | None:
        with self._lock:
            return self._backups.get(backup_id)

    def list_backups(self, *, limit: int = 100) -> tuple[BackupRecord, ...]:
        normalized_limit = max(1, min(limit, 1000))
        with self._lock:
            ordered = sorted(
                self._backups.values(),
                key=lambda item: (item.created_at, item.backup_id),
                reverse=True,
            )
        return tuple(ordered[:normalized_limit])

    def run_recovery_smoke(
        self,
        *,
        requested_by: str | None,
        request_id: str | None,
        reason: str | None,
    ) -> DRSmokeResult:
        sentinel_relative_path = Path("artifacts") / "semantic-review" / "smoke-sentinel.txt"
        sentinel_path = (self._workspace_root / sentinel_relative_path).resolve()
        self._assert_within_workspace(sentinel_path)
        sentinel_path.parent.mkdir(parents=True, exist_ok=True)

        baseline_content = f"dr-smoke-baseline-{datetime.now(tz=UTC).isoformat()}"
        sentinel_path.write_text(baseline_content, encoding="utf-8")

        backup_operation = self.trigger_backup(
            scope="full",
            product_id=None,
            reason=reason or "dr_smoke_backup",
            requested_by=requested_by,
            request_id=request_id,
        )
        if backup_operation.status is not BackupOperationStatus.COMPLETED:
            return DRSmokeResult(
                status=DRSmokeStatus.FAILED,
                backup_operation_id=backup_operation.operation_id,
                restore_operation_id=None,
                backup_id=backup_operation.backup_id,
                details="Backup stage failed.",
            )

        sentinel_path.write_text("dr-smoke-mutated", encoding="utf-8")

        restore_operation = self.trigger_restore(
            backup_id=str(backup_operation.backup_id),
            validate_only=False,
            reason=reason or "dr_smoke_restore",
            requested_by=requested_by,
            request_id=request_id,
        )
        if restore_operation.status is not BackupOperationStatus.COMPLETED:
            return DRSmokeResult(
                status=DRSmokeStatus.FAILED,
                backup_operation_id=backup_operation.operation_id,
                restore_operation_id=restore_operation.operation_id,
                backup_id=backup_operation.backup_id,
                details="Restore stage failed.",
            )

        restored_content = sentinel_path.read_text(encoding="utf-8")
        if restored_content != baseline_content:
            return DRSmokeResult(
                status=DRSmokeStatus.FAILED,
                backup_operation_id=backup_operation.operation_id,
                restore_operation_id=restore_operation.operation_id,
                backup_id=backup_operation.backup_id,
                details="Sentinel content mismatch after restore.",
            )

        return DRSmokeResult(
            status=DRSmokeStatus.PASSED,
            backup_operation_id=backup_operation.operation_id,
            restore_operation_id=restore_operation.operation_id,
            backup_id=backup_operation.backup_id,
            details="Backup and restore smoke stages passed.",
        )

    def _create_backup(self, *, scope: str, product_id: str | None) -> BackupRecord:
        now = datetime.now(tz=UTC)
        backup_id = self._next_backup_id()
        backup_root = (self._backups_dir / backup_id).resolve()
        snapshot_root = backup_root / "snapshot"
        manifest_path = backup_root / "manifest.json"
        self._assert_within_workspace(backup_root)
        backup_root.mkdir(parents=True, exist_ok=False)
        snapshot_root.mkdir(parents=True, exist_ok=False)

        copied_files_count = 0
        included_paths: list[str] = []

        for relative_path in self._DEFAULT_INCLUDE_PATHS:
            source_path = (self._workspace_root / relative_path).resolve()
            if not source_path.exists():
                continue
            self._assert_within_workspace(source_path)
            destination_path = (snapshot_root / relative_path).resolve()
            self._assert_within_workspace(destination_path)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.is_dir():
                shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
                copied_files_count += sum(
                    1 for item in destination_path.rglob("*") if item.is_file()
                )
            elif source_path.is_file():
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination_path)
                copied_files_count += 1
            included_paths.append(relative_path)

        external_components = {
            "postgres": "requires_pitr_or_pg_dump",
            "qdrant": "requires_qdrant_snapshot_api",
            "opensearch": "requires_opensearch_snapshot_repository",
        }

        backup = BackupRecord(
            backup_id=backup_id,
            scope=scope,
            product_id=product_id,
            created_at=now,
            snapshot_root=str(snapshot_root),
            manifest_path=str(manifest_path),
            included_paths=tuple(included_paths),
            copied_files_count=copied_files_count,
            external_components=external_components,
        )
        manifest_payload = {
            "backup_id": backup.backup_id,
            "scope": backup.scope,
            "product_id": backup.product_id,
            "created_at": backup.created_at.isoformat(),
            "snapshot_root": backup.snapshot_root,
            "manifest_path": backup.manifest_path,
            "included_paths": list(backup.included_paths),
            "copied_files_count": backup.copied_files_count,
            "external_components": dict(backup.external_components),
        }
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        with self._lock:
            self._backups[backup.backup_id] = backup
            self._save_state_locked()
        return backup

    def _restore_backup(
        self,
        *,
        backup: BackupRecord,
        validate_only: bool,
        operation_id: str,
    ) -> int:
        snapshot_root = Path(backup.snapshot_root).resolve()
        self._assert_within_workspace(snapshot_root)
        if not snapshot_root.exists() or not snapshot_root.is_dir():
            msg = f"Snapshot root missing for backup `{backup.backup_id}`."
            raise FileNotFoundError(msg)

        restored_files_count = 0
        for relative_path in backup.included_paths:
            source_path = (snapshot_root / relative_path).resolve()
            self._assert_within_workspace(source_path)
            if not source_path.exists():
                continue
            target_path = (self._workspace_root / relative_path).resolve()
            self._assert_within_workspace(target_path)
            if source_path.is_dir():
                restored_files_count += sum(1 for item in source_path.rglob("*") if item.is_file())
                if not validate_only:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            elif source_path.is_file():
                restored_files_count += 1
                if not validate_only:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, target_path)

        restore_report = {
            "operation_id": operation_id,
            "backup_id": backup.backup_id,
            "validate_only": validate_only,
            "restored_files_count": restored_files_count,
            "completed_at": datetime.now(tz=UTC).isoformat(),
        }
        report_path = (self._restores_dir / f"{operation_id}.json").resolve()
        self._assert_within_workspace(report_path)
        report_path.write_text(
            json.dumps(restore_report, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return restored_files_count

    def _new_operation(
        self,
        *,
        operation_type: BackupOperationType,
        scope: str,
        product_id: str | None,
        reason: str | None,
        requested_by: str | None,
        request_id: str | None,
        backup_id: str | None,
        target_backup_id: str | None,
        validate_only: bool,
    ) -> BackupOperationRecord:
        now = datetime.now(tz=UTC)
        operation = BackupOperationRecord(
            operation_id=self._next_operation_id(),
            operation_type=operation_type,
            status=BackupOperationStatus.QUEUED,
            created_at=now,
            started_at=None,
            finished_at=None,
            requested_by=_normalize_optional_string(requested_by),
            request_id=_normalize_optional_string(request_id),
            reason=_normalize_optional_string(reason),
            scope=_normalize_scope(scope),
            product_id=_normalize_optional_string(product_id),
            backup_id=backup_id,
            target_backup_id=target_backup_id,
            validate_only=validate_only,
            error_reason=None,
            restored_files_count=0,
            logs=("operation queued",),
        )
        with self._lock:
            self._operations[operation.operation_id] = operation
            self._save_state_locked()
        return operation

    def _update_operation(
        self,
        *,
        operation_id: str,
        status: BackupOperationStatus,
        append_log: str | None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        backup_id: str | None = None,
        error_reason: str | None = None,
        restored_files_count: int | None = None,
    ) -> BackupOperationRecord:
        with self._lock:
            current = self._operations[operation_id]
            logs = list(current.logs)
            if append_log is not None:
                logs.append(append_log)
            updated = replace(
                current,
                status=status,
                started_at=started_at if started_at is not None else current.started_at,
                finished_at=finished_at if finished_at is not None else current.finished_at,
                backup_id=backup_id if backup_id is not None else current.backup_id,
                error_reason=error_reason,
                restored_files_count=(
                    restored_files_count
                    if restored_files_count is not None
                    else current.restored_files_count
                ),
                logs=tuple(logs),
            )
            self._operations[operation_id] = updated
            self._save_state_locked()
            return updated

    def _load_state(self) -> None:
        operations_payload = _read_json_file(self._operations_file)
        backups_payload = _read_json_file(self._backups_file)

        if isinstance(operations_payload, list):
            for item in operations_payload:
                if not isinstance(item, dict):
                    continue
                operation = _deserialize_operation(item)
                if operation is None:
                    continue
                self._operations[operation.operation_id] = operation
                self._operation_counter = max(
                    self._operation_counter,
                    _extract_numeric_tail(operation.operation_id),
                )

        if isinstance(backups_payload, list):
            for item in backups_payload:
                if not isinstance(item, dict):
                    continue
                backup = _deserialize_backup(item)
                if backup is None:
                    continue
                self._backups[backup.backup_id] = backup
                self._backup_counter = max(
                    self._backup_counter,
                    _extract_numeric_tail(backup.backup_id),
                )

    def _save_state_locked(self) -> None:
        operations_payload = [
            _serialize_operation(item)
            for item in sorted(
                self._operations.values(), key=lambda value: (value.created_at, value.operation_id)
            )
        ]
        backups_payload = [
            _serialize_backup(item)
            for item in sorted(
                self._backups.values(),
                key=lambda value: (value.created_at, value.backup_id),
            )
        ]
        self._operations_file.write_text(
            json.dumps(operations_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self._backups_file.write_text(
            json.dumps(backups_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def _next_operation_id(self) -> str:
        with self._lock:
            self._operation_counter += 1
            return f"bkop-{self._operation_counter:08d}"

    def _next_backup_id(self) -> str:
        with self._lock:
            self._backup_counter += 1
            return f"backup-{self._backup_counter:08d}"

    def _assert_within_workspace(self, path: Path) -> None:
        resolved = path.resolve()
        if self._workspace_root == resolved:
            return
        if self._workspace_root not in resolved.parents:
            msg = f"Path escapes workspace root: {resolved.as_posix()}"
            raise ValueError(msg)


def _normalize_scope(scope: str) -> str:
    normalized = scope.strip().casefold() if isinstance(scope, str) else "full"
    if not normalized:
        return "full"
    if normalized not in {"full", "product", "analytics"}:
        return "full"
    return normalized


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _extract_numeric_tail(identifier: str) -> int:
    parts = identifier.rsplit("-", 1)
    if len(parts) != 2:
        return 0
    tail = parts[1]
    return int(tail) if tail.isdigit() else 0


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _serialize_operation(operation: BackupOperationRecord) -> dict[str, Any]:
    payload = asdict(operation)
    payload["operation_type"] = operation.operation_type.value
    payload["status"] = operation.status.value
    payload["created_at"] = operation.created_at.isoformat()
    payload["started_at"] = operation.started_at.isoformat() if operation.started_at else None
    payload["finished_at"] = operation.finished_at.isoformat() if operation.finished_at else None
    payload["logs"] = list(operation.logs)
    return payload


def _deserialize_operation(payload: dict[str, Any]) -> BackupOperationRecord | None:
    try:
        return BackupOperationRecord(
            operation_id=str(payload.get("operation_id", "")).strip(),
            operation_type=BackupOperationType(str(payload.get("operation_type", "backup"))),
            status=BackupOperationStatus(str(payload.get("status", "queued"))),
            created_at=_parse_datetime(payload.get("created_at")),
            started_at=_parse_optional_datetime(payload.get("started_at")),
            finished_at=_parse_optional_datetime(payload.get("finished_at")),
            requested_by=_normalize_optional_string(_as_optional_str(payload.get("requested_by"))),
            request_id=_normalize_optional_string(_as_optional_str(payload.get("request_id"))),
            reason=_normalize_optional_string(_as_optional_str(payload.get("reason"))),
            scope=_normalize_scope(str(payload.get("scope", "full"))),
            product_id=_normalize_optional_string(_as_optional_str(payload.get("product_id"))),
            backup_id=_normalize_optional_string(_as_optional_str(payload.get("backup_id"))),
            target_backup_id=_normalize_optional_string(
                _as_optional_str(payload.get("target_backup_id"))
            ),
            validate_only=bool(payload.get("validate_only", False)),
            error_reason=_normalize_optional_string(_as_optional_str(payload.get("error_reason"))),
            restored_files_count=int(payload.get("restored_files_count", 0)),
            logs=tuple(str(item) for item in payload.get("logs", []) if str(item)),
        )
    except (ValueError, TypeError):
        return None


def _serialize_backup(backup: BackupRecord) -> dict[str, Any]:
    payload = asdict(backup)
    payload["created_at"] = backup.created_at.isoformat()
    payload["included_paths"] = list(backup.included_paths)
    payload["external_components"] = dict(backup.external_components)
    return payload


def _deserialize_backup(payload: dict[str, Any]) -> BackupRecord | None:
    try:
        included_paths = payload.get("included_paths", [])
        if not isinstance(included_paths, list):
            return None
        external = payload.get("external_components", {})
        if not isinstance(external, dict):
            return None
        return BackupRecord(
            backup_id=str(payload.get("backup_id", "")).strip(),
            scope=_normalize_scope(str(payload.get("scope", "full"))),
            product_id=_normalize_optional_string(_as_optional_str(payload.get("product_id"))),
            created_at=_parse_datetime(payload.get("created_at")),
            snapshot_root=str(payload.get("snapshot_root", "")).strip(),
            manifest_path=str(payload.get("manifest_path", "")).strip(),
            included_paths=tuple(str(item).strip() for item in included_paths if str(item).strip()),
            copied_files_count=int(payload.get("copied_files_count", 0)),
            external_components={
                str(key): str(value) for key, value in external.items() if str(key).strip()
            },
        )
    except (ValueError, TypeError):
        return None


def _parse_datetime(raw_value: object) -> datetime:
    if isinstance(raw_value, str):
        return datetime.fromisoformat(raw_value)
    msg = "Invalid datetime payload."
    raise ValueError(msg)


def _parse_optional_datetime(raw_value: object) -> datetime | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str) and raw_value:
        return datetime.fromisoformat(raw_value)
    return None


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
