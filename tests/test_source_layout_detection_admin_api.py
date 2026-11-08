from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import adcs.ingestion.source_layout_detection_orchestrator as source_layout_detection_orchestrator
from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOrchestrationService,
    SourceLayoutDetectionResult,
)

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_source_layout_detection_api_triggers_and_exposes_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_command: list[str] = []

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        captured_command[:] = command
        assert cwd.exists()
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] layout detection completed\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        trigger_response = client.post(
            "/admin/v1/source-repositories/layout-detection",
            json={"repo_ids": ["aspose.ocr.apiref", "aspose.ocr.docs"]},
            headers=ADMIN_HEADERS,
        )
        assert trigger_response.status_code == 200
        trigger_body = trigger_response.json()
        assert trigger_body["status"] == "completed"
        assert trigger_body["layout_backend"] == "deterministic"
        assert trigger_body["repo_ids"] == ["aspose.ocr.apiref", "aspose.ocr.docs"]
        assert "--write" in captured_command
        assert captured_command.count("--repo-id") == 2
        assert trigger_body["logs"]
        assert trigger_body["started_at"] is not None
        assert trigger_body["finished_at"] is not None

        results_by_repo = {item["repo_id"]: item for item in trigger_body["results"]}
        assert results_by_repo["aspose.ocr.apiref"]["layout_type"] == (
            "doc_locale/programming_language/namespace"
        )
        assert results_by_repo["aspose.ocr.docs"]["layout_type"] == "programming_language/content"
        assert results_by_repo["aspose.ocr.apiref"]["detector_version"] == "layout-detector.v1"
        assert isinstance(results_by_repo["aspose.ocr.docs"]["confidence"], float)
        assert results_by_repo["aspose.ocr.docs"]["confidence_threshold"] == 0.8
        assert results_by_repo["aspose.ocr.docs"]["confidence_policy_status"] == "accepted"
        assert results_by_repo["aspose.ocr.docs"]["manual_override_applied"] is False
        assert results_by_repo["aspose.ocr.docs"]["sample_markdown_paths"]
        assert results_by_repo["aspose.ocr.docs"]["dimensions"]

        operation_id = trigger_body["operation_id"]
        operation_path = f"/admin/v1/source-repositories/layout-detection/{operation_id}"
        fetch_response = client.get(operation_path, headers=ADMIN_HEADERS)
        assert fetch_response.status_code == 200
        assert fetch_response.json()["results"] == trigger_body["results"]

        list_response = client.get(
            "/admin/v1/source-repositories/layout-detection?limit=5",
            headers=ADMIN_HEADERS,
        )
        assert list_response.status_code == 200
        listed_operations = list_response.json()
        assert listed_operations
        assert listed_operations[0]["operation_id"] == operation_id


def test_source_layout_detection_api_returns_failed_status_for_failed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, capture_output, text, check
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="[error] simulated layout detection failure\n",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        trigger_response = client.post(
            "/admin/v1/source-repositories/layout-detection",
            json={"repo_id": "aspose.ocr.apiref"},
            headers=ADMIN_HEADERS,
        )
        assert trigger_response.status_code == 200
        trigger_body = trigger_response.json()
        assert trigger_body["status"] == "failed"
        assert trigger_body["layout_backend"] == "deterministic"
        assert trigger_body["results"] == []
        assert any(
            item["stream"] == "stderr" and "simulated layout detection failure" in item["line"]
            for item in trigger_body["logs"]
        )

        operation_id = trigger_body["operation_id"]
        operation_path = f"/admin/v1/source-repositories/layout-detection/{operation_id}"
        fetch_response = client.get(operation_path, headers=ADMIN_HEADERS)
        assert fetch_response.status_code == 200
        assert fetch_response.json()["status"] == "failed"


def test_source_layout_detection_api_manual_override_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_set_manual_override(
        self: SourceLayoutDetectionOrchestrationService,
        *,
        repo_id: str,
        override_payload: dict[str, object],
    ) -> SourceLayoutDetectionResult:
        assert repo_id == "aspose.ocr.docs"
        assert override_payload["layout_type"] == "doc_locale/programming_language/content"
        return SourceLayoutDetectionResult(
            repo_id="aspose.ocr.docs",
            layout_type="doc_locale/programming_language/content",
            confidence=1.0,
            confidence_threshold=0.8,
            confidence_policy_status="manual_override_applied",
            manual_override_applied=True,
            dimensions=(
                {
                    "depth": 1,
                    "semantic": "doc_locale",
                    "values_sample": ["english"],
                },
            ),
            sample_markdown_paths=("english/net/getting-started/_index.md",),
            detector_version="layout-detector.manual-override.v1",
        )

    monkeypatch.setattr(
        SourceLayoutDetectionOrchestrationService,
        "set_manual_override",
        _fake_set_manual_override,
    )

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, capture_output, text, check
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="[ok] layout detection completed\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    app = create_app()
    with TestClient(app) as client:
        override_response = client.post(
            "/admin/v1/source-repositories/layout-detection/aspose.ocr.docs/override",
            json={
                "enabled": True,
                "layout_type": "doc_locale/programming_language/content",
                "confidence": 1.0,
                "dimensions": [
                    {
                        "depth": 1,
                        "semantic": "doc_locale",
                        "values_sample": ["english"],
                    }
                ],
                "sample_markdown_paths": ["english/net/getting-started/_index.md"],
                "detector_version": "layout-detector.manual-override.v1",
            },
            headers=ADMIN_HEADERS,
        )
        assert override_response.status_code == 200
        override_body = override_response.json()
        assert override_body["repo_id"] == "aspose.ocr.docs"
        assert override_body["manual_override_applied"] is True
        assert override_body["confidence_policy_status"] == "manual_override_applied"
        assert override_body["layout_type"] == "doc_locale/programming_language/content"
