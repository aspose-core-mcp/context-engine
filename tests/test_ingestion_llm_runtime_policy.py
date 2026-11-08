from __future__ import annotations

import json
from pathlib import Path

import pytest

from adcs.ingestion.llm_runtime_policy import (
    IngestionLLMBackend,
    IngestionLLMRuntimePolicy,
    IngestionLLMTask,
)


def test_ingestion_llm_runtime_policy_disabled_when_file_missing(tmp_path: Path) -> None:
    policy = IngestionLLMRuntimePolicy.from_config_file(
        config_path=tmp_path / "missing-policy.json"
    )
    assert policy.enabled is False
    assert (
        policy.resolve_backend(task=IngestionLLMTask.CONVERSION)
        is IngestionLLMBackend.DETERMINISTIC
    )
    assert (
        policy.resolve_backend(task=IngestionLLMTask.LAYOUT_DETECTION)
        is IngestionLLMBackend.DETERMINISTIC
    )


def test_ingestion_llm_runtime_policy_oss120b_resolution(tmp_path: Path) -> None:
    config_path = tmp_path / "ingestion_llm_policy.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "default_backend": "deterministic",
                "conversion_backend": "openai_compatible",
                "layout_detection_backend": "openai_compatible",
                "external_assistants_allowed": False,
                "openai_compatible": {
                    "base_url": "https://llm.example.com/v1",
                    "model": "gpt-oss",
                    "api_key_env_var": "ADCS_INGESTION_LLM_API_KEY",
                    "timeout_seconds": 15.0,
                },
            }
        ),
        encoding="utf-8",
    )

    policy = IngestionLLMRuntimePolicy.from_config_file(config_path=config_path)
    assert policy.enabled is True
    assert (
        policy.resolve_backend(task=IngestionLLMTask.CONVERSION)
        is IngestionLLMBackend.OPENAI_COMPATIBLE
    )
    assert (
        policy.resolve_backend(task=IngestionLLMTask.LAYOUT_DETECTION)
        is IngestionLLMBackend.OPENAI_COMPATIBLE
    )
    assert policy.safe_summary()["openai_compatible_model"] == "gpt-oss"


def test_ingestion_llm_runtime_policy_blocks_external_when_not_allowed(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "ingestion_llm_policy.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "default_backend": "deterministic",
                "conversion_backend": "external_assistant",
                "layout_detection_backend": "external_assistant",
                "external_assistants_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    policy = IngestionLLMRuntimePolicy.from_config_file(config_path=config_path)
    assert (
        policy.resolve_backend(task=IngestionLLMTask.CONVERSION)
        is IngestionLLMBackend.OPENAI_COMPATIBLE
    )


def test_ingestion_llm_runtime_policy_rejects_invalid_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "ingestion_llm_policy.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "default_backend": "invalid-backend",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        IngestionLLMRuntimePolicy.from_config_file(config_path=config_path)
