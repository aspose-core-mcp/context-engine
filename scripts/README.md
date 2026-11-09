# Scripts Map

A short map of the helper scripts in this repository, grouped by purpose. Paths are relative to the repository root. Where a Make target wraps a script, the target is shown in parentheses. Python scripts that import `adcs` need `PYTHONPATH=./src` (the Make targets set it) unless the project is installed with `pip install -e .`.

Generated reports are written under `reports/` (and some artifacts under `artifacts/`).

## Workspace bootstrap
- `scripts/bootstrap/workspace/setup_python_env.sh` (`make setup-python-env`)
  - Creates `.venv` if it is missing, upgrades `pip`/`setuptools`/`wheel`, and installs the project in editable mode with the `dev` extras.

## Environment checks
- `scripts/checks/environment/check_prereqs.sh` (`make check-prereqs`)
  - Checks local prerequisites (Python 3 version, `git`, `docker`, plus optional tools such as `npm`/`pnpm`, `kubectl`, `helm`, `make` and `jq`) and reports each as OK, WARN or FAIL.
- `scripts/checks/environment/smoke_compose_stack.py` (`make smoke`)
  - Smoke check for the full Docker Compose stack: waits for the API `/healthz` and `/readyz` endpoints (`ADCS_SMOKE_BASE_URL`, default `http://localhost:8080`).
- `scripts/checks/environment/smoke_infra_services.py` (`make infra-smoke`)
  - Smoke check for the supporting services in Docker (PostgreSQL, Valkey, RabbitMQ, Qdrant, OpenSearch) without running the API or worker in containers.

## Kubernetes packaging and disaster recovery
- `scripts/checks/k8s/verify_helm_packaging.py` (`make k8s-packaging-gates`)
  - Verifies the production packaging baseline of the Helm chart in `infra/helm/adcs/` (API / MCP gateway / worker / scheduler, HPA / PDB / probes / resources, split ingresses, network policy); `--output-json` writes a machine-readable result for CI.
- `scripts/checks/k8s/run_dr_recovery_smoke.py` (`make dr-recovery-smoke`)
  - Runs the DR smoke workflow `backup -> restore -> verify` and writes `reports/dr/recovery-smoke.json` and `reports/dr/recovery-smoke.log`. See the [backup/restore runbook](../infra/runbooks/dr-backup-restore.md).

## Deployment checks
- `scripts/checks/deploy/run_postdeploy_smoke.py` (`make deploy-smoke DEPLOY_SMOKE_BASE_URL=<url>`)
  - Post-deploy smoke checks against `/healthz`, `/readyz` and `/v1/status`; writes `reports/deploy/smoke-report.json` and `.log`.
- `scripts/checks/deploy/evaluate_canary_rollout.py` (`make deploy-canary-gate`)
  - Evaluates the latest smoke report against `config/canary-policy.json` and emits a go/rollback decision to `reports/deploy/canary-evaluation.json` and `.log`.

## Quality gates and release readiness
- `scripts/checks/quality/build_golden_eval_inputs.py` (`make quality-build-eval-inputs`)
  - Builds the deterministic quality-gate corpus and golden dataset (`artifacts/quality-gates/`) from publish-grade staging artifacts.
- `scripts/checks/quality/run_golden_dataset_eval.py` (`make acceptance-eval`)
  - Deterministic golden-dataset evaluation; writes `reports/quality-gates/evaluation-summary.json` and `.log`.
- `scripts/checks/quality/run_accuracy_matrix.py` (`make quality-accuracy-matrix`)
  - Unified accuracy matrix comparing the current corpus against a stale baseline corpus; writes `reports/quality-gates/accuracy-matrix.json` and `.log`.
- `scripts/checks/quality/run_perf_profiles.py` (`make perf-gates`, `make perf-gates-soak`, `make perf-gates-capacity`)
  - Runs the local sustained/burst/soak performance profiles (and a capacity profile); writes `reports/quality-gates/perf-summary*.json` and `.log`. Budgets on top of these results are enforced by the [perf + cost budget gate](perf/README.md).
- `scripts/checks/quality/build_release_readiness.py` (`make release-readiness`, `make release-readiness-preprod`)
  - Combines the evaluation and perf summaries into `reports/quality-gates/release-readiness-summary*.json` and `.log`. `make acceptance-gates` / `make acceptance-gates-preprod` run the whole chain.
- `scripts/checks/quality/run_release_go_no_go.py` (`make release-go-no-go`)
  - Builds a single go/no-go summary from the evaluation, perf and release-readiness reports plus the Helm packaging and DR smoke results; writes `reports/quality-gates/go-no-go-summary.json` and `.log`.
- `scripts/checks/quality/run_mutation_baseline.py` (`make mutation-test`, `make mutation-test-strict`, `make mutation-test-summary`)
  - Mutation-testing baseline via mutmut 3.x (install with `pip install -e ".[mutation]"`); writes `reports/quality-gates/mutation-baseline.json`. `--strict --min-kill-rate <rate>` enforces a kill-rate floor and `--skip-run` re-parses an existing run. A full run takes hours.
- `scripts/checks/quality/run_live_retrieval_eval.py`
  - Runs the golden dataset (`artifacts/quality-gates/golden_dataset.json`) against live Qdrant/OpenSearch backends with the configured embeddings; writes `reports/quality-gates/live-retrieval-eval.json`.
- `scripts/coverage/check_high_risk_coverage.py` (`make test-coverage-gate`)
  - Reads a Cobertura XML report (`reports/coverage/coverage.xml`) and fails if any high-risk module listed in `scripts/coverage/high_risk_modules.json` is below its minimum line coverage.

## Scale readiness
- `scripts/checks/scale/verify_multi_product_readiness.py` (`make multi-product-readiness`)
  - Checks multi-product readiness against the real source registry: number of products, a `docs`+`apiref` pair for each product, completeness of layout detection, and the active index topology profile (`config/index-topology-policy.json`). Writes `reports/scale/multi-product-readiness.json`.


## Performance and cost budgets
- `scripts/perf/measure_llm_cost_surface.py` (`make measure-cost-surface`)
  - Counts LLM call sites per module via AST inspection; writes `reports/quality-gates/cost-summary.json`.
- `scripts/perf/enforce_perf_budgets.py` (`make perf-budget-gate`)
  - Compares perf and cost measurements against `config/perf/budgets.yaml`. See [`perf/README.md`](perf/README.md).

## Chaos / DR drills
- `scripts/chaos/run_drill_suite.py` and `scripts/chaos/drills/` (`make chaos-drill-suite`, `make chaos-drill-suite-strict`)
  - Deterministic fault-injection drills (retrieval lane outages and timeouts, snapshot rollback, DR backup/restore); results go to `reports/chaos/`. See [`infra/chaos/README.md`](../infra/chaos/README.md).

## Quality loop
- `scripts/quality_loop/run_cycle.py` (`make quality-loop-cycle`, `make quality-loop-cycle-quiet`)
  - Runs one judge → diagnose → propose → guard cycle of the quality-improvement loop on a deterministic synthetic sample set; writes `reports/quality-loop/audit-log.jsonl`, `reports/quality-loop/last-summary.json` and per-cycle detail under `reports/quality-loop/cycles/`. See [`docs/quality-loop.md`](../docs/quality-loop.md).

## Sources / Registry (legacy workflow)

> **For new deployments, use [plugin-based ingestion](../docs/engine-only.md).** The source-registry and source-submodule workflow below is retained as a legacy path for existing deployments. Its configuration is separate from external plugin manifests; these synchronization tools do not prepare plugin-defined source workspaces. Prepare sources using the selected plugin's guide, then ingest with `adcs-platform-ingest`.

- `scripts/sources/registry/sync_source_repos.py` (`make source-validate`, `make source-sync`, `make source-update`)
  - Validates the source registry (`config/source-repositories.yaml` by default, JSON also supported) and validates, syncs or updates the corresponding git submodules (`--mode validate|sync|update`).
- `scripts/ops/register_docs_repo.py`
  - Inserts a new documentation or API-reference repository entry into `config/source-repositories.yaml` without reformatting the rest of the file, then checks that the registry still loads; idempotent for an existing `repo_id`.

## Sources / Layout
- `scripts/sources/layout/detect_source_layouts.py` (`make source-detect-layouts`, `make source-detect-layouts-write`)
  - Detects the layout of Hugo source trees (`docs`/`apiref`); with `--write` it records the result in the registry (YAML/JSON).

## LLM proxy
- `scripts/llm_proxy/live_acceptance.py`
  - Live acceptance check for the tool-aware LLM proxy: sends N identical tool-bearing chat-completion requests to an OpenAI-compatible endpoint (`OPENAI_BASE_URL`, `OPENAI_API_KEY`), once streamed and once non-streamed, and reports the empty-response rate of each. Exits non-zero if the non-streamed path returns any empty responses.

## Operational / Manual (ad-hoc)

These scripts are not wrapped by Make targets — they are operator utilities for manual runs (recovery, full re-ingestion, live API evaluation, end-to-end checks). Most have a docstring with usage instructions.

### Ingestion
- `scripts/clone_and_ingest.sh`
  - Bootstrap: shallow-initialises all registered git submodules (`source-repo-apiref/*`, `source-repo-docs/*`), resets the ingestion checkpoint (keeping a timestamped backup) and starts a full ingestion via `scripts/run_full_ingestion.py`. Use it for a fresh checkout or after wiping the sources.
- `scripts/run_full_ingestion.py`
  - Resilient full-catalog ingestion with checkpoint/resume. Runs every available repository through the ingestion pipeline; progress goes to `logs/ingestion_progress.log`, the checkpoint to `logs/ingestion_checkpoint.json`. Run it with `nohup` for long runs.
- `scripts/parallel_ingest.py`
  - Multi-worker, fault-tolerant ingestion using the same checkpoint file (`ADCS_INGEST_WORKERS`, default 4; `ADCS_EMBEDDING_BATCH_SIZE`, default 64; `ADCS_REPO_TIMEOUT_SECONDS`, default 3600). It does not wire in the Postgres API-reference symbol store, so use `scripts/ops/reingest_apiref_local.py` for apiref repositories.
- `scripts/ops/reingest_apiref_local.py`
  - Sequential, resumable re-ingestion of apiref repositories into the local Postgres structured symbol store (no embeddings, no Qdrant/OpenSearch); `--repos ...` or `--all`, with progress reported through a marker file (default `logs/reingest_apiref.marker.json`). Run it with `APIREF_STRUCTURED_STORE_ENABLED=true`, as shown in its usage example.

### Recovery and index maintenance
- `scripts/backfill_opensearch_from_qdrant.py`
  - **Recovery**: rebuilds the OpenSearch lexical docs index from Qdrant payloads (collection `DOCS_VECTOR_COLLECTION`, default `docs_dense_en_v1`) and sets up the `docs_lex_v1_active` alias the retrieval layer expects. It is the lexical-lane step of a DR restore and is also useful when the OpenSearch volume is lost. API reference data is served from the Postgres structured store, so the retired `apiref_dense_v1` collection is not backfilled.
- `scripts/drop_apiref_indexes.py`
  - Drops the legacy apiref Qdrant collection (`apiref_dense_v1`) and OpenSearch alias (`apiref_lex_v1_active`, with its backing indices) after the Postgres cutover. Dry-run by default (`--apply` to execute); refuses to run unless the Postgres store already holds apiref symbols (override with `--force`, not recommended).

### Evaluation and end-to-end checks
- `scripts/run_golden_eval.py`
  - Live API golden-dataset evaluation: sends curated golden queries to a running ADCS server (`--api-url`) and checks relevance ≥ 80 %, p95 latency ≤ 1200 ms, citation coverage = 100 % and version accuracy ≥ 95 %.
- `scripts/ops/e2e_smoke.py`
  - End-to-end smoke test against a running API (local full stack): health, the structured API-reference REST endpoints, and the MCP tool surface over HTTP. Exits non-zero if a hard check fails.
- `scripts/ops/e2e_detailed.py`
  - Detailed end-to-end tests against a running local API: multi-language scope isolation, case-insensitive FQN lookup, overload/facet response structure, `list_members` on namespaces, cross-product search and edge cases.
- `scripts/ops/bench_apiref.py`
  - Latency/throughput benchmark for the structured API-reference endpoints (p50/p95/p99 and requests per second per access path).
- `scripts/ops/verify_harness.py`
  - Verifies the two-source retrieval harness (docs via the live `/v1/docs:query` endpoint, API reference via the Postgres store) on live data, asserting that the fused results contain both docs and apiref hits.
