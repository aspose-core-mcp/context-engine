from __future__ import annotations

import json
from pathlib import Path

import pytest

from adcs.ingestion.llm_runtime_policy import IngestionLLMBackend
from adcs.ingestion.prompt_registry import (
    ConversionPromptAssignment,
    IngestionPromptRegistry,
)


def _write_prompt_registry_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    config_path = tmp_path / "config" / "ingestion_prompt_registry.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def test_prompt_registry_deterministically_assigns_variant_for_same_source_path(
    tmp_path: Path,
) -> None:
    config_path = _write_prompt_registry_config(
        tmp_path,
        {
            "enabled": True,
            "registry_version": "2026-03-04.v1",
            "conversion_experiment": {
                "experiment_id": "conversion.ab.v1",
                "assignment_unit": "source_path",
                "seed": "seed-123",
                "variants": [
                    {
                        "variant_id": "variant-a",
                        "weight_pct": 40,
                        "prompt_pack_version": "v1a",
                        "system_prompt_path": "prompts/hugo_conversion/system.v1.txt",
                        "user_base_prompt_path": "prompts/hugo_conversion/user.base.v1.txt",
                        "user_docs_prompt_path": "prompts/hugo_conversion/user.docs.v1.txt",
                        "user_apiref_prompt_path": "prompts/hugo_conversion/user.apiref.v1.txt",
                    },
                    {
                        "variant_id": "variant-b",
                        "weight_pct": 60,
                        "prompt_pack_version": "v1b",
                        "system_prompt_path": "prompts/hugo_conversion/system.v1.txt",
                        "user_base_prompt_path": "prompts/hugo_conversion/user.base.v1.txt",
                        "user_docs_prompt_path": "prompts/hugo_conversion/user.docs.v1.txt",
                        "user_apiref_prompt_path": "prompts/hugo_conversion/user.apiref.v1.txt",
                    },
                ],
            },
        },
    )
    registry = IngestionPromptRegistry.from_config_file(config_path=config_path)

    first = registry.assign(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_path="source-repo-docs/Aspose.OCR/net/getting-started/_index.md",
        fallback_backend=IngestionLLMBackend.DETERMINISTIC,
    )
    second = registry.assign(
        repo_id="aspose.ocr.docs",
        source_kind="docs",
        source_path="source-repo-docs/Aspose.OCR/net/getting-started/_index.md",
        fallback_backend=IngestionLLMBackend.OPENAI_COMPATIBLE,
    )

    assert first.variant_id == second.variant_id
    assert first.prompt_pack_version == second.prompt_pack_version
    assert first.user_prompt_path.endswith("user.docs.v1.txt")
    assert second.user_prompt_path.endswith("user.docs.v1.txt")
    assert second.backend is IngestionLLMBackend.OPENAI_COMPATIBLE


def test_prompt_registry_evaluation_produces_variant_metrics() -> None:
    registry = IngestionPromptRegistry.disabled()
    assignments = (
        ConversionPromptAssignment(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_path="docs/a.md",
            variant_id="variant-a",
            prompt_pack_version="v1a",
            system_prompt_path="system.v1",
            user_prompt_path="user.docs.v1",
            backend=IngestionLLMBackend.DETERMINISTIC,
        ),
        ConversionPromptAssignment(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_path="docs/b.md",
            variant_id="variant-a",
            prompt_pack_version="v1a",
            system_prompt_path="system.v1",
            user_prompt_path="user.docs.v1",
            backend=IngestionLLMBackend.DETERMINISTIC,
        ),
        ConversionPromptAssignment(
            repo_id="aspose.ocr.docs",
            source_kind="docs",
            source_path="docs/c.md",
            variant_id="variant-b",
            prompt_pack_version="v1b",
            system_prompt_path="system.v1",
            user_prompt_path="user.docs.v1",
            backend=IngestionLLMBackend.DETERMINISTIC,
        ),
    )

    summary = registry.evaluate(
        assignments=assignments,
        failed_source_paths=("docs/b.md",),
        parse_warnings_by_source_path={"docs/a.md": 1, "docs/c.md": 3},
    )

    assert summary.total_assigned_count == 3
    assert summary.successful_count == 2
    assert summary.failed_count == 1
    assert summary.parse_warnings_count == 4
    metrics = {item.variant_id: item for item in summary.variants}
    assert metrics["variant-a"].assigned_count == 2
    assert metrics["variant-a"].failed_count == 1
    assert metrics["variant-a"].success_rate == 0.5
    assert metrics["variant-b"].assigned_count == 1
    assert metrics["variant-b"].failed_count == 0
    assert metrics["variant-b"].success_rate == 1.0
    assert summary.best_variant_id == "variant-b"


def test_prompt_registry_rejects_invalid_variant_weight_sum(tmp_path: Path) -> None:
    config_path = _write_prompt_registry_config(
        tmp_path,
        {
            "enabled": True,
            "registry_version": "2026-03-04.v1",
            "conversion_experiment": {
                "experiment_id": "conversion.ab.v1",
                "assignment_unit": "source_path",
                "seed": "seed-123",
                "variants": [
                    {
                        "variant_id": "variant-a",
                        "weight_pct": 70,
                        "prompt_pack_version": "v1a",
                    },
                    {
                        "variant_id": "variant-b",
                        "weight_pct": 20,
                        "prompt_pack_version": "v1b",
                    },
                ],
            },
        },
    )

    with pytest.raises(ValueError, match="weight_pct sum must equal 100"):
        IngestionPromptRegistry.from_config_file(config_path=config_path)

