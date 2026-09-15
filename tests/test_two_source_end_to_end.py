"""End-to-end composition: Documentation (HybridRetriever) + API Reference (Postgres).

Proves the two corpora compose in one harness (ADR-011): a
query string flows through the real QueryPlanner → real HybridRetriever
(docs) and, in parallel, the structured symbol store (apiref), then fuses via
RRF. The dense/lexical lane adapters are stubbed — the Qdrant/OpenSearch
network adapters are exercised separately; here the composition is under test.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.models import QueryPlan
from adcs.retrieval.retrieval_models import (
    HybridScoringConfig,
    LaneCandidate,
    RetrievalCandidateMetadata,
)
from adcs.retrieval.two_source_retriever import (
    ApiRefRetriever,
    HybridRetrieverDocsLane,
    TwoSourceRetriever,
)

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")


def _lane_candidate(*, chunk_id: str, title: str, text: str, raw_score: float) -> LaneCandidate:
    meta = RetrievalCandidateMetadata(
        candidate_id=chunk_id,
        chunk_id=chunk_id,
        snapshot_id="docs-snap",
        product_id="aspose.slides",
        programming_language="net",
        version="24.1",
        source_kind="docs",
        doc_type="guide",
        doc_locale="en",
        symbol_fqn=None,
        title=title,
        canonical_url=f"https://docs.aspose.com/{chunk_id}",
        section_anchor="#main",
        source_revision="rev1",
        repo_id="aspose.slides.docs",
        text=text,
        checksum="x",
    )
    return LaneCandidate(metadata=meta, raw_score=raw_score)


class _StubLane:
    """Lane adapter returning fixed docs candidates regardless of plan."""

    def __init__(self, candidates: Sequence[LaneCandidate]) -> None:
        self._candidates = tuple(candidates)

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        return self._candidates[:limit]


def _docs_lane() -> HybridRetrieverDocsLane:
    docs = (
        _lane_candidate(
            chunk_id="guide-save",
            title="Saving a presentation",
            text="To save a presentation to a file, call the Save method.",
            raw_score=0.95,
        ),
        _lane_candidate(
            chunk_id="guide-slides",
            title="Working with slides",
            text="Iterate the Slides collection to add or remove slides.",
            raw_score=0.80,
        ),
    )
    hybrid = HybridRetriever(
        dense_lane_adapter=_StubLane(docs),
        lexical_lane_adapter=_StubLane(docs),
        scoring_config=HybridScoringConfig(candidate_pool_size=10, rerank_top_k=10),
    )
    return HybridRetrieverDocsLane(hybrid_retriever=hybrid, scope=SCOPE)


def _apiref_lane(store=None) -> ApiRefRetriever:
    store = store or InMemoryApiRefSymbolStore()
    if isinstance(store, InMemoryApiRefSymbolStore):
        store.upsert_symbols(
            [
                ApiRefSymbol(
                    snapshot_id="apiref-snap",
                    product=SCOPE.product,
                    language=SCOPE.language,
                    version=SCOPE.version,
                    locale=SCOPE.locale,
                    kind="method",
                    member_fqn="aspose.slides.Presentation.Save",
                    name="Save",
                    parent_fqn="aspose.slides.Presentation",
                    signature="void Save(string fileName, SaveFormat format)",
                    summary="Saves the presentation to a file.",
                    canonical_url="https://ref.aspose.com/Save",
                    is_deprecated=False,
                    payload={},
                ),
            ]
        )
        store.flip_active_snapshot(scope=SCOPE, snapshot_id="apiref-snap")
    return ApiRefRetriever(store=store)


def test_docs_lane_adapter_drives_real_hybrid_retriever() -> None:
    lane = _docs_lane()
    candidates = lane.search(query="how to save a presentation", limit=10)
    assert candidates
    assert all(c.metadata.source_kind == "docs" for c in candidates)


def test_two_source_fuses_docs_and_apiref() -> None:
    retriever = TwoSourceRetriever(docs_lane=_docs_lane(), apiref_lane=_apiref_lane())
    result = retriever.retrieve(query="save presentation", scope=SCOPE, limit=10)
    assert result.docs_count >= 1
    assert result.apiref_count >= 1
    assert {h.source for h in result.hits} == {"docs", "apiref"}


def test_two_source_exact_fqn_pins_symbol_over_docs() -> None:
    retriever = TwoSourceRetriever(docs_lane=_docs_lane(), apiref_lane=_apiref_lane())
    result = retriever.retrieve(query="aspose.slides.Presentation.Save", scope=SCOPE, limit=10)
    assert result.exact_symbol_hit
    assert result.hits[0].source == "apiref"
    assert result.hits[0].is_exact_symbol


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_two_source_end_to_end_with_real_postgres() -> None:
    pg_scope = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    store.upsert_symbols(
        [
            ApiRefSymbol(
                snapshot_id="e2e-snap",
                product=pg_scope.product,
                language=pg_scope.language,
                version=pg_scope.version,
                locale=pg_scope.locale,
                kind="method",
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(string fileName)",
                summary="Saves the presentation to a file.",
                canonical_url="https://ref.aspose.com/Save",
                is_deprecated=False,
                payload={},
            )
        ]
    )
    store.flip_active_snapshot(scope=pg_scope, snapshot_id="e2e-snap")
    retriever = TwoSourceRetriever(docs_lane=_docs_lane(), apiref_lane=ApiRefRetriever(store=store))

    fused = retriever.retrieve(query="save presentation", scope=pg_scope, limit=10)
    assert {h.source for h in fused.hits} == {"docs", "apiref"}

    exact = retriever.retrieve(query="aspose.slides.Presentation.Save", scope=pg_scope, limit=10)
    assert exact.hits[0].source == "apiref"
    assert exact.hits[0].is_exact_symbol
