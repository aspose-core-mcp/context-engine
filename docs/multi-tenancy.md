# Multi-Tenancy — Design and Implementation Status

> **Status:** Design **accepted**; partially implemented. The public query path filters retrieval results by tenant, and the identity, SQL persistence, Redis key namespacing, per-tenant metrics and migration building blocks exist as tested modules. OpenSearch index partitioning, the tenant-context middleware, PostgreSQL row-level security and a tenant management API/UI are not implemented.
> The running service is effectively single-tenant: every existing record belongs to the implicit `default` tenant.

ADCS runs as a single-tenant deployment per organization. This document describes the multi-tenant design — one shared deployment serving multiple isolated organizations ("tenants") with independent data, identity and audit trails — and records which parts of it exist in code.

## Implementation status

| Layer | Status | Where |
|-------|--------|-------|
| Identity scaffold (Tenant model, registry, scope-auth helper) | **Implemented** | [`src/adcs/admin/tenancy.py`](../src/adcs/admin/tenancy.py), [`tests/test_tenancy.py`](../tests/test_tenancy.py) |
| Admin principal `tenant_id` field | **Implemented** | [`src/adcs/api/admin_auth.py`](../src/adcs/api/admin_auth.py) — `AdminKeyPrincipal`, `AdminKeyMetadata`, and `_AdminKeyRecord` all carry `tenant_id: str = "default"`; `create_key()` accepts a `tenant_id` kwarg with whitespace normalisation; [`tests/test_admin_principal_tenancy.py`](../tests/test_admin_principal_tenancy.py) covers default + explicit + blank propagation paths |
| SQL persistence — `tenants` table + repository | **Implemented** (module; not used by the API) | [`src/adcs/admin/tenant_persistence.py`](../src/adcs/admin/tenant_persistence.py), [`tests/test_tenant_persistence.py`](../tests/test_tenant_persistence.py); `InMemoryTenantRepository` for unit tests + `SqlTenantRepository` for Postgres/SQLite; default tenant auto-seeded |
| Qdrant payload partitioning by `tenant_id` | **Implemented (post-filter mode)** | [`src/adcs/retrieval/tenant_lane_adapter.py`](../src/adcs/retrieval/tenant_lane_adapter.py), [`tests/test_tenant_lane_adapter.py`](../tests/test_tenant_lane_adapter.py); `TenantAwareLaneAdapter` wraps any inner adapter and post-filters by `metadata.tenant_id`. Pre-filtering inside the Qdrant search call (a `FieldCondition(key="tenant_id", ...)`) is not implemented |
| Public query tenant routing | **Implemented (post-filter mode)** | [`src/adcs/api/public_docs_query.py`](../src/adcs/api/public_docs_query.py), [`tests/test_query_docs_tenant_isolation.py`](../tests/test_query_docs_tenant_isolation.py) — the public query path resolves the tenant from the `x-tenant-id` header (set by an authenticating edge proxy; absent or blank means `default`) and wraps both the dense and lexical lanes in `TenantAwareLaneAdapter` |
| OpenSearch index partitioning | Not implemented | Lexical results are post-filtered by `TenantAwareLaneAdapter`; index-level partitioning (tenant field + search template) does not exist |
| Redis key namespacing | **Implemented** (module; not used by the API cache) | [`src/adcs/admin/tenant_redis.py`](../src/adcs/admin/tenant_redis.py), [`tests/test_tenant_redis.py`](../tests/test_tenant_redis.py); `TenantRedisKeyspace` wraps any redis-compatible client and prefixes every key with `tenant:{tenant_id}:`. Refuses colons in `tenant_id` to prevent prefix-confusion. 23 isolation tests verify cross-tenant key invisibility. |
| Per-tenant observability metrics | **Implemented** (module; not exported at `/metrics`) | [`src/adcs/admin/tenant_metrics.py`](../src/adcs/admin/tenant_metrics.py), [`tests/test_tenant_metrics.py`](../tests/test_tenant_metrics.py) — `PerTenantMetrics` keeps independent counters per tenant; `snapshot_requests` and `snapshot_latency` return per-tenant breakdowns. Complements (does not replace) the deployment-wide `InMemoryMetrics`. |
| Migration tooling (assign tenant_id to legacy rows) | **Implemented** (module) | [`src/adcs/admin/tenant_migration.py`](../src/adcs/admin/tenant_migration.py), [`tests/test_tenant_migration.py`](../tests/test_tenant_migration.py) — idempotent `run_tenant_backfill` adds `tenant_id` column with `DEFAULT 'default'` to legacy admin tables and backfills any NULL values; returns a `TenantMigrationReport` for operator review. Backend-agnostic (SQLite + Postgres). Preserves any already-tagged rows. |

The identity scaffold is the foundation: downstream layers read `tenant_id` from the identity layer instead of embedding the literal `"default"` string, so enabling multiple tenants is additive (assign tenant_ids to existing records + route by tenant) rather than a refactor.

Sections 1–10 describe the design. Where a section goes beyond the table above, it describes behaviour that is not implemented.

## 1. Goals and Non-Goals

### Goals
- **Data isolation** — no tenant can read another tenant's queries, audit log, or customizations
- **Identity isolation** — admin keys and roles scoped to a single tenant (with operator-level cross-tenant read for support)
- **Operational economy** — one deployment supports many tenants; not per-tenant deployments
- **Backward compat** — existing single-tenant deployments continue to work via a "default" tenant migration
- **Per-tenant observability** — analytics, audit, and quality reviews scoped to the tenant

### Non-goals
- Per-tenant infrastructure isolation (separate clusters, VPCs) — run a dedicated deployment instead
- Per-tenant billing automation
- Cross-tenant data sharing flows
- Tenant-specific code customization

## 2. Tenancy Model

We adopt the **Bridge model** (per AWS SaaS taxonomy):

- **Compute** — shared (one ADCS deployment per cluster)
- **Index storage (Qdrant + OpenSearch)** — shared cluster, partitioned by `tenant_id` payload field
- **Metadata DB (PostgreSQL)** — shared, row-level scoped by `tenant_id` column
- **Cache (Redis)** — shared, key prefix `tenant:{tenant_id}:...`
- **Audit log** — shared schema, scoped by `tenant_id`

**Why Bridge over Pool or Silo:**

| Model | Operational cost | Isolation strength | Chosen? |
|-------|------------------|--------------------|---------|
| Pool (everything shared) | Lowest | Weakest | No — audit and compliance issues |
| Bridge (shared compute, partitioned data) | Medium | Strong (logical) | **Yes** |
| Silo (per-tenant infra) | Highest | Strongest | No — defeats SaaS economics |

Bridge gives logical isolation strong enough for enterprise requirements without the operational cost of per-tenant clusters. Deployments that require physical isolation should run a dedicated (Silo-style) deployment instead; that is outside this design.

## 3. Identity Model

### 3.1 Tenant
A **tenant** is an organizational unit (typically one customer company). It owns:
- A unique `tenant_id` (immutable)
- A human-readable `tenant_slug` (`example-org`, `acme-corp`, ...) used in URLs and admin UI
- Configuration overrides (feature flags, retention policies)
- All admin keys, audit events, query analytics, quality reviews, and config history scoped to it

### 3.2 Roles within a tenant
Existing roles (per [`docs/rbac-and-audit.md`](rbac-and-audit.md)) are extended with tenant scope:

| Role | Tenant scope |
|------|--------------|
| `VIEWER` | Read-only within tenant |
| `OPERATOR` | Operational ops within tenant |
| `PO` | Quality reviews within tenant |
| `SUPERUSER` (per-tenant) | Full control within tenant |
| `PLATFORM_OPERATOR` (cross-tenant) | New role: operational support across tenants (read-only by default; write requires tenant grant) |
| `PLATFORM_SUPERUSER` (cross-tenant) | New role: ADCS platform owner; can manage tenants themselves |

The two `PLATFORM_*` roles are held by the operator of the shared deployment. Tenant admin keys always carry one of the per-tenant roles and are scoped to a single tenant.

### 3.3 API key shape
```json
{
  "key_id": "key_abc123",
  "tenant_id": "tenant_xyz789",
  "role": "operator",
  "product_scopes": ["aspose.ocr"],
  "created_at": "2026-09-01T...",
  "expires_at": null
}
```

Keys with `tenant_id = null` are platform keys (validated by `PLATFORM_*` role check).

## 4. Data Partitioning

### 4.1 PostgreSQL
Every tenant-aware table gets a `tenant_id` column and a composite index on `(tenant_id, created_at)`. Tenant-aware tables hold admin keys, ingestion jobs, snapshots, critical events, audit records and query analytics — for example:

- `admin_api_keys`
- `ingestion_jobs`, `index_snapshots`
- `critical_events`, `critical_event_actions`
- `snapshot_rollback_audit`, `snapshot_cleanup_audit`
- `query_events`, `usefulness_feedback`, `issue_intake_reports`

Every query must include `WHERE tenant_id = :current_tenant`. This is enforced via:

1. SQLAlchemy event listener (`before_compile`) that injects the filter automatically into every Query
2. PostgreSQL Row-Level Security (RLS) as defense in depth — `CREATE POLICY tenant_isolation ON ... USING (tenant_id = current_setting('adcs.tenant_id'))`

### 4.2 Qdrant
Each chunk's payload gains `tenant_id` (alongside existing `product_id`, `language`, `version`). The retrieval `Filter` always includes:

```python
filter = Filter(
    must=[
        FieldCondition(key="tenant_id", match=MatchValue(value=current_tenant_id)),
        # ... existing product/language/version filters ...
    ]
)
```

We choose **shared collection with payload filter** over **collection per tenant** because:
- 1000 tenants × 50 product collections = 50,000 collections — operationally untenable
- Qdrant payload filtering is cheap when the field is indexed (a `tenant_id` payload index)
- Collection per tenant only wins for noisy-neighbor workloads, which aren't an issue at our QPS

### 4.3 OpenSearch
Same approach: `tenant_id` field on every document, every search query has `term: { tenant_id: ... }` filter applied via a search template.

### 4.4 Redis
Key prefix: `tenant:{tenant_id}:original_key`. The cache wrapper applies the prefix transparently. Cache eviction on tenant deletion uses `SCAN` + `DEL` on the prefix.

## 5. Tenant Context Propagation

### 5.1 Request entry point
A FastAPI middleware extracts the tenant from the request:

| Source | Header | Use |
|--------|--------|-----|
| Admin API key | `x-api-key` → key lookup → `tenant_id` | Authenticated admin requests |
| Tenant subdomain | `acme.adcs.example.com` → DNS-derived tenant slug | Public MCP/REST when branded |
| Explicit header | `x-tenant-id` | Set by an authenticating edge proxy, or by platform operators acting on behalf of a tenant |

The middleware sets `request.state.tenant_id` and a Postgres session variable (`SET LOCAL adcs.tenant_id = ...`) for the request's duration.

Note: the implemented public query path reads the tenant from the `x-tenant-id` header, set by an authenticating edge proxy (see [Implementation status](#implementation-status)).

### 5.2 Async tasks (Celery)
Every Celery task signature carries a `tenant_id` argument. The task entry point sets the session variable and contextual logging field before doing work.

### 5.3 LLM calls
Calls to LLM and embedding endpoints carry `tenant_id`, so usage can be attributed per tenant.

## 6. Admin API & UI Changes

### 6.1 Tenant management endpoints (platform-only)
Platform superusers manage tenants through admin endpoints under `/admin/v1/` that:
- list tenants
- create a tenant
- update a tenant's configuration
- soft-delete a tenant (purged after a retention window)
- create admin keys for a tenant

The admin API has no tenant management endpoints today; `SqlTenantRepository` provides the storage operations they would use.

### 6.2 Per-tenant routes (existing)
All existing `/admin/v1/*` routes keep their signatures but auto-scope to the caller's tenant. No URL changes required for customer-side compatibility.

### 6.3 Admin UI tenant switcher
A tenant switcher in the admin UI header (visible only to PLATFORM_* roles) lets platform operators switch tenant context. All section data (analytics, ingestion, audit) re-scopes on switch.

## 7. Backward Compatibility

### 7.1 Migration of existing single-tenant deployments
The existing building blocks migrate a single-tenant deployment in place:

1. `SqlTenantRepository` creates the `tenants` table and seeds the `default` tenant
2. `run_tenant_backfill` ([`src/adcs/admin/tenant_migration.py`](../src/adcs/admin/tenant_migration.py)) adds a `tenant_id` column with `DEFAULT 'default'` to each target table that exists — the names passed in `table_names`, or `DEFAULT_TENANT_TABLES` when none are given; tables that do not exist are reported as skipped
3. The same run backfills NULL `tenant_id` values with `default` and leaves already-tagged rows untouched; running it again is a no-op

Existing admin keys already carry `tenant_id = "default"`, so existing deployments transition without changes.

### 7.2 No customer-side changes required
Single-tenant customers continue using the same MCP/REST endpoints with the same admin keys. The default tenant is invisible to them.

## 8. Index Isolation Enforcement

Two layers of defense (per [`docs/rbac-and-audit.md`](rbac-and-audit.md) defense-in-depth principle):

1. **Application layer** — every retrieval call is scoped to a tenant; `TenantAwareLaneAdapter` drops any candidate whose `tenant_id` does not match, before reranking and context packing. Candidates without an explicit `tenant_id` belong to `default`, which is not a wildcard.
2. **Database layer** — Postgres RLS, Qdrant payload index, OpenSearch search template constraint

Query-path isolation is covered by `tests/test_query_docs_tenant_isolation.py` and `tests/test_tenant_lane_adapter.py`; cache-key isolation by `tests/test_tenant_redis.py`.

## 9. Per-Tenant Configuration Overrides

Tenants can override these globals via admin UI:
- Retrieval feature flags
- Quarantine threshold (per product)
- Reranker / fusion weights
- Audit retention days (within bounds)
- PII masking rule pack version

Stored in a `tenants.config_overrides` JSONB column. Defaults inherit from global config; overrides apply on top.

## 10. Analytics & Audit Scoping

| Surface | Scope |
|---------|-------|
| Admin UI analytics (per-tenant) | This tenant only |
| Admin UI analytics (platform) | Cross-tenant aggregation (no cross-tenant query content visible) |
| Audit log (per-tenant) | This tenant only |
| Audit log (platform) | All tenants — visible to PLATFORM_SUPERUSER, with reason logging |
| Quality reviews | Per tenant |
| Critical events | Per tenant + platform-wide stream for ops |

## Related Documents

- [`docs/rbac-and-audit.md`](rbac-and-audit.md) — current single-tenant RBAC
- [`docs/architecture.md`](architecture.md) — system architecture
- [`docs/data-protection-and-pii.md`](data-protection-and-pii.md) — data protection controls
