"""Control-plane ingestion job repositories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from sqlalchemy import Engine, create_engine, text


@dataclass(frozen=True, slots=True)
class IngestionJobRecord:
    """Persisted placeholder for one ingestion orchestration operation."""

    operation_id: str
    status: str
    repo_ids: tuple[str, ...]
    mode: str
    partial_publish_threshold_pct: int
    request_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    updated_at: datetime
    dry_run: bool = False
    force_full_reindex: bool = False
    idempotency_key: str | None = None
    idempotency_scope: str | None = None
    idempotency_reused: bool = False
    idempotency_expires_at: datetime | None = None
    request_fingerprint: str | None = None
    attempt_count: int = 1
    max_attempts: int = 1
    next_retry_at: datetime | None = None
    last_error_kind: str | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    resumable: bool = False


class IngestionIdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request payload."""


@dataclass(frozen=True, slots=True)
class IngestionIdempotencyClaim:
    """Result of idempotency key claim/lookup."""

    operation_id: str
    reused: bool
    expires_at: datetime


class IngestionJobRepository(Protocol):
    """Contract for ingestion job persistence repositories."""

    def upsert(
        self,
        *,
        operation_id: str,
        status: str,
        repo_ids: tuple[str, ...],
        mode: str,
        partial_publish_threshold_pct: int,
        request_id: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        error_message: str | None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        idempotency_key: str | None = None,
        idempotency_scope: str | None = None,
        idempotency_reused: bool = False,
        idempotency_expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
        attempt_count: int = 1,
        max_attempts: int = 1,
        next_retry_at: datetime | None = None,
        last_error_kind: str | None = None,
        cancel_requested_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        resumable: bool = False,
    ) -> IngestionJobRecord:
        """Create or update one ingestion job placeholder row."""

    def claim_idempotency(
        self,
        *,
        idempotency_key: str,
        idempotency_scope: str,
        operation_id: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IngestionIdempotencyClaim:
        """Claim idempotency key/scope pair and return operation reference."""

    def get(self, operation_id: str) -> IngestionJobRecord | None:
        """Read one ingestion job by operation id."""

    def list(self, *, limit: int = 20) -> tuple[IngestionJobRecord, ...]:
        """List recent ingestion jobs ordered by update time."""


@dataclass(frozen=True, slots=True)
class _InMemoryIdempotencyRecord:
    operation_id: str
    request_fingerprint: str
    expires_at: datetime


class InMemoryIngestionJobRepository:
    """Deterministic in-memory ingestion job repository for tests/dev."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, IngestionJobRecord] = {}
        self._order: list[str] = []
        self._idempotency_records: dict[tuple[str, str], _InMemoryIdempotencyRecord] = {}

    def upsert(
        self,
        *,
        operation_id: str,
        status: str,
        repo_ids: tuple[str, ...],
        mode: str,
        partial_publish_threshold_pct: int,
        request_id: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        error_message: str | None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        idempotency_key: str | None = None,
        idempotency_scope: str | None = None,
        idempotency_reused: bool = False,
        idempotency_expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
        attempt_count: int = 1,
        max_attempts: int = 1,
        next_retry_at: datetime | None = None,
        last_error_kind: str | None = None,
        cancel_requested_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        resumable: bool = False,
    ) -> IngestionJobRecord:
        record = IngestionJobRecord(
            operation_id=operation_id,
            status=status,
            repo_ids=repo_ids,
            mode=mode,
            partial_publish_threshold_pct=partial_publish_threshold_pct,
            request_id=request_id,
            started_at=started_at,
            finished_at=finished_at,
            error_message=error_message,
            updated_at=datetime.now(tz=UTC),
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            idempotency_key=idempotency_key,
            idempotency_scope=idempotency_scope,
            idempotency_reused=idempotency_reused,
            idempotency_expires_at=idempotency_expires_at,
            request_fingerprint=request_fingerprint,
            attempt_count=max(1, attempt_count),
            max_attempts=max(1, max_attempts),
            next_retry_at=next_retry_at,
            last_error_kind=last_error_kind,
            cancel_requested_at=cancel_requested_at,
            cancelled_at=cancelled_at,
            resumable=resumable,
        )
        with self._lock:
            if operation_id not in self._records:
                self._order.append(operation_id)
            self._records[operation_id] = record
        return record

    def claim_idempotency(
        self,
        *,
        idempotency_key: str,
        idempotency_scope: str,
        operation_id: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IngestionIdempotencyClaim:
        normalized_key = _normalize_non_empty_string(
            idempotency_key,
            field_name="idempotency_key",
        )
        normalized_scope = _normalize_non_empty_string(
            idempotency_scope,
            field_name="idempotency_scope",
        )
        normalized_operation_id = _normalize_non_empty_string(
            operation_id,
            field_name="operation_id",
        )
        normalized_fingerprint = _normalize_non_empty_string(
            request_fingerprint,
            field_name="request_fingerprint",
        )
        now = datetime.now(tz=UTC)
        key = (normalized_key, normalized_scope)
        with self._lock:
            existing = self._idempotency_records.get(key)
            if existing is not None and existing.expires_at > now:
                if existing.request_fingerprint != normalized_fingerprint:
                    msg = (
                        "Idempotency key is already active for a different request payload."
                    )
                    raise IngestionIdempotencyConflictError(msg)
                return IngestionIdempotencyClaim(
                    operation_id=existing.operation_id,
                    reused=True,
                    expires_at=existing.expires_at,
                )
            self._idempotency_records[key] = _InMemoryIdempotencyRecord(
                operation_id=normalized_operation_id,
                request_fingerprint=normalized_fingerprint,
                expires_at=expires_at,
            )
        return IngestionIdempotencyClaim(
            operation_id=normalized_operation_id,
            reused=False,
            expires_at=expires_at,
        )

    def get(self, operation_id: str) -> IngestionJobRecord | None:
        with self._lock:
            return self._records.get(operation_id)

    def list(self, *, limit: int = 20) -> tuple[IngestionJobRecord, ...]:
        if limit < 1:
            return ()
        with self._lock:
            operation_ids = tuple(reversed(self._order[-limit:]))
            return tuple(self._records[operation_id] for operation_id in operation_ids)


class PostgresIngestionJobRepository:
    """PostgreSQL-backed ingestion job repository."""

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

    def upsert(
        self,
        *,
        operation_id: str,
        status: str,
        repo_ids: tuple[str, ...],
        mode: str,
        partial_publish_threshold_pct: int,
        request_id: str | None,
        started_at: datetime | None,
        finished_at: datetime | None,
        error_message: str | None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        idempotency_key: str | None = None,
        idempotency_scope: str | None = None,
        idempotency_reused: bool = False,
        idempotency_expires_at: datetime | None = None,
        request_fingerprint: str | None = None,
        attempt_count: int = 1,
        max_attempts: int = 1,
        next_retry_at: datetime | None = None,
        last_error_kind: str | None = None,
        cancel_requested_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        resumable: bool = False,
    ) -> IngestionJobRecord:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    INSERT INTO ingestion_jobs (
                        operation_id,
                        status,
                        repo_ids,
                        mode,
                        partial_publish_threshold_pct,
                        request_id,
                        started_at,
                        finished_at,
                        error_message,
                        dry_run,
                        force_full_reindex,
                        idempotency_key,
                        idempotency_scope,
                        idempotency_reused,
                        idempotency_expires_at,
                        request_fingerprint,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        last_error_kind,
                        cancel_requested_at,
                        cancelled_at,
                        resumable,
                        updated_at
                    )
                    VALUES (
                        :operation_id,
                        :status,
                        CAST(:repo_ids AS JSONB),
                        :mode,
                        :partial_publish_threshold_pct,
                        :request_id,
                        :started_at,
                        :finished_at,
                        :error_message,
                        :dry_run,
                        :force_full_reindex,
                        :idempotency_key,
                        :idempotency_scope,
                        :idempotency_reused,
                        :idempotency_expires_at,
                        :request_fingerprint,
                        :attempt_count,
                        :max_attempts,
                        :next_retry_at,
                        :last_error_kind,
                        :cancel_requested_at,
                        :cancelled_at,
                        :resumable,
                        NOW()
                    )
                    ON CONFLICT (operation_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        repo_ids = EXCLUDED.repo_ids,
                        mode = EXCLUDED.mode,
                        partial_publish_threshold_pct = EXCLUDED.partial_publish_threshold_pct,
                        request_id = EXCLUDED.request_id,
                        started_at = EXCLUDED.started_at,
                        finished_at = EXCLUDED.finished_at,
                        error_message = EXCLUDED.error_message,
                        dry_run = EXCLUDED.dry_run,
                        force_full_reindex = EXCLUDED.force_full_reindex,
                        idempotency_key = EXCLUDED.idempotency_key,
                        idempotency_scope = EXCLUDED.idempotency_scope,
                        idempotency_reused = EXCLUDED.idempotency_reused,
                        idempotency_expires_at = EXCLUDED.idempotency_expires_at,
                        request_fingerprint = EXCLUDED.request_fingerprint,
                        attempt_count = EXCLUDED.attempt_count,
                        max_attempts = EXCLUDED.max_attempts,
                        next_retry_at = EXCLUDED.next_retry_at,
                        last_error_kind = EXCLUDED.last_error_kind,
                        cancel_requested_at = EXCLUDED.cancel_requested_at,
                        cancelled_at = EXCLUDED.cancelled_at,
                        resumable = EXCLUDED.resumable,
                        updated_at = NOW()
                    RETURNING
                        operation_id,
                        status,
                        repo_ids,
                        mode,
                        partial_publish_threshold_pct,
                        request_id,
                        started_at,
                        finished_at,
                        error_message,
                        dry_run,
                        force_full_reindex,
                        idempotency_key,
                        idempotency_scope,
                        idempotency_reused,
                        idempotency_expires_at,
                        request_fingerprint,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        last_error_kind,
                        cancel_requested_at,
                        cancelled_at,
                        resumable,
                        updated_at
                    """
                ),
                {
                    "operation_id": operation_id,
                    "status": status,
                    "repo_ids": json.dumps(list(repo_ids)),
                    "mode": mode,
                    "partial_publish_threshold_pct": partial_publish_threshold_pct,
                    "request_id": request_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "error_message": error_message,
                    "dry_run": dry_run,
                    "force_full_reindex": force_full_reindex,
                    "idempotency_key": idempotency_key,
                    "idempotency_scope": idempotency_scope,
                    "idempotency_reused": idempotency_reused,
                    "idempotency_expires_at": idempotency_expires_at,
                    "request_fingerprint": request_fingerprint,
                    "attempt_count": max(1, attempt_count),
                    "max_attempts": max(1, max_attempts),
                    "next_retry_at": next_retry_at,
                    "last_error_kind": last_error_kind,
                    "cancel_requested_at": cancel_requested_at,
                    "cancelled_at": cancelled_at,
                    "resumable": resumable,
                },
            ).mappings().one()
        return _map_ingestion_job_row(row)

    def claim_idempotency(
        self,
        *,
        idempotency_key: str,
        idempotency_scope: str,
        operation_id: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> IngestionIdempotencyClaim:
        normalized_key = _normalize_non_empty_string(
            idempotency_key,
            field_name="idempotency_key",
        )
        normalized_scope = _normalize_non_empty_string(
            idempotency_scope,
            field_name="idempotency_scope",
        )
        normalized_operation_id = _normalize_non_empty_string(
            operation_id,
            field_name="operation_id",
        )
        normalized_fingerprint = _normalize_non_empty_string(
            request_fingerprint,
            field_name="request_fingerprint",
        )
        now = datetime.now(tz=UTC)
        with self._engine.begin() as connection:
            existing_row = connection.execute(
                text(
                    """
                    SELECT
                        operation_id,
                        request_fingerprint,
                        expires_at
                    FROM ingestion_idempotency_keys
                    WHERE idempotency_key = :idempotency_key
                      AND idempotency_scope = :idempotency_scope
                    FOR UPDATE
                    """
                ),
                {
                    "idempotency_key": normalized_key,
                    "idempotency_scope": normalized_scope,
                },
            ).mappings().first()

            if existing_row is not None:
                existing_operation_id = _normalize_non_empty_string(
                    str(existing_row.get("operation_id")),
                    field_name="operation_id",
                )
                existing_fingerprint = _normalize_non_empty_string(
                    str(existing_row.get("request_fingerprint")),
                    field_name="request_fingerprint",
                )
                existing_expires_at = _nullable_datetime(existing_row.get("expires_at"))
                if existing_expires_at is not None and existing_expires_at > now:
                    if existing_fingerprint != normalized_fingerprint:
                        msg = (
                            "Idempotency key is already active for a different request payload."
                        )
                        raise IngestionIdempotencyConflictError(msg)
                    return IngestionIdempotencyClaim(
                        operation_id=existing_operation_id,
                        reused=True,
                        expires_at=existing_expires_at,
                    )

            connection.execute(
                text(
                    """
                    INSERT INTO ingestion_idempotency_keys (
                        idempotency_key,
                        idempotency_scope,
                        operation_id,
                        request_fingerprint,
                        expires_at,
                        updated_at
                    )
                    VALUES (
                        :idempotency_key,
                        :idempotency_scope,
                        :operation_id,
                        :request_fingerprint,
                        :expires_at,
                        NOW()
                    )
                    ON CONFLICT (idempotency_key, idempotency_scope) DO UPDATE SET
                        operation_id = EXCLUDED.operation_id,
                        request_fingerprint = EXCLUDED.request_fingerprint,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """
                ),
                {
                    "idempotency_key": normalized_key,
                    "idempotency_scope": normalized_scope,
                    "operation_id": normalized_operation_id,
                    "request_fingerprint": normalized_fingerprint,
                    "expires_at": expires_at,
                },
            )
        return IngestionIdempotencyClaim(
            operation_id=normalized_operation_id,
            reused=False,
            expires_at=expires_at,
        )

    def get(self, operation_id: str) -> IngestionJobRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        operation_id,
                        status,
                        repo_ids,
                        mode,
                        partial_publish_threshold_pct,
                        request_id,
                        started_at,
                        finished_at,
                        error_message,
                        dry_run,
                        force_full_reindex,
                        idempotency_key,
                        idempotency_scope,
                        idempotency_reused,
                        idempotency_expires_at,
                        request_fingerprint,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        last_error_kind,
                        cancel_requested_at,
                        cancelled_at,
                        resumable,
                        updated_at
                    FROM ingestion_jobs
                    WHERE operation_id = :operation_id
                    """
                ),
                {"operation_id": operation_id},
            ).mappings().first()
        if row is None:
            return None
        return _map_ingestion_job_row(row)

    def list(self, *, limit: int = 20) -> tuple[IngestionJobRecord, ...]:
        if limit < 1:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        operation_id,
                        status,
                        repo_ids,
                        mode,
                        partial_publish_threshold_pct,
                        request_id,
                        started_at,
                        finished_at,
                        error_message,
                        dry_run,
                        force_full_reindex,
                        idempotency_key,
                        idempotency_scope,
                        idempotency_reused,
                        idempotency_expires_at,
                        request_fingerprint,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        last_error_kind,
                        cancel_requested_at,
                        cancelled_at,
                        resumable,
                        updated_at
                    FROM ingestion_jobs
                    ORDER BY updated_at DESC, operation_id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return tuple(_map_ingestion_job_row(row) for row in rows)

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_jobs (
                        operation_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        repo_ids JSONB NOT NULL,
                        mode TEXT NOT NULL,
                        partial_publish_threshold_pct INTEGER NOT NULL,
                        request_id TEXT NULL,
                        started_at TIMESTAMPTZ NULL,
                        finished_at TIMESTAMPTZ NULL,
                        error_message TEXT NULL,
                        dry_run BOOLEAN NOT NULL DEFAULT FALSE,
                        force_full_reindex BOOLEAN NOT NULL DEFAULT FALSE,
                        idempotency_key TEXT NULL,
                        idempotency_scope TEXT NULL,
                        idempotency_reused BOOLEAN NOT NULL DEFAULT FALSE,
                        idempotency_expires_at TIMESTAMPTZ NULL,
                        request_fingerprint TEXT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 1,
                        max_attempts INTEGER NOT NULL DEFAULT 1,
                        next_retry_at TIMESTAMPTZ NULL,
                        last_error_kind TEXT NULL,
                        cancel_requested_at TIMESTAMPTZ NULL,
                        cancelled_at TIMESTAMPTZ NULL,
                        resumable BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS dry_run BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS force_full_reindex BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS idempotency_key TEXT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS idempotency_scope TEXT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS idempotency_reused BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS idempotency_expires_at TIMESTAMPTZ NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS request_fingerprint TEXT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 1
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 1
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS last_error_kind TEXT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ingestion_jobs
                    ADD COLUMN IF NOT EXISTS resumable BOOLEAN NOT NULL DEFAULT FALSE
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_idempotency_keys (
                        idempotency_key TEXT NOT NULL,
                        idempotency_scope TEXT NOT NULL,
                        operation_id TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (idempotency_key, idempotency_scope)
                    )
                    """
                )
            )


def _map_ingestion_job_row(row: object) -> IngestionJobRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected ingestion job row payload."
        raise TypeError(msg)

    raw_repo_ids = row.get("repo_ids")
    if isinstance(raw_repo_ids, str):
        parsed = json.loads(raw_repo_ids)
    else:
        parsed = raw_repo_ids
    if not isinstance(parsed, list):
        parsed = []

    updated_at = row.get("updated_at")
    if not isinstance(updated_at, datetime):
        msg = "Invalid ingestion job updated_at value."
        raise TypeError(msg)
    threshold_value = row.get("partial_publish_threshold_pct")
    if threshold_value is None:
        msg = "Invalid ingestion job partial_publish_threshold_pct value."
        raise TypeError(msg)

    return IngestionJobRecord(
        operation_id=str(row.get("operation_id")),
        status=str(row.get("status")),
        repo_ids=tuple(str(item) for item in parsed if isinstance(item, str)),
        mode=str(row.get("mode")),
        partial_publish_threshold_pct=_required_int(
            threshold_value,
            field_name="partial_publish_threshold_pct",
        ),
        request_id=_nullable_string(row.get("request_id")),
        started_at=_nullable_datetime(row.get("started_at")),
        finished_at=_nullable_datetime(row.get("finished_at")),
        error_message=_nullable_string(row.get("error_message")),
        updated_at=updated_at,
        dry_run=_coerce_bool(row.get("dry_run"), default=False, field_name="dry_run"),
        force_full_reindex=_coerce_bool(
            row.get("force_full_reindex"),
            default=False,
            field_name="force_full_reindex",
        ),
        idempotency_key=_nullable_string(row.get("idempotency_key")),
        idempotency_scope=_nullable_string(row.get("idempotency_scope")),
        idempotency_reused=_coerce_bool(
            row.get("idempotency_reused"),
            default=False,
            field_name="idempotency_reused",
        ),
        idempotency_expires_at=_nullable_datetime(row.get("idempotency_expires_at")),
        request_fingerprint=_nullable_string(row.get("request_fingerprint")),
        attempt_count=max(
            1,
            _required_int(
                row.get("attempt_count") if row.get("attempt_count") is not None else 1,
                field_name="attempt_count",
            ),
        ),
        max_attempts=max(
            1,
            _required_int(
                row.get("max_attempts") if row.get("max_attempts") is not None else 1,
                field_name="max_attempts",
            ),
        ),
        next_retry_at=_nullable_datetime(row.get("next_retry_at")),
        last_error_kind=_nullable_string(row.get("last_error_kind")),
        cancel_requested_at=_nullable_datetime(row.get("cancel_requested_at")),
        cancelled_at=_nullable_datetime(row.get("cancelled_at")),
        resumable=_coerce_bool(row.get("resumable"), default=False, field_name="resumable"),
    )


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _nullable_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    msg = "Invalid datetime value."
    raise TypeError(msg)


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        msg = f"Invalid integer value for {field_name}."
        raise TypeError(msg)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            msg = f"Invalid integer value for {field_name}."
            raise TypeError(msg) from exc
    msg = f"Invalid integer value for {field_name}."
    raise TypeError(msg)


def _coerce_bool(value: object, *, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    msg = f"Invalid boolean value for {field_name}."
    raise TypeError(msg)


def _normalize_non_empty_string(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return normalized
