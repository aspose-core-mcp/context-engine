"""Tenant-aware lane-adapter wrapper.

Part of the multi-tenancy implementation. The identity layer
(:mod:`adcs.admin.tenancy`) defines the ``Tenant`` boundary; the SQL
persistence layer (:mod:`adcs.admin.tenant_persistence`) makes it durable.
This module adds the retrieval-side *enforcement*: a wrapper that decorates any
:class:`DenseLaneAdapter` or :class:`LexicalLaneAdapter` and filters
returned candidates by their ``tenant_id`` payload field.

Two enforcement modes:

* **post-filter** — for in-memory and SQLite-backed test adapters and
  for any production adapter that does not natively support payload
  filters. The inner adapter runs unchanged and the wrapper drops
  candidates whose tenant_id does not match the configured principal
  tenant. Used by tests and dev profiles.

* **pre-filter** (future) — for production Qdrant where the wrapper
  injects ``Filter(must=[FieldCondition(key="tenant_id",
  match=MatchValue(value=...))])`` into the search call. Significantly
  cheaper than post-filter because it never reads non-tenant points
  off disk. The Protocol is shaped so this implementation can be added
  without breaking the contract that callers see.

The wrapper's tenant-scope rule mirrors
:func:`adcs.admin.tenancy.is_tenant_scope_authorised`:

* a principal scoped to tenant ``X`` sees only candidates whose
  ``tenant_id == X``;
* the implicit single-tenant deployment (default tenant principal)
  sees only candidates whose ``tenant_id == "default"`` — the default
  tenant is NOT a wildcard.

This guarantees logical isolation even if upstream ingestion ever
misroutes a chunk: the wrapper drops it before the candidate reaches
the reranker, context packer, or the public response surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from adcs.admin.tenancy import DEFAULT_TENANT_ID
from adcs.retrieval.models import QueryPlan
from adcs.retrieval.retrieval_models import LaneCandidate


class _LaneAdapter(Protocol):
    """The structural surface every lane adapter exposes."""

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        """Search and return the top-N candidates."""


@dataclass
class TenantAwareLaneAdapter:
    """Wrap any lane adapter; drop candidates that do not match the tenant.

    The wrapper is intentionally *additive* — it does not modify the
    inner adapter, so any production adapter (in-memory, SQLite-backed,
    remote Qdrant) can be wrapped without changes. The cost is that
    enforcement is post-filter; the inner adapter still reads the full
    candidate set off disk. For Qdrant a pre-filter implementation will
    inject the payload filter into the search call directly.

    The ``over_fetch_factor`` argument compensates for the drop:
    callers ask for ``limit`` candidates, the wrapper requests
    ``limit * over_fetch_factor`` from the inner adapter, post-filters,
    and trims the result to ``limit``. The factor is configurable so
    deployments with very heavy cross-tenant contention can dial it up.
    """

    inner: _LaneAdapter
    tenant_id: str
    over_fetch_factor: int = 3

    def __post_init__(self) -> None:
        if self.over_fetch_factor < 1:
            msg = "over_fetch_factor must be >= 1"
            raise ValueError(msg)
        if not self.tenant_id:
            msg = "tenant_id must be a non-empty string"
            raise ValueError(msg)

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        """Run the inner adapter and post-filter by tenant.

        Empty / zero / negative ``limit`` short-circuits to an empty
        result without calling the inner adapter — the contract is the
        same as the inner lanes.
        """
        if limit < 1:
            return ()
        inner_limit = limit * self.over_fetch_factor
        candidates = self.inner.search(plan=plan, limit=inner_limit)
        filtered = _filter_by_tenant(
            candidates=candidates, tenant_id=self.tenant_id
        )
        return tuple(filtered[:limit])


def _filter_by_tenant(
    *, candidates: Sequence[LaneCandidate], tenant_id: str
) -> tuple[LaneCandidate, ...]:
    """Keep only candidates whose metadata.tenant_id matches.

    Candidates without an explicit tenant_id (legacy ingestion) carry
    ``tenant_id == "default"`` because that is the dataclass default;
    they are visible only to the default tenant. Any other named
    tenant cannot see them — preventing accidental data leakage during
    the migration window.
    """
    return tuple(c for c in candidates if c.metadata.tenant_id == tenant_id)


def matches_tenant_scope(
    *, candidate: LaneCandidate, principal_tenant_id: str
) -> bool:
    """Return True iff the principal may see the candidate.

    Centralised so both the wrapper and any future ad-hoc filtering
    code share the rule. Same semantics as
    :func:`adcs.admin.tenancy.is_tenant_scope_authorised`.
    """
    candidate_tenant = candidate.metadata.tenant_id
    if candidate_tenant == principal_tenant_id:
        return True
    return (
        candidate_tenant == DEFAULT_TENANT_ID
        and principal_tenant_id == DEFAULT_TENANT_ID
    )
