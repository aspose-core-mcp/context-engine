"""Deterministic golden-dataset evaluation for retrieval quality gates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from adcs.api.public_docs_query import PublicQueryService, QueryDocsRequest
from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet
from adcs.retrieval import TranslationFallbackService
from adcs.retrieval.filter_resolver import normalize_version_hint

TARGET_TOP_3_RELEVANCE = 0.80
TARGET_VERSION_ACCURACY = 0.95
TARGET_CITATION_COVERAGE = 0.98
TARGET_CITATION_INTEGRITY = 1.00
TARGET_QUERY_DOCS_P95_MS = 1200.0
_QUALITY_PHASE_MVP = "mvp"
_QUALITY_PHASE_PREPROD = "preprod"
_QUALITY_PHASE_GA = "ga"


@dataclass(frozen=True, slots=True)
class GoldenDatasetCase:
    """One deterministic golden query case."""

    case_id: str
    query: str
    product_id: str
    language: str
    version: str | None
    query_locale: str | None
    strict_version: bool
    top_k: int
    doc_types: tuple[str, ...]
    include_examples: bool
    expected_canonical_urls: tuple[str, ...]
    expected_version: str | None
    scenario: str | None = None
    scenario_bucket: str | None = None
    generation_source: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> GoldenDatasetCase:
        case_id = _required_non_empty_str(payload=payload, key="case_id")
        query = _required_non_empty_str(payload=payload, key="query")
        product_id = _required_non_empty_str(payload=payload, key="product_id")
        language = _required_non_empty_str(payload=payload, key="language")
        top_k = _positive_int(payload=payload, key="top_k", default=3)
        strict_version = bool(payload.get("strict_version", True))
        version = _optional_non_empty_str(payload=payload, key="version")
        expected_version = _optional_non_empty_str(payload=payload, key="expected_version")
        query_locale = _optional_non_empty_str(payload=payload, key="query_locale") or "en"
        doc_types = _tuple_of_strings(payload=payload, key="doc_types")
        include_examples = bool(payload.get("include_examples", True))
        scenario = _optional_non_empty_str(payload=payload, key="scenario")
        scenario_bucket = _optional_non_empty_str(payload=payload, key="scenario_bucket")
        generation_source = _optional_non_empty_str(payload=payload, key="generation_source")

        expected_canonical_urls = _tuple_of_strings(
            payload=payload,
            key="expected_canonical_urls",
            required=True,
        )
        if not expected_canonical_urls:
            msg = f"Golden case `{case_id}` must provide expected_canonical_urls."
            raise ValueError(msg)

        if strict_version and expected_version is None and version is not None:
            expected_version = version

        return cls(
            case_id=case_id,
            query=query,
            product_id=product_id,
            language=language,
            version=version,
            query_locale=query_locale,
            strict_version=strict_version,
            top_k=top_k,
            doc_types=doc_types,
            include_examples=include_examples,
            expected_canonical_urls=expected_canonical_urls,
            expected_version=expected_version,
            scenario=scenario,
            scenario_bucket=scenario_bucket,
            generation_source=generation_source,
        )

    def to_query_request(self) -> QueryDocsRequest:
        return QueryDocsRequest(
            query=self.query,
            product_id=self.product_id,
            language=self.language,
            version=self.version,
            query_locale=self.query_locale,
            top_k=self.top_k,
            strict_version=self.strict_version,
            doc_types=list(self.doc_types),
            include_examples=self.include_examples,
            debug=False,
        )


@dataclass(frozen=True, slots=True)
class GoldenDataset:
    """A deterministic golden dataset payload."""

    dataset_id: str
    seed: str
    cases: tuple[GoldenDatasetCase, ...]


def load_golden_dataset(path: Path) -> GoldenDataset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Golden dataset must be a JSON object."
        raise ValueError(msg)
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        msg = "Golden dataset must contain a non-empty `cases` array."
        raise ValueError(msg)

    dataset_id = str(payload.get("dataset_id") or "adcs-golden-dataset")
    seed = str(payload.get("seed") or "adcs-f003-seed")
    cases: list[GoldenDatasetCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            msg = "Each golden dataset case must be a JSON object."
            raise ValueError(msg)
        cases.append(GoldenDatasetCase.from_mapping(raw_case))
    return GoldenDataset(dataset_id=dataset_id, seed=seed, cases=tuple(cases))


def load_stage_d_corpus(path: Path) -> tuple[StageDChunkRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Corpus payload must be a JSON object."
        raise ValueError(msg)
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        msg = "Corpus payload must contain a non-empty `records` array."
        raise ValueError(msg)

    records: list[StageDChunkRecord] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            msg = "Each corpus record must be a JSON object."
            raise ValueError(msg)
        section_path = raw_record.get("section_path")
        if not isinstance(section_path, list):
            msg = "Each corpus record must include `section_path` as an array."
            raise ValueError(msg)
        normalized_record = {
            **raw_record,
            "section_path": tuple(str(item) for item in section_path),
            "executable_snippets": _normalize_executable_snippets(
                raw_record.get("executable_snippets")
            ),
        }
        records.append(StageDChunkRecord(**normalized_record))
    return tuple(records)


def build_public_query_service_with_corpus(
    *, corpus: tuple[StageDChunkRecord, ...]
) -> PublicQueryService:
    class _CorpusBackedOrchestrator:
        def get_latest_chunk_records(
            self,
            *,
            product_id: str | None = None,
            programming_language: str | None = None,
            version: str | None = None,
        ) -> tuple[StageDChunkRecord, ...]:
            return tuple(
                record
                for record in corpus
                if _scope_match(record.product_id, product_id)
                and _scope_match(record.programming_language, programming_language)
                and _scope_match(record.version, version)
            )

    translation_service = TranslationFallbackService(
        supported_locales=("en",),
        default_locale="en",
        translation_client=None,
    )
    return PublicQueryService(
        source_hugo_normalization_orchestrator=cast(Any, _CorpusBackedOrchestrator()),
        translation_fallback_service=translation_service,
    )


def run_golden_dataset_evaluation(
    *,
    dataset: GoldenDataset,
    corpus: tuple[StageDChunkRecord, ...],
    phase: str = _QUALITY_PHASE_MVP,
) -> dict[str, Any]:
    normalized_phase = _normalize_quality_phase(phase)
    service = build_public_query_service_with_corpus(corpus=corpus)
    citation_index = {(record.canonical_url, record.section_anchor) for record in corpus}
    chunk_version_index = {
        record.chunk_id: normalize_version_hint(record.version) or record.version
        for record in corpus
    }

    top_3_hits = 0
    top_k_hits = 0
    version_total = 0
    version_hits = 0
    citation_total = 0
    citation_coverage_hits = 0
    citation_integrity_hits = 0

    case_results: list[dict[str, Any]] = []
    functional_regressions: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    scenario_counts: dict[str, int] = {}
    scenario_regressions: dict[str, int] = {}
    product_top3_hits: dict[str, int] = {}
    product_totals: dict[str, int] = {}

    for case in dataset.cases:
        started_at = perf_counter()
        case_regressions: list[str] = []
        error_message: str | None = None
        response = None
        scenario_name = case.scenario or "unspecified"
        _increment_counter(scenario_counts, scenario_name)
        _increment_counter(product_totals, case.product_id)

        try:
            response = service.query_docs(request=case.to_query_request())
        except (ValueError, TypeError, RuntimeError) as exc:
            error_message = str(exc)

        latency_ms = max(0.0, (perf_counter() - started_at) * 1000.0)
        latencies_ms.append(latency_ms)

        if error_message is not None or response is None:
            case_regressions.append("query_execution_failed")
            functional_regressions.append(
                {
                    "case_id": case.case_id,
                    "scenario": scenario_name,
                    "regressions": tuple(case_regressions),
                    "error": error_message or "unknown_execution_error",
                }
            )
            _increment_counter(scenario_regressions, scenario_name)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "scenario": scenario_name,
                    "latency_ms": round(latency_ms, 3),
                    "error": error_message or "unknown_execution_error",
                    "functional_passed": False,
                }
            )
            continue

        result_urls = tuple(item.canonical_url for item in response.results)
        if _has_relevant_url(
            expected_urls=case.expected_canonical_urls,
            actual_urls=result_urls,
            limit=3,
        ):
            top_3_hits += 1
            top_3_hit = True
            _increment_counter(product_top3_hits, case.product_id)
        else:
            top_3_hit = False

        if _has_relevant_url(
            expected_urls=case.expected_canonical_urls,
            actual_urls=result_urls,
            limit=case.top_k,
        ):
            top_k_hits += 1
            top_k_hit = True
        else:
            top_k_hit = False

        version_match: bool | None = None
        if case.strict_version and case.expected_version is not None:
            version_total += 1
            expected_version = (
                normalize_version_hint(case.expected_version) or case.expected_version
            )
            if response.results:
                top_chunk_id = response.results[0].chunk_id
                actual_version = chunk_version_index.get(top_chunk_id)
            else:
                actual_version = None
            version_match = actual_version == expected_version
            if version_match:
                version_hits += 1

        missing_citation_detected = False
        citation_integrity_mismatch = False
        for item in response.results:
            citation_total += 1
            canonical_url = item.canonical_url.strip()
            section_anchor = item.section_anchor.strip()
            has_citation_fields = bool(canonical_url and section_anchor)
            if has_citation_fields:
                citation_coverage_hits += 1
                if (canonical_url, section_anchor) in citation_index:
                    citation_integrity_hits += 1
                else:
                    citation_integrity_mismatch = True
            else:
                missing_citation_detected = True

        if not response.results:
            case_regressions.append("no_results")
        if version_match is False:
            case_regressions.append("strict_version_mismatch")
        if missing_citation_detected:
            case_regressions.append("missing_citation_fields")
        if citation_integrity_mismatch:
            case_regressions.append("citation_integrity_mismatch")

        functional_passed = not case_regressions
        if not functional_passed:
            functional_regressions.append(
                {
                    "case_id": case.case_id,
                    "scenario": scenario_name,
                    "regressions": tuple(case_regressions),
                    "error": None,
                }
            )
            _increment_counter(scenario_regressions, scenario_name)

        case_results.append(
            {
                "case_id": case.case_id,
                "scenario": scenario_name,
                "latency_ms": round(latency_ms, 3),
                "results_count": len(response.results),
                "top_3_hit": top_3_hit,
                "top_k_hit": top_k_hit,
                "version_match": version_match,
                "functional_passed": functional_passed,
                "warnings": tuple(response.warnings),
            }
        )

    cases_total = len(dataset.cases)
    top_3_relevance = _safe_ratio(top_3_hits, cases_total)
    top_k_relevance = _safe_ratio(top_k_hits, cases_total)
    version_accuracy = _safe_ratio(version_hits, version_total)
    citation_coverage = _safe_ratio(citation_coverage_hits, citation_total)
    citation_integrity = _safe_ratio(citation_integrity_hits, citation_total)
    latency_summary = _compute_latency_summary(latencies_ms)
    latency_p95_ms = float(latency_summary["p95_ms"])

    target_checks = (
        _target_check(
            metric="top_3_relevance",
            actual=top_3_relevance,
            comparator=">=",
            target=TARGET_TOP_3_RELEVANCE,
        ),
        _target_check(
            metric="version_accuracy",
            actual=version_accuracy,
            comparator=">=",
            target=TARGET_VERSION_ACCURACY,
        ),
        _target_check(
            metric="citation_coverage",
            actual=citation_coverage,
            comparator=">=",
            target=TARGET_CITATION_COVERAGE,
        ),
        _target_check(
            metric="citation_integrity",
            actual=citation_integrity,
            comparator=">=",
            target=TARGET_CITATION_INTEGRITY,
        ),
        _target_check(
            metric="query_docs_p95_latency_ms",
            actual=latency_p95_ms,
            comparator="<=",
            target=TARGET_QUERY_DOCS_P95_MS,
        ),
    )
    target_misses = tuple(check["metric"] for check in target_checks if not check["met"])
    if normalized_phase == _QUALITY_PHASE_MVP:
        blocking_status = "fail" if functional_regressions else "pass"
        target_enforcement = "track_only"
        blocking_rule = "functional_regressions_only"
    else:
        blocking_status = "fail" if functional_regressions or target_misses else "pass"
        target_enforcement = "hard_block"
        blocking_rule = "functional_regressions_or_target_miss"

    return {
        "generated_at": _utc_now_iso(),
        "dataset_id": dataset.dataset_id,
        "dataset_seed": dataset.seed,
        "policy": {
            "phase": normalized_phase,
            "target_enforcement": target_enforcement,
            "blocking_rule": blocking_rule,
        },
        "counts": {
            "cases_total": cases_total,
            "cases_with_functional_regressions": len(functional_regressions),
            "strict_version_cases": version_total,
            "citation_items_total": citation_total,
        },
        "breakdown": {
            "scenarios": {
                scenario_name: {
                    "cases_total": scenario_counts.get(scenario_name, 0),
                    "regressions": scenario_regressions.get(scenario_name, 0),
                }
                for scenario_name in sorted(scenario_counts)
            },
            "products": {
                pid: {
                    "cases_total": product_totals[pid],
                    "top_3_hits": product_top3_hits.get(pid, 0),
                    "top_3_relevance": round(
                        _safe_ratio(product_top3_hits.get(pid, 0), product_totals[pid]),
                        4,
                    ),
                }
                for pid in sorted(product_totals)
            },
        },
        "metrics": {
            "top_3_relevance": round(top_3_relevance, 4),
            "top_k_relevance": round(top_k_relevance, 4),
            "version_accuracy": round(version_accuracy, 4),
            "citation_coverage": round(citation_coverage, 4),
            "citation_integrity": round(citation_integrity, 4),
            "latency_ms": latency_summary,
        },
        "targets": target_checks,
        "target_misses": target_misses,
        "functional_regressions": functional_regressions,
        "cases": case_results,
        "blocking_status": blocking_status,
    }


def render_golden_eval_human_report(summary: dict[str, Any]) -> str:
    counts = cast(dict[str, Any], summary.get("counts", {}))
    breakdown = cast(dict[str, Any], summary.get("breakdown", {}))
    metrics = cast(dict[str, Any], summary.get("metrics", {}))
    latency = cast(dict[str, Any], metrics.get("latency_ms", {}))
    target_checks = cast(tuple[dict[str, Any], ...], tuple(summary.get("targets", ())))
    target_misses = cast(tuple[str, ...], tuple(summary.get("target_misses", ())))
    regressions = cast(tuple[dict[str, Any], ...], tuple(summary.get("functional_regressions", ())))
    scenario_breakdown = cast(dict[str, Any], breakdown.get("scenarios", {}))

    lines = [
        "ADCS Golden Dataset Evaluation",
        f"dataset_id: {summary.get('dataset_id', 'unknown')}",
        f"generated_at: {summary.get('generated_at', 'unknown')}",
        f"blocking_status: {summary.get('blocking_status', 'unknown')}",
        (
            "cases_total: "
            f"{counts.get('cases_total', 0)} "
            f"(functional_regressions={counts.get('cases_with_functional_regressions', 0)})"
        ),
        (
            "metrics: "
            f"top_3_relevance={metrics.get('top_3_relevance', 0)}; "
            f"top_k_relevance={metrics.get('top_k_relevance', 0)}; "
            f"version_accuracy={metrics.get('version_accuracy', 0)}; "
            f"citation_coverage={metrics.get('citation_coverage', 0)}; "
            f"citation_integrity={metrics.get('citation_integrity', 0)}"
        ),
        (
            "latency_ms: "
            f"p50={latency.get('p50_ms', 0)}; "
            f"p95={latency.get('p95_ms', 0)}; "
            f"max={latency.get('max_ms', 0)}"
        ),
    ]
    if scenario_breakdown:
        lines.append("scenario_breakdown:")
        for scenario_name, scenario_data in scenario_breakdown.items():
            if not isinstance(scenario_data, dict):
                continue
            lines.append(
                f"- {scenario_name}: "
                f"cases_total={scenario_data.get('cases_total', 0)}; "
                f"regressions={scenario_data.get('regressions', 0)}"
            )

    product_breakdown = cast(dict[str, Any], breakdown.get("products", {}))
    if product_breakdown:
        lines.append("product_breakdown:")
        for pid, pdata in product_breakdown.items():
            if not isinstance(pdata, dict):
                continue
            lines.append(
                f"- {pid}: "
                f"top_3={pdata.get('top_3_relevance', 0)} "
                f"({pdata.get('top_3_hits', 0)}/{pdata.get('cases_total', 0)})"
            )

    if target_checks:
        lines.append("target_tracking:")
        for check in target_checks:
            status = "met" if check.get("met", False) else "miss"
            lines.append(
                f"- {check.get('metric')}: {check.get('actual')} "
                f"{check.get('comparator')} {check.get('target')} ({status})"
            )
    if target_misses:
        lines.append(f"target_misses: {', '.join(target_misses)}")
    if regressions:
        lines.append("functional_regressions:")
        for regression in regressions:
            regressions_list = tuple(regression.get("regressions", ()))
            regression_text = ", ".join(str(item) for item in regressions_list)
            lines.append(
                f"- {regression.get('case_id', 'unknown')}: {regression_text}"
            )
    return "\n".join(lines) + "\n"


def _required_non_empty_str(*, payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Field `{key}` must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _optional_non_empty_str(*, payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"Field `{key}` must be a string when provided."
        raise ValueError(msg)
    stripped = value.strip()
    return stripped or None


def _tuple_of_strings(
    *, payload: dict[str, Any], key: str, required: bool = False
) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        if required:
            msg = f"Field `{key}` is required."
            raise ValueError(msg)
        return ()
    if not isinstance(value, list):
        msg = f"Field `{key}` must be an array of strings."
        raise ValueError(msg)
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            msg = f"Field `{key}` must contain only strings."
            raise ValueError(msg)
        normalized = item.strip()
        if normalized:
            result.append(normalized)
    return tuple(result)


def _positive_int(*, payload: dict[str, Any], key: str, default: int) -> int:
    raw_value = payload.get(key, default)
    if not isinstance(raw_value, int) or raw_value < 1:
        msg = f"Field `{key}` must be a positive integer."
        raise ValueError(msg)
    return raw_value


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()


def _normalize_executable_snippets(raw_value: object) -> tuple[StageDExecutableSnippet, ...]:
    if not isinstance(raw_value, list):
        return ()
    snippets: list[StageDExecutableSnippet] = []
    for index, item in enumerate(raw_value, start=1):
        if not isinstance(item, dict):
            continue
        snippets.append(
            StageDExecutableSnippet(
                snippet_id=str(item.get("snippet_id") or f"snippet-{index}"),
                language=str(item.get("language") or "unknown"),
                code=str(item.get("code") or ""),
                parent_canonical_url=str(item.get("parent_canonical_url") or ""),
                parent_section_anchor=str(item.get("parent_section_anchor") or ""),
                parent_symbol_fqn=(
                    str(item["parent_symbol_fqn"])
                    if item.get("parent_symbol_fqn") is not None
                    else None
                ),
            )
        )
    return tuple(snippets)


def _url_match(expected: str, actual: str) -> bool:
    """Bidirectional substring match for canonical URLs.

    Forward: expected is a substring of actual (expected is a prefix/path).
    Reverse: actual is a substring of expected, but only if actual has a
    meaningful path (>=5 segments after split by ``/``) to avoid bare-root
    URLs like ``/net/`` matching everything.
    """
    if expected in actual:
        return True
    if actual in expected:
        stripped = actual.rstrip("/")
        segments = stripped.split("/")
        return len(segments) >= 5
    return False


def _has_relevant_url(
    *, expected_urls: tuple[str, ...], actual_urls: tuple[str, ...], limit: int
) -> bool:
    sliced = actual_urls[: max(limit, 1)]
    if not expected_urls:
        return True
    return any(
        any(_url_match(exp, act) for act in sliced)
        for exp in expected_urls
    )


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / float(denominator)


def _increment_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


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
    *, metric: str, actual: float, comparator: str, target: float
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
