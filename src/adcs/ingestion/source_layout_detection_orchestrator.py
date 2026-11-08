"""In-memory orchestration service for source layout detection operations."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib import request as urllib_request
from uuid import uuid4

import yaml

from adcs.ingestion.llm_runtime_policy import (
    IngestionLLMBackend,
    IngestionLLMRuntimePolicy,
    IngestionLLMTask,
    OpenAICompatibleBackendConfig,
)
from adcs.ingestion.operation_state_store import FileSystemOperationStateStore

# ---------------------------------------------------------------------------
# LLM verifier contract and concrete implementation
# ---------------------------------------------------------------------------

_VERIFY_SYSTEM_PROMPT = (
    "You are a source-layout verification assistant for a documentation indexing system. "
    "You are given a partially-resolved layout detection result and sample file paths from "
    "a documentation repository. Your task is to confirm or correct the detected directory "
    "layout dimensions. "
    "A 'dimension' describes one path-segment level with fields: "
    "  semantic — one of: programming_language, doc_locale, doc_type, namespace, version, "
    "product_id, unknown. "
    "  level — 1-based integer depth of that segment in the path. "
    "Return ONLY a JSON object with this exact schema, nothing else: "
    '{"verdict": "confirm"|"correct"|"cannot_determine", '
    '"dimensions"?: [{"semantic": str, "level": int}, ...], '
    '"layout_type"?: str, '
    '"rationale"?: str}'
)


class LayoutLLMVerifier(Protocol):
    """Protocol for LLM-backed layout verification."""

    def verify(self, *, detection: dict[str, Any]) -> dict[str, Any]:
        """Return a verdict dict: {verdict, dimensions?, layout_type?, rationale?}."""
        ...


class OpenAICompatibleLayoutVerifier:
    """Concrete verifier that calls the OpenAI-compatible LLM runtime."""

    def __init__(self, *, backend_config: OpenAICompatibleBackendConfig) -> None:
        self._config = backend_config
        api_key_env = backend_config.api_key_env_var
        self._api_key: str | None = os.environ.get(api_key_env) if api_key_env else None
        self._ssl_context = ssl.create_default_context()

    def verify(self, *, detection: dict[str, Any]) -> dict[str, Any]:
        """Call the LLM to confirm/correct/reject the uncertain layout detection."""
        dimensions = detection.get("dimensions", [])
        sample_paths = detection.get("sample_markdown_paths", [])
        user_content = (
            f"Detected dimensions: {json.dumps(dimensions)}\n"
            f"Sample markdown paths: {json.dumps(sample_paths[:10])}\n"
            "Is this layout detection correct? "
            "Return ONLY the JSON verdict object described in the system prompt."
        )
        try:
            return self._chat_completion(
                messages=(
                    {"role": "system", "content": _VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                )
            )
        except Exception:
            return {"verdict": "cannot_determine"}

    def _chat_completion(
        self,
        *,
        messages: tuple[dict[str, str], ...],
    ) -> dict[str, Any]:
        endpoint = f"{self._config.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": 0.0,
            "max_tokens": 512,
            "messages": list(messages),
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request_payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        req = urllib_request.Request(
            endpoint,
            data=request_payload,
            headers=headers,
            method="POST",
        )
        with urllib_request.urlopen(
            req,
            timeout=self._config.timeout_seconds,
            context=self._ssl_context,
        ) as response:
            raw = response.read()
        parsed_response = json.loads(raw.decode("utf-8"))
        content = _extract_llm_content(parsed_response)
        # Strip optional markdown fences before JSON parse
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```")[1]
            if stripped.startswith("json"):
                stripped = stripped[4:]
            stripped = stripped.strip()
        result = json.loads(stripped)
        if not isinstance(result, dict):
            return {"verdict": "cannot_determine"}
        return result


def _extract_llm_content(parsed: Any) -> str:
    """Extract text content from an OpenAI-compatible chat completion response."""
    choices = parsed.get("choices") if isinstance(parsed, dict) else None
    if not isinstance(choices, list) or not choices:
        msg = "LLM response missing choices."
        raise ValueError(msg)
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        msg = "LLM response choice missing message."
        raise ValueError(msg)
    content = message.get("content")
    if not isinstance(content, str):
        msg = "LLM response message missing content."
        raise ValueError(msg)
    return content


class SourceLayoutDetectionStatus(StrEnum):
    """Operation execution status for source layout detection."""

    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


class SourceLayoutDetectionOperationNotFoundError(KeyError):
    """Raised when an operation id does not exist in in-memory storage."""


@dataclass(frozen=True, slots=True)
class SourceLayoutDetectionLogLine:
    """Normalized layout detection operation log line."""

    stream: str
    line: str


@dataclass(frozen=True, slots=True)
class SourceLayoutDetectionResult:
    """Layout detection metadata exposed to Stage-A ingestion workflow."""

    repo_id: str
    layout_type: str
    confidence: float
    dimensions: tuple[dict[str, Any], ...]
    sample_markdown_paths: tuple[str, ...]
    detector_version: str
    confidence_threshold: float = 0.0
    confidence_policy_status: str = "accepted"
    manual_override_applied: bool = False


@dataclass(frozen=True, slots=True)
class SourceLayoutDetectionOperation:
    """Source layout detection operation record stored in memory."""

    operation_id: str
    status: SourceLayoutDetectionStatus
    repo_ids: tuple[str, ...]
    logs: tuple[SourceLayoutDetectionLogLine, ...]
    results: tuple[SourceLayoutDetectionResult, ...]
    started_at: datetime | None
    finished_at: datetime | None
    layout_backend: str = IngestionLLMBackend.DETERMINISTIC.value


class SourceLayoutDetectionOrchestrationService:
    """Run source layout detection script operations with in-memory status tracking."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        detection_script_path: str | Path | None = None,
        registry_path: str | Path | None = None,
        python_executable: str | None = None,
        llm_runtime_policy: IngestionLLMRuntimePolicy | None = None,
        confidence_threshold: float = 0.80,
        allow_manual_override: bool = True,
        operation_state_store: (
            FileSystemOperationStateStore[SourceLayoutDetectionOperation] | None
        ) = None,
    ) -> None:
        default_workspace_root = Path(__file__).resolve().parents[3]
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else default_workspace_root.resolve()
        )

        default_script_path = self._workspace_root / "scripts" / "sources" / "layout" / (
            "detect_source_layouts.py"
        )
        self._detection_script_path = (
            Path(detection_script_path).resolve()
            if detection_script_path is not None
            else default_script_path.resolve()
        )

        default_registry_path = self._workspace_root / "config" / "source-repositories.yaml"
        if not default_registry_path.exists():
            default_registry_path = self._workspace_root / "config" / "source-repositories.json"
        self._registry_path = (
            Path(registry_path).resolve()
            if registry_path is not None
            else default_registry_path.resolve()
        )

        self._python_executable = python_executable or sys.executable
        self._llm_runtime_policy = llm_runtime_policy or IngestionLLMRuntimePolicy.disabled()
        self._confidence_threshold = _normalize_confidence_threshold(confidence_threshold)
        self._allow_manual_override = bool(allow_manual_override)
        self._operation_state_store = operation_state_store or FileSystemOperationStateStore(
            namespace="layout-detection",
            record_type=SourceLayoutDetectionOperation,
            workspace_root=self._workspace_root,
        )

        self._lock = Lock()
        self._operations: dict[str, SourceLayoutDetectionOperation] = {}
        self._operation_order: list[str] = []

    def run(
        self,
        *,
        repo_ids: Sequence[str] | None = None,
        execute_immediately: bool = True,
    ) -> SourceLayoutDetectionOperation:
        """Execute one source layout detection operation and persist its result in memory."""
        normalized_repo_ids = _normalize_repo_ids(repo_ids)
        layout_backend = self._llm_runtime_policy.resolve_backend(
            task=IngestionLLMTask.LAYOUT_DETECTION
        )
        operation = SourceLayoutDetectionOperation(
            operation_id=str(uuid4()),
            status=SourceLayoutDetectionStatus.QUEUED,
            repo_ids=normalized_repo_ids,
            logs=(),
            results=(),
            started_at=None,
            finished_at=None,
            layout_backend=layout_backend.value,
        )
        self._save_operation(operation, append_new=True)
        if not execute_immediately:
            return operation
        return self.execute_operation(operation.operation_id)

    def execute_operation(self, operation_id: str) -> SourceLayoutDetectionOperation:
        """Execute one queued source layout-detection operation by id."""
        operation = self.get_operation(operation_id)
        if operation.status in {
            SourceLayoutDetectionStatus.RUNNING,
            SourceLayoutDetectionStatus.COMPLETED,
        }:
            return operation

        operation = replace(
            operation,
            status=SourceLayoutDetectionStatus.RUNNING,
            started_at=_now_utc(),
        )
        self._save_operation(operation)

        command = self._build_command(repo_ids=operation.repo_ids)
        try:
            completed = self._run_command(command)
        except OSError as exc:
            failed_operation = replace(
                operation,
                status=SourceLayoutDetectionStatus.FAILED,
                logs=(
                    SourceLayoutDetectionLogLine(
                        stream="stderr",
                        line=f"[error] {exc.__class__.__name__}: {exc}",
                    ),
                ),
                finished_at=_now_utc(),
            )
            self._save_operation(failed_operation)
            return failed_operation

        logs = self._collect_logs(stdout=completed.stdout, stderr=completed.stderr)
        policy_log = SourceLayoutDetectionLogLine(
            stream="stdout",
            line=(
                "[runtime_policy] "
                f"task=layout_detection backend={operation.layout_backend}"
            ),
        )
        logs = (policy_log,) + logs
        if completed.returncode != 0:
            if not logs:
                logs = (
                    SourceLayoutDetectionLogLine(
                        stream="stderr",
                        line=f"[error] Process exited with code {completed.returncode}.",
                    ),
                )
            failed_operation = replace(
                operation,
                status=SourceLayoutDetectionStatus.FAILED,
                logs=logs,
                finished_at=_now_utc(),
            )
            self._save_operation(failed_operation)
            return failed_operation

        try:
            results = self._load_detection_results(
                repo_ids=operation.repo_ids,
                layout_backend=IngestionLLMBackend(operation.layout_backend),
            )
        except (
            FileNotFoundError,
            ValueError,
            json.JSONDecodeError,
            yaml.YAMLError,
            TypeError,
        ) as exc:
            failed_logs = list(logs)
            failed_logs.append(
                SourceLayoutDetectionLogLine(
                    stream="stderr",
                    line=f"[error] Failed to load layout detection metadata: {exc}",
                )
            )
            failed_operation = replace(
                operation,
                status=SourceLayoutDetectionStatus.FAILED,
                logs=tuple(failed_logs),
                finished_at=_now_utc(),
            )
            self._save_operation(failed_operation)
            return failed_operation

        logs = logs + self._build_policy_logs(results=results)

        finished_operation = replace(
            operation,
            status=SourceLayoutDetectionStatus.COMPLETED,
            logs=logs,
            results=results,
            finished_at=_now_utc(),
        )
        self._save_operation(finished_operation)
        return finished_operation

    def get_operation(self, operation_id: str) -> SourceLayoutDetectionOperation:
        """Return one operation by id."""
        with self._lock:
            operation = self._operations.get(operation_id)
        persisted_state = self._operation_state_store.load(operation_id)
        if persisted_state is not None:
            self._save_operation(persisted_state, append_new=True)
            return persisted_state
        if operation is None:
            msg = f"Source layout detection operation `{operation_id}` was not found."
            raise SourceLayoutDetectionOperationNotFoundError(msg)
        return operation

    def list_operations(self, *, limit: int = 20) -> tuple[SourceLayoutDetectionOperation, ...]:
        """List recent operations ordered by most recent first."""
        if limit < 1:
            return ()

        with self._lock:
            operation_ids = list(reversed(self._operation_order[-limit:]))
            hydrated = [
                self._operations[operation_id] for operation_id in operation_ids
            ]
        results: list[SourceLayoutDetectionOperation] = []
        seen_operation_ids: set[str] = set()
        for operation in self._operation_state_store.list(limit=limit):
            results.append(operation)
            seen_operation_ids.add(operation.operation_id)
            self._save_operation(operation, append_new=True)
            if len(results) >= limit:
                return tuple(results[:limit])
        for operation in hydrated:
            if operation.operation_id in seen_operation_ids:
                continue
            results.append(operation)
            seen_operation_ids.add(operation.operation_id)
            if len(results) >= limit:
                break
        return tuple(results[:limit])

    def set_manual_override(
        self,
        *,
        repo_id: str,
        override_payload: dict[str, Any],
    ) -> SourceLayoutDetectionResult:
        """Persist manual layout override in registry and return effective result."""
        normalized_repo_id = repo_id.strip()
        if not normalized_repo_id:
            msg = "repo_id must not be empty."
            raise ValueError(msg)
        if not isinstance(override_payload, dict):
            msg = "override_payload must be an object."
            raise ValueError(msg)

        payload = self._read_registry_payload()
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            msg = "Invalid registry: `repositories` must be an array."
            raise ValueError(msg)

        target_repo: dict[str, Any] | None = None
        for repository in repositories:
            if isinstance(repository, dict) and repository.get("repo_id") == normalized_repo_id:
                target_repo = repository
                break
        if target_repo is None:
            msg = f"Unknown repo_id in registry: `{normalized_repo_id}`."
            raise ValueError(msg)

        layout_detection = target_repo.get("layout_detection")
        if not isinstance(layout_detection, dict):
            layout_detection = {}
            target_repo["layout_detection"] = layout_detection
        layout_detection["manual_override"] = {
            **override_payload,
            "updated_at_utc": _now_utc().isoformat(),
        }
        self._write_registry_payload(payload)

        results = self._load_detection_results(
            repo_ids=(normalized_repo_id,),
            layout_backend=IngestionLLMBackend.DETERMINISTIC,
        )
        if not results:
            msg = f"Failed to resolve layout detection result for `{normalized_repo_id}`."
            raise ValueError(msg)
        return results[0]

    def _build_command(self, *, repo_ids: tuple[str, ...]) -> list[str]:
        command = [
            self._python_executable,
            str(self._detection_script_path),
            "--registry",
            str(self._registry_path),
            "--write",
        ]
        for repo_id in repo_ids:
            command.extend(["--repo-id", repo_id])
        return command

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self._workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def _collect_logs(
        self,
        *,
        stdout: str,
        stderr: str,
    ) -> tuple[SourceLayoutDetectionLogLine, ...]:
        log_lines: list[SourceLayoutDetectionLogLine] = []

        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped:
                log_lines.append(SourceLayoutDetectionLogLine(stream="stdout", line=stripped))

        for line in stderr.splitlines():
            stripped = line.strip()
            if stripped:
                log_lines.append(SourceLayoutDetectionLogLine(stream="stderr", line=stripped))

        return tuple(log_lines)

    def _load_detection_results(
        self,
        *,
        repo_ids: tuple[str, ...],
        layout_backend: IngestionLLMBackend,
    ) -> tuple[SourceLayoutDetectionResult, ...]:
        payload = self._read_registry_payload()
        if not isinstance(payload, dict):
            raise ValueError("Invalid registry: top-level value must be an object.")
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            raise ValueError("Invalid registry: `repositories` must be an array.")

        selected_repositories = _select_repositories(repositories, repo_ids)
        verifier: LayoutLLMVerifier | None = (
            OpenAICompatibleLayoutVerifier(backend_config=self._llm_runtime_policy.openai_compatible)
            if layout_backend is not IngestionLLMBackend.DETERMINISTIC
            else None
        )
        results: list[SourceLayoutDetectionResult] = []
        for repo in selected_repositories:
            if not isinstance(repo, dict):
                raise ValueError("Invalid registry: repository entry must be an object.")
            repo_id = _read_required_string(repo, "repo_id", "repositories[*]")
            detection = repo.get("layout_detection")
            if not isinstance(detection, dict):
                msg = f"Missing `layout_detection` metadata for repo_id `{repo_id}`."
                raise ValueError(msg)
            effective_detection = dict(detection)
            if layout_backend is not IngestionLLMBackend.DETERMINISTIC:
                effective_detection = _apply_llm_assisted_enrichment(
                    detection=effective_detection,
                    backend=layout_backend,
                    verifier=verifier,
                )

            manual_override_applied = False
            if self._allow_manual_override:
                effective_detection, manual_override_applied = _apply_manual_override(
                    detection=effective_detection,
                    repo_id=repo_id,
                )

            dimensions = effective_detection.get("dimensions")
            if not isinstance(dimensions, list):
                msg = f"Invalid `layout_detection.dimensions` for repo_id `{repo_id}`."
                raise ValueError(msg)
            normalized_dimensions: list[dict[str, Any]] = []
            for dimension in dimensions:
                if not isinstance(dimension, dict):
                    msg = (
                        "Invalid `layout_detection.dimensions` entry for "
                        f"repo_id `{repo_id}`; expected object."
                    )
                    raise ValueError(msg)
                normalized_dimensions.append(dict(dimension))

            sample_paths = effective_detection.get("sample_markdown_paths")
            if not isinstance(sample_paths, list) or any(
                not isinstance(path, str) for path in sample_paths
            ):
                msg = f"Invalid `layout_detection.sample_markdown_paths` for repo_id `{repo_id}`."
                raise ValueError(msg)

            confidence_raw = effective_detection.get("confidence")
            if not isinstance(confidence_raw, (float, int)):
                msg = f"Invalid `layout_detection.confidence` for repo_id `{repo_id}`."
                raise ValueError(msg)
            confidence = float(confidence_raw)
            if manual_override_applied:
                policy_status = "manual_override_applied"
            elif confidence < self._confidence_threshold:
                policy_status = "low_confidence_requires_override"
            elif layout_backend is IngestionLLMBackend.DETERMINISTIC:
                policy_status = "accepted"
            else:
                policy_status = "accepted_llm_assisted"

            results.append(
                SourceLayoutDetectionResult(
                    repo_id=repo_id,
                    layout_type=_read_required_string(
                        effective_detection,
                        "layout_type",
                        f"layout_detection[{repo_id}]",
                    ),
                    confidence=confidence,
                    dimensions=tuple(normalized_dimensions),
                    sample_markdown_paths=tuple(sample_paths),
                    detector_version=_read_required_string(
                        effective_detection,
                        "detector_version",
                        f"layout_detection[{repo_id}]",
                    ),
                    confidence_threshold=self._confidence_threshold,
                    confidence_policy_status=policy_status,
                    manual_override_applied=manual_override_applied,
                )
            )

        return tuple(results)

    def _build_policy_logs(
        self,
        *,
        results: tuple[SourceLayoutDetectionResult, ...],
    ) -> tuple[SourceLayoutDetectionLogLine, ...]:
        log_lines: list[SourceLayoutDetectionLogLine] = []
        for result in results:
            if result.manual_override_applied:
                log_lines.append(
                    SourceLayoutDetectionLogLine(
                        stream="stdout",
                        line=(
                            f"[manual_override] repo_id={result.repo_id} "
                            f"layout_type={result.layout_type}"
                        ),
                    )
                )
            if result.confidence_policy_status == "low_confidence_requires_override":
                log_lines.append(
                    SourceLayoutDetectionLogLine(
                        stream="stderr",
                        line=(
                            f"[low_confidence] repo_id={result.repo_id} "
                            f"confidence={result.confidence:.3f} "
                            f"threshold={result.confidence_threshold:.3f}"
                        ),
                    )
                )
        return tuple(log_lines)

    def _read_registry_payload(self) -> dict[str, Any]:
        raw_payload = self._registry_path.read_text(encoding="utf-8")
        suffix = self._registry_path.suffix.casefold()
        if suffix == ".json":
            payload = json.loads(raw_payload)
        elif suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(raw_payload)
        else:
            raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json.")
        if not isinstance(payload, dict):
            msg = "Invalid registry: top-level value must be an object."
            raise ValueError(msg)
        return payload

    def _write_registry_payload(self, payload: dict[str, Any]) -> None:
        suffix = self._registry_path.suffix.casefold()
        if suffix == ".json":
            self._registry_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            mirror_path = self._registry_path.with_suffix(".yaml")
            if mirror_path.exists():
                mirror_path.write_text(
                    yaml.safe_dump(
                        payload,
                        sort_keys=False,
                        allow_unicode=False,
                        default_flow_style=False,
                    ),
                    encoding="utf-8",
                )
            return

        if suffix in {".yaml", ".yml"}:
            self._registry_path.write_text(
                yaml.safe_dump(
                    payload,
                    sort_keys=False,
                    allow_unicode=False,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
            mirror_path = self._registry_path.with_suffix(".json")
            if mirror_path.exists():
                mirror_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )
            return

        raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json.")

    def _save_operation(
        self, operation: SourceLayoutDetectionOperation, *, append_new: bool = False
    ) -> None:
        with self._lock:
            if append_new and operation.operation_id not in self._operation_order:
                self._operation_order.append(operation.operation_id)
            self._operations[operation.operation_id] = operation
        self._operation_state_store.save(
            record_id=operation.operation_id,
            record=operation,
        )


def _normalize_repo_ids(repo_ids: Sequence[str] | None) -> tuple[str, ...]:
    if not repo_ids:
        return ()

    normalized_repo_ids: list[str] = []
    seen_repo_ids: set[str] = set()
    for raw_repo_id in repo_ids:
        repo_id = raw_repo_id.strip()
        if not repo_id:
            raise ValueError("repo_ids must not contain empty values.")
        if repo_id in seen_repo_ids:
            continue
        seen_repo_ids.add(repo_id)
        normalized_repo_ids.append(repo_id)

    return tuple(normalized_repo_ids)


def _select_repositories(
    repositories: list[Any], repo_ids: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    normalized_repositories = tuple(
        repo for repo in repositories if isinstance(repo, dict) and "repo_id" in repo
    )
    if not repo_ids:
        return normalized_repositories

    selected_repositories = tuple(
        repo for repo in normalized_repositories if repo.get("repo_id") in repo_ids
    )
    selected_repo_ids = {str(repo.get("repo_id")) for repo in selected_repositories}
    missing_repo_ids = set(repo_ids) - selected_repo_ids
    if missing_repo_ids:
        raise ValueError(f"Unknown repo_id in registry: {sorted(missing_repo_ids)}")
    return selected_repositories


def _read_required_string(container: dict[str, Any], field_name: str, context: str) -> str:
    value = container.get(field_name)
    if not isinstance(value, str) or not value.strip():
        msg = f"Invalid registry: `{context}` missing required field `{field_name}`."
        raise ValueError(msg)
    return value.strip()


def _apply_llm_assisted_enrichment(
    *,
    detection: dict[str, Any],
    backend: IngestionLLMBackend,
    verifier: LayoutLLMVerifier | None = None,
) -> dict[str, Any]:
    enriched = dict(detection)
    if not bool(enriched.get("uncertain")):
        return enriched  # certain heuristic result — no LLM needed
    if verifier is None:
        return enriched  # backend on but no verifier wired: leave uncertain (will block)
    verdict = verifier.verify(detection=enriched)
    kind = verdict.get("verdict")
    if kind == "confirm":
        enriched["uncertain"] = False
    elif kind == "correct" and isinstance(verdict.get("dimensions"), list):
        enriched["dimensions"] = verdict["dimensions"]
        if isinstance(verdict.get("layout_type"), str):
            enriched["layout_type"] = verdict["layout_type"]
        enriched["uncertain"] = False
    else:  # cannot_determine or malformed
        enriched["schema_unresolvable"] = True
    metrics = enriched.get("algorithm_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    metrics["llm_assisted_backend"] = backend.value
    metrics["llm_verdict"] = kind
    enriched["algorithm_metrics"] = metrics
    enriched["detector_version"] = (
        f"{enriched.get('detector_version', 'layout-detector.v2')}+llm-verified"
    )
    return enriched


def _apply_manual_override(
    *,
    detection: dict[str, Any],
    repo_id: str,
) -> tuple[dict[str, Any], bool]:
    manual_override = detection.get("manual_override")
    if not isinstance(manual_override, dict):
        return detection, False
    if not bool(manual_override.get("enabled", True)):
        return detection, False

    layout_type = manual_override.get("layout_type")
    if not isinstance(layout_type, str) or not layout_type.strip():
        msg = (
            f"Invalid `layout_detection.manual_override.layout_type` for repo_id "
            f"`{repo_id}`."
        )
        raise ValueError(msg)
    dimensions = manual_override.get("dimensions", detection.get("dimensions"))
    if not isinstance(dimensions, list):
        msg = (
            f"Invalid `layout_detection.manual_override.dimensions` for repo_id "
            f"`{repo_id}`."
        )
        raise ValueError(msg)
    sample_paths = manual_override.get(
        "sample_markdown_paths",
        detection.get("sample_markdown_paths"),
    )
    if not isinstance(sample_paths, list):
        msg = (
            "Invalid `layout_detection.manual_override.sample_markdown_paths` for repo_id "
            f"`{repo_id}`."
        )
        raise ValueError(msg)
    confidence_raw = manual_override.get("confidence", 1.0)
    if not isinstance(confidence_raw, (float, int)):
        msg = (
            f"Invalid `layout_detection.manual_override.confidence` for repo_id "
            f"`{repo_id}`."
        )
        raise ValueError(msg)

    overridden = dict(detection)
    overridden["layout_type"] = layout_type.strip()
    overridden["dimensions"] = dimensions
    overridden["sample_markdown_paths"] = sample_paths
    overridden["confidence"] = float(confidence_raw)
    overridden["detector_version"] = str(
        manual_override.get("detector_version") or "layout-detector.manual-override.v1"
    )
    notes = overridden.get("notes")
    if not isinstance(notes, list):
        notes = []
    notes.append("Manual override applied from registry policy.")
    overridden["notes"] = notes
    return overridden, True


def _normalize_confidence_threshold(value: float) -> float:
    threshold = float(value)
    if threshold < 0.0 or threshold > 1.0:
        msg = "layout confidence threshold must be in range [0.0, 1.0]."
        raise ValueError(msg)
    return threshold


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)
