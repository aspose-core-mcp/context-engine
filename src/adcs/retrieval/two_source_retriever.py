"""Two-source retrieval harness: Documentation (Qdrant) + API Reference (Postgres).

ADCS serves two structurally different corpora (ADR-011):

* **Documentation** — unstructured prose, served by the dense+lexical hybrid
  retriever over Qdrant/OpenSearch.
* **API Reference** — structured symbols, served by the Postgres symbol store
  (exact FQN, name search, full-text), no vectors.

This module always *fans out to both* (never routes to one — ADR-011
§Decision 4) and fuses the two ranked lists with
Reciprocal Rank Fusion (k=60). Raw scores from the two sources are not
comparable (cosine vs ts_rank vs trigram similarity), so RRF — which uses
only ranks — is the robust default.

Two refinements on top of plain RRF:

* **Exact-FQN short-circuit.** A query that is itself a dotted symbol path
  (``aspose.slides.Presentation.Save``) is answered authoritatively by the
  symbol store; those hits are pinned to the top, above the fused tail.
* **Light cross-source dedup.** A doc chunk and a symbol that share a
  ``canonical_url`` are merged into one hit whose RRF score sums both
  contributions (the ADR flags docs↔apiref dedup as previously unverified).

The docs/apiref lanes are Protocols so the harness is unit-testable with
fakes; the concrete :class:`ApiRefRetriever` wraps an
:class:`~adcs.indexing.apiref_symbol_store.ApiRefSymbolStore`, and a docs-lane
adapter over the existing HybridRetriever is wired at the MCP/REST layer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    ApiRefSymbolStore,
)
from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.models import QueryPlannerInput
from adcs.retrieval.query_planner import QueryPlanner
from adcs.retrieval.retrieval_models import HybridCandidate

DEFAULT_RRF_K = 60
_FQN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")

SOURCE_DOCS = "docs"
SOURCE_APIREF = "apiref"


@dataclass(frozen=True, slots=True)
class UnifiedHit:
    """One fused retrieval result, from docs, apiref, or both (deduped)."""

    source: str
    result_id: str
    title: str
    canonical_url: str
    snippet: str
    rrf_score: float
    is_exact_symbol: bool = False
    docs_candidate: HybridCandidate | None = None
    apiref_symbol: ApiRefSymbol | None = None


@dataclass(frozen=True, slots=True)
class TwoSourceResult:
    """Outcome of a unified two-source retrieval."""

    query: str
    hits: tuple[UnifiedHit, ...]
    docs_count: int
    apiref_count: int
    exact_symbol_hit: bool
    rrf_k: int


class DocsLane(Protocol):
    """Documentation source (dense+lexical hybrid over Qdrant)."""

    def search(self, *, query: str, limit: int) -> Sequence[HybridCandidate]: ...


class ApiRefLane(Protocol):
    """API-reference source (Postgres symbol store)."""

    def lookup_exact(self, *, member_fqn: str, scope: ApiRefScope) -> Sequence[ApiRefSymbol]: ...

    def search(self, *, query: str, scope: ApiRefScope, limit: int) -> Sequence[ApiRefSymbol]: ...


def looks_like_fqn(query: str) -> bool:
    """True if the query is a bare dotted symbol path (no spaces, ≥1 dot)."""
    candidate = query.strip().removesuffix("()")
    return bool(_FQN_RE.match(candidate))


def _symbol_key(symbol: ApiRefSymbol) -> str:
    return f"{symbol.member_fqn}|{symbol.signature or ''}"


class ApiRefRetriever:
    """Concrete ApiRefLane over an :class:`ApiRefSymbolStore`.

    `search` blends name search (prefix/fuzzy) and full-text into one ranked
    list, deduped by (member_fqn, signature), preserving best rank.
    """

    def __init__(self, *, store: ApiRefSymbolStore) -> None:
        self._store = store

    def lookup_exact(self, *, member_fqn: str, scope: ApiRefScope) -> Sequence[ApiRefSymbol]:
        return self._store.get_symbol(member_fqn=member_fqn, scope=scope)

    def search(self, *, query: str, scope: ApiRefScope, limit: int) -> Sequence[ApiRefSymbol]:
        ordered: list[ApiRefSymbol] = []
        seen: set[str] = set()
        # Name search first (identifiers beat prose for symbol intent), then
        # full-text over name+summary fills in conceptual matches.
        for symbol in (
            *self._store.search_symbols(pattern=query, scope=scope, limit=limit),
            *self._store.fts_search(query=query, scope=scope, limit=limit),
        ):
            key = _symbol_key(symbol)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(symbol)
            if len(ordered) >= limit:
                break
        return tuple(ordered)


def _docs_hit(candidate: HybridCandidate, rrf_score: float) -> UnifiedHit:
    meta = candidate.metadata
    return UnifiedHit(
        source=SOURCE_DOCS,
        result_id=meta.chunk_id,
        title=meta.title,
        canonical_url=meta.canonical_url,
        snippet=meta.text,
        rrf_score=rrf_score,
        docs_candidate=candidate,
    )


def _apiref_hit(symbol: ApiRefSymbol, rrf_score: float, *, is_exact: bool = False) -> UnifiedHit:
    snippet = symbol.signature or symbol.summary or symbol.name
    return UnifiedHit(
        source=SOURCE_APIREF,
        result_id=_symbol_key(symbol),
        title=symbol.member_fqn,
        canonical_url=symbol.canonical_url or "",
        snippet=snippet,
        rrf_score=rrf_score,
        is_exact_symbol=is_exact,
        apiref_symbol=symbol,
    )


class TwoSourceRetriever:
    """Fan out to docs + apiref and fuse with RRF (k=60)."""

    def __init__(
        self,
        *,
        docs_lane: DocsLane,
        apiref_lane: ApiRefLane,
        rrf_k: int = DEFAULT_RRF_K,
        pool_size: int = 50,
    ) -> None:
        self._docs = docs_lane
        self._apiref = apiref_lane
        self._rrf_k = rrf_k
        self._pool_size = pool_size

    def retrieve(self, *, query: str, scope: ApiRefScope, limit: int = 10) -> TwoSourceResult:
        docs_hits = tuple(self._docs.search(query=query, limit=self._pool_size))
        apiref_hits = tuple(self._apiref.search(query=query, scope=scope, limit=self._pool_size))

        exact_symbols: tuple[ApiRefSymbol, ...] = ()
        if looks_like_fqn(query):
            exact_symbols = tuple(
                self._apiref.lookup_exact(member_fqn=query.strip().removesuffix("()"), scope=scope)
            )

        hits = self._fuse(
            docs_hits=docs_hits,
            apiref_hits=apiref_hits,
            exact_symbols=exact_symbols,
        )
        return TwoSourceResult(
            query=query,
            hits=hits[:limit],
            docs_count=len(docs_hits),
            apiref_count=len(apiref_hits),
            exact_symbol_hit=bool(exact_symbols),
            rrf_k=self._rrf_k,
        )

    def _fuse(
        self,
        *,
        docs_hits: Sequence[HybridCandidate],
        apiref_hits: Sequence[ApiRefSymbol],
        exact_symbols: Sequence[ApiRefSymbol],
    ) -> tuple[UnifiedHit, ...]:
        k = self._rrf_k
        # Accumulate RRF contributions keyed by canonical_url (cross-source
        # dedup) and carry the representative hit.
        contrib: dict[str, float] = {}
        representative: dict[str, UnifiedHit] = {}
        exact_keys = {_symbol_key(s) for s in exact_symbols}

        def _accumulate(key: str, score: float, hit: UnifiedHit) -> None:
            contrib[key] = contrib.get(key, 0.0) + score
            # Prefer an apiref representative over a docs one on a tie of keys
            # (the structured record is the more precise citation target).
            existing = representative.get(key)
            if existing is None or (existing.source == SOURCE_DOCS and hit.source == SOURCE_APIREF):
                representative[key] = hit

        for rank, candidate in enumerate(docs_hits, start=1):
            score = 1.0 / (k + rank)
            key = candidate.metadata.canonical_url or f"docs:{candidate.metadata.chunk_id}"
            _accumulate(key, score, _docs_hit(candidate, score))

        for rank, symbol in enumerate(apiref_hits, start=1):
            score = 1.0 / (k + rank)
            key = symbol.canonical_url or f"apiref:{_symbol_key(symbol)}"
            _accumulate(key, score, _apiref_hit(symbol, score))

        fused = [
            UnifiedHit(
                source=hit.source,
                result_id=hit.result_id,
                title=hit.title,
                canonical_url=hit.canonical_url,
                snippet=hit.snippet,
                rrf_score=contrib[key],
                is_exact_symbol=hit.result_id in exact_keys,
                docs_candidate=hit.docs_candidate,
                apiref_symbol=hit.apiref_symbol,
            )
            for key, hit in representative.items()
        ]
        # Exact-FQN matches pinned to the top, then by fused RRF score.
        fused.sort(key=lambda h: (not h.is_exact_symbol, -h.rrf_score, h.result_id))

        # Ensure exact symbols are present even if they fell outside the
        # apiref search pool (short-circuit guarantee).
        present_keys = {h.result_id for h in fused}
        missing_exact = [
            _apiref_hit(s, 1.0 / (k + 1), is_exact=True)
            for s in exact_symbols
            if _symbol_key(s) not in present_keys
        ]
        return tuple([*missing_exact, *fused])


class HybridRetrieverDocsLane:
    """DocsLane backed by the dense+lexical HybridRetriever (Qdrant/OpenSearch).

    Adapts the existing docs retrieval stack to the DocsLane Protocol: turns a
    query string into a QueryPlan (scoped to product/language/version/locale)
    and returns the reranked HybridCandidate list. This is what wires
    "Documentation on Qdrant" into the two-source harness.
    """

    def __init__(
        self,
        *,
        hybrid_retriever: HybridRetriever,
        scope: ApiRefScope,
        query_planner: QueryPlanner | None = None,
        strict_version: bool = False,
    ) -> None:
        self._retriever = hybrid_retriever
        self._planner = query_planner or QueryPlanner()
        self._scope = scope
        self._strict_version = strict_version

    def search(self, *, query: str, limit: int) -> Sequence[HybridCandidate]:
        plan = self._planner.plan(
            request=QueryPlannerInput(
                query=query,
                product_id=self._scope.product,
                programming_language=self._scope.language,
                version=self._scope.version,
                doc_locale=self._scope.locale,
                strict_version=self._strict_version,
            )
        )
        return self._retriever.retrieve(plan=plan).candidates[:limit]


__all__ = [
    "ApiRefLane",
    "ApiRefRetriever",
    "DocsLane",
    "HybridRetrieverDocsLane",
    "TwoSourceResult",
    "TwoSourceRetriever",
    "UnifiedHit",
    "looks_like_fqn",
]
