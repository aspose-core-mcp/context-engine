"""Qdrant/OpenSearch retrieval-lane adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from urllib import error, request

from adcs.indexing.embedding_provider import DeterministicLocalEmbeddingProvider, EmbeddingProvider
from adcs.retrieval.models import QueryPlan, RetrievalFilterRoute
from adcs.retrieval.retrieval_models import (
    LaneCandidate,
    RetrievalCandidateMetadata,
    RetrievalExecutableSnippet,
)

logger = logging.getLogger(__name__)

# Sentinel value used when the resolved set of active snapshots is empty.
# A real snapshot id can never equal this value, so the filter matches nothing
# and retrieval correctly returns zero results instead of serving stale points
# from inactive snapshots.
_NO_ACTIVE_SNAPSHOT_SENTINEL = "__D12_NO_ACTIVE_SNAPSHOT__"

# Locale expansion map: maps a canonical ISO locale to all index-level values
# that should be considered equivalent when querying Qdrant/OpenSearch.
# This compensates for inconsistent doc_locale values in indexed data
# (e.g., "english", "unknown") without requiring a costly re-index.
_LOCALE_INDEX_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "en": ("en", "english", "unknown"),
    "ru": ("ru", "russian"),
    "it": ("it", "italian"),
    "zh": ("zh", "chinese"),
    "de": ("de", "german"),
    "fr": ("fr", "french"),
    "es": ("es", "spanish"),
    "pt": ("pt", "portuguese"),
    "ar": ("ar", "arabic"),
    "ja": ("ja", "japanese"),
    "ko": ("ko", "korean"),
    "tr": ("tr", "turkish"),
    "pl": ("pl", "polish"),
    "nl": ("nl", "dutch"),
    "uk": ("uk", "ukrainian"),
    "bg": ("bg", "bulgarian"),
    "ro": ("ro", "romanian"),
    "th": ("th", "thai"),
    "vi": ("vi", "vietnamese"),
    "fa": ("fa", "persian"),
    "he": ("he", "hebrew"),
    "id": ("id", "indonesian"),
}


class _EmbeddingCache:
    """Thread-safe LRU cache for query embedding vectors."""

    def __init__(self, *, max_size: int = 256) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[float, ...] | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, vector: tuple[float, ...]) -> None:
        with self._lock:
            self._cache[key] = vector
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


class QdrantDenseLaneAdapter:
    """Dense retrieval lane adapter backed by Qdrant."""

    def __init__(
        self,
        *,
        qdrant_url: str,
        collection_names: tuple[str, ...] = ("docs_dense_v1", "apiref_dense_v1"),
        embedding_provider: EmbeddingProvider | None = None,
        timeout_seconds: float = 3.0,
        embedding_cache_size: int = 256,
    ) -> None:
        self._qdrant_url = qdrant_url.rstrip("/")
        self._collection_names = collection_names
        self._embedding_provider = embedding_provider or DeterministicLocalEmbeddingProvider()
        self._timeout_seconds = timeout_seconds
        self._embedding_cache = _EmbeddingCache(max_size=embedding_cache_size)

    def _embed_query(self, text: str) -> tuple[float, ...]:
        cache_key = hashlib.sha256(text.encode()).hexdigest()
        cached = self._embedding_cache.get(cache_key)
        if cached is not None:
            return cached
        vector = self._embedding_provider.embed_texts(texts=(text,))[0]
        self._embedding_cache.put(cache_key, vector)
        return vector

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        if limit < 1:
            return ()

        query_vector = self._embed_query(plan.normalized_query)
        seen_chunk_ids: set[str] = set()
        scored: list[tuple[int, float, RetrievalCandidateMetadata]] = []

        for route_index, route in enumerate(plan.filters.routes):
            qdrant_filter = _to_qdrant_filter(
                route=route,
                strict_version=plan.filters.strict_version,
            )
            for collection_name in self._collection_names:
                status_code, body = _request_json(
                    url=f"{self._qdrant_url}/collections/{collection_name}/points/search",
                    method="POST",
                    payload={
                        "vector": list(query_vector),
                        "limit": limit,
                        "with_payload": True,
                        "filter": qdrant_filter,
                    },
                    timeout_seconds=self._timeout_seconds,
                    backend_name="qdrant",
                )
                if status_code == 404:
                    # Collection does not exist yet (no data published
                    # for this source kind).  Skip gracefully.
                    logger.debug(
                        "Qdrant collection %s not found (status=404), skipping",
                        collection_name,
                    )
                    continue
                if status_code != 200:
                    msg = (
                        "Qdrant dense search failed "
                        f"(collection={collection_name}, status={status_code}, body={body!r})."
                    )
                    raise RuntimeError(msg)
                if not isinstance(body, dict):
                    continue
                result = body.get("result")
                if not isinstance(result, list):
                    continue

                for raw_item in result:
                    if not isinstance(raw_item, dict):
                        continue
                    payload = raw_item.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    metadata = _to_metadata(
                        source_payload=payload,
                        candidate_prefix="dense",
                    )
                    if metadata.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(metadata.chunk_id)
                    raw_score = float(raw_item.get("score", 0.0))
                    scored.append((route_index, raw_score, metadata))

        ordered = sorted(
            scored,
            key=lambda item: (item[0], -item[1], item[2].candidate_id),
        )[:limit]
        return tuple(
            LaneCandidate(
                metadata=metadata,
                raw_score=raw_score,
            )
            for _, raw_score, metadata in ordered
        )

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        """Non-blocking wrapper that runs the sync search in a thread pool."""
        return await asyncio.to_thread(self.search, plan=plan, limit=limit)


class OpenSearchLexicalLaneAdapter:
    """Lexical retrieval lane adapter backed by OpenSearch."""

    def __init__(
        self,
        *,
        opensearch_url: str,
        index_aliases: tuple[str, ...] = ("docs_lex_v1_active", "apiref_lex_v1_active"),
        timeout_seconds: float = 3.0,
    ) -> None:
        self._opensearch_url = opensearch_url.rstrip("/")
        self._index_aliases = index_aliases
        self._timeout_seconds = timeout_seconds

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        if limit < 1:
            return ()

        seen_chunk_ids: set[str] = set()
        scored: list[tuple[int, float, RetrievalCandidateMetadata]] = []
        for route_index, route in enumerate(plan.filters.routes):
            for index_alias in self._index_aliases:
                status_code, body = _request_json(
                    url=f"{self._opensearch_url}/{index_alias}/_search",
                    method="POST",
                    payload={
                        "size": limit,
                        "query": {
                            "bool": {
                                "must": [
                                    {
                                        "match": {
                                            "text": {
                                                "query": plan.normalized_query,
                                            }
                                        }
                                    }
                                ],
                                "filter": _to_opensearch_filters(
                                    route=route,
                                    strict_version=plan.filters.strict_version,
                                ),
                            }
                        },
                    },
                    timeout_seconds=self._timeout_seconds,
                    backend_name="opensearch",
                )
                if status_code == 404:
                    # Alias/index does not exist yet (no data published
                    # for this source kind).  Skip gracefully.
                    logger.debug(
                        "OpenSearch alias %s not found (status=404), skipping",
                        index_alias,
                    )
                    continue
                if status_code != 200:
                    msg = (
                        "OpenSearch lexical search failed "
                        f"(index={index_alias}, status={status_code}, body={body!r})."
                    )
                    raise RuntimeError(msg)
                if not isinstance(body, dict):
                    continue
                hits_payload = body.get("hits")
                if not isinstance(hits_payload, dict):
                    continue
                raw_hits = hits_payload.get("hits")
                if not isinstance(raw_hits, list):
                    continue

                for raw_hit in raw_hits:
                    if not isinstance(raw_hit, dict):
                        continue
                    source_payload = raw_hit.get("_source")
                    if not isinstance(source_payload, dict):
                        continue
                    metadata = _to_metadata(
                        source_payload=source_payload,
                        candidate_prefix="lexical",
                    )
                    if metadata.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(metadata.chunk_id)
                    raw_score = float(raw_hit.get("_score", 0.0))
                    scored.append((route_index, raw_score, metadata))

        ordered = sorted(
            scored,
            key=lambda item: (item[0], -item[1], item[2].candidate_id),
        )[:limit]
        return tuple(
            LaneCandidate(
                metadata=metadata,
                raw_score=raw_score,
            )
            for _, raw_score, metadata in ordered
        )

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        """Non-blocking wrapper that runs the sync search in a thread pool."""
        return await asyncio.to_thread(self.search, plan=plan, limit=limit)


def _to_qdrant_filter(
    *,
    route: RetrievalFilterRoute,
    strict_version: bool,
) -> dict[str, object]:
    must: list[dict[str, object]] = []
    if route.product_id is not None:
        must.append({"key": "product_id", "match": {"value": route.product_id}})
    if route.programming_language is not None:
        must.append(
            {
                "key": "programming_language",
                "match": {"value": route.programming_language},
            }
        )
    if strict_version and route.version is not None:
        must.append({"key": "version", "match": {"value": route.version}})
    locale_variants = _LOCALE_INDEX_EXPANSIONS.get(route.doc_locale)
    if locale_variants is not None and len(locale_variants) > 1:
        must.append({"key": "doc_locale", "match": {"any": list(locale_variants)}})
    else:
        must.append({"key": "doc_locale", "match": {"value": route.doc_locale}})
    # Restrict results to currently-active snapshots so that stale points
    # from promoted-then-rolled-back snapshots do not leak into retrieval.
    if route.active_snapshot_ids is not None:
        active_ids = list(route.active_snapshot_ids) or [_NO_ACTIVE_SNAPSHOT_SENTINEL]
        if len(active_ids) == 1:
            must.append({"key": "snapshot_id", "match": {"value": active_ids[0]}})
        else:
            must.append({"key": "snapshot_id", "match": {"any": active_ids}})
    return {"must": must}


def _to_opensearch_filters(
    *,
    route: RetrievalFilterRoute,
    strict_version: bool,
) -> list[dict[str, object]]:
    locale_variants = _LOCALE_INDEX_EXPANSIONS.get(route.doc_locale)
    if locale_variants is not None and len(locale_variants) > 1:
        filters: list[dict[str, object]] = [
            {"terms": {"doc_locale": list(locale_variants)}}
        ]
    else:
        filters = [{"term": {"doc_locale": route.doc_locale}}]
    if route.product_id is not None:
        filters.append({"term": {"product_id": route.product_id}})
    if route.programming_language is not None:
        filters.append({"term": {"programming_language": route.programming_language}})
    if strict_version and route.version is not None:
        filters.append({"term": {"version": route.version}})
    # Defense in depth — even though the lexical-lane alias is already
    # scoped to the active snapshot, explicitly filter by snapshot_id to
    # guarantee parity with the dense lane whenever the caller has resolved
    # active snapshot ids from the registry.
    if route.active_snapshot_ids is not None:
        active_ids = list(route.active_snapshot_ids) or [_NO_ACTIVE_SNAPSHOT_SENTINEL]
        if len(active_ids) == 1:
            filters.append({"term": {"snapshot_id": active_ids[0]}})
        else:
            filters.append({"terms": {"snapshot_id": active_ids}})
    return filters


def _to_metadata(
    *,
    source_payload: dict[str, object],
    candidate_prefix: str,
) -> RetrievalCandidateMetadata:
    chunk_id = _as_str(source_payload.get("chunk_id"), fallback="")
    if not chunk_id:
        chunk_id = _as_str(source_payload.get("point_id"), fallback="unknown-chunk")
    return RetrievalCandidateMetadata(
        candidate_id=f"{candidate_prefix}:{chunk_id}",
        chunk_id=chunk_id,
        snapshot_id=_as_str(source_payload.get("snapshot_id"), fallback=""),
        product_id=_as_str(source_payload.get("product_id"), fallback=""),
        programming_language=_as_str(source_payload.get("programming_language"), fallback=""),
        version=_as_str(source_payload.get("version"), fallback=""),
        source_kind=_as_str(source_payload.get("source_kind"), fallback=""),
        doc_type=_as_str(source_payload.get("doc_type"), fallback=""),
        doc_locale=_as_str(source_payload.get("doc_locale"), fallback="en"),
        symbol_fqn=_nullable_str(source_payload.get("symbol_fqn")),
        title=_as_str(source_payload.get("title"), fallback=chunk_id),
        canonical_url=_as_str(source_payload.get("canonical_url"), fallback=""),
        section_anchor=_as_str(source_payload.get("section_anchor"), fallback=""),
        source_revision=_as_str(source_payload.get("source_revision"), fallback=""),
        repo_id=_as_str(source_payload.get("repo_id"), fallback=""),
        text=_as_str(source_payload.get("text"), fallback=""),
        checksum=_as_str(source_payload.get("checksum"), fallback=""),
        executable_snippets=_parse_executable_snippets(
            source_payload.get("executable_snippets")
        ),
    )


def _request_json(
    *,
    url: str,
    method: str,
    payload: dict[str, object],
    timeout_seconds: float,
    backend_name: str,
) -> tuple[int, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            return response.status, _decode_json(raw_body)
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(raw_body)
    except error.URLError as exc:
        msg = f"{backend_name} request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _decode_json(raw_body: str) -> object:
    if not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None


def _as_str(value: object, *, fallback: str) -> str:
    if value is None:
        return fallback
    normalized = str(value)
    return normalized if normalized else fallback


def _parse_executable_snippets(raw_value: object) -> tuple[RetrievalExecutableSnippet, ...]:
    if not isinstance(raw_value, list):
        return ()
    snippets: list[RetrievalExecutableSnippet] = []
    for index, item in enumerate(raw_value, start=1):
        if not isinstance(item, dict):
            continue
        snippet_id = _as_str(item.get("snippet_id"), fallback=f"snippet-{index}")
        snippets.append(
            RetrievalExecutableSnippet(
                snippet_id=snippet_id,
                language=_as_str(item.get("language"), fallback="unknown"),
                code=_as_str(item.get("code"), fallback=""),
                parent_canonical_url=_as_str(item.get("parent_canonical_url"), fallback=""),
                parent_section_anchor=_as_str(item.get("parent_section_anchor"), fallback=""),
                parent_symbol_fqn=_nullable_str(item.get("parent_symbol_fqn")),
            )
        )
    return tuple(snippets)
