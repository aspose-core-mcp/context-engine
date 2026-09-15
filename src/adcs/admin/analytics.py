"""In-memory analytics storage, slices, and read-only SQL explorer."""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

_RETENTION_DAYS = 365
_SQL_MAX_ROWS = 10_000
_SQL_MAX_EXPORT_BYTES = 100 * 1024 * 1024
_SQL_STATEMENT_TIMEOUT_MS = 30_000
_USEFULNESS_RATINGS = ("useful", "partially_useful", "not_useful")
_USEFULNESS_NEGATIVE_RATINGS = {"partially_useful", "not_useful"}
_USEFULNESS_REASON_CODES = {
    "low_relevance",
    "missing_steps",
    "outdated_version",
    "wrong_sdk_language",
    "poor_citations",
    "no_examples",
    "incomplete_answer",
    "incorrect_answer",
    "other",
}
_ISSUE_TYPES = {
    "missing_docs",
    "wrong_docs",
    "outdated_docs",
    "bad_example",
    "other",
}


@dataclass(frozen=True, slots=True)
class AnalyticsQueryRecord:
    request_id: str
    endpoint: str
    tool: str
    raw_query: str
    product_id: str | None
    programming_language: str | None
    doc_locale: str | None
    hashed_ip: str | None
    fingerprint: str | None
    latency_ms: int
    confidence: float
    outcome: str
    retrieval_mode: str | None
    result_count: int
    zero_result_reason: str | None
    fallback_reason: str | None
    warning_codes: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UsefulnessFeedbackRecord:
    feedback_id: str
    request_id: str
    actor_identity: str
    endpoint: str
    tool: str
    raw_query: str
    product_id: str | None
    programming_language: str | None
    doc_locale: str | None
    outcome: str
    retrieval_mode: str | None
    result_count: int
    zero_result_reason: str | None
    fallback_reason: str | None
    warning_codes: tuple[str, ...]
    rating: str
    reason_codes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IssueIntakeRecord:
    issue_id: str
    request_id: str
    actor_identity: str
    endpoint: str
    tool: str
    raw_query: str
    product_id: str | None
    programming_language: str | None
    doc_locale: str | None
    outcome: str
    retrieval_mode: str | None
    result_count: int
    zero_result_reason: str | None
    fallback_reason: str | None
    warning_codes: tuple[str, ...]
    issue_type: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UsefulnessSummary:
    total_feedback: int
    useful_feedback: int
    partially_useful_feedback: int
    not_useful_feedback: int
    useful_share: float
    negative_share: float
    by_rating: dict[str, int]
    by_reason_code: dict[str, int]
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_doc_locale: dict[str, int]
    recent_negative_signals: tuple[UsefulnessFeedbackRecord, ...]
    refreshed_at: datetime
    refresh_lag_minutes: int


@dataclass(frozen=True, slots=True)
class AnalyticsSliceSummary:
    total_requests: int
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_doc_locale: dict[str, int]
    by_endpoint: dict[str, int]
    by_tool: dict[str, int]
    by_outcome: dict[str, int]
    by_retrieval_mode: dict[str, int]
    by_zero_result_reason: dict[str, int]
    by_fallback_reason: dict[str, int]
    by_warning_code: dict[str, int]
    refreshed_at: datetime
    refresh_lag_minutes: int


@dataclass(frozen=True, slots=True)
class ZeroResultClusterSummary:
    cluster_id: str
    zero_result_reason: str
    fallback_reason: str
    retrieval_mode: str
    primary_warning_code: str
    total_requests: int
    share_of_filtered_requests: float
    affected_products: tuple[str, ...]
    affected_programming_languages: tuple[str, ...]
    affected_doc_locales: tuple[str, ...]
    sample_queries: tuple[str, ...]
    recommendation_title: str
    recommendation_detail: str


@dataclass(frozen=True, slots=True)
class ZeroResultOverview:
    filtered_requests_total: int
    without_useful_result_requests: int
    without_useful_result_share: float
    no_result_requests: int
    low_confidence_requests: int
    by_zero_result_reason: dict[str, int]
    by_fallback_reason: dict[str, int]
    by_warning_code: dict[str, int]
    by_retrieval_mode: dict[str, int]
    top_affected_products: dict[str, int]
    top_affected_programming_languages: dict[str, int]
    clusters: tuple[ZeroResultClusterSummary, ...]
    refreshed_at: datetime
    refresh_lag_minutes: int


@dataclass(frozen=True, slots=True)
class CapacityForecastProductSummary:
    product_id: str
    recent_requests: int
    previous_window_requests: int
    projected_requests_next_24h: int
    growth_ratio: float
    zero_result_pressure_share: float
    low_confidence_share: float
    warning_density: float
    coverage_saturation_score: float
    saturation_risk: str
    recommended_action: str


@dataclass(frozen=True, slots=True)
class CapacityForecastSummary:
    filtered_requests_total: int
    observed_window_hours: float
    projected_requests_next_24h: int
    previous_window_requests: int
    growth_ratio: float
    zero_result_pressure_share: float
    low_confidence_share: float
    warning_density: float
    coverage_saturation_score: float
    saturation_risk: str
    recommended_action: str
    hottest_products: tuple[CapacityForecastProductSummary, ...]
    refreshed_at: datetime
    refresh_lag_minutes: int


@dataclass(frozen=True, slots=True)
class SqlQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    truncated: bool


@runtime_checkable
class AnalyticsService(Protocol):
    """Contract for analytics query/event storage and SQL exploration."""

    def record_query(
        self,
        *,
        request_id: str,
        endpoint: str,
        tool: str,
        raw_query: str,
        product_id: str | None,
        programming_language: str | None,
        doc_locale: str | None,
        hashed_ip: str | None,
        fingerprint: str | None,
        latency_ms: int,
        confidence: float,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        result_count: int | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_codes: Sequence[str] | None = None,
    ) -> AnalyticsQueryRecord:
        """Persist one analytics query event."""

    def get_record(self, request_id: str) -> AnalyticsQueryRecord | None:
        """Return one analytics query event by request_id."""

    def record_usefulness_feedback(
        self,
        *,
        request_id: str,
        actor_identity: str,
        rating: str,
        reason_codes: Sequence[str] | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, bool]:
        """Persist or overwrite usefulness feedback for request_id + actor_identity."""

    def record_issue_report(
        self,
        *,
        request_id: str,
        actor_identity: str,
        issue_type: str,
        notes: str | None = None,
    ) -> tuple[IssueIntakeRecord, bool]:
        """Persist or overwrite one issue-intake report for request_id + actor_identity."""

    def list_usefulness_feedback(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        negative_only: bool = False,
        limit: int | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, ...]:
        """List usefulness feedback records with optional filters."""

    def list_issue_reports(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        issue_type: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[IssueIntakeRecord, ...]:
        """List issue-intake records with optional filters."""

    def usefulness_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> UsefulnessSummary:
        """Build usefulness summary and recent negative signals."""

    def list_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[AnalyticsQueryRecord, ...]:
        """List analytics query events with optional filters."""

    def slice_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> AnalyticsSliceSummary:
        """Build aggregate counters for analytics dashboard slices."""

    def zero_result_overview(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> ZeroResultOverview:
        """Build focused overview for requests without useful retrieval output."""

    def capacity_forecast(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> CapacityForecastSummary:
        """Build deterministic short-horizon capacity forecast for ops planning."""

    def sql_query(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> SqlQueryResult:
        """Execute read-only SQL query with guardrails."""

    def sql_export_csv(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> str:
        """Export read-only SQL query results as CSV."""


class InMemoryAnalyticsService:
    """Store analytics events and provide read-only query helpers."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: list[AnalyticsQueryRecord] = []
        self._feedback_records: dict[tuple[str, str], UsefulnessFeedbackRecord] = {}
        self._issue_records: dict[tuple[str, str], IssueIntakeRecord] = {}

    def record_query(
        self,
        *,
        request_id: str,
        endpoint: str,
        tool: str,
        raw_query: str,
        product_id: str | None,
        programming_language: str | None,
        doc_locale: str | None,
        hashed_ip: str | None,
        fingerprint: str | None,
        latency_ms: int,
        confidence: float,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        result_count: int | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_codes: Sequence[str] | None = None,
    ) -> AnalyticsQueryRecord:
        now = datetime.now(tz=UTC)
        normalized_warning_codes = _normalize_warning_codes(warning_codes)
        record = AnalyticsQueryRecord(
            request_id=request_id,
            endpoint=endpoint,
            tool=tool,
            raw_query=raw_query,
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            latency_ms=max(latency_ms, 0),
            confidence=max(0.0, min(confidence, 1.0)),
            outcome=_normalize_outcome(
                outcome=outcome,
                confidence=confidence,
                result_count=result_count,
            ),
            retrieval_mode=_nullable_str(retrieval_mode),
            result_count=max(result_count or 0, 0),
            zero_result_reason=_nullable_str(zero_result_reason),
            fallback_reason=_nullable_str(fallback_reason),
            warning_codes=normalized_warning_codes,
            created_at=now,
        )
        cutoff = now - timedelta(days=_RETENTION_DAYS)
        with self._lock:
            self._records.append(record)
            self._records = [item for item in self._records if item.created_at >= cutoff]
        return record

    def get_record(self, request_id: str) -> AnalyticsQueryRecord | None:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return None
        with self._lock:
            for record in reversed(self._records):
                if record.request_id == normalized_request_id:
                    return record
        return None

    def record_usefulness_feedback(
        self,
        *,
        request_id: str,
        actor_identity: str,
        rating: str,
        reason_codes: Sequence[str] | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, bool]:
        query_record = self.get_record(request_id)
        if query_record is None:
            msg = "Analytics request_id was not found."
            raise LookupError(msg)
        normalized_actor_identity = _normalize_actor_identity(actor_identity)
        normalized_rating = _normalize_usefulness_rating(rating)
        normalized_reason_codes = _normalize_usefulness_reason_codes(reason_codes)
        now = datetime.now(tz=UTC)
        key = (query_record.request_id, normalized_actor_identity)
        feedback_id = _feedback_id(
            request_id=query_record.request_id,
            actor_identity=normalized_actor_identity,
        )
        with self._lock:
            existing = self._feedback_records.get(key)
            created_at = existing.created_at if existing is not None else now
            record = UsefulnessFeedbackRecord(
                feedback_id=feedback_id,
                request_id=query_record.request_id,
                actor_identity=normalized_actor_identity,
                endpoint=query_record.endpoint,
                tool=query_record.tool,
                raw_query=query_record.raw_query,
                product_id=query_record.product_id,
                programming_language=query_record.programming_language,
                doc_locale=query_record.doc_locale,
                outcome=query_record.outcome,
                retrieval_mode=query_record.retrieval_mode,
                result_count=query_record.result_count,
                zero_result_reason=query_record.zero_result_reason,
                fallback_reason=query_record.fallback_reason,
                warning_codes=query_record.warning_codes,
                rating=normalized_rating,
                reason_codes=normalized_reason_codes,
                created_at=created_at,
                updated_at=now,
            )
            cutoff = now - timedelta(days=_RETENTION_DAYS)
            self._feedback_records[key] = record
            self._feedback_records = {
                item_key: item
                for item_key, item in self._feedback_records.items()
                if item.updated_at >= cutoff
            }
        return record, existing is not None

    def record_issue_report(
        self,
        *,
        request_id: str,
        actor_identity: str,
        issue_type: str,
        notes: str | None = None,
    ) -> tuple[IssueIntakeRecord, bool]:
        query_record = self.get_record(request_id)
        if query_record is None:
            msg = "Analytics request_id was not found."
            raise LookupError(msg)
        normalized_actor_identity = _normalize_actor_identity(actor_identity)
        normalized_issue_type = _normalize_issue_type(issue_type)
        normalized_notes = _normalize_issue_notes(notes)
        now = datetime.now(tz=UTC)
        key = (query_record.request_id, normalized_actor_identity)
        issue_id = _issue_id(
            request_id=query_record.request_id,
            actor_identity=normalized_actor_identity,
        )
        with self._lock:
            existing = self._issue_records.get(key)
            created_at = existing.created_at if existing is not None else now
            record = IssueIntakeRecord(
                issue_id=issue_id,
                request_id=query_record.request_id,
                actor_identity=normalized_actor_identity,
                endpoint=query_record.endpoint,
                tool=query_record.tool,
                raw_query=query_record.raw_query,
                product_id=query_record.product_id,
                programming_language=query_record.programming_language,
                doc_locale=query_record.doc_locale,
                outcome=query_record.outcome,
                retrieval_mode=query_record.retrieval_mode,
                result_count=query_record.result_count,
                zero_result_reason=query_record.zero_result_reason,
                fallback_reason=query_record.fallback_reason,
                warning_codes=query_record.warning_codes,
                issue_type=normalized_issue_type,
                notes=normalized_notes,
                created_at=created_at,
                updated_at=now,
            )
            cutoff = now - timedelta(days=_RETENTION_DAYS)
            self._issue_records[key] = record
            self._issue_records = {
                item_key: item
                for item_key, item in self._issue_records.items()
                if item.updated_at >= cutoff
            }
        return record, existing is not None

    def list_usefulness_feedback(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        negative_only: bool = False,
        limit: int | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, ...]:
        with self._lock:
            records = tuple(self._feedback_records.values())
        return _filter_usefulness_feedback_records(
            records,
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=rating,
            reason_code=reason_code,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
            negative_only=negative_only,
            limit=limit,
        )

    def list_issue_reports(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        issue_type: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[IssueIntakeRecord, ...]:
        with self._lock:
            records = tuple(self._issue_records.values())
        return _filter_issue_intake_records(
            records,
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            issue_type=issue_type,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )

    def usefulness_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> UsefulnessSummary:
        records = self.list_usefulness_feedback(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=rating,
            reason_code=reason_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_usefulness_summary(records)

    def list_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[AnalyticsQueryRecord, ...]:
        with self._lock:
            records = tuple(self._records)

        def _matches(value: str | None, expected: str | None) -> bool:
            if expected is None:
                return True
            return value == expected

        return tuple(
            record
            for record in records
            if _matches(record.product_id, product_id)
            and _matches(record.programming_language, programming_language)
            and _matches(record.doc_locale, doc_locale)
            and _matches(record.endpoint, endpoint)
            and _matches(record.tool, tool)
            and _matches(record.hashed_ip, hashed_ip)
            and _matches(record.fingerprint, fingerprint)
            and _matches(record.outcome, outcome)
            and _matches(record.retrieval_mode, retrieval_mode)
            and _matches(record.zero_result_reason, zero_result_reason)
            and _matches(record.fallback_reason, fallback_reason)
            and (
                warning_code is None
                or warning_code.strip().casefold()
                in {item.casefold() for item in record.warning_codes}
            )
            and (from_ts is None or record.created_at >= from_ts)
            and (to_ts is None or record.created_at <= to_ts)
        )

    def slice_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> AnalyticsSliceSummary:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )

        return AnalyticsSliceSummary(
            total_requests=len(records),
            by_product_id=dict(Counter(record.product_id or "unknown" for record in records)),
            by_programming_language=dict(
                Counter(record.programming_language or "unknown" for record in records)
            ),
            by_doc_locale=dict(Counter(record.doc_locale or "unknown" for record in records)),
            by_endpoint=dict(Counter(record.endpoint for record in records)),
            by_tool=dict(Counter(record.tool for record in records)),
            by_outcome=dict(Counter(record.outcome for record in records)),
            by_retrieval_mode=dict(
                Counter(record.retrieval_mode or "unknown" for record in records)
            ),
            by_zero_result_reason=dict(
                Counter(record.zero_result_reason or "none" for record in records)
            ),
            by_fallback_reason=dict(
                Counter(record.fallback_reason or "none" for record in records)
            ),
            by_warning_code=dict(
                Counter(
                    warning_code
                    for record in records
                    for warning_code in (
                        record.warning_codes if record.warning_codes else ("none",)
                    )
                )
            ),
            refreshed_at=datetime.now(tz=UTC),
            refresh_lag_minutes=5,
        )

    def zero_result_overview(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> ZeroResultOverview:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_zero_result_overview(records)

    def capacity_forecast(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> CapacityForecastSummary:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_capacity_forecast(records)

    def sql_query(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> SqlQueryResult:
        normalized_sql = _validate_read_only_select(sql)
        clamped_max_rows = max(1, min(max_rows, _SQL_MAX_ROWS))
        with self._lock:
            records = tuple(self._records)

        try:
            with sqlite3.connect(":memory:") as conn:
                conn.execute(
                    """
                    create table analytics_queries (
                        request_id text,
                        endpoint text,
                        tool text,
                        raw_query text,
                        product_id text,
                        programming_language text,
                        doc_locale text,
                        hashed_ip text,
                        fingerprint text,
                        latency_ms integer,
                        confidence real,
                        outcome text,
                        retrieval_mode text,
                        result_count integer,
                        zero_result_reason text,
                        fallback_reason text,
                        warning_codes text,
                        created_at text
                    )
                    """
                )
                conn.executemany(
                    """
                    insert into analytics_queries (
                        request_id, endpoint, tool, raw_query, product_id,
                        programming_language, doc_locale, hashed_ip, fingerprint,
                        latency_ms, confidence, outcome, retrieval_mode, result_count,
                        zero_result_reason, fallback_reason, warning_codes, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.request_id,
                            item.endpoint,
                            item.tool,
                            item.raw_query,
                            item.product_id,
                            item.programming_language,
                            item.doc_locale,
                            item.hashed_ip,
                            item.fingerprint,
                            item.latency_ms,
                            item.confidence,
                            item.outcome,
                            item.retrieval_mode,
                            item.result_count,
                            item.zero_result_reason,
                            item.fallback_reason,
                            ",".join(item.warning_codes),
                            item.created_at.isoformat(),
                        )
                        for item in records
                    ],
                )
                conn.execute(
                    """
                    create table analytics_usefulness_feedback (
                        feedback_id text,
                        request_id text,
                        actor_identity text,
                        endpoint text,
                        tool text,
                        raw_query text,
                        product_id text,
                        programming_language text,
                        doc_locale text,
                        outcome text,
                        retrieval_mode text,
                        result_count integer,
                        zero_result_reason text,
                        fallback_reason text,
                        warning_codes text,
                        rating text,
                        reason_codes text,
                        created_at text,
                        updated_at text
                    )
                    """
                )
                conn.executemany(
                    """
                    insert into analytics_usefulness_feedback (
                        feedback_id, request_id, actor_identity, endpoint, tool, raw_query,
                        product_id, programming_language, doc_locale, outcome, retrieval_mode,
                        result_count, zero_result_reason, fallback_reason, warning_codes, rating,
                        reason_codes, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.feedback_id,
                            item.request_id,
                            item.actor_identity,
                            item.endpoint,
                            item.tool,
                            item.raw_query,
                            item.product_id,
                            item.programming_language,
                            item.doc_locale,
                            item.outcome,
                            item.retrieval_mode,
                            item.result_count,
                            item.zero_result_reason,
                            item.fallback_reason,
                            ",".join(item.warning_codes),
                            item.rating,
                            ",".join(item.reason_codes),
                            item.created_at.isoformat(),
                            item.updated_at.isoformat(),
                        )
                        for item in self._feedback_records.values()
                    ],
                )
                conn.execute(
                    """
                    create table analytics_issue_reports (
                        issue_id text,
                        request_id text,
                        actor_identity text,
                        endpoint text,
                        tool text,
                        raw_query text,
                        product_id text,
                        programming_language text,
                        doc_locale text,
                        outcome text,
                        retrieval_mode text,
                        result_count integer,
                        zero_result_reason text,
                        fallback_reason text,
                        warning_codes text,
                        issue_type text,
                        notes text,
                        created_at text,
                        updated_at text
                    )
                    """
                )
                conn.executemany(
                    """
                    insert into analytics_issue_reports (
                        issue_id, request_id, actor_identity, endpoint, tool, raw_query,
                        product_id, programming_language, doc_locale, outcome, retrieval_mode,
                        result_count, zero_result_reason, fallback_reason, warning_codes,
                        issue_type, notes, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.issue_id,
                            item.request_id,
                            item.actor_identity,
                            item.endpoint,
                            item.tool,
                            item.raw_query,
                            item.product_id,
                            item.programming_language,
                            item.doc_locale,
                            item.outcome,
                            item.retrieval_mode,
                            item.result_count,
                            item.zero_result_reason,
                            item.fallback_reason,
                            ",".join(item.warning_codes),
                            item.issue_type,
                            item.notes,
                            item.created_at.isoformat(),
                            item.updated_at.isoformat(),
                        )
                        for item in self._issue_records.values()
                    ],
                )

                cursor = conn.execute(normalized_sql)
                all_rows = cursor.fetchall()
                columns = tuple(column[0] for column in (cursor.description or []))
        except sqlite3.Error as exc:
            msg = "SQL execution failed."
            raise ValueError(msg) from exc

        truncated = len(all_rows) > clamped_max_rows
        rows = tuple(tuple(row) for row in all_rows[:clamped_max_rows])
        return SqlQueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    def sql_export_csv(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> str:
        result = self.sql_query(sql=sql, max_rows=max_rows)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(result.columns)
        for row in result.rows:
            writer.writerow(row)

        csv_payload = output.getvalue()
        encoded_size = len(csv_payload.encode("utf-8"))
        if encoded_size > _SQL_MAX_EXPORT_BYTES:
            msg = "CSV export exceeds max export size (100 MB)."
            raise ValueError(msg)
        return csv_payload


class PostgresAnalyticsService:
    """PostgreSQL-backed analytics storage with read-only SQL explorer."""

    def __init__(
        self,
        *,
        postgres_dsn: str,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self._engine: Engine = create_engine(
            postgres_dsn,
            pool_pre_ping=True,
            connect_args={"connect_timeout": int(connect_timeout_seconds)},
        )
        self._ensure_schema()

    def ping(self) -> None:
        """Validate that PostgreSQL connection is available."""
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def get_record(self, request_id: str) -> AnalyticsQueryRecord | None:
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return None
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        request_id,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        hashed_ip,
                        fingerprint,
                        latency_ms,
                        confidence,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        created_at
                    FROM query_events
                    WHERE request_id = :request_id
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT 1
                    """
                ),
                {"request_id": normalized_request_id},
            ).mappings().first()
        if row is None:
            return None
        return _map_query_event_row(row)

    def record_query(
        self,
        *,
        request_id: str,
        endpoint: str,
        tool: str,
        raw_query: str,
        product_id: str | None,
        programming_language: str | None,
        doc_locale: str | None,
        hashed_ip: str | None,
        fingerprint: str | None,
        latency_ms: int,
        confidence: float,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        result_count: int | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_codes: Sequence[str] | None = None,
    ) -> AnalyticsQueryRecord:
        clamped_confidence = max(0.0, min(confidence, 1.0))
        normalized_warning_codes = _normalize_warning_codes(warning_codes)
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    INSERT INTO query_events (
                        request_id,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        hashed_ip,
                        fingerprint,
                        latency_ms,
                        confidence,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        created_at
                    )
                    VALUES (
                        :request_id,
                        :endpoint,
                        :tool,
                        :raw_query,
                        :product_id,
                        :programming_language,
                        :doc_locale,
                        :hashed_ip,
                        :fingerprint,
                        :latency_ms,
                        :confidence,
                        :outcome,
                        :retrieval_mode,
                        :result_count,
                        :zero_result_reason,
                        :fallback_reason,
                        :warning_codes,
                        NOW()
                    )
                    RETURNING
                        request_id,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        hashed_ip,
                        fingerprint,
                        latency_ms,
                        confidence,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        created_at
                    """
                ),
                {
                    "request_id": request_id,
                    "endpoint": endpoint,
                    "tool": tool,
                    "raw_query": raw_query,
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "doc_locale": doc_locale,
                    "hashed_ip": hashed_ip,
                    "fingerprint": fingerprint,
                    "latency_ms": max(latency_ms, 0),
                    "confidence": clamped_confidence,
                    "outcome": _normalize_outcome(
                        outcome=outcome,
                        confidence=confidence,
                        result_count=result_count,
                    ),
                    "retrieval_mode": _nullable_str(retrieval_mode),
                    "result_count": max(result_count or 0, 0),
                    "zero_result_reason": _nullable_str(zero_result_reason),
                    "fallback_reason": _nullable_str(fallback_reason),
                    "warning_codes": ",".join(normalized_warning_codes),
                },
            ).mappings().one()
            cutoff = datetime.now(tz=UTC) - timedelta(days=_RETENTION_DAYS)
            connection.execute(
                text("DELETE FROM query_events WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
        return _map_query_event_row(row)

    def record_usefulness_feedback(
        self,
        *,
        request_id: str,
        actor_identity: str,
        rating: str,
        reason_codes: Sequence[str] | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, bool]:
        query_record = self.get_record(request_id)
        if query_record is None:
            msg = "Analytics request_id was not found."
            raise LookupError(msg)
        normalized_actor_identity = _normalize_actor_identity(actor_identity)
        normalized_rating = _normalize_usefulness_rating(rating)
        normalized_reason_codes = _normalize_usefulness_reason_codes(reason_codes)
        feedback_id = _feedback_id(
            request_id=query_record.request_id,
            actor_identity=normalized_actor_identity,
        )
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT feedback_id
                    FROM usefulness_feedback
                    WHERE request_id = :request_id
                      AND actor_identity = :actor_identity
                    """
                ),
                {
                    "request_id": query_record.request_id,
                    "actor_identity": normalized_actor_identity,
                },
            ).first()
            row = connection.execute(
                text(
                    """
                    INSERT INTO usefulness_feedback (
                        feedback_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        rating,
                        reason_codes,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :feedback_id,
                        :request_id,
                        :actor_identity,
                        :endpoint,
                        :tool,
                        :raw_query,
                        :product_id,
                        :programming_language,
                        :doc_locale,
                        :outcome,
                        :retrieval_mode,
                        :result_count,
                        :zero_result_reason,
                        :fallback_reason,
                        :warning_codes,
                        :rating,
                        :reason_codes,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (request_id, actor_identity)
                    DO UPDATE SET
                        endpoint = EXCLUDED.endpoint,
                        tool = EXCLUDED.tool,
                        raw_query = EXCLUDED.raw_query,
                        product_id = EXCLUDED.product_id,
                        programming_language = EXCLUDED.programming_language,
                        doc_locale = EXCLUDED.doc_locale,
                        outcome = EXCLUDED.outcome,
                        retrieval_mode = EXCLUDED.retrieval_mode,
                        result_count = EXCLUDED.result_count,
                        zero_result_reason = EXCLUDED.zero_result_reason,
                        fallback_reason = EXCLUDED.fallback_reason,
                        warning_codes = EXCLUDED.warning_codes,
                        rating = EXCLUDED.rating,
                        reason_codes = EXCLUDED.reason_codes,
                        updated_at = NOW()
                    RETURNING
                        feedback_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        rating,
                        reason_codes,
                        created_at,
                        updated_at
                    """
                ),
                {
                    "feedback_id": feedback_id,
                    "request_id": query_record.request_id,
                    "actor_identity": normalized_actor_identity,
                    "endpoint": query_record.endpoint,
                    "tool": query_record.tool,
                    "raw_query": query_record.raw_query,
                    "product_id": query_record.product_id,
                    "programming_language": query_record.programming_language,
                    "doc_locale": query_record.doc_locale,
                    "outcome": query_record.outcome,
                    "retrieval_mode": query_record.retrieval_mode,
                    "result_count": query_record.result_count,
                    "zero_result_reason": query_record.zero_result_reason,
                    "fallback_reason": query_record.fallback_reason,
                    "warning_codes": ",".join(query_record.warning_codes),
                    "rating": normalized_rating,
                    "reason_codes": ",".join(normalized_reason_codes),
                },
            ).mappings().one()
            cutoff = datetime.now(tz=UTC) - timedelta(days=_RETENTION_DAYS)
            connection.execute(
                text("DELETE FROM usefulness_feedback WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            )
        return _map_usefulness_feedback_row(row), existing is not None

    def record_issue_report(
        self,
        *,
        request_id: str,
        actor_identity: str,
        issue_type: str,
        notes: str | None = None,
    ) -> tuple[IssueIntakeRecord, bool]:
        query_record = self.get_record(request_id)
        if query_record is None:
            msg = "Analytics request_id was not found."
            raise LookupError(msg)
        normalized_actor_identity = _normalize_actor_identity(actor_identity)
        normalized_issue_type = _normalize_issue_type(issue_type)
        normalized_notes = _normalize_issue_notes(notes)
        issue_id = _issue_id(
            request_id=query_record.request_id,
            actor_identity=normalized_actor_identity,
        )
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    """
                    SELECT issue_id
                    FROM issue_intake_reports
                    WHERE request_id = :request_id
                      AND actor_identity = :actor_identity
                    """
                ),
                {
                    "request_id": query_record.request_id,
                    "actor_identity": normalized_actor_identity,
                },
            ).first()
            row = connection.execute(
                text(
                    """
                    INSERT INTO issue_intake_reports (
                        issue_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        issue_type,
                        notes,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :issue_id,
                        :request_id,
                        :actor_identity,
                        :endpoint,
                        :tool,
                        :raw_query,
                        :product_id,
                        :programming_language,
                        :doc_locale,
                        :outcome,
                        :retrieval_mode,
                        :result_count,
                        :zero_result_reason,
                        :fallback_reason,
                        :warning_codes,
                        :issue_type,
                        :notes,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (request_id, actor_identity)
                    DO UPDATE SET
                        endpoint = EXCLUDED.endpoint,
                        tool = EXCLUDED.tool,
                        raw_query = EXCLUDED.raw_query,
                        product_id = EXCLUDED.product_id,
                        programming_language = EXCLUDED.programming_language,
                        doc_locale = EXCLUDED.doc_locale,
                        outcome = EXCLUDED.outcome,
                        retrieval_mode = EXCLUDED.retrieval_mode,
                        result_count = EXCLUDED.result_count,
                        zero_result_reason = EXCLUDED.zero_result_reason,
                        fallback_reason = EXCLUDED.fallback_reason,
                        warning_codes = EXCLUDED.warning_codes,
                        issue_type = EXCLUDED.issue_type,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    RETURNING
                        issue_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        issue_type,
                        notes,
                        created_at,
                        updated_at
                    """
                ),
                {
                    "issue_id": issue_id,
                    "request_id": query_record.request_id,
                    "actor_identity": normalized_actor_identity,
                    "endpoint": query_record.endpoint,
                    "tool": query_record.tool,
                    "raw_query": query_record.raw_query,
                    "product_id": query_record.product_id,
                    "programming_language": query_record.programming_language,
                    "doc_locale": query_record.doc_locale,
                    "outcome": query_record.outcome,
                    "retrieval_mode": query_record.retrieval_mode,
                    "result_count": query_record.result_count,
                    "zero_result_reason": query_record.zero_result_reason,
                    "fallback_reason": query_record.fallback_reason,
                    "warning_codes": ",".join(query_record.warning_codes),
                    "issue_type": normalized_issue_type,
                    "notes": normalized_notes,
                },
            ).mappings().one()
            cutoff = datetime.now(tz=UTC) - timedelta(days=_RETENTION_DAYS)
            connection.execute(
                text("DELETE FROM issue_intake_reports WHERE updated_at < :cutoff"),
                {"cutoff": cutoff},
            )
        return _map_issue_intake_row(row), existing is not None

    def list_usefulness_feedback(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        negative_only: bool = False,
        limit: int | None = None,
    ) -> tuple[UsefulnessFeedbackRecord, ...]:
        normalized_rating = (
            _normalize_usefulness_rating(rating) if rating is not None else None
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        feedback_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        rating,
                        reason_codes,
                        created_at,
                        updated_at
                    FROM usefulness_feedback
                    WHERE
                        (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                        AND (
                            CAST(:programming_language AS TEXT) IS NULL
                            OR programming_language = :programming_language
                        )
                        AND (CAST(:doc_locale AS TEXT) IS NULL OR doc_locale = :doc_locale)
                        AND (CAST(:endpoint AS TEXT) IS NULL OR endpoint = :endpoint)
                        AND (CAST(:tool AS TEXT) IS NULL OR tool = :tool)
                        AND (CAST(:rating AS TEXT) IS NULL OR rating = :rating)
                        AND (CAST(:request_id AS TEXT) IS NULL OR request_id = :request_id)
                        AND (
                            CAST(:from_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR updated_at >= :from_ts
                        )
                        AND (
                            CAST(:to_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR updated_at <= :to_ts
                        )
                    ORDER BY updated_at DESC, feedback_id DESC
                    """
                ),
                {
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "doc_locale": doc_locale,
                    "endpoint": endpoint,
                    "tool": tool,
                    "rating": normalized_rating,
                    "request_id": request_id,
                    "from_ts": from_ts,
                    "to_ts": to_ts,
                },
            ).mappings().all()
        records = tuple(_map_usefulness_feedback_row(row) for row in rows)
        return _filter_usefulness_feedback_records(
            records,
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=normalized_rating,
            reason_code=reason_code,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
            negative_only=negative_only,
            limit=limit,
        )

    def list_issue_reports(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        issue_type: str | None = None,
        request_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[IssueIntakeRecord, ...]:
        normalized_issue_type = (
            _normalize_issue_type(issue_type) if issue_type is not None else None
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        issue_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        issue_type,
                        notes,
                        created_at,
                        updated_at
                    FROM issue_intake_reports
                    WHERE
                        (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                        AND (
                            CAST(:programming_language AS TEXT) IS NULL
                            OR programming_language = :programming_language
                        )
                        AND (CAST(:doc_locale AS TEXT) IS NULL OR doc_locale = :doc_locale)
                        AND (CAST(:endpoint AS TEXT) IS NULL OR endpoint = :endpoint)
                        AND (CAST(:tool AS TEXT) IS NULL OR tool = :tool)
                        AND (CAST(:issue_type AS TEXT) IS NULL OR issue_type = :issue_type)
                        AND (CAST(:request_id AS TEXT) IS NULL OR request_id = :request_id)
                        AND (
                            CAST(:from_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR updated_at >= :from_ts
                        )
                        AND (
                            CAST(:to_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR updated_at <= :to_ts
                        )
                    ORDER BY updated_at DESC, issue_id DESC
                    """
                ),
                {
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "doc_locale": doc_locale,
                    "endpoint": endpoint,
                    "tool": tool,
                    "issue_type": normalized_issue_type,
                    "request_id": request_id,
                    "from_ts": from_ts,
                    "to_ts": to_ts,
                },
            ).mappings().all()
        records = tuple(_map_issue_intake_row(row) for row in rows)
        return _filter_issue_intake_records(
            records,
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            issue_type=normalized_issue_type,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )

    def usefulness_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        rating: str | None = None,
        reason_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> UsefulnessSummary:
        records = self.list_usefulness_feedback(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=rating,
            reason_code=reason_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_usefulness_summary(records)

    def list_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[AnalyticsQueryRecord, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        request_id,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        hashed_ip,
                        fingerprint,
                        latency_ms,
                        confidence,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        created_at
                    FROM query_events
                    WHERE
                        (CAST(:product_id AS TEXT) IS NULL OR product_id = :product_id)
                        AND (
                            CAST(:programming_language AS TEXT) IS NULL
                            OR programming_language = :programming_language
                        )
                        AND (CAST(:doc_locale AS TEXT) IS NULL OR doc_locale = :doc_locale)
                        AND (CAST(:endpoint AS TEXT) IS NULL OR endpoint = :endpoint)
                        AND (CAST(:tool AS TEXT) IS NULL OR tool = :tool)
                        AND (CAST(:hashed_ip AS TEXT) IS NULL OR hashed_ip = :hashed_ip)
                        AND (CAST(:fingerprint AS TEXT) IS NULL OR fingerprint = :fingerprint)
                        AND (CAST(:outcome AS TEXT) IS NULL OR outcome = :outcome)
                        AND (
                            CAST(:retrieval_mode AS TEXT) IS NULL
                            OR retrieval_mode = :retrieval_mode
                        )
                        AND (
                            CAST(:zero_result_reason AS TEXT) IS NULL
                            OR zero_result_reason = :zero_result_reason
                        )
                        AND (
                            CAST(:fallback_reason AS TEXT) IS NULL
                            OR fallback_reason = :fallback_reason
                        )
                        AND (
                            CAST(:from_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR created_at >= :from_ts
                        )
                        AND (
                            CAST(:to_ts AS TIMESTAMP WITH TIME ZONE) IS NULL
                            OR created_at <= :to_ts
                        )
                    ORDER BY created_at ASC, request_id ASC
                    """
                ),
                {
                    "product_id": product_id,
                    "programming_language": programming_language,
                    "doc_locale": doc_locale,
                    "endpoint": endpoint,
                    "tool": tool,
                    "hashed_ip": hashed_ip,
                    "fingerprint": fingerprint,
                    "outcome": outcome,
                    "retrieval_mode": retrieval_mode,
                    "zero_result_reason": zero_result_reason,
                    "fallback_reason": fallback_reason,
                    "from_ts": from_ts,
                    "to_ts": to_ts,
                },
            ).mappings().all()
        records = tuple(_map_query_event_row(row) for row in rows)
        if warning_code is None:
            return records
        normalized_warning_code = warning_code.strip().casefold()
        return tuple(
            record
            for record in records
            if normalized_warning_code in {item.casefold() for item in record.warning_codes}
        )

    def slice_summary(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> AnalyticsSliceSummary:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return AnalyticsSliceSummary(
            total_requests=len(records),
            by_product_id=dict(Counter(record.product_id or "unknown" for record in records)),
            by_programming_language=dict(
                Counter(record.programming_language or "unknown" for record in records)
            ),
            by_doc_locale=dict(Counter(record.doc_locale or "unknown" for record in records)),
            by_endpoint=dict(Counter(record.endpoint for record in records)),
            by_tool=dict(Counter(record.tool for record in records)),
            by_outcome=dict(Counter(record.outcome for record in records)),
            by_retrieval_mode=dict(
                Counter(record.retrieval_mode or "unknown" for record in records)
            ),
            by_zero_result_reason=dict(
                Counter(record.zero_result_reason or "none" for record in records)
            ),
            by_fallback_reason=dict(
                Counter(record.fallback_reason or "none" for record in records)
            ),
            by_warning_code=dict(
                Counter(
                    warning_code
                    for record in records
                    for warning_code in (
                        record.warning_codes if record.warning_codes else ("none",)
                    )
                )
            ),
            refreshed_at=datetime.now(tz=UTC),
            refresh_lag_minutes=5,
        )

    def zero_result_overview(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> ZeroResultOverview:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_zero_result_overview(records)

    def capacity_forecast(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        doc_locale: str | None = None,
        endpoint: str | None = None,
        tool: str | None = None,
        hashed_ip: str | None = None,
        fingerprint: str | None = None,
        outcome: str | None = None,
        retrieval_mode: str | None = None,
        zero_result_reason: str | None = None,
        fallback_reason: str | None = None,
        warning_code: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> CapacityForecastSummary:
        records = self.list_records(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            hashed_ip=hashed_ip,
            fingerprint=fingerprint,
            outcome=outcome,
            retrieval_mode=retrieval_mode,
            zero_result_reason=zero_result_reason,
            fallback_reason=fallback_reason,
            warning_code=warning_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        return _build_capacity_forecast(records)

    def sql_query(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> SqlQueryResult:
        normalized_sql = _validate_read_only_select(sql)
        clamped_max_rows = max(1, min(max_rows, _SQL_MAX_ROWS))
        # Use integer interpolation for LIMIT to avoid psycopg3 parameter
        # binding issues inside subquery wrappers.
        safe_limit = int(clamped_max_rows + 1)
        wrapped_sql = (
            f"SELECT * FROM ({normalized_sql.rstrip(';')}) AS adcs_sql_query "
            f"LIMIT {safe_limit}"
        )
        try:
            with self._engine.connect() as connection:
                with connection.begin():
                    connection.execute(
                        text(
                            f"SET LOCAL statement_timeout = '{int(_SQL_STATEMENT_TIMEOUT_MS)}'"
                        ),
                    )
                    connection.execute(text("SET LOCAL default_transaction_read_only = on"))
                    result = connection.execute(text(wrapped_sql))
                    fetched_rows = result.fetchall()
                    columns = tuple(str(column_name) for column_name in result.keys())
        except SQLAlchemyError as exc:
            detail = str(exc).split("\n")[0] if str(exc) else "Unknown error"
            msg = f"SQL execution failed: {detail}"
            raise ValueError(msg) from exc

        truncated = len(fetched_rows) > clamped_max_rows
        rows = tuple(tuple(row) for row in fetched_rows[:clamped_max_rows])
        return SqlQueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    def sql_export_csv(self, *, sql: str, max_rows: int = _SQL_MAX_ROWS) -> str:
        result = self.sql_query(sql=sql, max_rows=max_rows)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(result.columns)
        for row in result.rows:
            writer.writerow(row)

        csv_payload = output.getvalue()
        encoded_size = len(csv_payload.encode("utf-8"))
        if encoded_size > _SQL_MAX_EXPORT_BYTES:
            msg = "CSV export exceeds max export size (100 MB)."
            raise ValueError(msg)
        return csv_payload

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS query_events (
                        event_id BIGSERIAL PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        raw_query TEXT NOT NULL,
                        product_id TEXT NULL,
                        programming_language TEXT NULL,
                        doc_locale TEXT NULL,
                        hashed_ip TEXT NULL,
                        fingerprint TEXT NULL,
                        latency_ms INTEGER NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        outcome TEXT NOT NULL DEFAULT 'unspecified',
                        retrieval_mode TEXT NULL,
                        result_count INTEGER NOT NULL DEFAULT 0,
                        zero_result_reason TEXT NULL,
                        fallback_reason TEXT NULL,
                        warning_codes TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS outcome TEXT NOT NULL DEFAULT 'unspecified'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS retrieval_mode TEXT NULL"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS result_count INTEGER NOT NULL DEFAULT 0"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS zero_result_reason TEXT NULL"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS fallback_reason TEXT NULL"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE query_events "
                    "ADD COLUMN IF NOT EXISTS warning_codes TEXT NULL"
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_query_events_created_at
                    ON query_events (created_at DESC)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_query_events_product_scope
                    ON query_events (product_id, programming_language, doc_locale)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_query_events_endpoint_tool
                    ON query_events (endpoint, tool)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS usefulness_feedback (
                        feedback_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        actor_identity TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        raw_query TEXT NOT NULL,
                        product_id TEXT NULL,
                        programming_language TEXT NULL,
                        doc_locale TEXT NULL,
                        outcome TEXT NOT NULL DEFAULT 'unspecified',
                        retrieval_mode TEXT NULL,
                        result_count INTEGER NOT NULL DEFAULT 0,
                        zero_result_reason TEXT NULL,
                        fallback_reason TEXT NULL,
                        warning_codes TEXT NULL,
                        rating TEXT NOT NULL,
                        reason_codes TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (request_id, actor_identity)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usefulness_feedback_updated_at
                    ON usefulness_feedback (updated_at DESC)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usefulness_feedback_scope
                    ON usefulness_feedback (product_id, programming_language, doc_locale)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS issue_intake_reports (
                        issue_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        actor_identity TEXT NOT NULL,
                        endpoint TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        raw_query TEXT NOT NULL,
                        product_id TEXT NULL,
                        programming_language TEXT NULL,
                        doc_locale TEXT NULL,
                        outcome TEXT NOT NULL DEFAULT 'unspecified',
                        retrieval_mode TEXT NULL,
                        result_count INTEGER NOT NULL DEFAULT 0,
                        zero_result_reason TEXT NULL,
                        fallback_reason TEXT NULL,
                        warning_codes TEXT NULL,
                        issue_type TEXT NOT NULL,
                        notes TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (request_id, actor_identity)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_issue_intake_reports_updated_at
                    ON issue_intake_reports (updated_at DESC)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_issue_intake_reports_scope
                    ON issue_intake_reports (product_id, programming_language, doc_locale)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW analytics_queries AS
                    SELECT
                        request_id,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        hashed_ip,
                        fingerprint,
                        latency_ms,
                        confidence,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        created_at
                    FROM query_events
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW analytics_usefulness_feedback AS
                    SELECT
                        feedback_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        rating,
                        reason_codes,
                        created_at,
                        updated_at
                    FROM usefulness_feedback
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE VIEW analytics_issue_reports AS
                    SELECT
                        issue_id,
                        request_id,
                        actor_identity,
                        endpoint,
                        tool,
                        raw_query,
                        product_id,
                        programming_language,
                        doc_locale,
                        outcome,
                        retrieval_mode,
                        result_count,
                        zero_result_reason,
                        fallback_reason,
                        warning_codes,
                        issue_type,
                        notes,
                        created_at,
                        updated_at
                    FROM issue_intake_reports
                    """
                )
            )


def _build_zero_result_overview(
    records: Sequence[AnalyticsQueryRecord],
) -> ZeroResultOverview:
    relevant_records = tuple(record for record in records if _is_zero_result_record(record))
    filtered_total = len(records)
    relevant_total = len(relevant_records)
    no_result_requests = sum(1 for record in relevant_records if record.outcome == "no_results")
    low_confidence_requests = sum(
        1 for record in relevant_records if record.outcome == "low_confidence"
    )
    by_zero_result_reason = dict(
        Counter(record.zero_result_reason or "none" for record in relevant_records)
    )
    by_fallback_reason = dict(
        Counter(record.fallback_reason or "none" for record in relevant_records)
    )
    by_warning_code = dict(
        Counter(
            warning_code
            for record in relevant_records
            for warning_code in (record.warning_codes if record.warning_codes else ("none",))
        )
    )
    by_retrieval_mode = dict(
        Counter(record.retrieval_mode or "unknown" for record in relevant_records)
    )
    top_affected_products = dict(
        Counter(record.product_id or "unknown" for record in relevant_records)
    )
    top_affected_programming_languages = dict(
        Counter(record.programming_language or "unknown" for record in relevant_records)
    )

    grouped_records: dict[tuple[str, str, str, str], list[AnalyticsQueryRecord]] = {}
    for record in relevant_records:
        primary_warning_code = (
            sorted(record.warning_codes, key=lambda item: (item.casefold(), item))[0]
            if record.warning_codes
            else "none"
        )
        key = (
            record.zero_result_reason or "none",
            record.fallback_reason or "none",
            record.retrieval_mode or "unknown",
            primary_warning_code,
        )
        grouped_records.setdefault(key, []).append(record)

    clusters = tuple(
        _build_zero_result_cluster(
            key=key,
            records=cluster_records,
            filtered_total=filtered_total,
        )
        for key, cluster_records in sorted(
            grouped_records.items(),
            key=lambda item: (
                -len(item[1]),
                item[0][0],
                item[0][1],
                item[0][2],
                item[0][3],
            ),
        )[:8]
    )
    share = (relevant_total / filtered_total) if filtered_total > 0 else 0.0
    return ZeroResultOverview(
        filtered_requests_total=filtered_total,
        without_useful_result_requests=relevant_total,
        without_useful_result_share=round(share, 4),
        no_result_requests=no_result_requests,
        low_confidence_requests=low_confidence_requests,
        by_zero_result_reason=by_zero_result_reason,
        by_fallback_reason=by_fallback_reason,
        by_warning_code=by_warning_code,
        by_retrieval_mode=by_retrieval_mode,
        top_affected_products=top_affected_products,
        top_affected_programming_languages=top_affected_programming_languages,
        clusters=clusters,
        refreshed_at=datetime.now(tz=UTC),
        refresh_lag_minutes=5,
    )


def _build_capacity_forecast(
    records: Sequence[AnalyticsQueryRecord],
) -> CapacityForecastSummary:
    if not records:
        return CapacityForecastSummary(
            filtered_requests_total=0,
            observed_window_hours=1.0,
            projected_requests_next_24h=0,
            previous_window_requests=0,
            growth_ratio=0.0,
            zero_result_pressure_share=0.0,
            low_confidence_share=0.0,
            warning_density=0.0,
            coverage_saturation_score=0.0,
            saturation_risk="low",
            recommended_action="No traffic yet. Keep monitoring until real usage data appears.",
            hottest_products=(),
            refreshed_at=datetime.now(tz=UTC),
            refresh_lag_minutes=5,
        )

    newest = max(record.created_at for record in records)
    oldest = min(record.created_at for record in records)
    recent_window_start = max(oldest, newest - timedelta(hours=24))
    recent_records = tuple(record for record in records if record.created_at >= recent_window_start)
    previous_records = tuple(
        record
        for record in records
        if recent_window_start - timedelta(hours=24) <= record.created_at < recent_window_start
    )
    observed_seconds = max(
        (newest - min(record.created_at for record in recent_records)).total_seconds(),
        3600.0,
    )
    observed_window_hours = round(observed_seconds / 3600.0, 2)
    projected_requests_next_24h = int(round(len(recent_records) / observed_window_hours * 24.0))
    previous_window_requests = len(previous_records)
    growth_ratio = _compute_growth_ratio(
        current=len(recent_records),
        previous=previous_window_requests,
    )
    zero_result_pressure_share = _share(
        sum(1 for record in recent_records if record.outcome == "no_results"),
        len(recent_records),
    )
    low_confidence_share = _share(
        sum(1 for record in recent_records if record.outcome == "low_confidence"),
        len(recent_records),
    )
    warning_density = round(
        sum(len(record.warning_codes) for record in recent_records) / len(recent_records),
        4,
    )

    recent_by_product = Counter(record.product_id or "unknown" for record in recent_records)
    previous_by_product = Counter(record.product_id or "unknown" for record in previous_records)
    hottest_products = tuple(
        _build_capacity_forecast_product_summary(
            product_id=product_id,
            recent_records=tuple(
                record
                for record in recent_records
                if (record.product_id or "unknown") == product_id
            ),
            total_recent_requests=len(recent_records),
            previous_window_requests=previous_by_product.get(product_id, 0),
        )
        for product_id, _count in sorted(
            recent_by_product.items(),
            key=lambda item: (-item[1], item[0]),
        )[:6]
    )
    coverage_saturation_score = (
        hottest_products[0].coverage_saturation_score if hottest_products else 0.0
    )
    saturation_risk = _forecast_risk_label(coverage_saturation_score)
    recommended_action = _capacity_recommendation(
        saturation_risk=saturation_risk,
        zero_result_pressure_share=zero_result_pressure_share,
        growth_ratio=growth_ratio,
    )
    return CapacityForecastSummary(
        filtered_requests_total=len(records),
        observed_window_hours=observed_window_hours,
        projected_requests_next_24h=projected_requests_next_24h,
        previous_window_requests=previous_window_requests,
        growth_ratio=growth_ratio,
        zero_result_pressure_share=zero_result_pressure_share,
        low_confidence_share=low_confidence_share,
        warning_density=warning_density,
        coverage_saturation_score=coverage_saturation_score,
        saturation_risk=saturation_risk,
        recommended_action=recommended_action,
        hottest_products=hottest_products,
        refreshed_at=datetime.now(tz=UTC),
        refresh_lag_minutes=5,
    )


def _build_capacity_forecast_product_summary(
    *,
    product_id: str,
    recent_records: Sequence[AnalyticsQueryRecord],
    total_recent_requests: int,
    previous_window_requests: int,
) -> CapacityForecastProductSummary:
    recent_requests = len(recent_records)
    observed_seconds = max(
        (
            max(record.created_at for record in recent_records)
            - min(record.created_at for record in recent_records)
        ).total_seconds(),
        3600.0,
    )
    projected_requests_next_24h = int(round(recent_requests / (observed_seconds / 3600.0) * 24.0))
    growth_ratio = _compute_growth_ratio(
        current=recent_requests,
        previous=previous_window_requests,
    )
    zero_result_pressure_share = _share(
        sum(1 for record in recent_records if record.outcome == "no_results"),
        recent_requests,
    )
    low_confidence_share = _share(
        sum(1 for record in recent_records if record.outcome == "low_confidence"),
        recent_requests,
    )
    warning_density = round(
        sum(len(record.warning_codes) for record in recent_records) / recent_requests,
        4,
    )
    request_share = _share(recent_requests, total_recent_requests)
    growth_component = min(max(growth_ratio, 0.0), 1.0)
    coverage_saturation_score = round(
        min(
            1.0,
            request_share * 0.45
            + zero_result_pressure_share * 0.35
            + low_confidence_share * 0.10
            + growth_component * 0.10,
        ),
        4,
    )
    saturation_risk = _forecast_risk_label(coverage_saturation_score)
    if zero_result_pressure_share >= 0.25:
        recommended_action = (
            "Increase indexed coverage or republish the latest-stable snapshot for this product."
        )
    elif growth_ratio >= 0.5:
        recommended_action = (
            "Traffic is growing quickly; validate hot SDK scopes and watch latency headroom."
        )
    elif warning_density >= 0.4:
        recommended_action = "Inspect warning-heavy requests before they grow into support load."
    else:
        recommended_action = "Monitor demand and keep latest-stable coverage fresh."
    return CapacityForecastProductSummary(
        product_id=product_id,
        recent_requests=recent_requests,
        previous_window_requests=previous_window_requests,
        projected_requests_next_24h=projected_requests_next_24h,
        growth_ratio=growth_ratio,
        zero_result_pressure_share=zero_result_pressure_share,
        low_confidence_share=low_confidence_share,
        warning_density=warning_density,
        coverage_saturation_score=coverage_saturation_score,
        saturation_risk=saturation_risk,
        recommended_action=recommended_action,
    )


def _share(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _compute_growth_ratio(*, current: int, previous: int) -> float:
    if current <= 0 and previous <= 0:
        return 0.0
    if previous <= 0:
        return 1.0
    return round((current - previous) / previous, 4)


def _forecast_risk_label(score: float) -> str:
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _capacity_recommendation(
    *,
    saturation_risk: str,
    zero_result_pressure_share: float,
    growth_ratio: float,
) -> str:
    if saturation_risk == "high":
        return (
            "Prioritize the hottest product scopes for coverage refresh and prepare extra runtime "
            "capacity before the next traffic spike."
        )
    if zero_result_pressure_share >= 0.2:
        return "Focus on missing coverage first; demand is already exposing answer gaps."
    if growth_ratio >= 0.5:
        return "Traffic is trending up. Watch latency, publish freshness, and hot product scopes."
    return "Current demand profile is stable. Keep monitoring and refresh snapshots routinely."


def _build_zero_result_cluster(
    *,
    key: tuple[str, str, str, str],
    records: Sequence[AnalyticsQueryRecord],
    filtered_total: int,
) -> ZeroResultClusterSummary:
    zero_result_reason, fallback_reason, retrieval_mode, primary_warning_code = key
    recommendation_title, recommendation_detail = _recommend_zero_result_action(
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        retrieval_mode=retrieval_mode,
        primary_warning_code=primary_warning_code,
    )
    share = (len(records) / filtered_total) if filtered_total > 0 else 0.0
    return ZeroResultClusterSummary(
        cluster_id="|".join(key),
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        retrieval_mode=retrieval_mode,
        primary_warning_code=primary_warning_code,
        total_requests=len(records),
        share_of_filtered_requests=round(share, 4),
        affected_products=_top_distinct_values(record.product_id for record in records),
        affected_programming_languages=_top_distinct_values(
            record.programming_language for record in records
        ),
        affected_doc_locales=_top_distinct_values(record.doc_locale for record in records),
        sample_queries=_sample_queries(records),
        recommendation_title=recommendation_title,
        recommendation_detail=recommendation_detail,
    )


def _is_zero_result_record(record: AnalyticsQueryRecord) -> bool:
    if record.outcome in {"no_results", "low_confidence"}:
        return True
    return record.zero_result_reason is not None or record.fallback_reason is not None


def _top_distinct_values(values: Iterable[str | None]) -> tuple[str, ...]:
    counter = Counter(value or "unknown" for value in values)
    return tuple(
        key
        for key, _count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0]),
        )[:4]
    )


def _sample_queries(records: Sequence[AnalyticsQueryRecord]) -> tuple[str, ...]:
    sample: list[str] = []
    seen: set[str] = set()
    for record in records:
        normalized = " ".join(record.raw_query.split()).strip()
        if not normalized:
            continue
        preview = normalized[:120]
        if preview in seen:
            continue
        seen.add(preview)
        sample.append(preview)
        if len(sample) >= 3:
            break
    return tuple(sample)


def _recommend_zero_result_action(
    *,
    zero_result_reason: str,
    fallback_reason: str,
    retrieval_mode: str,
    primary_warning_code: str,
) -> tuple[str, str]:
    if zero_result_reason == "no_index_data":
        return (
            "Publish or refresh coverage",
            "Run validate/publish for the affected product scope and verify "
            "that latest-stable snapshot exists.",
        )
    if zero_result_reason == "translation_dependency_unavailable" or (
        fallback_reason == "translation_dependency_unavailable"
    ):
        return (
            "Restore translation fallback",
            "Check the translation LLM endpoint or retry the query in English "
            "until translation dependency is healthy.",
        )
    if (
        fallback_reason == "low_confidence_best_effort"
        or primary_warning_code == "low_confidence_best_effort"
    ):
        return (
            "Inspect retrieval quality",
            "Review reranking, content freshness, and filters for this scope; "
            "low-confidence best-effort answers are dominating.",
        )
    if fallback_reason == "no_candidates":
        return (
            "Check filters and content fit",
            "Requested filters/version may be too narrow. Inspect version "
            "fallback and whether the product actually contains matching docs.",
        )
    if retrieval_mode == "symbol":
        return (
            "Verify symbol coverage",
            "Check symbol spelling, namespace normalization, and whether the "
            "target API reference was indexed for this language/version.",
        )
    if retrieval_mode == "release_notes":
        return (
            "Review release-note coverage",
            "Latest release artifacts may be missing or under-ranked. "
            "Validate release-note indexing and freshness weighting.",
        )
    return (
        "Review top warnings and scope filters",
        "Use the cluster warnings, affected products, and sample queries "
        "below to inspect coverage gaps or overly strict filters.",
    )


def _map_query_event_row(row: object) -> AnalyticsQueryRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected analytics query row payload."
        raise TypeError(msg)
    created_at = row.get("created_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid analytics query created_at value."
        raise TypeError(msg)
    return AnalyticsQueryRecord(
        request_id=str(row.get("request_id")),
        endpoint=str(row.get("endpoint")),
        tool=str(row.get("tool")),
        raw_query=str(row.get("raw_query")),
        product_id=_nullable_str(row.get("product_id")),
        programming_language=_nullable_str(row.get("programming_language")),
        doc_locale=_nullable_str(row.get("doc_locale")),
        hashed_ip=_nullable_str(row.get("hashed_ip")),
        fingerprint=_nullable_str(row.get("fingerprint")),
        latency_ms=max(_coerce_int(row.get("latency_ms")), 0),
        confidence=max(0.0, min(_coerce_float(row.get("confidence")), 1.0)),
        outcome=_normalize_outcome(
            outcome=_nullable_str(row.get("outcome")),
            confidence=_coerce_float(row.get("confidence")),
            result_count=_coerce_optional_int(row.get("result_count")),
        ),
        retrieval_mode=_nullable_str(row.get("retrieval_mode")),
        result_count=max(_coerce_optional_int(row.get("result_count")) or 0, 0),
        zero_result_reason=_nullable_str(row.get("zero_result_reason")),
        fallback_reason=_nullable_str(row.get("fallback_reason")),
        warning_codes=_parse_warning_codes(row.get("warning_codes")),
        created_at=created_at,
    )


def _map_usefulness_feedback_row(row: object) -> UsefulnessFeedbackRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected usefulness feedback row payload."
        raise TypeError(msg)
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        msg = "Invalid usefulness feedback timestamp value."
        raise TypeError(msg)
    return UsefulnessFeedbackRecord(
        feedback_id=str(row.get("feedback_id")),
        request_id=str(row.get("request_id")),
        actor_identity=str(row.get("actor_identity")),
        endpoint=str(row.get("endpoint")),
        tool=str(row.get("tool")),
        raw_query=str(row.get("raw_query")),
        product_id=_nullable_str(row.get("product_id")),
        programming_language=_nullable_str(row.get("programming_language")),
        doc_locale=_nullable_str(row.get("doc_locale")),
        outcome=_normalize_outcome(
            outcome=_nullable_str(row.get("outcome")),
            confidence=0.0,
            result_count=_coerce_optional_int(row.get("result_count")),
        ),
        retrieval_mode=_nullable_str(row.get("retrieval_mode")),
        result_count=max(_coerce_optional_int(row.get("result_count")) or 0, 0),
        zero_result_reason=_nullable_str(row.get("zero_result_reason")),
        fallback_reason=_nullable_str(row.get("fallback_reason")),
        warning_codes=_parse_warning_codes(row.get("warning_codes")),
        rating=_normalize_usefulness_rating(str(row.get("rating"))),
        reason_codes=_normalize_usefulness_reason_codes(_parse_warning_codes(row.get("reason_codes"))),
        created_at=created_at,
        updated_at=updated_at,
    )


def _map_issue_intake_row(row: object) -> IssueIntakeRecord:
    if not isinstance(row, Mapping):
        msg = "Unexpected issue intake row payload."
        raise TypeError(msg)
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
        msg = "Invalid issue intake timestamp value."
        raise TypeError(msg)
    return IssueIntakeRecord(
        issue_id=str(row.get("issue_id")),
        request_id=str(row.get("request_id")),
        actor_identity=str(row.get("actor_identity")),
        endpoint=str(row.get("endpoint")),
        tool=str(row.get("tool")),
        raw_query=str(row.get("raw_query")),
        product_id=_nullable_str(row.get("product_id")),
        programming_language=_nullable_str(row.get("programming_language")),
        doc_locale=_nullable_str(row.get("doc_locale")),
        outcome=_normalize_outcome(
            outcome=_nullable_str(row.get("outcome")),
            confidence=0.0,
            result_count=_coerce_optional_int(row.get("result_count")),
        ),
        retrieval_mode=_nullable_str(row.get("retrieval_mode")),
        result_count=max(_coerce_optional_int(row.get("result_count")) or 0, 0),
        zero_result_reason=_nullable_str(row.get("zero_result_reason")),
        fallback_reason=_nullable_str(row.get("fallback_reason")),
        warning_codes=_parse_warning_codes(row.get("warning_codes")),
        issue_type=_normalize_issue_type(str(row.get("issue_type"))),
        notes=_normalize_issue_notes(_nullable_str(row.get("notes"))),
        created_at=created_at,
        updated_at=updated_at,
    )


def _feedback_id(*, request_id: str, actor_identity: str) -> str:
    digest = hashlib.sha256(f"{request_id}|{actor_identity}".encode()).hexdigest()
    return f"fb_{digest[:16]}"


def _issue_id(*, request_id: str, actor_identity: str) -> str:
    digest = hashlib.sha256(f"{request_id}|{actor_identity}".encode()).hexdigest()
    return f"is_{digest[:16]}"


def _normalize_actor_identity(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = "actor_identity must not be empty."
        raise ValueError(msg)
    return normalized


def _normalize_usefulness_rating(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in _USEFULNESS_RATINGS:
        msg = "Invalid usefulness rating."
        raise ValueError(msg)
    return normalized


def _normalize_usefulness_reason_codes(reason_codes: Sequence[str] | None) -> tuple[str, ...]:
    if not reason_codes:
        return ()
    normalized = _normalize_warning_codes(reason_codes)
    invalid = sorted(
        code for code in normalized if code.casefold() not in _USEFULNESS_REASON_CODES
    )
    if invalid:
        msg = f"Invalid usefulness reason codes: {', '.join(invalid)}."
        raise ValueError(msg)
    return tuple(code.casefold() for code in normalized)


def _normalize_issue_type(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in _ISSUE_TYPES:
        msg = "Invalid issue type."
        raise ValueError(msg)
    return normalized


def _normalize_issue_notes(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 1000:
        msg = "Issue notes must be 1000 characters or fewer."
        raise ValueError(msg)
    return normalized


def _filter_usefulness_feedback_records(
    records: Sequence[UsefulnessFeedbackRecord],
    *,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    rating: str | None = None,
    reason_code: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    negative_only: bool = False,
    limit: int | None = None,
) -> tuple[UsefulnessFeedbackRecord, ...]:
    normalized_rating = (
        _normalize_usefulness_rating(rating) if rating is not None else None
    )
    normalized_reason_code = reason_code.strip().casefold() if reason_code else None

    def _matches(value: str | None, expected: str | None) -> bool:
        if expected is None:
            return True
        return value == expected

    filtered = tuple(
        record
        for record in records
        if _matches(record.product_id, product_id)
        and _matches(record.programming_language, programming_language)
        and _matches(record.doc_locale, doc_locale)
        and _matches(record.endpoint, endpoint)
        and _matches(record.tool, tool)
        and _matches(record.request_id, request_id)
        and (normalized_rating is None or record.rating == normalized_rating)
        and (
            normalized_reason_code is None
            or normalized_reason_code in {item.casefold() for item in record.reason_codes}
        )
        and (not negative_only or record.rating in _USEFULNESS_NEGATIVE_RATINGS)
        and (from_ts is None or record.updated_at >= from_ts)
        and (to_ts is None or record.updated_at <= to_ts)
    )
    ordered = tuple(
        sorted(
            filtered,
            key=lambda item: (item.updated_at, item.feedback_id),
            reverse=True,
        )
    )
    if limit is None:
        return ordered
    return ordered[: max(limit, 0)]


def _filter_issue_intake_records(
    records: Sequence[IssueIntakeRecord],
    *,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    issue_type: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int | None = None,
) -> tuple[IssueIntakeRecord, ...]:
    normalized_issue_type = (
        _normalize_issue_type(issue_type) if issue_type is not None else None
    )

    def _matches(value: str | None, expected: str | None) -> bool:
        if expected is None:
            return True
        return value == expected

    filtered = tuple(
        record
        for record in records
        if _matches(record.product_id, product_id)
        and _matches(record.programming_language, programming_language)
        and _matches(record.doc_locale, doc_locale)
        and _matches(record.endpoint, endpoint)
        and _matches(record.tool, tool)
        and _matches(record.request_id, request_id)
        and (normalized_issue_type is None or record.issue_type == normalized_issue_type)
        and (from_ts is None or record.updated_at >= from_ts)
        and (to_ts is None or record.updated_at <= to_ts)
    )
    ordered = tuple(
        sorted(
            filtered,
            key=lambda item: (item.updated_at, item.issue_id),
            reverse=True,
        )
    )
    if limit is None:
        return ordered
    return ordered[: max(limit, 0)]


def _build_usefulness_summary(
    records: Sequence[UsefulnessFeedbackRecord],
) -> UsefulnessSummary:
    total_feedback = len(records)
    by_rating = dict(Counter(record.rating for record in records))
    useful_feedback = by_rating.get("useful", 0)
    partially_useful_feedback = by_rating.get("partially_useful", 0)
    not_useful_feedback = by_rating.get("not_useful", 0)
    by_reason_code = dict(
        Counter(
            reason_code
            for record in records
            for reason_code in (record.reason_codes if record.reason_codes else ("none",))
        )
    )
    recent_negative_signals = _filter_usefulness_feedback_records(
        records,
        negative_only=True,
        limit=12,
    )
    return UsefulnessSummary(
        total_feedback=total_feedback,
        useful_feedback=useful_feedback,
        partially_useful_feedback=partially_useful_feedback,
        not_useful_feedback=not_useful_feedback,
        useful_share=(useful_feedback / total_feedback) if total_feedback > 0 else 0.0,
        negative_share=(
            (partially_useful_feedback + not_useful_feedback) / total_feedback
            if total_feedback > 0
            else 0.0
        ),
        by_rating=by_rating,
        by_reason_code=by_reason_code,
        by_product_id=dict(Counter(record.product_id or "unknown" for record in records)),
        by_programming_language=dict(
            Counter(record.programming_language or "unknown" for record in records)
        ),
        by_doc_locale=dict(Counter(record.doc_locale or "unknown" for record in records)),
        recent_negative_signals=recent_negative_signals,
        refreshed_at=datetime.now(tz=UTC),
        refresh_lag_minutes=5,
    )


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    msg = "Invalid integer value."
    raise TypeError(msg)


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _coerce_int(value)


def _coerce_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    msg = "Invalid float value."
    raise TypeError(msg)


def _normalize_warning_codes(warning_codes: Sequence[str] | None) -> tuple[str, ...]:
    if not warning_codes:
        return ()
    seen: set[str] = set()
    normalized_codes: list[str] = []
    for warning_code in warning_codes:
        normalized = warning_code.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_codes.append(normalized)
    return tuple(normalized_codes)


def _parse_warning_codes(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return _normalize_warning_codes(value.split(","))
    if isinstance(value, Sequence):
        return _normalize_warning_codes([str(item) for item in value])
    return ()


def _normalize_outcome(
    *,
    outcome: str | None,
    confidence: float,
    result_count: int | None,
) -> str:
    normalized = _nullable_str(outcome)
    if normalized is not None:
        return normalized
    if result_count is not None and result_count <= 0:
        return "no_results"
    if confidence <= 0.0:
        return "low_confidence"
    return "success"


# Tables and columns that are NEVER allowed to be queried via the SQL Explorer.
# These contain credentials, API key tokens (even hashed), session secrets,
# and other security-sensitive data that must not be exposed via ad-hoc SQL.
_BLOCKED_TABLES: tuple[str, ...] = (
    "admin_api_keys",
    "admin_sessions",
    "pg_authid",
    "pg_shadow",
    "pg_user",
    "pg_roles",
    "pg_user_mapping",
    "pg_db_role_setting",
    "information_schema.role_table_grants",
    "information_schema.role_column_grants",
)
_BLOCKED_COLUMN_PATTERNS: tuple[str, ...] = (
    "token_hash",
    "api_key",
    "password",
    "secret",
    "private_key",
    "credentials",
    "session_token",
)
# System schemas that may leak server internals — disallowed entirely.
_BLOCKED_SCHEMAS: tuple[str, ...] = (
    "pg_catalog",
    "pg_toast",
)


def _validate_read_only_select(sql: str) -> str:
    stripped_sql = sql.strip()
    if not stripped_sql:
        msg = "sql must not be empty."
        raise ValueError(msg)

    normalized_sql = " ".join(stripped_sql.split())
    lowered_sql = normalized_sql.casefold()
    if not lowered_sql.startswith("select") and not lowered_sql.startswith("with"):
        msg = "Only SELECT (or WITH ... SELECT) statements are allowed."
        raise ValueError(msg)

    # Block any DML/DDL keywords as standalone tokens.
    disallowed_tokens = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "grant",
        "revoke",
        "comment",
        "vacuum",
        "analyze",
        "copy",
        "lock",
        "reindex",
        "merge",
        "call",
        "do",
        "execute",
    )
    # Strip SQL identifier quoting before matching. The guard compares raw
    # substrings, so without this `SELECT * FROM "pg_authid"` would slip past every
    # check that `pg_authid` fails unquoted — the quote character is not one of
    # the prefixes the loops below look for. Double quotes are
    # the SQL-standard identifier delimiter and carry no meaning for these
    # checks; removing them makes quoted and unquoted spellings match alike.
    lowered_sql = lowered_sql.replace('"', "")
    tokenized_sql = f" {lowered_sql} "
    for token in disallowed_tokens:
        if f" {token} " in tokenized_sql:
            msg = f"Only read-only SELECT statements are allowed (forbidden token: {token})."
            raise ValueError(msg)

    if ";" in stripped_sql.rstrip(";"):
        msg = "Only a single SELECT statement is allowed."
        raise ValueError(msg)

    # Block sensitive tables and schemas — even read-only access leaks secrets.
    for blocked_table in _BLOCKED_TABLES:
        # Match the table as a whole word — looks for it preceded by
        # space, comma, dot, or open paren.
        for prefix in (" ", ",", "(", "."):
            if f"{prefix}{blocked_table.casefold()}" in tokenized_sql:
                msg = (
                    f"Access to table `{blocked_table}` is not allowed. "
                    "It contains credentials or sensitive data."
                )
                raise ValueError(msg)
        # Also catch when it appears at the start (no leading space).
        if tokenized_sql.lstrip().startswith(blocked_table.casefold()):
            msg = (
                f"Access to table `{blocked_table}` is not allowed. "
                "It contains credentials or sensitive data."
            )
            raise ValueError(msg)

    for blocked_schema in _BLOCKED_SCHEMAS:
        if f" {blocked_schema}." in tokenized_sql or f"({blocked_schema}." in tokenized_sql:
            msg = f"Access to system schema `{blocked_schema}` is not allowed."
            raise ValueError(msg)

    # Block sensitive column patterns — substring match because aliasing
    # could obscure them (e.g. `password AS x`).
    for blocked_column in _BLOCKED_COLUMN_PATTERNS:
        if blocked_column in lowered_sql:
            msg = (
                f"Access to column or pattern `{blocked_column}` is not allowed. "
                "Sensitive credential data must not be queried via SQL Explorer."
            )
            raise ValueError(msg)

    # Block obvious unbounded scans of pg_catalog via subquery / function.
    if "pg_read_server_files" in lowered_sql or "pg_ls_dir" in lowered_sql:
        msg = "Filesystem access functions are not allowed."
        raise ValueError(msg)

    return stripped_sql
