# Recipes use `set -o pipefail`, which POSIX sh does not have. make defaults to
# /bin/sh, which is dash on Debian but bash in sh-mode on macOS, so pin bash to
# get the same behaviour everywhere.
SHELL := /bin/bash

.PHONY: setup-python-env check-prereqs install-dev lint typecheck test test-coverage test-coverage-gate update-coverage-baseline test-contracts-consumer test-contracts-provider pact-broker-up pact-broker-down measure-cost-surface perf-budget-gate chaos-drill-suite chaos-drill-suite-strict quality-loop-cycle quality-loop-cycle-quiet admin-release-gates admin-ui-regression-gates chromium-headed chromium-debug webmcp-release-gates webmcp-browser-e2e staging-contract-gates k8s-packaging-gates dr-recovery-smoke deploy-smoke deploy-canary-gate release-go-no-go mutation-test mutation-test-strict mutation-test-summary run run-worker run-dev test-unit up down logs smoke docker-up docker-down docker-logs docker-smoke infra-up infra-down infra-logs infra-smoke source-validate source-sync source-update source-detect-layouts source-detect-layouts-write multi-product-readiness quality-build-eval-inputs quality-accuracy-matrix acceptance-eval perf-gates perf-gates-soak perf-gates-capacity release-readiness release-readiness-preprod acceptance-gates acceptance-gates-preprod

PYTHONPATH ?= ./src
COMPOSE_FILE ?= docker-compose.integration.yml
COMPOSE_PROJECT_NAME ?= adcs-local
DOCKER_COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)
COMPOSE_ENV_FILE ?= .env.compose.example
COMPOSE_CMD = ADCS_COMPOSE_ENV_FILE=$(COMPOSE_ENV_FILE) $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) -p $(COMPOSE_PROJECT_NAME)
INFRA_SERVICES ?= postgres redis rabbitmq qdrant opensearch
QUALITY_GATES_DATASET ?= artifacts/quality-gates/golden_dataset.json
QUALITY_GATES_CORPUS ?= artifacts/quality-gates/retrieval_corpus.json
QUALITY_GATES_STALE_CORPUS ?= artifacts/quality-gates/retrieval_corpus_stale.json
QUALITY_GATES_PROFILES ?= artifacts/quality-gates/perf_profiles.json
QUALITY_GATES_REPORT_DIR ?= reports/quality-gates
QUALITY_GATES_PHASE ?= mvp
CHROMIUM_UI_WORKERS ?= 1
DEPLOY_SMOKE_BASE_URL ?= http://127.0.0.1:8080

setup-python-env:
	bash ./scripts/bootstrap/workspace/setup_python_env.sh

check-prereqs:
	bash ./scripts/checks/environment/check_prereqs.sh

install-dev:
	python3 -m pip install -e ".[dev]"

lint:
	PYTHONPATH=$(PYTHONPATH) python3 -m ruff check src tests

typecheck:
	PYTHONPATH=$(PYTHONPATH) python3 -m mypy src

test:
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest

# Corpus-dependent suites, excluded from `make test` by the default `-m 'not live'`.
# ADCS_REQUIRE_LIVE_SURFACE turns "backend unreachable" from a silent skip into a
# failure, so an unavailable surface is reported instead of passing as green.
test-live:
	ADCS_REQUIRE_LIVE_SURFACE=true PYTHONPATH=$(PYTHONPATH) python3 -m pytest -m live -v

# ----------------------------------------------------------------------------
# Coverage targets
# ----------------------------------------------------------------------------
# - test-coverage         — run all tests with coverage, generate XML+HTML
# - test-coverage-gate    — enforce >=80% on high-risk modules
# - update-coverage-baseline — refresh baseline after intentional changes
# ----------------------------------------------------------------------------

test-coverage:
	@mkdir -p reports/coverage
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest \
		--cov=src/adcs \
		--cov-report=xml:reports/coverage/coverage.xml \
		--cov-report=html:reports/coverage/html \
		--cov-report=term

test-coverage-gate:
	@mkdir -p reports/coverage
	PYTHONPATH=$(PYTHONPATH) python3 scripts/coverage/check_high_risk_coverage.py \
		--xml reports/coverage/coverage.xml \
		--config scripts/coverage/high_risk_modules.json

update-coverage-baseline:
	@mkdir -p reports/coverage
	cp reports/coverage/coverage.xml reports/coverage/baseline.xml
	@echo "Baseline updated: reports/coverage/baseline.xml."

# ----------------------------------------------------------------------------
# Pact contract tests (self-hosted broker)
# ----------------------------------------------------------------------------
# - test-contracts-consumer  — generate pacts/{consumer}-{provider}.json
# - test-contracts-provider  — verify pact JSON against running ADCS API
# - pact-broker-up           — start local self-hosted broker
# - pact-broker-down         — stop local broker
# Requires extras: pip install -e ".[dev,contracts]"
# ----------------------------------------------------------------------------

test-contracts-consumer:
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest tests/contracts/consumer/ -v

test-contracts-provider:
	PYTHONPATH=$(PYTHONPATH) python3 tests/contracts/provider/verify_adcs_provider.py \
		--pact pacts/ai-ide-consumer-adcs-mcp-gateway.json \
		--provider-url $${ADCS_API_URL:-http://localhost:8080}

pact-broker-up:
	@test -f infra/pact-broker/.env || cp infra/pact-broker/.env.example infra/pact-broker/.env
	docker compose --env-file infra/pact-broker/.env -f infra/pact-broker/docker-compose.yml up -d
	@echo "Broker UI: http://localhost:9292 (credentials from infra/pact-broker/.env)"

pact-broker-down:
	@test -f infra/pact-broker/.env || cp infra/pact-broker/.env.example infra/pact-broker/.env
	docker compose --env-file infra/pact-broker/.env -f infra/pact-broker/docker-compose.yml down

# ----------------------------------------------------------------------------
# Perf + cost budget gates.
# - measure-cost-surface — count LLM call sites per module (writes cost-summary.json)
# - perf-budget-gate     — compare measurements against config/perf/budgets.yaml
# ----------------------------------------------------------------------------

measure-cost-surface:
	@mkdir -p reports/quality-gates
	PYTHONPATH=$(PYTHONPATH) python3 scripts/perf/measure_llm_cost_surface.py

perf-budget-gate:
	PYTHONPATH=$(PYTHONPATH) python3 scripts/perf/enforce_perf_budgets.py --strict

# ----------------------------------------------------------------------------
# Chaos / DR fault-injection drills.
# - chaos-drill-suite        — run every drill, append to reports/chaos/drill-log.jsonl
# - chaos-drill-suite-strict — same but DEGRADED counts as failure (release-gate posture)
# ----------------------------------------------------------------------------

chaos-drill-suite:
	@mkdir -p reports/chaos/drills
	PYTHONPATH=$(PYTHONPATH):. python3 scripts/chaos/run_drill_suite.py

chaos-drill-suite-strict:
	@mkdir -p reports/chaos/drills
	PYTHONPATH=$(PYTHONPATH):. python3 scripts/chaos/run_drill_suite.py --strict

# ----------------------------------------------------------------------------
# Continuous quality-improvement multi-agent loop.
# - quality-loop-cycle       — one cycle of judge -> diagnose -> propose -> guard
# - quality-loop-cycle-quiet — same but suppress info logs (CI-friendly)
# ----------------------------------------------------------------------------

quality-loop-cycle:
	@mkdir -p reports/quality-loop/cycles
	PYTHONPATH=$(PYTHONPATH) python3 scripts/quality_loop/run_cycle.py

quality-loop-cycle-quiet:
	@mkdir -p reports/quality-loop/cycles
	PYTHONPATH=$(PYTHONPATH) python3 scripts/quality_loop/run_cycle.py --quiet

admin-release-gates:
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest \
		tests/test_admin_api_auth.py \
		tests/test_admin_critical_events_api.py \
		tests/test_admin_registries_analytics_api.py \
		tests/test_admin_snapshots_api.py \
		tests/test_admin_observability_api.py \
		tests/test_admin_release_gates.py

admin-ui-regression-gates:
	cd frontend/admin && npm ci && npm run build && npm run test:e2e

chromium-headed:
	cd frontend/admin && npx playwright test -c playwright.config.ts --project=chromium --headed --workers=$(CHROMIUM_UI_WORKERS)

chromium-debug:
	cd frontend/admin && npx playwright test -c playwright.config.ts --project=chromium --debug --workers=1

webmcp-release-gates:
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest \
		tests/test_webmcp_gateway.py \
		tests/test_webmcp_confirmation.py \
		tests/test_webmcp_write_flow.py

webmcp-browser-e2e:
	cd frontend/admin && npm ci && npm run test:e2e

staging-contract-gates:
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest \
		tests/test_staging_store.py \
		tests/test_source_hugo_normalization_orchestrator.py::test_source_hugo_normalization_orchestrator_parses_repo_by_layout_metadata \
		tests/test_source_hugo_normalization_orchestrator.py::test_source_hugo_normalization_orchestrator_replays_from_staging_without_markdown_parse \
		tests/test_source_hugo_normalization_orchestrator.py::test_source_hugo_normalization_validate_only_keeps_publish_replay_snapshot \
		tests/test_source_hugo_normalization_orchestrator.py::test_source_hugo_normalization_orchestrator_replay_integrity_error_falls_back_and_emits_event \
		tests/test_source_hugo_normalization_admin_api.py::test_source_hugo_normalization_api_trigger_list_get

k8s-packaging-gates:
	python3 ./scripts/checks/k8s/verify_helm_packaging.py
	PYTHONPATH=$(PYTHONPATH) python3 -m pytest tests/test_k8s_packaging.py

dr-recovery-smoke:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/k8s/run_dr_recovery_smoke.py

deploy-smoke:
	python3 ./scripts/checks/deploy/run_postdeploy_smoke.py --base-url "$(DEPLOY_SMOKE_BASE_URL)"

# Mutation-testing baseline (30–90 min). Install via
# `pip install -e ".[mutation]"` first; config in pyproject.toml [tool.mutmut].
mutation-test:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_mutation_baseline.py

# Same, but enforces the configured kill-rate floor.
mutation-test-strict:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_mutation_baseline.py --strict --min-kill-rate 0.80

# Re-parse an existing `mutants/` state without re-running mutmut.
# Useful for iterating on the report shape locally.
mutation-test-summary:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_mutation_baseline.py --skip-run

deploy-canary-gate:
	python3 ./scripts/checks/deploy/evaluate_canary_rollout.py

release-go-no-go:
	$(MAKE) acceptance-gates-preprod
	python3 ./scripts/checks/k8s/verify_helm_packaging.py --output-json reports/k8s/helm-packaging.json
	$(MAKE) dr-recovery-smoke
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_release_go_no_go.py --phase preprod

run:
	PYTHONPATH=$(PYTHONPATH) python3 -m uvicorn adcs.api.main:app --host 0.0.0.0 --port 8080

run-worker:
	PYTHONPATH=$(PYTHONPATH) python3 -m celery -A adcs.worker.celery_app:celery_app worker --loglevel=info

run-dev: run

test-unit: test

up:
	$(COMPOSE_CMD) up -d --build

down:
	$(COMPOSE_CMD) down --remove-orphans

logs:
	$(COMPOSE_CMD) logs --tail=200 -f

smoke:
	$(COMPOSE_CMD) ps
	python3 ./scripts/checks/environment/smoke_compose_stack.py

docker-up: up

docker-down: down

docker-logs: logs

docker-smoke: smoke

infra-up:
	$(COMPOSE_CMD) up -d $(INFRA_SERVICES)

infra-down:
	$(COMPOSE_CMD) stop $(INFRA_SERVICES)

infra-logs:
	$(COMPOSE_CMD) logs --tail=200 -f $(INFRA_SERVICES)

infra-smoke:
	python3 ./scripts/checks/environment/smoke_infra_services.py

source-validate:
	python3 ./scripts/sources/registry/sync_source_repos.py --mode validate

source-sync:
	python3 ./scripts/sources/registry/sync_source_repos.py --mode sync

source-update:
	python3 ./scripts/sources/registry/sync_source_repos.py --mode update

source-detect-layouts:
	python3 ./scripts/sources/layout/detect_source_layouts.py

source-detect-layouts-write:
	python3 ./scripts/sources/layout/detect_source_layouts.py --write

multi-product-readiness:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/scale/verify_multi_product_readiness.py

quality-build-eval-inputs:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/build_golden_eval_inputs.py --seed-corpus "$(QUALITY_GATES_CORPUS)" --seed-dataset "$(QUALITY_GATES_DATASET)" --output-corpus "$(QUALITY_GATES_CORPUS)" --output-stale-corpus "$(QUALITY_GATES_STALE_CORPUS)" --output-dataset "$(QUALITY_GATES_DATASET)" --output-summary-json "$(QUALITY_GATES_REPORT_DIR)/eval-inputs-summary.json" --output-summary-log "$(QUALITY_GATES_REPORT_DIR)/eval-inputs-summary.log"

quality-accuracy-matrix:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_accuracy_matrix.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --stale-corpus "$(QUALITY_GATES_STALE_CORPUS)" --phase "$(QUALITY_GATES_PHASE)" --output-json "$(QUALITY_GATES_REPORT_DIR)/accuracy-matrix.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/accuracy-matrix.log"

acceptance-eval: quality-build-eval-inputs
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_golden_dataset_eval.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --phase "$(QUALITY_GATES_PHASE)" --output-json "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary.log"

perf-gates: quality-build-eval-inputs
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_perf_profiles.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --profiles "$(QUALITY_GATES_PROFILES)" --phase "$(QUALITY_GATES_PHASE)" --output-json "$(QUALITY_GATES_REPORT_DIR)/perf-summary.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/perf-summary.log"

perf-gates-soak: quality-build-eval-inputs
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_perf_profiles.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --profiles "$(QUALITY_GATES_PROFILES)" --phase "$(QUALITY_GATES_PHASE)" --profile soak --output-json "$(QUALITY_GATES_REPORT_DIR)/perf-summary-soak.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/perf-summary-soak.log"

perf-gates-capacity: quality-build-eval-inputs
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_perf_profiles.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --profiles "$(QUALITY_GATES_PROFILES)" --phase preprod --profile capacity-100-products --output-json "$(QUALITY_GATES_REPORT_DIR)/perf-summary-capacity.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/perf-summary-capacity.log"

release-readiness:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/build_release_readiness.py --evaluation "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary.json" --perf "$(QUALITY_GATES_REPORT_DIR)/perf-summary.json" --phase "$(QUALITY_GATES_PHASE)" --output-json "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary.log"

release-readiness-preprod:
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/build_release_readiness.py --evaluation "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary.json" --perf "$(QUALITY_GATES_REPORT_DIR)/perf-summary-capacity.json" --phase preprod --output-json "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary-preprod.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary-preprod.log"

acceptance-gates: acceptance-eval perf-gates quality-accuracy-matrix release-readiness

acceptance-gates-preprod:
	$(MAKE) quality-build-eval-inputs QUALITY_GATES_PHASE=preprod
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_golden_dataset_eval.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --phase preprod --output-json "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary-preprod.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary-preprod.log"
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/run_accuracy_matrix.py --dataset "$(QUALITY_GATES_DATASET)" --corpus "$(QUALITY_GATES_CORPUS)" --stale-corpus "$(QUALITY_GATES_STALE_CORPUS)" --phase preprod --output-json "$(QUALITY_GATES_REPORT_DIR)/accuracy-matrix-preprod.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/accuracy-matrix-preprod.log"
	$(MAKE) perf-gates-capacity
	PYTHONPATH=$(PYTHONPATH) python3 ./scripts/checks/quality/build_release_readiness.py --evaluation "$(QUALITY_GATES_REPORT_DIR)/evaluation-summary-preprod.json" --perf "$(QUALITY_GATES_REPORT_DIR)/perf-summary-capacity.json" --phase preprod --output-json "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary-preprod.json" --output-log "$(QUALITY_GATES_REPORT_DIR)/release-readiness-summary-preprod.log"
