#!/usr/bin/env python3
# Purpose: Run post-deploy smoke checks against ADCS API/public status endpoints and write a report.
# Source: Project-local deploy verification script for CI/manual smoke windows.
# Example: python3 scripts/checks/deploy/run_postdeploy_smoke.py --base-url http://127.0.0.1:8080

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--output-json",
        default="reports/deploy/smoke-report.json",
    )
    parser.add_argument(
        "--output-log",
        default="reports/deploy/smoke-report.log",
    )
    args = parser.parse_args()

    started_at = datetime.now(tz=UTC)
    checks = []
    checks.append(_run_check(base_url=args.base_url, path="/healthz", expected_status=200))
    checks.append(_run_check(base_url=args.base_url, path="/readyz", expected_status=None))
    checks.append(_run_check(base_url=args.base_url, path="/v1/status", expected_status=200))

    overall_status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
    finished_at = datetime.now(tz=UTC)
    payload = {
        "status": overall_status,
        "target_base_url": args.base_url.rstrip("/"),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "checks": checks,
    }

    output_json_path = Path(args.output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    output_log_path = Path(args.output_log)
    output_log_path.parent.mkdir(parents=True, exist_ok=True)
    output_log_path.write_text(
        "\n".join(
            [
                f"status: {overall_status}",
                *[
                    f"{check['check_id']}: {check['status']} ({check['detail']})"
                    for check in checks
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if overall_status == "pass" else 1


def _run_check(
    *,
    base_url: str,
    path: str,
    expected_status: int | None,
) -> dict[str, str]:
    target_url = f"{base_url.rstrip('/')}{path}"
    try:
        request = Request(target_url, method="GET")
        with urlopen(request, timeout=10) as response:  # noqa: S310
            raw_body = response.read().decode("utf-8")
            if expected_status is not None and response.status != expected_status:
                return {
                    "check_id": path,
                    "status": "fail",
                    "detail": f"expected={expected_status} actual={response.status}",
                }
            return {
                "check_id": path,
                "status": "pass",
                "detail": f"status={response.status} body={raw_body[:120]}",
            }
    except HTTPError as exc:
        if path == "/readyz" and exc.code == 503:
            return {
                "check_id": path,
                "status": "warn",
                "detail": "readyz returned 503",
            }
        return {
            "check_id": path,
            "status": "fail",
            "detail": f"http_error={exc.code}",
        }
    except URLError as exc:
        return {
            "check_id": path,
            "status": "fail",
            "detail": f"url_error={exc.reason}",
        }


if __name__ == "__main__":
    raise SystemExit(main())
