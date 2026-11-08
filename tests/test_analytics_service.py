from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from adcs.admin.analytics import AnalyticsQueryRecord, InMemoryAnalyticsService


def test_in_memory_analytics_records_quality_dimensions_and_slices() -> None:
    service = InMemoryAnalyticsService()
    service.record_query(
        request_id="req-1",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="extract table text",
        product_id="aspose.ocr",
        programming_language="net",
        doc_locale="en",
        hashed_ip="ip-hash",
        fingerprint="fp-1",
        latency_ms=12,
        confidence=0.0,
        outcome="no_results",
        retrieval_mode="task",
        result_count=0,
        zero_result_reason="no_index_data",
        fallback_reason="translation_dependency_unavailable",
        warning_codes=["no_index_data", "translation_dependency_unavailable"],
    )

    summary = service.slice_summary(tool="query_docs")
    assert summary.total_requests == 1
    assert summary.by_outcome["no_results"] == 1
    assert summary.by_retrieval_mode["task"] == 1
    assert summary.by_zero_result_reason["no_index_data"] == 1
    assert summary.by_fallback_reason["translation_dependency_unavailable"] == 1
    assert summary.by_warning_code["no_index_data"] == 1
    assert summary.by_warning_code["translation_dependency_unavailable"] == 1


def test_in_memory_analytics_supports_warning_code_filter() -> None:
    service = InMemoryAnalyticsService()
    service.record_query(
        request_id="req-1",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="query-1",
        product_id="aspose.ocr",
        programming_language="net",
        doc_locale="en",
        hashed_ip=None,
        fingerprint=None,
        latency_ms=30,
        confidence=0.9,
        outcome="success",
        retrieval_mode="symbol",
        result_count=3,
        warning_codes=[],
    )
    service.record_query(
        request_id="req-2",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="query-2",
        product_id="aspose.ocr",
        programming_language="net",
        doc_locale="en",
        hashed_ip=None,
        fingerprint=None,
        latency_ms=33,
        confidence=0.1,
        outcome="low_confidence",
        retrieval_mode="task",
        result_count=1,
        warning_codes=["low_confidence_best_effort"],
    )

    low_confidence_records = service.list_records(
        tool="query_docs",
        warning_code="low_confidence_best_effort",
    )
    assert len(low_confidence_records) == 1
    assert low_confidence_records[0].request_id == "req-2"


def test_in_memory_analytics_zero_result_overview_groups_clusters() -> None:
    service = InMemoryAnalyticsService()
    service.record_query(
        request_id="req-1",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="How to add OCR release feature",
        product_id="aspose.ocr",
        programming_language="net",
        doc_locale="en",
        hashed_ip=None,
        fingerprint="fp-1",
        latency_ms=18,
        confidence=0.0,
        outcome="no_results",
        retrieval_mode="release_notes",
        result_count=0,
        zero_result_reason="no_index_data",
        fallback_reason="no_candidates",
        warning_codes=["no_index_data"],
    )
    service.record_query(
        request_id="req-2",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="How to add OCR release feature",
        product_id="aspose.ocr",
        programming_language="java",
        doc_locale="en",
        hashed_ip=None,
        fingerprint="fp-2",
        latency_ms=21,
        confidence=0.22,
        outcome="low_confidence",
        retrieval_mode="release_notes",
        result_count=1,
        zero_result_reason=None,
        fallback_reason="low_confidence_best_effort",
        warning_codes=["low_confidence_best_effort"],
    )

    overview = service.zero_result_overview(tool="query_docs")
    assert overview.filtered_requests_total == 2
    assert overview.without_useful_result_requests == 2
    assert overview.no_result_requests == 1
    assert overview.low_confidence_requests == 1
    assert overview.by_zero_result_reason["no_index_data"] == 1
    assert overview.by_fallback_reason["low_confidence_best_effort"] == 1
    assert overview.top_affected_products["aspose.ocr"] == 2
    assert overview.clusters[0].recommendation_title in {
        "Publish or refresh coverage",
        "Inspect retrieval quality",
    }


def test_in_memory_analytics_capacity_forecast_surfaces_hot_products() -> None:
    service = InMemoryAnalyticsService()
    base = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    service._records = [
        AnalyticsQueryRecord(
            request_id="req-prev",
            endpoint="rest.docs.query",
            tool="query_docs",
            raw_query="old request",
            product_id="aspose.ocr",
            programming_language="net",
            doc_locale="en",
            hashed_ip=None,
            fingerprint="fp-prev",
            latency_ms=20,
            confidence=0.9,
            outcome="success",
            retrieval_mode="task",
            result_count=2,
            zero_result_reason=None,
            fallback_reason=None,
            warning_codes=(),
            created_at=base - timedelta(hours=30),
        ),
        AnalyticsQueryRecord(
            request_id="req-1",
            endpoint="rest.docs.query",
            tool="query_docs",
            raw_query="recent request 1",
            product_id="aspose.ocr",
            programming_language="net",
            doc_locale="en",
            hashed_ip=None,
            fingerprint="fp-1",
            latency_ms=30,
            confidence=0.0,
            outcome="no_results",
            retrieval_mode="task",
            result_count=0,
            zero_result_reason="no_index_data",
            fallback_reason="no_candidates",
            warning_codes=("no_index_data",),
            created_at=base - timedelta(hours=2),
        ),
        AnalyticsQueryRecord(
            request_id="req-2",
            endpoint="rest.docs.query",
            tool="query_docs",
            raw_query="recent request 2",
            product_id="aspose.ocr",
            programming_language="java",
            doc_locale="en",
            hashed_ip=None,
            fingerprint="fp-2",
            latency_ms=28,
            confidence=0.2,
            outcome="low_confidence",
            retrieval_mode="release_notes",
            result_count=1,
            zero_result_reason=None,
            fallback_reason="low_confidence_best_effort",
            warning_codes=("low_confidence_best_effort",),
            created_at=base - timedelta(hours=1),
        ),
        AnalyticsQueryRecord(
            request_id="req-3",
            endpoint="rest.docs.query",
            tool="query_docs",
            raw_query="recent request 3",
            product_id="groupdocs.parser",
            programming_language="net",
            doc_locale="en",
            hashed_ip=None,
            fingerprint="fp-3",
            latency_ms=14,
            confidence=0.95,
            outcome="success",
            retrieval_mode="symbol",
            result_count=3,
            zero_result_reason=None,
            fallback_reason=None,
            warning_codes=(),
            created_at=base - timedelta(minutes=30),
        ),
    ]

    forecast = service.capacity_forecast(tool="query_docs")
    assert forecast.filtered_requests_total == 4
    assert forecast.projected_requests_next_24h > 0
    assert forecast.saturation_risk in {"medium", "high"}
    assert forecast.hottest_products[0].product_id == "aspose.ocr"
    assert forecast.hottest_products[0].zero_result_pressure_share > 0
    assert forecast.hottest_products[0].recommended_action


def test_in_memory_analytics_feedback_deduplicates_by_request_and_actor() -> None:
    service = InMemoryAnalyticsService()
    service.record_query(
        request_id="req-1",
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query="latest OCR example",
        product_id="aspose.ocr",
        programming_language="net",
        doc_locale="en",
        hashed_ip="ip-1",
        fingerprint="fp-1",
        latency_ms=11,
        confidence=0.7,
        outcome="success",
        retrieval_mode="task",
        result_count=2,
        warning_codes=[],
    )

    first, updated_existing = service.record_usefulness_feedback(
        request_id="req-1",
        actor_identity="fingerprint:fp-1",
        rating="partially_useful",
        reason_codes=["incomplete_answer"],
    )
    second, updated_existing_second = service.record_usefulness_feedback(
        request_id="req-1",
        actor_identity="fingerprint:fp-1",
        rating="not_useful",
        reason_codes=["outdated_version", "no_examples"],
    )

    assert updated_existing is False
    assert updated_existing_second is True
    assert first.feedback_id == second.feedback_id

    summary = service.usefulness_summary(tool="query_docs")
    assert summary.total_feedback == 1
    assert summary.not_useful_feedback == 1
    assert summary.by_reason_code["outdated_version"] == 1
    assert summary.recent_negative_signals[0].rating == "not_useful"


def test_in_memory_analytics_feedback_requires_existing_request_id() -> None:
    service = InMemoryAnalyticsService()

    with pytest.raises(LookupError):
        service.record_usefulness_feedback(
            request_id="missing",
            actor_identity="fingerprint:fp-1",
            rating="useful",
            reason_codes=[],
        )


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT * FROM "admin_sessions"',
        'SELECT * FROM "pg_authid"',
        'SELECT * FROM "pg_shadow"',
        'SELECT * FROM "ADMIN_API_KEYS"',
        "SELECT * FROM pg_authid",
        "SELECT * FROM admin_api_keys",
    ],
)
def test_sql_explorer_blocks_sensitive_tables_however_they_are_spelled(sql: str) -> None:
    """Quoting an identifier must not walk the guard past the blocklist.

    A guard that matches raw substrings against a small set of prefixes (space,
    comma, dot, open paren) without the double quote lets the SQL-standard
    quoted spelling of every blocked table pass validation.
    """
    from adcs.admin.analytics import _validate_read_only_select

    with pytest.raises(ValueError, match="not allowed"):
        _validate_read_only_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM query_events",
        'SELECT "product_id", count(*) FROM query_events GROUP BY "product_id"',
    ],
)
def test_sql_explorer_still_accepts_legitimate_quoted_queries(sql: str) -> None:
    """Stripping quotes for the check must not reject ordinary quoted SQL."""
    from adcs.admin.analytics import _validate_read_only_select

    _validate_read_only_select(sql)
