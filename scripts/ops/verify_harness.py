#!/usr/bin/env python
"""Verify the two-source harness (docs + apiref) on REAL live data.

Builds a TwoSourceRetriever where:
  - the docs lane calls the live /v1/docs:query endpoint (Qdrant + embeddings) and
    maps results into HybridCandidate, and
  - the apiref lane is the real ApiRefRetriever over the live Postgres store.

Then runs queries scoped to products that have BOTH corpora locally and asserts
the fused result set contains docs AND apiref hits (RRF fan-out), plus that an
exact FQN short-circuits to the top.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Sequence

from adcs.indexing.apiref_symbol_store import ApiRefScope, PostgresApiRefSymbolStore
from adcs.retrieval.retrieval_models import HybridCandidate, RetrievalCandidateMetadata
from adcs.retrieval.two_source_retriever import (
    ApiRefRetriever,
    TwoSourceRetriever,
)

API = os.environ.get("ADCS_API", "http://localhost:8080")
DSN = os.environ.get("POSTGRES_DSN", "postgresql+psycopg://adcs:adcs@localhost:5432/adcs")


class LiveDocsLane:
    """DocsLane backed by the live /v1/docs:query endpoint."""

    def __init__(self, *, product: str, language: str) -> None:
        self._product = product
        self._language = language

    def search(self, *, query: str, limit: int) -> Sequence[HybridCandidate]:
        body = json.dumps(
            {
                "query": query,
                "product_id": self._product,
                "language": self._language,
                "top_k": min(limit, 20),
            }
        ).encode()
        req = urllib.request.Request(
            f"{API}/v1/docs:query",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = json.loads(resp.read() or b"{}")
        candidates: list[HybridCandidate] = []
        for index, item in enumerate(payload.get("results", [])):
            url = item.get("canonical_url") or f"docs:{index}"
            meta = RetrievalCandidateMetadata(
                candidate_id=url,
                chunk_id=url,
                snapshot_id="live",
                product_id=self._product,
                programming_language=self._language,
                version=item.get("version") or "latest-stable",
                source_kind="docs",
                doc_type="guide",
                doc_locale=item.get("doc_locale") or "unknown",
                symbol_fqn=None,
                title=item.get("title") or "",
                canonical_url=url,
                section_anchor=item.get("section_anchor") or "#",
                source_revision="live",
                repo_id=f"{self._product}.docs",
                text=(item.get("snippet") or item.get("text") or "")[:500],
                checksum="x",
            )
            score = float(len(payload["results"]) - index)
            candidates.append(
                HybridCandidate(
                    metadata=meta,
                    dense_raw_score=score,
                    lexical_raw_score=None,
                    dense_normalized_score=1.0,
                    lexical_normalized_score=0.0,
                    blended_score=score,
                    rerank_score=score,
                )
            )
        return candidates


def _run(*, product: str, language: str, version: str, query: str, fqn_query: str | None) -> bool:
    store = PostgresApiRefSymbolStore(postgres_dsn=DSN)
    scope = ApiRefScope(product=product, language=language, version=version, locale="en")
    retriever = TwoSourceRetriever(
        docs_lane=LiveDocsLane(product=product, language=language),
        apiref_lane=ApiRefRetriever(store=store),
    )
    ok = True

    result = retriever.retrieve(query=query, scope=scope, limit=10)
    sources = {h.source for h in result.hits}
    print(
        f"[{product}/{language}] q={query!r} -> docs={result.docs_count} "
        f"apiref={result.apiref_count} fused_sources={sorted(sources)}"
    )
    for h in result.hits[:6]:
        print(f"    {h.source:6} rrf={h.rrf_score:.4f} | {(h.title or '')[:60]}")
    if not ({"docs", "apiref"} <= sources):
        print("    !! expected BOTH docs and apiref in fused results")
        ok = False

    if fqn_query:
        exact = retriever.retrieve(query=fqn_query, scope=scope, limit=10)
        top = exact.hits[0] if exact.hits else None
        pinned = bool(top and top.source == "apiref" and top.is_exact_symbol)
        print(
            f"[{product}] exact-FQN {fqn_query!r} -> pinned_top={pinned} "
            f"(exact_hit={exact.exact_symbol_hit})"
        )
        if not pinned:
            print("    !! exact FQN did not pin a symbol to the top")
            ok = False
    return ok


def main() -> int:
    store = PostgresApiRefSymbolStore(postgres_dsn=DSN)
    # discover a real FQN for the apiref product to test the exact short-circuit
    from sqlalchemy import text

    cases = []
    for product, language, query in [
        ("aspose.cad", "net", "convert a CAD drawing to PDF"),
        ("aspose.email", "net", "read an email message from a file"),
    ]:
        with store._engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT version, member_fqn FROM symbols WHERE product=:p AND language=:l "
                    "AND member_fqn LIKE '%.%.%' ORDER BY md5(member_fqn) LIMIT 1"
                ),
                {"p": product, "l": language},
            ).first()
        if row is None:
            print(f"[skip] no apiref symbols for {product}/{language}")
            continue
        version, fqn = row
        cases.append((product, language, version, query, fqn))

    results = [
        _run(product=p, language=lang, version=v, query=q, fqn_query=f)
        for p, lang, v, q, f in cases
    ]
    print(f"\n== harness checks: {sum(results)}/{len(results)} products passed ==")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
