from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord


def test_get_symbol_doc_prefers_en_locale_over_other_locales() -> None:
    app = _create_app_with_symbol_locale_records()
    with TestClient(app) as client:
        response = client.post(
            "/v1/symbols:get",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "latest-stable",
                "symbol_fqn": "Aspose.OCR.AsposeOcr.RecognizeImage",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert "Recognize text on image." in payload["summary"]
    assert "/english/" in payload["citations"][0]["canonical_url"]


def test_get_symbol_doc_includes_deprecation_guardrail() -> None:
    app = _create_app_with_symbol_locale_records(deprecated=True)
    with TestClient(app) as client:
        response = client.post(
            "/v1/symbols:get",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "latest-stable",
                "symbol_fqn": "Aspose.OCR.AsposeOcr.RecognizeImage",
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deprecated"] is True
    assert any("deprecated" in rule.casefold() for rule in payload["guardrails"])


def _create_app_with_symbol_locale_records(*, deprecated: bool = False) -> FastAPI:
    app = create_app()
    records = _sample_records(deprecated=deprecated)
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            record
            for record in records
            if _scope_match(record.product_id, product_id)
            and _scope_match(record.programming_language, programming_language)
            and _scope_match(record.version, version)
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]
    # Disable Qdrant direct lookup so the test exercises the state-store fallback path.
    app.state.public_query_service._qdrant_url = None  # type: ignore[attr-defined]
    return app


def _sample_records(*, deprecated: bool = False) -> tuple[StageDChunkRecord, ...]:
    symbol = "Aspose.OCR.AsposeOcr.RecognizeImage"
    return (
        _record(
            chunk_id="chunk-arabic",
            doc_locale="arabic",
            symbol_fqn=symbol,
            text="يتعرف على النص على الصورة.",
            canonical_url="https://docs.aspose.com/arabic/net/aspose.ocr/asposeocr/recognizeimage/",
            is_deprecated=deprecated,
        ),
        _record(
            chunk_id="chunk-english",
            doc_locale="english",
            symbol_fqn=symbol,
            text="Recognize text on image.",
            canonical_url="https://docs.aspose.com/english/net/aspose.ocr/asposeocr/recognizeimage/",
            is_deprecated=deprecated,
        ),
    )


def _record(
    *,
    chunk_id: str,
    doc_locale: str,
    symbol_fqn: str,
    text: str,
    canonical_url: str,
    is_deprecated: bool,
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.apiref",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        version="latest-stable",
        source_kind="apiref",
        doc_locale=doc_locale,
        doc_type="api_signature",
        symbol_fqn=symbol_fqn,
        title="RecognizeImage",
        section_path=("root", "RecognizeImage"),
        canonical_url=canonical_url,
        section_anchor="#recognizeimage",
        source_path=f"source/{chunk_id}.md",
        source_revision="revision-abc123",
        is_deprecated=is_deprecated,
        has_code_example=False,
        chunk_type="api_signature",
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()
