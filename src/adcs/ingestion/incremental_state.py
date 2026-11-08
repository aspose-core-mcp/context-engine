"""Deterministic incremental ingestion baseline store and diff planner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from adcs.ingestion.chunking import StageDChunkRecord, StageDExecutableSnippet

_BASELINE_SCHEMA_VERSION = 1


class IncrementalBaselineCorruptError(ValueError):
    """Raised when persisted baseline payload cannot be decoded safely."""


@dataclass(frozen=True, slots=True)
class IncrementalFileChecksum:
    """File-level stable checksum tracked in incremental baseline."""

    source_path: str
    checksum: str


@dataclass(frozen=True, slots=True)
class IncrementalBaselineState:
    """Persisted baseline with file checksums and chunk records."""

    repo_id: str
    source_revision: str
    snapshot_id: str | None
    updated_at: datetime
    file_checksums: tuple[IncrementalFileChecksum, ...]
    chunk_records: tuple[StageDChunkRecord, ...]

    def file_checksums_map(self) -> dict[str, str]:
        """Return baseline file checksums as lookup map."""
        return {item.source_path: item.checksum for item in self.file_checksums}


@dataclass(frozen=True, slots=True)
class IncrementalFileDiffPlan:
    """File-level incremental diff outcome."""

    mode: str
    fallback_reason: str | None
    files_to_process: tuple[str, ...]
    files_new: tuple[str, ...]
    files_changed: tuple[str, ...]
    files_unchanged: tuple[str, ...]
    files_removed: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.files_new or self.files_changed or self.files_removed)


@dataclass(frozen=True, slots=True)
class IncrementalChunkDiffPlan:
    """Chunk-level incremental diff outcome."""

    chunk_ids_new: tuple[str, ...]
    chunk_ids_changed: tuple[str, ...]
    chunk_ids_unchanged: tuple[str, ...]
    chunk_ids_removed: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.chunk_ids_new or self.chunk_ids_changed or self.chunk_ids_removed)


class FileSystemIncrementalStateStore:
    """JSON-based baseline persistence for incremental ingestion runs."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._lock = Lock()
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self._artifact_root = (
            self._workspace_root / "artifacts" / "ingestion-incremental"
        ).resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)

    def load(self, *, repo_id: str) -> IncrementalBaselineState | None:
        """Load baseline for one repository, or None when missing."""
        baseline_path = self._baseline_path(repo_id=repo_id)
        if not baseline_path.exists():
            return None
        try:
            raw_payload = baseline_path.read_text(encoding="utf-8")
            payload = json.loads(raw_payload)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Incremental baseline is unreadable for repo_id={repo_id!r}."
            raise IncrementalBaselineCorruptError(msg) from exc
        return _parse_baseline_payload(repo_id=repo_id, payload=payload)

    def save(
        self,
        *,
        repo_id: str,
        source_revision: str,
        snapshot_id: str | None,
        file_checksums: Mapping[str, str],
        chunk_records: Sequence[StageDChunkRecord],
    ) -> IncrementalBaselineState:
        """Persist baseline for one repository with deterministic ordering."""
        normalized_repo_id = repo_id.strip()
        if not normalized_repo_id:
            msg = "repo_id must not be empty."
            raise ValueError(msg)
        normalized_source_revision = source_revision.strip()
        if not normalized_source_revision:
            msg = "source_revision must not be empty."
            raise ValueError(msg)

        updated_at = datetime.now(tz=UTC)
        file_items = tuple(
            IncrementalFileChecksum(source_path=source_path, checksum=file_checksums[source_path])
            for source_path in sorted(file_checksums)
        )
        sorted_chunk_records = tuple(sorted(chunk_records, key=_chunk_sort_key))
        state = IncrementalBaselineState(
            repo_id=normalized_repo_id,
            source_revision=normalized_source_revision,
            snapshot_id=snapshot_id,
            updated_at=updated_at,
            file_checksums=file_items,
            chunk_records=sorted_chunk_records,
        )

        payload = {
            "schema_version": _BASELINE_SCHEMA_VERSION,
            "repo_id": state.repo_id,
            "source_revision": state.source_revision,
            "snapshot_id": state.snapshot_id,
            "updated_at": state.updated_at.isoformat(),
            "file_checksums": [
                {"source_path": item.source_path, "checksum": item.checksum}
                for item in state.file_checksums
            ],
            "chunk_records": [_chunk_to_payload(record) for record in state.chunk_records],
        }

        baseline_path = self._baseline_path(repo_id=normalized_repo_id)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = baseline_path.with_suffix(".tmp")
        encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        with self._lock:
            temporary_path.write_text(encoded_payload, encoding="utf-8")
            temporary_path.replace(baseline_path)
        return state

    def _baseline_path(self, *, repo_id: str) -> Path:
        normalized = repo_id.strip().casefold().replace("/", "__")
        return self._artifact_root / f"{normalized}.json"


def checksum_text(raw_markdown: str) -> str:
    """Return stable content checksum for markdown source text."""
    return hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()


def build_file_diff_plan(
    *,
    current_file_checksums: Mapping[str, str],
    baseline_file_checksums: Mapping[str, str] | None,
    fallback_reason: str | None = None,
) -> IncrementalFileDiffPlan:
    """Build deterministic file-level diff classification."""
    current_paths = sorted(current_file_checksums)
    if baseline_file_checksums is None:
        return IncrementalFileDiffPlan(
            mode="full_reindex",
            fallback_reason=fallback_reason or "baseline_missing",
            files_to_process=tuple(current_paths),
            files_new=tuple(current_paths),
            files_changed=(),
            files_unchanged=(),
            files_removed=(),
        )

    baseline_paths = set(baseline_file_checksums)
    current_paths_set = set(current_paths)
    files_new = tuple(sorted(current_paths_set - baseline_paths))
    files_removed = tuple(sorted(baseline_paths - current_paths_set))
    common_paths = sorted(current_paths_set.intersection(baseline_paths))

    changed_paths: list[str] = []
    unchanged_paths: list[str] = []
    for source_path in common_paths:
        if current_file_checksums[source_path] == baseline_file_checksums[source_path]:
            unchanged_paths.append(source_path)
        else:
            changed_paths.append(source_path)

    return IncrementalFileDiffPlan(
        mode="incremental",
        fallback_reason=None,
        files_to_process=tuple(sorted((*files_new, *changed_paths))),
        files_new=files_new,
        files_changed=tuple(changed_paths),
        files_unchanged=tuple(unchanged_paths),
        files_removed=files_removed,
    )


def build_chunk_diff_plan(
    *,
    previous_chunk_records: Sequence[StageDChunkRecord],
    current_chunk_records: Sequence[StageDChunkRecord],
) -> IncrementalChunkDiffPlan:
    """Build deterministic chunk-level diff classification."""
    previous_grouped = _group_chunks_by_identity(previous_chunk_records)
    current_grouped = _group_chunks_by_identity(current_chunk_records)
    identities = tuple(sorted(set(previous_grouped).union(current_grouped)))

    new_ids: list[str] = []
    changed_ids: list[str] = []
    unchanged_ids: list[str] = []
    removed_ids: list[str] = []

    for identity in identities:
        previous_items = previous_grouped.get(identity, ())
        current_items = current_grouped.get(identity, ())
        pair_count = min(len(previous_items), len(current_items))

        for index in range(pair_count):
            previous = previous_items[index]
            current = current_items[index]
            if previous.checksum == current.checksum:
                unchanged_ids.append(current.chunk_id)
            else:
                changed_ids.append(current.chunk_id)
                removed_ids.append(previous.chunk_id)

        if len(current_items) > pair_count:
            new_ids.extend(item.chunk_id for item in current_items[pair_count:])
        if len(previous_items) > pair_count:
            removed_ids.extend(item.chunk_id for item in previous_items[pair_count:])

    return IncrementalChunkDiffPlan(
        chunk_ids_new=tuple(sorted(new_ids)),
        chunk_ids_changed=tuple(sorted(changed_ids)),
        chunk_ids_unchanged=tuple(sorted(unchanged_ids)),
        chunk_ids_removed=tuple(sorted(removed_ids)),
    )


def _group_chunks_by_identity(
    records: Sequence[StageDChunkRecord],
) -> dict[tuple[str, str, str, str], tuple[StageDChunkRecord, ...]]:
    grouped: dict[tuple[str, str, str, str], list[StageDChunkRecord]] = {}
    for record in records:
        identity = (
            record.source_path,
            record.section_anchor,
            record.chunk_type,
            "/".join(record.section_path),
        )
        grouped.setdefault(identity, []).append(record)
    return {
        identity: tuple(sorted(items, key=lambda item: item.chunk_id))
        for identity, items in grouped.items()
    }


def _chunk_sort_key(record: StageDChunkRecord) -> tuple[str, str, str]:
    return (record.source_path, record.section_anchor, record.chunk_id)


def _chunk_to_payload(record: StageDChunkRecord) -> dict[str, object]:
    return {
        "chunk_id": record.chunk_id,
        "repo_id": record.repo_id,
        "product_id": record.product_id,
        "product_family": record.product_family,
        "programming_language": record.programming_language,
        "version": record.version,
        "source_kind": record.source_kind,
        "doc_locale": record.doc_locale,
        "doc_type": record.doc_type,
        "symbol_fqn": record.symbol_fqn,
        "title": record.title,
        "section_path": list(record.section_path),
        "canonical_url": record.canonical_url,
        "section_anchor": record.section_anchor,
        "source_path": record.source_path,
        "source_revision": record.source_revision,
        "is_deprecated": record.is_deprecated,
        "has_code_example": record.has_code_example,
        "chunk_type": record.chunk_type,
        "text": record.text,
        "tokens": record.tokens,
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


def _parse_baseline_payload(*, repo_id: str, payload: object) -> IncrementalBaselineState:
    if not isinstance(payload, Mapping):
        msg = f"Incremental baseline payload is invalid for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)

    schema_version = payload.get("schema_version")
    if schema_version != _BASELINE_SCHEMA_VERSION:
        msg = (
            "Incremental baseline schema version mismatch for "
            f"repo_id={repo_id!r}: expected={_BASELINE_SCHEMA_VERSION}, actual={schema_version!r}."
        )
        raise IncrementalBaselineCorruptError(msg)

    stored_repo_id = payload.get("repo_id")
    source_revision = payload.get("source_revision")
    snapshot_id = payload.get("snapshot_id")
    updated_at_raw = payload.get("updated_at")
    if not isinstance(stored_repo_id, str) or not stored_repo_id.strip():
        msg = f"Incremental baseline repo_id is missing for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    if not isinstance(source_revision, str) or not source_revision.strip():
        msg = f"Incremental baseline source_revision is missing for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    if snapshot_id is not None and not isinstance(snapshot_id, str):
        msg = f"Incremental baseline snapshot_id is invalid for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    if not isinstance(updated_at_raw, str):
        msg = f"Incremental baseline updated_at is missing for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    try:
        updated_at = datetime.fromisoformat(updated_at_raw)
    except ValueError as exc:
        msg = f"Incremental baseline updated_at is invalid for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg) from exc

    raw_file_checksums = payload.get("file_checksums")
    if not isinstance(raw_file_checksums, list):
        msg = f"Incremental baseline file_checksums is invalid for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    file_checksums: list[IncrementalFileChecksum] = []
    for item in raw_file_checksums:
        if not isinstance(item, Mapping):
            msg = f"Incremental baseline file checksum entry is invalid for repo_id={repo_id!r}."
            raise IncrementalBaselineCorruptError(msg)
        source_path = item.get("source_path")
        checksum = item.get("checksum")
        if (
            not isinstance(source_path, str)
            or not source_path.strip()
            or not isinstance(checksum, str)
            or not checksum.strip()
        ):
            msg = f"Incremental baseline file checksum entry is incomplete for repo_id={repo_id!r}."
            raise IncrementalBaselineCorruptError(msg)
        file_checksums.append(IncrementalFileChecksum(source_path=source_path, checksum=checksum))

    raw_chunk_records = payload.get("chunk_records")
    if not isinstance(raw_chunk_records, list):
        msg = f"Incremental baseline chunk_records is invalid for repo_id={repo_id!r}."
        raise IncrementalBaselineCorruptError(msg)
    chunk_records: list[StageDChunkRecord] = []
    for item in raw_chunk_records:
        if not isinstance(item, Mapping):
            msg = f"Incremental baseline chunk entry is invalid for repo_id={repo_id!r}."
            raise IncrementalBaselineCorruptError(msg)
        try:
            section_path = item.get("section_path")
            if not isinstance(section_path, list):
                raise TypeError
            chunk_records.append(
                StageDChunkRecord(
                    chunk_id=_required_non_empty_str(item, "chunk_id"),
                    repo_id=_required_non_empty_str(item, "repo_id"),
                    product_id=_required_non_empty_str(item, "product_id"),
                    product_family=_required_non_empty_str(item, "product_family"),
                    programming_language=_required_non_empty_str(item, "programming_language"),
                    version=_required_non_empty_str(item, "version"),
                    source_kind=_required_non_empty_str(item, "source_kind"),
                    doc_locale=_required_non_empty_str(item, "doc_locale"),
                    doc_type=_required_non_empty_str(item, "doc_type"),
                    symbol_fqn=_nullable_str(item.get("symbol_fqn")),
                    title=_required_non_empty_str(item, "title"),
                    section_path=tuple(
                        _required_non_empty_str_from_raw(part) for part in section_path
                    ),
                    canonical_url=_required_non_empty_str(item, "canonical_url"),
                    section_anchor=_required_non_empty_str(item, "section_anchor"),
                    source_path=_required_non_empty_str(item, "source_path"),
                    source_revision=_required_non_empty_str(item, "source_revision"),
                    is_deprecated=bool(item.get("is_deprecated")),
                    has_code_example=bool(item.get("has_code_example")),
                    chunk_type=_required_non_empty_str(item, "chunk_type"),
                    text=_required_non_empty_str(item, "text"),
                    tokens=int(item.get("tokens", 0)),
                    checksum=_required_non_empty_str(item, "checksum"),
                    executable_snippets=_parse_executable_snippets(
                        item.get("executable_snippets")
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            msg = f"Incremental baseline chunk entry is malformed for repo_id={repo_id!r}."
            raise IncrementalBaselineCorruptError(msg) from exc

    return IncrementalBaselineState(
        repo_id=stored_repo_id,
        source_revision=source_revision,
        snapshot_id=snapshot_id,
        updated_at=updated_at,
        file_checksums=tuple(sorted(file_checksums, key=lambda item: item.source_path)),
        chunk_records=tuple(sorted(chunk_records, key=_chunk_sort_key)),
    )


def _required_non_empty_str(payload: Mapping[str, object], field: str) -> str:
    raw_value = payload.get(field)
    return _required_non_empty_str_from_raw(raw_value)


def _required_non_empty_str_from_raw(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        raise TypeError
    value = raw_value.strip()
    if not value:
        raise ValueError
    return value


def _nullable_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise TypeError
    normalized = raw_value.strip()
    return normalized if normalized else None


def _parse_executable_snippets(raw_value: object) -> tuple[StageDExecutableSnippet, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise TypeError
    snippets: list[StageDExecutableSnippet] = []
    for item in raw_value:
        if not isinstance(item, Mapping):
            raise TypeError
        snippets.append(
            StageDExecutableSnippet(
                snippet_id=_required_non_empty_str(item, "snippet_id"),
                language=_required_non_empty_str(item, "language"),
                code=_required_non_empty_str(item, "code"),
                parent_canonical_url=_required_non_empty_str(item, "parent_canonical_url"),
                parent_section_anchor=_required_non_empty_str(item, "parent_section_anchor"),
                parent_symbol_fqn=_nullable_str(item.get("parent_symbol_fqn")),
            )
        )
    return tuple(snippets)
