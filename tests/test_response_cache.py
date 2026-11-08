"""Response-cache behaviour, focused on the ways a cache answers wrong.

A cache that is merely slow is a performance problem. A cache with a key that is
too narrow serves one caller's answer to another, which is a correctness and
isolation problem — so these tests are mostly about the key, not the hit rate.
"""

from __future__ import annotations

from adcs.retrieval.response_cache import ResponseCache, build_cache_key

_BASE = {
    "tenant_id": "default",
    "query": "How to use RecognizeImage?",
    "product_id": "aspose.ocr",
    "language": "net",
    "version": "25.1",
    "query_locale": "en",
    "top_k": 8,
    "strict_version": True,
    "doc_types": ("guide",),
    "include_examples": True,
    "debug": False,
}


def _key(**overrides: object) -> str:
    payload = {**_BASE, **overrides}
    return build_cache_key(**payload)  # type: ignore[arg-type]


def test_identical_requests_share_a_key() -> None:
    assert _key() == _key()
    # Whitespace and doc-type ordering are not semantic differences.
    assert _key(query="  How to use RecognizeImage?  ") == _key()
    assert _key(doc_types=("guide", "api_reference")) == _key(
        doc_types=("api_reference", "guide")
    )


def test_tenant_is_part_of_the_key() -> None:
    """The isolation failure that matters most: one tenant's corpus is not another's."""
    assert _key(tenant_id="acme") != _key(tenant_id="globex")
    assert _key(tenant_id="acme") != _key()


def test_privileged_debug_responses_are_not_shared_with_anonymous_callers() -> None:
    """The debug payload is privileged.

    A response computed for a caller holding an admin key must never be replayed
    to an anonymous one, so the flag has to be part of the key.
    """
    assert _key(debug=True) != _key(debug=False)


def test_every_response_shaping_field_changes_the_key() -> None:
    """A key narrower than the request makes the cache answer the wrong question."""
    for field, value in (
        ("query", "How do I convert to PDF?"),
        ("product_id", "aspose.words"),
        ("language", "java"),
        ("version", "24.12"),
        ("query_locale", "de"),
        ("top_k", 3),
        ("strict_version", False),
        ("doc_types", ("api_reference",)),
        ("include_examples", False),
    ):
        assert _key(**{field: value}) != _key(), f"{field} must participate in the cache key"


def test_entries_expire_and_are_evicted() -> None:
    cache: ResponseCache[str] = ResponseCache(ttl_seconds=0.05, max_entries=2)
    cache.put("a", "value-a")
    assert cache.get("a") == "value-a"

    import time

    time.sleep(0.06)
    assert cache.get("a") is None, "an expired entry must not be served"

    cache_bounded: ResponseCache[str] = ResponseCache(ttl_seconds=60, max_entries=2)
    cache_bounded.put("a", "1")
    cache_bounded.put("b", "2")
    cache_bounded.put("c", "3")
    assert cache_bounded.get("a") is None, "the oldest entry should be evicted at the bound"
    assert cache_bounded.get("c") == "3"


def test_invalidate_all_clears_everything() -> None:
    """Publishing a new snapshot changes what should be served."""
    cache: ResponseCache[str] = ResponseCache(ttl_seconds=60, max_entries=8)
    cache.put("a", "1")
    cache.put("b", "2")

    assert cache.invalidate_all() == 2
    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.stats()["entries"] == 0


def test_cached_hit_does_not_replay_request_identifiers() -> None:
    """`request_id` keys feedback and issue dedup, so it must be per-caller.

    Replaying it would make two callers collide on each other's feedback records
    — the retrieval result is shareable, the identity of the request is not.
    """
    from tests.test_release_tools_lane_fallback import _LANE_RECORDS, _EmptyStateStore

    from adcs.api.public_docs_query import PublicQueryService, QueryDocsRequest
    from adcs.retrieval import TranslationFallbackService
    from adcs.retrieval.in_memory_lane_adapters import (
        InMemoryDenseLaneAdapter,
        InMemoryLexicalLaneAdapter,
    )

    cache: ResponseCache[object] = ResponseCache(ttl_seconds=60, max_entries=8)
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=_EmptyStateStore(),  # type: ignore[arg-type]
        translation_fallback_service=TranslationFallbackService(),
        dense_lane_adapter=InMemoryDenseLaneAdapter(
            chunk_records=_LANE_RECORDS, snapshot_id="snap-1"
        ),
        lexical_lane_adapter=InMemoryLexicalLaneAdapter(
            chunk_records=_LANE_RECORDS, snapshot_id="snap-1"
        ),
        response_cache=cache,  # type: ignore[arg-type]
    )

    payload = QueryDocsRequest(
        query="What's new in the latest release?",
        product_id="aspose.ocr",
        language="net",
        query_locale="en",
        top_k=2,
    )
    first = service.query_docs(request=payload)
    second = service.query_docs(request=payload)

    assert cache.stats()["entries"] == 1, "the second call should have been a cache hit"
    assert first.request_id != second.request_id, "request_id must not be replayed from cache"
    assert first.query_id != second.query_id
    # The retrieval result itself is what gets shared.
    assert [item.chunk_id for item in first.results] == [
        item.chunk_id for item in second.results
    ]
