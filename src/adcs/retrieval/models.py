"""Typed models for retrieval query planning and filter resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QueryPlannerInput:
    """Raw retrieval planning input from API or MCP layer."""

    query: str
    product_id: str | None = None
    programming_language: str | None = None
    version: str | None = None
    doc_locale: str | None = None
    strict_version: bool = False


@dataclass(frozen=True, slots=True)
class QueryNormalizationResult:
    """Normalized query payload used for routing and cache keys."""

    normalized_query: str
    removed_noise_prefixes: tuple[str, ...]
    symbol_candidates: tuple[str, ...]
    intent: str
    intent_reason_codes: tuple[str, ...]
    detected_version_tokens: tuple[str, ...]
    prefers_latest_stable: bool
    intent_subtype: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalFilterRoute:
    """One deterministic retrieval route for a concrete document locale.

    ``active_snapshot_ids`` is the set of currently-active snapshot identifiers
    that this route should restrict results to. It is resolved at query time
    by :class:`PublicQueryService` against the snapshot registry and applied
    as a payload filter in the dense/lexical lane adapters. This prevents
    stale points from promoted-then-rolled-back snapshots bleeding into
    retrieval results. ``None`` means "do not enforce" — reserved for
    legacy/test paths that do not have a registry available.
    """

    product_id: str | None
    programming_language: str | None
    version: str | None
    doc_locale: str
    active_snapshot_ids: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class FilterDebugMetadata:
    """Debug metadata describing requested/effective filter decisions."""

    requested_product_id: str | None
    requested_programming_language: str | None
    requested_version: str | None
    requested_doc_locale: str | None
    effective_product_id: str | None
    effective_programming_language: str | None
    preferred_version: str | None
    strict_version_value: str | None
    strict_version_enforced: bool
    locale_routing_order: tuple[str, ...]
    locale_fallback_to_en_enabled: bool


@dataclass(frozen=True, slots=True)
class ResolvedRetrievalFilters:
    """Resolved retrieval filters and route order for candidate generation."""

    product_id: str | None
    programming_language: str | None
    preferred_version: str | None
    strict_version: bool
    strict_version_value: str | None
    locale_routing_order: tuple[str, ...]
    routes: tuple[RetrievalFilterRoute, ...]
    debug: FilterDebugMetadata


@dataclass(frozen=True, slots=True)
class QueryPlanDebugMetadata:
    """Planner debug metadata for explainability and incident forensics."""

    raw_query: str
    normalized_query: str
    removed_noise_prefixes: tuple[str, ...]
    symbol_candidates: tuple[str, ...]
    intent: str
    intent_subtype: str | None
    intent_reason_codes: tuple[str, ...]
    detected_version_tokens: tuple[str, ...]
    prefers_latest_stable: bool
    filter_debug: FilterDebugMetadata


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Deterministic retrieval plan generated for one query request."""

    normalized_query: str
    query_fingerprint: str
    symbol_candidates: tuple[str, ...]
    intent: str
    intent_subtype: str | None
    intent_reason_codes: tuple[str, ...]
    detected_version_tokens: tuple[str, ...]
    prefers_latest_stable: bool
    filters: ResolvedRetrievalFilters
    debug: QueryPlanDebugMetadata


class ScopedIndexRecord(Protocol):
    """Contract shared by lexical/vector index records used by retrieval filters."""

    product_id: str
    programming_language: str
    version: str
    doc_locale: str
