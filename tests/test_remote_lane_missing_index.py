"""Tests for graceful handling of missing OpenSearch aliases and Qdrant collections.

When an alias/collection does not exist (HTTP 404), the lane adapters must skip
that index gracefully and return zero candidates instead of raising RuntimeError.
"""

from __future__ import annotations

from unittest.mock import patch

from adcs.retrieval.models import (
    FilterDebugMetadata,
    QueryPlan,
    QueryPlanDebugMetadata,
    ResolvedRetrievalFilters,
    RetrievalFilterRoute,
)
from adcs.retrieval.remote_lane_adapters import (
    OpenSearchLexicalLaneAdapter,
    QdrantDenseLaneAdapter,
)


def _make_plan() -> QueryPlan:
    route = RetrievalFilterRoute(
        product_id="aspose.ocr",
        programming_language="net",
        version=None,
        doc_locale="en",
    )
    debug_meta = FilterDebugMetadata(
        requested_product_id="aspose.ocr",
        requested_programming_language="net",
        requested_version=None,
        requested_doc_locale="en",
        effective_product_id="aspose.ocr",
        effective_programming_language="net",
        preferred_version=None,
        strict_version_value=None,
        strict_version_enforced=False,
        locale_routing_order=("en",),
        locale_fallback_to_en_enabled=True,
    )
    filters = ResolvedRetrievalFilters(
        product_id="aspose.ocr",
        programming_language="net",
        preferred_version=None,
        strict_version=False,
        strict_version_value=None,
        locale_routing_order=("en",),
        routes=(route,),
        debug=debug_meta,
    )
    plan_debug = QueryPlanDebugMetadata(
        raw_query="install ocr",
        normalized_query="install ocr",
        removed_noise_prefixes=(),
        symbol_candidates=(),
        intent="task",
        intent_subtype=None,
        intent_reason_codes=(),
        detected_version_tokens=(),
        prefers_latest_stable=True,
        filter_debug=debug_meta,
    )
    return QueryPlan(
        normalized_query="install ocr",
        query_fingerprint="fp-test",
        symbol_candidates=(),
        intent="task",
        intent_subtype=None,
        intent_reason_codes=(),
        detected_version_tokens=(),
        prefers_latest_stable=True,
        filters=filters,
        debug=plan_debug,
    )


def test_opensearch_adapter_skips_missing_alias_gracefully() -> None:
    """A 404 from OpenSearch (alias not yet created) must not raise."""
    adapter = OpenSearchLexicalLaneAdapter(
        opensearch_url="http://localhost:9200",
        index_aliases=("docs_lex_v1_active", "apiref_lex_v1_active"),
    )
    plan = _make_plan()

    with patch(
        "adcs.retrieval.remote_lane_adapters._request_json",
        return_value=(404, {"error": "index_not_found_exception"}),
    ):
        results = adapter.search(plan=plan, limit=10)

    assert results == ()


def test_opensearch_adapter_still_raises_on_non_404_errors() -> None:
    """Non-404 errors (e.g. 500) must still raise RuntimeError."""
    adapter = OpenSearchLexicalLaneAdapter(
        opensearch_url="http://localhost:9200",
        index_aliases=("docs_lex_v1_active",),
    )
    plan = _make_plan()

    with patch(
        "adcs.retrieval.remote_lane_adapters._request_json",
        return_value=(500, {"error": "internal_server_error"}),
    ):
        try:
            adapter.search(plan=plan, limit=10)
            raised = False
        except RuntimeError:
            raised = True

    assert raised, "Expected RuntimeError for HTTP 500"


def test_qdrant_adapter_skips_missing_collection_gracefully() -> None:
    """A 404 from Qdrant (collection not yet created) must not raise."""
    adapter = QdrantDenseLaneAdapter(
        qdrant_url="http://localhost:6333",
        collection_names=("docs_dense_v1", "apiref_dense_v1"),
    )
    plan = _make_plan()

    with patch(
        "adcs.retrieval.remote_lane_adapters._request_json",
        return_value=(404, {"status": {"error": "Not found"}}),
    ):
        results = adapter.search(plan=plan, limit=10)

    assert results == ()


def test_qdrant_adapter_still_raises_on_non_404_errors() -> None:
    """Non-404 errors (e.g. 500) must still raise RuntimeError."""
    adapter = QdrantDenseLaneAdapter(
        qdrant_url="http://localhost:6333",
        collection_names=("docs_dense_v1",),
    )
    plan = _make_plan()

    with patch(
        "adcs.retrieval.remote_lane_adapters._request_json",
        return_value=(500, {"status": {"error": "internal"}}),
    ):
        try:
            adapter.search(plan=plan, limit=10)
            raised = False
        except RuntimeError:
            raised = True

    assert raised, "Expected RuntimeError for HTTP 500"


def test_opensearch_adapter_returns_results_from_existing_alias_when_one_is_missing() -> None:
    """When one alias returns 404 and another returns hits, results are returned."""
    adapter = OpenSearchLexicalLaneAdapter(
        opensearch_url="http://localhost:9200",
        index_aliases=("docs_lex_v1_active", "apiref_lex_v1_active"),
    )
    plan = _make_plan()

    def mock_request_json(
        *, url: str, method: str, payload: object, timeout_seconds: float, backend_name: str
    ) -> tuple[int, object]:
        if "apiref_lex_v1_active" in url:
            return (404, {"error": "index_not_found_exception"})
        return (
            200,
            {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_score": 5.0,
                            "_source": {
                                "chunk_id": "chunk-found",
                                "text": "Found doc",
                                "snapshot_id": "snap-001",
                                "product_id": "aspose.ocr",
                                "programming_language": "net",
                                "version": "25.1",
                                "source_kind": "docs",
                                "doc_type": "guide_step",
                                "doc_locale": "en",
                                "symbol_fqn": None,
                                "title": "Found",
                                "canonical_url": "https://docs.aspose.com/ocr/net/",
                                "section_anchor": "#found",
                                "source_revision": "rev-1",
                                "repo_id": "aspose.ocr.docs",
                                "checksum": "abc",
                            },
                        }
                    ],
                }
            },
        )

    with patch(
        "adcs.retrieval.remote_lane_adapters._request_json",
        side_effect=mock_request_json,
    ):
        results = adapter.search(plan=plan, limit=10)

    assert len(results) == 1
    assert results[0].metadata.chunk_id == "chunk-found"
