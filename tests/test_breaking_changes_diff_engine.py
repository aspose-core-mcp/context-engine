from __future__ import annotations

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord


def test_list_breaking_changes_diff_engine_is_deterministic_and_paged() -> None:
    app = _create_app_with_versioned_records()
    with TestClient(app) as client:
        payload = {
            "product_id": "aspose.ocr",
            "language": "net",
            "from_version": "24.12",
            "to_version": "25.1",
            "page": 1,
            "page_size": 2,
        }
        first = client.post("/v1/changes:list", json=payload)
        second = client.post("/v1/changes:list", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()

        first_body = first.json()
        assert first_body["total"] == 4
        assert first_body["items"][0]["type"] == "symbol_removed"
        assert first_body["items"][1]["type"] == "symbol_changed"

        page_2 = client.post(
            "/v1/changes:list",
            json={**payload, "page": 2},
        )
        assert page_2.status_code == 200
        page_2_body = page_2.json()
        assert page_2_body["total"] == 4
        assert [item["type"] for item in page_2_body["items"]] == [
            "symbol_deprecated",
            "breaking_change_note",
        ]


def test_list_breaking_changes_mcp_and_rest_parity() -> None:
    app = _create_app_with_versioned_records()
    with TestClient(app) as client:
        request_payload = {
            "product_id": "aspose.ocr",
            "language": "net",
            "from_version": "24.12",
            "to_version": "25.1",
            "page": 1,
            "page_size": 10,
        }
        rest_response = client.post("/v1/changes:list", json=request_payload)
        assert rest_response.status_code == 200
        rest_body = rest_response.json()

        initialize_response = client.post("/mcp/v1/initialize", json={})
        assert initialize_response.status_code == 200
        session_id = initialize_response.json()["session_id"]
        mcp_response = client.post(
            "/mcp/v1/tools/list_breaking_changes",
            json={"session_id": session_id, "arguments": request_payload},
        )
        assert mcp_response.status_code == 200
        mcp_body = mcp_response.json()["result"]

    assert mcp_body == rest_body


def _create_app_with_versioned_records() -> FastAPI:
    app = create_app()
    records = _versioned_records()
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
    return app


def _versioned_records() -> tuple[StageDChunkRecord, ...]:
    return (
        _record(
            chunk_id="from-symbol-a",
            version="24.12",
            symbol_fqn="Aspose.OCR.Engine.Run",
            text="public Result Run(string imagePath)",
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/run/",
            section_anchor="#run",
            chunk_type="api_signature",
            doc_type="api_signature",
            is_deprecated=False,
        ),
        _record(
            chunk_id="from-symbol-b",
            version="24.12",
            symbol_fqn="Aspose.OCR.Engine.LegacyRun",
            text="public Result LegacyRun(string imagePath)",
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/legacyrun/",
            section_anchor="#legacyrun",
            chunk_type="api_signature",
            doc_type="api_signature",
            is_deprecated=False,
        ),
        _record(
            chunk_id="from-symbol-d",
            version="24.12",
            symbol_fqn="Aspose.OCR.Engine.Experimental",
            text="public Result Experimental(string imagePath)",
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/experimental/",
            section_anchor="#experimental",
            chunk_type="api_signature",
            doc_type="api_signature",
            is_deprecated=False,
        ),
        _record(
            chunk_id="to-symbol-a",
            version="25.1",
            symbol_fqn="Aspose.OCR.Engine.Run",
            text="public Result Run(byte[] imageData)",
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/run/",
            section_anchor="#run",
            chunk_type="api_signature",
            doc_type="api_signature",
            is_deprecated=False,
        ),
        _record(
            chunk_id="to-symbol-d",
            version="25.1",
            symbol_fqn="Aspose.OCR.Engine.Experimental",
            text="public Result Experimental(string imagePath)",
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/experimental/",
            section_anchor="#experimental",
            chunk_type="api_signature",
            doc_type="api_signature",
            is_deprecated=True,
        ),
        _record(
            chunk_id="to-release-note",
            version="25.1",
            symbol_fqn=None,
            text="Breaking change: LegacyRun was removed in 25.1. Use Run instead.",
            canonical_url="https://docs.aspose.com/ocr/net/release-notes/25-1/",
            section_anchor="#breaking-changes",
            chunk_type="migration_note",
            doc_type="release_notes",
            is_deprecated=False,
        ),
    )


def _record(
    *,
    chunk_id: str,
    version: str,
    symbol_fqn: str | None,
    text: str,
    canonical_url: str,
    section_anchor: str,
    chunk_type: str,
    doc_type: str,
    is_deprecated: bool,
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.apiref",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version=version,
        source_kind="apiref",
        doc_locale="en",
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=chunk_id,
        section_path=("root", chunk_id),
        canonical_url=canonical_url,
        section_anchor=section_anchor,
        source_path=f"source/{chunk_id}.md",
        source_revision=f"rev-{version}",
        is_deprecated=is_deprecated,
        has_code_example=False,
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{hashlib.sha256(text.encode()).hexdigest()[:16]}",
    )


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()
