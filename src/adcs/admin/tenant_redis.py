"""Tenant-aware Redis key namespacing.

Part of the multi-tenancy implementation. The tenant identity layer,
SQL persistence, and retrieval-side payload partitioning live in
their own modules. This module closes the Bridge-model partitioning by
namespacing Redis keys so a tenant's cache entries, rate-limit counters,
session records, and any other Redis-backed state cannot be accidentally
read or written by another tenant.

The Bridge model (see ``docs/multi-tenancy.md`` §2) keeps Redis shared
between tenants but partitions the key space by prefix:

    tenant:{tenant_id}:{logical_key}

This module is the **only** place that knows the prefix shape. All
Redis-backed code paths construct keys through :class:`TenantRedisKeyspace`
so the prefix cannot drift across the codebase and a typo in one caller
cannot accidentally produce a key that leaks across the tenant boundary.

The wrapper is duck-typed against the small subset of the `redis` API
that the project actually uses (``get``, ``set``, ``delete``, ``exists``,
``scan_iter``, ``incr``, ``expire``). It works with any client that
matches the shape — production ``redis.Redis``, an in-memory fake in
tests, or a Sentinel-backed proxy.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from adcs.admin.tenancy import DEFAULT_TENANT_ID

# Key prefix shape. Single source of truth — every caller goes through
# this module to construct keys. The colon-separated form matches Redis
# conventions and works cleanly with the SCAN MATCH glob.
_KEY_PREFIX_TEMPLATE = "tenant:{tenant_id}:"


class _RedisLike(Protocol):
    """Structural protocol covering the Redis ops this module uses.

    Production wires `redis.Redis`; tests inject a small dict-backed
    fake. The fake is sufficient because the wrapper is purely a
    key-construction + dispatch layer — it does not implement any
    Redis semantics itself.
    """

    def get(self, name: str) -> bytes | None: ...
    def set(self, name: str, value: bytes | str, ex: int | None = ...) -> bool: ...
    def delete(self, *names: str) -> int: ...
    def exists(self, *names: str) -> int: ...
    def scan_iter(
        self, match: str | None = ..., count: int | None = ...
    ) -> Iterator[bytes | str]: ...
    def incr(self, name: str, amount: int = ...) -> int: ...
    def expire(self, name: str, time: int) -> bool: ...


@dataclass
class TenantRedisKeyspace:
    """Wrap a Redis client and prefix every key with the tenant's namespace.

    Two read-only methods (``key``, ``has``) plus the wrapped mutating
    operations (``get``, ``set``, ``delete``, ``incr``, ``expire``,
    ``scan_my_keys``). The wrapper never accepts a fully-qualified key —
    callers pass *logical* (un-prefixed) keys and the wrapper handles
    the prefix.

    The prefix shape is ``tenant:{tenant_id}:`` (no trailing colon
    elision; that ensures ``scan_my_keys`` can disambiguate
    ``tenant:default:`` from ``tenant:default-something:``).
    """

    client: _RedisLike
    tenant_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id:
            msg = "tenant_id must be a non-empty string"
            raise ValueError(msg)
        if ":" in self.tenant_id:
            # The colon is our separator; refusing it in the tenant_id
            # itself protects against prefix-confusion attacks where a
            # caller could construct a tenant_id that overlaps another's
            # key space.
            msg = "tenant_id may not contain ':'"
            raise ValueError(msg)
        self._prefix = _KEY_PREFIX_TEMPLATE.format(tenant_id=self.tenant_id)

    @property
    def prefix(self) -> str:
        """The exact prefix this keyspace produces; useful for assertions."""
        return self._prefix

    def key(self, logical: str) -> str:
        """Construct the fully-qualified Redis key from a logical name.

        Empty logical keys are rejected — they would otherwise resolve
        to the prefix itself, which would collide across all callers.
        """
        if not logical:
            msg = "logical key must be a non-empty string"
            raise ValueError(msg)
        return self._prefix + logical

    # -- Wrapped client operations ---------------------------------------

    def get(self, logical: str) -> bytes | None:
        return self.client.get(self.key(logical))

    def set(
        self, logical: str, value: bytes | str, *, ex: int | None = None
    ) -> bool:
        return self.client.set(self.key(logical), value, ex=ex)

    def delete(self, *logicals: str) -> int:
        if not logicals:
            return 0
        return self.client.delete(*(self.key(name) for name in logicals))

    def exists(self, logical: str) -> bool:
        return bool(self.client.exists(self.key(logical)))

    def incr(self, logical: str, amount: int = 1) -> int:
        return self.client.incr(self.key(logical), amount)

    def expire(self, logical: str, seconds: int) -> bool:
        return self.client.expire(self.key(logical), seconds)

    def scan_my_keys(self, *, suffix_pattern: str = "*") -> Iterator[str]:
        """Yield this tenant's keys, stripped of the namespace prefix.

        Use the underlying client's SCAN MATCH with the tenant prefix
        glued onto the requested suffix pattern. Each yielded value is
        the logical key (caller-side) — the prefix is hidden so callers
        cannot accidentally treat the namespace as authoritative.
        """
        match = self._prefix + suffix_pattern
        for raw in self.client.scan_iter(match=match):
            value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if value.startswith(self._prefix):
                yield value[len(self._prefix) :]


def is_key_in_tenant_namespace(
    *, key: str, tenant_id: str = DEFAULT_TENANT_ID
) -> bool:
    """Return True iff ``key`` belongs to ``tenant_id``'s namespace.

    Centralised so test assertions and any future cross-tenant audit
    code share the rule. The check is strict-prefix matching against
    the canonical template — there is no fuzzy form.
    """
    prefix = _KEY_PREFIX_TEMPLATE.format(tenant_id=tenant_id)
    return key.startswith(prefix)
