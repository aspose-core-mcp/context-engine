"""Filter resolver for retrieval query planning."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

from adcs.retrieval.models import (
    FilterDebugMetadata,
    QueryPlannerInput,
    ResolvedRetrievalFilters,
    RetrievalFilterRoute,
    ScopedIndexRecord,
)

_PRODUCT_DELIMITER_RE = re.compile(r"[._\-/\s]+")
_PROGRAMMING_LANGUAGE_DELIMITER_RE = re.compile(r"[._/\s]+")
_DOC_LOCALE_DELIMITER_RE = re.compile(r"[_\s]+")
_VERSION_HINT_RE = re.compile(
    r"^(?:v)?(?P<major>\d+)(?:[.\-_](?P<minor>\d+|x))?$",
    re.IGNORECASE,
)

_DEFAULT_PROGRAMMING_LANGUAGE_ALIASES: dict[str, str] = {
    ".net": "net",
    "c#": "net",
    "csharp": "net",
    "dotnet": "net",
}
_DEFAULT_DOC_LOCALE_ALIASES: dict[str, str] = {
    "english": "en",
    "en-gb": "en",
    "en-us": "en",
}

Normalizer = Callable[[str], str | None]
RecordT = TypeVar("RecordT", bound=ScopedIndexRecord)


class FilterResolver:
    """Resolve strict retrieval filters and locale routing in deterministic order."""

    def __init__(
        self,
        *,
        product_aliases: Mapping[str, str] | None = None,
        programming_language_aliases: Mapping[str, str] | None = None,
        doc_locale_aliases: Mapping[str, str] | None = None,
        default_doc_locale: str = "en",
    ) -> None:
        self._product_aliases = _normalize_alias_map(
            aliases=product_aliases,
            normalizer=_normalize_product_id,
        )
        self._programming_language_aliases = {
            **_normalize_alias_map(
                aliases=_DEFAULT_PROGRAMMING_LANGUAGE_ALIASES,
                normalizer=_normalize_programming_language,
            ),
            **_normalize_alias_map(
                aliases=programming_language_aliases,
                normalizer=_normalize_programming_language,
            ),
        }
        self._doc_locale_aliases = {
            **_normalize_alias_map(
                aliases=_DEFAULT_DOC_LOCALE_ALIASES,
                normalizer=_normalize_doc_locale,
            ),
            **_normalize_alias_map(
                aliases=doc_locale_aliases,
                normalizer=_normalize_doc_locale,
            ),
        }
        normalized_default_locale = _normalize_doc_locale(default_doc_locale)
        self._default_doc_locale = normalized_default_locale or "en"

    def resolve(self, *, request: QueryPlannerInput) -> ResolvedRetrievalFilters:
        """Resolve effective product/language/version/locale filters for retrieval."""
        requested_product_id = _empty_to_none(request.product_id)
        requested_programming_language = _empty_to_none(request.programming_language)
        requested_version = _empty_to_none(request.version)
        requested_doc_locale = _empty_to_none(request.doc_locale)

        effective_product_id = _resolve_with_alias(
            raw_value=requested_product_id,
            aliases=self._product_aliases,
            normalizer=_normalize_product_id,
        )
        effective_programming_language = _resolve_with_alias(
            raw_value=requested_programming_language,
            aliases=self._programming_language_aliases,
            normalizer=_normalize_programming_language,
        )
        preferred_version = normalize_version_hint(requested_version)
        strict_version_value = preferred_version if request.strict_version else None

        preferred_doc_locale = _resolve_with_alias(
            raw_value=requested_doc_locale,
            aliases=self._doc_locale_aliases,
            normalizer=_normalize_doc_locale,
        )
        locale_routing_order = _build_locale_routing(
            preferred_doc_locale=preferred_doc_locale,
            default_doc_locale=self._default_doc_locale,
        )
        routes = tuple(
            RetrievalFilterRoute(
                product_id=effective_product_id,
                programming_language=effective_programming_language,
                version=strict_version_value,
                doc_locale=doc_locale,
            )
            for doc_locale in locale_routing_order
        )

        debug = FilterDebugMetadata(
            requested_product_id=requested_product_id,
            requested_programming_language=requested_programming_language,
            requested_version=requested_version,
            requested_doc_locale=requested_doc_locale,
            effective_product_id=effective_product_id,
            effective_programming_language=effective_programming_language,
            preferred_version=preferred_version,
            strict_version_value=strict_version_value,
            strict_version_enforced=request.strict_version and strict_version_value is not None,
            locale_routing_order=locale_routing_order,
            locale_fallback_to_en_enabled=len(locale_routing_order) > 1,
        )
        return ResolvedRetrievalFilters(
            product_id=effective_product_id,
            programming_language=effective_programming_language,
            preferred_version=preferred_version,
            strict_version=request.strict_version,
            strict_version_value=strict_version_value,
            locale_routing_order=locale_routing_order,
            routes=routes,
            debug=debug,
        )

    def record_matches_route(
        self,
        *,
        record: ScopedIndexRecord,
        route: RetrievalFilterRoute,
        strict_version: bool,
    ) -> bool:
        """Check whether one index record belongs to a resolved retrieval route."""
        if (
            route.product_id is not None
            and _normalize_product_id(record.product_id) != route.product_id
        ):
            return False
        if (
            route.programming_language is not None
            and _normalize_programming_language(record.programming_language)
            != route.programming_language
        ):
            return False
        if strict_version and route.version is not None:
            if normalize_version_hint(record.version) != route.version:
                return False
        normalized_record_locale = _resolve_with_alias(
            raw_value=record.doc_locale,
            aliases=self._doc_locale_aliases,
            normalizer=_normalize_doc_locale,
        )
        if normalized_record_locale == route.doc_locale:
            return True
        if _is_unknown_doc_locale(normalized_record_locale):
            return route.doc_locale == self._default_doc_locale
        return False

    def filter_records_for_route(
        self,
        *,
        records: Sequence[RecordT],
        route: RetrievalFilterRoute,
        strict_version: bool,
    ) -> tuple[RecordT, ...]:
        """Filter records by one retrieval route while enforcing strict mode guards."""
        return tuple(
            record
            for record in records
            if self.record_matches_route(record=record, route=route, strict_version=strict_version)
        )


def normalize_version_hint(version: str | None) -> str | None:
    """Normalize version hints (25, 25.x, v25.1) to deterministic tokens."""
    raw_version = _empty_to_none(version)
    if raw_version is None:
        return None

    lowered = raw_version.lower()
    if lowered in {"latest", "latest-stable", "stable"}:
        return "latest-stable"

    match = _VERSION_HINT_RE.fullmatch(lowered)
    if match is None:
        return lowered

    major = str(int(match.group("major")))
    minor = match.group("minor")
    if minor is None or minor == "x":
        return major
    return f"{major}.{int(minor)}"


def _build_locale_routing(
    *,
    preferred_doc_locale: str | None,
    default_doc_locale: str,
) -> tuple[str, ...]:
    first_locale = preferred_doc_locale or default_doc_locale
    if first_locale == default_doc_locale:
        return (first_locale,)
    return (first_locale, default_doc_locale)


def _resolve_with_alias(
    *,
    raw_value: str | None,
    aliases: Mapping[str, str],
    normalizer: Normalizer,
) -> str | None:
    if raw_value is None:
        return None

    normalized = normalizer(raw_value)
    if normalized is None:
        return None
    return aliases.get(normalized, normalized)


def _normalize_alias_map(
    *,
    aliases: Mapping[str, str] | None,
    normalizer: Normalizer,
) -> dict[str, str]:
    if aliases is None:
        return {}

    normalized_aliases: dict[str, str] = {}
    for alias, canonical in aliases.items():
        normalized_alias = normalizer(alias)
        normalized_canonical = normalizer(canonical)
        if normalized_alias is None or normalized_canonical is None:
            continue
        normalized_aliases[normalized_alias] = normalized_canonical
    return normalized_aliases


def _normalize_product_id(raw_value: str) -> str | None:
    cleaned = _empty_to_none(raw_value)
    if cleaned is None:
        return None

    parts = [part for part in _PRODUCT_DELIMITER_RE.split(cleaned.lower()) if part]
    if not parts:
        return None
    return ".".join(parts)


def _normalize_programming_language(raw_value: str) -> str | None:
    cleaned = _empty_to_none(raw_value)
    if cleaned is None:
        return None

    lowered = cleaned.lower()
    if lowered == "c++":
        return "cpp"
    parts = [part for part in _PROGRAMMING_LANGUAGE_DELIMITER_RE.split(lowered) if part]
    if not parts:
        return None
    return "-".join(parts)


def _normalize_doc_locale(raw_value: str) -> str | None:
    cleaned = _empty_to_none(raw_value)
    if cleaned is None:
        return None

    normalized = _DOC_LOCALE_DELIMITER_RE.sub("-", cleaned.lower())
    if len(normalized) == 2:
        return normalized
    if "-" in normalized:
        language_part = normalized.split("-", maxsplit=1)[0]
        if len(language_part) == 2:
            return language_part
    return normalized


def _is_unknown_doc_locale(value: str | None) -> bool:
    if value is None:
        return True
    return value in {"unknown", "und", "none", "n/a", "na"}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
