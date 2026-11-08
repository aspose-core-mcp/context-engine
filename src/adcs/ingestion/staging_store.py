"""Canonical staging storage in data-docs/data-apiref for ingestion artifacts."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any

from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet
from adcs.ingestion.normalized_document import (
    NormalizedChunk,
    NormalizedCitation,
    NormalizedDocument,
    NormalizedDocumentMetadata,
    NormalizedWarning,
)

STAGING_SCHEMA_VERSION = "adcs.canonical_staging.v1"
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class StagingSnapshotTier(StrEnum):
    """Staging snapshot tier for publish replay or review-only artifacts."""

    PUBLISH = "publish"
    REVIEW = "review"


class CanonicalStagingSnapshotIntegrityError(RuntimeError):
    """Raised when staging snapshot pointers violate workspace safety constraints."""

    def __init__(
        self,
        *,
        repo_id: str,
        source_kind: str,
        manifest_path: str,
        violations: Sequence[str],
    ) -> None:
        self.repo_id = repo_id
        self.source_kind = source_kind
        self.manifest_path = manifest_path
        self.violations = tuple(violations)
        super().__init__(
            "Staging snapshot integrity check failed for "
            f"`{repo_id}` ({source_kind}) at `{manifest_path}`: "
            + "; ".join(self.violations)
        )


@dataclass(frozen=True, slots=True)
class CanonicalStagingScopeSummary:
    """One scope-level manifest summary persisted in staging layer."""

    product_id: str
    programming_language: str
    version: str
    doc_locale: str
    source_kind: str
    manifest_path: str
    documents_count: int
    chunk_records_count: int


@dataclass(frozen=True, slots=True)
class CanonicalStagingWriteResult:
    """Write result for one repo staging snapshot update."""

    repository_manifest_path: str
    scope_summaries: tuple[CanonicalStagingScopeSummary, ...]
    documents_count: int
    chunk_records_count: int
    snapshot_tier: str = StagingSnapshotTier.PUBLISH.value


@dataclass(frozen=True, slots=True)
class CanonicalStagingReplaySnapshot:
    """Replay payload loaded from canonical staging layer."""

    repo_id: str
    source_kind: str
    source_revision: str
    file_checksums: Mapping[str, str]
    canonical_documents: tuple[NormalizedDocument, ...]
    chunk_records: tuple[StageDChunkRecord, ...]
    repository_manifest_path: str
    scope_summaries: tuple[CanonicalStagingScopeSummary, ...]


@dataclass(frozen=True, slots=True)
class _ScopeKey:
    product_id: str
    programming_language: str
    version: str
    doc_locale: str
    source_kind: str


class FileSystemCanonicalStagingStore:
    """Persist/replay canonical staging artifacts in data-docs/data-apiref."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or Path(__file__).resolve().parents[3]).resolve()
        self._data_docs_root = (self._workspace_root / "data-docs").resolve()
        self._data_apiref_root = (self._workspace_root / "data-apiref").resolve()
        self._data_docs_root.mkdir(parents=True, exist_ok=True)
        self._data_apiref_root.mkdir(parents=True, exist_ok=True)

    def write_repository_snapshot(
        self,
        *,
        repo_id: str,
        product_id: str | None = None,
        source_kind: str,
        source_revision: str,
        file_checksums: Mapping[str, str],
        canonical_documents: Sequence[NormalizedDocument],
        chunk_records: Sequence[StageDChunkRecord],
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
        operation_id: str | None = None,
    ) -> CanonicalStagingWriteResult:
        """Persist canonical staging manifests/documents/chunk records for one repository."""
        if not repo_id.strip():
            msg = "repo_id must not be empty."
            raise ValueError(msg)
        if source_kind not in {"docs", "apiref"}:
            msg = "source_kind must be one of: docs, apiref."
            raise ValueError(msg)

        normalized_snapshot_tier = _normalize_snapshot_tier(snapshot_tier)
        normalized_repo_id = repo_id.strip()
        normalized_source_revision = source_revision.strip() or "unknown"
        normalized_operation_id = (operation_id or "").strip()
        if normalized_snapshot_tier is StagingSnapshotTier.REVIEW and not normalized_operation_id:
            normalized_operation_id = _default_review_run_id(
                source_revision=normalized_source_revision,
                file_checksums=file_checksums,
            )
        current_source_paths = set(file_checksums.keys())
        root_path = self._root_for_source_kind(source_kind)

        previous_snapshot: CanonicalStagingReplaySnapshot | None = None
        if normalized_snapshot_tier is StagingSnapshotTier.PUBLISH:
            try:
                previous_snapshot = self.load_repository_snapshot(
                    repo_id=normalized_repo_id,
                    source_kind=source_kind,
                    snapshot_tier=StagingSnapshotTier.PUBLISH,
                )
            except CanonicalStagingSnapshotIntegrityError:
                previous_snapshot = None
        previous_documents_by_source: dict[str, dict[str, Any]] = {}
        if previous_snapshot is not None:
            for document in previous_snapshot.canonical_documents:
                previous_documents_by_source[document.document.source_path] = (
                    _serialize_normalized_document(document)
                )

        changed_documents_by_source: dict[str, dict[str, Any]] = {}
        for document in canonical_documents:
            changed_documents_by_source[document.document.source_path] = (
                _serialize_normalized_document(document)
            )

        merged_documents_by_source: dict[str, dict[str, Any]] = {}
        for source_path in sorted(current_source_paths):
            changed_document = changed_documents_by_source.get(source_path)
            if changed_document is not None:
                merged_documents_by_source[source_path] = changed_document
                continue
            previous_document = previous_documents_by_source.get(source_path)
            if previous_document is not None:
                merged_documents_by_source[source_path] = previous_document

        chunks_by_source_path: dict[str, list[StageDChunkRecord]] = defaultdict(list)
        for chunk_record in chunk_records:
            chunks_by_source_path[chunk_record.source_path].append(chunk_record)
        for source_path in chunks_by_source_path:
            chunks_by_source_path[source_path].sort(key=_chunk_sort_key)

        document_entries: list[dict[str, Any]] = []
        chunk_entries: list[dict[str, Any]] = []
        scopes: dict[_ScopeKey, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: {"documents": [], "chunks": []}
        )

        for source_path, serialized_document in sorted(merged_documents_by_source.items()):
            document_scope = _scope_from_serialized_document(serialized_document)
            scope_root_relative = self._scope_root(
                root_path=root_path,
                scope=document_scope,
            ).relative_to(self._workspace_root)
            repository_storage_segment = _repository_storage_segment(
                repo_id=normalized_repo_id,
                snapshot_tier=normalized_snapshot_tier,
                operation_id=normalized_operation_id,
            )
            document_relative_path = (
                scope_root_relative
                / repository_storage_segment
                / "normalized-documents"
                / _stable_file_name(prefix="doc", source_path=source_path)
            )
            document_absolute_path = self._workspace_root / document_relative_path
            document_absolute_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(document_absolute_path, serialized_document)

            document_entry = {
                "source_path": source_path,
                "scope": _scope_to_payload(document_scope),
                "document_path": document_relative_path.as_posix(),
                "document_checksum": _json_checksum(serialized_document),
            }
            document_entries.append(document_entry)
            scopes[document_scope]["documents"].append(document_entry)

        for source_path, source_chunks in sorted(chunks_by_source_path.items()):
            scope = _scope_from_chunk_record(source_chunks[0])
            scope_root_relative = self._scope_root(
                root_path=root_path,
                scope=scope,
            ).relative_to(self._workspace_root)
            repository_storage_segment = _repository_storage_segment(
                repo_id=normalized_repo_id,
                snapshot_tier=normalized_snapshot_tier,
                operation_id=normalized_operation_id,
            )
            chunk_payload = {
                "schema_version": STAGING_SCHEMA_VERSION,
                "repo_id": normalized_repo_id,
                "source_kind": source_kind,
                "source_revision": normalized_source_revision,
                "snapshot_tier": normalized_snapshot_tier.value,
                "operation_id": normalized_operation_id or None,
                "source_path": source_path,
                "chunk_records": [_serialize_chunk_record(item) for item in source_chunks],
            }
            chunk_relative_path = (
                scope_root_relative
                / repository_storage_segment
                / "chunk-records"
                / _stable_file_name(prefix="chunks", source_path=source_path)
            )
            chunk_absolute_path = self._workspace_root / chunk_relative_path
            chunk_absolute_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(chunk_absolute_path, chunk_payload)

            chunk_entry = {
                "source_path": source_path,
                "scope": _scope_to_payload(scope),
                "chunk_path": chunk_relative_path.as_posix(),
                "chunk_records_count": len(source_chunks),
                "chunk_checksum": _json_checksum(chunk_payload),
            }
            chunk_entries.append(chunk_entry)
            scopes[scope]["chunks"].append(chunk_entry)

        scope_summaries: list[CanonicalStagingScopeSummary] = []
        scope_manifest_paths: list[str] = []
        for scope, scope_payload in sorted(
            scopes.items(),
            key=lambda item: _scope_sort_key(item[0]),
        ):
            scope_root_relative = self._scope_root(
                root_path=root_path,
                scope=scope,
            ).relative_to(self._workspace_root)
            repository_storage_segment = _repository_storage_segment(
                repo_id=normalized_repo_id,
                snapshot_tier=normalized_snapshot_tier,
                operation_id=normalized_operation_id,
            )
            scope_manifest_relative_path = (
                scope_root_relative
                / repository_storage_segment
                / "manifest.json"
            )
            scope_manifest_absolute_path = self._workspace_root / scope_manifest_relative_path
            scope_manifest_absolute_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_payload = {
                "schema_version": STAGING_SCHEMA_VERSION,
                "repo_id": normalized_repo_id,
                "source_kind": source_kind,
                "source_revision": normalized_source_revision,
                "snapshot_tier": normalized_snapshot_tier.value,
                "operation_id": normalized_operation_id or None,
                "scope": _scope_to_payload(scope),
                "file_checksums": {
                    source_path: file_checksums[source_path]
                    for source_path in sorted(file_checksums)
                    if _source_path_in_scope(
                        source_path=source_path,
                        documents=scope_payload["documents"],
                        chunks=scope_payload["chunks"],
                    )
                },
                "documents": sorted(
                    scope_payload["documents"],
                    key=lambda item: str(item.get("source_path", "")),
                ),
                "chunk_objects": sorted(
                    scope_payload["chunks"],
                    key=lambda item: str(item.get("source_path", "")),
                ),
                "documents_count": len(scope_payload["documents"]),
                "chunk_records_count": sum(
                    int(item.get("chunk_records_count", 0)) for item in scope_payload["chunks"]
                ),
            }
            _write_json(scope_manifest_absolute_path, manifest_payload)
            scope_manifest_paths.append(scope_manifest_relative_path.as_posix())
            scope_summaries.append(
                CanonicalStagingScopeSummary(
                    product_id=scope.product_id,
                    programming_language=scope.programming_language,
                    version=scope.version,
                    doc_locale=scope.doc_locale,
                    source_kind=scope.source_kind,
                    manifest_path=scope_manifest_relative_path.as_posix(),
                    documents_count=len(scope_payload["documents"]),
                    chunk_records_count=sum(
                        int(item.get("chunk_records_count", 0))
                        for item in scope_payload["chunks"]
                    ),
                )
            )

        repository_product_id = _resolve_repository_product_id(
            scope_summaries=scope_summaries,
            canonical_documents=canonical_documents,
            chunk_records=chunk_records,
            fallback_product_id=product_id,
        )
        root_relative = root_path.relative_to(self._workspace_root)
        if normalized_snapshot_tier is StagingSnapshotTier.PUBLISH:
            repository_manifest_relative_path = (
                root_relative
                / _sanitize_segment(repository_product_id)
                / "_repo-staging"
                / _sanitize_segment(normalized_repo_id)
                / "repository-manifest.json"
            )
        else:
            repository_manifest_relative_path = (
                root_relative
                / _sanitize_segment(repository_product_id)
                / "_repo-staging-review"
                / _sanitize_segment(normalized_repo_id)
                / "runs"
                / _sanitize_segment(normalized_operation_id)
                / "repository-manifest.json"
            )
        repository_manifest_absolute_path = (
            self._workspace_root / repository_manifest_relative_path
        )
        repository_manifest_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        repository_manifest_payload = {
            "schema_version": STAGING_SCHEMA_VERSION,
            "repo_id": normalized_repo_id,
            "source_kind": source_kind,
            "source_revision": normalized_source_revision,
            "snapshot_tier": normalized_snapshot_tier.value,
            "operation_id": normalized_operation_id or None,
            "repository_manifest_path": repository_manifest_relative_path.as_posix(),
            "scope_manifests": sorted(scope_manifest_paths),
            "file_checksums": {
                source_path: file_checksums[source_path] for source_path in sorted(file_checksums)
            },
            "documents": sorted(
                document_entries, key=lambda item: str(item.get("source_path", ""))
            ),
            "chunk_objects": sorted(
                chunk_entries, key=lambda item: str(item.get("source_path", ""))
            ),
            "documents_count": len(document_entries),
            "chunk_records_count": sum(
                int(item.get("chunk_records_count", 0)) for item in chunk_entries
            ),
        }
        _write_json(repository_manifest_absolute_path, repository_manifest_payload)

        return CanonicalStagingWriteResult(
            repository_manifest_path=repository_manifest_relative_path.as_posix(),
            scope_summaries=tuple(
                sorted(
                    scope_summaries,
                    key=lambda item: (
                        item.product_id,
                        item.programming_language,
                        item.version,
                        item.doc_locale,
                        item.manifest_path,
                    ),
                )
            ),
            documents_count=len(document_entries),
            chunk_records_count=sum(
                int(item.get("chunk_records_count", 0)) for item in chunk_entries
            ),
            snapshot_tier=normalized_snapshot_tier.value,
        )

    def write_publish_snapshot_from_review(
        self,
        *,
        repo_id: str,
        product_id: str | None,
        source_kind: str,
        source_revision: str,
        file_checksums: Mapping[str, str],
        operation_id: str | None = None,
        skip_previous_merge: bool = True,
    ) -> CanonicalStagingWriteResult:
        """Promote a REVIEW-tier snapshot to PUBLISH by streaming from disk.

        Streaming PUBLISH writer: the parse loop already wrote
        the changed documents + chunks to the REVIEW-tier staging page-by-page, so
        this re-streams them — one page at a time — into a PUBLISH-tier
        :class:`RepositoryStreamingWriter`, never materialising the whole repo in
        RAM.

        ``skip_previous_merge=True`` (default) is the full-reindex / wholesale-
        replace promotion: the REVIEW snapshot already holds every current
        document, so the prior PUBLISH snapshot is not merged in.
        ``skip_previous_merge=False`` is the INCREMENTAL promotion: the REVIEW
        snapshot holds only this run's changed/new files, and ``close()`` carries
        forward the unchanged files' documents+chunks from the prior PUBLISH
        snapshot by streaming (dropping removed files via ``file_checksums``).
        Both are byte-equivalent to the legacy ``write_repository_snapshot`` for
        their mode, but stream from disk so peak RAM does not scale with repo size.
        """
        writer = self.open_repository_streaming_write(
            repo_id=repo_id,
            product_id=product_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=StagingSnapshotTier.PUBLISH,
            operation_id=operation_id,
            file_checksums=file_checksums,
        )
        # Documents and chunks are promoted INDEPENDENTLY: the staging model
        # allows a source_path to have chunks without a 1:1 document (apiref skips
        # namespace-page documents but keeps symbol chunks), so coupling them
        # would silently drop those chunks. Both passes stream one item at a time.
        for document in self.iter_canonical_documents(
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=StagingSnapshotTier.REVIEW,
        ):
            writer.append_document(canonical_document=document, chunk_records=())
            # `document` goes out of scope each iteration — flushed to disk.

        # Chunks arrive in global source_path order (the manifest sorts
        # chunk_objects by source_path), so a single pass groups contiguous
        # same-source_path chunks into one chunk file without buffering the repo.
        chunk_group: list[StageDChunkRecord] = []
        for chunk in self.iter_chunk_records(
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=StagingSnapshotTier.REVIEW,
        ):
            if chunk_group and chunk.source_path != chunk_group[0].source_path:
                writer.append_chunks(
                    source_path=chunk_group[0].source_path, chunk_records=chunk_group
                )
                chunk_group = []
            chunk_group.append(chunk)
        if chunk_group:
            writer.append_chunks(
                source_path=chunk_group[0].source_path, chunk_records=chunk_group
            )
        return writer.close(skip_previous_merge=skip_previous_merge)

    def load_repository_snapshot(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> CanonicalStagingReplaySnapshot | None:
        """Load repository staging snapshot from data-docs/data-apiref by repo_id."""
        normalized_snapshot_tier = _normalize_snapshot_tier(snapshot_tier)
        resolved_manifest = self._resolve_repository_manifest(
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=normalized_snapshot_tier,
        )
        if resolved_manifest is None:
            return None

        manifest_path, payload = resolved_manifest
        violations: list[str] = []

        canonical_documents: list[NormalizedDocument] = []
        for entry in payload.get("documents", []):
            document_path = self._resolve_workspace_pointer(
                pointer_value=str(entry.get("document_path", "")),
                pointer_kind="document_path",
                violations=violations,
            )
            if document_path is None:
                continue
            if not document_path.exists():
                continue
            serialized_document = _read_json(document_path)
            canonical_documents.append(_deserialize_normalized_document(serialized_document))

        chunk_records: list[StageDChunkRecord] = []
        for entry in payload.get("chunk_objects", []):
            chunk_path = self._resolve_workspace_pointer(
                pointer_value=str(entry.get("chunk_path", "")),
                pointer_kind="chunk_path",
                violations=violations,
            )
            if chunk_path is None:
                continue
            if not chunk_path.exists():
                continue
            chunk_payload = _read_json(chunk_path)
            for serialized_chunk in chunk_payload.get("chunk_records", []):
                chunk_records.append(_deserialize_chunk_record(serialized_chunk))

        scope_summaries: list[CanonicalStagingScopeSummary] = []
        for manifest_pointer in payload.get("scope_manifests", []):
            scope_manifest_path = self._resolve_workspace_pointer(
                pointer_value=str(manifest_pointer),
                pointer_kind="scope_manifest_path",
                violations=violations,
            )
            if scope_manifest_path is None:
                continue
            if not scope_manifest_path.exists():
                continue
            scope_payload = _read_json(scope_manifest_path)
            scope = scope_payload.get("scope", {})
            scope_summaries.append(
                CanonicalStagingScopeSummary(
                    product_id=str(scope.get("product_id", "unknown")),
                    programming_language=str(scope.get("programming_language", "unknown")),
                    version=str(scope.get("version", "latest-stable")),
                    doc_locale=str(scope.get("doc_locale", "en")),
                    source_kind=str(scope.get("source_kind", source_kind)),
                    manifest_path=str(manifest_pointer),
                    documents_count=int(scope_payload.get("documents_count", 0)),
                    chunk_records_count=int(scope_payload.get("chunk_records_count", 0)),
                )
            )

        if violations:
            raise CanonicalStagingSnapshotIntegrityError(
                repo_id=str(payload.get("repo_id", repo_id)),
                source_kind=str(payload.get("source_kind", source_kind)),
                manifest_path=manifest_path.relative_to(self._workspace_root).as_posix(),
                violations=violations,
            )

        return CanonicalStagingReplaySnapshot(
            repo_id=str(payload.get("repo_id", repo_id)),
            source_kind=str(payload.get("source_kind", source_kind)),
            source_revision=str(payload.get("source_revision", "")),
            file_checksums={
                str(key): str(value)
                for key, value in dict(payload.get("file_checksums", {})).items()
            },
            canonical_documents=tuple(
                sorted(canonical_documents, key=lambda item: item.document.source_path)
            ),
            chunk_records=tuple(sorted(chunk_records, key=_chunk_sort_key)),
            repository_manifest_path=manifest_path.relative_to(self._workspace_root).as_posix(),
            scope_summaries=tuple(
                sorted(
                    scope_summaries,
                    key=lambda item: (
                        item.product_id,
                        item.programming_language,
                        item.version,
                        item.doc_locale,
                        item.manifest_path,
                    ),
                )
            ),
        )

    def _root_for_source_kind(self, source_kind: str) -> Path:
        if source_kind == "docs":
            return self._data_docs_root
        if source_kind == "apiref":
            return self._data_apiref_root
        msg = "source_kind must be one of: docs, apiref."
        raise ValueError(msg)

    # --- Streaming write / read APIs ------------------------------------
    # The legacy `write_repository_snapshot` materialises an entire
    # repository's `canonical_documents` and `chunk_records` in memory
    # before writing. For repositories above ~40k files that peak RAM
    # exceeds the worker's budget. `RepositoryStreamingWriter` exposes the
    # same on-disk layout but accepts one document at a time, so the
    # caller can release each `NormalizedDocument` immediately after
    # appending and keep peak RAM bounded by a single document.

    def open_repository_streaming_write(
        self,
        *,
        repo_id: str,
        product_id: str | None,
        source_kind: str,
        source_revision: str,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
        operation_id: str | None = None,
        file_checksums: Mapping[str, str] | None = None,
    ) -> RepositoryStreamingWriter:
        """Open an incremental write session for a single repository.

        Use as a context manager; the manifest is written on ``__exit__``
        (or ``close()``). On exception, partial document/chunk JSON files
        remain on disk — the next run can either pick them up via the
        intra-normalize checkpoint, the REVIEW-tier staging replay, or
        overwrite by repeating the streaming write.
        """
        if not repo_id.strip():
            msg = "repo_id must not be empty."
            raise ValueError(msg)
        if source_kind not in {"docs", "apiref"}:
            msg = "source_kind must be one of: docs, apiref."
            raise ValueError(msg)
        normalized_snapshot_tier = _normalize_snapshot_tier(snapshot_tier)
        normalized_operation_id = (operation_id or "").strip()
        if normalized_snapshot_tier is StagingSnapshotTier.REVIEW and not normalized_operation_id:
            # REVIEW tier writes are namespaced by operation_id under
            # `_repo-staging-review/<repo>/runs/<op_id>/`. A streaming
            # writer that never received an operation_id would clobber
            # whatever run happens to share the default segment, so we
            # synthesise a deterministic id from the source_revision and
            # any pre-supplied checksums.
            normalized_operation_id = _default_review_run_id(
                source_revision=source_revision.strip() or "unknown",
                file_checksums=file_checksums or {},
            )
        return RepositoryStreamingWriter(
            store=self,
            repo_id=repo_id.strip(),
            product_id_fallback=product_id,
            source_kind=source_kind,
            source_revision=source_revision.strip() or "unknown",
            snapshot_tier=normalized_snapshot_tier,
            operation_id=normalized_operation_id,
            initial_file_checksums=dict(file_checksums or {}),
        )

    def iter_canonical_documents(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]:
        """Yield canonical documents from a staging snapshot one at a time.

        Peak RAM is bounded by a single deserialised document — unlike
        :meth:`load_repository_snapshot` which materialises the whole
        tuple. Documents that reference broken or missing files are
        silently skipped (consistent with the existing loader's behaviour
        in :meth:`load_repository_snapshot`).
        """
        normalized_snapshot_tier = _normalize_snapshot_tier(snapshot_tier)
        resolved_manifest = self._resolve_repository_manifest(
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=normalized_snapshot_tier,
        )
        if resolved_manifest is None:
            return
        _, payload = resolved_manifest
        # Pointer issues are swallowed during iteration; call
        # load_repository_snapshot if you need them surfaced as errors.
        violations: list[str] = []
        for entry in payload.get("documents", []):
            document_path = self._resolve_workspace_pointer(
                pointer_value=str(entry.get("document_path", "")),
                pointer_kind="document_path",
                violations=violations,
            )
            if document_path is None or not document_path.exists():
                continue
            yield _deserialize_normalized_document(_read_json(document_path))

    def iter_chunk_records(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        """Yield chunk records from a staging snapshot one at a time.

        Iteration order follows the manifest's chunk_objects ordering
        (which matches the order produced by `RepositoryStreamingWriter`
        / `write_repository_snapshot`: sorted by source_path).
        """
        normalized_snapshot_tier = _normalize_snapshot_tier(snapshot_tier)
        resolved_manifest = self._resolve_repository_manifest(
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=normalized_snapshot_tier,
        )
        if resolved_manifest is None:
            return
        _, payload = resolved_manifest
        violations: list[str] = []
        for entry in payload.get("chunk_objects", []):
            chunk_path = self._resolve_workspace_pointer(
                pointer_value=str(entry.get("chunk_path", "")),
                pointer_kind="chunk_path",
                violations=violations,
            )
            if chunk_path is None or not chunk_path.exists():
                continue
            chunk_payload = _read_json(chunk_path)
            for serialized_chunk in chunk_payload.get("chunk_records", []):
                yield _deserialize_chunk_record(serialized_chunk)



    def _scope_root(self, *, root_path: Path, scope: _ScopeKey) -> Path:
        return (
            root_path
            / _sanitize_segment(scope.product_id)
            / _sanitize_segment(scope.programming_language)
            / _sanitize_segment(scope.version)
            / _sanitize_segment(scope.doc_locale)
        )

    def _resolve_repository_manifest(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None,
        snapshot_tier: StagingSnapshotTier,
    ) -> tuple[Path, dict[str, Any]] | None:
        candidate_paths = self._find_repository_manifest_paths(
            repo_id=repo_id,
            source_kind=source_kind,
            snapshot_tier=snapshot_tier,
        )
        if not candidate_paths:
            return None
        for candidate_path in candidate_paths:
            try:
                payload = _read_json(candidate_path)
            except (OSError, ValueError):
                continue
            if (
                source_revision is not None
                and str(payload.get("source_revision", "")) != source_revision
            ):
                continue
            return candidate_path, payload
        return None

    def _find_repository_manifest_paths(
        self,
        *,
        repo_id: str,
        source_kind: str,
        snapshot_tier: StagingSnapshotTier,
    ) -> tuple[Path, ...]:
        root_path = self._root_for_source_kind(source_kind)
        sanitized_repo_id = _sanitize_segment(repo_id)
        if snapshot_tier is StagingSnapshotTier.PUBLISH:
            pattern = f"*/_repo-staging/{sanitized_repo_id}/repository-manifest.json"
        else:
            pattern = f"*/_repo-staging-review/{sanitized_repo_id}/runs/*/repository-manifest.json"
        return tuple(sorted(root_path.glob(pattern)))

    def _resolve_workspace_pointer(
        self,
        *,
        pointer_value: str,
        pointer_kind: str,
        violations: list[str],
    ) -> Path | None:
        normalized_pointer = pointer_value.strip()
        if not normalized_pointer:
            violations.append(f"{pointer_kind}:empty")
            return None
        raw_path = Path(normalized_pointer)
        candidate_path = (
            raw_path if raw_path.is_absolute() else self._workspace_root / raw_path
        )
        try:
            resolved_path = candidate_path.resolve(strict=False)
        except OSError:
            violations.append(f"{pointer_kind}:resolve_error:{normalized_pointer}")
            return None
        if not resolved_path.is_relative_to(self._workspace_root):
            violations.append(f"{pointer_kind}:outside_workspace:{normalized_pointer}")
            return None
        return resolved_path




class RepositoryStreamingWriter:
    """Incremental, context-managed write session for one repository.

    Owns transient index structures (scope membership, document/chunk
    entry summaries, file checksums) — these are small even for very
    large repos (~20 MB for 100k docs). The heavy `NormalizedDocument`
    and `StageDChunkRecord` payloads are flushed to disk by
    :meth:`append_document` and the caller is expected to release them
    immediately after.

    On :meth:`close` (also invoked by the context-manager exit) the
    scope manifests and the top-level repository manifest are finalised
    using the accumulated indices, after merging in any unchanged
    documents from a prior PUBLISH-tier snapshot (so partial re-ingest
    runs don't lose previously-published documents).
    """

    def __init__(
        self,
        *,
        store: FileSystemCanonicalStagingStore,
        repo_id: str,
        product_id_fallback: str | None,
        source_kind: str,
        source_revision: str,
        snapshot_tier: StagingSnapshotTier,
        operation_id: str,
        initial_file_checksums: dict[str, str],
    ) -> None:
        self._store = store
        self._repo_id = repo_id
        self._product_id_fallback = product_id_fallback
        self._source_kind = source_kind
        self._source_revision = source_revision
        self._snapshot_tier = snapshot_tier
        self._operation_id = operation_id
        self._file_checksums: dict[str, str] = dict(initial_file_checksums)
        self._scopes: dict[
            _ScopeKey, dict[str, list[dict[str, Any]]]
        ] = defaultdict(lambda: {"documents": [], "chunks": []})
        self._document_entries: list[dict[str, Any]] = []
        self._chunk_entries: list[dict[str, Any]] = []
        self._appended_source_paths: set[str] = set()
        # Source_paths whose CHUNKS were appended this run via append_chunks
        # (chunk-only apiref pages have no document, so _appended_source_paths
        # would miss them). Used by the incremental carry-forward to skip
        # re-emitted chunk-only files.
        self._appended_chunk_source_paths: set[str] = set()
        self._closed = False
        self._root_path = store._root_for_source_kind(source_kind)
        self._scope_root_method = store._scope_root  # bound for performance
        self._workspace_root = store._workspace_root

    @property
    def documents_count(self) -> int:
        return len(self._document_entries)

    @property
    def chunk_records_count(self) -> int:
        return sum(
            int(entry.get("chunk_records_count", 0)) for entry in self._chunk_entries
        )

    def set_file_checksum(self, source_path: str, checksum: str) -> None:
        """Record the source-file checksum that will appear in the manifest.

        Idempotent: re-setting the same source_path overwrites the prior
        value. Call once per file regardless of whether the document was
        appended (e.g. parse-failed files still belong in the manifest
        so incremental diff detection sees them).
        """
        self._file_checksums[source_path] = checksum

    def append_document(
        self,
        *,
        canonical_document: NormalizedDocument,
        chunk_records: Sequence[StageDChunkRecord] = (),
    ) -> None:
        """Flush one canonical_document (and its chunks) to disk.

        After this call returns the caller may safely drop the
        ``canonical_document`` and ``chunk_records`` references — they
        are persisted and will be reloaded via :meth:`iter_canonical_documents`
        when the consumer needs them.
        """
        if self._closed:
            msg = "RepositoryStreamingWriter is closed."
            raise RuntimeError(msg)

        source_path = canonical_document.document.source_path
        if source_path in self._appended_source_paths:
            # Same shape as the legacy writer: silently de-dupe so the
            # caller can re-emit a document after a recoverable error.
            return
        self._appended_source_paths.add(source_path)

        serialized_document = _serialize_normalized_document(canonical_document)
        document_scope = _scope_from_serialized_document(serialized_document)
        scope_root_relative = self._scope_root_method(
            root_path=self._root_path,
            scope=document_scope,
        ).relative_to(self._workspace_root)
        repository_storage_segment = _repository_storage_segment(
            repo_id=self._repo_id,
            snapshot_tier=self._snapshot_tier,
            operation_id=self._operation_id,
        )
        document_relative_path = (
            scope_root_relative
            / repository_storage_segment
            / "normalized-documents"
            / _stable_file_name(prefix="doc", source_path=source_path)
        )
        document_absolute_path = self._workspace_root / document_relative_path
        document_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(document_absolute_path, serialized_document)
        document_entry = {
            "source_path": source_path,
            "scope": _scope_to_payload(document_scope),
            "document_path": document_relative_path.as_posix(),
            "document_checksum": _json_checksum(serialized_document),
        }
        self._document_entries.append(document_entry)
        self._scopes[document_scope]["documents"].append(document_entry)

        if not chunk_records:
            return
        sorted_chunks = sorted(chunk_records, key=_chunk_sort_key)
        chunk_payload = {
            "schema_version": STAGING_SCHEMA_VERSION,
            "repo_id": self._repo_id,
            "source_kind": self._source_kind,
            "source_revision": self._source_revision,
            "snapshot_tier": self._snapshot_tier.value,
            "operation_id": self._operation_id or None,
            "source_path": source_path,
            "chunk_records": [_serialize_chunk_record(item) for item in sorted_chunks],
        }
        chunk_relative_path = (
            scope_root_relative
            / repository_storage_segment
            / "chunk-records"
            / _stable_file_name(prefix="chunks", source_path=source_path)
        )
        chunk_absolute_path = self._workspace_root / chunk_relative_path
        chunk_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(chunk_absolute_path, chunk_payload)
        chunk_entry = {
            "source_path": source_path,
            "scope": _scope_to_payload(document_scope),
            "chunk_path": chunk_relative_path.as_posix(),
            "chunk_records_count": len(sorted_chunks),
            "chunk_checksum": _json_checksum(chunk_payload),
        }
        self._chunk_entries.append(chunk_entry)
        self._scopes[document_scope]["chunks"].append(chunk_entry)

    def append_chunks(
        self,
        *,
        source_path: str,
        chunk_records: Sequence[StageDChunkRecord],
    ) -> None:
        """Flush one source_path's chunk group to disk, independent of a document.

        Mirrors the chunk half of :meth:`append_document` but derives the scope
        from the chunk records rather than a document — needed when a source_path
        has chunks but no 1:1 document (e.g. apiref, where namespace-page
        documents are skipped while the symbol chunks remain). The caller may drop
        ``chunk_records`` immediately after this returns.
        """
        if self._closed:
            msg = "RepositoryStreamingWriter is closed."
            raise RuntimeError(msg)
        if not chunk_records:
            return
        self._appended_chunk_source_paths.add(source_path)
        sorted_chunks = sorted(chunk_records, key=_chunk_sort_key)
        chunk_scope = _scope_from_chunk_record(sorted_chunks[0])
        scope_root_relative = self._scope_root_method(
            root_path=self._root_path,
            scope=chunk_scope,
        ).relative_to(self._workspace_root)
        repository_storage_segment = _repository_storage_segment(
            repo_id=self._repo_id,
            snapshot_tier=self._snapshot_tier,
            operation_id=self._operation_id,
        )
        chunk_payload = {
            "schema_version": STAGING_SCHEMA_VERSION,
            "repo_id": self._repo_id,
            "source_kind": self._source_kind,
            "source_revision": self._source_revision,
            "snapshot_tier": self._snapshot_tier.value,
            "operation_id": self._operation_id or None,
            "source_path": source_path,
            "chunk_records": [_serialize_chunk_record(item) for item in sorted_chunks],
        }
        chunk_relative_path = (
            scope_root_relative
            / repository_storage_segment
            / "chunk-records"
            / _stable_file_name(prefix="chunks", source_path=source_path)
        )
        chunk_absolute_path = self._workspace_root / chunk_relative_path
        chunk_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(chunk_absolute_path, chunk_payload)
        chunk_entry = {
            "source_path": source_path,
            "scope": _scope_to_payload(chunk_scope),
            "chunk_path": chunk_relative_path.as_posix(),
            "chunk_records_count": len(sorted_chunks),
            "chunk_checksum": _json_checksum(chunk_payload),
        }
        self._chunk_entries.append(chunk_entry)
        self._scopes[chunk_scope]["chunks"].append(chunk_entry)

    def _carry_forward_chunk_group(
        self,
        chunk_group: list[StageDChunkRecord],
        *,
        changed_this_run: set[str],
    ) -> None:
        """Carry one prior-snapshot chunk group forward during incremental close.

        Skips source_paths re-emitted this run (their new chunks already won) and
        removed files (absent from file_checksums).
        """
        if not chunk_group:
            return
        source_path = chunk_group[0].source_path
        if source_path in changed_this_run:
            return
        if source_path not in self._file_checksums:
            return
        self.append_chunks(source_path=source_path, chunk_records=chunk_group)

    def close(self, *, skip_previous_merge: bool = False) -> CanonicalStagingWriteResult:
        """Finalise scope + repository manifests and return the write result.

        Idempotent: a second call returns the previously-computed result.

        ``skip_previous_merge=True`` suppresses carrying forward unchanged
        documents from a prior PUBLISH snapshot — used by a full-reindex
        promotion, which replaces the snapshot wholesale rather than merging.
        """
        if self._closed:
            msg = "RepositoryStreamingWriter is already closed."
            raise RuntimeError(msg)

        # Merge with the previously-published PUBLISH-tier snapshot so documents
        # AND chunks that weren't re-emitted in this session are still referenced
        # from the new manifest (the legacy `write_repository_snapshot` performs
        # the same merge). STREAM the prior snapshot one item at a time
        # (iter_canonical_documents + iter_chunk_records) instead of loading it
        # whole, so an incremental re-ingest of a huge repo stays RAM-bounded.
        # A full-reindex promotion skips this (it re-streams every current item).
        if self._snapshot_tier is StagingSnapshotTier.PUBLISH and not skip_previous_merge:
            # Snapshot the set of source_paths written THIS run BEFORE carry-forward
            # (the doc carry-forward below mutates _appended_source_paths, so the
            # chunk carry-forward must filter against this frozen set, not the live
            # one — otherwise unchanged files' chunks would be wrongly skipped).
            changed_this_run = (
                self._appended_source_paths | self._appended_chunk_source_paths
            )
            for document in self._store.iter_canonical_documents(
                repo_id=self._repo_id,
                source_kind=self._source_kind,
                snapshot_tier=StagingSnapshotTier.PUBLISH,
            ):
                source_path = document.document.source_path
                if source_path in changed_this_run:
                    continue
                if source_path not in self._file_checksums:
                    # File no longer part of the repo — drop (removed file).
                    continue
                self.append_document(canonical_document=document, chunk_records=())
            # Carry forward unchanged chunks independently of documents (apiref
            # has chunk-only source_paths). Chunks arrive in global source_path
            # order, so group contiguous same-source_path chunks.
            carry_group: list[StageDChunkRecord] = []
            for chunk in self._store.iter_chunk_records(
                repo_id=self._repo_id,
                source_kind=self._source_kind,
                snapshot_tier=StagingSnapshotTier.PUBLISH,
            ):
                if carry_group and chunk.source_path != carry_group[0].source_path:
                    self._carry_forward_chunk_group(
                        carry_group, changed_this_run=changed_this_run
                    )
                    carry_group = []
                carry_group.append(chunk)
            if carry_group:
                self._carry_forward_chunk_group(
                    carry_group, changed_this_run=changed_this_run
                )

        # Build scope manifests + repository manifest, mirroring the
        # tail of `write_repository_snapshot`.
        scope_summaries: list[CanonicalStagingScopeSummary] = []
        scope_manifest_paths: list[str] = []
        for scope, scope_payload in sorted(
            self._scopes.items(),
            key=lambda item: _scope_sort_key(item[0]),
        ):
            scope_root_relative = self._scope_root_method(
                root_path=self._root_path,
                scope=scope,
            ).relative_to(self._workspace_root)
            repository_storage_segment = _repository_storage_segment(
                repo_id=self._repo_id,
                snapshot_tier=self._snapshot_tier,
                operation_id=self._operation_id,
            )
            scope_manifest_relative_path = (
                scope_root_relative / repository_storage_segment / "manifest.json"
            )
            scope_manifest_absolute_path = (
                self._workspace_root / scope_manifest_relative_path
            )
            scope_manifest_absolute_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_payload = {
                "schema_version": STAGING_SCHEMA_VERSION,
                "repo_id": self._repo_id,
                "source_kind": self._source_kind,
                "source_revision": self._source_revision,
                "snapshot_tier": self._snapshot_tier.value,
                "operation_id": self._operation_id or None,
                "scope": _scope_to_payload(scope),
                "file_checksums": {
                    source_path: self._file_checksums[source_path]
                    for source_path in sorted(self._file_checksums)
                    if _source_path_in_scope(
                        source_path=source_path,
                        documents=scope_payload["documents"],
                        chunks=scope_payload["chunks"],
                    )
                },
                "documents": sorted(
                    scope_payload["documents"],
                    key=lambda item: str(item.get("source_path", "")),
                ),
                "chunk_objects": sorted(
                    scope_payload["chunks"],
                    key=lambda item: str(item.get("source_path", "")),
                ),
                "documents_count": len(scope_payload["documents"]),
                "chunk_records_count": sum(
                    int(item.get("chunk_records_count", 0))
                    for item in scope_payload["chunks"]
                ),
            }
            _write_json(scope_manifest_absolute_path, manifest_payload)
            scope_manifest_paths.append(scope_manifest_relative_path.as_posix())
            scope_summaries.append(
                CanonicalStagingScopeSummary(
                    product_id=scope.product_id,
                    programming_language=scope.programming_language,
                    version=scope.version,
                    doc_locale=scope.doc_locale,
                    source_kind=scope.source_kind,
                    manifest_path=scope_manifest_relative_path.as_posix(),
                    documents_count=len(scope_payload["documents"]),
                    chunk_records_count=sum(
                        int(item.get("chunk_records_count", 0))
                        for item in scope_payload["chunks"]
                    ),
                )
            )

        repository_product_id = _resolve_repository_product_id(
            scope_summaries=scope_summaries,
            canonical_documents=(),  # already on disk; only fallback used
            chunk_records=(),
            fallback_product_id=self._product_id_fallback,
        )
        root_relative = self._root_path.relative_to(self._workspace_root)
        if self._snapshot_tier is StagingSnapshotTier.PUBLISH:
            repository_manifest_relative_path = (
                root_relative
                / _sanitize_segment(repository_product_id)
                / "_repo-staging"
                / _sanitize_segment(self._repo_id)
                / "repository-manifest.json"
            )
        else:
            repository_manifest_relative_path = (
                root_relative
                / _sanitize_segment(repository_product_id)
                / "_repo-staging-review"
                / _sanitize_segment(self._repo_id)
                / "runs"
                / _sanitize_segment(self._operation_id)
                / "repository-manifest.json"
            )
        repository_manifest_absolute_path = (
            self._workspace_root / repository_manifest_relative_path
        )
        repository_manifest_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        repository_manifest_payload = {
            "schema_version": STAGING_SCHEMA_VERSION,
            "repo_id": self._repo_id,
            "source_kind": self._source_kind,
            "source_revision": self._source_revision,
            "snapshot_tier": self._snapshot_tier.value,
            "operation_id": self._operation_id or None,
            "repository_manifest_path": repository_manifest_relative_path.as_posix(),
            "scope_manifests": sorted(scope_manifest_paths),
            "file_checksums": {
                source_path: self._file_checksums[source_path]
                for source_path in sorted(self._file_checksums)
            },
            "documents": sorted(
                self._document_entries,
                key=lambda item: str(item.get("source_path", "")),
            ),
            "chunk_objects": sorted(
                self._chunk_entries,
                key=lambda item: str(item.get("source_path", "")),
            ),
            "documents_count": len(self._document_entries),
            "chunk_records_count": sum(
                int(item.get("chunk_records_count", 0))
                for item in self._chunk_entries
            ),
        }
        _write_json(repository_manifest_absolute_path, repository_manifest_payload)

        self._closed = True
        self._result = CanonicalStagingWriteResult(
            repository_manifest_path=repository_manifest_relative_path.as_posix(),
            scope_summaries=tuple(
                sorted(
                    scope_summaries,
                    key=lambda item: (
                        item.product_id,
                        item.programming_language,
                        item.version,
                        item.doc_locale,
                        item.manifest_path,
                    ),
                )
            ),
            documents_count=len(self._document_entries),
            chunk_records_count=sum(
                int(item.get("chunk_records_count", 0))
                for item in self._chunk_entries
            ),
            snapshot_tier=self._snapshot_tier.value,
        )
        return self._result

    def __enter__(self) -> RepositoryStreamingWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Auto-finalise on clean exit. On exception, leave partial
        # state on disk for recovery on the next run; caller logs the
        # error via its own machinery.
        if exc_type is None and not self._closed:
            self.close()




def _serialize_normalized_document(document: NormalizedDocument) -> dict[str, Any]:
    return {
        "schema": document.schema,
        "document": asdict(document.document),
        "chunks": [
            {
                "chunk_key": chunk.chunk_key,
                "section_path": list(chunk.section_path),
                "section_anchor": chunk.section_anchor,
                "chunk_type": chunk.chunk_type,
                "text": chunk.text,
                "citations": [asdict(citation) for citation in chunk.citations],
                "title": chunk.title,
                "canonical_url": chunk.canonical_url,
            }
            for chunk in document.chunks
        ],
        "warnings": [asdict(warning) for warning in document.warnings],
    }


def _deserialize_normalized_document(payload: Mapping[str, Any]) -> NormalizedDocument:
    document_payload = dict(payload.get("document", {}))
    chunks_payload = list(payload.get("chunks", []))
    warnings_payload = list(payload.get("warnings", []))
    return NormalizedDocument(
        schema=str(payload.get("schema", "")),
        document=NormalizedDocumentMetadata(**document_payload),
        chunks=tuple(
            NormalizedChunk(
                chunk_key=str(chunk.get("chunk_key", "")),
                section_path=tuple(str(item) for item in chunk.get("section_path", [])),
                section_anchor=str(chunk.get("section_anchor", "")),
                chunk_type=str(chunk.get("chunk_type", "")),
                text=str(chunk.get("text", "")),
                citations=tuple(
                    NormalizedCitation(
                        canonical_url=str(citation.get("canonical_url", "")),
                        source_path=str(citation.get("source_path", "")),
                        title=str(citation.get("title", "")),
                        section_anchor=str(citation.get("section_anchor", "")),
                    )
                    for citation in chunk.get("citations", [])
                ),
                title=str(chunk.get("title", "")),
                canonical_url=str(chunk.get("canonical_url", "")),
            )
            for chunk in chunks_payload
        ),
        warnings=tuple(
            NormalizedWarning(
                code=str(item.get("code", "")),
                message=str(item.get("message", "")),
                source_path=str(item.get("source_path", "")),
                line_hint=_coerce_optional_int(item.get("line_hint")),
                severity=str(item.get("severity", "warning")),
            )
            for item in warnings_payload
        ),
    )


def _serialize_chunk_record(record: StageDChunkRecord) -> dict[str, Any]:
    return {
        "chunk_id": record.chunk_id,
        "repo_id": record.repo_id,
        "product_id": record.product_id,
        "product_family": record.product_family,
        "programming_language": record.programming_language,
        "version": record.version,
        "source_kind": record.source_kind,
        "doc_locale": record.doc_locale,
        "doc_type": record.doc_type,
        "symbol_fqn": record.symbol_fqn,
        "title": record.title,
        "section_path": list(record.section_path),
        "canonical_url": record.canonical_url,
        "section_anchor": record.section_anchor,
        "source_path": record.source_path,
        "source_revision": record.source_revision,
        "is_deprecated": record.is_deprecated,
        "has_code_example": record.has_code_example,
        "chunk_type": record.chunk_type,
        "text": record.text,
        "tokens": record.tokens,
        "checksum": record.checksum,
        "executable_snippets": [
            {
                "snippet_id": item.snippet_id,
                "language": item.language,
                "code": item.code,
                "parent_canonical_url": item.parent_canonical_url,
                "parent_section_anchor": item.parent_section_anchor,
                "parent_symbol_fqn": item.parent_symbol_fqn,
            }
            for item in record.executable_snippets
        ],
    }


def _deserialize_chunk_record(payload: Mapping[str, Any]) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=str(payload.get("chunk_id", "")),
        repo_id=str(payload.get("repo_id", "")),
        product_id=str(payload.get("product_id", "")),
        product_family=str(payload.get("product_family", "")),
        programming_language=str(payload.get("programming_language", "")),
        version=str(payload.get("version", "")),
        source_kind=str(payload.get("source_kind", "")),
        doc_locale=str(payload.get("doc_locale", "")),
        doc_type=str(payload.get("doc_type", "")),
        symbol_fqn=_coerce_optional_string(payload.get("symbol_fqn")),
        title=str(payload.get("title", "")),
        section_path=tuple(str(item) for item in payload.get("section_path", [])),
        canonical_url=str(payload.get("canonical_url", "")),
        section_anchor=str(payload.get("section_anchor", "")),
        source_path=str(payload.get("source_path", "")),
        source_revision=str(payload.get("source_revision", "")),
        is_deprecated=bool(payload.get("is_deprecated", False)),
        has_code_example=bool(payload.get("has_code_example", False)),
        chunk_type=str(payload.get("chunk_type", "")),
        text=str(payload.get("text", "")),
        tokens=int(payload.get("tokens", 0)),
        checksum=str(payload.get("checksum", "")),
        executable_snippets=tuple(
            StageDExecutableSnippet(
                snippet_id=str(item.get("snippet_id", "")),
                language=str(item.get("language", "")),
                code=str(item.get("code", "")),
                parent_canonical_url=str(item.get("parent_canonical_url", "")),
                parent_section_anchor=str(item.get("parent_section_anchor", "")),
                parent_symbol_fqn=_coerce_optional_string(item.get("parent_symbol_fqn")),
            )
            for item in payload.get("executable_snippets", [])
        ),
    )


def _scope_from_chunk_record(record: StageDChunkRecord) -> _ScopeKey:
    return _ScopeKey(
        product_id=record.product_id or "unknown",
        programming_language=record.programming_language or "unknown",
        version=record.version or "latest-stable",
        doc_locale=record.doc_locale or "en",
        source_kind=record.source_kind or "docs",
    )


def _scope_from_serialized_document(payload: Mapping[str, Any]) -> _ScopeKey:
    document_payload = dict(payload.get("document", {}))
    return _ScopeKey(
        product_id=str(document_payload.get("product_id", "unknown")),
        programming_language=str(document_payload.get("programming_language", "unknown")),
        version=str(document_payload.get("version", "latest-stable")),
        doc_locale=str(document_payload.get("doc_locale", "en")),
        source_kind=str(document_payload.get("source_kind", "docs")),
    )


def _scope_to_payload(scope: _ScopeKey) -> dict[str, str]:
    return {
        "product_id": scope.product_id,
        "programming_language": scope.programming_language,
        "version": scope.version,
        "doc_locale": scope.doc_locale,
        "source_kind": scope.source_kind,
    }


def _scope_sort_key(scope: _ScopeKey) -> tuple[str, str, str, str, str]:
    return (
        scope.product_id,
        scope.programming_language,
        scope.version,
        scope.doc_locale,
        scope.source_kind,
    )


def _source_path_in_scope(
    *,
    source_path: str,
    documents: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
) -> bool:
    if any(item.get("source_path") == source_path for item in documents):
        return True
    return any(item.get("source_path") == source_path for item in chunks)


def _stable_file_name(*, prefix: str, source_path: str) -> str:
    sanitized_prefix = _sanitize_segment(Path(source_path).stem or prefix)
    digest = sha256(source_path.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{sanitized_prefix}-{digest}.json"


def _chunk_sort_key(record: StageDChunkRecord) -> tuple[str, str, str]:
    return (record.source_path, record.section_anchor, record.chunk_id)


def _sanitize_segment(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "unknown"
    return _SAFE_SEGMENT_RE.sub("-", normalized)


def _json_checksum(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _resolve_repository_product_id(
    *,
    scope_summaries: Sequence[CanonicalStagingScopeSummary],
    canonical_documents: Sequence[NormalizedDocument],
    chunk_records: Sequence[StageDChunkRecord],
    fallback_product_id: str | None = None,
) -> str:
    if fallback_product_id is not None and fallback_product_id.strip():
        return fallback_product_id
    if scope_summaries:
        return scope_summaries[0].product_id
    if canonical_documents:
        return canonical_documents[0].document.product_id
    if chunk_records:
        return chunk_records[0].product_id
    return "unknown"


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None


def _normalize_snapshot_tier(snapshot_tier: StagingSnapshotTier | str) -> StagingSnapshotTier:
    if isinstance(snapshot_tier, StagingSnapshotTier):
        return snapshot_tier
    normalized = snapshot_tier.strip().lower()
    if normalized == StagingSnapshotTier.PUBLISH.value:
        return StagingSnapshotTier.PUBLISH
    if normalized == StagingSnapshotTier.REVIEW.value:
        return StagingSnapshotTier.REVIEW
    msg = "snapshot_tier must be one of: publish, review."
    raise ValueError(msg)


def _repository_storage_segment(
    *,
    repo_id: str,
    snapshot_tier: StagingSnapshotTier,
    operation_id: str,
) -> str:
    sanitized_repo_id = _sanitize_segment(repo_id)
    if snapshot_tier is StagingSnapshotTier.PUBLISH:
        return sanitized_repo_id
    return f"{sanitized_repo_id}--review--{_sanitize_segment(operation_id)}"


def _default_review_run_id(
    *,
    source_revision: str,
    file_checksums: Mapping[str, str],
) -> str:
    digest = sha256()
    digest.update(source_revision.encode("utf-8"))
    for source_path in sorted(file_checksums):
        digest.update(source_path.encode("utf-8"))
        digest.update(file_checksums[source_path].encode("utf-8"))
    return f"run-{digest.hexdigest()[:16]}"
