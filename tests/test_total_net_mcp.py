"""Total dispatch must preserve the two independent strict product scopes."""
from unittest.mock import Mock

import pytest

from test_words_net_mcp import TOOLS, _call, _client, _rpc, _store

TOTAL = "/total/net/mcp/v1/streamable-http"


def test_total_identity_manifest_and_resolution():
    client = _client(store=_store([("aspose.words", "net"), ("aspose.tex", "net")]))
    assert _rpc(client, "initialize", path=TOTAL)["result"]["serverInfo"]["name"] == (
        "aspose-total-net-mcp"
    )
    assert "get" in client.app.openapi()["paths"][TOTAL]
    for tool in _rpc(client, "tools/list", path=TOTAL)["result"]["tools"]:
        schema = tool["inputSchema"]
        assert schema["properties"]["product_id"]["enum"] == ["aspose.words", "aspose.tex"]
        assert "default" not in schema["properties"]["product_id"]
        assert schema["properties"]["language"]["enum"] == ["net"]
        assert "product_id" not in schema["required"]
    result = _call(client, "resolve_product", {"query": "Aspose.Cells Java"}, path=TOTAL)
    assert result["result"]["structuredContent"]["products"] == ["aspose.words", "aspose.tex"]


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("override", [
    {"product_id": "aspose.cells"}, {"product_id": "aspose.total"},
    {"language": "java"}, {"language": "python-net"}, {"product_id": []},
])
def test_total_rejects_overrides_for_every_tool(tool, override):
    client = _client(store=_store([]))
    assert _call(client, tool, {**TOOLS[tool], **override}, path=TOTAL)["error"]["code"] == -32602


@pytest.mark.parametrize("tool", ["query_docs", "get_symbol_doc",
                                  "list_breaking_changes", "list_latest_release_features"])
def test_total_public_dispatch_is_strict_and_explicit_selection_narrows(tool):
    public = Mock()
    method = getattr(public, tool)
    method.return_value.model_dump.return_value = {}
    method.return_value.results = []
    method.return_value.warnings = []
    client = _client(public)
    result = _call(client, tool, TOOLS[tool], path=TOTAL)["result"]["structuredContent"]
    assert [x["product_id"] for x in result["results_by_product"]] == ["aspose.words", "aspose.tex"]
    assert [x.kwargs["request"].product_id for x in method.call_args_list] == [
        "aspose.words", "aspose.tex",
    ]
    assert all(x.kwargs["request"].language == "net" for x in method.call_args_list)
    if tool == "query_docs":
        assert all(x.kwargs["allow_language_fallback"] is False for x in method.call_args_list)
    method.reset_mock()
    _call(client, tool, {**TOOLS[tool], "product_id": "TeX", "language": "C#"}, path=TOTAL)
    assert method.call_count == 1
    assert method.call_args.kwargs["request"].product_id == "aspose.tex"


@pytest.mark.parametrize("tool", ["aspose_lookup", "search_symbols", "get_symbol", "list_members"])
def test_total_structured_searches_both_without_language_fallback(tool):
    client = _client(store=_store([
        ("aspose.words", "net"), ("aspose.tex", "java"), ("aspose.cells", "net"),
    ]))
    args = {**TOOLS[tool]}
    if tool == "list_members":
        args["parent_fqn"] = "aspose.words"
    results = _call(client, tool, args, path=TOTAL)["result"]["structuredContent"]
    groups = results["results_by_product"]
    assert [x["product_id"] for x in groups] == ["aspose.words", "aspose.tex"]
    words, tex = [x["result"] for x in groups]
    assert words.get("found") or words.get("results") or words.get("members")
    assert not tex.get("found") and not tex.get("results") and not tex.get("members")
    assert tex["hint"]["resolved_language"] == "net"


def test_missing_product_does_not_hide_other_product_and_backend_errors_propagate():
    public = Mock()
    # Use a concrete successful response for the second product.
    found = Mock()
    found.model_dump.return_value = {"signature": "TeXJob"}
    public.get_symbol_doc.side_effect = [LookupError("missing"), found]
    client = _client(public)
    result = _call(client, "get_symbol_doc", {"symbol_fqn": "TeXJob"}, path=TOTAL)
    groups = result["result"]["structuredContent"]["results_by_product"]
    assert groups[0] == {"product_id": "aspose.words", "not_found": True}
    assert groups[1]["result"]["signature"] == "TeXJob"
    public.get_symbol_doc.side_effect = RuntimeError("backend unavailable")
    assert "error" in _call(client, "get_symbol_doc", {"symbol_fqn": "TeXJob"}, path=TOTAL)


def test_shorthand_and_shared_session_keep_total_scope():
    client = _client(store=_store([("aspose.words", "net"), ("aspose.tex", "net")]))
    session = _rpc(client, "initialize", path="/mcp/v1/streamable-http")["result"]["session_id"]
    result = _rpc(client, "tools/search_symbols", {
        "session_id": session, "arguments": {"query": "Document"},
    }, path=TOTAL)["result"]["structuredContent"]
    assert len(result["results_by_product"]) == 2
    assert all(x["result"]["results"] for x in result["results_by_product"])
