#!/usr/bin/env python
"""Latency/throughput benchmark for the structured API-reference endpoints.

Fires concurrent requests at the running API and reports p50/p95/p99 + req/s
per access path (exact get_symbol, list_members, name search, full-text via
search). Pure stdlib (threads + urllib).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://localhost:8080"
SCOPE = {
    "product_id": "aspose.cells",
    "language": "net",
    "version": "latest-stable",
    "locale": "en",
}


def _post(path: str, body: dict) -> float:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception:
        return -1.0
    return (time.perf_counter() - t) * 1000.0


def bench(name: str, path: str, bodies: list[dict], n: int, concurrency: int) -> None:
    calls = [bodies[i % len(bodies)] for i in range(n)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        lat = list(pool.map(lambda b: _post(path, b), calls))
    wall = time.perf_counter() - started
    ok = sorted(x for x in lat if x >= 0)
    fail = len(lat) - len(ok)
    if not ok:
        print(f"{name}: ALL FAILED ({fail})")
        return

    def pct(p: float) -> float:
        return ok[min(len(ok) - 1, int(len(ok) * p))]

    print(
        f"{name:16} n={n} c={concurrency} | "
        f"p50={statistics.median(ok):6.1f}ms p95={pct(0.95):6.1f}ms p99={pct(0.99):6.1f}ms "
        f"max={ok[-1]:6.1f}ms | {n / wall:6.0f} req/s | fail={fail}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2000)
    ap.add_argument("-c", "--concurrency", type=int, default=16)
    args = ap.parse_args()

    get_bodies = [
        {**SCOPE, "symbol_fqn": fqn}
        for fqn in (
            "Aspose.Cells.Workbook",
            "aspose.cells.worksheet",
            "aspose.cells.cell",
            "Aspose.Cells.Style",
        )
    ]
    members_bodies = [
        {**SCOPE, "parent_fqn": p}
        for p in (
            "aspose.cells.workbook",
            "aspose.cells.worksheet",
            "aspose.cells",
            "aspose.cells.cells",
        )
    ]
    search_bodies = [
        {**SCOPE, "query": q} for q in ("Workbook", "Worksheet", "save", "PivotTable", "Chart")
    ]

    print(f"== apiref benchmark @ {BASE} (135k-symbol corpus) ==", flush=True)
    # warmup
    for b in get_bodies:
        _post("/v1/symbols/structured:get", b)
    bench("get_symbol", "/v1/symbols/structured:get", get_bodies, args.n, args.concurrency)
    bench(
        "list_members", "/v1/symbols/structured:members", members_bodies, args.n, args.concurrency
    )
    bench(
        "search_symbols", "/v1/symbols/structured:search", search_bodies, args.n, args.concurrency
    )


if __name__ == "__main__":
    main()
