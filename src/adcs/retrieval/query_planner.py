"""Deterministic query normalization and planning for retrieval."""

from __future__ import annotations

import re

from adcs.ops.privacy import keyed_hash
from adcs.retrieval.filter_resolver import FilterResolver
from adcs.retrieval.models import (
    QueryNormalizationResult,
    QueryPlan,
    QueryPlanDebugMetadata,
    QueryPlannerInput,
)

_SYMBOL_CANDIDATE_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_VERSION_TOKEN_RE = re.compile(r"\bv?\d+(?:[.\-_](?:\d+|x)){0,2}\b", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_QUERY_LENGTH = 2000

_NOISE_PREFIXES: tuple[str, ...] = (
    "can you ",
    "could you ",
    "how do i ",
    "how to ",
    "i need to ",
    "please ",
    "would you ",
)
_TROUBLESHOOTING_KEYWORDS = (
    "error",
    "exception",
    "fail",
    "fails",
    "failing",
    "issue",
    "problem",
    "not work",
    "does not work",
    "cannot",
    "can't",
    "unable",
    "wrong result",
)
_RELEASE_NOTE_KEYWORDS = (
    "breaking",
    "deprecated",
    "migration",
    "migrate",
    "upgrade",
    "release",
    "what's new",
    "whats new",
    "new in",
    "changed",
)
_LATEST_STABLE_KEYWORDS = (
    "latest",
    "latest stable",
    "latest-stable",
    "newest",
    "most recent",
    "current version",
)
_HOW_TO_KEYWORDS = (
    "how",
    "use",
    "install",
    "call",
    "implement",
    "create",
    "extract",
    "recognize",
    "read",
    "write",
    "convert",
    "parse",
    "configure",
)


class QueryPlanner:
    """Build deterministic retrieval plans with normalized query and filters."""

    def __init__(self, *, filter_resolver: FilterResolver | None = None) -> None:
        self._filter_resolver = filter_resolver or FilterResolver()

    def plan(self, *, request: QueryPlannerInput) -> QueryPlan:
        """Create one retrieval query plan from raw user input."""
        normalized_query = normalize_query(request.query)
        resolved_filters = self._filter_resolver.resolve(request=request)
        debug = QueryPlanDebugMetadata(
            raw_query=request.query,
            normalized_query=normalized_query.normalized_query,
            removed_noise_prefixes=normalized_query.removed_noise_prefixes,
            symbol_candidates=normalized_query.symbol_candidates,
            intent=normalized_query.intent,
            intent_subtype=normalized_query.intent_subtype,
            intent_reason_codes=normalized_query.intent_reason_codes,
            detected_version_tokens=normalized_query.detected_version_tokens,
            prefers_latest_stable=normalized_query.prefers_latest_stable,
            filter_debug=resolved_filters.debug,
        )
        return QueryPlan(
            normalized_query=normalized_query.normalized_query,
            query_fingerprint=_fingerprint_query(normalized_query.normalized_query),
            symbol_candidates=normalized_query.symbol_candidates,
            intent=normalized_query.intent,
            intent_subtype=normalized_query.intent_subtype,
            intent_reason_codes=normalized_query.intent_reason_codes,
            detected_version_tokens=normalized_query.detected_version_tokens,
            prefers_latest_stable=normalized_query.prefers_latest_stable,
            filters=resolved_filters,
            debug=debug,
        )


def normalize_query(query: str) -> QueryNormalizationResult:
    """Normalize query text while preserving API-like identifiers."""
    compact_query = _WHITESPACE_RE.sub(" ", query).strip()
    if len(compact_query) > _MAX_QUERY_LENGTH:
        compact_query = compact_query[:_MAX_QUERY_LENGTH]
    if not compact_query:
        return QueryNormalizationResult(
            normalized_query="",
            removed_noise_prefixes=(),
            symbol_candidates=(),
            intent="general_reference",
            intent_reason_codes=(),
            detected_version_tokens=(),
            prefers_latest_stable=False,
            intent_subtype=None,
        )

    normalized_query, removed_noise_prefixes = _strip_noise_prefixes(compact_query)
    if not normalized_query:
        normalized_query = compact_query

    symbol_candidates = _extract_symbol_candidates(normalized_query)
    detected_version_tokens = _extract_version_tokens(normalized_query)
    prefers_latest_stable = _prefers_latest_stable(normalized_query)
    intent, intent_subtype, intent_reason_codes = _classify_intent(
        normalized_query=normalized_query,
        symbol_candidates=symbol_candidates,
        detected_version_tokens=detected_version_tokens,
        prefers_latest_stable=prefers_latest_stable,
    )

    return QueryNormalizationResult(
        normalized_query=normalized_query,
        removed_noise_prefixes=removed_noise_prefixes,
        symbol_candidates=symbol_candidates,
        intent=intent,
        intent_subtype=intent_subtype,
        intent_reason_codes=intent_reason_codes,
        detected_version_tokens=detected_version_tokens,
        prefers_latest_stable=prefers_latest_stable,
    )


def _strip_noise_prefixes(query: str) -> tuple[str, tuple[str, ...]]:
    working_query = query
    removed_prefixes: list[str] = []
    while working_query:
        lowered_query = working_query.lower()
        matched_prefix = next(
            (prefix for prefix in _NOISE_PREFIXES if lowered_query.startswith(prefix)),
            None,
        )
        if matched_prefix is None:
            break
        removed_prefixes.append(matched_prefix.strip())
        working_query = working_query[len(matched_prefix) :].strip()
    return working_query, tuple(removed_prefixes)


def _extract_symbol_candidates(query: str) -> tuple[str, ...]:
    symbol_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in _SYMBOL_CANDIDATE_RE.findall(query):
        if candidate in seen:
            continue
        seen.add(candidate)
        symbol_candidates.append(candidate)
    return tuple(symbol_candidates)


def _extract_version_tokens(query: str) -> tuple[str, ...]:
    version_tokens: list[str] = []
    seen: set[str] = set()
    for candidate in _VERSION_TOKEN_RE.findall(query):
        normalized = candidate.strip()
        if not normalized:
            continue
        candidate_key = normalized.casefold()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        version_tokens.append(normalized)
    return tuple(version_tokens)


def _prefers_latest_stable(query: str) -> bool:
    lowered_query = query.casefold()
    return any(keyword in lowered_query for keyword in _LATEST_STABLE_KEYWORDS)


def _classify_intent(
    *,
    normalized_query: str,
    symbol_candidates: tuple[str, ...],
    detected_version_tokens: tuple[str, ...],
    prefers_latest_stable: bool,
) -> tuple[str, str | None, tuple[str, ...]]:
    lowered_query = normalized_query.casefold()
    if symbol_candidates:
        return "symbol_lookup", _symbol_subtype(lowered_query), ("symbol_candidate",)

    troubleshooting_hits = tuple(
        keyword for keyword in _TROUBLESHOOTING_KEYWORDS if keyword in lowered_query
    )
    release_hits = tuple(
        keyword for keyword in _RELEASE_NOTE_KEYWORDS if keyword in lowered_query
    )
    how_to_hits = tuple(keyword for keyword in _HOW_TO_KEYWORDS if keyword in lowered_query)

    release_score = len(release_hits) + len(detected_version_tokens)
    if prefers_latest_stable:
        release_score += 2
    troubleshooting_score = len(troubleshooting_hits)

    if release_score > 0 and release_score >= troubleshooting_score:
        reason_codes: list[str] = []
        if any(keyword in release_hits for keyword in ("migration", "migrate", "upgrade")):
            reason_codes.append("migration_keyword")
        if any(
            keyword in release_hits
            for keyword in ("release", "what's new", "whats new", "new in")
        ):
            reason_codes.append("release_keyword")
        if any(keyword in release_hits for keyword in ("breaking", "deprecated", "changed")):
            reason_codes.append("change_keyword")
        if detected_version_tokens:
            reason_codes.append("version_token")
        if prefers_latest_stable:
            reason_codes.append("latest_stable_hint")
        return (
            "release_notes",
            _release_subtype(release_hits),
            tuple(reason_codes or ("release_keyword",)),
        )
    if troubleshooting_score > 0:
        return "troubleshooting", _troubleshooting_subtype(lowered_query), (
            "troubleshooting_keyword",
        )
    if how_to_hits:
        return "how_to", _how_to_subtype(lowered_query), ("how_to_keyword",)
    return "general_reference", None, ()


def _release_subtype(release_hits: tuple[str, ...]) -> str | None:
    if any(keyword in release_hits for keyword in ("migration", "migrate", "upgrade")):
        return "migration"
    if any(
        keyword in release_hits
        for keyword in ("release", "what's new", "whats new", "new in")
    ):
        return "latest_release"
    if any(keyword in release_hits for keyword in ("breaking", "deprecated", "changed")):
        return "breaking_change"
    return "release_summary"


def _troubleshooting_subtype(lowered_query: str) -> str | None:
    if any(keyword in lowered_query for keyword in ("accuracy", "wrong result", "poor result")):
        return "quality_issue"
    if any(keyword in lowered_query for keyword in ("timeout", "slow", "latency")):
        return "performance_issue"
    if any(keyword in lowered_query for keyword in ("error", "exception", "fail", "unable")):
        return "runtime_failure"
    return "general_issue"


def _how_to_subtype(lowered_query: str) -> str | None:
    if any(keyword in lowered_query for keyword in ("install", "nuget", "package")):
        return "installation"
    if any(keyword in lowered_query for keyword in ("configure", "settings", "option")):
        return "configuration"
    if any(keyword in lowered_query for keyword in ("extract", "recognize", "read", "convert")):
        return "implementation"
    return "general_usage"


def _symbol_subtype(lowered_query: str) -> str | None:
    if any(keyword in lowered_query for keyword in ("error", "exception", "fail", "issue")):
        return "symbol_troubleshooting"
    if any(keyword in lowered_query for keyword in ("deprecated", "migration", "replacement")):
        return "symbol_migration"
    return "symbol_reference"


def _fingerprint_query(normalized_query: str) -> str:
    return keyed_hash(normalized_query.lower(), purpose="query_fingerprint")
