from __future__ import annotations

from types import SimpleNamespace

import pytest

from adcs.config import PersistenceBackend, RetrievalBackend, Settings, WorkerExecutionMode
from adcs.runtime import ResolvedRuntimeAdapters
from adcs.worker.task_dispatcher import WorkerTaskDispatcher, resolve_worker_execution_mode


def test_worker_task_dispatcher_runs_inline_for_ingestion() -> None:
    calls: list[str] = []

    class _FakeIngestionOrchestrator:
        def execute_operation(self, *, operation_id: str) -> SimpleNamespace:
            calls.append(operation_id)
            return SimpleNamespace(operation_id=operation_id, status="completed")

    dispatcher = WorkerTaskDispatcher(mode=WorkerExecutionMode.INLINE)
    operation = dispatcher.dispatch_ingestion(
        orchestrator=_FakeIngestionOrchestrator(),  # type: ignore[arg-type]
        operation_id="op-inline",
    )

    assert calls == ["op-inline"]
    assert operation.operation_id == "op-inline"


def test_worker_task_dispatcher_sends_celery_tasks_when_enabled() -> None:
    sent_tasks: list[tuple[str, dict[str, str]]] = []

    class _FakeCelery:
        def send_task(self, task_name: str, kwargs: dict[str, str]) -> None:
            sent_tasks.append((task_name, kwargs))

    class _FakeSyncOrchestrator:
        def get_operation(self, operation_id: str) -> SimpleNamespace:
            return SimpleNamespace(operation_id=operation_id, status="queued")

    class _FakeLayoutOrchestrator:
        def get_operation(self, operation_id: str) -> SimpleNamespace:
            return SimpleNamespace(operation_id=operation_id, status="queued")

    class _FakeIngestionOrchestrator:
        def get_operation(self, operation_id: str) -> SimpleNamespace:
            return SimpleNamespace(operation_id=operation_id, status="queued")

    dispatcher = WorkerTaskDispatcher(
        mode=WorkerExecutionMode.CELERY,
        celery_app=_FakeCelery(),
    )

    dispatcher.dispatch_source_sync(
        orchestrator=_FakeSyncOrchestrator(),  # type: ignore[arg-type]
        operation_id="op-sync",
    )
    dispatcher.dispatch_layout_detection(
        orchestrator=_FakeLayoutOrchestrator(),  # type: ignore[arg-type]
        operation_id="op-layout",
    )
    dispatcher.dispatch_ingestion(
        orchestrator=_FakeIngestionOrchestrator(),  # type: ignore[arg-type]
        operation_id="op-ingestion",
    )

    assert sent_tasks == [
        ("adcs.source_sync.execute", {"operation_id": "op-sync"}),
        ("adcs.layout_detection.execute", {"operation_id": "op-layout"}),
        ("adcs.ingestion.execute", {"operation_id": "op-ingestion"}),
    ]


def test_worker_task_dispatcher_raises_when_celery_app_missing() -> None:
    dispatcher = WorkerTaskDispatcher(mode=WorkerExecutionMode.CELERY, celery_app=None)

    class _FakeOrchestrator:
        def get_operation(self, operation_id: str) -> SimpleNamespace:
            return SimpleNamespace(operation_id=operation_id, status="queued")

    with pytest.raises(RuntimeError, match="Celery dispatcher requested without configured"):
        dispatcher.dispatch_ingestion(
            orchestrator=_FakeOrchestrator(),  # type: ignore[arg-type]
            operation_id="op-fail",
        )


def _make_settings(**overrides: str) -> Settings:
    """Build a Settings instance with test-friendly defaults."""
    defaults: dict[str, str] = {
        "ADCS_ENV": "dev",
        "ADCS_API_KEY": "test-key",
        "ADCS_TEST_MODE": "false",
        "ADCS_WORKER_EXECUTION_MODE": "auto",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_resolve_worker_execution_mode_explicit_inline() -> None:
    settings = _make_settings(ADCS_WORKER_EXECUTION_MODE="inline")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.POSTGRES,
        retrieval_backend=RetrievalBackend.QDRANT_OPENSEARCH,
        is_test_runtime=False,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.INLINE


def test_resolve_worker_execution_mode_explicit_celery() -> None:
    settings = _make_settings(ADCS_WORKER_EXECUTION_MODE="celery")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.MEMORY,
        retrieval_backend=RetrievalBackend.MEMORY,
        is_test_runtime=True,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.CELERY


def test_resolve_worker_execution_mode_auto_test_mode_is_inline() -> None:
    settings = _make_settings(ADCS_TEST_MODE="true")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.POSTGRES,
        retrieval_backend=RetrievalBackend.QDRANT_OPENSEARCH,
        is_test_runtime=True,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.INLINE


def test_resolve_worker_execution_mode_auto_memory_persistence_is_inline() -> None:
    settings = _make_settings(ADCS_TEST_MODE="false")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.MEMORY,
        retrieval_backend=RetrievalBackend.QDRANT_OPENSEARCH,
        is_test_runtime=False,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.INLINE


def test_resolve_worker_execution_mode_auto_memory_retrieval_is_inline() -> None:
    settings = _make_settings(ADCS_TEST_MODE="false")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.POSTGRES,
        retrieval_backend=RetrievalBackend.MEMORY,
        is_test_runtime=False,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.INLINE


def test_resolve_worker_execution_mode_auto_full_infra_is_celery() -> None:
    settings = _make_settings(ADCS_TEST_MODE="false")
    adapter_modes = ResolvedRuntimeAdapters(
        persistence_backend=PersistenceBackend.POSTGRES,
        retrieval_backend=RetrievalBackend.QDRANT_OPENSEARCH,
        is_test_runtime=False,
    )
    result = resolve_worker_execution_mode(settings=settings, adapter_modes=adapter_modes)
    assert result is WorkerExecutionMode.CELERY
