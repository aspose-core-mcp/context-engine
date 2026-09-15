"""Critical event contracts and in-memory event store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, create_engine, text


class CriticalEventSeverity(StrEnum):
    """Supported critical event severities."""

    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"


class CriticalEventType(StrEnum):
    """Supported critical event types for ingestion workflows."""

    PARTIAL_PUBLISH = "partial_publish"
    PUBLISH_BLOCKED = "publish_blocked"
    INGESTION_CRITICAL_FAIL = "ingestion_critical_fail"
    ROLLBACK_SUCCEEDED = "rollback_succeeded"
    ROLLBACK_FAILED = "rollback_failed"


class CriticalEventActionType(StrEnum):
    """Supported critical-event action operations."""

    ACKNOWLEDGE = "acknowledge"
    MUTE = "mute"
    SNOOZE = "snooze"
    ASSIGN_OWNER = "assign_owner"
    SEVERITY_OVERRIDE = "severity_override"
    ESCALATE = "escalate"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class CriticalEventRecord:
    """One emitted critical event."""

    event_id: str
    severity: CriticalEventSeverity
    event_type: CriticalEventType
    message: str
    details: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CriticalEventActionRecord:
    """One auditable action taken for a critical event."""

    action_id: str
    event_id: str
    action: CriticalEventActionType
    actor_key_id: str
    request_id: str | None
    payload: dict[str, object]
    created_at: datetime


class CriticalEventPublisher(Protocol):
    """Contract for critical event publishers."""

    def emit(
        self,
        *,
        severity: CriticalEventSeverity,
        event_type: CriticalEventType,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> CriticalEventRecord:
        """Publish one critical event record."""


@runtime_checkable
class CriticalEventStore(CriticalEventPublisher, Protocol):
    """Contract for critical-event store and audit persistence."""

    def get_event(self, event_id: str) -> CriticalEventRecord | None:
        """Return one event by id."""

    def list_events(self, *, limit: int = 20) -> tuple[CriticalEventRecord, ...]:
        """List recent events in reverse chronological order."""

    def count_events_by_type(self) -> dict[str, int]:
        """Return lifetime event counts keyed by event type.

        `list_events` is capped and ordered for a UI; a metrics scrape needs
        totals, and paging the whole table on every scrape would make the
        endpoint scale with history.
        """

    def apply_action(
        self,
        *,
        event_id: str,
        action: CriticalEventActionType,
        actor_key_id: str,
        request_id: str | None,
        payload: Mapping[str, object] | None = None,
    ) -> CriticalEventActionRecord:
        """Persist one auditable critical-event action."""

    def list_actions(
        self,
        *,
        limit: int = 50,
        event_id: str | None = None,
    ) -> tuple[CriticalEventActionRecord, ...]:
        """List recent critical-event actions."""


class InMemoryCriticalEventStore:
    """In-memory implementation of critical event publisher."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0
        self._action_counter = 0
        self._records: list[CriticalEventRecord] = []
        self._records_by_id: dict[str, CriticalEventRecord] = {}
        self._actions: list[CriticalEventActionRecord] = []

    def emit(
        self,
        *,
        severity: CriticalEventSeverity,
        event_type: CriticalEventType,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> CriticalEventRecord:
        with self._lock:
            self._counter += 1
            event_id = f"evt-{self._counter:08d}"
            record = CriticalEventRecord(
                event_id=event_id,
                severity=severity,
                event_type=event_type,
                message=message,
                details=dict(details or {}),
                created_at=datetime.now(tz=UTC),
            )
            self._records.append(record)
            self._records_by_id[record.event_id] = record
        return record

    def get_event(self, event_id: str) -> CriticalEventRecord | None:
        """Return one event by id."""
        with self._lock:
            return self._records_by_id.get(event_id)

    def list_events(self, *, limit: int = 20) -> tuple[CriticalEventRecord, ...]:
        """List recent events in reverse chronological order."""
        if limit < 1:
            return ()
        with self._lock:
            return tuple(reversed(self._records[-limit:]))

    def count_events_by_type(self) -> dict[str, int]:
        """Return lifetime event counts keyed by event type."""
        counts: dict[str, int] = {}
        with self._lock:
            for record in self._records:
                key = str(record.event_type)
                counts[key] = counts.get(key, 0) + 1
        return counts

    def apply_action(
        self,
        *,
        event_id: str,
        action: CriticalEventActionType,
        actor_key_id: str,
        request_id: str | None,
        payload: Mapping[str, object] | None = None,
    ) -> CriticalEventActionRecord:
        """Persist one auditable critical-event action."""
        with self._lock:
            if event_id not in self._records_by_id:
                msg = f"Critical event `{event_id}` was not found."
                raise KeyError(msg)
            self._action_counter += 1
            action_id = f"evtact-{self._action_counter:08d}"
            record = CriticalEventActionRecord(
                action_id=action_id,
                event_id=event_id,
                action=action,
                actor_key_id=actor_key_id,
                request_id=request_id,
                payload=dict(payload or {}),
                created_at=datetime.now(tz=UTC),
            )
            self._actions.append(record)
            return record

    def list_actions(
        self,
        *,
        limit: int = 50,
        event_id: str | None = None,
    ) -> tuple[CriticalEventActionRecord, ...]:
        """List recent critical-event actions."""
        if limit < 1:
            return ()
        with self._lock:
            actions: list[CriticalEventActionRecord]
            if event_id is None:
                actions = self._actions
            else:
                actions = [action for action in self._actions if action.event_id == event_id]
            return tuple(reversed(actions[-limit:]))


class PostgresCriticalEventStore:
    """PostgreSQL-backed critical-event and audit-action store."""

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

    def emit(
        self,
        *,
        severity: CriticalEventSeverity,
        event_type: CriticalEventType,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> CriticalEventRecord:
        with self._engine.begin() as connection:
            sequence_value = int(
                connection.execute(text("SELECT nextval('adcs_event_seq')")).scalar_one()
            )
            event_id = f"evt-{sequence_value:08d}"
            row = connection.execute(
                text(
                    """
                    INSERT INTO critical_events (
                        event_id,
                        severity,
                        event_type,
                        message,
                        details_json,
                        created_at
                    )
                    VALUES (
                        :event_id,
                        :severity,
                        :event_type,
                        :message,
                        CAST(:details_json AS JSONB),
                        NOW()
                    )
                    RETURNING
                        event_id,
                        severity,
                        event_type,
                        message,
                        details_json,
                        created_at
                    """
                ),
                {
                    "event_id": event_id,
                    "severity": severity.value,
                    "event_type": event_type.value,
                    "message": message,
                    "details_json": json.dumps(dict(details or {})),
                },
            ).mappings().one()
        return _map_event_row(row)

    def get_event(self, event_id: str) -> CriticalEventRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        event_id,
                        severity,
                        event_type,
                        message,
                        details_json,
                        created_at
                    FROM critical_events
                    WHERE event_id = :event_id
                    """
                ),
                {"event_id": event_id},
            ).mappings().first()
        if row is None:
            return None
        return _map_event_row(row)

    def list_events(self, *, limit: int = 20) -> tuple[CriticalEventRecord, ...]:
        if limit < 1:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        event_id,
                        severity,
                        event_type,
                        message,
                        details_json,
                        created_at
                    FROM critical_events
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return tuple(_map_event_row(row) for row in rows)

    def count_events_by_type(self) -> dict[str, int]:
        """Return lifetime event counts keyed by event type."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT event_type, COUNT(*) AS event_count
                    FROM critical_events
                    GROUP BY event_type
                    """
                )
            ).mappings().all()
        return {str(row["event_type"]): int(row["event_count"]) for row in rows}

    def apply_action(
        self,
        *,
        event_id: str,
        action: CriticalEventActionType,
        actor_key_id: str,
        request_id: str | None,
        payload: Mapping[str, object] | None = None,
    ) -> CriticalEventActionRecord:
        with self._engine.begin() as connection:
            event_exists = connection.execute(
                text("SELECT 1 FROM critical_events WHERE event_id = :event_id"),
                {"event_id": event_id},
            ).first()
            if event_exists is None:
                msg = f"Critical event `{event_id}` was not found."
                raise KeyError(msg)

            sequence_value = int(
                connection.execute(text("SELECT nextval('adcs_event_action_seq')")).scalar_one()
            )
            action_id = f"evtact-{sequence_value:08d}"
            row = connection.execute(
                text(
                    """
                    INSERT INTO critical_event_actions (
                        action_id,
                        event_id,
                        action_type,
                        actor_key_id,
                        request_id,
                        payload_json,
                        created_at
                    )
                    VALUES (
                        :action_id,
                        :event_id,
                        :action_type,
                        :actor_key_id,
                        :request_id,
                        CAST(:payload_json AS JSONB),
                        NOW()
                    )
                    RETURNING
                        action_id,
                        event_id,
                        action_type,
                        actor_key_id,
                        request_id,
                        payload_json,
                        created_at
                    """
                ),
                {
                    "action_id": action_id,
                    "event_id": event_id,
                    "action_type": action.value,
                    "actor_key_id": actor_key_id,
                    "request_id": request_id,
                    "payload_json": json.dumps(dict(payload or {})),
                },
            ).mappings().one()
        return _map_action_row(row)

    def list_actions(
        self,
        *,
        limit: int = 50,
        event_id: str | None = None,
    ) -> tuple[CriticalEventActionRecord, ...]:
        if limit < 1:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        action_id,
                        event_id,
                        action_type,
                        actor_key_id,
                        request_id,
                        payload_json,
                        created_at
                    FROM critical_event_actions
                    WHERE (CAST(:event_id AS TEXT) IS NULL OR event_id = :event_id)
                    ORDER BY created_at DESC, action_id DESC
                    LIMIT :limit
                    """
                ),
                {"event_id": event_id, "limit": limit},
            ).mappings().all()
        return tuple(_map_action_row(row) for row in rows)

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS adcs_event_seq"))
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS adcs_event_action_seq"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS critical_events (
                        event_id TEXT PRIMARY KEY,
                        severity TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS critical_event_actions (
                        action_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL REFERENCES critical_events(event_id),
                        action_type TEXT NOT NULL,
                        actor_key_id TEXT NOT NULL,
                        request_id TEXT NULL,
                        payload_json JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_critical_event_actions_event
                    ON critical_event_actions (event_id, created_at DESC)
                    """
                )
            )


def _map_event_row(row: object) -> CriticalEventRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected critical event row payload."
        raise TypeError(msg)

    details = _coerce_json_object(row.get("details_json"))
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid critical event created_at value."
        raise TypeError(msg)

    return CriticalEventRecord(
        event_id=str(row.get("event_id")),
        severity=CriticalEventSeverity(str(row.get("severity"))),
        event_type=CriticalEventType(str(row.get("event_type"))),
        message=str(row.get("message")),
        details=details,
        created_at=created_at,
    )


def _map_action_row(row: object) -> CriticalEventActionRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected critical event action row payload."
        raise TypeError(msg)

    payload = _coerce_json_object(row.get("payload_json"))
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid critical event action created_at value."
        raise TypeError(msg)

    request_id_value = row.get("request_id")
    request_id = str(request_id_value) if request_id_value is not None else None
    return CriticalEventActionRecord(
        action_id=str(row.get("action_id")),
        event_id=str(row.get("event_id")),
        action=CriticalEventActionType(str(row.get("action_type"))),
        actor_key_id=str(row.get("actor_key_id")),
        request_id=request_id,
        payload=payload,
        created_at=created_at,
    )


def _coerce_json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(key): item for key, item in parsed.items()}
    return {}
