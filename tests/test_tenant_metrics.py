"""Tests for the per-tenant metrics breakdown.

Asserts that the wrapper:
* records each tenant's observations independently;
* exposes a snapshot per tenant + the union snapshot across all;
* normalises blank tenant_id to the default;
* clamps negative latency to zero;
* cross-tenant counters never mix (the safety claim).
"""

from __future__ import annotations

from adcs.admin.tenancy import DEFAULT_TENANT_ID
from adcs.admin.tenant_metrics import (
    PerTenantMetrics,
    TenantLatencyRow,
    TenantRequestRow,
)

# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_fresh_metrics_has_no_tenants() -> None:
    metrics = PerTenantMetrics()
    assert metrics.known_tenants() == ()
    assert metrics.snapshot_requests() == ()
    assert metrics.snapshot_latency() == ()


def test_unknown_tenant_snapshot_returns_empty() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-acme",
        method="GET",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.1,
    )
    assert metrics.snapshot_requests(tenant_id="t-missing") == ()
    assert metrics.snapshot_latency(tenant_id="t-missing") == ()


# ---------------------------------------------------------------------------
# Tenant isolation (the safety claim)
# ---------------------------------------------------------------------------


def test_named_tenants_have_independent_counters() -> None:
    metrics = PerTenantMetrics()
    for _ in range(3):
        metrics.observe_request(
            tenant_id="t-acme",
            method="GET",
            path="/v1/query_docs",
            status_code=200,
            latency_seconds=0.1,
        )
    metrics.observe_request(
        tenant_id="t-beta",
        method="GET",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.1,
    )
    acme_rows = metrics.snapshot_requests(tenant_id="t-acme")
    beta_rows = metrics.snapshot_requests(tenant_id="t-beta")
    assert acme_rows[0].count == 3
    assert beta_rows[0].count == 1


def test_known_tenants_reflects_all_observed() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-zeta",
        method="GET",
        path="/x",
        status_code=200,
        latency_seconds=0.1,
    )
    metrics.observe_request(
        tenant_id="t-alpha",
        method="GET",
        path="/x",
        status_code=200,
        latency_seconds=0.1,
    )
    # Sorted ascending
    assert metrics.known_tenants() == ("t-alpha", "t-zeta")


def test_union_snapshot_groups_by_tenant_then_key() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-acme",
        method="GET",
        path="/a",
        status_code=200,
        latency_seconds=0.1,
    )
    metrics.observe_request(
        tenant_id="t-beta",
        method="GET",
        path="/b",
        status_code=500,
        latency_seconds=0.5,
    )
    rows = metrics.snapshot_requests()
    assert [r.tenant_id for r in rows] == ["t-acme", "t-beta"]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_blank_tenant_id_normalised_to_default() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="",
        method="GET",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.1,
    )
    metrics.observe_request(
        tenant_id="   ",
        method="GET",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.1,
    )
    assert metrics.known_tenants() == (DEFAULT_TENANT_ID,)
    rows = metrics.snapshot_requests(tenant_id=DEFAULT_TENANT_ID)
    assert rows[0].count == 2


def test_negative_latency_clamped_to_zero() -> None:
    """Defensive clamp — negative latency makes no physical sense."""
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-acme",
        method="GET",
        path="/x",
        status_code=200,
        latency_seconds=-1.0,
    )
    latency = metrics.snapshot_latency(tenant_id="t-acme")[0]
    assert latency.sum_seconds == 0.0
    assert latency.mean_seconds == 0.0


# ---------------------------------------------------------------------------
# Latency aggregation
# ---------------------------------------------------------------------------


def test_latency_mean_is_sum_over_count() -> None:
    metrics = PerTenantMetrics()
    for latency in (0.1, 0.2, 0.3):
        metrics.observe_request(
            tenant_id="t-acme",
            method="GET",
            path="/x",
            status_code=200,
            latency_seconds=latency,
        )
    row = metrics.snapshot_latency(tenant_id="t-acme")[0]
    assert row.count == 3
    assert round(row.sum_seconds, 4) == 0.6
    assert round(row.mean_seconds, 4) == 0.2


def test_latency_zero_count_returns_zero_mean() -> None:
    """Defensive: a tenant with no observations has no rows."""
    metrics = PerTenantMetrics()
    assert metrics.snapshot_latency(tenant_id="t-no-data") == ()


# ---------------------------------------------------------------------------
# Row shape
# ---------------------------------------------------------------------------


def test_request_row_field_shape() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-acme",
        method="POST",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.05,
    )
    row = metrics.snapshot_requests(tenant_id="t-acme")[0]
    assert isinstance(row, TenantRequestRow)
    assert row.tenant_id == "t-acme"
    assert row.method == "POST"
    assert row.path == "/v1/query_docs"
    assert row.status_code == 200
    assert row.count == 1


def test_latency_row_field_shape() -> None:
    metrics = PerTenantMetrics()
    metrics.observe_request(
        tenant_id="t-acme",
        method="POST",
        path="/v1/query_docs",
        status_code=200,
        latency_seconds=0.05,
    )
    row = metrics.snapshot_latency(tenant_id="t-acme")[0]
    assert isinstance(row, TenantLatencyRow)
    assert row.tenant_id == "t-acme"
    assert row.method == "POST"
    assert row.path == "/v1/query_docs"
    assert row.count == 1
    assert round(row.sum_seconds, 4) == 0.05
    assert round(row.mean_seconds, 4) == 0.05
