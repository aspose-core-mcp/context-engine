"""Soft-throttle abuse guard for public REST/MCP request paths."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from fastapi import Request

from adcs.config import AbuseGuardMode, EnvironmentProfile, Settings
from adcs.ops.privacy import keyed_hash

_DEBUG_HEADER = "x-adcs-debug"
_FINGERPRINT_HEADER = "x-adcs-fingerprint"
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AbuseGuardSettingsSnapshot:
    """Runtime snapshot exposed by admin API."""

    mode: AbuseGuardMode
    allowlist: tuple[str, ...]
    requests_per_ip_per_minute: int
    requests_per_fingerprint_per_minute: int
    requests_global_per_minute: int
    debug_header_enabled: bool
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AbuseGuardDecision:
    """Decision for one request under current abuse policy."""

    blocked: bool
    exceeded: bool
    mode: AbuseGuardMode
    reason: str
    matched_allowlist: bool
    hashed_ip: str | None
    fingerprint: str | None
    global_count: int
    ip_count: int
    fingerprint_count: int


class AbuseGuardService:
    """In-memory minute-window soft-throttle and abuse guard policy."""

    def __init__(
        self,
        *,
        mode: AbuseGuardMode,
        allowlist: tuple[str, ...],
        requests_per_ip_per_minute: int,
        requests_per_fingerprint_per_minute: int,
        requests_global_per_minute: int,
        debug_header_enabled: bool,
        updated_by: str,
        trusted_proxy_hops: int = 0,
    ) -> None:
        self._lock = Lock()
        self._trusted_proxy_hops = trusted_proxy_hops
        self._mode = mode
        self._allowlist = tuple(_normalize_token(item) for item in allowlist if item.strip())
        self._requests_per_ip_per_minute = requests_per_ip_per_minute
        self._requests_per_fingerprint_per_minute = requests_per_fingerprint_per_minute
        self._requests_global_per_minute = requests_global_per_minute
        self._debug_header_enabled = debug_header_enabled
        self._updated_by = updated_by
        self._updated_at = datetime.now(tz=UTC)

        self._window_minute = _current_minute()
        self._global_count = 0
        self._per_ip_count: dict[str, int] = {}
        self._per_fingerprint_count: dict[str, int] = {}

    @classmethod
    def from_settings(cls, *, settings: Settings) -> AbuseGuardService:
        return cls(
            mode=settings.abuse_guard_mode,
            allowlist=settings.abuse_guard_allowlist,
            requests_per_ip_per_minute=settings.abuse_requests_per_ip_per_minute,
            requests_per_fingerprint_per_minute=settings.abuse_requests_per_fingerprint_per_minute,
            requests_global_per_minute=settings.abuse_requests_global_per_minute,
            debug_header_enabled=(
                settings.test_mode or settings.env_profile is EnvironmentProfile.DEV
            ),
            updated_by="bootstrap",
            trusted_proxy_hops=settings.trusted_proxy_hops,
        )

    def snapshot(self) -> AbuseGuardSettingsSnapshot:
        with self._lock:
            return AbuseGuardSettingsSnapshot(
                mode=self._mode,
                allowlist=self._allowlist,
                requests_per_ip_per_minute=self._requests_per_ip_per_minute,
                requests_per_fingerprint_per_minute=self._requests_per_fingerprint_per_minute,
                requests_global_per_minute=self._requests_global_per_minute,
                debug_header_enabled=self._debug_header_enabled,
                updated_by=self._updated_by,
                updated_at=self._updated_at,
            )

    def update_settings(
        self,
        *,
        actor_key_id: str,
        mode: AbuseGuardMode | None = None,
        allowlist: tuple[str, ...] | None = None,
        requests_per_ip_per_minute: int | None = None,
        requests_per_fingerprint_per_minute: int | None = None,
        requests_global_per_minute: int | None = None,
        debug_header_enabled: bool | None = None,
    ) -> AbuseGuardSettingsSnapshot:
        with self._lock:
            if mode is not None:
                self._mode = mode
            if allowlist is not None:
                self._allowlist = tuple(
                    _normalize_token(item) for item in allowlist if item.strip()
                )
            if requests_per_ip_per_minute is not None:
                self._requests_per_ip_per_minute = requests_per_ip_per_minute
            if requests_per_fingerprint_per_minute is not None:
                self._requests_per_fingerprint_per_minute = requests_per_fingerprint_per_minute
            if requests_global_per_minute is not None:
                self._requests_global_per_minute = requests_global_per_minute
            if debug_header_enabled is not None:
                self._debug_header_enabled = debug_header_enabled

            self._updated_by = actor_key_id
            self._updated_at = datetime.now(tz=UTC)
            return AbuseGuardSettingsSnapshot(
                mode=self._mode,
                allowlist=self._allowlist,
                requests_per_ip_per_minute=self._requests_per_ip_per_minute,
                requests_per_fingerprint_per_minute=self._requests_per_fingerprint_per_minute,
                requests_global_per_minute=self._requests_global_per_minute,
                debug_header_enabled=self._debug_header_enabled,
                updated_by=self._updated_by,
                updated_at=self._updated_at,
            )

    def evaluate_request(self, *, request: Request) -> AbuseGuardDecision:
        fingerprint = _normalize_nullable_token(request.headers.get(_FINGERPRINT_HEADER))
        client_host = _extract_client_host(
            request, trusted_proxy_hops=self._trusted_proxy_hops
        )
        hashed_ip = _hash_value(client_host) if client_host else None

        with self._lock:
            self._rotate_window_if_needed()

            if self._debug_header_enabled and _is_truthy(request.headers.get(_DEBUG_HEADER)):
                return AbuseGuardDecision(
                    blocked=False,
                    exceeded=False,
                    mode=self._mode,
                    reason="debug_bypass",
                    matched_allowlist=False,
                    hashed_ip=hashed_ip,
                    fingerprint=fingerprint,
                    global_count=self._global_count,
                    ip_count=self._per_ip_count.get(hashed_ip, 0) if hashed_ip else 0,
                    fingerprint_count=(
                        self._per_fingerprint_count.get(fingerprint, 0) if fingerprint else 0
                    ),
                )

            if self._matches_allowlist(
                client_host=client_host,
                hashed_ip=hashed_ip,
                fingerprint=fingerprint,
            ):
                return AbuseGuardDecision(
                    blocked=False,
                    exceeded=False,
                    mode=self._mode,
                    reason="allowlist_bypass",
                    matched_allowlist=True,
                    hashed_ip=hashed_ip,
                    fingerprint=fingerprint,
                    global_count=self._global_count,
                    ip_count=self._per_ip_count.get(hashed_ip, 0) if hashed_ip else 0,
                    fingerprint_count=(
                        self._per_fingerprint_count.get(fingerprint, 0) if fingerprint else 0
                    ),
                )

            self._global_count += 1
            ip_count = 0
            fingerprint_count = 0
            if hashed_ip:
                ip_count = self._per_ip_count.get(hashed_ip, 0) + 1
                self._per_ip_count[hashed_ip] = ip_count
            if fingerprint:
                fingerprint_count = self._per_fingerprint_count.get(fingerprint, 0) + 1
                self._per_fingerprint_count[fingerprint] = fingerprint_count

            exceeded = (
                self._global_count > self._requests_global_per_minute
                or (hashed_ip is not None and ip_count > self._requests_per_ip_per_minute)
                or (
                    fingerprint is not None
                    and fingerprint_count > self._requests_per_fingerprint_per_minute
                )
            )
            blocked = exceeded and self._mode is AbuseGuardMode.ENFORCE
            reason = (
                "threshold_exceeded_enforce"
                if blocked
                else ("threshold_exceeded_observe_only" if exceeded else "allowed")
            )
            return AbuseGuardDecision(
                blocked=blocked,
                exceeded=exceeded,
                mode=self._mode,
                reason=reason,
                matched_allowlist=False,
                hashed_ip=hashed_ip,
                fingerprint=fingerprint,
                global_count=self._global_count,
                ip_count=ip_count,
                fingerprint_count=fingerprint_count,
            )

    def _rotate_window_if_needed(self) -> None:
        current_minute = _current_minute()
        if current_minute == self._window_minute:
            return
        self._window_minute = current_minute
        self._global_count = 0
        self._per_ip_count = {}
        self._per_fingerprint_count = {}

    def _matches_allowlist(
        self,
        *,
        client_host: str | None,
        hashed_ip: str | None,
        fingerprint: str | None,
    ) -> bool:
        if not self._allowlist:
            return False
        candidates = {
            _normalize_token(value)
            for value in (client_host, hashed_ip, fingerprint)
            if value is not None and value.strip()
        }
        return any(item in candidates for item in self._allowlist)


def _current_minute() -> int:
    return int(time.time() // 60)


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().casefold() in _TRUTHY_VALUES


def _normalize_nullable_token(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return _normalize_token(normalized)


def _normalize_token(value: str) -> str:
    return value.strip().casefold()


def _extract_client_host(request: Request, *, trusted_proxy_hops: int = 0) -> str | None:
    """Resolve the caller's address, honouring a trusted proxy chain.

    With `trusted_proxy_hops = N > 0` the client sits at position -(N+1) in
    ``X-Forwarded-For``: each trusted proxy appends the address it received the
    request from, so the last N entries are proxies and the one before them is
    the caller. Entries further left are caller-supplied and must never be
    trusted. Falls back to the socket peer whenever the chain is shorter than
    the configured hop count.
    """
    forwarded_host: str | None = None
    if trusted_proxy_hops > 0:
        raw_chain = request.headers.get("x-forwarded-for", "")
        chain = [item.strip() for item in raw_chain.split(",") if item.strip()]
        if len(chain) >= trusted_proxy_hops + 1:
            forwarded_host = chain[-(trusted_proxy_hops + 1)]
    if forwarded_host:
        return forwarded_host

    client = request.client
    if client is None:
        return None
    host = client.host.strip()
    if not host:
        return None
    return host


def _hash_value(value: str) -> str:
    # Keyed so a stored ip_hash is a pseudonym rather than a reversible
    # encoding of a 2**32 keyspace (docs/data-protection-and-pii.md).
    return keyed_hash(value, purpose="ip_hash")
