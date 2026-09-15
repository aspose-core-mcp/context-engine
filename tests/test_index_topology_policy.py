from __future__ import annotations

import json
from pathlib import Path

import pytest

from adcs.indexing.lexical_index_writer import OpenSearchLexicalIndexWriter
from adcs.indexing.topology_policy import (
    CompactionTopologyPolicy,
    IndexTopologyPolicy,
    OpenSearchTopologyPolicy,
    QdrantTopologyPolicy,
    StorageTieringPolicy,
    load_index_topology_policy,
)
from adcs.indexing.vector_index_writer import QdrantVectorIndexWriter


def _custom_policy() -> IndexTopologyPolicy:
    return IndexTopologyPolicy(
        profile="prod",
        qdrant=QdrantTopologyPolicy(
            shard_number=6,
            replication_factor=2,
            write_consistency_factor=2,
        ),
        opensearch=OpenSearchTopologyPolicy(
            number_of_shards=7,
            number_of_replicas=2,
            refresh_interval="15s",
        ),
        compaction=CompactionTopologyPolicy(
            enabled=True,
            max_inactive_snapshots_per_scope=8,
            stale_snapshot_retention_days=180,
        ),
        storage_tiering=StorageTieringPolicy(
            latest_stable_tier="hot",
            archive_tier="warm",
        ),
    )


def test_load_index_topology_policy_reads_profile_values() -> None:
    policy = load_index_topology_policy(
        profile="prod",
        config_path=Path("config/index-topology-policy.json"),
    )

    assert policy.profile == "prod"
    assert policy.qdrant.shard_number == 4
    assert policy.qdrant.replication_factor == 2
    assert policy.opensearch.number_of_shards == 6
    assert policy.opensearch.number_of_replicas == 1
    assert policy.compaction.enabled is True
    assert policy.storage_tiering.archive_tier == "warm"


def test_qdrant_writer_applies_topology_policy_on_collection_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_create_payload: dict[str, object] | None = None

    def _fake_request_json(
        *,
        url: str,
        method: str,
        payload: dict[str, object] | None,
        timeout_seconds: float,
    ) -> tuple[int, object]:
        del timeout_seconds
        nonlocal seen_create_payload
        if method == "GET" and url.endswith("/collections/docs_dense_v1"):
            return 404, {}
        if method == "PUT" and url.endswith("/collections/docs_dense_v1"):
            if payload is not None and "vectors" in payload:
                seen_create_payload = payload
                return 200, {"result": "created"}
            return 200, {"result": {"status": "ok"}}
        if method == "PUT" and url.endswith("/collections/docs_dense_v1/points?wait=true"):
            return 200, {"result": {"status": "completed"}}
        msg = f"Unexpected request: method={method} url={url} payload={payload!r}"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "adcs.indexing.vector_index_writer._request_json",
        _fake_request_json,
    )

    writer = QdrantVectorIndexWriter(
        qdrant_url="http://qdrant.local",
        topology_policy=_custom_policy(),
    )
    writer.write_records(
        source_kind="docs",
        snapshot_id="snap-1",
        records=(
            type(
                "_Record",
                (),
                {
                    "point_id": "point-1",
                    "chunk_id": "chunk-1",
                    "text": "hello",
                    "vector": (0.1, 0.2, 0.3),
                    "snapshot_id": "snap-1",
                    "product_id": "aspose.ocr",
                    "product_family": "aspose",
                    "programming_language": "net",
                    "version": "25.1",
                    "source_kind": "docs",
                    "doc_type": "guide",
                    "doc_locale": "en",
                    "symbol_fqn": None,
                    "title": "Guide",
                    "canonical_url": "https://example.test/guide",
                    "section_anchor": "#intro",
                    "source_revision": "rev-1",
                    "repo_id": "aspose.ocr.docs",
                    "checksum": "sum-1",
                    "executable_snippets": (),
                },
            )(),
        ),
    )

    assert seen_create_payload is not None
    assert seen_create_payload["shard_number"] == 6
    assert seen_create_payload["replication_factor"] == 2
    assert seen_create_payload["write_consistency_factor"] == 2


def test_opensearch_writer_applies_topology_policy_on_index_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_create_payload: dict[str, object] | None = None

    def _fake_request_json(
        *,
        url: str,
        method: str,
        payload: dict[str, object] | None,
        timeout_seconds: float,
        content_type: str,
    ) -> tuple[int, object]:
        del timeout_seconds, content_type
        nonlocal seen_create_payload
        if method == "GET":
            return 404, {}
        if method == "PUT":
            seen_create_payload = payload
            return 200, {"acknowledged": True}
        if method == "POST" and url.endswith("/_aliases"):
            return 200, {"acknowledged": True}
        msg = f"Unexpected request: method={method} url={url} payload={payload!r}"
        raise AssertionError(msg)

    def _fake_request_text(
        *,
        url: str,
        method: str,
        payload: bytes | None,
        timeout_seconds: float,
        content_type: str,
    ) -> tuple[int, str]:
        del url, method, payload, timeout_seconds, content_type
        return 200, json.dumps({"errors": False})

    monkeypatch.setattr(
        "adcs.indexing.lexical_index_writer._request_json",
        _fake_request_json,
    )
    monkeypatch.setattr(
        "adcs.indexing.lexical_index_writer._request_text",
        _fake_request_text,
    )

    writer = OpenSearchLexicalIndexWriter(
        opensearch_url="http://opensearch.local",
        topology_policy=_custom_policy(),
    )
    writer.write_records(
        source_kind="docs",
        snapshot_id="snap-1",
        records=(
            type(
                "_Record",
                (),
                {
                    "chunk_id": "chunk-1",
                    "text": "hello",
                    "snapshot_id": "snap-1",
                    "product_id": "aspose.ocr",
                    "product_family": "aspose",
                    "programming_language": "net",
                    "version": "25.1",
                    "source_kind": "docs",
                    "doc_type": "guide",
                    "doc_locale": "en",
                    "symbol_fqn": None,
                    "title": "Guide",
                    "canonical_url": "https://example.test/guide",
                    "section_anchor": "#intro",
                    "source_revision": "rev-1",
                    "repo_id": "aspose.ocr.docs",
                    "checksum": "sum-1",
                    "executable_snippets": (),
                },
            )(),
        ),
    )

    assert seen_create_payload is not None
    settings = seen_create_payload["settings"]["index"]
    assert settings["number_of_shards"] == 7
    assert settings["number_of_replicas"] == 2
    assert settings["refresh_interval"] == "15s"
