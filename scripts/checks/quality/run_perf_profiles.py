#!/usr/bin/env python3
"""Run local sustained/burst/soak perf profile scaffolding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adcs.quality_gates import (
    load_golden_dataset,
    load_perf_profiles,
    load_stage_d_corpus,
    render_perf_human_report,
    run_perf_profiles,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local perf profiles.")
    parser.add_argument(
        "--dataset",
        default="artifacts/quality-gates/golden_dataset.json",
        help="Path to golden dataset JSON.",
    )
    parser.add_argument(
        "--corpus",
        default="artifacts/quality-gates/retrieval_corpus.json",
        help="Path to Stage-D retrieval corpus JSON.",
    )
    parser.add_argument(
        "--profiles",
        default="artifacts/quality-gates/perf_profiles.json",
        help="Path to perf profile definitions JSON.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Specific profile id to run (repeatable). Defaults to run_by_default profiles.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/quality-gates/perf-summary.json",
        help="Machine-readable report output path.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/quality-gates/perf-summary.log",
        help="Concise human-readable report output path.",
    )
    parser.add_argument(
        "--phase",
        default="mvp",
        choices=("mvp", "preprod", "ga"),
        help="Quality gate phase (controls blocking policy).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_golden_dataset(Path(args.dataset))
    corpus = load_stage_d_corpus(Path(args.corpus))
    profiles = load_perf_profiles(Path(args.profiles))

    selected_profile_ids: tuple[str, ...] | None
    if args.profile:
        selected_profile_ids = tuple(args.profile)
    else:
        selected_profile_ids = None

    summary = run_perf_profiles(
        dataset=dataset,
        corpus=corpus,
        profiles=profiles,
        selected_profile_ids=selected_profile_ids,
        phase=args.phase,
    )

    output_json_path = Path(args.output_json)
    output_log_path = Path(args.output_log)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_log_path.parent.mkdir(parents=True, exist_ok=True)

    output_json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    output_log_path.write_text(
        render_perf_human_report(summary),
        encoding="utf-8",
    )

    print(f"[info] perf summary written: {output_json_path.as_posix()}")
    print(f"[info] perf log written: {output_log_path.as_posix()}")
    if summary.get("blocking_status") != "pass":
        print("[fail] Functional regressions detected in perf profile execution.")
        return 1
    print("[pass] Perf profile execution completed with no blocking regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
