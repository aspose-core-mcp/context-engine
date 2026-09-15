# Performance + Cost Budget Gate

Gates ADCS releases on declarative budgets in [`config/perf/budgets.yaml`](../../config/perf/budgets.yaml).

The gate turns performance signals that were previously tracked for information only into a blocking check, and bounds the number of LLM call sites per module so that silent fan-out becomes visible.

## What is gated

### Performance budgets
Sourced from `reports/quality-gates/perf-summary.json` (produced by `make perf-gates`).

| Profile | Metric | Budget |
|---------|--------|--------|
| sustained | `query_docs_p50_latency_ms` | ≤ 350 ms |
| sustained | `query_docs_p95_latency_ms` | ≤ 1200 ms |
| sustained | `error_rate` | ≤ 1 % |
| sustained | `throughput_rps` | ≥ 40 RPS |
| burst | `query_docs_p95_latency_ms` | ≤ 1500 ms |

The p50 and p95 budgets match the latency targets of the acceptance eval suites (`make acceptance-gates`).

### Cost budgets
Sourced from `reports/quality-gates/cost-summary.json` (produced by [`measure_llm_cost_surface.py`](measure_llm_cost_surface.py)).

| Module | Budget | Current call sites |
|--------|--------|--------------------|
| `src/adcs/retrieval/translation_fallback.py` | 4 | 2 |
| `src/adcs/quality_gates/golden_eval.py` | 4 | 0 |
| `src/adcs/quality_gates/release_readiness.py` | 2 | 0 |
| `src/adcs/admin/quality_reviews.py` | 4 | 0 |
| **overall_max** | **25** | **2** |

A module listed in `budgets.yaml` without LLM call sites measures 0.

The cost surface is measured by AST inspection — counts of function-call sites whose receiver matches a known LLM verb (`chat.completions.create`, `embeddings.create`, `score_chunk`, `embed`, `translate`, etc.). It is approximate but stable, and most importantly **visible in code review** — silent fan-out shows up as a budget breach.

## Running locally

```bash
# 1. Measure the cost surface (writes reports/quality-gates/cost-summary.json)
make measure-cost-surface

# 2. Run perf-gates (produces reports/quality-gates/perf-summary.json)
make perf-gates              # heavy — needs Postgres, corpus, etc.

# 3. Enforce budgets
make perf-budget-gate        # exits 1 on breach (--strict)
```

When you only want to check cost (no perf-gates run), invoke the script directly:

```bash
PYTHONPATH=./src python3 scripts/perf/enforce_perf_budgets.py --strict
# Missing perf-summary.json → perf rules emit PASS with a "missing" note;
# cost rules are still enforced strictly.
```

## CI integration

CI configuration is not included in this repository. A typical setup uses three jobs:

1. **Cost surface measurement** — on every pull request, run `make measure-cost-surface` to write `cost-summary.json`. Runtime: ~1 second.
2. **Cost budget gate** — on every pull request, run `PYTHONPATH=./src python3 scripts/perf/enforce_perf_budgets.py --strict`; it fails strictly on a cost breach. This is the lightweight blocking signal that matters for typical code review.
3. **Full perf budget gate** — run `make perf-gates` followed by `make perf-budget-gate`; it fails on any perf or cost breach. Because `perf-gates` is heavy, run it as a manual/opt-in or scheduled job to keep pull-request pipelines fast.

## Updating budgets

Bumping a budget upward (loosening) requires maintainer approval:

1. A maintainer reviews the PR that edits `config/perf/budgets.yaml`
2. The same PR includes the code change that justifies the bump (e.g., new LLM call site for a planned feature)
3. Budgets table in this README is updated to keep it in sync

Tightening budgets (improvement) is always welcome — open a PR.

## Evidence trail

Keep the gate outputs as CI artifacts (for example `cost-summary.json` for 30 days and `perf-summary.json` for 90 days) to see how the LLM call surface and performance evolved over time.

## Related

- [`config/perf/budgets.yaml`](../../config/perf/budgets.yaml) — declarative budgets (source of truth)
- [`docs/test-coverage-matrix.md`](../../docs/test-coverage-matrix.md) — acceptance eval suites and their latency targets
