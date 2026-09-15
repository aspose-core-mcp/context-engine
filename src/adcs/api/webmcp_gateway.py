"""Optional WebMCP adapter for browser-facing tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.api import readiness
from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.api.error_messages import public_error_message
from adcs.api.public_docs_query import PublicQueryService, QueryDocsRequest, QueryDocsResponse
from adcs.api.webmcp_audit import (
    InMemoryWebMCPWriteAuditStore,
    WebMCPWriteAuditRecord,
    WebMCPWriteAuditStatus,
)
from adcs.api.webmcp_confirmation import (
    WebMCPConfirmationError,
    WebMCPConfirmationRecord,
    WebMCPConfirmationService,
)
from adcs.indexing import IngestionRunMode, SnapshotRecord, SnapshotRegistry
from adcs.ingestion.job_repository import IngestionIdempotencyConflictError
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.source_registry import SourceRegistryLookupError, SourceRegistryService

router = APIRouter(tags=["webmcp-gateway"])

_READ_ONLY_TOOL_NAMES = frozenset(
    {"web_get_system_status", "web_query_docs_preview", "web_list_ingestion_jobs"}
)
_WRITE_TOOL_NAMES = frozenset(
    {
        "web_trigger_ingestion",
        "web_trigger_reindex",
        "web_promote_snapshot",
    }
)
_ALL_WEBMCP_TOOL_NAMES = _READ_ONLY_TOOL_NAMES | _WRITE_TOOL_NAMES


class WebMCPToolDescriptor(BaseModel):
    tool_name: str
    read_only: bool
    mapped_backend_contract: str
    requires_confirmation: bool = False


class WebMCPCapabilitiesResponse(BaseModel):
    enabled: bool
    tools: list[WebMCPToolDescriptor]


class WebGetSystemStatusResponse(BaseModel):
    healthz: dict[str, Any]
    readyz: dict[str, Any]
    generated_at: datetime


class WebQueryDocsPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    product_id: str | None = None
    language: str | None = None
    version: str | None = None
    query_locale: str | None = None
    top_k: int = Field(default=3, ge=1, le=5)
    strict_version: bool = True
    doc_types: list[str] = Field(default_factory=list)
    include_examples: bool = True


class WebListIngestionJobsRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)


class WebIngestionJobResponse(BaseModel):
    operation_id: str
    status: str
    repo_ids: list[str]
    mode: str
    started_at: datetime | None
    finished_at: datetime | None
    request_id: str | None


class _WebMCPWriteBaseRequest(BaseModel):
    confirm_token: str | None = Field(default=None, max_length=512)
    reason: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("confirm_token", "reason")
    @classmethod
    def _normalize_optional_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class _WebMCPRepoTargetRequest(_WebMCPWriteBaseRequest):
    repo_id: str | None = None
    repo_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=256)

    @field_validator("repo_id", "idempotency_key")
    @classmethod
    def _normalize_optional_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @field_validator("repo_ids")
    @classmethod
    def _normalize_repo_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            token = item.strip()
            if not token:
                continue
            if token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def resolved_repo_ids(self) -> tuple[str, ...]:
        merged: list[str] = []
        seen: set[str] = set()
        if self.repo_id is not None:
            merged.append(self.repo_id)
        merged.extend(self.repo_ids)
        resolved: list[str] = []
        for item in merged:
            if item in seen:
                continue
            seen.add(item)
            resolved.append(item)
        return tuple(resolved)


class WebTriggerIngestionRequest(_WebMCPRepoTargetRequest):
    dry_run: bool = False


class WebTriggerReindexRequest(_WebMCPRepoTargetRequest):
    pass


class WebPromoteSnapshotRequest(_WebMCPWriteBaseRequest):
    snapshot_id: str = Field(min_length=1, max_length=120)

    @field_validator("snapshot_id")
    @classmethod
    def _normalize_snapshot_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "snapshot_id must not be empty."
            raise ValueError(msg)
        return normalized


class WebMCPConfirmationIssueRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=240)
    intent: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "reason")
    @classmethod
    def _normalize_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Value must not be empty."
            raise ValueError(msg)
        return normalized


class WebMCPConfirmationIssueResponse(BaseModel):
    confirm_token: str
    tool_name: str
    reason: str
    intent_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    ttl_seconds: int


class WebMCPWriteOperationResponse(BaseModel):
    tool_name: str
    status: str
    request_id: str | None
    audit_id: str
    operation_id: str | None = None
    snapshot_id: str | None = None
    repo_ids: list[str] = Field(default_factory=list)
    product_id: str | None = None
    programming_language: str | None = None
    version: str | None = None


class WebMCPWriteAuditResponse(BaseModel):
    audit_id: str
    tool_name: str
    status: WebMCPWriteAuditStatus
    actor_key_id: str
    request_id: str | None
    reason: str | None
    confirm_token_hash: str | None
    target: dict[str, Any]
    error_code: str | None
    created_at: datetime


def _settings(request: Request) -> Any:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        msg = "Settings are not configured."
        raise RuntimeError(msg)
    return settings


def _error_payload(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def _raise_http_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=_error_payload(request, code=code, message=message, details=details),
    )


def _error_code_from_http_exception(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
    return "HTTP_ERROR"


def _audit_status_from_http_status(status_code: int) -> WebMCPWriteAuditStatus:
    if status_code == 403:
        return WebMCPWriteAuditStatus.FORBIDDEN
    if status_code in {400, 404, 409, 422}:
        return WebMCPWriteAuditStatus.REJECTED
    return WebMCPWriteAuditStatus.FAILED


def _require_webmcp_enabled(request: Request) -> None:
    settings = _settings(request)
    if bool(getattr(settings, "webmcp_enabled", False)):
        return
    _raise_http_error(
        request,
        status_code=404,
        code="NOT_FOUND",
        message="WebMCP adapter is disabled.",
    )


def _public_query_service(request: Request) -> PublicQueryService:
    service = getattr(request.app.state, "public_query_service", None)
    if not isinstance(service, PublicQueryService):
        msg = "Public query service is not configured."
        raise RuntimeError(msg)
    return service


def _ingestion_orchestrator(request: Request) -> SourceHugoNormalizationOrchestrationService:
    orchestrator = getattr(request.app.state, "source_hugo_normalization_orchestrator", None)
    if not isinstance(orchestrator, SourceHugoNormalizationOrchestrationService):
        msg = "Ingestion orchestration service is not configured."
        raise RuntimeError(msg)
    return orchestrator


def _confirmation_service(request: Request) -> WebMCPConfirmationService:
    service = getattr(request.app.state, "webmcp_confirmation_service", None)
    if not isinstance(service, WebMCPConfirmationService):
        msg = "WebMCP confirmation service is not configured."
        raise RuntimeError(msg)
    return service


def _write_audit_store(request: Request) -> InMemoryWebMCPWriteAuditStore:
    store = getattr(request.app.state, "webmcp_write_audit_store", None)
    if not isinstance(store, InMemoryWebMCPWriteAuditStore):
        msg = "WebMCP write audit store is not configured."
        raise RuntimeError(msg)
    return store


def _source_registry_service(request: Request) -> SourceRegistryService:
    service = getattr(request.app.state, "source_registry_service", None)
    if not isinstance(service, SourceRegistryService):
        msg = "Source registry service is not configured."
        raise RuntimeError(msg)
    return service


def _snapshot_registry(request: Request) -> SnapshotRegistry:
    registry = getattr(request.app.state, "snapshot_registry", None)
    if registry is None:
        msg = "Snapshot registry is not configured."
        raise RuntimeError(msg)
    return registry


def _get_admin_principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _to_auth_http_exception(request: Request, exc: AdminAuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail=_error_payload(request, code=exc.code, message=exc.message),
    )


def _resolve_repo_ids_for_write(
    *,
    request: Request,
    payload: _WebMCPRepoTargetRequest,
) -> tuple[str, ...]:
    repo_ids = payload.resolved_repo_ids()
    if not repo_ids:
        _raise_http_error(
            request,
            status_code=400,
            code="VALIDATION_ERROR",
            message="At least one repository target is required: provide `repo_id` or `repo_ids`.",
        )
        raise RuntimeError("unreachable")
    return repo_ids


def _resolve_target_product_ids_for_repos(
    *,
    request: Request,
    repo_ids: tuple[str, ...],
) -> tuple[str, ...]:
    source_registry = _source_registry_service(request)
    product_ids: list[str] = []
    for repo_id in repo_ids:
        try:
            repository = source_registry.get_repository(repo_id)
        except SourceRegistryLookupError as exc:
            _raise_http_error(
                request,
                status_code=400,
                code="VALIDATION_ERROR",
                message=public_error_message(
                    exc,
                    fallback="The request could not be completed.",
                    request_id=getattr(request.state, "request_id", None),
                    context="webmcp_gateway:VALIDATION_ERROR",
                ),
            )
            raise RuntimeError from exc
        product_ids.append(repository.product_id)
    return tuple(sorted(set(product_ids)))


def _authorize_ingestion_write(
    *,
    request: Request,
    target_product_ids: tuple[str, ...],
) -> None:
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=target_product_ids,
            destructive=False,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _require_confirmation_reason(request: Request, reason: str | None) -> str:
    if reason is None or not reason.strip():
        _raise_http_error(
            request,
            status_code=400,
            code="CONFIRMATION_REQUIRED",
            message="Missing `reason` for WebMCP write confirmation.",
        )
        raise RuntimeError("unreachable")
    assert reason is not None
    return reason.strip()


def _compose_confirmation_intent(
    *,
    intent_payload: dict[str, Any],
    principal: AdminKeyPrincipal,
) -> dict[str, Any]:
    payload = dict(intent_payload)
    payload["actor_key_id"] = principal.key_id
    return payload


def _consume_confirmation_or_raise(
    *,
    request: Request,
    tool_name: str,
    confirm_token: str | None,
    reason: str,
    intent_payload: dict[str, Any],
    principal: AdminKeyPrincipal,
) -> WebMCPConfirmationRecord:
    confirmation_service = _confirmation_service(request)
    try:
        return confirmation_service.consume(
            confirm_token=confirm_token,
            tool_name=tool_name,
            reason=reason,
            intent_payload=_compose_confirmation_intent(
                intent_payload=intent_payload,
                principal=principal,
            ),
            request_id=getattr(request.state, "request_id", None),
        )
    except WebMCPConfirmationError as exc:
        status_code = 409 if exc.code == "CONFIRMATION_REPLAYED" else 400
        _raise_http_error(
            request,
            status_code=status_code,
            code=exc.code,
            message=exc.message,
        )
    except ValueError as exc:
        _raise_http_error(
            request,
            status_code=400,
            code="VALIDATION_ERROR",
            message=public_error_message(
                exc,
                fallback="The request could not be completed.",
                request_id=getattr(request.state, "request_id", None),
                context="webmcp_gateway:VALIDATION_ERROR",
            ),
        )
    raise RuntimeError("unreachable")


def _record_write_audit(
    *,
    request: Request,
    tool_name: str,
    status: WebMCPWriteAuditStatus,
    reason: str | None,
    confirm_token: str | None,
    target: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> WebMCPWriteAuditRecord:
    principal = _get_admin_principal(request)
    store = _write_audit_store(request)
    record = store.record(
        tool_name=tool_name,
        status=status,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=reason,
        confirm_token=confirm_token,
        target=target,
        error_code=error_code,
    )
    request.state.webmcp_write_audit_recorded = True
    return record


def _to_confirmation_response(
    *,
    record: WebMCPConfirmationRecord,
    ttl_seconds: int,
) -> WebMCPConfirmationIssueResponse:
    return WebMCPConfirmationIssueResponse(
        confirm_token=record.confirm_token,
        tool_name=record.tool_name,
        reason=record.reason,
        intent_fingerprint=record.intent_fingerprint,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
        ttl_seconds=ttl_seconds,
    )


def _to_ingestion_write_response(
    *,
    tool_name: str,
    operation: SourceHugoNormalizationOperation,
    repo_ids: tuple[str, ...],
    audit_id: str,
    request_id: str | None,
) -> WebMCPWriteOperationResponse:
    return WebMCPWriteOperationResponse(
        tool_name=tool_name,
        status=operation.status.value,
        request_id=request_id,
        audit_id=audit_id,
        operation_id=operation.operation_id,
        repo_ids=list(repo_ids),
    )


def _to_snapshot_write_response(
    *,
    tool_name: str,
    snapshot: SnapshotRecord,
    audit_id: str,
    request_id: str | None,
) -> WebMCPWriteOperationResponse:
    return WebMCPWriteOperationResponse(
        tool_name=tool_name,
        status="completed",
        request_id=request_id,
        audit_id=audit_id,
        snapshot_id=snapshot.snapshot_id,
        product_id=snapshot.product_id,
        programming_language=snapshot.programming_language,
        version=snapshot.version,
    )


def _to_write_audit_response(record: WebMCPWriteAuditRecord) -> WebMCPWriteAuditResponse:
    return WebMCPWriteAuditResponse(
        audit_id=record.audit_id,
        tool_name=record.tool_name,
        status=record.status,
        actor_key_id=record.actor_key_id,
        request_id=record.request_id,
        reason=record.reason,
        confirm_token_hash=record.confirm_token_hash,
        target=dict(record.target),
        error_code=record.error_code,
        created_at=record.created_at,
    )


@router.get("/webmcp/v1/capabilities", response_model=WebMCPCapabilitiesResponse)
def webmcp_capabilities(request: Request) -> WebMCPCapabilitiesResponse:
    _require_webmcp_enabled(request)
    return WebMCPCapabilitiesResponse(
        enabled=True,
        tools=[
            WebMCPToolDescriptor(
                tool_name="web_get_system_status",
                read_only=True,
                mapped_backend_contract="GET /healthz + GET /readyz",
            ),
            WebMCPToolDescriptor(
                tool_name="web_query_docs_preview",
                read_only=True,
                mapped_backend_contract="POST /v1/docs:query",
            ),
            WebMCPToolDescriptor(
                tool_name="web_list_ingestion_jobs",
                read_only=True,
                mapped_backend_contract="GET /admin/v1/ingestion/jobs",
            ),
            WebMCPToolDescriptor(
                tool_name="web_trigger_ingestion",
                read_only=False,
                mapped_backend_contract="POST /admin/v1/ingestion/trigger",
                requires_confirmation=True,
            ),
            WebMCPToolDescriptor(
                tool_name="web_trigger_reindex",
                read_only=False,
                mapped_backend_contract="POST /admin/v1/ingestion/reindex",
                requires_confirmation=True,
            ),
            WebMCPToolDescriptor(
                tool_name="web_promote_snapshot",
                read_only=False,
                mapped_backend_contract="POST /admin/v1/snapshots/{snapshot_id}:promote",
                requires_confirmation=True,
            ),
        ],
    )


@router.post(
    "/webmcp/v1/confirmations",
    response_model=WebMCPConfirmationIssueResponse,
    dependencies=[Depends(require_admin_principal)],
)
def issue_webmcp_confirmation(
    payload: WebMCPConfirmationIssueRequest,
    request: Request,
) -> WebMCPConfirmationIssueResponse:
    _require_webmcp_enabled(request)
    if payload.tool_name not in _ALL_WEBMCP_TOOL_NAMES:
        _raise_http_error(
            request,
            status_code=400,
            code="VALIDATION_ERROR",
            message=f"Unsupported WebMCP tool: `{payload.tool_name}`.",
            details={"supported_tools": sorted(_ALL_WEBMCP_TOOL_NAMES)},
        )
    principal = _get_admin_principal(request)
    service = _confirmation_service(request)
    issued = service.issue(
        tool_name=payload.tool_name,
        reason=payload.reason,
        intent_payload=_compose_confirmation_intent(
            intent_payload=payload.intent,
            principal=principal,
        ),
    )
    return _to_confirmation_response(record=issued, ttl_seconds=service.ttl_seconds)


@router.post("/webmcp/v1/tools/web_get_system_status", response_model=WebGetSystemStatusResponse)
def web_get_system_status(request: Request) -> WebGetSystemStatusResponse:
    _require_webmcp_enabled(request)
    readiness_results = readiness.check_dependencies(
        request.app.state.settings,
        adapter_modes=getattr(request.app.state, "adapter_modes", None),
    )
    _, ready_payload = readiness.build_readiness_response(readiness_results)
    return WebGetSystemStatusResponse(
        healthz={"status": "ok"},
        readyz=ready_payload,
        generated_at=datetime.now(tz=UTC),
    )


@router.post("/webmcp/v1/tools/web_query_docs_preview", response_model=QueryDocsResponse)
def web_query_docs_preview(
    payload: WebQueryDocsPreviewRequest,
    request: Request,
) -> QueryDocsResponse:
    _require_webmcp_enabled(request)
    service = _public_query_service(request)
    return service.query_docs(
        request=QueryDocsRequest(
            query=payload.query,
            product_id=payload.product_id,
            language=payload.language,
            version=payload.version,
            query_locale=payload.query_locale,
            top_k=payload.top_k,
            strict_version=payload.strict_version,
            doc_types=payload.doc_types,
            include_examples=payload.include_examples,
            debug=False,
        )
    )


@router.post(
    "/webmcp/v1/tools/web_list_ingestion_jobs",
    response_model=list[WebIngestionJobResponse],
    dependencies=[Depends(require_admin_principal)],
)
def web_list_ingestion_jobs(
    payload: WebListIngestionJobsRequest,
    request: Request,
) -> list[WebIngestionJobResponse]:
    _require_webmcp_enabled(request)
    orchestrator = _ingestion_orchestrator(request)
    operations = orchestrator.list_operations(limit=payload.limit)
    return [
        WebIngestionJobResponse(
            operation_id=operation.operation_id,
            status=operation.status.value,
            repo_ids=list(operation.repo_ids),
            mode=operation.mode.value,
            started_at=operation.started_at,
            finished_at=operation.finished_at,
            request_id=operation.request_id,
        )
        for operation in operations
    ]


@router.get(
    "/webmcp/v1/tools/web_list_ingestion_jobs",
    response_model=list[WebIngestionJobResponse],
    dependencies=[Depends(require_admin_principal)],
)
def web_list_ingestion_jobs_get(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[WebIngestionJobResponse]:
    return web_list_ingestion_jobs(
        payload=WebListIngestionJobsRequest(limit=limit),
        request=request,
    )


@router.post(
    "/webmcp/v1/tools/web_trigger_ingestion",
    response_model=WebMCPWriteOperationResponse,
    dependencies=[Depends(require_admin_principal)],
)
def web_trigger_ingestion(
    payload: WebTriggerIngestionRequest,
    request: Request,
) -> WebMCPWriteOperationResponse:
    _require_webmcp_enabled(request)
    tool_name = "web_trigger_ingestion"
    request_id = getattr(request.state, "request_id", None)
    reason = payload.reason
    target: dict[str, Any] = {
        "repo_ids": [],
        "product_ids": [],
        "dry_run": payload.dry_run,
        "force_full_reindex": False,
    }
    try:
        repo_ids = _resolve_repo_ids_for_write(request=request, payload=payload)
        target_product_ids = _resolve_target_product_ids_for_repos(
            request=request,
            repo_ids=repo_ids,
        )
        target["repo_ids"] = list(repo_ids)
        target["product_ids"] = list(target_product_ids)
        principal = _get_admin_principal(request)
        _authorize_ingestion_write(request=request, target_product_ids=target_product_ids)
        normalized_reason = _require_confirmation_reason(request, payload.reason)
        _consume_confirmation_or_raise(
            request=request,
            tool_name=tool_name,
            confirm_token=payload.confirm_token,
            reason=normalized_reason,
            intent_payload={"repo_ids": list(repo_ids), "dry_run": payload.dry_run},
            principal=principal,
        )
        operation = _ingestion_orchestrator(request).run(
            repo_ids=repo_ids,
            mode=IngestionRunMode.PUBLISH,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            dry_run=payload.dry_run,
            force_full_reindex=False,
        )
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=WebMCPWriteAuditStatus.SUCCEEDED,
            reason=normalized_reason,
            confirm_token=payload.confirm_token,
            target=target,
        )
        return _to_ingestion_write_response(
            tool_name=tool_name,
            operation=operation,
            repo_ids=repo_ids,
            audit_id=audit.audit_id,
            request_id=request_id,
        )
    except IngestionIdempotencyConflictError as exc:
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=WebMCPWriteAuditStatus.REJECTED,
            reason=reason,
            confirm_token=payload.confirm_token,
            target=target,
            error_code="IDEMPOTENCY_CONFLICT",
        )
        _raise_http_error(
            request,
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message=public_error_message(
                exc,
                fallback="The request could not be completed.",
                request_id=getattr(request.state, "request_id", None),
                context="webmcp_gateway:IDEMPOTENCY_CONFLICT",
            ),
            details={"audit_id": audit.audit_id},
        )
        raise RuntimeError("unreachable")
    except HTTPException as exc:
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=_audit_status_from_http_status(exc.status_code),
            reason=reason,
            confirm_token=payload.confirm_token,
            target=target,
            error_code=_error_code_from_http_exception(exc),
        )
        detail = exc.detail
        if isinstance(detail, dict):
            error = detail.get("error")
            if isinstance(error, dict):
                details = error.get("details")
                if isinstance(details, dict):
                    details.setdefault("audit_id", audit.audit_id)
                else:
                    error["details"] = {"audit_id": audit.audit_id}
        raise


@router.post(
    "/webmcp/v1/tools/web_trigger_reindex",
    response_model=WebMCPWriteOperationResponse,
    dependencies=[Depends(require_admin_principal)],
)
def web_trigger_reindex(
    payload: WebTriggerReindexRequest,
    request: Request,
) -> WebMCPWriteOperationResponse:
    _require_webmcp_enabled(request)
    tool_name = "web_trigger_reindex"
    request_id = getattr(request.state, "request_id", None)
    reason = payload.reason
    target: dict[str, Any] = {
        "repo_ids": [],
        "product_ids": [],
        "force_full_reindex": True,
    }
    try:
        repo_ids = _resolve_repo_ids_for_write(request=request, payload=payload)
        target_product_ids = _resolve_target_product_ids_for_repos(
            request=request,
            repo_ids=repo_ids,
        )
        target["repo_ids"] = list(repo_ids)
        target["product_ids"] = list(target_product_ids)
        principal = _get_admin_principal(request)
        _authorize_ingestion_write(request=request, target_product_ids=target_product_ids)
        normalized_reason = _require_confirmation_reason(request, payload.reason)
        _consume_confirmation_or_raise(
            request=request,
            tool_name=tool_name,
            confirm_token=payload.confirm_token,
            reason=normalized_reason,
            intent_payload={"repo_ids": list(repo_ids), "force_full_reindex": True},
            principal=principal,
        )
        operation = _ingestion_orchestrator(request).run(
            repo_ids=repo_ids,
            mode=IngestionRunMode.PUBLISH,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            dry_run=False,
            force_full_reindex=True,
        )
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=WebMCPWriteAuditStatus.SUCCEEDED,
            reason=normalized_reason,
            confirm_token=payload.confirm_token,
            target=target,
        )
        return _to_ingestion_write_response(
            tool_name=tool_name,
            operation=operation,
            repo_ids=repo_ids,
            audit_id=audit.audit_id,
            request_id=request_id,
        )
    except IngestionIdempotencyConflictError as exc:
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=WebMCPWriteAuditStatus.REJECTED,
            reason=reason,
            confirm_token=payload.confirm_token,
            target=target,
            error_code="IDEMPOTENCY_CONFLICT",
        )
        _raise_http_error(
            request,
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message=public_error_message(
                exc,
                fallback="The request could not be completed.",
                request_id=getattr(request.state, "request_id", None),
                context="webmcp_gateway:IDEMPOTENCY_CONFLICT",
            ),
            details={"audit_id": audit.audit_id},
        )
        raise RuntimeError("unreachable")
    except HTTPException as exc:
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=_audit_status_from_http_status(exc.status_code),
            reason=reason,
            confirm_token=payload.confirm_token,
            target=target,
            error_code=_error_code_from_http_exception(exc),
        )
        detail = exc.detail
        if isinstance(detail, dict):
            error = detail.get("error")
            if isinstance(error, dict):
                details = error.get("details")
                if isinstance(details, dict):
                    details.setdefault("audit_id", audit.audit_id)
                else:
                    error["details"] = {"audit_id": audit.audit_id}
        raise


@router.post(
    "/webmcp/v1/tools/web_promote_snapshot",
    response_model=WebMCPWriteOperationResponse,
    dependencies=[Depends(require_admin_principal)],
)
def web_promote_snapshot(
    payload: WebPromoteSnapshotRequest,
    request: Request,
) -> WebMCPWriteOperationResponse:
    _require_webmcp_enabled(request)
    tool_name = "web_promote_snapshot"
    request_id = getattr(request.state, "request_id", None)
    reason = payload.reason
    target: dict[str, Any] = {"snapshot_id": payload.snapshot_id}
    try:
        principal = _get_admin_principal(request)
        snapshot = _snapshot_registry(request).get_snapshot(payload.snapshot_id)
        if snapshot is None:
            _raise_http_error(
                request,
                status_code=404,
                code="NOT_FOUND",
                message=f"Snapshot `{payload.snapshot_id}` was not found.",
            )
            raise RuntimeError("unreachable")
        assert snapshot is not None
        _authorize_ingestion_write(
            request=request,
            target_product_ids=(snapshot.product_id,),
        )
        target.update(
            {
                "product_id": snapshot.product_id,
                "programming_language": snapshot.programming_language,
                "version": snapshot.version,
            }
        )
        normalized_reason = _require_confirmation_reason(request, payload.reason)
        _consume_confirmation_or_raise(
            request=request,
            tool_name=tool_name,
            confirm_token=payload.confirm_token,
            reason=normalized_reason,
            intent_payload={"snapshot_id": payload.snapshot_id},
            principal=principal,
        )
        promoted = _snapshot_registry(request).promote_snapshot(snapshot_id=payload.snapshot_id)
        if promoted is None:
            _raise_http_error(
                request,
                status_code=404,
                code="NOT_FOUND",
                message=f"Snapshot `{payload.snapshot_id}` was not found.",
            )
            raise RuntimeError("unreachable")
        assert promoted is not None
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=WebMCPWriteAuditStatus.SUCCEEDED,
            reason=normalized_reason,
            confirm_token=payload.confirm_token,
            target=target,
        )
        return _to_snapshot_write_response(
            tool_name=tool_name,
            snapshot=promoted,
            audit_id=audit.audit_id,
            request_id=request_id,
        )
    except HTTPException as exc:
        audit = _record_write_audit(
            request=request,
            tool_name=tool_name,
            status=_audit_status_from_http_status(exc.status_code),
            reason=reason,
            confirm_token=payload.confirm_token,
            target=target,
            error_code=_error_code_from_http_exception(exc),
        )
        detail = exc.detail
        if isinstance(detail, dict):
            error = detail.get("error")
            if isinstance(error, dict):
                details = error.get("details")
                if isinstance(details, dict):
                    details.setdefault("audit_id", audit.audit_id)
                else:
                    error["details"] = {"audit_id": audit.audit_id}
        raise


@router.get(
    "/webmcp/v1/audit/write-invocations",
    response_model=list[WebMCPWriteAuditResponse],
    dependencies=[Depends(require_admin_principal)],
)
def list_webmcp_write_invocations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    tool_name: str | None = None,
    status: WebMCPWriteAuditStatus | None = None,
) -> list[WebMCPWriteAuditResponse]:
    _require_webmcp_enabled(request)
    records = _write_audit_store(request).list_records(
        limit=limit,
        tool_name=tool_name,
        status=status,
    )
    return [_to_write_audit_response(record) for record in records]
