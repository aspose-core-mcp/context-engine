"""Tests for locale expansion in Qdrant/OpenSearch lane adapter filter builders."""

from __future__ import annotations

from typing import Any, cast

from adcs.retrieval.models import RetrievalFilterRoute
from adcs.retrieval.remote_lane_adapters import (
    _LOCALE_INDEX_EXPANSIONS,
    _to_opensearch_filters,
    _to_qdrant_filter,
)


def _make_route(*, doc_locale: str) -> RetrievalFilterRoute:
    return RetrievalFilterRoute(
        product_id="aspose.ocr",
        programming_language="net",
        version=None,
        doc_locale=doc_locale,
    )


def _extract_qdrant_locale_clause(qdrant_filter: dict[str, object]) -> dict[str, Any]:
    """Extract the doc_locale clause from a Qdrant filter dict."""
    must = cast(list[dict[str, Any]], qdrant_filter["must"])
    locale_clauses = [c for c in must if c.get("key") == "doc_locale"]
    assert len(locale_clauses) == 1, f"Expected 1 locale clause, got {len(locale_clauses)}"
    return cast(dict[str, Any], locale_clauses[0]["match"])


def test_qdrant_filter_expands_en_locale_to_include_english_and_unknown() -> None:
    """Locale 'en' must match indexed values 'en', 'english', and 'unknown'."""
    route = _make_route(doc_locale="en")
    qdrant_filter = _to_qdrant_filter(route=route, strict_version=False)
    match_value = _extract_qdrant_locale_clause(qdrant_filter)

    assert "any" in match_value
    locale_list = match_value["any"]
    assert "en" in locale_list
    assert "english" in locale_list
    assert "unknown" in locale_list


def test_qdrant_filter_uses_exact_match_for_unmapped_locale() -> None:
    """Locales not in expansion map should use exact match."""
    route = _make_route(doc_locale="sv")
    qdrant_filter = _to_qdrant_filter(route=route, strict_version=False)
    match_value = _extract_qdrant_locale_clause(qdrant_filter)

    assert match_value == {"value": "sv"}


def test_opensearch_filter_expands_en_locale_to_terms_query() -> None:
    """Locale 'en' in OpenSearch must use 'terms' with expanded values."""
    route = _make_route(doc_locale="en")
    os_filters = _to_opensearch_filters(route=route, strict_version=False)

    terms_filters = [f for f in os_filters if "terms" in f]
    assert len(terms_filters) == 1

    terms_obj = cast(dict[str, Any], terms_filters[0]["terms"])
    locale_list = terms_obj["doc_locale"]
    assert "en" in locale_list
    assert "english" in locale_list
    assert "unknown" in locale_list


def test_opensearch_filter_uses_term_for_unmapped_locale() -> None:
    """Locales not in expansion map should use exact 'term' match."""
    route = _make_route(doc_locale="sv")
    os_filters = _to_opensearch_filters(route=route, strict_version=False)

    # No "terms" (multi-value) filter should be present for unmapped locale
    terms_filters = [f for f in os_filters if "terms" in f]
    assert len(terms_filters) == 0

    # The locale should appear as a single-value "term" filter
    locale_term_filters = [
        f for f in os_filters
        if "term" in f and "doc_locale" in cast(dict[str, Any], f["term"])
    ]
    assert len(locale_term_filters) == 1
    term_obj = cast(dict[str, Any], locale_term_filters[0]["term"])
    assert term_obj["doc_locale"] == "sv"


def test_locale_expansion_map_includes_en_with_unknown() -> None:
    """The 'en' expansion must include 'unknown' since most docs have unknown locale."""
    assert "en" in _LOCALE_INDEX_EXPANSIONS
    en_variants = _LOCALE_INDEX_EXPANSIONS["en"]
    assert "unknown" in en_variants
    assert "english" in en_variants
    assert "en" in en_variants


def test_qdrant_filter_expands_ru_locale() -> None:
    """Locale 'ru' should expand to include 'russian'."""
    route = _make_route(doc_locale="ru")
    qdrant_filter = _to_qdrant_filter(route=route, strict_version=False)
    match_value = _extract_qdrant_locale_clause(qdrant_filter)

    assert "any" in match_value
    assert "ru" in match_value["any"]
    assert "russian" in match_value["any"]
