"""Admin API endpoints for registries, retrieval settings, and analytics."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.admin import (
    AnalyticsService,
    InMemoryConfigHistoryService,
    InMemoryRegistryService,
    InMemoryRetrievalSettingsService,
    InMemorySemanticReviewService,
    SemanticReviewBlockingErrorType,
    SemanticReviewCandidateItem,
    SemanticReviewFixPlanPriority,
    SemanticReviewFixPlanStep,
    SemanticReviewGuidedFixPlan,
    SemanticReviewRunOrigin,
)
from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.api.admin_quality_reviews import (
    QualityReviewRunResponse,
    _to_run_response,
)
from adcs.api.admin_system import _collect_content_service_rows
from adcs.api.public_docs_query import (
    PublicQueryService,
    QueryDocsRequest,
    QueryDocsResponse,
    _filter_release_feature_records,
)
from adcs.indexing.snapshot_registry import SnapshotRegistry
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)

router = APIRouter(
    tags=["admin-registries-analytics"],
    dependencies=[Depends(require_admin_principal)],
)


class RegistryLanguageResponse(BaseModel):
    lang_id: str
    display_name: str
    enabled: bool
    created_at: datetime


class RegistryLocaleResponse(BaseModel):
    locale_id: str
    display_name: str
    enabled: bool
    created_at: datetime


class RegistryAliasResponse(BaseModel):
    product_id: str
    external_language_id: str
    canonical_lang_id: str
    created_at: datetime


class UpsertRegistryLanguageRequest(BaseModel):
    lang_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True

    @field_validator("lang_id", "display_name")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class UpsertRegistryLocaleRequest(BaseModel):
    locale_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool = True

    @field_validator("locale_id", "display_name")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class UpsertRegistryAliasRequest(BaseModel):
    product_id: str = Field(min_length=1)
    external_language_id: str = Field(min_length=1)
    canonical_lang_id: str = Field(min_length=1)

    @field_validator("product_id", "external_language_id", "canonical_lang_id")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class RetrievalSettingsResponse(BaseModel):
    product_id: str
    top_k: int
    max_context_tokens: int
    excerpt_char_limit: int
    low_confidence_threshold: float
    clarification_policy: str
    updated_by: str
    updated_at: datetime


class PatchRetrievalSettingsRequest(BaseModel):
    top_k: int = Field(ge=1, le=50)
    max_context_tokens: int = Field(ge=512, le=65536)
    excerpt_char_limit: int = Field(ge=120, le=5000)
    low_confidence_threshold: float = Field(ge=0.0, le=1.0)
    clarification_policy: str = Field(min_length=1, max_length=120)


class AnalyticsSliceResponse(BaseModel):
    total_requests: int
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_doc_locale: dict[str, int]
    by_endpoint: dict[str, int]
    by_tool: dict[str, int]
    by_outcome: dict[str, int]
    by_retrieval_mode: dict[str, int]
    by_zero_result_reason: dict[str, int]
    by_fallback_reason: dict[str, int]
    by_warning_code: dict[str, int]
    refreshed_at: datetime
    refresh_lag_minutes: int


class ZeroResultClusterResponse(BaseModel):
    cluster_id: str
    zero_result_reason: str
    fallback_reason: str
    retrieval_mode: str
    primary_warning_code: str
    total_requests: int
    share_of_filtered_requests: float
    affected_products: list[str]
    affected_programming_languages: list[str]
    affected_doc_locales: list[str]
    sample_queries: list[str]
    recommendation_title: str
    recommendation_detail: str


class ZeroResultOverviewResponse(BaseModel):
    filtered_requests_total: int
    without_useful_result_requests: int
    without_useful_result_share: float
    no_result_requests: int
    low_confidence_requests: int
    by_zero_result_reason: dict[str, int]
    by_fallback_reason: dict[str, int]
    by_warning_code: dict[str, int]
    by_retrieval_mode: dict[str, int]
    top_affected_products: dict[str, int]
    top_affected_programming_languages: dict[str, int]
    clusters: list[ZeroResultClusterResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class CapacityForecastProductResponse(BaseModel):
    product_id: str
    recent_requests: int
    previous_window_requests: int
    projected_requests_next_24h: int
    growth_ratio: float
    zero_result_pressure_share: float
    low_confidence_share: float
    warning_density: float
    coverage_saturation_score: float
    saturation_risk: str
    recommended_action: str


class CapacityForecastResponse(BaseModel):
    filtered_requests_total: int
    observed_window_hours: float
    projected_requests_next_24h: int
    previous_window_requests: int
    growth_ratio: float
    zero_result_pressure_share: float
    low_confidence_share: float
    warning_density: float
    coverage_saturation_score: float
    saturation_risk: str
    recommended_action: str
    hottest_products: list[CapacityForecastProductResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class UsefulnessSignalResponse(BaseModel):
    feedback_id: str
    request_id: str
    rating: str
    reason_codes: list[str]
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    endpoint: str
    tool: str
    raw_query: str
    outcome: str
    retrieval_mode: str | None = None
    result_count: int
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    warning_codes: list[str]
    created_at: datetime
    updated_at: datetime


class UsefulnessSummaryResponse(BaseModel):
    total_feedback: int
    useful_feedback: int
    partially_useful_feedback: int
    not_useful_feedback: int
    useful_share: float
    negative_share: float
    by_rating: dict[str, int]
    by_reason_code: dict[str, int]
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_doc_locale: dict[str, int]
    recent_negative_signals: list[UsefulnessSignalResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class IssueReviewSignalResponse(BaseModel):
    issue_id: str
    request_id: str
    issue_type: str
    severity: str
    severity_reason: str
    recommendation_title: str
    recommendation_detail: str
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    endpoint: str
    tool: str
    raw_query: str
    outcome: str
    retrieval_mode: str | None = None
    result_count: int
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    warning_codes: list[str]
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class IssueReviewSummaryResponse(BaseModel):
    total_reports: int
    by_issue_type: dict[str, int]
    by_severity: dict[str, int]
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_doc_locale: dict[str, int]
    recommendation_mix: dict[str, int]
    recent_reports: list[IssueReviewSignalResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class RequestReplayInputResponse(BaseModel):
    query: str
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    version: str | None = None
    top_k: int
    strict_version: bool
    include_examples: bool
    doc_types: list[str]
    assumptions: list[str]


class RequestEvidenceOriginalResponse(BaseModel):
    request_id: str
    endpoint: str
    tool: str
    raw_query: str
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    confidence: float
    outcome: str
    retrieval_mode: str | None = None
    result_count: int
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    warning_codes: list[str]
    created_at: datetime


class RequestEvidenceReplayResponse(BaseModel):
    executed_at: datetime
    request: RequestReplayInputResponse
    outcome: str
    result_count: int
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    response: QueryDocsResponse


class RequestEvidenceDiffResponse(BaseModel):
    drift_status: str
    summary: str
    outcome_changed: bool
    original_outcome: str
    current_outcome: str
    result_count_delta: int
    confidence_delta: float
    warning_codes_added: list[str]
    warning_codes_removed: list[str]
    fallback_changed: bool
    original_fallback_reason: str | None = None
    current_fallback_reason: str | None = None
    zero_result_reason_changed: bool
    original_zero_result_reason: str | None = None
    current_zero_result_reason: str | None = None
    suspected_fault_domain: str
    suspected_fault_reason: str
    operator_hint: str
    unavailable_original_fields: list[str]


class RequestEvidenceResponse(BaseModel):
    request_id: str
    original: RequestEvidenceOriginalResponse
    replay: RequestEvidenceReplayResponse
    diff: RequestEvidenceDiffResponse
    related_issue_reports: list[IssueReviewSignalResponse]
    related_usefulness_feedback: list[UsefulnessSignalResponse]
    copy_context: dict[str, Any]
    generated_at: datetime


class CreateGuidedContentFixDraftRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    issue_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("request_id", "issue_id")
    @classmethod
    def _normalize_optional_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class GuidedContentFixStepResponse(BaseModel):
    step_id: str
    title: str
    detail: str
    target_section: str
    action_kind: str


class GuidedContentFixPlanResponse(BaseModel):
    summary: str
    priority: str
    owner_hint: str
    next_step: str
    actions: list[GuidedContentFixStepResponse]


class GuidedContentFixDraftResponse(BaseModel):
    request_id: str
    issue_id: str | None = None
    issue_type: str | None = None
    severity: str | None = None
    product_id: str
    programming_language: str | None = None
    doc_locale: str | None = None
    source_revision: str
    recommendation_title: str
    recommendation_detail: str
    quality_review_run: QualityReviewRunResponse
    fix_plan: GuidedContentFixPlanResponse
    generated_at: datetime


class IssueHotspotClusterResponse(BaseModel):
    hotspot_id: str
    priority: str
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    issue_type: str
    severity: str
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    primary_warning_code: str
    total_reports: int
    unique_request_ids: int
    recent_reports_24h: int
    previous_reports_24h: int
    trend_status: str
    trend_delta: int
    share_of_filtered_reports: float
    sample_queries: list[str]
    sample_request_ids: list[str]
    recommendation_title: str
    recommendation_detail: str


class IssueHotspotOverviewResponse(BaseModel):
    filtered_reports_total: int
    hotspots_total: int
    by_priority: dict[str, int]
    by_product_id: dict[str, int]
    by_issue_type: dict[str, int]
    by_severity: dict[str, int]
    clusters: list[IssueHotspotClusterResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class PublicFunnelStageResponse(BaseModel):
    stage_id: str
    title: str
    sessions: int
    share_of_filtered_sessions: float
    conversion_from_previous: float | None = None


class PublicFunnelDropoffResponse(BaseModel):
    dropoff_id: str
    stage_id: str
    reason: str
    sessions: int
    share_of_filtered_sessions: float
    recommendation_title: str
    recommendation_detail: str


class PublicFunnelScopeResponse(BaseModel):
    scope_id: str
    product_id: str | None = None
    programming_language: str | None = None
    client_id: str | None = None
    sessions: int
    resolve_sessions: int
    self_test_sessions: int
    query_sessions: int
    feedback_sessions: int
    issue_sessions: int
    zero_result_sessions: int
    latest_activity_at: datetime


class PublicFunnelOverviewResponse(BaseModel):
    filtered_sessions_total: int
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_client_id: dict[str, int]
    stages: list[PublicFunnelStageResponse]
    top_dropoffs: list[PublicFunnelDropoffResponse]
    scopes: list[PublicFunnelScopeResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class FreshnessWatchlistScopeResponse(BaseModel):
    scope_id: str
    product_id: str
    programming_language: str | None = None
    source_kind: str
    repo_id: str
    risk_score: int
    risk_level: str
    primary_reason: str
    recommended_action: str
    stale_days: int | None = None
    latest_active_snapshot_at: datetime | None = None
    latest_active_version: str | None = None
    newest_visible_version: str | None = None
    release_visibility_gap: bool
    release_feature_signals: int
    query_sessions_30d: int
    no_result_sessions_30d: int
    low_confidence_sessions_30d: int
    issue_reports_30d: int
    critical_issue_reports_30d: int
    negative_feedback_30d: int
    indexed_chunks_count: int
    executable_snippets_count: int
    parse_warnings_count: int
    failed_items_count: int
    service_status: str
    service_status_reason: str
    fix_plan: list[str]


class FreshnessWatchlistOverviewResponse(BaseModel):
    filtered_scopes_total: int
    high_risk_total: int
    medium_risk_total: int
    low_risk_total: int
    by_product_id: dict[str, int]
    by_programming_language: dict[str, int]
    by_source_kind: dict[str, int]
    status_summary: str
    items: list[FreshnessWatchlistScopeResponse]
    refreshed_at: datetime
    refresh_lag_minutes: int


class AnalyticsSqlQueryRequest(BaseModel):
    sql: str = Field(min_length=1)
    max_rows: int = Field(default=1000, ge=1, le=10_000)


class AnalyticsSqlQueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class AnalyticsSqlExportResponse(BaseModel):
    filename: str
    row_count: int
    csv_payload: str


class AnalyticsSqlSchemaColumn(BaseModel):
    name: str
    data_type: str
    description: str | None = None


class AnalyticsSqlSchemaTable(BaseModel):
    name: str
    description: str
    columns: list[AnalyticsSqlSchemaColumn]
    sample_query: str


class AnalyticsSqlSchemaResponse(BaseModel):
    tables: list[AnalyticsSqlSchemaTable]
    blocked_tables: list[str]
    blocked_column_patterns: list[str]
    notes: list[str]


class ConfigHistoryResponse(BaseModel):
    change_id: str
    product_id: str
    config_scope: str
    config_key: str
    action_type: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    actor_key_id: str
    request_id: str | None
    reason: str | None
    rollback_of_change_id: str | None
    created_at: datetime
    artifact_path: str


class ConfigRollbackRequest(BaseModel):
    change_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, min_length=1, max_length=240)


class ConfigRollbackResponse(BaseModel):
    rolled_back_change_id: str
    rollback_change_id: str
    status: str


def _get_registry_service(request: Request) -> InMemoryRegistryService:
    service = getattr(request.app.state, "registry_service", None)
    if not isinstance(service, InMemoryRegistryService):
        msg = "Registry service is not configured."
        raise RuntimeError(msg)
    return service


def _get_retrieval_settings_service(request: Request) -> InMemoryRetrievalSettingsService:
    service = getattr(request.app.state, "retrieval_settings_service", None)
    if not isinstance(service, InMemoryRetrievalSettingsService):
        msg = "Retrieval settings service is not configured."
        raise RuntimeError(msg)
    return service


def _get_analytics_service(request: Request) -> AnalyticsService:
    service = getattr(request.app.state, "analytics_service", None)
    if not isinstance(service, AnalyticsService):
        msg = "Analytics service is not configured."
        raise RuntimeError(msg)
    return service


def _get_public_query_service(request: Request) -> PublicQueryService:
    service = getattr(request.app.state, "public_query_service", None)
    if not isinstance(service, PublicQueryService):
        msg = "Public query service is not configured."
        raise RuntimeError(msg)
    return service


def _get_review_service(request: Request) -> InMemorySemanticReviewService:
    service = getattr(request.app.state, "semantic_review_service", None)
    if not isinstance(service, InMemorySemanticReviewService):
        msg = "Semantic review service is not configured."
        raise RuntimeError(msg)
    return service


def _get_source_hugo_orchestrator(
    request: Request,
) -> SourceHugoNormalizationOrchestrationService | None:
    service = getattr(request.app.state, "source_hugo_normalization_orchestrator", None)
    if not isinstance(service, SourceHugoNormalizationOrchestrationService):
        return None
    return service


def _get_snapshot_registry(request: Request) -> SnapshotRegistry:
    service = getattr(request.app.state, "snapshot_registry", None)
    if service is None or not hasattr(service, "list_snapshots"):
        msg = "Snapshot registry is not configured."
        raise RuntimeError(msg)
    return service


def _get_config_history_service(request: Request) -> InMemoryConfigHistoryService:
    service = getattr(request.app.state, "config_history_service", None)
    if not isinstance(service, InMemoryConfigHistoryService):
        msg = "Config history service is not configured."
        raise RuntimeError(msg)
    return service


def _get_admin_principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


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


def _authorize_write_for_product(request: Request, *, product_id: str) -> None:
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=(product_id.strip().casefold(),),
            destructive=False,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _authorize_global_registry_write(request: Request) -> None:
    principal = _get_admin_principal(request)
    if principal.is_superuser:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": {
                "code": "FORBIDDEN",
                "message": "Only superuser key can mutate global registries.",
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _record_config_history(
    request: Request,
    *,
    product_id: str,
    config_scope: str,
    config_key: str,
    action_type: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None = None,
    rollback_of_change_id: str | None = None,
) -> ConfigHistoryResponse:
    history_service = _get_config_history_service(request)
    principal = _get_admin_principal(request)
    record = history_service.record_change(
        product_id=product_id,
        config_scope=config_scope,
        config_key=config_key,
        action_type=action_type,
        before=before,
        after=after,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=reason,
        rollback_of_change_id=rollback_of_change_id,
    )
    return ConfigHistoryResponse(
        change_id=record.change_id,
        product_id=record.product_id,
        config_scope=record.config_scope,
        config_key=record.config_key,
        action_type=record.action_type,
        before=record.before,
        after=record.after,
        actor_key_id=record.actor_key_id,
        request_id=record.request_id,
        reason=record.reason,
        rollback_of_change_id=record.rollback_of_change_id,
        created_at=record.created_at,
        artifact_path=record.artifact_path,
    )

@router.get("/admin/v1/registries/languages", response_model=list[RegistryLanguageResponse])
def list_registry_languages(request: Request) -> list[RegistryLanguageResponse]:
    service = _get_registry_service(request)
    return [
        RegistryLanguageResponse(
            lang_id=record.lang_id,
            display_name=record.display_name,
            enabled=record.enabled,
            created_at=record.created_at,
        )
        for record in service.list_languages()
    ]


@router.post("/admin/v1/registries/languages", response_model=RegistryLanguageResponse)
def upsert_registry_language(
    payload: UpsertRegistryLanguageRequest,
    request: Request,
) -> RegistryLanguageResponse:
    _authorize_global_registry_write(request)
    service = _get_registry_service(request)
    record = service.upsert_language(
        lang_id=payload.lang_id,
        display_name=payload.display_name,
        enabled=payload.enabled,
    )
    return RegistryLanguageResponse(
        lang_id=record.lang_id,
        display_name=record.display_name,
        enabled=record.enabled,
        created_at=record.created_at,
    )


@router.delete("/admin/v1/registries/languages")
def delete_registry_language(
    request: Request,
    lang_id: str = Query(min_length=1),
) -> dict[str, object]:
    _authorize_global_registry_write(request)
    service = _get_registry_service(request)
    try:
        deleted = service.delete_language(lang_id=lang_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": str(exc),
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        ) from exc
    return {"deleted": deleted}


@router.get("/admin/v1/registries/locales", response_model=list[RegistryLocaleResponse])
def list_registry_locales(request: Request) -> list[RegistryLocaleResponse]:
    service = _get_registry_service(request)
    return [
        RegistryLocaleResponse(
            locale_id=record.locale_id,
            display_name=record.display_name,
            enabled=record.enabled,
            created_at=record.created_at,
        )
        for record in service.list_locales()
    ]


@router.post("/admin/v1/registries/locales", response_model=RegistryLocaleResponse)
def upsert_registry_locale(
    payload: UpsertRegistryLocaleRequest,
    request: Request,
) -> RegistryLocaleResponse:
    _authorize_global_registry_write(request)
    service = _get_registry_service(request)
    record = service.upsert_locale(
        locale_id=payload.locale_id,
        display_name=payload.display_name,
        enabled=payload.enabled,
    )
    return RegistryLocaleResponse(
        locale_id=record.locale_id,
        display_name=record.display_name,
        enabled=record.enabled,
        created_at=record.created_at,
    )


@router.delete("/admin/v1/registries/locales")
def delete_registry_locale(
    request: Request,
    locale_id: str = Query(min_length=1),
) -> dict[str, object]:
    _authorize_global_registry_write(request)
    service = _get_registry_service(request)
    deleted = service.delete_locale(locale_id=locale_id)
    return {"deleted": deleted}


@router.get(
    "/admin/v1/registries/languages/aliases",
    response_model=list[RegistryAliasResponse],
)
def list_registry_language_aliases(
    request: Request,
    product_id: str | None = None,
) -> list[RegistryAliasResponse]:
    service = _get_registry_service(request)
    return [
        RegistryAliasResponse(
            product_id=record.product_id,
            external_language_id=record.external_language_id,
            canonical_lang_id=record.canonical_lang_id,
            created_at=record.created_at,
        )
        for record in service.list_language_aliases(product_id=product_id)
    ]


@router.post(
    "/admin/v1/registries/languages/aliases",
    response_model=RegistryAliasResponse,
)
def upsert_registry_language_alias(
    payload: UpsertRegistryAliasRequest,
    request: Request,
) -> RegistryAliasResponse:
    _authorize_write_for_product(request, product_id=payload.product_id)
    service = _get_registry_service(request)
    previous = service.get_language_alias(
        product_id=payload.product_id,
        external_language_id=payload.external_language_id,
    )
    try:
        record = service.upsert_language_alias(
            product_id=payload.product_id,
            external_language_id=payload.external_language_id,
            canonical_lang_id=payload.canonical_lang_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_config_history(
        request,
        product_id=record.product_id,
        config_scope="language_alias",
        config_key=f"{record.product_id}:{record.external_language_id}",
        action_type="upsert_alias",
        before=(
            {
                "product_id": previous.product_id,
                "external_language_id": previous.external_language_id,
                "canonical_lang_id": previous.canonical_lang_id,
            }
            if previous is not None
            else None
        ),
        after={
            "product_id": record.product_id,
            "external_language_id": record.external_language_id,
            "canonical_lang_id": record.canonical_lang_id,
        },
    )
    return RegistryAliasResponse(
        product_id=record.product_id,
        external_language_id=record.external_language_id,
        canonical_lang_id=record.canonical_lang_id,
        created_at=record.created_at,
    )


@router.delete("/admin/v1/registries/languages/aliases")
def delete_registry_language_alias(
    request: Request,
    product_id: str = Query(min_length=1),
    external_language_id: str = Query(min_length=1),
) -> dict[str, object]:
    _authorize_write_for_product(request, product_id=product_id)
    service = _get_registry_service(request)
    previous = service.get_language_alias(
        product_id=product_id,
        external_language_id=external_language_id,
    )
    deleted = service.delete_language_alias(
        product_id=product_id,
        external_language_id=external_language_id,
    )
    if deleted:
        _record_config_history(
            request,
            product_id=product_id,
            config_scope="language_alias",
            config_key=f"{product_id.strip().casefold()}:{external_language_id.strip().casefold()}",
            action_type="delete_alias",
            before=(
                {
                    "product_id": previous.product_id,
                    "external_language_id": previous.external_language_id,
                    "canonical_lang_id": previous.canonical_lang_id,
                }
                if previous is not None
                else None
            ),
            after=None,
        )
    return {"deleted": deleted}


@router.get(
    "/admin/v1/settings/retrieval/{product_id}",
    response_model=RetrievalSettingsResponse,
)
def get_product_retrieval_settings(
    product_id: str,
    request: Request,
) -> RetrievalSettingsResponse:
    service = _get_retrieval_settings_service(request)
    record = service.get(product_id=product_id)
    return RetrievalSettingsResponse(
        product_id=record.product_id,
        top_k=record.top_k,
        max_context_tokens=record.max_context_tokens,
        excerpt_char_limit=record.excerpt_char_limit,
        low_confidence_threshold=record.low_confidence_threshold,
        clarification_policy=record.clarification_policy,
        updated_by=record.updated_by,
        updated_at=record.updated_at,
    )


@router.patch(
    "/admin/v1/settings/retrieval/{product_id}",
    response_model=RetrievalSettingsResponse,
)
def patch_product_retrieval_settings(
    product_id: str,
    payload: PatchRetrievalSettingsRequest,
    request: Request,
) -> RetrievalSettingsResponse:
    _authorize_write_for_product(request, product_id=product_id)
    principal = _get_admin_principal(request)
    service = _get_retrieval_settings_service(request)
    previous = service.get(product_id=product_id)
    record = service.upsert(
        product_id=product_id,
        top_k=payload.top_k,
        max_context_tokens=payload.max_context_tokens,
        excerpt_char_limit=payload.excerpt_char_limit,
        low_confidence_threshold=payload.low_confidence_threshold,
        clarification_policy=payload.clarification_policy,
        updated_by=principal.key_id,
    )
    _record_config_history(
        request,
        product_id=record.product_id,
        config_scope="retrieval_settings",
        config_key=record.product_id,
        action_type="update_retrieval_settings",
        before={
            "product_id": previous.product_id,
            "top_k": previous.top_k,
            "max_context_tokens": previous.max_context_tokens,
            "excerpt_char_limit": previous.excerpt_char_limit,
            "low_confidence_threshold": previous.low_confidence_threshold,
            "clarification_policy": previous.clarification_policy,
        },
        after={
            "product_id": record.product_id,
            "top_k": record.top_k,
            "max_context_tokens": record.max_context_tokens,
            "excerpt_char_limit": record.excerpt_char_limit,
            "low_confidence_threshold": record.low_confidence_threshold,
            "clarification_policy": record.clarification_policy,
        },
    )
    return RetrievalSettingsResponse(
        product_id=record.product_id,
        top_k=record.top_k,
        max_context_tokens=record.max_context_tokens,
        excerpt_char_limit=record.excerpt_char_limit,
        low_confidence_threshold=record.low_confidence_threshold,
        clarification_policy=record.clarification_policy,
        updated_by=record.updated_by,
        updated_at=record.updated_at,
    )


@router.get("/admin/v1/analytics/slices", response_model=AnalyticsSliceResponse)
def get_analytics_slices(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    hashed_ip: str | None = None,
    fingerprint: str | None = None,
    outcome: str | None = None,
    retrieval_mode: str | None = None,
    zero_result_reason: str | None = None,
    fallback_reason: str | None = None,
    warning_code: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> AnalyticsSliceResponse:
    service = _get_analytics_service(request)
    summary = service.slice_summary(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        endpoint=endpoint,
        tool=tool,
        hashed_ip=hashed_ip,
        fingerprint=fingerprint,
        outcome=outcome,
        retrieval_mode=retrieval_mode,
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        warning_code=warning_code,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return AnalyticsSliceResponse(
        total_requests=summary.total_requests,
        by_product_id=dict(summary.by_product_id),
        by_programming_language=dict(summary.by_programming_language),
        by_doc_locale=dict(summary.by_doc_locale),
        by_endpoint=dict(summary.by_endpoint),
        by_tool=dict(summary.by_tool),
        by_outcome=dict(summary.by_outcome),
        by_retrieval_mode=dict(summary.by_retrieval_mode),
        by_zero_result_reason=dict(summary.by_zero_result_reason),
        by_fallback_reason=dict(summary.by_fallback_reason),
        by_warning_code=dict(summary.by_warning_code),
        refreshed_at=summary.refreshed_at,
        refresh_lag_minutes=summary.refresh_lag_minutes,
    )


@router.get("/admin/v1/analytics/zero-results", response_model=ZeroResultOverviewResponse)
def get_zero_result_overview(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    hashed_ip: str | None = None,
    fingerprint: str | None = None,
    outcome: str | None = None,
    retrieval_mode: str | None = None,
    zero_result_reason: str | None = None,
    fallback_reason: str | None = None,
    warning_code: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> ZeroResultOverviewResponse:
    service = _get_analytics_service(request)
    overview = service.zero_result_overview(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        endpoint=endpoint,
        tool=tool,
        hashed_ip=hashed_ip,
        fingerprint=fingerprint,
        outcome=outcome,
        retrieval_mode=retrieval_mode,
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        warning_code=warning_code,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return ZeroResultOverviewResponse(
        filtered_requests_total=overview.filtered_requests_total,
        without_useful_result_requests=overview.without_useful_result_requests,
        without_useful_result_share=overview.without_useful_result_share,
        no_result_requests=overview.no_result_requests,
        low_confidence_requests=overview.low_confidence_requests,
        by_zero_result_reason=dict(overview.by_zero_result_reason),
        by_fallback_reason=dict(overview.by_fallback_reason),
        by_warning_code=dict(overview.by_warning_code),
        by_retrieval_mode=dict(overview.by_retrieval_mode),
        top_affected_products=dict(overview.top_affected_products),
        top_affected_programming_languages=dict(overview.top_affected_programming_languages),
        clusters=[
            ZeroResultClusterResponse(
                cluster_id=cluster.cluster_id,
                zero_result_reason=cluster.zero_result_reason,
                fallback_reason=cluster.fallback_reason,
                retrieval_mode=cluster.retrieval_mode,
                primary_warning_code=cluster.primary_warning_code,
                total_requests=cluster.total_requests,
                share_of_filtered_requests=cluster.share_of_filtered_requests,
                affected_products=list(cluster.affected_products),
                affected_programming_languages=list(cluster.affected_programming_languages),
                affected_doc_locales=list(cluster.affected_doc_locales),
                sample_queries=list(cluster.sample_queries),
                recommendation_title=cluster.recommendation_title,
                recommendation_detail=cluster.recommendation_detail,
            )
            for cluster in overview.clusters
        ],
        refreshed_at=overview.refreshed_at,
        refresh_lag_minutes=overview.refresh_lag_minutes,
    )


@router.get("/admin/v1/analytics/capacity-forecast", response_model=CapacityForecastResponse)
def get_capacity_forecast(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    hashed_ip: str | None = None,
    fingerprint: str | None = None,
    outcome: str | None = None,
    retrieval_mode: str | None = None,
    zero_result_reason: str | None = None,
    fallback_reason: str | None = None,
    warning_code: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> CapacityForecastResponse:
    service = _get_analytics_service(request)
    forecast = service.capacity_forecast(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        endpoint=endpoint,
        tool=tool,
        hashed_ip=hashed_ip,
        fingerprint=fingerprint,
        outcome=outcome,
        retrieval_mode=retrieval_mode,
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        warning_code=warning_code,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    return CapacityForecastResponse(
        filtered_requests_total=forecast.filtered_requests_total,
        observed_window_hours=forecast.observed_window_hours,
        projected_requests_next_24h=forecast.projected_requests_next_24h,
        previous_window_requests=forecast.previous_window_requests,
        growth_ratio=forecast.growth_ratio,
        zero_result_pressure_share=forecast.zero_result_pressure_share,
        low_confidence_share=forecast.low_confidence_share,
        warning_density=forecast.warning_density,
        coverage_saturation_score=forecast.coverage_saturation_score,
        saturation_risk=forecast.saturation_risk,
        recommended_action=forecast.recommended_action,
        hottest_products=[
            CapacityForecastProductResponse(
                product_id=item.product_id,
                recent_requests=item.recent_requests,
                previous_window_requests=item.previous_window_requests,
                projected_requests_next_24h=item.projected_requests_next_24h,
                growth_ratio=item.growth_ratio,
                zero_result_pressure_share=item.zero_result_pressure_share,
                low_confidence_share=item.low_confidence_share,
                warning_density=item.warning_density,
                coverage_saturation_score=item.coverage_saturation_score,
                saturation_risk=item.saturation_risk,
                recommended_action=item.recommended_action,
            )
            for item in forecast.hottest_products
        ],
        refreshed_at=forecast.refreshed_at,
        refresh_lag_minutes=forecast.refresh_lag_minutes,
    )


@router.get("/admin/v1/analytics/usefulness", response_model=UsefulnessSummaryResponse)
def get_usefulness_summary(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    rating: str | None = None,
    reason_code: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> UsefulnessSummaryResponse:
    service = _get_analytics_service(request)
    try:
        summary = service.usefulness_summary(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=rating,
            reason_code=reason_code,
            from_ts=from_ts,
            to_ts=to_ts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UsefulnessSummaryResponse(
        total_feedback=summary.total_feedback,
        useful_feedback=summary.useful_feedback,
        partially_useful_feedback=summary.partially_useful_feedback,
        not_useful_feedback=summary.not_useful_feedback,
        useful_share=summary.useful_share,
        negative_share=summary.negative_share,
        by_rating=dict(summary.by_rating),
        by_reason_code=dict(summary.by_reason_code),
        by_product_id=dict(summary.by_product_id),
        by_programming_language=dict(summary.by_programming_language),
        by_doc_locale=dict(summary.by_doc_locale),
        recent_negative_signals=[
            _to_usefulness_signal_response(record)
            for record in summary.recent_negative_signals
        ],
        refreshed_at=summary.refreshed_at,
        refresh_lag_minutes=summary.refresh_lag_minutes,
    )


@router.get("/admin/v1/analytics/issues", response_model=IssueReviewSummaryResponse)
def get_issue_review_summary(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> IssueReviewSummaryResponse:
    service = _get_analytics_service(request)
    try:
        records = service.list_issue_reports(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            issue_type=issue_type,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        normalized_severity = _normalize_issue_severity(severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    signals = tuple(_to_issue_review_signal_response(record) for record in records)
    if normalized_severity is not None:
        signals = tuple(item for item in signals if item.severity == normalized_severity)
    return IssueReviewSummaryResponse(
        total_reports=len(signals),
        by_issue_type=dict(Counter(item.issue_type for item in signals)),
        by_severity=dict(Counter(item.severity for item in signals)),
        by_product_id=dict(Counter(item.product_id or "unknown" for item in signals)),
        by_programming_language=dict(
            Counter(item.programming_language or "unknown" for item in signals)
        ),
        by_doc_locale=dict(Counter(item.doc_locale or "unknown" for item in signals)),
        recommendation_mix=dict(Counter(item.recommendation_title for item in signals)),
        recent_reports=list(signals[:12]),
        refreshed_at=datetime.now(tz=UTC),
        refresh_lag_minutes=5,
    )


@router.get(
    "/admin/v1/analytics/usefulness-signals",
    response_model=list[UsefulnessSignalResponse],
)
def get_usefulness_signals(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    rating: str | None = None,
    reason_code: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    negative_only: bool = True,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[UsefulnessSignalResponse]:
    service = _get_analytics_service(request)
    try:
        records = service.list_usefulness_feedback(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            rating=rating,
            reason_code=reason_code,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
            negative_only=negative_only,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_to_usefulness_signal_response(record) for record in records]


@router.get(
    "/admin/v1/analytics/issue-signals",
    response_model=list[IssueReviewSignalResponse],
)
def get_issue_review_signals(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[IssueReviewSignalResponse]:
    service = _get_analytics_service(request)
    try:
        records = service.list_issue_reports(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            issue_type=issue_type,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        normalized_severity = _normalize_issue_severity(severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    signals = [_to_issue_review_signal_response(record) for record in records]
    if normalized_severity is not None:
        signals = [item for item in signals if item.severity == normalized_severity]
    return signals[:limit]


@router.get(
    "/admin/v1/analytics/request-evidence",
    response_model=RequestEvidenceResponse,
)
def get_request_evidence(
    request: Request,
    request_id: str = Query(min_length=1),
) -> RequestEvidenceResponse:
    return _build_request_evidence_response(request=request, request_id=request_id)


@router.post(
    "/admin/v1/analytics/request-evidence:create-fix-draft",
    response_model=GuidedContentFixDraftResponse,
)
def create_guided_content_fix_draft(
    payload: CreateGuidedContentFixDraftRequest,
    request: Request,
) -> GuidedContentFixDraftResponse:
    evidence = _build_request_evidence_response(request=request, request_id=payload.request_id)
    product_id = (evidence.original.product_id or "").strip().casefold()
    if not product_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Replay evidence does not resolve to a product_id, so a fix draft "
                "cannot be created."
            ),
        )
    _authorize_write_for_product(request, product_id=product_id)
    principal = _get_admin_principal(request)
    selected_issue = _select_guided_fix_issue(
        issues=evidence.related_issue_reports,
        requested_issue_id=payload.issue_id,
    )
    source_revision = _resolve_guided_fix_source_revision(evidence=evidence)
    guided_fix_plan = _build_guided_fix_plan(
        evidence=evidence,
        selected_issue=selected_issue,
    )
    review_items = _build_guided_fix_review_items(
        evidence=evidence,
        selected_issue=selected_issue,
    )
    review_run = _get_review_service(request).create_run(
        product_id=product_id,
        version=evidence.replay.response.version_resolution.resolved_version,
        source_revision=source_revision,
        trigger_type="manual",
        created_by="admin_key",
        created_by_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        items=tuple(review_items),
        origin=SemanticReviewRunOrigin(
            source="issue_handoff",
            request_id=evidence.request_id,
            issue_id=selected_issue.issue_id if selected_issue is not None else None,
            issue_type=selected_issue.issue_type if selected_issue is not None else None,
            severity=selected_issue.severity if selected_issue is not None else None,
            raw_query=evidence.original.raw_query,
            suspected_fault_domain=evidence.diff.suspected_fault_domain,
            suspected_fault_reason=evidence.diff.suspected_fault_reason,
            recommendation_title=(
                selected_issue.recommendation_title
                if selected_issue is not None
                else _guided_fix_default_recommendation_title(evidence)
            ),
            recommendation_detail=(
                selected_issue.recommendation_detail
                if selected_issue is not None
                else evidence.diff.operator_hint
            ),
        ),
        guided_fix_plan=guided_fix_plan,
    )
    return GuidedContentFixDraftResponse(
        request_id=evidence.request_id,
        issue_id=selected_issue.issue_id if selected_issue is not None else None,
        issue_type=selected_issue.issue_type if selected_issue is not None else None,
        severity=selected_issue.severity if selected_issue is not None else None,
        product_id=product_id,
        programming_language=evidence.original.programming_language,
        doc_locale=evidence.original.doc_locale,
        source_revision=source_revision,
        recommendation_title=(
            selected_issue.recommendation_title
            if selected_issue is not None
            else _guided_fix_default_recommendation_title(evidence)
        ),
        recommendation_detail=(
            selected_issue.recommendation_detail
            if selected_issue is not None
            else evidence.diff.operator_hint
        ),
        quality_review_run=_to_run_response(review_run),
        fix_plan=GuidedContentFixPlanResponse(
            summary=guided_fix_plan.summary,
            priority=guided_fix_plan.priority,
            owner_hint=guided_fix_plan.owner_hint,
            next_step=guided_fix_plan.next_step,
            actions=[
                GuidedContentFixStepResponse(
                    step_id=step.step_id,
                    title=step.title,
                    detail=step.detail,
                    target_section=step.target_section,
                    action_kind=step.action_kind,
                )
                for step in guided_fix_plan.actions
            ],
        ),
        generated_at=datetime.now(tz=UTC),
    )


def _build_request_evidence_response(
    *,
    request: Request,
    request_id: str,
) -> RequestEvidenceResponse:
    analytics_service = _get_analytics_service(request)
    record = analytics_service.get_record(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Analytics request_id was not found.")
    if record.tool != "query_docs":
        raise HTTPException(
            status_code=400,
            detail="Replay evidence is only supported for query_docs analytics records.",
        )

    replay_request, assumptions = _build_request_replay(record)
    replay_response = _get_public_query_service(request).query_docs(request=replay_request)
    replay_response.query_id = f"replay:{record.request_id}"
    replay_response.request_id = f"replay:{record.request_id}"
    current_outcome = _derive_query_docs_outcome_from_response(replay_response)
    current_zero_result_reason = _derive_zero_result_reason_from_response(replay_response)
    current_fallback_reason = (
        replay_response.fallback_reason
        or _derive_fallback_reason_from_response(replay_response)
    )
    related_issue_reports = [
        _to_issue_review_signal_response(item)
        for item in analytics_service.list_issue_reports(request_id=record.request_id, limit=10)
    ]
    related_usefulness_feedback = [
        _to_usefulness_signal_response(item)
        for item in analytics_service.list_usefulness_feedback(
            request_id=record.request_id,
            negative_only=False,
            limit=10,
        )
    ]
    replay_payload = RequestEvidenceReplayResponse(
        executed_at=datetime.now(tz=UTC),
        request=RequestReplayInputResponse(
            query=replay_request.query,
            product_id=replay_request.product_id,
            programming_language=replay_request.language,
            doc_locale=replay_request.query_locale,
            version=replay_request.version,
            top_k=replay_request.top_k,
            strict_version=replay_request.strict_version,
            include_examples=replay_request.include_examples,
            doc_types=list(replay_request.doc_types),
            assumptions=assumptions,
        ),
        outcome=current_outcome,
        result_count=len(replay_response.results),
        zero_result_reason=current_zero_result_reason,
        fallback_reason=current_fallback_reason,
        response=replay_response,
    )
    original_payload = RequestEvidenceOriginalResponse(
        request_id=record.request_id,
        endpoint=record.endpoint,
        tool=record.tool,
        raw_query=record.raw_query,
        product_id=record.product_id,
        programming_language=record.programming_language,
        doc_locale=record.doc_locale,
        confidence=record.confidence,
        outcome=record.outcome,
        retrieval_mode=record.retrieval_mode,
        result_count=record.result_count,
        zero_result_reason=record.zero_result_reason,
        fallback_reason=record.fallback_reason,
        warning_codes=list(record.warning_codes),
        created_at=record.created_at,
    )
    diff_payload = _build_request_evidence_diff(
        original=record,
        replay=replay_response,
        replay_outcome=current_outcome,
        replay_zero_result_reason=current_zero_result_reason,
        replay_fallback_reason=current_fallback_reason,
        related_issue_reports=related_issue_reports,
        related_usefulness_feedback=related_usefulness_feedback,
    )
    copy_context = {
        "request_id": record.request_id,
        "original": original_payload.model_dump(mode="json"),
        "replay": replay_payload.model_dump(mode="json"),
        "diff": diff_payload.model_dump(mode="json"),
        "related_issue_reports": [
            item.model_dump(mode="json") for item in related_issue_reports
        ],
        "related_usefulness_feedback": [
            item.model_dump(mode="json") for item in related_usefulness_feedback
        ],
    }
    return RequestEvidenceResponse(
        request_id=record.request_id,
        original=original_payload,
        replay=replay_payload,
        diff=diff_payload,
        related_issue_reports=related_issue_reports,
        related_usefulness_feedback=related_usefulness_feedback,
        copy_context=copy_context,
        generated_at=datetime.now(tz=UTC),
    )


def _select_guided_fix_issue(
    *,
    issues: list[IssueReviewSignalResponse],
    requested_issue_id: str | None,
) -> IssueReviewSignalResponse | None:
    if requested_issue_id is not None:
        for issue in issues:
            if issue.issue_id == requested_issue_id:
                return issue
        raise HTTPException(
            status_code=404,
            detail=f"Issue `{requested_issue_id}` was not found for the selected request_id.",
        )
    if not issues:
        return None
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(
        issues,
        key=lambda issue: (
            severity_order.get(issue.severity, 99),
            -issue.updated_at.timestamp(),
            issue.issue_id,
        ),
    )[0]


def _resolve_guided_fix_source_revision(*, evidence: RequestEvidenceResponse) -> str:
    revisions = [
        result.source_revision.strip()
        for result in evidence.replay.response.results
        if result.source_revision.strip()
    ]
    if revisions:
        return Counter(revisions).most_common(1)[0][0]
    return f"analytics:{evidence.request_id}"


def _guided_fix_default_recommendation_title(evidence: RequestEvidenceResponse) -> str:
    fault_domain = evidence.diff.suspected_fault_domain.casefold()
    if fault_domain == "coverage":
        return "Recover missing content coverage"
    if fault_domain == "freshness":
        return "Refresh latest-stable content"
    if fault_domain == "answer_formatting":
        return "Repair examples and answer completeness"
    return "Review ranking and retrieval evidence"


def _guided_fix_blocking_error_type(
    *,
    evidence: RequestEvidenceResponse,
    selected_issue: IssueReviewSignalResponse | None,
) -> SemanticReviewBlockingErrorType | None:
    issue_type = selected_issue.issue_type.casefold() if selected_issue is not None else ""
    fault_domain = evidence.diff.suspected_fault_domain.casefold()
    if issue_type == "missing_docs" or fault_domain == "coverage":
        return "citation_or_source_path_loss"
    if issue_type == "outdated_docs" or fault_domain == "freshness":
        return "invalid_signature_or_parameters_or_returns"
    if issue_type == "wrong_docs" or fault_domain == "retrieval":
        return "hallucinated_api_member"
    if issue_type == "bad_example" or fault_domain == "answer_formatting":
        return "invalid_signature_or_parameters_or_returns"
    return None


def _guided_fix_priority(
    *,
    evidence: RequestEvidenceResponse,
    selected_issue: IssueReviewSignalResponse | None,
) -> SemanticReviewFixPlanPriority:
    if selected_issue is not None and selected_issue.severity == "critical":
        return "high"
    if evidence.diff.drift_status == "regressed":
        return "high"
    if evidence.diff.suspected_fault_domain in {"coverage", "freshness"}:
        return "medium"
    return "low"


def _build_guided_fix_review_items(
    *,
    evidence: RequestEvidenceResponse,
    selected_issue: IssueReviewSignalResponse | None,
) -> list[SemanticReviewCandidateItem]:
    blocking_error_type = _guided_fix_blocking_error_type(
        evidence=evidence,
        selected_issue=selected_issue,
    )
    priority = _guided_fix_priority(evidence=evidence, selected_issue=selected_issue)
    score = 3.25 if priority == "high" else 3.95 if priority == "medium" else 4.3
    items: list[SemanticReviewCandidateItem] = [
        SemanticReviewCandidateItem(
            source_path=f"analytics/request-evidence/{evidence.request_id}/original-query.md",
            stratum="reported_workflow",
            simulated_score=score,
            simulated_blocking_error_type=blocking_error_type if priority == "high" else None,
            review_notes=evidence.diff.summary,
        ),
        SemanticReviewCandidateItem(
            source_path=f"analytics/request-evidence/{evidence.request_id}/replay-diff.md",
            stratum=f"fault_domain_{evidence.diff.suspected_fault_domain}",
            simulated_score=min(4.6, score + 0.25),
            simulated_blocking_error_type=None,
            review_notes=evidence.diff.operator_hint,
        ),
    ]
    if selected_issue is not None:
        items.append(
            SemanticReviewCandidateItem(
                source_path=f"analytics/issues/{selected_issue.issue_id}.md",
                stratum=f"issue_{selected_issue.issue_type}",
                simulated_score=score,
                simulated_blocking_error_type=blocking_error_type,
                review_notes=selected_issue.recommendation_detail,
            )
        )
    for index, result in enumerate(evidence.replay.response.results[:3], start=1):
        items.append(
            SemanticReviewCandidateItem(
                source_path=f"{result.canonical_url}#{result.section_anchor}",
                stratum="retrieved_content_sample",
                simulated_score=min(4.8, score + 0.45 + (index * 0.05)),
                simulated_blocking_error_type=None,
                review_notes=f"Replay result {index}: {result.title}",
            )
        )
    return items


def _build_guided_fix_plan(
    *,
    evidence: RequestEvidenceResponse,
    selected_issue: IssueReviewSignalResponse | None,
) -> SemanticReviewGuidedFixPlan:
    fault_domain = evidence.diff.suspected_fault_domain.casefold()
    priority = _guided_fix_priority(evidence=evidence, selected_issue=selected_issue)
    actions: list[SemanticReviewFixPlanStep]
    if fault_domain == "coverage":
        actions = [
            SemanticReviewFixPlanStep(
                step_id="inspect-evidence",
                title="Inspect replay evidence",
                detail=(
                    "Confirm the affected request scope and missing coverage before "
                    "running ingestion again."
                ),
                target_section="analytics",
                action_kind="inspect_replay",
            ),
            SemanticReviewFixPlanStep(
                step_id="validate-ingestion",
                title="Run validate-only ingestion",
                detail=(
                    "Validate source layout and indexing coverage for the affected "
                    "repo before publish."
                ),
                target_section="ingestion-jobs",
                action_kind="validate_ingestion",
            ),
            SemanticReviewFixPlanStep(
                step_id="publish-fresh-snapshot",
                title="Publish a corrected snapshot",
                detail=(
                    "Republish the fixed scope after validation passes and coverage "
                    "is restored."
                ),
                target_section="snapshots",
                action_kind="publish_snapshot",
            ),
        ]
    elif fault_domain == "freshness":
        actions = [
            SemanticReviewFixPlanStep(
                step_id="review-release-drift",
                title="Review release freshness",
                detail=(
                    "Check version fallback and release visibility before deciding "
                    "whether the active snapshot is stale."
                ),
                target_section="analytics",
                action_kind="inspect_replay",
            ),
            SemanticReviewFixPlanStep(
                step_id="refresh-sources",
                title="Sync sources and reindex",
                detail=(
                    "Pull the latest stable docs or API reference revisions and "
                    "republish the freshest validated snapshot."
                ),
                target_section="ingestion-jobs",
                action_kind="reingest",
            ),
            SemanticReviewFixPlanStep(
                step_id="confirm-runtime",
                title="Confirm active snapshot",
                detail=(
                    "Verify that the updated snapshot is active and ready before "
                    "closing the report."
                ),
                target_section="snapshots",
                action_kind="verify_snapshot",
            ),
        ]
    elif fault_domain == "answer_formatting":
        actions = [
            SemanticReviewFixPlanStep(
                step_id="open-review-draft",
                title="Open the quality review draft",
                detail=(
                    "Inspect the generated review package and focus on missing "
                    "steps, examples, and snippet usefulness."
                ),
                target_section="quality-reviews",
                action_kind="open_quality_review",
            ),
            SemanticReviewFixPlanStep(
                step_id="improve-examples",
                title="Improve examples and chunk packing",
                detail=(
                    "Adjust examples, section packing, or chunk coverage before "
                    "publishing a new snapshot."
                ),
                target_section="quality-reviews",
                action_kind="review_examples",
            ),
            SemanticReviewFixPlanStep(
                step_id="replay-after-fix",
                title="Replay the request again",
                detail=(
                    "Use the replay inspector after content changes to verify the "
                    "answer is now actionable."
                ),
                target_section="analytics",
                action_kind="inspect_replay",
            ),
        ]
    else:
        actions = [
            SemanticReviewFixPlanStep(
                step_id="open-review-draft",
                title="Open the quality review draft",
                detail=(
                    "Inspect the generated review package alongside replay top "
                    "results and warning deltas."
                ),
                target_section="quality-reviews",
                action_kind="open_quality_review",
            ),
            SemanticReviewFixPlanStep(
                step_id="check-retrieval-settings",
                title="Review retrieval evidence",
                detail=(
                    "Compare current replay ordering, intent routing, and "
                    "reranker-related evidence before changing content."
                ),
                target_section="retrieval-settings",
                action_kind="review_retrieval",
            ),
            SemanticReviewFixPlanStep(
                step_id="replay-after-change",
                title="Replay after the correction",
                detail=(
                    "Re-run the reported request_id after ranking or content "
                    "adjustments to confirm recovery."
                ),
                target_section="analytics",
                action_kind="inspect_replay",
            ),
        ]
    if selected_issue is not None and selected_issue.severity == "critical":
        actions.append(
            SemanticReviewFixPlanStep(
                step_id="escalate-critical",
                title="Escalate the critical issue",
                detail=(
                    "Keep the incident visible until replay confirms recovery and "
                    "postmortem notes are captured."
                ),
                target_section="critical-events",
                action_kind="escalate",
            )
        )
    return SemanticReviewGuidedFixPlan(
        summary=evidence.diff.summary,
        priority=priority,
        owner_hint="product_owner",
        next_step=actions[0].title,
        actions=tuple(actions),
    )


@router.get(
    "/admin/v1/analytics/issue-hotspots",
    response_model=IssueHotspotOverviewResponse,
)
def get_issue_hotspots(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    endpoint: str | None = None,
    tool: str | None = None,
    issue_type: str | None = None,
    severity: str | None = None,
    request_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> IssueHotspotOverviewResponse:
    service = _get_analytics_service(request)
    try:
        records = service.list_issue_reports(
            product_id=product_id,
            programming_language=programming_language,
            doc_locale=doc_locale,
            endpoint=endpoint,
            tool=tool,
            issue_type=issue_type,
            request_id=request_id,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        normalized_severity = _normalize_issue_severity(severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    signals = tuple(_to_issue_review_signal_response(record) for record in records)
    if normalized_severity is not None:
        signals = tuple(item for item in signals if item.severity == normalized_severity)
    overview = _build_issue_hotspot_overview(signals=signals, limit=limit)
    return IssueHotspotOverviewResponse(
        filtered_reports_total=overview["filtered_reports_total"],
        hotspots_total=overview["hotspots_total"],
        by_priority=overview["by_priority"],
        by_product_id=overview["by_product_id"],
        by_issue_type=overview["by_issue_type"],
        by_severity=overview["by_severity"],
        clusters=overview["clusters"],
        refreshed_at=overview["refreshed_at"],
        refresh_lag_minutes=overview["refresh_lag_minutes"],
    )


@router.get(
    "/admin/v1/analytics/public-funnel",
    response_model=PublicFunnelOverviewResponse,
)
def get_public_adoption_funnel(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    doc_locale: str | None = None,
    client_id: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=12, ge=1, le=50),
) -> PublicFunnelOverviewResponse:
    service = _get_analytics_service(request)
    query_records = service.list_records(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    feedback_records = service.list_usefulness_feedback(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    issue_records = service.list_issue_reports(
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    overview = _build_public_adoption_funnel(
        query_records=query_records,
        feedback_records=feedback_records,
        issue_records=issue_records,
        client_id=client_id,
        limit=limit,
    )
    return PublicFunnelOverviewResponse(
        filtered_sessions_total=overview["filtered_sessions_total"],
        by_product_id=overview["by_product_id"],
        by_programming_language=overview["by_programming_language"],
        by_client_id=overview["by_client_id"],
        stages=overview["stages"],
        top_dropoffs=overview["top_dropoffs"],
        scopes=overview["scopes"],
        refreshed_at=overview["refreshed_at"],
        refresh_lag_minutes=overview["refresh_lag_minutes"],
    )


@router.get(
    "/admin/v1/analytics/freshness-watchlist",
    response_model=FreshnessWatchlistOverviewResponse,
)
def get_freshness_watchlist(
    request: Request,
    product_id: str | None = None,
    programming_language: str | None = None,
    source_kind: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    issue_window_days: int = Query(default=30, ge=1, le=180),
    stale_after_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=100),
) -> FreshnessWatchlistOverviewResponse:
    service = _get_analytics_service(request)
    window_end = to_ts or datetime.now(tz=UTC)
    window_start = from_ts or (window_end - timedelta(days=issue_window_days))
    query_records = service.list_records(
        product_id=product_id,
        programming_language=programming_language,
        tool="query_docs",
        from_ts=window_start,
        to_ts=window_end,
    )
    feedback_records = service.list_usefulness_feedback(
        product_id=product_id,
        programming_language=programming_language,
        tool="query_docs",
        negative_only=True,
        from_ts=window_start,
        to_ts=window_end,
    )
    issue_records = service.list_issue_reports(
        product_id=product_id,
        programming_language=programming_language,
        tool="query_docs",
        from_ts=window_start,
        to_ts=window_end,
    )
    overview = _build_freshness_watchlist(
        request=request,
        query_records=query_records,
        feedback_records=feedback_records,
        issue_records=issue_records,
        product_id=product_id,
        programming_language=programming_language,
        source_kind=source_kind,
        stale_after_days=stale_after_days,
        limit=limit,
    )
    return FreshnessWatchlistOverviewResponse(
        filtered_scopes_total=overview["filtered_scopes_total"],
        high_risk_total=overview["high_risk_total"],
        medium_risk_total=overview["medium_risk_total"],
        low_risk_total=overview["low_risk_total"],
        by_product_id=overview["by_product_id"],
        by_programming_language=overview["by_programming_language"],
        by_source_kind=overview["by_source_kind"],
        status_summary=overview["status_summary"],
        items=overview["items"],
        refreshed_at=overview["refreshed_at"],
        refresh_lag_minutes=overview["refresh_lag_minutes"],
    )


@router.post("/admin/v1/analytics/sql:query", response_model=AnalyticsSqlQueryResponse)
def query_analytics_sql(
    payload: AnalyticsSqlQueryRequest,
    request: Request,
) -> AnalyticsSqlQueryResponse:
    service = _get_analytics_service(request)
    try:
        result = service.sql_query(sql=payload.sql, max_rows=payload.max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnalyticsSqlQueryResponse(
        columns=list(result.columns),
        rows=[list(row) for row in result.rows],
        row_count=result.row_count,
        truncated=result.truncated,
    )


@router.post("/admin/v1/analytics/sql:export", response_model=AnalyticsSqlExportResponse)
def export_analytics_sql(
    payload: AnalyticsSqlQueryRequest,
    request: Request,
) -> AnalyticsSqlExportResponse:
    service = _get_analytics_service(request)
    try:
        csv_payload = service.sql_export_csv(sql=payload.sql, max_rows=payload.max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row_count = max(0, len(csv_payload.splitlines()) - 1)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    return AnalyticsSqlExportResponse(
        filename=f"analytics-export-{timestamp}.csv",
        row_count=row_count,
        csv_payload=csv_payload,
    )


# Static schema description for the SQL Explorer "Schema" tab.
# Only safe, queryable analytics tables are listed. Sensitive tables
# (admin_api_keys, admin_sessions, pg_catalog.*) are blocked at the
# validator level — see _validate_read_only_select.
_SQL_EXPLORER_SCHEMA: list[AnalyticsSqlSchemaTable] = [
    AnalyticsSqlSchemaTable(
        name="analytics_queries",
        description=(
            "View of every retrieval / MCP request handled by the service. "
            "Use this for traffic, latency, confidence, and outcome analysis. "
            "Each row is one external request — no aggregation."
        ),
        columns=[
            AnalyticsSqlSchemaColumn(
                name="request_id",
                data_type="text",
                description=(
                    "Unique request id; use to join with usefulness_feedback "
                    "or issue_intake_reports."
                ),
            ),
            AnalyticsSqlSchemaColumn(
                name="endpoint",
                data_type="text",
                description=(
                    "REST or MCP endpoint that served the request, e.g. v1.docs.query."
                ),
            ),
            AnalyticsSqlSchemaColumn(
                name="tool",
                data_type="text",
                description="MCP tool name (query_docs, get_symbol_doc, etc.).",
            ),
            AnalyticsSqlSchemaColumn(
                name="raw_query",
                data_type="text",
                description="The user-provided query string.",
            ),
            AnalyticsSqlSchemaColumn(
                name="product_id",
                data_type="text",
                description="Aspose product id, e.g. aspose.ocr.",
            ),
            AnalyticsSqlSchemaColumn(
                name="programming_language",
                data_type="text",
                description="SDK language: net, java, python-net, etc.",
            ),
            AnalyticsSqlSchemaColumn(
                name="doc_locale",
                data_type="text",
                description="Documentation locale, e.g. en, ru.",
            ),
            AnalyticsSqlSchemaColumn(
                name="latency_ms",
                data_type="integer",
                description="End-to-end latency in milliseconds.",
            ),
            AnalyticsSqlSchemaColumn(
                name="confidence",
                data_type="double precision",
                description="Retrieval confidence score, 0.0–1.0.",
            ),
            AnalyticsSqlSchemaColumn(
                name="outcome",
                data_type="text",
                description=(
                    "Result classification: ok, no_results, low_confidence, error."
                ),
            ),
            AnalyticsSqlSchemaColumn(
                name="retrieval_mode",
                data_type="text",
                description="symbol_first, task_howto, migration.",
            ),
            AnalyticsSqlSchemaColumn(
                name="result_count",
                data_type="integer",
                description="Number of chunks returned.",
            ),
            AnalyticsSqlSchemaColumn(
                name="zero_result_reason",
                data_type="text",
                description="Why zero results were returned (if applicable).",
            ),
            AnalyticsSqlSchemaColumn(
                name="fallback_reason",
                data_type="text",
                description="Why a fallback path was taken (if applicable).",
            ),
            AnalyticsSqlSchemaColumn(
                name="warning_codes",
                data_type="text",
                description=(
                    "Comma-separated warning codes emitted during retrieval."
                ),
            ),
            AnalyticsSqlSchemaColumn(
                name="created_at",
                data_type="timestamptz",
                description="When the request was processed.",
            ),
        ],
        sample_query=(
            "SELECT product_id, COUNT(*) AS requests, AVG(latency_ms) AS avg_latency_ms\n"
            "FROM analytics_queries\n"
            "WHERE created_at >= NOW() - INTERVAL '7 days'\n"
            "GROUP BY product_id\n"
            "ORDER BY requests DESC"
        ),
    ),
    AnalyticsSqlSchemaTable(
        name="usefulness_feedback",
        description=(
            "User feedback on individual retrieval results. Join with analytics_queries "
            "via request_id to correlate ratings with the original query context."
        ),
        columns=[
            AnalyticsSqlSchemaColumn(name="feedback_id", data_type="text"),
            AnalyticsSqlSchemaColumn(
                name="request_id",
                data_type="text",
                description="Joins to analytics_queries.request_id.",
            ),
            AnalyticsSqlSchemaColumn(
                name="actor_identity",
                data_type="text",
                description="Hashed actor id; never raw email.",
            ),
            AnalyticsSqlSchemaColumn(name="endpoint", data_type="text"),
            AnalyticsSqlSchemaColumn(name="tool", data_type="text"),
            AnalyticsSqlSchemaColumn(name="product_id", data_type="text"),
            AnalyticsSqlSchemaColumn(name="programming_language", data_type="text"),
            AnalyticsSqlSchemaColumn(
                name="rating",
                data_type="text",
                description="useful, partially, negative.",
            ),
            AnalyticsSqlSchemaColumn(
                name="reason_codes",
                data_type="text",
                description="Comma-separated reason codes.",
            ),
            AnalyticsSqlSchemaColumn(name="created_at", data_type="timestamptz"),
            AnalyticsSqlSchemaColumn(name="updated_at", data_type="timestamptz"),
        ],
        sample_query=(
            "SELECT rating, COUNT(*) AS feedback_count\n"
            "FROM usefulness_feedback\n"
            "WHERE updated_at >= NOW() - INTERVAL '30 days'\n"
            "GROUP BY rating\n"
            "ORDER BY feedback_count DESC"
        ),
    ),
    AnalyticsSqlSchemaTable(
        name="issue_intake_reports",
        description=(
            "Issue reports filed by users about retrieval quality. Use to find "
            "the most-reported issue types per product/scope."
        ),
        columns=[
            AnalyticsSqlSchemaColumn(name="issue_id", data_type="text"),
            AnalyticsSqlSchemaColumn(
                name="request_id",
                data_type="text",
                description="Joins to analytics_queries.request_id.",
            ),
            AnalyticsSqlSchemaColumn(
                name="actor_identity",
                data_type="text",
                description="Hashed actor id; never raw email.",
            ),
            AnalyticsSqlSchemaColumn(name="product_id", data_type="text"),
            AnalyticsSqlSchemaColumn(name="programming_language", data_type="text"),
            AnalyticsSqlSchemaColumn(
                name="issue_type",
                data_type="text",
                description="Reported issue category.",
            ),
            AnalyticsSqlSchemaColumn(
                name="notes",
                data_type="text",
                description="Free-text notes from the reporter.",
            ),
            AnalyticsSqlSchemaColumn(name="created_at", data_type="timestamptz"),
            AnalyticsSqlSchemaColumn(name="updated_at", data_type="timestamptz"),
        ],
        sample_query=(
            "SELECT product_id, issue_type, COUNT(*) AS reports\n"
            "FROM issue_intake_reports\n"
            "WHERE created_at >= NOW() - INTERVAL '30 days'\n"
            "GROUP BY product_id, issue_type\n"
            "ORDER BY reports DESC\n"
            "LIMIT 50"
        ),
    ),
]


@router.get("/admin/v1/analytics/sql:schema", response_model=AnalyticsSqlSchemaResponse)
def get_analytics_sql_schema(request: Request) -> AnalyticsSqlSchemaResponse:
    """Return the static schema of analytics tables that the SQL Explorer can query.

    This endpoint is read-only and exposes only metadata. It does NOT include
    sensitive tables (admin_api_keys, admin_sessions, pg_catalog.*) — those
    are blocked at the validator layer.
    """
    _ = _get_analytics_service(request)  # ensure service initialized
    return AnalyticsSqlSchemaResponse(
        tables=_SQL_EXPLORER_SCHEMA,
        blocked_tables=[
            "admin_api_keys",
            "admin_sessions",
            "pg_authid",
            "pg_shadow",
            "pg_user",
            "pg_roles",
        ],
        blocked_column_patterns=[
            "token_hash",
            "api_key",
            "password",
            "secret",
            "private_key",
            "credentials",
            "session_token",
        ],
        notes=[
            "SQL Explorer is read-only: only SELECT (or WITH ... SELECT) statements are allowed.",
            "Multiple statements, DML, DDL, and stored procedure calls are blocked at the backend.",
            (
                "Tables containing credentials, password hashes, API key tokens, "
                "or session secrets are blocked."
            ),
            "Each query has a 30-second timeout and a 10,000-row result limit.",
            "CSV export is capped at 100 MB.",
            (
                "All queries run inside a read-only transaction with "
                "default_transaction_read_only = on."
            ),
        ],
    )


def _build_request_replay(record: Any) -> tuple[QueryDocsRequest, list[str]]:
    assumptions = [
        "Replay uses the stored raw query and request scope from analytics history.",
        (
            "Version hint was not stored in analytics history, so replay resolves "
            "the current default latest-stable scope."
        ),
        (
            "Original top_k, include_examples, doc_types, and debug flags were not "
            "stored; replay uses admin baseline defaults."
        ),
    ]
    return (
        QueryDocsRequest(
            query=record.raw_query,
            product_id=record.product_id,
            language=record.programming_language,
            version=None,
            query_locale=record.doc_locale,
            top_k=8,
            strict_version=True,
            doc_types=[],
            include_examples=True,
            debug=True,
        ),
        assumptions,
    )


def _derive_query_docs_outcome_from_response(response: QueryDocsResponse) -> str:
    warning_codes = {warning.strip().casefold() for warning in response.warnings}
    if len(response.results) <= 0:
        return "no_results"
    if response.fallback_reason == "low_confidence_best_effort":
        return "low_confidence"
    if "low_confidence_best_effort" in warning_codes or response.confidence < 0.35:
        return "low_confidence"
    return "success"


def _derive_zero_result_reason_from_response(response: QueryDocsResponse) -> str | None:
    if len(response.results) > 0:
        return None
    warning_codes = {warning.strip().casefold() for warning in response.warnings}
    if "no_index_data" in warning_codes:
        return "no_index_data"
    if "product_scope_missing" in warning_codes:
        return "product_scope_missing"
    if "version_scope_missing" in warning_codes:
        return "version_scope_missing"
    if "translation_dependency_unavailable" in warning_codes:
        return "translation_dependency_unavailable"
    return "empty_after_ranking"


def _derive_fallback_reason_from_response(response: QueryDocsResponse) -> str | None:
    warning_codes = {warning.strip().casefold() for warning in response.warnings}
    if "low_confidence_best_effort" in warning_codes:
        return "low_confidence_best_effort"
    if "translation_dependency_unavailable" in warning_codes:
        return "translation_dependency_unavailable"
    if "abuse_guard_threshold_exceeded_observe_only" in warning_codes:
        return "abuse_guard_observe_only"
    return None


def _build_request_evidence_diff(
    *,
    original: Any,
    replay: QueryDocsResponse,
    replay_outcome: str,
    replay_zero_result_reason: str | None,
    replay_fallback_reason: str | None,
    related_issue_reports: list[IssueReviewSignalResponse],
    related_usefulness_feedback: list[UsefulnessSignalResponse],
) -> RequestEvidenceDiffResponse:
    current_warning_codes = tuple(item.strip() for item in replay.warnings if item.strip())
    original_warning_codes = tuple(item.strip() for item in original.warning_codes if item.strip())
    warning_codes_added = sorted(set(current_warning_codes) - set(original_warning_codes))
    warning_codes_removed = sorted(set(original_warning_codes) - set(current_warning_codes))
    result_count_delta = len(replay.results) - original.result_count
    confidence_delta = round(replay.confidence - original.confidence, 4)
    issue_types = {item.issue_type for item in related_issue_reports}
    feedback_reason_codes = {
        reason_code
        for item in related_usefulness_feedback
        for reason_code in item.reason_codes
    }
    suspected_fault_domain, suspected_fault_reason, operator_hint = _classify_request_fault_domain(
        original=original,
        replay=replay,
        replay_outcome=replay_outcome,
        replay_zero_result_reason=replay_zero_result_reason,
        replay_fallback_reason=replay_fallback_reason,
        issue_types=issue_types,
        feedback_reason_codes=feedback_reason_codes,
    )
    drift_status, drift_summary = _build_request_drift_summary(
        original=original,
        replay_outcome=replay_outcome,
        replay_result_count=len(replay.results),
        replay_zero_result_reason=replay_zero_result_reason,
        replay_fallback_reason=replay_fallback_reason,
        confidence_delta=confidence_delta,
        warning_codes_added=warning_codes_added,
        warning_codes_removed=warning_codes_removed,
    )
    return RequestEvidenceDiffResponse(
        drift_status=drift_status,
        summary=drift_summary,
        outcome_changed=original.outcome != replay_outcome,
        original_outcome=original.outcome,
        current_outcome=replay_outcome,
        result_count_delta=result_count_delta,
        confidence_delta=confidence_delta,
        warning_codes_added=warning_codes_added,
        warning_codes_removed=warning_codes_removed,
        fallback_changed=original.fallback_reason != replay_fallback_reason,
        original_fallback_reason=original.fallback_reason,
        current_fallback_reason=replay_fallback_reason,
        zero_result_reason_changed=original.zero_result_reason != replay_zero_result_reason,
        original_zero_result_reason=original.zero_result_reason,
        current_zero_result_reason=replay_zero_result_reason,
        suspected_fault_domain=suspected_fault_domain,
        suspected_fault_reason=suspected_fault_reason,
        operator_hint=operator_hint,
        unavailable_original_fields=[
            "quality",
            "version_resolution",
            "results",
            "citations",
            "debug",
        ],
    )


def _build_request_drift_summary(
    *,
    original: Any,
    replay_outcome: str,
    replay_result_count: int,
    replay_zero_result_reason: str | None,
    replay_fallback_reason: str | None,
    confidence_delta: float,
    warning_codes_added: list[str],
    warning_codes_removed: list[str],
) -> tuple[str, str]:
    if original.outcome == "no_results" and replay_outcome == "success":
        return (
            "improved",
            "Current replay now returns usable results for a request that originally had none.",
        )
    if original.outcome == "success" and replay_outcome == "no_results":
        return (
            "regressed",
            (
                "Current replay lost results that were previously available, so "
                "retrieval or content freshness regressed."
            ),
        )
    if (
        original.outcome == replay_outcome
        and original.result_count == replay_result_count
        and original.zero_result_reason == replay_zero_result_reason
        and original.fallback_reason == replay_fallback_reason
        and abs(confidence_delta) < 0.05
        and not warning_codes_added
        and not warning_codes_removed
    ):
        return (
            "stable",
            "Current replay is materially consistent with the stored analytics outcome.",
        )
    if confidence_delta < -0.15 or replay_result_count < original.result_count:
        return (
            "regressed",
            (
                "Current replay is weaker than the stored analytics evidence and "
                "should be investigated before publish."
            ),
        )
    return (
        "changed",
        (
            "Current replay differs from stored analytics evidence and needs "
            "operator review before drawing conclusions."
        ),
    )


def _classify_request_fault_domain(
    *,
    original: Any,
    replay: QueryDocsResponse,
    replay_outcome: str,
    replay_zero_result_reason: str | None,
    replay_fallback_reason: str | None,
    issue_types: set[str],
    feedback_reason_codes: set[str],
) -> tuple[str, str, str]:
    if (
        replay_zero_result_reason == "no_index_data"
        or original.zero_result_reason == "no_index_data"
        or "missing_docs" in issue_types
    ):
        return (
            "coverage",
            (
                "The request is blocked by missing or unpublished indexed content "
                "in the requested scope."
            ),
            (
                "Validate source layout and latest-stable snapshot coverage before "
                "replaying publish decisions."
            ),
        )
    if (
        replay.version_resolution.fallback_applied
        or "outdated_docs" in issue_types
        or "outdated_version" in feedback_reason_codes
    ):
        return (
            "freshness",
            (
                "Version resolution or release freshness looks stale relative to "
                "the requested developer scenario."
            ),
            (
                "Inspect release metadata, latest-stable source revisions, and "
                "republish the freshest compatible snapshot."
            ),
        )
    if (
        "bad_example" in issue_types
        or "missing_steps" in feedback_reason_codes
        or "no_examples" in feedback_reason_codes
        or "incomplete_answer" in feedback_reason_codes
    ):
        return (
            "answer_formatting",
            (
                "The system found some content, but steps or executable examples "
                "are not sufficient for the reported workflow."
            ),
            (
                "Inspect returned snippets and chunk excerpts, then improve "
                "examples or chunk packing for the affected scope."
            ),
        )
    if (
        replay_outcome == "low_confidence"
        or original.outcome == "low_confidence"
        or replay_fallback_reason == "low_confidence_best_effort"
        or original.fallback_reason == "low_confidence_best_effort"
        or "wrong_docs" in issue_types
    ):
        return (
            "retrieval",
            (
                "Ranking or intent routing likely selected weak or misleading "
                "content for this request."
            ),
            (
                "Inspect replay top results, warning deltas, and intent/reranker "
                "behavior before changing content."
            ),
        )
    return (
        "retrieval",
        (
            "Replay drift does not point to one single subsystem, so retrieval "
            "evidence should be inspected first."
        ),
        (
            "Start with replay result ordering and warnings, then escalate to "
            "coverage or freshness only if evidence confirms it."
        ),
    )


def _build_issue_hotspot_overview(
    *,
    signals: tuple[IssueReviewSignalResponse, ...],
    limit: int,
) -> dict[str, Any]:
    total_reports = len(signals)
    if total_reports == 0:
        return {
            "filtered_reports_total": 0,
            "hotspots_total": 0,
            "by_priority": {},
            "by_product_id": {},
            "by_issue_type": {},
            "by_severity": {},
            "clusters": [],
            "refreshed_at": datetime.now(tz=UTC),
            "refresh_lag_minutes": 5,
        }

    grouped: dict[tuple[str, ...], list[IssueReviewSignalResponse]] = {}
    for signal in signals:
        key = (
            (signal.product_id or "unknown").strip().casefold(),
            (signal.programming_language or "unknown").strip().casefold(),
            (signal.doc_locale or "unknown").strip().casefold(),
            signal.issue_type.strip().casefold(),
            signal.severity.strip().casefold(),
            (signal.zero_result_reason or "none").strip().casefold(),
            (signal.fallback_reason or "none").strip().casefold(),
            _primary_warning_code(signal.warning_codes),
        )
        grouped.setdefault(key, []).append(signal)

    clusters = [
        _build_issue_hotspot_cluster(cluster_signals=cluster_signals, filtered_total=total_reports)
        for cluster_signals in grouped.values()
    ]
    clusters.sort(
        key=lambda item: (
            _hotspot_priority_rank(item.priority),
            -item.total_reports,
            -item.recent_reports_24h,
            item.hotspot_id,
        )
    )
    return {
        "filtered_reports_total": total_reports,
        "hotspots_total": len(clusters),
        "by_priority": dict(Counter(item.priority for item in clusters)),
        "by_product_id": dict(Counter(item.product_id or "unknown" for item in signals)),
        "by_issue_type": dict(Counter(item.issue_type for item in signals)),
        "by_severity": dict(Counter(item.severity for item in signals)),
        "clusters": clusters[:limit],
        "refreshed_at": datetime.now(tz=UTC),
        "refresh_lag_minutes": 5,
    }


def _build_issue_hotspot_cluster(
    *,
    cluster_signals: list[IssueReviewSignalResponse],
    filtered_total: int,
) -> IssueHotspotClusterResponse:
    ordered_signals = sorted(
        cluster_signals,
        key=lambda item: (item.updated_at, item.issue_id),
        reverse=True,
    )
    representative = ordered_signals[0]
    now = datetime.now(tz=UTC)
    recent_cutoff = now - timedelta(hours=24)
    previous_cutoff = now - timedelta(hours=48)
    recent_reports = sum(1 for item in ordered_signals if item.updated_at >= recent_cutoff)
    previous_reports = sum(
        1
        for item in ordered_signals
        if previous_cutoff <= item.updated_at < recent_cutoff
    )
    trend_delta = recent_reports - previous_reports
    if recent_reports > 0 and previous_reports == 0 and len(ordered_signals) <= 2:
        trend_status = "new"
    elif trend_delta > 0:
        trend_status = "rising"
    elif trend_delta < 0:
        trend_status = "cooling"
    else:
        trend_status = "stable"
    priority = _issue_hotspot_priority(
        severity=representative.severity,
        total_reports=len(ordered_signals),
        trend_status=trend_status,
    )
    unique_queries = _dedupe_strings(item.raw_query for item in ordered_signals)
    unique_request_ids = _dedupe_strings(item.request_id for item in ordered_signals)
    hotspot_id = ":".join(
        [
            (representative.product_id or "unknown").strip().casefold(),
            (representative.programming_language or "unknown").strip().casefold(),
            representative.issue_type.strip().casefold(),
            representative.severity.strip().casefold(),
            _primary_warning_code(representative.warning_codes),
            (representative.fallback_reason or "none").strip().casefold(),
        ]
    )
    return IssueHotspotClusterResponse(
        hotspot_id=hotspot_id,
        priority=priority,
        product_id=representative.product_id,
        programming_language=representative.programming_language,
        doc_locale=representative.doc_locale,
        issue_type=representative.issue_type,
        severity=representative.severity,
        zero_result_reason=representative.zero_result_reason,
        fallback_reason=representative.fallback_reason,
        primary_warning_code=_primary_warning_code(representative.warning_codes),
        total_reports=len(ordered_signals),
        unique_request_ids=len(set(item.request_id for item in ordered_signals)),
        recent_reports_24h=recent_reports,
        previous_reports_24h=previous_reports,
        trend_status=trend_status,
        trend_delta=trend_delta,
        share_of_filtered_reports=round(len(ordered_signals) / filtered_total, 4),
        sample_queries=unique_queries[:3],
        sample_request_ids=unique_request_ids[:3],
        recommendation_title=representative.recommendation_title,
        recommendation_detail=representative.recommendation_detail,
    )


def _issue_hotspot_priority(
    *,
    severity: str,
    total_reports: int,
    trend_status: str,
) -> str:
    normalized_severity = severity.strip().casefold()
    if normalized_severity == "critical" and (total_reports >= 3 or trend_status == "rising"):
        return "highest"
    if normalized_severity == "critical" or total_reports >= 4:
        return "high"
    if normalized_severity == "warning" and total_reports >= 2:
        return "medium"
    return "low"


def _hotspot_priority_rank(value: str) -> int:
    mapping = {
        "highest": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    return mapping.get(value.strip().casefold(), 9)


def _primary_warning_code(warning_codes: list[str]) -> str:
    priority_order = {
        "no_index_data": 0,
        "product_scope_missing": 1,
        "version_scope_missing": 2,
        "translation_dependency_unavailable": 3,
        "low_confidence_best_effort": 4,
        "answer_incomplete": 5,
    }
    normalized_warning_codes = sorted(
        (item.strip().casefold() for item in warning_codes if item.strip()),
        key=lambda item: (priority_order.get(item, 99), item),
    )
    if normalized_warning_codes:
        return normalized_warning_codes[0]
    return "none"


def _dedupe_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rows.append(normalized)
    return rows


def _build_public_adoption_funnel(
    *,
    query_records: tuple[Any, ...],
    feedback_records: tuple[Any, ...],
    issue_records: tuple[Any, ...],
    client_id: str | None,
    limit: int,
) -> dict[str, Any]:
    sessions: dict[str, dict[str, Any]] = {}
    request_to_session: dict[str, str] = {}

    for record in query_records:
        stage_id = _public_funnel_stage_from_query_record(record)
        if stage_id is None:
            continue
        session_id = _public_session_identity_from_query_record(record)
        request_to_session[str(record.request_id)] = session_id
        session = sessions.setdefault(session_id, _create_public_funnel_session(session_id))
        _merge_public_funnel_scope(
            session=session,
            product_id=record.product_id,
            programming_language=record.programming_language,
            doc_locale=record.doc_locale,
            prefer_primary=stage_id in {"self_test", "query"},
        )
        session["stages"].add(stage_id)
        session["latest_activity_at"] = max(session["latest_activity_at"], record.created_at)
        session["request_ids"].add(str(record.request_id))
        if stage_id == "self_test":
            parsed_client_id = _parse_public_self_test_field(record.raw_query, "client")
            if parsed_client_id:
                session["client_ids"].add(parsed_client_id)
                session["primary_client_id"] = session["primary_client_id"] or parsed_client_id
            self_test_status = _parse_public_self_test_field(record.raw_query, "status")
            if self_test_status:
                session["self_test_status"] = self_test_status
            self_test_transport = _parse_public_self_test_field(record.raw_query, "transport")
            if self_test_transport:
                session["self_test_transport"] = self_test_transport
        if stage_id == "query":
            outcome = str(record.outcome or "unknown").strip().casefold()
            if outcome:
                session["query_outcomes"].add(outcome)
            if _record_has_query_problem(record):
                session["poor_query_request_ids"].add(str(record.request_id))
            if record.zero_result_reason:
                session["zero_result_reasons"].add(str(record.zero_result_reason).strip().casefold())
            if record.fallback_reason:
                session["fallback_reasons"].add(str(record.fallback_reason).strip().casefold())

    for record in feedback_records:
        resolved_session_id = request_to_session.get(str(record.request_id))
        if resolved_session_id is None:
            resolved_session_id = _public_session_identity_from_actor(
                actor_identity=record.actor_identity,
                request_id=record.request_id,
            )
        session = sessions.setdefault(
            resolved_session_id,
            _create_public_funnel_session(resolved_session_id),
        )
        _merge_public_funnel_scope(
            session=session,
            product_id=record.product_id,
            programming_language=record.programming_language,
            doc_locale=record.doc_locale,
            prefer_primary=True,
        )
        session["stages"].add("feedback")
        session["latest_activity_at"] = max(session["latest_activity_at"], record.updated_at)
        session["request_ids"].add(str(record.request_id))
        session["feedback_request_ids"].add(str(record.request_id))
        _merge_public_funnel_actor_identity(session=session, actor_identity=record.actor_identity)
        if record.zero_result_reason:
            session["zero_result_reasons"].add(str(record.zero_result_reason).strip().casefold())
        if record.fallback_reason:
            session["fallback_reasons"].add(str(record.fallback_reason).strip().casefold())

    for record in issue_records:
        resolved_session_id = request_to_session.get(str(record.request_id))
        if resolved_session_id is None:
            resolved_session_id = _public_session_identity_from_actor(
                actor_identity=record.actor_identity,
                request_id=record.request_id,
            )
        session = sessions.setdefault(
            resolved_session_id,
            _create_public_funnel_session(resolved_session_id),
        )
        _merge_public_funnel_scope(
            session=session,
            product_id=record.product_id,
            programming_language=record.programming_language,
            doc_locale=record.doc_locale,
            prefer_primary=True,
        )
        session["stages"].add("issue")
        session["latest_activity_at"] = max(session["latest_activity_at"], record.updated_at)
        session["request_ids"].add(str(record.request_id))
        session["issue_request_ids"].add(str(record.request_id))
        _merge_public_funnel_actor_identity(session=session, actor_identity=record.actor_identity)
        if record.zero_result_reason:
            session["zero_result_reasons"].add(str(record.zero_result_reason).strip().casefold())
        if record.fallback_reason:
            session["fallback_reasons"].add(str(record.fallback_reason).strip().casefold())

    normalized_client_id = client_id.strip().casefold() if client_id and client_id.strip() else None
    filtered_sessions = [
        session
        for session in sessions.values()
        if normalized_client_id is None or normalized_client_id in session["client_ids"]
    ]
    total_sessions = len(filtered_sessions)
    if total_sessions == 0:
        return {
            "filtered_sessions_total": 0,
            "by_product_id": {},
            "by_programming_language": {},
            "by_client_id": {},
            "stages": [
                PublicFunnelStageResponse(
                    stage_id=stage_id,
                    title=title,
                    sessions=0,
                    share_of_filtered_sessions=0.0,
                    conversion_from_previous=None if index == 0 else 0.0,
                )
                for index, (stage_id, title) in enumerate(_public_funnel_stage_order())
            ],
            "top_dropoffs": [],
            "scopes": [],
            "refreshed_at": datetime.now(tz=UTC),
            "refresh_lag_minutes": 5,
        }

    stage_counts = {
        stage_id: sum(1 for session in filtered_sessions if stage_id in session["stages"])
        for stage_id, _ in _public_funnel_stage_order()
    }
    stages: list[PublicFunnelStageResponse] = []
    previous_count: int | None = None
    for stage_id, title in _public_funnel_stage_order():
        current_count = stage_counts[stage_id]
        stages.append(
            PublicFunnelStageResponse(
                stage_id=stage_id,
                title=title,
                sessions=current_count,
                share_of_filtered_sessions=round(current_count / total_sessions, 4),
                conversion_from_previous=(
                    None
                    if previous_count is None
                    else round(current_count / previous_count, 4)
                    if previous_count > 0
                    else 0.0
                ),
            )
        )
        previous_count = current_count

    grouped_scopes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for session in filtered_sessions:
        scope_key = (
            session["primary_product_id"] or "unknown",
            session["primary_programming_language"] or "unknown",
            session["primary_client_id"] or "unknown",
        )
        grouped_scopes.setdefault(scope_key, []).append(session)

    scopes: list[PublicFunnelScopeResponse] = []
    for (
        scope_product_id,
        scope_language,
        scope_client_id,
    ), scope_sessions in grouped_scopes.items():
        latest_activity = max(session["latest_activity_at"] for session in scope_sessions)
        scopes.append(
            PublicFunnelScopeResponse(
                scope_id=f"{scope_product_id}:{scope_language}:{scope_client_id}",
                product_id=None if scope_product_id == "unknown" else scope_product_id,
                programming_language=None if scope_language == "unknown" else scope_language,
                client_id=None if scope_client_id == "unknown" else scope_client_id,
                sessions=len(scope_sessions),
                resolve_sessions=sum(
                    1 for session in scope_sessions if "resolve" in session["stages"]
                ),
                self_test_sessions=sum(
                    1 for session in scope_sessions if "self_test" in session["stages"]
                ),
                query_sessions=sum(1 for session in scope_sessions if "query" in session["stages"]),
                feedback_sessions=sum(
                    1 for session in scope_sessions if "feedback" in session["stages"]
                ),
                issue_sessions=sum(1 for session in scope_sessions if "issue" in session["stages"]),
                zero_result_sessions=sum(
                    1 for session in scope_sessions if len(session["poor_query_request_ids"]) > 0
                ),
                latest_activity_at=latest_activity,
            )
        )
    scopes.sort(
        key=lambda item: (
            -item.sessions,
            -item.query_sessions,
            -item.zero_result_sessions,
            item.scope_id,
        )
    )

    dropoff_rows = _build_public_funnel_dropoffs(filtered_sessions=filtered_sessions)
    dropoff_rows.sort(
        key=lambda item: (-item.sessions, item.stage_id, item.dropoff_id),
    )

    return {
        "filtered_sessions_total": total_sessions,
        "by_product_id": _count_session_scope_values(filtered_sessions, "product_ids"),
        "by_programming_language": _count_session_scope_values(
            filtered_sessions,
            "programming_languages",
        ),
        "by_client_id": _count_session_scope_values(filtered_sessions, "client_ids"),
        "stages": stages,
        "top_dropoffs": dropoff_rows[:limit],
        "scopes": scopes[:limit],
        "refreshed_at": datetime.now(tz=UTC),
        "refresh_lag_minutes": 5,
    }


def _public_funnel_stage_order() -> tuple[tuple[str, str], ...]:
    return (
        ("resolve", "Resolve product"),
        ("self_test", "Run self-test"),
        ("query", "Execute query"),
        ("feedback", "Submit usefulness feedback"),
        ("issue", "Submit issue report"),
    )


def _create_public_funnel_session(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "stages": set(),
        "request_ids": set(),
        "feedback_request_ids": set(),
        "issue_request_ids": set(),
        "product_ids": set(),
        "programming_languages": set(),
        "doc_locales": set(),
        "client_ids": set(),
        "query_outcomes": set(),
        "poor_query_request_ids": set(),
        "zero_result_reasons": set(),
        "fallback_reasons": set(),
        "primary_product_id": None,
        "primary_programming_language": None,
        "primary_client_id": None,
        "self_test_status": None,
        "self_test_transport": None,
        "latest_activity_at": datetime.fromtimestamp(0, tz=UTC),
    }


def _merge_public_funnel_scope(
    *,
    session: dict[str, Any],
    product_id: str | None,
    programming_language: str | None,
    doc_locale: str | None,
    prefer_primary: bool = False,
) -> None:
    normalized_product_id = _normalize_public_scope_value(product_id)
    if normalized_product_id is not None:
        session["product_ids"].add(normalized_product_id)
        if prefer_primary or session["primary_product_id"] is None:
            session["primary_product_id"] = normalized_product_id
    normalized_programming_language = _normalize_public_scope_value(programming_language)
    if normalized_programming_language is not None:
        session["programming_languages"].add(normalized_programming_language)
        if prefer_primary or session["primary_programming_language"] is None:
            session["primary_programming_language"] = normalized_programming_language
    normalized_doc_locale = _normalize_public_scope_value(doc_locale)
    if normalized_doc_locale is not None:
        session["doc_locales"].add(normalized_doc_locale)


def _merge_public_funnel_actor_identity(
    *,
    session: dict[str, Any],
    actor_identity: str,
) -> None:
    normalized_actor_identity = actor_identity.strip()
    if normalized_actor_identity.startswith("client:"):
        client_value = _normalize_public_scope_value(
            normalized_actor_identity.split(":", maxsplit=1)[1]
        )
        if client_value is not None:
            session["client_ids"].add(client_value)
            session["primary_client_id"] = session["primary_client_id"] or client_value


def _normalize_public_scope_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    return normalized


def _public_funnel_stage_from_query_record(record: Any) -> str | None:
    endpoint = str(record.endpoint).strip().casefold()
    if endpoint == "rest.products.resolve":
        return "resolve"
    if endpoint == "public.integrations.self_test":
        return "self_test"
    if endpoint == "rest.docs.query":
        return "query"
    return None


def _public_session_identity_from_query_record(record: Any) -> str:
    fingerprint = _normalize_public_scope_value(record.fingerprint)
    if fingerprint is not None:
        return f"fingerprint:{fingerprint}"
    hashed_ip = _normalize_public_scope_value(record.hashed_ip)
    if hashed_ip is not None:
        return f"hashed_ip:{hashed_ip}"
    return f"request:{record.request_id}"


def _public_session_identity_from_actor(*, actor_identity: str, request_id: str) -> str:
    normalized_actor_identity = actor_identity.strip()
    if normalized_actor_identity:
        return normalized_actor_identity
    return f"request:{request_id}"


def _parse_public_self_test_field(raw_query: str, field_name: str) -> str | None:
    segments = [segment.strip() for segment in raw_query.split(";") if segment.strip()]
    normalized_field_name = field_name.strip().casefold()
    for segment in segments:
        key, separator, value = segment.partition("=")
        if separator != "=":
            continue
        if key.strip().casefold() != normalized_field_name:
            continue
        normalized_value = _normalize_public_scope_value(value)
        if normalized_value is not None:
            return normalized_value
    return None


def _record_has_query_problem(record: Any) -> bool:
    outcome = str(record.outcome or "").strip().casefold()
    if outcome in {"no_results", "low_confidence"}:
        return True
    if record.zero_result_reason is not None:
        return True
    fallback_reason = _normalize_public_scope_value(record.fallback_reason)
    return fallback_reason == "low_confidence_best_effort"


def _count_session_scope_values(
    sessions: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for session in sessions:
        values = session[key]
        if values:
            counter.update(values)
        else:
            counter.update(["unknown"])
    return dict(counter)


def _build_public_funnel_dropoffs(
    *,
    filtered_sessions: list[dict[str, Any]],
) -> list[PublicFunnelDropoffResponse]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for session in filtered_sessions:
        stage_ids = session["stages"]
        dropoff_id: str | None = None
        stage_id: str | None = None
        reason: str | None = None
        recommendation_title: str | None = None
        recommendation_detail: str | None = None
        if "resolve" in stage_ids and "self_test" not in stage_ids:
            dropoff_id = "resolved_without_self_test"
            stage_id = "resolve"
            reason = "Users resolved the product but never validated MCP connectivity."
            recommendation_title = "Promote self-test sooner"
            recommendation_detail = (
                "Move the caller from product resolution into the public self-test flow so client "
                "config and readiness issues are discovered before the first real query."
            )
        elif "self_test" in stage_ids and "query" not in stage_ids:
            self_test_status = session["self_test_status"] or "unknown"
            stage_id = "self_test"
            if self_test_status == "ready":
                dropoff_id = "self_test_ready_without_query"
                reason = "The self-test succeeded, but no real query followed."
                recommendation_title = "Tighten quick-start guidance"
                recommendation_detail = (
                    "Surface starter prompts and first queries more aggressively after a ready "
                    "self-test so developers can immediately prove value."
                )
            elif self_test_status == "partial":
                dropoff_id = "self_test_partial_without_query"
                reason = "The self-test returned partial readiness and the journey stopped there."
                recommendation_title = "Reduce partial-readiness friction"
                recommendation_detail = (
                    "Clarify which source kind or snippet surface is missing and link directly to "
                    "coverage/freshness guidance so users know whether the limitation is blocking."
                )
            else:
                dropoff_id = "self_test_not_ready"
                reason = "The self-test found readiness problems before the first query."
                recommendation_title = "Fix readiness blockers"
                recommendation_detail = (
                    "Prioritize missing active snapshots, degraded dependencies, or unsupported "
                    "client/transport combinations that stop the first successful query."
                )
        elif "query" in stage_ids and "feedback" not in stage_ids and "issue" not in stage_ids:
            problematic_query = len(session["poor_query_request_ids"]) > 0
            if problematic_query:
                if "no_results" in session["query_outcomes"] or session["zero_result_reasons"]:
                    dropoff_id = "query_zero_result_without_followup"
                    reason = (
                        "The journey reached query execution, but the result was empty "
                        "and no follow-up signal was left."
                    )
                    recommendation_title = "Improve issue/report prompts"
                    recommendation_detail = (
                        "Prompt for usefulness feedback or issue intake immediately "
                        "after zero-result responses so product owners get actionable "
                        "evidence instead of silent drop-off."
                    )
                else:
                    dropoff_id = "query_low_confidence_without_followup"
                    reason = (
                        "Low-confidence retrieval finished the journey without "
                        "feedback or issue evidence."
                    )
                    recommendation_title = "Ask for post-query confirmation"
                    recommendation_detail = (
                        "Offer sharper feedback prompts after low-confidence answers "
                        "and direct the developer toward replay/share tools when the "
                        "answer still looks weak."
                    )
                stage_id = "query"
        if dropoff_id is None or stage_id is None or reason is None:
            continue
        grouped.setdefault(dropoff_id, []).append(
            {
                "stage_id": stage_id,
                "reason": reason,
                "recommendation_title": recommendation_title,
                "recommendation_detail": recommendation_detail,
            }
        )

    total_sessions = len(filtered_sessions)
    rows: list[PublicFunnelDropoffResponse] = []
    for dropoff_id, entries in grouped.items():
        representative = entries[0]
        rows.append(
            PublicFunnelDropoffResponse(
                dropoff_id=dropoff_id,
                stage_id=representative["stage_id"],
                reason=representative["reason"],
                sessions=len(entries),
                share_of_filtered_sessions=round(len(entries) / total_sessions, 4),
                recommendation_title=representative["recommendation_title"],
                recommendation_detail=representative["recommendation_detail"],
            )
        )
    return rows


def _build_freshness_watchlist(
    *,
    request: Request,
    query_records: tuple[Any, ...],
    feedback_records: tuple[Any, ...],
    issue_records: tuple[Any, ...],
    product_id: str | None,
    programming_language: str | None,
    source_kind: str | None,
    stale_after_days: int,
    limit: int,
) -> dict[str, Any]:
    normalized_source_kind = source_kind.strip().casefold() if source_kind else None
    service_rows = _collect_content_service_rows(request, product_id=product_id)
    snapshot_registry = _get_snapshot_registry(request)
    orchestrator = _get_source_hugo_orchestrator(request)
    snapshots = snapshot_registry.list_snapshots(
        product_id=product_id,
        programming_language=programming_language,
    )

    scope_snapshots: dict[tuple[str, str, str], list[Any]] = {}
    product_languages: dict[str, set[str]] = {}
    for snapshot in snapshots:
        language_key = snapshot.programming_language.strip()
        if not language_key:
            continue
        product_languages.setdefault(snapshot.product_id, set()).add(language_key)
        scope_snapshots.setdefault(
            (snapshot.product_id, language_key, snapshot.source_kind),
            [],
        ).append(snapshot)

    for record in query_records:
        if record.product_id and record.programming_language:
            product_languages.setdefault(record.product_id, set()).add(
                record.programming_language
            )
    for record in feedback_records:
        if record.product_id and record.programming_language:
            product_languages.setdefault(record.product_id, set()).add(
                record.programming_language
            )
    for record in issue_records:
        if record.product_id and record.programming_language:
            product_languages.setdefault(record.product_id, set()).add(
                record.programming_language
            )

    query_counts: dict[tuple[str, str], Counter[str]] = {}
    for record in query_records:
        if not record.product_id or not record.programming_language:
            continue
        scope_key = (record.product_id, record.programming_language)
        counts = query_counts.setdefault(scope_key, Counter())
        counts["query_sessions"] += 1
        if record.outcome == "no_results":
            counts["no_result_sessions"] += 1
        if record.outcome == "low_confidence" or (
            record.fallback_reason == "low_confidence_best_effort"
        ):
            counts["low_confidence_sessions"] += 1

    feedback_counts: Counter[tuple[str, str]] = Counter()
    for record in feedback_records:
        if not record.product_id or not record.programming_language:
            continue
        feedback_counts[(record.product_id, record.programming_language)] += 1

    issue_counts: dict[tuple[str, str], Counter[str]] = {}
    for record in issue_records:
        if not record.product_id or not record.programming_language:
            continue
        scope_key = (record.product_id, record.programming_language)
        counts = issue_counts.setdefault(scope_key, Counter())
        signal = _to_issue_review_signal_response(record)
        counts["issue_reports"] += 1
        counts[signal.severity] += 1

    release_counts: Counter[tuple[str, str, str]] = Counter()
    snippet_counts: Counter[tuple[str, str, str]] = Counter()
    indexed_counts: Counter[tuple[str, str, str]] = Counter()
    if orchestrator is not None:
        latest_records = orchestrator.get_latest_chunk_records(
            product_id=product_id,
            programming_language=programming_language,
        )
        for record in latest_records:
            chunk_scope_key: tuple[str, str, str] = (
                record.product_id,
                record.programming_language,
                record.source_kind,
            )
            indexed_counts[chunk_scope_key] += 1
            snippet_counts[chunk_scope_key] += len(record.executable_snippets)
        for record in _filter_release_feature_records(
            records=latest_records,
            requested_version=None,
        ):
            release_scope_key: tuple[str, str, str] = (
                record.product_id,
                record.programming_language,
                record.source_kind,
            )
            release_counts[release_scope_key] += 1

    items: list[FreshnessWatchlistScopeResponse] = []
    now = datetime.now(tz=UTC)
    for service_row in service_rows:
        if normalized_source_kind and service_row.source_kind.casefold() != normalized_source_kind:
            continue

        language_candidates = sorted(
            set(service_row.supported_programming_languages)
            | product_languages.get(service_row.product_id, set())
        )
        if programming_language:
            language_candidates = [programming_language]
        if not language_candidates:
            language_candidates = ["unknown"]

        for language_value in language_candidates:
            language_key = language_value if language_value != "unknown" else ""
            scoped_snapshots = scope_snapshots.get(
                (service_row.product_id, language_key, service_row.source_kind),
                [],
            )
            active_snapshot = max(
                (
                    snapshot
                    for snapshot in scoped_snapshots
                    if snapshot.status.value == "active"
                ),
                key=lambda item: item.created_at,
                default=None,
            )
            latest_active_version = active_snapshot.version if active_snapshot is not None else None
            newest_visible_version = (
                max(
                    scoped_snapshots,
                    key=lambda item: _analytics_version_sort_key(item.version),
                ).version
                if scoped_snapshots
                else None
            )
            stale_days = None
            if active_snapshot is not None:
                stale_days = max(
                    0,
                    int((now - active_snapshot.created_at).total_seconds() // 86400),
                )

            language_scope = (service_row.product_id, language_key or "unknown")
            source_scope = (
                service_row.product_id,
                language_key or "unknown",
                service_row.source_kind,
            )
            query_scope_counts = query_counts.get(language_scope, Counter())
            issue_scope_counts = issue_counts.get(language_scope, Counter())
            indexed_chunks_count = indexed_counts.get(source_scope, 0)
            executable_snippets_count = snippet_counts.get(source_scope, 0)
            release_feature_signals = release_counts.get(source_scope, 0)
            release_visibility_gap = bool(
                latest_active_version
                and newest_visible_version
                and latest_active_version != newest_visible_version
            )

            risk_score, primary_reason, recommended_action = _freshness_watchlist_risk(
                service_status=service_row.service_status,
                stale_days=stale_days,
                stale_after_days=stale_after_days,
                release_visibility_gap=release_visibility_gap,
                release_feature_signals=release_feature_signals,
                no_result_sessions=query_scope_counts.get("no_result_sessions", 0),
                low_confidence_sessions=query_scope_counts.get("low_confidence_sessions", 0),
                issue_reports=issue_scope_counts.get("issue_reports", 0),
                critical_issue_reports=issue_scope_counts.get("critical", 0),
                negative_feedback=feedback_counts.get(language_scope, 0),
                indexed_chunks_count=indexed_chunks_count,
                executable_snippets_count=executable_snippets_count,
                parse_warnings_count=service_row.parse_warnings_count,
                failed_items_count=service_row.failed_items_count,
            )
            fix_plan = list(service_row.fix_plan)
            if release_visibility_gap:
                fix_plan.append(
                    "Compare active and newest visible versions, then republish "
                    "the newest validated snapshot."
                )
            if issue_scope_counts.get("critical", 0) > 0:
                fix_plan.append(
                    "Inspect recent issue reports and replay evidence before "
                    "changing content or retrieval policy."
                )
            if executable_snippets_count <= 0 and indexed_chunks_count > 0:
                fix_plan.append(
                    "Recover executable snippets so public MCP answers can "
                    "return runnable examples."
                )
            items.append(
                FreshnessWatchlistScopeResponse(
                    scope_id=(
                        f"{service_row.product_id}:"
                        f"{language_key or 'unknown'}:"
                        f"{service_row.source_kind}:"
                        f"{service_row.repo_id}"
                    ),
                    product_id=service_row.product_id,
                    programming_language=language_key or None,
                    source_kind=service_row.source_kind,
                    repo_id=service_row.repo_id,
                    risk_score=risk_score,
                    risk_level=_freshness_watchlist_level(risk_score),
                    primary_reason=primary_reason,
                    recommended_action=recommended_action,
                    stale_days=stale_days,
                    latest_active_snapshot_at=(
                        active_snapshot.created_at if active_snapshot is not None else None
                    ),
                    latest_active_version=latest_active_version,
                    newest_visible_version=newest_visible_version,
                    release_visibility_gap=release_visibility_gap,
                    release_feature_signals=release_feature_signals,
                    query_sessions_30d=query_scope_counts.get("query_sessions", 0),
                    no_result_sessions_30d=query_scope_counts.get("no_result_sessions", 0),
                    low_confidence_sessions_30d=query_scope_counts.get(
                        "low_confidence_sessions",
                        0,
                    ),
                    issue_reports_30d=issue_scope_counts.get("issue_reports", 0),
                    critical_issue_reports_30d=issue_scope_counts.get("critical", 0),
                    negative_feedback_30d=feedback_counts.get(language_scope, 0),
                    indexed_chunks_count=indexed_chunks_count,
                    executable_snippets_count=executable_snippets_count,
                    parse_warnings_count=service_row.parse_warnings_count,
                    failed_items_count=service_row.failed_items_count,
                    service_status=service_row.service_status,
                    service_status_reason=service_row.service_status_reason,
                    fix_plan=_dedupe_preserve_order(fix_plan)[:5],
                )
            )

    items.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.risk_level, 9),
            -item.risk_score,
            -(item.issue_reports_30d + item.negative_feedback_30d),
            -(item.stale_days or -1),
            item.product_id,
            (item.programming_language or "unknown"),
            item.source_kind,
        )
    )
    items = items[:limit]
    high_risk_total = sum(1 for item in items if item.risk_level == "high")
    medium_risk_total = sum(1 for item in items if item.risk_level == "medium")
    low_risk_total = sum(1 for item in items if item.risk_level == "low")
    status_summary = (
        (
            f"Freshness watchlist scopes={len(items)}: high={high_risk_total}, "
            f"medium={medium_risk_total}, low={low_risk_total}."
        )
        if items
        else "No freshness watchlist scopes matched the current filters."
    )
    return {
        "filtered_scopes_total": len(items),
        "high_risk_total": high_risk_total,
        "medium_risk_total": medium_risk_total,
        "low_risk_total": low_risk_total,
        "by_product_id": dict(Counter(item.product_id for item in items)),
        "by_programming_language": dict(
            Counter(item.programming_language or "unknown" for item in items)
        ),
        "by_source_kind": dict(Counter(item.source_kind for item in items)),
        "status_summary": status_summary,
        "items": items,
        "refreshed_at": now,
        "refresh_lag_minutes": 5,
    }


def _freshness_watchlist_risk(
    *,
    service_status: str,
    stale_days: int | None,
    stale_after_days: int,
    release_visibility_gap: bool,
    release_feature_signals: int,
    no_result_sessions: int,
    low_confidence_sessions: int,
    issue_reports: int,
    critical_issue_reports: int,
    negative_feedback: int,
    indexed_chunks_count: int,
    executable_snippets_count: int,
    parse_warnings_count: int,
    failed_items_count: int,
) -> tuple[int, str, str]:
    contributions: list[tuple[int, str, str]] = []
    if service_status != "healthy":
        contributions.append(
            (
                42,
                "No active healthy content service is serving this scope.",
                "Reingest or republish the scope before public traffic grows further.",
            )
        )
    if stale_days is not None and stale_days > stale_after_days:
        stale_points = 35 if stale_days >= max(stale_after_days * 2, 60) else 22
        contributions.append(
            (
                stale_points,
                f"Active snapshot age reached {stale_days} day(s), beyond the freshness threshold.",
                "Sync sources and publish a fresher validated snapshot.",
            )
        )
    elif stale_days is not None and stale_days >= max(14, stale_after_days // 2):
        contributions.append(
            (
                10,
                f"Snapshot age is drifting upward ({stale_days} day(s)).",
                "Schedule a validation run before the scope becomes stale.",
            )
        )
    if release_visibility_gap:
        contributions.append(
            (
                16,
                "A newer visible version exists than the currently active one.",
                "Inspect release visibility and promote the newest validated version.",
            )
        )
    if release_feature_signals <= 0:
        contributions.append(
            (
                6,
                "No release-note feature signals were extracted for this scope.",
                "Validate release-note indexing so freshness cues stay explainable.",
            )
        )
    if indexed_chunks_count <= 0:
        contributions.append(
            (
                24,
                "No indexed chunks are available for this scope.",
                "Fix ingestion coverage before troubleshooting retrieval ranking.",
            )
        )
    if indexed_chunks_count > 0 and executable_snippets_count <= 0:
        contributions.append(
            (
                8,
                "Indexed content has no executable snippets.",
                "Recover code examples so MCP answers remain actionable.",
            )
        )
    if no_result_sessions > 0:
        contributions.append(
            (
                min(18, no_result_sessions * 4),
                f"Recent public queries still hit {no_result_sessions} no-result session(s).",
                "Inspect zero-result evidence and republish missing coverage.",
            )
        )
    if low_confidence_sessions > 0:
        contributions.append(
            (
                min(14, low_confidence_sessions * 3),
                (
                    "Low-confidence answers were observed in "
                    f"{low_confidence_sessions} recent session(s)."
                ),
                "Review release freshness, examples, and reranking for this scope.",
            )
        )
    if critical_issue_reports > 0:
        contributions.append(
            (
                min(22, critical_issue_reports * 8),
                f"Critical issue pressure exists in {critical_issue_reports} recent report(s).",
                "Open issue evidence first and turn it into a concrete content fix plan.",
            )
        )
    elif issue_reports > 0:
        contributions.append(
            (
                min(12, issue_reports * 3),
                f"Recent issue pressure exists in {issue_reports} report(s).",
                "Review reported problems before they turn into broader adoption drop-offs.",
            )
        )
    if negative_feedback > 0:
        contributions.append(
            (
                min(10, negative_feedback * 2),
                f"Negative usefulness feedback was recorded {negative_feedback} time(s).",
                "Inspect answer completeness and release freshness for the affected workflow.",
            )
        )
    if failed_items_count > 0:
        contributions.append(
            (
                min(12, failed_items_count * 2),
                f"Latest ingestion still has {failed_items_count} failed item(s).",
                (
                    "Clear failed ingestion items before trusting stale-risk "
                    "as only a retrieval problem."
                ),
            )
        )
    if parse_warnings_count > 0:
        contributions.append(
            (
                min(8, parse_warnings_count),
                f"Latest ingestion still reports {parse_warnings_count} parse warning(s).",
                "Inspect parser warnings to avoid silent content drift.",
            )
        )

    if not contributions:
        return (
            0,
            "No strong freshness-drift signals are active for this scope.",
            "Keep the scope under normal monitoring and rerun ingestion on the regular cadence.",
        )

    contributions.sort(key=lambda item: (-item[0], item[1]))
    risk_score = max(0, min(100, sum(item[0] for item in contributions)))
    return risk_score, contributions[0][1], contributions[0][2]


def _freshness_watchlist_level(risk_score: int) -> str:
    if risk_score >= 65:
        return "high"
    if risk_score >= 35:
        return "medium"
    return "low"


def _analytics_version_sort_key(version: str) -> tuple[int, int, int, int]:
    tokens = re.findall(r"\d+", version)
    numbers = [int(token) for token in tokens[:4]]
    while len(numbers) < 4:
        numbers.append(-1)
    return (-numbers[0], -numbers[1], -numbers[2], -numbers[3])


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _to_config_history_response(record: Any) -> ConfigHistoryResponse:
    return ConfigHistoryResponse(
        change_id=record.change_id,
        product_id=record.product_id,
        config_scope=record.config_scope,
        config_key=record.config_key,
        action_type=record.action_type,
        before=record.before,
        after=record.after,
        actor_key_id=record.actor_key_id,
        request_id=record.request_id,
        reason=record.reason,
        rollback_of_change_id=record.rollback_of_change_id,
        created_at=record.created_at,
        artifact_path=record.artifact_path,
    )


def _to_usefulness_signal_response(record: Any) -> UsefulnessSignalResponse:
    return UsefulnessSignalResponse(
        feedback_id=record.feedback_id,
        request_id=record.request_id,
        rating=record.rating,
        reason_codes=list(record.reason_codes),
        product_id=record.product_id,
        programming_language=record.programming_language,
        doc_locale=record.doc_locale,
        endpoint=record.endpoint,
        tool=record.tool,
        raw_query=record.raw_query,
        outcome=record.outcome,
        retrieval_mode=record.retrieval_mode,
        result_count=record.result_count,
        zero_result_reason=record.zero_result_reason,
        fallback_reason=record.fallback_reason,
        warning_codes=list(record.warning_codes),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_issue_review_signal_response(record: Any) -> IssueReviewSignalResponse:
    severity, severity_reason = _issue_review_severity(record)
    recommendation_title, recommendation_detail = _issue_review_recommendation(record)
    return IssueReviewSignalResponse(
        issue_id=record.issue_id,
        request_id=record.request_id,
        issue_type=record.issue_type,
        severity=severity,
        severity_reason=severity_reason,
        recommendation_title=recommendation_title,
        recommendation_detail=recommendation_detail,
        product_id=record.product_id,
        programming_language=record.programming_language,
        doc_locale=record.doc_locale,
        endpoint=record.endpoint,
        tool=record.tool,
        raw_query=record.raw_query,
        outcome=record.outcome,
        retrieval_mode=record.retrieval_mode,
        result_count=record.result_count,
        zero_result_reason=record.zero_result_reason,
        fallback_reason=record.fallback_reason,
        warning_codes=list(record.warning_codes),
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _normalize_issue_severity(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if normalized not in {"critical", "warning", "info"}:
        msg = "Invalid issue severity."
        raise ValueError(msg)
    return normalized


def _issue_review_severity(record: Any) -> tuple[str, str]:
    warning_codes = {item.casefold() for item in getattr(record, "warning_codes", ())}
    issue_type = str(record.issue_type).casefold()
    if issue_type == "missing_docs" and (
        record.result_count == 0
        or record.zero_result_reason is not None
        or record.outcome in {"no_results", "low_confidence"}
    ):
        return (
            "critical",
            "No usable content was returned for the reported scope, "
            "so the developer is blocked without an obvious workaround.",
        )
    if issue_type == "wrong_docs" and record.result_count > 0:
        return (
            "critical",
            "The caller reported incorrect documentation despite a non-empty answer, "
            "which risks generating confidently wrong code.",
        )
    if issue_type in {"missing_docs", "wrong_docs", "outdated_docs", "bad_example"}:
        return (
            "warning",
            "The report points to a quality gap that needs review, "
            "but the request was not fully blocked by an empty result.",
        )
    if record.fallback_reason is not None or "low_confidence_best_effort" in warning_codes:
        return (
            "warning",
            "Fallback or low-confidence retrieval signals were present, "
            "so the issue should be reviewed before more users hit the same path.",
        )
    return (
        "info",
        "The report needs manual triage because current telemetry does not show "
        "a clear blocking or quality-degrading failure pattern.",
    )


def _issue_review_recommendation(record: Any) -> tuple[str, str]:
    issue_type = str(record.issue_type).casefold()
    if issue_type == "missing_docs" and (
        record.zero_result_reason == "no_index_data" or record.result_count == 0
    ):
        return (
            "Republish or expand coverage",
            "Validate the source scope, check latest-stable snapshot presence, "
            "and republish or widen indexed coverage for the affected product/language.",
        )
    if issue_type == "wrong_docs":
        return (
            "Replay and inspect ranking",
            "Replay the original request_id, compare current vs original results, "
            "and inspect whether ranking, filters, or symbol/task intent routing "
            "selected the wrong source.",
        )
    if issue_type == "outdated_docs":
        return (
            "Review freshness and release scope",
            "Check latest release visibility, snapshot age, and release-aware "
            "retrieval so the latest-stable documentation outranks stale results.",
        )
    if issue_type == "bad_example":
        return (
            "Revise examples and snippets",
            "Review the cited examples, add or replace runnable snippets, and "
            "ensure the task answer includes the expected implementation path.",
        )
    return (
        "Manual triage",
        "Inspect the linked request evidence, warnings, and fallback signals, "
        "then decide whether this is a coverage, freshness, retrieval, or UX problem.",
    )


def _to_retrieval_snapshot_from_record(record: Any) -> dict[str, Any]:
    return {
        "product_id": record.product_id,
        "top_k": record.top_k,
        "max_context_tokens": record.max_context_tokens,
        "excerpt_char_limit": record.excerpt_char_limit,
        "low_confidence_threshold": record.low_confidence_threshold,
        "clarification_policy": record.clarification_policy,
    }


def _resolve_alias_external_language_id(change: Any) -> str:
    before = change.before if isinstance(change.before, dict) else None
    after = change.after if isinstance(change.after, dict) else None
    if before is not None:
        value = before.get("external_language_id")
        if isinstance(value, str) and value.strip():
            return value
    if after is not None:
        value = after.get("external_language_id")
        if isinstance(value, str) and value.strip():
            return value
    config_key = str(change.config_key)
    if ":" in config_key:
        return config_key.split(":", maxsplit=1)[1]
    msg = "Cannot resolve external_language_id from config history record."
    raise ValueError(msg)


@router.get("/admin/v1/config/history", response_model=list[ConfigHistoryResponse])
def list_config_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    product_id: str | None = None,
    config_scope: str | None = None,
) -> list[ConfigHistoryResponse]:
    history_service = _get_config_history_service(request)
    records = history_service.list_changes(
        limit=limit,
        product_id=product_id,
        config_scope=config_scope,
    )
    return [_to_config_history_response(record) for record in records]


@router.post("/admin/v1/config/rollback", response_model=ConfigRollbackResponse)
def rollback_config_change(
    payload: ConfigRollbackRequest,
    request: Request,
) -> ConfigRollbackResponse:
    history_service = _get_config_history_service(request)
    change = history_service.get_change(payload.change_id)
    if change is None:
        raise HTTPException(
            status_code=404,
            detail=f"Config change `{payload.change_id}` was not found.",
        )

    if change.product_id == "_global":
        _authorize_global_registry_write(request)
    else:
        _authorize_write_for_product(request, product_id=change.product_id)
    principal = _get_admin_principal(request)

    if change.config_scope == "retrieval_settings":
        settings_service = _get_retrieval_settings_service(request)
        current = settings_service.peek(product_id=change.product_id)
        current_snapshot = (
            _to_retrieval_snapshot_from_record(current) if current is not None else None
        )
        before = change.before if isinstance(change.before, dict) else None
        if before is None:
            settings_service.delete(product_id=change.product_id)
            rolled_state: dict[str, Any] | None = None
        else:
            rolled_record = settings_service.upsert(
                product_id=change.product_id,
                top_k=int(before["top_k"]),
                max_context_tokens=int(before["max_context_tokens"]),
                excerpt_char_limit=int(before["excerpt_char_limit"]),
                low_confidence_threshold=float(before["low_confidence_threshold"]),
                clarification_policy=str(before["clarification_policy"]),
                updated_by=principal.key_id,
            )
            rolled_state = _to_retrieval_snapshot_from_record(rolled_record)

    elif change.config_scope == "language_alias":
        registry_service = _get_registry_service(request)
        external_language_id = _resolve_alias_external_language_id(change)
        current_alias = registry_service.get_language_alias(
            product_id=change.product_id,
            external_language_id=external_language_id,
        )
        current_snapshot = (
            {
                "product_id": current_alias.product_id,
                "external_language_id": current_alias.external_language_id,
                "canonical_lang_id": current_alias.canonical_lang_id,
            }
            if current_alias is not None
            else None
        )
        before = change.before if isinstance(change.before, dict) else None
        if before is None:
            registry_service.delete_language_alias(
                product_id=change.product_id,
                external_language_id=external_language_id,
            )
            rolled_state = None
        else:
            rolled_alias = registry_service.upsert_language_alias(
                product_id=change.product_id,
                external_language_id=str(before["external_language_id"]),
                canonical_lang_id=str(before["canonical_lang_id"]),
            )
            rolled_state = {
                "product_id": rolled_alias.product_id,
                "external_language_id": rolled_alias.external_language_id,
                "canonical_lang_id": rolled_alias.canonical_lang_id,
            }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Rollback is not supported for config scope `{change.config_scope}`.",
        )

    rollback_record = history_service.record_change(
        product_id=change.product_id,
        config_scope=change.config_scope,
        config_key=change.config_key,
        action_type="rollback",
        before=current_snapshot,
        after=rolled_state,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=payload.reason,
        rollback_of_change_id=change.change_id,
    )
    return ConfigRollbackResponse(
        rolled_back_change_id=change.change_id,
        rollback_change_id=rollback_record.change_id,
        status="rolled_back",
    )
