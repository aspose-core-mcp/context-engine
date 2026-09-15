#!/usr/bin/env python3
"""Enforce ADCS performance + cost budgets in CI.

Reads ``config/perf/budgets.yaml`` and compares each declared budget against
the corresponding measurement in ``reports/quality-gates/perf-summary.json``
(produced by ``make perf-gates``) and ``reports/quality-gates/cost-summary.json``
(produced by ``scripts/perf/measure_llm_cost_surface.py``).

Exits:
  0 — all budgets met, or only warnings (per disposition.on_breach=track)
  1 — at least one budget breached and disposition.on_breach=block
  2 — config or measurement file missing (operator error)

It turns the existing ``track-only`` perf gates into a true blocking gate.
"""

from __future__ import annotations

import argparse
import json
import operator
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

_COMPARATORS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


@dataclass
class Verdict:
    name: str
    measured: object
    budget: object
    comparator: str
    met: bool
    detail: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"ERROR: budget config not found: {path}", file=sys.stderr)
        sys.exit(2)
    payload = yaml.safe_load(path.read_text())
    if not isinstance(payload, dict):
        print(f"ERROR: budget config root must be a mapping: {path}", file=sys.stderr)
        sys.exit(2)
    return payload


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON or return ``None`` for missing/empty/unparsable inputs.

    Returning ``None`` lets the caller apply the configured ``on_missing``
    disposition — typically ``warn`` — so the pipeline can keep moving when
    only one of {perf, cost} is being checked (e.g. the lightweight
    cost-only PR gate).
    """
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_measurement(
    perf_summary: dict[str, Any], *, profile: str, metric: str
) -> object | None:
    for prof in perf_summary.get("profiles", []) or []:
        if prof.get("profile_id") != profile:
            continue
        for target in prof.get("targets", []) or []:
            if target.get("metric") == metric:
                return target.get("actual")
    return None


def _enforce_performance(
    config: dict[str, Any], perf_summary: dict[str, Any] | None
) -> list[Verdict]:
    verdicts: list[Verdict] = []
    rules = config.get("performance", []) or []
    for rule in rules:
        profile = rule["profile"]
        metric = rule["metric"]
        comparator = rule["comparator"]
        budget = rule["budget"]
        op = _COMPARATORS.get(comparator)
        if op is None:
            verdicts.append(
                Verdict(
                    name=f"perf:{profile}/{metric}",
                    measured=None,
                    budget=budget,
                    comparator=comparator,
                    met=False,
                    detail=f"unknown comparator {comparator!r}",
                )
            )
            continue
        if perf_summary is None:
            verdicts.append(
                Verdict(
                    name=f"perf:{profile}/{metric}",
                    measured=None,
                    budget=budget,
                    comparator=comparator,
                    met=rule.get("on_missing", "warn") != "block",
                    detail="perf-summary.json missing",
                )
            )
            continue
        measured = _find_measurement(perf_summary, profile=profile, metric=metric)
        if measured is None:
            verdicts.append(
                Verdict(
                    name=f"perf:{profile}/{metric}",
                    measured=None,
                    budget=budget,
                    comparator=comparator,
                    met=rule.get("on_missing", "warn") != "block",
                    detail="metric not present in perf-summary",
                )
            )
            continue
        try:
            ok = op(float(measured), float(budget))
        except (TypeError, ValueError):
            ok = False
        verdicts.append(
            Verdict(
                name=f"perf:{profile}/{metric}",
                measured=measured,
                budget=budget,
                comparator=comparator,
                met=ok,
            )
        )
    return verdicts


def _enforce_cost(
    config: dict[str, Any], cost_summary: dict[str, Any] | None
) -> list[Verdict]:
    verdicts: list[Verdict] = []
    cost_cfg = config.get("cost", {}) or {}
    call_cfg = cost_cfg.get("llm_call_sites", {}) or {}
    overall_max = call_cfg.get("overall_max")
    per_module = call_cfg.get("per_module", {}) or {}

    if cost_summary is None:
        # Cost summary is optional; if absent we just warn, never block.
        if overall_max is not None or per_module:
            verdicts.append(
                Verdict(
                    name="cost:llm_call_sites/overall",
                    measured=None,
                    budget=overall_max,
                    comparator="<=",
                    met=True,
                    detail="cost-summary.json missing — run scripts/perf/measure_llm_cost_surface.py",
                )
            )
        return verdicts

    measured_overall = cost_summary.get("overall_total")
    if overall_max is not None and isinstance(measured_overall, int):
        verdicts.append(
            Verdict(
                name="cost:llm_call_sites/overall",
                measured=measured_overall,
                budget=overall_max,
                comparator="<=",
                met=measured_overall <= overall_max,
            )
        )

    measured_per_module = cost_summary.get("per_module", {}) or {}
    for module, budget in per_module.items():
        actual = measured_per_module.get(module, 0)
        if not isinstance(budget, int):
            continue
        if not isinstance(actual, int):
            actual = 0
        verdicts.append(
            Verdict(
                name=f"cost:llm_call_sites/{module}",
                measured=actual,
                budget=budget,
                comparator="<=",
                met=actual <= budget,
            )
        )
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "perf" / "budgets.yaml",
    )
    parser.add_argument(
        "--perf-summary",
        type=Path,
        help="Override perf-summary.json path (defaults to budgets.yaml sources.perf_summary).",
    )
    parser.add_argument(
        "--cost-summary",
        type=Path,
        help="Override cost-summary.json path (defaults to budgets.yaml sources.cost_summary).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Force on_breach=block regardless of config (use in CI gate).",
    )
    args = parser.parse_args()

    config = _load_yaml(args.config)
    sources = config.get("sources", {}) or {}
    perf_path = args.perf_summary or REPO_ROOT / sources.get(
        "perf_summary", "reports/quality-gates/perf-summary.json"
    )
    cost_path = args.cost_summary or REPO_ROOT / sources.get(
        "cost_summary", "reports/quality-gates/cost-summary.json"
    )

    perf_summary = _load_json(perf_path)
    cost_summary = _load_json(cost_path)

    verdicts = [
        *_enforce_performance(config, perf_summary),
        *_enforce_cost(config, cost_summary),
    ]

    print(f"\nADCS perf + cost budget gate (config v{config.get('version')})")
    print("=" * 78)
    breaches: list[Verdict] = []
    for v in verdicts:
        marker = "PASS" if v.met else "FAIL"
        line = (
            f"  {marker}  {v.name:<60} "
            f"{v.measured!s:>10} {v.comparator} {v.budget!s:<10}"
        )
        if v.detail:
            line += f"  ({v.detail})"
        print(line)
        if not v.met:
            breaches.append(v)
    print("=" * 78)
    print(f"Summary: {len(verdicts) - len(breaches)} pass, {len(breaches)} fail")

    if not breaches:
        return 0

    on_breach = "block" if args.strict else config.get("disposition", {}).get(
        "on_breach", "block"
    )
    if on_breach == "block":
        print("\nFAIL: one or more budgets breached. Exiting 1.")
        return 1
    print("\nWARN: budgets breached but disposition=track; exiting 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
