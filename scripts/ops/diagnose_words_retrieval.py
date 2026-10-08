"""Read-only candidate diagnostics; run from the worktree with PYTHONPATH=src.

Reads the configured PostgreSQL store and queries an already running local API.
Does not initialize stores, alter indexes, or invoke ingestion.
"""

from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, text

from adcs.config import get_settings
from adcs.indexing.apiref_symbol_store import _latest_version
from adcs.retrieval.two_source_retriever import api_search_queries

QUESTION = "How do I convert a Word document to PDF?"
SCOPE = """
FROM symbols s JOIN apiref_active_snapshot a
 ON s.snapshot_id=a.snapshot_id AND s.product=a.product
 AND s.language=a.language AND s.version=a.version AND s.locale=a.locale
WHERE s.product=:product AND s.language=:language AND s.locale=:locale
 AND s.version=:version
"""


def main() -> None:
    settings = get_settings()
    report: dict = {"structured_store_enabled_in_local_settings":
                    settings.apiref_structured_store_enabled}
    report["production_search_queries"] = api_search_queries(QUESTION)
    engine = create_engine(settings.postgres_dsn)
    params = {"product": "aspose.words", "language": "net", "locale": "en"}
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            snapshots = connection.execute(text(
                "SELECT version, snapshot_id FROM apiref_active_snapshot "
                "WHERE product=:product AND language=:language AND locale=:locale"
            ), params).mappings().all()
            report["active_snapshots"] = [dict(row) for row in snapshots]
            params["version"] = _latest_version({row["version"] for row in snapshots})
            report["resolved_version"] = params["version"]
            if not params["version"]:
                raise RuntimeError("No active Words/.NET API snapshot")
            report["active_symbol_count"] = connection.execute(
                text("SELECT count(*) " + SCOPE), params
            ).scalar_one()
            probes = []
            for query in (QUESTION, "convert PDF", "PDF", "Save", "Document"):
                p = {**params, "q": query, "prefix": query + "%"}
                probe = {"query": query}
                probe["fts_query"] = connection.execute(
                    text("SELECT CAST(websearch_to_tsquery('simple', :q) AS TEXT)"), p
                ).scalar_one()
                predicates = {
                    "name": "(s.name ILIKE :prefix OR similarity(s.name, :q) > 0.3)",
                    "fts": "s.fts @@ websearch_to_tsquery('simple', :q)",
                }
                for lane, predicate in predicates.items():
                    probe[lane + "_count"] = connection.execute(
                        text("SELECT count(*) " + SCOPE + " AND " + predicate), p
                    ).scalar_one()
                    order = (
                        "(s.name ILIKE :prefix) DESC, similarity(s.name, :q) DESC, s.name"
                        if lane == "name"
                        else "ts_rank(s.fts, websearch_to_tsquery('simple', :q)) DESC"
                    )
                    rows = connection.execute(text(
                        "SELECT s.member_fqn, s.signature, s.canonical_url " + SCOPE
                        + " AND " + predicate + " ORDER BY " + order + " LIMIT 5"
                    ), p).mappings().all()
                    probe[lane + "_samples"] = [dict(row) for row in rows]
                probes.append(probe)
            report["postgres_candidate_probes"] = probes
    finally:
        engine.dispose()

    report["api_queries"] = []
    for query in (QUESTION, "Aspose.Words.Document.Save"):
        request = Request(
            "http://127.0.0.1:8080/v1/docs:query",
            data=json.dumps({
                "query": query, "product_id": "aspose.words", "language": "net",
                "query_locale": "en", "top_k": 20, "include_examples": True,
                "debug": True,
            }).encode(),
            # `debug` is intentionally restricted to administrators. The key
            # comes from local settings and is never emitted in this report.
            headers={
                "Content-Type": "application/json",
                "x-api-key": settings.admin_api_key.get_secret_value(),
            },
        )
        try:
            with urlopen(request, timeout=90) as response:
                payload = json.load(response)
            report["api_queries"].append({
                "query": query, "warnings": payload.get("warnings"),
                "quality": payload.get("quality"),
                "debug": payload.get("debug"),
                "results": [{
                    "rank": i, "chunk_id": item["chunk_id"], "title": item["title"],
                    "score": item["score"], "canonical_url": item["canonical_url"],
                } for i, item in enumerate(payload.get("results", []), 1)],
            })
        except Exception as exc:
            error = {"query": query, "error_type": type(exc).__name__}
            if isinstance(exc, URLError):
                error["connection_reason"] = str(exc.reason)[:300]
            report["api_queries"].append(error)
    print(json.dumps(report, indent=2))
    if any("error_type" in result for result in report["api_queries"]):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Database exceptions can include connection details; do not print secrets.
        print(f"Diagnostic failed: {type(exc).__name__}; check local settings/services.",
              file=sys.stderr)
        raise SystemExit(1) from None
