#!/usr/bin/env python3
"""Backfill the OpenSearch lexical index from Qdrant vector payloads.

Reads all points from the Qdrant docs collection (``DOCS_VECTOR_COLLECTION``,
default ``docs_dense_en_v1``), creates the consolidated OpenSearch lexical index,
and sets up the ``docs_lex_v1_active`` alias the retrieval layer expects. apiref
is served from the Postgres structured store (ADR-011), so the retired
``apiref_dense_v1`` vector collection is NOT backfilled here.

This is the lexical-lane step of the DR restore (OpenSearch is not backed up to
object storage; it is rebuilt from Qdrant after the dense collection is restored)
and is also useful when OpenSearch data is lost (volume wipe, crash-loop) but
Qdrant retains the full payload data.

Usage:
    python3 scripts/backfill_opensearch_from_qdrant.py

Environment:
    QDRANT_URL              (default: http://localhost:6333)
    OPENSEARCH_URL          (default: http://localhost:9200)
    DOCS_VECTOR_COLLECTION  (default: docs_dense_en_v1) — source collection
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib import error, request

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")

# Qdrant collection -> OpenSearch index/alias mapping. Only the EN docs collection
# feeds the lexical lane; the name is settings-driven so serving, admin counters,
# and the DR backup/restore bundle all agree on it.
_DOCS_COLLECTION = os.environ.get("DOCS_VECTOR_COLLECTION", "docs_dense_en_v1")
COLLECTION_MAP = {
    _DOCS_COLLECTION: {
        "index": "docs_lex_v1_consolidated",
        "alias": "docs_lex_v1_active",
        "source_kind": "docs",
    },
}

OPENSEARCH_MAPPINGS = {
    "properties": {
        "chunk_id": {"type": "keyword"},
        "snapshot_id": {"type": "keyword"},
        "product_id": {"type": "keyword"},
        "product_family": {"type": "keyword"},
        "programming_language": {"type": "keyword"},
        "version": {"type": "keyword"},
        "source_kind": {"type": "keyword"},
        "doc_type": {"type": "keyword"},
        "doc_locale": {"type": "keyword"},
        "symbol_fqn": {"type": "keyword"},
        "title": {"type": "text"},
        "canonical_url": {"type": "keyword"},
        "section_anchor": {"type": "keyword"},
        "source_revision": {"type": "keyword"},
        "repo_id": {"type": "keyword"},
        "checksum": {"type": "keyword"},
        "text": {"type": "text"},
        "executable_snippets": {
            "type": "nested",
            "properties": {
                "snippet_id": {"type": "keyword"},
                "language": {"type": "keyword"},
                "code": {"type": "text"},
                "parent_canonical_url": {"type": "keyword"},
                "parent_section_anchor": {"type": "keyword"},
                "parent_symbol_fqn": {"type": "keyword"},
            },
        },
    }
}

BULK_BATCH_SIZE = 500
QDRANT_SCROLL_LIMIT = 200


def http_request(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 30.0,
    content_type: str = "application/json",
) -> tuple[int, object]:
    body: bytes | None = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = content_type
    req = request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw.strip():
                return response.status, {}
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                # Not every OpenSearch endpoint speaks JSON: the _cat APIs return
                # plain text. Hand the raw body back (exactly as the HTTPError
                # path below already does) instead of raising, so callers can
                # print it. Raising here made every backfill run end in a
                # traceback at the final _cat/indices verification.
                return response.status, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def http_request_ndjson(
    url: str,
    payload_bytes: bytes,
    timeout: float = 60.0,
) -> tuple[int, object]:
    headers = {"Content-Type": "application/x-ndjson"}
    req = request.Request(url=url, data=payload_bytes, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw.strip():
                return response.status, {}
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                # Same tolerance as http_request: never raise on a non-JSON body.
                return response.status, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def check_opensearch_health() -> bool:
    try:
        status, body = http_request(f"{OPENSEARCH_URL}/_cluster/health", timeout=5.0)
        if status == 200 and isinstance(body, dict):
            print(f"  OpenSearch cluster: {body.get('status')}, "
                  f"nodes: {body.get('number_of_nodes')}")
            return True
    except Exception as exc:
        print(f"  OpenSearch not reachable: {exc}")
    return False


def check_qdrant_health() -> bool:
    try:
        status, body = http_request(f"{QDRANT_URL}/collections", timeout=5.0)
        if status == 200 and isinstance(body, dict):
            collections = body.get("result", {}).get("collections", [])
            print(f"  Qdrant collections: {[c['name'] for c in collections]}")
            return True
    except Exception as exc:
        print(f"  Qdrant not reachable: {exc}")
    return False


def get_qdrant_collection_count(collection: str) -> int:
    status, body = http_request(f"{QDRANT_URL}/collections/{collection}", timeout=5.0)
    if status == 200 and isinstance(body, dict):
        return body.get("result", {}).get("points_count", 0)
    return 0


def create_opensearch_index(index_name: str) -> None:
    # Check if index already exists
    status, _ = http_request(f"{OPENSEARCH_URL}/{index_name}", timeout=5.0)
    if status == 200:
        print(f"  Index {index_name} already exists, deleting...")
        del_status, _ = http_request(
            f"{OPENSEARCH_URL}/{index_name}", method="DELETE", timeout=10.0
        )
        if del_status not in (200,):
            print(f"  WARNING: Failed to delete index {index_name}")
            return

    payload = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "-1",  # Disable refresh during bulk load
            }
        },
        "mappings": OPENSEARCH_MAPPINGS,
    }
    status, body = http_request(
        f"{OPENSEARCH_URL}/{index_name}", method="PUT", payload=payload, timeout=10.0
    )
    if status != 200:
        print(f"  ERROR creating index {index_name}: {body}")
        sys.exit(1)
    print(f"  Created index: {index_name}")


def scroll_qdrant_collection(collection: str):
    """Generator that yields all points from a Qdrant collection using scroll API."""
    offset = None
    while True:
        payload: dict = {
            "limit": QDRANT_SCROLL_LIMIT,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset

        status, body = http_request(
            f"{QDRANT_URL}/collections/{collection}/points/scroll",
            method="POST",
            payload=payload,
            timeout=30.0,
        )
        if status != 200 or not isinstance(body, dict):
            print(f"  ERROR scrolling {collection}: status={status}")
            break

        result = body.get("result", {})
        points = result.get("points", [])
        if not points:
            break

        yield from points

        next_offset = result.get("next_page_offset")
        if next_offset is None:
            break
        offset = next_offset


def bulk_index_to_opensearch(index_name: str, docs: list[dict]) -> int:
    """Bulk index documents into OpenSearch. Returns count of successfully indexed docs."""
    if not docs:
        return 0

    lines: list[str] = []
    for doc in docs:
        chunk_id = doc.get("chunk_id", "")
        lines.append(json.dumps({"index": {"_index": index_name, "_id": chunk_id}}))
        lines.append(json.dumps(doc))

    bulk_payload = "\n".join(lines) + "\n"
    status, body = http_request_ndjson(
        f"{OPENSEARCH_URL}/_bulk",
        payload_bytes=bulk_payload.encode("utf-8"),
        timeout=120.0,
    )
    if status != 200:
        print(f"  ERROR: Bulk index failed (status={status})")
        return 0

    if isinstance(body, dict) and body.get("errors"):
        error_count = sum(
            1
            for item in body.get("items", [])
            if "error" in item.get("index", {})
        )
        return len(docs) - error_count

    return len(docs)


def set_alias(index_name: str, alias_name: str) -> None:
    """Set an alias pointing to the given index, removing from any other indices."""
    # First check for existing aliases
    status, body = http_request(f"{OPENSEARCH_URL}/_alias/{alias_name}", timeout=5.0)
    actions: list[dict] = []
    if status == 200 and isinstance(body, dict):
        for old_index in body:
            actions.append({"remove": {"index": old_index, "alias": alias_name}})
    actions.append({"add": {"index": index_name, "alias": alias_name}})

    status, body = http_request(
        f"{OPENSEARCH_URL}/_aliases",
        method="POST",
        payload={"actions": actions},
        timeout=10.0,
    )
    if status != 200:
        print(f"  ERROR setting alias {alias_name} -> {index_name}: {body}")
    else:
        print(f"  Alias: {alias_name} -> {index_name}")


def enable_refresh(index_name: str) -> None:
    """Re-enable refresh interval after bulk loading."""
    status, _ = http_request(
        f"{OPENSEARCH_URL}/{index_name}/_settings",
        method="PUT",
        payload={"index": {"refresh_interval": "1s"}},
        timeout=10.0,
    )
    if status != 200:
        print(f"  WARNING: Failed to re-enable refresh for {index_name}")
    # Force refresh
    http_request(f"{OPENSEARCH_URL}/{index_name}/_refresh", method="POST", timeout=30.0)


def payload_to_opensearch_doc(payload: dict) -> dict:
    """Convert a Qdrant payload to an OpenSearch document."""
    snippets = payload.get("executable_snippets", [])
    if not isinstance(snippets, list):
        snippets = []

    return {
        "chunk_id": payload.get("chunk_id", ""),
        "snapshot_id": payload.get("snapshot_id", ""),
        "product_id": payload.get("product_id", ""),
        "product_family": payload.get("product_family", ""),
        "programming_language": payload.get("programming_language", ""),
        "version": payload.get("version", ""),
        "source_kind": payload.get("source_kind", ""),
        "doc_type": payload.get("doc_type", ""),
        "doc_locale": payload.get("doc_locale", ""),
        "symbol_fqn": payload.get("symbol_fqn"),
        "title": payload.get("title", ""),
        "canonical_url": payload.get("canonical_url", ""),
        "section_anchor": payload.get("section_anchor", ""),
        "source_revision": payload.get("source_revision", ""),
        "repo_id": payload.get("repo_id", ""),
        "checksum": payload.get("checksum", ""),
        "text": payload.get("text", ""),
        "executable_snippets": [
            {
                "snippet_id": s.get("snippet_id", ""),
                "language": s.get("language", ""),
                "code": s.get("code", ""),
                "parent_canonical_url": s.get("parent_canonical_url", ""),
                "parent_section_anchor": s.get("parent_section_anchor", ""),
                "parent_symbol_fqn": s.get("parent_symbol_fqn"),
            }
            for s in snippets
            if isinstance(s, dict)
        ],
    }


def backfill_collection(collection: str, index_name: str, alias_name: str) -> int:
    """Backfill one OpenSearch index from a Qdrant collection."""
    total_count = get_qdrant_collection_count(collection)
    print(f"\n  Backfilling {collection} -> {index_name} ({total_count:,} points)")

    create_opensearch_index(index_name)

    batch: list[dict] = []
    total_indexed = 0
    start_time = time.time()

    for point in scroll_qdrant_collection(collection):
        payload = point.get("payload", {})
        if not payload:
            continue

        doc = payload_to_opensearch_doc(payload)
        batch.append(doc)

        if len(batch) >= BULK_BATCH_SIZE:
            indexed = bulk_index_to_opensearch(index_name, batch)
            total_indexed += indexed
            elapsed = time.time() - start_time
            rate = total_indexed / elapsed if elapsed > 0 else 0
            pct = (total_indexed / total_count * 100) if total_count > 0 else 0
            print(
                f"    Indexed: {total_indexed:,}/{total_count:,} "
                f"({pct:.1f}%) | {rate:.0f} docs/s",
                end="\r",
            )
            batch = []

    # Index remaining batch
    if batch:
        indexed = bulk_index_to_opensearch(index_name, batch)
        total_indexed += indexed

    elapsed = time.time() - start_time
    rate = total_indexed / elapsed if elapsed > 0 else 0
    print(
        f"\n    Done: {total_indexed:,} docs indexed in {elapsed:.1f}s "
        f"({rate:.0f} docs/s)"
    )

    # Re-enable refresh and set alias
    enable_refresh(index_name)
    set_alias(index_name, alias_name)

    return total_indexed


def main() -> None:
    print("=" * 60)
    print("OpenSearch Backfill from Qdrant")
    print("=" * 60)

    print("\nChecking services...")
    if not check_qdrant_health():
        print("ERROR: Qdrant is not available. Aborting.")
        sys.exit(1)
    if not check_opensearch_health():
        print("ERROR: OpenSearch is not available. Aborting.")
        sys.exit(1)

    grand_total = 0
    grand_start = time.time()

    for collection, config in COLLECTION_MAP.items():
        count = backfill_collection(
            collection=collection,
            index_name=config["index"],
            alias_name=config["alias"],
        )
        grand_total += count

    grand_elapsed = time.time() - grand_start

    # Final verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)
    status, body = http_request(
        f"{OPENSEARCH_URL}/_cat/indices?v&s=index", timeout=10.0
    )
    if status == 200 and isinstance(body, str):
        print(body)
    else:
        # cat API returns text, not JSON -- handle both
        for line in str(body).split("\n"):
            if "lex" in line or "health" in line:
                print(f"  {line}")

    print(f"\nTotal: {grand_total:,} documents indexed in {grand_elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
