"""Task dispatch policy for API-triggered background operations."""

from __future__ import annotations

from dataclasses import dataclass

from celery import Celery

from adcs.config import RetrievalBackend, Settings, WorkerExecutionMode
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOperation,
    SourceLayoutDetectionOrchestrationService,
)
from adcs.ingestion.source_sync_orchestrator import (
    SourceSyncOperation,
    SourceSyncOrchestrationService,
)
from adcs.runtime import ResolvedRuntimeAdapters


def resolve_worker_execution_mode(
    *,
    settings: Settings,
    adapter_modes: ResolvedRuntimeAdapters,
) -> WorkerExecutionMode:
    """Resolve effective execution mode from settings and runtime topology."""
    if settings.worker_execution_mode is not WorkerExecutionMode.AUTO:
        return settings.worker_execution_mode
    if settings.test_mode:
        return WorkerExecutionMode.INLINE
    if adapter_modes.persistence_backend.value == "memory":
        return WorkerExecutionMode.INLINE
    if adapter_modes.retrieval_backend is not RetrievalBackend.QDRANT_OPENSEARCH:
        return WorkerExecutionMode.INLINE
    return WorkerExecutionMode.CELERY


@dataclass(slots=True)
class WorkerTaskDispatcher:
    """Dispatch orchestration operations inline or through Celery queues."""

    mode: WorkerExecutionMode
    celery_app: Celery | None = None

    def dispatch_source_sync(
        self,
        *,
        orchestrator: SourceSyncOrchestrationService,
        operation_id: str,
    ) -> SourceSyncOperation:
        if self.mode is WorkerExecutionMode.CELERY:
            self._require_celery().send_task(
                "adcs.source_sync.execute",
                kwargs={"operation_id": operation_id},
            )
            return orchestrator.get_operation(operation_id)
        return orchestrator.execute_operation(operation_id)

    def dispatch_layout_detection(
        self,
        *,
        orchestrator: SourceLayoutDetectionOrchestrationService,
        operation_id: str,
    ) -> SourceLayoutDetectionOperation:
        if self.mode is WorkerExecutionMode.CELERY:
            self._require_celery().send_task(
                "adcs.layout_detection.execute",
                kwargs={"operation_id": operation_id},
            )
            return orchestrator.get_operation(operation_id)
        return orchestrator.execute_operation(operation_id)

    def dispatch_ingestion(
        self,
        *,
        orchestrator: SourceHugoNormalizationOrchestrationService,
        operation_id: str,
    ) -> SourceHugoNormalizationOperation:
        if self.mode is WorkerExecutionMode.CELERY:
            self._require_celery().send_task(
                "adcs.ingestion.execute",
                kwargs={"operation_id": operation_id},
            )
            return orchestrator.get_operation(operation_id)
        return orchestrator.execute_operation(operation_id=operation_id)

    def _require_celery(self) -> Celery:
        if self.celery_app is None:
            msg = "Celery dispatcher requested without configured Celery app."
            raise RuntimeError(msg)
        return self.celery_app
