"""Stage-E/Stage-F publish orchestrator for embedding and index writes.

Supports chunk-level checkpoint/resume so that large repos (e.g. 18k+ chunks)
can survive mid-run crashes without losing hours of embedding work.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from adcs.indexing.embedding_provider import (
    DeterministicLocalEmbeddingProvider,
    EmbeddingProvider,
)
from adcs.indexing.index_models import (
    IndexExecutableSnippet,
    IndexPublishSummary,
    LexicalIndexRecord,
    VectorIndexRecord,
)
from adcs.indexing.lexical_index_writer import InMemoryLexicalIndexWriter, LexicalIndexWriter
from adcs.indexing.snapshot_registry import InMemorySnapshotRegistry, SnapshotRegistry
from adcs.indexing.vector_index_writer import InMemoryVectorIndexWriter, VectorIndexWriter

if TYPE_CHECKING:
    from adcs.ingestion.chunking import StageDChunkRecord

logger = logging.getLogger(__name__)

_DEFAULT_PUBLISH_BATCH_SIZE = 500
_DEFAULT_CHUNK_RETRY_LIMIT = 3


@dataclass(frozen=True, slots=True)
class PublishCheckpointState:
    """Persisted checkpoint for a batched publish run."""

    scope_fingerprint: str
    snapshot_id: str
    batches_completed: int
    total_batches: int
    embedded_chunk_ids: tuple[str, ...]
    skipped_chunk_ids: tuple[str, ...]
    vector_records_written: int
    lexical_records_written: int


def _compute_scope_fingerprint(
    *,
    chunk_records: Sequence[StageDChunkRecord],
) -> str:
    """Deterministic fingerprint for a set of chunks in a scope.

    Uses chunk_ids + checksums so that if the input changes, the checkpoint
    is invalidated automatically.
    """
    hasher = hashlib.sha256()
    for chunk in chunk_records:
        hasher.update(f"{chunk.chunk_id}:{chunk.checksum}\n".encode())
    return hasher.hexdigest()[:16]


def _checkpoint_path(
    checkpoint_dir: Path,
    scope_fingerprint: str,
) -> Path:
    return checkpoint_dir / f"publish_checkpoint_{scope_fingerprint}.json"


def _load_checkpoint(path: Path) -> PublishCheckpointState | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return PublishCheckpointState(
            scope_fingerprint=data["scope_fingerprint"],
            snapshot_id=data["snapshot_id"],
            batches_completed=data["batches_completed"],
            total_batches=data["total_batches"],
            embedded_chunk_ids=tuple(data.get("embedded_chunk_ids", ())),
            skipped_chunk_ids=tuple(data.get("skipped_chunk_ids", ())),
            vector_records_written=data.get("vector_records_written", 0),
            lexical_records_written=data.get("lexical_records_written", 0),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Corrupt checkpoint at %s, ignoring", path)
        return None


def _save_checkpoint(path: Path, state: PublishCheckpointState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(
            {
                "scope_fingerprint": state.scope_fingerprint,
                "snapshot_id": state.snapshot_id,
                "batches_completed": state.batches_completed,
                "total_batches": state.total_batches,
                "embedded_chunk_ids": list(state.embedded_chunk_ids),
                "skipped_chunk_ids": list(state.skipped_chunk_ids),
                "vector_records_written": state.vector_records_written,
                "lexical_records_written": state.lexical_records_written,
            },
            f,
        )
    tmp_path.replace(path)


def _delete_checkpoint(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class IndexPublishOrchestrator:
    """Publish Stage-D chunks into embedding + vector/lexical indexing lanes.

    Supports checkpoint/resume for large repos: after each batch of chunks is
    embedded and written, progress is saved to a checkpoint file.  On retry the
    orchestrator skips already-processed batches.

    Individual chunks that fail embedding repeatedly (``chunk_retry_limit``
    times) are skipped and logged rather than crashing the entire pipeline.
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index_writer: VectorIndexWriter | None = None,
        lexical_index_writer: LexicalIndexWriter | None = None,
        snapshot_registry: SnapshotRegistry | None = None,
        checkpoint_dir: Path | str | None = None,
        publish_batch_size: int = _DEFAULT_PUBLISH_BATCH_SIZE,
        chunk_retry_limit: int = _DEFAULT_CHUNK_RETRY_LIMIT,
    ) -> None:
        self._embedding_provider = embedding_provider or DeterministicLocalEmbeddingProvider()
        self._vector_index_writer = vector_index_writer or InMemoryVectorIndexWriter()
        self._lexical_index_writer = lexical_index_writer or InMemoryLexicalIndexWriter()
        self._snapshot_registry = snapshot_registry or InMemorySnapshotRegistry()
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir is not None else None
        self._publish_batch_size = max(1, publish_batch_size)
        self._chunk_retry_limit = max(1, chunk_retry_limit)

    def publish(
        self,
        *,
        chunk_records: Sequence[StageDChunkRecord] | None = None,
        chunk_iter: Iterable[StageDChunkRecord] | None = None,
        write_dense_lexical: bool = True,
        english_only_embed: bool = False,
    ) -> IndexPublishSummary:
        """Publish all chunks of one ingestion run.

        Two input modes are supported:

        * ``chunk_records=<Sequence>`` — legacy, full sequence is held in
          process memory.
        * ``chunk_iter=<Iterable>`` — streaming, the orchestrator does not
          need to materialise the whole chunk set in RAM. The iterable is
          drained scope-by-scope; only the current scope's chunks are
          buffered, so peak overhead is bounded by the largest scope
          rather than the whole repository.

        Exactly one of the two inputs must be provided; both empty or
        both non-empty raise ``ValueError``.
        """
        if chunk_records is None and chunk_iter is None:
            msg = "Either chunk_records or chunk_iter must be provided."
            raise ValueError(msg)
        if chunk_records is not None and chunk_iter is not None:
            msg = "Only one of chunk_records / chunk_iter may be provided."
            raise ValueError(msg)
        if chunk_records is not None:
            if not chunk_records:
                msg = "chunk_records must not be empty."
                raise ValueError(msg)
            grouped_records = _group_chunk_records_by_scope(chunk_records=chunk_records)
        else:
            grouped_records = _group_chunk_records_by_scope_iter(
                chunk_iter=chunk_iter,  # type: ignore[arg-type]
            )
            if not grouped_records:
                msg = "chunk_iter produced no chunk records."
                raise ValueError(msg)
        summaries = tuple(
            self._publish_single_scope(
                chunk_records=scope_chunk_records,
                write_dense_lexical=write_dense_lexical,
                english_only_embed=english_only_embed,
            )
            for scope_chunk_records in grouped_records
        )
        if len(summaries) == 1:
            return summaries[0]

        primary = summaries[0]
        return IndexPublishSummary(
            snapshot_id=primary.snapshot_id,
            product_id=primary.product_id,
            programming_language=primary.programming_language,
            version=primary.version,
            source_kind=primary.source_kind,
            source_revision=primary.source_revision,
            indexed_chunks_count=sum(item.indexed_chunks_count for item in summaries),
            vector_records_count=sum(item.vector_records_count for item in summaries),
            lexical_records_count=sum(item.lexical_records_count for item in summaries),
            vector_collection=primary.vector_collection,
            lexical_index=primary.lexical_index,
            lexical_alias=primary.lexical_alias,
            active_snapshot_id=primary.active_snapshot_id,
        )

    def _publish_single_scope(
        self,
        *,
        chunk_records: Sequence[StageDChunkRecord],
        write_dense_lexical: bool = True,
        english_only_embed: bool = False,
    ) -> IndexPublishSummary:
        scope = _resolve_scope(chunk_records=chunk_records)

        if english_only_embed and write_dense_lexical:
            # EN-only index gate: every locale is parsed to the
            # staging store, but only English chunks are embedded into the
            # vector/lexical indexes. Non-English content stays in staging for
            # a future locale rollout without re-parsing. Scope is resolved
            # above from the unfiltered set (locale-agnostic), so the snapshot
            # is still tagged with the correct product/language/version. Gated on
            # write_dense_lexical so it never mutates the chunk set (and the
            # snapshot's indexed_chunks_count) for the apiref structured-store
            # path, which skips the embed lane entirely.
            kept: list[StageDChunkRecord] = []
            dropped_by_locale: dict[str, int] = {}
            for record in chunk_records:
                if _is_english_locale(record.doc_locale):
                    kept.append(record)
                else:
                    key = record.doc_locale or "<empty>"
                    dropped_by_locale[key] = dropped_by_locale.get(key, 0) + 1
            if dropped_by_locale:
                # Surface the per-locale breakdown so an unexpected
                # "unknown"/"<empty>" bucket (English content with an unresolved
                # locale) is visible rather than silently dropped.
                logger.info(
                    "EN-only embed gate dropped %d non-English chunks for "
                    "%s:%s:%s (by locale: %s)",
                    sum(dropped_by_locale.values()),
                    scope.product_id,
                    scope.programming_language,
                    scope.version,
                    dict(sorted(dropped_by_locale.items())),
                )
            chunk_records = tuple(kept)

        # --- Checkpoint: determine if we can resume a prior run ---
        use_checkpoint = self._checkpoint_dir is not None and len(chunk_records) > 0
        scope_fingerprint = ""
        ckpt_path: Path | None = None
        prior_state: PublishCheckpointState | None = None

        if use_checkpoint:
            scope_fingerprint = _compute_scope_fingerprint(chunk_records=chunk_records)
            ckpt_path = _checkpoint_path(self._checkpoint_dir, scope_fingerprint)  # type: ignore[arg-type]
            prior_state = _load_checkpoint(ckpt_path)
            if prior_state is not None and prior_state.scope_fingerprint != scope_fingerprint:
                logger.info("Checkpoint fingerprint mismatch, starting fresh")
                prior_state = None

        # Capture the prior active snapshot for THIS scope before creating the new
        # one, so the lexical alias switch supersedes only this scope's previous
        # index (additive — other scopes/products stay live under the alias).
        _prior_active = self._snapshot_registry.get_active_snapshot(
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
        )
        _superseded_snapshot_id = (
            _prior_active.snapshot_id if _prior_active is not None else None
        )

        snapshot = self._snapshot_registry.create_snapshot(
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
            source_revision=scope.source_revision,
            indexed_chunks_count=len(chunk_records),
        )

        if not write_dense_lexical or not chunk_records:
            # Allocate the snapshot id but skip embedding and the vector/lexical
            # writes entirely, in either of two cases:
            #   * Structured-store mode (apiref -> Postgres): apiref is served
            #     from the Postgres symbol store, not Qdrant/OpenSearch
            #     (ADR-011).
            #   * No embeddable chunks remain after the EN-only gate
            #     (write_dense_lexical is True but every chunk was non-English).
            return IndexPublishSummary(
                snapshot_id=snapshot.snapshot_id,
                product_id=scope.product_id,
                programming_language=scope.programming_language,
                version=scope.version,
                source_kind=scope.source_kind,
                source_revision=scope.source_revision,
                indexed_chunks_count=0,
                vector_records_count=0,
                lexical_records_count=0,
                vector_collection="",
                lexical_index="",
                lexical_alias="",
                active_snapshot_id=snapshot.snapshot_id,
            )

        # When not using checkpointing, use the original single-pass path
        if not use_checkpoint:
            return self._publish_single_pass(
                chunk_records=chunk_records,
                scope=scope,
                snapshot_id=snapshot.snapshot_id,
            )

        # --- Batched publish with checkpoint/resume ---
        batch_size = self._publish_batch_size
        batches: list[tuple[StageDChunkRecord, ...]] = []
        for start in range(0, len(chunk_records), batch_size):
            batches.append(tuple(chunk_records[start : start + batch_size]))

        total_batches = len(batches)
        batches_completed = 0
        all_embedded_chunk_ids: list[str] = []
        all_skipped_chunk_ids: list[str] = []
        total_vector_written = 0
        total_lexical_written = 0

        # Resume from checkpoint
        if prior_state is not None and prior_state.batches_completed > 0:
            batches_completed = min(prior_state.batches_completed, total_batches)
            all_embedded_chunk_ids.extend(prior_state.embedded_chunk_ids)
            all_skipped_chunk_ids.extend(prior_state.skipped_chunk_ids)
            total_vector_written = prior_state.vector_records_written
            total_lexical_written = prior_state.lexical_records_written
            logger.info(
                "Resuming publish from batch %d/%d (%d chunks already embedded, "
                "%d skipped)",
                batches_completed,
                total_batches,
                len(all_embedded_chunk_ids),
                len(all_skipped_chunk_ids),
            )

        for batch_idx in range(batches_completed, total_batches):
            batch = batches[batch_idx]
            batch_vectors, batch_skipped = self._embed_batch_with_retry(batch=batch)

            # Build records only for successfully embedded chunks
            batch_vector_records: list[VectorIndexRecord] = []
            batch_lexical_records: list[LexicalIndexRecord] = []
            embedded_in_batch: list[str] = []
            vec_idx = 0
            for chunk in batch:
                if chunk.chunk_id in batch_skipped:
                    continue
                batch_vector_records.append(
                    _to_vector_index_record(
                        chunk_record=chunk,
                        vector=batch_vectors[vec_idx],
                        snapshot_id=snapshot.snapshot_id,
                    )
                )
                batch_lexical_records.append(
                    _to_lexical_index_record(
                        chunk_record=chunk,
                        snapshot_id=snapshot.snapshot_id,
                    )
                )
                embedded_in_batch.append(chunk.chunk_id)
                vec_idx += 1

            # Write batch to indexes
            if batch_vector_records:
                vr = self._vector_index_writer.write_records(
                    source_kind=scope.source_kind,
                    snapshot_id=snapshot.snapshot_id,
                    records=batch_vector_records,
                )
                total_vector_written += vr.written_count
            if batch_lexical_records:
                lr = self._lexical_index_writer.write_records(
                    source_kind=scope.source_kind,
                    snapshot_id=snapshot.snapshot_id,
                    records=batch_lexical_records,
                )
                total_lexical_written += lr.written_count

            all_embedded_chunk_ids.extend(embedded_in_batch)
            all_skipped_chunk_ids.extend(sorted(batch_skipped))

            # Save checkpoint after each batch
            assert ckpt_path is not None  # guarded by use_checkpoint
            _save_checkpoint(
                ckpt_path,
                PublishCheckpointState(
                    scope_fingerprint=scope_fingerprint,
                    snapshot_id=snapshot.snapshot_id,
                    batches_completed=batch_idx + 1,
                    total_batches=total_batches,
                    embedded_chunk_ids=tuple(all_embedded_chunk_ids),
                    skipped_chunk_ids=tuple(all_skipped_chunk_ids),
                    vector_records_written=total_vector_written,
                    lexical_records_written=total_lexical_written,
                ),
            )
            logger.info(
                "Publish batch %d/%d done (%d embedded, %d skipped in batch)",
                batch_idx + 1,
                total_batches,
                len(embedded_in_batch),
                len(batch_skipped),
            )

        # All batches done -- switch lexical alias now that the index is complete
        self._lexical_index_writer.switch_alias(
            source_kind=scope.source_kind,
            snapshot_id=snapshot.snapshot_id,
            superseded_snapshot_id=(
                _superseded_snapshot_id
                if _superseded_snapshot_id != snapshot.snapshot_id
                else None
            ),
        )
        logger.info(
            "Lexical alias switched to snapshot %s after all %d batches published",
            snapshot.snapshot_id,
            total_batches,
        )

        # Clean up checkpoint
        if ckpt_path is not None:
            _delete_checkpoint(ckpt_path)

        if all_skipped_chunk_ids:
            logger.warning(
                "Publish completed with %d skipped chunks: %s",
                len(all_skipped_chunk_ids),
                all_skipped_chunk_ids[:20],
            )

        active_snapshot = self._snapshot_registry.get_active_snapshot(
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
        )
        active_snapshot_id = (
            active_snapshot.snapshot_id if active_snapshot is not None else snapshot.snapshot_id
        )

        return IndexPublishSummary(
            snapshot_id=snapshot.snapshot_id,
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
            source_revision=scope.source_revision,
            indexed_chunks_count=len(all_embedded_chunk_ids),
            vector_records_count=total_vector_written,
            lexical_records_count=total_lexical_written,
            vector_collection=_vector_collection_for_scope(scope),
            lexical_index=_lexical_index_for_scope(scope, snapshot.snapshot_id),
            lexical_alias=_lexical_alias_for_scope(scope),
            active_snapshot_id=active_snapshot_id,
        )

    def _publish_single_pass(
        self,
        *,
        chunk_records: Sequence[StageDChunkRecord],
        scope: _PublishScope,
        snapshot_id: str,
    ) -> IndexPublishSummary:
        """Original single-pass publish (no checkpointing)."""
        vectors = self._embedding_provider.embed_texts(
            texts=tuple(chunk.text for chunk in chunk_records)
        )
        if len(vectors) != len(chunk_records):
            msg = (
                "Embedding provider returned an invalid vector count "
                f"(expected={len(chunk_records)}, actual={len(vectors)})."
            )
            raise ValueError(msg)

        vector_records = tuple(
            _to_vector_index_record(
                chunk_record=chunk_record,
                vector=vector,
                snapshot_id=snapshot_id,
            )
            for chunk_record, vector in zip(chunk_records, vectors, strict=True)
        )
        lexical_records = tuple(
            _to_lexical_index_record(chunk_record=chunk_record, snapshot_id=snapshot_id)
            for chunk_record in chunk_records
        )

        vector_write_result = self._vector_index_writer.write_records(
            source_kind=scope.source_kind,
            snapshot_id=snapshot_id,
            records=vector_records,
        )
        lexical_write_result = self._lexical_index_writer.write_records(
            source_kind=scope.source_kind,
            snapshot_id=snapshot_id,
            records=lexical_records,
        )
        # Switch lexical alias after all records are written
        self._lexical_index_writer.switch_alias(
            source_kind=scope.source_kind,
            snapshot_id=snapshot_id,
        )
        active_snapshot = self._snapshot_registry.get_active_snapshot(
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
        )
        if active_snapshot is not None:
            active_snapshot_id = active_snapshot.snapshot_id
        else:
            active_snapshot_id = snapshot_id

        return IndexPublishSummary(
            snapshot_id=snapshot_id,
            product_id=scope.product_id,
            programming_language=scope.programming_language,
            version=scope.version,
            source_kind=scope.source_kind,
            source_revision=scope.source_revision,
            indexed_chunks_count=len(chunk_records),
            vector_records_count=vector_write_result.written_count,
            lexical_records_count=lexical_write_result.written_count,
            vector_collection=vector_write_result.collection_name,
            lexical_index=lexical_write_result.index_name,
            lexical_alias=lexical_write_result.alias_name,
            active_snapshot_id=active_snapshot_id,
        )

    def _embed_batch_with_retry(
        self,
        *,
        batch: tuple[StageDChunkRecord, ...],
    ) -> tuple[list[tuple[float, ...]], set[str]]:
        """Embed a batch of chunks, retrying failures per-chunk.

        Returns (vectors_for_successful_chunks, set_of_skipped_chunk_ids).
        On first attempt, tries the whole batch.  If it fails, falls back to
        per-chunk embedding with individual retry logic.
        """
        try:
            batch_result = self._embedding_provider.embed_texts(
                texts=tuple(chunk.text for chunk in batch)
            )
            if len(batch_result) == len(batch):
                return list(batch_result), set()
        except Exception:
            logger.warning(
                "Batch embedding failed for %d chunks, falling back to per-chunk",
                len(batch),
            )

        # Per-chunk fallback with retry
        fallback_vectors: list[tuple[float, ...]] = []
        skipped: set[str] = set()
        for chunk in batch:
            vector = self._embed_single_with_retry(chunk=chunk)
            if vector is not None:
                fallback_vectors.append(vector)
            else:
                skipped.add(chunk.chunk_id)
        return fallback_vectors, skipped

    def _embed_single_with_retry(
        self,
        *,
        chunk: StageDChunkRecord,
    ) -> tuple[float, ...] | None:
        """Embed a single chunk, retrying up to chunk_retry_limit times.

        Returns the embedding vector, or None if all retries are exhausted.
        """
        for attempt in range(1, self._chunk_retry_limit + 1):
            try:
                result = self._embedding_provider.embed_texts(texts=(chunk.text,))
                if result:
                    return result[0]
            except Exception:
                logger.warning(
                    "Embedding failed for chunk %s (attempt %d/%d)",
                    chunk.chunk_id,
                    attempt,
                    self._chunk_retry_limit,
                )
        logger.error(
            "Skipping chunk %s after %d failed attempts (source=%s)",
            chunk.chunk_id,
            self._chunk_retry_limit,
            chunk.source_path,
        )
        return None

    def get_active_snapshot(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
    ) -> str | None:
        snapshot = self._snapshot_registry.get_active_snapshot(
            product_id=product_id,
            programming_language=programming_language,
            version=version,
        )
        return snapshot.snapshot_id if snapshot is not None else None

    def list_snapshots(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[str, ...]:
        snapshots = self._snapshot_registry.list_snapshots(
            product_id=product_id,
            programming_language=programming_language,
            version=version,
        )
        return tuple(snapshot.snapshot_id for snapshot in snapshots)


class _PublishScope:
    def __init__(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str,
        source_kind: str,
        source_revision: str,
    ) -> None:
        self.product_id = product_id
        self.programming_language = programming_language
        self.version = version
        self.source_kind = source_kind
        self.source_revision = source_revision


# Locale values that count as English for the EN-only embed gate.
# Mirrors the alias map in adcs.indexing.apiref_symbol_publisher so the docs and
# apiref lanes treat "english"/"en-gb"/"en-us" identically. Any "en-*" regional
# subtag (en-au, en-ca, ...) is also accepted via the prefix check below.
_DOC_LOCALE_ENGLISH_ALIASES: frozenset[str] = frozenset({"en", "english", "eng"})


def _is_english_locale(doc_locale: str | None) -> bool:
    """True if *doc_locale* normalizes to English (incl. any ``en-*`` subtag).

    Strict: an empty/unknown locale is treated as non-English and dropped, so
    only content whose locale is positively identified as English is embedded.
    Callers should surface drop counts per locale (see the gate in
    :meth:`IndexPublishOrchestrator._publish_single_scope`) so an unexpected
    ``unknown``/empty locale does not silently lose English content.
    """
    if not doc_locale:
        return False
    normalized = doc_locale.strip().casefold()
    return normalized in _DOC_LOCALE_ENGLISH_ALIASES or normalized.startswith("en-")


def _scope_key(*, chunk_record: StageDChunkRecord) -> tuple[str, str, str, str, str]:
    return (
        chunk_record.product_id,
        chunk_record.programming_language,
        chunk_record.version,
        chunk_record.source_kind,
        chunk_record.source_revision,
    )


def _group_chunk_records_by_scope(
    *,
    chunk_records: Sequence[StageDChunkRecord],
) -> tuple[tuple[StageDChunkRecord, ...], ...]:
    grouped: OrderedDict[
        tuple[str, str, str, str, str],
        list[StageDChunkRecord],
    ] = OrderedDict()
    for chunk_record in chunk_records:
        key = _scope_key(chunk_record=chunk_record)
        grouped.setdefault(key, []).append(chunk_record)
    return tuple(tuple(records) for records in grouped.values())


def _group_chunk_records_by_scope_iter(
    *,
    chunk_iter: Iterable[StageDChunkRecord],
) -> tuple[tuple[StageDChunkRecord, ...], ...]:
    """Streaming variant of :func:`_group_chunk_records_by_scope`.

    Drains the input iterator into per-scope buckets. Peak memory is
    bounded by the largest scope rather than the whole input — the
    caller's iterator can yield from disk via
    :meth:`FileSystemCanonicalStagingStore.iter_chunk_records` without
    materialising the full chunk set up-front.

    Implementation note: scope-bucketing still requires accumulating each
    scope's chunks before the per-scope publish call, because
    :meth:`_publish_single_scope` needs an indexable batch. A future
    per-scope-streaming refactor (out of scope here) would let each
    scope emit chunks straight into the publish batches.
    """
    grouped: OrderedDict[
        tuple[str, str, str, str, str],
        list[StageDChunkRecord],
    ] = OrderedDict()
    for chunk_record in chunk_iter:
        key = _scope_key(chunk_record=chunk_record)
        grouped.setdefault(key, []).append(chunk_record)
    return tuple(tuple(records) for records in grouped.values())


def _resolve_scope(*, chunk_records: Sequence[StageDChunkRecord]) -> _PublishScope:
    first = chunk_records[0]
    scope = _PublishScope(
        product_id=first.product_id,
        programming_language=first.programming_language,
        version=first.version,
        source_kind=first.source_kind,
        source_revision=first.source_revision,
    )
    for index, chunk in enumerate(chunk_records[1:], start=1):
        if (
            chunk.product_id != scope.product_id
            or chunk.programming_language != scope.programming_language
            or chunk.version != scope.version
            or chunk.source_kind != scope.source_kind
            or chunk.source_revision != scope.source_revision
        ):
            msg = (
                "chunk_records must share one publish scope "
                f"(first_scope={scope.product_id}/{scope.programming_language}/{scope.version}/"
                f"{scope.source_kind}/{scope.source_revision}, mismatch_index={index})."
            )
            raise ValueError(msg)
    return scope


def _to_vector_index_record(
    *,
    chunk_record: StageDChunkRecord,
    vector: tuple[float, ...],
    snapshot_id: str,
) -> VectorIndexRecord:
    return VectorIndexRecord(
        chunk_id=chunk_record.chunk_id,
        point_id=chunk_record.chunk_id,
        text=chunk_record.text,
        vector=vector,
        snapshot_id=snapshot_id,
        product_id=chunk_record.product_id,
        product_family=chunk_record.product_family,
        programming_language=chunk_record.programming_language,
        version=chunk_record.version,
        source_kind=chunk_record.source_kind,
        doc_type=chunk_record.doc_type,
        doc_locale=chunk_record.doc_locale,
        symbol_fqn=chunk_record.symbol_fqn,
        title=chunk_record.title,
        canonical_url=chunk_record.canonical_url,
        section_anchor=chunk_record.section_anchor,
        source_revision=chunk_record.source_revision,
        repo_id=chunk_record.repo_id,
        checksum=chunk_record.checksum,
        executable_snippets=_to_index_snippets(chunk_record=chunk_record),
    )


def _to_lexical_index_record(
    *,
    chunk_record: StageDChunkRecord,
    snapshot_id: str,
) -> LexicalIndexRecord:
    return LexicalIndexRecord(
        chunk_id=chunk_record.chunk_id,
        text=chunk_record.text,
        snapshot_id=snapshot_id,
        product_id=chunk_record.product_id,
        product_family=chunk_record.product_family,
        programming_language=chunk_record.programming_language,
        version=chunk_record.version,
        source_kind=chunk_record.source_kind,
        doc_type=chunk_record.doc_type,
        doc_locale=chunk_record.doc_locale,
        symbol_fqn=chunk_record.symbol_fqn,
        title=chunk_record.title,
        canonical_url=chunk_record.canonical_url,
        section_anchor=chunk_record.section_anchor,
        source_revision=chunk_record.source_revision,
        repo_id=chunk_record.repo_id,
        checksum=chunk_record.checksum,
        executable_snippets=_to_index_snippets(chunk_record=chunk_record),
    )


def _to_index_snippets(*, chunk_record: StageDChunkRecord) -> tuple[IndexExecutableSnippet, ...]:
    return tuple(
        IndexExecutableSnippet(
            snippet_id=snippet.snippet_id,
            language=snippet.language,
            code=snippet.code,
            parent_canonical_url=snippet.parent_canonical_url,
            parent_section_anchor=snippet.parent_section_anchor,
            parent_symbol_fqn=snippet.parent_symbol_fqn,
        )
        for snippet in chunk_record.executable_snippets
    )


def _vector_collection_for_scope(scope: _PublishScope) -> str:
    """Derive vector collection name from scope (matches vector_index_writer convention)."""
    if scope.source_kind == "apiref":
        return "apiref_dense_v1"
    return "docs_dense_v1"


def _lexical_index_for_scope(scope: _PublishScope, snapshot_id: str) -> str:
    """Derive lexical index name from scope (matches lexical_index_writer convention)."""
    return f"{scope.source_kind}_lex_v1_{snapshot_id}"


def _lexical_alias_for_scope(scope: _PublishScope) -> str:
    """Derive lexical alias name from scope (matches lexical_index_writer convention)."""
    return f"{scope.source_kind}_lex_v1_active"
