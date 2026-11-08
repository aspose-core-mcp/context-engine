from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from adcs.retrieval import (
    HybridCandidate,
    HybridRetriever,
    HybridScoringConfig,
    LaneCandidate,
    QueryPlan,
    QueryPlanner,
    QueryPlannerInput,
    RetrievalCandidateMetadata,
)


class _StubDenseLaneAdapter:
    def __init__(
        self,
        *,
        candidates: tuple[LaneCandidate, ...],
        raise_on_search: bool = False,
    ) -> None:
        self._candidates = candidates
        self._raise_on_search = raise_on_search
        self.search_limits: list[int] = []

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        if self._raise_on_search:
            msg = "Qdrant connection refused"
            raise RuntimeError(msg)
        self.search_limits.append(limit)
        return self._candidates[:limit]


class _StubLexicalLaneAdapter:
    def __init__(
        self,
        *,
        candidates: tuple[LaneCandidate, ...],
        raise_on_search: bool = False,
    ) -> None:
        self._candidates = candidates
        self._raise_on_search = raise_on_search
        self.search_limits: list[int] = []

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        if self._raise_on_search:
            msg = "OpenSearch connection refused"
            raise RuntimeError(msg)
        self.search_limits.append(limit)
        return self._candidates[:limit]


class _PassThroughReranker:
    def rerank(
        self,
        *,
        plan: QueryPlan,
        candidates: Sequence[HybridCandidate],
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        del plan
        return tuple(candidates[:limit])


def test_hybrid_retriever_fuses_scores_and_deduplicates_by_chunk_id() -> None:
    plan = _make_plan(query="How to use OCR API?")
    dense_adapter = _StubDenseLaneAdapter(
        candidates=(
            _lane_candidate(
                candidate_id="candidate-a-dense",
                chunk_id="chunk-a",
                raw_score=0.90,
                title="Recognize API",
                text="API reference content",
            ),
            _lane_candidate(
                candidate_id="candidate-b-dense",
                chunk_id="chunk-b",
                raw_score=0.80,
                title="Guide setup",
                text="Guide setup content",
            ),
            _lane_candidate(
                candidate_id="candidate-d-dense",
                chunk_id="chunk-d",
                raw_score=0.70,
                title="Troubleshooting",
                text="Troubleshooting steps",
            ),
        )
    )
    lexical_adapter = _StubLexicalLaneAdapter(
        candidates=(
            _lane_candidate(
                candidate_id="candidate-a-lexical",
                chunk_id="chunk-a",
                raw_score=100.0,
                title="Recognize API",
                text="API reference content",
            ),
            _lane_candidate(
                candidate_id="candidate-c-lexical",
                chunk_id="chunk-c",
                raw_score=90.0,
                title="Best practices",
                text="Best practices content",
            ),
            _lane_candidate(
                candidate_id="candidate-d-lexical",
                chunk_id="chunk-d",
                raw_score=80.0,
                title="Troubleshooting",
                text="Troubleshooting steps",
            ),
        )
    )
    retriever = HybridRetriever(
        dense_lane_adapter=dense_adapter,
        lexical_lane_adapter=lexical_adapter,
        scoring_config=HybridScoringConfig(
            dense_weight=0.6,
            lexical_weight=0.4,
            candidate_pool_size=10,
            rerank_top_k=10,
        ),
        reranker=_PassThroughReranker(),
    )

    result = retriever.retrieve(plan=plan)

    assert dense_adapter.search_limits == [10]
    assert lexical_adapter.search_limits == [10]
    assert [candidate.metadata.candidate_id for candidate in result.candidates] == [
        "candidate-a-dense",
        "candidate-b-dense",
        "candidate-c-lexical",
        "candidate-d-dense",
    ]
    assert result.candidates[0].dense_raw_score == pytest.approx(0.90)
    assert result.candidates[0].lexical_raw_score == pytest.approx(100.0)
    assert result.candidates[0].blended_score == pytest.approx(1.0)
    assert result.candidates[1].lexical_raw_score is None
    assert result.candidates[1].blended_score == pytest.approx(0.3)
    assert result.candidates[2].dense_raw_score is None
    assert result.candidates[2].blended_score == pytest.approx(0.2)
    assert result.dense_candidates_count == 3
    assert result.lexical_candidates_count == 3
    assert result.fused_candidates_count == 4
    assert result.dense_weight == pytest.approx(0.6)
    assert result.lexical_weight == pytest.approx(0.4)


def test_hybrid_retriever_applies_rerank_top_k_with_deterministic_reranker() -> None:
    plan = _make_plan(query="How to call Aspose.OCR.Engine.Recognize?")
    dense_adapter = _StubDenseLaneAdapter(
        candidates=(
            _lane_candidate(
                candidate_id="guide-dense",
                chunk_id="chunk-guide",
                raw_score=0.95,
                title="OCR installation guide",
                text="Installation prerequisites and basic setup flow.",
                symbol_fqn=None,
            ),
            _lane_candidate(
                candidate_id="symbol-dense",
                chunk_id="chunk-symbol",
                raw_score=0.90,
                title="Aspose.OCR.Engine.Recognize method",
                text="Use Aspose.OCR.Engine.Recognize to extract text from images.",
                symbol_fqn="Aspose.OCR.Engine.Recognize",
            ),
            _lane_candidate(
                candidate_id="noise-dense",
                chunk_id="chunk-noise",
                raw_score=0.40,
                title="Unrelated note",
                text="General product announcement.",
                symbol_fqn=None,
            ),
        )
    )
    lexical_adapter = _StubLexicalLaneAdapter(
        candidates=(
            _lane_candidate(
                candidate_id="guide-lexical",
                chunk_id="chunk-guide",
                raw_score=0.96,
                title="OCR installation guide",
                text="Installation prerequisites and basic setup flow.",
                symbol_fqn=None,
            ),
            _lane_candidate(
                candidate_id="noise-lexical",
                chunk_id="chunk-noise",
                raw_score=0.50,
                title="Unrelated note",
                text="General product announcement.",
                symbol_fqn=None,
            ),
        )
    )
    retriever = HybridRetriever(
        dense_lane_adapter=dense_adapter,
        lexical_lane_adapter=lexical_adapter,
        scoring_config=HybridScoringConfig(
            dense_weight=0.9,
            lexical_weight=0.1,
            candidate_pool_size=3,
            rerank_top_k=2,
        ),
    )

    result = retriever.retrieve(plan=plan)

    assert len(result.candidates) == 2
    assert result.fused_candidates_count == 3
    assert [candidate.metadata.candidate_id for candidate in result.candidates] == [
        "symbol-dense",
        "guide-dense",
    ]
    assert result.candidates[0].rerank_score > result.candidates[1].rerank_score


def _make_plan(*, query: str) -> QueryPlan:
    planner = QueryPlanner()
    return planner.plan(
        request=QueryPlannerInput(
            query=query,
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )


def _lane_candidate(
    *,
    candidate_id: str,
    chunk_id: str,
    raw_score: float,
    title: str,
    text: str,
    symbol_fqn: str | None = None,
) -> LaneCandidate:
    return LaneCandidate(
        metadata=_metadata(
            candidate_id=candidate_id,
            chunk_id=chunk_id,
            title=title,
            text=text,
            symbol_fqn=symbol_fqn,
        ),
        raw_score=raw_score,
    )


def test_sync_retrieve_degrades_when_dense_lane_fails() -> None:
    """When dense lane raises, retriever returns lexical-only results."""
    plan = _make_plan(query="OCR quickstart")
    lexical_candidate = _lane_candidate(
        candidate_id="lex-a", chunk_id="chunk-a", raw_score=50.0,
        title="Quickstart", text="Getting started",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_StubDenseLaneAdapter(candidates=(), raise_on_search=True),
        lexical_lane_adapter=_StubLexicalLaneAdapter(candidates=(lexical_candidate,)),
        scoring_config=HybridScoringConfig(candidate_pool_size=10, rerank_top_k=10),
        reranker=_PassThroughReranker(),
    )

    result = retriever.retrieve(plan=plan)

    assert result.dense_candidates_count == 0
    assert result.lexical_candidates_count == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].metadata.candidate_id == "lex-a"


def test_sync_retrieve_degrades_when_lexical_lane_fails() -> None:
    """When lexical lane raises, retriever returns dense-only results."""
    plan = _make_plan(query="OCR quickstart")
    dense_candidate = _lane_candidate(
        candidate_id="dns-a", chunk_id="chunk-a", raw_score=0.9,
        title="Quickstart", text="Getting started",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_StubDenseLaneAdapter(candidates=(dense_candidate,)),
        lexical_lane_adapter=_StubLexicalLaneAdapter(candidates=(), raise_on_search=True),
        scoring_config=HybridScoringConfig(candidate_pool_size=10, rerank_top_k=10),
        reranker=_PassThroughReranker(),
    )

    result = retriever.retrieve(plan=plan)

    assert result.dense_candidates_count == 1
    assert result.lexical_candidates_count == 0
    assert len(result.candidates) == 1


def test_sync_retrieve_returns_empty_when_both_lanes_fail() -> None:
    """When both lanes raise, retriever returns empty results."""
    plan = _make_plan(query="OCR quickstart")
    retriever = HybridRetriever(
        dense_lane_adapter=_StubDenseLaneAdapter(candidates=(), raise_on_search=True),
        lexical_lane_adapter=_StubLexicalLaneAdapter(candidates=(), raise_on_search=True),
        scoring_config=HybridScoringConfig(candidate_pool_size=10, rerank_top_k=10),
        reranker=_PassThroughReranker(),
    )

    result = retriever.retrieve(plan=plan)

    assert result.dense_candidates_count == 0
    assert result.lexical_candidates_count == 0
    assert len(result.candidates) == 0


# ---------------------------------------------------------------------------
# Coverage for async_retrieve, tiebreakers, and _select_metadata.
# ---------------------------------------------------------------------------


class _AsyncDenseLaneAdapter:
    """Adapter that exposes ``async_search`` so the async path skips to_thread."""

    def __init__(
        self,
        *,
        candidates: tuple[LaneCandidate, ...],
        raise_on_search: bool = False,
    ) -> None:
        self._candidates = candidates
        self._raise_on_search = raise_on_search

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        # Should never be called in async path when async_search is present.
        del plan
        return self._candidates[:limit]

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        del plan
        if self._raise_on_search:
            msg = "Qdrant async failure"
            raise RuntimeError(msg)
        return self._candidates[:limit]


class _AsyncLexicalLaneAdapter:
    def __init__(
        self,
        *,
        candidates: tuple[LaneCandidate, ...],
        raise_on_search: bool = False,
    ) -> None:
        self._candidates = candidates
        self._raise_on_search = raise_on_search

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        return self._candidates[:limit]

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        del plan
        if self._raise_on_search:
            msg = "OpenSearch async failure"
            raise RuntimeError(msg)
        return self._candidates[:limit]


def test_async_retrieve_with_sync_adapters_uses_thread_offload() -> None:
    """Sync-only adapters are offloaded via asyncio.to_thread (covers else branches)."""
    plan = _make_plan(query="async offload")
    dense_candidate = _lane_candidate(
        candidate_id="dns-async", chunk_id="chunk-a", raw_score=0.7,
        title="A", text="alpha",
    )
    lexical_candidate = _lane_candidate(
        candidate_id="lex-async", chunk_id="chunk-b", raw_score=10.0,
        title="B", text="beta",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_StubDenseLaneAdapter(candidates=(dense_candidate,)),
        lexical_lane_adapter=_StubLexicalLaneAdapter(candidates=(lexical_candidate,)),
        scoring_config=HybridScoringConfig(candidate_pool_size=5, rerank_top_k=5),
        reranker=_PassThroughReranker(),
    )

    result = asyncio.run(retriever.async_retrieve(plan=plan))

    assert result.dense_candidates_count == 1
    assert result.lexical_candidates_count == 1
    assert {c.metadata.candidate_id for c in result.candidates} == {
        "dns-async",
        "lex-async",
    }


def test_async_retrieve_with_async_adapters() -> None:
    """When adapters expose async_search, that path is used directly."""
    plan = _make_plan(query="async native")
    dense_candidate = _lane_candidate(
        candidate_id="dns-native", chunk_id="chunk-a", raw_score=0.5,
        title="A", text="alpha",
    )
    lexical_candidate = _lane_candidate(
        candidate_id="lex-native", chunk_id="chunk-a", raw_score=20.0,
        title="A", text="alpha",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_AsyncDenseLaneAdapter(candidates=(dense_candidate,)),
        lexical_lane_adapter=_AsyncLexicalLaneAdapter(candidates=(lexical_candidate,)),
        scoring_config=HybridScoringConfig(candidate_pool_size=5, rerank_top_k=5),
        reranker=_PassThroughReranker(),
    )

    result = asyncio.run(retriever.async_retrieve(plan=plan))

    assert result.dense_candidates_count == 1
    assert result.lexical_candidates_count == 1
    # Same chunk fused across lanes
    assert len(result.candidates) == 1


def test_async_retrieve_degrades_when_dense_lane_raises() -> None:
    """Dense lane raises -> retriever falls back to lexical-only."""
    plan = _make_plan(query="dense fails")
    lex = _lane_candidate(
        candidate_id="lex-only", chunk_id="chunk-a", raw_score=42.0,
        title="A", text="alpha",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_AsyncDenseLaneAdapter(candidates=(), raise_on_search=True),
        lexical_lane_adapter=_AsyncLexicalLaneAdapter(candidates=(lex,)),
        scoring_config=HybridScoringConfig(candidate_pool_size=5, rerank_top_k=5),
        reranker=_PassThroughReranker(),
    )

    result = asyncio.run(retriever.async_retrieve(plan=plan))

    assert result.dense_candidates_count == 0
    assert result.lexical_candidates_count == 1
    assert result.candidates[0].metadata.candidate_id == "lex-only"


def test_async_retrieve_degrades_when_lexical_lane_raises() -> None:
    """Lexical lane raises -> retriever falls back to dense-only."""
    plan = _make_plan(query="lexical fails")
    dense = _lane_candidate(
        candidate_id="dns-only", chunk_id="chunk-a", raw_score=0.42,
        title="A", text="alpha",
    )
    retriever = HybridRetriever(
        dense_lane_adapter=_AsyncDenseLaneAdapter(candidates=(dense,)),
        lexical_lane_adapter=_AsyncLexicalLaneAdapter(
            candidates=(), raise_on_search=True
        ),
        scoring_config=HybridScoringConfig(candidate_pool_size=5, rerank_top_k=5),
        reranker=_PassThroughReranker(),
    )

    result = asyncio.run(retriever.async_retrieve(plan=plan))

    assert result.dense_candidates_count == 1
    assert result.lexical_candidates_count == 0
    assert result.candidates[0].metadata.candidate_id == "dns-only"


def test_async_retrieve_returns_empty_when_both_lanes_raise() -> None:
    """Both lanes raise -> retriever returns empty result without raising."""
    plan = _make_plan(query="all fail")
    retriever = HybridRetriever(
        dense_lane_adapter=_AsyncDenseLaneAdapter(
            candidates=(), raise_on_search=True
        ),
        lexical_lane_adapter=_AsyncLexicalLaneAdapter(
            candidates=(), raise_on_search=True
        ),
        scoring_config=HybridScoringConfig(candidate_pool_size=5, rerank_top_k=5),
        reranker=_PassThroughReranker(),
    )

    result = asyncio.run(retriever.async_retrieve(plan=plan))

    assert result.dense_candidates_count == 0
    assert result.lexical_candidates_count == 0
    assert result.candidates == ()


def test_best_candidate_per_chunk_keeps_higher_raw_score() -> None:
    """When two candidates share a chunk_id, the higher raw_score wins (line 179-181)."""
    from adcs.retrieval.hybrid_retriever import _best_candidate_per_chunk

    lower = _lane_candidate(
        candidate_id="cand-low", chunk_id="chunk-x", raw_score=0.3,
        title="X", text="xx",
    )
    higher = _lane_candidate(
        candidate_id="cand-high", chunk_id="chunk-x", raw_score=0.9,
        title="X", text="xx",
    )

    best = _best_candidate_per_chunk(candidates=(lower, higher))

    assert set(best.keys()) == {"chunk-x"}
    assert best["chunk-x"].metadata.candidate_id == "cand-high"


def test_best_candidate_per_chunk_breaks_tie_by_candidate_id() -> None:
    """When raw_score ties, the lexicographically smaller candidate_id wins (lines 182-186)."""
    from adcs.retrieval.hybrid_retriever import _best_candidate_per_chunk

    bigger_id = _lane_candidate(
        candidate_id="cand-z",
        chunk_id="chunk-x",
        raw_score=0.7,
        title="X",
        text="xx",
    )
    smaller_id = _lane_candidate(
        candidate_id="cand-a",
        chunk_id="chunk-x",
        raw_score=0.7,
        title="X",
        text="xx",
    )

    # Order must not affect the result; insertion order tries the bigger id first.
    best = _best_candidate_per_chunk(candidates=(bigger_id, smaller_id))

    assert best["chunk-x"].metadata.candidate_id == "cand-a"


def test_select_metadata_raises_when_both_lanes_missing() -> None:
    """_select_metadata is a defensive guard; both-None must raise (lines 261-262)."""
    from adcs.retrieval.hybrid_retriever import _select_metadata

    with pytest.raises(ValueError, match="At least one lane candidate"):
        _select_metadata(dense_candidate=None, lexical_candidate=None)


def _metadata(
    *,
    candidate_id: str,
    chunk_id: str,
    title: str,
    text: str,
    symbol_fqn: str | None,
) -> RetrievalCandidateMetadata:
    return RetrievalCandidateMetadata(
        candidate_id=candidate_id,
        chunk_id=chunk_id,
        snapshot_id="snapshot-25.1",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="apiref",
        doc_type="api_method",
        doc_locale="en",
        symbol_fqn=symbol_fqn,
        title=title,
        canonical_url=f"https://docs.aspose.com/ocr/net/{chunk_id}/",
        section_anchor="#main",
        source_revision="revision-abc123",
        repo_id="aspose.ocr.docs",
        text=text,
        checksum=f"checksum-{chunk_id}",
    )
