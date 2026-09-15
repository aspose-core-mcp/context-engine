from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from adcs.indexing.embedding_provider import DeterministicLocalEmbeddingProvider, EmbeddingProvider
from adcs.indexing.lexical_index_writer import InMemoryLexicalIndexWriter
from adcs.indexing.publish_orchestrator import (
    IndexPublishOrchestrator,
    PublishCheckpointState,
    _checkpoint_path,
    _compute_scope_fingerprint,
    _load_checkpoint,
    _save_checkpoint,
)
from adcs.indexing.snapshot_registry import InMemorySnapshotRegistry
from adcs.indexing.vector_index_writer import InMemoryVectorIndexWriter
from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet


def _make_chunk_records() -> tuple[StageDChunkRecord, ...]:
    return (
        StageDChunkRecord(
            chunk_id="chunk-001",
            repo_id="aspose.ocr.docs",
            product_id="aspose.ocr",
            product_family="aspose",
            programming_language="net",
            version="25.1",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide_step",
            symbol_fqn=None,
            title="Install Package",
            section_path=("Getting Started", "Install"),
            canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
            section_anchor="#install",
            source_path="source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
            source_revision="revision-abc123",
            is_deprecated=False,
            has_code_example=False,
            chunk_type="guide_step",
            text="Install the package and configure OCR options.",
            tokens=18,
            checksum="checksum-001",
        ),
        StageDChunkRecord(
            chunk_id="chunk-002",
            repo_id="aspose.ocr.docs",
            product_id="aspose.ocr",
            product_family="aspose",
            programming_language="net",
            version="25.1",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide_step",
            symbol_fqn=None,
            title="Run First Request",
            section_path=("Getting Started", "Run"),
            canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
            section_anchor="#run",
            source_path="source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
            source_revision="revision-abc123",
            is_deprecated=False,
            has_code_example=True,
            chunk_type="guide_step",
            text="Run your first OCR request with local input files.",
            tokens=22,
            checksum="checksum-002",
            executable_snippets=(
                StageDExecutableSnippet(
                    snippet_id="snippet-002",
                    language="csharp",
                    code='var result = ocr.RecognizeImage("sample.png");',
                    parent_canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
                    parent_section_anchor="#run",
                    parent_symbol_fqn=None,
                ),
            ),
        ),
    )


def _make_multi_scope_chunk_records() -> tuple[StageDChunkRecord, ...]:
    net_chunk, java_chunk = _make_chunk_records()
    return (
        replace(
            net_chunk,
            chunk_id="chunk-net-001",
            checksum="checksum-net-001",
            programming_language="net",
            canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
            source_path=(
                "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md"
            ),
        ),
        replace(
            java_chunk,
            chunk_id="chunk-java-001",
            checksum="checksum-java-001",
            programming_language="java",
            canonical_url="https://docs.aspose.com/ocr/java/getting-started/",
            source_path=(
                "source-repo-docs/Aspose.OCR/english/java/getting-started/_index.md"
            ),
        ),
    )


def test_publish_skips_dense_and_lexical_when_write_dense_lexical_false() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    snapshot_registry = InMemorySnapshotRegistry()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=snapshot_registry,
    )

    summary = orchestrator.publish(
        chunk_records=_make_chunk_records(),
        write_dense_lexical=False,
    )

    # apiref structured-store mode: a snapshot id is still allocated (to tag the
    # symbol set) but nothing reaches the dense/lexical indexes.
    assert summary.snapshot_id
    assert summary.vector_records_count == 0
    assert summary.lexical_records_count == 0
    assert summary.indexed_chunks_count == 0
    assert summary.vector_collection == ""
    assert vector_writer.get_snapshot_records(summary.snapshot_id) == ()
    assert lexical_writer.get_snapshot_records(summary.snapshot_id) == ()


def _make_mixed_locale_chunk_records() -> tuple[StageDChunkRecord, ...]:
    en_one, en_two = _make_chunk_records()
    japanese = replace(
        en_one,
        chunk_id="chunk-ja-001",
        checksum="checksum-ja-001",
        doc_locale="ja",
        canonical_url="https://docs.aspose.com/ocr/ja/getting-started/",
    )
    german = replace(
        en_two,
        chunk_id="chunk-de-001",
        checksum="checksum-de-001",
        doc_locale="de",
        canonical_url="https://docs.aspose.com/ocr/de/getting-started/",
    )
    english_alias = replace(
        en_one,
        chunk_id="chunk-en-gb-001",
        checksum="checksum-en-gb-001",
        doc_locale="English",
    )
    return (en_one, en_two, japanese, german, english_alias)


def test_publish_english_only_embed_filters_non_english_chunks() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=InMemorySnapshotRegistry(),
    )

    summary = orchestrator.publish(
        chunk_records=_make_mixed_locale_chunk_records(),
        english_only_embed=True,
    )

    # Only the three English chunks (en, en, "English") are embedded; ja/de drop.
    assert summary.indexed_chunks_count == 3
    assert summary.vector_records_count == 3
    embedded_ids = {
        record.chunk_id for record in vector_writer.get_snapshot_records(summary.snapshot_id)
    }
    assert embedded_ids == {"chunk-001", "chunk-002", "chunk-en-gb-001"}


def test_publish_english_only_embed_disabled_keeps_all_locales() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
    )

    summary = orchestrator.publish(
        chunk_records=_make_mixed_locale_chunk_records(),
        english_only_embed=False,
    )

    # Default behaviour: every locale is embedded.
    assert summary.indexed_chunks_count == 5
    assert summary.vector_records_count == 5


def test_index_publish_orchestrator_writes_both_lanes_with_required_metadata() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    snapshot_registry = InMemorySnapshotRegistry()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=snapshot_registry,
    )

    summary = orchestrator.publish(chunk_records=_make_chunk_records())

    assert summary.snapshot_id == "snap-00000001"
    assert summary.vector_records_count == 2
    assert summary.lexical_records_count == 2
    assert summary.active_snapshot_id == summary.snapshot_id

    vector_records = vector_writer.get_snapshot_records(summary.snapshot_id)
    lexical_records = lexical_writer.get_snapshot_records(summary.snapshot_id)
    assert len(vector_records) == 2
    assert len(lexical_records) == 2

    first_vector = vector_records[0]
    assert first_vector.snapshot_id == summary.snapshot_id
    assert first_vector.canonical_url.endswith("/getting-started/")
    assert first_vector.section_anchor == "#install"
    assert first_vector.source_revision == "revision-abc123"
    assert first_vector.repo_id == "aspose.ocr.docs"
    assert first_vector.product_id == "aspose.ocr"
    assert first_vector.programming_language == "net"
    assert first_vector.version == "25.1"

    first_lexical = lexical_records[0]
    assert first_lexical.snapshot_id == summary.snapshot_id
    assert first_lexical.canonical_url.endswith("/getting-started/")
    assert first_lexical.section_anchor == "#install"
    assert first_lexical.source_revision == "revision-abc123"
    assert first_lexical.repo_id == "aspose.ocr.docs"

    snippet_vectors = [record for record in vector_records if record.executable_snippets]
    snippet_lexicals = [record for record in lexical_records if record.executable_snippets]
    assert len(snippet_vectors) == 1
    assert len(snippet_lexicals) == 1
    assert snippet_vectors[0].executable_snippets[0].language == "csharp"
    assert snippet_lexicals[0].executable_snippets[0].parent_section_anchor == "#run"


def test_index_publish_orchestrator_is_deterministic_for_same_input() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    snapshot_registry = InMemorySnapshotRegistry()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=snapshot_registry,
    )

    first_summary = orchestrator.publish(chunk_records=_make_chunk_records())
    second_summary = orchestrator.publish(chunk_records=_make_chunk_records())

    assert first_summary.snapshot_id != second_summary.snapshot_id
    assert orchestrator.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    ) == second_summary.snapshot_id

    first_vectors = [
        record.vector for record in vector_writer.get_snapshot_records(first_summary.snapshot_id)
    ]
    second_vectors = [
        record.vector for record in vector_writer.get_snapshot_records(second_summary.snapshot_id)
    ]
    assert first_vectors == second_vectors

    first_lexical_checksums = [
        record.checksum
        for record in lexical_writer.get_snapshot_records(first_summary.snapshot_id)
    ]
    second_lexical_checksums = [
        record.checksum
        for record in lexical_writer.get_snapshot_records(second_summary.snapshot_id)
    ]
    assert first_lexical_checksums == second_lexical_checksums
    assert orchestrator.list_snapshots(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    ) == (first_summary.snapshot_id, second_summary.snapshot_id)


def test_index_publish_orchestrator_supports_multi_scope_records() -> None:
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    snapshot_registry = InMemorySnapshotRegistry()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=snapshot_registry,
    )

    summary = orchestrator.publish(chunk_records=_make_multi_scope_chunk_records())

    assert summary.snapshot_id == "snap-00000001"
    assert summary.indexed_chunks_count == 2
    assert summary.vector_records_count == 2
    assert summary.lexical_records_count == 2
    assert orchestrator.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
    ) == "snap-00000001"
    assert orchestrator.get_active_snapshot(
        product_id="aspose.ocr",
        programming_language="java",
        version="25.1",
    ) == "snap-00000002"

    net_vectors = vector_writer.get_snapshot_records("snap-00000001")
    java_vectors = vector_writer.get_snapshot_records("snap-00000002")
    assert len(net_vectors) == 1
    assert len(java_vectors) == 1
    assert net_vectors[0].programming_language == "net"
    assert java_vectors[0].programming_language == "java"


# ---------------------------------------------------------------------------
# Helpers for checkpoint/resume tests
# ---------------------------------------------------------------------------


def _make_many_chunk_records(count: int) -> tuple[StageDChunkRecord, ...]:
    """Generate ``count`` chunk records with unique ids."""
    base = _make_chunk_records()[0]
    return tuple(
        replace(
            base,
            chunk_id=f"chunk-{i:04d}",
            checksum=f"checksum-{i:04d}",
            text=f"Chunk text number {i}",
        )
        for i in range(count)
    )


class _FailingEmbeddingProvider:
    """Embedding provider that fails on specific chunk texts."""

    def __init__(
        self,
        *,
        fail_texts: set[str],
        inner: EmbeddingProvider | None = None,
    ) -> None:
        self._fail_texts = fail_texts
        self._inner = inner or DeterministicLocalEmbeddingProvider(embedding_dimensions=12)
        self.call_count = 0

    def embed_texts(self, *, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.call_count += 1
        for t in texts:
            if t in self._fail_texts:
                msg = f"Simulated embedding failure for text: {t[:40]}"
                raise RuntimeError(msg)
        return self._inner.embed_texts(texts=texts)


class _CrashAfterNEmbeddingProvider:
    """Embedding provider that crashes after N successful embed_texts calls."""

    def __init__(self, *, crash_after: int) -> None:
        self._inner = DeterministicLocalEmbeddingProvider(embedding_dimensions=12)
        self._crash_after = crash_after
        self._call_count = 0

    def embed_texts(self, *, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self._call_count += 1
        if self._call_count > self._crash_after:
            msg = "Simulated crash"
            raise RuntimeError(msg)
        return self._inner.embed_texts(texts=texts)


# ---------------------------------------------------------------------------
# Checkpoint/resume tests
# ---------------------------------------------------------------------------


def test_checkpoint_publish_writes_all_chunks(tmp_path: Path) -> None:
    """With checkpoint enabled, all chunks are embedded and written."""
    chunks = _make_many_chunk_records(10)
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=InMemoryVectorIndexWriter(),
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
        checkpoint_dir=tmp_path,
        publish_batch_size=3,
    )

    summary = orchestrator.publish(chunk_records=chunks)

    assert summary.indexed_chunks_count == 10
    assert summary.vector_records_count == 10
    assert summary.lexical_records_count == 10
    # Checkpoint file should be cleaned up after success
    assert list(tmp_path.glob("publish_checkpoint_*.json")) == []


def test_checkpoint_resume_skips_completed_batches(tmp_path: Path) -> None:
    """On resume, already-completed batches are skipped."""
    chunks = _make_many_chunk_records(6)
    scope_fp = _compute_scope_fingerprint(chunk_records=chunks)

    # Simulate a prior run that completed batch 0 (chunks 0-2) of 2 batches
    ckpt_path = _checkpoint_path(tmp_path, scope_fp)
    _save_checkpoint(
        ckpt_path,
        PublishCheckpointState(
            scope_fingerprint=scope_fp,
            snapshot_id="snap-prior",
            batches_completed=1,
            total_batches=2,
            embedded_chunk_ids=("chunk-0000", "chunk-0001", "chunk-0002"),
            skipped_chunk_ids=(),
            vector_records_written=3,
            lexical_records_written=3,
        ),
    )

    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=InMemorySnapshotRegistry(),
        checkpoint_dir=tmp_path,
        publish_batch_size=3,
    )

    summary = orchestrator.publish(chunk_records=chunks)

    # 3 from checkpoint + 3 from new batch
    assert summary.indexed_chunks_count == 6
    assert summary.vector_records_count == 6
    assert summary.lexical_records_count == 6
    # Checkpoint cleaned up
    assert not ckpt_path.exists()


def test_checkpoint_skip_after_repeated_failure(tmp_path: Path) -> None:
    """Chunks that fail embedding repeatedly are skipped, not crash the run."""
    chunks = _make_many_chunk_records(5)
    fail_text = chunks[2].text  # chunk-0002 will always fail

    provider = _FailingEmbeddingProvider(fail_texts={fail_text})
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=provider,
        vector_index_writer=InMemoryVectorIndexWriter(),
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
        checkpoint_dir=tmp_path,
        publish_batch_size=5,
        chunk_retry_limit=3,
    )

    summary = orchestrator.publish(chunk_records=chunks)

    # 4 succeed, 1 skipped
    assert summary.indexed_chunks_count == 4
    assert summary.vector_records_count == 4
    assert summary.lexical_records_count == 4


def test_checkpoint_no_dir_uses_single_pass(tmp_path: Path) -> None:
    """Without checkpoint_dir, the original single-pass logic is used."""
    chunks = _make_chunk_records()
    vector_writer = InMemoryVectorIndexWriter()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
        # No checkpoint_dir
    )

    summary = orchestrator.publish(chunk_records=chunks)
    assert summary.indexed_chunks_count == 2
    assert summary.vector_records_count == 2


def test_checkpoint_fingerprint_mismatch_starts_fresh(tmp_path: Path) -> None:
    """If chunk content changes, old checkpoint is ignored."""
    chunks_v1 = _make_many_chunk_records(4)
    fp_v1 = _compute_scope_fingerprint(chunk_records=chunks_v1)

    # Write a checkpoint for v1
    ckpt_path = _checkpoint_path(tmp_path, fp_v1)
    _save_checkpoint(
        ckpt_path,
        PublishCheckpointState(
            scope_fingerprint=fp_v1,
            snapshot_id="snap-old",
            batches_completed=1,
            total_batches=2,
            embedded_chunk_ids=("chunk-0000", "chunk-0001"),
            skipped_chunk_ids=(),
            vector_records_written=2,
            lexical_records_written=2,
        ),
    )

    # Now publish with different chunks (different fingerprint)
    chunks_v2 = _make_many_chunk_records(3)
    # Alter a chunk to guarantee different fingerprint
    chunks_v2 = tuple(
        replace(c, checksum=f"new-{c.checksum}") for c in chunks_v2
    )
    fp_v2 = _compute_scope_fingerprint(chunk_records=chunks_v2)
    assert fp_v1 != fp_v2  # sanity

    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=InMemoryVectorIndexWriter(),
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
        checkpoint_dir=tmp_path,
        publish_batch_size=2,
    )

    summary = orchestrator.publish(chunk_records=chunks_v2)
    assert summary.indexed_chunks_count == 3


def test_checkpoint_save_load_roundtrip(tmp_path: Path) -> None:
    """Checkpoint state survives save/load roundtrip."""
    state = PublishCheckpointState(
        scope_fingerprint="abc123",
        snapshot_id="snap-001",
        batches_completed=5,
        total_batches=10,
        embedded_chunk_ids=("c1", "c2", "c3"),
        skipped_chunk_ids=("c4",),
        vector_records_written=3,
        lexical_records_written=3,
    )
    path = tmp_path / "test_checkpoint.json"
    _save_checkpoint(path, state)
    loaded = _load_checkpoint(path)

    assert loaded is not None
    assert loaded.scope_fingerprint == "abc123"
    assert loaded.batches_completed == 5
    assert loaded.total_batches == 10
    assert loaded.embedded_chunk_ids == ("c1", "c2", "c3")
    assert loaded.skipped_chunk_ids == ("c4",)
    assert loaded.vector_records_written == 3
    assert loaded.lexical_records_written == 3


def test_load_corrupt_checkpoint_returns_none(tmp_path: Path) -> None:
    """A corrupt checkpoint file is safely ignored."""
    path = tmp_path / "bad.json"
    path.write_text("not valid json {{{")
    assert _load_checkpoint(path) is None


# --- chunk_iter streaming publish ---------------------------------------


def test_publish_accepts_chunk_iter_streaming() -> None:
    """`publish(chunk_iter=...)` should produce the same outputs as the
    legacy `publish(chunk_records=...)` path while only iterating the
    chunks once (the caller may yield from disk via
    `iter_chunk_records` without materialising the full set in RAM).
    """
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    snapshot_registry = InMemorySnapshotRegistry()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=snapshot_registry,
    )

    chunks = _make_chunk_records()
    summary = orchestrator.publish(chunk_iter=iter(chunks))

    assert summary.vector_records_count == len(chunks)
    assert summary.lexical_records_count == len(chunks)
    assert summary.active_snapshot_id == summary.snapshot_id


def test_publish_requires_exactly_one_input() -> None:
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=InMemoryVectorIndexWriter(),
        lexical_index_writer=InMemoryLexicalIndexWriter(),
        snapshot_registry=InMemorySnapshotRegistry(),
    )
    chunks = _make_chunk_records()
    # both provided → error
    import pytest as _pytest

    with _pytest.raises(ValueError, match="Only one of"):
        orchestrator.publish(chunk_records=chunks, chunk_iter=iter(chunks))
    # neither provided → error
    with _pytest.raises(ValueError, match="Either"):
        orchestrator.publish()
    # iter produces nothing → error
    with _pytest.raises(ValueError, match="produced no"):
        orchestrator.publish(chunk_iter=iter(()))


def test_publish_chunk_iter_multi_scope_buckets_correctly() -> None:
    """The streaming bucketer must group chunks by scope (product_id +
    programming_language + version + source_kind + source_revision) just
    like the legacy sequence path.
    """
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    orchestrator = IndexPublishOrchestrator(
        embedding_provider=DeterministicLocalEmbeddingProvider(embedding_dimensions=12),
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
        snapshot_registry=InMemorySnapshotRegistry(),
    )
    # Same base set twice with one differing scope element → 2 scopes.
    chunks_a = _make_chunk_records()
    chunks_b = [
        replace(chunk, programming_language="java", chunk_id=f"{chunk.chunk_id}-java")
        for chunk in chunks_a
    ]

    summary = orchestrator.publish(chunk_iter=iter([*chunks_a, *chunks_b]))
    # Multi-scope publish returns sum of all scope counts.
    assert summary.vector_records_count == len(chunks_a) + len(chunks_b)
    assert summary.lexical_records_count == len(chunks_a) + len(chunks_b)
