# RBAC and Audit

This document describes the access-control model for the ADCS APIs and the audit records the service writes.

Reference implementation: `src/adcs/api/admin_auth.py`.

## Authentication Tiers

| Channel | Auth required? | Mechanism |
|---------|----------------|-----------|
| Public MCP (`/mcp/v1/*`: streamable HTTP, SSE; stdio) | No | Anonymous; abuse guard (`ADCS_ABUSE_GUARD_MODE`) |
| Public REST `/v1/*` | No | Anonymous; retrieval endpoints go through the abuse guard |
| Admin REST `/admin/v1/*` and `/v1/admin/quality-loop/*` | Yes | `x-api-key` header, or the HTTP-only session cookie issued by `POST /admin/v1/system/session/login` |
| WebMCP `/webmcp/v1/*` (only when `ADCS_WEBMCP_ENABLED=true`) | Read tools: no. Confirmations, job listing, write tools and audit: yes | Admin key + confirmation flow + audit |

`POST /admin/v1/system/session/login` is the only admin route that accepts a request without a key or session; it exchanges a valid key for a session cookie and throttles failed attempts.

## Scopes and Roles

Authorization is **scope-based**. Every admin key has:

- `is_superuser` — a superuser key passes every check and carries the wildcard scope `*`
- `scopes` — write scopes: `write:ingestion`, `write:settings`, `write:destructive`
- `product_scopes` — the products a non-superuser key may change; a non-superuser key must have at least one

| Scope | Grants |
|-------|--------|
| *(any valid, enabled key)* | Every read endpoint, the read-only analytics SQL explorer, and content previews |
| `write:ingestion` | Source sync, layout detection, Hugo normalization, ingestion trigger/reindex/cancel/retry/resume, snapshot promote and rollback, critical-event actions, WebMCP write tools |
| `write:settings` | Quality-review runs and policies, HowTo overrides, per-product retrieval settings and language aliases, per-product config rollback, fix drafts from request evidence, admin key management within the key's products, per-product backup and restore |
| `write:destructive` | Required in addition for destructive operations: snapshot cleanup (with `write:ingestion`), backup restore (with `write:settings`); on its own it grants bulk snapshot cleanup |
| superuser | Everything above plus global registries (languages, locales), abuse-guard settings, product onboarding, global config rollback, global backup and restore, the DR recovery smoke, and superuser keys |

The admin console shows an **effective role** derived from those attributes by `_derive_effective_role()`: `is_superuser` → `superuser`; `write:destructive` or `write:settings` → `product-owner`; `write:ingestion` → `operator`; otherwise `viewer`. The role is a label; the checks use scopes.

## Permission Matrix

### Public Endpoints (No Auth)

| Endpoint | Notes |
|----------|-------|
| `POST /v1/products:resolve` | Abuse guard |
| `POST /v1/docs:query` | Abuse guard |
| `POST /v1/symbols:get` | Abuse guard |
| `POST /v1/changes:list` | Abuse guard |
| `POST /v1/releases:latest` | Abuse guard |
| `POST /v1/symbols/structured:lookup`, `:get`, `:members`, `:search` | Abuse guard; require `APIREF_STRUCTURED_STORE_ENABLED=true` |
| `POST /v1/docs:feedback`, `POST /v1/docs:issues`, `GET /v1/docs:repro-pack` | Abuse guard |
| `POST /mcp/v1/streamable-http` (and the SSE and legacy `/mcp/v1/*` routes) | Abuse guard on initialize and tool calls |
| `GET /v1/status`, `/v1/status/page`, `/v1/topology`, `/v1/integrations/*`, `/v1/snippets`, `/v1/howto/*` | Read-only |
| `GET /healthz`, `/readyz`, `/metrics`, `/openapi.json` | Operations |

### Admin Endpoints (Auth Required)

Legend: ✓ = any valid key; a scope name = that scope is required (superuser keys always pass); **SU** = superuser only; ✗ = HTTP 403 for everyone else.

| Endpoint | Requirement |
|----------|-------------|
| `GET /admin/v1/system/health`, `/system/session`, `/system/topology`, `/system/content-services` | ✓ |
| `GET /admin/v1/observability/summary`, `/index-status`, `/product-coverage`, `/products` | ✓ |
| `GET /admin/v1/analytics/*` | ✓ |
| `POST /admin/v1/analytics/sql:query`, `sql:export`; `GET /admin/v1/analytics/sql:schema` | ✓ (read-only `SELECT` only) |
| `POST /admin/v1/analytics/request-evidence:create-fix-draft` | `write:settings` |
| `GET /admin/v1/source-repositories/*`, `GET /admin/v1/ingestion/jobs*` | ✓ |
| `POST /admin/v1/source-repositories/review-artifact:preview`, `raw-markdown:preview`, `staging-manifest:preview` | ✓ |
| `POST /admin/v1/source-repositories/sync`, `layout-detection`, `layout-detection/{repo_id}/override`, `hugo-normalize` | `write:ingestion` |
| `POST /admin/v1/ingestion/trigger`, `reindex`, `jobs/{operation_id}:cancel`, `:retry`, `:resume` | `write:ingestion` |
| `POST /admin/v1/source-repositories/onboard-product` | **SU** |
| `GET /admin/v1/snapshots`, `/snapshots/active`, `/snapshots/{snapshot_id}`, `snapshots:compare`, `snapshots:rollback-audit`, `snapshots:cleanup-history` | ✓ |
| `POST /admin/v1/snapshots/{snapshot_id}:promote`, `:rollback-confirmation`, `:rollback` | `write:ingestion` |
| `POST /admin/v1/snapshots:cleanup-preview`, `snapshots:cleanup` | `write:ingestion` + `write:destructive` |
| `POST /admin/v1/snapshots:bulk-cleanup` | `write:destructive` |
| `GET /admin/v1/events/critical`, `/events/critical/actions` | ✓ |
| `POST /admin/v1/events/critical/{event_id}:acknowledge`, `:mute`, `:snooze`, `:assign`, `:severity-override`, `:escalate`, `:resolve` | `write:ingestion` |
| `GET /admin/v1/quality-reviews/runs*`, `/quality-reviews/policy-presets` | ✓ |
| `POST /admin/v1/quality-reviews/runs`, `runs/{run_id}:approve-all`, `runs/{run_id}:reject`, `runs:batch-approve-all`, `runs:batch-reject`; `PATCH /admin/v1/quality-reviews/policy`; `POST /admin/v1/quality-reviews/policy:apply-preset` | `write:settings` |
| `GET /admin/v1/howto/articles*` | ✓ |
| `PUT /admin/v1/howto/articles/{article_id}/draft`; `POST …:publish`, `:reset-draft`, `:clear-published`; `POST /admin/v1/howto/assets:upload` | `write:settings` |
| `GET /admin/v1/registries/*`, `/settings/retrieval/{product_id}` | ✓ |
| `POST`/`DELETE /admin/v1/registries/languages`, `/registries/locales` | **SU** |
| `POST`/`DELETE /admin/v1/registries/languages/aliases`; `PATCH /admin/v1/settings/retrieval/{product_id}` | `write:settings` |
| `GET /admin/v1/settings/public-api/abuse-guard` | ✓ |
| `PATCH /admin/v1/settings/public-api/abuse-guard` | **SU** |
| `GET /admin/v1/config/history` | ✓ |
| `POST /admin/v1/config/rollback` | `write:settings`; **SU** for global (`_global`) changes |
| `GET /admin/v1/keys`, `/keys/audit`, `keys:export` | ✓ (metadata only, never tokens) |
| `POST /admin/v1/keys`, `keys:import`, `keys/{key_id}:rotate`, `:enable`, `:disable`; `PATCH /admin/v1/keys/{key_id}/scopes` | `write:settings`; **SU** to create or manage superuser keys |
| `GET /admin/v1/system/backups*`, `/system/backup-operations*` | ✓ |
| `POST /admin/v1/system/backups:trigger` | `write:settings`; **SU** for a global backup |
| `POST /admin/v1/system/backups/{backup_id}:restore` | `write:settings` + `write:destructive` (unless `validate_only`); **SU** for a global restore |
| `POST /admin/v1/system/dr:recovery-smoke` | **SU** |
| `GET /v1/admin/quality-loop/calibration` | ✓ |
| `POST /webmcp/v1/confirmations`, `GET`/`POST /webmcp/v1/tools/web_list_ingestion_jobs`, `GET /webmcp/v1/audit/write-invocations` | ✓ |
| `POST /webmcp/v1/tools/web_trigger_ingestion`, `web_trigger_reindex`, `web_promote_snapshot` | `write:ingestion` + confirmation |

## Product Scope Enforcement

Non-superuser keys carry a `product_scopes` list. Every mutating request:

1. Identifies the target products (from URL path, body, or the affected repositories)
2. Validates that each target product is in `key.product_scopes` (superuser keys bypass the check)
3. Returns HTTP 403 (`FORBIDDEN`, "Product scope violation") on a scope violation

When a mutation targets no specific repository — for example an ingestion trigger for all sources — every registered product is a target, so only keys scoped to all products (or superuser keys) pass. Key management has two more rules: a non-superuser key can grant only write scopes it holds itself, and never `*`.

Read-only requests are accepted for any valid, enabled key.

Reference: `src/adcs/api/admin_auth.py::AdminAuthService.authorize_mutation()`.

## Audit Records

Audit records are written by component-specific stores:

- Admin key lifecycle (create, scope change, enable, disable; a rotation is a create plus a disable) — `AdminAuthService` in `src/adcs/api/admin_auth.py`, exposed at `GET /admin/v1/keys/audit`
- Snapshot rollback and cleanup — `snapshot_rollback_audit` and `snapshot_cleanup_audit` tables (`src/adcs/ops/snapshot_rollback_audit.py`, `src/adcs/ops/snapshot_cleanup_audit.py`)
- Critical events and operator actions on them — `critical_events` and `critical_event_actions` tables (`src/adcs/ops/critical_events.py`)
- Configuration changes with before/after state — `src/adcs/admin/config_history.py`
- WebMCP write flows — `src/adcs/api/webmcp_audit.py`

Each record carries the acting `key_id` and the `request_id` of the call, so it can be joined with the structured request logs.

## Retention

ADCS does not purge audit records or query analytics. Retention is a deployment decision: choose periods that meet your compliance requirements and enforce them in the database (for example with partitioned tables and a scheduled purge) and in your log pipeline.

## PII Handling in Audit

Audit events and analytics may include PII (IP addresses, queries). Per [`docs/data-protection-and-pii.md`](data-protection-and-pii.md):

- IP addresses → `ip_hash` (HMAC-SHA256 keyed from `ADCS_HASH_SECRET`)
- Query text → `query_fingerprint` (HMAC-SHA256) for analytics joins; query analytics also keep the raw query text, so include them in your retention policy
- User identifiers → never logged (we don't have end-user identity)

## Immutability and Integrity

Recommended database-level controls for deployments:

- Make audit tables `INSERT`-only for application roles (revoke `UPDATE` and `DELETE` from non-DBA roles)
- Run a daily integrity check (row count + checksum diff)
- Include audit tables in backups — see [`infra/runbooks/dr-backup-restore.md`](../infra/runbooks/dr-backup-restore.md)

## Querying the Audit Log

For incident response, query the audit tables directly:

```sql
-- Rollbacks performed by a specific key in the last 24h
SELECT * FROM snapshot_rollback_audit
WHERE actor_key_id = 'key_abc123'
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Operator actions on critical events
SELECT * FROM critical_event_actions
ORDER BY created_at DESC
LIMIT 100;
```

## Incident Response

If audit logs reveal suspicious activity:

1. Disable the suspect key (`POST /admin/v1/keys/{key_id}:disable`)
2. Follow [`infra/runbooks/incident-response-playbooks.md`](../infra/runbooks/incident-response-playbooks.md)
3. Snapshot affected resources for forensics
4. Rotate any potentially-compromised credentials
