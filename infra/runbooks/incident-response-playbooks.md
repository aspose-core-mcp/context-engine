# Incident Response Playbooks

Playbooks for operators of an ADCS deployment. The alert rules in
[`infra/observability/prometheus/adcs-alerts.yaml`](../observability/prometheus/adcs-alerts.yaml)
link to the sections below through their `runbook_url` annotations.

Conventions used in the commands:

- The Helm chart is installed as release `adcs` in namespace `adcs`, as in
  [`infra/helm/adcs/README.md`](../helm/adcs/README.md), so the workloads are
  `deployment/adcs-api`, `deployment/adcs-mcp-gateway` and `deployment/adcs-worker`.
- `$API` is the public API base URL, `$ADMIN` the admin API base URL, and
  `$ADCS_API_KEY` an admin key sent as the `x-api-key` header.
- `$QDRANT_URL` and `$OPENSEARCH_URL` are the backing-store endpoints configured in
  `global.externalServices`.
- PromQL queries assume the scrape job name used by the alert rules (`adcs-api`).

## Severity Definitions

| Severity | Meaning | Examples | Suggested routing |
|----------|---------|----------|-------------------|
| Sev1 | Service unavailable or data integrity at risk | API returning 5xx, no retrieval results | Page immediately |
| Sev2 | SLO at risk or a major feature degraded | High latency, citation coverage breach, fast error-budget burn | Page |
| Sev3 | Minor degradation, a workaround exists | Abuse storm, partial-publish burst, slow error-budget burn | Ticket or chat notification |
| Sev4 | Informational | Single failed background job | Periodic review |

## First Steps

For any alert:

1. Confirm the signal: run the alert expression in Prometheus, or read `/metrics`
   from an affected pod. Request and retrieval metrics are held per pod and reset when
   a pod restarts.
2. Check process and dependency health. `/readyz` returns `503` and marks the
   unreachable dependency (`postgres`, `redis`, `qdrant`, `opensearch`) as
   `not_ready`:

   ```bash
   curl -s "$API/readyz" | jq
   curl -s "$ADMIN/admin/v1/system/health" -H "x-api-key: $ADCS_API_KEY" | jq
   kubectl get pods -n adcs -l app.kubernetes.io/instance=adcs
   ```

3. Look for recent changes:

   ```bash
   helm history adcs -n adcs
   curl -s "$ADMIN/admin/v1/snapshots:rollback-audit" -H "x-api-key: $ADCS_API_KEY" | jq
   curl -s "$ADMIN/admin/v1/config/history" -H "x-api-key: $ADCS_API_KEY" | jq
   curl -s "$ADMIN/admin/v1/events/critical" -H "x-api-key: $ADCS_API_KEY" | jq
   ```

4. Keep a timeline of what you observe and change.

---

## Playbook S1A: Complete Indexing Failure (Sev1)

**Trigger**: `query_docs` (MCP) and `POST /v1/docs:query` return empty results or
errors for every product. `ADCSLowConfidenceRetrieval` jumping towards 100% is a
common early sign.

**Possible causes**:

- Qdrant and OpenSearch both unavailable (retrieval returns an empty envelope, not a 500)
- No active snapshot for the requested product, language and version
- Full disk on index storage

**Diagnosis**:

```bash
# 1. Dependency reachability as seen by the API
curl -s "$API/readyz" | jq

# 2. Snapshot registry: totals, then the active snapshot for one scope
curl -s "$API/metrics" | grep -E '^adcs_index_(snapshots_total|active_snapshots)'
curl -s "$ADMIN/admin/v1/snapshots/active?product_id=<product>&programming_language=<language>&version=<version>" \
  -H "x-api-key: $ADCS_API_KEY" | jq

# 3. API logs
kubectl logs -n adcs deployment/adcs-api --tail=200 | grep -iE "qdrant|opensearch|snapshot"

# 4. Backing stores, from a host that can reach them
curl -s "$QDRANT_URL/healthz"
curl -s "$OPENSEARCH_URL/_cluster/health?pretty"
```

**Recovery options** (try in order):

### Option A: Rollback to last known good snapshot

```bash
# List snapshots for the affected scope, newest first
curl -s "$ADMIN/admin/v1/snapshots?product_id=<product>&programming_language=<language>&version=<version>" \
  -H "x-api-key: $ADCS_API_KEY" | jq

# Request a single-use confirmation token for the snapshot to roll back to
curl -s -X POST "$ADMIN/admin/v1/snapshots/<target_snapshot_id>:rollback-confirmation" \
  -H "x-api-key: $ADCS_API_KEY" -H "content-type: application/json" \
  -d '{"reason": "<reason>"}'

# Roll back with the same reason and the returned confirm_token
curl -s -X POST "$ADMIN/admin/v1/snapshots/<target_snapshot_id>:rollback" \
  -H "x-api-key: $ADCS_API_KEY" -H "content-type: application/json" \
  -d '{"reason": "<reason>", "confirm_token": "<confirm_token>"}'
```

The token expires after `ADCS_WEBMCP_CONFIRM_TTL_SECONDS` (300 by default). Tokens are
held in the memory of the pod that issued them, so with several API replicas send both
calls to the same pod, for example through
`kubectl port-forward -n adcs deployment/adcs-api 8080:8080` with
`ADMIN=http://127.0.0.1:8080`.

The rollback runs preflight checks, guards against a concurrent change of the active
snapshot, and is recorded in the rollback audit
(`GET /admin/v1/snapshots:rollback-audit`, `src/adcs/ops/snapshot_rollback_audit.py`).

### Option B: Restore from backup

Follow the [backup and restore runbook](dr-backup-restore.md).

### Option C: Rebuild the index from source

```bash
curl -s -X POST "$ADMIN/admin/v1/ingestion/reindex" \
  -H "x-api-key: $ADCS_API_KEY" -H "content-type: application/json" \
  -d '{"repo_ids": ["<repo_id>"]}'

curl -s "$ADMIN/admin/v1/ingestion/jobs/<operation_id>" -H "x-api-key: $ADCS_API_KEY" | jq
```

Repository IDs are listed in `config/source-repositories.yaml`. This is the slowest
option; use it when A and B are not possible.

**Verification**:

```bash
make deploy-smoke DEPLOY_SMOKE_BASE_URL="$API"

curl -s -X POST "$API/v1/docs:query" -H "content-type: application/json" \
  -d '{"query": "<known query>", "product_id": "<product>"}' | jq '.results | length'
```

`make deploy-smoke` checks `/healthz`, `/readyz` and `/v1/status`; the query must
return a non-empty `results` list.

---

## Playbook S1B: API Availability Breach (Sev1)

**Trigger**: `ADCSCriticalApiAvailability` — more than 5% of requests return 5xx for
5 minutes. `ADCSSlo99_9_FastBurn` (Sev2) and `ADCSSlo99_9_SlowBurn` (Sev3) are
earlier warnings about the same error budget.

**Diagnosis**:

```promql
# Which routes fail, and with which status
sum by (path, status) (rate(adcs_http_requests_total{job="adcs-api",status=~"5.."}[5m]))
```

```bash
kubectl get pods -n adcs -l app.kubernetes.io/instance=adcs
kubectl logs -n adcs deployment/adcs-api --tail=200
kubectl logs -n adcs deployment/adcs-api --previous --tail=200   # after a restart
curl -s "$API/readyz" | jq
```

**Common causes**:

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Pods restarting or never ready | Start-up validation rejects configuration | Set the values listed under "Required values" in [`infra/helm/adcs/README.md`](../helm/adcs/README.md) |
| `/readyz` marks a dependency `not_ready` | PostgreSQL, Redis, Qdrant or OpenSearch unreachable | Restore the dependency or its network path |
| `503` responses with error code `TIMEOUT` | Requests exceed `ADCS_ENDPOINT_TIMEOUT_SECONDS` (default 30) | Follow [Playbook S2A](#playbook-s2a-api-latency-slo-breach-sev2) |
| Errors began with a release | Regression in the new version | Roll back the release (below) |

**Mitigation**: roll back to the last good release.

```bash
helm history adcs -n adcs
helm rollback adcs <revision> -n adcs
```

**Recovery**: the availability ratio in the alert expression returns above 95%
and the burn-rate alerts resolve.

---

## Playbook S2A: API Latency SLO Breach (Sev2)

**Trigger**: `ADCSHighLatencyP95` — API p95 latency above 1.8s for 10 min.

**Diagnosis**:

```promql
# Slowest routes
topk(5, histogram_quantile(0.95,
  sum by (le, path) (rate(adcs_http_request_duration_seconds_bucket{job="adcs-api"}[5m]))))

# Retrieval pipeline stages
histogram_quantile(0.95,
  sum by (le, stage) (rate(adcs_retrieval_stage_duration_seconds_bucket{job="adcs-api"}[5m])))
```

```bash
# Upstream health
curl -s "$QDRANT_URL/healthz"
curl -s "$OPENSEARCH_URL/_cluster/health?pretty"

# Resource saturation and autoscaling headroom
kubectl top pods -n adcs
kubectl get hpa -n adcs
```

**Mitigation options**:

### Option A: Scale up

The chart autoscales `adcs-api` and `adcs-mcp-gateway` between `hpa.minReplicas` and
`hpa.maxReplicas`. If the HPA is at its maximum, raise the limit:

```bash
helm upgrade adcs infra/helm/adcs -n adcs --reuse-values \
  --set api.hpa.maxReplicas=20
```

### Option B: Switch the reranker backend

If `ADCS_RERANKER_BACKEND=openai_compatible` and the reranker endpoint is slow, switch
to the local `advanced_heuristic` backend (the default):

```bash
helm upgrade adcs infra/helm/adcs -n adcs --reuse-values \
  --set global.extraEnv.ADCS_RERANKER_BACKEND=advanced_heuristic
```

Reference: `src/adcs/retrieval/reranker.py`.

### Option C: Shorten the retrieval lane timeout

When one retrieval lane (Qdrant or OpenSearch) is slow, the other lane keeps serving
once `ADCS_HYBRID_LANE_TIMEOUT_SECONDS` (default 10) elapses. Lowering it caps the
time a slow lane can add to each query:

```bash
helm upgrade adcs infra/helm/adcs -n adcs --reuse-values \
  --set-string global.extraEnv.ADCS_HYBRID_LANE_TIMEOUT_SECONDS=2
```

Reference: `src/adcs/retrieval/hybrid_retriever.py`.

**Recovery**: revert the overrides once the root cause is fixed, and confirm that p95
is back below the threshold.

---

## Playbook S2B: Strict-Version Violation (Sev2 — Data Integrity)

**Trigger**: a query with `strict_version: true` returns results from a different
version. No metric covers this; it is reported by clients or found during review.

**Diagnosis**:

```bash
curl -s -X POST "$API/v1/docs:query" -H "content-type: application/json" \
  -d '{"query": "<query>", "product_id": "<product>", "language": "<language>", "version": "<version>", "strict_version": true}' \
  | jq '{version_resolution, results: [.results[] | {canonical_url, source_revision}]}'
```

Add `-H "x-api-key: $ADCS_API_KEY"` and `"debug": true` to include the effective
filters in the response.

**Mitigation**: if the violation started with a publish, roll back to the previous
snapshot ([Playbook S1A, Option A](#option-a-rollback-to-last-known-good-snapshot)).
To see what changed between two snapshots:

```bash
curl -s "$ADMIN/admin/v1/snapshots:compare?base_snapshot_id=<previous>&target_snapshot_id=<current>" \
  -H "x-api-key: $ADCS_API_KEY" | jq
```

**Root causes** are usually one of:

- Index payload missing the `version` field
- Filter resolution allowing unfiltered results (`src/adcs/retrieval/filter_resolver.py`)
- Snapshot published with mixed-version data (`src/adcs/indexing/publish_orchestrator.py`)

---

## Playbook S2D: Citation Coverage Breach (Sev2 — Data Integrity)

**Trigger**: `ADCSCitationCoverageBreach` — `adcs_citation_missing_ratio` above 0.5%
(coverage below 99.5%) for 60 minutes. Results without a `canonical_url` or
`section_anchor` cannot be verified by callers.

`adcs_citation_missing_ratio` is cumulative since the pod started, so it reacts slowly
to a new regression and stays high after a fix until the pod restarts. For a recent
window, use the counters:

```promql
sum(rate(adcs_retrieval_results_missing_citation_total{job="adcs-api"}[15m]))
/
sum(rate(adcs_retrieval_results_total{job="adcs-api"}[15m]))
```

**Diagnosis**:

```bash
# Reproduce and list results without a citation
curl -s -X POST "$API/v1/docs:query" -H "content-type: application/json" \
  -d '{"query": "<query>", "product_id": "<product>"}' \
  | jq '[.results[] | select(.canonical_url == "" or .section_anchor == "")]'

# Recent publish events for the affected product
curl -s "$ADMIN/admin/v1/events/critical?product_id=<product>" -H "x-api-key: $ADCS_API_KEY" | jq
```

**Common causes**:

1. **A new publish with broken metadata** — pages were normalised without canonical
   URLs. Compare the active snapshot with the previous one using
   `GET /admin/v1/snapshots:compare`.
2. **The reranker dropping citation metadata** — see `src/adcs/retrieval/reranker.py`
   and `tests/test_reranker.py`, `tests/test_reranker_properties.py`.
3. **Translation fallback stripping citations** — see
   `src/adcs/retrieval/translation_fallback.py`.

**Mitigation**:

### Option A: Rollback to the previous snapshot

If the breach started right after a publish, rollback is the fastest safe action — see
[Playbook S1A, Option A](#option-a-rollback-to-last-known-good-snapshot). Confirm with
the counter query above that coverage recovers.

### Option B: Fix and re-ingest

Fix the source or the code path, then re-run ingestion for the affected repositories
(`POST /admin/v1/ingestion/trigger`, or `POST /admin/v1/ingestion/reindex` for a full
rebuild) and add a test that covers the failure.

---

## Playbook S3A: Rate-Limit / Abuse Storm (Sev3)

**Trigger**: `ADCSAbuseStorm` — more than 10 requests per second answered with `429`
for 5 minutes. In the default `observe-only` mode no `429` is sent; watch for a surge
of `threshold_exceeded_observe_only` decisions instead.

**Diagnosis**:

```promql
sum by (mode, decision) (rate(adcs_abuse_guard_decisions_total{job="adcs-api"}[5m]))
```

```bash
curl -s "$ADMIN/admin/v1/settings/public-api/abuse-guard" -H "x-api-key: $ADCS_API_KEY" | jq
curl -s "$ADMIN/admin/v1/observability/summary" -H "x-api-key: $ADCS_API_KEY" | jq
```

**Mitigation**:

### Option A: Tighten rate limits via abuse_guard

With the superuser key:

```bash
curl -s -X PATCH "$ADMIN/admin/v1/settings/public-api/abuse-guard" \
  -H "x-api-key: $ADCS_API_KEY" -H "content-type: application/json" \
  -d '{"mode": "enforce", "requests_per_ip_per_minute": 60}'
```

Abuse-guard settings and counters are held in process memory: the call changes only the
pod that serves it, and the change is lost on restart. To apply a setting to every
replica, set it in the chart values and upgrade:

```bash
helm upgrade adcs infra/helm/adcs -n adcs --reuse-values \
  --set global.env.ADCS_ABUSE_GUARD_MODE=enforce \
  --set-string global.env.ADCS_ABUSE_REQUESTS_PER_IP_PER_MINUTE=60
```

Reference: `src/adcs/api/abuse_guard.py`.

### Option B: Block sources at the edge

The abuse guard supports an allowlist but no blocklist. Block offending sources at the
ingress controller, load balancer or WAF.

**Recovery**: return to `observe-only` mode after the storm subsides.

---

## Playbook S3B: Ingestion Pipeline Failure (Sev3)

**Trigger**: `ADCSPartialPublishBurst` — more than 3 partial publishes in 6 hours — or
ingestion jobs failing repeatedly.

**Diagnosis**:

```bash
# Recent jobs that failed
curl -s "$ADMIN/admin/v1/ingestion/jobs?limit=50" -H "x-api-key: $ADCS_API_KEY" \
  | jq '[.[] | select(.status == "failed")]'

# One job in detail
curl -s "$ADMIN/admin/v1/ingestion/jobs/<operation_id>" -H "x-api-key: $ADCS_API_KEY" | jq

# Partial-publish events
curl -s "$ADMIN/admin/v1/events/critical?event_type=partial_publish" -H "x-api-key: $ADCS_API_KEY" | jq

# Worker logs
kubectl logs -n adcs deployment/adcs-worker --tail=200
```

**Common causes**:

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| All runs of a single product failing | Source registry config error | Check `config/source-repositories.yaml`, run `make source-validate` |
| Random failures across products | Embedding endpoint rate limit | Throttle requests or scale the endpoint behind `ADCS_EMBEDDING_API_URL` |
| Layout detection errors | Repository structure changed | Re-run layout detection: `make source-detect-layouts-write` |
| Repeated partial publishes | Source data quality regression | Review the dropped documents and the quarantine policy (`ADCS_INGESTION_METADATA_QUARANTINE_POLICY`) |

**Recovery**: retry failed jobs after the fix. Retry applies to jobs in `failed` or
`retry_scheduled` status:

```bash
curl -s -X POST "$ADMIN/admin/v1/ingestion/jobs/<operation_id>:retry" \
  -H "x-api-key: $ADCS_API_KEY" -H "content-type: application/json" -d '{}'
```

Reference: `src/adcs/ingestion/source_hugo_normalization_orchestrator.py`.

---

## Reproducibility — chaos / DR drills

Several playbooks above have a matching fault-injection drill in
[`infra/chaos/`](../chaos/README.md). Per-drill detail JSON is written under
`reports/chaos/drills/`; the append-only log is written to
`reports/chaos/drill-log.jsonl`.

| Playbook | Drill | What the drill verifies |
|----------|-------|--------------------------|
| S1A — Complete indexing failure | **D-03** `both_lanes_outage` | Empty envelope returned, no 500 |
| S1A — Rollback to last known good snapshot | **D-05** `snapshot_rollback` | Atomic rollback with optimistic concurrency |
| S1A — Restore from backup | **D-06** `dr_backup_restore` | Sentinel round-trips through backup/restore |
| S2A — API latency SLO breach (Qdrant slow) | **D-04** `lane_timeout` | Slow lane cancelled at `lane_timeout_seconds` |
| S2A — API latency SLO breach (Qdrant down) | **D-01** `dense_lane_outage` | Lexical-only results served |
| S2A — API latency SLO breach (OpenSearch down) | **D-02** `lexical_lane_outage` | Vector-only results served |

Run the drill suite on a schedule and on demand (`make chaos-drill-suite-strict`). The
log gains one line per run, giving a time-stamped history of whether each
degraded-mode contract still held.

## Related

- [Backup and restore runbook](dr-backup-restore.md)
- [Chaos drill catalog](../chaos/README.md)
- [Observability: metrics and alert rules](../observability/README.md)
- [Helm chart](../helm/adcs/README.md)
