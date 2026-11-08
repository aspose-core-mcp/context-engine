"""Admin system endpoints for auth session, health, and DR operations."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, NoReturn
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.admin import AnalyticsService
from adcs.api import readiness
from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.api.public_docs_query import (
    ListBreakingChangesRequest,
    ListBreakingChangesResponse,
    ListLatestReleaseFeaturesRequest,
    ListLatestReleaseFeaturesResponse,
    PublicQueryService,
    ReleaseFeatureCitationResponse,
    ReleaseFeatureItemResponse,
    _build_release_feature_items,
    _filter_release_feature_records,
    _resolve_latest_version,
)
from adcs.indexing.index_models import SnapshotRecord, SnapshotStatus
from adcs.indexing.snapshot_registry import SnapshotRegistry
from adcs.indexing.topology_policy import IndexTopologyPolicy
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationResult,
    SourceHugoNormalizationStatus,
)
from adcs.ingestion.source_registry import SourceRegistryService
from adcs.ops import (
    BackupOperationRecord,
    BackupOperationStatus,
    BackupRecord,
    BackupRestoreService,
    DRSmokeResult,
)
from adcs.ops.privacy import keyed_hash

router = APIRouter(
    tags=["admin-system"],
    dependencies=[Depends(require_admin_principal)],
)
public_router = APIRouter(tags=["public-system"])


class AdminSessionResponse(BaseModel):
    """Authenticated admin key session for UI role/scopes rendering."""

    key_id: str
    effective_role: str
    is_superuser: bool
    scopes: list[str]
    product_scopes: list[str]
    source: str
    owner_email: str = "system@local"


class AdminDependencyHealthResponse(BaseModel):
    """One dependency readiness entry."""

    status: str
    reason: str
    required: bool
    summary: str
    fix_plan: list[str]


class AdminSystemHealthResponse(BaseModel):
    """System health payload for admin landing page."""

    status: str
    process: str
    dependencies: dict[str, AdminDependencyHealthResponse]
    request_id: str | None
    generated_at: datetime


class AdminContentServiceHealthResponse(BaseModel):
    """Per-repository MCP content service health row."""

    repo_id: str
    product_id: str
    product_family: str
    product_family_dir: str
    source_kind: str
    git_url: str
    default_branch: str
    submodule_path: str
    layout_type: str | None
    layout_confidence: float | None
    latest_operation_id: str | None
    latest_operation_status: str | None
    latest_operation_finished_at: datetime | None
    parse_warnings_count: int
    failed_items_count: int
    active_snapshot_id: str | None
    active_snapshot_created_at: datetime | None
    active_scopes_count: int
    supported_programming_languages: list[str]
    supported_versions: list[str]
    mcp_ready: bool
    onboarding_status: str
    service_status: str
    service_status_reason: str
    indicator_color: str
    service_status_summary: str
    fix_plan: list[str]


class AdminContentServicesOverviewResponse(BaseModel):
    """High-level MCP docs/apiref service coverage and status summary."""

    total_services: int
    docs_services_total: int
    apiref_services_total: int
    docs_mcp_ready_total: int
    apiref_mcp_ready_total: int
    pending_first_ingestion_total: int
    healthy_total: int
    warning_total: int
    critical_total: int
    unknown_total: int
    services: list[AdminContentServiceHealthResponse]
    request_id: str | None
    generated_at: datetime


class PublicStatusResponse(BaseModel):
    """Public-facing status payload without admin-only controls."""

    status: str
    process: str
    dependencies: dict[str, AdminDependencyHealthResponse]
    total_services: int
    docs_services_total: int
    apiref_services_total: int
    docs_mcp_ready_total: int
    apiref_mcp_ready_total: int
    pending_first_ingestion_total: int
    healthy_total: int
    warning_total: int
    critical_total: int
    unknown_total: int
    filters: dict[str, str | None]
    services: list[AdminContentServiceHealthResponse]
    request_id: str | None
    generated_at: datetime


class PublicMCPClientConfigSnippetResponse(BaseModel):
    """Ready-to-paste MCP client snippet for one IDE or CLI."""

    client_id: str
    display_name: str
    config_path_hint: str
    format: str
    snippet: str
    instructions: list[str]


class PublicMCPConfigExportResponse(BaseModel):
    """Collection of MCP client configs for popular tools."""

    server_name: str
    product_id: str | None
    transport: str
    mcp_url: str
    sample_prompt: str
    clients: list[PublicMCPClientConfigSnippetResponse]
    generated_at: datetime


class PublicSnippetItemResponse(BaseModel):
    """Public snippet explorer item."""

    snippet_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    doc_type: str
    title: str
    canonical_url: str
    section_anchor: str
    symbol_fqn: str | None
    snippet_language: str
    code: str
    source_revision: str
    repo_id: str


class PublicSnippetExplorerResponse(BaseModel):
    """Public snippet explorer response."""

    product_id: str | None
    programming_language: str | None
    version: str | None
    source_kind: str | None
    total_snippets: int
    items: list[PublicSnippetItemResponse]
    generated_at: datetime


class PublicMCPSelfTestCheckResponse(BaseModel):
    """One public self-test check row."""

    check_id: str
    title: str
    status: str
    summary: str
    details: list[str]


class PublicMCPSelfTestResponse(BaseModel):
    """Self-test response for external MCP onboarding."""

    product_id: str
    programming_language: str | None
    client_id: str
    transport: str
    status: str
    status_summary: str
    docs_ready_count: int
    apiref_ready_count: int
    total_ready_services: int
    total_registered_services: int
    snippet_count: int
    available_programming_languages: list[str]
    available_versions: list[str]
    checks: list[PublicMCPSelfTestCheckResponse]
    fix_plan: list[str]
    config_export_url: str
    status_page_url: str
    mcp_url: str
    sample_prompt: str
    generated_at: datetime


class PublicReleaseFeaturePreviewResponse(BaseModel):
    """Preview of one latest release feature or migration note."""

    kind: str
    summary: str
    symbol_fqn: str | None
    version: str
    source_kind: str
    canonical_url: str
    section_anchor: str


class PublicFreshnessServiceScopeResponse(BaseModel):
    """Freshness view for one source kind scope."""

    source_kind: str
    mcp_ready: bool
    latest_version: str | None
    latest_source_revision: str | None
    latest_snapshot_id: str | None
    latest_snapshot_created_at: datetime | None
    indexed_chunks_count: int


class PublicReleaseFreshnessResponse(BaseModel):
    """Public freshness and release visibility payload."""

    product_id: str
    programming_language: str | None
    requested_version: str | None
    resolved_version: str | None
    newest_available_version: str | None
    available_versions: list[str]
    latest_active_snapshot_at: datetime | None
    services: list[PublicFreshnessServiceScopeResponse]
    release_features: list[PublicReleaseFeaturePreviewResponse]
    status_summary: str
    generated_at: datetime


class PublicContentTriageGapResponse(BaseModel):
    """One stale/no-index/no-snippet triage gap."""

    gap_id: str
    severity: str
    signal_type: str
    product_id: str
    repo_id: str
    source_kind: str
    mcp_ready: bool
    indexed_chunks_count: int
    executable_snippets_count: int
    active_snapshot_created_at: datetime | None
    stale_days: int | None
    summary: str
    service_status: str
    service_status_reason: str
    fix_plan: list[str]


class PublicContentTriageResponse(BaseModel):
    """Public/admin content-triage response."""

    filters: dict[str, str | None]
    stale_after_days: int
    total_items: int
    critical_total: int
    warning_total: int
    info_total: int
    status_summary: str
    items: list[PublicContentTriageGapResponse]
    generated_at: datetime


class PublicStarterPackItemResponse(BaseModel):
    """One ready-to-copy onboarding starter pack."""

    pack_id: str
    client_id: str
    display_name: str
    title: str
    description: str
    config_path_hint: str
    config_format: str
    config_snippet: str
    starter_prompt: str
    first_queries: list[str]
    starter_checklist: list[str]
    bundle_markdown: str
    download_filename: str


class PublicStarterPackResponse(BaseModel):
    """Collection of onboarding starter packs."""

    product_id: str | None
    programming_language: str | None
    transport: str
    packs: list[PublicStarterPackItemResponse]
    generated_at: datetime


class PublicCoverageSourceKindStateResponse(BaseModel):
    """Coverage state for one source kind within a product/language surface."""

    source_kind: str
    registered: bool
    ready: bool
    repo_ids: list[str]
    active_snapshot_ids: list[str]
    active_versions: list[str]
    latest_stable_visible: bool
    supported_versions: list[str]
    service_statuses: list[str]
    service_reasons: list[str]


class PublicCoverageSurfaceResponse(BaseModel):
    """Coverage status for one product/programming-language surface."""

    surface_id: str
    product_id: str
    product_name: str
    product_family: str
    programming_language: str
    status: str
    onboarding_priority: str
    registered_source_kinds: list[str]
    ready_source_kinds: list[str]
    latest_stable_visible: bool
    executable_snippets_count: int
    expected_versions: list[str]
    gap_badges: list[str]
    summary: str
    source_kinds: list[PublicCoverageSourceKindStateResponse]


class PublicCoverageProductResponse(BaseModel):
    """Coverage roll-up for one product across all tracked surfaces."""

    product_id: str
    product_name: str
    product_family: str
    product_family_dirs: list[str]
    repo_ids: list[str]
    registered_source_kinds: list[str]
    expected_programming_languages: list[str]
    ready_surfaces_total: int
    partial_surfaces_total: int
    registered_only_surfaces_total: int
    high_priority_surfaces_total: int
    medium_priority_surfaces_total: int
    low_priority_surfaces_total: int
    surfaces: list[PublicCoverageSurfaceResponse]


class PublicCoverageGapTrackerResponse(BaseModel):
    """Coverage gap tracker response for multi-product onboarding planning."""

    filters: dict[str, str | None]
    products_total: int
    surfaces_total: int
    ready_surfaces_total: int
    partial_surfaces_total: int
    registered_only_surfaces_total: int
    high_priority_surfaces_total: int
    medium_priority_surfaces_total: int
    low_priority_surfaces_total: int
    status_summary: str
    products: list[PublicCoverageProductResponse]
    generated_at: datetime


class PublicCapabilityActionResponse(BaseModel):
    """One deep-link action for a capability row."""

    label: str
    href: str


class PublicCapabilityItemResponse(BaseModel):
    """Capability readiness summary for one product/language surface."""

    capability_id: str
    product_id: str
    product_name: str
    product_family: str
    programming_language: str
    status: str
    onboarding_priority: str
    latest_stable_visible: bool
    freshness_label: str | None
    resolved_version: str | None
    newest_available_version: str | None
    executable_snippets_count: int
    registered_source_kinds: list[str]
    ready_source_kinds: list[str]
    gap_badges: list[str]
    summary: str
    snippet_titles: list[str]
    actions: list[PublicCapabilityActionResponse]


class PublicCapabilityExplorerResponse(BaseModel):
    """Public capability explorer response for product adoption workflows."""

    filters: dict[str, str | None]
    products_total: int
    capabilities_total: int
    ready_total: int
    partial_total: int
    gap_total: int
    available_programming_languages: list[str]
    available_source_kinds: list[str]
    status_summary: str
    items: list[PublicCapabilityItemResponse]
    generated_at: datetime


class PublicCoverageNavigatorCellResponse(BaseModel):
    """Compact readiness cell for one source kind inside the public coverage navigator."""

    source_kind: str
    status: str
    active_versions: list[str]
    service_reason: str | None = None


class PublicCoverageNavigatorSurfaceResponse(BaseModel):
    """Compact product/language readiness row for the public coverage navigator."""

    surface_id: str
    product_id: str
    product_name: str
    product_family: str
    programming_language: str
    overall_status: str
    onboarding_priority: str
    latest_visible_versions: list[str]
    executable_snippets_count: int
    gap_badges: list[str]
    summary: str
    remediation: list[str]
    cells: list[PublicCoverageNavigatorCellResponse]
    actions: list[PublicCapabilityActionResponse]


class PublicCoverageNavigatorResponse(BaseModel):
    """Compact coverage navigator for public MCP scope readiness and next actions."""

    filters: dict[str, str | None]
    products_total: int
    surfaces_total: int
    ready_total: int
    partial_total: int
    registered_only_total: int
    available_products: list[str]
    available_programming_languages: list[str]
    available_source_kinds: list[str]
    available_versions: list[str]
    status_summary: str
    surfaces: list[PublicCoverageNavigatorSurfaceResponse]
    generated_at: datetime


class PublicTrustSignalScorecardResponse(BaseModel):
    """One public trust scorecard backed by explicit evidence links."""

    signal_id: str
    title: str
    status: str
    score: int
    summary: str
    evidence: list[str]
    actions: list[PublicCapabilityActionResponse]


class PublicTrustSignalsBoardResponse(BaseModel):
    """Public trust-signal board for one selected MCP scope."""

    product_id: str
    programming_language: str | None
    requested_version: str | None
    resolved_version: str | None
    trust_posture: str
    strong_total: int
    watch_total: int
    weak_total: int
    status_summary: str
    explainability: list[str]
    scorecards: list[PublicTrustSignalScorecardResponse]
    generated_at: datetime


class PublicScopeCompareSummaryResponse(BaseModel):
    """Compact summary for one side of the public scope-compare board."""

    product_id: str
    programming_language: str | None
    requested_version: str | None
    resolved_version: str | None
    trust_posture: str
    average_signal_score: float
    executable_snippets_count: int
    summary: str


class PublicScopeCompareMetricResponse(BaseModel):
    """One explainable side-by-side metric inside the scope compare board."""

    metric_id: str
    title: str
    preferred_side: str
    summary: str
    left_score: float
    right_score: float
    left_status: str
    right_status: str
    left_evidence: list[str]
    right_evidence: list[str]
    left_href: str
    right_href: str


class PublicScopeCompareBoardResponse(BaseModel):
    """Public side-by-side comparison of two MCP scopes."""

    preferred_side: str
    status_summary: str
    explainability: list[str]
    left_scope: PublicScopeCompareSummaryResponse
    right_scope: PublicScopeCompareSummaryResponse
    metrics: list[PublicScopeCompareMetricResponse]
    generated_at: datetime


class PublicTroubleshootingActionResponse(BaseModel):
    """Actionable deep link from one troubleshooting path."""

    label: str
    href: str


class PublicTroubleshootingPathResponse(BaseModel):
    """One troubleshooting path for a public MCP issue."""

    path_id: str
    title: str
    severity: str
    summary: str
    match_reason: str
    evidence: list[str]
    fix_plan: list[str]
    copy_block_label: str | None = None
    copy_block_text: str | None = None
    actions: list[PublicTroubleshootingActionResponse]


class PublicTroubleshootingResponse(BaseModel):
    """Public troubleshooting overview for onboarding and retrieval faults."""

    filters: dict[str, str | None]
    status_summary: str
    self_test_status: str
    critical_gap_total: int
    warning_gap_total: int
    request_diagnostics: dict[str, str | int | float | None]
    paths: list[PublicTroubleshootingPathResponse]
    generated_at: datetime


class PublicReleaseAdoptionRangeResponse(BaseModel):
    """One upgrade range candidate for release adoption planning."""

    range_id: str
    from_version: str
    to_version: str
    breaking_changes_total: int
    status: str
    summary: str


class PublicReleaseAdoptionResponse(BaseModel):
    """Public release adoption desk payload."""

    product_id: str
    programming_language: str | None
    requested_version: str | None
    resolved_version: str | None
    newest_available_version: str | None
    recommended_from_version: str | None
    recommended_to_version: str | None
    status: str
    freshness_label: str
    status_summary: str
    latest_active_snapshot_at: datetime | None
    migration_checklist: list[str]
    upgrade_prompt: str
    fix_plan: list[str]
    compare_ranges: list[PublicReleaseAdoptionRangeResponse]
    latest_release: ListLatestReleaseFeaturesResponse
    breaking_changes: ListBreakingChangesResponse
    actions: list[PublicTroubleshootingActionResponse]
    generated_at: datetime


class PublicUseCaseClientNoteResponse(BaseModel):
    """Client-specific guidance for one gallery card."""

    client_id: str
    note: str


class PublicUseCaseEvidenceResponse(BaseModel):
    """Live evidence link attached to a use-case card."""

    evidence_type: str
    title: str
    canonical_url: str
    section_anchor: str
    snippet_id: str | None = None


class PublicUseCaseItemResponse(BaseModel):
    """One curated public use-case card."""

    use_case_id: str
    category: str
    title: str
    status: str
    summary: str
    starter_prompt: str
    starter_query: str
    recommended_journey_id: str | None = None
    client_notes: list[PublicUseCaseClientNoteResponse]
    evidence: list[PublicUseCaseEvidenceResponse]
    actions: list[PublicTroubleshootingActionResponse]


class PublicUseCaseGalleryResponse(BaseModel):
    """Curated public gallery for high-value MCP-first scenarios."""

    filters: dict[str, str | None]
    status_summary: str
    items: list[PublicUseCaseItemResponse]
    generated_at: datetime


class TopologyQdrantResponse(BaseModel):
    shard_number: int
    replication_factor: int
    write_consistency_factor: int


class TopologyOpenSearchResponse(BaseModel):
    number_of_shards: int
    number_of_replicas: int
    refresh_interval: str


class TopologyCompactionResponse(BaseModel):
    enabled: bool
    max_inactive_snapshots_per_scope: int
    stale_snapshot_retention_days: int


class TopologyStorageTieringResponse(BaseModel):
    latest_stable_tier: str
    archive_tier: str


class TopologyPolicyResponse(BaseModel):
    profile: str
    persistence_backend: str
    retrieval_backend: str
    config_path: str
    qdrant: TopologyQdrantResponse
    opensearch: TopologyOpenSearchResponse
    compaction: TopologyCompactionResponse
    storage_tiering: TopologyStorageTieringResponse
    summary: str
    generated_at: datetime


class AdminBackupTriggerRequest(BaseModel):
    """Backup trigger payload."""

    scope: str = "full"
    product_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in {"full", "product", "analytics"}:
            raise ValueError("scope must be one of: full, product, analytics.")
        return normalized

    @field_validator("product_id")
    @classmethod
    def _validate_product_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("product_id must not be empty.")
        return normalized


class AdminRestoreTriggerRequest(BaseModel):
    """Restore trigger payload."""

    validate_only: bool = False
    reason: str | None = Field(default=None, max_length=500)


class AdminBackupRecordResponse(BaseModel):
    """Backup manifest response."""

    backup_id: str
    scope: str
    product_id: str | None
    created_at: datetime
    snapshot_root: str
    manifest_path: str
    included_paths: list[str]
    copied_files_count: int
    external_components: dict[str, str]


class AdminBackupOperationResponse(BaseModel):
    """Backup/restore operation response."""

    operation_id: str
    operation_type: str
    status: BackupOperationStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    requested_by: str | None
    request_id: str | None
    reason: str | None
    scope: str
    product_id: str | None
    backup_id: str | None
    target_backup_id: str | None
    validate_only: bool
    error_reason: str | None
    restored_files_count: int
    logs: list[str]


class AdminDRSmokeResponse(BaseModel):
    """DR smoke response."""

    status: str
    backup_operation_id: str | None
    restore_operation_id: str | None
    backup_id: str | None
    details: str
    request_id: str | None
    generated_at: datetime


class AdminDRSmokeTriggerRequest(BaseModel):
    """DR smoke trigger payload."""

    reason: str | None = Field(default=None, max_length=500)


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


def _raise_structured_http_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> NoReturn:
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


def _backup_restore_service(request: Request) -> BackupRestoreService:
    service = getattr(request.app.state, "backup_restore_service", None)
    if not isinstance(service, BackupRestoreService):
        msg = "Backup restore service is not configured."
        raise RuntimeError(msg)
    return service


def _source_registry_service(request: Request) -> SourceRegistryService:
    service = getattr(request.app.state, "source_registry_service", None)
    if not isinstance(service, SourceRegistryService):
        msg = "Source registry service is not configured."
        raise RuntimeError(msg)
    return service


def _source_hugo_orchestrator(
    request: Request,
) -> SourceHugoNormalizationOrchestrationService | None:
    orchestrator = getattr(request.app.state, "source_hugo_normalization_orchestrator", None)
    if isinstance(orchestrator, SourceHugoNormalizationOrchestrationService):
        return orchestrator
    return None


def _snapshot_registry(request: Request) -> SnapshotRegistry:
    registry = getattr(request.app.state, "snapshot_registry", None)
    if registry is None:
        msg = "Snapshot registry is not configured."
        raise RuntimeError(msg)
    return registry


def _resolve_auth_target_product_ids(
    *,
    principal: AdminKeyPrincipal,
    product_id: str | None,
    request: Request,
) -> tuple[str, ...]:
    if product_id is None:
        if principal.is_superuser:
            return ()
        _raise_structured_http_error(
            request,
            status_code=403,
            code="FORBIDDEN",
            message="Global backup/restore operations require superuser key.",
        )
    assert product_id is not None
    return (product_id,)


def _authorize_backup_mutation(
    *,
    request: Request,
    principal: AdminKeyPrincipal,
    target_product_ids: tuple[str, ...],
    destructive: bool = False,
) -> None:
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=target_product_ids,
            destructive=destructive,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _to_backup_response(backup: BackupRecord) -> AdminBackupRecordResponse:
    return AdminBackupRecordResponse(
        backup_id=backup.backup_id,
        scope=backup.scope,
        product_id=backup.product_id,
        created_at=backup.created_at,
        snapshot_root=backup.snapshot_root,
        manifest_path=backup.manifest_path,
        included_paths=list(backup.included_paths),
        copied_files_count=backup.copied_files_count,
        external_components=dict(backup.external_components),
    )


def _to_operation_response(operation: BackupOperationRecord) -> AdminBackupOperationResponse:
    return AdminBackupOperationResponse(
        operation_id=operation.operation_id,
        operation_type=operation.operation_type.value,
        status=operation.status,
        created_at=operation.created_at,
        started_at=operation.started_at,
        finished_at=operation.finished_at,
        requested_by=operation.requested_by,
        request_id=operation.request_id,
        reason=operation.reason,
        scope=operation.scope,
        product_id=operation.product_id,
        backup_id=operation.backup_id,
        target_backup_id=operation.target_backup_id,
        validate_only=operation.validate_only,
        error_reason=operation.error_reason,
        restored_files_count=operation.restored_files_count,
        logs=list(operation.logs),
    )


def _service_status_from_signals(
    *,
    latest_operation: SourceHugoNormalizationOperation | None,
    latest_result: SourceHugoNormalizationResult | None,
    active_snapshot: SnapshotRecord | None,
) -> tuple[str, str, str]:
    if latest_operation is not None:
        if latest_operation.status in {
            SourceHugoNormalizationStatus.RUNNING,
            SourceHugoNormalizationStatus.QUEUED,
            SourceHugoNormalizationStatus.CANCEL_REQUESTED,
            SourceHugoNormalizationStatus.RETRY_SCHEDULED,
        }:
            return ("warning", "ingestion_in_progress", "yellow")
        if latest_operation.status in {
            SourceHugoNormalizationStatus.FAILED,
            SourceHugoNormalizationStatus.CANCELLED,
        }:
            return ("critical", "latest_ingestion_failed", "red")
        if latest_result is not None and latest_result.failed_items:
            return ("warning", "latest_ingestion_has_failed_items", "yellow")
        if latest_result is not None and latest_result.parse_warnings_count > 0:
            return ("warning", "latest_ingestion_has_parse_warnings", "yellow")

    if active_snapshot is not None and active_snapshot.status is SnapshotStatus.ACTIVE:
        return ("healthy", "active_snapshot_available", "green")
    if (
        latest_operation is not None
        and latest_operation.status is SourceHugoNormalizationStatus.COMPLETED
    ):
        return ("warning", "completed_without_active_snapshot", "yellow")
    return ("unknown", "no_recent_runtime_signal", "gray")


def _build_dependency_health(
    request: Request,
) -> tuple[str, dict[str, AdminDependencyHealthResponse]]:
    settings = request.app.state.settings
    adapter_modes = getattr(request.app.state, "adapter_modes", None)
    readiness_results = readiness.check_dependencies(settings, adapter_modes=adapter_modes)
    required_dependencies = readiness.resolve_required_dependencies(adapter_modes)
    _, readiness_payload = readiness.build_readiness_response(readiness_results)
    dependencies_payload = readiness_payload.get("dependencies")
    if not isinstance(dependencies_payload, dict):
        dependencies_payload = {}
    dependencies = {
        dependency_name: AdminDependencyHealthResponse(
            status=str(entry.get("status", "unknown")),
            reason=str(entry.get("reason", "unknown")),
            required=required_dependencies.get(dependency_name, True),
            summary=_build_dependency_summary(
                dependency_name=dependency_name,
                status=str(entry.get("status", "unknown")),
                reason=str(entry.get("reason", "unknown")),
                required=required_dependencies.get(dependency_name, True),
            ),
            fix_plan=_build_dependency_fix_plan(
                dependency_name=dependency_name,
                status=str(entry.get("status", "unknown")),
                reason=str(entry.get("reason", "unknown")),
                required=required_dependencies.get(dependency_name, True),
            ),
        )
        for dependency_name, entry in dependencies_payload.items()
        if isinstance(entry, dict)
    }
    return str(readiness_payload.get("status", "not_ready")), dependencies


def _build_dependency_summary(
    *,
    dependency_name: str,
    status: str,
    reason: str,
    required: bool,
) -> str:
    if status == "ready" and not required:
        return (
            f"{dependency_name} is not required for the current runtime topology, so readiness "
            "does not depend on it."
        )
    if status == "ready":
        return f"{dependency_name} connectivity probe succeeded."
    return f"{dependency_name} probe failed or degraded: {reason}."


def _build_dependency_fix_plan(
    *,
    dependency_name: str,
    status: str,
    reason: str,
    required: bool,
) -> list[str]:
    if status == "ready":
        if not required:
            return [
                "No action required for the current runtime profile.",
                "If you expect this dependency to be used, switch the runtime adapters "
                "and re-run readiness.",
            ]
        return [
            "No immediate action is required.",
            "Keep monitoring health checks and traces for regressions.",
        ]

    common_tail = [
        "Re-run `/readyz` or refresh the Health page after remediation.",
        "Correlate the failure with request logs, traces, and container health "
        "if the problem persists.",
    ]
    dependency_specific: dict[str, list[str]] = {
        "postgres": [
            "Verify the PostgreSQL host, port, and credentials configured in ADCS settings.",
            "Check that the PostgreSQL service/container is reachable on the expected network.",
        ],
        "redis": [
            "Verify the Redis/Valkey URL and password used by ADCS.",
            "Check that the Redis service is running and accepts connections "
            "from the ADCS runtime.",
        ],
        "qdrant": [
            "Verify the Qdrant endpoint and ensure the vector service finished startup.",
            "Check whether the retrieval backend is intentionally using memory "
            "mode instead of Qdrant.",
        ],
        "opensearch": [
            "Verify the OpenSearch endpoint and cluster startup state.",
            "Check indexer/retrieval configuration and confirm OpenSearch is "
            "reachable from the ADCS runtime.",
        ],
    }
    plan = list(dependency_specific.get(dependency_name, []))
    if "missing host" in reason:
        plan.insert(
            0,
            "Fix the configured endpoint first: the dependency URL is missing a valid host.",
        )
    return plan + common_tail


class _OpMetaProxy:
    """Lightweight proxy mimicking SourceHugoNormalizationOperation from metadata."""

    __slots__ = ("operation_id", "status", "finished_at", "repo_ids", "results")

    def __init__(self, scalars: dict[str, Any]) -> None:
        self.operation_id: str = scalars.get("operation_id", "")
        raw_status = scalars.get("status", "completed")
        try:
            self.status = SourceHugoNormalizationStatus(raw_status)
        except ValueError:
            self.status = SourceHugoNormalizationStatus.COMPLETED
        self.finished_at = scalars.get("finished_at")
        self.repo_ids: tuple[str, ...] = tuple(scalars.get("repo_ids", []))
        self.results: tuple[Any, ...] = ()


class _ResultMetaProxy:
    """Lightweight proxy mimicking SourceHugoNormalizationResult from metadata."""

    __slots__ = ("repo_id", "parse_warnings_count", "failed_items")

    def __init__(self, result_scope: dict[str, Any]) -> None:
        self.repo_id: str = result_scope.get("repo_id", "")
        self.parse_warnings_count: int = int(result_scope.get("parse_warnings_count", 0))
        failed_count = int(result_scope.get("failed_items_count", 0))
        # Create stub list of correct length for len() checks.
        self.failed_items: list[Any] = [None] * failed_count


def _collect_content_service_rows(
    request: Request,
    *,
    product_id: str | None = None,
    repo_id: str | None = None,
) -> list[AdminContentServiceHealthResponse]:
    repositories = _source_registry_service(request).list_repositories()
    orchestrator = _source_hugo_orchestrator(request)
    snapshot_registry = _snapshot_registry(request)
    snapshots = snapshot_registry.list_snapshots()

    # Build lightweight operation/result lookup from metadata envelopes
    # instead of loading full multi-GB operation JSON files.
    _latest_op_meta_by_repo: dict[str, dict[str, Any]] = {}
    _latest_result_meta_by_repo: dict[str, dict[str, Any]] = {}

    if orchestrator is not None:
        for envelope in orchestrator.list_operation_metadata(limit=200):
            scalars = envelope.record_scalars
            repo_ids: list[str] = scalars.get("repo_ids", [])
            result_scope: list[dict[str, Any]] = scalars.get("_result_scope", [])
            result_scope_by_repo = {
                rs.get("repo_id", ""): rs for rs in result_scope
            }
            for current_repo_id in repo_ids:
                if current_repo_id in _latest_op_meta_by_repo:
                    continue
                _latest_op_meta_by_repo[current_repo_id] = scalars
                rs_meta = result_scope_by_repo.get(current_repo_id)
                if rs_meta is not None:
                    _latest_result_meta_by_repo[current_repo_id] = rs_meta

    normalized_product_id = product_id.strip().casefold() if product_id else None
    normalized_repo_id = repo_id.strip().casefold() if repo_id else None
    services: list[AdminContentServiceHealthResponse] = []
    for repository in repositories:
        if normalized_product_id and repository.product_id.casefold() != normalized_product_id:
            continue
        if normalized_repo_id and repository.repo_id.casefold() != normalized_repo_id:
            continue

        matching_snapshots = [
            snapshot
            for snapshot in snapshots
            if snapshot.product_id == repository.product_id
            and snapshot.source_kind == repository.source_kind
        ]
        matching_active_snapshots = [
            snapshot
            for snapshot in matching_snapshots
            if snapshot.status is SnapshotStatus.ACTIVE
        ]
        active_snapshot = (
            max(matching_active_snapshots, key=lambda item: item.created_at)
            if matching_active_snapshots
            else None
        )
        # Build lightweight proxies from metadata for status computation.
        # The proxies structurally mimic SourceHugoNormalizationOperation /
        # SourceHugoNormalizationResult for the attribute subset consumed by
        # _service_status_from_signals and _build_content_service_fix_plan.
        op_meta = _latest_op_meta_by_repo.get(repository.repo_id)
        result_meta = _latest_result_meta_by_repo.get(repository.repo_id)
        latest_operation: SourceHugoNormalizationOperation | None = (
            _OpMetaProxy(op_meta) if op_meta else None  # type: ignore[assignment]
        )
        latest_result: SourceHugoNormalizationResult | None = (
            _ResultMetaProxy(result_meta) if result_meta else None  # type: ignore[assignment]
        )
        service_status, status_reason, indicator_color = _service_status_from_signals(
            latest_operation=latest_operation,
            latest_result=latest_result,
            active_snapshot=active_snapshot,
        )
        service_status_summary, fix_plan = _build_content_service_fix_plan(
            latest_operation=latest_operation,
            latest_result=latest_result,
            active_snapshot=active_snapshot,
            status_reason=status_reason,
        )

        layout_payload = (
            repository.layout_detection if isinstance(repository.layout_detection, dict) else {}
        )
        supported_programming_languages = sorted(
            {snapshot.programming_language for snapshot in matching_snapshots}
        )
        supported_versions = sorted({snapshot.version for snapshot in matching_snapshots})
        services.append(
            AdminContentServiceHealthResponse(
                repo_id=repository.repo_id,
                product_id=repository.product_id,
                product_family=repository.product_family,
                product_family_dir=repository.product_family_dir,
                source_kind=repository.source_kind,
                git_url=repository.git.url,
                default_branch=repository.git.default_branch,
                submodule_path=repository.git.submodule_path.as_posix(),
                layout_type=(
                    str(layout_payload.get("layout_type"))
                    if layout_payload.get("layout_type") is not None
                    else None
                ),
                layout_confidence=(
                    float(layout_payload["confidence"])
                    if isinstance(layout_payload.get("confidence"), int | float)
                    else None
                ),
                latest_operation_id=(
                    latest_operation.operation_id if latest_operation is not None else None
                ),
                latest_operation_status=(
                    latest_operation.status.value if latest_operation is not None else None
                ),
                latest_operation_finished_at=(
                    latest_operation.finished_at if latest_operation is not None else None
                ),
                parse_warnings_count=(
                    latest_result.parse_warnings_count if latest_result is not None else 0
                ),
                failed_items_count=(
                    len(latest_result.failed_items) if latest_result is not None else 0
                ),
                active_snapshot_id=(
                    active_snapshot.snapshot_id if active_snapshot is not None else None
                ),
                active_snapshot_created_at=(
                    active_snapshot.created_at if active_snapshot is not None else None
                ),
                active_scopes_count=len(matching_active_snapshots),
                supported_programming_languages=supported_programming_languages,
                supported_versions=supported_versions,
                mcp_ready=active_snapshot is not None,
                onboarding_status=(
                    "active" if active_snapshot is not None
                    else "ingested" if latest_operation is not None
                    else "pending_first_ingestion"
                ),
                service_status=service_status,
                service_status_reason=status_reason,
                indicator_color=indicator_color,
                service_status_summary=service_status_summary,
                fix_plan=fix_plan,
            )
        )
    return sorted(services, key=lambda item: (item.product_id, item.source_kind, item.repo_id))


def _build_content_service_fix_plan(
    *,
    latest_operation: SourceHugoNormalizationOperation | None,
    latest_result: SourceHugoNormalizationResult | None,
    active_snapshot: SnapshotRecord | None,
    status_reason: str,
) -> tuple[str, list[str]]:
    if active_snapshot is not None and status_reason == "active_snapshot_available":
        return (
            "Active snapshot is published and the repository is considered MCP-ready.",
            [
                "No immediate action is required.",
                "Refresh the service after the next ingestion if you expect newer content.",
            ],
        )
    if status_reason == "ingestion_in_progress":
        return (
            "An ingestion job is still running for this repository.",
            [
                "Wait for the current ingestion job to finish.",
                "Inspect the latest job logs if it remains queued/running "
                "longer than expected.",
                "Run Trigger Publish after a validate-only run if the latest "
                "job did not activate a snapshot.",
            ],
        )
    if status_reason == "latest_ingestion_failed":
        return (
            "The latest ingestion did not complete successfully, so MCP cannot "
            "trust the resulting content.",
            [
                "Open Ingestion Jobs and inspect failed items for this repository.",
                "Fix the parser/layout/conversion issue indicated in the latest job logs.",
                "Re-run Validate-Only first, then Trigger Publish after the "
                "repository passes cleanly.",
            ],
        )
    if status_reason == "latest_ingestion_has_failed_items":
        return (
            "The latest ingestion completed with failed items, so some content "
            "may be missing or invalid.",
            [
                "Review failed items and markdown parse issues in the latest job output.",
                "Correct the affected source files or improve the conversion prompt/rules.",
                "Re-run Validate-Only before publishing another snapshot.",
            ],
        )
    if status_reason == "latest_ingestion_has_parse_warnings":
        return (
            "The latest ingestion completed with parse warnings that may reduce retrieval quality.",
            [
                "Review parser warnings and chunk previews in the review workspace.",
                "Decide whether the warnings are acceptable for publish or "
                "require source/conversion fixes.",
                "Publish a new snapshot only after warning severity is understood.",
            ],
        )
    if status_reason == "completed_without_active_snapshot":
        return (
            "Content was processed, but no active snapshot was promoted for runtime serving.",
            [
                "Run Trigger Publish for this repository to activate a snapshot.",
                "If publish is blocked, inspect quality gate output and resolve blocking checks.",
                "Verify the active snapshot appears in the Snapshots panel after publish.",
            ],
        )
    if status_reason == "no_recent_runtime_signal":
        return (
            "No recent runtime signal exists yet, so the service cannot prove MCP readiness.",
            [
                "Run layout detection and Validate-Only if this repository was onboarded recently.",
                "Publish an active snapshot if none exists yet for this source kind.",
                "Run a public query or smoke test and verify backend health to "
                "confirm runtime traffic.",
            ],
        )
    if latest_result is not None and latest_result.parse_warnings_count > 0:
        return (
            "Latest result contains warnings that should be reviewed before relying on MCP output.",
            [
                "Inspect parse warnings and chunk previews in the review workspace.",
                "Re-run validation after correcting the underlying source or conversion issue.",
            ],
        )
    return (
        "Inspect the latest ingestion run, active snapshot state, and runtime "
        "health to restore readiness.",
        [
            "Open Ingestion Jobs and review the latest repository run.",
            "Check whether an active snapshot exists for the required source kind.",
            "Verify runtime dependencies and recent MCP traffic after remediation.",
        ],
    )


def _build_content_services_overview(
    request: Request,
    *,
    product_id: str | None = None,
    repo_id: str | None = None,
) -> AdminContentServicesOverviewResponse:
    services = _collect_content_service_rows(request, product_id=product_id, repo_id=repo_id)
    docs_services = [service for service in services if service.source_kind == "docs"]
    apiref_services = [service for service in services if service.source_kind == "apiref"]
    return AdminContentServicesOverviewResponse(
        total_services=len(services),
        docs_services_total=len(docs_services),
        apiref_services_total=len(apiref_services),
        docs_mcp_ready_total=sum(1 for service in docs_services if service.mcp_ready),
        apiref_mcp_ready_total=sum(1 for service in apiref_services if service.mcp_ready),
        pending_first_ingestion_total=sum(
            1 for service in services if service.onboarding_status == "pending_first_ingestion"
        ),
        healthy_total=sum(1 for service in services if service.service_status == "healthy"),
        warning_total=sum(1 for service in services if service.service_status == "warning"),
        critical_total=sum(1 for service in services if service.service_status == "critical"),
        unknown_total=sum(1 for service in services if service.service_status == "unknown"),
        services=services,
        request_id=getattr(request.state, "request_id", None),
        generated_at=datetime.now(tz=UTC),
    )


def _build_topology_policy_response(request: Request) -> TopologyPolicyResponse:
    topology_policy = getattr(request.app.state, "index_topology_policy", None)
    if not isinstance(topology_policy, IndexTopologyPolicy):
        msg = "Index topology policy is not configured."
        raise RuntimeError(msg)

    adapter_modes = getattr(request.app.state, "adapter_modes", None)
    settings = request.app.state.settings
    persistence_backend = (
        adapter_modes.persistence_backend.value if adapter_modes is not None else "unknown"
    )
    retrieval_backend = (
        adapter_modes.retrieval_backend.value if adapter_modes is not None else "unknown"
    )
    summary = (
        f"profile={topology_policy.profile}; persistence={persistence_backend}; "
        f"retrieval={retrieval_backend}; "
        f"qdrant={topology_policy.qdrant.shard_number} shard(s)/"
        f"{topology_policy.qdrant.replication_factor} replica(s); "
        f"opensearch={topology_policy.opensearch.number_of_shards} shard(s)/"
        f"{topology_policy.opensearch.number_of_replicas} replica(s); "
        f"compaction={'on' if topology_policy.compaction.enabled else 'off'}"
    )
    return TopologyPolicyResponse(
        profile=topology_policy.profile,
        persistence_backend=persistence_backend,
        retrieval_backend=retrieval_backend,
        config_path=str(settings.index_topology_policy_config_path),
        qdrant=TopologyQdrantResponse(
            shard_number=topology_policy.qdrant.shard_number,
            replication_factor=topology_policy.qdrant.replication_factor,
            write_consistency_factor=topology_policy.qdrant.write_consistency_factor,
        ),
        opensearch=TopologyOpenSearchResponse(
            number_of_shards=topology_policy.opensearch.number_of_shards,
            number_of_replicas=topology_policy.opensearch.number_of_replicas,
            refresh_interval=topology_policy.opensearch.refresh_interval,
        ),
        compaction=TopologyCompactionResponse(
            enabled=topology_policy.compaction.enabled,
            max_inactive_snapshots_per_scope=(
                topology_policy.compaction.max_inactive_snapshots_per_scope
            ),
            stale_snapshot_retention_days=(
                topology_policy.compaction.stale_snapshot_retention_days
            ),
        ),
        storage_tiering=TopologyStorageTieringResponse(
            latest_stable_tier=topology_policy.storage_tiering.latest_stable_tier,
            archive_tier=topology_policy.storage_tiering.archive_tier,
        ),
        summary=summary,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_mcp_config_export(
    request: Request,
    *,
    product_id: str | None,
    transport: str,
) -> PublicMCPConfigExportResponse:
    normalized_transport = transport.strip().casefold()
    transport_paths = {
        "streamable-http": "/mcp/v1/streamable-http",
        "sse": "/mcp/v1/sse",
    }
    if normalized_transport not in transport_paths:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_TRANSPORT",
                    "message": "transport must be `streamable-http` or `sse`.",
                    "details": {"transport": transport},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    base_url = str(request.base_url).rstrip("/")
    mcp_url = f"{base_url}{transport_paths[normalized_transport]}"
    normalized_product_id = product_id.strip() if product_id else None
    server_name = (
        normalized_product_id.replace(".", "-")
        if normalized_product_id
        else "adcs-public-docs"
    )
    prompt_product = normalized_product_id or "Aspose.OCR"
    sample_prompt = (
        f"Use MCP server `{server_name}`. First resolve product `{prompt_product}`, then query "
        "latest stable docs or API reference before generating code."
    )

    cursor_snippet = {
        "mcpServers": {
            server_name: {
                "url": mcp_url,
            }
        }
    }
    claude_snippet = {
        "mcpServers": {
            server_name: {
                "type": "http",
                "url": mcp_url,
            }
        }
    }
    qwen_server_payload = (
        {"httpUrl": mcp_url} if normalized_transport == "streamable-http" else {"url": mcp_url}
    )
    qwen_snippet = {
        "mcpServers": {
            server_name: qwen_server_payload,
        }
    }
    vscode_snippet = {
        "servers": {
            server_name: {
                "type": "http",
                "url": mcp_url,
            }
        }
    }
    snippets = [
        PublicMCPClientConfigSnippetResponse(
            client_id="cursor",
            display_name="Cursor",
            config_path_hint=".cursor/mcp.json",
            format="json",
            snippet=json.dumps(cursor_snippet, indent=2),
            instructions=[
                "Save the snippet into .cursor/mcp.json inside your workspace or global Cursor "
                "MCP settings.",
                "Enable the MCP server in Cursor Settings -> Tools & Integrations -> MCP.",
            ],
        ),
        PublicMCPClientConfigSnippetResponse(
            client_id="claude-desktop",
            display_name="Claude Desktop",
            config_path_hint=".mcp.json",
            format="json",
            snippet=json.dumps(claude_snippet, indent=2),
            instructions=[
                "Save the snippet into your project .mcp.json or Claude Desktop MCP configuration "
                "file.",
                "Restart Claude Desktop so the new HTTP MCP server is discovered.",
            ],
        ),
        PublicMCPClientConfigSnippetResponse(
            client_id="qwen-code",
            display_name="Qwen Code",
            config_path_hint="~/.qwen/settings.json",
            format="json",
            snippet=json.dumps(qwen_snippet, indent=2),
            instructions=[
                "Merge the mcpServers entry into ~/.qwen/settings.json.",
                "Use httpUrl for streamable-http and url for SSE, matching the selected transport.",
            ],
        ),
        PublicMCPClientConfigSnippetResponse(
            client_id="vscode",
            display_name="VS Code",
            config_path_hint=".vscode/mcp.json",
            format="json",
            snippet=json.dumps(vscode_snippet, indent=2),
            instructions=[
                "Save the snippet into .vscode/mcp.json in the target workspace.",
                "Reload the VS Code window after editing the MCP config.",
            ],
        ),
    ]
    return PublicMCPConfigExportResponse(
        server_name=server_name,
        product_id=normalized_product_id,
        transport=normalized_transport,
        mcp_url=mcp_url,
        sample_prompt=sample_prompt,
        clients=snippets,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_starter_packs(
    request: Request,
    *,
    product_id: str | None,
    programming_language: str | None,
    transport: str,
) -> PublicStarterPackResponse:
    config_export = _build_public_mcp_config_export(
        request,
        product_id=product_id,
        transport=transport,
    )
    normalized_product_id = config_export.product_id or "aspose.ocr"
    normalized_language = programming_language.strip() if programming_language else None
    language_hint = normalized_language or "preferred SDK language"

    first_queries = [
        (
            f"Resolve product `{normalized_product_id}` and confirm that the preferred "
            f"SDK language is `{language_hint}`."
        ),
        (
            f"List the latest stable release features for `{normalized_product_id}` "
            f"in `{language_hint}` before generating code."
        ),
        (
            f"Show a minimal cited quickstart for `{normalized_product_id}` in "
            f"`{language_hint}` and validate the main API signatures."
        ),
    ]
    starter_prompt = (
        f"Use MCP server `{config_export.server_name}`. Resolve product "
        f"`{normalized_product_id}` first, prefer SDK language "
        f"`{language_hint}`, read the latest stable docs and API reference, "
        "validate every non-trivial API with symbol docs, and prefer the newest "
        "release APIs over legacy equivalents."
    )

    packs: list[PublicStarterPackItemResponse] = []
    for client in config_export.clients:
        bundle_markdown = "\n".join(
            [
                f"# {client.display_name} Starter Pack",
                "",
                f"- product_id: `{normalized_product_id}`",
                f"- programming_language: `{language_hint}`",
                f"- transport: `{config_export.transport}`",
                "",
                "## MCP Config",
                f"Save into `{client.config_path_hint}`.",
                "",
                f"```{client.format}",
                client.snippet,
                "```",
                "",
                "## Starter Prompt",
                "",
                "```text",
                starter_prompt,
                "```",
                "",
                "## First Queries",
                "",
                *[f"1. {query}" for query in first_queries],
                "",
                "## Checklist",
                "",
                *[
                    f"1. {step}"
                    for step in (
                        [
                            *client.instructions,
                            "Run the MCP self-test and confirm the product/client scope is ready.",
                            (
                                "Execute the first three starter queries "
                                "before asking the agent to write code."
                            ),
                        ]
                    )
                ],
            ]
        )
        packs.append(
            PublicStarterPackItemResponse(
                pack_id=(
                    f"{client.client_id}:{normalized_product_id}:"
                    f"{normalized_language or 'auto'}"
                ),
                client_id=client.client_id,
                display_name=client.display_name,
                title=f"{client.display_name} starter pack for {normalized_product_id}",
                description=(
                    f"Ready-to-paste MCP config, guided prompt, and first queries for "
                    f"{client.display_name} using `{normalized_product_id}` and "
                    f"`{language_hint}`."
                ),
                config_path_hint=client.config_path_hint,
                config_format=client.format,
                config_snippet=client.snippet,
                starter_prompt=starter_prompt,
                first_queries=first_queries,
                starter_checklist=[
                    *client.instructions,
                    "Run the MCP self-test before starting a new coding task.",
                    "Use the starter queries to verify freshness, releases, and symbol coverage.",
                ],
                bundle_markdown=bundle_markdown,
                download_filename=(
                    f"{normalized_product_id.replace('.', '-')}-{client.client_id}-starter-pack.md"
                ),
            )
        )

    return PublicStarterPackResponse(
        product_id=config_export.product_id,
        programming_language=normalized_language,
        transport=config_export.transport,
        packs=packs,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_snippet_explorer(
    request: Request,
    *,
    product_id: str | None,
    programming_language: str | None,
    version: str | None,
    source_kind: str | None,
    limit: int,
) -> PublicSnippetExplorerResponse:
    orchestrator = _source_hugo_orchestrator(request)
    if orchestrator is None:
        return PublicSnippetExplorerResponse(
            product_id=product_id,
            programming_language=programming_language,
            version=version,
            source_kind=source_kind,
            total_snippets=0,
            items=[],
            generated_at=datetime.now(tz=UTC),
        )

    chunk_records = orchestrator.get_latest_chunk_records(
        product_id=product_id,
        programming_language=programming_language,
        version=version,
    )
    filtered_records = tuple(
        record
        for record in chunk_records
        if record.executable_snippets
        and (source_kind is None or record.source_kind == source_kind)
    )
    ordered_records = tuple(
        sorted(
            filtered_records,
            key=_public_snippet_sort_key,
        )
    )
    total_snippets = sum(len(record.executable_snippets) for record in ordered_records)
    items: list[PublicSnippetItemResponse] = []
    for record in ordered_records:
        for snippet in record.executable_snippets:
            items.append(
                PublicSnippetItemResponse(
                    snippet_id=snippet.snippet_id,
                    product_id=record.product_id,
                    programming_language=record.programming_language,
                    version=record.version,
                    source_kind=record.source_kind,
                    doc_type=record.doc_type,
                    title=record.title,
                    canonical_url=record.canonical_url,
                    section_anchor=record.section_anchor,
                    symbol_fqn=record.symbol_fqn,
                    snippet_language=snippet.language,
                    code=snippet.code,
                    source_revision=record.source_revision,
                    repo_id=record.repo_id,
                )
            )
            if len(items) >= limit:
                return PublicSnippetExplorerResponse(
                    product_id=product_id,
                    programming_language=programming_language,
                    version=version,
                    source_kind=source_kind,
                    total_snippets=total_snippets,
                    items=items,
                    generated_at=datetime.now(tz=UTC),
                )
    return PublicSnippetExplorerResponse(
        product_id=product_id,
        programming_language=programming_language,
        version=version,
        source_kind=source_kind,
        total_snippets=total_snippets,
        items=items,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_mcp_self_test(
    request: Request,
    *,
    product_id: str,
    programming_language: str | None,
    client_id: str,
    transport: str,
) -> PublicMCPSelfTestResponse:
    normalized_product_id = product_id.strip()
    if not normalized_product_id:
        _raise_structured_http_error(
            request,
            status_code=400,
            code="INVALID_PRODUCT_ID",
            message="product_id must not be empty.",
        )

    normalized_client_id = client_id.strip().casefold()
    supported_client_ids = {"cursor", "claude-desktop", "qwen-code", "vscode"}
    if normalized_client_id not in supported_client_ids:
        _raise_structured_http_error(
            request,
            status_code=400,
            code="INVALID_CLIENT_ID",
            message="client_id must be one of: cursor, claude-desktop, qwen-code, vscode.",
            details={"client_id": client_id},
        )

    config_export = _build_public_mcp_config_export(
        request,
        product_id=normalized_product_id,
        transport=transport,
    )
    normalized_transport = config_export.transport
    base_url = str(request.base_url).rstrip("/")
    status_page_url = f"{base_url}/status?product_id={normalized_product_id}"
    config_export_url = (
        f"{base_url}/integrations?product_id={normalized_product_id}"
        f"&language={programming_language or ''}&transport={normalized_transport}"
    )

    repositories = _source_registry_service(request).list_repositories()
    product_repositories = tuple(
        repository
        for repository in repositories
        if repository.product_id.casefold() == normalized_product_id.casefold()
    )
    services = _collect_content_service_rows(request, product_id=normalized_product_id)
    ready_services = [service for service in services if service.mcp_ready]
    docs_ready_count = sum(1 for service in ready_services if service.source_kind == "docs")
    apiref_ready_count = sum(1 for service in ready_services if service.source_kind == "apiref")

    available_programming_languages = sorted(
        {
            language
            for service in services
            for language in service.supported_programming_languages
            if language
        }
    )
    available_versions = sorted(
        {
            version
            for service in services
            for version in service.supported_versions
            if version
        },
        key=_public_version_sort_key,
    )

    snippet_count = 0
    orchestrator = _source_hugo_orchestrator(request)
    if orchestrator is not None:
        chunk_records = orchestrator.get_latest_chunk_records(
            product_id=normalized_product_id,
            programming_language=programming_language,
            version=None,
        )
        snippet_count = sum(len(record.executable_snippets) for record in chunk_records)

    readiness_status, dependency_entries = _build_dependency_health(request)
    degraded_dependencies = [
        dependency_name
        for dependency_name, entry in dependency_entries.items()
        if entry.required and entry.status != "ready"
    ]

    checks: list[PublicMCPSelfTestCheckResponse] = []
    checks.append(
        PublicMCPSelfTestCheckResponse(
            check_id="product-registered",
            title="Product registration",
            status="pass" if product_repositories else "fail",
            summary=(
                f"Product `{normalized_product_id}` is registered in the source registry."
                if product_repositories
                else (
                    f"Product `{normalized_product_id}` is not registered in the public "
                    "source registry."
                )
            ),
            details=(
                [
                    "Registered repositories: "
                    + ", ".join(sorted(repository.repo_id for repository in product_repositories)),
                    "Source kinds found: "
                    + (
                        ", ".join(
                            sorted(
                                {
                                    repository.source_kind
                                    for repository in product_repositories
                                }
                            )
                        )
                        or "none"
                    ),
                ]
                if product_repositories
                else [
                    "Use the canonical product_id from the public docs or status page.",
                    "If this product should exist, ask the product owner to onboard "
                    "its docs/apiref repositories.",
                ]
            ),
        )
    )
    checks.append(
        PublicMCPSelfTestCheckResponse(
            check_id="client-transport",
            title="Client and transport",
            status="pass",
            summary=(
                f"Client `{normalized_client_id}` supports transport "
                f"`{normalized_transport}` for this public MCP surface."
            ),
            details=[
                "Use config file hint from the generated client snippet "
                f"for `{normalized_client_id}`.",
                f"Public MCP endpoint: {config_export.mcp_url}",
            ],
        )
    )

    if not product_repositories:
        content_status = "fail"
        content_summary = (
            "No repositories are registered for this product yet, so MCP "
            "cannot serve content."
        )
        content_details = [
            "Open the public status page to confirm current product coverage.",
            "Use a registered product_id or ask an operator to onboard this product family.",
        ]
    else:
        total_ready_services = len(ready_services)
        total_registered_services = len(services)
        if total_ready_services == 0:
            content_status = "fail"
            content_summary = (
                "The product is registered, but no active docs/API reference "
                "snapshot is currently MCP-ready."
            )
        elif docs_ready_count == 0 or apiref_ready_count == 0:
            content_status = "warn"
            content_summary = (
                "The product is partially MCP-ready. One source kind is available, "
                "but full docs/apiref coverage is incomplete."
            )
        else:
            content_status = "pass"
            content_summary = (
                "Both docs and API reference services have active MCP-ready snapshots."
            )
        content_details = [
            f"Ready services: {total_ready_services}/{total_registered_services}",
            f"Docs ready: {docs_ready_count}; API reference ready: {apiref_ready_count}",
        ]
        if services:
            content_details.append(
                "Repositories: " + ", ".join(sorted(service.repo_id for service in services))
            )
    checks.append(
        PublicMCPSelfTestCheckResponse(
            check_id="content-readiness",
            title="Content readiness",
            status=content_status,
            summary=content_summary,
            details=content_details,
        )
    )

    snippet_status = "pass"
    snippet_summary = (
        f"Executable snippet coverage is available for `{programming_language}`."
        if programming_language
        else "Executable snippet coverage is available for this product."
    )
    snippet_details = [
        f"Detected executable snippets: {snippet_count}",
        f"Available SDK languages: {', '.join(available_programming_languages) or 'none'}",
    ]
    if programming_language and programming_language not in available_programming_languages:
        snippet_status = "warn"
        snippet_summary = (
            f"No indexed snippet surface is available yet for `{programming_language}`."
        )
        snippet_details.append(
            "Try one of the available SDK languages or rely on "
            "citation-only retrieval until snippets are added."
        )
    elif snippet_count == 0 and product_repositories:
        snippet_status = "warn"
        snippet_summary = (
            "The product is indexed, but no executable snippets were found "
            "for this scope yet."
        )
        snippet_details.append(
            "Query_docs may still work, but generated code examples will be weaker "
            "until snippet extraction covers this scope."
        )
    checks.append(
        PublicMCPSelfTestCheckResponse(
            check_id="snippet-coverage",
            title="Snippet coverage",
            status=snippet_status,
            summary=snippet_summary,
            details=snippet_details,
        )
    )

    dependency_status = "pass" if readiness_status == "ready" else "warn"
    dependency_summary = (
        "Runtime dependencies are healthy."
        if readiness_status == "ready"
        else "Public runtime is degraded; MCP may still respond, but reliability is reduced."
    )
    dependency_details = [
        f"{dependency_name}: {entry.status} ({entry.reason})"
        for dependency_name, entry in dependency_entries.items()
    ]
    checks.append(
        PublicMCPSelfTestCheckResponse(
            check_id="runtime-dependencies",
            title="Runtime dependencies",
            status=dependency_status,
            summary=dependency_summary,
            details=dependency_details,
        )
    )

    if not product_repositories or content_status == "fail":
        overall_status = "not_ready"
    elif snippet_status == "warn" or dependency_status == "warn" or content_status == "warn":
        overall_status = "partial"
    else:
        overall_status = "ready"

    fix_plan: list[str] = []
    if not product_repositories:
        fix_plan.extend(
            [
                "Use a product_id that appears on the public status page "
                "or in the product resolver output.",
                "If the product should exist, ask the product owner to onboard "
                "docs and API reference repositories first.",
            ]
        )
    elif content_status == "fail":
        fix_plan.extend(
            [
                "Wait for a publish run to promote at least one active snapshot "
                "for docs or API reference.",
                "Re-check the product on the public status page after the next "
                "ingestion/publish cycle.",
            ]
        )
    elif content_status == "warn":
        fix_plan.append(
            "The product is usable, but expect incomplete answers until both docs "
            "and API reference services are MCP-ready."
        )
    if snippet_status == "warn":
        fix_plan.append(
            "Rely on citations and release notes for now, or switch to one of the "
            "SDK languages that already has executable snippets."
        )
    if degraded_dependencies:
        fix_plan.append(
            "Retry later if public status remains degraded, especially when "
            "OpenSearch/Qdrant are not ready."
        )
    fix_plan.extend(
        [
            "Copy the client config from the generated snippet below instead of "
            "writing MCP JSON manually.",
            "Run a real query in the public query playground after MCP connects successfully.",
        ]
    )
    deduped_fix_plan = list(dict.fromkeys(fix_plan))

    status_summary = {
        "ready": "This product/client/transport combination is ready for external MCP use.",
        "partial": (
            "MCP can be used now, but coverage or runtime quality is only partial "
            "for this scope."
        ),
        "not_ready": (
            "Do not rely on MCP for this scope yet; at least one blocking "
            "readiness condition is still missing."
        ),
    }[overall_status]
    return PublicMCPSelfTestResponse(
        product_id=normalized_product_id,
        programming_language=programming_language,
        client_id=normalized_client_id,
        transport=normalized_transport,
        status=overall_status,
        status_summary=status_summary,
        docs_ready_count=docs_ready_count,
        apiref_ready_count=apiref_ready_count,
        total_ready_services=len(ready_services),
        total_registered_services=len(services),
        snippet_count=snippet_count,
        available_programming_languages=available_programming_languages,
        available_versions=available_versions,
        checks=checks,
        fix_plan=deduped_fix_plan,
        config_export_url=config_export_url,
        status_page_url=status_page_url,
        mcp_url=config_export.mcp_url,
        sample_prompt=config_export.sample_prompt,
        generated_at=datetime.now(tz=UTC),
    )


def _analytics_service(request: Request) -> AnalyticsService | None:
    service = getattr(request.app.state, "analytics_service", None)
    if isinstance(service, AnalyticsService):
        return service
    return None


def _public_query_service(request: Request) -> PublicQueryService:
    return request.app.state.public_query_service


def _hash_client_ip(request: Request) -> str | None:
    client = request.client
    if client is None or not client.host.strip():
        return None
    return keyed_hash(client.host, purpose="ip_hash")


def _record_public_self_test_analytics(
    *,
    request: Request,
    response: PublicMCPSelfTestResponse,
    latency_ms: int,
) -> None:
    analytics_service = _analytics_service(request)
    if analytics_service is None:
        return
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    analytics_service.record_query(
        request_id=str(request_id),
        endpoint="public.integrations.self_test",
        tool="mcp_self_test",
        raw_query=(
            f"client={response.client_id};transport={response.transport};"
            f"status={response.status}"
        ),
        product_id=response.product_id,
        programming_language=response.programming_language,
        doc_locale=None,
        hashed_ip=_hash_client_ip(request),
        fingerprint=request.headers.get("x-adcs-fingerprint"),
        latency_ms=latency_ms,
        confidence=(
            1.0
            if response.status == "ready"
            else 0.6
            if response.status == "partial"
            else 0.0
        ),
        outcome=response.status,
        retrieval_mode=response.transport,
        result_count=response.total_ready_services,
        zero_result_reason="no_ready_services" if response.total_ready_services == 0 else None,
        warning_codes=_self_test_warning_codes(response),
    )


def _self_test_warning_codes(response: PublicMCPSelfTestResponse) -> list[str]:
    warnings = [
        f"self_test:{item.check_id}"
        for item in response.checks
        if item.status != "pass"
    ]
    if response.status != "ready":
        warnings.append(f"self_test_status:{response.status}")
    return warnings


def _build_public_release_freshness(
    request: Request,
    *,
    product_id: str,
    programming_language: str | None,
    version: str | None,
    top_k: int,
) -> PublicReleaseFreshnessResponse:
    normalized_product_id = product_id.strip()
    snapshot_registry = _snapshot_registry(request)
    snapshots = tuple(
        snapshot
        for snapshot in snapshot_registry.list_snapshots()
        if snapshot.product_id.casefold() == normalized_product_id.casefold()
        and (
            programming_language is None
            or snapshot.programming_language.casefold() == programming_language.casefold()
        )
    )
    available_versions = sorted(
        {snapshot.version for snapshot in snapshots},
        key=_public_version_sort_key,
    )
    newest_available_version = available_versions[0] if available_versions else None
    active_snapshots = tuple(
        snapshot for snapshot in snapshots if snapshot.status is SnapshotStatus.ACTIVE
    )
    latest_active_snapshot_at = (
        max(snapshot.created_at for snapshot in active_snapshots) if active_snapshots else None
    )

    services: list[PublicFreshnessServiceScopeResponse] = []
    for source_kind in sorted({snapshot.source_kind for snapshot in snapshots}):
        scoped_snapshots = [
            snapshot for snapshot in snapshots if snapshot.source_kind == source_kind
        ]
        latest_snapshot = max(scoped_snapshots, key=lambda item: item.created_at, default=None)
        active_snapshot = max(
            (
                snapshot
                for snapshot in scoped_snapshots
                if snapshot.status is SnapshotStatus.ACTIVE
            ),
            key=lambda item: item.created_at,
            default=None,
        )
        reference_snapshot = active_snapshot or latest_snapshot
        services.append(
            PublicFreshnessServiceScopeResponse(
                source_kind=source_kind,
                mcp_ready=active_snapshot is not None,
                latest_version=reference_snapshot.version if reference_snapshot else None,
                latest_source_revision=(
                    reference_snapshot.source_revision if reference_snapshot else None
                ),
                latest_snapshot_id=(
                    reference_snapshot.snapshot_id if reference_snapshot else None
                ),
                latest_snapshot_created_at=(
                    reference_snapshot.created_at if reference_snapshot else None
                ),
                indexed_chunks_count=(
                    reference_snapshot.indexed_chunks_count if reference_snapshot else 0
                ),
            )
        )

    release_features: list[PublicReleaseFeaturePreviewResponse] = []
    resolved_version: str | None = version
    orchestrator = _source_hugo_orchestrator(request)
    if orchestrator is not None:
        chunk_records = orchestrator.get_latest_chunk_records(
            product_id=normalized_product_id,
            programming_language=programming_language,
            version=version,
        )
        if chunk_records:
            filtered_release_records = _filter_release_feature_records(
                records=chunk_records,
                requested_version=version,
            )
            if filtered_release_records:
                resolved_version = _resolve_latest_version(
                    records=filtered_release_records,
                    requested_version=version,
                )
                release_features = [
                    PublicReleaseFeaturePreviewResponse(
                        kind=item.kind,
                        summary=item.summary,
                        symbol_fqn=item.symbol_fqn,
                        version=item.version,
                        source_kind=item.source_kind,
                        canonical_url=item.citation.canonical_url,
                        section_anchor=item.citation.section_anchor,
                    )
                    for item in _build_release_feature_items(
                        records=filtered_release_records,
                        top_k=top_k,
                    )
                ]

    if resolved_version is None:
        resolved_version = newest_available_version

    if active_snapshots and release_features:
        status_summary = (
            "Active snapshots are available and release-note signals were extracted "
            "for the latest visible scope."
        )
    elif active_snapshots:
        status_summary = (
            "Active snapshots are available, but no explicit release-note features "
            "were extracted for this scope."
        )
    elif snapshots:
        status_summary = (
            "Snapshots exist for this scope, but no active runtime snapshot is "
            "currently serving MCP traffic."
        )
    else:
        status_summary = (
            "No snapshot or release visibility signals are available for this "
            "product/language scope yet."
        )

    return PublicReleaseFreshnessResponse(
        product_id=normalized_product_id,
        programming_language=programming_language,
        requested_version=version,
        resolved_version=resolved_version,
        newest_available_version=newest_available_version,
        available_versions=available_versions,
        latest_active_snapshot_at=latest_active_snapshot_at,
        services=services,
        release_features=release_features,
        status_summary=status_summary,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_scope_link(
    *,
    product_id: str | None = None,
    programming_language: str | None = None,
    source_kind: str | None = None,
    version: str | None = None,
    anchor: str,
) -> str:
    params: dict[str, str] = {}
    if product_id:
        params["product_id"] = product_id
    if programming_language:
        params["language"] = programming_language
    if source_kind:
        params["source_kind"] = source_kind
    if version:
        params["version"] = version
    query = urlencode(params)
    return f"/integrations?{query}{anchor}" if query else f"/integrations{anchor}"


def _build_public_shared_request_link(*, request: Request, request_id: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/integrations?shared_request_id={request_id}"


def _content_gap_severity(
    *,
    signal_type: str,
    service: AdminContentServiceHealthResponse,
    stale_days: int | None = None,
) -> str:
    if signal_type == "no_active_snapshot":
        return "critical" if service.service_status == "critical" else "warning"
    if signal_type == "no_index_data":
        return "critical" if service.mcp_ready else "warning"
    if signal_type == "stale_snapshot":
        if stale_days is not None and stale_days >= 90:
            return "critical"
        return "warning"
    if signal_type == "no_snippet_coverage":
        return "warning"
    return "info"


def _build_public_content_triage(
    request: Request,
    *,
    product_id: str | None,
    repo_id: str | None,
    severity: str | None,
    source_kind: str | None,
    stale_after_days: int,
    limit: int,
) -> PublicContentTriageResponse:
    services = _collect_content_service_rows(request, product_id=product_id, repo_id=repo_id)
    orchestrator = _source_hugo_orchestrator(request)
    repo_stats: dict[str, dict[str, int]] = {}
    if orchestrator is not None:
        records = orchestrator.get_latest_chunk_records(product_id=product_id)
        for record in records:
            if repo_id is not None and record.repo_id.casefold() != repo_id.casefold():
                continue
            stats = repo_stats.setdefault(
                record.repo_id,
                {"indexed_chunks_count": 0, "executable_snippets_count": 0},
            )
            stats["indexed_chunks_count"] += 1
            stats["executable_snippets_count"] += len(record.executable_snippets)

    normalized_severity = severity.strip().casefold() if severity else None
    normalized_source_kind = source_kind.strip().casefold() if source_kind else None
    now = datetime.now(tz=UTC)
    items: list[PublicContentTriageGapResponse] = []
    for service in services:
        if (
            normalized_source_kind
            and service.source_kind.casefold() != normalized_source_kind
        ):
            continue
        stats = repo_stats.get(
            service.repo_id,
            {"indexed_chunks_count": 0, "executable_snippets_count": 0},
        )
        indexed_chunks_count = stats["indexed_chunks_count"]
        executable_snippets_count = stats["executable_snippets_count"]
        stale_days: int | None = None
        if service.active_snapshot_created_at is not None:
            stale_days = max(
                0,
                int((now - service.active_snapshot_created_at).total_seconds() // 86400),
            )

        candidate_gaps: list[tuple[str, str, list[str], int | None]] = []
        if not service.mcp_ready:
            candidate_gaps.append(
                (
                    "no_active_snapshot",
                    service.service_status_summary,
                    service.fix_plan,
                    stale_days,
                )
            )
        if indexed_chunks_count <= 0:
            candidate_gaps.append(
                (
                    "no_index_data",
                    (
                        "No normalized chunk records were found for this "
                        "repository, so retrieval cannot return content from it."
                    ),
                    [
                        (
                            "Run Validate-Only and inspect the review "
                            "workspace for chunk output."
                        ),
                        (
                            "Fix parser, layout, or conversion issues until "
                            "chunk records are generated."
                        ),
                        (
                            "Publish a new snapshot only after indexed content "
                            "exists for this repository."
                        ),
                    ],
                    stale_days,
                )
            )
        if stale_days is not None and stale_days > stale_after_days:
            candidate_gaps.append(
                (
                    "stale_snapshot",
                    (
                        f"Active snapshot is {stale_days} day(s) old, which exceeds the "
                        "freshness threshold for public MCP guidance."
                    ),
                    [
                        "Sync the source repository and run ingestion for the affected repo.",
                        "Review the freshness panel to confirm newer versions are visible.",
                        "Promote a newer active snapshot after validation is clean.",
                    ],
                    stale_days,
                )
            )
        if indexed_chunks_count > 0 and executable_snippets_count <= 0:
            candidate_gaps.append(
                (
                    "no_snippet_coverage",
                    (
                        "Indexed content exists, but no executable snippets "
                        "were extracted for this repository."
                    ),
                    [
                        (
                            "Inspect chunk previews and confirm code fences are "
                            "preserved during normalization."
                        ),
                        (
                            "Add or recover representative code examples in "
                            "the upstream documentation where appropriate."
                        ),
                        (
                            "Re-run ingestion and verify the snippet explorer "
                            "now exposes executable examples."
                        ),
                    ],
                    stale_days,
                )
            )

        for signal_type, summary, fix_plan, gap_stale_days in candidate_gaps:
            gap_severity = _content_gap_severity(
                signal_type=signal_type,
                service=service,
                stale_days=gap_stale_days,
            )
            if normalized_severity and gap_severity.casefold() != normalized_severity:
                continue
            items.append(
                PublicContentTriageGapResponse(
                    gap_id=f"{service.repo_id}:{signal_type}",
                    severity=gap_severity,
                    signal_type=signal_type,
                    product_id=service.product_id,
                    repo_id=service.repo_id,
                    source_kind=service.source_kind,
                    mcp_ready=service.mcp_ready,
                    indexed_chunks_count=indexed_chunks_count,
                    executable_snippets_count=executable_snippets_count,
                    active_snapshot_created_at=service.active_snapshot_created_at,
                    stale_days=gap_stale_days,
                    summary=summary,
                    service_status=service.service_status,
                    service_status_reason=service.service_status_reason,
                    fix_plan=fix_plan,
                )
            )

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    items.sort(
        key=lambda item: (
            severity_rank.get(item.severity, 9),
            item.product_id,
            item.repo_id,
            item.signal_type,
        )
    )
    items = items[:limit]
    critical_total = sum(1 for item in items if item.severity == "critical")
    warning_total = sum(1 for item in items if item.severity == "warning")
    info_total = sum(1 for item in items if item.severity == "info")
    if items:
        status_summary = (
            f"Found {len(items)} triage gap(s): critical={critical_total}, "
            f"warning={warning_total}, info={info_total}."
        )
    else:
        status_summary = (
            "No stale, no-index, or snippet-coverage gaps were detected for "
            "the current filter set."
        )

    return PublicContentTriageResponse(
        filters={
            "product_id": product_id,
            "repo_id": repo_id,
            "severity": severity,
            "source_kind": source_kind,
        },
        stale_after_days=stale_after_days,
        total_items=len(items),
        critical_total=critical_total,
        warning_total=warning_total,
        info_total=info_total,
        status_summary=status_summary,
        items=items,
        generated_at=now,
    )


def _collect_expected_programming_languages(repository: Any) -> tuple[str, ...]:
    languages: list[str] = []
    seen_languages: set[str] = set()

    for value in getattr(repository, "onboarding_programming_languages", ()):
        if not isinstance(value, str) or not value.strip():
            continue
        normalized_value = value.strip()
        dedupe_key = normalized_value.casefold()
        if dedupe_key in seen_languages:
            continue
        seen_languages.add(dedupe_key)
        languages.append(normalized_value)

    layout_detection = getattr(repository, "layout_detection", None)
    if not isinstance(layout_detection, dict):
        return tuple(languages)

    dimensions = layout_detection.get("dimensions")
    if not isinstance(dimensions, list):
        return tuple(languages)

    for dimension in dimensions:
        if not isinstance(dimension, dict):
            continue
        semantic = dimension.get("semantic")
        if not isinstance(semantic, str) or semantic.strip().casefold() != "programming_language":
            continue
        values_sample = dimension.get("values_sample")
        if not isinstance(values_sample, list):
            continue
        for value in values_sample:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized_value = value.strip()
            dedupe_key = normalized_value.casefold()
            if dedupe_key in seen_languages:
                continue
            seen_languages.add(dedupe_key)
            languages.append(normalized_value)

    return tuple(languages)


def _build_public_coverage_gap_tracker(
    request: Request,
    *,
    product_id: str | None,
    programming_language: str | None,
    source_kind: str | None,
    version: str | None,
) -> PublicCoverageGapTrackerResponse:
    repositories = _source_registry_service(request).list_repositories()
    services = _collect_content_service_rows(request, product_id=product_id)
    snapshots = _snapshot_registry(request).list_snapshots(product_id=product_id)
    orchestrator = _source_hugo_orchestrator(request)

    normalized_product_id = product_id.strip().casefold() if product_id else None
    normalized_programming_language = (
        programming_language.strip().casefold() if programming_language else None
    )
    normalized_source_kind = source_kind.strip().casefold() if source_kind else None
    normalized_version = version.strip() if version else None

    filtered_repositories = [
        repository
        for repository in repositories
        if (
            normalized_product_id is None
            or repository.product_id.casefold() == normalized_product_id
        )
    ]
    service_rows_by_repo = {service.repo_id: service for service in services}

    snapshot_rows = [
        snapshot
        for snapshot in snapshots
        if (
            normalized_source_kind is None
            or snapshot.source_kind.casefold() == normalized_source_kind
        )
        and (
            normalized_programming_language is None
            or snapshot.programming_language.casefold() == normalized_programming_language
        )
        and (normalized_version is None or snapshot.version == normalized_version)
    ]

    executable_snippet_counts: dict[tuple[str, str], int] = {}
    if orchestrator is not None:
        for record in orchestrator.get_latest_chunk_records(
            product_id=product_id,
            programming_language=programming_language,
            version=version,
        ):
            if (
                normalized_source_kind is not None
                and record.source_kind.casefold() != normalized_source_kind
            ):
                continue
            surface_key = (record.product_id.casefold(), record.programming_language.casefold())
            executable_snippet_counts[surface_key] = (
                executable_snippet_counts.get(surface_key, 0)
                + len(record.executable_snippets)
            )

    product_ids = sorted({repository.product_id for repository in filtered_repositories})
    products: list[PublicCoverageProductResponse] = []
    ready_surfaces_total = 0
    partial_surfaces_total = 0
    registered_only_surfaces_total = 0
    high_priority_surfaces_total = 0
    medium_priority_surfaces_total = 0
    low_priority_surfaces_total = 0

    for current_product_id in product_ids:
        product_repositories = [
            repository
            for repository in filtered_repositories
            if repository.product_id == current_product_id
        ]
        product_services = [
            service for service in services if service.product_id == current_product_id
        ]
        product_snapshots = [
            snapshot for snapshot in snapshot_rows if snapshot.product_id == current_product_id
        ]
        product_name = next(
            (
                repository.product_name
                for repository in product_repositories
                if repository.product_name
            ),
            current_product_id,
        )
        product_family = (
            product_repositories[0].product_family
            if product_repositories
            else current_product_id
        )
        product_family_dirs = sorted(
            {repository.product_family_dir for repository in product_repositories}
        )
        repo_ids = sorted(repository.repo_id for repository in product_repositories)

        registered_source_kinds = sorted(
            {repository.source_kind for repository in product_repositories}
        )
        coverage_source_kinds = [
            kind
            for kind in ("docs", "apiref")
            if normalized_source_kind is None or kind == normalized_source_kind
        ]

        expected_languages: list[str] = []
        seen_languages: set[str] = set()
        for repository in product_repositories:
            for language_value in _collect_expected_programming_languages(repository):
                dedupe_key = language_value.casefold()
                if dedupe_key in seen_languages:
                    continue
                seen_languages.add(dedupe_key)
                expected_languages.append(language_value)
        for service in product_services:
            for language_value in service.supported_programming_languages:
                dedupe_key = language_value.casefold()
                if dedupe_key in seen_languages:
                    continue
                seen_languages.add(dedupe_key)
                expected_languages.append(language_value)
        for snapshot in product_snapshots:
            dedupe_key = snapshot.programming_language.casefold()
            if dedupe_key in seen_languages:
                continue
            seen_languages.add(dedupe_key)
            expected_languages.append(snapshot.programming_language)
        if (
            normalized_programming_language
            and normalized_programming_language not in seen_languages
        ):
            expected_languages.append(programming_language or normalized_programming_language)
            seen_languages.add(normalized_programming_language)
        if normalized_programming_language is not None:
            expected_languages = [
                item
                for item in expected_languages
                if item.casefold() == normalized_programming_language
            ]
        expected_languages.sort(key=str.casefold)

        surfaces: list[PublicCoverageSurfaceResponse] = []
        for current_language in expected_languages:
            current_language_key = current_language.casefold()
            source_kind_states: list[PublicCoverageSourceKindStateResponse] = []
            ready_source_kinds: list[str] = []
            surface_gap_badges: list[str] = []
            expected_versions: set[str] = set()

            for current_source_kind in coverage_source_kinds:
                matching_repositories = [
                    repository
                    for repository in product_repositories
                    if repository.source_kind == current_source_kind
                ]
                matching_services = [
                    service_rows_by_repo[repository.repo_id]
                    for repository in matching_repositories
                    if repository.repo_id in service_rows_by_repo
                ]
                matching_snapshots = [
                    snapshot
                    for snapshot in product_snapshots
                    if snapshot.source_kind == current_source_kind
                    and snapshot.programming_language.casefold() == current_language_key
                ]
                active_snapshots = [
                    snapshot
                    for snapshot in matching_snapshots
                    if snapshot.status is SnapshotStatus.ACTIVE
                ]
                if normalized_version is not None:
                    expected_versions.add(normalized_version)
                else:
                    expected_versions.update(snapshot.version for snapshot in matching_snapshots)

                registered = bool(matching_repositories)
                ready = bool(active_snapshots)
                if ready:
                    ready_source_kinds.append(current_source_kind)
                elif registered:
                    surface_gap_badges.append(f"{current_source_kind}_not_ready")
                else:
                    surface_gap_badges.append(f"{current_source_kind}_not_registered")

                source_kind_states.append(
                    PublicCoverageSourceKindStateResponse(
                        source_kind=current_source_kind,
                        registered=registered,
                        ready=ready,
                        repo_ids=sorted(repository.repo_id for repository in matching_repositories),
                        active_snapshot_ids=sorted(
                            snapshot.snapshot_id for snapshot in active_snapshots
                        ),
                        active_versions=sorted(
                            {snapshot.version for snapshot in active_snapshots},
                            key=_public_version_sort_key,
                        ),
                        latest_stable_visible=ready,
                        supported_versions=sorted(
                            {snapshot.version for snapshot in matching_snapshots},
                            key=_public_version_sort_key,
                        ),
                        service_statuses=sorted(
                            {service.service_status for service in matching_services}
                        ),
                        service_reasons=sorted(
                            {service.service_status_reason for service in matching_services}
                        ),
                    )
                )

            executable_snippets_count = executable_snippet_counts.get(
                (current_product_id.casefold(), current_language_key),
                0,
            )
            if any(state.ready for state in source_kind_states) and executable_snippets_count <= 0:
                surface_gap_badges.append("no_snippets")

            registered_states = [state for state in source_kind_states if state.registered]
            ready_states = [state for state in registered_states if state.ready]
            if (
                registered_states
                and len(ready_states) == len(registered_states)
                and len(registered_states) == len(source_kind_states)
                and executable_snippets_count > 0
            ):
                surface_status = "ready"
                onboarding_priority = "low"
            elif not ready_states:
                surface_status = "registered_only"
                onboarding_priority = "high"
            else:
                surface_status = "partial"
                onboarding_priority = "medium"

            if any(badge.endswith("_not_registered") for badge in surface_gap_badges):
                onboarding_priority = "high"
                if surface_status == "ready":
                    surface_status = "partial"
            elif "no_snippets" in surface_gap_badges and onboarding_priority == "low":
                onboarding_priority = "medium"
                surface_status = "partial"

            latest_stable_visible = bool(registered_states) and all(
                state.latest_stable_visible for state in registered_states
            )
            source_kind_summary = ", ".join(
                f"{state.source_kind}={'ready' if state.ready else 'gap'}"
                for state in source_kind_states
            )
            if source_kind_summary:
                source_kind_summary = f"{source_kind_summary}; "
            summary = (
                f"{source_kind_summary}latest stable visible={latest_stable_visible}; "
                f"snippets={executable_snippets_count}."
            )

            surfaces.append(
                PublicCoverageSurfaceResponse(
                    surface_id=f"{current_product_id}:{current_language}",
                    product_id=current_product_id,
                    product_name=product_name,
                    product_family=product_family,
                    programming_language=current_language,
                    status=surface_status,
                    onboarding_priority=onboarding_priority,
                    registered_source_kinds=sorted(
                        state.source_kind for state in source_kind_states if state.registered
                    ),
                    ready_source_kinds=sorted(ready_source_kinds),
                    latest_stable_visible=latest_stable_visible,
                    executable_snippets_count=executable_snippets_count,
                    expected_versions=sorted(expected_versions, key=_public_version_sort_key),
                    gap_badges=sorted(set(surface_gap_badges)),
                    summary=summary,
                    source_kinds=source_kind_states,
                )
            )

        surfaces.sort(
            key=lambda item: (
                {"high": 0, "medium": 1, "low": 2}.get(item.onboarding_priority, 9),
                {"registered_only": 0, "partial": 1, "ready": 2}.get(item.status, 9),
                item.programming_language.casefold(),
            )
        )

        current_ready_surfaces = sum(1 for item in surfaces if item.status == "ready")
        current_partial_surfaces = sum(1 for item in surfaces if item.status == "partial")
        current_registered_only_surfaces = sum(
            1 for item in surfaces if item.status == "registered_only"
        )
        current_high_priority = sum(
            1 for item in surfaces if item.onboarding_priority == "high"
        )
        current_medium_priority = sum(
            1 for item in surfaces if item.onboarding_priority == "medium"
        )
        current_low_priority = sum(1 for item in surfaces if item.onboarding_priority == "low")

        ready_surfaces_total += current_ready_surfaces
        partial_surfaces_total += current_partial_surfaces
        registered_only_surfaces_total += current_registered_only_surfaces
        high_priority_surfaces_total += current_high_priority
        medium_priority_surfaces_total += current_medium_priority
        low_priority_surfaces_total += current_low_priority

        products.append(
            PublicCoverageProductResponse(
                product_id=current_product_id,
                product_name=product_name,
                product_family=product_family,
                product_family_dirs=product_family_dirs,
                repo_ids=repo_ids,
                registered_source_kinds=registered_source_kinds,
                expected_programming_languages=expected_languages,
                ready_surfaces_total=current_ready_surfaces,
                partial_surfaces_total=current_partial_surfaces,
                registered_only_surfaces_total=current_registered_only_surfaces,
                high_priority_surfaces_total=current_high_priority,
                medium_priority_surfaces_total=current_medium_priority,
                low_priority_surfaces_total=current_low_priority,
                surfaces=surfaces,
            )
        )

    surfaces_total = sum(len(product.surfaces) for product in products)
    if surfaces_total:
        status_summary = (
            f"Tracked {surfaces_total} surfaces across {len(products)} product(s): "
            f"ready={ready_surfaces_total}, partial={partial_surfaces_total}, "
            f"registered_only={registered_only_surfaces_total}, "
            f"high_priority={high_priority_surfaces_total}."
        )
    else:
        status_summary = "No coverage surfaces matched the current filter set."

    return PublicCoverageGapTrackerResponse(
        filters={
            "product_id": product_id,
            "programming_language": programming_language,
            "source_kind": source_kind,
            "version": version,
        },
        products_total=len(products),
        surfaces_total=surfaces_total,
        ready_surfaces_total=ready_surfaces_total,
        partial_surfaces_total=partial_surfaces_total,
        registered_only_surfaces_total=registered_only_surfaces_total,
        high_priority_surfaces_total=high_priority_surfaces_total,
        medium_priority_surfaces_total=medium_priority_surfaces_total,
        low_priority_surfaces_total=low_priority_surfaces_total,
        status_summary=status_summary,
        products=products,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_surface_actions(
    *,
    product_id: str,
    programming_language: str,
    source_kind: str | None,
    version: str | None,
) -> list[PublicCapabilityActionResponse]:
    surface_link_params = {
        "product_id": product_id,
        "programming_language": programming_language,
        "source_kind": source_kind,
        "version": version,
    }
    return [
        PublicCapabilityActionResponse(
            label="Coverage tracker",
            href=_build_public_scope_link(
                **surface_link_params,
                anchor="#coverage-gap-tracker",
            ),
        ),
        PublicCapabilityActionResponse(
            label="Capability explorer",
            href=_build_public_scope_link(
                **surface_link_params,
                anchor="#capability-explorer",
            ),
        ),
        PublicCapabilityActionResponse(
            label="Starter packs",
            href=_build_public_scope_link(
                **surface_link_params,
                anchor="#starter-packs",
            ),
        ),
        PublicCapabilityActionResponse(
            label="Prompt cookbook",
            href=_build_public_scope_link(
                **surface_link_params,
                anchor="#prompt-cookbook",
            ),
        ),
    ]


def _build_public_coverage_navigator(
    request: Request,
    *,
    product_id: str | None,
    programming_language: str | None,
    source_kind: str | None,
    version: str | None,
) -> PublicCoverageNavigatorResponse:
    coverage = _build_public_coverage_gap_tracker(
        request,
        product_id=product_id,
        programming_language=programming_language,
        source_kind=source_kind,
        version=version,
    )

    available_products: set[str] = set()
    available_programming_languages: set[str] = set()
    available_source_kinds: set[str] = set()
    available_versions: set[str] = set()
    surfaces: list[PublicCoverageNavigatorSurfaceResponse] = []
    for product in coverage.products:
        available_products.add(product.product_id)
        for surface in product.surfaces:
            available_programming_languages.add(surface.programming_language)
            available_versions.update(surface.expected_versions)
            available_source_kinds.update(
                state.source_kind for state in surface.source_kinds if state.registered
            )
            remediation: list[str] = []
            cells: list[PublicCoverageNavigatorCellResponse] = []
            for state in surface.source_kinds:
                if state.ready:
                    status = "ready"
                elif state.registered:
                    status = "gap"
                else:
                    status = "missing"
                cells.append(
                    PublicCoverageNavigatorCellResponse(
                        source_kind=state.source_kind,
                        status=status,
                        active_versions=state.active_versions or state.supported_versions,
                        service_reason=state.service_reasons[0] if state.service_reasons else None,
                    )
                )
                if status == "gap":
                    remediation.append(
                        "Publish an active "
                        f"{state.source_kind} snapshot for "
                        f"{surface.programming_language}."
                    )
                elif status == "missing":
                    remediation.append(
                        "Onboard the "
                        f"{state.source_kind} repository before relying "
                        "on MCP for this scope."
                    )
            if surface.executable_snippets_count <= 0:
                remediation.append(
                    "Add executable snippets or rely on cited API docs before code generation."
                )
            if not surface.latest_stable_visible:
                remediation.append(
                    "Check release freshness before using latest-stable prompts for this scope."
                )
            surfaces.append(
                PublicCoverageNavigatorSurfaceResponse(
                    surface_id=surface.surface_id,
                    product_id=surface.product_id,
                    product_name=surface.product_name,
                    product_family=surface.product_family,
                    programming_language=surface.programming_language,
                    overall_status=surface.status,
                    onboarding_priority=surface.onboarding_priority,
                    latest_visible_versions=surface.expected_versions,
                    executable_snippets_count=surface.executable_snippets_count,
                    gap_badges=surface.gap_badges,
                    summary=surface.summary,
                    remediation=list(dict.fromkeys(remediation)),
                    cells=cells,
                    actions=_build_public_surface_actions(
                        product_id=surface.product_id,
                        programming_language=surface.programming_language,
                        source_kind=source_kind,
                        version=version,
                    ),
                )
            )

    surfaces.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.onboarding_priority, 9),
            {"registered_only": 0, "partial": 1, "ready": 2}.get(item.overall_status, 9),
            item.product_id.casefold(),
            item.programming_language.casefold(),
        )
    )
    ready_total = sum(1 for item in surfaces if item.overall_status == "ready")
    partial_total = sum(1 for item in surfaces if item.overall_status == "partial")
    registered_only_total = sum(
        1 for item in surfaces if item.overall_status == "registered_only"
    )
    if surfaces:
        status_summary = (
            f"Navigator surfaced {len(surfaces)} scope row(s): ready={ready_total}, "
            f"partial={partial_total}, registered_only={registered_only_total}."
        )
    else:
        status_summary = "No navigator rows matched the current public filter set."

    return PublicCoverageNavigatorResponse(
        filters={
            "product_id": product_id,
            "programming_language": programming_language,
            "source_kind": source_kind,
            "version": version,
        },
        products_total=coverage.products_total,
        surfaces_total=len(surfaces),
        ready_total=ready_total,
        partial_total=partial_total,
        registered_only_total=registered_only_total,
        available_products=sorted(available_products),
        available_programming_languages=sorted(available_programming_languages),
        available_source_kinds=sorted(available_source_kinds),
        available_versions=sorted(available_versions, key=_public_version_sort_key),
        status_summary=status_summary,
        surfaces=surfaces,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_capability_explorer(
    request: Request,
    *,
    product_id: str | None,
    programming_language: str | None,
    source_kind: str | None,
    version: str | None,
) -> PublicCapabilityExplorerResponse:
    coverage = _build_public_coverage_gap_tracker(
        request,
        product_id=product_id,
        programming_language=programming_language,
        source_kind=source_kind,
        version=version,
    )
    snippet_explorer = _build_public_snippet_explorer(
        request,
        product_id=product_id,
        programming_language=programming_language,
        version=version,
        source_kind=source_kind,
        limit=24,
    )
    freshness = (
        _build_public_release_freshness(
            request,
            product_id=product_id,
            programming_language=programming_language,
            version=version,
            top_k=4,
        )
        if product_id
        else None
    )

    snippet_titles_by_surface: dict[tuple[str, str], list[str]] = {}
    for item in snippet_explorer.items:
        surface_key = (item.product_id.casefold(), item.programming_language.casefold())
        titles = snippet_titles_by_surface.setdefault(surface_key, [])
        if item.title not in titles:
            titles.append(item.title)
        if len(titles) >= 3:
            snippet_titles_by_surface[surface_key] = titles[:3]

    freshness_label: str | None = None
    resolved_version = freshness.resolved_version if freshness else None
    newest_available_version = freshness.newest_available_version if freshness else None
    if freshness is not None:
        if freshness.latest_active_snapshot_at is None:
            freshness_label = "not-ready"
        elif (
            freshness.resolved_version
            and freshness.newest_available_version
            and freshness.resolved_version != freshness.newest_available_version
        ):
            freshness_label = "watch-now"
        elif len(freshness.release_features) <= 0:
            freshness_label = "monitor"
        else:
            freshness_label = "fresh"

    items: list[PublicCapabilityItemResponse] = []
    available_programming_languages: set[str] = set()
    available_source_kinds: set[str] = set()
    for product in coverage.products:
        for surface in product.surfaces:
            available_programming_languages.add(surface.programming_language)
            available_source_kinds.update(surface.registered_source_kinds)
            surface_freshness = freshness_label
            if not surface.latest_stable_visible:
                surface_freshness = "not-ready"
            items.append(
                PublicCapabilityItemResponse(
                    capability_id=surface.surface_id,
                    product_id=surface.product_id,
                    product_name=surface.product_name,
                    product_family=surface.product_family,
                    programming_language=surface.programming_language,
                    status=surface.status,
                    onboarding_priority=surface.onboarding_priority,
                    latest_stable_visible=surface.latest_stable_visible,
                    freshness_label=surface_freshness,
                    resolved_version=resolved_version,
                    newest_available_version=newest_available_version,
                    executable_snippets_count=surface.executable_snippets_count,
                    registered_source_kinds=surface.registered_source_kinds,
                    ready_source_kinds=surface.ready_source_kinds,
                    gap_badges=surface.gap_badges,
                    summary=surface.summary,
                    snippet_titles=snippet_titles_by_surface.get(
                        (surface.product_id.casefold(), surface.programming_language.casefold()),
                        [],
                    ),
                    actions=_build_public_surface_actions(
                        product_id=surface.product_id,
                        programming_language=surface.programming_language,
                        source_kind=source_kind,
                        version=version,
                    ),
                )
            )

    items.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.onboarding_priority, 9),
            {"registered_only": 0, "partial": 1, "ready": 2}.get(item.status, 9),
            item.product_id.casefold(),
            item.programming_language.casefold(),
        )
    )
    ready_total = sum(1 for item in items if item.status == "ready")
    partial_total = sum(1 for item in items if item.status == "partial")
    gap_total = sum(1 for item in items if item.status == "registered_only")
    if items:
        status_summary = (
            f"Capability explorer surfaced {ready_total} ready, {partial_total} partial, "
            f"and {gap_total} registered-only surface(s) for the current public scope."
        )
    else:
        status_summary = "No capability surfaces matched the current filter set."

    return PublicCapabilityExplorerResponse(
        filters={
            "product_id": product_id,
            "programming_language": programming_language,
            "source_kind": source_kind,
            "version": version,
        },
        products_total=coverage.products_total,
        capabilities_total=len(items),
        ready_total=ready_total,
        partial_total=partial_total,
        gap_total=gap_total,
        available_programming_languages=sorted(available_programming_languages, key=str.casefold),
        available_source_kinds=sorted(available_source_kinds, key=str.casefold),
        status_summary=status_summary,
        items=items,
        generated_at=datetime.now(tz=UTC),
    )


def _clamp_trust_score(value: int) -> int:
    return max(0, min(100, value))


def _trust_score_status(score: int) -> str:
    if score >= 80:
        return "strong"
    if score >= 55:
        return "watch"
    return "weak"


def _build_public_trust_signals_board(
    request: Request,
    *,
    product_id: str,
    programming_language: str | None,
    version: str | None,
) -> PublicTrustSignalsBoardResponse:
    coverage = _build_public_coverage_navigator(
        request,
        product_id=product_id,
        programming_language=programming_language,
        source_kind=None,
        version=version,
    )
    freshness = _build_public_release_freshness(
        request,
        product_id=product_id,
        programming_language=programming_language,
        version=version,
        top_k=6,
    )
    analytics_service = _analytics_service(request)
    feedback_summary = (
        analytics_service.usefulness_summary(
            product_id=product_id,
            programming_language=programming_language,
        )
        if analytics_service is not None
        else None
    )
    issue_records = (
        analytics_service.list_issue_reports(
            product_id=product_id,
            programming_language=programming_language,
            limit=5,
        )
        if analytics_service is not None
        else ()
    )

    selected_surface = next(
        (
            item
            for item in coverage.surfaces
            if item.product_id == product_id
            and (
                programming_language is None
                or item.programming_language == programming_language
            )
        ),
        coverage.surfaces[0] if coverage.surfaces else None,
    )

    scorecards: list[PublicTrustSignalScorecardResponse] = []

    if selected_surface is None:
        readiness_score = 20
        readiness_summary = (
            "No public-ready scope row was found for the selected product/language filter."
        )
        readiness_evidence = [
            f"navigator_surfaces={coverage.surfaces_total}",
            "selected_scope=missing",
            "mcp_readiness=unknown",
        ]
        readiness_actions = [
            PublicCapabilityActionResponse(
                label="Open coverage navigator",
                href=_build_public_scope_link(
                    product_id=product_id,
                    programming_language=programming_language,
                    source_kind=None,
                    version=version,
                    anchor="#coverage-navigator",
                ),
            )
        ]
    else:
        readiness_score = {
            "ready": 92,
            "partial": 66,
            "registered_only": 34,
        }.get(selected_surface.overall_status, 45)
        if selected_surface.executable_snippets_count <= 0:
            readiness_score -= 8
        if not selected_surface.latest_visible_versions:
            readiness_score -= 10
        if any(cell.status == "missing" for cell in selected_surface.cells):
            readiness_score -= 12
        readiness_summary = selected_surface.summary
        readiness_evidence = [
            f"overall_status={selected_surface.overall_status}",
            "cells="
            + ", ".join(
                f"{cell.source_kind}:{cell.status}" for cell in selected_surface.cells
            ),
            "latest_versions="
            + (
                ", ".join(selected_surface.latest_visible_versions)
                if selected_surface.latest_visible_versions
                else "none"
            ),
            f"executable_snippets={selected_surface.executable_snippets_count}",
        ]
        readiness_actions = selected_surface.actions[:3]

    readiness_score = _clamp_trust_score(readiness_score)
    scorecards.append(
        PublicTrustSignalScorecardResponse(
            signal_id="readiness",
            title="Scope readiness",
            status=_trust_score_status(readiness_score),
            score=readiness_score,
            summary=readiness_summary,
            evidence=readiness_evidence,
            actions=readiness_actions,
        )
    )

    freshness_score = 52
    if freshness.latest_active_snapshot_at is None:
        freshness_score = 24
    elif (
        freshness.resolved_version
        and freshness.newest_available_version
        and freshness.resolved_version != freshness.newest_available_version
    ):
        freshness_score = 58
    elif len(freshness.release_features) <= 0:
        freshness_score = 70
    else:
        freshness_score = 90
    if any(not item.mcp_ready for item in freshness.services):
        freshness_score -= 8
    freshness_score = _clamp_trust_score(freshness_score)
    scorecards.append(
        PublicTrustSignalScorecardResponse(
            signal_id="freshness",
            title="Release freshness",
            status=_trust_score_status(freshness_score),
            score=freshness_score,
            summary=freshness.status_summary,
            evidence=[
                f"resolved_version={freshness.resolved_version or 'none'}",
                f"newest_visible_version={freshness.newest_available_version or 'none'}",
                f"release_features={len(freshness.release_features)}",
                "latest_snapshot="
                + (
                    freshness.latest_active_snapshot_at.isoformat()
                    if freshness.latest_active_snapshot_at is not None
                    else "none"
                ),
            ],
            actions=[
                PublicCapabilityActionResponse(
                    label="Open release freshness",
                    href=_build_public_scope_link(
                        product_id=product_id,
                        programming_language=programming_language,
                        source_kind=None,
                        version=version,
                        anchor="#release-freshness",
                    ),
                ),
                PublicCapabilityActionResponse(
                    label="Open upgrade assistant",
                    href=_build_public_scope_link(
                        product_id=product_id,
                        programming_language=programming_language,
                        source_kind=None,
                        version=version,
                        anchor="#upgrade-assistant",
                    ),
                ),
            ],
        )
    )

    feedback_score = 58
    feedback_summary_text = (
        "No public usefulness feedback has been recorded for this scope yet."
    )
    feedback_evidence = [
        "feedback_total=0",
        "useful_share=n/a",
        "negative_share=n/a",
        f"issue_reports={len(issue_records)}",
    ]
    if feedback_summary is not None:
        feedback_total = feedback_summary.total_feedback
        issue_total = len(issue_records)
        if feedback_total > 0:
            feedback_score = int(round(feedback_summary.useful_share * 100))
            feedback_score -= int(round(feedback_summary.negative_share * 35))
            feedback_score -= min(issue_total, 5) * 5
            feedback_summary_text = (
                f"Public developers left {feedback_total} usefulness signal(s) for this "
                "scope. Use the negative reasons and issue intake to decide whether the "
                "problem is accuracy, freshness, or missing content."
            )
        elif issue_total > 0:
            feedback_score = 42
            feedback_summary_text = (
                "Public issue intake exists for this scope, but usefulness feedback is still "
                "sparse. Treat the trust signal as provisional."
            )
        feedback_evidence = [
            f"feedback_total={feedback_total}",
            f"useful_share={feedback_summary.useful_share:.2f}",
            f"negative_share={feedback_summary.negative_share:.2f}",
            f"issue_reports={issue_total}",
        ]
        if feedback_summary.by_reason_code:
            top_reason = max(
                feedback_summary.by_reason_code.items(),
                key=lambda item: item[1],
            )[0]
            feedback_evidence.append(f"top_negative_reason={top_reason}")
    feedback_score = _clamp_trust_score(feedback_score)
    scorecards.append(
        PublicTrustSignalScorecardResponse(
            signal_id="feedback",
            title="Developer feedback",
            status=_trust_score_status(feedback_score),
            score=feedback_score,
            summary=feedback_summary_text,
            evidence=feedback_evidence,
            actions=[
                PublicCapabilityActionResponse(
                    label="Open public playground",
                    href=_build_public_scope_link(
                        product_id=product_id,
                        programming_language=programming_language,
                        source_kind=None,
                        version=version,
                        anchor="#public-playground",
                    ),
                ),
                PublicCapabilityActionResponse(
                    label="Open content triage",
                    href=_build_public_scope_link(
                        product_id=product_id,
                        programming_language=programming_language,
                        source_kind=None,
                        version=version,
                        anchor="#content-triage",
                    ),
                ),
            ],
        )
    )

    strong_total = sum(1 for item in scorecards if item.status == "strong")
    watch_total = sum(1 for item in scorecards if item.status == "watch")
    weak_total = sum(1 for item in scorecards if item.status == "weak")

    if weak_total > 0:
        trust_posture = "investigate"
        status_summary = (
            "One or more trust signals are weak. Validate readiness gaps, release freshness, "
            "or developer feedback before treating this MCP scope as production-safe."
        )
    elif watch_total >= 2:
        trust_posture = "guarded"
        status_summary = (
            "The trust board is usable but still guarded. The current scope works, yet at least "
            "two evidence areas still need operator attention."
        )
    else:
        trust_posture = "high"
        status_summary = (
            "Trust signals are strong for this scope. You still have direct links to the "
            "underlying evidence if you want to verify the claim before coding."
        )

    return PublicTrustSignalsBoardResponse(
        product_id=product_id,
        programming_language=programming_language,
        requested_version=version,
        resolved_version=freshness.resolved_version,
        trust_posture=trust_posture,
        strong_total=strong_total,
        watch_total=watch_total,
        weak_total=weak_total,
        status_summary=status_summary,
        explainability=[
            "Scope readiness comes from live docs/API-reference publish "
            "coverage for the selected scope.",
            "Release freshness compares the newest visible version with the "
            "currently active snapshot.",
            "Developer feedback rolls up public usefulness ratings and issue "
            "intake for the selected scope.",
        ],
        scorecards=scorecards,
        generated_at=datetime.now(tz=UTC),
    )


def _average_signal_score(
    board: PublicTrustSignalsBoardResponse,
) -> float:
    if not board.scorecards:
        return 0.0
    return round(
        sum(item.score for item in board.scorecards) / len(board.scorecards),
        2,
    )


def _trust_scorecard(
    board: PublicTrustSignalsBoardResponse,
    signal_id: str,
) -> PublicTrustSignalScorecardResponse:
    for item in board.scorecards:
        if item.signal_id == signal_id:
            return item
    return PublicTrustSignalScorecardResponse(
        signal_id=signal_id,
        title=signal_id.replace("_", " ").title(),
        status="weak",
        score=0,
        summary="No evidence was generated for this signal.",
        evidence=["missing_signal"],
        actions=[],
    )


def _coverage_surface_for_scope(
    coverage: PublicCoverageNavigatorResponse,
    *,
    product_id: str,
    programming_language: str | None,
) -> PublicCoverageNavigatorSurfaceResponse | None:
    return next(
        (
            item
            for item in coverage.surfaces
            if item.product_id == product_id
            and (
                programming_language is None
                or item.programming_language == programming_language
            )
        ),
        coverage.surfaces[0] if coverage.surfaces else None,
    )


def _build_public_scope_compare_board(
    request: Request,
    *,
    left_product_id: str,
    left_programming_language: str | None,
    left_version: str | None,
    left_source_kind: str | None,
    right_product_id: str,
    right_programming_language: str | None,
    right_version: str | None,
    right_source_kind: str | None,
) -> PublicScopeCompareBoardResponse:
    left_board = _build_public_trust_signals_board(
        request,
        product_id=left_product_id,
        programming_language=left_programming_language,
        version=left_version,
    )
    right_board = _build_public_trust_signals_board(
        request,
        product_id=right_product_id,
        programming_language=right_programming_language,
        version=right_version,
    )
    left_coverage = _build_public_coverage_navigator(
        request,
        product_id=left_product_id,
        programming_language=left_programming_language,
        source_kind=left_source_kind,
        version=left_version,
    )
    right_coverage = _build_public_coverage_navigator(
        request,
        product_id=right_product_id,
        programming_language=right_programming_language,
        source_kind=right_source_kind,
        version=right_version,
    )
    left_surface = _coverage_surface_for_scope(
        left_coverage,
        product_id=left_product_id,
        programming_language=left_programming_language,
    )
    right_surface = _coverage_surface_for_scope(
        right_coverage,
        product_id=right_product_id,
        programming_language=right_programming_language,
    )

    metrics: list[PublicScopeCompareMetricResponse] = []
    for signal_id, title, anchor in (
        ("readiness", "Scope readiness", "#coverage-navigator"),
        ("freshness", "Release freshness", "#release-freshness"),
        ("feedback", "Developer feedback", "#public-playground"),
    ):
        left_card = _trust_scorecard(left_board, signal_id)
        right_card = _trust_scorecard(right_board, signal_id)
        if left_card.score > right_card.score:
            preferred_side = "left"
        elif right_card.score > left_card.score:
            preferred_side = "right"
        else:
            preferred_side = "tie"
        if preferred_side == "tie":
            summary = (
                f"Both scopes expose the same {title.lower()} score, so use the evidence links "
                "to inspect the underlying differences before deciding."
            )
        else:
            summary = (
                f"{'Primary' if preferred_side == 'left' else 'Compared'} scope is stronger for "
                f"{title.lower()}."
            )
        metrics.append(
            PublicScopeCompareMetricResponse(
                metric_id=signal_id,
                title=title,
                preferred_side=preferred_side,
                summary=summary,
                left_score=left_card.score,
                right_score=right_card.score,
                left_status=left_card.status,
                right_status=right_card.status,
                left_evidence=left_card.evidence,
                right_evidence=right_card.evidence,
                left_href=_build_public_scope_link(
                    product_id=left_product_id,
                    programming_language=left_programming_language,
                    source_kind=left_source_kind,
                    version=left_version,
                    anchor=anchor,
                ),
                right_href=_build_public_scope_link(
                    product_id=right_product_id,
                    programming_language=right_programming_language,
                    source_kind=right_source_kind,
                    version=right_version,
                    anchor=anchor,
                ),
            )
        )

    left_snippets = left_surface.executable_snippets_count if left_surface is not None else 0
    right_snippets = (
        right_surface.executable_snippets_count if right_surface is not None else 0
    )
    if left_snippets > right_snippets:
        snippet_preferred_side = "left"
    elif right_snippets > left_snippets:
        snippet_preferred_side = "right"
    else:
        snippet_preferred_side = "tie"
    metrics.append(
        PublicScopeCompareMetricResponse(
            metric_id="snippet_evidence",
            title="Executable snippet evidence",
            preferred_side=snippet_preferred_side,
            summary=(
                "Higher snippet density usually makes the public MCP scope easier to trust for "
                "copy-ready code generation."
            ),
            left_score=float(left_snippets),
            right_score=float(right_snippets),
            left_status=(
                "strong" if left_snippets > 0 else "weak"
            ),
            right_status=(
                "strong" if right_snippets > 0 else "weak"
            ),
            left_evidence=[f"executable_snippets={left_snippets}"],
            right_evidence=[f"executable_snippets={right_snippets}"],
            left_href=_build_public_scope_link(
                product_id=left_product_id,
                programming_language=left_programming_language,
                source_kind=left_source_kind,
                version=left_version,
                anchor="#snippet-explorer",
            ),
            right_href=_build_public_scope_link(
                product_id=right_product_id,
                programming_language=right_programming_language,
                source_kind=right_source_kind,
                version=right_version,
                anchor="#snippet-explorer",
            ),
        )
    )

    left_average = _average_signal_score(left_board)
    right_average = _average_signal_score(right_board)
    if left_average > right_average:
        preferred_side = "left"
    elif right_average > left_average:
        preferred_side = "right"
    else:
        preferred_side = "tie"

    if preferred_side == "tie":
        status_summary = (
            "Both scopes are closely matched. Use the per-metric evidence links to decide "
            "which SDK/version is safer for your task."
        )
    else:
        status_summary = (
            f"{'Primary' if preferred_side == 'left' else 'Compared'} scope looks stronger overall "
            "for current MCP adoption signals."
        )

    return PublicScopeCompareBoardResponse(
        preferred_side=preferred_side,
        status_summary=status_summary,
        explainability=[
            "The compare board reuses the same public trust, readiness, "
            "freshness, and snippet evidence shown elsewhere in the portal.",
            "Use preferred-side badges as a shortcut only; the evidence "
            "bullets and deep links remain the source of truth.",
        ],
        left_scope=PublicScopeCompareSummaryResponse(
            product_id=left_product_id,
            programming_language=left_programming_language,
            requested_version=left_version,
            resolved_version=left_board.resolved_version,
            trust_posture=left_board.trust_posture,
            average_signal_score=left_average,
            executable_snippets_count=left_snippets,
            summary=left_board.status_summary,
        ),
        right_scope=PublicScopeCompareSummaryResponse(
            product_id=right_product_id,
            programming_language=right_programming_language,
            requested_version=right_version,
            resolved_version=right_board.resolved_version,
            trust_posture=right_board.trust_posture,
            average_signal_score=right_average,
            executable_snippets_count=right_snippets,
            summary=right_board.status_summary,
        ),
        metrics=metrics,
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_troubleshooting(
    request: Request,
    *,
    product_id: str,
    programming_language: str | None,
    client_id: str,
    transport: str,
    request_id: str | None,
) -> PublicTroubleshootingResponse:
    self_test = _build_public_mcp_self_test(
        request,
        product_id=product_id,
        programming_language=programming_language,
        client_id=client_id,
        transport=transport,
    )
    triage = _build_public_content_triage(
        request,
        product_id=product_id,
        repo_id=None,
        severity=None,
        source_kind=None,
        stale_after_days=30,
        limit=12,
    )
    paths: list[PublicTroubleshootingPathResponse] = []

    if self_test.status != "ready":
        paths.append(
            PublicTroubleshootingPathResponse(
                path_id="connection-readiness",
                title="Connection and readiness recovery",
                severity="error" if self_test.status == "not_ready" else "warning",
                summary=self_test.status_summary,
                match_reason=(
                    "The MCP self-test is not fully ready for the selected client/transport scope."
                ),
                evidence=[
                    f"self_test={self_test.status}",
                    f"ready_services={self_test.total_ready_services}/{self_test.total_registered_services}",
                    f"snippet_count={self_test.snippet_count}",
                ],
                fix_plan=self_test.fix_plan,
                copy_block_label="Copy self-test fix plan",
                copy_block_text="\n".join(
                    [
                        "Troubleshooting scope: "
                        f"{product_id} / {programming_language or 'auto'} / "
                        f"{client_id} / {transport}",
                        *[f"{index + 1}. {step}" for index, step in enumerate(self_test.fix_plan)],
                    ]
                ),
                actions=[
                    PublicTroubleshootingActionResponse(
                        label="Open self-test",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=programming_language,
                            version=None,
                            source_kind=None,
                            anchor="#self-test",
                        ),
                    ),
                    PublicTroubleshootingActionResponse(
                        label="Open starter packs",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=programming_language,
                            version=None,
                            source_kind=None,
                            anchor="#starter-packs",
                        ),
                    ),
                ],
            )
        )

    if triage.critical_total > 0 or triage.warning_total > 0:
        fix_plan = list(
            dict.fromkeys(
                step
                for item in triage.items[:4]
                for step in item.fix_plan
            )
        )
        paths.append(
            PublicTroubleshootingPathResponse(
                path_id="content-coverage-gap",
                title="Content coverage and freshness gap recovery",
                severity="error" if triage.critical_total > 0 else "warning",
                summary=triage.status_summary,
                match_reason=(
                    "Public triage signals show stale, missing, or "
                    "not-yet-ready content for this scope."
                ),
                evidence=[
                    f"critical_gaps={triage.critical_total}",
                    f"warning_gaps={triage.warning_total}",
                    f"top_repo={triage.items[0].repo_id if triage.items else 'none'}",
                ],
                fix_plan=fix_plan
                or [
                    "Inspect the highest-severity gap first.",
                    "Re-run ingestion or publish for the missing source kind.",
                ],
                copy_block_label="Copy content-gap handoff",
                copy_block_text="\n".join(
                    [
                        f"Triage summary: {triage.status_summary}",
                        *[
                            f"- {item.repo_id} / {item.signal_type}: {item.summary}"
                            for item in triage.items[:4]
                        ],
                    ]
                ),
                actions=[
                    PublicTroubleshootingActionResponse(
                        label="Open content triage",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=programming_language,
                            version=None,
                            source_kind=None,
                            anchor="#content-triage",
                        ),
                    ),
                    PublicTroubleshootingActionResponse(
                        label="Open capability explorer",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=programming_language,
                            version=None,
                            source_kind=None,
                            anchor="#capability-explorer",
                        ),
                    ),
                ],
            )
        )

    request_diagnostics: dict[str, str | int | float | None] = {
        "request_id": request_id,
        "outcome": None,
        "result_count": None,
        "confidence": None,
        "zero_result_reason": None,
        "fallback_reason": None,
        "feedback_total": 0,
        "issue_total": 0,
    }
    analytics_service = _analytics_service(request)
    if request_id and analytics_service is not None:
        record = analytics_service.get_record(request_id)
        if record is not None:
            feedback_records = analytics_service.list_usefulness_feedback(request_id=request_id)
            issue_records = analytics_service.list_issue_reports(request_id=request_id)
            request_diagnostics = {
                "request_id": request_id,
                "outcome": record.outcome,
                "result_count": record.result_count,
                "confidence": round(record.confidence, 3),
                "zero_result_reason": record.zero_result_reason,
                "fallback_reason": record.fallback_reason,
                "feedback_total": len(feedback_records),
                "issue_total": len(issue_records),
            }
            if (
                record.result_count <= 0
                or record.confidence < 0.6
                or record.zero_result_reason is not None
                or record.fallback_reason is not None
                or record.warning_codes
            ):
                request_fix_plan = [
                    "Replay the request in the public query playground and inspect "
                    "the current citations first.",
                    "Classify the issue as connection/runtime, content gap, or "
                    "low-confidence retrieval before changing code.",
                    "If the issue is reproducible, share the repro link with "
                    "support or the product owner.",
                ]
                if record.zero_result_reason:
                    request_fix_plan.append(
                        "Zero-result reason: "
                        f"{record.zero_result_reason}. Start by validating "
                        "source coverage for the current scope."
                    )
                if record.fallback_reason:
                    request_fix_plan.append(
                        "Fallback reason: "
                        f"{record.fallback_reason}. Re-check version and "
                        "language hints in the selected scope."
                    )
                share_url = _build_public_shared_request_link(
                    request=request,
                    request_id=request_id,
                )
                paths.append(
                    PublicTroubleshootingPathResponse(
                        path_id="request-quality-recovery",
                        title="Request-quality recovery",
                        severity=(
                            "error"
                            if record.result_count <= 0 or record.outcome == "not_ready"
                            else "warning"
                        ),
                        summary=(
                            "The referenced public request shows low-confidence, "
                            "zero-result, or fallback-heavy retrieval behavior."
                        ),
                        match_reason=(
                            "A concrete request_id was provided and its "
                            "analytics history indicates a problematic public answer."
                        ),
                        evidence=[
                            f"request_id={request_id}",
                            f"outcome={record.outcome}",
                            f"result_count={record.result_count}",
                            f"confidence={record.confidence:.2f}",
                            f"warnings={len(record.warning_codes)}",
                        ],
                        fix_plan=request_fix_plan,
                        copy_block_label="Copy escalation handoff",
                        copy_block_text="\n".join(
                            [
                                f"request_id={request_id}",
                                f"outcome={record.outcome}",
                                f"result_count={record.result_count}",
                                f"confidence={record.confidence:.2f}",
                                f"zero_result_reason={record.zero_result_reason or 'none'}",
                                f"fallback_reason={record.fallback_reason or 'none'}",
                                f"feedback_total={len(feedback_records)}",
                                f"issue_total={len(issue_records)}",
                                f"share_url={share_url}",
                            ]
                        ),
                        actions=[
                            PublicTroubleshootingActionResponse(
                                label="Open public playground",
                                href=_build_public_scope_link(
                                    product_id=record.product_id,
                                    programming_language=record.programming_language,
                                    version=None,
                                    source_kind=None,
                                    anchor="#public-playground",
                                ),
                            ),
                            PublicTroubleshootingActionResponse(
                                label="Open shared request",
                                href=_build_public_shared_request_link(
                                    request=request,
                                    request_id=request_id,
                                ),
                            ),
                        ],
                    )
                )

    if not paths:
        paths.append(
            PublicTroubleshootingPathResponse(
                path_id="no-active-issues",
                title="No active public troubleshooting blockers",
                severity="info",
                summary=(
                    "No blocking self-test, content-gap, or request-quality "
                    "issues are currently visible."
                ),
                match_reason=(
                    "The selected scope is public-ready and no failing request "
                    "evidence was supplied."
                ),
                evidence=[
                    f"self_test={self_test.status}",
                    f"critical_gaps={triage.critical_total}",
                    f"warning_gaps={triage.warning_total}",
                ],
                fix_plan=[
                    "Use guided journeys or starter packs for the next task.",
                    "Run a fresh public query before escalating anything.",
                ],
                copy_block_label=None,
                copy_block_text=None,
                actions=[
                    PublicTroubleshootingActionResponse(
                        label="Open guided journeys",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=programming_language,
                            version=None,
                            source_kind=None,
                            anchor="#guided-journeys",
                        ),
                    ),
                ],
            )
        )

    status_summary = (
        f"Troubleshooting surfaced {len(paths)} path(s) for {product_id} / "
        f"{programming_language or 'auto'} / {client_id}."
    )
    return PublicTroubleshootingResponse(
        filters={
            "product_id": product_id,
            "programming_language": programming_language,
            "client_id": client_id,
            "transport": transport,
            "request_id": request_id,
        },
        status_summary=status_summary,
        self_test_status=self_test.status,
        critical_gap_total=triage.critical_total,
        warning_gap_total=triage.warning_total,
        request_diagnostics=request_diagnostics,
        paths=paths,
        generated_at=datetime.now(tz=UTC),
    )


def _fallback_latest_release_response(
    *,
    freshness: PublicReleaseFreshnessResponse,
    product_id: str,
    programming_language: str,
    version: str | None,
) -> ListLatestReleaseFeaturesResponse:
    resolved_version = (
        freshness.newest_available_version
        or freshness.resolved_version
        or version
        or "latest-stable"
    )
    return ListLatestReleaseFeaturesResponse(
        product_id=product_id,
        language=programming_language,
        resolved_version=resolved_version,
        items=[
            ReleaseFeatureItemResponse(
                kind=item.kind,
                summary=item.summary,
                symbol_fqn=item.symbol_fqn,
                version=item.version,
                source_kind=item.source_kind,
                citation=ReleaseFeatureCitationResponse(
                    canonical_url=item.canonical_url,
                    section_anchor=item.section_anchor,
                ),
            )
            for item in freshness.release_features[:6]
        ],
        guardrails=[
            "Validate changed APIs with get_symbol_doc before generating upgrade code.",
            "Inspect freshness and content readiness if release signals look incomplete.",
        ],
    )


def _build_public_release_adoption(
    request: Request,
    *,
    product_id: str,
    programming_language: str,
    version: str | None,
) -> PublicReleaseAdoptionResponse:
    freshness = _build_public_release_freshness(
        request,
        product_id=product_id,
        programming_language=programming_language,
        version=version,
        top_k=6,
    )
    recommended_to_version = (
        freshness.newest_available_version
        or freshness.resolved_version
        or version
    )
    recommended_from_version: str | None = None
    if version and version != recommended_to_version:
        recommended_from_version = version
    else:
        for candidate in freshness.available_versions:
            if candidate and candidate != recommended_to_version:
                recommended_from_version = candidate
                break

    service = _public_query_service(request)
    try:
        latest_release = service.list_latest_release_features(
            request=ListLatestReleaseFeaturesRequest(
                product_id=product_id,
                language=programming_language,
                version=recommended_to_version,
                top_k=6,
            )
        )
    except LookupError:
        latest_release = _fallback_latest_release_response(
            freshness=freshness,
            product_id=product_id,
            programming_language=programming_language,
            version=recommended_to_version,
        )

    if recommended_from_version and recommended_to_version:
        breaking_changes = service.list_breaking_changes(
            request=ListBreakingChangesRequest(
                product_id=product_id,
                language=programming_language,
                from_version=recommended_from_version,
                to_version=recommended_to_version,
                page=1,
                page_size=6,
            )
        )
    else:
        breaking_changes = ListBreakingChangesResponse(
            items=[],
            page=1,
            page_size=6,
            total=0,
        )

    compare_ranges: list[PublicReleaseAdoptionRangeResponse] = []
    target_version = recommended_to_version or latest_release.resolved_version
    if target_version:
        for from_version in freshness.available_versions[:6]:
            if from_version == target_version:
                continue
            diff = service.list_breaking_changes(
                request=ListBreakingChangesRequest(
                    product_id=product_id,
                    language=programming_language,
                    from_version=from_version,
                    to_version=target_version,
                    page=1,
                    page_size=1,
                )
            )
            range_status = (
                "ready"
                if diff.total == 0
                else "watch"
                if diff.total <= 3
                else "attention"
            )
            compare_ranges.append(
                PublicReleaseAdoptionRangeResponse(
                    range_id=f"{from_version}-to-{target_version}",
                    from_version=from_version,
                    to_version=target_version,
                    breaking_changes_total=diff.total,
                    status=range_status,
                    summary=(
                        f"Compare {from_version} -> {target_version} before switching "
                        "production prompts or generated code."
                    ),
                )
            )

    if (
        freshness.latest_active_snapshot_at is None
        or freshness.newest_available_version is None
    ):
        status = "blocked"
        freshness_label = "not-ready"
    elif recommended_to_version != freshness.resolved_version or breaking_changes.total > 0:
        status = "watch"
        freshness_label = "watch"
    else:
        status = "ready"
        freshness_label = "fresh"

    migration_checklist = [
        (
            f"Validate the target release scope "
            f"`{recommended_to_version or 'latest-stable'}` before changing code."
        ),
        (
            f"Review {breaking_changes.total} breaking change(s) between "
            f"`{recommended_from_version or 'current'}` and "
            f"`{recommended_to_version or 'target'}`."
        ),
        "Confirm the latest release features are cited and still MCP-ready.",
        "Re-run the public query playground after the upgrade plan is drafted.",
        *latest_release.guardrails[:2],
    ]
    fix_plan = [
        (
            "Start from the recommended range and only then open the upgrade assistant "
            "for a detailed migration brief."
        ),
        (
            "If the newest release is visible but not fully ready, validate freshness "
            "and MCP readiness before switching prompts."
        ),
        (
            "Treat breaking-change-heavy ranges as review-first migrations, not direct "
            "code regeneration tasks."
        ),
    ]
    upgrade_prompt = " ".join(
        [
            f"Use Aspose MCP to upgrade `{product_id}` in `{programming_language}`",
            f"from `{recommended_from_version or 'current'}` to "
            f"`{recommended_to_version or 'latest-stable'}`.",
            "First list the latest release features and breaking changes with citations.",
            "Then produce a migration checklist, exact symbol validation steps, and a "
            "minimal safe-upgrade code sketch.",
            "Call out any freshness drift, fallback versioning, or missing coverage "
            "before final code.",
        ]
    )
    status_summary = (
        f"Release adoption for {product_id} / {programming_language}: "
        f"target={recommended_to_version or 'unknown'}, "
        f"breaking_changes={breaking_changes.total}, "
        f"release_features={len(latest_release.items)}, "
        f"freshness={freshness_label}."
    )

    return PublicReleaseAdoptionResponse(
        product_id=product_id,
        programming_language=programming_language,
        requested_version=version,
        resolved_version=freshness.resolved_version,
        newest_available_version=freshness.newest_available_version,
        recommended_from_version=recommended_from_version,
        recommended_to_version=recommended_to_version,
        status=status,
        freshness_label=freshness_label,
        status_summary=status_summary,
        latest_active_snapshot_at=freshness.latest_active_snapshot_at,
        migration_checklist=migration_checklist,
        upgrade_prompt=upgrade_prompt,
        fix_plan=fix_plan,
        compare_ranges=compare_ranges,
        latest_release=latest_release,
        breaking_changes=breaking_changes,
        actions=[
            PublicTroubleshootingActionResponse(
                label="Open release freshness",
                href=_build_public_scope_link(
                    product_id=product_id,
                    programming_language=programming_language,
                    version=version,
                    source_kind=None,
                    anchor="#release-freshness",
                ),
            ),
            PublicTroubleshootingActionResponse(
                label="Open upgrade assistant",
                href=_build_public_scope_link(
                    product_id=product_id,
                    programming_language=programming_language,
                    version=version,
                    source_kind=None,
                    anchor="#upgrade-assistant",
                ),
            ),
        ],
        generated_at=datetime.now(tz=UTC),
    )


def _build_public_use_case_gallery(
    request: Request,
    *,
    product_id: str,
    programming_language: str | None,
    client_id: str,
    status_filter: str | None,
) -> PublicUseCaseGalleryResponse:
    language = programming_language or "net"
    self_test = _build_public_mcp_self_test(
        request,
        product_id=product_id,
        programming_language=language,
        client_id=client_id,
        transport="streamable-http",
    )
    snippets = _build_public_snippet_explorer(
        request,
        product_id=product_id,
        programming_language=language,
        version=None,
        source_kind=None,
        limit=12,
    )
    base_prompt = _build_public_mcp_config_export(
        request,
        product_id=product_id,
        transport="streamable-http",
    ).sample_prompt

    snippet_items = list(snippets.items)

    def pick_evidence(*terms: str) -> list[PublicUseCaseEvidenceResponse]:
        lowered_terms = tuple(term.casefold() for term in terms)
        matched = [
            item
            for item in snippet_items
            if any(
                term in " ".join(
                    filter(
                        None,
                        [
                            item.title.casefold(),
                            (item.symbol_fqn or "").casefold(),
                            item.code.casefold(),
                        ],
                    )
                )
                for term in lowered_terms
            )
        ]
        selected = matched[:2] if matched else snippet_items[:1]
        return [
            PublicUseCaseEvidenceResponse(
                evidence_type="snippet",
                title=item.title,
                canonical_url=item.canonical_url,
                section_anchor=item.section_anchor,
                snippet_id=item.snippet_id,
            )
            for item in selected
        ]

    def build_status(evidence: list[PublicUseCaseEvidenceResponse]) -> str:
        if self_test.status == "not_ready":
            return "blocked"
        if self_test.status == "partial" or not evidence:
            return "watch"
        return "ready"

    client_notes = [
        PublicUseCaseClientNoteResponse(
            client_id="cursor",
            note="Use a workspace-local MCP config and keep the starter prompt in the same chat.",
        ),
        PublicUseCaseClientNoteResponse(
            client_id="claude-desktop",
            note="Paste the prompt with explicit citations and keep the MCP config short.",
        ),
        PublicUseCaseClientNoteResponse(
            client_id="qwen-code",
            note="State the desired output format explicitly before asking for code.",
        ),
        PublicUseCaseClientNoteResponse(
            client_id="vscode",
            note="Validate the cited symbol contracts before accepting inline code actions.",
        ),
    ]

    templates: list[dict[str, Any]] = [
        {
            "use_case_id": "phone-table-photo",
            "category": "tables",
            "title": "Phone photo of a skewed table",
            "summary": (
                "Start from a photographed table with perspective distortion, low contrast, "
                "or uneven lighting and force the agent to validate table-specific OCR paths."
            ),
            "starter_query": (
                "How do I extract a photographed table with perspective distortion and "
                "low contrast while keeping the table structure explainable?"
            ),
            "recommended_journey_id": "release-safe-rollout",
            "terms": ("table", "recognizetables"),
        },
        {
            "use_case_id": "scanned-document-text",
            "category": "document-text",
            "title": "Scanned document to plain text",
            "summary": (
                "Use this when the developer needs a cited plain-text extraction flow for "
                "a scanner-produced document rather than a photographed scene."
            ),
            "starter_query": (
                "Show the minimal cited flow for converting a scanned document image "
                "into plain text with exact API validation steps."
            ),
            "recommended_journey_id": "first-cited-answer",
            "terms": ("recognizeimage", "plain text", "quickstart"),
        },
        {
            "use_case_id": "release-upgrade-check",
            "category": "upgrade",
            "title": "Adopt the latest OCR release safely",
            "summary": (
                "Use this card when a team wants newer OCR behavior but must compare "
                "release notes, breaking changes, and freshness before changing code."
            ),
            "starter_query": (
                "List the latest release features, breaking changes, and a safe upgrade "
                "checklist before generating any new OCR code."
            ),
            "recommended_journey_id": "release-safe-rollout",
            "terms": ("release", "migration", "recognizeimage"),
        },
        {
            "use_case_id": "zero-result-recovery",
            "category": "troubleshooting",
            "title": "Weak or zero-result public answer recovery",
            "summary": (
                "Use this when an AI IDE produced a weak OCR answer and you need a fast "
                "MCP-grounded diagnosis before changing code or content."
            ),
            "starter_query": (
                "Diagnose whether a weak OCR answer is caused by coverage gaps, freshness "
                "drift, or low-confidence retrieval, then give the smallest next-step plan."
            ),
            "recommended_journey_id": "zero-result-recovery",
            "terms": ("recognizeimage", "quickstart", "ocr"),
        },
    ]

    items: list[PublicUseCaseItemResponse] = []
    for template in templates:
        evidence = pick_evidence(*template["terms"])
        status = build_status(evidence)
        if status_filter and status != status_filter:
            continue
        items.append(
            PublicUseCaseItemResponse(
                use_case_id=template["use_case_id"],
                category=template["category"],
                title=template["title"],
                status=status,
                summary=template["summary"],
                starter_prompt=" ".join(
                    [
                        base_prompt,
                        (
                            f"Focus on the use case `{template['title']}` for "
                            f"`{product_id}` / `{language}`."
                        ),
                        template["starter_query"],
                    ]
                ),
                starter_query=template["starter_query"],
                recommended_journey_id=template["recommended_journey_id"],
                client_notes=client_notes,
                evidence=evidence,
                actions=[
                    PublicTroubleshootingActionResponse(
                        label="Open snippet explorer",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=language,
                            version=None,
                            source_kind=None,
                            anchor="#snippet-explorer",
                        ),
                    ),
                    PublicTroubleshootingActionResponse(
                        label="Open guided journeys",
                        href=_build_public_scope_link(
                            product_id=product_id,
                            programming_language=language,
                            version=None,
                            source_kind=None,
                            anchor="#guided-journeys",
                        ),
                    ),
                ],
            )
        )

    return PublicUseCaseGalleryResponse(
        filters={
            "product_id": product_id,
            "programming_language": language,
            "client_id": client_id,
            "status": status_filter,
        },
        status_summary=(
            f"Curated {len(items)} use-case card(s) for {product_id} / {language}; "
            f"self-test={self_test.status}, snippets={snippets.total_snippets}."
        ),
        items=items,
        generated_at=datetime.now(tz=UTC),
    )


def _public_snippet_sort_key(
    record: StageDChunkRecord,
) -> tuple[tuple[int, int, int, int], int, str, str]:
    source_kind_priority = 0 if record.source_kind == "docs" else 1
    return (
        _public_version_sort_key(record.version),
        source_kind_priority,
        record.programming_language.casefold(),
        record.title.casefold(),
    )


def _public_version_sort_key(version: str) -> tuple[int, int, int, int]:
    tokens = re.findall(r"\d+", version)
    numbers = [int(token) for token in tokens[:4]]
    while len(numbers) < 4:
        numbers.append(-1)
    return (-numbers[0], -numbers[1], -numbers[2], -numbers[3])


@router.get("/admin/v1/system/session", response_model=AdminSessionResponse)
def get_admin_session(request: Request) -> AdminSessionResponse:
    """Return authenticated admin key identity and effective role/scopes."""
    principal = _get_admin_principal(request)
    return AdminSessionResponse(
        key_id=principal.key_id,
        effective_role=principal.effective_role,
        is_superuser=principal.is_superuser,
        scopes=list(principal.scopes),
        product_scopes=list(principal.product_scopes),
        source=principal.source,
        owner_email=principal.owner_email,
    )


@router.get("/admin/v1/system/health", response_model=AdminSystemHealthResponse)
def get_admin_system_health(request: Request) -> AdminSystemHealthResponse:
    """Return process and dependency readiness for admin health dashboard."""
    readiness_status, dependencies = _build_dependency_health(request)
    return AdminSystemHealthResponse(
        status="ok" if readiness_status == "ready" else "degraded",
        process="ok",
        dependencies=dependencies,
        request_id=getattr(request.state, "request_id", None),
        generated_at=datetime.now(tz=UTC),
    )


@router.get(
    "/admin/v1/system/content-services",
    response_model=AdminContentServicesOverviewResponse,
)
def get_admin_content_services_overview(request: Request) -> AdminContentServicesOverviewResponse:
    """Return docs/apiref MCP coverage and per-repository service health details."""
    return _build_content_services_overview(request)


@router.get("/admin/v1/system/topology", response_model=TopologyPolicyResponse)
def get_admin_topology_policy(request: Request) -> TopologyPolicyResponse:
    """Return runtime topology policy resolved for the current environment."""
    return _build_topology_policy_response(request)


@public_router.get("/v1/status", response_model=PublicStatusResponse)
def get_public_status(
    request: Request,
    product_id: str | None = Query(default=None),
    repo_id: str | None = Query(default=None),
) -> PublicStatusResponse:
    """Return public readiness and MCP content coverage without admin auth."""
    readiness_status, dependencies = _build_dependency_health(request)
    overview = _build_content_services_overview(request, product_id=product_id, repo_id=repo_id)
    return PublicStatusResponse(
        status="ok" if readiness_status == "ready" else "degraded",
        process="ok",
        dependencies=dependencies,
        total_services=overview.total_services,
        docs_services_total=overview.docs_services_total,
        apiref_services_total=overview.apiref_services_total,
        docs_mcp_ready_total=overview.docs_mcp_ready_total,
        apiref_mcp_ready_total=overview.apiref_mcp_ready_total,
        pending_first_ingestion_total=overview.pending_first_ingestion_total,
        healthy_total=overview.healthy_total,
        warning_total=overview.warning_total,
        critical_total=overview.critical_total,
        unknown_total=overview.unknown_total,
        filters={"product_id": product_id, "repo_id": repo_id},
        services=overview.services,
        request_id=getattr(request.state, "request_id", None),
        generated_at=datetime.now(tz=UTC),
    )


@public_router.get("/v1/topology", response_model=TopologyPolicyResponse)
def get_public_topology_policy(request: Request) -> TopologyPolicyResponse:
    """Return public runtime topology policy summary for diagnostics."""
    return _build_topology_policy_response(request)


@public_router.get(
    "/v1/integrations/mcp-configs",
    response_model=PublicMCPConfigExportResponse,
)
def get_public_mcp_config_export(
    request: Request,
    product_id: str | None = Query(default=None),
    transport: str = Query(default="streamable-http"),
) -> PublicMCPConfigExportResponse:
    """Return ready-to-paste MCP client configs for common IDEs and CLIs."""
    return _build_public_mcp_config_export(
        request,
        product_id=product_id,
        transport=transport,
    )


@public_router.get(
    "/v1/integrations/starter-packs",
    response_model=PublicStarterPackResponse,
)
def get_public_starter_packs(
    request: Request,
    product_id: str | None = Query(default=None),
    programming_language: str | None = Query(default=None),
    transport: str = Query(default="streamable-http"),
) -> PublicStarterPackResponse:
    """Return ready-to-copy onboarding starter packs for supported clients."""
    return _build_public_starter_packs(
        request,
        product_id=product_id.strip() if product_id else None,
        programming_language=programming_language.strip() if programming_language else None,
        transport=transport,
    )


@public_router.get(
    "/v1/integrations/capabilities",
    response_model=PublicCapabilityExplorerResponse,
)
def get_public_capability_explorer(
    request: Request,
    product_id: str | None = Query(default=None),
    programming_language: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    version: str | None = Query(default=None),
) -> PublicCapabilityExplorerResponse:
    """Return a compact capability explorer for current public MCP scope."""
    return _build_public_capability_explorer(
        request,
        product_id=product_id.strip() if product_id else None,
        programming_language=programming_language.strip() if programming_language else None,
        source_kind=source_kind.strip() if source_kind else None,
        version=version.strip() if version else None,
    )


@public_router.get(
    "/v1/integrations/troubleshooting",
    response_model=PublicTroubleshootingResponse,
)
def get_public_troubleshooting(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str | None = Query(default=None),
    client_id: str = Query(default="cursor"),
    transport: str = Query(default="streamable-http"),
    request_id: str | None = Query(default=None),
) -> PublicTroubleshootingResponse:
    """Return public troubleshooting paths for onboarding and request-quality issues."""
    return _build_public_troubleshooting(
        request,
        product_id=product_id.strip(),
        programming_language=programming_language.strip() if programming_language else None,
        client_id=client_id.strip(),
        transport=transport.strip(),
        request_id=request_id.strip() if request_id else None,
    )


@public_router.get(
    "/v1/integrations/coverage-gaps",
    response_model=PublicCoverageGapTrackerResponse,
)
def get_public_coverage_gaps(
    request: Request,
    product_id: str | None = Query(default=None),
    programming_language: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    version: str | None = Query(default=None),
) -> PublicCoverageGapTrackerResponse:
    """Return a product/language coverage tracker for onboarding prioritization."""
    return _build_public_coverage_gap_tracker(
        request,
        product_id=product_id.strip() if product_id else None,
        programming_language=programming_language.strip() if programming_language else None,
        source_kind=source_kind.strip() if source_kind else None,
        version=version.strip() if version else None,
    )


@public_router.get(
    "/v1/integrations/coverage-navigator",
    response_model=PublicCoverageNavigatorResponse,
)
def get_public_coverage_navigator(
    request: Request,
    product_id: str | None = Query(default=None),
    programming_language: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    version: str | None = Query(default=None),
) -> PublicCoverageNavigatorResponse:
    """Return a compact public coverage navigator with direct readiness remediation."""
    return _build_public_coverage_navigator(
        request,
        product_id=product_id.strip() if product_id else None,
        programming_language=programming_language.strip() if programming_language else None,
        source_kind=source_kind.strip() if source_kind else None,
        version=version.strip() if version else None,
    )


@public_router.get(
    "/v1/integrations/trust-signals",
    response_model=PublicTrustSignalsBoardResponse,
)
def get_public_trust_signals_board(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str | None = Query(default=None),
    version: str | None = Query(default=None),
) -> PublicTrustSignalsBoardResponse:
    """Return explainable public trust signals for one MCP product/language scope."""
    return _build_public_trust_signals_board(
        request,
        product_id=product_id.strip(),
        programming_language=programming_language.strip() if programming_language else None,
        version=version.strip() if version else None,
    )


@public_router.get(
    "/v1/integrations/compare-board",
    response_model=PublicScopeCompareBoardResponse,
)
def get_public_scope_compare_board(
    request: Request,
    left_product_id: str = Query(min_length=1),
    left_programming_language: str | None = Query(default=None),
    left_version: str | None = Query(default=None),
    left_source_kind: str | None = Query(default=None),
    right_product_id: str = Query(min_length=1),
    right_programming_language: str | None = Query(default=None),
    right_version: str | None = Query(default=None),
    right_source_kind: str | None = Query(default=None),
) -> PublicScopeCompareBoardResponse:
    """Return an explainable side-by-side comparison of two public MCP scopes."""
    return _build_public_scope_compare_board(
        request,
        left_product_id=left_product_id.strip(),
        left_programming_language=(
            left_programming_language.strip()
            if left_programming_language
            else None
        ),
        left_version=left_version.strip() if left_version else None,
        left_source_kind=left_source_kind.strip() if left_source_kind else None,
        right_product_id=right_product_id.strip(),
        right_programming_language=(
            right_programming_language.strip()
            if right_programming_language
            else None
        ),
        right_version=right_version.strip() if right_version else None,
        right_source_kind=right_source_kind.strip() if right_source_kind else None,
    )


@public_router.get(
    "/v1/integrations/self-test",
    response_model=PublicMCPSelfTestResponse,
)
def get_public_mcp_self_test(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str | None = Query(default=None),
    client_id: str = Query(default="cursor"),
    transport: str = Query(default="streamable-http"),
) -> PublicMCPSelfTestResponse:
    """Run a public MCP readiness self-test for one product/client/transport scope."""
    started_at = perf_counter()
    response = _build_public_mcp_self_test(
        request,
        product_id=product_id,
        programming_language=programming_language.strip() if programming_language else None,
        client_id=client_id,
        transport=transport,
    )
    _record_public_self_test_analytics(
        request=request,
        response=response,
        latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
    )
    return response


@public_router.get(
    "/v1/integrations/freshness",
    response_model=PublicReleaseFreshnessResponse,
)
def get_public_release_freshness(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str | None = Query(default=None),
    version: str | None = Query(default=None),
    top_k: int = Query(default=6, ge=1, le=20),
) -> PublicReleaseFreshnessResponse:
    """Return release freshness and latest-version visibility for one public scope."""
    return _build_public_release_freshness(
        request,
        product_id=product_id,
        programming_language=programming_language.strip() if programming_language else None,
        version=version.strip() if version else None,
        top_k=top_k,
    )


@public_router.get(
    "/v1/integrations/release-adoption",
    response_model=PublicReleaseAdoptionResponse,
)
def get_public_release_adoption(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str = Query(min_length=1),
    version: str | None = Query(default=None),
) -> PublicReleaseAdoptionResponse:
    """Return a unified release-adoption plan for one public product/language scope."""
    return _build_public_release_adoption(
        request,
        product_id=product_id,
        programming_language=programming_language.strip(),
        version=version.strip() if version else None,
    )


@public_router.get(
    "/v1/integrations/use-cases",
    response_model=PublicUseCaseGalleryResponse,
)
def get_public_use_case_gallery(
    request: Request,
    product_id: str = Query(min_length=1),
    programming_language: str | None = Query(default=None),
    client_id: str = Query(default="cursor"),
    status: str | None = Query(default=None),
) -> PublicUseCaseGalleryResponse:
    """Return curated MCP-first use-case cards for one public scope."""
    return _build_public_use_case_gallery(
        request,
        product_id=product_id,
        programming_language=programming_language.strip() if programming_language else None,
        client_id=client_id.strip(),
        status_filter=status.strip() if status else None,
    )


@public_router.get(
    "/v1/integrations/triage",
    response_model=PublicContentTriageResponse,
)
def get_public_content_triage(
    request: Request,
    product_id: str | None = Query(default=None),
    repo_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    stale_after_days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> PublicContentTriageResponse:
    """Return stale/no-index/no-snippet coverage gaps for triage."""
    return _build_public_content_triage(
        request,
        product_id=product_id.strip() if product_id else None,
        repo_id=repo_id.strip() if repo_id else None,
        severity=severity.strip() if severity else None,
        source_kind=source_kind.strip() if source_kind else None,
        stale_after_days=stale_after_days,
        limit=limit,
    )


@public_router.get(
    "/v1/snippets",
    response_model=PublicSnippetExplorerResponse,
)
def get_public_snippet_explorer(
    request: Request,
    product_id: str | None = Query(default=None),
    programming_language: str | None = Query(default=None),
    version: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
) -> PublicSnippetExplorerResponse:
    """Return public executable snippet catalog for one product/language scope."""
    return _build_public_snippet_explorer(
        request,
        product_id=product_id,
        programming_language=programming_language,
        version=version,
        source_kind=source_kind,
        limit=limit,
    )


@router.post(
    "/admin/v1/system/backups:trigger",
    response_model=AdminBackupOperationResponse,
)
def trigger_backup(
    request: Request,
    payload: AdminBackupTriggerRequest,
) -> AdminBackupOperationResponse:
    """Trigger backup pipeline and return operation summary."""
    principal = _get_admin_principal(request)
    target_product_ids = _resolve_auth_target_product_ids(
        principal=principal,
        product_id=payload.product_id,
        request=request,
    )
    _authorize_backup_mutation(
        request=request,
        principal=principal,
        target_product_ids=target_product_ids,
        destructive=False,
    )

    operation = _backup_restore_service(request).trigger_backup(
        scope=payload.scope,
        product_id=payload.product_id,
        reason=payload.reason,
        requested_by=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
    )
    return _to_operation_response(operation)


@router.get("/admin/v1/system/backups", response_model=list[AdminBackupRecordResponse])
def list_backups(request: Request, limit: int = 100) -> list[AdminBackupRecordResponse]:
    """List known backups."""
    backups = _backup_restore_service(request).list_backups(limit=limit)
    return [_to_backup_response(item) for item in backups]


@router.get("/admin/v1/system/backups/{backup_id}", response_model=AdminBackupRecordResponse)
def get_backup(request: Request, backup_id: str) -> AdminBackupRecordResponse:
    """Get one backup by id."""
    backup = _backup_restore_service(request).get_backup(backup_id)
    if backup is None:
        _raise_structured_http_error(
            request,
            status_code=404,
            code="BACKUP_NOT_FOUND",
            message=f"Backup `{backup_id}` was not found.",
        )
    return _to_backup_response(backup)


@router.post(
    "/admin/v1/system/backups/{backup_id}:restore",
    response_model=AdminBackupOperationResponse,
)
def trigger_restore(
    request: Request,
    backup_id: str,
    payload: AdminRestoreTriggerRequest,
) -> AdminBackupOperationResponse:
    """Trigger restore pipeline for one backup id."""
    principal = _get_admin_principal(request)
    backup = _backup_restore_service(request).get_backup(backup_id)
    if backup is None:
        _raise_structured_http_error(
            request,
            status_code=404,
            code="BACKUP_NOT_FOUND",
            message=f"Backup `{backup_id}` was not found.",
        )

    target_product_ids = _resolve_auth_target_product_ids(
        principal=principal,
        product_id=backup.product_id,
        request=request,
    )
    _authorize_backup_mutation(
        request=request,
        principal=principal,
        target_product_ids=target_product_ids,
        destructive=not payload.validate_only,
    )

    operation = _backup_restore_service(request).trigger_restore(
        backup_id=backup_id,
        validate_only=payload.validate_only,
        reason=payload.reason,
        requested_by=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
    )
    return _to_operation_response(operation)


@router.get(
    "/admin/v1/system/backup-operations",
    response_model=list[AdminBackupOperationResponse],
)
def list_backup_operations(
    request: Request,
    limit: int = 100,
) -> list[AdminBackupOperationResponse]:
    """List backup/restore operations."""
    operations = _backup_restore_service(request).list_operations(limit=limit)
    return [_to_operation_response(item) for item in operations]


@router.get(
    "/admin/v1/system/backup-operations/{operation_id}",
    response_model=AdminBackupOperationResponse,
)
def get_backup_operation(request: Request, operation_id: str) -> AdminBackupOperationResponse:
    """Get one backup/restore operation."""
    operation = _backup_restore_service(request).get_operation(operation_id)
    if operation is None:
        _raise_structured_http_error(
            request,
            status_code=404,
            code="BACKUP_OPERATION_NOT_FOUND",
            message=f"Backup operation `{operation_id}` was not found.",
        )
    return _to_operation_response(operation)


@router.post("/admin/v1/system/dr:recovery-smoke", response_model=AdminDRSmokeResponse)
def run_dr_recovery_smoke(
    request: Request,
    payload: AdminDRSmokeTriggerRequest,
) -> AdminDRSmokeResponse:
    """Run deterministic DR smoke (backup -> restore -> verify)."""
    principal = _get_admin_principal(request)
    if not principal.is_superuser:
        _raise_structured_http_error(
            request,
            status_code=403,
            code="FORBIDDEN",
            message="DR smoke run requires superuser key.",
        )
    _authorize_backup_mutation(
        request=request,
        principal=principal,
        target_product_ids=(),
        destructive=True,
    )

    result: DRSmokeResult = _backup_restore_service(request).run_recovery_smoke(
        requested_by=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        reason=payload.reason,
    )
    return AdminDRSmokeResponse(
        status=result.status.value,
        backup_operation_id=result.backup_operation_id,
        restore_operation_id=result.restore_operation_id,
        backup_id=result.backup_id,
        details=result.details,
        request_id=getattr(request.state, "request_id", None),
        generated_at=datetime.now(tz=UTC),
    )
