#!/usr/bin/env python3
"""Smoke checks for local Docker infra dependencies used by ADCS."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

TIMEOUT_SECONDS = float(os.environ.get("ADCS_INFRA_SMOKE_TIMEOUT_SECONDS", "120"))
INTERVAL_SECONDS = float(os.environ.get("ADCS_INFRA_SMOKE_INTERVAL_SECONDS", "2"))

POSTGRES_HOST = os.environ.get("ADCS_INFRA_POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.environ.get("ADCS_INFRA_POSTGRES_PORT", "5432"))
REDIS_HOST = os.environ.get("ADCS_INFRA_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("ADCS_INFRA_REDIS_PORT", "6379"))
RABBITMQ_HOST = os.environ.get("ADCS_INFRA_RABBITMQ_HOST", "127.0.0.1")
RABBITMQ_PORT = int(os.environ.get("ADCS_INFRA_RABBITMQ_PORT", "5672"))
QDRANT_URL = os.environ.get("ADCS_INFRA_QDRANT_URL", "http://127.0.0.1:6333/readyz")
OPENSEARCH_URL = os.environ.get(
    "ADCS_INFRA_OPENSEARCH_URL",
    "http://127.0.0.1:9200/_cluster/health?wait_for_status=yellow&timeout=5s",
)


def _wait_until_ok(name: str, check: Callable[[], tuple[bool, str]]) -> bool:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_error = "no checks executed"
    while time.monotonic() < deadline:
        ok, details = check()
        if ok:
            print(f"[OK] {name}: {details}")
            return True
        last_error = details
        time.sleep(INTERVAL_SECONDS)
    print(f"[FAIL] {name}: {last_error}", file=sys.stderr)
    return False


def _check_tcp(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, f"tcp://{host}:{port}"
    except OSError as exc:
        return False, f"tcp://{host}:{port} ({exc})"


def _check_redis(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=3) as conn:
            conn.settimeout(3)
            conn.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = conn.recv(64)
        if response.startswith(b"+PONG"):
            return True, f"redis://{host}:{port} (PONG)"
        return False, f"redis://{host}:{port} (unexpected response={response!r})"
    except OSError as exc:
        return False, f"redis://{host}:{port} ({exc})"


def _request_json(url: str) -> tuple[int, Any]:
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return response.status, parsed


def _check_qdrant() -> tuple[bool, str]:
    try:
        status_code, _ = _request_json(QDRANT_URL)
        if status_code == 200:
            return True, f"{QDRANT_URL} (200)"
        return False, f"{QDRANT_URL} (status={status_code})"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, f"{QDRANT_URL} ({exc})"


def _check_opensearch() -> tuple[bool, str]:
    try:
        status_code, payload = _request_json(OPENSEARCH_URL)
        if status_code != 200:
            return False, f"{OPENSEARCH_URL} (status={status_code})"
        if isinstance(payload, dict):
            cluster_state = payload.get("status")
            if cluster_state in {"green", "yellow"}:
                return True, f"{OPENSEARCH_URL} (cluster={cluster_state})"
            return False, f"{OPENSEARCH_URL} (cluster={cluster_state!r})"
        return True, f"{OPENSEARCH_URL} (200)"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, f"{OPENSEARCH_URL} ({exc})"


def main() -> int:
    checks: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
        ("postgres", lambda: _check_tcp(POSTGRES_HOST, POSTGRES_PORT)),
        ("redis", lambda: _check_redis(REDIS_HOST, REDIS_PORT)),
        ("rabbitmq", lambda: _check_tcp(RABBITMQ_HOST, RABBITMQ_PORT)),
        ("qdrant", _check_qdrant),
        ("opensearch", _check_opensearch),
    ]
    results = [_wait_until_ok(name, check) for name, check in checks]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
