"""Celery bootstrap and task registration for ADCS workers."""

from __future__ import annotations

import logging

from celery import Celery
from kombu import Exchange, Queue
from pydantic import ValidationError

from adcs.admin import InMemorySemanticReviewService
from adcs.config import Settings, get_settings
from adcs.indexing.apiref_symbol_store import build_apiref_symbol_store
from adcs.ingestion.llm_runtime_policy import IngestionLLMRuntimePolicy
from adcs.ingestion.prompt_registry import IngestionPromptRegistry
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOrchestrationService,
)
from adcs.ingestion.source_sync_orchestrator import SourceSyncOrchestrationService
from adcs.ops import NotificationService
from adcs.runtime import RuntimeComponents, build_runtime_components

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE = "adcs.default"
_TASK_ROUTES = {
    "adcs.source_sync.execute": {"queue": "adcs.source-sync"},
    "adcs.layout_detection.execute": {"queue": "adcs.layout-detection"},
    "adcs.ingestion.execute": {"queue": "adcs.ingestion"},
    "adcs.plugins.ingestion.execute": {"queue": "adcs.ingestion"},
}


def _load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        msg = "Invalid ADCS runtime configuration."
        raise RuntimeError(msg) from exc


def _load_runtime_components(settings: Settings) -> RuntimeComponents:
    try:
        return build_runtime_components(settings)
    except Exception as exc:
        msg = "Failed to initialize ADCS worker runtime adapters."
        raise RuntimeError(msg) from exc


def _build_sync_service(_settings: Settings) -> SourceSyncOrchestrationService:
    return SourceSyncOrchestrationService()


def _build_layout_detection_service(
    settings: Settings,
) -> SourceLayoutDetectionOrchestrationService:
    ingestion_llm_runtime_policy = IngestionLLMRuntimePolicy.from_config_file(
        config_path=settings.ingestion_llm_policy_config_path
    )
    return SourceLayoutDetectionOrchestrationService(
        llm_runtime_policy=ingestion_llm_runtime_policy,
        confidence_threshold=settings.layout_detection_confidence_threshold,
        allow_manual_override=settings.layout_detection_allow_manual_override,
    )


def _build_ingestion_service(
    settings: Settings,
    runtime_components: RuntimeComponents,
) -> SourceHugoNormalizationOrchestrationService:
    notification_service = NotificationService()
    ingestion_llm_runtime_policy = IngestionLLMRuntimePolicy.from_config_file(
        config_path=settings.ingestion_llm_policy_config_path
    )
    ingestion_prompt_registry = IngestionPromptRegistry.from_config_file(
        config_path=settings.ingestion_prompt_registry_config_path
    )
    return SourceHugoNormalizationOrchestrationService(
        partial_publish_threshold_pct=settings.ingestion_partial_publish_threshold_pct,
        publish_safety_min_coverage_pct=settings.ingestion_publish_safety_min_coverage_pct,
        metadata_quarantine_policy=settings.ingestion_metadata_quarantine_policy,
        retry_max_attempts=settings.ingestion_retry_max_attempts,
        retry_backoff_base_seconds=settings.ingestion_retry_backoff_base_seconds,
        retry_backoff_max_seconds=settings.ingestion_retry_backoff_max_seconds,
        llm_runtime_policy=ingestion_llm_runtime_policy,
        prompt_registry=ingestion_prompt_registry,
        quality_gate_phase=settings.quality_gate_phase.value,
        critical_event_publisher=runtime_components.critical_event_store,
        notification_service=notification_service,
        semantic_review_service=InMemorySemanticReviewService(),
        index_publish_orchestrator=runtime_components.index_publish_orchestrator,
        ingestion_job_repository=runtime_components.ingestion_job_repository,
        apiref_symbol_store=build_apiref_symbol_store(
            enabled=settings.apiref_structured_store_enabled,
            postgres_dsn=settings.postgres_dsn,
        ),
        docs_english_only_embed=settings.docs_english_only_embed,
    )


def create_celery_app() -> Celery:
    """Create a Celery app configured for ADCS worker execution."""
    settings = _load_settings()
    runtime_components = _load_runtime_components(settings)

    app = Celery("adcs-worker", broker=settings.rabbitmq_url, backend=settings.redis_url)
    app.conf.update(
        task_default_queue=_DEFAULT_QUEUE,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_routes=_TASK_ROUTES,
        # A worker started without -Q consumes every queue listed here. Without this
        # list it would consume only the default queue, and the routed source-sync,
        # layout-detection and ingestion tasks would never run.
        task_queues=tuple(
            Queue(name, Exchange(name, type="direct"), routing_key=name)
            for name in dict.fromkeys(
                (_DEFAULT_QUEUE, *(route["queue"] for route in _TASK_ROUTES.values()))
            )
        ),
        adcs_persistence_backend=runtime_components.adapter_modes.persistence_backend.value,
        adcs_retrieval_backend=runtime_components.adapter_modes.retrieval_backend.value,
    )
    logger.info(
        "Worker runtime adapters initialized.",
        extra={
            "persistence_backend": runtime_components.adapter_modes.persistence_backend.value,
            "retrieval_backend": runtime_components.adapter_modes.retrieval_backend.value,
            "is_test_runtime": runtime_components.adapter_modes.is_test_runtime,
        },
    )
    return app


celery_app = create_celery_app()


@celery_app.task(name="adcs.ping")
def ping() -> str:
    """Simple smoke task for worker bootstrap checks."""
    return "pong"


@celery_app.task(name="adcs.source_sync.execute")
def execute_source_sync(*, operation_id: str) -> dict[str, str]:
    """Execute one queued source-sync operation."""
    settings = _load_settings()
    service = _build_sync_service(settings)
    operation = service.execute_operation(operation_id)
    return {"operation_id": operation.operation_id, "status": operation.status.value}


@celery_app.task(name="adcs.layout_detection.execute")
def execute_layout_detection(*, operation_id: str) -> dict[str, str]:
    """Execute one queued layout-detection operation."""
    settings = _load_settings()
    service = _build_layout_detection_service(settings)
    operation = service.execute_operation(operation_id)
    return {"operation_id": operation.operation_id, "status": operation.status.value}


@celery_app.task(name="adcs.ingestion.execute")
def execute_ingestion(*, operation_id: str) -> dict[str, str]:
    """Execute one queued ingestion operation."""
    settings = _load_settings()
    runtime_components = _load_runtime_components(settings)
    service = _build_ingestion_service(settings, runtime_components)
    operation = service.execute_operation(operation_id=operation_id)
    return {"operation_id": operation.operation_id, "status": operation.status.value}


@celery_app.task(name="adcs.plugins.ingestion.execute", bind=True,
                 acks_late=True, reject_on_worker_lost=True, max_retries=None)
def execute_plugin_ingestion(self, *, operation_id: str, workspace: str) -> dict[str, str]:
    """Reconstruct the registered plugin from durable shared-workspace state."""
    from adcs.plugins.queued_jobs import PluginJobBusy, execute_job

    try:
        job = execute_job(operation_id=operation_id, workspace=workspace)
    except PluginJobBusy as exc:
        raise self.retry(exc=exc, countdown=15)
    return {"operation_id": operation_id, "status": job["status"]}
