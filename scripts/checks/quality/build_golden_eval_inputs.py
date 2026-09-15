#!/usr/bin/env python3
"""Build deterministic golden-eval inputs from publish-grade staging artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adcs.quality_gates import (
    build_eval_inputs,
    corpus_to_payload,
    dataset_to_payload,
    default_staging_manifest_paths,
    load_golden_dataset,
    load_stage_d_corpus_from_artifact,
    summary_to_payload,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic quality-gate corpus and golden dataset."
    )
    parser.add_argument(
        "--staging-manifest",
        action="append",
        default=[],
        help="Explicit staging manifest path (repeatable). Defaults to OCR docs/apiref staging.",
    )
    parser.add_argument(
        "--seed-corpus",
        default="artifacts/quality-gates/retrieval_corpus.json",
        help="Existing corpus artifact to merge as seed input when present.",
    )
    parser.add_argument(
        "--seed-dataset",
        default="artifacts/quality-gates/golden_dataset.json",
        help="Existing golden dataset artifact to preserve as seed cases when present.",
    )
    parser.add_argument(
        "--target-cases",
        type=int,
        default=500,
        help="Target number of generated golden cases.",
    )
    parser.add_argument(
        "--output-corpus",
        default="artifacts/quality-gates/retrieval_corpus.json",
        help="Output path for current retrieval corpus.",
    )
    parser.add_argument(
        "--output-stale-corpus",
        default="artifacts/quality-gates/retrieval_corpus_stale.json",
        help="Output path for stale baseline corpus.",
    )
    parser.add_argument(
        "--output-dataset",
        default="artifacts/quality-gates/golden_dataset.json",
        help="Output path for golden dataset.",
    )
    parser.add_argument(
        "--output-summary-json",
        default="reports/quality-gates/eval-inputs-summary.json",
        help="Output path for machine-readable build summary.",
    )
    parser.add_argument(
        "--output-summary-log",
        default="reports/quality-gates/eval-inputs-summary.log",
        help="Output path for concise human-readable build summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    staging_manifest_paths = (
        tuple(Path(path) for path in args.staging_manifest)
        if args.staging_manifest
        else default_staging_manifest_paths()
    )
    seed_corpus_path = Path(args.seed_corpus)
    seed_dataset_path = Path(args.seed_dataset)

    seed_corpus = load_stage_d_corpus_from_artifact(seed_corpus_path)
    if seed_dataset_path.exists():
        seed_dataset = load_golden_dataset(seed_dataset_path)
        seed_cases = tuple(
            case
            for case in seed_dataset.cases
            if case.scenario_bucket != "generated" and case.generation_source != "staging"
        )
    else:
        seed_cases = ()

    inputs = build_eval_inputs(
        staging_manifest_paths=staging_manifest_paths,
        seed_corpus=seed_corpus,
        seed_dataset_cases=seed_cases,
        target_cases=args.target_cases,
    )

    output_corpus = Path(args.output_corpus)
    output_stale_corpus = Path(args.output_stale_corpus)
    output_dataset = Path(args.output_dataset)
    output_summary_json = Path(args.output_summary_json)
    output_summary_log = Path(args.output_summary_log)

    for output_path in (
        output_corpus,
        output_stale_corpus,
        output_dataset,
        output_summary_json,
        output_summary_log,
    ):
        output_path.parent.mkdir(parents=True, exist_ok=True)

    output_corpus.write_text(
        json.dumps(
            corpus_to_payload(records=inputs.corpus_records),
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output_stale_corpus.write_text(
        json.dumps(
            corpus_to_payload(records=inputs.stale_baseline_records),
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dataset.write_text(
        json.dumps(dataset_to_payload(dataset=inputs.dataset), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    summary_payload = summary_to_payload(inputs=inputs)
    output_summary_json.write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    output_summary_log.write_text(render_human_summary(summary_payload), encoding="utf-8")

    print(f"[ok] corpus written: {output_corpus.as_posix()}")
    print(f"[ok] stale corpus written: {output_stale_corpus.as_posix()}")
    print(f"[ok] dataset written: {output_dataset.as_posix()}")
    print(f"[ok] summary written: {output_summary_json.as_posix()}")
    return 0


def render_human_summary(summary: dict[str, object]) -> str:
    counts = summary.get("counts", {})
    breakdown = summary.get("breakdown", {})
    lines = [
        "ADCS Eval Inputs Build",
        f"schema_version: {summary.get('schema_version', 'unknown')}",
    ]
    if isinstance(counts, dict):
        lines.append(
            "counts: "
            f"corpus={counts.get('corpus_records', 0)}; "
            f"stale_baseline={counts.get('stale_baseline_records', 0)}; "
            f"dataset_cases={counts.get('dataset_cases', 0)}"
        )
    if isinstance(breakdown, dict):
        for section_name in ("languages", "locales", "doc_types", "case_scenarios"):
            section = breakdown.get(section_name, {})
            if not isinstance(section, dict) or not section:
                continue
            lines.append(f"{section_name}:")
            for key, value in sorted(section.items(), key=lambda item: str(item[0])):
                lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
