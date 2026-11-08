"""Snapshot registries for versioned index publish runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from sqlalchemy import Engine, create_engine, text

from adcs.indexing.index_models import (
    SnapshotRecord,
    SnapshotRollbackOutcome,
    SnapshotStatus,
)


class SnapshotRollbackConflictError(RuntimeError):
    """Raised when rollback expected-active guard fails."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        expected_active_snapshot_id: str,
        current_active_snapshot_id: str | None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.expected_active_snapshot_id = expected_active_snapshot_id
        self.current_active_snapshot_id = current_active_snapshot_id


class SnapshotRegistry(Protocol):
    """Contract for snapshot lifecycle persistence."""

    def create_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str,
        source_revision: str,
        indexed_chunks_count: int,
    ) -> SnapshotRecord:
        """Create a new active snapshot and deactivate previous scope-active snapshot."""

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        """Return one snapshot by id."""

    def get_active_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str | None = None,
    ) -> SnapshotRecord | None:
        """Return current active snapshot for one retrieval scope."""

    def list_snapshots(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[SnapshotRecord, ...]:
        """List snapshots optionally filtered by scope."""

    def promote_snapshot(self, *, snapshot_id: str) -> SnapshotRecord | None:
        """Set existing snapshot as active for its scope."""

    def rollback_snapshot(
        self,
        *,
        target_snapshot_id: str,
        expected_active_snapshot_id: str,
    ) -> SnapshotRollbackOutcome | None:
        """Atomically rollback active snapshot to one previous revision."""

    def delete_snapshots(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> tuple[SnapshotRecord, ...]:
        """Delete inactive snapshots by id and return removed records."""


class InMemorySnapshotRegistry:
    """Track multiple snapshots and active resolution by scope."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counter = 0
        self._snapshots: dict[str, SnapshotRecord] = {}
        self._snapshot_order: list[str] = []
        self._active_by_scope: dict[tuple[str, str, str, str], str] = {}

    def create_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str,
        source_revision: str,
        indexed_chunks_count: int,
    ) -> SnapshotRecord:
        scope = (product_id, programming_language, version, source_kind)
        with self._lock:
            self._counter += 1
            snapshot_id = f"snap-{self._counter:08d}"
            previous_active_snapshot_id = self._active_by_scope.get(scope)
            if previous_active_snapshot_id is not None:
                previous_active = self._snapshots[previous_active_snapshot_id]
                self._snapshots[previous_active_snapshot_id] = replace(
                    previous_active,
                    status=SnapshotStatus.INACTIVE,
                )

            snapshot = SnapshotRecord(
                snapshot_id=snapshot_id,
                product_id=product_id,
                programming_language=programming_language,
                version=version,
                source_kind=source_kind,
                source_revision=source_revision,
                status=SnapshotStatus.ACTIVE,
                indexed_chunks_count=indexed_chunks_count,
                created_at=datetime.now(tz=UTC),
            )
            self._snapshots[snapshot_id] = snapshot
            self._snapshot_order.append(snapshot_id)
            self._active_by_scope[scope] = snapshot_id
            return snapshot

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        with self._lock:
            return self._snapshots.get(snapshot_id)

    def get_active_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str | None = None,
    ) -> SnapshotRecord | None:
        with self._lock:
            if source_kind is None:
                return next(
                    (
                        self._snapshots[snapshot_id]
                        for snapshot_id in reversed(self._snapshot_order)
                        if self._snapshots[snapshot_id].product_id == product_id
                        and self._snapshots[snapshot_id].programming_language
                        == programming_language
                        and self._snapshots[snapshot_id].version == version
                        and self._snapshots[snapshot_id].status is SnapshotStatus.ACTIVE
                    ),
                    None,
                )
            scope = (product_id, programming_language, version, source_kind)
            active_snapshot_id = self._active_by_scope.get(scope)
            if active_snapshot_id is None:
                return None
            return self._snapshots.get(active_snapshot_id)

    def list_snapshots(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[SnapshotRecord, ...]:
        with self._lock:
            snapshots = tuple(self._snapshots[snapshot_id] for snapshot_id in self._snapshot_order)

        if product_id is None and programming_language is None and version is None:
            return snapshots

        return tuple(
            snapshot
            for snapshot in snapshots
            if (product_id is None or snapshot.product_id == product_id)
            and (
                programming_language is None
                or snapshot.programming_language == programming_language
            )
            and (version is None or snapshot.version == version)
        )

    def promote_snapshot(self, *, snapshot_id: str) -> SnapshotRecord | None:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None:
                return None

            scope = (
                snapshot.product_id,
                snapshot.programming_language,
                snapshot.version,
                snapshot.source_kind,
            )
            previous_active_snapshot_id = self._active_by_scope.get(scope)
            if (
                previous_active_snapshot_id is not None
                and previous_active_snapshot_id != snapshot_id
            ):
                previous_active = self._snapshots.get(previous_active_snapshot_id)
                if previous_active is not None:
                    self._snapshots[previous_active_snapshot_id] = replace(
                        previous_active,
                        status=SnapshotStatus.INACTIVE,
                    )

            promoted = replace(snapshot, status=SnapshotStatus.ACTIVE)
            self._snapshots[snapshot_id] = promoted
            self._active_by_scope[scope] = snapshot_id
            return promoted

    def rollback_snapshot(
        self,
        *,
        target_snapshot_id: str,
        expected_active_snapshot_id: str,
    ) -> SnapshotRollbackOutcome | None:
        with self._lock:
            target = self._snapshots.get(target_snapshot_id)
            if target is None:
                return None

            scope = (
                target.product_id,
                target.programming_language,
                target.version,
                target.source_kind,
            )
            current_active_snapshot_id = self._active_by_scope.get(scope)
            if current_active_snapshot_id is None:
                raise SnapshotRollbackConflictError(
                    code="ACTIVE_SNAPSHOT_NOT_FOUND",
                    message="No active snapshot found for requested rollback scope.",
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=None,
                )
            if current_active_snapshot_id != expected_active_snapshot_id:
                raise SnapshotRollbackConflictError(
                    code="ACTIVE_SNAPSHOT_CHANGED",
                    message=(
                        "Active snapshot changed since preflight; rollback execution is rejected."
                    ),
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=current_active_snapshot_id,
                )
            if current_active_snapshot_id == target_snapshot_id:
                raise SnapshotRollbackConflictError(
                    code="TARGET_ALREADY_ACTIVE",
                    message="Target snapshot is already active for requested rollback scope.",
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=current_active_snapshot_id,
                )

            previous_active = self._snapshots.get(current_active_snapshot_id)
            if previous_active is None:
                raise SnapshotRollbackConflictError(
                    code="ACTIVE_SNAPSHOT_NOT_FOUND",
                    message="No active snapshot found for requested rollback scope.",
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=None,
                )

            previous_inactive = replace(previous_active, status=SnapshotStatus.INACTIVE)
            promoted_target = replace(target, status=SnapshotStatus.ACTIVE)
            self._snapshots[current_active_snapshot_id] = previous_inactive
            self._snapshots[target_snapshot_id] = promoted_target
            self._active_by_scope[scope] = target_snapshot_id
            return SnapshotRollbackOutcome(
                target_snapshot=promoted_target,
                previous_active_snapshot=previous_inactive,
            )

    def delete_snapshots(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> tuple[SnapshotRecord, ...]:
        if not snapshot_ids:
            return ()
        with self._lock:
            removed: list[SnapshotRecord] = []
            requested_ids = set(snapshot_ids)
            remaining_order: list[str] = []
            for snapshot_id in self._snapshot_order:
                snapshot = self._snapshots.get(snapshot_id)
                if snapshot is None:
                    continue
                if snapshot_id in requested_ids and snapshot.status is SnapshotStatus.INACTIVE:
                    removed.append(snapshot)
                    self._snapshots.pop(snapshot_id, None)
                    continue
                remaining_order.append(snapshot_id)
            self._snapshot_order = remaining_order
            return tuple(removed)


class PostgresSnapshotRegistry:
    """PostgreSQL-backed snapshot registry."""

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

    def create_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str,
        source_revision: str,
        indexed_chunks_count: int,
    ) -> SnapshotRecord:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE index_snapshots
                    SET status = :inactive_status
                    WHERE
                        product_id = :product_id
                        AND programming_language = :programming_language
                        AND version = :version
                        AND source_kind = :source_kind
                        AND status = :active_status
                    """
                ),
                {
                    "inactive_status": SnapshotStatus.INACTIVE.value,
                    "active_status": SnapshotStatus.ACTIVE.value,
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "version": version,
                    "source_kind": source_kind,
                },
            )
            sequence_value = int(
                connection.execute(text("SELECT nextval('adcs_snapshot_seq')")).scalar_one()
            )
            snapshot_id = f"snap-{sequence_value:08d}"
            row = connection.execute(
                text(
                    """
                    INSERT INTO index_snapshots (
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    )
                    VALUES (
                        :snapshot_id,
                        :product_id,
                        :programming_language,
                        :version,
                        :source_kind,
                        :source_revision,
                        :status,
                        :indexed_chunks_count,
                        NOW()
                    )
                    RETURNING
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "version": version,
                    "source_kind": source_kind,
                    "source_revision": source_revision,
                    "status": SnapshotStatus.ACTIVE.value,
                    "indexed_chunks_count": indexed_chunks_count,
                },
            ).mappings().one()
        return _map_snapshot_row(row)

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE snapshot_id = :snapshot_id
                    """
                ),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
        if row is None:
            return None
        return _map_snapshot_row(row)

    def get_active_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str | None = None,
    ) -> SnapshotRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE
                        product_id = :product_id
                        AND programming_language = :programming_language
                        AND version = :version
                        AND (CAST(:source_kind AS TEXT) IS NULL OR source_kind = :source_kind)
                        AND status = :status
                    ORDER BY created_at DESC, snapshot_id DESC
                    LIMIT 1
                    """
                ),
                {
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "version": version,
                    "source_kind": source_kind,
                    "status": SnapshotStatus.ACTIVE.value,
                },
            ).mappings().first()
        if row is None:
            return None
        return _map_snapshot_row(row)

    def list_snapshots(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[SnapshotRecord, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE
                        (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                        AND (
                            CAST(:programming_language AS TEXT) IS NULL
                            OR programming_language = :programming_language
                        )
                        AND (CAST(:version AS TEXT) IS NULL OR version = :version)
                    ORDER BY created_at ASC, snapshot_id ASC
                    """
                ),
                {
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "version": version,
                },
            ).mappings().all()
        return tuple(_map_snapshot_row(row) for row in rows)

    def promote_snapshot(self, *, snapshot_id: str) -> SnapshotRecord | None:
        with self._engine.begin() as connection:
            current = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE snapshot_id = :snapshot_id
                    FOR UPDATE
                    """
                ),
                {"snapshot_id": snapshot_id},
            ).mappings().first()
            if current is None:
                return None

            connection.execute(
                text(
                    """
                    UPDATE index_snapshots
                    SET status = :inactive_status
                    WHERE
                        product_id = :product_id
                        AND programming_language = :programming_language
                        AND version = :version
                        AND source_kind = :source_kind
                        AND snapshot_id <> :snapshot_id
                        AND status = :active_status
                    """
                ),
                {
                    "inactive_status": SnapshotStatus.INACTIVE.value,
                    "active_status": SnapshotStatus.ACTIVE.value,
                    "product_id": current["product_id"],
                    "programming_language": current["programming_language"],
                    "version": current["version"],
                    "source_kind": current["source_kind"],
                    "snapshot_id": snapshot_id,
                },
            )
            promoted = connection.execute(
                text(
                    """
                    UPDATE index_snapshots
                    SET status = :active_status
                    WHERE snapshot_id = :snapshot_id
                    RETURNING
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "active_status": SnapshotStatus.ACTIVE.value,
                },
            ).mappings().one()
        return _map_snapshot_row(promoted)

    def rollback_snapshot(
        self,
        *,
        target_snapshot_id: str,
        expected_active_snapshot_id: str,
    ) -> SnapshotRollbackOutcome | None:
        with self._engine.begin() as connection:
            target = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE snapshot_id = :snapshot_id
                    FOR UPDATE
                    """
                ),
                {"snapshot_id": target_snapshot_id},
            ).mappings().first()
            if target is None:
                return None

            current_active = connection.execute(
                text(
                    """
                    SELECT
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    FROM index_snapshots
                    WHERE
                        product_id = :product_id
                        AND programming_language = :programming_language
                        AND version = :version
                        AND source_kind = :source_kind
                        AND status = :status
                    ORDER BY created_at DESC, snapshot_id DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {
                    "product_id": target["product_id"],
                    "programming_language": target["programming_language"],
                    "version": target["version"],
                    "source_kind": target["source_kind"],
                    "status": SnapshotStatus.ACTIVE.value,
                },
            ).mappings().first()
            if current_active is None:
                raise SnapshotRollbackConflictError(
                    code="ACTIVE_SNAPSHOT_NOT_FOUND",
                    message="No active snapshot found for requested rollback scope.",
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=None,
                )

            current_active_snapshot_id = str(current_active["snapshot_id"])
            if current_active_snapshot_id != expected_active_snapshot_id:
                raise SnapshotRollbackConflictError(
                    code="ACTIVE_SNAPSHOT_CHANGED",
                    message=(
                        "Active snapshot changed since preflight; rollback execution is rejected."
                    ),
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=current_active_snapshot_id,
                )
            if current_active_snapshot_id == target_snapshot_id:
                raise SnapshotRollbackConflictError(
                    code="TARGET_ALREADY_ACTIVE",
                    message="Target snapshot is already active for requested rollback scope.",
                    expected_active_snapshot_id=expected_active_snapshot_id,
                    current_active_snapshot_id=current_active_snapshot_id,
                )

            previous_active_row = connection.execute(
                text(
                    """
                    UPDATE index_snapshots
                    SET status = :inactive_status
                    WHERE snapshot_id = :snapshot_id
                    RETURNING
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    """
                ),
                {
                    "inactive_status": SnapshotStatus.INACTIVE.value,
                    "snapshot_id": current_active_snapshot_id,
                },
            ).mappings().one()

            promoted_target_row = connection.execute(
                text(
                    """
                    UPDATE index_snapshots
                    SET status = :active_status
                    WHERE snapshot_id = :snapshot_id
                    RETURNING
                        snapshot_id,
                        product_id,
                        programming_language,
                        version,
                        source_kind,
                        source_revision,
                        status,
                        indexed_chunks_count,
                        created_at
                    """
                ),
                {
                    "active_status": SnapshotStatus.ACTIVE.value,
                    "snapshot_id": target_snapshot_id,
                },
            ).mappings().one()
        return SnapshotRollbackOutcome(
            target_snapshot=_map_snapshot_row(promoted_target_row),
            previous_active_snapshot=_map_snapshot_row(previous_active_row),
        )

    def delete_snapshots(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> tuple[SnapshotRecord, ...]:
        if not snapshot_ids:
            return ()
        removed: list[SnapshotRecord] = []
        with self._engine.begin() as connection:
            for snapshot_id in snapshot_ids:
                row = connection.execute(
                    text(
                        """
                        SELECT
                            snapshot_id,
                            product_id,
                            programming_language,
                            version,
                            source_kind,
                            source_revision,
                            status,
                            indexed_chunks_count,
                            created_at
                        FROM index_snapshots
                        WHERE snapshot_id = :snapshot_id
                        FOR UPDATE
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                ).mappings().first()
                if row is None:
                    continue
                if SnapshotStatus(str(row["status"])) is not SnapshotStatus.INACTIVE:
                    continue
                connection.execute(
                    text(
                        """
                        DELETE FROM index_snapshots
                        WHERE snapshot_id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": snapshot_id},
                )
                removed.append(_map_snapshot_row(row))
        return tuple(removed)

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("CREATE SEQUENCE IF NOT EXISTS adcs_snapshot_seq"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS index_snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        product_id TEXT NOT NULL,
                        programming_language TEXT NOT NULL,
                        version TEXT NOT NULL,
                        source_kind TEXT NOT NULL,
                        source_revision TEXT NOT NULL,
                        status TEXT NOT NULL,
                        indexed_chunks_count INTEGER NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_index_snapshots_scope_active
                    ON index_snapshots (
                        product_id,
                        programming_language,
                        version,
                        status,
                        created_at DESC
                    )
                    """
                )
            )


def _map_snapshot_row(row: object) -> SnapshotRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected snapshot row payload."
        raise TypeError(msg)

    status = SnapshotStatus(str(row.get("status")))
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid snapshot created_at value."
        raise TypeError(msg)
    indexed_chunks_count = row.get("indexed_chunks_count")
    if indexed_chunks_count is None:
        msg = "Invalid snapshot indexed_chunks_count value."
        raise TypeError(msg)

    return SnapshotRecord(
        snapshot_id=str(row.get("snapshot_id")),
        product_id=str(row.get("product_id")),
        programming_language=str(row.get("programming_language")),
        version=str(row.get("version")),
        source_kind=str(row.get("source_kind")),
        source_revision=str(row.get("source_revision")),
        status=status,
        indexed_chunks_count=_required_int(
            indexed_chunks_count,
            field_name="indexed_chunks_count",
        ),
        created_at=created_at,
    )


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
