# Test Coverage Matrix

This document maps each major subsystem to its corresponding test files. ADCS has **about 180 pytest modules** spanning unit, integration, contract, chaos, and end-to-end tiers, plus Playwright specs for the admin UI.

For automated coverage execution and reports: `make test`, `make test-coverage`, `make acceptance-gates`, `make release-go-no-go`.

## Test Tiers

| Tier | Tool | Target | Run via |
|------|------|--------|---------|
| Unit | pytest | Module-local logic | `make test` |
| Integration | pytest + Postgres/Qdrant/OpenSearch | Cross-module flows | `make infra-up && make test`; corpus-dependent suites via `make test-live` |
| Contract | pytest (+ Pact) | MCP/REST API contracts | `make webmcp-release-gates`, `make staging-contract-gates`, `make test-contracts-consumer` |
| Acceptance | Python eval scripts + golden dataset | Quality + accuracy + perf | `make acceptance-gates` |
| Release Gate | make + Python scripts | Full pre-ship check | `make release-go-no-go` |
| Chaos / DR drills | Drill runner + pytest drills in `tests/chaos/` | Fault injection, rollback, backup/restore | `make chaos-drill-suite` |
| Frontend E2E | Playwright | Admin UI flows | `cd frontend/admin && npm run test:e2e` |
| Admin UI | Playwright | Admin UI build and end-to-end run | `make admin-ui-regression-gates` |

## Coverage by Subsystem

### Admin API (high-risk)

| Module | Test files |
|--------|------------|
| `src/adcs/api/admin_auth.py` | `tests/test_admin_api_auth.py`, `tests/test_admin_auth_unit.py`, `tests/test_admin_session_cookie_auth.py` |
| `src/adcs/api/admin_keys.py` | `tests/test_admin_keys_api.py` |
| `src/adcs/api/admin_products.py` | `tests/test_admin_products_api.py` |
| `src/adcs/api/admin_snapshots.py` | `tests/test_admin_snapshots_api.py` |
| `src/adcs/api/admin_observability.py` | `tests/test_admin_observability_api.py`, `tests/test_api_observability.py` |
| `src/adcs/api/admin_critical_events.py` | `tests/test_admin_critical_events_api.py`, `tests/test_critical_events_notifications.py` |
| `src/adcs/api/admin_quality_reviews.py` | `tests/test_admin_quality_reviews_api.py` |
| `src/adcs/api/admin_howto.py` | `tests/test_admin_howto_api.py`, `tests/test_howto_override_store.py` |
| `src/adcs/api/admin_system.py` | `tests/test_admin_system_api.py` |
| `src/adcs/admin/config_history.py` | `tests/test_admin_config_history_rollback.py` |

### Retrieval Engine (high-risk)

| Module | Test files |
|--------|------------|
| `src/adcs/retrieval/hybrid_retriever.py` | `tests/test_hybrid_retriever.py`, `tests/test_two_source_end_to_end.py` |
| `src/adcs/retrieval/two_source_retriever.py` | `tests/test_two_source_retriever.py` |
| `src/adcs/retrieval/query_planner.py` | `tests/test_query_planner.py`, `tests/test_query_planner_properties.py` |
| `src/adcs/retrieval/reranker.py` | `tests/test_reranker.py`, `tests/test_reranker_properties.py` |
| `src/adcs/retrieval/context_packer.py` | `tests/test_context_packer.py`, `tests/test_context_packer_properties.py` |
| `src/adcs/retrieval/filter_resolver.py` | `tests/test_filter_resolver.py`, `tests/test_filter_resolver_properties.py` |
| `src/adcs/retrieval/translation_fallback.py` | `tests/test_translation_fallback.py`, `tests/test_translation_fallback_properties.py` |
| `src/adcs/retrieval/release_catalog.py` | `tests/test_release_catalog_properties.py` |
| `list_breaking_changes` diff engine (`src/adcs/api/public_docs_query.py`) | `tests/test_breaking_changes_diff_engine.py` |

### MCP Layer (contract tests required)

| Module | Test files |
|--------|------------|
| `src/adcs/mcp/stdio_server.py` | `tests/test_mcp_transport_matrix.py`, `tests/test_mcp_revision_telemetry.py` |
| `src/adcs/mcp/tool_gateway.py` | `tests/test_mcp_stateless_sessions.py`, `tests/test_apiref_symbol_mcp_rest.py` |
| `src/adcs/mcp/revision_negotiation.py` | `tests/test_mcp_gateway.py`, `tests/test_mcp_stateless_sessions.py` |
| `src/adcs/api/mcp_gateway.py` | `tests/test_mcp_gateway.py`, `tests/test_apiref_symbol_mcp_rest.py` |
| `src/adcs/api/webmcp_*` | `tests/test_webmcp_gateway.py`, `tests/test_webmcp_confirmation.py`, `tests/test_webmcp_write_flow.py` |
| MCP/REST parity (cross-cutting) | `tests/test_mcp_rest_parity_offline.py`, `tests/test_public_rest_parity.py` |

### Ingestion Pipeline

| Module | Test files |
|--------|------------|
| `src/adcs/ingestion/hugo_parser.py` | `tests/test_hugo_markdown_parser.py`, `tests/test_hugo_parser_properties.py` |
| `src/adcs/ingestion/normalized_document.py` | `tests/test_normalized_document_validator.py`, `tests/test_hugo_to_normalized_document_converter.py` |
| `src/adcs/ingestion/chunking.py` | `tests/test_chunking_policy.py` |
| `src/adcs/ingestion/source_*_orchestrator.py` | `tests/test_source_*_orchestrator.py`, `tests/test_source_*_admin_api.py` |
| `src/adcs/ingestion/canonical_url_mapping.py` | `tests/test_canonical_url_mapping.py` |
| `src/adcs/ingestion/metadata_quarantine.py` | `tests/test_metadata_quarantine.py` |
| `src/adcs/ingestion/source_registry.py` | `tests/test_source_registry_*.py` |
| `src/adcs/ingestion/staging_store.py` | `tests/test_staging_store.py` |

### Indexing

| Module | Test files |
|--------|------------|
| `src/adcs/indexing/publish_orchestrator.py` | `tests/test_index_publish_orchestrator.py`, `tests/test_ingestion_publish_policy.py` |
| `src/adcs/indexing/embedding_provider.py` | `tests/test_index_publish_orchestrator.py` |
| `src/adcs/indexing/snapshot_registry.py` | `tests/test_snapshot_registry.py` |
| `src/adcs/indexing/snapshot_cleanup.py` | `tests/test_snapshot_cleanup_service.py` |
| `src/adcs/indexing/apiref_symbol_store.py`, `apiref_symbol_publisher.py` | `tests/test_apiref_symbol_store.py`, `tests/test_apiref_symbol_publisher.py`, `tests/test_apiref_full_chain.py` |

### Quality Gates

| Module | Test files |
|--------|------------|
| `src/adcs/quality_gates/golden_eval.py` | `tests/test_quality_gates.py`, `tests/test_url_matching.py` |
| `src/adcs/quality_gates/perf_profiles.py` | `tests/test_quality_gates.py` |
| `src/adcs/quality_gates/release_readiness.py` | `tests/test_quality_gates.py` |
| `src/adcs/quality_gates/go_no_go.py` | `tests/test_go_no_go_gate.py` |
| `src/adcs/admin/quality_reviews.py` | `tests/test_admin_quality_reviews_api.py` |

### Quality Loop

| Module | Test files |
|--------|------------|
| `src/adcs/quality_loop/` | `tests/quality_loop/` (per-agent, coordinator, calibration, message-bus, and audit-replay tests) |

### Worker / Async

| Module | Test files |
|--------|------------|
| `src/adcs/worker/celery_app.py` | `tests/test_worker_bootstrap.py` |
| `src/adcs/worker/task_dispatcher.py` | `tests/test_worker_task_dispatcher.py` |

### Ops

| Module | Test files |
|--------|------------|
| `src/adcs/ops/backup_restore.py` | `tests/test_backup_restore_service.py` |
| `src/adcs/ops/critical_events.py`, `notifications.py` | `tests/test_critical_events_notifications.py` |
| `src/adcs/ops/snapshot_rollback_audit.py` | No dedicated test module; rollback flows are exercised by `tests/test_admin_snapshots_api.py` |
| `src/adcs/ops/observability_*.py` | `tests/test_api_observability.py`, `tests/test_admin_observability_api.py`, `tests/test_observability_control_plane.py` |
| `src/adcs/ops/privacy.py` | `tests/test_privacy.py` |
| Prometheus alert rules (`infra/observability/prometheus/adcs-alerts.yaml`) | `tests/observability/test_alert_rules.py` (structure), `tests/observability/test_alert_firing_promtool.py` (firing, skipped without `promtool`) |
| Chaos / DR drills | `tests/chaos/` (dense, lexical, and dual lane outages; lane timeout; snapshot rollback; DR backup/restore) |

### Frontend (Playwright E2E)

`frontend/admin/e2e/`:
- `mono-smoke.spec.ts` — admin console shell (default Health section and sidebar, command palette, hash-routed section navigation, theme and density toggles, status-pill accessibility) and the public `/status` and `/integrations` pages

## High-Risk Component Coverage Goals

`make test-coverage-gate` enforces **≥80% line coverage** on every module listed in `scripts/coverage/high_risk_modules.json` (run `make test-coverage` first to produce `reports/coverage/coverage.xml`). The targets below are the longer-term goals.

| Component | Risk | Target Coverage | Tests |
|-----------|------|-----------------|-------|
| Admin auth | Critical (auth bypass) | ≥90% | See Admin API |
| Retrieval pipeline | Critical (incorrect results) | ≥85% | See Retrieval Engine |
| MCP layer | Critical (contract drift) | ≥85% | See MCP Layer |
| Publish orchestrator | High (data integrity) | ≥85% | See Indexing |
| Quality gates | High (release safety) | ≥80% | See Quality Gates |
| Source registry | High (config drift) | ≥80% | `tests/test_source_registry_*.py` (3 files) |
| Embedding provider | Medium | ≥75% | See Indexing |
| Frontend E2E | Medium (UX regression) | All critical paths | `frontend/admin/e2e/` |

## Mandatory Pre-Merge Checks

All four must pass before merging:

1. `make lint` — Ruff lint over `src/` + `tests/`
2. `make typecheck` — mypy over `src/` (configured in `pyproject.toml`)
3. `make test` — full pytest suite (tests marked `live` are excluded by default)
4. `make source-validate` — source registry validation

## Acceptance Eval Suites

Per `make acceptance-gates`:

- **Quality**: golden dataset (top-k relevance ≥80%, version accuracy = 100% under strict_version)
- **Performance**: latency p50 ≤350 ms, p95 ≤1200 ms
- **Accuracy**: citation coverage 100%, no hallucinated symbols
- **MCP/REST parity**: contract diff = 0
- **Compatibility**: 3 MCP revisions accepted, fallback to nearest

## Coverage Reports

Generated artifacts (under `reports/quality-gates/`):

- `accuracy-matrix.json` — top-k relevance × version accuracy matrix
- `evaluation-summary.json` — aggregate eval pass/fail
- `live-retrieval-eval.json` — live system eval results
- `perf-summary.json` — latency distributions (p50/p95/p99)
- `release-readiness-summary.json` — go/no-go decision artifact

## How to Run a Single Test

```bash
PYTHONPATH=./src python3 -m pytest tests/test_admin_api_auth.py -v

# Single test:
PYTHONPATH=./src python3 -m pytest tests/test_admin_api_auth.py::test_admin_api_enforces_write_scope_and_product_scope_for_mutations -v
```

## Mutation Testing

Mutation testing measures the *effectiveness* of the test suite — not
just whether tests run, but whether they actually catch behavioural
regressions. The tool is `mutmut` ≥ 3.5.0 (configured in
`pyproject.toml` `[tool.mutmut]`, installed via the `mutation` extra).

**Scope:** mutmut 3.x requires `paths_to_mutate` to cover the whole
`src/adcs/` package (the test suite imports `adcs.config`), so a sweep is
narrowed at invocation time via `mutmut run <MUTANT_NAMES>`. The baseline
prioritises `quality_loop/audit_replay.py`, `quality_loop/diagnosis_agent.py`,
and `admin/tenant_persistence.py`; scope expands to `src/adcs/retrieval/`
and `src/adcs/quality_gates/` as the kill rate on the baseline scope
stabilises.

**Cadence:** scheduled (for example weekly) or on demand — never on every
pull request. The baseline run takes 30–90 minutes, and a full sweep of the
package takes hours.

**Floor:** `make mutation-test-strict` enforces a kill-rate floor of
**0.80**. Below that, it exits non-zero; the report
(`reports/quality-gates/mutation-baseline.json`) records the kill-rate
baseline for triage.

**Running locally:**

```bash
pip install -e ".[dev,mutation]"     # one-time
make mutation-test                    # runs mutmut, reports baseline
make mutation-test-strict             # same + enforces 0.80 floor
make mutation-test-summary            # skip the run, re-parse existing mutants/
```

**Artifacts:**

- `reports/quality-gates/mutation-baseline.json` — machine-readable kill-rate baseline
- `reports/quality-gates/mutation-baseline.txt` — human-readable table
- `mutants/` — mutmut working state (worth keeping as a CI artifact)

Mutation testing turns test volume into harder evidence: it shows which
mutations the suite catches and which slip through.

## See Also

- [Architecture](architecture.md) — the components these tests cover
- [Quality loop](quality-loop.md) — the subject of `tests/quality_loop/`
- [Observability](../infra/observability/README.md) — the metrics and alert rules covered by `tests/observability/`
