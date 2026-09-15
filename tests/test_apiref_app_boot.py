"""Boot the real FastAPI app with APIREF_STRUCTURED_STORE_ENABLED and serve.

Proves the production wiring end to end: create_app() constructs a
Postgres-backed ApiRefSymbolService, the MCP gateway advertises + dispatches
the structured tools, and the REST endpoints answer — all against live
Postgres. Opt-in (requires ADCS_TEST_POSTGRES_DSN). Also covers the
flag-off default (tools absent, endpoint 503) without a database.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from adcs.config import clear_settings_cache
from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol, PostgresApiRefSymbolStore

_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")
SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")


def _seed(dsn: str) -> None:
    store = PostgresApiRefSymbolStore(postgres_dsn=dsn)
    store.upsert_symbols(
        [
            ApiRefSymbol(
                snapshot_id="boot-1",
                product=SCOPE.product,
                language=SCOPE.language,
                version=SCOPE.version,
                locale=SCOPE.locale,
                kind="method",
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(string fileName)",
                summary="Saves the presentation to a file.",
                canonical_url="https://ref.aspose.com/Save",
                is_deprecated=False,
                payload={},
            )
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="boot-1")


def _body() -> dict[str, str]:
    return {"product_id": "aspose.slides", "language": "net", "version": "24.1"}


def test_app_boot_flag_off_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default (flag off): no database needed; structured surface is absent.
    monkeypatch.delenv("APIREF_STRUCTURED_STORE_ENABLED", raising=False)
    clear_settings_cache()
    from adcs.api.main import create_app

    app = create_app()
    assert app.state.apiref_symbol_service is None
    assert "get_symbol" not in app.state.mcp_tool_gateway.supported_tools()
    with TestClient(app) as client:
        response = client.post("/v1/symbols/structured:get", json={**_body(), "symbol_fqn": "x.y"})
        assert response.status_code == 503


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_app_boot_flag_on_serves_structured_apiref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _PG_DSN is not None
    _seed(_PG_DSN)
    monkeypatch.setenv("APIREF_STRUCTURED_STORE_ENABLED", "true")
    monkeypatch.setenv("POSTGRES_DSN", _PG_DSN)
    clear_settings_cache()
    from adcs.api.main import create_app

    app = create_app()
    # Service constructed; MCP advertises the structured tools.
    assert app.state.apiref_symbol_service is not None
    tools = app.state.mcp_tool_gateway.supported_tools()
    assert {"get_symbol", "list_members", "search_symbols"} <= set(tools)

    # REST endpoint answers from Postgres.
    with TestClient(app) as client:
        got = client.post(
            "/v1/symbols/structured:get",
            json={**_body(), "symbol_fqn": "aspose.slides.Presentation.Save"},
        )
        assert got.status_code == 200, got.text
        assert got.json()["found"] is True
        assert got.json()["overloads"][0]["signature"] == "void Save(string fileName)"

        members = client.post(
            "/v1/symbols/structured:members",
            json={**_body(), "parent_fqn": "aspose.slides.Presentation"},
        )
        assert members.status_code == 200
        assert [m["name"] for m in members.json()["members"]] == ["Save"]

    # MCP gateway dispatch through the real app.
    gateway = app.state.mcp_tool_gateway
    session = gateway.initialize(requested_revision=None)
    result = gateway.call_tool(
        session_id=session.session_id,
        tool_name="get_symbol",
        arguments={**_body(), "symbol_fqn": "aspose.slides.Presentation.Save"},
    )
    assert result["found"] is True
