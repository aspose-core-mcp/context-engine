#!/usr/bin/env python
"""End-to-end smoke test against a running ADCS API (local full stack).

Exercises health, the structured API-reference REST endpoints (Postgres path),
and the MCP tool surface over HTTP. Prints PASS/FAIL per check; exits non-zero
if any hard check fails. Pure stdlib (urllib) so it runs anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PASS = "PASS"
FAIL = "FAIL"
_results: list[tuple[str, str, str]] = []


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def _get(base: str, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(base + path, timeout=15) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw or b"{}")
            except Exception:
                return resp.status, {"_raw": raw.decode(errors="replace")[:200]}
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((PASS if ok else FAIL, name, detail))
    print(f"[{PASS if ok else FAIL}] {name}{' — ' + detail if detail else ''}", flush=True)


def wait_healthy(base: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            status, _ = _get(base, "/healthz")
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--product", default="aspose.cells")
    ap.add_argument("--language", default="net")
    ap.add_argument("--version", default="latest-stable")
    ap.add_argument("--locale", default="en")
    # query proper-case to exercise case-insensitive FQN lookup
    ap.add_argument("--symbol", default="Aspose.Cells.Workbook")
    ap.add_argument("--parent", default="aspose.cells.workbook")
    ap.add_argument("--search", default="Workbook")
    args = ap.parse_args()
    base = args.base
    scope = {
        "product_id": args.product,
        "language": args.language,
        "version": args.version,
        "locale": args.locale,
    }

    print(f"== waiting for {base}/healthz ==", flush=True)
    if not wait_healthy(base):
        check("api healthy", False, "no /healthz 200")
        return 1
    check("api healthy", True)

    st, _ = _get(base, "/readyz")
    check("readyz", st in (200, 503), f"status={st}")  # 503 ok if docs index empty

    # --- REST: structured apiref (Postgres path) ---
    st, body = _post(base, "/v1/symbols/structured:get", {**scope, "symbol_fqn": args.symbol})
    found = bool(body.get("found"))
    check(
        "REST get_symbol (case-insensitive)",
        st == 200 and found,
        f"status={st} found={found} overloads={len(body.get('overloads', []))}",
    )

    st, body = _post(base, "/v1/symbols/structured:members", {**scope, "parent_fqn": args.parent})
    n_members = len(body.get("members", []))
    check("REST list_members", st == 200 and n_members > 0, f"status={st} members={n_members}")

    st, body = _post(base, "/v1/symbols/structured:search", {**scope, "query": args.search})
    n_results = len(body.get("results", []))
    check("REST search_symbols", st == 200 and n_results > 0, f"status={st} results={n_results}")

    # --- MCP tool surface ---
    st, body = _post(base, "/mcp/v1/initialize", {"requested_revision": None})
    session = body.get("session_id", "")
    check(
        "MCP initialize",
        st == 200 and bool(session),
        f"status={st} rev={body.get('negotiated_revision')}",
    )

    if session:
        tools = body.get("capabilities", {}).get("tools", [])
        has_structured = {"get_symbol", "list_members", "search_symbols"} <= set(tools)
        check("MCP advertises structured tools", has_structured, f"tools={tools}")

        st, body = _post(
            base,
            "/mcp/v1/tools/get_symbol",
            {"session_id": session, "arguments": {**scope, "symbol_fqn": args.symbol}},
        )
        result = body.get("result", body)
        check(
            "MCP get_symbol",
            st == 200 and bool(result.get("found")),
            f"status={st} found={result.get('found')}",
        )

        st, body = _post(
            base,
            "/mcp/v1/tools/list_members",
            {"session_id": session, "arguments": {**scope, "parent_fqn": args.parent}},
        )
        result = body.get("result", body)
        check(
            "MCP list_members",
            st == 200 and len(result.get("members", [])) > 0,
            f"status={st} members={len(result.get('members', []))}",
        )

        st, body = _post(
            base,
            "/mcp/v1/tools/search_symbols",
            {"session_id": session, "arguments": {**scope, "query": args.search}},
        )
        result = body.get("result", body)
        check(
            "MCP search_symbols",
            st == 200 and len(result.get("results", [])) > 0,
            f"status={st} results={len(result.get('results', []))}",
        )

        st, body = _post(
            base,
            "/mcp/v1/tools/resolve_product",
            {"session_id": session, "arguments": {"query": "Aspose.Cells for .NET"}},
        )
        result = body.get("result", body)
        check("MCP resolve_product", st == 200, f"status={st} product={result.get('product_id')}")

        st, body = _post(
            base,
            "/mcp/v1/tools/query_docs",
            {
                "session_id": session,
                "arguments": {
                    "query": "how to save a workbook",
                    "product_id": args.product,
                    "language": args.language,
                    "top_k": 3,
                },
            },
        )
        # docs index is empty locally → tool must still respond 200 (just no/empty results)
        check("MCP query_docs responds", st == 200, f"status={st}")

    failed = [r for r in _results if r[0] == FAIL]
    print(f"\n== {len(_results) - len(failed)}/{len(_results)} checks passed ==", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
