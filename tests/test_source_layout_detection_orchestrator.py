from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import adcs.ingestion.source_layout_detection_orchestrator as source_layout_detection_orchestrator
from adcs.ingestion.llm_runtime_policy import (
    IngestionLLMBackend,
    IngestionLLMRuntimePolicy,
    OpenAICompatibleBackendConfig,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOrchestrationService,
    SourceLayoutDetectionStatus,
)


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def _make_layout_registry_payload() -> dict[str, Any]:
    return {
        "source_roots": [
            {"root_id": "apiref-root", "source_kind": "apiref", "path": "source-repo-apiref"},
            {"root_id": "docs-root", "source_kind": "docs", "path": "source-repo-docs"},
        ],
        "repositories": [
            {
                "repo_id": "aspose.ocr.apiref",
                "layout_detection": {
                    "layout_type": "doc_locale/programming_language/namespace",
                    "confidence": 0.99,
                    "dimensions": [
                        {
                            "depth": 1,
                            "semantic": "doc_locale",
                            "values_sample": ["english"],
                        }
                    ],
                    "sample_markdown_paths": ["english/net/aspose.ocr/_index.md"],
                    "detector_version": "layout-detector.v1",
                },
            },
            {
                "repo_id": "aspose.ocr.docs",
                "layout_detection": {
                    "layout_type": "programming_language/content",
                    "confidence": 0.97,
                    "dimensions": [
                        {
                            "depth": 1,
                            "semantic": "programming_language",
                            "values_sample": ["net", "java"],
                        }
                    ],
                    "sample_markdown_paths": ["net/getting-started/_index.md"],
                    "detector_version": "layout-detector.v1",
                },
            },
        ],
    }


def test_source_layout_detection_orchestrator_run_success_records_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "layout" / "detect_source_layouts.py"
    registry_path = _write_registry(tmp_path, _make_layout_registry_payload())
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        detection_script_path=script_path,
        registry_path=registry_path,
        python_executable="python3",
    )

    expected_command = [
        "python3",
        str(script_path),
        "--registry",
        str(registry_path),
        "--write",
        "--repo-id",
        "aspose.ocr.apiref",
        "--repo-id",
        "aspose.ocr.docs",
    ]

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == expected_command
        assert cwd == workspace_root
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] detected\n[ok] wrote registry\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    operation = service.run(repo_ids=("aspose.ocr.apiref", "aspose.ocr.docs"))

    assert operation.status is SourceLayoutDetectionStatus.COMPLETED
    assert operation.layout_backend == "deterministic"
    assert operation.repo_ids == ("aspose.ocr.apiref", "aspose.ocr.docs")
    assert operation.started_at is not None
    assert operation.finished_at is not None
    assert operation.finished_at >= operation.started_at
    assert [(line.stream, line.line) for line in operation.logs] == [
        ("stdout", "[runtime_policy] task=layout_detection backend=deterministic"),
        ("stdout", "[ok] detected"),
        ("stdout", "[ok] wrote registry"),
    ]

    by_repo = {result.repo_id: result for result in operation.results}
    assert by_repo["aspose.ocr.apiref"].layout_type == "doc_locale/programming_language/namespace"
    assert by_repo["aspose.ocr.apiref"].detector_version == "layout-detector.v1"
    assert by_repo["aspose.ocr.apiref"].confidence_policy_status == "accepted"
    assert by_repo["aspose.ocr.apiref"].manual_override_applied is False
    assert by_repo["aspose.ocr.apiref"].sample_markdown_paths == (
        "english/net/aspose.ocr/_index.md",
    )
    assert by_repo["aspose.ocr.docs"].layout_type == "programming_language/content"
    assert by_repo["aspose.ocr.docs"].dimensions == (
        {
            "depth": 1,
            "semantic": "programming_language",
            "values_sample": ["net", "java"],
        },
    )


def test_source_layout_detection_orchestrator_run_failure_records_failed_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "layout" / "detect_source_layouts.py"
    registry_path = _write_registry(tmp_path, _make_layout_registry_payload())
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        detection_script_path=script_path,
        registry_path=registry_path,
        python_executable="python3",
    )

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert "--write" in command
        assert cwd == workspace_root
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=2,
            stdout="",
            stderr="[error] detection failed\n",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceLayoutDetectionStatus.FAILED
    assert operation.layout_backend == "deterministic"
    assert operation.repo_ids == ("aspose.ocr.docs",)
    assert operation.results == ()
    assert operation.started_at is not None
    assert operation.finished_at is not None
    assert operation.finished_at >= operation.started_at
    assert [(line.stream, line.line) for line in operation.logs] == [
        ("stdout", "[runtime_policy] task=layout_detection backend=deterministic"),
        ("stderr", "[error] detection failed")
    ]


def test_source_layout_detection_orchestrator_exposes_expected_aspose_ocr_layout_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = Path(__file__).resolve().parents[1]
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        python_executable="python3",
    )

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert "--write" in command
        assert "--repo-id" in command
        assert cwd == workspace_root
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="[ok] integrated detection\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)

    operation = service.run(repo_ids=("aspose.ocr.apiref", "aspose.ocr.docs"))

    assert operation.status is SourceLayoutDetectionStatus.COMPLETED
    assert operation.layout_backend == "deterministic"
    layout_types_by_repo = {result.repo_id: result.layout_type for result in operation.results}
    assert layout_types_by_repo["aspose.ocr.apiref"] == "doc_locale/programming_language/namespace"
    assert layout_types_by_repo["aspose.ocr.docs"] == "programming_language/content"


def test_source_layout_detection_applies_manual_override_from_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _make_layout_registry_payload()
    payload["repositories"][1]["layout_detection"]["manual_override"] = {
        "enabled": True,
        "layout_type": "doc_locale/programming_language/content",
        "confidence": 1.0,
        "dimensions": [{"depth": 1, "semantic": "doc_locale", "values_sample": ["english"]}],
        "sample_markdown_paths": ["english/net/getting-started/_index.md"],
        "detector_version": "layout-detector.manual-override.v1",
    }
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "layout" / "detect_source_layouts.py"
    registry_path = _write_registry(tmp_path, payload)
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        detection_script_path=script_path,
        registry_path=registry_path,
        python_executable="python3",
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
            stdout="[ok] detected\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)
    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.status is SourceLayoutDetectionStatus.COMPLETED
    assert operation.results[0].manual_override_applied is True
    assert operation.results[0].confidence_policy_status == "manual_override_applied"
    assert operation.results[0].layout_type == "doc_locale/programming_language/content"
    assert operation.results[0].detector_version == "layout-detector.manual-override.v1"
    assert any(log.line.startswith("[manual_override]") for log in operation.logs)


def test_source_layout_detection_marks_low_confidence_without_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _make_layout_registry_payload()
    payload["repositories"][0]["layout_detection"]["confidence"] = 0.35
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "layout" / "detect_source_layouts.py"
    registry_path = _write_registry(tmp_path, payload)
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        detection_script_path=script_path,
        registry_path=registry_path,
        python_executable="python3",
        confidence_threshold=0.80,
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
            stdout="[ok] detected\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)
    operation = service.run(repo_ids=("aspose.ocr.apiref",))

    assert operation.status is SourceLayoutDetectionStatus.COMPLETED
    assert operation.results[0].confidence_policy_status == "low_confidence_requires_override"
    assert any(log.line.startswith("[low_confidence]") for log in operation.logs)


def test_source_layout_detection_llm_assisted_backend_enriches_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path
    script_path = workspace_root / "scripts" / "sources" / "layout" / "detect_source_layouts.py"
    registry_path = _write_registry(tmp_path, _make_layout_registry_payload())
    policy = IngestionLLMRuntimePolicy(
        enabled=True,
        default_backend=IngestionLLMBackend.OPENAI_COMPATIBLE,
        conversion_backend=IngestionLLMBackend.DETERMINISTIC,
        layout_detection_backend=IngestionLLMBackend.OPENAI_COMPATIBLE,
        external_assistants_allowed=False,
        openai_compatible=OpenAICompatibleBackendConfig(
            base_url="https://llm.example.com/v1",
            model="gpt-oss",
            api_key_env_var="ADCS_INGESTION_LLM_API_KEY",
            timeout_seconds=20.0,
        ),
    )
    service = SourceLayoutDetectionOrchestrationService(
        workspace_root=workspace_root,
        detection_script_path=script_path,
        registry_path=registry_path,
        python_executable="python3",
        llm_runtime_policy=policy,
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
            stdout="[ok] detected\n",
            stderr="",
        )

    monkeypatch.setattr(source_layout_detection_orchestrator.subprocess, "run", _fake_run)
    operation = service.run(repo_ids=("aspose.ocr.docs",))

    assert operation.layout_backend == "openai_compatible"
    assert operation.results[0].confidence_policy_status == "accepted_llm_assisted"
    # When the detection is certain (uncertain=False/absent), the LLM hook returns
    # early and does not mutate detector_version or confidence.
    assert operation.results[0].detector_version == "layout-detector.v1"
