"""End-to-end checks that the strict English-only gate halts ingestion.

When ``english_only_strict=True`` the orchestrator must block a repository that
has no English content (or an unresolvable locale/language schema) and emit a
severity-1 ``INGESTION_CRITICAL_FAIL`` critical event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ops import CriticalEventType


def _registry_payload() -> dict[str, Any]:
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


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def _write_page(tmp_path: Path, relative_path: str, title: str) -> None:
    repo_root = tmp_path / "source-repo-docs" / "Aspose.OCR"
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\ntitle: {title}\n---\n## Intro\nWelcome.\n", encoding="utf-8")


def _run(tmp_path: Path) -> Any:
    registry_path = _write_registry(tmp_path, _registry_payload())
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry_path,
        source_revision_resolver=lambda _: "revision-abc123",
        english_only_strict=True,
    )
    return service.run(repo_ids=("aspose.ocr.docs",)).results[0]


def test_strict_gate_blocks_repo_with_no_english_documents(tmp_path: Path) -> None:
    # Only a non-English (ru) page exists -> rule 1: English version missing.
    _write_page(tmp_path, "ru/net/getting-started/_index.md", "Nachalo")

    result = _run(tmp_path)

    assert result.indexing_summary.decision.value == "publish_blocked"
    assert result.indexing_summary.publish_blocked_reason == "english_only_gate_failed"
    assert (
        CriticalEventType.INGESTION_CRITICAL_FAIL.value
        in result.indexing_summary.event_summary.event_types
    )


def test_strict_gate_allows_repo_with_english_documents(tmp_path: Path) -> None:
    # English page (no locale prefix) -> gate passes; repo is not blocked by the gate.
    _write_page(tmp_path, "net/getting-started/_index.md", "Getting Started")

    result = _run(tmp_path)

    assert result.indexing_summary.publish_blocked_reason != "english_only_gate_failed"
