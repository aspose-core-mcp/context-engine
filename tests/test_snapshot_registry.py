from __future__ import annotations

from adcs.indexing.index_models import SnapshotStatus
from adcs.indexing.snapshot_registry import (
    InMemorySnapshotRegistry,
    SnapshotRollbackConflictError,
)


def test_snapshot_registry_keeps_multiple_versions_and_resolves_active() -> None:
    registry = InMemorySnapshotRegistry()

    first = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-aaa111",
        indexed_chunks_count=4,
    )
    second = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-bbb222",
        indexed_chunks_count=5,
    )

    assert first.snapshot_id == "snap-00000001"
    assert second.snapshot_id == "snap-00000002"

    active = registry.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    assert active is not None
    assert active.snapshot_id == second.snapshot_id
    assert active.status is SnapshotStatus.ACTIVE

    all_snapshots = registry.list_snapshots(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    assert [snapshot.snapshot_id for snapshot in all_snapshots] == [
        first.snapshot_id,
        second.snapshot_id,
    ]
    assert all_snapshots[0].status is SnapshotStatus.INACTIVE
    assert all_snapshots[1].status is SnapshotStatus.ACTIVE


def test_snapshot_registry_can_promote_existing_snapshot() -> None:
    registry = InMemorySnapshotRegistry()
    first = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-aaa111",
        indexed_chunks_count=4,
    )
    second = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-bbb222",
        indexed_chunks_count=5,
    )

    promoted = registry.promote_snapshot(snapshot_id=first.snapshot_id)
    assert promoted is not None
    assert promoted.snapshot_id == first.snapshot_id
    assert promoted.status is SnapshotStatus.ACTIVE

    active = registry.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    assert active is not None
    assert active.snapshot_id == first.snapshot_id

    snapshots = registry.list_snapshots(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    assert by_id[first.snapshot_id].status is SnapshotStatus.ACTIVE
    assert by_id[second.snapshot_id].status is SnapshotStatus.INACTIVE


def test_snapshot_registry_can_rollback_to_previous_active_snapshot() -> None:
    registry = InMemorySnapshotRegistry()
    first = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-aaa111",
        indexed_chunks_count=4,
    )
    second = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-bbb222",
        indexed_chunks_count=5,
    )

    outcome = registry.rollback_snapshot(
        target_snapshot_id=first.snapshot_id,
        expected_active_snapshot_id=second.snapshot_id,
    )

    assert outcome is not None
    assert outcome.target_snapshot.snapshot_id == first.snapshot_id
    assert outcome.target_snapshot.status is SnapshotStatus.ACTIVE
    assert outcome.previous_active_snapshot.snapshot_id == second.snapshot_id
    assert outcome.previous_active_snapshot.status is SnapshotStatus.INACTIVE
    active = registry.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    assert active is not None
    assert active.snapshot_id == first.snapshot_id


def test_snapshot_registry_rollback_conflict_preserves_state() -> None:
    registry = InMemorySnapshotRegistry()
    first = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-aaa111",
        indexed_chunks_count=4,
    )
    second = registry.create_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        source_revision="revision-bbb222",
        indexed_chunks_count=5,
    )

    try:
        registry.rollback_snapshot(
            target_snapshot_id=first.snapshot_id,
            expected_active_snapshot_id="snap-incorrect",
        )
    except SnapshotRollbackConflictError as exc:
        assert exc.code == "ACTIVE_SNAPSHOT_CHANGED"
        assert exc.expected_active_snapshot_id == "snap-incorrect"
        assert exc.current_active_snapshot_id == second.snapshot_id
    else:
        raise AssertionError("Expected SnapshotRollbackConflictError was not raised.")

    active = registry.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    )
    assert active is not None
    assert active.snapshot_id == second.snapshot_id
    assert active.status is SnapshotStatus.ACTIVE
