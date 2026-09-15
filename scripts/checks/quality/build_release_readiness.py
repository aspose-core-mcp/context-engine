#!/usr/bin/env python3
"""Build release-readiness baseline summary from eval/perf reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from adcs.quality_gates import (
    build_release_readiness_summary,
    render_release_readiness_human_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build release-readiness baseline summary.")
    parser.add_argument(
        "--evaluation",
        default="reports/quality-gates/evaluation-summary.json",
        help="Path to golden evaluation summary JSON.",
    )
    parser.add_argument(
        "--perf",
        default="reports/quality-gates/perf-summary.json",
        help="Path to perf summary JSON.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/quality-gates/release-readiness-summary.json",
        help="Machine-readable release-readiness report output path.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/quality-gates/release-readiness-summary.log",
        help="Concise human-readable release-readiness report output path.",
    )
    parser.add_argument(
        "--phase",
        default="mvp",
        choices=("mvp", "preprod", "ga"),
        help="Quality gate phase (controls target enforcement policy).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evaluation_summary = _read_json(Path(args.evaluation))
    perf_summary = _read_json(Path(args.perf))
    summary = build_release_readiness_summary(
        evaluation_summary=evaluation_summary,
        perf_summary=perf_summary,
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
        render_release_readiness_human_report(summary),
        encoding="utf-8",
    )

    print(f"[info] release-readiness summary written: {output_json_path.as_posix()}")
    print(f"[info] release-readiness log written: {output_log_path.as_posix()}")
    if summary.get("blocking_status") != "pass":
        print("[fail] Release readiness is blocked by functional regressions.")
        return 1
    print("[pass] Release readiness baseline completed (MVP tracking mode).")
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"Expected JSON object at `{path.as_posix()}`."
        raise ValueError(msg)
    return payload


if __name__ == "__main__":
    sys.exit(main())
