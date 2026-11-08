from __future__ import annotations

import json
from pathlib import Path

import pytest

from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import (
    NormalizedChunk,
    NormalizedCitation,
    NormalizedDocument,
    NormalizedDocumentMetadata,
)
from adcs.ingestion.staging_store import (
    CanonicalStagingSnapshotIntegrityError,
    FileSystemCanonicalStagingStore,
    StagingSnapshotTier,
)


def _make_normalized_document(source_path: str) -> NormalizedDocument:
    return NormalizedDocument(
        schema="adcs.normalized_document.v1",
        document=NormalizedDocumentMetadata(
            repo_id="aspose.ocr.docs",
            product_id="aspose.ocr",
            product_family="aspose",
            source_kind="docs",
            programming_language="net",
            doc_locale="english",
            version="latest-stable",
            title=Path(source_path).stem,
            doc_type="guide_overview",
            canonical_url=f"https://docs.aspose.com/{Path(source_path).stem}/",
            source_path=source_path,
            source_revision="revision-abc123",
        ),
        chunks=(
            NormalizedChunk(
                chunk_key=f"{source_path}:main",
                section_path=("Overview",),
                section_anchor="#overview",
                chunk_type="guide_overview",
                text="Overview text.",
                citations=(
                    NormalizedCitation(
                        canonical_url=f"https://docs.aspose.com/{Path(source_path).stem}/",
                        source_path=source_path,
                        title="Overview",
                        section_anchor="#overview",
                    ),
                ),
                title="Overview",
                canonical_url=f"https://docs.aspose.com/{Path(source_path).stem}/",
            ),
        ),
        warnings=(),
    )


def _make_chunk_record(source_path: str, chunk_id: str) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        version="latest-stable",
        source_kind="docs",
        doc_locale="english",
        doc_type="guide_overview",
        symbol_fqn=None,
        title="Overview",
        section_path=("Overview",),
        canonical_url=f"https://docs.aspose.com/{Path(source_path).stem}/",
        section_anchor="#overview",
        source_path=source_path,
        source_revision="revision-abc123",
        is_deprecated=False,
        has_code_example=False,
        chunk_type="guide_overview",
        text="Overview text.",
        tokens=42,
        checksum=f"checksum-{chunk_id}",
    )


def test_staging_store_writes_deterministic_repository_manifest(tmp_path: Path) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_paths = (
        "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
        "source-repo-docs/Aspose.OCR/english/net/getting-started/install.md",
    )
    payload = {
        "repo_id": "aspose.ocr.docs",
        "source_kind": "docs",
        "source_revision": "revision-abc123",
        "file_checksums": {source_paths[0]: "a" * 64, source_paths[1]: "b" * 64},
        "canonical_documents": tuple(_make_normalized_document(path) for path in source_paths),
        "chunk_records": (
            _make_chunk_record(source_paths[0], "chunk-1"),
            _make_chunk_record(source_paths[1], "chunk-2"),
        ),
    }

    first = store.write_repository_snapshot(**payload)
    first_manifest_path = tmp_path / first.repository_manifest_path
    first_manifest_payload = json.loads(first_manifest_path.read_text(encoding="utf-8"))

    second = store.write_repository_snapshot(**payload)
    second_manifest_path = tmp_path / second.repository_manifest_path
    second_manifest_payload = json.loads(second_manifest_path.read_text(encoding="utf-8"))

    assert first.repository_manifest_path == second.repository_manifest_path
    assert first_manifest_payload == second_manifest_payload
    assert first.documents_count == 2
    assert first.chunk_records_count == 2
    assert first.scope_summaries
    scope_manifest_path = tmp_path / first.scope_summaries[0].manifest_path
    assert scope_manifest_path.exists()
    assert (
        "data-docs/aspose.ocr/net/latest-stable/english"
        in first.scope_summaries[0].manifest_path
    )


def test_staging_store_loads_replay_snapshot_by_revision(tmp_path: Path) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_path = "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md"
    store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums={source_path: "a" * 64},
        canonical_documents=(_make_normalized_document(source_path),),
        chunk_records=(_make_chunk_record(source_path, "chunk-1"),),
    )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
    )
    assert snapshot is not None
    assert snapshot.repo_id == "aspose.ocr.docs"
    assert snapshot.source_revision == "revision-abc123"
    assert len(snapshot.file_checksums) == 1
    assert len(snapshot.canonical_documents) == 1
    assert len(snapshot.chunk_records) == 1
    assert snapshot.scope_summaries

    missing_revision = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-other",
    )
    assert missing_revision is None


def test_staging_store_resolves_revision_across_multiple_manifest_candidates(
    tmp_path: Path,
) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    first_manifest = (
        tmp_path
        / "data-docs"
        / "aaa"
        / "_repo-staging"
        / "aspose.ocr.docs"
        / "repository-manifest.json"
    )
    second_manifest = (
        tmp_path
        / "data-docs"
        / "zzz"
        / "_repo-staging"
        / "aspose.ocr.docs"
        / "repository-manifest.json"
    )
    first_manifest.parent.mkdir(parents=True, exist_ok=True)
    second_manifest.parent.mkdir(parents=True, exist_ok=True)

    first_manifest.write_text(
        json.dumps(
            {
                "schema_version": "adcs.canonical_staging.v1",
                "repo_id": "aspose.ocr.docs",
                "source_kind": "docs",
                "source_revision": "revision-old",
                "repository_manifest_path": str(first_manifest.relative_to(tmp_path)),
                "scope_manifests": [],
                "file_checksums": {},
                "documents": [],
                "chunk_objects": [],
                "documents_count": 0,
                "chunk_records_count": 0,
            }
        ),
        encoding="utf-8",
    )
    second_manifest.write_text(
        json.dumps(
            {
                "schema_version": "adcs.canonical_staging.v1",
                "repo_id": "aspose.ocr.docs",
                "source_kind": "docs",
                "source_revision": "revision-target",
                "repository_manifest_path": str(second_manifest.relative_to(tmp_path)),
                "scope_manifests": [],
                "file_checksums": {},
                "documents": [],
                "chunk_objects": [],
                "documents_count": 0,
                "chunk_records_count": 0,
            }
        ),
        encoding="utf-8",
    )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-target",
    )
    assert snapshot is not None
    assert snapshot.source_revision == "revision-target"


def test_staging_store_rejects_outside_workspace_manifest_pointers(tmp_path: Path) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_path = "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md"
    write_result = store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums={source_path: "a" * 64},
        canonical_documents=(_make_normalized_document(source_path),),
        chunk_records=(_make_chunk_record(source_path, "chunk-1"),),
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )

    manifest_path = tmp_path / write_result.repository_manifest_path
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    outside_path = tmp_path.parent / "outside-doc.json"
    outside_path.write_text("{}", encoding="utf-8")
    payload["documents"][0]["document_path"] = str(outside_path)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CanonicalStagingSnapshotIntegrityError) as exc_info:
        store.load_repository_snapshot(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
        )
    assert "outside_workspace" in str(exc_info.value)


# --- Streaming write/read APIs -------------------------------------------


def test_streaming_writer_round_trip_matches_batch_write(tmp_path: Path) -> None:
    """Streaming writer + iter_* should produce the same canonical_documents
    and chunk_records as a single batch write_repository_snapshot.
    """
    source_paths = (
        "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
        "source-repo-docs/Aspose.OCR/english/net/getting-started/install.md",
        "source-repo-docs/Aspose.OCR/english/net/getting-started/quickstart.md",
    )
    file_checksums = {p: f"{i:0>64}" for i, p in enumerate(source_paths)}
    docs = [_make_normalized_document(p) for p in source_paths]
    chunks_by_path = {p: [_make_chunk_record(p, f"chunk-{p}")] for p in source_paths}

    # Reference: batch write
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    batch_store = FileSystemCanonicalStagingStore(workspace_root=batch_dir)
    batch_result = batch_store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums=file_checksums,
        canonical_documents=tuple(docs),
        chunk_records=tuple(c for cs in chunks_by_path.values() for c in cs),
    )

    # Subject under test: streaming write
    stream_dir = tmp_path / "stream"
    stream_dir.mkdir()
    stream_store = FileSystemCanonicalStagingStore(workspace_root=stream_dir)
    with stream_store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
    ) as writer:
        for source_path, checksum in file_checksums.items():
            writer.set_file_checksum(source_path, checksum)
        for doc in docs:
            writer.append_document(
                canonical_document=doc,
                chunk_records=chunks_by_path[doc.document.source_path],
            )

    # Compare manifest counts + structure
    batch_manifest = json.loads(
        (batch_dir / batch_result.repository_manifest_path).read_text(encoding="utf-8")
    )
    streamed_canonical = list(
        stream_store.iter_canonical_documents(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
        )
    )
    streamed_chunks = list(
        stream_store.iter_chunk_records(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
        )
    )

    assert len(streamed_canonical) == len(docs) == batch_manifest["documents_count"]
    assert len(streamed_chunks) == sum(len(cs) for cs in chunks_by_path.values())
    assert {d.document.source_path for d in streamed_canonical} == set(source_paths)
    assert {c.source_path for c in streamed_chunks} == set(source_paths)


def test_streaming_writer_finalises_on_context_exit(tmp_path: Path) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_path = "source-repo-docs/Aspose.OCR/english/net/_index.md"
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
    ) as writer:
        writer.set_file_checksum(source_path, "a" * 64)
        writer.append_document(
            canonical_document=_make_normalized_document(source_path),
            chunk_records=[_make_chunk_record(source_path, "chunk-1")],
        )
    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
    )
    assert snapshot is not None
    assert len(snapshot.canonical_documents) == 1
    assert len(snapshot.chunk_records) == 1


def test_streaming_writer_merges_with_previous_publish_snapshot(tmp_path: Path) -> None:
    """An incremental streaming write that only touches one file should
    still produce a manifest containing the other previously-published
    documents (so partial re-ingest doesn't drop unchanged docs).
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_paths = (
        "source-repo-docs/Aspose.OCR/english/net/a.md",
        "source-repo-docs/Aspose.OCR/english/net/b.md",
    )
    store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums={p: f"{i:0>64}" for i, p in enumerate(source_paths)},
        canonical_documents=tuple(_make_normalized_document(p) for p in source_paths),
        chunk_records=tuple(_make_chunk_record(p, f"chunk-{p}") for p in source_paths),
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )

    # Now stream-write only the FIRST file with a new revision.
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) as writer:
        for p, i in zip(source_paths, range(len(source_paths)), strict=True):
            writer.set_file_checksum(p, f"{i:0>64}")
        writer.append_document(
            canonical_document=_make_normalized_document(source_paths[0]),
            chunk_records=[_make_chunk_record(source_paths[0], "chunk-new")],
        )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
    )
    assert snapshot is not None
    # Both source paths should be represented — first via the streaming
    # append, second carried forward from the prior publish snapshot.
    assert {d.document.source_path for d in snapshot.canonical_documents} == set(
        source_paths
    )


def test_write_publish_snapshot_from_review_round_trips(tmp_path: Path) -> None:
    """Promote a REVIEW snapshot to PUBLISH by re-streaming from disk
    (no whole-repo materialisation), producing a complete, readable PUBLISH
    snapshot identical in content to the REVIEW input.
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_paths = (
        "source-repo-docs/Aspose.OCR/english/net/a.md",
        "source-repo-docs/Aspose.OCR/english/net/b.md",
        "source-repo-docs/Aspose.OCR/english/net/c.md",
    )
    file_checksums = {p: f"{i:0>64}" for i, p in enumerate(source_paths)}
    docs = [_make_normalized_document(p) for p in source_paths]
    chunks_by_path = {p: [_make_chunk_record(p, f"chunk-{p}")] for p in source_paths}

    # 1. Build a REVIEW snapshot via the streaming writer (parse-loop shape).
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.REVIEW,
        operation_id="op-1",
    ) as writer:
        for source_path, checksum in file_checksums.items():
            writer.set_file_checksum(source_path, checksum)
        for doc in docs:
            writer.append_document(
                canonical_document=doc,
                chunk_records=chunks_by_path[doc.document.source_path],
            )

    # 2. Promote REVIEW -> PUBLISH by streaming (subject under test).
    result = store.write_publish_snapshot_from_review(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums=file_checksums,
        operation_id="op-1",
    )

    assert result.snapshot_tier == StagingSnapshotTier.PUBLISH.value
    assert result.documents_count == len(source_paths)
    pub_docs = list(
        store.iter_canonical_documents(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )
    )
    pub_chunks = list(
        store.iter_chunk_records(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )
    )
    assert {d.document.source_path for d in pub_docs} == set(source_paths)
    assert {c.source_path for c in pub_chunks} == set(source_paths)


def test_write_publish_snapshot_from_review_promotes_chunks_without_documents(
    tmp_path: Path,
) -> None:
    """apiref-shape REVIEW snapshots have chunk files with NO 1:1 document
    (namespace-page documents are skipped). The promotion must carry every
    chunk into PUBLISH — coupling chunks to documents would drop them all.
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_paths = (
        "source-repo-apiref/Aspose.Cells/english/net/a.md",
        "source-repo-apiref/Aspose.Cells/english/net/b.md",
    )
    file_checksums = {p: f"{i:0>64}" for i, p in enumerate(source_paths)}
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.REVIEW,
        operation_id="op-3",
    ) as writer:
        for source_path, checksum in file_checksums.items():
            writer.set_file_checksum(source_path, checksum)
            # Chunks only — no append_document (apiref symbol/namespace shape).
            writer.append_chunks(
                source_path=source_path,
                chunk_records=[_make_chunk_record(source_path, f"chunk-{source_path}")],
            )

    result = store.write_publish_snapshot_from_review(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums=file_checksums,
        operation_id="op-3",
    )

    pub_chunks = list(
        store.iter_chunk_records(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )
    )
    assert {c.source_path for c in pub_chunks} == set(source_paths)
    assert result.chunk_records_count == len(source_paths)


def test_write_publish_snapshot_from_review_replaces_not_merges(tmp_path: Path) -> None:
    """Full-reindex semantics: the promotion must NOT carry forward documents
    from a prior PUBLISH snapshot (it replaces wholesale, unlike the
    incremental streaming-writer merge).
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    old_paths = (
        "source-repo-docs/Aspose.OCR/english/net/a.md",
        "source-repo-docs/Aspose.OCR/english/net/b.md",
    )
    store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums={p: f"{i:0>64}" for i, p in enumerate(old_paths)},
        canonical_documents=tuple(_make_normalized_document(p) for p in old_paths),
        chunk_records=tuple(_make_chunk_record(p, f"c-{p}") for p in old_paths),
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )

    # REVIEW snapshot for THIS run touches only a.md (full reindex of fewer files).
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.REVIEW,
        operation_id="op-2",
    ) as writer:
        writer.set_file_checksum(old_paths[0], "0" * 64)
        writer.append_document(
            canonical_document=_make_normalized_document(old_paths[0]),
            chunk_records=[_make_chunk_record(old_paths[0], "c-new")],
        )

    store.write_publish_snapshot_from_review(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        file_checksums={old_paths[0]: "0" * 64},
        operation_id="op-2",
    )

    pub_docs = list(
        store.iter_canonical_documents(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )
    )
    # b.md must be DROPPED — full reindex replaces, it does not merge.
    assert {d.document.source_path for d in pub_docs} == {old_paths[0]}


def test_streaming_writer_incremental_merge_carries_chunks_and_documents(
    tmp_path: Path,
) -> None:
    """Variant 2 keystone: close(skip_previous_merge=False) must carry forward an
    unchanged file's DOCUMENT *and its CHUNKS* from the prior PUBLISH snapshot —
    today it carries documents only, silently dropping unchanged chunks. A removed
    file (absent from file_checksums) must be dropped entirely.
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    paths = (
        "source-repo-docs/Aspose.OCR/english/net/a.md",
        "source-repo-docs/Aspose.OCR/english/net/b.md",
        "source-repo-docs/Aspose.OCR/english/net/c.md",
    )
    store.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="rev",
        file_checksums={p: f"{i:0>64}" for i, p in enumerate(paths)},
        canonical_documents=tuple(_make_normalized_document(p) for p in paths),
        chunk_records=tuple(_make_chunk_record(p, f"c-{p}") for p in paths),
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )

    # Incremental run: only a.md re-emitted; b.md unchanged; c.md REMOVED
    # (not in file_checksums).
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="rev",
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) as writer:
        writer.set_file_checksum(paths[0], "a" * 64)
        writer.set_file_checksum(paths[1], f"{1:0>64}")
        writer.append_document(
            canonical_document=_make_normalized_document(paths[0]),
            chunk_records=[_make_chunk_record(paths[0], "c-a-new")],
        )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="rev",
    )
    assert snapshot is not None
    # a re-emitted + b carried forward; c dropped (removed).
    assert {d.document.source_path for d in snapshot.canonical_documents} == {
        paths[0],
        paths[1],
    }
    # THE FIX: b.md's CHUNKS are carried forward (not just its document).
    assert {c.source_path for c in snapshot.chunk_records} == {paths[0], paths[1]}


def test_incremental_streaming_publish_matches_legacy(tmp_path: Path) -> None:
    """Variant 2 master gate: the streaming incremental PUBLISH
    (write_publish_snapshot_from_review skip_previous_merge=False) must produce the
    SAME document+chunk set as the legacy whole-RAM write_repository_snapshot, for
    a changed/unchanged/removed file mix.
    """
    a, b, c = (
        "source-repo-docs/Aspose.OCR/english/net/a.md",
        "source-repo-docs/Aspose.OCR/english/net/b.md",
        "source-repo-docs/Aspose.OCR/english/net/c.md",
    )
    prior_checksums = {a: "0" * 64, b: "1" * 64, c: "2" * 64}
    current_checksums = {a: "a" * 64, b: "1" * 64}  # a changed, b unchanged, c removed

    def _seed_prior(store: FileSystemCanonicalStagingStore) -> None:
        store.write_repository_snapshot(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="rev1",
            file_checksums=prior_checksums,
            canonical_documents=tuple(_make_normalized_document(p) for p in (a, b, c)),
            chunk_records=tuple(_make_chunk_record(p, f"c-{p}") for p in (a, b, c)),
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )

    # --- LEGACY whole-RAM incremental publish ---
    legacy = FileSystemCanonicalStagingStore(workspace_root=tmp_path / "legacy")
    _seed_prior(legacy)
    legacy.write_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="rev2",
        file_checksums=current_checksums,
        canonical_documents=(_make_normalized_document(a),),  # changed doc only
        chunk_records=(  # full merged current chunks
            _make_chunk_record(a, "c-a-new"),
            _make_chunk_record(b, f"c-{b}"),
        ),
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )

    # --- Variant 2 streaming incremental publish ---
    stream = FileSystemCanonicalStagingStore(workspace_root=tmp_path / "stream")
    _seed_prior(stream)
    with stream.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="rev2",
        snapshot_tier=StagingSnapshotTier.REVIEW,
        operation_id="op-inc",
    ) as writer:
        writer.set_file_checksum(a, "a" * 64)
        writer.append_document(
            canonical_document=_make_normalized_document(a),
            chunk_records=[_make_chunk_record(a, "c-a-new")],
        )
    stream.write_publish_snapshot_from_review(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="rev2",
        file_checksums=current_checksums,
        operation_id="op-inc",
        skip_previous_merge=False,
    )

    def _docs(store: FileSystemCanonicalStagingStore) -> set[str]:
        return {
            d.document.source_path
            for d in store.iter_canonical_documents(
                repo_id="aspose.ocr.docs",
                source_kind="docs",
                source_revision="rev2",
                snapshot_tier=StagingSnapshotTier.PUBLISH,
            )
        }

    def _chunks(store: FileSystemCanonicalStagingStore) -> set[str]:
        return {
            ch.source_path
            for ch in store.iter_chunk_records(
                repo_id="aspose.ocr.docs",
                source_kind="docs",
                source_revision="rev2",
                snapshot_tier=StagingSnapshotTier.PUBLISH,
            )
        }

    assert _docs(legacy) == _docs(stream) == {a, b}  # c removed, b carried
    assert _chunks(legacy) == _chunks(stream) == {a, b}


def test_streaming_writer_dedupes_repeated_source_path(tmp_path: Path) -> None:
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_path = "source-repo-docs/Aspose.OCR/english/net/x.md"
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
    ) as writer:
        writer.set_file_checksum(source_path, "a" * 64)
        writer.append_document(
            canonical_document=_make_normalized_document(source_path),
            chunk_records=[_make_chunk_record(source_path, "chunk-1")],
        )
        # Repeat call should be a no-op — first append wins.
        writer.append_document(
            canonical_document=_make_normalized_document(source_path),
            chunk_records=[_make_chunk_record(source_path, "chunk-2")],
        )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
    )
    assert snapshot is not None
    assert len(snapshot.canonical_documents) == 1
    # Only the first chunk-1 should remain.
    assert [c.chunk_id for c in snapshot.chunk_records] == ["chunk-1"]


def test_streaming_writer_review_tier_synthesises_operation_id(tmp_path: Path) -> None:
    """REVIEW-tier streaming write without an explicit operation_id should
    still produce a valid manifest under runs/<auto-id>/.
    """
    store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    source_path = "source-repo-docs/Aspose.OCR/english/net/_index.md"
    with store.open_repository_streaming_write(
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.REVIEW,
        file_checksums={source_path: "a" * 64},
    ) as writer:
        writer.append_document(
            canonical_document=_make_normalized_document(source_path),
            chunk_records=[_make_chunk_record(source_path, "chunk-1")],
        )

    snapshot = store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.REVIEW,
    )
    assert snapshot is not None
    assert "_repo-staging-review" in snapshot.repository_manifest_path
    assert "runs/" in snapshot.repository_manifest_path
