"""MCP protocol revision negotiation with nearest-supported fallback policy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class MCPFallbackReason(StrEnum):
    """Negotiation fallback reasons used by telemetry/debug surfaces."""

    NONE = "none"
    UNKNOWN_REVISION = "unknown_revision"
    BELOW_MIN_SUPPORTED = "below_min_supported"
    INVALID_REVISION_FORMAT = "invalid_revision_format"
    MISSING_REQUESTED_REVISION = "missing_requested_revision"


@dataclass(frozen=True, slots=True)
class MCPRevisionNegotiationResult:
    """Result of one MCP revision negotiation call."""

    requested_revision: str | None
    negotiated_revision: str
    fallback_applied: bool
    fallback_reason: MCPFallbackReason


def negotiate_mcp_revision(
    *,
    requested_revision: str | None,
    supported_revisions: Iterable[str],
    primary_revision: str,
) -> MCPRevisionNegotiationResult:
    """Negotiate one revision using codified nearest-supported algorithm."""
    supported = _normalize_and_sort_supported_revisions(supported_revisions)
    if not supported:
        msg = "supported_revisions must not be empty."
        raise ValueError(msg)
    if primary_revision not in supported:
        msg = "primary_revision must be present in supported_revisions."
        raise ValueError(msg)

    if requested_revision is None or not requested_revision.strip():
        # Not a fallback. The primary target is the defined outcome when no
        # revision is requested, and there are exactly three fallback reasons
        # (invalid format, below minimum, unknown revision) — this is not among
        # them. Counting it as a fallback moved `mcp_negotiation_fail_ratio`
        # against its SLO every time a client initialized without
        # protocolVersion, which is both common and correct. The reason is still
        # reported so telemetry can distinguish this shape of handshake.
        return MCPRevisionNegotiationResult(
            requested_revision=requested_revision,
            negotiated_revision=primary_revision,
            fallback_applied=False,
            fallback_reason=MCPFallbackReason.MISSING_REQUESTED_REVISION,
        )

    requested_value = requested_revision.strip()
    requested_date = _parse_revision_or_none(requested_value)
    if requested_date is None:
        return MCPRevisionNegotiationResult(
            requested_revision=requested_value,
            negotiated_revision=primary_revision,
            fallback_applied=True,
            fallback_reason=MCPFallbackReason.INVALID_REVISION_FORMAT,
        )

    if requested_value in supported:
        return MCPRevisionNegotiationResult(
            requested_revision=requested_value,
            negotiated_revision=requested_value,
            fallback_applied=False,
            fallback_reason=MCPFallbackReason.NONE,
        )

    supported_dates = tuple((_parse_revision_or_raise(value), value) for value in supported)
    min_date, min_revision = supported_dates[0]
    if requested_date < min_date:
        return MCPRevisionNegotiationResult(
            requested_revision=requested_value,
            negotiated_revision=min_revision,
            fallback_applied=True,
            fallback_reason=MCPFallbackReason.BELOW_MIN_SUPPORTED,
        )

    eligible = [
        revision
        for revision_date, revision in supported_dates
        if revision_date <= requested_date
    ]
    negotiated = eligible[-1] if eligible else min_revision
    return MCPRevisionNegotiationResult(
        requested_revision=requested_value,
        negotiated_revision=negotiated,
        fallback_applied=True,
        fallback_reason=MCPFallbackReason.UNKNOWN_REVISION,
    )


def _normalize_and_sort_supported_revisions(revisions: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_revision in revisions:
        revision = raw_revision.strip()
        if not revision or revision in seen:
            continue
        _parse_revision_or_raise(revision)
        seen.add(revision)
        normalized.append(revision)
    return tuple(sorted(normalized, key=_parse_revision_or_raise))


def _parse_revision_or_none(revision: str) -> date | None:
    try:
        return _parse_revision_or_raise(revision)
    except ValueError:
        return None


def _parse_revision_or_raise(revision: str) -> date:
    try:
        year_str, month_str, day_str = revision.split("-")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        return date(year, month, day)
    except (ValueError, TypeError) as exc:
        msg = f"Invalid MCP revision format: {revision!r}"
        raise ValueError(msg) from exc
