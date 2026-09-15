#!/usr/bin/env python3
"""Run golden-dataset evaluation against live Qdrant/OpenSearch with production embeddings."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

os.environ.setdefault("ADCS_RETRIEVAL_BACKEND", "qdrant_opensearch")
os.environ.setdefault("ADCS_PERSISTENCE_BACKEND", "memory")
os.environ.setdefault("ADCS_TEST_MODE", "false")


def main() -> int:
    from adcs.api.main import create_app
    from adcs.api.public_docs_query import QueryDocsRequest

    dataset_path = Path("artifacts/quality-gates/golden_dataset.json")
    output_path = Path("reports/quality-gates/live-retrieval-eval.json")

    with open(dataset_path) as f:
        dataset = json.load(f)

    app = create_app()
    service = app.state.public_query_service

    cases = dataset["cases"]
    total = len(cases)
    top_1_hits = 0
    top_3_hits = 0
    top_5_hits = 0
    top_k_hits = 0
    version_ok = 0
    version_total = 0
    citation_ok = 0
    citation_total = 0
    errors = 0
    latencies: list[float] = []
    per_product: dict[str, dict[str, int]] = {}

    print(f"Running live retrieval eval: {total} cases")
    t0 = time.monotonic()

    for i, case in enumerate(cases, 1):
        product_id = case["product_id"]
        if product_id not in per_product:
            per_product[product_id] = {"total": 0, "top3": 0}
        per_product[product_id]["total"] += 1

        try:
            request = QueryDocsRequest(
                product_id=product_id,
                query=case["query"],
                language=case.get("language", ""),
                version=case.get("version", ""),
                query_locale=case.get("query_locale", "en"),
                strict_version=case.get("strict_version", False),
                top_k=case.get("top_k", 3),
            )
            ts = time.monotonic()
            response = service.query_docs(request=request)
            latency_ms = (time.monotonic() - ts) * 1000
            latencies.append(latency_ms)
        except Exception as exc:
            errors += 1
            if i <= 5 or i % 50 == 0:
                print(f"  [{i}/{total}] ERROR {case['case_id']}: {exc}")
            continue

        result_urls = [r.canonical_url for r in response.results]
        expected_urls = case.get("expected_canonical_urls", [])

        def _url_match(exp: str, actual: str) -> bool:
            """Bidirectional substring match for canonical URLs.

            Forward: expected is a substring of actual (expected is a prefix).
            Reverse: actual is a substring of expected, but only if actual
            has a meaningful path (≥3 segments after domain) to avoid
            bare-root URLs like ``/net/`` matching everything.
            """
            if exp in actual:
                return True
            # Reverse match: require actual has meaningful depth
            if actual in exp:
                stripped = actual.rstrip("/")
                segments = stripped.split("/")
                # "https://docs.aspose.com/net/aspose.ocr/..." → 5+ segments
                return len(segments) >= 5
            return False

        def _any_hit(expected: list[str], candidates: list[str]) -> bool:
            if not expected:
                return True
            return any(
                any(_url_match(exp, actual) for actual in candidates)
                for exp in expected
            )

        # Top-1 relevance
        if _any_hit(expected_urls, result_urls[:1]):
            top_1_hits += 1

        # Top-3 relevance
        if _any_hit(expected_urls, result_urls[:3]):
            top_3_hits += 1
            per_product[product_id]["top3"] += 1

        # Top-5 relevance
        if _any_hit(expected_urls, result_urls[:5]):
            top_5_hits += 1

        # Top-k relevance
        if _any_hit(expected_urls, result_urls):
            top_k_hits += 1

        # Version accuracy
        expected_version = case.get("expected_version")
        if expected_version and case.get("strict_version"):
            version_total += 1
            if all(
                getattr(r, "version", "") == expected_version
                for r in response.results
                if hasattr(r, "version")
            ):
                version_ok += 1

        # Citation coverage
        for r in response.results:
            citation_total += 1
            if r.canonical_url:
                citation_ok += 1

        if i <= 5 or i % 50 == 0:
            elapsed = time.monotonic() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            print(
                f"  [{i}/{total}] {rate:.1f} cases/s | "
                f"top3={top_3_hits}/{i} ({100*top_3_hits/i:.0f}%) | "
                f"ETA {eta:.0f}s"
            )

    elapsed = time.monotonic() - t0
    evaluated = total - errors

    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    summary = {
        "eval_type": "live_retrieval",
        "total_cases": total,
        "evaluated": evaluated,
        "errors": errors,
        "metrics": {
            "top_1_relevance": round(top_1_hits / evaluated, 4) if evaluated else 0,
            "top_3_relevance": round(top_3_hits / evaluated, 4) if evaluated else 0,
            "top_5_relevance": round(top_5_hits / evaluated, 4) if evaluated else 0,
            "top_k_relevance": round(top_k_hits / evaluated, 4) if evaluated else 0,
            "citation_coverage": round(citation_ok / citation_total, 4) if citation_total else 0,
            "version_accuracy": round(version_ok / version_total, 4) if version_total else 0,
        },
        "latency_ms": {
            "p50": round(p50, 1),
            "p95": round(p95, 1),
            "p99": round(p99, 1),
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        },
        "per_product": {
            pid: {
                "total": v["total"],
                "top3_hits": v["top3"],
                "top3_pct": round(100 * v["top3"] / v["total"], 1) if v["total"] else 0,
            }
            for pid, v in sorted(per_product.items())
        },
        "elapsed_seconds": round(elapsed, 1),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Live Retrieval Eval Complete ({elapsed:.1f}s)")
    print(f"  Cases: {evaluated}/{total} (errors: {errors})")
    print(f"  Top-1 relevance: {summary['metrics']['top_1_relevance']*100:.1f}%")
    print(f"  Top-3 relevance: {summary['metrics']['top_3_relevance']*100:.1f}%")
    print(f"  Top-5 relevance: {summary['metrics']['top_5_relevance']*100:.1f}%")
    print(f"  Top-k relevance: {summary['metrics']['top_k_relevance']*100:.1f}%")
    print(f"  Citation coverage: {summary['metrics']['citation_coverage']*100:.1f}%")
    print(f"  Latency p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms")
    print(f"  Report: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
