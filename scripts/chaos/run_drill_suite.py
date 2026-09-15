#!/usr/bin/env python3
"""Run the ADCS chaos / DR fault-injection drill suite.

Each drill exercises a real degraded-mode code path
documented in ``infra/runbooks/incident-response-playbooks.md`` and emits
a structured JSON record under ``reports/chaos/`` so auditors can verify
the resilience claim end-to-end.

Outputs:

- ``reports/chaos/drill-log.jsonl`` (committed) — append-only audit log;
  one line per drill run, suitable for time-series analysis.
- ``reports/chaos/drills/<drill_id>/<utc_ts>.json`` (gitignored) — full
  per-drill detail with verified[], failures[], telemetry{}, recovery_steps[].
- ``reports/chaos/last-summary.json`` (gitignored) — most recent suite
  summary, used by the CI gate.

Exit codes:

- 0 — every drill PASS or DEGRADED.
- 1 — at least one drill FAIL or ERROR (block release).
- 2 — runner itself failed.

Usage:

  PYTHONPATH=./src:. python3 scripts/chaos/run_drill_suite.py
  PYTHONPATH=./src:. python3 scripts/chaos/run_drill_suite.py --strict
  PYTHONPATH=./src:. python3 scripts/chaos/run_drill_suite.py --skip D-06
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.chaos.drills.base import DrillResult, write_evidence

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_ROOT = REPO_ROOT / "reports" / "chaos"

DRILLS: tuple[tuple[str, str], ...] = (
    ("D-01", "scripts.chaos.drills.d01_dense_lane_outage"),
    ("D-02", "scripts.chaos.drills.d02_lexical_lane_outage"),
    ("D-03", "scripts.chaos.drills.d03_both_lanes_outage"),
    ("D-04", "scripts.chaos.drills.d04_lane_timeout"),
    ("D-05", "scripts.chaos.drills.d05_snapshot_rollback"),
    ("D-06", "scripts.chaos.drills.d06_dr_backup_restore"),
)


def run_drill(module_name: str) -> DrillResult:
    module = importlib.import_module(module_name)
    runner = getattr(module, "run", None)
    if runner is None:
        msg = f"drill module {module_name} has no run() entry point"
        raise RuntimeError(msg)
    return runner()


def append_log_line(record: dict[str, Any], *, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True))
        fh.write("\n")


def write_summary(
    summary: dict[str, Any], *, summary_path: Path
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat DEGRADED outcomes as failures (CI release-gate mode).",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="DRILL_ID",
        help="Drill ID to skip (e.g. D-06). May be passed multiple times.",
    )
    parser.add_argument(
        "--reports-root",
        type=Path,
        default=REPORTS_ROOT,
        help="Override reports/chaos/ root.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    skip_set = {drill_id.strip() for drill_id in args.skip}
    log_path = args.reports_root / "drill-log.jsonl"
    summary_path = args.reports_root / "last-summary.json"

    results: list[DrillResult] = []
    skipped: list[str] = []
    print(f"\nADCS chaos drill suite — {len(DRILLS)} drills configured\n" + "=" * 78)
    for drill_id, module_name in DRILLS:
        if drill_id in skip_set:
            print(f"  SKIP  {drill_id}")
            skipped.append(drill_id)
            continue
        try:
            result = run_drill(module_name)
        except Exception as exc:  # pragma: no cover — defensive runner guard
            print(f"  ERROR {drill_id}  runner crashed: {exc!r}")
            return 2

        evidence = write_evidence(result, root=args.reports_root)
        record = result.to_dict()
        try:
            record["evidence_artifact"] = evidence.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            # reports_root overridden to a path outside REPO_ROOT (e.g. pytest
            # tmp_path). Fall back to the absolute path so the audit log is
            # still self-describing.
            record["evidence_artifact"] = evidence.as_posix()
        append_log_line(record, log_path=log_path)
        results.append(result)

        marker = {
            "PASS": "PASS ",
            "DEGRADED": "DEGR ",
            "FAIL": "FAIL ",
            "ERROR": "ERR  ",
        }[result.outcome]
        print(
            f"  {marker} {drill_id}  {result.drill_name:<30} "
            f"rto={result.rto_observed_seconds * 1000:>8.2f}ms / "
            f"target {result.rto_target_seconds:>5.1f}s   "
            f"verified={len(result.verified)}  failures={len(result.failures)}"
        )
        for failure in result.failures:
            print(f"        ! {failure}")

    print("=" * 78)
    pass_count = sum(1 for r in results if r.outcome == "PASS")
    degraded_count = sum(1 for r in results if r.outcome == "DEGRADED")
    fail_count = sum(1 for r in results if r.outcome == "FAIL")
    error_count = sum(1 for r in results if r.outcome == "ERROR")
    print(
        f"Summary: {pass_count} pass, {degraded_count} degraded, "
        f"{fail_count} fail, {error_count} error, {len(skipped)} skipped"
    )

    summary = {
        "ran": [
            {
                "drill_id": r.drill_id,
                "drill_name": r.drill_name,
                "outcome": r.outcome,
                "rto_observed_seconds": r.rto_observed_seconds,
                "rto_target_seconds": r.rto_target_seconds,
                "verified_count": len(r.verified),
                "failure_count": len(r.failures),
                "started_at": r.started_at,
                "completed_at": r.completed_at,
            }
            for r in results
        ],
        "skipped": skipped,
        "totals": {
            "pass": pass_count,
            "degraded": degraded_count,
            "fail": fail_count,
            "error": error_count,
            "skipped": len(skipped),
        },
        "strict_mode": args.strict,
    }
    write_summary(summary, summary_path=summary_path)

    def _printable(path: Path) -> str:
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    print(f"\nlog appended:  {_printable(log_path)}")
    print(f"summary:       {_printable(summary_path)}")

    if fail_count or error_count:
        return 1
    if args.strict and degraded_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
