#!/usr/bin/env python3
"""Build a unified accuracy matrix for current and stale retrieval quality signals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from adcs.quality_gates import (
    load_golden_dataset,
    load_stage_d_corpus,
    render_golden_eval_human_report,
    run_golden_dataset_evaluation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval accuracy matrix.")
    parser.add_argument(
        "--dataset",
        default="artifacts/quality-gates/golden_dataset.json",
        help="Path to golden dataset JSON.",
    )
    parser.add_argument(
        "--corpus",
        default="artifacts/quality-gates/retrieval_corpus.json",
        help="Path to current retrieval corpus JSON.",
    )
    parser.add_argument(
        "--stale-corpus",
        default="artifacts/quality-gates/retrieval_corpus_stale.json",
        help="Path to stale baseline retrieval corpus JSON.",
    )
    parser.add_argument(
        "--phase",
        default="mvp",
        choices=("mvp", "preprod", "ga"),
        help="Quality gate phase.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/quality-gates/accuracy-matrix.json",
        help="Output path for machine-readable matrix summary.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/quality-gates/accuracy-matrix.log",
        help="Output path for human-readable matrix summary.",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero if matrix decision is block.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = load_golden_dataset(Path(args.dataset))
    current_summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=load_stage_d_corpus(Path(args.corpus)),
        phase=args.phase,
    )
    stale_summary = run_golden_dataset_evaluation(
        dataset=dataset,
        corpus=load_stage_d_corpus(Path(args.stale_corpus)),
        phase=args.phase,
    )

    matrix = _build_matrix(
        phase=args.phase,
        current_summary=current_summary,
        stale_summary=stale_summary,
    )

    output_json = Path(args.output_json)
    output_log = Path(args.output_log)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_log.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(matrix, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    output_log.write_text(_render_matrix_log(matrix), encoding="utf-8")

    print(f"[ok] accuracy matrix written: {output_json.as_posix()}")
    if args.enforce and matrix.get("decision") != "go":
        print("[fail] accuracy matrix decision is block.")
        return 1
    return 0


def _build_matrix(
    *,
    phase: str,
    current_summary: dict[str, Any],
    stale_summary: dict[str, Any],
) -> dict[str, Any]:
    current_metrics = _metrics(current_summary)
    stale_metrics = _metrics(stale_summary)
    delta = {
        "top_3_relevance": round(
            current_metrics["top_3_relevance"] - stale_metrics["top_3_relevance"],
            4,
        ),
        "top_k_relevance": round(
            current_metrics["top_k_relevance"] - stale_metrics["top_k_relevance"],
            4,
        ),
        "version_accuracy": round(
            current_metrics["version_accuracy"] - stale_metrics["version_accuracy"],
            4,
        ),
        "citation_coverage": round(
            current_metrics["citation_coverage"] - stale_metrics["citation_coverage"],
            4,
        ),
        "citation_integrity": round(
            current_metrics["citation_integrity"] - stale_metrics["citation_integrity"],
            4,
        ),
    }
    decision_reasons: list[str] = []
    decision = "go"
    if current_summary.get("blocking_status") != "pass":
        decision = "block"
        decision_reasons.append("current_corpus_blocking_status_failed")
    if delta["top_3_relevance"] < 0.0:
        decision = "block"
        decision_reasons.append("top_3_relevance_regressed_vs_stale")
    if delta["version_accuracy"] < 0.0:
        decision = "block"
        decision_reasons.append("version_accuracy_regressed_vs_stale")

    return {
        "phase": phase,
        "decision": decision,
        "decision_reasons": decision_reasons,
        "retrieval": {
            "current": current_summary,
            "stale_baseline": stale_summary,
            "delta_vs_stale": delta,
        },
    }


def _metrics(summary: dict[str, Any]) -> dict[str, float]:
    metrics = summary.get("metrics", {})
    if not isinstance(metrics, dict):
        return {
            "top_3_relevance": 0.0,
            "top_k_relevance": 0.0,
            "version_accuracy": 0.0,
            "citation_coverage": 0.0,
            "citation_integrity": 0.0,
        }
    return {
        "top_3_relevance": float(metrics.get("top_3_relevance", 0.0)),
        "top_k_relevance": float(metrics.get("top_k_relevance", 0.0)),
        "version_accuracy": float(metrics.get("version_accuracy", 0.0)),
        "citation_coverage": float(metrics.get("citation_coverage", 0.0)),
        "citation_integrity": float(metrics.get("citation_integrity", 0.0)),
    }


def _render_matrix_log(matrix: dict[str, Any]) -> str:
    retrieval = matrix.get("retrieval", {})
    delta_vs_stale = retrieval.get("delta_vs_stale", {})
    lines = [
        "ADCS Accuracy Matrix",
        f"phase: {matrix.get('phase', 'unknown')}",
        f"decision: {matrix.get('decision', 'unknown')}",
        "decision_reasons: "
        + (", ".join(matrix.get("decision_reasons", [])) or "none"),
        "",
        "## Current Retrieval",
        render_golden_eval_human_report(retrieval.get("current", {})).strip(),
        "",
        "## Stale Baseline Retrieval",
        render_golden_eval_human_report(retrieval.get("stale_baseline", {})).strip(),
        "",
        "## Delta Vs Stale",
    ]
    if isinstance(delta_vs_stale, dict):
        for key, value in delta_vs_stale.items():
            lines.append(f"- {key}: {value}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
