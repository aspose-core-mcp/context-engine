from adcs.indexing.index_models import SnapshotStatus
from adcs.indexing.snapshot_registry import InMemorySnapshotRegistry


def test_source_kinds_survive_publish_promotion_and_rollback():
    registry = InMemorySnapshotRegistry()
    scope = dict(product_id="aspose.words", programming_language="net", version="latest-stable")

    def create(kind):
        return registry.create_snapshot(
            **scope, source_kind=kind, source_revision="test", indexed_chunks_count=1
        )

    docs = create("docs")
    api = create("apiref")
    newer = create("docs")
    assert registry.get_snapshot(docs.snapshot_id).status is SnapshotStatus.INACTIVE
    assert registry.get_snapshot(api.snapshot_id).status is SnapshotStatus.ACTIVE
    registry.rollback_snapshot(
        target_snapshot_id=docs.snapshot_id, expected_active_snapshot_id=newer.snapshot_id
    )
    assert registry.get_snapshot(api.snapshot_id).status is SnapshotStatus.ACTIVE
    registry.promote_snapshot(snapshot_id=newer.snapshot_id)
    assert registry.get_snapshot(api.snapshot_id).status is SnapshotStatus.ACTIVE
    for kind, expected in [("docs", newer), ("apiref", api)]:
        assert (
            registry.get_active_snapshot(**scope, source_kind=kind).snapshot_id
            == expected.snapshot_id
        )
