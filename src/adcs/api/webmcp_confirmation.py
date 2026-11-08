"""One-time WebMCP confirmation token service with TTL and replay protection."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any


@dataclass(frozen=True, slots=True)
class WebMCPConfirmationRecord:
    """Issued WebMCP confirmation token metadata."""

    confirm_token: str
    tool_name: str
    reason: str
    intent_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    consumed_request_id: str | None


@dataclass(frozen=True, slots=True)
class WebMCPConfirmationError(Exception):
    """Deterministic confirmation validation error."""

    code: str
    message: str


@dataclass(slots=True)
class _StoredConfirmationToken:
    confirm_token: str
    tool_name: str
    reason: str
    intent_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    consumed_request_id: str | None = None

    def as_record(self) -> WebMCPConfirmationRecord:
        return WebMCPConfirmationRecord(
            confirm_token=self.confirm_token,
            tool_name=self.tool_name,
            reason=self.reason,
            intent_fingerprint=self.intent_fingerprint,
            issued_at=self.issued_at,
            expires_at=self.expires_at,
            consumed_at=self.consumed_at,
            consumed_request_id=self.consumed_request_id,
        )


class WebMCPConfirmationService:
    """Issue and consume one-time confirmation tokens for WebMCP write tools."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        max_tokens: int = 10_000,
    ) -> None:
        if ttl_seconds < 1:
            msg = "ttl_seconds must be >= 1."
            raise ValueError(msg)
        if max_tokens < 100:
            msg = "max_tokens must be >= 100."
            raise ValueError(msg)
        self._ttl_seconds = ttl_seconds
        self._max_tokens = max_tokens
        self._lock = Lock()
        self._tokens: dict[str, _StoredConfirmationToken] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue(
        self,
        *,
        tool_name: str,
        reason: str,
        intent_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WebMCPConfirmationRecord:
        issued_at = now or datetime.now(tz=UTC)
        normalized_tool_name = _normalize_non_empty(tool_name, field_name="tool_name")
        normalized_reason = _normalize_non_empty(reason, field_name="reason")
        intent_fingerprint = _fingerprint_payload(intent_payload or {})
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        record = _StoredConfirmationToken(
            confirm_token="wmcp_cf_" + secrets.token_urlsafe(32),
            tool_name=normalized_tool_name,
            reason=normalized_reason,
            intent_fingerprint=intent_fingerprint,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        with self._lock:
            self._prune_locked(now=issued_at)
            self._tokens[record.confirm_token] = record
            self._trim_locked()
        return record.as_record()

    def consume(
        self,
        *,
        confirm_token: str | None,
        tool_name: str,
        reason: str,
        intent_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> WebMCPConfirmationRecord:
        resolved_now = now or datetime.now(tz=UTC)
        if confirm_token is None or not confirm_token.strip():
            raise WebMCPConfirmationError(
                code="CONFIRMATION_REQUIRED",
                message="Missing `confirm_token` for WebMCP write operation.",
            )
        normalized_token = confirm_token.strip()
        normalized_tool_name = _normalize_non_empty(tool_name, field_name="tool_name")
        normalized_reason = _normalize_non_empty(reason, field_name="reason")
        expected_intent_fingerprint = _fingerprint_payload(intent_payload or {})

        with self._lock:
            stored = self._tokens.get(normalized_token)
            if stored is None:
                raise WebMCPConfirmationError(
                    code="CONFIRMATION_INVALID",
                    message="Unknown confirmation token.",
                )
            if resolved_now >= stored.expires_at:
                del self._tokens[normalized_token]
                raise WebMCPConfirmationError(
                    code="CONFIRMATION_EXPIRED",
                    message="Confirmation token is expired.",
                )
            if stored.consumed_at is not None:
                raise WebMCPConfirmationError(
                    code="CONFIRMATION_REPLAYED",
                    message="Confirmation token has already been consumed.",
                )
            if (
                stored.tool_name != normalized_tool_name
                or stored.reason != normalized_reason
                or stored.intent_fingerprint != expected_intent_fingerprint
            ):
                raise WebMCPConfirmationError(
                    code="CONFIRMATION_MISMATCH",
                    message=(
                        "Confirmation token payload mismatch. Ensure tool_name, reason, "
                        "and target payload match issued confirmation."
                    ),
                )
            stored.consumed_at = resolved_now
            stored.consumed_request_id = request_id
            return stored.as_record()

    def _prune_locked(self, *, now: datetime) -> None:
        expired_tokens = tuple(
            token
            for token, item in self._tokens.items()
            if now >= item.expires_at
        )
        for token in expired_tokens:
            self._tokens.pop(token, None)

    def _trim_locked(self) -> None:
        overflow = len(self._tokens) - self._max_tokens
        if overflow <= 0:
            return
        ordered = sorted(
            self._tokens.values(),
            key=lambda item: (item.expires_at, item.issued_at, item.confirm_token),
        )
        for item in ordered[:overflow]:
            self._tokens.pop(item.confirm_token, None)


def _normalize_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = f"{field_name} must not be empty."
        raise ValueError(msg)
    return normalized


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
