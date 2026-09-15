"""Multi-tenancy identity layer.

ADCS runs as a single-tenant deployment by default. The multi-tenancy
design (see ``docs/multi-tenancy.md``) uses a Bridge model: shared
compute + shared infrastructure, partitioned by ``tenant_id`` at the
identity, data, and audit layers.

This module is the **identity-layer scaffold** for that work. It
introduces a typed :class:`Tenant` record, a :class:`TenantRegistry`
that resolves tenants by id / slug, and a constant :data:`DEFAULT_TENANT`
so existing single-tenant deployments continue to work unchanged — every
existing admin key, every existing audit row, every existing query
implicitly belongs to the ``default`` tenant.

Downstream surfaces (admin principal, audit log, retrieval routing)
will read tenant_id from this layer rather than embed the literal
string. That way a multi-tenant rollout becomes a
data migration (assign tenant_ids to existing keys / audit rows) plus
a routing change — the identity contract itself is already in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

# Reserved identifier for the implicit single-tenant deployment. Every
# existing record (admin key, audit row, query analytic) is treated as
# belonging to this tenant until the explicit multi-tenant migration
# assigns concrete tenant_ids.
DEFAULT_TENANT_ID: Final[str] = "default"
DEFAULT_TENANT_SLUG: Final[str] = "default"

# Tenant slug rules — alphanumeric + hyphen, 2..40 chars, must start with
# a letter (the leading-digit constraint avoids slug collisions with id
# prefixes the admin UI uses as table-row keys).
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


@dataclass(frozen=True, slots=True)
class Tenant:
    """One tenancy boundary.

    A tenant is an organizational unit (typically one customer company)
    that owns its keys, audit log, query analytics, and config history.
    """

    tenant_id: str
    slug: str
    display_name: str
    enabled: bool = True
    notes: str = ""


_DEFAULT_TENANT = Tenant(
    tenant_id=DEFAULT_TENANT_ID,
    slug=DEFAULT_TENANT_SLUG,
    display_name="Default tenant",
    enabled=True,
    notes=(
        "Implicit single-tenant scope. Every record without an explicit "
        "tenant_id is owned by this tenant; the multi-tenant migration "
        "assigns concrete tenant_ids to existing rows."
    ),
)


@dataclass
class TenantRegistry:
    """In-memory registry of known tenants.

    The default tenant is always registered. Production deployments
    that need multi-tenant operation register additional tenants via
    :meth:`register`. Lookups are by ``tenant_id`` (primary key) or by
    ``slug`` (URL / admin UI handle).

    This is the read surface the rest of the codebase consumes; the
    write surface (CRUD endpoints for tenants) is part of the larger
    multi-tenancy implementation and is intentionally out of scope for
    this module.
    """

    _by_id: dict[str, Tenant] = field(default_factory=dict)
    _by_slug: dict[str, Tenant] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if DEFAULT_TENANT_ID not in self._by_id:
            self.register(_DEFAULT_TENANT)

    def register(self, tenant: Tenant) -> None:
        """Add a tenant. Raises ValueError on duplicate id/slug or invalid slug."""
        if not _SLUG_RE.fullmatch(tenant.slug):
            msg = (
                f"invalid tenant slug {tenant.slug!r}: must match "
                f"{_SLUG_RE.pattern}"
            )
            raise ValueError(msg)
        if tenant.tenant_id in self._by_id:
            msg = f"tenant_id {tenant.tenant_id!r} already registered"
            raise ValueError(msg)
        if tenant.slug in self._by_slug:
            msg = f"tenant slug {tenant.slug!r} already in use"
            raise ValueError(msg)
        self._by_id[tenant.tenant_id] = tenant
        self._by_slug[tenant.slug] = tenant

    def get_by_id(self, tenant_id: str) -> Tenant | None:
        return self._by_id.get(tenant_id)

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self._by_slug.get(slug)

    def all(self) -> tuple[Tenant, ...]:
        return tuple(self._by_id.values())

    def has(self, tenant_id: str) -> bool:
        return tenant_id in self._by_id


def is_tenant_scope_authorised(
    *, principal_tenant_id: str, target_tenant_id: str
) -> bool:
    """Return True iff a principal scoped to one tenant may operate on another.

    The rule is strict-equality, with one exception: the default tenant
    represents the implicit single-tenant deployment and is allowed to
    operate on records that have not yet been migrated to a concrete
    tenant_id. Any cross-tenant access between two named tenants is
    denied.
    """
    if principal_tenant_id == target_tenant_id:
        return True
    if (
        principal_tenant_id == DEFAULT_TENANT_ID
        and target_tenant_id == DEFAULT_TENANT_ID
    ):
        return True
    return False
