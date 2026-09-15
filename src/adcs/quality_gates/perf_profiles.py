"""Deterministic local load/perf profile scaffolding for MVP gates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet
from adcs.quality_gates.golden_eval import (
    TARGET_QUERY_DOCS_P95_MS,
    GoldenDataset,
    GoldenDatasetCase,
    build_public_query_service_with_corpus,
)

TARGET_QUERY_DOCS_P50_MS = 350.0
_QUALITY_PHASE_MVP = "mvp"
_QUALITY_PHASE_PREPROD = "preprod"
_QUALITY_PHASE_GA = "ga"
_MAX_SIMULATED_PRODUCTS = 500
_PRODUCT_MARKER_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PerfProfile:
    """One local perf profile definition."""

    profile_id: str
    target_rps: int
    duration_seconds: int
    run_by_default: bool
    description: str
    simulated_products: int = 1
    required_min_products: int = 0


def load_perf_profiles(path: Path) -> tuple[PerfProfile, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Perf profile file must be a JSON object."
        raise ValueError(msg)
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        msg = "Perf profile file must contain a non-empty `profiles` array."
        raise ValueError(msg)

    profiles: list[PerfProfile] = []
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict):
            msg = "Each perf profile must be a JSON object."
            raise ValueError(msg)
        profile_id = _required_non_empty_str(raw_profile, "profile_id")
        target_rps = _positive_int(raw_profile, "target_rps")
        duration_seconds = _positive_int(raw_profile, "duration_seconds")
        run_by_default = bool(raw_profile.get("run_by_default", False))
        description = str(raw_profile.get("description") or "").strip()
        simulated_products = _positive_int(raw_profile, "simulated_products", default=1)
        required_min_products = _non_negative_int(
            raw_profile,
            "required_min_products",
            default=0,
        )
        profiles.append(
            PerfProfile(
                profile_id=profile_id,
                target_rps=target_rps,
                duration_seconds=duration_seconds,
                run_by_default=run_by_default,
                description=description,
                simulated_products=simulated_products,
                required_min_products=required_min_products,
            )
        )
    return tuple(profiles)


def run_perf_profiles(
    *,
    dataset: GoldenDataset,
    corpus: tuple[StageDChunkRecord, ...],
    profiles: tuple[PerfProfile, ...],
    selected_profile_ids: tuple[str, ...] | None = None,
    phase: str = _QUALITY_PHASE_MVP,
) -> dict[str, Any]:
    normalized_phase = _normalize_quality_phase(phase)
    selected = _resolve_selected_profile_ids(
        profiles=profiles,
        selected_profile_ids=selected_profile_ids,
    )

    profile_results: list[dict[str, Any]] = []
    aggregated_regressions: list[dict[str, Any]] = []
    target_misses: list[str] = []

    for profile in profiles:
        if profile.profile_id not in selected:
            profile_results.append(
                {
                    "profile_id": profile.profile_id,
                    "target_rps": profile.target_rps,
                    "duration_seconds": profile.duration_seconds,
                    "executed": False,
                    "reason": "not_selected",
                    "description": profile.description,
                    "simulated_products": profile.simulated_products,
                    "required_min_products": profile.required_min_products,
                }
            )
            continue

        profile_dataset, profile_corpus, capacity_summary = _prepare_profile_inputs(
            dataset=dataset,
            corpus=corpus,
            profile=profile,
        )
        service = build_public_query_service_with_corpus(corpus=profile_corpus)
        profile_result = _run_single_profile(
            dataset=profile_dataset,
            profile=profile,
            service=service,
        )
        profile_result["capacity"] = capacity_summary
        profile_result["simulated_products"] = profile.simulated_products
        profile_result["required_min_products"] = profile.required_min_products

        targets = profile_result.get("targets", ())
        if isinstance(targets, list):
            targets = tuple(targets)
        if isinstance(targets, tuple) and profile.required_min_products > 0:
            capacity_target = _target_check(
                metric="simulated_product_count",
                actual=float(capacity_summary["unique_products_corpus"]),
                comparator=">=",
                target=float(profile.required_min_products),
            )
            profile_result["targets"] = (*targets, capacity_target)

        profile_results.append(profile_result)
        regressions = profile_result.get("functional_regressions", ())
        if isinstance(regressions, list):
            regressions = tuple(regressions)
        if isinstance(regressions, tuple):
            aggregated_regressions.extend(regressions)

        checks = profile_result.get("targets", ())
        if isinstance(checks, tuple):
            for check in checks:
                if not bool(check.get("met", False)):
                    target_misses.append(f"{profile.profile_id}:{check.get('metric')}")

    capacity_profiles_executed = [
        item
        for item in profile_results
        if isinstance(item, dict)
        and bool(item.get("executed", False))
        and isinstance(item.get("capacity"), dict)
    ]
    max_products_corpus = 0
    max_products_dataset = 0
    required_capacity_failures = 0
    for profile_result_entry in capacity_profiles_executed:
        capacity = profile_result_entry.get("capacity", {})
        if not isinstance(capacity, dict):
            continue
        unique_products_corpus = int(capacity.get("unique_products_corpus", 0))
        unique_products_dataset = int(capacity.get("unique_products_dataset", 0))
        max_products_corpus = max(max_products_corpus, unique_products_corpus)
        max_products_dataset = max(max_products_dataset, unique_products_dataset)
        required_min_products = int(capacity.get("required_min_products", 0))
        meets_min_products = bool(capacity.get("meets_required_min_products", True))
        if required_min_products > 0 and not meets_min_products:
            required_capacity_failures += 1

    if normalized_phase == _QUALITY_PHASE_MVP:
        blocking_status = "fail" if aggregated_regressions else "pass"
        target_enforcement = "track_only"
        blocking_rule = "functional_regressions_only"
    else:
        blocking_status = "fail" if aggregated_regressions or target_misses else "pass"
        target_enforcement = "hard_block"
        blocking_rule = "functional_regressions_or_target_miss"
    return {
        "generated_at": _utc_now_iso(),
        "policy": {
            "phase": normalized_phase,
            "target_enforcement": target_enforcement,
            "blocking_rule": blocking_rule,
        },
        "counts": {
            "profiles_defined": len(profiles),
            "profiles_executed": sum(1 for item in profile_results if item.get("executed", False)),
            "functional_regressions": len(aggregated_regressions),
            "capacity_profiles_executed": len(capacity_profiles_executed),
            "required_capacity_failures": required_capacity_failures,
        },
        "capacity": {
            "max_unique_products_dataset": max_products_dataset,
            "max_unique_products_corpus": max_products_corpus,
        },
        "profiles": profile_results,
        "target_misses": tuple(target_misses),
        "functional_regressions": aggregated_regressions,
        "blocking_status": blocking_status,
    }


def render_perf_human_report(summary: dict[str, Any]) -> str:
    counts = summary.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    profiles = summary.get("profiles", ())
    if not isinstance(profiles, list):
        profiles = []

    lines = [
        "ADCS Local Perf Profiles",
        f"generated_at: {summary.get('generated_at', 'unknown')}",
        f"blocking_status: {summary.get('blocking_status', 'unknown')}",
        (
            "profiles: "
            f"defined={counts.get('profiles_defined', 0)}; "
            f"executed={counts.get('profiles_executed', 0)}; "
            f"functional_regressions={counts.get('functional_regressions', 0)}; "
            f"capacity_profiles={counts.get('capacity_profiles_executed', 0)}"
        ),
    ]

    capacity_summary = summary.get("capacity", {})
    if isinstance(capacity_summary, dict):
        max_unique_products_dataset = capacity_summary.get("max_unique_products_dataset", 0)
        max_unique_products_corpus = capacity_summary.get("max_unique_products_corpus", 0)
        lines.append(
            "capacity: "
            f"max_unique_products_dataset={max_unique_products_dataset}; "
            f"max_unique_products_corpus={max_unique_products_corpus}"
        )

    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        profile_id = profile.get("profile_id", "unknown")
        if not profile.get("executed", False):
            lines.append(f"- {profile_id}: skipped ({profile.get('reason', 'not_selected')})")
            continue

        latency = profile.get("latency_ms", {})
        if not isinstance(latency, dict):
            latency = {}
        lines.append(
            f"- {profile_id}: target_rps={profile.get('target_rps', 0)}; "
            f"achieved_rps={profile.get('achieved_rps', 0)}; "
            f"error_rate={profile.get('error_rate', 0)}; "
            f"p95_ms={latency.get('p95_ms', 0)}"
        )
        capacity = profile.get("capacity", {})
        if isinstance(capacity, dict):
            lines.append(
                "  capacity: "
                f"simulated_products={capacity.get('simulated_products_target', 0)}; "
                f"unique_products_corpus={capacity.get('unique_products_corpus', 0)}; "
                f"required_min_products={capacity.get('required_min_products', 0)}"
            )

    target_misses = summary.get("target_misses", ())
    if isinstance(target_misses, (tuple, list)) and target_misses:
        lines.append(f"target_misses: {', '.join(str(item) for item in target_misses)}")
    return "\n".join(lines) + "\n"


def _run_single_profile(
    *,
    dataset: GoldenDataset,
    profile: PerfProfile,
    service: Any,
) -> dict[str, Any]:
    if not dataset.cases:
        msg = "Golden dataset cases are required for perf profile execution."
        raise ValueError(msg)
    requests_total = max(1, profile.target_rps * profile.duration_seconds)

    latencies_ms: list[float] = []
    failed_requests = 0
    error_buckets: dict[str, int] = {}
    started_at = perf_counter()

    for request_index in range(requests_total):
        expected_at = started_at + (request_index / profile.target_rps)
        delay_seconds = expected_at - perf_counter()
        if delay_seconds > 0:
            sleep(delay_seconds)

        case = dataset.cases[request_index % len(dataset.cases)]
        request_started_at = perf_counter()
        request_failed = False
        try:
            response = service.query_docs(request=case.to_query_request())
            if not response.results:
                request_failed = True
                error_buckets["empty_results"] = error_buckets.get("empty_results", 0) + 1
        except (ValueError, TypeError, RuntimeError):
            request_failed = True
            error_buckets["query_execution_failed"] = (
                error_buckets.get("query_execution_failed", 0) + 1
            )

        latency_ms = max(0.0, (perf_counter() - request_started_at) * 1000.0)
        latencies_ms.append(latency_ms)
        if request_failed:
            failed_requests += 1

    elapsed_seconds = max(perf_counter() - started_at, 1e-9)
    achieved_rps = requests_total / elapsed_seconds
    error_rate = failed_requests / float(requests_total)
    latency_summary = _compute_latency_summary(latencies_ms)
    latency_p95_ms = float(latency_summary["p95_ms"])

    target_checks = (
        _target_check(
            metric="throughput_rps",
            actual=achieved_rps,
            comparator=">=",
            target=float(profile.target_rps),
        ),
        _target_check(
            metric="query_docs_p50_latency_ms",
            actual=float(latency_summary["p50_ms"]),
            comparator="<=",
            target=TARGET_QUERY_DOCS_P50_MS,
        ),
        _target_check(
            metric="query_docs_p95_latency_ms",
            actual=latency_p95_ms,
            comparator="<=",
            target=TARGET_QUERY_DOCS_P95_MS,
        ),
        _target_check(
            metric="error_rate",
            actual=error_rate,
            comparator="<=",
            target=0.01,
        ),
    )
    blocking_status = "fail" if failed_requests > 0 else "pass"
    return {
        "profile_id": profile.profile_id,
        "target_rps": profile.target_rps,
        "duration_seconds": profile.duration_seconds,
        "description": profile.description,
        "executed": True,
        "simulated_products": profile.simulated_products,
        "required_min_products": profile.required_min_products,
        "requests_total": requests_total,
        "failed_requests": failed_requests,
        "error_rate": round(error_rate, 4),
        "achieved_rps": round(achieved_rps, 3),
        "latency_ms": latency_summary,
        "targets": target_checks,
        "functional_regressions": (
            ()
            if failed_requests == 0
            else (
                {
                    "profile_id": profile.profile_id,
                    "regression": "request_failures_detected",
                    "failed_requests": failed_requests,
                    "error_buckets": error_buckets,
                },
            )
        ),
        "blocking_status": blocking_status,
    }


def _resolve_selected_profile_ids(
    *, profiles: tuple[PerfProfile, ...], selected_profile_ids: tuple[str, ...] | None
) -> set[str]:
    if selected_profile_ids:
        return {profile_id.strip() for profile_id in selected_profile_ids if profile_id.strip()}
    defaults = {profile.profile_id for profile in profiles if profile.run_by_default}
    if defaults:
        return defaults
    return {profile.profile_id for profile in profiles}


def _prepare_profile_inputs(
    *,
    dataset: GoldenDataset,
    corpus: tuple[StageDChunkRecord, ...],
    profile: PerfProfile,
) -> tuple[GoldenDataset, tuple[StageDChunkRecord, ...], dict[str, Any]]:
    if profile.simulated_products > _MAX_SIMULATED_PRODUCTS:
        msg = (
            "Perf profile simulated_products exceeds supported limit: "
            f"{profile.simulated_products}>{_MAX_SIMULATED_PRODUCTS}."
        )
        raise ValueError(msg)

    if profile.simulated_products <= 1:
        dataset_products = {case.product_id for case in dataset.cases}
        corpus_products = {record.product_id for record in corpus}
        capacity = {
            "simulated_products_target": profile.simulated_products,
            "required_min_products": profile.required_min_products,
            "unique_products_dataset": len(dataset_products),
            "unique_products_corpus": len(corpus_products),
            "meets_required_min_products": (
                len(corpus_products) >= profile.required_min_products
                if profile.required_min_products > 0
                else True
            ),
        }
        return dataset, corpus, capacity
    return _synthesize_multi_product_inputs(
        dataset=dataset,
        corpus=corpus,
        profile=profile,
    )


def _synthesize_multi_product_inputs(
    *,
    dataset: GoldenDataset,
    corpus: tuple[StageDChunkRecord, ...],
    profile: PerfProfile,
) -> tuple[GoldenDataset, tuple[StageDChunkRecord, ...], dict[str, Any]]:
    base_product_ids = tuple(
        dict.fromkeys(
            [
                *(case.product_id for case in dataset.cases),
                *(record.product_id for record in corpus),
            ]
        )
    )
    if not base_product_ids:
        msg = "Unable to synthesize multi-product perf dataset without base product ids."
        raise ValueError(msg)

    target_products = max(profile.simulated_products, len(base_product_ids))
    expanded_product_ids: list[str] = list(base_product_ids)
    synthetic_index = 1
    while len(expanded_product_ids) < target_products:
        template_product_id = base_product_ids[
            (len(expanded_product_ids) - len(base_product_ids)) % len(base_product_ids)
        ]
        expanded_product_ids.append(f"{template_product_id}.sim{synthetic_index:03d}")
        synthetic_index += 1

    cases_by_product: dict[str, list[GoldenDatasetCase]] = {}
    for case in dataset.cases:
        cases_by_product.setdefault(case.product_id, []).append(case)

    records_by_product: dict[str, list[StageDChunkRecord]] = {}
    for record in corpus:
        records_by_product.setdefault(record.product_id, []).append(record)

    expanded_cases: list[GoldenDatasetCase] = []
    expanded_records: list[StageDChunkRecord] = []

    for index, product_id in enumerate(expanded_product_ids):
        template_product_id = base_product_ids[index % len(base_product_ids)]
        template_cases = cases_by_product.get(template_product_id) or list(dataset.cases)
        for case in template_cases:
            expanded_cases.append(_clone_case_for_product(case=case, product_id=product_id))

        template_records = records_by_product.get(template_product_id) or list(corpus)
        for record in template_records:
            expanded_records.append(_clone_record_for_product(record=record, product_id=product_id))

    expanded_dataset = GoldenDataset(
        dataset_id=f"{dataset.dataset_id}-capacity-{target_products}",
        seed=dataset.seed,
        cases=tuple(expanded_cases),
    )
    expanded_corpus = tuple(expanded_records)
    unique_products_dataset = len({case.product_id for case in expanded_dataset.cases})
    unique_products_corpus = len({record.product_id for record in expanded_corpus})
    capacity = {
        "simulated_products_target": target_products,
        "required_min_products": profile.required_min_products,
        "unique_products_dataset": unique_products_dataset,
        "unique_products_corpus": unique_products_corpus,
        "meets_required_min_products": (
            unique_products_corpus >= profile.required_min_products
            if profile.required_min_products > 0
            else True
        ),
    }
    return expanded_dataset, expanded_corpus, capacity


def _clone_case_for_product(*, case: GoldenDatasetCase, product_id: str) -> GoldenDatasetCase:
    marker = _slugify_product_id(product_id)
    expected_canonical_urls = tuple(
        _append_product_marker_to_url(url=url, marker=marker)
        for url in case.expected_canonical_urls
    )
    return replace(
        case,
        case_id=f"{case.case_id}::{marker}",
        product_id=product_id,
        expected_canonical_urls=expected_canonical_urls,
    )


def _clone_record_for_product(
    *,
    record: StageDChunkRecord,
    product_id: str,
) -> StageDChunkRecord:
    marker = _slugify_product_id(product_id)
    canonical_url = _append_product_marker_to_url(url=record.canonical_url, marker=marker)
    section_anchor = f"{record.section_anchor}-{marker}"
    source_path = f"{record.source_path}#adcs-product={marker}"
    snippets: tuple[StageDExecutableSnippet, ...] = tuple(
        replace(
            snippet,
            snippet_id=f"{snippet.snippet_id}::{marker}",
            parent_canonical_url=canonical_url,
            parent_section_anchor=section_anchor,
        )
        for snippet in record.executable_snippets
    )
    return replace(
        record,
        chunk_id=f"{record.chunk_id}::{marker}",
        product_id=product_id,
        canonical_url=canonical_url,
        section_anchor=section_anchor,
        source_path=source_path,
        executable_snippets=snippets,
    )


def _append_product_marker_to_url(*, url: str, marker: str) -> str:
    parts = urlsplit(url)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    query_pairs.append(("adcs_product", marker))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query_pairs, doseq=True),
            parts.fragment,
        )
    )


def _slugify_product_id(product_id: str) -> str:
    normalized = product_id.strip().casefold()
    if not normalized:
        return "product"
    slug = _PRODUCT_MARKER_RE.sub("-", normalized).strip("-")
    return slug or "product"


def _required_non_empty_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Field `{key}` must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _positive_int(payload: dict[str, Any], key: str, *, default: int | None = None) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value < 1:
        msg = f"Field `{key}` must be a positive integer."
        raise ValueError(msg)
    return value


def _non_negative_int(payload: dict[str, Any], key: str, *, default: int = 0) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value < 0:
        msg = f"Field `{key}` must be a non-negative integer."
        raise ValueError(msg)
    return value


def _compute_latency_summary(latencies_ms: list[float]) -> dict[str, float | int]:
    if not latencies_ms:
        return {
            "samples": 0,
            "min_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
        }
    ordered = sorted(latencies_ms)
    return {
        "samples": len(ordered),
        "min_ms": round(ordered[0], 3),
        "p50_ms": round(_percentile(ordered, 50.0), 3),
        "p95_ms": round(_percentile(ordered, 95.0), 3),
        "p99_ms": round(_percentile(ordered, 99.0), 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(sum(ordered) / len(ordered), 3),
    }


def _percentile(ordered_values: list[float], percentile: float) -> float:
    if not ordered_values:
        return 0.0
    if len(ordered_values) == 1:
        return ordered_values[0]
    position = (len(ordered_values) - 1) * (percentile / 100.0)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered_values) - 1)
    if lower_index == upper_index:
        return ordered_values[lower_index]
    fraction = position - lower_index
    return (
        ordered_values[lower_index] * (1.0 - fraction)
        + ordered_values[upper_index] * fraction
    )


def _target_check(
    *,
    metric: str,
    actual: float,
    comparator: str,
    target: float,
) -> dict[str, Any]:
    if comparator == ">=":
        met = actual >= target
    elif comparator == "<=":
        met = actual <= target
    else:
        msg = f"Unsupported comparator `{comparator}`."
        raise ValueError(msg)
    return {
        "metric": metric,
        "actual": round(actual, 4),
        "comparator": comparator,
        "target": round(target, 4),
        "met": met,
    }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _normalize_quality_phase(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {_QUALITY_PHASE_MVP, _QUALITY_PHASE_PREPROD, _QUALITY_PHASE_GA}:
        return normalized
    msg = (
        "quality phase must be one of: "
        f"{_QUALITY_PHASE_MVP}, {_QUALITY_PHASE_PREPROD}, {_QUALITY_PHASE_GA}."
    )
    raise ValueError(msg)
