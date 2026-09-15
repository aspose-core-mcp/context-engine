"""FastAPI bootstrap entrypoint for ADCS."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware

from adcs.admin import (
    FileBackedHowToOverrideStore,
    InMemoryConfigHistoryService,
    InMemoryRegistryService,
    InMemoryRetrievalSettingsService,
    InMemorySemanticReviewService,
)
from adcs.api import readiness
from adcs.api.abuse_guard import AbuseGuardService
from adcs.api.admin_abuse_guard import router as admin_abuse_guard_router
from adcs.api.admin_auth import AdminAuthService
from adcs.api.admin_critical_events import router as admin_critical_events_router
from adcs.api.admin_howto import public_router as public_howto_router
from adcs.api.admin_howto import router as admin_howto_router
from adcs.api.admin_index_status import router as admin_index_status_router
from adcs.api.admin_keys import router as admin_keys_router
from adcs.api.admin_observability import router as admin_observability_router
from adcs.api.admin_products import router as admin_products_router
from adcs.api.admin_quality_loop import router as admin_quality_loop_router
from adcs.api.admin_quality_reviews import router as admin_quality_reviews_router
from adcs.api.admin_registries_analytics import router as admin_registries_analytics_router
from adcs.api.admin_session import router as admin_session_router
from adcs.api.admin_snapshots import router as admin_snapshots_router
from adcs.api.admin_source_repositories import router as source_repositories_router
from adcs.api.admin_system import public_router as public_system_router
from adcs.api.admin_system import router as admin_system_router
from adcs.api.apiref_symbol_query import ApiRefSymbolService
from adcs.api.apiref_symbols import router as apiref_symbols_router
from adcs.api.ingestion_slis import render_ingestion_slis
from adcs.api.mcp_gateway import router as mcp_gateway_router
from adcs.api.metrics import InMemoryMetrics
from adcs.api.middleware import request_context_middleware
from adcs.api.product_coverage import router as product_coverage_router
from adcs.api.public_docs_query import PublicQueryService
from adcs.api.public_docs_query import router as public_docs_query_router
from adcs.api.public_status_page import router as public_status_page_router
from adcs.api.webmcp_audit import InMemoryWebMCPWriteAuditStore
from adcs.api.webmcp_confirmation import WebMCPConfirmationService
from adcs.api.webmcp_gateway import router as webmcp_gateway_router
from adcs.config import Settings, get_settings
from adcs.indexing.apiref_symbol_store import ApiRefSymbolStore, build_apiref_symbol_store
from adcs.ingestion.llm_runtime_policy import IngestionLLMRuntimePolicy
from adcs.ingestion.prompt_registry import IngestionPromptRegistry
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOrchestrationService,
)
from adcs.ingestion.source_registry import SourceRegistryService
from adcs.ingestion.source_sync_orchestrator import SourceSyncOrchestrationService
from adcs.mcp.revision_negotiation import MCPRevisionNegotiationResult
from adcs.mcp.tool_gateway import MCPToolGateway
from adcs.ops import (
    FileBackedBackupRestoreService,
    NotificationService,
    ObservabilityControlPlane,
)
from adcs.ops.logging_config import configure_logging
from adcs.ops.metrics import render_metrics as render_prometheus_metrics
from adcs.ops.tracing import TracingService
from adcs.retrieval import (
    HybridScoringConfig,
    ReleaseCatalog,
    TranslationFallbackService,
    build_candidate_reranker,
)
from adcs.retrieval.response_cache import ResponseCache
from adcs.runtime import build_runtime_components
from adcs.worker.task_dispatcher import (
    WorkerTaskDispatcher,
    resolve_worker_execution_mode,
)

logger = logging.getLogger(__name__)


def _load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        msg = "Invalid ADCS runtime configuration."
        raise RuntimeError(msg) from exc


def _build_apiref_symbol_store(settings: Settings) -> ApiRefSymbolStore | None:
    """Build the shared Postgres symbol store (orchestrator writes + service reads)."""
    return build_apiref_symbol_store(
        enabled=settings.apiref_structured_store_enabled,
        postgres_dsn=settings.postgres_dsn,
    )


def create_app() -> FastAPI:
    """Create the API application instance."""
    settings = _load_settings()
    # Apply ADCS_LOG_LEVEL before anything else can log. Until this call existed
    # the setting was inert: it was parsed and reported by the admin snapshot,
    # but no handler or level was ever configured from it.
    configure_logging(level=settings.log_level.value)
    try:
        runtime_components = build_runtime_components(settings)
    except Exception as exc:
        msg = "Failed to initialize runtime adapters."
        raise RuntimeError(msg) from exc
    # Swagger UI and ReDoc load scripts, styles and fonts from public CDNs, so the pages are
    # opt-in; the OpenAPI schema itself is always served at /openapi.json.
    docs_enabled = settings.api_docs_enabled
    app = FastAPI(
        title="ADCS API",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    notification_service = NotificationService()
    tracing_service = TracingService.from_settings(settings)
    ingestion_llm_runtime_policy = IngestionLLMRuntimePolicy.from_config_file(
        config_path=settings.ingestion_llm_policy_config_path
    )
    ingestion_prompt_registry = IngestionPromptRegistry.from_config_file(
        config_path=settings.ingestion_prompt_registry_config_path
    )
    app.state.settings = settings
    app.state.adapter_modes = runtime_components.adapter_modes
    app.state.tracing_service = tracing_service
    app.state.observability_control_plane = ObservabilityControlPlane(
        config_path=settings.observability_control_plane_config_path,
        canary_policy_path=settings.canary_policy_config_path,
        smoke_report_path=settings.deploy_smoke_report_path,
        canary_report_path=settings.canary_evaluation_report_path,
    )
    worker_execution_mode = resolve_worker_execution_mode(
        settings=settings,
        adapter_modes=runtime_components.adapter_modes,
    )
    if worker_execution_mode.value == "celery":
        from adcs.worker.celery_app import celery_app

        app.state.task_dispatcher = WorkerTaskDispatcher(
            mode=worker_execution_mode,
            celery_app=celery_app,
        )
    else:
        app.state.task_dispatcher = WorkerTaskDispatcher(mode=worker_execution_mode)
    app.state.worker_execution_mode = worker_execution_mode
    app.state.ingestion_llm_runtime_policy = ingestion_llm_runtime_policy
    app.state.ingestion_prompt_registry = ingestion_prompt_registry
    app.state.admin_auth_service = AdminAuthService(settings=settings)
    app.state.metrics = InMemoryMetrics()
    app.state.abuse_guard_service = AbuseGuardService.from_settings(settings=settings)
    app.state.index_topology_policy = runtime_components.topology_policy
    app.state.critical_event_store = runtime_components.critical_event_store
    app.state.snapshot_cleanup_audit_store = runtime_components.cleanup_audit_store
    app.state.snapshot_rollback_audit_store = runtime_components.rollback_audit_store
    app.state.snapshot_registry = runtime_components.snapshot_registry
    app.state.lexical_index_writer = runtime_components.lexical_index_writer
    app.state.backup_restore_service = FileBackedBackupRestoreService()
    app.state.notification_service = notification_service
    app.state.registry_service = InMemoryRegistryService()
    app.state.retrieval_settings_service = InMemoryRetrievalSettingsService()
    # Retrieval response cache. Held on app state so the snapshot promote
    # path can invalidate it — a publish changes what should be served, and a
    # stale answer is a correctness bug, not a slow one.
    app.state.retrieval_response_cache = ResponseCache()
    app.state.analytics_service = runtime_components.analytics_service
    app.state.config_history_service = InMemoryConfigHistoryService()
    app.state.howto_override_store = FileBackedHowToOverrideStore(
        storage_path=settings.howto_override_store_path,
        asset_dir=settings.howto_asset_root,
    )
    app.state.semantic_review_service = InMemorySemanticReviewService()
    app.state.source_registry_service = SourceRegistryService()
    app.state.source_sync_orchestrator = SourceSyncOrchestrationService()
    app.state.source_layout_detection_orchestrator = SourceLayoutDetectionOrchestrationService(
        llm_runtime_policy=ingestion_llm_runtime_policy,
        confidence_threshold=settings.layout_detection_confidence_threshold,
        allow_manual_override=settings.layout_detection_allow_manual_override,
    )
    apiref_symbol_store = _build_apiref_symbol_store(settings)
    app.state.source_hugo_normalization_orchestrator = SourceHugoNormalizationOrchestrationService(
        partial_publish_threshold_pct=settings.ingestion_partial_publish_threshold_pct,
        apiref_symbol_store=apiref_symbol_store,
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
        semantic_review_service=app.state.semantic_review_service,
        index_publish_orchestrator=runtime_components.index_publish_orchestrator,
        ingestion_job_repository=runtime_components.ingestion_job_repository,
        docs_english_only_embed=settings.docs_english_only_embed,
    )
    app.state.translation_fallback_service = TranslationFallbackService.from_config_file(
        config_path=settings.translation_llm_config_path
    )
    app.state.release_catalog = ReleaseCatalog.from_config_file(
        config_path=settings.release_catalog_config_path
    )
    app.state.candidate_reranker = build_candidate_reranker(
        backend=settings.reranker_backend.value,
        release_catalog=app.state.release_catalog,
    )
    scoring_config = HybridScoringConfig(
        dense_weight=settings.hybrid_dense_weight,
        lexical_weight=settings.hybrid_lexical_weight,
        lane_timeout_seconds=settings.hybrid_lane_timeout_seconds,
    )
    app.state.public_query_service = PublicQueryService(
        source_hugo_normalization_orchestrator=app.state.source_hugo_normalization_orchestrator,
        translation_fallback_service=app.state.translation_fallback_service,
        source_registry_service=app.state.source_registry_service,
        dense_lane_adapter=runtime_components.dense_lane_adapter,
        lexical_lane_adapter=runtime_components.lexical_lane_adapter,
        candidate_reranker=app.state.candidate_reranker,
        release_catalog=app.state.release_catalog,
        qdrant_url=settings.qdrant_url,
        scoring_config=scoring_config,
        snapshot_registry=runtime_components.snapshot_registry,
        apiref_symbol_store=apiref_symbol_store,
        # Same instance the admin API mutates, so an operator's change reaches
        # the query path instead of being written to the audit trail and ignored.
        retrieval_settings_service=app.state.retrieval_settings_service,
        response_cache=app.state.retrieval_response_cache,
        # Per-stage timings are computed on every query; export them as
        # component metrics instead of only logging them.
        stage_observer=app.state.metrics.observe_retrieval_stage,
    )
    app.state.endpoint_timeout_seconds = settings.endpoint_timeout_seconds
    app.state.webmcp_confirmation_service = WebMCPConfirmationService(
        ttl_seconds=settings.webmcp_confirmation_ttl_seconds
    )
    app.state.webmcp_write_audit_store = InMemoryWebMCPWriteAuditStore()

    def _observe_mcp_negotiation(negotiation: MCPRevisionNegotiationResult) -> None:
        metrics = getattr(app.state, "metrics", None)
        if not isinstance(metrics, InMemoryMetrics):
            return
        if not negotiation.negotiated_revision:
            return
        metrics.observe_mcp_negotiation(
            requested_revision=negotiation.requested_revision,
            negotiated_revision=negotiation.negotiated_revision,
            fallback_reason=negotiation.fallback_reason.value,
            fallback_applied=negotiation.fallback_applied,
        )

    app.state.apiref_symbol_service = (
        ApiRefSymbolService(store=apiref_symbol_store)
        if apiref_symbol_store is not None
        else None
    )

    app.state.mcp_tool_gateway = MCPToolGateway(
        public_query_service=app.state.public_query_service,
        supported_revisions=settings.mcp_supported_revisions,
        primary_revision=settings.mcp_supported_revisions[0],
        negotiation_observer=_observe_mcp_negotiation,
        apiref_symbol_service=app.state.apiref_symbol_service,
    )
    logger.info(
        "Runtime adapters initialized.",
        extra={
            "persistence_backend": runtime_components.adapter_modes.persistence_backend.value,
            "retrieval_backend": runtime_components.adapter_modes.retrieval_backend.value,
            "is_test_runtime": runtime_components.adapter_modes.is_test_runtime,
        },
    )
    app.middleware("http")(request_context_middleware)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # `str(exc)` embedded the server's absolute source path, the line number
        # and Pydantic internals in the body of an unauthenticated endpoint, and
        # echoed the caller's input back. Report which field failed and why —
        # nothing about the server.
        details = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "reason": str(error.get("msg", "invalid value")),
                "type": str(error.get("type", "value_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "Request validation failed.",
                    "details": {"fields": details},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {"service": "adcs-api", "status": "ok"}

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/healthz", tags=["ops"])
    async def v1_healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        readiness_results = readiness.check_dependencies(
            app.state.settings,
            adapter_modes=app.state.adapter_modes,
        )
        status_code, payload = readiness.build_readiness_response(readiness_results)
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/v1/readyz", tags=["ops"])
    async def v1_readyz() -> JSONResponse:
        readiness_results = readiness.check_dependencies(
            app.state.settings,
            adapter_modes=app.state.adapter_modes,
        )
        status_code, payload = readiness.build_readiness_response(readiness_results)
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/metrics", tags=["ops"])
    async def metrics() -> PlainTextResponse:
        # Combine legacy in-memory metrics with prometheus_client output.
        legacy = app.state.metrics.render_prometheus()
        prom = render_prometheus_metrics()
        # Ingestion-sourced SLIs are derived from Postgres on scrape: the worker
        # that produces them serves no HTTP.
        ingestion = render_ingestion_slis(
            snapshot_registry=getattr(app.state, "snapshot_registry", None),
            critical_event_store=getattr(app.state, "critical_event_store", None),
        )
        combined = legacy + prom + ingestion
        return PlainTextResponse(
            combined,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.include_router(source_repositories_router)
    app.include_router(admin_session_router)
    app.include_router(admin_system_router)
    app.include_router(public_system_router)
    app.include_router(public_status_page_router)
    app.include_router(admin_keys_router)
    app.include_router(admin_products_router)
    app.include_router(admin_observability_router)
    app.include_router(admin_abuse_guard_router)
    app.include_router(admin_critical_events_router)
    app.include_router(admin_howto_router)
    app.include_router(admin_registries_analytics_router)
    app.include_router(admin_snapshots_router)
    app.include_router(admin_index_status_router)
    app.include_router(product_coverage_router)
    app.include_router(admin_quality_reviews_router)
    app.include_router(admin_quality_loop_router)
    app.include_router(public_docs_query_router)
    app.include_router(apiref_symbols_router)
    app.include_router(mcp_gateway_router)
    app.include_router(webmcp_gateway_router)
    app.include_router(public_howto_router)

    return app


app = create_app()
