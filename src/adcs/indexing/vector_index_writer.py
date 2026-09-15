"""Vector-lane index writer contracts and in-memory adapter."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from threading import Lock
from typing import Protocol
from urllib import error, request

from adcs.indexing.index_models import VectorIndexRecord, VectorWriteResult
from adcs.indexing.topology_policy import IndexTopologyPolicy


def _to_qdrant_uuid(point_id: str) -> str:
    """Convert an arbitrary string point_id to a deterministic UUID for Qdrant."""
    digest = hashlib.sha256(point_id.encode()).digest()[:16]
    return str(uuid.UUID(bytes=digest))


class VectorIndexWriter(Protocol):
    """Contract for vector lane writers (Qdrant-style payload model)."""

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[VectorIndexRecord],
    ) -> VectorWriteResult:
        """Persist vector records for one snapshot."""


class InMemoryVectorIndexWriter:
    """In-memory vector index writer for development and tests."""

    def __init__(self, *, topology_policy: IndexTopologyPolicy | None = None) -> None:
        del topology_policy
        self._lock = Lock()
        self._records_by_snapshot: dict[str, tuple[VectorIndexRecord, ...]] = {}
        self._collection_by_snapshot: dict[str, str] = {}

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[VectorIndexRecord],
    ) -> VectorWriteResult:
        collection_name = _collection_for_source_kind(source_kind=source_kind)
        with self._lock:
            self._records_by_snapshot[snapshot_id] = tuple(records)
            self._collection_by_snapshot[snapshot_id] = collection_name
        return VectorWriteResult(collection_name=collection_name, written_count=len(records))

    def get_snapshot_records(self, snapshot_id: str) -> tuple[VectorIndexRecord, ...]:
        with self._lock:
            return self._records_by_snapshot.get(snapshot_id, ())

    def get_collection_name(self, snapshot_id: str) -> str | None:
        with self._lock:
            return self._collection_by_snapshot.get(snapshot_id)


# Legacy defaults, kept only as the fallback when no collection names are passed
# in. The serving read lane takes its collection names from settings; a write path
# left on these literals would send writes, retention purges and admin index-status
# to a collection nobody reads once the alias is dropped. Callers should thread
# settings.docs_vector_collection / apiref_vector_collection through.
_DEFAULT_DOCS_COLLECTION = "docs_dense_v1"
_DEFAULT_APIREF_COLLECTION = "apiref_dense_v1"


def _collection_for_source_kind(
    *,
    source_kind: str,
    docs_collection: str = _DEFAULT_DOCS_COLLECTION,
    apiref_collection: str = _DEFAULT_APIREF_COLLECTION,
) -> str:
    if source_kind == "apiref":
        return apiref_collection
    return docs_collection


class QdrantVectorIndexWriter:
    """Qdrant-backed vector index writer for production-oriented local runtime."""

    def __init__(
        self,
        *,
        qdrant_url: str,
        timeout_seconds: float = 5.0,
        topology_policy: IndexTopologyPolicy | None = None,
        docs_collection: str = _DEFAULT_DOCS_COLLECTION,
        apiref_collection: str = _DEFAULT_APIREF_COLLECTION,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._topology_policy = topology_policy
        self._docs_collection = docs_collection
        self._apiref_collection = apiref_collection

    _UPSERT_BATCH_SIZE = 100

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[VectorIndexRecord],
    ) -> VectorWriteResult:
        del snapshot_id
        collection_name = _collection_for_source_kind(
            source_kind=source_kind,
            docs_collection=self._docs_collection,
            apiref_collection=self._apiref_collection,
        )
        if not records:
            return VectorWriteResult(collection_name=collection_name, written_count=0)

        vector_size = len(records[0].vector)
        self._ensure_collection(collection_name=collection_name, vector_size=vector_size)

        total_written = 0
        for start in range(0, len(records), self._UPSERT_BATCH_SIZE):
            batch = records[start : start + self._UPSERT_BATCH_SIZE]
            points_payload = [self._to_point(record=record) for record in batch]
            status_code, body = _request_json(
                url=f"{self._qdrant_url}/collections/{collection_name}/points?wait=true",
                method="PUT",
                payload={"points": points_payload},
                timeout_seconds=max(self._timeout_seconds, 30.0),
            )
            if status_code not in {200}:
                msg = f"Qdrant upsert failed (status={status_code}, body={body!r})."
                raise RuntimeError(msg)
            total_written += len(batch)

        return VectorWriteResult(collection_name=collection_name, written_count=total_written)

    @staticmethod
    def _to_point(*, record: VectorIndexRecord) -> dict[str, object]:
        return {
            "id": _to_qdrant_uuid(record.point_id),
            "vector": list(record.vector),
            "payload": {
                "chunk_id": record.chunk_id,
                "snapshot_id": record.snapshot_id,
                "product_id": record.product_id,
                "product_family": record.product_family,
                "programming_language": record.programming_language,
                "version": record.version,
                "source_kind": record.source_kind,
                "doc_type": record.doc_type,
                "doc_locale": record.doc_locale,
                "symbol_fqn": record.symbol_fqn,
                "title": record.title,
                "canonical_url": record.canonical_url,
                "section_anchor": record.section_anchor,
                "source_revision": record.source_revision,
                "repo_id": record.repo_id,
                "checksum": record.checksum,
                "text": record.text,
                "executable_snippets": [
                    {
                        "snippet_id": snippet.snippet_id,
                        "language": snippet.language,
                        "code": snippet.code,
                        "parent_canonical_url": snippet.parent_canonical_url,
                        "parent_section_anchor": snippet.parent_section_anchor,
                        "parent_symbol_fqn": snippet.parent_symbol_fqn,
                    }
                    for snippet in record.executable_snippets
                ],
            },
        }

    def _ensure_collection(self, *, collection_name: str, vector_size: int) -> None:
        status_code, body = _request_json(
            url=f"{self._qdrant_url}/collections/{collection_name}",
            method="GET",
            payload=None,
            timeout_seconds=self._timeout_seconds,
        )
        if status_code == 200:
            return
        if status_code != 404:
            msg = f"Qdrant collection lookup failed (status={status_code}, body={body!r})."
            raise RuntimeError(msg)

        payload: dict[str, object] = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine",
            }
        }
        if self._topology_policy is not None:
            payload["shard_number"] = self._topology_policy.qdrant.shard_number
            payload["replication_factor"] = self._topology_policy.qdrant.replication_factor
            payload["write_consistency_factor"] = (
                self._topology_policy.qdrant.write_consistency_factor
            )

        create_status, create_body = _request_json(
            url=f"{self._qdrant_url}/collections/{collection_name}",
            method="PUT",
            payload=payload,
            timeout_seconds=self._timeout_seconds,
        )
        if create_status not in {200}:
            msg = (
                f"Qdrant collection create failed (status={create_status}, "
                f"body={create_body!r})."
            )
            raise RuntimeError(msg)


def _request_json(
    *,
    url: str,
    method: str,
    payload: dict[str, object] | None,
    timeout_seconds: float,
) -> tuple[int, object]:
    body: bytes | None = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            return response.status, _decode_json(raw_body)
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(raw_body)
    except error.URLError as exc:
        msg = f"Qdrant request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _decode_json(raw_body: str) -> object:
    if not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


_QDRANT_COLLECTIONS = (_DEFAULT_DOCS_COLLECTION, _DEFAULT_APIREF_COLLECTION)


class InMemoryVectorIndexPurger:
    """In-memory vector purger for tests — tracks purge calls."""

    def __init__(self) -> None:
        self._purged_ids: list[str] = []
        self._purge_count = 0

    def purge_snapshot_vectors(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> int:
        self._purged_ids.extend(snapshot_ids)
        count = len(snapshot_ids) * 10  # synthetic count for test assertion
        self._purge_count += count
        return count

    @property
    def purged_snapshot_ids(self) -> tuple[str, ...]:
        return tuple(self._purged_ids)


class QdrantVectorIndexPurger:
    """Delete Qdrant points by snapshot_id payload filter across all collections."""

    _DELETE_BATCH_LIMIT = 500

    def __init__(
        self,
        *,
        qdrant_url: str,
        timeout_seconds: float = 30.0,
        collections: tuple[str, ...] = _QDRANT_COLLECTIONS,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        # Retention purges must target the collections actually written to. A
        # purger pinned to the legacy names skips the served collection silently
        # (`_collection_exists` returns False -> `continue`), so retention appears
        # to run while deleting nothing.
        self._collections = collections

    def purge_snapshot_vectors(
        self,
        *,
        snapshot_ids: tuple[str, ...],
    ) -> int:
        if not snapshot_ids:
            return 0

        total_purged = 0
        for collection_name in self._collections:
            if not self._collection_exists(collection_name):
                continue
            for batch_start in range(0, len(snapshot_ids), self._DELETE_BATCH_LIMIT):
                batch = snapshot_ids[batch_start : batch_start + self._DELETE_BATCH_LIMIT]
                purged = self._delete_by_snapshot_ids(
                    collection_name=collection_name,
                    snapshot_ids=batch,
                )
                total_purged += purged
        return total_purged

    def _collection_exists(self, collection_name: str) -> bool:
        status_code, _ = _request_json(
            url=f"{self._qdrant_url}/collections/{collection_name}",
            method="GET",
            payload=None,
            timeout_seconds=self._timeout_seconds,
        )
        return status_code == 200

    def _delete_by_snapshot_ids(
        self,
        *,
        collection_name: str,
        snapshot_ids: tuple[str, ...] | Sequence[str],
    ) -> int:
        filter_payload: dict[str, object] = {
            "filter": {
                "should": [
                    {"key": "snapshot_id", "match": {"value": sid}}
                    for sid in snapshot_ids
                ]
            }
        }
        status_code, body = _request_json(
            url=(
                f"{self._qdrant_url}/collections/{collection_name}"
                f"/points/delete?wait=true"
            ),
            method="POST",
            payload=filter_payload,
            timeout_seconds=max(self._timeout_seconds, 60.0),
        )
        if status_code not in {200}:
            msg = (
                f"Qdrant delete by snapshot_id failed "
                f"(collection={collection_name}, status={status_code}, body={body!r})"
            )
            raise RuntimeError(msg)
        if isinstance(body, dict):
            result = body.get("result", {})
            if isinstance(result, dict):
                status = result.get("status")
                if status == "acknowledged":
                    # Qdrant returns acknowledged for filter deletes;
                    # exact count is not available via this API path.
                    # We return len(snapshot_ids) as a proxy.
                    return len(snapshot_ids)
        return len(snapshot_ids)
