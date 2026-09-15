"""Runtime policy resolver for ingestion/layout LLM backend selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class IngestionLLMBackend(StrEnum):
    """Supported backend ids for ingestion-time LLM operations."""

    DETERMINISTIC = "deterministic"
    OPENAI_COMPATIBLE = "openai_compatible"
    EXTERNAL_ASSISTANT = "external_assistant"


class IngestionLLMTask(StrEnum):
    """Logical task lanes that can use LLM runtime policy."""

    CONVERSION = "conversion"
    LAYOUT_DETECTION = "layout_detection"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleBackendConfig:
    """Connection profile for an OpenAI-compatible backend."""

    base_url: str
    model: str
    api_key_env_var: str | None
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class IngestionLLMRuntimePolicy:
    """Ingestion runtime policy with per-task backend selection."""

    enabled: bool
    default_backend: IngestionLLMBackend
    conversion_backend: IngestionLLMBackend
    layout_detection_backend: IngestionLLMBackend
    external_assistants_allowed: bool
    openai_compatible: OpenAICompatibleBackendConfig

    @classmethod
    def disabled(cls) -> IngestionLLMRuntimePolicy:
        """Return deterministic-only policy."""
        return cls(
            enabled=False,
            default_backend=IngestionLLMBackend.DETERMINISTIC,
            conversion_backend=IngestionLLMBackend.DETERMINISTIC,
            layout_detection_backend=IngestionLLMBackend.DETERMINISTIC,
            external_assistants_allowed=False,
            openai_compatible=OpenAICompatibleBackendConfig(
                base_url="http://localhost:11434/v1",
                model="gpt-oss",
                api_key_env_var="ADCS_INGESTION_LLM_API_KEY",
                timeout_seconds=20.0,
            ),
        )

    @classmethod
    def from_config_file(
        cls,
        *,
        config_path: str | Path,
    ) -> IngestionLLMRuntimePolicy:
        """Load ingestion runtime policy from JSON file with deterministic fallback."""
        resolved_path = Path(config_path)
        if not resolved_path.exists():
            return cls.disabled()

        raw_payload = resolved_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_payload)
        if not isinstance(parsed, dict):
            msg = "ingestion_llm_policy config must be a JSON object."
            raise ValueError(msg)

        defaults = cls.disabled()
        enabled = bool(parsed.get("enabled", defaults.enabled))
        default_backend = _parse_backend(
            parsed.get("default_backend", defaults.default_backend.value),
            field_name="default_backend",
        )
        conversion_backend = _parse_backend(
            parsed.get("conversion_backend", default_backend.value),
            field_name="conversion_backend",
        )
        layout_detection_backend = _parse_backend(
            parsed.get("layout_detection_backend", default_backend.value),
            field_name="layout_detection_backend",
        )
        external_assistants_allowed = bool(
            parsed.get("external_assistants_allowed", defaults.external_assistants_allowed)
        )
        backend_payload = parsed.get("openai_compatible")
        backend_defaults = defaults.openai_compatible
        if backend_payload is None:
            backend_config = backend_defaults
        else:
            if not isinstance(backend_payload, dict):
                msg = "`openai_compatible` must be a JSON object when provided."
                raise ValueError(msg)
            backend_config = OpenAICompatibleBackendConfig(
                base_url=str(
                    backend_payload.get("base_url", backend_defaults.base_url)
                ).rstrip("/"),
                model=str(backend_payload.get("model", backend_defaults.model)),
                api_key_env_var=(
                    str(backend_payload["api_key_env_var"])
                    if "api_key_env_var" in backend_payload
                    and backend_payload["api_key_env_var"] is not None
                    else backend_defaults.api_key_env_var
                ),
                timeout_seconds=float(
                    backend_payload.get("timeout_seconds", backend_defaults.timeout_seconds)
                ),
            )

        return cls(
            enabled=enabled,
            default_backend=default_backend,
            conversion_backend=conversion_backend,
            layout_detection_backend=layout_detection_backend,
            external_assistants_allowed=external_assistants_allowed,
            openai_compatible=backend_config,
        )

    def resolve_backend(self, *, task: IngestionLLMTask) -> IngestionLLMBackend:
        """Resolve backend for task, applying policy safety fallbacks."""
        if not self.enabled:
            return IngestionLLMBackend.DETERMINISTIC

        requested_backend = (
            self.conversion_backend
            if task is IngestionLLMTask.CONVERSION
            else self.layout_detection_backend
        )
        if (
            requested_backend is IngestionLLMBackend.EXTERNAL_ASSISTANT
            and not self.external_assistants_allowed
        ):
            return IngestionLLMBackend.OPENAI_COMPATIBLE
        return requested_backend

    def safe_summary(self) -> dict[str, object]:
        """Return redacted policy summary for telemetry/logging."""
        return {
            "enabled": self.enabled,
            "default_backend": self.default_backend.value,
            "conversion_backend": self.conversion_backend.value,
            "layout_detection_backend": self.layout_detection_backend.value,
            "external_assistants_allowed": self.external_assistants_allowed,
            "openai_compatible_base_url": self.openai_compatible.base_url,
            "openai_compatible_model": self.openai_compatible.model,
            "openai_compatible_api_key_env_var": self.openai_compatible.api_key_env_var,
            "openai_compatible_timeout_seconds": self.openai_compatible.timeout_seconds,
        }


def _parse_backend(raw_value: object, *, field_name: str) -> IngestionLLMBackend:
    if not isinstance(raw_value, str):
        msg = f"`{field_name}` must be a string."
        raise ValueError(msg)
    normalized = raw_value.strip().lower()
    try:
        return IngestionLLMBackend(normalized)
    except ValueError as exc:
        msg = f"`{field_name}` has unsupported value `{raw_value}`."
        raise ValueError(msg) from exc
