#!/usr/bin/env python
"""Detailed end-to-end tests against the running ADCS API (local full stack).

Goes beyond the smoke test: multi-language scope isolation, case-insensitive
FQN lookup, overload/facet response structure, list_members on namespaces,
cross-product search, edge cases (miss → 404 / found=False, wrong scope), and
the legacy dense get_symbol_doc path degrading gracefully on an empty Qdrant.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8080"
_results: list[tuple[bool, str, str]] = []


def _post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def ck(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}", flush=True)


# (product, language, version, locale, member_fqn, parent_fqn) — clean primary scopes
CELLS_NET = ("aspose.cells", "net", "latest-stable", "en", "aspose.cells.workbook", "aspose.cells")
CELLS_JAVA = (
    "aspose.cells",
    "java",
    "latest-stable",
    "en",
    "com.aspose.cells.workbook",
    "com.aspose.cells",
)


def _scope(t):
    return {"product_id": t[0], "language": t[1], "version": t[2], "locale": t[3]}


def main() -> int:
    # 1. Case-insensitive exact lookup — three casings resolve to one row.
    p, lang, ver, loc, fqn, parent = CELLS_NET
    sc = _scope(CELLS_NET)
    variants = {}
    for label, q in (("lower", fqn.lower()), ("UPPER", fqn.upper()), ("Mixed", fqn.title())):
        st, body = _post("/v1/symbols/structured:get", {**sc, "symbol_fqn": q})
        variants[label] = (st, body.get("found"), body.get("member_fqn"))
    ck(
        "case-insensitive get_symbol (3 casings)",
        all(v[0] == 200 and v[1] for v in variants.values())
        and len({v[2] for v in variants.values()}) == 1,
        str({k: v[1] for k, v in variants.items()}),
    )

    # 2. Overload/facet response structure.
    st, body = _post("/v1/symbols/structured:get", {**sc, "symbol_fqn": fqn})
    ov = (body.get("overloads") or [{}])[0]
    ck(
        "get_symbol response structure",
        st == 200
        and "kind" in body
        and "overloads" in body
        and {"signature", "summary", "parameters", "returns", "remarks", "examples"}
        <= set(ov.keys()),
        f"kind={body.get('kind')} keys={sorted(ov.keys())}",
    )

    # 3. list_members of a class → sorted children.
    st, body = _post("/v1/symbols/structured:members", {**sc, "parent_fqn": parent})
    members = body.get("members", [])
    kinds_names = [(m["kind"], m["name"]) for m in members]
    ck(
        "list_members sorted by (kind,name)",
        st == 200 and len(members) > 5 and kinds_names == sorted(kinds_names),
        f"n={len(members)}",
    )

    # 4. Multi-language scope isolation: java member found in java, not in net.
    pj, lj, vj, lcj, fqj, parj = CELLS_JAVA
    scj = _scope(CELLS_JAVA)
    st_j, b_j = _post("/v1/symbols/structured:get", {**scj, "symbol_fqn": fqj})
    st_x, b_x = _post(
        "/v1/symbols/structured:get", {**sc, "symbol_fqn": fqj}
    )  # java fqn in net scope
    ck(
        "scope isolation (java fqn: found in java, 404 in net)",
        st_j == 200 and b_j.get("found") is True and st_x == 404,
        f"java=(200,{b_j.get('found')}) net_status={st_x}",
    )

    # 5. Cross-product search.
    hits = {}
    for prod, q in (
        ("aspose.cells", "Workbook"),
        ("aspose.html", "Element"),
        ("aspose.email", "Message"),
    ):
        st, body = _post(
            "/v1/symbols/structured:search",
            {
                "product_id": prod,
                "language": "net",
                "version": "latest-stable",
                "locale": "en",
                "query": q,
            },
        )
        hits[prod] = len(body.get("results", []))
    ck("cross-product search returns results", all(v > 0 for v in hits.values()), str(hits))

    # 6. Edge: nonexistent symbol → REST 404 + MCP found=False.
    st, _ = _post(
        "/v1/symbols/structured:get", {**sc, "symbol_fqn": "aspose.cells.NoSuchSymbolXyz"}
    )
    ck("miss → REST 404", st == 404, f"status={st}")

    # 7. Edge: wrong scope (valid fqn, bogus version) → 404 not found.
    st, body = _post(
        "/v1/symbols/structured:get", {**sc, "version": "does-not-exist", "symbol_fqn": fqn}
    )
    ck("wrong-version scope → 404", st == 404, f"status={st}")

    # 8. MCP session + structured tool parity with REST.
    st, init = _post("/mcp/v1/initialize", {"requested_revision": None})
    sess = init.get("session_id", "")
    st, body = _post(
        "/mcp/v1/tools/get_symbol",
        {"session_id": sess, "arguments": {**sc, "symbol_fqn": fqn.upper()}},
    )
    res = body.get("result", body)
    ck(
        "MCP get_symbol parity (case-insensitive)",
        st == 200 and res.get("found") is True,
        f"found={res.get('found')}",
    )

    # 9. Legacy dense get_symbol_doc degrades gracefully on empty Qdrant (no 500).
    st, _ = _post(
        "/mcp/v1/tools/get_symbol_doc",
        {
            "session_id": sess,
            "arguments": {"product_id": p, "language": lang, "symbol_fqn": "Aspose.Cells.Workbook"},
        },
    )
    ck("legacy get_symbol_doc no 500 (empty dense index)", st in (200, 404, 422), f"status={st}")

    failed = [r for r in _results if not r[0]]
    print(
        f"\n== {len(_results) - len(failed)}/{len(_results)} detailed checks passed ==", flush=True
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
