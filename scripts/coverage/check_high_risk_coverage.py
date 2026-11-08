#!/usr/bin/env python3
"""Coverage gate enforcement script for ADCS.

Reads a Cobertura XML coverage report, looks up per-module thresholds from
the supplied config (default: scripts/coverage/high_risk_modules.json), and
exits non-zero if any high-risk module is below its `min_line_coverage_percent`.

Usage:
    python3 scripts/coverage/check_high_risk_coverage.py \\
        --xml reports/coverage/coverage.xml \\
        --config scripts/coverage/high_risk_modules.json

High-risk modules require >=80% line coverage; other modules are
report-only.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModuleRule:
    path_glob: str
    min_percent: float
    rationale: str


@dataclass(frozen=True)
class ModuleCoverage:
    filename: str
    line_rate: float  # 0..1

    @property
    def percent(self) -> float:
        return self.line_rate * 100.0


def load_rules(config_path: Path) -> tuple[list[ModuleRule], float]:
    data = json.loads(config_path.read_text())
    rules = [
        ModuleRule(
            path_glob=item["path_glob"],
            min_percent=float(item["min_line_coverage_percent"]),
            rationale=str(item.get("rationale", "")),
        )
        for item in data.get("high_risk_modules", [])
    ]
    global_threshold = float(data.get("global_threshold_percent", 0))
    return rules, global_threshold


def parse_cobertura(xml_path: Path) -> tuple[list[ModuleCoverage], str]:
    """Return list of file coverages plus the <source> root path (if any)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    out: list[ModuleCoverage] = []
    source_root = ""
    sources = root.find("sources")
    if sources is not None:
        first_src = sources.find("source")
        if first_src is not None and first_src.text:
            source_root = first_src.text.strip()
    # Cobertura format: <coverage><packages><package><classes><class filename="..." line-rate="...">
    for cls in root.iter("class"):
        filename = cls.get("filename") or ""
        line_rate = float(cls.get("line-rate", "0"))
        if filename:
            out.append(ModuleCoverage(filename=filename, line_rate=line_rate))
    return out, source_root


def _normalize(path: str) -> str:
    return path.lstrip("./").lstrip("/")


def find_matching(
    modules: Iterable[ModuleCoverage], path_glob: str, source_root: str = ""
) -> list[ModuleCoverage]:
    """Match coverage entries to a target path.

    Coverage XML may store filenames either as ``src/adcs/foo/bar.py`` or as
    ``foo/bar.py`` (relative to the <source> root). We accept both: build the
    candidate fully-qualified path by prefixing source_root and compare by
    suffix on either form.
    """
    target = _normalize(path_glob)
    target_parts = target.split("/")
    src_root_norm = _normalize(source_root)
    src_root_parts = src_root_norm.split("/") if src_root_norm else []

    matches: list[ModuleCoverage] = []
    for mod in modules:
        candidate = _normalize(mod.filename)
        candidate_parts = candidate.split("/")

        # Try direct suffix match
        if (
            len(candidate_parts) >= len(target_parts)
            and candidate_parts[-len(target_parts):] == target_parts
        ):
            matches.append(mod)
            continue

        # Try with source_root prefix
        if src_root_parts:
            full_parts = src_root_parts + candidate_parts
            if (
                len(full_parts) >= len(target_parts)
                and full_parts[-len(target_parts):] == target_parts
            ):
                matches.append(mod)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True, help="Cobertura XML coverage report")
    parser.add_argument("--config", type=Path, required=True, help="High-risk modules config JSON")
    parser.add_argument("--quiet", action="store_true", help="Only print failures")
    args = parser.parse_args()

    if not args.xml.exists():
        print(f"ERROR: coverage XML not found: {args.xml}", file=sys.stderr)
        print("Run `make test-coverage` first.", file=sys.stderr)
        return 2
    if not args.config.exists():
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        return 2

    rules, _global_threshold = load_rules(args.config)
    modules, source_root = parse_cobertura(args.xml)

    if not modules:
        print("WARNING: no module coverage data found in XML", file=sys.stderr)

    failures: list[tuple[ModuleRule, list[ModuleCoverage]]] = []
    passes: list[tuple[ModuleRule, ModuleCoverage]] = []
    missing: list[ModuleRule] = []

    for rule in rules:
        matches = find_matching(modules, rule.path_glob, source_root=source_root)
        if not matches:
            missing.append(rule)
            continue
        # If multiple matches, take the one with the longest filename (most specific)
        match = max(matches, key=lambda m: len(m.filename))
        if match.percent < rule.min_percent:
            failures.append((rule, [match]))
        else:
            passes.append((rule, match))

    # Report
    if not args.quiet:
        print(f"\nHigh-risk module coverage report ({len(rules)} rules)")
        print("=" * 78)
        for rule, mod in passes:
            print(f"  PASS  {rule.path_glob:<60} {mod.percent:6.2f}% >= {rule.min_percent:.0f}%")

    for rule, matches in failures:
        for match in matches:
            print(
                f"  FAIL  {rule.path_glob:<60} {match.percent:6.2f}% <  {rule.min_percent:.0f}%"
            )
            print(f"        rationale: {rule.rationale}")
    for rule in missing:
        print(f"  WARN  {rule.path_glob:<60} not found in coverage report")

    print("=" * 78)
    print(f"Summary: {len(passes)} pass, {len(failures)} fail, {len(missing)} missing")

    if failures:
        print("\nFAIL: one or more high-risk modules below their coverage threshold.")
        return 1
    if missing == rules:
        print("\nFAIL: no high-risk modules matched in coverage report.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
