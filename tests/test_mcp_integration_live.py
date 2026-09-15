"""End-to-end MCP integration tests against real Qdrant/OpenSearch.

These tests require live infrastructure (Qdrant, OpenSearch, embedding API).
They are skipped automatically when backends are unreachable.

Run explicitly:
    PYTHONPATH=./src python3 -m pytest tests/test_mcp_integration_live.py -v
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any
from urllib import error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Skip conditions — bail out early if infrastructure is unreachable.
# ---------------------------------------------------------------------------

_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")


def _is_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3):
            return True
    except (error.URLError, TimeoutError, OSError):
        return False


_qdrant_live = _is_reachable(_QDRANT_URL)
_opensearch_live = _is_reachable(_OPENSEARCH_URL)

# When the caller demands the live surface (`make test-live`), an unreachable
# backend must fail rather than skip — a silent skip is what let these assertions
# read as green while the surface they cover was broken.
_require_live = os.environ.get("ADCS_REQUIRE_LIVE_SURFACE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _require_live and not (_qdrant_live and _opensearch_live),
        reason="Qdrant and/or OpenSearch not reachable — skipping live integration tests",
    ),
]

# ---------------------------------------------------------------------------
# App fixture — creates a FastAPI app wired to real backends.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_app() -> FastAPI:
    """Create app connected to real Qdrant/OpenSearch."""
    os.environ["ADCS_RETRIEVAL_BACKEND"] = "qdrant_opensearch"
    os.environ["ADCS_PERSISTENCE_BACKEND"] = "memory"
    os.environ["ADCS_TEST_MODE"] = "false"

    from adcs.api.main import create_app

    app = create_app()

    # Verify lane adapters are real, not in-memory stubs.
    assert app.state.public_query_service._dense_lane_adapter is not None
    assert app.state.public_query_service._lexical_lane_adapter is not None
    return app


@pytest.fixture(scope="module")
def client(live_app: FastAPI) -> TestClient:
    with TestClient(live_app) as c:
        yield c


@pytest.fixture(scope="module")
def session_id(client: TestClient) -> str:
    resp = client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# MCP Initialize
# ---------------------------------------------------------------------------


class TestMCPInitialize:
    def test_initialize_returns_session_and_capabilities(self, client: TestClient) -> None:
        resp = client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"]
        assert data["negotiated_revision"] == "2025-11-25"
        assert data["fallback_applied"] is False
        assert "query_docs" in data["capabilities"]["tools"]
        assert "resolve_product" in data["capabilities"]["tools"]
        assert "get_symbol_doc" in data["capabilities"]["tools"]

    def test_initialize_with_old_revision_falls_back(self, client: TestClient) -> None:
        resp = client.post("/mcp/v1/initialize", json={"protocol_revision": "2024-01-01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["fallback_applied"] is True


# ---------------------------------------------------------------------------
# resolve_product — real product registry
# ---------------------------------------------------------------------------


class TestResolveProduct:
    def test_resolve_aspose_ocr(self, client: TestClient, session_id: str) -> None:
        resp = client.post(
            "/mcp/v1/tools/resolve_product",
            json={"session_id": session_id, "arguments": {"query": "Aspose OCR"}},
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["product_id"] == "aspose.ocr"

    def test_resolve_aspose_cells(self, client: TestClient, session_id: str) -> None:
        resp = client.post(
            "/mcp/v1/tools/resolve_product",
            json={"session_id": session_id, "arguments": {"query": "Aspose.Cells"}},
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["product_id"] == "aspose.cells"

    def test_resolve_groupdocs_viewer(self, client: TestClient, session_id: str) -> None:
        resp = client.post(
            "/mcp/v1/tools/resolve_product",
            json={"session_id": session_id, "arguments": {"query": "groupdocs viewer"}},
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["product_id"] == "groupdocs.viewer"


# ---------------------------------------------------------------------------
# query_docs — real vector + lexical retrieval
# ---------------------------------------------------------------------------


class TestQueryDocs:
    def test_query_aspose_ocr_returns_results(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "How to recognize text from an image",
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "query_locale": "en",
                    "top_k": 5,
                },
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert len(result["results"]) > 0
        first = result["results"][0]
        assert first["canonical_url"]
        assert first["chunk_id"]
        assert "score" in first

    def test_query_aspose_words_returns_results(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "How to convert document to PDF",
                    "product_id": "aspose.words",
                    "language": "net",
                    "query_locale": "en",
                    "top_k": 3,
                },
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert len(result["results"]) > 0

    def test_query_results_have_citation_fields(
        self, client: TestClient, session_id: str
    ) -> None:
        """Every result MUST include citation metadata."""
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "PDF document conversion",
                    "product_id": "aspose.pdf",
                    "language": "net",
                    "top_k": 3,
                },
            },
        )
        assert resp.status_code == 200
        results = resp.json()["result"]["results"]
        for item in results:
            assert "canonical_url" in item, "Missing citation: canonical_url"
            assert "chunk_id" in item
            assert "score" in item

    def test_query_respects_top_k_limit(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "barcode generation",
                    "product_id": "aspose.barcode",
                    "language": "net",
                    "top_k": 2,
                },
            },
        )
        assert resp.status_code == 200
        results = resp.json()["result"]["results"]
        assert len(results) <= 2

    def test_query_with_english_locale_returns_results(
        self, client: TestClient, session_id: str
    ) -> None:
        """English locale expansion ('en' → 'en','english','unknown') must find indexed docs."""
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "recognize text from image",
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "query_locale": "en",
                    "top_k": 5,
                },
            },
        )
        assert resp.status_code == 200
        results = resp.json()["result"]["results"]
        assert len(results) > 0, "English locale query must return results"


# ---------------------------------------------------------------------------
# get_symbol_doc — exact API symbol lookup
# ---------------------------------------------------------------------------


class TestGetSymbolDoc:
    def test_symbol_lookup_known_class(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/get_symbol_doc",
            json={
                "session_id": session_id,
                "arguments": {
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "symbol_fqn": "Aspose.OCR.AsposeOcr",
                },
            },
        )
        # 200 if found in Qdrant/state store, 404 if not indexed yet.
        assert resp.status_code in {200, 404}
        if resp.status_code == 200:
            result = resp.json()["result"]
            assert result["symbol_fqn"]

    def test_symbol_lookup_unknown_returns_404(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/get_symbol_doc",
            json={
                "session_id": session_id,
                "arguments": {
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "symbol_fqn": "Nonexistent.Class.That.Does.Not.Exist",
                },
            },
        )
        # Unknown symbol must return 404, not 500.
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Transport parity — same query through streamable-http, SSE, JSON-RPC
# ---------------------------------------------------------------------------


class TestTransportParity:
    """Verify that different MCP transports return consistent results."""

    _QUERY_ARGS: dict[str, Any] = {
        "query": "OCR image recognition",
        "product_id": "aspose.ocr",
        "language": "net",
        "top_k": 3,
    }

    def test_streamable_http_transport(self, client: TestClient) -> None:
        init = client.post(
            "/mcp/v1/streamable-http/initialize", json={}
        )
        assert init.status_code == 200
        sid = init.json()["session_id"]

        resp = client.post(
            "/mcp/v1/streamable-http/tools/query_docs",
            json={"session_id": sid, "arguments": self._QUERY_ARGS},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["results"]

    def test_sse_transport(self, client: TestClient) -> None:
        init = client.post("/mcp/v1/sse/initialize", json={})
        assert init.status_code == 200
        init_event, init_data = _parse_sse(init.text)
        assert init_event == "initialize"
        sid = init_data["session_id"]

        resp = client.post(
            "/mcp/v1/sse/tools/query_docs",
            json={"session_id": sid, "arguments": self._QUERY_ARGS},
        )
        assert resp.status_code == 200
        event, data = _parse_sse(resp.text)
        assert event == "tool_result"
        assert data["result"]["results"]

    def test_jsonrpc_transport(self, client: TestClient) -> None:
        init = client.post(
            "/mcp/v1/streamable-http",
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )
        assert init.status_code == 200
        sid = init.headers.get("mcp-session-id")
        assert sid

        resp = client.post(
            "/mcp/v1/streamable-http",
            headers={"mcp-session-id": sid},
            json={
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "query_docs", "arguments": self._QUERY_ARGS},
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["result"]["structuredContent"]["results"]

    def test_jsonrpc_tools_list(self, client: TestClient) -> None:
        init = client.post(
            "/mcp/v1/streamable-http",
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {},
            },
        )
        sid = init.headers.get("mcp-session-id")

        resp = client.post(
            "/mcp/v1/streamable-http",
            headers={"mcp-session-id": sid},
            json={
                "jsonrpc": "2.0",
                "id": "list-1",
                "method": "tools/list",
                "params": {},
            },
        )
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "query_docs" in tool_names
        assert "resolve_product" in tool_names
        assert "get_symbol_doc" in tool_names

    def test_stdio_transport(self, live_app: FastAPI) -> None:
        from adcs.mcp.stdio_server import MCPStdioTransport

        gateway = live_app.state.mcp_tool_gateway
        transport = MCPStdioTransport(gateway=gateway)

        init = transport.handle_message(
            {"id": "1", "method": "initialize", "params": {}}
        )
        sid = init["result"]["session_id"]

        result = transport.handle_message(
            {
                "id": "2",
                "method": "tools/query_docs",
                "params": {"session_id": sid, "arguments": self._QUERY_ARGS},
            }
        )
        assert result["result"]["result"]["results"]


# ---------------------------------------------------------------------------
# REST parity — same query via REST endpoint
# ---------------------------------------------------------------------------


class TestRESTParity:
    def test_rest_query_docs_matches_mcp(
        self, client: TestClient, session_id: str
    ) -> None:
        # MCP query
        mcp_resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "OCR recognition",
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "top_k": 3,
                },
            },
        )
        assert mcp_resp.status_code == 200
        mcp_results = mcp_resp.json()["result"]["results"]

        # REST query (note: REST uses /v1/docs:query, not /v1/query_docs)
        rest_resp = client.post(
            "/v1/docs:query",
            json={
                "query": "OCR recognition",
                "product_id": "aspose.ocr",
                "language": "net",
                "top_k": 3,
            },
        )
        assert rest_resp.status_code == 200
        rest_results = rest_resp.json()["results"]

        # Both should return results from same backends.
        assert len(mcp_results) > 0
        assert len(rest_results) > 0
        # Chunk IDs should match (same query, same backends).
        mcp_ids = {r["chunk_id"] for r in mcp_results}
        rest_ids = {r["chunk_id"] for r in rest_results}
        assert mcp_ids == rest_ids, "MCP/REST parity violated"

    def test_rest_resolve_product(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose.Words for Java"},
        )
        assert resp.status_code == 200
        assert resp.json()["product_id"] == "aspose.words"

    def test_rest_health_endpoints(self, client: TestClient) -> None:
        for path in ("/healthz", "/v1/healthz"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Data quality assertions
# ---------------------------------------------------------------------------


class TestDataQuality:
    """Verify indexed data meets basic quality thresholds."""

    def test_aspose_ocr_has_sufficient_results(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "RecognizeImage method parameters",
                    "product_id": "aspose.ocr",
                    "language": "net",
                    "top_k": 10,
                },
            },
        )
        results = resp.json()["result"]["results"]
        assert len(results) >= 3, (
            f"Expected at least 3 results for core Aspose.OCR query, got {len(results)}"
        )

    def test_results_contain_non_empty_text(
        self, client: TestClient, session_id: str
    ) -> None:
        resp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session_id,
                "arguments": {
                    "query": "PDF to Word conversion",
                    "product_id": "aspose.pdf",
                    "language": "net",
                    "top_k": 3,
                },
            },
        )
        results = resp.json()["result"]["results"]
        for item in results:
            assert item.get("excerpt", "").strip(), f"Empty excerpt in chunk {item.get('chunk_id')}"

    def test_multiple_products_return_results(
        self, client: TestClient, session_id: str
    ) -> None:
        """At least 5 different products should have indexed data."""
        products_with_data = []
        test_products = [
            ("aspose.ocr", "image recognition"),
            ("aspose.words", "document processing"),
            ("aspose.pdf", "PDF manipulation"),
            ("aspose.cells", "spreadsheet workbook"),
            ("aspose.email", "email message"),
            ("aspose.slides", "presentation slide"),
            ("aspose.barcode", "barcode generation"),
            ("aspose.imaging", "image format conversion"),
        ]
        for product_id, query in test_products:
            resp = client.post(
                "/mcp/v1/tools/query_docs",
                json={
                    "session_id": session_id,
                    "arguments": {
                        "query": query,
                        "product_id": product_id,
                        "language": "net",
                        "top_k": 1,
                    },
                },
            )
            if resp.status_code == 200 and resp.json()["result"]["results"]:
                products_with_data.append(product_id)

        assert len(products_with_data) >= 5, (
            f"Only {len(products_with_data)} products have data: {products_with_data}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse(body: str) -> tuple[str, dict[str, Any]]:
    event: str | None = None
    payload: dict[str, Any] | None = None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            payload = json.loads(line.removeprefix("data:").strip())
    if event is None or payload is None:
        raise AssertionError(f"Incomplete SSE response: {body[:200]}")
    return event, payload
