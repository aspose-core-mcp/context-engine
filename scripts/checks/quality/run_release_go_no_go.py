#!/usr/bin/env python3
"""Build unified release go/no-go summary from quality and infra gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from adcs.quality_gates import build_go_no_go_summary, render_go_no_go_human_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ADCS release go/no-go summary.")
    parser.add_argument(
        "--phase",
        default="preprod",
        choices=("mvp", "preprod", "ga"),
        help="Gate phase.",
    )
    parser.add_argument(
        "--evaluation",
        default="reports/quality-gates/evaluation-summary-preprod.json",
        help="Path to evaluation summary JSON.",
    )
    parser.add_argument(
        "--perf",
        default="reports/quality-gates/perf-summary-capacity.json",
        help="Path to perf summary JSON.",
    )
    parser.add_argument(
        "--release-readiness",
        default="reports/quality-gates/release-readiness-summary-preprod.json",
        help="Path to release-readiness summary JSON.",
    )
    parser.add_argument(
        "--dr-smoke",
        default="reports/dr/recovery-smoke.json",
        help="Path to DR smoke report JSON.",
    )
    parser.add_argument(
        "--helm-packaging",
        default="reports/k8s/helm-packaging.json",
        help="Path to Helm packaging report JSON.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/quality-gates/go-no-go-summary.json",
        help="Go/no-go JSON output path.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/quality-gates/go-no-go-summary.log",
        help="Go/no-go human report output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    evaluation_summary = _read_json(Path(args.evaluation))
    perf_summary = _read_json(Path(args.perf))
    release_readiness_summary = _read_json(Path(args.release_readiness))
    dr_smoke_summary = _read_json(Path(args.dr_smoke))
    helm_packaging_summary = _read_json(Path(args.helm_packaging))

    summary = build_go_no_go_summary(
        phase=args.phase,
        evaluation_summary=evaluation_summary,
        perf_summary=perf_summary,
        release_readiness_summary=release_readiness_summary,
        dr_smoke_summary=dr_smoke_summary,
        helm_packaging_summary=helm_packaging_summary,
    )

    output_json = Path(args.output_json)
    output_log = Path(args.output_log)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_log.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    output_log.write_text(render_go_no_go_human_report(summary), encoding="utf-8")

    print(f"[info] go/no-go summary json: {output_json.as_posix()}")
    print(f"[info] go/no-go summary log: {output_log.as_posix()}")

    if summary.get("decision") != "go":
        print("[fail] Release Go/No-Go gate failed.")
        return 1

    print("[pass] Release Go/No-Go gate passed.")
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"Expected JSON object at `{path.as_posix()}`."
        raise ValueError(msg)
    return payload


if __name__ == "__main__":
    sys.exit(main())
