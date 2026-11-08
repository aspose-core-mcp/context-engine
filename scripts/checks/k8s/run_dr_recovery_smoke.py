#!/usr/bin/env python3
"""Run deterministic DR recovery smoke check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from adcs.ops import DRSmokeStatus, FileBackedBackupRestoreService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DR recovery smoke workflow.")
    parser.add_argument(
        "--output-json",
        default="reports/dr/recovery-smoke.json",
        help="Path to JSON report.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/dr/recovery-smoke.log",
        help="Path to human-readable report.",
    )
    parser.add_argument(
        "--reason",
        default="ci_dr_smoke",
        help="Reason attached to smoke operation records.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = FileBackedBackupRestoreService()
    result = service.run_recovery_smoke(
        requested_by="dr-smoke-script",
        request_id="dr-smoke-script",
        reason=args.reason,
    )

    output_json = Path(args.output_json)
    output_log = Path(args.output_log)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_log.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "status": result.status.value,
        "backup_operation_id": result.backup_operation_id,
        "restore_operation_id": result.restore_operation_id,
        "backup_id": result.backup_id,
        "details": result.details,
    }
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    human_report = (
        "ADCS DR Recovery Smoke\n"
        f"status: {result.status.value}\n"
        f"backup_operation_id: {result.backup_operation_id}\n"
        f"restore_operation_id: {result.restore_operation_id}\n"
        f"backup_id: {result.backup_id}\n"
        f"details: {result.details}\n"
    )
    output_log.write_text(human_report, encoding="utf-8")

    print(f"[info] report json: {output_json.as_posix()}")
    print(f"[info] report log: {output_log.as_posix()}")
    if result.status is DRSmokeStatus.PASSED:
        print("[pass] DR recovery smoke passed.")
        return 0
    print("[fail] DR recovery smoke failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
