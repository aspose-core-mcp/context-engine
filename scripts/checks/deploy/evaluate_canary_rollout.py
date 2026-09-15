#!/usr/bin/env python3
# Purpose: Evaluate latest deploy smoke report against canary policy and emit go/rollback decision.
# Source: Project-local release-gate helper for CI and manual rollout checks.
# Example: python3 scripts/checks/deploy/evaluate_canary_rollout.py --smoke-report reports/deploy/smoke-report.json

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy-json",
        default="config/canary-policy.json",
    )
    parser.add_argument(
        "--smoke-report",
        default="reports/deploy/smoke-report.json",
    )
    parser.add_argument(
        "--output-json",
        default="reports/deploy/canary-evaluation.json",
    )
    parser.add_argument(
        "--output-log",
        default="reports/deploy/canary-evaluation.log",
    )
    args = parser.parse_args()

    policy = _read_json(Path(args.policy_json))
    smoke_report = _read_json(Path(args.smoke_report))

    enabled = bool(policy.get("enabled", True))
    smoke_status = str(smoke_report.get("status", "unknown"))
    if not enabled:
        decision = "skipped"
        reason = "canary_disabled"
    elif smoke_status == "pass":
        decision = "promote"
        reason = "smoke_checks_passed"
    else:
        decision = "rollback" if bool(policy.get("auto_rollback", True)) else "hold"
        reason = "smoke_checks_failed"

    payload = {
        "decision": decision,
        "reason": reason,
        "policy": {
            "enabled": enabled,
            "initial_traffic_pct": int(policy.get("initial_traffic_pct", 10)),
            "full_traffic_pct": int(policy.get("full_traffic_pct", 100)),
            "analysis_window_minutes": int(policy.get("analysis_window_minutes", 15)),
            "max_error_rate_pct": float(policy.get("max_error_rate_pct", 1.0)),
            "max_latency_p95_ms": int(policy.get("max_latency_p95_ms", 1200)),
            "auto_rollback": bool(policy.get("auto_rollback", True)),
        },
        "smoke_status": smoke_status,
        "target_base_url": smoke_report.get("target_base_url"),
    }

    output_json_path = Path(args.output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    output_log_path = Path(args.output_log)
    output_log_path.parent.mkdir(parents=True, exist_ok=True)
    output_log_path.write_text(
        f"decision: {decision}\nreason: {reason}\nsmoke_status: {smoke_status}\n",
        encoding="utf-8",
    )
    return 0 if decision in {"promote", "skipped"} else 1


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
