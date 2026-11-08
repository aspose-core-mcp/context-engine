from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.indexing.index_models import IndexPublishSummary, IngestionRunMode, PublishDecision
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.hugo_parser import (
    HugoCodeBlock,
    HugoHeading,
    HugoNormalizedPage,
    HugoParseWarning,
)
from adcs.ingestion.normalized_document import (
    NormalizedChunk,
    NormalizedCitation,
    NormalizedDocument,
    NormalizedDocumentMetadata,
)
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationFailedItem,
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationOperationNotFoundError,
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationResult,
    SourceHugoNormalizationStatus,
)
from adcs.ingestion.source_registry import SourceRegistryService

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _bootstrap_preview_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    docs_root = workspace_root / "source-repo-docs" / "Aspose.OCR" / "english" / "net"
    apiref_root = workspace_root / "source-repo-apiref" / "Aspose.OCR" / "english" / "net"
    source_doc_path = "source-repo-docs/Aspose.OCR/english/net/overview.md"
    staged_document_path = (
        "data-docs/aspose.ocr/net/latest-stable/english/"
        "_repo-staging-review/aspose.ocr.docs/runs/op-preview/"
        "normalized-documents/doc-overview.json"
    )
    staged_chunk_path = (
        "data-docs/aspose.ocr/net/latest-stable/english/"
        "_repo-staging-review/aspose.ocr.docs/runs/op-preview/"
        "chunk-records/chunks-overview.json"
    )
    staged_scope_manifest_path = (
        "data-docs/aspose.ocr/net/latest-stable/english/"
        "_repo-staging-review/aspose.ocr.docs/runs/op-preview/manifest.json"
    )
    staged_repository_manifest_path = (
        "data-docs/aspose.ocr/_repo-staging-review/"
        "aspose.ocr.docs/runs/op-preview/repository-manifest.json"
    )
    docs_root.mkdir(parents=True)
    apiref_root.mkdir(parents=True)
    raw_markdown_path = docs_root / "overview.md"
    raw_markdown_path.write_text(
        "---\n"
        "title: Overview\n"
        "---\n\n"
        "# Overview\n\n"
        "Sample documentation body.\n",
        encoding="utf-8",
    )

    registry_dir = workspace_root / "config"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "source-repositories.yaml"
    registry_path.write_text(
        """
schema_version: 1.1.0
source_roots:
  - root_id: docs-root
    source_kind: docs
    path: source-repo-docs
  - root_id: apiref-root
    source_kind: apiref
    path: source-repo-apiref
repositories:
  - repo_id: aspose.ocr.docs
    product_id: aspose.ocr
    product_family: aspose
    product_family_dir: Aspose.OCR
    source_kind: docs
    git:
      url: https://github.com/aspose-ocr/Aspose.OCR-Documentation.git
      submodule_path: source-repo-docs/Aspose.OCR
      default_branch: main
  - repo_id: aspose.ocr.apiref
    product_id: aspose.ocr
    product_family: aspose
    product_family_dir: Aspose.OCR
    source_kind: apiref
    git:
      url: https://github.com/aspose-ocr/Aspose.OCR-API-References.git
      submodule_path: source-repo-apiref/Aspose.OCR
      default_branch: main
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    artifact_dir = (
        workspace_root
        / "artifacts"
        / "ingestion-review"
        / "aspose.ocr.docs"
        / "revision-abc123"
    )
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / "op-preview.json"
    artifact_path.write_text(
        json.dumps(
            {
                "operation_id": "op-preview",
                "repo_id": "aspose.ocr.docs",
                "summary": {
                    "parsed_pages_count": 1,
                    "chunk_records_count": 1,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    staging_root = (
        workspace_root
        / "data-docs"
        / "aspose.ocr"
        / "net"
        / "latest-stable"
        / "english"
        / "_repo-staging-review"
        / "aspose.ocr.docs"
        / "runs"
        / "op-preview"
    )
    normalized_dir = staging_root / "normalized-documents"
    chunks_dir = staging_root / "chunk-records"
    normalized_dir.mkdir(parents=True)
    chunks_dir.mkdir(parents=True)

    document_path = normalized_dir / "doc-overview.json"
    document_path.write_text(
        json.dumps(
            {
                "schema": "adcs.normalized_document.v1",
                "document": {
                    "repo_id": "aspose.ocr.docs",
                    "product_id": "aspose.ocr",
                    "product_family": "aspose",
                    "source_kind": "docs",
                    "programming_language": "net",
                    "doc_locale": "english",
                    "version": "latest-stable",
                    "title": "Overview",
                    "doc_type": "guide_overview",
                    "canonical_url": "https://docs.aspose.com/ocr/net/overview/",
                    "source_path": source_doc_path,
                    "source_revision": "revision-abc123",
                },
                "chunks": [
                    {
                        "chunk_key": "overview-1",
                        "section_path": ["Overview"],
                        "section_anchor": "#overview",
                        "chunk_type": "guide_overview",
                        "text": "Sample documentation body.",
                        "citations": [
                            {
                                "canonical_url": "https://docs.aspose.com/ocr/net/overview/",
                                "source_path": source_doc_path,
                                "title": "Overview",
                                "section_anchor": "#overview",
                            }
                        ],
                        "title": "Overview",
                        "canonical_url": "https://docs.aspose.com/ocr/net/overview/",
                    }
                ],
                "warnings": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    chunk_path = chunks_dir / "chunks-overview.json"
    chunk_path.write_text(
        json.dumps(
            {
                "schema_version": "adcs.canonical_staging.v1",
                "repo_id": "aspose.ocr.docs",
                "source_kind": "docs",
                "source_revision": "revision-abc123",
                "snapshot_tier": "review",
                "operation_id": "op-preview",
                "source_path": source_doc_path,
                "chunk_records": [
                    {
                        "chunk_id": "chunk-1",
                        "repo_id": "aspose.ocr.docs",
                        "product_id": "aspose.ocr",
                        "product_family": "aspose",
                        "programming_language": "net",
                        "version": "latest-stable",
                        "source_kind": "docs",
                        "doc_locale": "english",
                        "doc_type": "guide_overview",
                        "symbol_fqn": None,
                        "title": "Overview",
                        "section_path": ["Overview"],
                        "canonical_url": "https://docs.aspose.com/ocr/net/overview/",
                        "section_anchor": "#overview",
                        "source_path": source_doc_path,
                        "source_revision": "revision-abc123",
                        "is_deprecated": False,
                        "has_code_example": False,
                        "chunk_type": "guide_overview",
                        "text": "Sample documentation body.",
                        "tokens": 42,
                        "checksum": "checksum-1",
                        "executable_snippets": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    scope_manifest_path = staging_root / "manifest.json"
    scope_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "adcs.canonical_staging.v1",
                "repo_id": "aspose.ocr.docs",
                "source_kind": "docs",
                "source_revision": "revision-abc123",
                "snapshot_tier": "review",
                "operation_id": "op-preview",
                "scope": {
                    "product_id": "aspose.ocr",
                    "programming_language": "net",
                    "version": "latest-stable",
                    "doc_locale": "english",
                    "source_kind": "docs",
                },
                "file_checksums": {source_doc_path: "checksum-source-1"},
                "documents": [
                    {
                        "source_path": source_doc_path,
                        "scope": {
                            "product_id": "aspose.ocr",
                            "programming_language": "net",
                            "version": "latest-stable",
                            "doc_locale": "english",
                            "source_kind": "docs",
                        },
                        "document_path": staged_document_path,
                        "document_checksum": "doc-checksum-1",
                    }
                ],
                "chunk_objects": [
                    {
                        "source_path": source_doc_path,
                        "scope": {
                            "product_id": "aspose.ocr",
                            "programming_language": "net",
                            "version": "latest-stable",
                            "doc_locale": "english",
                            "source_kind": "docs",
                        },
                        "chunk_path": staged_chunk_path,
                        "chunk_records_count": 1,
                        "chunk_checksum": "chunk-checksum-1",
                    }
                ],
                "documents_count": 1,
                "chunk_records_count": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    repository_manifest_dir = (
        workspace_root
        / "data-docs"
        / "aspose.ocr"
        / "_repo-staging-review"
        / "aspose.ocr.docs"
        / "runs"
        / "op-preview"
    )
    repository_manifest_dir.mkdir(parents=True)
    repository_manifest_path = repository_manifest_dir / "repository-manifest.json"
    repository_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "adcs.canonical_staging.v1",
                "repo_id": "aspose.ocr.docs",
                "source_kind": "docs",
                "source_revision": "revision-abc123",
                "snapshot_tier": "review",
                "operation_id": "op-preview",
                "repository_manifest_path": staged_repository_manifest_path,
                "scope_manifests": [staged_scope_manifest_path],
                "file_checksums": {source_doc_path: "checksum-source-1"},
                "documents": [
                    {
                        "source_path": source_doc_path,
                        "scope": {
                            "product_id": "aspose.ocr",
                            "programming_language": "net",
                            "version": "latest-stable",
                            "doc_locale": "english",
                            "source_kind": "docs",
                        },
                        "document_path": staged_document_path,
                        "document_checksum": "doc-checksum-1",
                    }
                ],
                "chunk_objects": [
                    {
                        "source_path": source_doc_path,
                        "scope": {
                            "product_id": "aspose.ocr",
                            "programming_language": "net",
                            "version": "latest-stable",
                            "doc_locale": "english",
                            "source_kind": "docs",
                        },
                        "chunk_path": staged_chunk_path,
                        "chunk_records_count": 1,
                        "chunk_checksum": "chunk-checksum-1",
                    }
                ],
                "documents_count": 1,
                "chunk_records_count": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root, registry_path


def test_source_hugo_normalization_api_trigger_list_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(tz=UTC)
    page = HugoNormalizedPage(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
        source_kind="docs",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title="Overview",
        metadata={"title": "Overview"},
        body_plain="Overview body",
        headings=(HugoHeading(level=2, text="Overview", line_hint=3),),
        code_blocks=(
            HugoCodeBlock(
                language="bash",
                code="pip install aspose-ocr-python-net",
                line_start=6,
                line_end=8,
            ),
        ),
        parse_warnings=(
            HugoParseWarning(
                code="HTML_EMBED_DETECTED",
                message="Inline `<script>` embed is not supported in baseline parser.",
                line_hint=9,
            ),
        ),
        is_index_page=True,
    )
    operation = SourceHugoNormalizationOperation(
        operation_id="test-op",
        status=SourceHugoNormalizationStatus.COMPLETED,
        repo_ids=("aspose.ocr.docs",),
        logs=(),
        results=(
            SourceHugoNormalizationResult(
                repo_id="aspose.ocr.docs",
                source_kind="docs",
                parsed_pages_count=1,
                parse_warnings_count=1,
                pages=(page,),
                canonical_documents=(
                    NormalizedDocument(
                        schema="adcs.normalized_document.v1",
                        document=NormalizedDocumentMetadata(
                            repo_id="aspose.ocr.docs",
                            product_id="aspose.ocr",
                            product_family="aspose",
                            source_kind="docs",
                            programming_language="net",
                            doc_locale="english",
                            version="latest-stable",
                            title="Overview",
                            doc_type="index_overview",
                            canonical_url="https://docs.aspose.com/ocr/net/",
                            source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
                            source_revision="revision-abc123",
                        ),
                        chunks=(
                            NormalizedChunk(
                                chunk_key="c1",
                                section_path=("Overview",),
                                section_anchor="#overview",
                                chunk_type="guide_overview",
                                text="Overview body",
                                citations=(
                                    NormalizedCitation(
                                        canonical_url="https://docs.aspose.com/ocr/net/",
                                        source_path=(
                                            "source-repo-docs/Aspose.OCR/english/net/_index.md"
                                        ),
                                        title="Overview",
                                        section_anchor="#overview",
                                    ),
                                ),
                                title="Overview",
                                canonical_url="https://docs.aspose.com/ocr/net/",
                            ),
                        ),
                        warnings=(),
                    ),
                ),
                chunk_records=(
                    StageDChunkRecord(
                        chunk_id="chunk-1",
                        repo_id="aspose.ocr.docs",
                        product_id="aspose.ocr",
                        product_family="aspose",
                        programming_language="net",
                        version="latest-stable",
                        source_kind="docs",
                        doc_locale="english",
                        doc_type="index_overview",
                        symbol_fqn=None,
                        title="Overview",
                        section_path=("Overview",),
                        canonical_url="https://docs.aspose.com/ocr/net/",
                        section_anchor="#overview",
                        source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
                        source_revision="revision-abc123",
                        is_deprecated=False,
                        has_code_example=False,
                        chunk_type="guide_overview",
                        text="Overview body",
                        tokens=128,
                        checksum="checksum-1",
                    ),
                ),
                indexing_summary=IndexPublishSummary(
                    snapshot_id="",
                    product_id="aspose.ocr",
                    programming_language="net",
                    version="latest-stable",
                    source_kind="docs",
                    source_revision="revision-abc123",
                    indexed_chunks_count=0,
                    vector_records_count=0,
                    lexical_records_count=0,
                    vector_collection="",
                    lexical_index="",
                    lexical_alias="",
                    active_snapshot_id="",
                    mode=IngestionRunMode.VALIDATE_ONLY,
                    partial_publish_threshold_pct=40,
                    error_ratio=0.25,
                    decision=PublishDecision.VALIDATE_ONLY,
                    total_items_count=4,
                    failed_items_count=1,
                ),
                failed_items=(
                    SourceHugoNormalizationFailedItem(
                        source_path="source-repo-docs/Aspose.OCR/english/net/broken.md",
                        error_code="HUGO_FRONT_MATTER_UNCLOSED",
                        message="Front matter was not closed.",
                    ),
                ),
            ),
        ),
        started_at=now,
        finished_at=now,
    )
    captured_calls: list[dict[str, object]] = []
    latest_operation: SourceHugoNormalizationOperation = operation

    def _fake_run(
        self: SourceHugoNormalizationOrchestrationService,
        *,
        repo_ids: tuple[str, ...] | None = None,
        mode: IngestionRunMode = IngestionRunMode.PUBLISH,
        partial_publish_threshold_pct: int | None = None,
        metadata_quarantine_policy: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        bypass_staging_replay: bool = False,
        semantic_review_trigger_type: str = "major_change",
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        nonlocal latest_operation
        captured_calls.append(
            {
                "repo_ids": repo_ids,
                "mode": mode,
                "partial_publish_threshold_pct": partial_publish_threshold_pct,
                "metadata_quarantine_policy": metadata_quarantine_policy,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "dry_run": dry_run,
                "force_full_reindex": force_full_reindex,
                "bypass_staging_replay": bypass_staging_replay,
                "semantic_review_trigger_type": semantic_review_trigger_type,
                "execute_immediately": execute_immediately,
            }
        )
        effective_mode = IngestionRunMode.VALIDATE_ONLY if dry_run else mode
        latest_operation = replace(
            operation,
            mode=effective_mode,
            requested_mode=mode,
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            request_id=request_id,
            idempotency_key=idempotency_key,
            idempotency_scope="scope-test" if idempotency_key is not None else None,
            idempotency_reused=False,
        )
        return latest_operation

    def _fake_list(
        self: SourceHugoNormalizationOrchestrationService,
        *,
        limit: int = 20,
    ) -> tuple[SourceHugoNormalizationOperation, ...]:
        assert limit == 5
        return (operation,)

    def _fake_get(
        self: SourceHugoNormalizationOrchestrationService,
        operation_id: str,
    ) -> SourceHugoNormalizationOperation:
        if operation_id != operation.operation_id:
            raise SourceHugoNormalizationOperationNotFoundError("missing")
        return operation

    monkeypatch.setattr(SourceHugoNormalizationOrchestrationService, "run", _fake_run)
    monkeypatch.setattr(
        SourceHugoNormalizationOrchestrationService,
        "list_operations",
        _fake_list,
    )
    monkeypatch.setattr(
        SourceHugoNormalizationOrchestrationService,
        "get_operation",
        _fake_get,
    )

    app = create_app()
    app.state.task_dispatcher = type(
        "_FakeDispatcher",
        (),
        {
            "dispatch_source_sync": lambda self, **kwargs: kwargs["orchestrator"].get_operation(
                kwargs["operation_id"]
            ),
            "dispatch_layout_detection": lambda self, **kwargs: kwargs[
                "orchestrator"
            ].get_operation(kwargs["operation_id"]),
            "dispatch_ingestion": lambda self, **_: latest_operation,
        },
    )()
    with TestClient(app) as client:
        trigger_response = client.post(
            "/admin/v1/source-repositories/hugo-normalize",
            json={
                "repo_id": "aspose.ocr.docs",
                "mode": "validate_only",
                "partial_publish_threshold_pct": 40,
            },
            headers=ADMIN_HEADERS,
        )
        assert trigger_response.status_code == 200
        trigger_body = trigger_response.json()
        assert trigger_body["status"] == "completed"
        assert trigger_body["job_id"] == "test-op"
        assert trigger_body["mode"] == "validate_only"
        assert trigger_body["requested_mode"] == "validate_only"
        assert trigger_body["conversion_backend"] == "deterministic"
        assert trigger_body["prompt_registry_version"] == "disabled"
        assert trigger_body["prompt_experiment_id"] == "conversion.default.v1"
        assert trigger_body["dry_run"] is False
        assert trigger_body["force_full_reindex"] is False
        assert trigger_body["idempotency_key"] is None
        assert trigger_body["idempotency_scope"] is None
        assert trigger_body["idempotency_reused"] is False
        assert trigger_body["attempt_count"] == 1
        assert trigger_body["max_attempts"] == 1
        assert trigger_body["next_retry_at"] is None
        assert trigger_body["last_error_kind"] is None
        assert trigger_body["cancel_requested_at"] is None
        assert trigger_body["cancelled_at"] is None
        assert trigger_body["resumable"] is False
        assert trigger_body["results"][0]["parsed_pages_count"] == 1
        assert trigger_body["results"][0]["pages"][0]["doc_locale"] == "english"
        assert trigger_body["results"][0]["review_artifact_path"] is None
        assert trigger_body["results"][0]["staging_repository_manifest_path"] is None
        assert trigger_body["results"][0]["staging_replay_used"] is False
        assert trigger_body["results"][0]["staging_scopes"] == []
        assert trigger_body["results"][0]["chunk_records"][0]["chunk_id"] == "chunk-1"
        assert trigger_body["results"][0]["chunk_records"][0]["checksum"] == "checksum-1"
        assert trigger_body["results"][0]["indexing_summary"]["snapshot_id"] == ""
        assert trigger_body["results"][0]["indexing_summary"]["vector_records_count"] == 0
        assert trigger_body["results"][0]["indexing_summary"]["mode"] == "validate_only"
        assert trigger_body["results"][0]["indexing_summary"]["decision"] == "validate_only"
        assert (
            trigger_body["results"][0]["indexing_summary"]["publish_blocked_reason"] is None
        )
        assert (
            trigger_body["results"][0]["indexing_summary"]["partial_publish_threshold_pct"] == 40
        )
        assert trigger_body["results"][0]["indexing_summary"]["dry_run"] is False
        assert (
            trigger_body["results"][0]["indexing_summary"]["force_full_reindex"] is False
        )
        assert trigger_body["results"][0]["indexing_summary"]["error_ratio"] == 0.25
        assert trigger_body["results"][0]["indexing_summary"]["failed_items_count"] == 1
        assert (
            trigger_body["results"][0]["indexing_summary"]["metadata_quarantine_policy"]
            == "best_effort_continue"
        )
        assert trigger_body["results"][0]["indexing_summary"]["quarantined_items_count"] == 0
        assert trigger_body["results"][0]["indexing_summary"]["semantic_gate"]["enforced"] is False
        assert (
            trigger_body["results"][0]["indexing_summary"]["conversion_gate"]["phase"] == "mvp"
        )
        assert trigger_body["results"][0]["failed_items"][0]["error_code"] == (
            "HUGO_FRONT_MATTER_UNCLOSED"
        )
        assert trigger_body["results"][0]["metadata_quarantine"]["total_count"] == 0
        assert trigger_body["results"][0]["prompt_evaluation"]["registry_version"] == "disabled"
        assert trigger_body["results"][0]["canonical_url_mapping"]["remap_entries_count"] == 0

        future_trigger_response = client.post(
            "/admin/v1/ingestion/trigger",
            json={
                "repo_id": "aspose.ocr.docs",
                "mode": "publish",
                "dry_run": True,
                "force_full_reindex": True,
                "idempotency_key": "idem-xyz",
            },
            headers=ADMIN_HEADERS,
        )
        assert future_trigger_response.status_code == 200
        future_trigger_body = future_trigger_response.json()
        assert future_trigger_body["operation_id"] == "test-op"
        assert future_trigger_body["job_id"] == "test-op"
        assert future_trigger_body["mode"] == "validate_only"
        assert future_trigger_body["requested_mode"] == "publish"
        assert future_trigger_body["conversion_backend"] == "deterministic"
        assert future_trigger_body["dry_run"] is True
        assert future_trigger_body["force_full_reindex"] is True
        assert future_trigger_body["idempotency_key"] == "idem-xyz"
        assert future_trigger_body["idempotency_scope"] == "scope-test"
        assert future_trigger_body["attempt_count"] == 1

        reindex_trigger_response = client.post(
            "/admin/v1/ingestion/reindex",
            json={
                "repo_id": "aspose.ocr.docs",
                "mode": "publish",
                "force_full_reindex": False,
            },
            headers=ADMIN_HEADERS,
        )
        assert reindex_trigger_response.status_code == 200
        reindex_trigger_body = reindex_trigger_response.json()
        assert reindex_trigger_body["operation_id"] == "test-op"
        assert reindex_trigger_body["requested_mode"] == "publish"
        assert reindex_trigger_body["dry_run"] is False
        assert reindex_trigger_body["force_full_reindex"] is True

        list_response = client.get(
            "/admin/v1/source-repositories/hugo-normalize?limit=5",
            headers=ADMIN_HEADERS,
        )
        assert list_response.status_code == 200
        assert list_response.json()[0]["operation_id"] == "test-op"

        get_response = client.get(
            "/admin/v1/source-repositories/hugo-normalize/test-op",
            headers=ADMIN_HEADERS,
        )
        assert get_response.status_code == 200
        assert get_response.json()["operation_id"] == "test-op"

        list_future_response = client.get(
            "/admin/v1/ingestion/jobs?limit=5",
            headers=ADMIN_HEADERS,
        )
        assert list_future_response.status_code == 200
        assert list_future_response.json()[0]["operation_id"] == "test-op"

        get_future_response = client.get(
            "/admin/v1/ingestion/jobs/test-op",
            headers=ADMIN_HEADERS,
        )
        assert get_future_response.status_code == 200
        assert get_future_response.json()["operation_id"] == "test-op"

    assert len(captured_calls) == 3
    first_call = captured_calls[0]
    assert first_call["repo_ids"] == ("aspose.ocr.docs",)
    assert first_call["mode"] is IngestionRunMode.VALIDATE_ONLY
    assert first_call["partial_publish_threshold_pct"] == 40
    assert first_call["metadata_quarantine_policy"] is None
    assert isinstance(first_call["request_id"], str)
    assert first_call["idempotency_key"] is None
    assert first_call["dry_run"] is False
    assert first_call["force_full_reindex"] is False
    assert first_call["semantic_review_trigger_type"] == "major_change"
    assert first_call["execute_immediately"] is False

    second_call = captured_calls[1]
    assert second_call["repo_ids"] == ("aspose.ocr.docs",)
    assert second_call["mode"] is IngestionRunMode.PUBLISH
    assert second_call["dry_run"] is True
    assert second_call["force_full_reindex"] is True
    assert second_call["idempotency_key"] == "idem-xyz"

    third_call = captured_calls[2]
    assert third_call["repo_ids"] == ("aspose.ocr.docs",)
    assert third_call["mode"] is IngestionRunMode.PUBLISH
    assert third_call["dry_run"] is False
    assert third_call["force_full_reindex"] is True


def test_ingestion_job_lifecycle_endpoints_cancel_retry_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(tz=UTC)
    operation = SourceHugoNormalizationOperation(
        operation_id="job-lifecycle",
        status=SourceHugoNormalizationStatus.RETRY_SCHEDULED,
        repo_ids=("aspose.ocr.docs",),
        logs=(),
        results=(),
        started_at=now,
        finished_at=now,
        attempt_count=2,
        max_attempts=5,
        next_retry_at=now,
        last_error_kind="transient_error",
        resumable=True,
    )
    calls: list[tuple[str, str]] = []
    latest_operation: SourceHugoNormalizationOperation = operation

    def _fake_get(
        self: SourceHugoNormalizationOrchestrationService,
        operation_id: str,
    ) -> SourceHugoNormalizationOperation:
        nonlocal latest_operation
        if operation_id != operation.operation_id:
            raise SourceHugoNormalizationOperationNotFoundError("missing")
        return latest_operation

    def _fake_cancel(
        self: SourceHugoNormalizationOrchestrationService,
        *,
        operation_id: str,
        request_id: str | None = None,
    ) -> SourceHugoNormalizationOperation:
        nonlocal latest_operation
        calls.append(("cancel", operation_id))
        latest_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.CANCELLED,
            cancel_requested_at=now,
            cancelled_at=now,
        )
        return latest_operation

    def _fake_retry(
        self: SourceHugoNormalizationOrchestrationService,
        *,
        operation_id: str,
        request_id: str | None = None,
        force: bool = False,
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        nonlocal latest_operation
        calls.append(("retry", operation_id))
        assert force is True
        latest_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.RUNNING,
            attempt_count=3,
            next_retry_at=None,
            last_error_kind=None,
        )
        return latest_operation

    def _fake_resume(
        self: SourceHugoNormalizationOrchestrationService,
        *,
        operation_id: str,
        request_id: str | None = None,
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        nonlocal latest_operation
        calls.append(("resume", operation_id))
        latest_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.RUNNING,
            attempt_count=3,
            cancelled_at=None,
            cancel_requested_at=None,
        )
        return latest_operation

    monkeypatch.setattr(SourceHugoNormalizationOrchestrationService, "get_operation", _fake_get)
    monkeypatch.setattr(
        SourceHugoNormalizationOrchestrationService,
        "cancel_operation",
        _fake_cancel,
    )
    monkeypatch.setattr(
        SourceHugoNormalizationOrchestrationService,
        "retry_operation",
        _fake_retry,
    )
    monkeypatch.setattr(
        SourceHugoNormalizationOrchestrationService,
        "resume_operation",
        _fake_resume,
    )

    app = create_app()
    app.state.task_dispatcher = type(
        "_FakeDispatcher",
        (),
        {
            "dispatch_source_sync": lambda self, **kwargs: kwargs["orchestrator"].get_operation(
                kwargs["operation_id"]
            ),
            "dispatch_layout_detection": lambda self, **kwargs: kwargs[
                "orchestrator"
            ].get_operation(kwargs["operation_id"]),
            "dispatch_ingestion": lambda self, **kwargs: latest_operation,
        },
    )()
    with TestClient(app) as client:
        cancel_response = client.post(
            "/admin/v1/ingestion/jobs/job-lifecycle:cancel",
            headers=ADMIN_HEADERS,
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"

        retry_response = client.post(
            "/admin/v1/ingestion/jobs/job-lifecycle:retry",
            json={"force": True},
            headers=ADMIN_HEADERS,
        )
        assert retry_response.status_code == 200
        retry_payload = retry_response.json()
        assert retry_payload["status"] == "running"
        assert retry_payload["attempt_count"] == 3

        resume_response = client.post(
            "/admin/v1/ingestion/jobs/job-lifecycle:resume",
            headers=ADMIN_HEADERS,
        )
        assert resume_response.status_code == 200
        assert resume_response.json()["status"] == "running"

    assert calls == [
        ("cancel", "job-lifecycle"),
        ("retry", "job-lifecycle"),
        ("resume", "job-lifecycle"),
    ]


def test_ingestion_review_preview_endpoints_load_artifacts_and_staging(
    tmp_path: Path,
) -> None:
    workspace_root, registry_path = _bootstrap_preview_workspace(tmp_path)
    artifact_path = (
        "artifacts/ingestion-review/aspose.ocr.docs/revision-abc123/op-preview.json"
    )
    source_path = "source-repo-docs/Aspose.OCR/english/net/overview.md"
    manifest_path = (
        "data-docs/aspose.ocr/_repo-staging-review/"
        "aspose.ocr.docs/runs/op-preview/repository-manifest.json"
    )
    app = create_app()
    app.state.source_registry_service = SourceRegistryService(
        registry_path=registry_path,
        workspace_root=workspace_root,
    )

    with TestClient(app) as client:
        artifact_response = client.post(
            "/admin/v1/source-repositories/review-artifact:preview",
            headers=ADMIN_HEADERS,
            json={"artifact_path": artifact_path},
        )
        assert artifact_response.status_code == 200
        artifact_payload = artifact_response.json()
        assert artifact_payload["payload"]["summary"]["parsed_pages_count"] == 1

        raw_response = client.post(
            "/admin/v1/source-repositories/raw-markdown:preview",
            headers=ADMIN_HEADERS,
            json={"source_path": source_path},
        )
        assert raw_response.status_code == 200
        raw_payload = raw_response.json()
        assert raw_payload["line_count"] >= 4
        assert "Sample documentation body." in raw_payload["raw_markdown"]

        manifest_response = client.post(
            "/admin/v1/source-repositories/staging-manifest:preview",
            headers=ADMIN_HEADERS,
            json={"manifest_path": manifest_path},
        )
        assert manifest_response.status_code == 200
        manifest_payload = manifest_response.json()
        assert manifest_payload["manifest_kind"] == "repository"
        assert manifest_payload["payload"]["documents_count"] == 1
        assert (
            manifest_payload["documents_preview"][0]["payload"]["document"]["title"]
            == "Overview"
        )
        assert (
            manifest_payload["chunk_objects_preview"][0]["payload"]["chunk_records"][0]["chunk_id"]
            == "chunk-1"
        )
        assert manifest_payload["documents_truncated"] is False
        assert manifest_payload["chunk_objects_truncated"] is False
        assert manifest_payload["chunk_records_truncated"] is False


def test_ingestion_review_preview_enforces_workspace_boundary(
    tmp_path: Path,
) -> None:
    workspace_root, registry_path = _bootstrap_preview_workspace(tmp_path)
    app = create_app()
    app.state.source_registry_service = SourceRegistryService(
        registry_path=registry_path,
        workspace_root=workspace_root,
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/source-repositories/raw-markdown:preview",
            headers=ADMIN_HEADERS,
            json={"source_path": "../outside.md"},
        )

    assert response.status_code == 400
    assert "workspace boundary" in response.json()["detail"]
