# Chaos / DR Fault-Injection Drill Catalog

A catalog of deterministic fault-injection drills for the ADCS retrieval, snapshot, and disaster-recovery paths. Each drill turns a documented degraded-mode contract into a recurring, time-stamped check.

## Why these drills exist

The ADCS retrieval and ingestion stack has *several* documented degraded-mode contracts:

- One retrieval lane (Qdrant or OpenSearch) can be unavailable without taking `query_docs` down.
- A slow lane is cancelled at `lane_timeout_seconds` — the survivor still serves.
- Both lanes down returns a clean empty envelope (no 500).
- A bad snapshot can be rolled back atomically with optimistic-concurrency.
- Control-plane state can be backed up and restored with zero data loss for the sentinel set.

Unit tests verify these contracts at a single point in time. Running the drills on a schedule makes that verification **continuous and time-stamped**: every run appends a line to `reports/chaos/drill-log.jsonl` with the recovery time actually observed, so "did the degraded-mode contract still hold last month?" can be answered from one file.

## Catalog

| ID | Name | What is broken | Expected behaviour | RTO target | RPO target |
|----|------|----------------|---------------------|------------|------------|
| **D-01** | `dense_lane_outage` | Qdrant primary unavailable; dense lane raises | Lexical-only results, WARNING logged, no exception escapes | 5 s | 0 s |
| **D-02** | `lexical_lane_outage` | OpenSearch unavailable; lexical lane raises | Vector-only results, WARNING logged | 5 s | 0 s |
| **D-03** | `both_lanes_outage` | Both Qdrant **and** OpenSearch unavailable | Empty envelope, two WARNINGs, no 500 | 5 s | 0 s |
| **D-04** | `lane_timeout` | Dense lane responds slower than `lane_timeout_seconds` | Slow lane cancelled, survivor serves within timeout | 1 s | 0 s |
| **D-05** | `snapshot_rollback` | Active snapshot is corrupted | Operator rolls back to N-1 with optimistic-concurrency guard | 60 s | 0 s |
| **D-06** | `dr_backup_restore` | Control-plane state destroyed | `FileBackedBackupRestoreService.run_recovery_smoke` round-trips a sentinel | 600 s | 0 s |

Each drill exercises **real ADCS code** (`HybridRetriever`, `InMemorySnapshotRegistry`, `FileBackedBackupRestoreService`) — not a mock — so the evidence is structurally identical to what production would do.

## Outcomes

| Outcome | Meaning | Exit code (default) | Exit code (`--strict`) |
|---------|---------|---------------------|------------------------|
| `PASS` | Recovery within RTO + every verification entry satisfied | 0 | 0 |
| `DEGRADED` | Recovery succeeded but at least one verification missed (e.g. RTO overrun) | 0 | 1 |
| `FAIL` | Degraded-mode contract violated — exception escaped or empty envelope expected but caller would 500 | 1 | 1 |
| `ERROR` | Drill itself crashed; result inconclusive — investigate harness | 1 | 1 |

## Outputs

The runner writes three artifact families:

1. **`reports/chaos/drill-log.jsonl`** — append-only log. One line per drill run, suitable for time-series analysis (e.g. RTO drift over months). Each line is a complete `DrillResult` JSON object. Keep it under version control or as a long-retention CI artifact to preserve the history.
2. **`reports/chaos/drills/<drill_id>/<UTC_timestamp>.json`** — per-drill detail with full `verified[]`, `failures[]`, `telemetry{}`, `recovery_steps[]`. Not meant to be committed; retain it as a CI artifact (for example for 90 days) if needed.
3. **`reports/chaos/last-summary.json`** — summary of the most recent suite run; a CI gate can consume it.

## Running locally

```bash
# Recommended for dev iteration — D-06 is already covered by the pytest
# wrapper (tests/chaos/test_d06_dr_backup_restore_drill.py, tmp_path-isolated)
# so skipping it locally avoids writing backup/restore state under artifacts/dr/.
PYTHONPATH=./src:. python3 scripts/chaos/run_drill_suite.py --skip D-06

# Full suite — performs a real backup+restore cycle under artifacts/dr/.
# Will leave a new backup-NNNNNNNN/ directory in the worktree (see invariants
# below). Prefer the --skip D-06 form unless you're explicitly exercising the
# DR path or running on CI.
make chaos-drill-suite

# Strict mode — DEGRADED counts as failure (release-gate posture).
# Also available as `make chaos-drill-suite-strict`.
PYTHONPATH=./src:. python3 scripts/chaos/run_drill_suite.py --strict
```

## CI integration

The bundled CI workflow (`.github/workflows/ci.yml`) runs the pytest wrappers in `tests/chaos/` as part of `make test`, but not the drill suite itself. Recommended setup for the suite:

| Job | Trigger | Strict? | Artifact retention |
|-----|---------|---------|--------------------|
| `make chaos-drill-suite-strict` | scheduled (monthly) + manual | yes | 90 days (`reports/chaos/`) |

The drill suite is intentionally *not* run on every pull request — it's a monthly + on-demand evidence event. The DR drill (D-06) does real filesystem I/O which would slow pull-request pipelines unproductively. The cheap drills (D-01..D-05) run in <1 s combined and could run on every pull request (with `--skip D-06`) if needed.

## Adding a new drill

1. Drop a module under `scripts/chaos/drills/dNN_<short_name>.py` exposing a `run() -> DrillResult` entry point. Use the `_fixtures.py` helpers and the `DrillTimer` / `utc_iso` from `base.py`.
2. Register it in `scripts/chaos/run_drill_suite.py::DRILLS`.
3. Add a row to the catalog table above.
4. Add a row to the runbook cross-link table in [`infra/runbooks/incident-response-playbooks.md`](../runbooks/incident-response-playbooks.md).

## Anti-regression invariants

- Drills D-01..D-05 must never write to `artifacts/` or other version-controlled directories. Per-drill detail JSON goes under `reports/chaos/drills/`; only the JSONL log line is meant to be kept long-term.
- D-06 is the only drill that writes to `artifacts/`. The `FileBackedBackupRestoreService` it wraps is workspace-bounded (asserts `_assert_within_workspace`) and persists its operations + backup snapshots to `artifacts/dr/` (operations.json, backups.json, backups/backup-NNNNNNNN/, restores/). Each invocation appends two new operations and one new backup directory, so a full suite run from `make chaos-drill-suite` will dirty the worktree by design. The pytest wrapper at `tests/chaos/test_d06_dr_backup_restore_drill.py` redirects this to `tmp_path` so the regression check is isolation-safe; the `--skip D-06` invocation above is the safe default for local dev.
- The drill suite must remain runnable without Postgres, Qdrant, OpenSearch, RabbitMQ, or Kubernetes. It exercises degraded-mode contracts in process; it does not inject faults into a running cluster.

## Related

- [`scripts/chaos/run_drill_suite.py`](../../scripts/chaos/run_drill_suite.py) — runner
- [`scripts/chaos/drills/`](../../scripts/chaos/drills/) — individual drill modules
- [`infra/runbooks/incident-response-playbooks.md`](../runbooks/incident-response-playbooks.md) — runbooks each drill exercises
- [`infra/runbooks/dr-backup-restore.md`](../runbooks/dr-backup-restore.md) — backup/restore that D-06 wraps
