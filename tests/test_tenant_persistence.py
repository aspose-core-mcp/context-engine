"""Tests for the tenant SQL persistence layer.

Two implementations share the :class:`TenantRepository` contract:
:class:`InMemoryTenantRepository` and :class:`SqlTenantRepository`. The
tests run against both so the contract surface is enforced uniformly
and the in-memory implementation cannot drift from the SQL one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from adcs.admin.tenancy import DEFAULT_TENANT_ID, DEFAULT_TENANT_SLUG
from adcs.admin.tenant_persistence import (
    InMemoryTenantRepository,
    SqlTenantRepository,
    TenantAlreadyExistsError,
)


@pytest.fixture(params=["in_memory", "sqlite"])
def repo(request: pytest.FixtureRequest):
    """Run every test against both repository implementations."""
    if request.param == "in_memory":
        return InMemoryTenantRepository()
    engine = create_engine("sqlite:///:memory:")
    return SqlTenantRepository(engine_or_dsn=engine)


# ---------------------------------------------------------------------------
# Default tenant auto-seed
# ---------------------------------------------------------------------------


def test_default_tenant_seeded_on_first_bootstrap(repo) -> None:
    """The default tenant exists after a fresh bootstrap (both implementations)."""
    default = repo.get_by_id(DEFAULT_TENANT_ID)
    assert default is not None
    assert default.slug == DEFAULT_TENANT_SLUG
    assert default.enabled is True
    assert default.created_at == default.updated_at


def test_default_tenant_seed_is_idempotent() -> None:
    """Re-instantiating the SQL repo against the same engine does not duplicate."""
    engine = create_engine("sqlite:///:memory:")
    repo1 = SqlTenantRepository(engine_or_dsn=engine)
    repo2 = SqlTenantRepository(engine_or_dsn=engine)
    assert (
        len(repo1.list(include_disabled=True))
        == len(repo2.list(include_disabled=True))
        == 1
    )


# ---------------------------------------------------------------------------
# Create / lookup happy paths
# ---------------------------------------------------------------------------


def test_create_and_lookup_round_trip(repo) -> None:
    created = repo.create(
        tenant_id="t-acme-1",
        slug="acme",
        display_name="ACME Corporation",
        notes="Pilot customer",
    )
    assert created.tenant_id == "t-acme-1"
    assert created.enabled is True
    by_id = repo.get_by_id("t-acme-1")
    assert by_id == created
    by_slug = repo.get_by_slug("acme")
    assert by_slug == created


def test_create_returns_tenant_with_audit_timestamps(repo) -> None:
    created = repo.create(
        tenant_id="t-foo", slug="foo", display_name="Foo Inc"
    )
    assert created.created_at == created.updated_at
    assert created.created_at.tzinfo is not None


def test_list_includes_default_and_created(repo) -> None:
    repo.create(tenant_id="t-1", slug="acme-1", display_name="A1")
    repo.create(tenant_id="t-2", slug="acme-2", display_name="A2")
    ids = [r.tenant_id for r in repo.list()]
    assert ids[0] == DEFAULT_TENANT_ID
    assert set(ids) == {DEFAULT_TENANT_ID, "t-1", "t-2"}


def test_list_ordering_is_stable_by_created_at(repo) -> None:
    """list() returns records oldest-first; default is always first."""
    repo.create(tenant_id="t-z-late", slug="z-late", display_name="Z")
    repo.create(tenant_id="t-a-later", slug="a-later", display_name="A")
    records = repo.list()
    # Default tenant was seeded first → must appear first
    assert records[0].tenant_id == DEFAULT_TENANT_ID
    # Subsequent records are in insertion order, not alphabetic
    assert [r.tenant_id for r in records[1:]] == ["t-z-late", "t-a-later"]


# ---------------------------------------------------------------------------
# Conflict / not-found
# ---------------------------------------------------------------------------


def test_create_rejects_duplicate_tenant_id(repo) -> None:
    repo.create(tenant_id="t-dup", slug="acme-one", display_name="A1")
    with pytest.raises(TenantAlreadyExistsError, match="already exists"):
        repo.create(tenant_id="t-dup", slug="acme-two", display_name="A2")


def test_create_rejects_duplicate_slug(repo) -> None:
    repo.create(tenant_id="t-1", slug="shared", display_name="A1")
    with pytest.raises(TenantAlreadyExistsError, match="already in use"):
        repo.create(tenant_id="t-2", slug="shared", display_name="A2")


def test_create_rejects_collision_with_default_tenant(repo) -> None:
    with pytest.raises(TenantAlreadyExistsError):
        repo.create(
            tenant_id=DEFAULT_TENANT_ID,
            slug="something-else",
            display_name="should fail",
        )
    with pytest.raises(TenantAlreadyExistsError):
        repo.create(
            tenant_id="t-something",
            slug=DEFAULT_TENANT_SLUG,
            display_name="should fail",
        )


def test_unknown_lookup_returns_none(repo) -> None:
    assert repo.get_by_id("t-not-there") is None
    assert repo.get_by_slug("not-there") is None


# ---------------------------------------------------------------------------
# Disable / enable lifecycle
# ---------------------------------------------------------------------------


def test_disable_marks_tenant_inactive(repo) -> None:
    repo.create(tenant_id="t-disable", slug="disable-me", display_name="X")
    disabled = repo.disable("t-disable")
    assert disabled is not None
    assert disabled.enabled is False
    assert disabled.updated_at >= disabled.created_at


def test_enable_reactivates_disabled_tenant(repo) -> None:
    repo.create(tenant_id="t-re", slug="re-enable", display_name="X")
    repo.disable("t-re")
    re_enabled = repo.enable("t-re")
    assert re_enabled is not None
    assert re_enabled.enabled is True


def test_list_filters_disabled_when_requested(repo) -> None:
    repo.create(tenant_id="t-active", slug="active", display_name="Active")
    repo.create(tenant_id="t-disabled", slug="disabled", display_name="Disabled")
    repo.disable("t-disabled")
    all_records = repo.list(include_disabled=True)
    active_only = repo.list(include_disabled=False)
    all_ids = {r.tenant_id for r in all_records}
    active_ids = {r.tenant_id for r in active_only}
    assert "t-disabled" in all_ids
    assert "t-disabled" not in active_ids
    assert "t-active" in active_ids


def test_disable_unknown_tenant_returns_none(repo) -> None:
    assert repo.disable("t-never-existed") is None
    assert repo.enable("t-never-existed") is None


# ---------------------------------------------------------------------------
# Round-trip through the runtime Tenant view
# ---------------------------------------------------------------------------


def test_record_converts_to_runtime_tenant(repo) -> None:
    created = repo.create(
        tenant_id="t-rt",
        slug="rt-corp",
        display_name="RT Corporation",
        notes="Round-trip test",
    )
    tenant = created.to_tenant()
    assert tenant.tenant_id == "t-rt"
    assert tenant.slug == "rt-corp"
    assert tenant.display_name == "RT Corporation"
    assert tenant.enabled is True
    assert tenant.notes == "Round-trip test"
