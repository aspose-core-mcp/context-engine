"""Tests for the tenant-aware Redis namespacing.

The tests use a small in-memory fake Redis client that implements the
subset of the API the wrapper needs (get/set/delete/exists/scan_iter/
incr/expire). The fake's only job is to expose the actual stored keys
so assertions can verify prefix construction and tenant isolation.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from adcs.admin.tenancy import DEFAULT_TENANT_ID
from adcs.admin.tenant_redis import (
    TenantRedisKeyspace,
    is_key_in_tenant_namespace,
)


class _FakeRedis:
    """In-memory Redis stand-in implementing the wrapper's read surface."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}

    # ---- redis-compatible methods ------------------------------------

    def get(self, name: str) -> bytes | None:
        return self.store.get(name)

    def set(
        self, name: str, value: bytes | str, ex: int | None = None
    ) -> bool:
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.store[name] = value
        if ex is not None:
            self.expirations[name] = ex
        return True

    def delete(self, *names: str) -> int:
        deleted = 0
        for n in names:
            if n in self.store:
                del self.store[n]
                deleted += 1
        return deleted

    def exists(self, *names: str) -> int:
        return sum(1 for n in names if n in self.store)

    def scan_iter(
        self, match: str | None = None, count: int | None = None
    ) -> Iterator[str]:
        prefix = (match or "*").rstrip("*")
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k

    def incr(self, name: str, amount: int = 1) -> int:
        current = int(self.store.get(name, b"0") or 0)
        new = current + amount
        self.store[name] = str(new).encode("utf-8")
        return new

    def expire(self, name: str, time: int) -> bool:
        if name not in self.store:
            return False
        self.expirations[name] = time
        return True


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_construction_rejects_empty_tenant_id() -> None:
    fake = _FakeRedis()
    with pytest.raises(ValueError, match="non-empty"):
        TenantRedisKeyspace(client=fake, tenant_id="")


def test_construction_rejects_colon_in_tenant_id() -> None:
    """Colons in tenant_id would break the prefix separator contract."""
    fake = _FakeRedis()
    with pytest.raises(ValueError, match="may not contain"):
        TenantRedisKeyspace(client=fake, tenant_id="t-acme:hacked")


def test_prefix_exposed_for_assertions() -> None:
    ks = TenantRedisKeyspace(client=_FakeRedis(), tenant_id="t-acme")
    assert ks.prefix == "tenant:t-acme:"


def test_key_rejects_empty_logical() -> None:
    ks = TenantRedisKeyspace(client=_FakeRedis(), tenant_id="t-acme")
    with pytest.raises(ValueError, match="non-empty"):
        ks.key("")


def test_key_constructs_canonical_form() -> None:
    ks = TenantRedisKeyspace(client=_FakeRedis(), tenant_id="t-acme")
    assert ks.key("admin:session:abc") == "tenant:t-acme:admin:session:abc"


# ---------------------------------------------------------------------------
# Wrapped operations
# ---------------------------------------------------------------------------


def test_set_and_get_round_trip() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    ks.set("rate-limit:abc", "1")
    assert ks.get("rate-limit:abc") == b"1"
    # The underlying store has the fully-qualified key, not the logical one
    assert "tenant:t-acme:rate-limit:abc" in fake.store
    assert "rate-limit:abc" not in fake.store


def test_delete_returns_count_of_deleted_keys() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    ks.set("k1", "v1")
    ks.set("k2", "v2")
    assert ks.delete("k1", "k2", "k3-missing") == 2


def test_delete_with_no_arguments_returns_zero_without_calling_client() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    ks.set("k1", "v1")
    assert ks.delete() == 0
    # The pre-existing key is untouched
    assert fake.store["tenant:t-acme:k1"] == b"v1"


def test_exists_returns_boolean() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    assert ks.exists("k1") is False
    ks.set("k1", "v1")
    assert ks.exists("k1") is True


def test_incr_increments_namespaced_counter() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    assert ks.incr("counter") == 1
    assert ks.incr("counter") == 2
    assert ks.incr("counter", 10) == 12
    # Other tenants see their own counter
    other = TenantRedisKeyspace(client=fake, tenant_id="t-beta")
    assert other.incr("counter") == 1


def test_expire_sets_ttl_on_namespaced_key() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    ks.set("session", "x")
    assert ks.expire("session", 60) is True
    assert fake.expirations["tenant:t-acme:session"] == 60


def test_expire_returns_false_for_missing_key() -> None:
    fake = _FakeRedis()
    ks = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    assert ks.expire("never-existed", 60) is False


# ---------------------------------------------------------------------------
# Tenant isolation — the safety claim
# ---------------------------------------------------------------------------


def test_named_tenant_cannot_read_another_tenants_key() -> None:
    fake = _FakeRedis()
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    beta = TenantRedisKeyspace(client=fake, tenant_id="t-beta")
    acme.set("secret", "acme-only")
    assert beta.get("secret") is None
    assert acme.get("secret") == b"acme-only"


def test_default_tenant_cannot_read_named_tenant_key() -> None:
    """Default is NOT a wildcard — mirrors the identity-layer rule."""
    fake = _FakeRedis()
    default = TenantRedisKeyspace(client=fake, tenant_id="default")
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    acme.set("k", "acme-data")
    assert default.get("k") is None


def test_named_tenant_cannot_read_default_tenant_key() -> None:
    fake = _FakeRedis()
    default = TenantRedisKeyspace(client=fake, tenant_id="default")
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    default.set("k", "default-data")
    assert acme.get("k") is None


def test_delete_only_affects_own_tenant_namespace() -> None:
    fake = _FakeRedis()
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    beta = TenantRedisKeyspace(client=fake, tenant_id="t-beta")
    acme.set("shared-name", "acme-value")
    beta.set("shared-name", "beta-value")
    acme.delete("shared-name")
    assert acme.get("shared-name") is None
    # Beta's key with the SAME logical name is untouched
    assert beta.get("shared-name") == b"beta-value"


# ---------------------------------------------------------------------------
# scan_my_keys
# ---------------------------------------------------------------------------


def test_scan_my_keys_returns_only_logical_keys_for_this_tenant() -> None:
    fake = _FakeRedis()
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    beta = TenantRedisKeyspace(client=fake, tenant_id="t-beta")
    acme.set("session:1", "x")
    acme.set("session:2", "y")
    beta.set("session:3", "z")
    # Scan acme: must NOT yield beta's keys
    keys = sorted(acme.scan_my_keys())
    assert keys == ["session:1", "session:2"]


def test_scan_my_keys_yields_stripped_logical_keys() -> None:
    fake = _FakeRedis()
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    acme.set("session:1", "x")
    yielded = next(acme.scan_my_keys())
    assert yielded == "session:1"


def test_scan_my_keys_supports_suffix_pattern() -> None:
    fake = _FakeRedis()
    acme = TenantRedisKeyspace(client=fake, tenant_id="t-acme")
    acme.set("session:1", "x")
    acme.set("session:2", "y")
    acme.set("rate-limit:1", "z")
    sessions = sorted(acme.scan_my_keys(suffix_pattern="session:*"))
    assert sessions == ["session:1", "session:2"]


# ---------------------------------------------------------------------------
# is_key_in_tenant_namespace helper
# ---------------------------------------------------------------------------


def test_is_key_in_tenant_namespace_matches_canonical_prefix() -> None:
    assert is_key_in_tenant_namespace(
        key="tenant:t-acme:session:1", tenant_id="t-acme"
    )


def test_is_key_in_tenant_namespace_rejects_wrong_tenant() -> None:
    assert not is_key_in_tenant_namespace(
        key="tenant:t-beta:session:1", tenant_id="t-acme"
    )


def test_is_key_in_tenant_namespace_rejects_unprefixed_key() -> None:
    assert not is_key_in_tenant_namespace(
        key="session:1", tenant_id="t-acme"
    )


def test_is_key_in_tenant_namespace_default_tenant_default_id() -> None:
    """Default-id form is convenience for the implicit-single-tenant case."""
    assert is_key_in_tenant_namespace(key=f"tenant:{DEFAULT_TENANT_ID}:s:1")
    assert not is_key_in_tenant_namespace(key="tenant:t-acme:s:1")
