"""TeX/Java MCP endpoint: route-selected scope, isolated from TeX/.NET and Words/Java."""
from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.apiref_symbol_query import ApiRefSymbolService
from adcs.api.mcp_gateway import router
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
)
from adcs.mcp.tool_gateway import MCPToolGateway

ENDPOINT = "/tex/java/mcp/v1/streamable-http"
NET_ENDPOINT = "/tex/net/mcp/v1/streamable-http"
WORDS_JAVA_ENDPOINT = "/words/java/mcp/v1/streamable-http"
TOOLS = {
    "resolve_product": {},
    "query_docs": {"query": "TeXJob"},
    "get_symbol_doc": {"symbol_fqn": "com.aspose.tex.TeXJob"},
    "list_breaking_changes": {"from_version": "24.1", "to_version": "25.1"},
    "list_latest_release_features": {},
    "aspose_lookup": {"query": "TeXJob"},
    "get_symbol": {"symbol_fqn": "TeXJob"},
    "list_members": {"parent_fqn": "TeXJob"},
    "search_symbols": {"query": "TeXJob"},
}


def _store():
    store = InMemoryApiRefSymbolStore()
    for language, fqn in (("java", "com.aspose.tex.TeXJob"),
                          ("net", "Aspose.TeX.TeXJob")):
        package = fqn.rsplit(".", 1)[0]
        snapshot = f"tex-{language}"
        store.upsert_symbols([
            ApiRefSymbol(
                snapshot_id=snapshot, product="aspose.tex", language=language,
                version="24.9", locale="en", kind="class", member_fqn=fqn, name="TeXJob",
                parent_fqn=package, signature=f"public class TeXJob /*{language}*/",
                summary="Implements features of a TeX job.",
                canonical_url=f"https://reference.aspose.com/tex/{language}/texjob/",
                is_deprecated=False, payload={},
            ),
            ApiRefSymbol(
                snapshot_id=snapshot, product="aspose.tex", language=language,
                version="24.9", locale="en", kind="method", member_fqn=f"{fqn}.run",
                name="run", parent_fqn=fqn, signature=f"run /*{language}*/",
                summary="Runs TeX job.",
                canonical_url=f"https://reference.aspose.com/tex/{language}/texjob/",
                is_deprecated=False, payload={},
            ),
        ])
        store.flip_active_snapshot(
            scope=ApiRefScope(product="aspose.tex", language=language, version="24.9"),
            snapshot_id=snapshot,
        )
    return store


def _client(public=None, store=None):
    app = FastAPI()
    app.include_router(router)
    service = ApiRefSymbolService(store=store) if store is not None else None
    app.state.apiref_symbol_service = service
    app.state.mcp_tool_gateway = MCPToolGateway(
        public_query_service=public if public is not None else Mock(),
        apiref_symbol_service=service,
        supported_revisions=("2025-11-25",), primary_revision="2025-11-25",
    )
    return TestClient(app)


def _rpc(client, method, params=None, path=ENDPOINT):
    response = client.post(path, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
    })
    assert response.status_code == 200
    return response.json()


def _call(client, name, arguments, path=ENDPOINT):
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments}, path=path)


def test_initialize_and_manifest_are_fixed_to_tex_java():
    client = _client(store=_store())
    initialized = _rpc(client, "initialize")["result"]
    assert initialized["serverInfo"]["name"] == "aspose-tex-java-mcp"
    for tool in _rpc(client, "tools/list")["result"]["tools"]:
        schema = tool["inputSchema"]
        assert schema["properties"]["product_id"]["enum"] == ["aspose.tex"]
        assert schema["properties"]["language"]["enum"] == ["java"]
    content = _call(client, "resolve_product", {"query": "Aspose.TeX for .NET"})
    assert content["result"]["structuredContent"]["language"] == "java"
    assert "get" in client.app.openapi()["paths"][ENDPOINT]


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("override", [
    {"language": "net"}, {"language": "C#"}, {"product_id": "aspose.words"},
])
def test_scope_overrides_are_rejected_before_retrieval(tool, override):
    public = Mock()
    result = _call(_client(public, _store()), tool, {**TOOLS[tool], **override})
    assert result["error"]["code"] == -32602
    assert not public.mock_calls


@pytest.mark.parametrize("language", ["java", "Java", "JVM"])
def test_java_aliases_are_accepted(language):
    content = _call(_client(store=_store()), "get_symbol", {
        "symbol_fqn": "com.aspose.tex.TeXJob", "language": language,
    })["result"]["structuredContent"]
    assert content["found"]


def test_structured_tools_return_only_java_and_resolve_partial_names():
    client = _client(store=_store())
    content = _call(client, "get_symbol", {"symbol_fqn": "TeXJob.run"})
    overloads = content["result"]["structuredContent"]["overloads"]
    assert [o["signature"] for o in overloads] == ["run /*java*/"]
    members = _call(client, "list_members", {"parent_fqn": "com.aspose.tex.TeXJob"})
    assert [m["signature"] for m in members["result"]["structuredContent"]["members"]] == [
        "run /*java*/"
    ]
    net = _call(client, "get_symbol", {"symbol_fqn": "Aspose.TeX.TeXJob"},
                path=NET_ENDPOINT)["result"]["structuredContent"]
    assert net["overloads"][0]["signature"] == "public class TeXJob /*net*/"


def test_public_tools_receive_java_scope_without_language_fallback():
    public = Mock()
    public.query_docs.return_value.results = []
    public.query_docs.return_value.warnings = []
    public.query_docs.return_value.model_dump.return_value = {}
    assert "error" not in _call(_client(public), "query_docs", {"query": "latex to pdf"})
    kwargs = public.query_docs.call_args.kwargs
    assert (kwargs["request"].product_id, kwargs["request"].language) == ("aspose.tex", "java")
    assert kwargs["allow_language_fallback"] is False


def test_words_java_endpoint_cannot_reach_tex_java_content():
    content = _call(_client(store=_store()), "get_symbol", {"symbol_fqn": "com.aspose.tex.TeXJob"},
                    path=WORDS_JAVA_ENDPOINT)["result"]["structuredContent"]
    assert not content["found"]
