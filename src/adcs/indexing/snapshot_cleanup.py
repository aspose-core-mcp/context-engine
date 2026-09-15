"""Retention-aware snapshot cleanup planning and execution."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from adcs.indexing.index_models import SnapshotRecord, SnapshotStatus
from adcs.indexing.snapshot_registry import SnapshotRegistry
from adcs.indexing.topology_policy import IndexTopologyPolicy

logger = logging.getLogger(__name__)


class VectorIndexPurger(Protocol):
    """Contract for deleting vector points by snapshot_id filter."""

    def purge_snapshot_vectors(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> int:
        """Delete all vector points whose snapshot_id matches any of the given ids.

        Returns total number of points deleted across all collections.
        """


@dataclass(frozen=True, slots=True)
class SnapshotCleanupFilters:
    """Scope filters applied to cleanup preview/execution."""

    product_id: str
    programming_language: str | None = None
    version: str | None = None
    source_kind: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotCleanupProtectedSnapshot:
    """Snapshot kept by cleanup policy with explicit reason."""

    snapshot: SnapshotRecord
    reason: str


@dataclass(frozen=True, slots=True)
class SnapshotCleanupPreview:
    """Deterministic cleanup preview calculated from retention policy."""

    operation_id: str
    filters: SnapshotCleanupFilters
    compaction_enabled: bool
    max_inactive_snapshots_per_scope: int
    stale_snapshot_retention_days: int
    matched_snapshots: tuple[SnapshotRecord, ...]
    delete_candidates: tuple[SnapshotRecord, ...]
    protected_snapshots: tuple[SnapshotCleanupProtectedSnapshot, ...]
    risk_summary: tuple[str, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotCleanupExecutionResult:
    """Snapshot cleanup execution result."""

    preview: SnapshotCleanupPreview
    deleted_snapshots: tuple[SnapshotRecord, ...]


@dataclass(frozen=True, slots=True)
class BulkSnapshotCleanupScopeSummary:
    """Per-scope summary within a bulk cleanup operation."""

    product_id: str
    deleted_count: int
    protected_count: int
    deleted_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkSnapshotCleanupResult:
    """Aggregated result from cross-product bulk snapshot cleanup."""

    operation_id: str
    total_scanned: int
    total_deleted: int
    total_protected: int
    total_vectors_purged: int
    scope_summaries: tuple[BulkSnapshotCleanupScopeSummary, ...]
    compaction_enabled: bool
    max_inactive_snapshots_per_scope: int
    stale_snapshot_retention_days: int
    dry_run: bool
    generated_at: datetime


class SnapshotCleanupService:
    """Build preview and execute snapshot cleanup based on topology policy."""

    def __init__(
        self,
        *,
        snapshot_registry: SnapshotRegistry,
        topology_policy: IndexTopologyPolicy,
    ) -> None:
        self._snapshot_registry = snapshot_registry
        self._topology_policy = topology_policy

    def preview(
        self,
        *,
        filters: SnapshotCleanupFilters,
        now: datetime | None = None,
    ) -> SnapshotCleanupPreview:
        preview_now = now or datetime.now(tz=UTC)
        matched_snapshots = tuple(
            snapshot
            for snapshot in self._snapshot_registry.list_snapshots(
                product_id=filters.product_id,
                programming_language=filters.programming_language,
                version=filters.version,
            )
            if filters.source_kind is None or snapshot.source_kind == filters.source_kind
        )
        delete_candidates, protected_snapshots = self._classify_snapshots(
            matched_snapshots=matched_snapshots,
            generated_at=preview_now,
        )
        return SnapshotCleanupPreview(
            operation_id=f"cln-op-{uuid4().hex[:12]}",
            filters=filters,
            compaction_enabled=self._topology_policy.compaction.enabled,
            max_inactive_snapshots_per_scope=(
                self._topology_policy.compaction.max_inactive_snapshots_per_scope
            ),
            stale_snapshot_retention_days=(
                self._topology_policy.compaction.stale_snapshot_retention_days
            ),
            matched_snapshots=matched_snapshots,
            delete_candidates=delete_candidates,
            protected_snapshots=protected_snapshots,
            risk_summary=self._build_risk_summary(
                filters=filters,
                delete_candidates=delete_candidates,
                protected_snapshots=protected_snapshots,
            ),
            generated_at=preview_now,
        )

    def execute(
        self,
        *,
        filters: SnapshotCleanupFilters,
        now: datetime | None = None,
    ) -> SnapshotCleanupExecutionResult:
        preview = self.preview(filters=filters, now=now)
        deleted_snapshots = self._snapshot_registry.delete_snapshots(
            snapshot_ids=tuple(snapshot.snapshot_id for snapshot in preview.delete_candidates)
        )
        return SnapshotCleanupExecutionResult(
            preview=preview,
            deleted_snapshots=deleted_snapshots,
        )

    def bulk_cleanup(
        self,
        *,
        dry_run: bool = True,
        purge_vectors: bool = False,
        vector_purger: VectorIndexPurger | None = None,
        now: datetime | None = None,
    ) -> BulkSnapshotCleanupResult:
        """Run retention-based cleanup across ALL products and scopes.

        Iterates every distinct product_id in the snapshot registry, applies
        the compaction policy, deletes excess inactive snapshots from the
        registry, and optionally purges orphaned vectors from Qdrant.

        Args:
            dry_run: If True, compute what would be deleted but do not mutate.
            purge_vectors: If True and not dry_run, delete Qdrant vectors for
                removed snapshot_ids via the vector_purger.
            vector_purger: Optional adapter for Qdrant vector deletion.
            now: Override current time for deterministic testing.
        """
        cleanup_now = now or datetime.now(tz=UTC)
        operation_id = f"bulk-cln-{uuid4().hex[:12]}"

        all_snapshots = self._snapshot_registry.list_snapshots()
        product_ids = sorted({snap.product_id for snap in all_snapshots})

        scope_summaries: list[BulkSnapshotCleanupScopeSummary] = []
        total_deleted = 0
        total_protected = 0
        all_deleted_snapshot_ids: list[str] = []

        for product_id in product_ids:
            filters = SnapshotCleanupFilters(product_id=product_id)
            preview = self.preview(filters=filters, now=cleanup_now)

            if not preview.delete_candidates:
                scope_summaries.append(
                    BulkSnapshotCleanupScopeSummary(
                        product_id=product_id,
                        deleted_count=0,
                        protected_count=len(preview.protected_snapshots),
                        deleted_snapshot_ids=(),
                    )
                )
                total_protected += len(preview.protected_snapshots)
                continue

            deleted_ids: tuple[str, ...]
            deleted_count: int
            if dry_run:
                deleted_ids = tuple(
                    snap.snapshot_id for snap in preview.delete_candidates
                )
                deleted_count = len(deleted_ids)
            else:
                deleted_snapshots = self._snapshot_registry.delete_snapshots(
                    snapshot_ids=tuple(
                        snap.snapshot_id for snap in preview.delete_candidates
                    )
                )
                deleted_ids = tuple(snap.snapshot_id for snap in deleted_snapshots)
                deleted_count = len(deleted_snapshots)

            logger.info(
                "Bulk cleanup scope product_id=%s: %d deleted, %d protected%s",
                product_id,
                deleted_count,
                len(preview.protected_snapshots),
                " (dry_run)" if dry_run else "",
            )

            all_deleted_snapshot_ids.extend(deleted_ids)
            total_deleted += deleted_count
            total_protected += len(preview.protected_snapshots)
            scope_summaries.append(
                BulkSnapshotCleanupScopeSummary(
                    product_id=product_id,
                    deleted_count=deleted_count,
                    protected_count=len(preview.protected_snapshots),
                    deleted_snapshot_ids=deleted_ids,
                )
            )

        total_vectors_purged = 0
        if (
            not dry_run
            and purge_vectors
            and vector_purger is not None
            and all_deleted_snapshot_ids
        ):
            logger.info(
                "Purging Qdrant vectors for %d deleted snapshot ids",
                len(all_deleted_snapshot_ids),
            )
            total_vectors_purged = vector_purger.purge_snapshot_vectors(
                snapshot_ids=tuple(all_deleted_snapshot_ids),
            )
            logger.info("Purged %d Qdrant vector points", total_vectors_purged)

        return BulkSnapshotCleanupResult(
            operation_id=operation_id,
            total_scanned=len(all_snapshots),
            total_deleted=total_deleted,
            total_protected=total_protected,
            total_vectors_purged=total_vectors_purged,
            scope_summaries=tuple(scope_summaries),
            compaction_enabled=self._topology_policy.compaction.enabled,
            max_inactive_snapshots_per_scope=(
                self._topology_policy.compaction.max_inactive_snapshots_per_scope
            ),
            stale_snapshot_retention_days=(
                self._topology_policy.compaction.stale_snapshot_retention_days
            ),
            dry_run=dry_run,
            generated_at=cleanup_now,
        )

    def _classify_snapshots(
        self,
        *,
        matched_snapshots: tuple[SnapshotRecord, ...],
        generated_at: datetime,
    ) -> tuple[tuple[SnapshotRecord, ...], tuple[SnapshotCleanupProtectedSnapshot, ...]]:
        if not self._topology_policy.compaction.enabled:
            return (), tuple(
                SnapshotCleanupProtectedSnapshot(
                    snapshot=snapshot,
                    reason="compaction_disabled",
                )
                for snapshot in matched_snapshots
            )

        delete_candidates: list[SnapshotRecord] = []
        protected_snapshots: list[SnapshotCleanupProtectedSnapshot] = []
        grouped_inactive: dict[
            tuple[str, str, str, str],
            list[SnapshotRecord],
        ] = defaultdict(list)

        for snapshot in matched_snapshots:
            if snapshot.status is SnapshotStatus.ACTIVE:
                protected_snapshots.append(
                    SnapshotCleanupProtectedSnapshot(
                        snapshot=snapshot,
                        reason="active_snapshot",
                    )
                )
                continue
            group_key = (
                snapshot.product_id,
                snapshot.programming_language,
                snapshot.version,
                snapshot.source_kind,
            )
            grouped_inactive[group_key].append(snapshot)

        max_inactive = self._topology_policy.compaction.max_inactive_snapshots_per_scope
        stale_days = self._topology_policy.compaction.stale_snapshot_retention_days

        for scope_snapshots in grouped_inactive.values():
            ordered = sorted(
                scope_snapshots,
                key=lambda item: (item.created_at, item.snapshot_id),
                reverse=True,
            )
            for index, snapshot in enumerate(ordered):
                snapshot_age_days = max(
                    0,
                    int((generated_at - snapshot.created_at).total_seconds() // 86_400),
                )
                should_delete = index >= max_inactive or snapshot_age_days >= stale_days
                if should_delete:
                    delete_candidates.append(snapshot)
                    continue
                reason = (
                    "retained_recent_slot"
                    if index < max_inactive
                    else "within_retention_window"
                )
                protected_snapshots.append(
                    SnapshotCleanupProtectedSnapshot(snapshot=snapshot, reason=reason)
                )

        delete_candidates.sort(key=lambda item: (item.created_at, item.snapshot_id))
        protected_snapshots.sort(
            key=lambda item: (item.snapshot.created_at, item.snapshot.snapshot_id)
        )
        return tuple(delete_candidates), tuple(protected_snapshots)

    def _build_risk_summary(
        self,
        *,
        filters: SnapshotCleanupFilters,
        delete_candidates: tuple[SnapshotRecord, ...],
        protected_snapshots: tuple[SnapshotCleanupProtectedSnapshot, ...],
    ) -> tuple[str, ...]:
        messages: list[str] = [
            "Active snapshots are excluded from cleanup by policy.",
        ]
        if not self._topology_policy.compaction.enabled:
            messages.append("Compaction policy is disabled in the current runtime profile.")
            return tuple(messages)
        if not delete_candidates:
            messages.append("No inactive snapshots currently exceed the retention policy.")
        else:
            messages.append(
                f"{len(delete_candidates)} inactive snapshot(s) are eligible for deletion."
            )
        if filters.programming_language is None or filters.version is None:
            messages.append(
                "Broad filters may affect multiple SDK languages or versions "
                "inside the selected product."
            )
        if filters.source_kind is None:
            messages.append(
                "Cleanup preview spans both documentation and API reference "
                "snapshots for this scope."
            )
        protected_active = sum(
            1 for item in protected_snapshots if item.reason == "active_snapshot"
        )
        messages.append(
            f"{protected_active} active snapshot(s) remain protected after cleanup."
        )
        return tuple(messages)
