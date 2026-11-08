"""Per-tenant observability metrics.

Part of the multi-tenancy implementation. The existing
:class:`adcs.api.metrics.InMemoryMetrics` aggregates request counters
and latency totals across the entire deployment. With multi-tenant
operation we need the same observability surface broken down by
``tenant_id`` so per-tenant SLOs, billing telemetry, and tenant-scoped
alerting are possible.

This module is the **tenant-scoped breakdown**. It runs alongside the
existing global metrics (does not replace them) — the global ones
remain useful as deployment-wide health signals; the per-tenant ones
answer the "is *this* customer's traffic healthy?" question.

The wrapper is intentionally narrow: it tracks the same shape of
observation (method × path × status × latency) but keyed by
``(tenant_id, ...)`` so a snapshot can return the per-tenant
breakdown in one call. Cross-tenant counters never mix — the SLO
math for tenant A is computed against tenant A's series alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

from adcs.admin.tenancy import DEFAULT_TENANT_ID


@dataclass(frozen=True, slots=True)
class TenantRequestRow:
    """One row in the per-tenant request breakdown."""

    tenant_id: str
    method: str
    path: str
    status_code: int
    count: int


@dataclass(frozen=True, slots=True)
class TenantLatencyRow:
    """One row in the per-tenant latency breakdown (mean only).

    ``mean_seconds`` is ``sum_seconds / count`` and is ``0.0`` when
    ``count == 0``. Higher percentiles (p95, p99) are out of scope for
    this layer; emit them via a separate histogram backend (e.g.,
    Prometheus client) when ingestion of the breakdown is wired up.
    """

    tenant_id: str
    method: str
    path: str
    count: int
    sum_seconds: float
    mean_seconds: float


@dataclass
class _TenantState:
    """Per-tenant in-memory state (private — built by PerTenantMetrics)."""

    request_count: dict[tuple[str, str, int], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    latency_sum_seconds: dict[tuple[str, str], float] = field(
        default_factory=lambda: defaultdict(float)
    )
    latency_count: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int)
    )


class PerTenantMetrics:
    """Tenant-keyed request + latency counters.

    Thread-safe. ``observe_request`` is the single mutation entry;
    ``snapshot`` and ``known_tenants`` are read-only.

    The class is *not* a drop-in replacement for
    :class:`adcs.api.metrics.InMemoryMetrics` — it complements it.
    Production code calls *both* in the request middleware: the
    global one for deployment-wide signals, this one for per-tenant
    breakdowns.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._tenants: dict[str, _TenantState] = {}

    def observe_request(
        self,
        *,
        tenant_id: str,
        method: str,
        path: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        """Record one request observation for the given tenant.

        Empty / blank tenant_id collapses to ``DEFAULT_TENANT_ID``
        (matches the implicit single-tenant convention of the identity layer).
        Negative latency is clamped to 0 — observations must be
        non-negative.
        """
        normalised_tenant = (tenant_id or "").strip() or DEFAULT_TENANT_ID
        clamped_latency = max(0.0, float(latency_seconds))
        counter_key = (method, path, int(status_code))
        latency_key = (method, path)
        with self._lock:
            state = self._tenants.setdefault(normalised_tenant, _TenantState())
            state.request_count[counter_key] += 1
            state.latency_sum_seconds[latency_key] += clamped_latency
            state.latency_count[latency_key] += 1

    def known_tenants(self) -> tuple[str, ...]:
        """Return the tenant_ids that have at least one observation."""
        with self._lock:
            return tuple(sorted(self._tenants.keys()))

    def snapshot_requests(
        self, *, tenant_id: str | None = None
    ) -> tuple[TenantRequestRow, ...]:
        """Return the request-count rows for one tenant (or every tenant)."""
        with self._lock:
            if tenant_id is not None:
                state = self._tenants.get(tenant_id)
                if state is None:
                    return ()
                return tuple(
                    _to_request_row(tenant_id, key, count)
                    for key, count in sorted(state.request_count.items())
                )
            rows: list[TenantRequestRow] = []
            for tid in sorted(self._tenants):
                state = self._tenants[tid]
                for key, count in sorted(state.request_count.items()):
                    rows.append(_to_request_row(tid, key, count))
            return tuple(rows)

    def snapshot_latency(
        self, *, tenant_id: str | None = None
    ) -> tuple[TenantLatencyRow, ...]:
        """Return the latency rows for one tenant (or every tenant)."""
        with self._lock:
            if tenant_id is not None:
                state = self._tenants.get(tenant_id)
                if state is None:
                    return ()
                return _state_to_latency_rows(tenant_id, state)
            rows: list[TenantLatencyRow] = []
            for tid in sorted(self._tenants):
                rows.extend(_state_to_latency_rows(tid, self._tenants[tid]))
            return tuple(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_request_row(
    tenant_id: str, key: tuple[str, str, int], count: int
) -> TenantRequestRow:
    method, path, status_code = key
    return TenantRequestRow(
        tenant_id=tenant_id,
        method=method,
        path=path,
        status_code=status_code,
        count=count,
    )


def _state_to_latency_rows(
    tenant_id: str, state: _TenantState
) -> tuple[TenantLatencyRow, ...]:
    rows: list[TenantLatencyRow] = []
    for key in sorted(state.latency_count.keys()):
        method, path = key
        count = state.latency_count[key]
        sum_seconds = state.latency_sum_seconds[key]
        mean = sum_seconds / count if count > 0 else 0.0
        rows.append(
            TenantLatencyRow(
                tenant_id=tenant_id,
                method=method,
                path=path,
                count=count,
                sum_seconds=sum_seconds,
                mean_seconds=round(mean, 6),
            )
        )
    return tuple(rows)
