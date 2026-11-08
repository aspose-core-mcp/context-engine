"""Tests for error-handling hardening in MCP gateway, REST endpoints, and stdio transport."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.mcp.stdio_server import MCPStdioTransport
from adcs.mcp.tool_gateway import MCPToolGateway

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    """Create the ADCS app with sample chunk records wired in."""
    app = create_app()
    orchestrator = app.state.source_hugo_normalization_orchestrator

    records = _sample_chunk_records()

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            r
            for r in records
            if _scope_match(r.product_id, product_id)
            and _scope_match(r.programming_language, programming_language)
            and _scope_match(r.version, version)
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records
    return app


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()


def _sample_chunk_records() -> tuple[StageDChunkRecord, ...]:
    return (
        StageDChunkRecord(
            chunk_id="chunk-api-signature",
            repo_id="aspose.ocr.apiref",
            product_id="aspose.ocr",
            product_family="Aspose.OCR",
            programming_language="net",
            version="25.1",
            source_kind="apiref",
            doc_locale="en",
            doc_type="api_signature",
            symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
            title="RecognizeImage Method",
            section_path=("root", "RecognizeImage Method"),
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/",
            section_anchor="#recognizeimage",
            source_path="source/chunk-api-signature.md",
            source_revision="revision-abc123",
            is_deprecated=False,
            has_code_example=False,
            chunk_type="api_signature",
            text="public RecognitionResult RecognizeImage(string imagePath)",
            tokens=8,
            checksum="checksum-chunk-api-signature",
        ),
    )


def _init_session(client: TestClient) -> str:
    """Initialize an MCP session and return the session_id."""
    resp = client.post("/mcp/v1/initialize", json={})
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# REST endpoint error handling — query_docs
# ---------------------------------------------------------------------------


class TestRestQueryDocsErrorHandling:
    """Verify that RuntimeError and TimeoutError from the service layer
    translate to 503 in the REST query_docs endpoint, with the code that
    distinguishes them: DEPENDENCY_UNAVAILABLE vs TIMEOUT."""

    def test_runtime_error_returns_503(self) -> None:
        app = _build_app()
        service = app.state.public_query_service
        service.query_docs = MagicMock(
            side_effect=RuntimeError("Qdrant cluster unavailable"),
        )
        with TestClient(app) as client:
            resp = client.post(
                "/v1/docs:query",
                json={
                    "query": "How to recognize text?",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "Qdrant cluster unavailable" in body["detail"]["error"]["message"]

    def test_timeout_error_returns_503(self) -> None:
        app = _build_app()
        service = app.state.public_query_service
        service.query_docs = MagicMock(
            side_effect=TimeoutError("query timed out after 5s"),
        )
        with TestClient(app) as client:
            resp = client.post(
                "/v1/docs:query",
                json={
                    "query": "How to recognize text?",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "TIMEOUT"
        assert "query timed out" in body["detail"]["error"]["message"]


# ---------------------------------------------------------------------------
# REST endpoint error handling — list_breaking_changes
# ---------------------------------------------------------------------------


class TestRestListBreakingChangesErrorHandling:
    """Verify that RuntimeError from the service layer translates to
    503 in the REST list_breaking_changes endpoint, with the code that
    distinguishes them: DEPENDENCY_UNAVAILABLE vs TIMEOUT."""

    def test_runtime_error_returns_503(self) -> None:
        app = _build_app()
        service = app.state.public_query_service
        service.list_breaking_changes = MagicMock(
            side_effect=RuntimeError("backend unreachable"),
        )
        with TestClient(app) as client:
            resp = client.post(
                "/v1/changes:list",
                json={
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "from_version": "24.1",
                    "to_version": "25.1",
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "backend unreachable" in body["detail"]["error"]["message"]

    def test_timeout_error_returns_503(self) -> None:
        app = _build_app()
        service = app.state.public_query_service
        service.list_breaking_changes = MagicMock(
            side_effect=TimeoutError("breaking changes query timed out"),
        )
        with TestClient(app) as client:
            resp = client.post(
                "/v1/changes:list",
                json={
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "from_version": "24.1",
                    "to_version": "25.1",
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "TIMEOUT"
        assert "breaking changes query timed out" in body["detail"]["error"]["message"]


# ---------------------------------------------------------------------------
# MCP HTTP gateway error handling — tool call
# ---------------------------------------------------------------------------


class TestMcpGatewayToolCallErrorHandling:
    """Verify that RuntimeError and TimeoutError during MCP tool execution
    translate to correct HTTP error responses via the MCP gateway."""

    def test_runtime_error_returns_503(self) -> None:
        app = _build_app()
        gateway: MCPToolGateway = app.state.mcp_tool_gateway

        def _raise_runtime(
            *,
            session_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            raise RuntimeError("retrieval backend down")

        gateway.call_tool = _raise_runtime  # type: ignore[method-assign]
        with TestClient(app) as client:
            session_id = _init_session(client)
            resp = client.post(
                "/mcp/v1/tools/query_docs",
                json={
                    "session_id": session_id,
                    "arguments": {
                        "query": "test query",
                        "product_id": "aspose.ocr",
                        "language": "net",
                    },
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "retrieval backend down" in body["detail"]["error"]["message"]

    def test_timeout_error_returns_503(self) -> None:
        app = _build_app()
        gateway: MCPToolGateway = app.state.mcp_tool_gateway

        def _raise_timeout(
            *,
            session_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            raise TimeoutError("tool call exceeded 10s deadline")

        gateway.call_tool = _raise_timeout  # type: ignore[method-assign]
        with TestClient(app) as client:
            session_id = _init_session(client)
            resp = client.post(
                "/mcp/v1/tools/query_docs",
                json={
                    "session_id": session_id,
                    "arguments": {
                        "query": "test query",
                        "product_id": "aspose.ocr",
                        "language": "net",
                    },
                },
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["error"]["code"] == "TIMEOUT"
        assert "tool call exceeded 10s deadline" in body["detail"]["error"]["message"]

    def test_validation_error_returns_400(self) -> None:
        """MCP tool call with invalid arguments (e.g. top_k='not_a_number')
        should be caught by Pydantic validation and result in 400."""
        app = _build_app()
        with TestClient(app) as client:
            session_id = _init_session(client)
            resp = client.post(
                "/mcp/v1/tools/query_docs",
                json={
                    "session_id": session_id,
                    "arguments": {
                        "query": "test query",
                        "product_id": "aspose.ocr",
                        "language": "net",
                        "top_k": "not_a_number",
                    },
                },
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# Stdio transport error handling
# ---------------------------------------------------------------------------


class TestStdioTransportErrorHandling:
    """Verify error handling in the MCP stdio transport layer."""

    def _build_transport(self) -> tuple[MCPStdioTransport, MCPToolGateway]:
        app = _build_app()
        gateway: MCPToolGateway = app.state.mcp_tool_gateway
        transport = MCPStdioTransport(gateway=gateway)
        return transport, gateway

    def test_validation_error_returns_invalid_argument(self) -> None:
        """A message that fails MCPStdioRequest validation should return
        INVALID_ARGUMENT error."""
        transport, _ = self._build_transport()
        # method is required with min_length=1, empty string should fail
        result = transport.handle_message({"method": ""})
        assert "error" in result
        assert result["error"]["code"] == "INVALID_ARGUMENT"

    def test_broad_exception_returns_internal_error(self) -> None:
        """An unexpected exception in _dispatch should be caught by the
        broad Exception handler and return a JSON-RPC -32603 error."""
        transport, gateway = self._build_transport()

        # Initialize a session first
        init_result = transport.handle_message({"id": 1, "method": "initialize"})
        session_id = init_result["result"]["session_id"]

        # Monkey-patch call_tool to raise an unexpected exception type
        def _raise_unexpected(
            *,
            session_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            raise Exception("unexpected internal failure")

        gateway.call_tool = _raise_unexpected  # type: ignore[method-assign]
        result = transport.handle_message({
            "id": 2,
            "method": "tools/query_docs",
            "params": {
                "session_id": session_id,
                "arguments": {
                    "query": "test",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            },
        })
        assert "error" in result
        assert result["error"]["code"] == -32603
        assert "Internal error" in result["error"]["message"]

    def test_runtime_error_returns_dependency_unavailable(self) -> None:
        """RuntimeError during tool dispatch should return DEPENDENCY_UNAVAILABLE."""
        transport, gateway = self._build_transport()

        init_result = transport.handle_message({"id": 1, "method": "initialize"})
        session_id = init_result["result"]["session_id"]

        def _raise_runtime(
            *,
            session_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            raise RuntimeError("service crashed")

        gateway.call_tool = _raise_runtime  # type: ignore[method-assign]
        result = transport.handle_message({
            "id": 3,
            "method": "tools/query_docs",
            "params": {
                "session_id": session_id,
                "arguments": {
                    "query": "test",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            },
        })
        assert "error" in result
        assert result["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert "service crashed" in result["error"]["message"]

    def test_timeout_error_returns_timeout(self) -> None:
        """TimeoutError during tool dispatch should return TIMEOUT."""
        transport, gateway = self._build_transport()

        init_result = transport.handle_message({"id": 1, "method": "initialize"})
        session_id = init_result["result"]["session_id"]

        def _raise_timeout(
            *,
            session_id: str,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            raise TimeoutError("operation timed out")

        gateway.call_tool = _raise_timeout  # type: ignore[method-assign]
        result = transport.handle_message({
            "id": 4,
            "method": "tools/query_docs",
            "params": {
                "session_id": session_id,
                "arguments": {
                    "query": "test",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            },
        })
        assert "error" in result
        assert result["error"]["code"] == "TIMEOUT"
        assert "operation timed out" in result["error"]["message"]


def test_validation_error_body_does_not_leak_server_internals() -> None:
    """Public error bodies must not expose the server's filesystem or framework.

    A missing required field on the unauthenticated `/v1/docs:query` must not
    return `str(RequestValidationError)`, which embeds the absolute source path,
    the line number and Pydantic internals, and echoes the caller's input back.
    """
    app = _build_app()
    with TestClient(app) as client:
        response = client.post("/v1/docs:query", json={"product_id": "aspose.ocr"})

    assert response.status_code == 400
    body = response.text
    for leak in ("/Users/", "/app/src/", "Traceback", "errors.pydantic.dev", ".py\", line"):
        assert leak not in body, f"public error body leaks {leak!r}: {body}"

    error = response.json()["error"]
    assert error["code"] == "INVALID_ARGUMENT"
    # Still actionable: the caller learns which field failed and why.
    fields = error["details"]["fields"]
    assert any(item["field"].endswith("query") for item in fields)
    assert any(item["reason"] for item in fields)


def test_public_error_bodies_never_carry_internal_exception_text() -> None:
    """Service failures must not hand the caller server internals.

    Interpolating `str(exc)` into the response body of an unauthenticated code
    path hands a SQLAlchemy driver error or a Pydantic dump to the caller
    verbatim — including the DSN and the server's source path.
    """
    app = _build_app()
    service = app.state.public_query_service

    def _raise_internal(**_: Any) -> None:
        raise RuntimeError(
            '(psycopg.OperationalError) connection to server at "127.0.0.1", port 5432 '
            'failed; see File "/app/src/adcs/api/public_docs_query.py", line 1572'
        )

    service.list_breaking_changes = _raise_internal  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.post(
            "/v1/changes:list",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "from_version": "24.1",
                "to_version": "25.1",
            },
        )

    assert response.status_code == 503
    body = response.text
    for leak in ("psycopg", "127.0.0.1", "/app/src/", "port 5432"):
        assert leak not in body, f"public error body leaks {leak!r}: {body}"
    assert response.json()["detail"]["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_public_error_bodies_keep_deliberate_service_messages() -> None:
    """Sanitising must not flatten messages written for the caller."""
    app = _build_app()
    service = app.state.public_query_service

    def _raise_lookup(**_: Any) -> None:
        raise LookupError("product 'aspose.nope' is not in the catalog")

    service.list_breaking_changes = _raise_lookup  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.post(
            "/v1/changes:list",
            json={
                "product_id": "aspose.nope",
                "language": "net",
                "from_version": "24.1",
                "to_version": "25.1",
            },
        )

    assert response.status_code == 404
    assert "aspose.nope" in response.json()["detail"]["error"]["message"]


def test_debug_payload_requires_a_privileged_caller() -> None:
    """The debug payload is privileged; the endpoint is not.

    An anonymous caller asking for debug=true must not receive the normalised
    query, intent reason codes, snapshot/locale routing order and effective
    filters.
    """
    app = _build_app()
    body = {
        "query": "How to use RecognizeImage?",
        "product_id": "aspose.ocr",
        "language": "net",
        "query_locale": "en",
        "top_k": 2,
        "debug": True,
    }

    with TestClient(app) as client:
        anonymous = client.post("/v1/docs:query", json=body)
        privileged = client.post("/v1/docs:query", json=body, headers={"x-api-key": "replace-me"})

    assert anonymous.status_code == 200
    assert anonymous.json()["debug"] is None, "debug must be withheld from anonymous callers"

    assert privileged.status_code == 200
    assert privileged.json()["debug"] is not None, "a valid admin key must still get debug"
