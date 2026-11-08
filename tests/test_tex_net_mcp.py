"""Product-scoped HTTP MCP isolation, including empty scopes and shared caches."""
from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from adcs.api.apiref_symbol_query import ApiRefSymbolService
from adcs.api.mcp_gateway import mcp_streamable_http_sse, router
from adcs.api.public_docs_query import PublicQueryService
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.mcp.tool_gateway import MCPToolGateway
from adcs.retrieval.response_cache import ResponseCache
from adcs.retrieval.translation_fallback import TranslationFallbackService

ENDPOINT = "/tex/net/mcp/v1/streamable-http"
SHARED = "/mcp/v1/streamable-http"
TOOLS = {
    "resolve_product": {},
    "query_docs": {"query": "Document"},
    "get_symbol_doc": {"symbol_fqn": "Aspose.TeX.Document"},
    "list_breaking_changes": {"from_version": "24.1", "to_version": "25.1"},
    "list_latest_release_features": {},
    "aspose_lookup": {"query": "Document"},
    "get_symbol": {"symbol_fqn": "Aspose.TeX.Document"},
    "list_members": {"parent_fqn": "Aspose.TeX.Document"},
    "search_symbols": {"query": "Document"},
}


def _store(scopes):
    store = InMemoryApiRefSymbolStore()
    for product, language in scopes:
        snapshot = f"{product}-{language}"
        store.upsert_symbols([
            ApiRefSymbol(
                snapshot_id=snapshot, product=product, language=language,
                version="25.1", locale="en", kind="class",
                member_fqn=f"{product}.Document", name="Document", parent_fqn=product,
                signature=f"class Document_{language}", summary="Document API",
                canonical_url=f"https://reference.aspose.com/{product}/{language}/document",
                is_deprecated=False, payload={},
            ),
        ])
        store.flip_active_snapshot(
            scope=ApiRefScope(product=product, language=language, version="25.1"),
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


def _rpc(client, method, params=None, path=ENDPOINT, headers=None):
    response = client.post(path, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
    }, headers=headers)
    assert response.status_code == 200
    return response.json()


def _call(client, name, arguments, **kwargs):
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments}, **kwargs)


def test_initialize_manifest_and_fixed_resolution():
    client = _client(store=_store([("aspose.tex", "java"), ("aspose.cells", "net")]))
    initialized = _rpc(client, "initialize")["result"]
    assert initialized["serverInfo"]["name"] == "aspose-tex-net-mcp"
    tools = _rpc(client, "tools/list")["result"]["tools"]
    assert {tool["name"] for tool in tools} == set(TOOLS)
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["properties"]["product_id"]["enum"] == ["aspose.tex"]
        assert schema["properties"]["language"]["enum"] == ["net"]
        assert not {"product_id", "language"} & set(schema["required"])
    result = _call(client, "resolve_product", {"query": "Aspose.Cells for Java"})
    assert result["result"]["structuredContent"]["product_id"] == "aspose.tex"
    assert result["result"]["structuredContent"]["language"] == "net"
    assert "error" not in _call(client, "resolve_product", {})
    assert _rpc(client, "ping")["result"] == {}
    assert client.post(ENDPOINT, json={
        "jsonrpc": "2.0", "method": "notifications/initialized",
    }).status_code == 202
    shared = _rpc(client, "tools/list", path=SHARED)["result"]["tools"]
    assert "product_id" in shared[1]["inputSchema"]["required"]
    assert _rpc(client, "initialize", path=SHARED)["result"]["serverInfo"]["name"] == "adcs-mcp"


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("override", [
    {"product_id": "aspose.cells"}, {"language": "java"},
    {"language": "python-net"}, {"product_id": ["aspose.tex"]},
])
def test_all_tools_reject_scope_override(tool, override):
    public = Mock()
    client = _client(public, _store([("aspose.tex", "net")]))
    result = _call(client, tool, {**TOOLS[tool], **override})
    assert result["error"]["code"] == -32602
    assert not public.mock_calls


@pytest.mark.parametrize("tool", [
    "query_docs", "get_symbol_doc", "list_breaking_changes", "list_latest_release_features",
])
def test_public_tools_receive_fixed_scope(tool):
    public = Mock()
    getattr(public, tool).return_value.model_dump.return_value = {}
    if tool == "query_docs":
        public.query_docs.return_value.results = []
        public.query_docs.return_value.warnings = []
    client = _client(public)
    result = _call(client, tool, TOOLS[tool])
    assert "error" not in result
    kwargs = getattr(public, tool).call_args.kwargs
    assert kwargs["request"].product_id == "aspose.tex"
    assert kwargs["request"].language == "net"
    if tool == "query_docs":
        assert kwargs["allow_language_fallback"] is False


def test_missing_structured_scope_does_not_fall_back_or_follow_query():
    client = _client(store=_store([("aspose.tex", "java"), ("aspose.cells", "net")]))
    for tool in ("aspose_lookup", "get_symbol", "list_members", "search_symbols"):
        args = {**TOOLS[tool], "query": "Aspose.Cells Document for Java"}
        content = _call(client, tool, args)["result"]["structuredContent"]
        assert not content.get("results")
        assert not content.get("members")
        assert not content.get("found")
        assert content["hint"]["resolved_product_id"] == "aspose.tex"
        assert content["hint"]["resolved_language"] == "net"
        assert content["hint"]["retry_with"] is None
    # The unscoped endpoint still performs its existing language fallback.
    content = _call(client, "get_symbol", {
        "product_id": "aspose.tex", "language": "net",
        "symbol_fqn": "aspose.tex.Document",
    }, path=SHARED)["result"]["structuredContent"]
    assert content["found"]
    assert content["hint"]["resolved_language"] == "java"


def test_unknown_product_is_not_derived_from_lookup_query():
    client = _client(store=_store([("aspose.cells", "net")]))
    content = _call(client, "aspose_lookup", {
        "query": "Aspose.Cells Document",
    })["result"]["structuredContent"]
    assert content["resolved_product_id"] == "aspose.tex"
    assert content["results"] == []
    assert content["symbol"] is None


def test_aliases_and_shared_session_cannot_change_scope():
    client = _client(store=_store([("aspose.tex", "net"), ("aspose.tex", "java")]))
    session = _rpc(client, "initialize", path=SHARED)["result"]["session_id"]
    args = {"symbol_fqn": "aspose.tex.Document", "product_id": "TeX", "language": "C#"}
    content = _call(client, "get_symbol", args, headers={
        "mcp-session-id": session,
    })["result"]["structuredContent"]
    assert content["found"]
    assert content["overloads"][0]["signature"] == "class Document_net"
    # The shorthand method and params session token must enforce the same scope.
    result = _rpc(client, "tools/get_symbol", {
        "session_id": session, "arguments": {**args, "language": "java"},
    })
    assert result["error"]["code"] == -32602


def test_manifest_omits_unconfigured_structured_tools():
    tools = _rpc(_client(), "tools/list")["result"]["tools"]
    assert len(tools) == 5


def _record(language):
    text = "Document save PDF with Aspose.TeX Document API."
    return StageDChunkRecord(
        chunk_id=f"doc-{language}", repo_id="tex-docs", product_id="aspose.tex",
        product_family="Aspose.TeX", programming_language=language, version="25.1",
        source_kind="docs", doc_locale="en", doc_type="guide", symbol_fqn=None,
        title="Document", section_path=("Document",),
        canonical_url=f"https://docs.aspose.com/tex/{language}/document/",
        section_anchor="", source_path="document.md", source_revision="abc",
        is_deprecated=False, has_code_example=False, chunk_type="text", text=text,
        tokens=len(text.split()), checksum=language,
    )


@pytest.mark.parametrize("first_path", [SHARED, ENDPOINT])
def test_docs_language_fallback_and_cache_are_isolated(monkeypatch, first_path):
    orchestrator = SourceHugoNormalizationOrchestrationService()
    records = (_record("java"),)

    def records_for_scope(*, product_id=None, programming_language=None, version=None):
        return tuple(r for r in records if
            (product_id is None or r.product_id == product_id)
            and (programming_language is None or r.programming_language == programming_language)
            and (version is None or r.version == version))

    monkeypatch.setattr(orchestrator, "get_latest_chunk_records", records_for_scope)
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=orchestrator,
        translation_fallback_service=TranslationFallbackService(),
        response_cache=ResponseCache(),
    )
    client = _client(service)
    args = {"query": "Document", "product_id": "aspose.tex", "language": "net"}
    # Repeat both orders to catch cache leakage in either direction.
    for path in [first_path, ENDPOINT if first_path == SHARED else SHARED, first_path]:
        content = _call(client, "query_docs", args, path=path)["result"]["structuredContent"]
        if path == ENDPOINT:
            assert content["results"] == []
            assert "cross_language_fallback" not in content["warnings"]
        else:
            assert content["results"]
            assert "cross_language_fallback" in content["warnings"]


def test_scoped_get_has_sse_handler():
    app = _client().app
    assert "get" in app.openapi()["paths"][ENDPOINT]

    async def first_event():
        response = await mcp_streamable_http_sse(Request({
            "type": "http", "method": "GET", "path": ENDPOINT, "headers": [],
        }))
        assert response.media_type == "text/event-stream"
        assert await anext(response.body_iterator) == b": ok\n\n"
        await response.body_iterator.aclose()

    asyncio.run(first_event())


@pytest.mark.parametrize("tool", ["aspose_lookup", "get_symbol", "list_members", "search_symbols"])
def test_structured_tools_return_only_tex_net(tool):
    client = _client(store=_store([
        ("aspose.tex", "net"), ("aspose.tex", "java"), ("aspose.cells", "net"),
    ]))
    args = {**TOOLS[tool]}
    if tool == "list_members":
        args["parent_fqn"] = "aspose.tex"
    result = _call(client, tool, args)["result"]["structuredContent"]
    if tool == "get_symbol":
        symbols = result["overloads"]
    elif tool == "list_members":
        symbols = result["members"]
    else:
        symbols = result["results"]
    assert symbols
    for symbol in symbols:
        assert symbol["signature"] == "class Document_net"
        assert "/aspose.tex/net/" in symbol["canonical_url"]


def test_docs_positive_results_stay_in_scope(monkeypatch):
    orchestrator = SourceHugoNormalizationOrchestrationService()
    records = (_record("net"), _record("java"))

    def records_for_scope(*, product_id=None, programming_language=None, version=None):
        return tuple(r for r in records if
            (product_id is None or r.product_id == product_id)
            and (programming_language is None or r.programming_language == programming_language)
            and (version is None or r.version == version))

    monkeypatch.setattr(orchestrator, "get_latest_chunk_records", records_for_scope)
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=orchestrator,
        translation_fallback_service=TranslationFallbackService(),
    )
    content = _call(_client(service), "query_docs", {
        "query": "Document", "allow_language_fallback": True,
    })["result"]["structuredContent"]
    assert content["results"]
    assert {item["chunk_id"] for item in content["results"]} == {"doc-net"}
