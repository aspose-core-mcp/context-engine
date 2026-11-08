from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.mcp.stdio_server import MCPStdioTransport


def test_mcp_streamable_http_transport_initialize_and_tool_call() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp/v1/streamable-http/initialize",
            json={"protocol_revision": "2025-10-01"},
        )
        assert initialize_response.status_code == 200
        initialize_payload = initialize_response.json()
        assert initialize_payload["fallback_reason"] == "unknown_revision"

        tool_response = client.post(
            "/mcp/v1/streamable-http/tools/query_docs",
            json={
                "session_id": initialize_payload["session_id"],
                "arguments": _query_docs_arguments(),
            },
        )
        assert tool_response.status_code == 200
        assert tool_response.json()["result"]["results"]


def test_mcp_streamable_http_jsonrpc_initialize_tools_list_and_call() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp/v1/streamable-http",
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {"protocolVersion": "2025-10-01"},
            },
        )
        assert initialize_response.status_code == 200
        initialize_payload = initialize_response.json()
        session_id = initialize_response.headers.get("mcp-session-id")
        assert session_id
        assert initialize_payload["result"]["protocolVersion"] == "2025-06-18"

        tools_response = client.post(
            "/mcp/v1/streamable-http",
            headers={"mcp-session-id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": "tools-1",
                "method": "tools/list",
                "params": {},
            },
        )
        assert tools_response.status_code == 200
        tools_payload = tools_response.json()
        tool_names = {item["name"] for item in tools_payload["result"]["tools"]}
        assert "query_docs" in tool_names
        assert "get_symbol_doc" in tool_names
        assert "list_latest_release_features" in tool_names

        tool_call_response = client.post(
            "/mcp/v1/streamable-http",
            headers={"mcp-session-id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "query_docs", "arguments": _query_docs_arguments()},
            },
        )
        assert tool_call_response.status_code == 200
        tool_call_payload = tool_call_response.json()
        assert tool_call_payload["result"]["structuredContent"]["results"]


def test_mcp_streamable_http_jsonrpc_call_auto_initializes_session() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        tool_call_response = client.post(
            "/mcp/v1/streamable-http",
            json={
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "query_docs", "arguments": _query_docs_arguments()},
            },
        )
        assert tool_call_response.status_code == 200
        assert tool_call_response.headers.get("mcp-session-id")
        payload = tool_call_response.json()
        assert payload["result"]["structuredContent"]["results"]


def test_mcp_sse_transport_initialize_and_tool_call() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp/v1/sse/initialize",
            json={"protocol_revision": "2025-10-01"},
        )
        assert initialize_response.status_code == 200
        assert initialize_response.headers["content-type"].startswith("text/event-stream")
        initialize_event, initialize_payload = _parse_sse_response(initialize_response.text)
        assert initialize_event == "initialize"
        assert initialize_payload["fallback_reason"] == "unknown_revision"

        tool_response = client.post(
            "/mcp/v1/sse/tools/query_docs",
            json={
                "session_id": initialize_payload["session_id"],
                "arguments": _query_docs_arguments(),
            },
        )
        assert tool_response.status_code == 200
        tool_event, tool_payload = _parse_sse_response(tool_response.text)
        assert tool_event == "tool_result"
        assert tool_payload["result"]["results"]


def test_mcp_sse_transport_reports_structured_error_event() -> None:
    app = _create_app_with_records()
    with TestClient(app) as client:
        tool_response = client.post(
            "/mcp/v1/sse/tools/query_docs",
            json={
                "session_id": "missing-session",
                "arguments": _query_docs_arguments(),
            },
        )
        assert tool_response.status_code == 200
        event, payload = _parse_sse_response(tool_response.text)
        assert event == "error"
        assert payload["error"]["code"] == "NOT_FOUND"


def test_mcp_stdio_transport_initialize_and_tool_call() -> None:
    app = _create_app_with_records()
    gateway = app.state.mcp_tool_gateway
    transport = MCPStdioTransport(gateway=gateway)

    initialize_response = transport.handle_message(
        {
            "id": "init-1",
            "method": "initialize",
            "params": {"protocol_revision": "2025-10-01"},
        }
    )
    assert initialize_response["id"] == "init-1"
    assert initialize_response["result"]["fallback_reason"] == "unknown_revision"

    tool_response = transport.handle_message(
        {
            "id": "tool-1",
            "method": "tools/query_docs",
            "params": {
                "session_id": initialize_response["result"]["session_id"],
                "arguments": _query_docs_arguments(),
            },
        }
    )
    assert tool_response["id"] == "tool-1"
    assert tool_response["result"]["result"]["results"]


def test_mcp_transport_matrix_preserves_query_docs_contract_parity() -> None:
    app = _create_app_with_records()

    with TestClient(app) as client:
        http_init = client.post("/mcp/v1/initialize", json={}).json()
        streamable_init = client.post("/mcp/v1/streamable-http/initialize", json={}).json()
        sse_init_event, sse_init_payload = _parse_sse_response(
            client.post("/mcp/v1/sse/initialize", json={}).text
        )
        assert sse_init_event == "initialize"

        http_tool = client.post(
            "/mcp/v1/tools/query_docs",
            json={"session_id": http_init["session_id"], "arguments": _query_docs_arguments()},
        ).json()
        streamable_tool = client.post(
            "/mcp/v1/streamable-http/tools/query_docs",
            json={
                "session_id": streamable_init["session_id"],
                "arguments": _query_docs_arguments(),
            },
        ).json()
        _, sse_tool_payload = _parse_sse_response(
            client.post(
                "/mcp/v1/sse/tools/query_docs",
                json={
                    "session_id": sse_init_payload["session_id"],
                    "arguments": _query_docs_arguments(),
                },
            ).text
        )

    gateway = app.state.mcp_tool_gateway
    stdio_transport = MCPStdioTransport(gateway=gateway)
    stdio_init = stdio_transport.handle_message({"id": 1, "method": "initialize", "params": {}})
    stdio_tool = stdio_transport.handle_message(
        {
            "id": 2,
            "method": "tools/query_docs",
            "params": {
                "session_id": stdio_init["result"]["session_id"],
                "arguments": _query_docs_arguments(),
            },
        }
    )

    assert http_tool["result"]["results"][0]["chunk_id"] == streamable_tool["result"]["results"][0][
        "chunk_id"
    ]
    assert (
        http_tool["result"]["results"][0]["chunk_id"]
        == sse_tool_payload["result"]["results"][0]["chunk_id"]
    )
    assert http_tool["result"]["results"][0]["chunk_id"] == stdio_tool["result"]["result"][
        "results"
    ][0]["chunk_id"]


def _parse_sse_response(body: str) -> tuple[str, dict[str, Any]]:
    event: str | None = None
    payload: dict[str, Any] | None = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_text = line.removeprefix("data:").strip()
            loaded = json.loads(data_text)
            if not isinstance(loaded, dict):
                raise AssertionError("SSE data payload must be an object.")
            payload = loaded
            continue

    if event is None or payload is None:
        raise AssertionError("Incomplete SSE response payload.")
    return event, payload


def _query_docs_arguments() -> dict[str, Any]:
    return {
        "query": "How to use RecognizeImage?",
        "product_id": "aspose.ocr",
        "language": "net",
        "version": "25.1",
        "query_locale": "en",
        "top_k": 2,
    }


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
