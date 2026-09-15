"""In-memory orchestration service for source repository sync operations."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from uuid import uuid4

from adcs.ingestion.operation_state_store import FileSystemOperationStateStore


class SourceSyncMode(StrEnum):
    """Supported source synchronization modes."""

    VALIDATE = "validate"
    SYNC = "sync"
    UPDATE = "update"


class SourceSyncStatus(StrEnum):
    """Operation execution status for source synchronization."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


class SourceSyncOperationNotFoundError(KeyError):
    """Raised when an operation id does not exist in in-memory storage."""


@dataclass(frozen=True, slots=True)
class SourceSyncLogLine:
    """Normalized sync operation log line."""

    stream: str
    line: str


@dataclass(frozen=True, slots=True)
class SourceSyncOperation:
    """Source sync operation record stored in memory."""

    operation_id: str
    status: SourceSyncStatus
    mode: SourceSyncMode
    repo_ids: tuple[str, ...]
    logs: tuple[SourceSyncLogLine, ...]
    started_at: datetime | None
    finished_at: datetime | None


class SourceSyncOrchestrationService:
    """Run source sync script operations and expose in-memory operation records."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        sync_script_path: str | Path | None = None,
        python_executable: str | None = None,
        operation_state_store: FileSystemOperationStateStore[SourceSyncOperation] | None = None,
    ) -> None:
        default_workspace_root = Path(__file__).resolve().parents[3]
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else default_workspace_root.resolve()
        )

        default_script_path = self._workspace_root / "scripts" / "sources" / "registry" / (
            "sync_source_repos.py"
        )
        self._sync_script_path = (
            Path(sync_script_path).resolve()
            if sync_script_path is not None
            else default_script_path.resolve()
        )
        self._python_executable = python_executable or sys.executable
        self._operation_state_store = operation_state_store or FileSystemOperationStateStore(
            namespace="source-sync",
            record_type=SourceSyncOperation,
            workspace_root=self._workspace_root,
        )

        self._lock = Lock()
        self._operations: dict[str, SourceSyncOperation] = {}
        self._operation_order: list[str] = []

    def run(
        self,
        *,
        mode: SourceSyncMode,
        repo_ids: Sequence[str] | None = None,
        execute_immediately: bool = True,
    ) -> SourceSyncOperation:
        """Execute one source sync operation and persist its result in memory."""
        normalized_repo_ids = _normalize_repo_ids(repo_ids)
        operation = SourceSyncOperation(
            operation_id=str(uuid4()),
            status=SourceSyncStatus.QUEUED,
            mode=mode,
            repo_ids=normalized_repo_ids,
            logs=(),
            started_at=None,
            finished_at=None,
        )
        self._save_operation(operation, append_new=True)
        if not execute_immediately:
            return operation
        return self.execute_operation(operation.operation_id)

    def execute_operation(self, operation_id: str) -> SourceSyncOperation:
        """Execute one queued source sync operation by id."""
        operation = self.get_operation(operation_id)
        if operation.status in {SourceSyncStatus.RUNNING, SourceSyncStatus.COMPLETED}:
            return operation

        operation = replace(
            operation,
            status=SourceSyncStatus.RUNNING,
            started_at=_now_utc(),
        )
        self._save_operation(operation)

        command = self._build_command(mode=operation.mode, repo_ids=operation.repo_ids)

        try:
            completed = self._run_command(command)
        except OSError as exc:
            failed_operation = replace(
                operation,
                status=SourceSyncStatus.FAILED,
                logs=(
                    SourceSyncLogLine(
                        stream="stderr",
                        line=f"[error] {exc.__class__.__name__}: {exc}",
                    ),
                ),
                finished_at=_now_utc(),
            )
            self._save_operation(failed_operation)
            return failed_operation

        logs = self._collect_logs(stdout=completed.stdout, stderr=completed.stderr)
        status = (
            SourceSyncStatus.COMPLETED
            if completed.returncode == 0
            else SourceSyncStatus.FAILED
        )
        if completed.returncode != 0 and not logs:
            logs = (
                SourceSyncLogLine(
                    stream="stderr",
                    line=f"[error] Process exited with code {completed.returncode}.",
                ),
            )

        finished_operation = replace(
            operation,
            status=status,
            logs=logs,
            finished_at=_now_utc(),
        )
        self._save_operation(finished_operation)
        return finished_operation

    def get_operation(self, operation_id: str) -> SourceSyncOperation:
        """Return one operation by id."""
        with self._lock:
            operation = self._operations.get(operation_id)
        persisted_state = self._operation_state_store.load(operation_id)
        if persisted_state is not None:
            self._save_operation(persisted_state, append_new=True)
            return persisted_state
        if operation is None:
            msg = f"Source sync operation `{operation_id}` was not found."
            raise SourceSyncOperationNotFoundError(msg)
        return operation

    def list_operations(self, *, limit: int = 20) -> tuple[SourceSyncOperation, ...]:
        """List recent operations ordered by most recent first."""
        if limit < 1:
            return ()

        with self._lock:
            operation_ids = list(reversed(self._operation_order[-limit:]))
            hydrated = [
                self._operations[operation_id] for operation_id in operation_ids
            ]
        results: list[SourceSyncOperation] = []
        seen_operation_ids: set[str] = set()
        for operation in self._operation_state_store.list(limit=limit):
            results.append(operation)
            seen_operation_ids.add(operation.operation_id)
            self._save_operation(operation, append_new=True)
            if len(results) >= limit:
                return tuple(results[:limit])
        for operation in hydrated:
            if operation.operation_id in seen_operation_ids:
                continue
            results.append(operation)
            seen_operation_ids.add(operation.operation_id)
            if len(results) >= limit:
                break
        return tuple(results[:limit])

    def _build_command(self, *, mode: SourceSyncMode, repo_ids: tuple[str, ...]) -> list[str]:
        command = [
            self._python_executable,
            str(self._sync_script_path),
            "--mode",
            mode.value,
        ]
        for repo_id in repo_ids:
            command.extend(["--repo-id", repo_id])
        return command

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self._workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _collect_logs(self, *, stdout: str, stderr: str) -> tuple[SourceSyncLogLine, ...]:
        log_lines: list[SourceSyncLogLine] = []

        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped:
                log_lines.append(SourceSyncLogLine(stream="stdout", line=stripped))

        for line in stderr.splitlines():
            stripped = line.strip()
            if stripped:
                log_lines.append(SourceSyncLogLine(stream="stderr", line=stripped))

        return tuple(log_lines)

    def _save_operation(self, operation: SourceSyncOperation, *, append_new: bool = False) -> None:
        with self._lock:
            if append_new and operation.operation_id not in self._operation_order:
                self._operation_order.append(operation.operation_id)
            self._operations[operation.operation_id] = operation
        self._operation_state_store.save(
            record_id=operation.operation_id,
            record=operation,
        )


def _normalize_repo_ids(repo_ids: Sequence[str] | None) -> tuple[str, ...]:
    if not repo_ids:
        return ()

    normalized_repo_ids: list[str] = []
    seen_repo_ids: set[str] = set()
    for raw_repo_id in repo_ids:
        repo_id = raw_repo_id.strip()
        if not repo_id:
            raise ValueError("repo_ids must not contain empty values.")
        if repo_id in seen_repo_ids:
            continue
        seen_repo_ids.add(repo_id)
        normalized_repo_ids.append(repo_id)

    return tuple(normalized_repo_ids)


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)
