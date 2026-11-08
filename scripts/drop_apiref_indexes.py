#!/usr/bin/env python3
"""Drop the legacy apiref vector/lexical indexes after the Postgres cutover.

Once API Reference is served from the Postgres structured symbol store (ADR-011)
and the docs hybrid lane is docs-only
(``APIREF_STRUCTURED_STORE_ENABLED=true``; see ``runtime/components.py``), the
Qdrant ``apiref_dense_v1`` collection and the OpenSearch ``apiref_lex_v1_active``
alias (and its backing indices) are no longer queried and can be removed.

Safety:
  * Dry-run by default — prints exactly what *would* be dropped. Pass ``--apply``
    to execute.
  * Refuses to drop unless the Postgres structured store actually holds apiref
    symbols for at least one product (so we never strand API Reference by
    dropping the vector lane before the cutover data is in place). Override this
    guard only with ``--force`` (not recommended).
  * Idempotent — a missing collection/alias is reported and skipped, not failed.

Usage:
    PYTHONPATH=./src python3 scripts/drop_apiref_indexes.py            # dry-run
    PYTHONPATH=./src python3 scripts/drop_apiref_indexes.py --apply    # execute

Env:
    QDRANT_URL       (default http://localhost:6333)
    OPENSEARCH_URL   (default http://localhost:9200)
    POSTGRES_DSN     (default postgresql+psycopg://adcs:adcs@localhost:5432/adcs)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql+psycopg://adcs:adcs@localhost:5432/adcs"
)

QDRANT_APIREF_COLLECTION = "apiref_dense_v1"
OPENSEARCH_APIREF_ALIAS = "apiref_lex_v1_active"


def _http(method: str, url: str, timeout: float = 15.0) -> tuple[int, object]:
    req = request.Request(url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except (error.URLError, TimeoutError) as exc:  # connection refused, DNS, ...
        return 0, str(exc)


def _structured_store_has_symbols() -> tuple[bool, str]:
    """True when the Postgres structured store holds apiref for ≥1 product."""
    try:
        from adcs.indexing.apiref_symbol_store import build_apiref_symbol_store
    except Exception as exc:  # pragma: no cover - import/path issue
        return False, f"could not import structured store: {exc}"
    store = build_apiref_symbol_store(enabled=True, postgres_dsn=POSTGRES_DSN)
    if store is None:
        return False, "structured store unavailable (Postgres unreachable?)"
    try:
        vocabulary = store.known_vocabulary()
    except Exception as exc:  # pragma: no cover - query failure
        return False, f"known_vocabulary failed: {exc}"
    products = sorted(vocabulary)
    if not products:
        return False, "structured store has zero apiref products"
    return True, f"{len(products)} apiref products in Postgres: {', '.join(products[:6])}…"


def _drop_qdrant(apply: bool) -> None:
    status, body = _http("GET", f"{QDRANT_URL}/collections/{QDRANT_APIREF_COLLECTION}")
    if status == 404:
        print(f"  [skip] Qdrant collection {QDRANT_APIREF_COLLECTION} already absent")
        return
    if status != 200:
        print(f"  [warn] Qdrant probe status={status} body={body!r} — leaving untouched")
        return
    points = ""
    if isinstance(body, dict):
        result = body.get("result", {})
        points = f" (points_count={result.get('points_count')})"
    if not apply:
        print(f"  [dry-run] would DELETE Qdrant collection {QDRANT_APIREF_COLLECTION}{points}")
        return
    status, body = _http("DELETE", f"{QDRANT_URL}/collections/{QDRANT_APIREF_COLLECTION}")
    print(f"  [apply] DELETE Qdrant {QDRANT_APIREF_COLLECTION} -> status={status}")


def _drop_opensearch(apply: bool) -> None:
    status, body = _http("GET", f"{OPENSEARCH_URL}/_alias/{OPENSEARCH_APIREF_ALIAS}")
    if status == 404:
        print(f"  [skip] OpenSearch alias {OPENSEARCH_APIREF_ALIAS} already absent")
        return
    if status != 200 or not isinstance(body, dict):
        print(f"  [warn] OpenSearch alias probe status={status} body={body!r} — leaving untouched")
        return
    indices = sorted(body.keys())
    if not indices:
        print(f"  [skip] OpenSearch alias {OPENSEARCH_APIREF_ALIAS} has no backing indices")
        return
    if not apply:
        print(
            f"  [dry-run] would DELETE {len(indices)} OpenSearch index(es) behind "
            f"{OPENSEARCH_APIREF_ALIAS}: {', '.join(indices)}"
        )
        return
    # Deleting the indices removes them from the alias atomically.
    joined = ",".join(indices)
    status, body = _http("DELETE", f"{OPENSEARCH_URL}/{joined}")
    print(f"  [apply] DELETE OpenSearch indices [{joined}] -> status={status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="drop even if the Postgres structured store looks empty (unsafe)",
    )
    args = parser.parse_args()

    print(f"Qdrant     : {QDRANT_URL}")
    print(f"OpenSearch : {OPENSEARCH_URL}")
    print(f"Postgres   : {POSTGRES_DSN.rsplit('@', 1)[-1]}")
    print(f"Mode       : {'APPLY (destructive)' if args.apply else 'dry-run'}\n")

    ok, detail = _structured_store_has_symbols()
    print(f"Precondition (apiref in Postgres): {'OK' if ok else 'FAILED'} — {detail}")
    if not ok and not args.force:
        print(
            "\nAborting: refusing to drop the apiref vector/lexical lane while the "
            "Postgres cutover data is not in place. Re-run with --force to override."
        )
        return 1

    print("\nQdrant:")
    _drop_qdrant(args.apply)
    print("\nOpenSearch:")
    _drop_opensearch(args.apply)

    if not args.apply:
        print("\nDry-run complete. Re-run with --apply to drop the indexes.")
    else:
        print("\nDone. The apiref vector/lexical lane has been retired.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
