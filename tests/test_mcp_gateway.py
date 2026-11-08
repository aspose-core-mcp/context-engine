from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.mcp import MCPFallbackReason, MCPToolError, negotiate_mcp_revision


def test_revision_negotiation_matrix() -> None:
    supported = ("2025-11-25", "2025-06-18", "2024-11-05")

    exact = negotiate_mcp_revision(
        requested_revision="2025-06-18",
        supported_revisions=supported,
        primary_revision="2025-11-25",
    )
    assert exact.negotiated_revision == "2025-06-18"
    assert exact.fallback_applied is False
    assert exact.fallback_reason is MCPFallbackReason.NONE

    unknown = negotiate_mcp_revision(
        requested_revision="2025-10-01",
        supported_revisions=supported,
        primary_revision="2025-11-25",
    )
    assert unknown.negotiated_revision == "2025-06-18"
    assert unknown.fallback_applied is True
    assert unknown.fallback_reason is MCPFallbackReason.UNKNOWN_REVISION

    below_min = negotiate_mcp_revision(
        requested_revision="2024-01-01",
        supported_revisions=supported,
        primary_revision="2025-11-25",
    )
    assert below_min.negotiated_revision == "2024-11-05"
    assert below_min.fallback_reason is MCPFallbackReason.BELOW_MIN_SUPPORTED

    invalid = negotiate_mcp_revision(
        requested_revision="invalid",
        supported_revisions=supported,
        primary_revision="2025-11-25",
    )
    assert invalid.negotiated_revision == "2025-11-25"
    assert invalid.fallback_reason is MCPFallbackReason.INVALID_REVISION_FORMAT

    missing = negotiate_mcp_revision(
        requested_revision=None,
        supported_revisions=supported,
        primary_revision="2025-11-25",
    )
    assert missing.negotiated_revision == "2025-11-25"
    assert missing.fallback_reason is MCPFallbackReason.MISSING_REQUESTED_REVISION
    # Using the primary target when nothing was requested is the documented
    # outcome, not a fallback — counting it as one would make
    # mcp_negotiation_fail_ratio move on correct handshakes.
    assert missing.fallback_applied is False


def test_mcp_tool_gateway_dispatches_tools_with_negotiated_session() -> None:
    app = _create_app_with_records()
    gateway = app.state.mcp_tool_gateway
    initialized = gateway.initialize(requested_revision="2025-06-18")

    assert initialized.negotiated_revision == "2025-06-18"
    assert initialized.fallback_applied is False

    resolved = gateway.call_tool(
        session_id=initialized.session_id,
        tool_name="resolve_product",
        arguments={"query": "Aspose.OCR for .NET"},
    )
    assert resolved["product_id"] == "aspose.ocr"

    docs_result = gateway.call_tool(
        session_id=initialized.session_id,
        tool_name="query_docs",
        arguments={
            "query": "How to use RecognizeImage?",
            "product_id": "aspose.ocr",
            "language": "net",
            "version": "25.1",
            "query_locale": "en",
            "top_k": 2,
        },
    )
    assert docs_result["results"]
    assert "confidence" in docs_result

    releases_result = gateway.call_tool(
        session_id=initialized.session_id,
        tool_name="list_latest_release_features",
        arguments={
            "product_id": "aspose.ocr",
            "language": "net",
            "top_k": 5,
        },
    )
    assert releases_result["items"]
    assert releases_result["resolved_version"] == "25.1"


def test_mcp_tool_gateway_rejects_unsupported_tool() -> None:
    app = _create_app_with_records()
    gateway = app.state.mcp_tool_gateway
    initialized = gateway.initialize(requested_revision="2025-11-25")

    try:
        gateway.call_tool(
            session_id=initialized.session_id,
            tool_name="unknown_tool",
            arguments={},
        )
    except MCPToolError:
        pass
    else:
        raise AssertionError("Expected MCPToolError for unsupported tool.")


def test_mcp_http_adapter_initialize_and_tool_call() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp/v1/initialize",
            json={"protocol_revision": "2025-10-01"},
        )
        assert initialize_response.status_code == 200
        initialize_payload = initialize_response.json()
        assert initialize_payload["negotiated_revision"] == "2025-06-18"
        assert initialize_payload["fallback_reason"] == "unknown_revision"

        tool_response = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": initialize_payload["session_id"],
                "arguments": {
                    "query": "How to use RecognizeImage?",
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "version": "25.1",
                    "query_locale": "en",
                    "top_k": 2,
                },
            },
        )
        assert tool_response.status_code == 200
        payload = tool_response.json()
        assert payload["result"]["results"]


def test_mcp_http_adapter_returns_structured_errors() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        invalid_session_response = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": "missing",
                "arguments": {
                    "query": "How to use RecognizeImage?",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            },
        )
        assert invalid_session_response.status_code == 404
        invalid_session_payload = invalid_session_response.json()
        assert invalid_session_payload["detail"]["error"]["code"] == "NOT_FOUND"

        initialize_response = client.post("/mcp/v1/initialize", json={})
        session_id = initialize_response.json()["session_id"]
        invalid_tool_response = client.post(
            "/mcp/v1/tools/unknown_tool",
            json={"session_id": session_id, "arguments": {}},
        )
        assert invalid_tool_response.status_code == 400
        invalid_tool_payload = invalid_tool_response.json()
        assert invalid_tool_payload["detail"]["error"]["code"] == "INVALID_ARGUMENT"


def _create_app_with_records() -> FastAPI:
    app = create_app()
    records = _sample_chunk_records()
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


def _sample_chunk_records() -> tuple[StageDChunkRecord, ...]:
    return (
        _record(
            chunk_id="chunk-api-signature",
            source_kind="apiref",
            doc_type="api_signature",
            symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
            title="RecognizeImage Method",
            text=(
                "public RecognitionResult RecognizeImage(string imagePath)\n"
                "Recognize text from one image."
            ),
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/",
            section_anchor="#recognizeimage",
            chunk_type="api_signature",
        ),
        _record(
            chunk_id="chunk-guide",
            source_kind="docs",
            doc_type="guide_step",
            symbol_fqn=None,
            title="How to Recognize Text",
            text="Use Aspose.OCR.AsposeOcr.RecognizeImage in a simple setup flow.",
            canonical_url="https://docs.aspose.com/ocr/net/quickstart/",
            section_anchor="#how-to-recognize-text",
            chunk_type="guide_step",
        ),
        _record(
            chunk_id="chunk-release",
            source_kind="docs",
            doc_type="release_notes",
            symbol_fqn="Aspose.OCR.Legacy.OldRecognize",
            title="Release Notes 25.1",
            text="Breaking change: OldRecognize is deprecated, migrate to RecognizeImage.",
            canonical_url="https://docs.aspose.com/ocr/net/release-notes/25-1/",
            section_anchor="#breaking-changes",
            chunk_type="migration_note",
        ),
    )


def _record(
    *,
    chunk_id: str,
    source_kind: str,
    doc_type: str,
    symbol_fqn: str | None,
    title: str,
    text: str,
    canonical_url: str,
    section_anchor: str,
    chunk_type: str,
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id=f"aspose.ocr.{source_kind}",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version="25.1",
        source_kind=source_kind,
        doc_locale="en",
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=title,
        section_path=("root", title),
        canonical_url=canonical_url,
        section_anchor=section_anchor,
        source_path=f"source/{chunk_id}.md",
        source_revision="revision-abc123",
        is_deprecated=False,
        has_code_example=False,
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()
