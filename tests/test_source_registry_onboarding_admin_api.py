from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.indexing.index_models import IndexPublishSummary, IngestionRunMode
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationLogLine,
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationResult,
    SourceHugoNormalizationStatus,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionLogLine,
    SourceLayoutDetectionOperation,
    SourceLayoutDetectionResult,
    SourceLayoutDetectionStatus,
)
from adcs.ingestion.source_registry import SourceRegistryService

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _bootstrap_registry_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    source_docs_root = workspace_root / "source-repo-docs"
    source_apiref_root = workspace_root / "source-repo-apiref"
    source_docs_root.mkdir(parents=True)
    source_apiref_root.mkdir(parents=True)
    (source_docs_root / "Aspose.OCR").mkdir(parents=True)
    (source_apiref_root / "Aspose.OCR").mkdir(parents=True)

    registry_dir = workspace_root / "config"
    registry_dir.mkdir(parents=True)
    registry_path = registry_dir / "source-repositories.yaml"
    payload = {
        "schema_version": "1.1.0",
        "source_roots": [
            {"root_id": "docs-root", "source_kind": "docs", "path": "source-repo-docs"},
            {
                "root_id": "apiref-root",
                "source_kind": "apiref",
                "path": "source-repo-apiref",
            },
        ],
        "repositories": [
            {
                "repo_id": "aspose.ocr.docs",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "docs",
                "git": {
                    "url": "https://github.com/aspose-ocr/Aspose.OCR-Documentation.git",
                    "submodule_path": "source-repo-docs/Aspose.OCR",
                    "default_branch": "main",
                },
            },
            {
                "repo_id": "aspose.ocr.apiref",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "apiref",
                "git": {
                    "url": "https://github.com/aspose-ocr/Aspose.OCR-API-References.git",
                    "submodule_path": "source-repo-apiref/Aspose.OCR",
                    "default_branch": "main",
                },
            },
        ],
    }
    registry_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    (registry_dir / "source-repositories.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return workspace_root, registry_path


def test_source_registry_onboarding_creates_docs_and_apiref_entries(tmp_path: Path) -> None:
    workspace_root, registry_path = _bootstrap_registry_workspace(tmp_path)

    app = create_app()
    app.state.source_registry_service = SourceRegistryService(
        registry_path=registry_path,
        workspace_root=workspace_root,
    )
    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/source-repositories/onboard-product",
            headers=ADMIN_HEADERS,
            json={
                "product_id": "aspose.omr",
                "product_name": "Aspose.OMR",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OMR",
                "docs_git_url": "https://github.com/aspose-omr/Aspose.OMR-Documentation.git",
                "docs_default_branch": "main",
                "apiref_git_url": (
                    "https://github.com/aspose-omr/Aspose.OMR-API-References.git"
                ),
                "apiref_default_branch": "main",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == "aspose.omr"
    assert body["created_repo_ids"] == ["aspose.omr.docs", "aspose.omr.apiref"]
    assert (workspace_root / "source-repo-docs" / "Aspose.OMR").exists()
    assert (workspace_root / "source-repo-apiref" / "Aspose.OMR").exists()

    updated_payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert isinstance(updated_payload, dict)
    repositories = updated_payload.get("repositories")
    assert isinstance(repositories, list)
    onboarded_repo_ids = {
        item.get("repo_id")
        for item in repositories
        if isinstance(item, dict)
        and str(item.get("product_id", "")).strip() == "aspose.omr"
    }
    assert onboarded_repo_ids == {"aspose.omr.docs", "aspose.omr.apiref"}
    mirror_payload = json.loads(
        (workspace_root / "config" / "source-repositories.json").read_text(encoding="utf-8")
    )
    mirror_repo_ids = {
        item.get("repo_id")
        for item in mirror_payload["repositories"]
        if item.get("product_id") == "aspose.omr"
    }
    assert mirror_repo_ids == {"aspose.omr.docs", "aspose.omr.apiref"}


def test_source_registry_onboarding_can_return_bootstrap_operations(tmp_path: Path) -> None:
    workspace_root, registry_path = _bootstrap_registry_workspace(tmp_path)

    app = create_app()
    app.state.source_registry_service = SourceRegistryService(
        registry_path=registry_path,
        workspace_root=workspace_root,
    )

    layout_operation = SourceLayoutDetectionOperation(
        operation_id="layout-op-1",
        status=SourceLayoutDetectionStatus.COMPLETED,
        repo_ids=("aspose.omr.docs", "aspose.omr.apiref"),
        logs=(SourceLayoutDetectionLogLine(stream="stdout", line="[ok] layout"),),
        results=(
            SourceLayoutDetectionResult(
                repo_id="aspose.omr.docs",
                layout_type="programming_language/content",
                confidence=0.99,
                dimensions=(),
                sample_markdown_paths=("docs/net/overview.md",),
                detector_version="layout-detector.v1",
                confidence_threshold=0.8,
                confidence_policy_status="accepted",
                manual_override_applied=False,
            ),
        ),
        started_at=datetime.now(tz=UTC),
        finished_at=datetime.now(tz=UTC),
        layout_backend="deterministic",
    )
    validate_operation = SourceHugoNormalizationOperation(
        operation_id="ing-op-1",
        status=SourceHugoNormalizationStatus.COMPLETED,
        repo_ids=("aspose.omr.docs", "aspose.omr.apiref"),
        logs=(SourceHugoNormalizationLogLine(stream="stdout", line="[ok] validate"),),
        results=(
            SourceHugoNormalizationResult(
                repo_id="aspose.omr.docs",
                source_kind="docs",
                parsed_pages_count=1,
                parse_warnings_count=0,
                pages=(),
                canonical_documents=(),
                chunk_records=(),
                indexing_summary=IndexPublishSummary(
                    snapshot_id="snap-preview",
                    product_id="aspose.omr",
                    programming_language="net",
                    version="latest-stable",
                    source_kind="docs",
                    source_revision="rev-preview",
                    indexed_chunks_count=0,
                    vector_records_count=0,
                    lexical_records_count=0,
                    vector_collection="adcs-dev",
                    lexical_index="adcs-dev",
                    lexical_alias="adcs-dev",
                    active_snapshot_id="snap-preview",
                    mode=IngestionRunMode.VALIDATE_ONLY,
                    dry_run=True,
                ),
            ),
        ),
        started_at=datetime.now(tz=UTC),
        finished_at=datetime.now(tz=UTC),
        mode=IngestionRunMode.VALIDATE_ONLY,
        requested_mode=IngestionRunMode.VALIDATE_ONLY,
        dry_run=True,
        conversion_backend="deterministic",
        prompt_registry_version="v1",
        prompt_experiment_id="exp-1",
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        app.state.source_layout_detection_orchestrator,
        "run",
        lambda *, repo_ids: layout_operation,
    )
    monkeypatch.setattr(
        app.state.source_hugo_normalization_orchestrator,
        "run",
        lambda *, repo_ids, mode, dry_run: validate_operation,
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/source-repositories/onboard-product",
            headers=ADMIN_HEADERS,
            json={
                "product_id": "aspose.omr",
                "product_name": "Aspose.OMR",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OMR",
                "docs_git_url": "https://github.com/aspose-omr/Aspose.OMR-Documentation.git",
                "docs_default_branch": "main",
                "apiref_git_url": (
                    "https://github.com/aspose-omr/Aspose.OMR-API-References.git"
                ),
                "apiref_default_branch": "main",
                "auto_run_layout_detection": True,
                "auto_run_validate_only": True,
            },
        )

    monkeypatch.undo()

    assert response.status_code == 200
    body = response.json()
    assert body["bootstrap"]["status"] == "completed"
    assert body["bootstrap"]["layout_detection_requested"] is True
    assert body["bootstrap"]["validate_only_requested"] is True
    assert body["bootstrap"]["layout_detection_operation"]["operation_id"] == "layout-op-1"
    assert body["bootstrap"]["validate_only_operation"]["operation_id"] == "ing-op-1"


def test_source_registry_onboarding_requires_superuser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root, registry_path = _bootstrap_registry_workspace(tmp_path)
    keys_path = tmp_path / "admin_keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:ingestion", "write:settings"],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))

    app = create_app()
    app.state.source_registry_service = SourceRegistryService(
        registry_path=registry_path,
        workspace_root=workspace_root,
    )
    with TestClient(app) as client:
        response = client.post(
            "/admin/v1/source-repositories/onboard-product",
            headers={"x-api-key": "owner-token"},
            json={
                "product_id": "aspose.omr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OMR",
                "docs_git_url": "https://example.local/docs.git",
                "docs_default_branch": "main",
                "apiref_git_url": "https://example.local/apiref.git",
                "apiref_default_branch": "main",
            },
        )

    assert response.status_code == 403
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "FORBIDDEN"
    assert "superuser" in payload["detail"]["error"]["message"].lower()
