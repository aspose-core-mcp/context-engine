from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from adcs.indexing.index_models import IngestionRunMode
from adcs.ingestion.metadata_quarantine import MetadataQuarantineReasonCode
from adcs.ingestion.normalized_document import resolve_git_submodule_revision
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationStatus,
)
from adcs.ingestion.staging_store import StagingSnapshotTier
from adcs.ops import CriticalEventType, InMemoryCriticalEventStore


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def _make_registry_payload() -> dict[str, Any]:
    return {
        "source_roots": [
            {"root_id": "docs-root", "source_kind": "docs", "path": "source-repo-docs"},
        ],
        "repositories": [
            {
                "repo_id": "aspose.ocr.docs",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "docs",
                "git": {
                    "url": "https://example.com/aspose.ocr.docs.git",
                    "submodule_path": "source-repo-docs/Aspose.OCR",
                    "default_branch": "main",
                },
                "layout_detection": {
                    "layout_type": "doc_locale/programming_language/content",
                },
            }
        ],
    }


def _write_docs_pages(tmp_path: Path) -> Path:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net" / "getting-started"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "_index.md").write_text(
        """---
title: Getting Started
---
## Intro
Welcome.
""",
        encoding="utf-8",
    )
    (repo_root / "install.md").write_text(
        """---
title: Install
---
```bash
pip install aspose-ocr-python-net
```
""",
        encoding="utf-8",
    )
    return repo_root


def _write_page(repo_root: Path, relative_path: str, content: str) -> None:
    target_path = repo_root / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "-C", str(repo_root), "init", "-b", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "tests@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Test Suite"],
        check=True,
    )
    _git_commit_all(repo_root, "initial import")


def _git_commit_all(repo_root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", message], check=True)


def test_source_hugo_normalization_orchestrator_parses_repo_by_layout_metadata(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())

    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert operation.conversion_backend == "deterministic"
    assert operation.prompt_registry_version == "disabled"
    assert operation.prompt_experiment_id == "conversion.default.v1"
    assert operation.repo_ids == ("aspose.ocr.docs",)
    assert operation.results
    result = operation.results[0]
    assert result.repo_id == "aspose.ocr.docs"
    assert result.parsed_pages_count == 2
    assert result.parse_warnings_count == 0
    # The streaming path leaves these tuples empty
    # — the docs themselves are persisted to staging and accessible via
    # `FileSystemCanonicalStagingStore.iter_canonical_documents(...)`. The
    # cardinality is preserved through `parsed_pages_count`.
    assert result.canonical_documents == ()
    assert result.pages == ()
    assert result.chunk_records
    assert result.indexing_summary.snapshot_id == "snap-00000001"
    assert result.indexing_summary.vector_records_count == len(result.chunk_records)
    assert result.indexing_summary.lexical_records_count == len(result.chunk_records)
    assert result.indexing_summary.active_snapshot_id == "snap-00000001"
    assert result.indexing_summary.mode.value == "publish"
    assert result.indexing_summary.decision.value == "full_publish"
    assert result.indexing_summary.error_ratio == 0.0
    assert result.indexing_summary.total_items_count == 2
    assert result.indexing_summary.failed_items_count == 0
    assert result.indexing_summary.event_summary.event_types == ()
    assert result.indexing_summary.notification_summary.sent_count == 0
    assert result.prompt_evaluation.registry_version == "disabled"
    assert result.prompt_evaluation.total_assigned_count == 2
    assert result.prompt_evaluation.failed_count == 0
    assert result.review_artifact_path is not None
    artifact_path = tmp_path / "artifacts" / result.review_artifact_path
    assert artifact_path.exists()
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["repo_id"] == "aspose.ocr.docs"
    assert artifact_payload["summary"]["chunk_records_count"] == len(result.chunk_records)
    assert artifact_payload["summary"]["parse_warnings_count"] == 0
    assert "pages" not in artifact_payload
    assert "normalized_documents" not in artifact_payload
    assert "chunk_records" not in artifact_payload
    assert result.staging_repository_manifest_path is not None
    staging_manifest_path = tmp_path / result.staging_repository_manifest_path
    assert staging_manifest_path.exists()
    assert result.staging_scopes
    assert result.staging_scopes[0].manifest_path

    # Stream the documents back from the on-disk staging snapshot to verify
    # they were persisted correctly under the streaming-writer path.
    # Parser-level concerns (heading extraction, code-block language
    # detection) are covered by the dedicated `test_hugo_parser.py` —
    # here we only check that the orchestrator's downstream artefact is
    # complete and structurally correct.
    from adcs.ingestion.staging_store import (
        FileSystemCanonicalStagingStore,
        StagingSnapshotTier,
    )
    streaming_store = FileSystemCanonicalStagingStore(workspace_root=tmp_path)
    streamed_documents = {
        document.document.source_path: document
        for document in streaming_store.iter_canonical_documents(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_revision="revision-abc123",
            snapshot_tier=StagingSnapshotTier.PUBLISH,
        )
    }
    index_path = "source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md"
    install_path = "source-repo-docs/Aspose.OCR/english/net/getting-started/install.md"
    assert set(streamed_documents) == {index_path, install_path}
    assert streamed_documents[index_path].document.source_revision == "revision-abc123"
    assert streamed_documents[install_path].chunks
    assert streamed_documents[install_path].chunks[0].citations
    first_chunk_record = result.chunk_records[0]
    assert first_chunk_record.repo_id == "aspose.ocr.docs"
    assert first_chunk_record.source_kind == "docs"
    assert first_chunk_record.canonical_url
    assert first_chunk_record.section_anchor.startswith("#")
    assert first_chunk_record.tokens > 0
    assert first_chunk_record.checksum
    snippet_records = [
        record for record in result.chunk_records if record.executable_snippets
    ]
    assert snippet_records
    snippet = snippet_records[0].executable_snippets[0]
    assert snippet.language == "bash"
    assert snippet.parent_canonical_url == snippet_records[0].canonical_url
    assert any(
        "task=conversion backend=deterministic" in log_line.line for log_line in operation.logs
    )
    assert any(
        log_line.line.startswith("[prompt_registry]") for log_line in operation.logs
    )


def test_source_hugo_normalization_operation_state_persists_across_service_instances(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())

    queued_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    queued_operation = queued_service.run(
        repo_ids=("aspose.ocr.docs",),
        execute_immediately=False,
    )

    assert queued_operation.status is SourceHugoNormalizationStatus.QUEUED
    assert queued_operation.results == ()

    worker_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    restored_queued_operation = worker_service.get_operation(queued_operation.operation_id)
    assert restored_queued_operation.status is SourceHugoNormalizationStatus.QUEUED

    completed_operation = worker_service.execute_operation(
        operation_id=queued_operation.operation_id
    )
    assert completed_operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert completed_operation.results

    observer_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    restored_completed_operation = observer_service.get_operation(
        queued_operation.operation_id
    )
    assert restored_completed_operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert restored_completed_operation.results[0].parsed_pages_count == 2


def test_source_hugo_normalization_orchestrator_blocks_publish_on_fatal_front_matter_error(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "_index.md").write_text(
        """---
title: Broken Front Matter
## Missing closing delimiter
""",
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())

    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert len(operation.results) == 1
    result = operation.results[0]
    assert len(result.failed_items) == 1
    assert result.failed_items[0].error_code == "HUGO_FRONT_MATTER_UNCLOSED"
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.snapshot_id == ""
    assert result.indexing_summary.vector_records_count == 0
    assert result.indexing_summary.lexical_records_count == 0
    assert result.indexing_summary.error_ratio == 1.0
    assert result.indexing_summary.publish_blocked_reason == "publish_safety_gate"
    assert result.indexing_summary.publish_safety_gate.blocking is True
    assert result.indexing_summary.publish_safety_gate.reason_codes == (
        "critical_parser_errors_present",
        "empty_usable_scope",
        "usable_chunk_coverage_below_threshold",
    )
    assert result.indexing_summary.conversion_gate.phase == "mvp"
    assert result.indexing_summary.conversion_gate.blocking is False
    assert result.indexing_summary.event_summary.event_types == ("publish_blocked",)
    assert result.indexing_summary.notification_summary.sent_count == 1


def test_source_hugo_normalization_preprod_blocks_publish_on_conversion_gate(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "_index.md").write_text(
        """---
title: Overview
---
## Intro
Valid content.
""",
        encoding="utf-8",
    )
    (repo_root / "broken.md").write_text(
        """---
title: Broken
## Missing closing delimiter
""",
        encoding="utf-8",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        quality_gate_phase="preprod",
    )

    operation = service.run(repo_ids=("aspose.ocr.docs",))
    result = operation.results[0]

    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.publish_blocked_reason == "publish_safety_gate"
    assert result.indexing_summary.publish_safety_gate.blocking is True
    assert "critical_parser_errors_present" in (
        result.indexing_summary.publish_safety_gate.reason_codes
    )
    assert result.indexing_summary.conversion_gate.phase == "preprod"
    assert result.indexing_summary.conversion_gate.enforcement_mode == "hard_block"
    assert result.indexing_summary.conversion_gate.blocking is True
    assert "parse_coverage_below_threshold" in result.indexing_summary.conversion_gate.reason_codes


def test_source_hugo_normalization_orchestrator_marks_no_changes_and_reuses_baseline(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    first_result = first_operation.results[0]
    assert first_result.indexing_summary.incremental_mode == "full_reindex"
    assert first_result.indexing_summary.incremental_detection_strategy == "checksum_diff"
    assert first_result.indexing_summary.incremental_fallback_reason == "baseline_missing"
    assert first_result.indexing_summary.file_new_count == 2
    assert first_result.indexing_summary.file_changed_count == 0
    assert first_result.indexing_summary.file_unchanged_count == 0
    assert first_result.indexing_summary.file_removed_count == 0
    first_snapshot_id = first_result.indexing_summary.snapshot_id
    assert first_snapshot_id == "snap-00000001"

    second_operation = service.run(repo_ids=("aspose.ocr.docs",))
    second_result = second_operation.results[0]
    assert second_result.parsed_pages_count == 0
    assert second_result.indexing_summary.decision.value == "no_changes"
    assert second_result.indexing_summary.incremental_mode == "incremental"
    assert second_result.indexing_summary.incremental_detection_strategy == "checksum_diff"
    assert second_result.indexing_summary.incremental_fallback_reason is None
    assert second_result.indexing_summary.baseline_snapshot_id == first_snapshot_id
    assert second_result.indexing_summary.active_snapshot_id == first_snapshot_id
    assert second_result.indexing_summary.file_total_count == 2
    assert second_result.indexing_summary.file_new_count == 0
    assert second_result.indexing_summary.file_changed_count == 0
    assert second_result.indexing_summary.file_unchanged_count == 2
    assert second_result.indexing_summary.file_removed_count == 0
    assert second_result.indexing_summary.chunk_new_count == 0
    assert second_result.indexing_summary.chunk_changed_count == 0
    assert second_result.indexing_summary.chunk_removed_count == 0
    assert second_result.indexing_summary.chunk_unchanged_count == len(second_result.chunk_records)
    assert second_result.indexing_summary.snapshot_id == ""


def test_source_hugo_normalization_orchestrator_reprocesses_only_changed_files(
    tmp_path: Path,
) -> None:
    repo_root = _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    first_snapshot_id = first_operation.results[0].indexing_summary.snapshot_id
    install_path = repo_root / "install.md"
    install_path.write_text(
        """---
title: Install
---
```bash
pip install aspose-ocr-python-net
```
Run OCR using new flags.
""",
        encoding="utf-8",
    )

    second_operation = service.run(repo_ids=("aspose.ocr.docs",))
    second_result = second_operation.results[0]
    assert second_result.indexing_summary.decision.value == "full_publish"
    assert second_result.indexing_summary.incremental_mode == "incremental"
    assert second_result.indexing_summary.incremental_detection_strategy == "checksum_diff"
    assert second_result.indexing_summary.incremental_fallback_reason is None
    assert second_result.indexing_summary.file_total_count == 2
    assert second_result.indexing_summary.file_new_count == 0
    assert second_result.indexing_summary.file_changed_count == 1
    assert second_result.indexing_summary.file_unchanged_count == 1
    assert second_result.indexing_summary.file_removed_count == 0
    assert second_result.parsed_pages_count == 1
    changed_or_new_chunks = (
        second_result.indexing_summary.chunk_changed_count
        + second_result.indexing_summary.chunk_new_count
    )
    assert changed_or_new_chunks >= 1
    assert second_result.indexing_summary.chunk_unchanged_count >= 1
    assert second_result.indexing_summary.snapshot_id != first_snapshot_id


def test_source_hugo_normalization_orchestrator_tracks_removed_files_incrementally(
    tmp_path: Path,
) -> None:
    repo_root = _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    service.run(repo_ids=("aspose.ocr.docs",))
    (repo_root / "install.md").unlink()

    operation = service.run(repo_ids=("aspose.ocr.docs",))
    result = operation.results[0]
    assert result.indexing_summary.incremental_mode == "incremental"
    assert result.indexing_summary.incremental_detection_strategy == "checksum_diff"
    assert result.indexing_summary.file_total_count == 1
    assert result.indexing_summary.file_new_count == 0
    assert result.indexing_summary.file_changed_count == 0
    assert result.indexing_summary.file_unchanged_count == 1
    assert result.indexing_summary.file_removed_count == 1
    assert result.indexing_summary.chunk_removed_count >= 1


def test_source_hugo_normalization_orchestrator_falls_back_when_baseline_is_corrupt(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    service.run(repo_ids=("aspose.ocr.docs",))

    baseline_path = tmp_path / "artifacts" / "ingestion-incremental" / "aspose.ocr.docs.json"
    baseline_path.write_text("{invalid-json", encoding="utf-8")
    operation = service.run(repo_ids=("aspose.ocr.docs",))
    result = operation.results[0]

    assert result.parsed_pages_count == 2
    assert result.indexing_summary.incremental_mode == "full_reindex"
    assert result.indexing_summary.incremental_fallback_reason == "baseline_corrupt"
    assert result.indexing_summary.file_new_count == 2
    assert result.indexing_summary.file_changed_count == 0
    assert result.indexing_summary.file_unchanged_count == 0


def test_source_hugo_normalization_orchestrator_uses_git_diff_strategy_between_commits(
    tmp_path: Path,
) -> None:
    repo_root = _write_docs_pages(tmp_path)
    submodule_root = tmp_path / "source-repo-docs" / "Aspose.OCR"
    _init_git_repo(submodule_root)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=(
            lambda submodule_path: resolve_git_submodule_revision(submodule_path=submodule_path)
        ),
    )

    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    first_result = first_operation.results[0]
    first_revision = resolve_git_submodule_revision(submodule_path=submodule_root)
    assert first_result.indexing_summary.incremental_detection_strategy == "checksum_diff"

    install_path = repo_root / "install.md"
    install_path.write_text(
        """---
title: Install
---
```bash
pip install aspose-ocr-python-net
```
Run OCR using git-diff-aware flow.
""",
        encoding="utf-8",
    )
    _git_commit_all(submodule_root, "update install guide")

    second_operation = service.run(repo_ids=("aspose.ocr.docs",))
    second_result = second_operation.results[0]
    assert second_result.indexing_summary.incremental_mode == "incremental"
    assert second_result.indexing_summary.incremental_detection_strategy == "git_diff"
    assert second_result.indexing_summary.incremental_git_base_revision == first_revision
    assert second_result.indexing_summary.file_changed_count == 1
    assert second_result.indexing_summary.file_unchanged_count == 1


def test_source_hugo_normalization_orchestrator_applies_canonical_remap_to_unchanged_chunks(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    _write_page(
        repo_root,
        "legacy.md",
        """---
title: Legacy Topic
url: /ocr/net/legacy-topic/
---
Legacy topic content.
""",
    )
    _write_page(
        repo_root,
        "guide.md",
        """---
title: Guide
url: /ocr/net/guide/
---
Guide content.
""",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    assert first_operation.results[0].indexing_summary.decision.value == "full_publish"

    _write_page(
        repo_root,
        "moved.md",
        """---
title: New Topic
url: /ocr/net/new-topic/
canonical_url_old: /ocr/net/legacy-topic/
---
New topic content.
""",
    )

    second_operation = service.run(repo_ids=("aspose.ocr.docs",))
    second_result = second_operation.results[0]
    assert second_result.indexing_summary.decision.value in {"full_publish", "partial_publish"}
    assert second_result.canonical_url_mapping.remap_entries_count >= 1
    assert second_result.canonical_url_mapping.remap_applied_count >= 1

    legacy_records = [
        record
        for record in second_result.chunk_records
        if record.source_path.endswith("legacy.md")
    ]
    assert legacy_records
    assert all(
        record.canonical_url == "https://docs.aspose.com/ocr/net/new-topic/"
        for record in legacy_records
    )


def test_source_hugo_normalization_orchestrator_reports_conflicting_canonical_remaps(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    _write_page(
        repo_root,
        "a.md",
        """---
title: Topic A
url: /ocr/net/new-a/
canonical_url_old: /ocr/net/shared-old/
---
Topic A body.
""",
    )
    _write_page(
        repo_root,
        "b.md",
        """---
title: Topic B
url: /ocr/net/new-b/
canonical_url_old: /ocr/net/shared-old/
---
Topic B body.
""",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        partial_publish_threshold_pct=100,
    )
    result = operation.results[0]
    assert result.indexing_summary.decision.value == "partial_publish"
    assert result.canonical_url_mapping.remap_conflict_count == 1
    assert result.metadata_quarantine.total_count >= 1
    assert any(
        item.reason_code == MetadataQuarantineReasonCode.CANONICAL_REMAP_CONFLICT.value
        for item in result.metadata_quarantine.sample_items
    )


def test_source_hugo_normalization_orchestrator_honors_quarantine_policy_modes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    _write_page(
        repo_root,
        "good.md",
        """---
title: Good
url: /ocr/net/good/
---
Good content.
""",
    )
    _write_page(
        repo_root,
        "bad.md",
        """---
title: Bad
url: https://docs.aspose.com/ocr net/bad/
---
Bad metadata URL.
""",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())

    strict_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        metadata_quarantine_policy="strict_block",
    )
    strict_result = strict_service.run(
        repo_ids=("aspose.ocr.docs",),
        partial_publish_threshold_pct=100,
    ).results[0]
    assert strict_result.indexing_summary.decision.value == "publish_blocked"
    assert (
        strict_result.indexing_summary.publish_blocked_reason
        == "metadata_quarantine_strict_block"
    )
    assert strict_result.indexing_summary.event_summary.event_types == ("publish_blocked",)
    assert strict_result.metadata_quarantine.policy_mode == "strict_block"
    assert strict_result.metadata_quarantine.total_count >= 1

    best_effort_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        metadata_quarantine_policy="best_effort_continue",
    )
    best_effort_result = best_effort_service.run(
        repo_ids=("aspose.ocr.docs",),
        partial_publish_threshold_pct=100,
    ).results[0]
    assert best_effort_result.indexing_summary.decision.value == "partial_publish"
    assert best_effort_result.indexing_summary.publish_blocked_reason is None
    assert best_effort_result.metadata_quarantine.policy_mode == "best_effort_continue"
    assert best_effort_result.metadata_quarantine.total_count >= 1


def test_source_hugo_normalization_orchestrator_reuses_operation_for_same_idempotency_key(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    first_operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        idempotency_key="idem-trigger-1",
    )
    second_operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        idempotency_key="idem-trigger-1",
    )

    assert first_operation.idempotency_reused is False
    assert second_operation.idempotency_reused is True
    assert second_operation.operation_id == first_operation.operation_id
    assert second_operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert len(service.list_operations(limit=20)) == 1


def test_source_hugo_normalization_orchestrator_forced_reindex_bypasses_incremental_baseline(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    assert first_operation.results[0].indexing_summary.incremental_mode == "full_reindex"

    second_operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        force_full_reindex=True,
    )
    second_result = second_operation.results[0]
    assert second_result.indexing_summary.decision.value == "full_publish"
    assert second_result.indexing_summary.incremental_mode == "full_reindex"
    assert (
        second_result.indexing_summary.incremental_fallback_reason
        == "forced_reindex_requested"
    )
    assert second_result.indexing_summary.file_new_count == 2
    assert second_result.indexing_summary.file_unchanged_count == 0
    assert second_result.indexing_summary.force_full_reindex is True


def test_source_hugo_normalization_orchestrator_replays_from_staging_without_markdown_parse(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    initial_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    first_result = initial_service.run(repo_ids=("aspose.ocr.docs",)).results[0]
    assert first_result.staging_repository_manifest_path is not None

    class _FailingParser:
        def parse_document(self, *args: object, **kwargs: object) -> object:
            msg = "parser must not be called during staging replay"
            raise AssertionError(msg)

    replay_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        parser=_FailingParser(),  # type: ignore[arg-type]
    )
    operation = replay_service.run(
        repo_ids=("aspose.ocr.docs",),
        force_full_reindex=True,
        dry_run=True,
    )
    result = operation.results[0]
    assert result.staging_replay_used is True
    assert result.parsed_pages_count == 0
    assert result.indexing_summary.mode.value == "validate_only"
    assert result.indexing_summary.incremental_mode == "full_reindex"
    assert result.indexing_summary.file_total_count == 2
    assert result.indexing_summary.file_new_count == 2
    assert result.chunk_records


def test_source_hugo_normalization_validate_only_keeps_publish_replay_snapshot(
    tmp_path: Path,
) -> None:
    repo_root = _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )

    publish_result = service.run(repo_ids=("aspose.ocr.docs",)).results[0]
    assert publish_result.staging_repository_manifest_path is not None
    assert "_repo-staging/" in publish_result.staging_repository_manifest_path

    (repo_root / "_index.md").write_text(
        """---
title: Broken Front Matter
## Missing closing delimiter
""",
        encoding="utf-8",
    )
    validate_result = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.VALIDATE_ONLY,
    ).results[0]
    assert validate_result.indexing_summary.decision.value == "validate_only"
    assert validate_result.staging_repository_manifest_path is not None
    assert "_repo-staging-review/" in validate_result.staging_repository_manifest_path

    replay_snapshot = service._canonical_staging_store.load_repository_snapshot(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_revision="revision-abc123",
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    )
    assert replay_snapshot is not None
    assert replay_snapshot.chunk_records

    class _FailingParser:
        def parse_document(self, *args: object, **kwargs: object) -> object:
            msg = "parser must not be called during staging replay"
            raise AssertionError(msg)

    replay_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        parser=_FailingParser(),  # type: ignore[arg-type]
    )
    replay_result = replay_service.run(
        repo_ids=("aspose.ocr.docs",),
        force_full_reindex=True,
        dry_run=True,
    ).results[0]
    assert replay_result.staging_replay_used is True
    assert replay_result.chunk_records


def test_source_hugo_normalization_orchestrator_replay_integrity_error_falls_back_and_emits_event(
    tmp_path: Path,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    bootstrap_service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
    )
    publish_result = bootstrap_service.run(repo_ids=("aspose.ocr.docs",)).results[0]
    assert publish_result.staging_repository_manifest_path is not None

    outside_path = tmp_path.parent / "outside-doc.json"
    outside_path.write_text("{}", encoding="utf-8")

    def _corrupt_manifest(manifest_path: Path) -> None:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_payload["documents"][0]["document_path"] = str(outside_path)
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    # Corrupt the PUBLISH-tier manifest written by the legacy finalize step.
    _corrupt_manifest(tmp_path / publish_result.staging_repository_manifest_path)
    # With streaming normalization, the orchestrator also writes a REVIEW-tier
    # streaming snapshot during the parse loop. Both must be corrupted to
    # make the staging-replay loader fail on every candidate tier (and thus
    # surface the integrity-error event the test asserts on).
    review_manifests = list(
        (tmp_path / "data-docs").glob(
            "*/_repo-staging-review/aspose.ocr.docs/runs/*/repository-manifest.json"
        )
    )
    assert review_manifests, "the streaming parse loop should have produced a REVIEW-tier manifest"
    for review_manifest in review_manifests:
        _corrupt_manifest(review_manifest)

    event_store = InMemoryCriticalEventStore()
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        critical_event_publisher=event_store,
    )
    result = service.run(
        repo_ids=("aspose.ocr.docs",),
        force_full_reindex=True,
        dry_run=True,
    ).results[0]

    assert result.staging_replay_used is False
    assert result.parsed_pages_count == 2
    assert any(
        item.error_code == "STAGING_REPLAY_INTEGRITY_ERROR"
        for item in result.failed_items
    )
    assert result.indexing_summary.event_summary.event_types == ("ingestion_critical_fail",)
    events = event_store.list_events(limit=5)
    assert events
    assert events[0].event_type is CriticalEventType.INGESTION_CRITICAL_FAIL


def test_source_hugo_normalization_orchestrator_dry_run_skips_publish_and_mapping_writes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    repo_root.mkdir(parents=True, exist_ok=True)
    _write_page(
        repo_root,
        "moved.md",
        """---
title: New Topic
url: /ocr/net/new-topic/
canonical_url_old: /ocr/net/legacy-topic/
---
New topic content.
""",
    )
    registry_path = _write_registry(tmp_path, _make_registry_payload())

    class _FailOnPublish:
        def __init__(self) -> None:
            self.called = False

        def publish(self, *, chunk_records: object) -> object:
            self.called = True
            raise AssertionError("publish must not be called in dry_run mode")

    publish_probe = _FailOnPublish()
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        index_publish_orchestrator=publish_probe,  # type: ignore[arg-type]
    )

    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        dry_run=True,
    )
    result = operation.results[0]
    mapping_path = (
        tmp_path
        / "artifacts"
        / "runtime-safe"
        / "canonical-url-mapping"
        / "aspose.ocr"
        / "docs"
        / "net"
        / "latest-stable.json"
    )

    assert publish_probe.called is False
    assert operation.mode is IngestionRunMode.VALIDATE_ONLY
    assert operation.requested_mode is IngestionRunMode.PUBLISH
    assert operation.dry_run is True
    assert result.indexing_summary.mode is IngestionRunMode.VALIDATE_ONLY
    assert result.indexing_summary.decision.value == "validate_only"
    assert result.indexing_summary.snapshot_id == ""
    assert result.indexing_summary.dry_run is True
    assert mapping_path.exists() is False


def test_source_hugo_normalization_orchestrator_schedules_retry_and_allows_manual_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        retry_max_attempts=3,
        retry_backoff_base_seconds=1,
        retry_backoff_max_seconds=4,
    )

    original_normalize_repository = service._normalize_repository
    call_state = {"count": 0}

    def _flaky_normalize_repository(*args: object, **kwargs: object) -> object:
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise OSError("temporary source checkout failure")
        return original_normalize_repository(*args, **kwargs)

    monkeypatch.setattr(
        service,
        "_normalize_repository",
        _flaky_normalize_repository,
    )

    first_operation = service.run(repo_ids=("aspose.ocr.docs",))
    assert first_operation.status is SourceHugoNormalizationStatus.RETRY_SCHEDULED
    assert first_operation.attempt_count == 1
    assert first_operation.max_attempts == 3
    assert first_operation.next_retry_at is not None
    assert first_operation.last_error_kind == "transient_error"
    assert first_operation.resumable is True

    retried_operation = service.retry_operation(
        operation_id=first_operation.operation_id,
        force=True,
    )
    assert retried_operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert retried_operation.attempt_count == 2
    assert retried_operation.next_retry_at is None
    assert retried_operation.last_error_kind is None


def test_source_hugo_normalization_orchestrator_cancel_and_resume_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_docs_pages(tmp_path)
    registry_path = _write_registry(tmp_path, _make_registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        retry_max_attempts=2,
        retry_backoff_base_seconds=1,
        retry_backoff_max_seconds=2,
    )

    original_normalize_repository = service._normalize_repository
    call_state = {"count": 0}

    def _flaky_normalize_repository(*args: object, **kwargs: object) -> object:
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise OSError("temporary parse dependency failure")
        return original_normalize_repository(*args, **kwargs)

    monkeypatch.setattr(
        service,
        "_normalize_repository",
        _flaky_normalize_repository,
    )

    scheduled_operation = service.run(repo_ids=("aspose.ocr.docs",))
    assert scheduled_operation.status is SourceHugoNormalizationStatus.RETRY_SCHEDULED

    cancelled_operation = service.cancel_operation(operation_id=scheduled_operation.operation_id)
    assert cancelled_operation.status is SourceHugoNormalizationStatus.CANCELLED
    assert cancelled_operation.cancelled_at is not None
    assert cancelled_operation.resumable is True

    resumed_operation = service.resume_operation(operation_id=scheduled_operation.operation_id)
    assert resumed_operation.status is SourceHugoNormalizationStatus.COMPLETED
    assert resumed_operation.attempt_count >= 2
