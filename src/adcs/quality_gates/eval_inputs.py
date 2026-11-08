"""Builders for golden-eval corpus and dataset artifacts."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet
from adcs.quality_gates.golden_eval import GoldenDataset, GoldenDatasetCase

_VERSION_SEGMENT_RE = re.compile(r"(?:/|^)(latest-stable|\d{2}(?:[.-]\d+)?)(?:/|$)")

_PROGRAMMING_LANGUAGE_DISPLAY = {
    "net": ".NET",
    "java": "Java",
    "cpp": "C++",
    "js": "JavaScript",
    "nodejs-cpp": "Node.js C++",
    "python": "Python",
    "python-java": "Python via Java",
    "python-net": "Python via .NET",
    "python-cpp": "Python via C++",
    "javascript-cpp": "JavaScript C++",
}

_QUERY_LOCALE_BY_DOC_LOCALE = {
    "english": "en",
    "russian": "ru",
    "german": "de",
    "french": "fr",
    "italian": "it",
    "spanish": "es",
    "swedish": "sv",
    "turkish": "tr",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "indonesian": "id",
    "arabic": "ar",
    "greece": "el",
    "netherlands": "nl",
    "indian": "hi",
    "unknown": "en",
}

_STAGING_DATA_ROOTS = (
    Path("data-docs"),
    Path("data-apiref"),
)

_STAGING_DIR_NAME = "_repo-staging"


@dataclass(frozen=True, slots=True)
class GeneratedEvalInputs:
    """Deterministic evaluation inputs and build summary."""

    corpus_records: tuple[StageDChunkRecord, ...]
    stale_baseline_records: tuple[StageDChunkRecord, ...]
    dataset: GoldenDataset
    summary: dict[str, Any]


def default_staging_manifest_paths() -> tuple[Path, ...]:
    """Auto-discover all publish-grade staging manifest paths.

    Scans ``data-docs/`` and ``data-apiref/`` for
    ``<product>/_repo-staging/<repo_id>/repository-manifest.json`` entries.
    Falls back to the legacy Aspose.OCR-only pair if no manifests are found.
    """
    discovered: list[Path] = []
    for root in _STAGING_DATA_ROOTS:
        if not root.is_dir():
            continue
        for product_dir in sorted(root.iterdir()):
            staging_dir = product_dir / _STAGING_DIR_NAME
            if not staging_dir.is_dir():
                continue
            for repo_dir in sorted(staging_dir.iterdir()):
                manifest = repo_dir / "repository-manifest.json"
                if manifest.is_file():
                    discovered.append(manifest)
    if discovered:
        return tuple(sorted(discovered, key=lambda p: p.as_posix()))
    # Fallback: legacy Aspose.OCR-only paths for backward compatibility
    return (
        Path("data-docs/Aspose.OCR/_repo-staging/aspose.ocr.docs/repository-manifest.json"),
        Path("data-apiref/Aspose.OCR/_repo-staging/aspose.ocr.apiref/repository-manifest.json"),
    )


def load_stage_d_corpus_from_staging_manifests(
    manifest_paths: tuple[Path, ...],
) -> tuple[StageDChunkRecord, ...]:
    """Load Stage-D records from publish-grade repository staging manifests."""
    records_by_chunk_id: dict[str, StageDChunkRecord] = {}
    for manifest_path in sorted(manifest_paths, key=lambda item: item.as_posix()):
        manifest_payload = _read_json_object(manifest_path)
        chunk_objects = manifest_payload.get("chunk_objects")
        if not isinstance(chunk_objects, list):
            continue
        for chunk_object in sorted(
            chunk_objects,
            key=lambda item: str(item.get("chunk_path", "")) if isinstance(item, dict) else "",
        ):
            if not isinstance(chunk_object, dict):
                continue
            chunk_path_value = chunk_object.get("chunk_path")
            if not isinstance(chunk_path_value, str) or not chunk_path_value.strip():
                continue
            chunk_path = Path(chunk_path_value)
            chunk_payload = _read_json_object(chunk_path)
            raw_chunk_records = chunk_payload.get("chunk_records")
            if not isinstance(raw_chunk_records, list):
                continue
            for raw_chunk_record in raw_chunk_records:
                if not isinstance(raw_chunk_record, dict):
                    continue
                record = _stage_d_record_from_mapping(raw_chunk_record)
                records_by_chunk_id.setdefault(record.chunk_id, record)
    return tuple(sorted(records_by_chunk_id.values(), key=_chunk_sort_key))


def load_stage_d_corpus_from_artifact(path: Path) -> tuple[StageDChunkRecord, ...]:
    """Load existing artifact corpus if present."""
    if not path.exists():
        return ()
    payload = _read_json_object(path)
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return ()
    records: list[StageDChunkRecord] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        records.append(_stage_d_record_from_mapping(raw_record))
    return tuple(sorted(records, key=_chunk_sort_key))


def build_eval_inputs(
    *,
    staging_manifest_paths: tuple[Path, ...],
    seed_corpus: tuple[StageDChunkRecord, ...] = (),
    seed_dataset_cases: tuple[GoldenDatasetCase, ...] = (),
    target_cases: int = 500,
    dataset_id: str = "adcs-f003-golden-v2",
    seed: str = "adcs-s35-deterministic-seed",
) -> GeneratedEvalInputs:
    """Build deterministic eval corpus, stale baseline corpus, and golden dataset."""
    staging_records = load_stage_d_corpus_from_staging_manifests(staging_manifest_paths)
    corpus_records = _merge_corpora(staging_records, seed_corpus)
    stale_baseline_records = _build_stale_baseline_corpus(records=corpus_records)
    dataset = _build_golden_dataset(
        records=corpus_records,
        seed_cases=seed_dataset_cases,
        target_cases=target_cases,
        dataset_id=dataset_id,
        seed=seed,
    )
    summary = _build_summary(
        corpus_records=corpus_records,
        stale_baseline_records=stale_baseline_records,
        dataset=dataset,
        staging_manifest_paths=staging_manifest_paths,
    )
    return GeneratedEvalInputs(
        corpus_records=corpus_records,
        stale_baseline_records=stale_baseline_records,
        dataset=dataset,
        summary=summary,
    )


def corpus_to_payload(*, records: tuple[StageDChunkRecord, ...]) -> dict[str, Any]:
    """Render Stage-D records as retrieval corpus artifact payload."""
    return {
        "schema_version": "adcs.retrieval_corpus.v2",
        "records": [_chunk_record_to_mapping(record) for record in records],
    }


def dataset_to_payload(*, dataset: GoldenDataset) -> dict[str, Any]:
    """Render golden dataset dataclass as artifact payload."""
    return {
        "dataset_id": dataset.dataset_id,
        "seed": dataset.seed,
        "cases": [_case_to_mapping(case) for case in dataset.cases],
    }


def summary_to_payload(*, inputs: GeneratedEvalInputs) -> dict[str, Any]:
    """Return build summary payload."""
    return dict(inputs.summary)


def _build_golden_dataset(
    *,
    records: tuple[StageDChunkRecord, ...],
    seed_cases: tuple[GoldenDatasetCase, ...],
    target_cases: int,
    dataset_id: str,
    seed: str,
) -> GoldenDataset:
    selected_cases: list[GoldenDatasetCase] = list(seed_cases)
    selected_case_ids = {case.case_id for case in selected_cases}

    generated_groups = (
        _generate_symbol_exact_cases(records=records, limit=max(80, target_cases // 4)),
        _generate_symbol_howto_cases(records=records, limit=max(80, target_cases // 4)),
        _generate_overview_cases(records=records, limit=max(80, target_cases // 4)),
        _generate_product_overview_cases(records=records, limit=max(80, target_cases // 4)),
        # Locale cases excluded until locale-aware retrieval is implemented.
        # _generate_locale_cases(records=records, limit=max(40, target_cases // 6)),
    )
    for group in generated_groups:
        for case in group:
            if case.case_id in selected_case_ids:
                continue
            selected_cases.append(case)
            selected_case_ids.add(case.case_id)
            if len(selected_cases) >= target_cases:
                break
        if len(selected_cases) >= target_cases:
            break

    return GoldenDataset(
        dataset_id=dataset_id,
        seed=seed,
        cases=tuple(selected_cases),
    )


def _generate_symbol_exact_cases(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[GoldenDatasetCase, ...]:
    candidates = [
        record
        for record in records
        if bool(record.symbol_fqn)
        and _has_valid_eval_url(record)
        and _is_english_locale(record)
    ]
    selected = _balanced_pick(records=tuple(candidates), limit=limit)
    return tuple(
        GoldenDatasetCase(
            case_id=f"AUTO-SYM-EXACT-{index:03d}",
            query=str(record.symbol_fqn),
            product_id=record.product_id,
            language=record.programming_language,
            version=record.version,
            query_locale="en",
            strict_version=record.version != "latest-stable",
            top_k=3,
            doc_types=_query_doc_types_for_record(record),
            include_examples=record.has_code_example,
            expected_canonical_urls=(record.canonical_url,),
            expected_version=record.version,
            scenario="symbol_exact",
            scenario_bucket="generated",
            generation_source="staging",
        )
        for index, record in enumerate(selected, start=1)
    )


def _generate_symbol_howto_cases(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[GoldenDatasetCase, ...]:
    candidates = [
        record
        for record in records
        if _is_useful_language(record.programming_language)
        and bool(record.symbol_fqn)
        and _has_valid_eval_url(record)
        and _is_english_locale(record)
    ]
    selected = _balanced_pick(records=tuple(candidates), limit=limit)
    cases: list[GoldenDatasetCase] = []
    for index, record in enumerate(selected, start=1):
        symbol_tail = str(record.symbol_fqn).split(".")[-1]
        language_display = _PROGRAMMING_LANGUAGE_DISPLAY.get(
            record.programming_language, record.programming_language
        )
        cases.append(
            GoldenDatasetCase(
                case_id=f"AUTO-SYM-HOWTO-{index:03d}",
                query=f"How do I use {symbol_tail} in {language_display}?",
                product_id=record.product_id,
                language=record.programming_language,
                version=record.version,
                query_locale="en",
                strict_version=record.version != "latest-stable",
                top_k=3,
                doc_types=_query_doc_types_for_record(record),
                include_examples=True,
                expected_canonical_urls=(record.canonical_url,),
                expected_version=record.version,
                scenario="symbol_howto",
                scenario_bucket="generated",
                generation_source="staging",
            )
        )
    return tuple(cases)


def _generate_overview_cases(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[GoldenDatasetCase, ...]:
    candidates = [
        record
        for record in records
        if _is_useful_language(record.programming_language)
        and record.doc_type in {"index_overview", "guide", "guide_step"}
        and _has_valid_eval_url(record)
        and _is_english_locale(record)
        and _has_meaningful_title(record)
    ]
    selected = _balanced_pick(records=tuple(candidates), limit=limit)
    cases: list[GoldenDatasetCase] = []
    for index, record in enumerate(selected, start=1):
        language_display = _PROGRAMMING_LANGUAGE_DISPLAY.get(
            record.programming_language, record.programming_language
        )
        use_strict = record.version != "latest-stable"
        cases.append(
            GoldenDatasetCase(
                case_id=f"AUTO-OVERVIEW-{index:03d}",
                query=f"{record.title} for {language_display}",
                product_id=record.product_id,
                language=record.programming_language,
                version=record.version,
                query_locale="en",
                strict_version=use_strict,
                top_k=3,
                doc_types=_query_doc_types_for_record(record),
                include_examples=record.has_code_example,
                expected_canonical_urls=(record.canonical_url,),
                expected_version=record.version,
                scenario="task_overview",
                scenario_bucket="generated",
                generation_source="staging",
            )
        )
    return tuple(cases)


def _generate_product_overview_cases(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[GoldenDatasetCase, ...]:
    """Generate overview cases for products with any language (including unknown).

    This covers products whose staging data does not include a specific
    programming_language, ensuring every ingested product gets eval coverage.
    """
    candidates = [
        record
        for record in records
        if record.doc_type in {"index_overview", "guide", "guide_step"}
        and not _is_useful_language(record.programming_language)
        and _has_valid_eval_url(record)
        and _is_english_locale(record)
        and _has_meaningful_title(record)
    ]
    selected = _balanced_pick(records=tuple(candidates), limit=limit)
    cases: list[GoldenDatasetCase] = []
    for index, record in enumerate(selected, start=1):
        product_display = record.product_family or record.product_id
        use_strict = record.version != "latest-stable"
        cases.append(
            GoldenDatasetCase(
                case_id=f"AUTO-PRODOVERVIEW-{index:03d}",
                query=f"{record.title} in {product_display}",
                product_id=record.product_id,
                language=record.programming_language,
                version=record.version,
                query_locale="en",
                strict_version=use_strict,
                top_k=3,
                doc_types=_query_doc_types_for_record(record),
                include_examples=record.has_code_example,
                expected_canonical_urls=(record.canonical_url,),
                expected_version=record.version,
                scenario="product_overview",
                scenario_bucket="generated",
                generation_source="staging",
            )
        )
    return tuple(cases)


def _generate_locale_cases(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[GoldenDatasetCase, ...]:
    candidates = [
        record
        for record in records
        if _is_useful_language(record.programming_language)
        and bool(record.symbol_fqn)
        and record.doc_locale not in {"unknown", "english"}
        and _has_valid_eval_url(record)
    ]
    selected = _balanced_pick(records=tuple(candidates), limit=limit)
    cases: list[GoldenDatasetCase] = []
    for index, record in enumerate(selected, start=1):
        query_locale = _QUERY_LOCALE_BY_DOC_LOCALE.get(record.doc_locale, "en")
        cases.append(
            GoldenDatasetCase(
                case_id=f"AUTO-LOCALE-{index:03d}",
                query=str(record.symbol_fqn),
                product_id=record.product_id,
                language=record.programming_language,
                version=record.version,
                query_locale=query_locale,
                strict_version=True,
                top_k=3,
                doc_types=_query_doc_types_for_record(record),
                include_examples=True,
                expected_canonical_urls=(record.canonical_url,),
                expected_version=record.version,
                scenario="locale_symbol_lookup",
                scenario_bucket="generated",
                generation_source="staging",
            )
        )
    return tuple(cases)


def _balanced_pick(
    *, records: tuple[StageDChunkRecord, ...], limit: int
) -> tuple[StageDChunkRecord, ...]:
    if limit <= 0 or not records:
        return ()
    buckets: dict[tuple[str, str, str], list[StageDChunkRecord]] = defaultdict(list)
    for record in sorted(records, key=_chunk_sort_key):
        bucket_key = (record.product_id, record.programming_language, record.doc_locale)
        buckets[bucket_key].append(record)

    ordered_bucket_keys = sorted(
        buckets.keys(),
        key=lambda item: (
            item[0] == "unknown",
            item[0],
            item[1] == "unknown",
            item[1],
            item[2] == "unknown",
            item[2],
        ),
    )
    selected: list[StageDChunkRecord] = []
    cursor_by_bucket = {bucket_key: 0 for bucket_key in ordered_bucket_keys}

    while len(selected) < limit:
        made_progress = False
        for bucket_key in ordered_bucket_keys:
            cursor = cursor_by_bucket[bucket_key]
            bucket_records = buckets[bucket_key]
            if cursor >= len(bucket_records):
                continue
            selected.append(bucket_records[cursor])
            cursor_by_bucket[bucket_key] = cursor + 1
            made_progress = True
            if len(selected) >= limit:
                break
        if not made_progress:
            break
    return tuple(selected)


def _build_stale_baseline_corpus(
    *, records: tuple[StageDChunkRecord, ...]
) -> tuple[StageDChunkRecord, ...]:
    grouped: dict[tuple[str, str, str, str], list[StageDChunkRecord]] = defaultdict(list)
    for record in records:
        version_key = (
            record.product_id,
            record.programming_language,
            record.source_kind,
            _stale_group_key(record),
        )
        grouped[version_key].append(record)

    selected: list[StageDChunkRecord] = []
    for bucket_records in grouped.values():
        explicit_legacy_records = [
            record
            for record in bucket_records
            if (record.version or "").strip() not in {"", "latest-stable"}
        ]
        if explicit_legacy_records:
            ordered = sorted(
                explicit_legacy_records,
                key=lambda item: (_version_rank(item.version), _chunk_sort_key(item)),
            )
            selected.append(ordered[0])
            continue

        selected.append(min(bucket_records, key=_chunk_sort_key))
    deduped: dict[str, StageDChunkRecord] = {}
    for record in selected:
        deduped.setdefault(record.chunk_id, record)
    return tuple(sorted(deduped.values(), key=_chunk_sort_key))


def _stale_group_key(record: StageDChunkRecord) -> str:
    if record.symbol_fqn:
        return str(record.symbol_fqn)
    normalized_url = _VERSION_SEGMENT_RE.sub("/", record.canonical_url)
    return normalized_url or record.title


def _build_summary(
    *,
    corpus_records: tuple[StageDChunkRecord, ...],
    stale_baseline_records: tuple[StageDChunkRecord, ...],
    dataset: GoldenDataset,
    staging_manifest_paths: tuple[Path, ...],
) -> dict[str, Any]:
    corpus_products = Counter(record.product_id for record in corpus_records)
    corpus_languages = Counter(record.programming_language for record in corpus_records)
    corpus_locales = Counter(record.doc_locale for record in corpus_records)
    corpus_doc_types = Counter(record.doc_type for record in corpus_records)
    case_scenarios = Counter(case.scenario for case in dataset.cases)
    case_products = Counter(case.product_id for case in dataset.cases)
    return {
        "schema_version": "adcs.golden_eval_inputs.v1",
        "staging_manifests": [path.as_posix() for path in staging_manifest_paths],
        "counts": {
            "corpus_records": len(corpus_records),
            "stale_baseline_records": len(stale_baseline_records),
            "dataset_cases": len(dataset.cases),
            "products": len(corpus_products),
        },
        "breakdown": {
            "products": dict(corpus_products),
            "languages": dict(corpus_languages),
            "locales": dict(corpus_locales),
            "doc_types": dict(corpus_doc_types),
            "case_scenarios": dict(case_scenarios),
            "case_products": dict(case_products),
        },
    }


def _chunk_sort_key(record: StageDChunkRecord) -> tuple[str, ...]:
    return (
        record.product_id,
        record.programming_language,
        record.version,
        record.doc_locale,
        record.source_kind,
        record.doc_type,
        record.canonical_url,
        record.chunk_id,
    )


def _merge_corpora(*corpora: tuple[StageDChunkRecord, ...]) -> tuple[StageDChunkRecord, ...]:
    records_by_chunk_id: dict[str, StageDChunkRecord] = {}
    for corpus in corpora:
        for record in corpus:
            records_by_chunk_id.setdefault(record.chunk_id, record)
    return tuple(sorted(records_by_chunk_id.values(), key=_chunk_sort_key))


def _chunk_record_to_mapping(record: StageDChunkRecord) -> dict[str, Any]:
    return {
        "chunk_id": record.chunk_id,
        "repo_id": record.repo_id,
        "product_id": record.product_id,
        "product_family": record.product_family,
        "programming_language": record.programming_language,
        "version": record.version,
        "source_kind": record.source_kind,
        "doc_locale": record.doc_locale,
        "doc_type": record.doc_type,
        "symbol_fqn": record.symbol_fqn,
        "title": record.title,
        "section_path": list(record.section_path),
        "canonical_url": record.canonical_url,
        "section_anchor": record.section_anchor,
        "source_path": record.source_path,
        "source_revision": record.source_revision,
        "is_deprecated": record.is_deprecated,
        "has_code_example": record.has_code_example,
        "chunk_type": record.chunk_type,
        "text": record.text,
        "tokens": record.tokens,
        "checksum": record.checksum,
        "executable_snippets": [
            {
                "snippet_id": snippet.snippet_id,
                "language": snippet.language,
                "code": snippet.code,
                "parent_canonical_url": snippet.parent_canonical_url,
                "parent_section_anchor": snippet.parent_section_anchor,
                "parent_symbol_fqn": snippet.parent_symbol_fqn,
            }
            for snippet in record.executable_snippets
        ],
    }


def _case_to_mapping(case: GoldenDatasetCase) -> dict[str, Any]:
    payload = {
        "case_id": case.case_id,
        "query": case.query,
        "product_id": case.product_id,
        "language": case.language,
        "version": case.version,
        "query_locale": case.query_locale,
        "strict_version": case.strict_version,
        "top_k": case.top_k,
        "doc_types": list(case.doc_types),
        "include_examples": case.include_examples,
        "expected_canonical_urls": list(case.expected_canonical_urls),
        "expected_version": case.expected_version,
    }
    if case.scenario is not None:
        payload["scenario"] = case.scenario
    if case.scenario_bucket is not None:
        payload["scenario_bucket"] = case.scenario_bucket
    if case.generation_source is not None:
        payload["generation_source"] = case.generation_source
    return payload


def _stage_d_record_from_mapping(payload: dict[str, Any]) -> StageDChunkRecord:
    section_path_raw = payload.get("section_path", ())
    if isinstance(section_path_raw, list):
        section_path = tuple(str(item) for item in section_path_raw)
    elif isinstance(section_path_raw, tuple):
        section_path = tuple(str(item) for item in section_path_raw)
    else:
        section_path = ()
    raw_snippets = payload.get("executable_snippets", ())
    snippets = tuple(_snippet_from_mapping(item, index) for index, item in enumerate(raw_snippets))
    return StageDChunkRecord(
        chunk_id=str(payload.get("chunk_id", "")),
        repo_id=str(payload.get("repo_id", "")),
        product_id=str(payload.get("product_id", "")),
        product_family=str(payload.get("product_family", "")),
        programming_language=str(payload.get("programming_language", "")),
        version=str(payload.get("version", "")),
        source_kind=str(payload.get("source_kind", "")),
        doc_locale=str(payload.get("doc_locale", "")),
        doc_type=str(payload.get("doc_type", "")),
        symbol_fqn=_optional_string(payload.get("symbol_fqn")),
        title=str(payload.get("title", "")),
        section_path=section_path,
        canonical_url=str(payload.get("canonical_url", "")),
        section_anchor=str(payload.get("section_anchor", "")),
        source_path=str(payload.get("source_path", "")),
        source_revision=str(payload.get("source_revision", "")),
        is_deprecated=bool(payload.get("is_deprecated", False)),
        has_code_example=bool(payload.get("has_code_example", False)),
        chunk_type=str(payload.get("chunk_type", "")),
        text=str(payload.get("text", "")),
        tokens=int(payload.get("tokens", 0)),
        checksum=str(payload.get("checksum", "")),
        executable_snippets=snippets,
    )


def _snippet_from_mapping(payload: Any, index: int) -> StageDExecutableSnippet:
    if not isinstance(payload, dict):
        return StageDExecutableSnippet(
            snippet_id=f"snippet-{index}",
            language="unknown",
            code="",
            parent_canonical_url="",
            parent_section_anchor="",
            parent_symbol_fqn=None,
        )
    return StageDExecutableSnippet(
        snippet_id=str(payload.get("snippet_id", f"snippet-{index}")),
        language=str(payload.get("language", "unknown")),
        code=str(payload.get("code", "")),
        parent_canonical_url=str(payload.get("parent_canonical_url", "")),
        parent_section_anchor=str(payload.get("parent_section_anchor", "")),
        parent_symbol_fqn=_optional_string(payload.get("parent_symbol_fqn")),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at `{path.as_posix()}`.")
    return payload


def _version_rank(version: str) -> tuple[int, int]:
    if version == "latest-stable":
        return (9999, 9999)
    normalized = version.replace("-", ".")
    pieces = normalized.split(".")
    if len(pieces) < 2:
        return (0, 0)
    try:
        return (int(pieces[0]), int(pieces[1]))
    except ValueError:
        return (0, 0)


def _is_useful_language(language: str) -> bool:
    return language not in {"unknown", "apps", ""}


def _has_valid_eval_url(record: StageDChunkRecord) -> bool:
    """Reject records with bare-root canonical URLs unsuitable for eval.

    A valid URL must have at least 3 path segments after the domain
    (e.g. ``/ocr/net/quickstart/``).  Bare language roots like
    ``https://docs.aspose.com/java/`` produce false-negative eval hits
    because they are not substrings of content URLs for any specific product.

    Also rejects ``reference.aspose.com`` URLs — this domain is not indexed
    in the current pipeline (only ``docs.aspose.com`` is indexed).
    """
    url = record.canonical_url.rstrip("/")
    if "://" not in url:
        return False
    # reference.aspose.com is not indexed; only docs.aspose.com
    if "reference.aspose.com" in url:
        return False
    path = url.split("://", 1)[1]
    # path = "docs.aspose.com/ocr/net/quickstart" → split("/") → 4 parts
    segments = path.split("/")
    # segments[0] is domain; we need ≥3 path segments after domain
    return len(segments) >= 4


def _is_english_locale(record: StageDChunkRecord) -> bool:
    """Only allow English-locale records for eval until locale retrieval is live.

    Non-English records produce canonical URLs with locale prefixes (``/ar/``,
    ``/zh/``) that the current retrieval pipeline does not return, causing
    systematic false-negative eval hits.
    """
    return record.doc_locale in {"english", "en", "unknown", ""}


def _has_meaningful_title(record: StageDChunkRecord) -> bool:
    """Reject records whose title is a filesystem artifact or placeholder.

    Titles like ``_index``, empty strings, or single-character values
    produce low-quality auto-generated queries that pollute eval results.
    """
    title = (record.title or "").strip()
    if len(title) < 3:
        return False
    if title.startswith("_"):
        return False
    return True


def _query_doc_types_for_record(record: StageDChunkRecord) -> tuple[str, ...]:
    if record.source_kind == "apiref":
        return ("api_reference",)
    return ("guide",)
