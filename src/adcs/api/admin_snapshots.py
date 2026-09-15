"""Admin API endpoints for index snapshot inspection contracts."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.api.webmcp_confirmation import WebMCPConfirmationError, WebMCPConfirmationService
from adcs.indexing import (
    InMemoryVectorIndexPurger,
    QdrantVectorIndexPurger,
    SnapshotCleanupFilters,
    SnapshotCleanupService,
    SnapshotRecord,
    SnapshotRegistry,
    SnapshotRollbackConflictError,
    SnapshotStatus,
)
from adcs.indexing.index_models import IndexPublishSummary
from adcs.indexing.lexical_index_writer import LexicalIndexWriter
from adcs.indexing.snapshot_cleanup import BulkSnapshotCleanupResult, VectorIndexPurger
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ops import (
    CriticalEventSeverity,
    CriticalEventStore,
    CriticalEventType,
    InMemorySnapshotCleanupAuditStore,
    PostgresSnapshotCleanupAuditStore,
    SnapshotCleanupAuditRecord,
    SnapshotCleanupAuditStore,
    SnapshotCleanupResultStatus,
    SnapshotRollbackAuditRecord,
    SnapshotRollbackAuditStore,
    SnapshotRollbackResultStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["admin-snapshots"],
    dependencies=[Depends(require_admin_principal)],
)
_ADMIN_SNAPSHOT_ROLLBACK_TOOL = "admin_snapshot_rollback"


class RollbackPreflightCheckStatus(str):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class AdminSnapshotResponse(BaseModel):
    snapshot_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    source_revision: str
    status: SnapshotStatus
    indexed_chunks_count: int
    created_at: datetime


class AdminSnapshotCompareResponse(BaseModel):
    base_snapshot: AdminSnapshotResponse
    target_snapshot: AdminSnapshotResponse
    same_scope: bool
    same_source_kind: bool
    indexed_chunks_delta: int
    created_at_delta_seconds: int


class AdminSnapshotRollbackConfirmationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "reason must not be empty."
            raise ValueError(msg)
        return normalized


class AdminSnapshotRollbackConfirmationResponse(BaseModel):
    snapshot_id: str
    confirm_token: str
    expires_at: datetime
    ttl_seconds: int


class AdminSnapshotRollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)
    confirm_token: str = Field(min_length=1, max_length=512)

    @field_validator("reason", "confirm_token")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Value must not be empty."
            raise ValueError(msg)
        return normalized


class AdminSnapshotRollbackPreflightCheck(BaseModel):
    code: str
    status: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class AdminSnapshotRollbackExecutionResponse(BaseModel):
    audit_id: str
    operation_id: str
    status: str
    can_execute: bool
    target_snapshot: AdminSnapshotResponse
    active_snapshot_before: AdminSnapshotResponse
    active_snapshot_after: AdminSnapshotResponse
    preflight_diagnostics: list[AdminSnapshotRollbackPreflightCheck]
    consistency_checks: list[AdminSnapshotRollbackPreflightCheck]
    history_preserved: bool


class AdminSnapshotRollbackAuditResponse(BaseModel):
    audit_id: str
    operation_id: str
    result_status: str
    actor_key_id: str
    request_id: str | None
    reason: str
    product_id: str
    programming_language: str
    version: str
    target_snapshot_id: str
    active_snapshot_before_id: str | None
    active_snapshot_after_id: str | None
    diagnostics: dict[str, object]
    created_at: datetime


class AdminSnapshotCleanupRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=160)
    programming_language: str | None = Field(default=None, max_length=160)
    version: str | None = Field(default=None, max_length=160)
    source_kind: str | None = Field(default=None, max_length=64)

    @field_validator("product_id", "programming_language", "version", "source_kind")
    @classmethod
    def _normalize_optional_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class AdminSnapshotCleanupExecutionRequest(AdminSnapshotCleanupRequest):
    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "reason must not be empty."
            raise ValueError(msg)
        return normalized


class AdminSnapshotCleanupProtectedResponse(BaseModel):
    snapshot: AdminSnapshotResponse
    reason: str


class AdminSnapshotCleanupPreviewResponse(BaseModel):
    operation_id: str
    status: str
    compaction_enabled: bool
    matched_snapshots_count: int
    delete_candidates_count: int
    protected_snapshots_count: int
    max_inactive_snapshots_per_scope: int
    stale_snapshot_retention_days: int
    product_id: str
    programming_language: str | None
    version: str | None
    source_kind: str | None
    delete_candidates: list[AdminSnapshotResponse]
    protected_snapshots: list[AdminSnapshotCleanupProtectedResponse]
    risk_summary: list[str]
    generated_at: datetime


class AdminSnapshotCleanupExecutionResponse(AdminSnapshotCleanupPreviewResponse):
    audit_id: str
    deleted_snapshots_count: int
    deleted_snapshots: list[AdminSnapshotResponse]
    reason: str


class AdminSnapshotCleanupAuditResponse(BaseModel):
    audit_id: str
    operation_id: str
    result_status: str
    actor_key_id: str
    request_id: str | None
    reason: str
    product_id: str
    programming_language: str | None
    version: str | None
    source_kind: str | None
    dry_run: bool
    deleted_snapshot_ids: list[str]
    protected_snapshot_ids: list[str]
    diagnostics: dict[str, object]
    created_at: datetime


class AdminBulkCleanupRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)
    dry_run: bool = Field(default=True)
    purge_vectors: bool = Field(default=False)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "reason must not be empty."
            raise ValueError(msg)
        return normalized


class AdminBulkCleanupScopeSummaryResponse(BaseModel):
    product_id: str
    deleted_count: int
    protected_count: int
    deleted_snapshot_ids: list[str]


class AdminBulkCleanupResponse(BaseModel):
    operation_id: str
    total_scanned: int
    total_deleted: int
    total_protected: int
    total_vectors_purged: int
    scope_summaries: list[AdminBulkCleanupScopeSummaryResponse]
    compaction_enabled: bool
    max_inactive_snapshots_per_scope: int
    stale_snapshot_retention_days: int
    dry_run: bool
    generated_at: datetime


def _snapshot_registry(request: Request) -> SnapshotRegistry:
    registry = getattr(request.app.state, "snapshot_registry", None)
    if registry is None:
        msg = "Snapshot registry is not configured."
        raise RuntimeError(msg)
    return registry


def _rollback_audit_store(request: Request) -> SnapshotRollbackAuditStore:
    store = getattr(request.app.state, "snapshot_rollback_audit_store", None)
    if not isinstance(store, SnapshotRollbackAuditStore):
        msg = "Snapshot rollback audit store is not configured."
        raise RuntimeError(msg)
    return store


def _snapshot_cleanup_audit_store(request: Request) -> SnapshotCleanupAuditStore:
    store = getattr(request.app.state, "snapshot_cleanup_audit_store", None)
    if not isinstance(
        store,
        InMemorySnapshotCleanupAuditStore | PostgresSnapshotCleanupAuditStore,
    ):
        msg = "Snapshot cleanup audit store is not configured."
        raise RuntimeError(msg)
    return store


def _critical_event_store(request: Request) -> CriticalEventStore:
    store = getattr(request.app.state, "critical_event_store", None)
    if not isinstance(store, CriticalEventStore):
        msg = "Critical event store is not configured."
        raise RuntimeError(msg)
    return store


def _confirmation_service(request: Request) -> WebMCPConfirmationService:
    service = getattr(request.app.state, "webmcp_confirmation_service", None)
    if not isinstance(service, WebMCPConfirmationService):
        msg = "WebMCP confirmation service is not configured."
        raise RuntimeError(msg)
    return service


def _source_hugo_orchestrator(
    request: Request,
) -> SourceHugoNormalizationOrchestrationService | None:
    orchestrator = getattr(request.app.state, "source_hugo_normalization_orchestrator", None)
    if isinstance(orchestrator, SourceHugoNormalizationOrchestrationService):
        return orchestrator
    return None


def _get_admin_principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _snapshot_cleanup_service(request: Request) -> SnapshotCleanupService:
    topology_policy = getattr(request.app.state, "index_topology_policy", None)
    if topology_policy is None:
        msg = "Index topology policy is not configured."
        raise RuntimeError(msg)
    return SnapshotCleanupService(
        snapshot_registry=_snapshot_registry(request),
        topology_policy=topology_policy,
    )


def _resolve_vector_purger(request: Request) -> VectorIndexPurger | None:
    purger = getattr(request.app.state, "vector_index_purger", None)
    if isinstance(purger, (InMemoryVectorIndexPurger, QdrantVectorIndexPurger)):
        return purger
    settings = getattr(request.app.state, "settings", None)
    if settings is not None:
        qdrant_url = getattr(settings, "qdrant_url", None)
        if qdrant_url:
            # Purge the collections this deployment actually writes to, not the
            # legacy literals — otherwise retention reports success on a
            # collection that does not exist and leaves the served one untouched.
            collections = tuple(
                dict.fromkeys(
                    name
                    for name in (
                        getattr(settings, "docs_vector_collection", None),
                        getattr(settings, "apiref_vector_collection", None),
                    )
                    if name
                )
            )
            if collections:
                return QdrantVectorIndexPurger(qdrant_url=qdrant_url, collections=collections)
            return QdrantVectorIndexPurger(qdrant_url=qdrant_url)
    return None


def _resolve_lexical_index_writer(request: Request) -> LexicalIndexWriter | None:
    """Return the runtime lexical index writer, if wired on app state.

    Used by promote/rollback flows to atomically switch the `*_lex_v1_active`
    alias to the newly activated snapshot's per-snapshot index. Returning
    None lets callers gracefully no-op in test runtimes that don't wire the
    writer.
    """
    writer = getattr(request.app.state, "lexical_index_writer", None)
    if writer is None:
        return None
    # Duck-type on switch_alias rather than isinstance — the concrete writers
    # live in adcs.indexing.lexical_index_writer, but tests may inject fakes.
    if not hasattr(writer, "switch_alias"):
        return None
    return writer


def _try_switch_lexical_alias(
    *,
    request: Request,
    source_kind: str,
    snapshot_id: str,
    flow: str,
) -> None:
    """Best-effort OpenSearch alias switch for promote/rollback.

    Updating only Postgres `index_snapshots.status` on promote/rollback would
    leave the `*_lex_v1_active` alias pointing at the last-published snapshot's
    index, so retrieval would keep serving the wrong snapshot after a rollback.
    This helper re-points the alias to the target snapshot's per-snapshot index
    so the lexical lane reflects the active snapshot record.

    NOTE: The Qdrant dense lane still has a known architectural gap — Qdrant
    point_ids are derived solely from chunk_id, so each publish overwrites
    points from previous snapshots. Dense retrieval therefore serves the
    last-published snapshot regardless of promote/rollback. Fixing this
    requires snapshot-aware point_ids and query-time snapshot_id filters.
    """
    writer = _resolve_lexical_index_writer(request)
    if writer is None:
        return
    try:
        writer.switch_alias(source_kind=source_kind, snapshot_id=snapshot_id)
    except Exception as exc:  # pragma: no cover - best-effort degradation
        # Do not fail the promote/rollback if the alias switch fails — the
        # Postgres record is already updated and retrieval will continue with
        # stale alias until the next publish. Log so operators can notice.
        import logging
        logging.getLogger(__name__).warning(
            "lexical_alias_switch_failed flow=%s snapshot_id=%s source_kind=%s error=%s",
            flow, snapshot_id, source_kind, exc,
        )


def _to_auth_http_exception(request: Request, exc: AdminAuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _raise_structured_http_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )



def _invalidate_retrieval_response_cache(*, request: Request, reason: str) -> None:
    """Drop the public retrieval response cache, if one is wired."""
    cache = getattr(request.app.state, "retrieval_response_cache", None)
    invalidate = getattr(cache, "invalidate_all", None)
    if invalidate is None:
        return
    dropped = invalidate()
    logger.info("retrieval_response_cache_invalidated reason=%s dropped=%d", reason, dropped)


def _to_snapshot_response(snapshot: SnapshotRecord) -> AdminSnapshotResponse:
    return AdminSnapshotResponse(
        snapshot_id=snapshot.snapshot_id,
        product_id=snapshot.product_id,
        programming_language=snapshot.programming_language,
        version=snapshot.version,
        source_kind=snapshot.source_kind,
        source_revision=snapshot.source_revision,
        status=snapshot.status,
        indexed_chunks_count=snapshot.indexed_chunks_count,
        created_at=snapshot.created_at,
    )


def _to_rollback_audit_response(
    record: SnapshotRollbackAuditRecord,
) -> AdminSnapshotRollbackAuditResponse:
    return AdminSnapshotRollbackAuditResponse(
        audit_id=record.audit_id,
        operation_id=record.operation_id,
        result_status=record.result_status.value,
        actor_key_id=record.actor_key_id,
        request_id=record.request_id,
        reason=record.reason,
        product_id=record.product_id,
        programming_language=record.programming_language,
        version=record.version,
        target_snapshot_id=record.target_snapshot_id,
        active_snapshot_before_id=record.active_snapshot_before_id,
        active_snapshot_after_id=record.active_snapshot_after_id,
        diagnostics=dict(record.diagnostics),
        created_at=record.created_at,
    )


def _to_snapshot_cleanup_audit_response(
    record: SnapshotCleanupAuditRecord,
) -> AdminSnapshotCleanupAuditResponse:
    return AdminSnapshotCleanupAuditResponse(
        audit_id=record.audit_id,
        operation_id=record.operation_id,
        result_status=record.result_status.value,
        actor_key_id=record.actor_key_id,
        request_id=record.request_id,
        reason=record.reason,
        product_id=record.product_id,
        programming_language=record.programming_language,
        version=record.version,
        source_kind=record.source_kind,
        dry_run=record.dry_run,
        deleted_snapshot_ids=list(record.deleted_snapshot_ids),
        protected_snapshot_ids=list(record.protected_snapshot_ids),
        diagnostics=dict(record.diagnostics),
        created_at=record.created_at,
    )


def _to_cleanup_filters(payload: AdminSnapshotCleanupRequest) -> SnapshotCleanupFilters:
    return SnapshotCleanupFilters(
        product_id=payload.product_id,
        programming_language=payload.programming_language,
        version=payload.version,
        source_kind=payload.source_kind,
    )


def _to_cleanup_preview_response(
    preview: object,
    *,
    status: str,
) -> AdminSnapshotCleanupPreviewResponse:
    delete_candidates = getattr(preview, "delete_candidates")
    protected_snapshots = getattr(preview, "protected_snapshots")
    filters = getattr(preview, "filters")
    return AdminSnapshotCleanupPreviewResponse(
        operation_id=getattr(preview, "operation_id"),
        status=status,
        compaction_enabled=getattr(preview, "compaction_enabled"),
        matched_snapshots_count=len(getattr(preview, "matched_snapshots")),
        delete_candidates_count=len(delete_candidates),
        protected_snapshots_count=len(protected_snapshots),
        max_inactive_snapshots_per_scope=getattr(
            preview,
            "max_inactive_snapshots_per_scope",
        ),
        stale_snapshot_retention_days=getattr(
            preview,
            "stale_snapshot_retention_days",
        ),
        product_id=filters.product_id,
        programming_language=filters.programming_language,
        version=filters.version,
        source_kind=filters.source_kind,
        delete_candidates=[
            _to_snapshot_response(snapshot) for snapshot in delete_candidates
        ],
        protected_snapshots=[
            AdminSnapshotCleanupProtectedResponse(
                snapshot=_to_snapshot_response(item.snapshot),
                reason=item.reason,
            )
            for item in protected_snapshots
        ],
        risk_summary=list(getattr(preview, "risk_summary")),
        generated_at=getattr(preview, "generated_at"),
    )


def _authorize_snapshot_cleanup(
    *,
    request: Request,
    product_id: str,
) -> None:
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=(product_id,),
            destructive=True,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _record_snapshot_cleanup_audit(
    *,
    request: Request,
    operation_id: str,
    result_status: SnapshotCleanupResultStatus,
    reason: str,
    filters: SnapshotCleanupFilters,
    dry_run: bool,
    deleted_snapshot_ids: tuple[str, ...],
    protected_snapshot_ids: tuple[str, ...],
    diagnostics: dict[str, object] | None = None,
) -> SnapshotCleanupAuditRecord:
    principal = _get_admin_principal(request)
    return _snapshot_cleanup_audit_store(request).record(
        operation_id=operation_id,
        result_status=result_status,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=reason,
        product_id=filters.product_id,
        programming_language=filters.programming_language,
        version=filters.version,
        source_kind=filters.source_kind,
        dry_run=dry_run,
        deleted_snapshot_ids=deleted_snapshot_ids,
        protected_snapshot_ids=protected_snapshot_ids,
        diagnostics=diagnostics or {},
    )


def _resolve_snapshot_or_404(*, request: Request, snapshot_id: str) -> SnapshotRecord:
    snapshot = _snapshot_registry(request).get_snapshot(snapshot_id)
    if snapshot is None:
        _raise_structured_http_error(
            request,
            status_code=404,
            code="NOT_FOUND",
            message=f"Snapshot `{snapshot_id}` was not found.",
        )
    assert snapshot is not None
    return snapshot


def _authorize_snapshot_write(*, request: Request, snapshot: SnapshotRecord) -> None:
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=(snapshot.product_id,),
            destructive=False,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _record_rollback_audit(
    *,
    request: Request,
    operation_id: str,
    result_status: SnapshotRollbackResultStatus,
    reason: str,
    target_snapshot: SnapshotRecord,
    active_snapshot_before: SnapshotRecord | None,
    active_snapshot_after: SnapshotRecord | None,
    diagnostics: dict[str, object] | None = None,
) -> SnapshotRollbackAuditRecord:
    principal = _get_admin_principal(request)
    return _rollback_audit_store(request).record(
        operation_id=operation_id,
        result_status=result_status,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=reason,
        product_id=target_snapshot.product_id,
        programming_language=target_snapshot.programming_language,
        version=target_snapshot.version,
        target_snapshot_id=target_snapshot.snapshot_id,
        active_snapshot_before_id=(
            active_snapshot_before.snapshot_id
            if active_snapshot_before is not None
            else None
        ),
        active_snapshot_after_id=(
            active_snapshot_after.snapshot_id
            if active_snapshot_after is not None
            else None
        ),
        diagnostics=diagnostics or {},
    )


def _emit_rollback_critical_event(
    *,
    request: Request,
    result_status: SnapshotRollbackResultStatus,
    audit_record: SnapshotRollbackAuditRecord,
) -> None:
    if result_status is SnapshotRollbackResultStatus.COMPLETED:
        severity = CriticalEventSeverity.WARNING
        event_type = CriticalEventType.ROLLBACK_SUCCEEDED
        message = "Runtime snapshot rollback completed."
    elif result_status is SnapshotRollbackResultStatus.CONFLICT:
        severity = CriticalEventSeverity.HIGH
        event_type = CriticalEventType.ROLLBACK_FAILED
        message = "Runtime snapshot rollback rejected due to active snapshot conflict."
    elif result_status is SnapshotRollbackResultStatus.PREFLIGHT_FAILED:
        severity = CriticalEventSeverity.HIGH
        event_type = CriticalEventType.ROLLBACK_FAILED
        message = "Runtime snapshot rollback preflight failed."
    else:
        severity = CriticalEventSeverity.CRITICAL
        event_type = CriticalEventType.ROLLBACK_FAILED
        message = "Runtime snapshot rollback failed consistency checks."

    _critical_event_store(request).emit(
        severity=severity,
        event_type=event_type,
        message=message,
        details={
            "audit_id": audit_record.audit_id,
            "operation_id": audit_record.operation_id,
            "result_status": audit_record.result_status.value,
            "actor_key_id": audit_record.actor_key_id,
            "request_id": audit_record.request_id,
            "product_id": audit_record.product_id,
            "programming_language": audit_record.programming_language,
            "version": audit_record.version,
            "target_snapshot_id": audit_record.target_snapshot_id,
            "active_snapshot_before_id": audit_record.active_snapshot_before_id,
            "active_snapshot_after_id": audit_record.active_snapshot_after_id,
        },
    )


def _consume_rollback_confirmation_or_raise(
    *,
    request: Request,
    snapshot_id: str,
    reason: str,
    confirm_token: str,
) -> None:
    principal = _get_admin_principal(request)
    service = _confirmation_service(request)
    try:
        service.consume(
            confirm_token=confirm_token,
            tool_name=_ADMIN_SNAPSHOT_ROLLBACK_TOOL,
            reason=reason,
            intent_payload={
                "snapshot_id": snapshot_id,
                "actor_key_id": principal.key_id,
            },
            request_id=getattr(request.state, "request_id", None),
        )
    except WebMCPConfirmationError as exc:
        status_code = 409 if exc.code == "CONFIRMATION_REPLAYED" else 400
        _raise_structured_http_error(
            request,
            status_code=status_code,
            code=exc.code,
            message=exc.message,
        )
    except ValueError as exc:
        _raise_structured_http_error(
            request,
            status_code=400,
            code="VALIDATION_ERROR",
            message=str(exc),
        )


def _find_index_publish_summary(
    *,
    request: Request,
    snapshot_id: str,
) -> IndexPublishSummary | None:
    """Find the IndexPublishSummary for ``snapshot_id`` by scanning recent operations.

    Each ``list_operations`` call hydrates operation state files from disk which
    can be multi-MB per entry. Scanning 500 of them blocks the request for
    20+ seconds on a warm cache. We cap the scan at the 50 most recent
    operations — that covers real-world rollback targets (you almost always
    roll back to a snapshot whose publish is in the recent history) and keeps
    the preflight check sub-second. If the snapshot can't be found in the
    recent window, callers fall back to a WARN diagnostic instead of FAIL,
    which preserves the existing behaviour when evidence is unavailable.
    """
    orchestrator = _source_hugo_orchestrator(request)
    if orchestrator is None:
        return None
    operations = orchestrator.list_operations(limit=50)
    for operation in operations:
        for result in operation.results:
            summary = result.indexing_summary
            if summary.snapshot_id == snapshot_id:
                return summary
    return None


def _build_rollback_preflight_checks(
    *,
    request: Request,
    target_snapshot: SnapshotRecord,
    active_snapshot: SnapshotRecord | None,
) -> tuple[list[AdminSnapshotRollbackPreflightCheck], bool]:
    checks: list[AdminSnapshotRollbackPreflightCheck] = []

    if active_snapshot is None:
        checks.append(
            AdminSnapshotRollbackPreflightCheck(
                code="ACTIVE_SNAPSHOT_EXISTS",
                status=RollbackPreflightCheckStatus.FAIL,
                message=(
                    "No active snapshot found for rollback scope "
                    f"({target_snapshot.product_id}, {target_snapshot.programming_language}, "
                    f"{target_snapshot.version})."
                ),
            )
        )
        return checks, False

    same_scope = (
        active_snapshot.product_id == target_snapshot.product_id
        and active_snapshot.programming_language == target_snapshot.programming_language
        and active_snapshot.version == target_snapshot.version
    )
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="SCOPE_COMPATIBLE",
            status=(
                RollbackPreflightCheckStatus.PASS
                if same_scope
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Target snapshot scope matches active scope."
                if same_scope
                else "Target snapshot scope does not match current active scope."
            ),
            details={
                "active_scope": (
                    f"{active_snapshot.product_id}/"
                    f"{active_snapshot.programming_language}/{active_snapshot.version}"
                ),
                "target_scope": (
                    f"{target_snapshot.product_id}/"
                    f"{target_snapshot.programming_language}/{target_snapshot.version}"
                ),
            },
        )
    )

    target_not_active = active_snapshot.snapshot_id != target_snapshot.snapshot_id
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="TARGET_IS_NOT_ACTIVE",
            status=(
                RollbackPreflightCheckStatus.PASS
                if target_not_active
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Target snapshot is not the currently active snapshot."
                if target_not_active
                else "Target snapshot is already active; rollback is not applicable."
            ),
            details={"active_snapshot_id": active_snapshot.snapshot_id},
        )
    )

    older_revision = target_snapshot.created_at < active_snapshot.created_at
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="TARGET_IS_PREVIOUS_REVISION",
            status=(
                RollbackPreflightCheckStatus.PASS
                if older_revision
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Target snapshot is older than active snapshot."
                if older_revision
                else "Target snapshot is not an older revision than active snapshot."
            ),
            details={
                "target_created_at": target_snapshot.created_at.isoformat(),
                "active_created_at": active_snapshot.created_at.isoformat(),
            },
        )
    )

    same_source_kind = target_snapshot.source_kind == active_snapshot.source_kind
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="SOURCE_KIND_COMPATIBLE",
            status=(
                RollbackPreflightCheckStatus.PASS
                if same_source_kind
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Target and active snapshots have compatible source_kind."
                if same_source_kind
                else "Target and active snapshots use different source_kind."
            ),
            details={
                "target_source_kind": target_snapshot.source_kind,
                "active_source_kind": active_snapshot.source_kind,
            },
        )
    )

    indexed_chunks_ok = target_snapshot.indexed_chunks_count > 0
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="INDEXED_CHUNKS_PRESENT",
            status=(
                RollbackPreflightCheckStatus.PASS
                if indexed_chunks_ok
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Target snapshot contains indexed chunks."
                if indexed_chunks_ok
                else "Target snapshot has zero indexed chunks."
            ),
            details={"indexed_chunks_count": target_snapshot.indexed_chunks_count},
        )
    )

    # Short-circuit: if any fast preflight check has already failed (e.g. target is
    # already active, scope mismatch, zero chunks), don't run the expensive
    # _find_index_publish_summary() call. That function scans up to 500 on-disk
    # operation state JSON files and can cost multiple seconds per invocation —
    # callers must get a fast rejection when the request is obviously invalid.
    if any(check.status == RollbackPreflightCheckStatus.FAIL for check in checks):
        return checks, False

    summary = _find_index_publish_summary(request=request, snapshot_id=target_snapshot.snapshot_id)
    if summary is None:
        checks.append(
            AdminSnapshotRollbackPreflightCheck(
                code="LANE_EVIDENCE_AVAILABLE",
                status=RollbackPreflightCheckStatus.WARN,
                message=(
                    "No in-memory publish evidence found for target snapshot; "
                    "vector/lexical lane record counts could not be verified."
                ),
            )
        )
    else:
        vector_ok = summary.vector_records_count > 0
        checks.append(
            AdminSnapshotRollbackPreflightCheck(
                code="VECTOR_LANE_RECORDS_PRESENT",
                status=(
                    RollbackPreflightCheckStatus.PASS
                    if vector_ok
                    else RollbackPreflightCheckStatus.FAIL
                ),
                message=(
                    "Vector lane records are present for target snapshot."
                    if vector_ok
                    else "Vector lane records are missing for target snapshot."
                ),
                details={
                    "vector_records_count": summary.vector_records_count,
                    "vector_collection": summary.vector_collection,
                },
            )
        )
        lexical_ok = summary.lexical_records_count > 0
        checks.append(
            AdminSnapshotRollbackPreflightCheck(
                code="LEXICAL_LANE_RECORDS_PRESENT",
                status=(
                    RollbackPreflightCheckStatus.PASS
                    if lexical_ok
                    else RollbackPreflightCheckStatus.FAIL
                ),
                message=(
                    "Lexical lane records are present for target snapshot."
                    if lexical_ok
                    else "Lexical lane records are missing for target snapshot."
                ),
                details={
                    "lexical_records_count": summary.lexical_records_count,
                    "lexical_index": summary.lexical_index,
                    "lexical_alias": summary.lexical_alias,
                },
            )
        )

    can_execute = all(
        check.status != RollbackPreflightCheckStatus.FAIL
        for check in checks
    )
    return checks, can_execute


def _build_rollback_consistency_checks(
    *,
    request: Request,
    target_snapshot: SnapshotRecord,
    active_snapshot_before: SnapshotRecord,
    active_snapshot_after: SnapshotRecord | None,
    previous_active_after: SnapshotRecord | None,
) -> tuple[list[AdminSnapshotRollbackPreflightCheck], bool, bool]:
    checks: list[AdminSnapshotRollbackPreflightCheck] = []

    active_switched = (
        active_snapshot_after is not None
        and active_snapshot_after.snapshot_id == target_snapshot.snapshot_id
        and active_snapshot_after.status is SnapshotStatus.ACTIVE
    )
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="ACTIVE_SNAPSHOT_SWITCHED",
            status=(
                RollbackPreflightCheckStatus.PASS
                if active_switched
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Active snapshot switched to rollback target."
                if active_switched
                else "Active snapshot did not switch to rollback target."
            ),
            details={
                "active_after_snapshot_id": (
                    active_snapshot_after.snapshot_id
                    if active_snapshot_after is not None
                    else None
                ),
                "target_snapshot_id": target_snapshot.snapshot_id,
            },
        )
    )

    previous_demoted = (
        previous_active_after is not None
        and previous_active_after.snapshot_id == active_snapshot_before.snapshot_id
        and previous_active_after.status is SnapshotStatus.INACTIVE
    )
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="PREVIOUS_ACTIVE_DEMOTED",
            status=(
                RollbackPreflightCheckStatus.PASS
                if previous_demoted
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Previously active snapshot was demoted to inactive."
                if previous_demoted
                else "Previously active snapshot was not demoted to inactive."
            ),
            details={
                "previous_active_snapshot_id": active_snapshot_before.snapshot_id,
                "observed_status": (
                    previous_active_after.status.value
                    if previous_active_after is not None
                    else None
                ),
            },
        )
    )

    scope_snapshots = _snapshot_registry(request).list_snapshots(
        product_id=target_snapshot.product_id,
        programming_language=target_snapshot.programming_language,
        version=target_snapshot.version,
    )
    scope_snapshot_ids = {item.snapshot_id for item in scope_snapshots}
    history_preserved = (
        target_snapshot.snapshot_id in scope_snapshot_ids
        and active_snapshot_before.snapshot_id in scope_snapshot_ids
    )
    checks.append(
        AdminSnapshotRollbackPreflightCheck(
            code="SNAPSHOT_HISTORY_PRESERVED",
            status=(
                RollbackPreflightCheckStatus.PASS
                if history_preserved
                else RollbackPreflightCheckStatus.FAIL
            ),
            message=(
                "Snapshot history retained both target and previous active revisions."
                if history_preserved
                else "Snapshot history lost target or previous active revision."
            ),
            details={
                "scope_snapshot_count": len(scope_snapshots),
                "scope_snapshot_ids": sorted(scope_snapshot_ids),
            },
        )
    )

    checks_ok = all(
        check.status != RollbackPreflightCheckStatus.FAIL
        for check in checks
    )
    return checks, checks_ok, history_preserved


@router.get("/admin/v1/snapshots", response_model=list[AdminSnapshotResponse])
def list_snapshots(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    version: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AdminSnapshotResponse]:
    registry = _snapshot_registry(request)
    snapshots = registry.list_snapshots(
        product_id=product_id,
        programming_language=programming_language,
        version=version,
    )
    ordered = sorted(
        snapshots,
        key=lambda item: (item.created_at, item.snapshot_id),
        reverse=True,
    )[:limit]
    return [_to_snapshot_response(snapshot) for snapshot in ordered]


@router.get("/admin/v1/snapshots/active", response_model=AdminSnapshotResponse)
def get_active_snapshot(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str = Query(min_length=1),
    version: str = Query(min_length=1),
) -> AdminSnapshotResponse:
    registry = _snapshot_registry(request)
    snapshot = registry.get_active_snapshot(
        product_id=product_id,
        programming_language=programming_language,
        version=version,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": (
                        "Active snapshot was not found for requested scope "
                        f"({product_id}, {programming_language}, {version})."
                    ),
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    return _to_snapshot_response(snapshot)


@router.get("/admin/v1/snapshots/{snapshot_id}", response_model=AdminSnapshotResponse)
def get_snapshot(snapshot_id: str, request: Request) -> AdminSnapshotResponse:
    registry = _snapshot_registry(request)
    snapshot = registry.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Snapshot `{snapshot_id}` was not found.",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    return _to_snapshot_response(snapshot)


@router.post("/admin/v1/snapshots/{snapshot_id}:promote", response_model=AdminSnapshotResponse)
def promote_snapshot(snapshot_id: str, request: Request) -> AdminSnapshotResponse:
    registry = _snapshot_registry(request)
    snapshot = registry.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Snapshot `{snapshot_id}` was not found.",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=(snapshot.product_id,),
            destructive=False,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc

    promoted = registry.promote_snapshot(snapshot_id=snapshot_id)
    if promoted is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Snapshot `{snapshot_id}` was not found.",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    # Repoint the OpenSearch active alias to the promoted snapshot so the
    # lexical retrieval lane immediately reflects the new active snapshot.
    _try_switch_lexical_alias(
        request=request,
        source_kind=promoted.source_kind,
        snapshot_id=promoted.snapshot_id,
        flow="promote",
    )
    # A promote changes what retrieval serves, so any cached response predates
    # the new truth. Clearing costs a brief dip in hit rate; not clearing
    # serves answers from the snapshot that was just replaced.
    _invalidate_retrieval_response_cache(request=request, reason="snapshot_promote")
    return _to_snapshot_response(promoted)


@router.post(
    "/admin/v1/snapshots/{snapshot_id}:rollback-confirmation",
    response_model=AdminSnapshotRollbackConfirmationResponse,
)
def issue_snapshot_rollback_confirmation(
    snapshot_id: str,
    payload: AdminSnapshotRollbackConfirmationRequest,
    request: Request,
) -> AdminSnapshotRollbackConfirmationResponse:
    snapshot = _resolve_snapshot_or_404(request=request, snapshot_id=snapshot_id)
    _authorize_snapshot_write(request=request, snapshot=snapshot)
    principal = _get_admin_principal(request)
    confirmation = _confirmation_service(request).issue(
        tool_name=_ADMIN_SNAPSHOT_ROLLBACK_TOOL,
        reason=payload.reason,
        intent_payload={
            "snapshot_id": snapshot_id,
            "actor_key_id": principal.key_id,
        },
    )
    service = _confirmation_service(request)
    return AdminSnapshotRollbackConfirmationResponse(
        snapshot_id=snapshot_id,
        confirm_token=confirmation.confirm_token,
        expires_at=confirmation.expires_at,
        ttl_seconds=service.ttl_seconds,
    )


@router.post(
    "/admin/v1/snapshots/{snapshot_id}:rollback",
    response_model=AdminSnapshotRollbackExecutionResponse,
)
def rollback_snapshot_execute(
    snapshot_id: str,
    payload: AdminSnapshotRollbackRequest,
    request: Request,
) -> AdminSnapshotRollbackExecutionResponse:
    target_snapshot = _resolve_snapshot_or_404(request=request, snapshot_id=snapshot_id)
    _authorize_snapshot_write(request=request, snapshot=target_snapshot)
    _consume_rollback_confirmation_or_raise(
        request=request,
        snapshot_id=snapshot_id,
        reason=payload.reason,
        confirm_token=payload.confirm_token,
    )

    active_snapshot = _snapshot_registry(request).get_active_snapshot(
        product_id=target_snapshot.product_id,
        programming_language=target_snapshot.programming_language,
        version=target_snapshot.version,
    )
    diagnostics, can_execute = _build_rollback_preflight_checks(
        request=request,
        target_snapshot=target_snapshot,
        active_snapshot=active_snapshot,
    )
    operation_id = f"rbk-op-{uuid4().hex[:12]}"

    if not can_execute:
        audit_record = _record_rollback_audit(
            request=request,
            operation_id=operation_id,
            result_status=SnapshotRollbackResultStatus.PREFLIGHT_FAILED,
            reason=payload.reason,
            target_snapshot=target_snapshot,
            active_snapshot_before=active_snapshot,
            active_snapshot_after=active_snapshot,
            diagnostics={
                "status": "preflight_failed",
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            },
        )
        _emit_rollback_critical_event(
            request=request,
            result_status=SnapshotRollbackResultStatus.PREFLIGHT_FAILED,
            audit_record=audit_record,
        )
        _raise_structured_http_error(
            request,
            status_code=409,
            code="ROLLBACK_PREFLIGHT_FAILED",
            message="Rollback preflight checks failed for requested snapshot.",
            details={
                "audit_id": audit_record.audit_id,
                "operation_id": operation_id,
                "status": "preflight_failed",
                "target_snapshot_id": target_snapshot.snapshot_id,
                "active_snapshot_id": (
                    active_snapshot.snapshot_id if active_snapshot is not None else None
                ),
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            },
        )

    assert active_snapshot is not None
    registry = _snapshot_registry(request)
    try:
        rollback_outcome = registry.rollback_snapshot(
            target_snapshot_id=target_snapshot.snapshot_id,
            expected_active_snapshot_id=active_snapshot.snapshot_id,
        )
    except SnapshotRollbackConflictError as exc:
        current_active_snapshot = (
            registry.get_snapshot(exc.current_active_snapshot_id)
            if exc.current_active_snapshot_id is not None
            else None
        )
        audit_record = _record_rollback_audit(
            request=request,
            operation_id=operation_id,
            result_status=SnapshotRollbackResultStatus.CONFLICT,
            reason=payload.reason,
            target_snapshot=target_snapshot,
            active_snapshot_before=active_snapshot,
            active_snapshot_after=current_active_snapshot,
            diagnostics={
                "status": "rollback_conflict",
                "expected_active_snapshot_id": exc.expected_active_snapshot_id,
                "current_active_snapshot_id": exc.current_active_snapshot_id,
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            },
        )
        _emit_rollback_critical_event(
            request=request,
            result_status=SnapshotRollbackResultStatus.CONFLICT,
            audit_record=audit_record,
        )
        _raise_structured_http_error(
            request,
            status_code=409,
            code=exc.code,
            message=exc.message,
            details={
                "audit_id": audit_record.audit_id,
                "operation_id": operation_id,
                "status": "rollback_conflict",
                "target_snapshot_id": target_snapshot.snapshot_id,
                "expected_active_snapshot_id": exc.expected_active_snapshot_id,
                "current_active_snapshot_id": exc.current_active_snapshot_id,
                "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            },
        )
    if rollback_outcome is None:
        _raise_structured_http_error(
            request,
            status_code=404,
            code="NOT_FOUND",
            message=f"Snapshot `{snapshot_id}` was not found.",
            details={
                "operation_id": operation_id,
            },
        )
    assert rollback_outcome is not None

    active_snapshot_after = registry.get_active_snapshot(
        product_id=target_snapshot.product_id,
        programming_language=target_snapshot.programming_language,
        version=target_snapshot.version,
    )
    # Repoint the OpenSearch active alias to the rollback target so the
    # lexical retrieval lane immediately reflects the rolled-back snapshot.
    # The dense (Qdrant) lane has a separate known limitation — see
    # _try_switch_lexical_alias docstring.
    _try_switch_lexical_alias(
        request=request,
        source_kind=target_snapshot.source_kind,
        snapshot_id=target_snapshot.snapshot_id,
        flow="rollback",
    )
    consistency_checks, checks_ok, history_preserved = _build_rollback_consistency_checks(
        request=request,
        target_snapshot=target_snapshot,
        active_snapshot_before=active_snapshot,
        active_snapshot_after=active_snapshot_after,
        previous_active_after=rollback_outcome.previous_active_snapshot,
    )
    if not checks_ok:
        recovery_status = "not_attempted"
        try:
            registry.rollback_snapshot(
                target_snapshot_id=active_snapshot.snapshot_id,
                expected_active_snapshot_id=target_snapshot.snapshot_id,
            )
            recovery_status = "recovered_to_previous_active"
        except Exception:
            recovery_status = "recovery_failed"

        audit_record = _record_rollback_audit(
            request=request,
            operation_id=operation_id,
            result_status=SnapshotRollbackResultStatus.FAILED,
            reason=payload.reason,
            target_snapshot=target_snapshot,
            active_snapshot_before=active_snapshot,
            active_snapshot_after=active_snapshot_after,
            diagnostics={
                "status": "rollback_failed",
                "history_preserved": history_preserved,
                "recovery_status": recovery_status,
                "preflight_diagnostics": [
                    item.model_dump(mode="json") for item in diagnostics
                ],
                "consistency_checks": [
                    item.model_dump(mode="json") for item in consistency_checks
                ],
            },
        )
        _emit_rollback_critical_event(
            request=request,
            result_status=SnapshotRollbackResultStatus.FAILED,
            audit_record=audit_record,
        )
        _raise_structured_http_error(
            request,
            status_code=500,
            code="ROLLBACK_CONSISTENCY_CHECK_FAILED",
            message="Rollback execution failed post-consistency checks.",
            details={
                "audit_id": audit_record.audit_id,
                "operation_id": operation_id,
                "status": "rollback_failed",
                "target_snapshot_id": target_snapshot.snapshot_id,
                "active_snapshot_before_id": active_snapshot.snapshot_id,
                "active_snapshot_after_id": (
                    active_snapshot_after.snapshot_id
                    if active_snapshot_after is not None
                    else None
                ),
                "history_preserved": history_preserved,
                "recovery_status": recovery_status,
                "preflight_diagnostics": [
                    item.model_dump(mode="json") for item in diagnostics
                ],
                "consistency_checks": [
                    item.model_dump(mode="json") for item in consistency_checks
                ],
            },
        )

    assert active_snapshot_after is not None
    audit_record = _record_rollback_audit(
        request=request,
        operation_id=operation_id,
        result_status=SnapshotRollbackResultStatus.COMPLETED,
        reason=payload.reason,
        target_snapshot=target_snapshot,
        active_snapshot_before=active_snapshot,
        active_snapshot_after=active_snapshot_after,
        diagnostics={
            "status": "completed",
            "history_preserved": history_preserved,
            "preflight_diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            "consistency_checks": [item.model_dump(mode="json") for item in consistency_checks],
        },
    )
    _emit_rollback_critical_event(
        request=request,
        result_status=SnapshotRollbackResultStatus.COMPLETED,
        audit_record=audit_record,
    )
    return AdminSnapshotRollbackExecutionResponse(
        audit_id=audit_record.audit_id,
        operation_id=operation_id,
        status="completed",
        can_execute=True,
        target_snapshot=_to_snapshot_response(target_snapshot),
        active_snapshot_before=_to_snapshot_response(active_snapshot),
        active_snapshot_after=_to_snapshot_response(active_snapshot_after),
        preflight_diagnostics=diagnostics,
        consistency_checks=consistency_checks,
        history_preserved=history_preserved,
    )


@router.get(
    "/admin/v1/snapshots:rollback-audit",
    response_model=list[AdminSnapshotRollbackAuditResponse],
)
def list_snapshot_rollback_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    product_id: str | None = None,
) -> list[AdminSnapshotRollbackAuditResponse]:
    records = _rollback_audit_store(request).list_records(
        limit=limit,
        product_id=product_id,
    )
    return [_to_rollback_audit_response(record) for record in records]


@router.post(
    "/admin/v1/snapshots:cleanup-preview",
    response_model=AdminSnapshotCleanupPreviewResponse,
)
def preview_snapshot_cleanup(
    payload: AdminSnapshotCleanupRequest,
    request: Request,
) -> AdminSnapshotCleanupPreviewResponse:
    _authorize_snapshot_cleanup(request=request, product_id=payload.product_id)
    preview = _snapshot_cleanup_service(request).preview(
        filters=_to_cleanup_filters(payload),
    )
    return _to_cleanup_preview_response(preview, status="preview")


@router.post(
    "/admin/v1/snapshots:cleanup",
    response_model=AdminSnapshotCleanupExecutionResponse,
)
def execute_snapshot_cleanup(
    payload: AdminSnapshotCleanupExecutionRequest,
    request: Request,
) -> AdminSnapshotCleanupExecutionResponse:
    _authorize_snapshot_cleanup(request=request, product_id=payload.product_id)
    filters = _to_cleanup_filters(payload)
    execution = _snapshot_cleanup_service(request).execute(filters=filters)
    deleted_snapshot_ids = tuple(
        snapshot.snapshot_id for snapshot in execution.deleted_snapshots
    )
    protected_snapshot_ids = tuple(
        item.snapshot.snapshot_id for item in execution.preview.protected_snapshots
    )
    result_status = (
        SnapshotCleanupResultStatus.COMPLETED
        if deleted_snapshot_ids
        else SnapshotCleanupResultStatus.NOOP
    )
    audit_record = _record_snapshot_cleanup_audit(
        request=request,
        operation_id=execution.preview.operation_id,
        result_status=result_status,
        reason=payload.reason,
        filters=filters,
        dry_run=False,
        deleted_snapshot_ids=deleted_snapshot_ids,
        protected_snapshot_ids=protected_snapshot_ids,
        diagnostics={
            "matched_snapshots_count": len(execution.preview.matched_snapshots),
            "delete_candidates_count": len(execution.preview.delete_candidates),
            "deleted_snapshots_count": len(execution.deleted_snapshots),
            "risk_summary": list(execution.preview.risk_summary),
        },
    )
    preview_response = _to_cleanup_preview_response(
        execution.preview,
        status=result_status.value,
    )
    return AdminSnapshotCleanupExecutionResponse(
        **preview_response.model_dump(mode="json"),
        audit_id=audit_record.audit_id,
        deleted_snapshots_count=len(execution.deleted_snapshots),
        deleted_snapshots=[
            _to_snapshot_response(snapshot) for snapshot in execution.deleted_snapshots
        ],
        reason=payload.reason,
    )


@router.get(
    "/admin/v1/snapshots:cleanup-history",
    response_model=list[AdminSnapshotCleanupAuditResponse],
)
def list_snapshot_cleanup_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    product_id: str | None = None,
) -> list[AdminSnapshotCleanupAuditResponse]:
    records = _snapshot_cleanup_audit_store(request).list_records(
        limit=limit,
        product_id=product_id,
    )
    return [_to_snapshot_cleanup_audit_response(record) for record in records]


@router.get("/admin/v1/snapshots:compare", response_model=AdminSnapshotCompareResponse)
def compare_snapshots(
    request: Request,
    base_snapshot_id: str = Query(min_length=1),
    target_snapshot_id: str = Query(min_length=1),
) -> AdminSnapshotCompareResponse:
    registry = _snapshot_registry(request)
    base_snapshot = registry.get_snapshot(base_snapshot_id)
    if base_snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Snapshot `{base_snapshot_id}` was not found.",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
    target_snapshot = registry.get_snapshot(target_snapshot_id)
    if target_snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Snapshot `{target_snapshot_id}` was not found.",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    same_scope = (
        base_snapshot.product_id == target_snapshot.product_id
        and base_snapshot.programming_language == target_snapshot.programming_language
        and base_snapshot.version == target_snapshot.version
    )
    return AdminSnapshotCompareResponse(
        base_snapshot=_to_snapshot_response(base_snapshot),
        target_snapshot=_to_snapshot_response(target_snapshot),
        same_scope=same_scope,
        same_source_kind=base_snapshot.source_kind == target_snapshot.source_kind,
        indexed_chunks_delta=(
            target_snapshot.indexed_chunks_count - base_snapshot.indexed_chunks_count
        ),
        created_at_delta_seconds=int(
            (target_snapshot.created_at - base_snapshot.created_at).total_seconds()
        ),
    )


@router.post(
    "/admin/v1/snapshots:bulk-cleanup",
    response_model=AdminBulkCleanupResponse,
)
def bulk_snapshot_cleanup(
    payload: AdminBulkCleanupRequest,
    request: Request,
) -> AdminBulkCleanupResponse:
    """Run retention-based cleanup across ALL products.

    Requires superuser key with write:destructive scope.
    Defaults to dry_run=True for safety.
    """
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:destructive",
            target_product_ids=(),
            destructive=True,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc

    cleanup_service = _snapshot_cleanup_service(request)
    vector_purger = _resolve_vector_purger(request) if payload.purge_vectors else None

    result: BulkSnapshotCleanupResult = cleanup_service.bulk_cleanup(
        dry_run=payload.dry_run,
        purge_vectors=payload.purge_vectors,
        vector_purger=vector_purger,
    )

    # Record audit entry for the entire bulk operation
    if not payload.dry_run:
        all_deleted_ids: list[str] = []
        all_protected_ids: list[str] = []
        for scope in result.scope_summaries:
            all_deleted_ids.extend(scope.deleted_snapshot_ids)
        # Record a single consolidated audit record under a synthetic product_id
        _record_snapshot_cleanup_audit(
            request=request,
            operation_id=result.operation_id,
            result_status=(
                SnapshotCleanupResultStatus.COMPLETED
                if result.total_deleted > 0
                else SnapshotCleanupResultStatus.NOOP
            ),
            reason=payload.reason,
            filters=SnapshotCleanupFilters(product_id="__bulk__"),
            dry_run=False,
            deleted_snapshot_ids=tuple(all_deleted_ids),
            protected_snapshot_ids=tuple(all_protected_ids),
            diagnostics={
                "bulk_operation": True,
                "total_scanned": result.total_scanned,
                "total_deleted": result.total_deleted,
                "total_protected": result.total_protected,
                "total_vectors_purged": result.total_vectors_purged,
                "product_count": len(result.scope_summaries),
                "purge_vectors": payload.purge_vectors,
            },
        )

    return AdminBulkCleanupResponse(
        operation_id=result.operation_id,
        total_scanned=result.total_scanned,
        total_deleted=result.total_deleted,
        total_protected=result.total_protected,
        total_vectors_purged=result.total_vectors_purged,
        scope_summaries=[
            AdminBulkCleanupScopeSummaryResponse(
                product_id=scope.product_id,
                deleted_count=scope.deleted_count,
                protected_count=scope.protected_count,
                deleted_snapshot_ids=list(scope.deleted_snapshot_ids),
            )
            for scope in result.scope_summaries
        ],
        compaction_enabled=result.compaction_enabled,
        max_inactive_snapshots_per_scope=result.max_inactive_snapshots_per_scope,
        stale_snapshot_retention_days=result.stale_snapshot_retention_days,
        dry_run=result.dry_run,
        generated_at=result.generated_at,
    )
