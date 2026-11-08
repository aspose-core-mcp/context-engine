"""Regression evidence for Support Redmine #135683."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.apiref_symbol_query import ApiRefSymbolService, GetSymbolRequest
from adcs.api.mcp_gateway import router
from adcs.api.public_docs_query import GetSymbolDocRequest
from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol, InMemoryApiRefSymbolStore
from adcs.indexing.symbol_resolution import SymbolNotFoundError, find_symbol_candidates
from adcs.mcp.stdio_server import MCPStdioTransport
from adcs.mcp.tool_gateway import MCPToolGateway
from test_public_query_structured_symbol_doc import _service

SCOPE = ApiRefScope(product="aspose.words", language="net", version="latest-stable")
CANONICAL = "Aspose.Words.Comparing.CompareOptions"
REQUESTED = "Aspose.Words.CompareOptions"


def symbol(fqn=CANONICAL, **changes):
    row = ApiRefSymbol(
        snapshot_id="recovery",
        product=SCOPE.product,
        language=SCOPE.language,
        version=SCOPE.version,
        locale="en",
        member_fqn=fqn,
        name=fqn.rsplit(".", 1)[-1],
        kind="class",
        parent_fqn=fqn.rsplit(".", 1)[0],
        signature="public class CompareOptions",
    )
    return replace(row, **changes)


def store_for(*rows):
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(rows or [symbol()])
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="recovery")
    return store


def request(fqn=REQUESTED):
    return GetSymbolRequest(
        product_id=SCOPE.product, language=SCOPE.language, version=SCOPE.version, symbol_fqn=fqn
    )


def test_unique_type_recovery_ignores_constructor_and_overloads():
    store = store_for(
        symbol(),
        symbol(CANONICAL + ".CompareOptions", kind="constructor"),
        symbol(signature="public class CompareOptions : object"),
    )
    response = ApiRefSymbolService(store=store).get_symbol(request=request())
    assert response.found and response.member_fqn == CANONICAL
    assert "Resolved" in response.hint.message


def test_ambiguous_type_returns_candidates_without_selecting_first():
    store = store_for(symbol(), symbol("Aspose.Words.Other.CompareOptions"))
    response = ApiRefSymbolService(store=store).get_symbol(request=request())
    assert not response.found
    assert len(response.suggested_symbols) == 2
    assert all(s["match_reason"] == "short_name_match" for s in response.suggested_symbols)


def test_scope_and_excluded_namespace_boundaries(monkeypatch):
    from adcs.retrieval.profiles import RetrievalProfile

    profile = RetrievalProfile(
        schema_version=1, profile_id="test-policy", version="1",
        product_id=SCOPE.product, language=SCOPE.language,
        excluded_namespaces=["Aspose.Words.LowCode"], rules=[],
    )
    monkeypatch.setattr("adcs.retrieval.profiles.profile_for", lambda *args: profile)
    rows = [
        symbol("Aspose.Words.LowCode.CompareOptions"),
        symbol(language="java"),
        symbol(version="old"),
        symbol(locale="fr"),
        symbol(product="aspose.cells"),
    ]
    # Deliberately untrusted/custom store ignores scope filtering.
    store = SimpleNamespace(search_symbols=lambda **kwargs: rows)
    result = find_symbol_candidates(store=store, scope=SCOPE, requested=REQUESTED)
    assert result.symbols == ()


def test_truncated_search_never_claims_unique_match():
    rows = [symbol()] + [symbol(f"Aspose.Words.CompareOptions{i}") for i in range(100)]
    store = SimpleNamespace(search_symbols=lambda **kwargs: rows)
    result = find_symbol_candidates(store=store, scope=SCOPE, requested=REQUESTED)
    assert result.unique_fqn is None and result.truncated


def test_doc_lookup_remains_strict_and_supplies_canonical_retry():
    service = _service(store_for())
    args = dict(product_id=SCOPE.product, language=SCOPE.language, version=SCOPE.version)
    result = service.get_symbol_doc(request=GetSymbolDocRequest(**args, symbol_fqn=CANONICAL))
    assert result.symbol_fqn == CANONICAL
    with pytest.raises(SymbolNotFoundError) as caught:
        service.get_symbol_doc(request=GetSymbolDocRequest(**args, symbol_fqn=REQUESTED))
    assert caught.value.details["requested_symbol"] == REQUESTED
    assert caught.value.details["suggested_symbols"][0]["symbol_fqn"] == CANONICAL
    assert CANONICAL in str(caught.value)
    with pytest.raises(SymbolNotFoundError) as caught:
        service.get_symbol_doc(
            request=GetSymbolDocRequest(**args, symbol_fqn="Aspose.Words.Missing")
        )
    assert caught.value.details["suggested_symbols"] == []


def gateway():
    store = store_for()
    return MCPToolGateway(
        public_query_service=_service(store),
        supported_revisions=("2024-11-05",),
        primary_revision="2024-11-05",
        apiref_symbol_service=ApiRefSymbolService(store=store),
    )


def test_stdio_preserves_canonical_suggestions():
    transport = MCPStdioTransport(gateway=gateway())
    response = transport.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_symbol_doc", "arguments": request().model_dump()},
        }
    )
    assert response["error"]["data"]["adcs_code"] == "NOT_FOUND"
    assert response["error"]["data"]["details"]["suggested_symbols"][0]["symbol_fqn"] == CANONICAL


def test_streamable_http_preserves_canonical_suggestions():
    app = FastAPI()
    app.state.mcp_tool_gateway = gateway()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/mcp/v1/streamable-http",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_symbol_doc", "arguments": request().model_dump()},
            },
        )
    payload = response.json()
    assert payload["error"]["data"]["adcs_code"] == "NOT_FOUND"
    assert payload["error"]["data"]["details"]["suggested_symbols"][0]["symbol_fqn"] == CANONICAL
