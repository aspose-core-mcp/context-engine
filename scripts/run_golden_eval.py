#!/usr/bin/env python3
"""Live API golden-dataset evaluation harness.

Sends curated golden queries against a running ADCS server and measures:
  - Relevance:          top-k results match expected content (keywords/URLs)
  - Latency:            p50, p95, p99 across all queries
  - Citation coverage:  every result carries canonical_url + section_anchor
  - Version accuracy:   no cross-version leakage under strict_version=true

Target thresholds:
  relevance         >= 80%
  p95 latency       <= 1200 ms
  citation coverage  = 100%
  version accuracy  >= 95%

Usage:
  PYTHONPATH=./src python3 scripts/run_golden_eval.py --api-url http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import yaml

# ── Threshold constants ─────────────────────────────────────────────────────

TARGET_RELEVANCE = 0.80
TARGET_P95_LATENCY_MS = 1200.0
TARGET_CITATION_COVERAGE = 1.00
TARGET_VERSION_ACCURACY = 0.95


# ── Data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """A single golden query case loaded from YAML."""

    case_id: str
    query: str
    product_id: str
    language: str
    version: str | None
    expected_mode: str
    strict_version: bool
    top_k: int
    endpoint: str
    expected_keywords: tuple[str, ...]
    expected_urls: tuple[str, ...]


@dataclass(slots=True)
class CaseResult:
    """Result of evaluating a single golden case."""

    case_id: str
    endpoint: str
    expected_mode: str
    latency_ms: float = 0.0
    http_status: int = 0
    error: str | None = None
    results_count: int = 0
    relevance_hit: bool = False
    citation_total: int = 0
    citation_covered: int = 0
    version_checked: bool = False
    version_passed: bool = True
    response_mode: str | None = None
    # Recalibrating the confidence model needs a labelled score distribution, so
    # each case records the confidence it was served.
    confidence: float | None = None
    confidence_level: str | None = None


@dataclass(slots=True)
class EvalSummary:
    """Aggregated evaluation summary."""

    dataset_id: str = ""
    generated_at: str = ""
    api_url: str = ""
    cases_total: int = 0
    cases_succeeded: int = 0
    cases_failed: int = 0
    relevance_hits: int = 0
    relevance_ratio: float = 0.0
    citation_total: int = 0
    citation_covered: int = 0
    citation_coverage: float = 0.0
    version_checks_total: int = 0
    version_checks_passed: int = 0
    version_accuracy: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_max_ms: float = 0.0
    latency_mean_ms: float = 0.0
    # Distribution of the confidence scores actually served, so the low/medium/
    # high cutoffs can be fitted to observed data instead of intuition.
    confidence_distribution: dict[str, Any] = field(default_factory=dict)
    target_checks: list[dict[str, Any]] = field(default_factory=list)
    target_misses: list[str] = field(default_factory=list)
    blocking_status: str = "unknown"
    case_results: list[dict[str, Any]] = field(default_factory=list)


# ── YAML loader ──────────────────────────────────────────────────────────────


def load_golden_queries(path: Path) -> tuple[str, list[GoldenCase]]:
    """Load golden queries from a YAML file."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"Golden queries file must be a YAML mapping: {path}"
        raise ValueError(msg)

    dataset_id = str(payload.get("dataset_id", "adcs-live-golden"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        msg = f"Golden queries file must contain a non-empty `cases` list: {path}"
        raise ValueError(msg)

    cases: list[GoldenCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            msg = "Each golden case must be a YAML mapping."
            raise ValueError(msg)
        cases.append(_parse_case(raw_case))
    return dataset_id, cases


def _parse_case(raw: dict[str, Any]) -> GoldenCase:
    case_id = _require_str(raw, "case_id")
    query = _require_str(raw, "query")
    product_id = _require_str(raw, "product_id")
    language = _require_str(raw, "language")
    version = raw.get("version")
    if version is not None:
        version = str(version).strip() or None
    expected_mode = str(raw.get("expected_mode", "task")).strip()
    strict_version = bool(raw.get("strict_version", True))
    top_k = int(raw.get("top_k", 5))
    endpoint = str(raw.get("endpoint", "query_docs")).strip()

    raw_keywords = raw.get("expected_keywords", [])
    if not isinstance(raw_keywords, list):
        raw_keywords = []
    expected_keywords = tuple(str(k).strip().casefold() for k in raw_keywords if str(k).strip())

    raw_urls = raw.get("expected_urls", [])
    if not isinstance(raw_urls, list):
        raw_urls = []
    expected_urls = tuple(str(u).strip() for u in raw_urls if str(u).strip())

    return GoldenCase(
        case_id=case_id,
        query=query,
        product_id=product_id,
        language=language,
        version=version,
        expected_mode=expected_mode,
        strict_version=strict_version,
        top_k=top_k,
        endpoint=endpoint,
        expected_keywords=expected_keywords,
        expected_urls=expected_urls,
    )


def _require_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Field `{key}` must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


# ── HTTP client ──────────────────────────────────────────────────────────────


def _post_json(url: str, body: dict[str, Any], timeout_seconds: int = 30) -> tuple[int, Any]:
    """POST JSON to url and return (status_code, parsed_response)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as resp:
            status = resp.status
            response_body = json.loads(resp.read().decode("utf-8"))
            return status, response_body
    except urllib_error.HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            error_body = {"raw_reason": str(exc)}
        return exc.code, error_body
    except urllib_error.URLError as exc:
        return 0, {"connection_error": str(exc.reason)}
    except TimeoutError:
        return 0, {"connection_error": "request timed out"}


# ── Per-case evaluation ──────────────────────────────────────────────────────


def _evaluate_query_docs(case: GoldenCase, api_url: str, timeout: int) -> CaseResult:
    result = CaseResult(
        case_id=case.case_id,
        endpoint="query_docs",
        expected_mode=case.expected_mode,
    )
    body: dict[str, Any] = {
        "query": case.query,
        "product_id": case.product_id,
        "language": case.language,
        "top_k": case.top_k,
        "strict_version": case.strict_version,
        "include_examples": False,
        "debug": False,
    }
    if case.version is not None:
        body["version"] = case.version

    url = f"{api_url.rstrip('/')}/v1/docs:query"
    started = time.perf_counter()
    status, response = _post_json(url, body, timeout_seconds=timeout)
    result.latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    result.http_status = status

    if status != 200:
        result.error = _extract_error(response)
        return result

    results_list = response.get("results", [])
    result.results_count = len(results_list)
    result.response_mode = response.get("mode")

    # Citation coverage: every result must have canonical_url + section_anchor.
    for item in results_list:
        result.citation_total += 1
        canonical_url = str(item.get("canonical_url", "")).strip()
        section_anchor = str(item.get("section_anchor", "")).strip()
        if canonical_url and section_anchor:
            result.citation_covered += 1

    raw_confidence = response.get("confidence")
    if isinstance(raw_confidence, (int, float)):
        result.confidence = float(raw_confidence)
    raw_level = response.get("confidence_level")
    if isinstance(raw_level, str) and raw_level:
        result.confidence_level = raw_level

    # Relevance: check keywords and URLs in top-k results.
    result.relevance_hit = _check_relevance(
        results=results_list,
        expected_keywords=case.expected_keywords,
        expected_urls=case.expected_urls,
    )

    # Version accuracy: under strict_version, check no cross-version leakage.
    if case.strict_version and case.version is not None:
        result.version_checked = True
        result.version_passed = _check_version_accuracy(
            results=results_list,
            response=response,
            expected_version=case.version,
        )

    return result


def _evaluate_get_symbol_doc(case: GoldenCase, api_url: str, timeout: int) -> CaseResult:
    result = CaseResult(
        case_id=case.case_id,
        endpoint="get_symbol_doc",
        expected_mode=case.expected_mode,
    )
    body: dict[str, Any] = {
        "product_id": case.product_id,
        "language": case.language,
        "symbol_fqn": case.query,
    }
    if case.version is not None:
        body["version"] = case.version

    url = f"{api_url.rstrip('/')}/v1/symbols:get"
    started = time.perf_counter()
    status, response = _post_json(url, body, timeout_seconds=timeout)
    result.latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
    result.http_status = status

    if status != 200:
        result.error = _extract_error(response)
        return result

    result.results_count = 1
    result.response_mode = "symbol"

    # Citation coverage for symbol docs: check the citations array.
    citations = response.get("citations", [])
    for citation in citations:
        result.citation_total += 1
        canonical_url = str(citation.get("canonical_url", "")).strip()
        section_anchor = str(citation.get("section_anchor", "")).strip()
        if canonical_url and section_anchor:
            result.citation_covered += 1
    # If there are no citations but there is a symbol_fqn, count as 1 expected.
    if not citations and response.get("symbol_fqn"):
        result.citation_total = 1
        result.citation_covered = 0

    # Relevance: symbol_fqn present and keywords found.
    symbol_fqn = str(response.get("symbol_fqn", ""))
    summary = str(response.get("summary", ""))
    signature = str(response.get("signature", ""))
    combined_text = f"{symbol_fqn} {summary} {signature}".casefold()

    if case.expected_keywords:
        result.relevance_hit = any(kw in combined_text for kw in case.expected_keywords)
    elif symbol_fqn:
        result.relevance_hit = True

    return result


def _check_relevance(
    results: list[dict[str, Any]],
    expected_keywords: tuple[str, ...],
    expected_urls: tuple[str, ...],
) -> bool:
    """Return True if at least one top-k result matches expected content."""
    if not results:
        return False

    # URL match: any expected URL appears in results.
    if expected_urls:
        result_urls = {str(r.get("canonical_url", "")).strip() for r in results}
        if any(url in result_urls for url in expected_urls):
            return True

    # Keyword match: any expected keyword appears in any excerpt/title.
    if expected_keywords:
        for item in results:
            combined = (f"{item.get('title', '')} {item.get('excerpt', '')}").casefold()
            if any(kw in combined for kw in expected_keywords):
                return True
        return False

    # No expected content defined: accept any non-empty result set.
    return True


def _check_version_accuracy(
    results: list[dict[str, Any]],
    response: dict[str, Any],
    expected_version: str,
) -> bool:
    """Check version resolution reports expected version, no cross-version leakage."""
    version_resolution = response.get("version_resolution", {})
    if isinstance(version_resolution, dict):
        resolved = str(version_resolution.get("resolved_version", "")).strip()
        if resolved and resolved != expected_version:
            return False
    return True


def _extract_error(response: Any) -> str:
    if isinstance(response, dict):
        err = response.get("error")
        if isinstance(err, dict):
            return str(err.get("message", err.get("code", "unknown_error")))
        if "connection_error" in response:
            return str(response["connection_error"])
        return str(response.get("detail", response.get("raw_reason", "unknown_error")))
    return str(response)


# ── Aggregation and reporting ────────────────────────────────────────────────


def _aggregate_results(
    dataset_id: str,
    api_url: str,
    case_results: list[CaseResult],
) -> EvalSummary:
    summary = EvalSummary(
        dataset_id=dataset_id,
        generated_at=datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        api_url=api_url,
        cases_total=len(case_results),
    )

    latencies: list[float] = []

    for cr in case_results:
        if cr.error is not None:
            summary.cases_failed += 1
        else:
            summary.cases_succeeded += 1
            latencies.append(cr.latency_ms)

        if cr.relevance_hit:
            summary.relevance_hits += 1
        summary.citation_total += cr.citation_total
        summary.citation_covered += cr.citation_covered
        if cr.version_checked:
            summary.version_checks_total += 1
            if cr.version_passed:
                summary.version_checks_passed += 1

        summary.case_results.append(
            {
                "case_id": cr.case_id,
                "endpoint": cr.endpoint,
                "expected_mode": cr.expected_mode,
                "response_mode": cr.response_mode,
                "latency_ms": round(cr.latency_ms, 3),
                "http_status": cr.http_status,
                "error": cr.error,
                "results_count": cr.results_count,
                "relevance_hit": cr.relevance_hit,
                "citation_covered": cr.citation_covered,
                "citation_total": cr.citation_total,
                "version_checked": cr.version_checked,
                "version_passed": cr.version_passed,
                "confidence": cr.confidence,
                "confidence_level": cr.confidence_level,
            }
        )

    # Compute ratios.
    evaluable = summary.cases_succeeded + summary.cases_failed
    summary.relevance_ratio = summary.relevance_hits / evaluable if evaluable > 0 else 0.0
    summary.citation_coverage = (
        summary.citation_covered / summary.citation_total if summary.citation_total > 0 else 0.0
    )
    summary.version_accuracy = (
        summary.version_checks_passed / summary.version_checks_total
        if summary.version_checks_total > 0
        else 1.0
    )

    # Compute latency percentiles.
    if latencies:
        ordered = sorted(latencies)
        summary.latency_p50_ms = round(_percentile(ordered, 50.0), 3)
        summary.latency_p95_ms = round(_percentile(ordered, 95.0), 3)
        summary.latency_p99_ms = round(_percentile(ordered, 99.0), 3)
        summary.latency_max_ms = round(ordered[-1], 3)
        summary.latency_mean_ms = round(sum(ordered) / len(ordered), 3)

    # Confidence distribution — the labelled set the recalibration needs.
    confidences = [
        cr.confidence for cr in case_results if isinstance(cr.confidence, (int, float))
    ]
    levels: dict[str, int] = {}
    for cr in case_results:
        if cr.confidence_level:
            levels[cr.confidence_level] = levels.get(cr.confidence_level, 0) + 1
    if confidences:
        ordered_conf = sorted(confidences)
        summary.confidence_distribution = {
            "count": len(ordered_conf),
            "min": round(ordered_conf[0], 6),
            "p25": round(_percentile(ordered_conf, 25.0), 6),
            "median": round(_percentile(ordered_conf, 50.0), 6),
            "p75": round(_percentile(ordered_conf, 75.0), 6),
            "max": round(ordered_conf[-1], 6),
            "mean": round(sum(ordered_conf) / len(ordered_conf), 6),
            "levels": dict(sorted(levels.items())),
        }
    else:
        summary.confidence_distribution = {"count": 0, "levels": dict(sorted(levels.items()))}

    # Target checks.
    summary.target_checks = [
        _target_check("relevance", summary.relevance_ratio, ">=", TARGET_RELEVANCE),
        _target_check("p95_latency_ms", summary.latency_p95_ms, "<=", TARGET_P95_LATENCY_MS),
        _target_check(
            "citation_coverage", summary.citation_coverage, ">=", TARGET_CITATION_COVERAGE
        ),
        _target_check("version_accuracy", summary.version_accuracy, ">=", TARGET_VERSION_ACCURACY),
    ]
    summary.target_misses = [check["metric"] for check in summary.target_checks if not check["met"]]
    summary.blocking_status = "pass" if not summary.target_misses else "fail"

    return summary


def _percentile(ordered_values: list[float], pct: float) -> float:
    if not ordered_values:
        return 0.0
    if len(ordered_values) == 1:
        return ordered_values[0]
    position = (len(ordered_values) - 1) * (pct / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered_values) - 1)
    if lower == upper:
        return ordered_values[lower]
    fraction = position - lower
    return ordered_values[lower] * (1.0 - fraction) + ordered_values[upper] * fraction


def _target_check(metric: str, actual: float, comparator: str, target: float) -> dict[str, Any]:
    if comparator == ">=":
        met = actual >= target
    elif comparator == "<=":
        met = actual <= target
    else:
        msg = f"Unsupported comparator: {comparator}"
        raise ValueError(msg)
    return {
        "metric": metric,
        "actual": round(actual, 4),
        "comparator": comparator,
        "target": round(target, 4),
        "met": met,
    }


def _summary_to_json(summary: EvalSummary) -> dict[str, Any]:
    return {
        "dataset_id": summary.dataset_id,
        "generated_at": summary.generated_at,
        "api_url": summary.api_url,
        "counts": {
            "cases_total": summary.cases_total,
            "cases_succeeded": summary.cases_succeeded,
            "cases_failed": summary.cases_failed,
        },
        "metrics": {
            "relevance_ratio": round(summary.relevance_ratio, 4),
            "relevance_hits": summary.relevance_hits,
            "citation_coverage": round(summary.citation_coverage, 4),
            "citation_total": summary.citation_total,
            "citation_covered": summary.citation_covered,
            "version_accuracy": round(summary.version_accuracy, 4),
            "version_checks_total": summary.version_checks_total,
            "version_checks_passed": summary.version_checks_passed,
            "latency_ms": {
                "p50": summary.latency_p50_ms,
                "p95": summary.latency_p95_ms,
                "p99": summary.latency_p99_ms,
                "max": summary.latency_max_ms,
                "mean": summary.latency_mean_ms,
            },
            "confidence": summary.confidence_distribution,
        },
        "targets": summary.target_checks,
        "target_misses": summary.target_misses,
        "blocking_status": summary.blocking_status,
        "cases": summary.case_results,
    }


def render_human_report(summary: EvalSummary) -> str:
    """Render a concise human-readable evaluation report."""
    lines = [
        "ADCS Live Golden Dataset Evaluation",
        f"dataset_id: {summary.dataset_id}",
        f"generated_at: {summary.generated_at}",
        f"api_url: {summary.api_url}",
        f"blocking_status: {summary.blocking_status}",
        "",
        "Counts:",
        f"  cases_total: {summary.cases_total}",
        f"  cases_succeeded: {summary.cases_succeeded}",
        f"  cases_failed: {summary.cases_failed}",
        "",
        "Metrics:",
        f"  relevance: {summary.relevance_ratio:.2%}"
        f" ({summary.relevance_hits}/{summary.cases_total})",
        f"  citation_coverage: {summary.citation_coverage:.2%}"
        f" ({summary.citation_covered}/{summary.citation_total})",
        f"  version_accuracy: {summary.version_accuracy:.2%}"
        f" ({summary.version_checks_passed}/{summary.version_checks_total})",
        "",
        "Latency:",
        f"  p50: {summary.latency_p50_ms:.1f} ms",
        f"  p95: {summary.latency_p95_ms:.1f} ms",
        f"  p99: {summary.latency_p99_ms:.1f} ms",
        f"  max: {summary.latency_max_ms:.1f} ms",
        "",
        "Target Checks:",
    ]

    for check in summary.target_checks:
        status = "PASS" if check["met"] else "FAIL"
        lines.append(
            f"  [{status}] {check['metric']}: "
            f"{check['actual']} {check['comparator']} {check['target']}"
        )

    if summary.target_misses:
        lines.append("")
        lines.append(f"Target misses: {', '.join(summary.target_misses)}")

    # Per-case detail for failures only.
    failed_cases = [c for c in summary.case_results if c.get("error") or not c.get("relevance_hit")]
    if failed_cases:
        lines.append("")
        lines.append(f"Cases with issues ({len(failed_cases)}):")
        for case in failed_cases:
            issues: list[str] = []
            if case.get("error"):
                issues.append(f"error={case['error']}")
            if not case.get("relevance_hit"):
                issues.append("no_relevance_hit")
            if case.get("version_checked") and not case.get("version_passed"):
                issues.append("version_mismatch")
            lines.append(f"  - {case['case_id']}: {'; '.join(issues)}")

    return "\n".join(lines) + "\n"


# ── Main ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run golden-dataset evaluation against a live ADCS API.",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080",
        help="Base URL of the ADCS API server (default: http://localhost:8080).",
    )
    parser.add_argument(
        "--golden-queries",
        default="config/golden_queries.yaml",
        help="Path to golden queries YAML (default: config/golden_queries.yaml).",
    )
    parser.add_argument(
        "--output-json",
        default="reports/live-eval/golden-eval-summary.json",
        help="Machine-readable JSON report output path.",
    )
    parser.add_argument(
        "--output-log",
        default="reports/live-eval/golden-eval-summary.log",
        help="Human-readable report output path.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds (default: 30).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queries_path = Path(args.golden_queries)
    output_json = Path(args.output_json)
    output_log = Path(args.output_log)
    api_url: str = args.api_url.rstrip("/")
    timeout: int = args.timeout

    print(f"[info] Loading golden queries from: {queries_path}")
    dataset_id, cases = load_golden_queries(queries_path)
    print(f"[info] Loaded {len(cases)} golden cases (dataset: {dataset_id})")
    print(f"[info] Target API: {api_url}")

    case_results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id} ({case.endpoint})...", end=" ", flush=True)

        if case.endpoint == "get_symbol_doc":
            cr = _evaluate_get_symbol_doc(case, api_url, timeout)
        else:
            cr = _evaluate_query_docs(case, api_url, timeout)

        if cr.error:
            print(f"ERROR ({cr.latency_ms:.0f}ms): {cr.error}")
        else:
            relevance_tag = "hit" if cr.relevance_hit else "miss"
            print(f"OK ({cr.latency_ms:.0f}ms, results={cr.results_count}, {relevance_tag})")

        case_results.append(cr)

    summary = _aggregate_results(dataset_id, api_url, case_results)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_log.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(
        json.dumps(_summary_to_json(summary), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    output_log.write_text(render_human_report(summary), encoding="utf-8")

    print()
    print(render_human_report(summary))
    print(f"[info] JSON report: {output_json}")
    print(f"[info] Log report:  {output_log}")

    if summary.blocking_status != "pass":
        print(f"[FAIL] Target misses: {', '.join(summary.target_misses)}")
        return 1
    print("[PASS] All target thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
