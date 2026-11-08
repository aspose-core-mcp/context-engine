"""Lexical-lane index writer contracts and in-memory adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from threading import Lock
from typing import Protocol
from urllib import error, request

from adcs.indexing.index_models import LexicalIndexRecord, LexicalWriteResult
from adcs.indexing.topology_policy import IndexTopologyPolicy


class LexicalIndexWriter(Protocol):
    """Contract for lexical lane writers (OpenSearch-style document model)."""

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[LexicalIndexRecord],
    ) -> LexicalWriteResult:
        """Persist lexical records for one snapshot (without alias switch)."""

    def switch_alias(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        superseded_snapshot_id: str | None = None,
    ) -> None:
        """Point the active alias at the given scope's snapshot index, additively.

        The alias is SHARED across every per-scope snapshot index, so the switch
        must only ADD the new index and (optionally) remove the same scope's
        ``superseded_snapshot_id`` index — never drop other scopes. Must be
        called only after ALL batches have been written for a snapshot.
        """


class InMemoryLexicalIndexWriter:
    """In-memory lexical index writer for development and tests."""

    def __init__(self, *, topology_policy: IndexTopologyPolicy | None = None) -> None:
        del topology_policy
        self._lock = Lock()
        self._records_by_snapshot: dict[str, tuple[LexicalIndexRecord, ...]] = {}
        self._index_by_snapshot: dict[str, str] = {}
        self._alias_by_snapshot: dict[str, str] = {}

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[LexicalIndexRecord],
    ) -> LexicalWriteResult:
        index_name = f"{source_kind}_lex_v1_{snapshot_id}"
        alias_name = f"{source_kind}_lex_v1_active"
        with self._lock:
            self._records_by_snapshot[snapshot_id] = tuple(records)
            self._index_by_snapshot[snapshot_id] = index_name
            self._alias_by_snapshot[snapshot_id] = alias_name
        return LexicalWriteResult(
            index_name=index_name,
            alias_name=alias_name,
            written_count=len(records),
        )

    def switch_alias(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        superseded_snapshot_id: str | None = None,
    ) -> None:
        del superseded_snapshot_id  # in-memory model stores one entry per snapshot
        index_name = f"{source_kind}_lex_v1_{snapshot_id}"
        alias_name = f"{source_kind}_lex_v1_active"
        with self._lock:
            self._index_by_snapshot[snapshot_id] = index_name
            self._alias_by_snapshot[snapshot_id] = alias_name

    def get_snapshot_records(self, snapshot_id: str) -> tuple[LexicalIndexRecord, ...]:
        with self._lock:
            return self._records_by_snapshot.get(snapshot_id, ())

    def get_index_name(self, snapshot_id: str) -> str | None:
        with self._lock:
            return self._index_by_snapshot.get(snapshot_id)

    def get_alias_name(self, snapshot_id: str) -> str | None:
        with self._lock:
            return self._alias_by_snapshot.get(snapshot_id)


class OpenSearchLexicalIndexWriter:
    """OpenSearch-backed lexical index writer for production-oriented local runtime."""

    def __init__(
        self,
        *,
        opensearch_url: str,
        timeout_seconds: float = 5.0,
        topology_policy: IndexTopologyPolicy | None = None,
    ) -> None:
        self._opensearch_url = opensearch_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._topology_policy = topology_policy

    def write_records(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        records: Sequence[LexicalIndexRecord],
    ) -> LexicalWriteResult:
        index_name = f"{source_kind}_lex_v1_{snapshot_id}"
        alias_name = f"{source_kind}_lex_v1_active"
        self._ensure_index(index_name=index_name)
        if records:
            self._bulk_index(index_name=index_name, records=records)
        return LexicalWriteResult(
            index_name=index_name,
            alias_name=alias_name,
            written_count=len(records),
        )

    def switch_alias(
        self,
        *,
        source_kind: str,
        snapshot_id: str,
        superseded_snapshot_id: str | None = None,
    ) -> None:
        """Point the active alias at this scope's index, additively.

        Adds the new index and (optionally) removes the same scope's
        ``superseded_snapshot_id`` index — never drops other scopes from the
        shared alias. Must be called only after ALL batches are written.
        """
        index_name = f"{source_kind}_lex_v1_{snapshot_id}"
        alias_name = f"{source_kind}_lex_v1_active"
        superseded_index = (
            f"{source_kind}_lex_v1_{superseded_snapshot_id}"
            if superseded_snapshot_id
            else None
        )
        self._switch_alias(
            index_name=index_name,
            alias_name=alias_name,
            superseded_index=superseded_index,
        )

    def _ensure_index(self, *, index_name: str) -> None:
        status_code, body = _request_json(
            url=f"{self._opensearch_url}/{index_name}",
            method="GET",
            payload=None,
            timeout_seconds=self._timeout_seconds,
            content_type="application/json",
        )
        if status_code == 200:
            return
        if status_code != 404:
            msg = f"OpenSearch index lookup failed (status={status_code}, body={body!r})."
            raise RuntimeError(msg)

        index_settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "1s",
        }
        if self._topology_policy is not None:
            index_settings = {
                "number_of_shards": self._topology_policy.opensearch.number_of_shards,
                "number_of_replicas": self._topology_policy.opensearch.number_of_replicas,
                "refresh_interval": self._topology_policy.opensearch.refresh_interval,
            }

        create_status, create_body = _request_json(
            url=f"{self._opensearch_url}/{index_name}",
            method="PUT",
            payload={
                "settings": {"index": index_settings},
                "mappings": {
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
                },
            },
            timeout_seconds=self._timeout_seconds,
            content_type="application/json",
        )
        if create_status not in {200}:
            msg = (
                f"OpenSearch index create failed (status={create_status}, "
                f"body={create_body!r})."
            )
            raise RuntimeError(msg)

    _BULK_BATCH_SIZE = 200

    def _bulk_index(self, *, index_name: str, records: Sequence[LexicalIndexRecord]) -> None:
        for start in range(0, len(records), self._BULK_BATCH_SIZE):
            batch = records[start : start + self._BULK_BATCH_SIZE]
            self._bulk_index_batch(index_name=index_name, records=batch)

    def _bulk_index_batch(
        self, *, index_name: str, records: Sequence[LexicalIndexRecord]
    ) -> None:
        lines: list[str] = []
        for record in records:
            lines.append(json.dumps({"index": {"_index": index_name, "_id": record.chunk_id}}))
            lines.append(
                json.dumps(
                    {
                        "chunk_id": record.chunk_id,
                        "text": record.text,
                        "snapshot_id": record.snapshot_id,
                        "product_id": record.product_id,
                        "product_family": record.product_family,
                        "programming_language": record.programming_language,
                        "version": record.version,
                        "source_kind": record.source_kind,
                        "doc_type": record.doc_type,
                        "doc_locale": record.doc_locale,
                        "symbol_fqn": record.symbol_fqn,
                        "title": record.title,
                        "canonical_url": record.canonical_url,
                        "section_anchor": record.section_anchor,
                        "source_revision": record.source_revision,
                        "repo_id": record.repo_id,
                        "checksum": record.checksum,
                        "executable_snippets": [
                            {
                                "snippet_id": snippet.snippet_id,
                                "language": snippet.language,
                                "code": snippet.code,
                                "parent_canonical_url": snippet.parent_canonical_url,
                                "parent_section_anchor": snippet.parent_section_anchor,
                                "parent_symbol_fqn": snippet.parent_symbol_fqn,
                            }
                            for snippet in record.executable_snippets
                        ],
                    }
                )
            )
        bulk_payload = "\n".join(lines) + "\n"
        status_code, body = _request_text(
            url=f"{self._opensearch_url}/_bulk?refresh=true",
            method="POST",
            payload=bulk_payload.encode("utf-8"),
            timeout_seconds=max(self._timeout_seconds, 30.0),
            content_type="application/x-ndjson",
        )
        if status_code not in {200}:
            msg = f"OpenSearch bulk index failed (status={status_code}, body={body!r})."
            raise RuntimeError(msg)

        decoded = _decode_json(body)
        if isinstance(decoded, dict) and bool(decoded.get("errors")):
            msg = f"OpenSearch bulk index response contains errors: {decoded!r}"
            raise RuntimeError(msg)

    def _switch_alias(
        self, *, index_name: str, alias_name: str, superseded_index: str | None = None
    ) -> None:
        # Additive: add this scope's index and, if it is still aliased, remove the
        # same scope's superseded index. Other scopes' indexes are left untouched
        # so a single-scope publish never drops other products from the alias.
        effective_superseded: str | None = None
        if superseded_index:
            existing_status, existing_body = _request_json(
                url=f"{self._opensearch_url}/_alias/{alias_name}",
                method="GET",
                payload=None,
                timeout_seconds=self._timeout_seconds,
                content_type="application/json",
            )
            if (
                existing_status == 200
                and isinstance(existing_body, dict)
                and superseded_index in existing_body
            ):
                effective_superseded = superseded_index
        actions = _build_alias_actions(
            index_name=index_name,
            alias_name=alias_name,
            superseded_index=effective_superseded,
        )
        status_code, body = _request_json(
            url=f"{self._opensearch_url}/_aliases",
            method="POST",
            payload={"actions": actions},
            timeout_seconds=self._timeout_seconds,
            content_type="application/json",
        )
        if status_code not in {200}:
            msg = f"OpenSearch alias switch failed (status={status_code}, body={body!r})."
            raise RuntimeError(msg)


def _build_alias_actions(
    *,
    index_name: str,
    alias_name: str,
    superseded_index: str | None = None,
) -> list[dict[str, object]]:
    """Build the additive `_aliases` actions for a scope's alias switch.

    Returns ``[remove superseded?] + [add new]`` — only the same scope's
    superseded index is removed (if provided and distinct); other scopes' indexes
    under the shared alias are never touched.
    """
    actions: list[dict[str, object]] = []
    if superseded_index and superseded_index != index_name:
        actions.append({"remove": {"index": superseded_index, "alias": alias_name}})
    actions.append({"add": {"index": index_name, "alias": alias_name}})
    return actions


def _request_json(
    *,
    url: str,
    method: str,
    payload: dict[str, object] | None,
    timeout_seconds: float,
    content_type: str,
) -> tuple[int, object]:
    body: bytes | None = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = content_type
    return _request_bytes(
        url=url,
        method=method,
        payload=body,
        timeout_seconds=timeout_seconds,
        headers=headers,
    )


def _request_text(
    *,
    url: str,
    method: str,
    payload: bytes | None,
    timeout_seconds: float,
    content_type: str,
) -> tuple[int, str]:
    status_code, body = _request_bytes(
        url=url,
        method=method,
        payload=payload,
        timeout_seconds=timeout_seconds,
        headers={"Content-Type": content_type},
    )
    if isinstance(body, str):
        return status_code, body
    return status_code, json.dumps(body)


def _request_bytes(
    *,
    url: str,
    method: str,
    payload: bytes | None,
    timeout_seconds: float,
    headers: dict[str, str],
) -> tuple[int, object]:
    req = request.Request(url=url, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            return response.status, _decode_json(raw_body)
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _decode_json(raw_body)
    except error.URLError as exc:
        msg = f"OpenSearch request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _decode_json(raw_body: str) -> object:
    if not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body
