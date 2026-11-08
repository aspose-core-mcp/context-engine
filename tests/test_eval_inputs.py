from __future__ import annotations

import json
from pathlib import Path

from adcs.ingestion.chunking import StageDChunkRecord
from adcs.quality_gates import GoldenDatasetCase, build_eval_inputs


def test_build_eval_inputs_preserves_seed_cases_and_generates_target_count(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(
        tmp_path=tmp_path,
        records=(
            _record(
                chunk_id="chunk-current",
                version="latest-stable",
                canonical_url="https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
                doc_locale="english",
            ),
            _record(
                chunk_id="chunk-guide",
                version="latest-stable",
                canonical_url="https://docs.aspose.com/ocr/net/quickstart/getting-started/",
                doc_locale="english",
                doc_type="guide",
            ),
        ),
    )

    inputs = build_eval_inputs(
        staging_manifest_paths=(manifest_path,),
        seed_corpus=(),
        seed_dataset_cases=(
            GoldenDatasetCase(
                case_id="seed-case",
                query="RecognizeImage 24.12",
                product_id="aspose.ocr",
                language="net",
                version="24.12",
                query_locale="en",
                strict_version=True,
                top_k=3,
                doc_types=("api_signature",),
                include_examples=True,
                expected_canonical_urls=(
                    "https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/24-12/",
                ),
                expected_version="24.12",
                scenario="seed_release_case",
                scenario_bucket="seed",
                generation_source="legacy_artifact",
            ),
        ),
        target_cases=4,
    )

    assert len(inputs.dataset.cases) >= 4
    assert inputs.dataset.cases[0].case_id == "seed-case"
    assert inputs.summary["counts"]["dataset_cases"] >= 4
    assert inputs.summary["breakdown"]["case_scenarios"]["seed_release_case"] == 1
    assert inputs.summary["breakdown"]["case_scenarios"]["symbol_exact"] >= 1


def test_build_eval_inputs_prefers_explicit_legacy_versions_for_stale_baseline(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(
        tmp_path=tmp_path,
        records=(
            _record(
                chunk_id="chunk-current",
                version="latest-stable",
                canonical_url="https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
            ),
        ),
    )

    inputs = build_eval_inputs(
        staging_manifest_paths=(manifest_path,),
        seed_corpus=(
            _record(
                chunk_id="chunk-legacy",
                version="24.12",
                canonical_url="https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/24-12/",
            ),
        ),
        seed_dataset_cases=(),
        target_cases=2,
    )

    stale_versions = {record.version for record in inputs.stale_baseline_records}
    stale_chunk_ids = {record.chunk_id for record in inputs.stale_baseline_records}
    assert "24.12" in stale_versions
    assert "chunk-legacy" in stale_chunk_ids
    assert "chunk-current" not in stale_chunk_ids


def _write_manifest(*, tmp_path: Path, records: tuple[StageDChunkRecord, ...]) -> Path:
    chunk_path = tmp_path / "chunk.json"
    chunk_path.write_text(
        json.dumps(
            {
                "chunk_records": [_record_to_payload(record) for record in records],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "chunk_objects": [
                    {
                        "chunk_path": chunk_path.as_posix(),
                    }
                ]
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _record(
    *,
    chunk_id: str,
    version: str,
    canonical_url: str,
    doc_locale: str = "english",
    doc_type: str = "api_signature",
) -> StageDChunkRecord:
    source_kind = "apiref" if doc_type == "api_signature" else "docs"
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.apiref",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version=version,
        source_kind=source_kind,
        doc_locale=doc_locale,
        doc_type=doc_type,
        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
        title="RecognizeImage",
        section_path=("AsposeOcr", "RecognizeImage"),
        canonical_url=canonical_url,
        section_anchor="recognizeimage",
        source_path=f"source/{chunk_id}.md",
        source_revision=f"rev-{version}",
        is_deprecated=False,
        has_code_example=True,
        chunk_type="api_signature",
        text="public RecognitionResult RecognizeImage(string imagePath)",
        tokens=7,
        checksum=f"checksum-{chunk_id}",
    )


def _record_to_payload(record: StageDChunkRecord) -> dict[str, object]:
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
        "executable_snippets": [],
    }
