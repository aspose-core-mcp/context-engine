"""Property-based tests for the deterministic reranker.

Fuzzes the limit-handling, subset-property, and sort-stability invariants
of DeterministicReranker.rerank across wide candidate-pool shapes and
limits. Uses lightweight synthetic HybridCandidate fixtures so the
tests stay decoupled from the full hybrid retrieval stack.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.models import (
    FilterDebugMetadata,
    QueryPlan,
    QueryPlanDebugMetadata,
    ResolvedRetrievalFilters,
    RetrievalFilterRoute,
)
from adcs.retrieval.reranker import DeterministicReranker
from adcs.retrieval.retrieval_models import (
    HybridCandidate,
    RetrievalCandidateMetadata,
)


def _make_plan() -> QueryPlan:
    """A minimal but valid QueryPlan for fuzzing reranker behaviour."""
    filters = ResolvedRetrievalFilters(
        product_id="aspose.ocr",
        programming_language="net",
        preferred_version=None,
        strict_version=False,
        strict_version_value=None,
        locale_routing_order=("en",),
        routes=(
            RetrievalFilterRoute(
                product_id="aspose.ocr",
                programming_language="net",
                version=None,
                doc_locale="en",
            ),
        ),
        debug=FilterDebugMetadata(
            requested_product_id=None,
            requested_programming_language=None,
            requested_version=None,
            requested_doc_locale=None,
            effective_product_id="aspose.ocr",
            effective_programming_language="net",
            preferred_version=None,
            strict_version_value=None,
            strict_version_enforced=False,
            locale_routing_order=("en",),
            locale_fallback_to_en_enabled=True,
        ),
    )
    debug = QueryPlanDebugMetadata(
        raw_query="how to recognize image",
        normalized_query="how to recognize image",
        removed_noise_prefixes=(),
        symbol_candidates=(),
        intent="how_to",
        intent_subtype=None,
        intent_reason_codes=("how_to_keyword",),
        detected_version_tokens=(),
        prefers_latest_stable=False,
        filter_debug=filters.debug,
    )
    return QueryPlan(
        normalized_query="how to recognize image",
        query_fingerprint="qfingerprint-xyz",
        symbol_candidates=(),
        intent="how_to",
        intent_subtype=None,
        intent_reason_codes=("how_to_keyword",),
        detected_version_tokens=(),
        prefers_latest_stable=False,
        filters=filters,
        debug=debug,
    )


def _make_candidate(idx: int, dense: float, lexical: float) -> HybridCandidate:
    """Lightweight HybridCandidate fixture parameterized by index + scores."""
    meta = RetrievalCandidateMetadata(
        candidate_id=f"cand-{idx}",
        chunk_id=f"chunk-{idx}",
        snapshot_id="snap-1",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="docs",
        doc_type="how_to",
        doc_locale="en",
        symbol_fqn=None,
        title=f"Doc {idx}",
        canonical_url=f"https://example.com/{idx}",
        section_anchor=f"sec-{idx}",
        source_revision=f"rev-{idx}",
        repo_id="aspose.ocr.docs",
        text=f"Body text for candidate {idx}.",
        checksum=f"chk-{idx}",
    )
    blended = max(dense, lexical)
    return HybridCandidate(
        metadata=meta,
        dense_raw_score=dense,
        lexical_raw_score=lexical,
        dense_normalized_score=dense,
        lexical_normalized_score=lexical,
        blended_score=blended,
        rerank_score=0.0,
    )


_score = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_pool_size = st.integers(min_value=0, max_value=25)
_limit = st.integers(min_value=-3, max_value=30)


@given(pool_size=_pool_size, limit=_limit, base=_score)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rerank_output_length_respects_limit(pool_size: int, limit: int, base: float) -> None:
    """Output length must be min(limit, pool_size) for limit >= 1, else 0."""
    reranker = DeterministicReranker()
    candidates = [
        _make_candidate(i, base + i * 0.01, base + i * 0.005) for i in range(pool_size)
    ]
    result = reranker.rerank(plan=_make_plan(), candidates=candidates, limit=limit)
    if limit < 1 or pool_size == 0:
        assert result == ()
    else:
        assert len(result) == min(limit, pool_size)


@given(pool_size=_pool_size, limit=_limit, base=_score)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rerank_output_is_subset_of_input(pool_size: int, limit: int, base: float) -> None:
    """Every output candidate must come from the input pool — no fabrication."""
    reranker = DeterministicReranker()
    candidates = [
        _make_candidate(i, base + i * 0.01, base + i * 0.005) for i in range(pool_size)
    ]
    input_ids = {c.metadata.candidate_id for c in candidates}
    result = reranker.rerank(plan=_make_plan(), candidates=candidates, limit=limit)
    for r in result:
        assert r.metadata.candidate_id in input_ids


@given(pool_size=st.integers(min_value=1, max_value=15), base=_score)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rerank_is_deterministic(pool_size: int, base: float) -> None:
    """Two rerank calls with the same input must produce equal output."""
    reranker = DeterministicReranker()
    candidates = [
        _make_candidate(i, base + i * 0.01, base + i * 0.005) for i in range(pool_size)
    ]
    a = reranker.rerank(plan=_make_plan(), candidates=candidates, limit=10)
    b = reranker.rerank(plan=_make_plan(), candidates=candidates, limit=10)
    assert a == b


@given(pool_size=st.integers(min_value=1, max_value=15), base=_score)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rerank_output_is_sorted_descending(pool_size: int, base: float) -> None:
    """Output candidates must be sorted by rerank_score descending."""
    reranker = DeterministicReranker()
    candidates = [
        _make_candidate(i, base + i * 0.01, base + i * 0.005) for i in range(pool_size)
    ]
    result = reranker.rerank(plan=_make_plan(), candidates=candidates, limit=pool_size)
    scores = [c.rerank_score for c in result]
    assert scores == sorted(scores, reverse=True)


def test_empty_candidates_yield_empty_output() -> None:
    """Empty candidate pool maps to empty output regardless of limit."""
    reranker = DeterministicReranker()
    for limit in (-1, 0, 1, 100):
        assert reranker.rerank(plan=_make_plan(), candidates=[], limit=limit) == ()


def test_negative_or_zero_limit_yields_empty_output() -> None:
    """limit < 1 must always yield empty output, even with non-empty pool."""
    reranker = DeterministicReranker()
    pool = [_make_candidate(i, 0.5, 0.4) for i in range(5)]
    for limit in (-100, -1, 0):
        assert reranker.rerank(plan=_make_plan(), candidates=pool, limit=limit) == ()
