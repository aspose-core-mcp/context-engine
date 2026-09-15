from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from adcs.indexing import (
    InMemorySnapshotRegistry,
    InMemoryVectorIndexPurger,
    SnapshotCleanupFilters,
    SnapshotCleanupService,
)
from adcs.indexing.topology_policy import (
    CompactionTopologyPolicy,
    IndexTopologyPolicy,
    OpenSearchTopologyPolicy,
    QdrantTopologyPolicy,
    StorageTieringPolicy,
)


def _policy(*, max_inactive: int = 1, stale_days: int = 30) -> IndexTopologyPolicy:
    return IndexTopologyPolicy(
        profile="dev",
        qdrant=QdrantTopologyPolicy(),
        opensearch=OpenSearchTopologyPolicy(),
        compaction=CompactionTopologyPolicy(
            enabled=True,
            max_inactive_snapshots_per_scope=max_inactive,
            stale_snapshot_retention_days=stale_days,
        ),
        storage_tiering=StorageTieringPolicy(),
    )


def test_snapshot_cleanup_preview_protects_active_and_selects_old_inactive() -> None:
    registry = InMemorySnapshotRegistry()
    first = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    second = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    third = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-3",
        indexed_chunks_count=14,
    )
    registry.promote_snapshot(snapshot_id=first.snapshot_id)
    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=_policy(max_inactive=1, stale_days=30),
    )

    preview = cleanup_service.preview(
        filters=SnapshotCleanupFilters(
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="docs",
        ),
        now=datetime.now(tz=UTC) + timedelta(days=1),
    )

    protected_ids = {item.snapshot.snapshot_id for item in preview.protected_snapshots}
    candidate_ids = {item.snapshot_id for item in preview.delete_candidates}
    assert first.snapshot_id in protected_ids
    assert third.snapshot_id in protected_ids
    assert second.snapshot_id in candidate_ids


def test_snapshot_cleanup_execute_deletes_only_candidates() -> None:
    registry = InMemorySnapshotRegistry()
    active = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    stale = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    registry.promote_snapshot(snapshot_id=active.snapshot_id)
    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=_policy(max_inactive=1, stale_days=1),
    )
    stale_snapshot = registry.get_snapshot(stale.snapshot_id)
    assert stale_snapshot is not None
    registry._snapshots[stale.snapshot_id] = replace(
        stale_snapshot,
        created_at=datetime.now(tz=UTC) - timedelta(days=10),
    )

    result = cleanup_service.execute(
        filters=SnapshotCleanupFilters(
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="docs",
        ),
        now=datetime.now(tz=UTC),
    )

    assert [item.snapshot_id for item in result.deleted_snapshots] == [stale.snapshot_id]
    assert registry.get_snapshot(stale.snapshot_id) is None
    assert registry.get_snapshot(active.snapshot_id) is not None


def test_bulk_cleanup_dry_run_does_not_delete() -> None:
    registry = InMemorySnapshotRegistry()
    registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    stale = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    registry.create_snapshot(
        product_id="aspose.pdf",
        programming_language="java",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=5,
    )
    second_stale = registry.create_snapshot(
        product_id="aspose.pdf",
        programming_language="java",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=6,
    )

    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=_policy(max_inactive=0, stale_days=0),
    )

    result = cleanup_service.bulk_cleanup(
        dry_run=True,
        now=datetime.now(tz=UTC) + timedelta(days=1),
    )

    assert result.dry_run is True
    assert result.total_deleted >= 2
    # Snapshots are still present because dry_run=True
    assert registry.get_snapshot(stale.snapshot_id) is not None
    assert registry.get_snapshot(second_stale.snapshot_id) is not None


def test_bulk_cleanup_execute_deletes_across_products() -> None:
    registry = InMemorySnapshotRegistry()
    ocr_active = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    ocr_stale = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    # Promote first so second is inactive
    registry.promote_snapshot(snapshot_id=ocr_active.snapshot_id)

    pdf_active = registry.create_snapshot(
        product_id="aspose.pdf",
        programming_language="java",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=5,
    )
    pdf_stale = registry.create_snapshot(
        product_id="aspose.pdf",
        programming_language="java",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=6,
    )
    registry.promote_snapshot(snapshot_id=pdf_active.snapshot_id)

    # Make stale snapshots old
    for snap_id in [ocr_stale.snapshot_id, pdf_stale.snapshot_id]:
        snap = registry.get_snapshot(snap_id)
        assert snap is not None
        registry._snapshots[snap_id] = replace(
            snap,
            created_at=datetime.now(tz=UTC) - timedelta(days=60),
        )

    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=_policy(max_inactive=1, stale_days=30),
    )

    result = cleanup_service.bulk_cleanup(
        dry_run=False,
        now=datetime.now(tz=UTC),
    )

    assert result.dry_run is False
    assert result.total_deleted == 2
    assert registry.get_snapshot(ocr_stale.snapshot_id) is None
    assert registry.get_snapshot(pdf_stale.snapshot_id) is None
    assert registry.get_snapshot(ocr_active.snapshot_id) is not None
    assert registry.get_snapshot(pdf_active.snapshot_id) is not None

    # Check scope summaries
    product_ids = {s.product_id for s in result.scope_summaries}
    assert "aspose.ocr" in product_ids
    assert "aspose.pdf" in product_ids


def test_bulk_cleanup_with_vector_purge() -> None:
    registry = InMemorySnapshotRegistry()
    active = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    stale = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )
    registry.promote_snapshot(snapshot_id=active.snapshot_id)

    snap = registry.get_snapshot(stale.snapshot_id)
    assert snap is not None
    registry._snapshots[stale.snapshot_id] = replace(
        snap,
        created_at=datetime.now(tz=UTC) - timedelta(days=60),
    )

    purger = InMemoryVectorIndexPurger()
    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=_policy(max_inactive=1, stale_days=30),
    )

    result = cleanup_service.bulk_cleanup(
        dry_run=False,
        purge_vectors=True,
        vector_purger=purger,
        now=datetime.now(tz=UTC),
    )

    assert result.total_deleted == 1
    assert result.total_vectors_purged > 0
    assert stale.snapshot_id in purger.purged_snapshot_ids


def test_bulk_cleanup_no_deletes_when_compaction_disabled() -> None:
    registry = InMemorySnapshotRegistry()
    registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-1",
        indexed_chunks_count=10,
    )
    registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="rev-2",
        indexed_chunks_count=12,
    )

    disabled_policy = IndexTopologyPolicy(
        profile="dev",
        qdrant=QdrantTopologyPolicy(),
        opensearch=OpenSearchTopologyPolicy(),
        compaction=CompactionTopologyPolicy(enabled=False),
        storage_tiering=StorageTieringPolicy(),
    )
    cleanup_service = SnapshotCleanupService(
        snapshot_registry=registry,
        topology_policy=disabled_policy,
    )

    result = cleanup_service.bulk_cleanup(dry_run=False)

    assert result.total_deleted == 0
    assert result.compaction_enabled is False
