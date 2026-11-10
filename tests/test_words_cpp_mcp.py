"""Words/C++ MCP endpoint: route-selected scope, isolated from Words/.NET."""
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

ENDPOINT = "/words/cpp/mcp/v1/streamable-http"
NET_ENDPOINT = "/words/net/mcp/v1/streamable-http"
TOOLS = {
    "resolve_product": {},
    "query_docs": {"query": "Document"},
    "get_symbol_doc": {"symbol_fqn": "Aspose.Words.Document"},
    "list_breaking_changes": {"from_version": "24.1", "to_version": "25.1"},
    "list_latest_release_features": {},
    "aspose_lookup": {"query": "Document"},
    "get_symbol": {"symbol_fqn": "Document"},
    "list_members": {"parent_fqn": "Document"},
    "search_symbols": {"query": "Document"},
}


def _store():
    store = InMemoryApiRefSymbolStore()
    for language, fqn in (("cpp", "Aspose.Words.Document"),
                          ("net", "Aspose.Words.Document")):
        package = fqn.rsplit(".", 1)[0]
        snapshot = f"words-{language}"
        store.upsert_symbols([
            ApiRefSymbol(
                snapshot_id=snapshot, product="aspose.words", language=language,
                version="25.1", locale="en", kind="class", member_fqn=fqn, name="Document",
                parent_fqn=package, signature=f"public class Document /*{language}*/",
                summary="Represents a Word document.",
                canonical_url=f"https://reference.aspose.com/words/{language}/document/",
                is_deprecated=False, payload={},
            ),
            ApiRefSymbol(
                snapshot_id=snapshot, product="aspose.words", language=language,
                version="25.1", locale="en", kind="method", member_fqn=f"{fqn}.Save",
                name="Save", parent_fqn=fqn, signature=("void Aspose::Words::Document::Save(System::String fileName)" if language == "cpp" else "public void Save(string fileName)"),
                summary="Saves the document.",
                canonical_url=f"https://reference.aspose.com/words/{language}/document/",
                is_deprecated=False, payload={},
            ),
        ])
        store.flip_active_snapshot(
            scope=ApiRefScope(product="aspose.words", language=language, version="25.1"),
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


def test_initialize_and_manifest_are_fixed_to_words_cpp():
    client = _client(store=_store())
    initialized = _rpc(client, "initialize")["result"]
    assert initialized["serverInfo"]["name"] == "aspose-words-cpp-mcp"
    for tool in _rpc(client, "tools/list")["result"]["tools"]:
        schema = tool["inputSchema"]
        assert schema["properties"]["product_id"]["enum"] == ["aspose.words"]
        assert schema["properties"]["language"]["enum"] == ["cpp"]
    content = _call(client, "resolve_product", {"query": "Aspose.Words for .NET"})
    assert content["result"]["structuredContent"]["language"] == "cpp"
    assert "get" in client.app.openapi()["paths"][ENDPOINT]


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("override", [
    {"language": "net"}, {"language": "C#"}, {"language": "java"}, {"product_id": "aspose.cells"},
])
def test_scope_overrides_are_rejected_before_retrieval(tool, override):
    public = Mock()
    result = _call(_client(public, _store()), tool, {**TOOLS[tool], **override})
    assert result["error"]["code"] == -32602
    assert not public.mock_calls


@pytest.mark.parametrize("language", ["cpp", "CPP", "c++", "C++"])
def test_cpp_aliases_are_accepted(language):
    content = _call(_client(store=_store()), "get_symbol", {
        "symbol_fqn": "Aspose.Words.Document", "language": language,
    })["result"]["structuredContent"]
    assert content["found"]


def test_structured_tools_return_only_cpp_and_resolve_partial_names():
    client = _client(store=_store())
    content = _call(client, "get_symbol", {"symbol_fqn": "Document.Save"})
    overloads = content["result"]["structuredContent"]["overloads"]
    assert [o["signature"] for o in overloads] == ["void Aspose::Words::Document::Save(System::String fileName)"]
    members = _call(client, "list_members", {"parent_fqn": "Aspose.Words.Document"})
    assert [m["signature"] for m in members["result"]["structuredContent"]["members"]] == [
        "void Aspose::Words::Document::Save(System::String fileName)"
    ]
    net = _call(client, "get_symbol", {"symbol_fqn": "Aspose.Words.Document"},
                path=NET_ENDPOINT)["result"]["structuredContent"]
    assert net["overloads"][0]["signature"] == "public class Document /*net*/"


def test_public_tools_receive_cpp_scope_without_language_fallback():
    public = Mock()
    public.query_docs.return_value.results = []
    public.query_docs.return_value.warnings = []
    public.query_docs.return_value.model_dump.return_value = {}
    assert "error" not in _call(_client(public), "query_docs", {"query": "mail merge"})
    kwargs = public.query_docs.call_args.kwargs
    assert (kwargs["request"].product_id, kwargs["request"].language) == ("aspose.words", "cpp")
    assert kwargs["allow_language_fallback"] is False
