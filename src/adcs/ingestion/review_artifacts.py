"""Filesystem storage for lightweight ingestion review artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adcs.indexing.index_models import IndexPublishSummary
from adcs.ingestion.staging_store import CanonicalStagingScopeSummary

_ARTIFACT_SCHEMA_VERSION = "2.0.0"
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class FileSystemIngestionReviewArtifactStore:
    """Persist lightweight summary + pointers for ingestion review UI."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self._artifact_root = (
            self._workspace_root / "artifacts" / "ingestion-review"
        ).resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)

    def write_artifact(
        self,
        *,
        operation_id: str,
        repo_id: str,
        source_kind: str,
        source_revision: str,
        parsed_pages_count: int,
        parse_warnings_count: int,
        normalized_documents_count: int,
        chunk_records_count: int,
        file_checksums: Mapping[str, str],
        staging_repository_manifest_path: str | None,
        staging_scope_summaries: Sequence[CanonicalStagingScopeSummary],
        staging_replay_used: bool,
        indexing_summary: IndexPublishSummary,
        failed_items: Sequence[Any],
        metadata_quarantine: Any,
        canonical_url_mapping: Any,
    ) -> str:
        """Write one ingestion review artifact and return repository-relative path."""
        normalized_repo_id = _sanitize_segment(repo_id)
        normalized_source_revision = _sanitize_segment(source_revision)
        filename = f"{operation_id}.json"
        relative_path = (
            Path("ingestion-review")
            / normalized_repo_id
            / normalized_source_revision
            / filename
        )
        absolute_path = (
            self._artifact_root
            / normalized_repo_id
            / normalized_source_revision
            / filename
        )
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version": _ARTIFACT_SCHEMA_VERSION,
            "generated_at_utc": datetime.now(tz=UTC).isoformat(),
            "operation_id": operation_id,
            "repo_id": repo_id,
            "source_kind": source_kind,
            "source_revision": source_revision,
            "summary": {
                "parsed_pages_count": parsed_pages_count,
                "parse_warnings_count": parse_warnings_count,
                "normalized_documents_count": normalized_documents_count,
                "chunk_records_count": chunk_records_count,
                "failed_items_count": len(failed_items),
                "source_files_count": len(file_checksums),
            },
            "staging": {
                "repository_manifest_path": staging_repository_manifest_path,
                "scope_manifests": [
                    {
                        "product_id": item.product_id,
                        "programming_language": item.programming_language,
                        "version": item.version,
                        "doc_locale": item.doc_locale,
                        "source_kind": item.source_kind,
                        "manifest_path": item.manifest_path,
                        "documents_count": item.documents_count,
                        "chunk_records_count": item.chunk_records_count,
                    }
                    for item in staging_scope_summaries
                ],
                "replay_used": staging_replay_used,
            },
            "file_checksums": {
                source_path: file_checksums[source_path] for source_path in sorted(file_checksums)
            },
            "failed_items": [
                {
                    "source_path": str(getattr(item, "source_path", "")),
                    "error_code": str(getattr(item, "error_code", "")),
                    "message": str(getattr(item, "message", "")),
                }
                for item in failed_items
            ],
            "indexing_summary": _serialize_indexing_summary(indexing_summary),
            "metadata_quarantine": _serialize_metadata_quarantine(metadata_quarantine),
            "canonical_url_mapping": _serialize_canonical_mapping(canonical_url_mapping),
        }

        temporary_path = absolute_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(absolute_path)
        return relative_path.as_posix()


def _sanitize_segment(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "unknown"
    return _SAFE_SEGMENT_RE.sub("-", normalized)


def _serialize_indexing_summary(summary: IndexPublishSummary) -> dict[str, Any]:
    return {
        "snapshot_id": summary.snapshot_id,
        "product_id": summary.product_id,
        "programming_language": summary.programming_language,
        "version": summary.version,
        "source_kind": summary.source_kind,
        "source_revision": summary.source_revision,
        "indexed_chunks_count": summary.indexed_chunks_count,
        "vector_records_count": summary.vector_records_count,
        "lexical_records_count": summary.lexical_records_count,
        "vector_collection": summary.vector_collection,
        "lexical_index": summary.lexical_index,
        "lexical_alias": summary.lexical_alias,
        "active_snapshot_id": summary.active_snapshot_id,
        "mode": summary.mode.value,
        "dry_run": summary.dry_run,
        "force_full_reindex": summary.force_full_reindex,
        "partial_publish_threshold_pct": summary.partial_publish_threshold_pct,
        "error_ratio": summary.error_ratio,
        "decision": summary.decision.value,
        "publish_blocked_reason": summary.publish_blocked_reason,
        "total_items_count": summary.total_items_count,
        "failed_items_count": summary.failed_items_count,
        "metadata_quarantine_policy": summary.metadata_quarantine_policy,
        "quarantined_items_count": summary.quarantined_items_count,
        "incremental_mode": summary.incremental_mode,
        "incremental_fallback_reason": summary.incremental_fallback_reason,
        "baseline_snapshot_id": summary.baseline_snapshot_id,
        "file_total_count": summary.file_total_count,
        "file_new_count": summary.file_new_count,
        "file_changed_count": summary.file_changed_count,
        "file_unchanged_count": summary.file_unchanged_count,
        "file_removed_count": summary.file_removed_count,
        "chunk_total_count": summary.chunk_total_count,
        "chunk_new_count": summary.chunk_new_count,
        "chunk_changed_count": summary.chunk_changed_count,
        "chunk_unchanged_count": summary.chunk_unchanged_count,
        "chunk_removed_count": summary.chunk_removed_count,
    }


def _serialize_metadata_quarantine(summary: Any) -> dict[str, Any]:
    return {
        "policy_mode": str(getattr(summary, "policy_mode", "")),
        "total_count": int(getattr(summary, "total_count", 0)),
        "reason_counts": [
            {
                "reason_code": str(getattr(item, "reason_code", "")),
                "count": int(getattr(item, "count", 0)),
            }
            for item in getattr(summary, "reason_counts", ())
        ],
        "sample_items": [
            {
                "source_path": str(getattr(item, "source_path", "")),
                "reason_code": str(getattr(item, "reason_code", "")),
                "message": str(getattr(item, "message", "")),
            }
            for item in getattr(summary, "sample_items", ())
        ],
    }


def _serialize_canonical_mapping(summary: Any) -> dict[str, Any]:
    return {
        "contexts": list(getattr(summary, "contexts", ())),
        "remap_entries_count": int(getattr(summary, "remap_entries_count", 0)),
        "remap_applied_count": int(getattr(summary, "remap_applied_count", 0)),
        "remap_conflict_count": int(getattr(summary, "remap_conflict_count", 0)),
        "remap_override_count": int(getattr(summary, "remap_override_count", 0)),
    }
