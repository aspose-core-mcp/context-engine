#!/usr/bin/env python3
"""Smoke checks for API health/readiness in docker-compose stack."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

BASE_URL = os.environ.get("ADCS_SMOKE_BASE_URL", "http://localhost:8080").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("ADCS_SMOKE_TIMEOUT_SECONDS", "180"))
INTERVAL_SECONDS = float(os.environ.get("ADCS_SMOKE_INTERVAL_SECONDS", "2"))


def _parse_json_or_text(raw_body: str) -> Any:
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


def _request_json(url: str) -> tuple[int, Any]:
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        return response.status, _parse_json_or_text(body)


def _wait_until_ok(
    name: str,
    url: str,
    validator: Callable[[Any], bool],
) -> bool:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error = "no response received"

    while time.monotonic() < deadline:
        try:
            status_code, payload = _request_json(url)
            if status_code == 200 and validator(payload):
                print(f"[OK] {name}: {url}")
                return True
            last_error = f"status={status_code}, payload={payload!r}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            payload = _parse_json_or_text(body)
            last_error = f"http={exc.code}, payload={payload!r}"
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            last_error = str(exc).strip() or exc.__class__.__name__

        time.sleep(INTERVAL_SECONDS)

    print(f"[FAIL] {name}: {url} ({last_error})", file=sys.stderr)
    return False


def _health_payload_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("status") == "ok"


def _ready_payload_ok(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    if payload.get("status") != "ready":
        return False

    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, dict):
        return False

    required_dependencies = {"postgres", "redis", "qdrant", "opensearch"}
    for dependency_name in required_dependencies:
        dependency_payload = dependencies.get(dependency_name)
        if not isinstance(dependency_payload, dict):
            return False
        if dependency_payload.get("status") != "ready":
            return False
    return True


def main() -> int:
    health_url = f"{BASE_URL}/healthz"
    ready_url = f"{BASE_URL}/readyz"

    print(f"Running smoke checks against {BASE_URL}")
    health_ok = _wait_until_ok("healthz", health_url, _health_payload_ok)
    ready_ok = _wait_until_ok("readyz", ready_url, _ready_payload_ok)

    return 0 if health_ok and ready_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
