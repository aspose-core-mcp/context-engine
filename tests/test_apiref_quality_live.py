"""Live end-to-end regression gate for the apiref MCP client-quality fixes.

The service-layer fixes are unit-tested against the in-memory store; this harness
re-asserts the same behaviours against the *running* MCP (real Postgres data), so a
data re-ingest or a deploy regression is caught with one command:

    ADCS_MCP_URL=http://localhost:8080 \\
    PYTHONPATH=src .venv/bin/python -m pytest tests/test_apiref_quality_live.py -q

Auto-skips when the MCP is unreachable (e.g. CI without the stack up). Assertions
are deliberately robust to data churn — they pin the *behaviours* the audit fixed
(ranking, forgiveness, no-dead-end), not exact corpus counts. Requires aspose.cells
and aspose.psd to be loaded (they are in the dev corpus).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

_MCP_URL = os.environ.get("ADCS_MCP_URL", "http://localhost:8080").rstrip("/")
_ENDPOINT = f"{_MCP_URL}/mcp/v1/streamable-http"


def _reachable() -> bool:
    try:
        response = httpx.post(
            _ENDPOINT,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            timeout=3.0,
        )
        return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


_require_live = os.environ.get("ADCS_REQUIRE_LIVE_SURFACE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _require_live and not _reachable(),
        reason=f"apiref MCP not reachable at {_ENDPOINT} — skipping live gate",
    ),
]


def _call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        _ENDPOINT,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        timeout=30.0,
    )
    response.raise_for_status()
    blocks = response.json().get("result", {}).get("content", [])
    for block in blocks:
        if block.get("type") == "text":
            parsed: dict[str, Any] = json.loads(block["text"])
            return parsed
    raise AssertionError(f"no text content in {tool} response")


def _top(results: list[dict[str, Any]]) -> str | None:
    return results[0]["member_fqn"] if results else None


# --- #4: never silently substitute a different real product (pdf -> psd) ---


def test_live_pdf_does_not_resolve_to_psd() -> None:
    out = _call("aspose_lookup", {"query": "save", "product_id": "aspose.pdf", "language": "net"})
    # aspose.pdf is a real, loaded product: it must resolve to itself and return
    # PDF symbols — never the edit-distance-1 neighbour aspose.psd (Photoshop).
    assert out["resolved_product_id"] == "aspose.pdf"
    assert all(r["member_fqn"].startswith("aspose.pdf.") for r in out["results"])


# --- #5: canonical class outranks namesake property accessors ---


def test_live_worksheet_canonical_class_ranks_first() -> None:
    out = _call("aspose_lookup", {"query": "Worksheet", "product_id": "cells", "language": "net"})
    assert _top(out["results"]) == "aspose.cells.worksheet"


# --- #7: get_symbol resolves a bare name ---


def test_live_get_symbol_bare_name_resolves() -> None:
    out = _call("get_symbol", {"product_id": "cells", "language": "net", "symbol_fqn": "Workbook"})
    assert out["found"] is True
    assert out["member_fqn"] == "aspose.cells.workbook"


# --- #8: no test-fixture product leaks into did-you-mean ---


def test_live_no_test_fixture_in_suggestions() -> None:
    out = _call("aspose_lookup", {"query": "Doc", "product_id": "restpg", "language": "net"})
    suggestions = (out.get("hint") or {}).get("available_products") or []
    assert all(s.split(".", 1)[0] in {"aspose", "groupdocs"} for s in suggestions)


# --- #13: a distinctive bare product leaf in prose grounds ---


def test_live_bare_leaf_in_prose_grounds() -> None:
    out = _call("aspose_lookup", {"query": "how to make a chart in cells"})
    assert out["resolved_product_id"] == "aspose.cells"
    assert out["results"]


# --- parity: search_symbols and aspose_lookup agree on the same query ---


def test_live_search_lookup_parity() -> None:
    query = "Worksheet"
    args = {"product_id": "cells", "language": "net", "query": query}
    search = _call("search_symbols", args)
    lookup = _call("aspose_lookup", args)
    assert _top(search["results"]) == _top(lookup["results"])


# --- hint hygiene: 'unknown' never advertised as a language ---


def test_live_hint_excludes_unknown_language() -> None:
    out = _call(
        "search_symbols",
        {"product_id": "cells", "language": "net", "query": "zzz_no_such_symbol_123"},
    )
    languages = (out.get("hint") or {}).get("available_languages") or []
    assert "unknown" not in languages


# --- #2: an explicit non-matching version is not a dead-end ---


def test_live_explicit_version_resolves_not_dead_end() -> None:
    out = _call(
        "aspose_lookup",
        {"query": "Workbook", "product_id": "cells", "language": "net", "version": "1.2.3"},
    )
    assert out["results"]  # resolves to the active snapshot instead of returning []


# --- #5/#7 generalise across products, not just cells (cross-product QA) ---


@pytest.mark.parametrize(
    ("product", "flagship_class"),
    [
        ("email", "MailMessage"),
        ("ocr", "AsposeOcr"),
        ("psd", "PsdImage"),
        ("html", "HTMLDocument"),
        ("zip", "Archive"),
    ],
)
def test_live_cross_product_bare_name_resolves(product: str, flagship_class: str) -> None:
    # The bare-name fallback + canonical-class rerank are generic; verify each
    # product's flagship class resolves (guards a per-product regression).
    args = {"product_id": product, "language": "net", "symbol_fqn": flagship_class}
    out = _call("get_symbol", args)
    assert out["found"] is True
    assert out["member_fqn"].rsplit(".", 1)[-1] == flagship_class.lower()
