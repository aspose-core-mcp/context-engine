#!/usr/bin/env python3
"""Run deterministic golden-dataset evaluation and write reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adcs.quality_gates import (
    load_golden_dataset,
    load_stage_d_corpus,
    render_golden_eval_human_report,
    run_golden_dataset_evaluation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic golden dataset evaluation.")
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
        "--output-json",
        default="reports/quality-gates/evaluation-summary.json",
        help="Machine-readable report output path.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/quality-gates/evaluation-summary.log",
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
    dataset_path = Path(args.dataset)
    corpus_path = Path(args.corpus)
    output_json_path = Path(args.output_json)
    output_log_path = Path(args.output_log)

    dataset = load_golden_dataset(dataset_path)
    corpus = load_stage_d_corpus(corpus_path)
    summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=corpus,
        phase=args.phase,
    )

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_log_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    output_log_path.write_text(
        render_golden_eval_human_report(summary),
        encoding="utf-8",
    )

    print(f"[info] evaluation summary written: {output_json_path.as_posix()}")
    print(f"[info] evaluation log written: {output_log_path.as_posix()}")
    if summary.get("blocking_status") != "pass":
        print("[fail] Functional regressions detected in golden evaluation.")
        return 1
    print("[pass] Golden evaluation completed with no blocking regressions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
