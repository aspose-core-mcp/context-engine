#!/usr/bin/env python3
"""Run a mutation-testing baseline via mutmut (>= 3.5) and emit a report.

mutmut 3.x replaced the 2.x results interface this script originally
used. The 2.x ``mutmut results --output=json`` command no longer exists;
3.x exposes machine-readable stats through ``mutmut export-cicd-stats``,
which writes ``mutants/mutmut-cicd-stats.json`` with a flat schema::

    {
      "killed": int, "survived": int, "total": int,
      "no_tests": int, "skipped": int, "suspicious": int,
      "timeout": int, "segfault": int,
      "check_was_interrupted_by_user": bool
    }

This script wraps the 3.x flow: ``mutmut run`` → ``mutmut
export-cicd-stats`` → read the JSON → write a structured baseline to
``reports/quality-gates/mutation-baseline.json`` plus a human-readable
table.

The report is consumed by:

* ``make mutation-test-strict``, which gates the kill rate against the
  configured floor (default 0.80);
* the test-coverage review in ``docs/test-coverage-matrix.md``.

Mutation runs are expensive. mutmut 3.x copies the whole ``adcs`` package
into a ``mutants/`` sandbox and runs the suite once per surviving mutant;
a full pass is multi-hour wall-clock, so it runs on demand, never on every
PR. ``PYTHONPATH=./src`` must be exported in the
environment (mutmut 3.x ignores the 2.x ``runner`` config key); the
Makefile ``mutation-test`` target does this.

Usage::

    PYTHONPATH=./src python3 scripts/checks/quality/run_mutation_baseline.py
    PYTHONPATH=./src python3 scripts/checks/quality/run_mutation_baseline.py \\
        --min-kill-rate 0.85 --strict
    # Re-parse an existing run without re-mutating:
    PYTHONPATH=./src python3 scripts/checks/quality/run_mutation_baseline.py \\
        --skip-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REPORT_JSON = Path("reports/quality-gates/mutation-baseline.json")
REPORT_TXT = Path("reports/quality-gates/mutation-baseline.txt")
# mutmut 3.x writes its CI/CD stats here, relative to the cwd.
CICD_STATS_PATH = Path("mutants/mutmut-cicd-stats.json")
PYPROJECT_PATH = Path("pyproject.toml")


@dataclass
class MutationBaseline:
    generated_at: str
    paths_mutated: tuple[str, ...]
    total_mutants: int
    killed: int
    survived: int
    timed_out: int
    suspicious: int
    skipped: int
    no_tests: int
    segfault: int
    kill_rate: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _configured_paths() -> tuple[str, ...]:
    """Best-effort read of ``[tool.mutmut].paths_to_mutate`` from pyproject.

    The flat ``export-cicd-stats`` schema carries no per-file breakdown,
    so the mutated scope is reported from the config instead. Returns an
    empty tuple if pyproject is missing or malformed — the report still
    writes, just without the scope annotation.
    """
    if not PYPROJECT_PATH.exists():
        return ()
    try:
        data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    mutmut_cfg = data.get("tool", {}).get("mutmut", {})
    paths = mutmut_cfg.get("paths_to_mutate", [])
    if isinstance(paths, str):
        return (paths,)
    return tuple(str(p) for p in paths)


def _parse_results(stats: dict) -> MutationBaseline:
    """Parse the flat ``mutmut export-cicd-stats`` JSON into a baseline.

    Kill rate is ``killed / tested`` where ``tested`` excludes mutants
    that were skipped or had no covering test (those are not a verdict
    on the suite). Timeouts are counted as caught (a mutant that hangs
    the suite is detected), matching mutmut's own scoring.
    """
    killed = int(stats.get("killed", 0))
    survived = int(stats.get("survived", 0))
    timed_out = int(stats.get("timeout", 0))
    suspicious = int(stats.get("suspicious", 0))
    skipped = int(stats.get("skipped", 0))
    no_tests = int(stats.get("no_tests", 0))
    segfault = int(stats.get("segfault", 0))
    total = int(
        stats.get(
            "total",
            killed + survived + timed_out + suspicious + skipped + no_tests,
        )
    )

    tested = killed + survived + timed_out + suspicious
    kill_rate = (killed + timed_out) / tested if tested > 0 else 0.0
    return MutationBaseline(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        paths_mutated=_configured_paths(),
        total_mutants=total,
        killed=killed,
        survived=survived,
        timed_out=timed_out,
        suspicious=suspicious,
        skipped=skipped,
        no_tests=no_tests,
        segfault=segfault,
        kill_rate=round(kill_rate, 4),
    )


def _run_mutmut(skip_run: bool) -> None:
    if skip_run:
        print("--skip-run set; expecting an existing `mutants/` directory")
        return
    print("Running `mutmut run` … (multi-hour; whole-package sandbox)")
    subprocess.check_call(["mutmut", "run"])


def _export_cicd_stats() -> None:
    """Ask mutmut 3.x to (re)write ``mutants/mutmut-cicd-stats.json``."""
    subprocess.check_call(["mutmut", "export-cicd-stats"])


def _read_cicd_stats(path: Path = CICD_STATS_PATH) -> dict:
    """Read the flat stats JSON; empty dict when the file is absent."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _write_reports(baseline: MutationBaseline) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(baseline.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"Mutation baseline — generated {baseline.generated_at}",
        "-" * 72,
        f"  Paths mutated:    {', '.join(baseline.paths_mutated) or '(unknown)'}",
        f"  Total mutants:    {baseline.total_mutants}",
        f"  Killed:           {baseline.killed}",
        f"  Survived:         {baseline.survived}",
        f"  Timed out:        {baseline.timed_out}",
        f"  Suspicious:       {baseline.suspicious}",
        f"  Skipped:          {baseline.skipped}",
        f"  No covering test: {baseline.no_tests}",
        f"  Segfault:         {baseline.segfault}",
        f"  Kill rate:        {baseline.kill_rate:.4f}",
        "",
    ]
    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--min-kill-rate",
        type=float,
        default=0.80,
        help="Minimum acceptable kill rate (0..1); default 0.80.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when kill rate is below --min-kill-rate.",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Skip `mutmut run`; export + parse the existing mutants/ state.",
    )
    args = parser.parse_args()

    try:
        _run_mutmut(skip_run=args.skip_run)
    except FileNotFoundError:
        print(
            "::error::`mutmut` is not on PATH. Install via "
            "`pip install -e \".[mutation]\"`.",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as exc:
        # Mutmut returns non-zero when survived mutants exist; we still
        # want to export + read the stats below.
        print(f"mutmut exit code {exc.returncode}; exporting partial stats")

    try:
        _export_cicd_stats()
    except FileNotFoundError:
        print(
            "::error::`mutmut` is not on PATH. Install via "
            "`pip install -e \".[mutation]\"`.",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as exc:
        # export-cicd-stats exits non-zero when there is no run data; we
        # fall through and write a zeroed baseline so the report path is
        # always produced for CI to inspect.
        print(f"export-cicd-stats exit code {exc.returncode}; reading partial")

    baseline = _parse_results(_read_cicd_stats())
    _write_reports(baseline)

    if args.strict and baseline.kill_rate < args.min_kill_rate:
        print(
            f"\n::error::kill rate {baseline.kill_rate:.4f} is below "
            f"--min-kill-rate {args.min_kill_rate:.4f}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
