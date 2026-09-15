"""Snapshot rollback audit trail contracts and adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, create_engine, text


class SnapshotRollbackResultStatus(StrEnum):
    """Execution status for one rollback audit record."""

    COMPLETED = "completed"
    PREFLIGHT_FAILED = "preflight_failed"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SnapshotRollbackAuditRecord:
    """One auditable runtime snapshot rollback operation."""

    audit_id: str
    operation_id: str
    result_status: SnapshotRollbackResultStatus
    actor_key_id: str
    request_id: str | None
    reason: str
    product_id: str
    programming_language: str
    version: str
    target_snapshot_id: str
    active_snapshot_before_id: str | None
    active_snapshot_after_id: str | None
    diagnostics: dict[str, object]
    created_at: datetime


@runtime_checkable
class SnapshotRollbackAuditStore(Protocol):
    """Contract for rollback audit persistence."""

    def record(
        self,
        *,
        operation_id: str,
        result_status: SnapshotRollbackResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str,
        version: str,
        target_snapshot_id: str,
        active_snapshot_before_id: str | None,
        active_snapshot_after_id: str | None,
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotRollbackAuditRecord:
        """Persist one rollback audit record."""

    def list_records(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
    ) -> tuple[SnapshotRollbackAuditRecord, ...]:
        """List rollback audit records in reverse chronological order."""


class InMemorySnapshotRollbackAuditStore:
    """In-memory rollback audit store for tests/dev."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0
        self._records: list[SnapshotRollbackAuditRecord] = []

    def record(
        self,
        *,
        operation_id: str,
        result_status: SnapshotRollbackResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str,
        version: str,
        target_snapshot_id: str,
        active_snapshot_before_id: str | None,
        active_snapshot_after_id: str | None,
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotRollbackAuditRecord:
        with self._lock:
            self._counter += 1
            record = SnapshotRollbackAuditRecord(
                audit_id=f"rbka-{self._counter:08d}",
                operation_id=operation_id,
                result_status=result_status,
                actor_key_id=actor_key_id,
                request_id=request_id,
                reason=reason,
                product_id=product_id,
                programming_language=programming_language,
                version=version,
                target_snapshot_id=target_snapshot_id,
                active_snapshot_before_id=active_snapshot_before_id,
                active_snapshot_after_id=active_snapshot_after_id,
                diagnostics=dict(diagnostics or {}),
                created_at=datetime.now(tz=UTC),
            )
            self._records.append(record)
            return record

    def list_records(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
    ) -> tuple[SnapshotRollbackAuditRecord, ...]:
        if limit < 1:
            return ()
        with self._lock:
            records = list(self._records)
        if product_id is not None:
            records = [item for item in records if item.product_id == product_id]
        return tuple(reversed(records[-limit:]))


class PostgresSnapshotRollbackAuditStore:
    """PostgreSQL-backed rollback audit store."""

    def __init__(
        self,
        *,
        postgres_dsn: str,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self._engine: Engine = create_engine(
            postgres_dsn,
            pool_pre_ping=True,
            connect_args={"connect_timeout": int(connect_timeout_seconds)},
        )
        self._ensure_schema()

    def ping(self) -> None:
        """Validate that PostgreSQL connection is available."""
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def record(
        self,
        *,
        operation_id: str,
        result_status: SnapshotRollbackResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str,
        version: str,
        target_snapshot_id: str,
        active_snapshot_before_id: str | None,
        active_snapshot_after_id: str | None,
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotRollbackAuditRecord:
        with self._engine.begin() as connection:
            sequence_value = int(
                connection.execute(text("SELECT nextval('adcs_rollback_audit_seq')")).scalar_one()
            )
            audit_id = f"rbka-{sequence_value:08d}"
            row = connection.execute(
                text(
                    """
                    INSERT INTO snapshot_rollback_audit (
                        audit_id,
                        operation_id,
                        result_status,
                        actor_key_id,
                        request_id,
                        reason,
                        product_id,
                        programming_language,
                        version,
                        target_snapshot_id,
                        active_snapshot_before_id,
                        active_snapshot_after_id,
                        diagnostics_json,
                        created_at
                    )
                    VALUES (
                        :audit_id,
                        :operation_id,
                        :result_status,
                        :actor_key_id,
                        :request_id,
                        :reason,
                        :product_id,
                        :programming_language,
                        :version,
                        :target_snapshot_id,
                        :active_snapshot_before_id,
                        :active_snapshot_after_id,
                        CAST(:diagnostics_json AS JSONB),
                        NOW()
                    )
                    RETURNING
                        audit_id,
                        operation_id,
                        result_status,
                        actor_key_id,
                        request_id,
                        reason,
                        product_id,
                        programming_language,
                        version,
                        target_snapshot_id,
                        active_snapshot_before_id,
                        active_snapshot_after_id,
                        diagnostics_json,
                        created_at
                    """
                ),
                {
                    "audit_id": audit_id,
                    "operation_id": operation_id,
                    "result_status": result_status.value,
                    "actor_key_id": actor_key_id,
                    "request_id": request_id,
                    "reason": reason,
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "version": version,
                    "target_snapshot_id": target_snapshot_id,
                    "active_snapshot_before_id": active_snapshot_before_id,
                    "active_snapshot_after_id": active_snapshot_after_id,
                    "diagnostics_json": json.dumps(dict(diagnostics or {})),
                },
            ).mappings().one()
        return _map_row(row)

    def list_records(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
    ) -> tuple[SnapshotRollbackAuditRecord, ...]:
        if limit < 1:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        audit_id,
                        operation_id,
                        result_status,
                        actor_key_id,
                        request_id,
                        reason,
                        product_id,
                        programming_language,
                        version,
                        target_snapshot_id,
                        active_snapshot_before_id,
                        active_snapshot_after_id,
                        diagnostics_json,
                        created_at
                    FROM snapshot_rollback_audit
                    WHERE (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                    ORDER BY created_at DESC, audit_id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "product_id": product_id,
                    "limit": limit,
                },
            ).mappings().all()
        return tuple(_map_row(row) for row in rows)

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS adcs_rollback_audit_seq"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS snapshot_rollback_audit (
                        audit_id TEXT PRIMARY KEY,
                        operation_id TEXT NOT NULL,
                        result_status TEXT NOT NULL,
                        actor_key_id TEXT NOT NULL,
                        request_id TEXT NULL,
                        reason TEXT NOT NULL,
                        product_id TEXT NOT NULL,
                        programming_language TEXT NOT NULL,
                        version TEXT NOT NULL,
                        target_snapshot_id TEXT NOT NULL,
                        active_snapshot_before_id TEXT NULL,
                        active_snapshot_after_id TEXT NULL,
                        diagnostics_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_snapshot_rollback_audit_scope
                    ON snapshot_rollback_audit (
                        product_id,
                        programming_language,
                        version,
                        created_at DESC
                    )
                    """
                )
            )


def _map_row(row: object) -> SnapshotRollbackAuditRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected rollback audit row payload."
        raise TypeError(msg)
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid rollback audit created_at value."
        raise TypeError(msg)
    diagnostics = row.get("diagnostics_json")
    if isinstance(diagnostics, str):
        parsed = json.loads(diagnostics)
    elif isinstance(diagnostics, Mapping):
        parsed = dict(diagnostics)
    else:
        parsed = {}
    return SnapshotRollbackAuditRecord(
        audit_id=str(row.get("audit_id")),
        operation_id=str(row.get("operation_id")),
        result_status=SnapshotRollbackResultStatus(str(row.get("result_status"))),
        actor_key_id=str(row.get("actor_key_id")),
        request_id=None if row.get("request_id") is None else str(row.get("request_id")),
        reason=str(row.get("reason")),
        product_id=str(row.get("product_id")),
        programming_language=str(row.get("programming_language")),
        version=str(row.get("version")),
        target_snapshot_id=str(row.get("target_snapshot_id")),
        active_snapshot_before_id=(
            None
            if row.get("active_snapshot_before_id") is None
            else str(row.get("active_snapshot_before_id"))
        ),
        active_snapshot_after_id=(
            None
            if row.get("active_snapshot_after_id") is None
            else str(row.get("active_snapshot_after_id"))
        ),
        diagnostics=parsed,
        created_at=created_at,
    )
