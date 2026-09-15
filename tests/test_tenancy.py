"""Tests for the multi-tenancy identity layer.

Covers the data model and identity surface. SQL persistence and the
routing layer are tested separately.
"""

from __future__ import annotations

import pytest

from adcs.admin.tenancy import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_SLUG,
    Tenant,
    TenantRegistry,
    is_tenant_scope_authorised,
)


def test_default_tenant_registered_on_empty_registry() -> None:
    """A freshly-constructed registry always has the default tenant."""
    registry = TenantRegistry()
    default = registry.get_by_id(DEFAULT_TENANT_ID)
    assert default is not None
    assert default.slug == DEFAULT_TENANT_SLUG
    assert default.enabled is True
    assert registry.has(DEFAULT_TENANT_ID)


def test_register_adds_a_tenant_and_makes_it_lookup_able() -> None:
    registry = TenantRegistry()
    acme = Tenant(
        tenant_id="t-acme-1234",
        slug="acme-corp",
        display_name="ACME Corporation",
    )
    registry.register(acme)
    assert registry.get_by_id("t-acme-1234") == acme
    assert registry.get_by_slug("acme-corp") == acme
    assert acme in registry.all()


def test_register_rejects_duplicate_id() -> None:
    registry = TenantRegistry()
    t1 = Tenant(tenant_id="t-acme", slug="acme-one", display_name="ACME One")
    t2 = Tenant(tenant_id="t-acme", slug="acme-two", display_name="ACME Two")
    registry.register(t1)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(t2)


def test_register_rejects_duplicate_slug() -> None:
    registry = TenantRegistry()
    t1 = Tenant(tenant_id="t-1", slug="acme", display_name="ACME 1")
    t2 = Tenant(tenant_id="t-2", slug="acme", display_name="ACME 2")
    registry.register(t1)
    with pytest.raises(ValueError, match="already in use"):
        registry.register(t2)


@pytest.mark.parametrize(
    "bad_slug",
    [
        "",                 # empty
        "a",                # too short
        "1acme",            # starts with digit
        "ACME",             # uppercase
        "ac me",            # space
        "ac_me",            # underscore
        "a" * 41,           # too long
    ],
)
def test_register_rejects_invalid_slug(bad_slug: str) -> None:
    registry = TenantRegistry()
    bad = Tenant(tenant_id=f"t-{bad_slug}", slug=bad_slug, display_name="x")
    with pytest.raises(ValueError, match="invalid tenant slug"):
        registry.register(bad)


def test_unknown_tenant_lookup_returns_none() -> None:
    registry = TenantRegistry()
    assert registry.get_by_id("t-missing") is None
    assert registry.get_by_slug("missing") is None
    assert registry.has("t-missing") is False


def test_all_returns_default_plus_registered() -> None:
    registry = TenantRegistry()
    registry.register(
        Tenant(tenant_id="t-1", slug="acme-1", display_name="A1"),
    )
    registry.register(
        Tenant(tenant_id="t-2", slug="acme-2", display_name="A2"),
    )
    ids = {t.tenant_id for t in registry.all()}
    assert ids == {DEFAULT_TENANT_ID, "t-1", "t-2"}


# ---------------------------------------------------------------------------
# Scope authorisation
# ---------------------------------------------------------------------------


def test_same_tenant_access_is_authorised() -> None:
    assert is_tenant_scope_authorised(
        principal_tenant_id="t-acme",
        target_tenant_id="t-acme",
    )


def test_cross_named_tenant_access_is_denied() -> None:
    """Two distinct named tenants cannot access each other's records."""
    assert not is_tenant_scope_authorised(
        principal_tenant_id="t-acme",
        target_tenant_id="t-beta",
    )


def test_default_tenant_does_not_grant_cross_tenant_access() -> None:
    """The default tenant is implicit-single-tenant, NOT a wildcard."""
    assert not is_tenant_scope_authorised(
        principal_tenant_id=DEFAULT_TENANT_ID,
        target_tenant_id="t-acme",
    )
    assert not is_tenant_scope_authorised(
        principal_tenant_id="t-acme",
        target_tenant_id=DEFAULT_TENANT_ID,
    )


def test_default_to_default_access_is_authorised() -> None:
    """Default → default is the legacy single-tenant path."""
    assert is_tenant_scope_authorised(
        principal_tenant_id=DEFAULT_TENANT_ID,
        target_tenant_id=DEFAULT_TENANT_ID,
    )
