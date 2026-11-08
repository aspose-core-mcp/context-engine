from __future__ import annotations

import os
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.apiref_symbol_query import ApiRefSymbolService
from adcs.api.apiref_symbols import router as apiref_symbols_router
from adcs.api.mcp_gateway import _streamable_tools_manifest
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.mcp import MCPToolError
from adcs.mcp.tool_gateway import MCPToolGateway

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")
_REVISIONS = ("2025-11-25", "2025-06-18", "2024-11-05")


def _seed_store() -> InMemoryApiRefSymbolStore:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(
        [
            ApiRefSymbol(
                snapshot_id="snap-1",
                product=SCOPE.product,
                language=SCOPE.language,
                version=SCOPE.version,
                locale=SCOPE.locale,
                kind="class",
                member_fqn="aspose.slides.Presentation",
                name="Presentation",
                parent_fqn="aspose.slides",
                summary="Represents a presentation.",
                canonical_url="https://ref/Presentation",
                is_deprecated=False,
                payload={},
            ),
            ApiRefSymbol(
                snapshot_id="snap-1",
                product=SCOPE.product,
                language=SCOPE.language,
                version=SCOPE.version,
                locale=SCOPE.locale,
                kind="method",
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(string fileName)",
                summary="Saves to a file.",
                canonical_url="https://ref/Save",
                is_deprecated=False,
                payload={"parameters": "fileName: path"},
            ),
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    return store


def _gateway(service: ApiRefSymbolService | None) -> MCPToolGateway:
    # The apiref dispatch path never touches public_query_service, so a stub
    # is sufficient for these tests.
    return MCPToolGateway(
        public_query_service=cast(Any, object()),
        supported_revisions=_REVISIONS,
        primary_revision=_REVISIONS[0],
        apiref_symbol_service=service,
    )


def _base() -> dict[str, str]:
    return {"product_id": "aspose.slides", "language": "net", "version": "24.1"}


# --- MCP gateway ------------------------------------------------------------


def test_mcp_advertises_structured_tools_only_when_configured() -> None:
    with_service = _gateway(ApiRefSymbolService(store=_seed_store()))
    assert {"aspose_lookup", "get_symbol", "list_members", "search_symbols"} <= set(
        with_service.supported_tools()
    )
    without = _gateway(None)
    assert "get_symbol" not in without.supported_tools()
    assert "aspose_lookup" not in without.supported_tools()


def test_mcp_dispatches_aspose_lookup() -> None:
    gateway = _gateway(ApiRefSymbolService(store=_seed_store()))
    session = gateway.initialize(requested_revision="2025-06-18")

    # Weak-model call: bare product + 'csharp' → still grounds in one call.
    search = gateway.call_tool(
        session_id=session.session_id,
        tool_name="aspose_lookup",
        arguments={
            "query": "Save",
            "product_id": "slides",
            "language": "csharp",
            "version": "24.1",
        },
    )
    assert search["mode"] == "search"
    assert search["resolved_product_id"] == "aspose.slides"
    assert search["resolved_language"] == "net"
    assert any(r["signature"] for r in search["results"])

    # Exact FQN → full symbol, no follow-up get_symbol needed.
    exact = gateway.call_tool(
        session_id=session.session_id,
        tool_name="aspose_lookup",
        arguments={"query": "aspose.slides.Presentation.Save", "version": "24.1"},
    )
    assert exact["mode"] == "symbol"
    assert exact["symbol"]["found"] is True


def test_mcp_dispatches_structured_tools() -> None:
    gateway = _gateway(ApiRefSymbolService(store=_seed_store()))
    session = gateway.initialize(requested_revision="2025-06-18")

    got = gateway.call_tool(
        session_id=session.session_id,
        tool_name="get_symbol",
        arguments={**_base(), "symbol_fqn": "aspose.slides.Presentation.Save"},
    )
    assert got["found"] is True
    assert got["overloads"][0]["parameters"] == "fileName: path"

    members = gateway.call_tool(
        session_id=session.session_id,
        tool_name="list_members",
        arguments={**_base(), "parent_fqn": "aspose.slides.Presentation"},
    )
    assert [m["name"] for m in members["members"]] == ["Save"]

    search = gateway.call_tool(
        session_id=session.session_id,
        tool_name="search_symbols",
        arguments={**_base(), "query": "Pres"},
    )
    assert any(r["name"] == "Presentation" for r in search["results"])


def test_b4_language_enum_injected_into_structured_tools() -> None:
    tools = _streamable_tools_manifest(language_enum=["net", "java", "cpp"])
    manifest = {t["name"]: t for t in tools}
    for name in ("aspose_lookup", "get_symbol", "list_members", "search_symbols"):
        language = manifest[name]["inputSchema"]["properties"]["language"]
        assert language["enum"] == ["net", "java", "cpp"]
        assert "net" in language["description"]


def test_b4_language_enum_absent_when_not_supplied() -> None:
    manifest = {t["name"]: t for t in _streamable_tools_manifest()}
    # structured tools: plain string, no enum (B1 still normalises server-side)
    assert "enum" not in manifest["search_symbols"]["inputSchema"]["properties"]["language"]
    # docs tools stay out of B4 scope
    assert "enum" not in manifest["query_docs"]["inputSchema"]["properties"]["language"]


def test_mcp_structured_tool_unconfigured_raises() -> None:
    gateway = _gateway(None)
    session = gateway.initialize(requested_revision="2025-06-18")
    with pytest.raises(MCPToolError):
        gateway.call_tool(
            session_id=session.session_id,
            tool_name="get_symbol",
            arguments={**_base(), "symbol_fqn": "x.y"},
        )


# --- REST parity ------------------------------------------------------------


def _client(service: ApiRefSymbolService | None) -> TestClient:
    app = FastAPI()
    app.state.apiref_symbol_service = service
    app.include_router(apiref_symbols_router)
    return TestClient(app)


def test_rest_get_symbol_and_members_and_search() -> None:
    client = _client(ApiRefSymbolService(store=_seed_store()))

    got = client.post(
        "/v1/symbols/structured:get",
        json={**_base(), "symbol_fqn": "aspose.slides.Presentation.Save"},
    )
    assert got.status_code == 200
    assert got.json()["found"] is True

    members = client.post(
        "/v1/symbols/structured:members",
        json={**_base(), "parent_fqn": "aspose.slides.Presentation"},
    )
    assert members.status_code == 200
    assert [m["name"] for m in members.json()["members"]] == ["Save"]

    search = client.post("/v1/symbols/structured:search", json={**_base(), "query": "Pres"})
    assert search.status_code == 200
    assert search.json()["results"]


def test_rest_lookup_one_shot() -> None:
    client = _client(ApiRefSymbolService(store=_seed_store()))
    response = client.post(
        "/v1/symbols/structured:lookup",
        json={"query": "Save", "product_id": "slides", "language": "csharp", "version": "24.1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "search"
    assert body["resolved_product_id"] == "aspose.slides"
    assert any(r["signature"] for r in body["results"])


def test_rest_get_symbol_404() -> None:
    client = _client(ApiRefSymbolService(store=_seed_store()))
    response = client.post(
        "/v1/symbols/structured:get", json={**_base(), "symbol_fqn": "aspose.slides.Nope"}
    )
    assert response.status_code == 404


def test_rest_503_when_unconfigured() -> None:
    client = _client(None)
    response = client.post("/v1/symbols/structured:get", json={**_base(), "symbol_fqn": "x.y"})
    assert response.status_code == 503


# --- opt-in real Postgres E2E ----------------------------------------------


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_rest_against_real_postgres() -> None:
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    iso = ApiRefScope(product="rest.pg", language="net", version="rt", locale="en")
    store.upsert_symbols(
        [
            ApiRefSymbol(
                snapshot_id="rest-rt",
                product=iso.product,
                language=iso.language,
                version=iso.version,
                locale=iso.locale,
                kind="method",
                member_fqn="rest.pg.Doc.Save",
                name="Save",
                parent_fqn="rest.pg.Doc",
                signature="void Save()",
                summary="Saves the doc.",
                canonical_url="https://ref/save",
                is_deprecated=False,
                payload={},
            )
        ]
    )
    store.flip_active_snapshot(scope=iso, snapshot_id="rest-rt")
    client = _client(ApiRefSymbolService(store=store))
    response = client.post(
        "/v1/symbols/structured:get",
        json={
            "product_id": "rest.pg",
            "language": "net",
            "version": "rt",
            "symbol_fqn": "rest.pg.Doc.Save",
        },
    )
    assert response.status_code == 200
    assert response.json()["found"] is True
