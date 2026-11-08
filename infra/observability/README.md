# Observability — Metrics and Prometheus Rules

ADCS exposes Prometheus metrics at `/metrics` and ships a set of alert rules that query
them.

## Layout

```
infra/observability/
├── prometheus/
│   └── adcs-alerts.yaml   # Sev1-Sev3 alerts and SLO burn-rate alerts
└── README.md (this file)
```

## The `/metrics` endpoint

Every API process serves `GET /metrics` in the Prometheus text format. With the Helm
chart that includes both the `api` and `mcp-gateway` pods (Services `<release>-api`
and `<release>-mcp-gateway`, port name `http`). The worker and scheduler serve no HTTP;
ingestion SLIs are read from PostgreSQL by the API at scrape time.

Series rendered by `src/adcs/api/metrics.py` are held in process memory: each is per pod
and starts from zero when the pod restarts, and ratios such as
`adcs_citation_missing_ratio` are cumulative since start-up. Series rendered by
`src/adcs/api/ingestion_slis.py` are read from PostgreSQL on every scrape.

### Metric families

Rendered by [`src/adcs/api/metrics.py`](../../src/adcs/api/metrics.py):

| Metric | Type | Labels |
|--------|------|--------|
| `adcs_http_requests_total` | counter | `method`, `path`, `status` |
| `adcs_http_request_duration_seconds` | histogram | `method`, `path`, `le` |
| `adcs_http_request_latency_seconds_sum` | counter | `method`, `path` |
| `adcs_http_request_latency_seconds_count` | counter | `method`, `path` |
| `mcp_sessions_by_revision` | counter | `revision` |
| `mcp_negotiation_total` | counter | — |
| `mcp_negotiation_fallback_total` | counter | `requested_revision`, `negotiated_revision`, `fallback_reason` |
| `mcp_negotiation_fail_ratio` | gauge | — |
| `adcs_abuse_guard_decisions_total` | counter | `mode`, `decision` |
| `adcs_retrieval_responses_total` | counter | `confidence_level` |
| `adcs_retrieval_confidence_low_ratio` | gauge | — |
| `adcs_retrieval_results_total` | counter | — |
| `adcs_retrieval_results_missing_citation_total` | counter | — |
| `adcs_citation_missing_ratio` | gauge | — |
| `adcs_semantic_review_failfast_block_count` | counter | — |
| `adcs_retrieval_stage_duration_seconds` | histogram | `stage`, `le` |

Rendered by [`src/adcs/api/ingestion_slis.py`](../../src/adcs/api/ingestion_slis.py):

| Metric | Type | Labels |
|--------|------|--------|
| `adcs_index_snapshots_total` | gauge | — |
| `adcs_index_active_snapshots` | gauge | — |
| `adcs_index_freshness_seconds` | gauge | — |
| `adcs_index_freshness_newest_seconds` | gauge | — |
| `adcs_ingestion_publish_events_total` | counter | `event_type` |
| `adcs_ingestion_sli_collection_errors` | gauge | — |

Notes:

- `path` is the raw request path.
- `adcs_retrieval_stage_duration_seconds` appears after the first retrieval, and the
  two `adcs_index_freshness_*` gauges appear only while at least one snapshot is active.
- `adcs_ingestion_sli_collection_errors` above zero means the ingestion series are stale
  or missing for that scrape.
- The container images install `prometheus-client`, which adds the client library's
  default process and Python runtime families and the families declared in
  [`src/adcs/ops/metrics.py`](../../src/adcs/ops/metrics.py).

## Alert rules

[`prometheus/adcs-alerts.yaml`](prometheus/adcs-alerts.yaml) defines:

| Alert | Severity | Condition |
|-------|----------|-----------|
| `ADCSCriticalApiAvailability` | sev1 | Non-5xx share of requests below 95% for 5m |
| `ADCSHighLatencyP95` | sev2 | p95 request latency above 1.8s for 10m |
| `ADCSCitationCoverageBreach` | sev2 | `adcs_citation_missing_ratio` above 0.005 for 60m |
| `ADCSSlo99_9_FastBurn` | sev2 | 99.9% availability SLO burning at 14.4x over 1h and 5m |
| `ADCSLowConfidenceRetrieval` | sev3 | `adcs_retrieval_confidence_low_ratio` above 0.2 for 30m |
| `ADCSAbuseStorm` | sev3 | More than 10 req/s answered with `429` for 5m |
| `ADCSMcpNegotiationFallbackSpike` | sev3 | MCP revision fallbacks above 20% of negotiations for 30m |
| `ADCSPartialPublishBurst` | sev3 | More than 3 partial publishes in 6h |
| `ADCSSlo99_9_SlowBurn` | sev3 | 99.9% availability SLO burning at 6x over 6h and 30m |

Severity labels match the [severity definitions](../runbooks/incident-response-playbooks.md#severity-definitions)
in the incident playbooks, and `runbook_url` annotations link to the matching playbook.

Rules that select `job="adcs-api"` assume both the `api` and `mcp-gateway` pods are
scraped under that job name. Use that job name in your scrape configuration, or edit the
selectors.

## Loading the rules

### Standalone Prometheus

Scrape the API and load the rules file in `prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/rules/adcs-alerts.yaml

scrape_configs:
  - job_name: adcs-api
    metrics_path: /metrics
    static_configs:
      - targets: ["<api-host>:8080"]
```

Mount `infra/observability/prometheus/adcs-alerts.yaml` at that path and reload
Prometheus.

### Prometheus Operator

Wrap the `groups:` list from `adcs-alerts.yaml` in a `PrometheusRule`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: adcs-alerts
  namespace: monitoring
spec:
  groups: []  # paste the groups from adcs-alerts.yaml
```

Add labels that match your Prometheus `ruleSelector`. Scrape the `api` and
`mcp-gateway` Services on port `http`, for example with a `ServiceMonitor` whose
endpoint relabelling sets `job` to `adcs-api`.

## Testing the rules

```bash
# Structural checks: severities, runbook links, exported metrics, durations
PYTHONPATH=./src python3 -m pytest tests/observability

# Syntax check with promtool (part of the Prometheus distribution)
promtool check rules infra/observability/prometheus/adcs-alerts.yaml

# Firing semantics against synthetic series
promtool test rules tests/observability/fixtures/alerts-firing-test.yaml
```

`tests/observability/test_alert_firing_promtool.py` runs both promtool commands and is
skipped when `promtool` is not on `PATH`.

## Adding an alert

1. Emit the metric in the service and add it to the tables above.
2. Add the rule to `adcs-alerts.yaml` with a `severity` label, a `summary` annotation
   and, for Sev1 and Sev2, a `runbook_url` that points at a heading in
   [`infra/runbooks/incident-response-playbooks.md`](../runbooks/incident-response-playbooks.md).
3. Add a firing case to `tests/observability/fixtures/alerts-firing-test.yaml`.
4. Run the tests above.

## Naming conventions

- **Alerts**: `ADCS{PascalCase}` (e.g. `ADCSHighLatencyP95`)
- **Severity labels**: `sev1`, `sev2`, `sev3`, `sev4`
- **Service labels**: `adcs-api`, `retrieval`, `ingestion`

## Related

- [`infra/runbooks/incident-response-playbooks.md`](../runbooks/incident-response-playbooks.md) — playbooks linked from `runbook_url` annotations
- [`docs/architecture.md`](../../docs/architecture.md) — where metrics are produced
