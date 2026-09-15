"""Snapshot cleanup audit trail contracts and adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import Engine, create_engine, text


class SnapshotCleanupResultStatus(StrEnum):
    """Execution status for one snapshot cleanup operation."""

    PREVIEW = "preview"
    COMPLETED = "completed"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class SnapshotCleanupAuditRecord:
    """One auditable snapshot cleanup preview or execution."""

    audit_id: str
    operation_id: str
    result_status: SnapshotCleanupResultStatus
    actor_key_id: str
    request_id: str | None
    reason: str
    product_id: str
    programming_language: str | None
    version: str | None
    source_kind: str | None
    dry_run: bool
    deleted_snapshot_ids: tuple[str, ...]
    protected_snapshot_ids: tuple[str, ...]
    diagnostics: dict[str, object]
    created_at: datetime


@runtime_checkable
class SnapshotCleanupAuditStore(Protocol):
    """Contract for snapshot cleanup audit persistence."""

    def record(
        self,
        *,
        operation_id: str,
        result_status: SnapshotCleanupResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str | None,
        version: str | None,
        source_kind: str | None,
        dry_run: bool,
        deleted_snapshot_ids: tuple[str, ...],
        protected_snapshot_ids: tuple[str, ...],
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotCleanupAuditRecord:
        """Persist one cleanup audit record."""

    def list_records(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
    ) -> tuple[SnapshotCleanupAuditRecord, ...]:
        """List cleanup audit records in reverse chronological order."""


class InMemorySnapshotCleanupAuditStore:
    """In-memory snapshot cleanup audit store for tests/dev."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0
        self._records: list[SnapshotCleanupAuditRecord] = []

    def record(
        self,
        *,
        operation_id: str,
        result_status: SnapshotCleanupResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str | None,
        version: str | None,
        source_kind: str | None,
        dry_run: bool,
        deleted_snapshot_ids: tuple[str, ...],
        protected_snapshot_ids: tuple[str, ...],
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotCleanupAuditRecord:
        with self._lock:
            self._counter += 1
            record = SnapshotCleanupAuditRecord(
                audit_id=f"clna-{self._counter:08d}",
                operation_id=operation_id,
                result_status=result_status,
                actor_key_id=actor_key_id,
                request_id=request_id,
                reason=reason,
                product_id=product_id,
                programming_language=programming_language,
                version=version,
                source_kind=source_kind,
                dry_run=dry_run,
                deleted_snapshot_ids=tuple(deleted_snapshot_ids),
                protected_snapshot_ids=tuple(protected_snapshot_ids),
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
    ) -> tuple[SnapshotCleanupAuditRecord, ...]:
        if limit < 1:
            return ()
        with self._lock:
            records = list(self._records)
        if product_id is not None:
            records = [item for item in records if item.product_id == product_id]
        return tuple(reversed(records[-limit:]))


class PostgresSnapshotCleanupAuditStore:
    """PostgreSQL-backed snapshot cleanup audit store."""

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
        result_status: SnapshotCleanupResultStatus,
        actor_key_id: str,
        request_id: str | None,
        reason: str,
        product_id: str,
        programming_language: str | None,
        version: str | None,
        source_kind: str | None,
        dry_run: bool,
        deleted_snapshot_ids: tuple[str, ...],
        protected_snapshot_ids: tuple[str, ...],
        diagnostics: Mapping[str, object] | None = None,
    ) -> SnapshotCleanupAuditRecord:
        with self._engine.begin() as connection:
            sequence_value = int(
                connection.execute(text("SELECT nextval('adcs_cleanup_audit_seq')")).scalar_one()
            )
            audit_id = f"clna-{sequence_value:08d}"
            row = connection.execute(
                text(
                    """
                    INSERT INTO snapshot_cleanup_audit (
                        audit_id,
                        operation_id,
                        result_status,
                        actor_key_id,
                        request_id,
                        reason,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        dry_run,
                        deleted_snapshot_ids_json,
                        protected_snapshot_ids_json,
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
                        :source_kind,
                        :dry_run,
                        CAST(:deleted_snapshot_ids_json AS JSONB),
                        CAST(:protected_snapshot_ids_json AS JSONB),
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
                        source_kind,
                        dry_run,
                        deleted_snapshot_ids_json,
                        protected_snapshot_ids_json,
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
                    "source_kind": source_kind,
                    "dry_run": dry_run,
                    "deleted_snapshot_ids_json": json.dumps(list(deleted_snapshot_ids)),
                    "protected_snapshot_ids_json": json.dumps(list(protected_snapshot_ids)),
                    "diagnostics_json": json.dumps(dict(diagnostics or {})),
                },
            ).mappings().one()
        return _map_row(cast(Mapping[str, Any], row))

    def list_records(
        self,
        *,
        limit: int = 50,
        product_id: str | None = None,
    ) -> tuple[SnapshotCleanupAuditRecord, ...]:
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
                        source_kind,
                        dry_run,
                        deleted_snapshot_ids_json,
                        protected_snapshot_ids_json,
                        diagnostics_json,
                        created_at
                    FROM snapshot_cleanup_audit
                    WHERE (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                    ORDER BY created_at DESC, audit_id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "product_id": product_id,
                    "limit": max(1, min(limit, 500)),
                },
            ).mappings().all()
        return tuple(_map_row(cast(Mapping[str, Any], row)) for row in rows)

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS adcs_cleanup_audit_seq"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS snapshot_cleanup_audit (
                        audit_id TEXT PRIMARY KEY,
                        operation_id TEXT NOT NULL,
                        result_status TEXT NOT NULL,
                        actor_key_id TEXT NOT NULL,
                        request_id TEXT NULL,
                        reason TEXT NOT NULL,
                        product_id TEXT NOT NULL,
                        programming_language TEXT NULL,
                        version TEXT NULL,
                        source_kind TEXT NULL,
                        dry_run BOOLEAN NOT NULL,
                        deleted_snapshot_ids_json JSONB NOT NULL,
                        protected_snapshot_ids_json JSONB NOT NULL,
                        diagnostics_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_snapshot_cleanup_audit_product_created
                    ON snapshot_cleanup_audit (product_id, created_at DESC)
                    """
                )
            )


def _map_row(row: Mapping[str, Any]) -> SnapshotCleanupAuditRecord:
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid snapshot cleanup audit created_at value."
        raise TypeError(msg)
    result_status = SnapshotCleanupResultStatus(str(row.get("result_status")))
    deleted_snapshot_ids = _load_string_tuple(row.get("deleted_snapshot_ids_json"))
    protected_snapshot_ids = _load_string_tuple(row.get("protected_snapshot_ids_json"))
    diagnostics = _load_mapping(row.get("diagnostics_json"))
    return SnapshotCleanupAuditRecord(
        audit_id=str(row.get("audit_id")),
        operation_id=str(row.get("operation_id")),
        result_status=result_status,
        actor_key_id=str(row.get("actor_key_id")),
        request_id=_nullable_str(row.get("request_id")),
        reason=str(row.get("reason")),
        product_id=str(row.get("product_id")),
        programming_language=_nullable_str(row.get("programming_language")),
        version=_nullable_str(row.get("version")),
        source_kind=_nullable_str(row.get("source_kind")),
        dry_run=bool(row.get("dry_run")),
        deleted_snapshot_ids=deleted_snapshot_ids,
        protected_snapshot_ids=protected_snapshot_ids,
        diagnostics=diagnostics,
        created_at=created_at,
    )


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _load_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, list):
            return tuple(str(item) for item in loaded)
    msg = "Invalid string tuple payload."
    raise TypeError(msg)


def _load_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return dict(loaded)
    msg = "Invalid diagnostics mapping payload."
    raise TypeError(msg)
