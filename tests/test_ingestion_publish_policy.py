from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adcs.admin import (
    InMemorySemanticReviewService,
    SemanticReviewApprovalMode,
    SemanticReviewCandidateItem,
)
from adcs.indexing import (
    IndexPublishOrchestrator,
    InMemoryLexicalIndexWriter,
    InMemorySnapshotRegistry,
    InMemoryVectorIndexWriter,
)
from adcs.indexing.index_models import IngestionRunMode
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationStatus,
)
from adcs.ops import (
    CriticalEventType,
    InMemoryCriticalEventStore,
    InMemorySmtpTransport,
    NotificationService,
)


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


def _make_service(
    tmp_path: Path,
    *,
    partial_publish_threshold_pct: int = 30,
    quality_gate_phase: str = "mvp",
    semantic_review_service: InMemorySemanticReviewService | None = None,
    critical_event_publisher: InMemoryCriticalEventStore | None = None,
    notification_service: NotificationService | None = None,
) -> tuple[
    SourceHugoNormalizationOrchestrationService,
    InMemorySnapshotRegistry,
    InMemoryVectorIndexWriter,
    InMemoryLexicalIndexWriter,
]:
    snapshot_registry = InMemorySnapshotRegistry()
    vector_writer = InMemoryVectorIndexWriter()
    lexical_writer = InMemoryLexicalIndexWriter()
    publish_orchestrator = IndexPublishOrchestrator(
        snapshot_registry=snapshot_registry,
        vector_index_writer=vector_writer,
        lexical_index_writer=lexical_writer,
    )
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=tmp_path / "config" / "source-repositories.json",
        source_revision_resolver=lambda _: "revision-abc123",
        index_publish_orchestrator=publish_orchestrator,
        partial_publish_threshold_pct=partial_publish_threshold_pct,
        semantic_review_service=semantic_review_service,
        critical_event_publisher=critical_event_publisher,
        notification_service=notification_service,
        quality_gate_phase=quality_gate_phase,
    )
    return service, snapshot_registry, vector_writer, lexical_writer


def _write_valid_docs_pages(tmp_path: Path) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net" / "guide"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "_index.md").write_text(
        """---
title: Guide Overview
---
## Intro
Overview text.
""",
        encoding="utf-8",
    )
    (repo_root / "install.md").write_text(
        """---
title: Install
---
Install package and run OCR.
""",
        encoding="utf-8",
    )


def _write_valid_and_invalid_pages(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net" / "guide"
    (repo_root / "broken.md").write_text(
        """---
title: Broken
## missing closing front matter
""",
        encoding="utf-8",
    )


def _write_valid_and_quarantine_pages(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR" / "english" / "net" / "guide"
    (repo_root / "bad-url.md").write_text(
        """---
title: Bad URL
url: https://docs.aspose.com/ocr net/bad-url/
---
Bad metadata URL.
""",
        encoding="utf-8",
    )


def _make_semantic_review_service(
    *,
    tmp_path: Path,
    approval_mode: SemanticReviewApprovalMode = "auto_approve",
) -> InMemorySemanticReviewService:
    service = InMemorySemanticReviewService(workspace_root=tmp_path)
    service.patch_policy(
        product_id="aspose.ocr",
        updated_by="test-suite",
        sample_size=60,
        threshold_score=4.3,
        approval_mode=approval_mode,
    )
    return service


def _review_items_for_pass() -> tuple[SemanticReviewCandidateItem, ...]:
    return (
        SemanticReviewCandidateItem(
            source_path="docs/aspose.ocr/guide/install.md",
            stratum="docs_shortcode",
            simulated_score=4.7,
        ),
        SemanticReviewCandidateItem(
            source_path="docs/aspose.ocr/guide/overview.md",
            stratum="docs_html_embed",
            simulated_score=4.8,
        ),
    )


def test_validate_only_runs_validation_without_snapshot_publish(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    service, snapshot_registry, vector_writer, lexical_writer = _make_service(tmp_path)

    operation = service.run(repo_ids=("aspose.ocr.docs",), mode=IngestionRunMode.VALIDATE_ONLY)

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    result = operation.results[0]
    assert result.chunk_records
    assert result.failed_items == ()
    assert result.indexing_summary.decision.value == "validate_only"
    assert result.indexing_summary.mode.value == "validate_only"
    assert result.indexing_summary.snapshot_id == ""
    assert result.indexing_summary.vector_records_count == 0
    assert result.indexing_summary.lexical_records_count == 0
    assert result.indexing_summary.total_items_count == 2
    assert result.indexing_summary.failed_items_count == 0
    assert result.indexing_summary.event_summary.event_types == ()
    assert result.indexing_summary.notification_summary.sent_count == 0

    assert snapshot_registry.list_snapshots() == ()
    assert vector_writer.get_snapshot_records("snap-00000001") == ()
    assert lexical_writer.get_snapshot_records("snap-00000001") == ()


def test_partial_publish_allowed_when_error_ratio_within_threshold(tmp_path: Path) -> None:
    _write_valid_and_quarantine_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    service, snapshot_registry, _, _ = _make_service(tmp_path, partial_publish_threshold_pct=30)

    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        partial_publish_threshold_pct=60,
    )

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    result = operation.results[0]
    assert len(result.failed_items) == 1
    assert result.indexing_summary.decision.value == "partial_publish"
    assert result.indexing_summary.snapshot_id == "snap-00000001"
    assert result.indexing_summary.vector_records_count == len(result.chunk_records)
    assert result.indexing_summary.lexical_records_count == len(result.chunk_records)
    assert result.indexing_summary.total_items_count == 3
    assert result.indexing_summary.failed_items_count == 1
    assert result.indexing_summary.error_ratio == 1 / 3
    assert result.indexing_summary.partial_publish_threshold_pct == 60
    assert result.indexing_summary.publish_safety_gate.blocking is False
    assert result.indexing_summary.event_summary.event_types == ("partial_publish",)
    assert result.indexing_summary.notification_summary.sent_count == 1

    snapshots = snapshot_registry.list_snapshots(
        product_id="aspose.ocr",
        programming_language="net",
        version="latest-stable",
    )
    assert [snapshot.snapshot_id for snapshot in snapshots] == ["snap-00000001"]


def test_publish_blocked_when_error_ratio_exceeds_threshold(tmp_path: Path) -> None:
    _write_valid_and_quarantine_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    service, snapshot_registry, _, _ = _make_service(tmp_path, partial_publish_threshold_pct=30)

    operation = service.run(repo_ids=("aspose.ocr.docs",), mode=IngestionRunMode.PUBLISH)

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    result = operation.results[0]
    assert len(result.failed_items) == 1
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.snapshot_id == ""
    assert result.indexing_summary.vector_records_count == 0
    assert result.indexing_summary.lexical_records_count == 0
    assert result.indexing_summary.total_items_count == 3
    assert result.indexing_summary.failed_items_count == 1
    assert result.indexing_summary.error_ratio == 1 / 3
    assert result.indexing_summary.partial_publish_threshold_pct == 30
    assert result.indexing_summary.event_summary.event_types == ("publish_blocked",)
    assert result.indexing_summary.notification_summary.sent_count == 1

    assert snapshot_registry.list_snapshots() == ()


def test_publish_safety_gate_blocks_partial_publish_on_critical_parser_error(
    tmp_path: Path,
) -> None:
    _write_valid_and_invalid_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    service, snapshot_registry, _, _ = _make_service(tmp_path, partial_publish_threshold_pct=30)

    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        partial_publish_threshold_pct=60,
    )

    assert operation.status is SourceHugoNormalizationStatus.COMPLETED
    result = operation.results[0]
    assert len(result.failed_items) == 1
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.publish_blocked_reason == "publish_safety_gate"
    assert result.indexing_summary.publish_safety_gate.blocking is True
    assert result.indexing_summary.publish_safety_gate.reason_codes == (
        "critical_parser_errors_present",
    )
    assert result.indexing_summary.publish_safety_gate.parser_critical_failed_items_count == 1
    assert result.indexing_summary.event_summary.event_types == ("publish_blocked",)
    assert result.indexing_summary.notification_summary.sent_count == 1
    assert snapshot_registry.list_snapshots() == ()


def test_publish_allows_missing_semantic_review_run_in_mvp_track_only(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(
        tmp_path=tmp_path,
        approval_mode="human_approve_all",
    )

    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
        quality_gate_phase="mvp",
    )
    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-missing-mvp",
    )

    result = operation.results[0]
    assert result.indexing_summary.decision.value == "full_publish"
    assert result.indexing_summary.snapshot_id == "snap-00000001"
    assert snapshot_registry.list_snapshots()
    gate = result.indexing_summary.semantic_gate
    assert gate.enforced is False
    assert gate.decision.value == "not_enforced"
    assert gate.reason_codes == (
        "semantic_review_run_missing",
        "semantic_review_missing_required_approval",
    )
    assert gate.review_run_id is None
    assert gate.review_status is None


def test_publish_blocks_missing_semantic_review_run_in_preprod(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(
        tmp_path=tmp_path,
        approval_mode="human_approve_all",
    )
    event_store = InMemoryCriticalEventStore()
    notification_service = NotificationService(smtp_transport=InMemorySmtpTransport())

    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
        quality_gate_phase="preprod",
        critical_event_publisher=event_store,
        notification_service=notification_service,
    )
    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-missing-preprod",
    )

    result = operation.results[0]
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.snapshot_id == ""
    assert snapshot_registry.list_snapshots() == ()
    gate = result.indexing_summary.semantic_gate
    assert gate.enforced is True
    assert gate.decision.value == "block_publish"
    assert gate.reason_codes == (
        "semantic_review_run_missing",
        "semantic_review_missing_required_approval",
    )

    events = event_store.list_events(limit=1)
    assert len(events) == 1
    assert events[0].event_type is CriticalEventType.PUBLISH_BLOCKED
    assert events[0].details["publish_blocked_reason"] == "semantic_review_hard_gate"


def test_publish_allowed_when_auto_approve_passes_all_semantic_gates(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(tmp_path=tmp_path, approval_mode="auto_approve")
    review_run = review_service.create_run(
        product_id="aspose.ocr",
        version="latest-stable",
        source_revision="revision-abc123",
        trigger_type="major_change",
        created_by="agent",
        created_by_key_id=None,
        request_id="req-review-pass",
        items=_review_items_for_pass(),
    )
    assert review_run.status == "approved"

    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
    )
    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-pass",
    )

    result = operation.results[0]
    assert result.indexing_summary.decision.value == "full_publish"
    assert result.indexing_summary.snapshot_id == "snap-00000001"
    assert snapshot_registry.list_snapshots()
    gate = result.indexing_summary.semantic_gate
    assert gate.enforced is True
    assert gate.decision.value == "allow_publish"
    assert gate.reason_codes == ()
    assert gate.review_run_id == review_run.run_id
    assert gate.review_status == "approved"
    assert gate.approval_mode == "auto_approve"


def test_publish_blocked_when_semantic_score_is_below_threshold(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(tmp_path=tmp_path, approval_mode="auto_approve")
    review_run = review_service.create_run(
        product_id="aspose.ocr",
        version="latest-stable",
        source_revision="revision-abc123",
        trigger_type="major_change",
        created_by="agent",
        created_by_key_id=None,
        request_id="req-review-low-score",
        items=(
            SemanticReviewCandidateItem(
                source_path="docs/aspose.ocr/guide/score-low.md",
                stratum="docs_shortcode",
                simulated_score=4.0,
            ),
            SemanticReviewCandidateItem(
                source_path="docs/aspose.ocr/guide/score-low-2.md",
                stratum="docs_html_embed",
                simulated_score=4.1,
            ),
        ),
    )
    assert review_run.status == "rejected"

    event_store = InMemoryCriticalEventStore()
    notification_service = NotificationService(smtp_transport=InMemorySmtpTransport())
    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
        critical_event_publisher=event_store,
        notification_service=notification_service,
    )
    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-score",
    )

    result = operation.results[0]
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.snapshot_id == ""
    assert snapshot_registry.list_snapshots() == ()
    gate = result.indexing_summary.semantic_gate
    assert gate.decision.value == "block_publish"
    assert gate.reason_codes == ("semantic_review_score_below_threshold",)
    assert gate.review_run_id == review_run.run_id
    assert gate.review_status == "rejected"

    events = event_store.list_events(limit=1)
    assert len(events) == 1
    assert events[0].event_type is CriticalEventType.PUBLISH_BLOCKED
    assert events[0].details["reason_codes"] == ["semantic_review_score_below_threshold"]
    assert events[0].details["job_id"] == operation.operation_id
    assert events[0].details["request_id"] == "req-sem-score"

    updated_run = review_service.get_run(review_run.run_id)
    assert updated_run.publish_gate_trail
    assert updated_run.publish_gate_trail[-1].reason_codes == (
        "semantic_review_score_below_threshold",
    )


def test_publish_blocked_when_semantic_fail_fast_blocking_finding_present(
    tmp_path: Path,
) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(tmp_path=tmp_path, approval_mode="auto_approve")
    review_run = review_service.create_run(
        product_id="aspose.ocr",
        version="latest-stable",
        source_revision="revision-abc123",
        trigger_type="major_change",
        created_by="agent",
        created_by_key_id=None,
        request_id="req-review-blocking",
        items=(
            SemanticReviewCandidateItem(
                source_path="apiref/aspose.ocr/hallucinated-symbol.md",
                stratum="apiref_symbol_rich",
                simulated_score=4.9,
                simulated_blocking_error_type="hallucinated_api_member",
            ),
            SemanticReviewCandidateItem(
                source_path="docs/aspose.ocr/guide/overview.md",
                stratum="docs_shortcode",
                simulated_score=4.8,
            ),
        ),
    )
    assert review_run.status == "blocked"

    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
    )
    operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-fail-fast",
    )

    result = operation.results[0]
    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.snapshot_id == ""
    assert snapshot_registry.list_snapshots() == ()
    gate = result.indexing_summary.semantic_gate
    assert gate.decision.value == "block_publish"
    assert gate.reason_codes == ("semantic_review_blocking_finding_present",)
    assert gate.fail_fast_triggered is True
    assert gate.blocking_error_count == 1
    assert gate.review_status == "blocked"


def test_publish_blocked_in_human_mode_until_manual_approve(tmp_path: Path) -> None:
    _write_valid_docs_pages(tmp_path)
    _write_registry(tmp_path, _make_registry_payload())
    review_service = _make_semantic_review_service(
        tmp_path=tmp_path,
        approval_mode="human_approve_all",
    )
    review_run = review_service.create_run(
        product_id="aspose.ocr",
        version="latest-stable",
        source_revision="revision-abc123",
        trigger_type="major_change",
        created_by="agent",
        created_by_key_id=None,
        request_id="req-review-awaiting",
        items=_review_items_for_pass(),
    )
    assert review_run.status == "awaiting_approval"

    service, snapshot_registry, _, _ = _make_service(
        tmp_path,
        semantic_review_service=review_service,
    )
    blocked_operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-human-block",
    )
    blocked_result = blocked_operation.results[0]
    assert blocked_result.indexing_summary.decision.value == "publish_blocked"
    assert blocked_result.indexing_summary.semantic_gate.reason_codes == (
        "semantic_review_missing_required_approval",
    )
    assert blocked_result.indexing_summary.semantic_gate.review_status == "awaiting_approval"
    assert snapshot_registry.list_snapshots() == ()

    approved_run = review_service.approve_all(
        run_id=review_run.run_id,
        actor_key_id="owner-key",
        request_id="req-manual-approve",
    )
    assert approved_run.status == "approved"

    allowed_operation = service.run(
        repo_ids=("aspose.ocr.docs",),
        mode=IngestionRunMode.PUBLISH,
        request_id="req-sem-human-pass",
    )
    allowed_result = allowed_operation.results[0]
    assert allowed_result.indexing_summary.decision.value == "full_publish"
    assert allowed_result.indexing_summary.semantic_gate.decision.value == "allow_publish"
    assert allowed_result.indexing_summary.semantic_gate.reason_codes == ()
    assert snapshot_registry.list_snapshots()
