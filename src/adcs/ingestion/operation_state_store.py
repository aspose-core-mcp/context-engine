"""Filesystem-backed persistence for orchestration operation dataclasses."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")
T = TypeVar("T")

_logger = logging.getLogger(__name__)

# Fields containing heavy nested data (pages, documents, chunk records).
# These are excluded from metadata sidecar files to keep them lightweight.
_HEAVY_RECORD_FIELDS: frozenset[str] = frozenset(
    {"results", "logs", "pages", "canonical_documents", "chunk_records"}
)

# Heavy *sub*-fields nested inside each ``results`` entry. For streaming-mode
# runs these payloads also live on disk in the canonical staging store
# (reachable via ``staging_repository_manifest_path``), so embedding them in the
# operation-state JSON merely duplicates gigabytes of data.
_HEAVY_RESULT_SUBFIELDS: tuple[str, ...] = ("chunk_records", "canonical_documents", "pages")

# When the *estimated serialized size* of the inline chunk records in a single
# operation exceeds this byte budget, the heavy sub-fields above are pruned from
# the *persisted* main JSON file (the in-memory record is never touched). The
# trigger is a byte estimate, not a chunk count: a count threshold does not map
# to file size (short API-reference signature chunks serialize to ~1 KB, fat
# full-page chunks to ~75 KB), so a count cap would either prune small reloadable
# operations or fail to prune huge ones. Only operations far above the
# 50 MB / 10 MB reload-listing caps are pruned, so moderate operations stay fully
# reloadable cross-process; the cap exists purely to prevent the multi-GB
# ``json.dumps`` that would otherwise OOM the process on very large repos (e.g. a
# 76k-file API-reference repository whose state serializes to several GB). Pruned
# operations are large API-reference / docs repos served from the structured
# store / vector index, not from operation-state chunk records.
_MAX_PERSISTED_HEAVY_BYTES: int = 200 * 1024 * 1024  # 200 MB
# Number of chunk records sampled per result to estimate average serialized size.
_HEAVY_BYTES_SAMPLE_SIZE: int = 256


@dataclass(frozen=True, slots=True)
class OperationMetadataEnvelope:
    """Lightweight metadata envelope returned by :meth:`list_metadata_envelopes`.

    Contains only scalar/small fields from the operation record — the heavy
    nested data (``results``, ``logs``) is omitted so that listing hundreds
    of operations never requires reading multi-GB JSON files.
    """

    record_id: str
    saved_at_utc: str
    record_scalars: dict[str, Any]
    source_path: Path


class FileSystemOperationStateStore[T]:
    """Persist operation dataclasses as JSON snapshots under artifacts/runtime-state."""

    def __init__(
        self,
        *,
        namespace: str,
        record_type: type[T],
        workspace_root: Path | None = None,
        storage_root: Path | None = None,
    ) -> None:
        resolved_workspace_root = (
            workspace_root or Path(__file__).resolve().parents[3]
        ).resolve()
        self._record_type = record_type
        self._storage_root = (
            storage_root
            or resolved_workspace_root / "artifacts" / "runtime-state" / namespace
        ).resolve()
        self._storage_root.mkdir(parents=True, exist_ok=True)

    def save(self, *, record_id: str, record: T) -> None:
        target_path = self._path_for_record(record_id)
        serialized_record = _serialize_value(record)
        persisted_record = _prune_heavy_results_for_persistence(
            serialized_record, record_id=record_id
        )
        payload = {
            "record_id": record_id,
            "saved_at_utc": datetime.now(tz=UTC).isoformat(),
            "record": persisted_record,
        }
        temporary_path = target_path.with_suffix(".tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(target_path)
        except FileNotFoundError:
            # Race condition: parent dir was removed or .tmp was consumed by
            # a concurrent writer. Ensure dir exists and retry once.
            self._storage_root.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(target_path)

        # Write lightweight metadata sidecar (scalar fields only + result scope).
        meta_path = target_path.with_suffix(".meta.json")
        record_scalars: dict[str, Any] = (
            {k: v for k, v in serialized_record.items() if k not in _HEAVY_RECORD_FIELDS}
            if isinstance(serialized_record, dict)
            else {}
        )
        # Derive a compact scope summary from results so callers can filter
        # by product/language without loading the full multi-GB JSON file.
        record_scalars["_result_scope"] = _extract_result_scope_summary(
            serialized_record
        )
        meta_payload = {
            "record_id": record_id,
            "saved_at_utc": payload["saved_at_utc"],
            "record": record_scalars,
        }
        meta_tmp = meta_path.with_suffix(".meta.tmp")
        try:
            meta_tmp.write_text(
                json.dumps(meta_payload, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
            meta_tmp.replace(meta_path)
        except FileNotFoundError:
            _logger.warning(
                "Metadata sidecar write failed for %s (concurrent access); skipping.",
                record_id,
            )

    def load(self, record_id: str) -> T | None:
        target_path = self._path_for_record(record_id)
        if not target_path.exists():
            return None
        payload = json.loads(target_path.read_text(encoding="utf-8"))
        return _deserialize_value(payload["record"], self._record_type)

    def list(
        self, *, limit: int = 20, max_file_size_bytes: int = 50 * 1024 * 1024
    ) -> tuple[T, ...]:
        """Return most recent records, skipping files larger than *max_file_size_bytes*."""
        if limit < 1:
            return ()
        records: list[T] = []
        candidate_paths = sorted(
            (
                p
                for p in self._storage_root.glob("*.json")
                if not p.name.endswith(".meta.json")
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate_path in candidate_paths:
            if len(records) >= limit:
                break
            file_size = candidate_path.stat().st_size
            if file_size > max_file_size_bytes:
                _logger.debug(
                    "Skipping oversized state file: %s (%d bytes)",
                    candidate_path.name,
                    file_size,
                )
                continue
            try:
                payload = json.loads(candidate_path.read_text(encoding="utf-8"))
                records.append(_deserialize_value(payload["record"], self._record_type))
            except (json.JSONDecodeError, OSError) as exc:
                _logger.warning("Failed to load state file %s: %s", candidate_path.name, exc)
                continue
        return tuple(records)

    def list_metadata_envelopes(
        self,
        *,
        limit: int = 100,
    ) -> tuple[OperationMetadataEnvelope, ...]:
        """Return lightweight metadata envelopes without loading heavy data.

        Reads ``.meta.json`` sidecar files when available, falling back to the
        full JSON only for files smaller than 10 MB (to avoid blocking on
        multi-GB operation snapshots).
        """
        if limit < 1:
            return ()

        # Discover all main JSON files sorted by mtime (most recent first).
        main_paths = sorted(
            (
                p
                for p in self._storage_root.glob("*.json")
                if not p.name.endswith(".meta.json")
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        envelopes: list[OperationMetadataEnvelope] = []
        _fallback_size_limit = 10 * 1024 * 1024  # 10 MB

        for main_path in main_paths:
            if len(envelopes) >= limit:
                break

            meta_path = main_path.with_suffix(".meta.json")
            try:
                if meta_path.exists():
                    raw = json.loads(meta_path.read_text(encoding="utf-8"))
                elif main_path.stat().st_size <= _fallback_size_limit:
                    # Small file — safe to read fully, extract scalars.
                    full_raw = json.loads(main_path.read_text(encoding="utf-8"))
                    record_data = full_raw.get("record", {})
                    raw = {
                        "record_id": full_raw.get("record_id", ""),
                        "saved_at_utc": full_raw.get("saved_at_utc", ""),
                        "record": {
                            k: v
                            for k, v in record_data.items()
                            if k not in _HEAVY_RECORD_FIELDS
                        }
                        if isinstance(record_data, dict)
                        else {},
                    }
                else:
                    # Large file without sidecar — skip to avoid blocking.
                    _logger.debug(
                        "Skipping large state file without metadata sidecar: %s (%d bytes)",
                        main_path.name,
                        main_path.stat().st_size,
                    )
                    continue
            except (json.JSONDecodeError, OSError) as exc:
                _logger.warning(
                    "Failed to read metadata for %s: %s", main_path.name, exc
                )
                continue

            envelopes.append(
                OperationMetadataEnvelope(
                    record_id=raw.get("record_id", ""),
                    saved_at_utc=raw.get("saved_at_utc", ""),
                    record_scalars=raw.get("record", {}),
                    source_path=main_path,
                )
            )

        return tuple(envelopes)

    def _path_for_record(self, record_id: str) -> Path:
        normalized_record_id = _sanitize_segment(record_id)
        return self._storage_root / f"{normalized_record_id}.json"


def _estimate_inline_chunk_bytes(serialized_record: Any) -> int:
    """Estimate the serialized byte size of all inline chunk records.

    Samples a bounded number of chunks per result (:data:`_HEAVY_BYTES_SAMPLE_SIZE`)
    and extrapolates by count, so the estimate is cheap even for a multi-GB
    payload — it never re-serializes the whole set (which is exactly the
    allocation pruning exists to avoid).
    """
    if not isinstance(serialized_record, dict):
        return 0
    results = serialized_record.get("results")
    if not isinstance(results, list):
        return 0
    total = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        chunks = result.get("chunk_records")
        if not isinstance(chunks, list) or not chunks:
            continue
        count = len(chunks)
        sample_size = min(count, _HEAVY_BYTES_SAMPLE_SIZE)
        step = max(1, count // sample_size)
        sample = chunks[::step][:sample_size]
        if not sample:
            continue
        sample_bytes = len(json.dumps(sample, ensure_ascii=True))
        total += int(sample_bytes / len(sample) * count)
    return total


def _prune_heavy_results_for_persistence(
    serialized_record: Any, *, record_id: str
) -> Any:
    """Return a copy of *serialized_record* safe to ``json.dumps`` to disk.

    When the estimated serialized size of the inline chunk records exceeds
    :data:`_MAX_PERSISTED_HEAVY_BYTES`, the heavy sub-fields
    (:data:`_HEAVY_RESULT_SUBFIELDS`) are replaced with empty lists so the
    persisted JSON stays bounded and the ``json.dumps`` cannot OOM. The
    cardinality fields (``chunk_records_count`` / ``canonical_documents_count``)
    and ``staging_repository_manifest_path`` are preserved. The in-memory record
    handed in by the caller is never mutated — a shallow copy is built. A
    ``_heavy_subfields_pruned`` marker is set so reload-time consumers can detect
    that chunks must be recovered from the canonical staging store rather than
    inline.
    """
    if not isinstance(serialized_record, dict):
        return serialized_record
    estimated_bytes = _estimate_inline_chunk_bytes(serialized_record)
    if estimated_bytes <= _MAX_PERSISTED_HEAVY_BYTES:
        return serialized_record

    results = serialized_record.get("results")
    if not isinstance(results, list):
        return serialized_record

    pruned_results: list[Any] = []
    for result in results:
        if not isinstance(result, dict):
            pruned_results.append(result)
            continue
        pruned_result = dict(result)
        for field_name in _HEAVY_RESULT_SUBFIELDS:
            if field_name in pruned_result:
                pruned_result[field_name] = []
        pruned_result["_heavy_subfields_pruned"] = True
        pruned_results.append(pruned_result)

    pruned_record = dict(serialized_record)
    pruned_record["results"] = pruned_results
    _logger.info(
        "Pruned inline chunk records from persisted operation state '%s' "
        "(~%d MB estimated, exceeds %d MB cap); chunks recoverable from the "
        "canonical staging store via staging_repository_manifest_path.",
        record_id,
        estimated_bytes // (1024 * 1024),
        _MAX_PERSISTED_HEAVY_BYTES // (1024 * 1024),
    )
    return pruned_record


def _extract_result_scope_summary(serialized_record: Any) -> list[dict[str, Any]]:
    """Build a compact scope summary from the serialized ``results`` field.

    Each entry contains ``repo_id``, ``chunk_count``, and unique
    ``product_ids`` / ``programming_languages`` found in the chunk records.
    This lets callers decide whether to load the full multi-GB file.
    """
    if not isinstance(serialized_record, dict):
        return []
    results = serialized_record.get("results")
    if not isinstance(results, list):
        return []
    scope: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        chunks = result.get("chunk_records", [])
        product_ids: set[str] = set()
        languages: set[str] = set()
        for chunk in chunks:
            if isinstance(chunk, dict):
                pid = chunk.get("product_id")
                lang = chunk.get("programming_language")
                if isinstance(pid, str):
                    product_ids.add(pid)
                if isinstance(lang, str):
                    languages.add(lang)
        failed_items = result.get("failed_items", [])
        scope.append(
            {
                "repo_id": result.get("repo_id", ""),
                "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
                "product_ids": sorted(product_ids),
                "programming_languages": sorted(languages),
                "parse_warnings_count": result.get("parse_warnings_count", 0),
                "failed_items_count": (
                    len(failed_items) if isinstance(failed_items, list) else 0
                ),
            }
        )
    return scope


def _sanitize_segment(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "unknown"
    return _SAFE_SEGMENT_RE.sub("-", normalized)


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _serialize_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _serialize_value(item_value) for key, item_value in value.items()
        }
    return value


def _deserialize_value(value: Any, expected_type: Any) -> Any:
    if expected_type in {Any, object}:
        return value

    origin = get_origin(expected_type)
    args = get_args(expected_type)

    if origin is None:
        if value is None:
            return None
        if expected_type is datetime:
            return datetime.fromisoformat(value)
        if isinstance(expected_type, type):
            if issubclass(expected_type, Enum):
                return expected_type(value)
            if is_dataclass(expected_type):
                if not isinstance(value, dict):
                    msg = f"Expected object payload for dataclass `{expected_type}`."
                    raise TypeError(msg)
                type_hints = get_type_hints(expected_type)
                field_values = {
                    field.name: _deserialize_value(
                        value.get(field.name),
                        type_hints.get(field.name, field.type),
                    )
                    for field in fields(expected_type)
                }
                return expected_type(**field_values)
        return value

    if origin in {list, tuple}:
        if not isinstance(value, list):
            msg = f"Expected list payload for `{expected_type}`."
            raise TypeError(msg)
        item_type = args[0] if args else Any
        if origin is tuple:
            if len(args) > 1 and args[1] is not Ellipsis:
                return tuple(
                    _deserialize_value(item_value, item_type)
                    for item_value, item_type in zip(value, args, strict=False)
                )
            return tuple(_deserialize_value(item_value, item_type) for item_value in value)
        return [_deserialize_value(item_value, item_type) for item_value in value]

    if origin in {dict, Mapping}:
        key_type = args[0] if len(args) > 0 else Any
        value_type = args[1] if len(args) > 1 else Any
        if not isinstance(value, dict):
            msg = f"Expected object payload for `{expected_type}`."
            raise TypeError(msg)
        return {
            _deserialize_value(item_key, key_type): _deserialize_value(
                item_value, value_type
            )
            for item_key, item_value in value.items()
        }

    if origin in {UnionType} or str(origin) == "typing.Union":
        if value is None:
            return None
        for union_type in args:
            if union_type is type(None):
                continue
            try:
                return _deserialize_value(value, union_type)
            except (TypeError, ValueError):
                continue
        return value

    return value
