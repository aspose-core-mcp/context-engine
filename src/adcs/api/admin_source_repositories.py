"""Admin API endpoints for source repository synchronization orchestration."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.indexing.index_models import (
    ConversionGateSummary,
    CriticalEventSummary,
    IndexPublishSummary,
    IngestionRunMode,
    NotificationDispatchSummary,
    PublishDecision,
    PublishSafetyGateSummary,
    SemanticGateStatusTransition,
    SemanticGateSummary,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.hugo_parser import (
    HugoCodeBlock,
    HugoHeading,
    HugoNormalizedPage,
    HugoParseWarning,
)
from adcs.ingestion.job_repository import IngestionIdempotencyConflictError
from adcs.ingestion.metadata_quarantine import (
    MetadataQuarantinePolicy,
    MetadataQuarantineSummary,
)
from adcs.ingestion.prompt_registry import (
    ConversionPromptEvaluationSummary,
    ConversionPromptVariantEvaluation,
)
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceCanonicalUrlMappingSummary,
    SourceHugoNormalizationFailedItem,
    SourceHugoNormalizationOperation,
    SourceHugoNormalizationOperationNotFoundError,
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationResult,
    SourceHugoNormalizationStatus,
    SourceStagingScopeSummary,
)
from adcs.ingestion.source_layout_detection_orchestrator import (
    SourceLayoutDetectionOperation,
    SourceLayoutDetectionOperationNotFoundError,
    SourceLayoutDetectionOrchestrationService,
    SourceLayoutDetectionResult,
    SourceLayoutDetectionStatus,
)
from adcs.ingestion.source_registry import SourceRegistryLookupError, SourceRegistryService
from adcs.ingestion.source_sync_orchestrator import (
    SourceSyncMode,
    SourceSyncOperation,
    SourceSyncOperationNotFoundError,
    SourceSyncOrchestrationService,
    SourceSyncStatus,
)
from adcs.worker.task_dispatcher import WorkerTaskDispatcher

router = APIRouter(
    tags=["admin-source-repositories"],
    dependencies=[Depends(require_admin_principal)],
)

_PRODUCT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,126}$")
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,127}$")
_ARTIFACT_PREVIEW_ROOTS = frozenset({"artifacts"})
_STAGING_PREVIEW_ROOTS = frozenset({"data-docs", "data-apiref"})
_SOURCE_PREVIEW_ROOTS = frozenset({"source-repo-docs", "source-repo-apiref"})


class _SourceRepositoriesRepoFilterRequest(BaseModel):
    """Base payload model with optional repo_id/repo_ids filtering."""

    repo_id: str | None = None
    repo_ids: list[str] = Field(default_factory=list)

    @field_validator("repo_id")
    @classmethod
    def _validate_repo_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            raise ValueError("repo_id must not be empty.")
        return normalized

    @field_validator("repo_ids")
    @classmethod
    def _validate_repo_ids(cls, values: list[str]) -> list[str]:
        normalized_values: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized:
                raise ValueError("repo_ids must not contain empty values.")
            normalized_values.append(normalized)
        return normalized_values

    def resolved_repo_ids(self) -> tuple[str, ...]:
        merged_repo_ids: list[str] = []
        seen_repo_ids: set[str] = set()

        if self.repo_id is not None:
            merged_repo_ids.append(self.repo_id)
        merged_repo_ids.extend(self.repo_ids)

        resolved_repo_ids: list[str] = []
        for repo_id in merged_repo_ids:
            if repo_id in seen_repo_ids:
                continue
            seen_repo_ids.add(repo_id)
            resolved_repo_ids.append(repo_id)

        return tuple(resolved_repo_ids)


class SourceRepositoriesSyncTriggerRequest(_SourceRepositoriesRepoFilterRequest):
    """Trigger payload for source repository synchronization."""

    mode: SourceSyncMode


class SourceLayoutDetectionTriggerRequest(_SourceRepositoriesRepoFilterRequest):
    """Trigger payload for source repository layout detection."""


class SourceHugoNormalizationTriggerRequest(_SourceRepositoriesRepoFilterRequest):
    """Trigger payload for source repository Hugo normalization."""

    mode: IngestionRunMode = IngestionRunMode.PUBLISH
    partial_publish_threshold_pct: int | None = Field(default=None, ge=0, le=100)
    metadata_quarantine_policy: MetadataQuarantinePolicy | None = None
    dry_run: bool = False
    force_full_reindex: bool = False
    bypass_staging_replay: bool = False
    idempotency_key: str | None = Field(default=None, max_length=256)

    @field_validator("idempotency_key")
    @classmethod
    def _validate_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("idempotency_key must not be empty.")
        return normalized


class IngestionJobRetryRequest(BaseModel):
    """Retry payload for failed/retry-scheduled ingestion jobs."""

    force: bool = False


class SourceRepositoriesOnboardProductRequest(BaseModel):
    """Create one new product with docs/apiref repository registry entries."""

    product_id: str
    product_name: str | None = None
    product_family: str
    product_family_dir: str
    docs_git_url: str
    docs_default_branch: str = "main"
    apiref_git_url: str
    apiref_default_branch: str = "main"
    programming_languages: list[str] = Field(default_factory=list)
    auto_run_layout_detection: bool = False
    auto_run_validate_only: bool = False

    @field_validator("product_id")
    @classmethod
    def _validate_product_id(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _PRODUCT_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "product_id must match pattern: lowercase letters/digits with . _ - separators."
            )
        return normalized

    @field_validator("product_name")
    @classmethod
    def _validate_product_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 128:
            raise ValueError("product_name length must be <= 128 characters.")
        return normalized

    @field_validator("product_family")
    @classmethod
    def _validate_product_family(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _TOKEN_PATTERN.fullmatch(normalized):
            raise ValueError(
                "product_family must contain only letters, digits, '.', '_' or '-'."
            )
        return normalized

    @field_validator("product_family_dir")
    @classmethod
    def _validate_product_family_dir(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("product_family_dir must not be empty.")
        if len(normalized) > 128:
            raise ValueError("product_family_dir length must be <= 128 characters.")
        if "/" in normalized or "\\" in normalized:
            raise ValueError("product_family_dir must be a single directory name.")
        if normalized in {".", ".."}:
            raise ValueError("product_family_dir must be a safe directory name.")
        return normalized

    @field_validator(
        "docs_git_url",
        "apiref_git_url",
        "docs_default_branch",
        "apiref_default_branch",
    )
    @classmethod
    def _validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty.")
        return normalized

    @field_validator("programming_languages")
    @classmethod
    def _validate_programming_languages(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized_values: list[str] = []
        for item in values:
            normalized = item.strip().casefold()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_values.append(normalized)
        return normalized_values


class SourceRepositoriesOnboardedRepoResponse(BaseModel):
    repo_id: str
    source_kind: str
    git_url: str
    default_branch: str
    submodule_path: str
    local_path_created: bool


class SourceRepositoriesOnboardProductResponse(BaseModel):
    product_id: str
    product_family: str
    product_family_dir: str
    created_repo_ids: list[str]
    repositories: list[SourceRepositoriesOnboardedRepoResponse]
    programming_languages: list[str]
    registry_path: str
    next_steps: list[str]
    bootstrap: SourceRepositoriesOnboardProductBootstrapResponse


class SourceRepositoriesOnboardProductBootstrapResponse(BaseModel):
    status: str
    layout_detection_requested: bool
    validate_only_requested: bool
    layout_detection_operation: SourceLayoutDetectionOperationResponse | None
    validate_only_operation: SourceHugoNormalizationOperationResponse | None
    warnings: list[str]


class SourceReviewArtifactPreviewRequest(BaseModel):
    """Request payload for lightweight review artifact preview."""

    artifact_path: str = Field(min_length=1, max_length=1024)

    @field_validator("artifact_path")
    @classmethod
    def _validate_artifact_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("artifact_path must not be empty.")
        return normalized


class SourceReviewArtifactPreviewResponse(BaseModel):
    """API response with parsed review artifact payload."""

    artifact_path: str
    payload: dict[str, Any]


class SourceRawMarkdownPreviewRequest(BaseModel):
    """Request payload for source markdown preview."""

    source_path: str = Field(min_length=1, max_length=1024)

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source_path must not be empty.")
        return normalized


class SourceRawMarkdownPreviewResponse(BaseModel):
    """API response with raw markdown preview for review UI."""

    source_path: str
    size_bytes: int
    line_count: int
    raw_markdown: str


class SourceStagingManifestPreviewRequest(BaseModel):
    """Request payload for staged manifest preview with embedded sample payloads."""

    manifest_path: str = Field(min_length=1, max_length=1024)
    max_documents: int = Field(default=5, ge=1, le=25)
    max_chunk_objects: int = Field(default=5, ge=1, le=25)
    max_chunk_records_per_object: int = Field(default=10, ge=1, le=50)

    @field_validator("manifest_path")
    @classmethod
    def _validate_manifest_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("manifest_path must not be empty.")
        return normalized


class SourceStagingDocumentPreviewResponse(BaseModel):
    """Embedded staged normalized document preview."""

    source_path: str
    document_path: str
    document_checksum: str
    payload: dict[str, Any]


class SourceStagingChunkPreviewResponse(BaseModel):
    """Embedded staged chunk object preview."""

    source_path: str
    chunk_path: str
    chunk_records_count: int
    payload: dict[str, Any]


class SourceStagingManifestPreviewResponse(BaseModel):
    """API response with manifest JSON plus limited embedded document/chunk payloads."""

    manifest_path: str
    manifest_kind: str
    payload: dict[str, Any]
    documents_preview: list[SourceStagingDocumentPreviewResponse]
    chunk_objects_preview: list[SourceStagingChunkPreviewResponse]
    documents_truncated: bool
    chunk_objects_truncated: bool
    chunk_records_truncated: bool


class SourceOperationLogLineResponse(BaseModel):
    """API representation of one operation log line."""

    stream: str
    line: str


class SourceSyncOperationResponse(BaseModel):
    """API representation of one source sync operation."""

    operation_id: str
    status: SourceSyncStatus
    mode: SourceSyncMode
    repo_ids: list[str]
    logs: list[SourceOperationLogLineResponse]
    started_at: datetime | None
    finished_at: datetime | None


class SourceLayoutDetectionResultResponse(BaseModel):
    """API representation of persisted layout detection metadata."""

    repo_id: str
    layout_type: str
    confidence: float
    confidence_threshold: float
    confidence_policy_status: str
    manual_override_applied: bool
    dimensions: list[dict[str, Any]]
    sample_markdown_paths: list[str]
    detector_version: str


class SourceLayoutManualOverrideRequest(BaseModel):
    """Manual override payload for layout detection metadata."""

    enabled: bool = True
    layout_type: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    sample_markdown_paths: list[str] = Field(default_factory=list)
    detector_version: str | None = None


class SourceLayoutDetectionOperationResponse(BaseModel):
    """API representation of one source layout detection operation."""

    operation_id: str
    status: SourceLayoutDetectionStatus
    repo_ids: list[str]
    layout_backend: str
    logs: list[SourceOperationLogLineResponse]
    results: list[SourceLayoutDetectionResultResponse]
    started_at: datetime | None
    finished_at: datetime | None


class SourceHugoParseWarningResponse(BaseModel):
    """API representation of one Hugo parse warning."""

    code: str
    message: str
    line_hint: int | None
    severity: str


class SourceHugoHeadingResponse(BaseModel):
    """API representation of one extracted markdown heading."""

    level: int
    text: str
    line_hint: int


class SourceHugoCodeBlockResponse(BaseModel):
    """API representation of one extracted code block."""

    language: str | None
    code: str
    line_start: int
    line_end: int


class SourceHugoNormalizedPageResponse(BaseModel):
    """API representation of one normalized Hugo page model."""

    repo_id: str
    source_path: str
    source_kind: str
    product_id: str | None
    product_family: str | None
    programming_language: str | None
    doc_locale: str | None
    title: str
    metadata: dict[str, Any]
    body_plain: str
    headings: list[SourceHugoHeadingResponse]
    code_blocks: list[SourceHugoCodeBlockResponse]
    parse_warnings: list[SourceHugoParseWarningResponse]
    is_index_page: bool


class SourceExecutableSnippetResponse(BaseModel):
    """API representation of one executable snippet metadata record."""

    snippet_id: str
    language: str
    code: str
    parent_canonical_url: str
    parent_section_anchor: str
    parent_symbol_fqn: str | None


class SourceChunkRecordResponse(BaseModel):
    """API representation of one Stage-D chunk record."""

    chunk_id: str
    repo_id: str
    product_id: str
    product_family: str
    programming_language: str
    version: str
    source_kind: str
    doc_locale: str
    doc_type: str
    symbol_fqn: str | None
    title: str
    section_path: list[str]
    canonical_url: str
    section_anchor: str
    source_path: str
    source_revision: str
    is_deprecated: bool
    has_code_example: bool
    chunk_type: str
    text: str
    tokens: int
    checksum: str
    executable_snippets: list[SourceExecutableSnippetResponse]


class SourceIndexPublishSummaryResponse(BaseModel):
    """API representation of one Stage-F publish summary."""

    snapshot_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    source_revision: str
    indexed_chunks_count: int
    vector_records_count: int
    lexical_records_count: int
    vector_collection: str
    lexical_index: str
    lexical_alias: str
    active_snapshot_id: str
    mode: IngestionRunMode
    dry_run: bool
    force_full_reindex: bool
    partial_publish_threshold_pct: int
    error_ratio: float
    decision: PublishDecision
    publish_blocked_reason: str | None
    total_items_count: int
    failed_items_count: int
    metadata_quarantine_policy: str
    quarantined_items_count: int
    canonical_url_remap_entries_count: int
    canonical_url_remap_applied_count: int
    canonical_url_remap_conflict_count: int
    canonical_url_remap_override_count: int
    event_summary: SourceCriticalEventSummaryResponse
    notification_summary: SourceNotificationSummaryResponse
    semantic_gate: SourceSemanticGateSummaryResponse
    conversion_gate: SourceConversionGateSummaryResponse
    publish_safety_gate: SourcePublishSafetyGateSummaryResponse
    incremental_mode: str
    incremental_detection_strategy: str
    incremental_fallback_reason: str | None
    incremental_git_base_revision: str | None
    baseline_snapshot_id: str | None
    file_total_count: int
    file_new_count: int
    file_changed_count: int
    file_unchanged_count: int
    file_removed_count: int
    chunk_total_count: int
    chunk_new_count: int
    chunk_changed_count: int
    chunk_unchanged_count: int
    chunk_removed_count: int


class SourceCriticalEventSummaryResponse(BaseModel):
    """API representation of critical event summary for one result."""

    event_ids: list[str]
    event_types: list[str]


class SourceNotificationSummaryResponse(BaseModel):
    """API representation of SMTP dispatch summary for one result."""

    sent_count: int
    failed_count: int


class SourceSemanticGateTransitionResponse(BaseModel):
    """API representation of one semantic gate status transition."""

    transition_id: str
    from_status: str
    to_status: str
    actor_type: str
    actor_key_id: str | None
    reason: str
    request_id: str | None
    created_at: datetime


class SourceSemanticGateSummaryResponse(BaseModel):
    """API representation of semantic review gate output metadata."""

    enforced: bool
    trigger_type: str
    decision: str
    reason_codes: list[str]
    review_run_id: str | None
    review_status: str | None
    approval_mode: str | None
    overall_score: float | None
    threshold_score: float | None
    fail_fast_triggered: bool
    blocking_error_count: int
    status_transitions: list[SourceSemanticGateTransitionResponse]


class SourceConversionGateSummaryResponse(BaseModel):
    """API representation of conversion quality gate summary."""

    phase: str
    enforcement_mode: str
    blocking: bool
    reason_codes: list[str]
    parse_coverage_pct: float
    schema_valid_pct: float
    metadata_completeness_pct: float
    citation_integrity_pct: float
    api_signature_coverage_pct: float | None
    api_parameter_coverage_pct: float | None
    hallucination_risk_pct: float


class SourcePublishSafetyGateSummaryResponse(BaseModel):
    """API representation of publish safety gate summary."""

    blocking: bool
    reason_codes: list[str]
    usable_chunk_coverage_pct: float
    coverage_threshold_pct: float
    parser_critical_failed_items_count: int
    active_scopes_count: int
    empty_usable_scope_detected: bool


class SourceMetadataQuarantineReasonCountResponse(BaseModel):
    """API representation of one quarantine reason-code aggregate."""

    reason_code: str
    count: int


class SourceMetadataQuarantineItemResponse(BaseModel):
    """API representation of one quarantined metadata sample item."""

    source_path: str
    reason_code: str
    message: str


class SourceMetadataQuarantineSummaryResponse(BaseModel):
    """API representation of metadata quarantine summary."""

    policy_mode: str
    total_count: int
    reason_counts: list[SourceMetadataQuarantineReasonCountResponse]
    sample_items: list[SourceMetadataQuarantineItemResponse]


class SourceCanonicalUrlMappingSummaryResponse(BaseModel):
    """API representation of canonical URL remap summary."""

    contexts: list[str]
    remap_entries_count: int
    remap_applied_count: int
    remap_conflict_count: int
    remap_override_count: int


class SourcePromptVariantEvaluationResponse(BaseModel):
    """API representation of one prompt variant evaluation row."""

    variant_id: str
    assigned_count: int
    success_count: int
    failed_count: int
    parse_warnings_count: int
    success_rate: float
    warning_rate: float


class SourcePromptEvaluationSummaryResponse(BaseModel):
    """API representation of conversion prompt A/B evaluation summary."""

    registry_version: str
    experiment_id: str
    assignment_unit: str
    total_assigned_count: int
    successful_count: int
    failed_count: int
    parse_warnings_count: int
    best_variant_id: str | None
    variants: list[SourcePromptVariantEvaluationResponse]


class SourceStagingScopeSummaryResponse(BaseModel):
    """API representation of one scope-level staging manifest summary."""

    product_id: str
    programming_language: str
    version: str
    doc_locale: str
    source_kind: str
    manifest_path: str
    documents_count: int
    chunk_records_count: int


class SourceHugoNormalizationFailedItemResponse(BaseModel):
    """API representation of one failed parse/normalize item."""

    source_path: str
    error_code: str
    message: str


class SourceHugoNormalizationResultResponse(BaseModel):
    """API representation of one repository parse + normalize result.

    In streaming-ingestion mode (the default), `pages` is empty by design —
    the documents live on disk and are fetched via
    `staging_repository_manifest_path` + `iter_canonical_documents`.
    Cardinality is exposed via `parsed_pages_count`,
    `canonical_documents_count`, and `chunk_records_count`.
    """

    repo_id: str
    source_kind: str
    parsed_pages_count: int
    parse_warnings_count: int
    review_artifact_path: str | None
    staging_repository_manifest_path: str | None
    staging_replay_used: bool
    staging_scopes: list[SourceStagingScopeSummaryResponse]
    pages: list[SourceHugoNormalizedPageResponse]
    chunk_records: list[SourceChunkRecordResponse]
    indexing_summary: SourceIndexPublishSummaryResponse
    failed_items: list[SourceHugoNormalizationFailedItemResponse]
    metadata_quarantine: SourceMetadataQuarantineSummaryResponse
    prompt_evaluation: SourcePromptEvaluationSummaryResponse
    canonical_url_mapping: SourceCanonicalUrlMappingSummaryResponse
    canonical_documents_count: int = 0
    chunk_records_count: int = 0


class SourceHugoNormalizationOperationResponse(BaseModel):
    """API representation of one source Hugo normalization operation."""

    operation_id: str
    job_id: str
    status: SourceHugoNormalizationStatus
    repo_ids: list[str]
    mode: IngestionRunMode
    requested_mode: IngestionRunMode
    conversion_backend: str
    prompt_registry_version: str
    prompt_experiment_id: str
    dry_run: bool
    force_full_reindex: bool
    request_id: str | None
    idempotency_key: str | None
    idempotency_scope: str | None
    idempotency_reused: bool
    idempotency_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    last_error_kind: str | None
    cancel_requested_at: datetime | None
    cancelled_at: datetime | None
    resumable: bool
    logs: list[SourceOperationLogLineResponse]
    results: list[SourceHugoNormalizationResultResponse]
    started_at: datetime | None
    finished_at: datetime | None


def _get_orchestrator(request: Request) -> SourceSyncOrchestrationService:
    orchestrator = getattr(request.app.state, "source_sync_orchestrator", None)
    if not isinstance(orchestrator, SourceSyncOrchestrationService):
        msg = "Source sync orchestrator service is not configured."
        raise RuntimeError(msg)
    return orchestrator


def _get_layout_detection_orchestrator(
    request: Request,
) -> SourceLayoutDetectionOrchestrationService:
    orchestrator = getattr(request.app.state, "source_layout_detection_orchestrator", None)
    if not isinstance(orchestrator, SourceLayoutDetectionOrchestrationService):
        msg = "Source layout detection orchestrator service is not configured."
        raise RuntimeError(msg)
    return orchestrator


def _get_hugo_normalization_orchestrator(
    request: Request,
) -> SourceHugoNormalizationOrchestrationService:
    orchestrator = getattr(request.app.state, "source_hugo_normalization_orchestrator", None)
    if not isinstance(orchestrator, SourceHugoNormalizationOrchestrationService):
        msg = "Source Hugo normalization orchestrator service is not configured."
        raise RuntimeError(msg)
    return orchestrator


def _get_admin_principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _get_source_registry_service(request: Request) -> SourceRegistryService:
    service = getattr(request.app.state, "source_registry_service", None)
    if not isinstance(service, SourceRegistryService):
        msg = "Source registry service is not configured."
        raise RuntimeError(msg)
    return service


def _get_task_dispatcher(request: Request) -> WorkerTaskDispatcher:
    dispatcher = getattr(request.app.state, "task_dispatcher", None)
    if dispatcher is None or not all(
        hasattr(dispatcher, attribute_name)
        for attribute_name in (
            "dispatch_source_sync",
            "dispatch_layout_detection",
            "dispatch_ingestion",
        )
    ):
        msg = "Worker task dispatcher is not configured."
        raise RuntimeError(msg)
    return dispatcher


def _resolve_target_product_ids(
    *,
    request: Request,
    repo_ids: tuple[str, ...],
) -> tuple[str, ...]:
    source_registry = _get_source_registry_service(request)
    if repo_ids:
        product_ids: list[str] = []
        for repo_id in repo_ids:
            try:
                repository = source_registry.get_repository(repo_id)
            except SourceRegistryLookupError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            product_ids.append(repository.product_id)
        return tuple(sorted(set(product_ids)))

    return tuple(
        sorted({repository.product_id for repository in source_registry.list_repositories()})
    )


def _authorize_ingestion_mutation(*, request: Request, repo_ids: tuple[str, ...]) -> None:
    principal = _get_admin_principal(request)
    target_product_ids = _resolve_target_product_ids(request=request, repo_ids=repo_ids)
    auth_service = get_admin_auth_service(request)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=target_product_ids,
            destructive=False,
        )
    except AdminAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        ) from exc


def _authorize_superuser_mutation(*, request: Request) -> None:
    principal = _get_admin_principal(request)
    if principal.is_superuser:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": {
                "code": "FORBIDDEN",
                "message": "Only superuser key can onboard new products.",
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _load_registry_payload(path: Path) -> dict[str, Any]:
    raw_payload = path.read_text(encoding="utf-8")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(raw_payload)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_payload)
    else:
        raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json.")
    if not isinstance(payload, dict):
        raise ValueError("Invalid registry: top-level value must be an object.")
    return payload


def _write_registry_payload(path: Path, payload: dict[str, Any]) -> None:
    suffix = path.suffix.casefold()
    if suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        mirror_path = path.with_suffix(".json")
        mirror_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return
    if suffix == ".json":
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        mirror_path = path.with_suffix(".yaml")
        mirror_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return
    raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json.")


def _extract_source_roots_by_kind(payload: dict[str, Any]) -> dict[str, Path]:
    source_roots_payload = payload.get("source_roots")
    if not isinstance(source_roots_payload, list):
        raise ValueError("Invalid registry: `source_roots` must be an array.")
    roots_by_kind: dict[str, Path] = {}
    for item in source_roots_payload:
        if not isinstance(item, dict):
            continue
        source_kind = item.get("source_kind")
        path_value = item.get("path")
        if not isinstance(source_kind, str) or not source_kind.strip():
            continue
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        roots_by_kind[source_kind.strip()] = Path(path_value.strip())
    return roots_by_kind


def _resolve_workspace_preview_path(
    *,
    request: Request,
    pointer_value: str,
    pointer_kind: str,
    allowed_roots: frozenset[str],
    allowed_suffixes: frozenset[str],
) -> tuple[Path, str]:
    source_registry = _get_source_registry_service(request)
    workspace_root = source_registry.workspace_root
    normalized_pointer = pointer_value.strip()
    if not normalized_pointer:
        raise HTTPException(status_code=400, detail=f"{pointer_kind} must not be empty.")

    candidate_path = Path(normalized_pointer)
    if not candidate_path.is_absolute():
        candidate_path = workspace_root / candidate_path
    try:
        resolved_path = candidate_path.resolve(strict=False)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to resolve {pointer_kind} `{normalized_pointer}`.",
        ) from exc

    if not resolved_path.is_relative_to(workspace_root):
        raise HTTPException(
            status_code=400,
            detail=f"{pointer_kind} must stay inside workspace boundary.",
        )

    relative_path = resolved_path.relative_to(workspace_root)
    if not relative_path.parts or relative_path.parts[0] not in allowed_roots:
        allowed_roots_label = ", ".join(sorted(allowed_roots))
        raise HTTPException(
            status_code=400,
            detail=f"{pointer_kind} must be under one of: {allowed_roots_label}.",
        )

    if allowed_suffixes and resolved_path.suffix.casefold() not in allowed_suffixes:
        allowed_suffixes_label = ", ".join(sorted(allowed_suffixes))
        raise HTTPException(
            status_code=400,
            detail=f"{pointer_kind} must use one of: {allowed_suffixes_label}.",
        )

    if not resolved_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{pointer_kind} `{relative_path.as_posix()}` was not found.",
        )

    return resolved_path, relative_path.as_posix()


def _read_json_object(path: Path, *, pointer_kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read {pointer_kind} `{path.as_posix()}`.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to decode {pointer_kind} `{path.as_posix()}` "
                f"at line {exc.lineno}, column {exc.colno}."
            ),
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{pointer_kind} `{path.as_posix()}` must contain a JSON object.",
        )
    return payload


def _preview_staged_documents(
    *,
    request: Request,
    manifest_payload: dict[str, Any],
    max_documents: int,
) -> tuple[list[SourceStagingDocumentPreviewResponse], bool]:
    entries = list(manifest_payload.get("documents", []))
    preview_rows: list[SourceStagingDocumentPreviewResponse] = []
    for entry in entries[:max_documents]:
        if not isinstance(entry, dict):
            continue
        document_path_value = str(entry.get("document_path", "")).strip()
        if not document_path_value:
            continue
        document_path, relative_document_path = _resolve_workspace_preview_path(
            request=request,
            pointer_value=document_path_value,
            pointer_kind="document_path",
            allowed_roots=_STAGING_PREVIEW_ROOTS,
            allowed_suffixes=frozenset({".json"}),
        )
        document_payload = _read_json_object(
            document_path,
            pointer_kind="staged document",
        )
        preview_rows.append(
            SourceStagingDocumentPreviewResponse(
                source_path=str(entry.get("source_path", "")),
                document_path=relative_document_path,
                document_checksum=str(entry.get("document_checksum", "")),
                payload=document_payload,
            )
        )
    return preview_rows, len(entries) > len(preview_rows)


def _preview_staged_chunk_objects(
    *,
    request: Request,
    manifest_payload: dict[str, Any],
    max_chunk_objects: int,
    max_chunk_records_per_object: int,
) -> tuple[list[SourceStagingChunkPreviewResponse], bool, bool]:
    entries = list(manifest_payload.get("chunk_objects", []))
    preview_rows: list[SourceStagingChunkPreviewResponse] = []
    any_chunk_record_truncated = False
    for entry in entries[:max_chunk_objects]:
        if not isinstance(entry, dict):
            continue
        chunk_path_value = str(entry.get("chunk_path", "")).strip()
        if not chunk_path_value:
            continue
        chunk_path, relative_chunk_path = _resolve_workspace_preview_path(
            request=request,
            pointer_value=chunk_path_value,
            pointer_kind="chunk_path",
            allowed_roots=_STAGING_PREVIEW_ROOTS,
            allowed_suffixes=frozenset({".json"}),
        )
        chunk_payload = _read_json_object(chunk_path, pointer_kind="staged chunk payload")
        raw_chunk_records = chunk_payload.get("chunk_records", [])
        if (
            isinstance(raw_chunk_records, list)
            and len(raw_chunk_records) > max_chunk_records_per_object
        ):
            any_chunk_record_truncated = True
            chunk_payload = dict(chunk_payload)
            chunk_payload["chunk_records"] = raw_chunk_records[:max_chunk_records_per_object]
            chunk_payload["chunk_records_truncated"] = True
            chunk_payload["chunk_records_total"] = len(raw_chunk_records)
        preview_rows.append(
            SourceStagingChunkPreviewResponse(
                source_path=str(entry.get("source_path", "")),
                chunk_path=relative_chunk_path,
                chunk_records_count=int(entry.get("chunk_records_count", 0)),
                payload=chunk_payload,
            )
        )
    return preview_rows, len(entries) > len(preview_rows), any_chunk_record_truncated


def _to_response(operation: SourceSyncOperation) -> SourceSyncOperationResponse:
    return SourceSyncOperationResponse(
        operation_id=operation.operation_id,
        status=operation.status,
        mode=operation.mode,
        repo_ids=list(operation.repo_ids),
        logs=[
            SourceOperationLogLineResponse(stream=log_line.stream, line=log_line.line)
            for log_line in operation.logs
        ],
        started_at=operation.started_at,
        finished_at=operation.finished_at,
    )


def _to_layout_detection_result_response(
    result: SourceLayoutDetectionResult,
) -> SourceLayoutDetectionResultResponse:
    return SourceLayoutDetectionResultResponse(
        repo_id=result.repo_id,
        layout_type=result.layout_type,
        confidence=result.confidence,
        confidence_threshold=result.confidence_threshold,
        confidence_policy_status=result.confidence_policy_status,
        manual_override_applied=result.manual_override_applied,
        dimensions=[dict(item) for item in result.dimensions],
        sample_markdown_paths=list(result.sample_markdown_paths),
        detector_version=result.detector_version,
    )


def _to_layout_detection_response(
    operation: SourceLayoutDetectionOperation,
) -> SourceLayoutDetectionOperationResponse:
    return SourceLayoutDetectionOperationResponse(
        operation_id=operation.operation_id,
        status=operation.status,
        repo_ids=list(operation.repo_ids),
        layout_backend=operation.layout_backend,
        logs=[
            SourceOperationLogLineResponse(stream=log_line.stream, line=log_line.line)
            for log_line in operation.logs
        ],
        results=[
            _to_layout_detection_result_response(result) for result in operation.results
        ],
        started_at=operation.started_at,
        finished_at=operation.finished_at,
    )


def _to_hugo_parse_warning_response(
    warning: HugoParseWarning,
) -> SourceHugoParseWarningResponse:
    return SourceHugoParseWarningResponse(
        code=warning.code,
        message=warning.message,
        line_hint=warning.line_hint,
        severity=warning.severity,
    )


def _to_hugo_heading_response(heading: HugoHeading) -> SourceHugoHeadingResponse:
    return SourceHugoHeadingResponse(
        level=heading.level,
        text=heading.text,
        line_hint=heading.line_hint,
    )


def _to_hugo_code_block_response(code_block: HugoCodeBlock) -> SourceHugoCodeBlockResponse:
    return SourceHugoCodeBlockResponse(
        language=code_block.language,
        code=code_block.code,
        line_start=code_block.line_start,
        line_end=code_block.line_end,
    )


def _to_hugo_page_response(page: HugoNormalizedPage) -> SourceHugoNormalizedPageResponse:
    return SourceHugoNormalizedPageResponse(
        repo_id=page.repo_id,
        source_path=page.source_path,
        source_kind=page.source_kind,
        product_id=page.product_id,
        product_family=page.product_family,
        programming_language=page.programming_language,
        doc_locale=page.doc_locale,
        title=page.title,
        metadata=dict(page.metadata),
        body_plain=page.body_plain,
        headings=[_to_hugo_heading_response(heading) for heading in page.headings],
        code_blocks=[_to_hugo_code_block_response(code_block) for code_block in page.code_blocks],
        parse_warnings=[
            _to_hugo_parse_warning_response(warning) for warning in page.parse_warnings
        ],
        is_index_page=page.is_index_page,
    )


def _to_chunk_record_response(record: StageDChunkRecord) -> SourceChunkRecordResponse:
    return SourceChunkRecordResponse(
        chunk_id=record.chunk_id,
        repo_id=record.repo_id,
        product_id=record.product_id,
        product_family=record.product_family,
        programming_language=record.programming_language,
        version=record.version,
        source_kind=record.source_kind,
        doc_locale=record.doc_locale,
        doc_type=record.doc_type,
        symbol_fqn=record.symbol_fqn,
        title=record.title,
        section_path=list(record.section_path),
        canonical_url=record.canonical_url,
        section_anchor=record.section_anchor,
        source_path=record.source_path,
        source_revision=record.source_revision,
        is_deprecated=record.is_deprecated,
        has_code_example=record.has_code_example,
        chunk_type=record.chunk_type,
        text=record.text,
        tokens=record.tokens,
        checksum=record.checksum,
        executable_snippets=[
            SourceExecutableSnippetResponse(
                snippet_id=snippet.snippet_id,
                language=snippet.language,
                code=snippet.code,
                parent_canonical_url=snippet.parent_canonical_url,
                parent_section_anchor=snippet.parent_section_anchor,
                parent_symbol_fqn=snippet.parent_symbol_fqn,
            )
            for snippet in record.executable_snippets
        ],
    )


def _to_index_publish_summary_response(
    summary: IndexPublishSummary,
) -> SourceIndexPublishSummaryResponse:
    return SourceIndexPublishSummaryResponse(
        snapshot_id=summary.snapshot_id,
        product_id=summary.product_id,
        programming_language=summary.programming_language,
        version=summary.version,
        source_kind=summary.source_kind,
        source_revision=summary.source_revision,
        indexed_chunks_count=summary.indexed_chunks_count,
        vector_records_count=summary.vector_records_count,
        lexical_records_count=summary.lexical_records_count,
        vector_collection=summary.vector_collection,
        lexical_index=summary.lexical_index,
        lexical_alias=summary.lexical_alias,
        active_snapshot_id=summary.active_snapshot_id,
        mode=summary.mode,
        dry_run=summary.dry_run,
        force_full_reindex=summary.force_full_reindex,
        partial_publish_threshold_pct=summary.partial_publish_threshold_pct,
        error_ratio=summary.error_ratio,
        decision=summary.decision,
        publish_blocked_reason=summary.publish_blocked_reason,
        total_items_count=summary.total_items_count,
        failed_items_count=summary.failed_items_count,
        metadata_quarantine_policy=summary.metadata_quarantine_policy,
        quarantined_items_count=summary.quarantined_items_count,
        canonical_url_remap_entries_count=summary.canonical_url_remap_entries_count,
        canonical_url_remap_applied_count=summary.canonical_url_remap_applied_count,
        canonical_url_remap_conflict_count=summary.canonical_url_remap_conflict_count,
        canonical_url_remap_override_count=summary.canonical_url_remap_override_count,
        event_summary=_to_critical_event_summary_response(summary.event_summary),
        notification_summary=_to_notification_summary_response(summary.notification_summary),
        semantic_gate=_to_semantic_gate_summary_response(summary.semantic_gate),
        conversion_gate=_to_conversion_gate_summary_response(summary.conversion_gate),
        publish_safety_gate=_to_publish_safety_gate_summary_response(
            summary.publish_safety_gate
        ),
        incremental_mode=summary.incremental_mode,
        incremental_detection_strategy=summary.incremental_detection_strategy,
        incremental_fallback_reason=summary.incremental_fallback_reason,
        incremental_git_base_revision=summary.incremental_git_base_revision,
        baseline_snapshot_id=summary.baseline_snapshot_id,
        file_total_count=summary.file_total_count,
        file_new_count=summary.file_new_count,
        file_changed_count=summary.file_changed_count,
        file_unchanged_count=summary.file_unchanged_count,
        file_removed_count=summary.file_removed_count,
        chunk_total_count=summary.chunk_total_count,
        chunk_new_count=summary.chunk_new_count,
        chunk_changed_count=summary.chunk_changed_count,
        chunk_unchanged_count=summary.chunk_unchanged_count,
        chunk_removed_count=summary.chunk_removed_count,
    )


def _to_critical_event_summary_response(
    summary: CriticalEventSummary,
) -> SourceCriticalEventSummaryResponse:
    return SourceCriticalEventSummaryResponse(
        event_ids=list(summary.event_ids),
        event_types=list(summary.event_types),
    )


def _to_notification_summary_response(
    summary: NotificationDispatchSummary,
) -> SourceNotificationSummaryResponse:
    return SourceNotificationSummaryResponse(
        sent_count=summary.sent_count,
        failed_count=summary.failed_count,
    )


def _to_semantic_gate_transition_response(
    transition: SemanticGateStatusTransition,
) -> SourceSemanticGateTransitionResponse:
    return SourceSemanticGateTransitionResponse(
        transition_id=transition.transition_id,
        from_status=transition.from_status,
        to_status=transition.to_status,
        actor_type=transition.actor_type,
        actor_key_id=transition.actor_key_id,
        reason=transition.reason,
        request_id=transition.request_id,
        created_at=transition.created_at,
    )


def _to_semantic_gate_summary_response(
    summary: SemanticGateSummary,
) -> SourceSemanticGateSummaryResponse:
    return SourceSemanticGateSummaryResponse(
        enforced=summary.enforced,
        trigger_type=summary.trigger_type,
        decision=summary.decision.value,
        reason_codes=list(summary.reason_codes),
        review_run_id=summary.review_run_id,
        review_status=summary.review_status,
        approval_mode=summary.approval_mode,
        overall_score=summary.overall_score,
        threshold_score=summary.threshold_score,
        fail_fast_triggered=summary.fail_fast_triggered,
        blocking_error_count=summary.blocking_error_count,
        status_transitions=[
            _to_semantic_gate_transition_response(transition)
            for transition in summary.status_transitions
        ],
    )


def _to_conversion_gate_summary_response(
    summary: ConversionGateSummary,
) -> SourceConversionGateSummaryResponse:
    return SourceConversionGateSummaryResponse(
        phase=str(summary.phase),
        enforcement_mode=str(summary.enforcement_mode),
        blocking=bool(summary.blocking),
        reason_codes=list(summary.reason_codes),
        parse_coverage_pct=float(summary.parse_coverage_pct),
        schema_valid_pct=float(summary.schema_valid_pct),
        metadata_completeness_pct=float(summary.metadata_completeness_pct),
        citation_integrity_pct=float(summary.citation_integrity_pct),
        api_signature_coverage_pct=(
            float(summary.api_signature_coverage_pct)
            if summary.api_signature_coverage_pct is not None
            else None
        ),
        api_parameter_coverage_pct=(
            float(summary.api_parameter_coverage_pct)
            if summary.api_parameter_coverage_pct is not None
            else None
        ),
        hallucination_risk_pct=float(summary.hallucination_risk_pct),
    )


def _to_publish_safety_gate_summary_response(
    summary: PublishSafetyGateSummary,
) -> SourcePublishSafetyGateSummaryResponse:
    return SourcePublishSafetyGateSummaryResponse(
        blocking=bool(summary.blocking),
        reason_codes=list(summary.reason_codes),
        usable_chunk_coverage_pct=float(summary.usable_chunk_coverage_pct),
        coverage_threshold_pct=float(summary.coverage_threshold_pct),
        parser_critical_failed_items_count=int(summary.parser_critical_failed_items_count),
        active_scopes_count=int(summary.active_scopes_count),
        empty_usable_scope_detected=bool(summary.empty_usable_scope_detected),
    )


def _to_metadata_quarantine_summary_response(
    summary: MetadataQuarantineSummary,
) -> SourceMetadataQuarantineSummaryResponse:
    return SourceMetadataQuarantineSummaryResponse(
        policy_mode=summary.policy_mode,
        total_count=summary.total_count,
        reason_counts=[
            SourceMetadataQuarantineReasonCountResponse(
                reason_code=reason_count.reason_code,
                count=reason_count.count,
            )
            for reason_count in summary.reason_counts
        ],
        sample_items=[
            SourceMetadataQuarantineItemResponse(
                source_path=item.source_path,
                reason_code=item.reason_code,
                message=item.message,
            )
            for item in summary.sample_items
        ],
    )


def _to_canonical_url_mapping_summary_response(
    summary: SourceCanonicalUrlMappingSummary,
) -> SourceCanonicalUrlMappingSummaryResponse:
    return SourceCanonicalUrlMappingSummaryResponse(
        contexts=list(summary.contexts),
        remap_entries_count=summary.remap_entries_count,
        remap_applied_count=summary.remap_applied_count,
        remap_conflict_count=summary.remap_conflict_count,
        remap_override_count=summary.remap_override_count,
    )


def _to_prompt_variant_evaluation_response(
    summary: ConversionPromptVariantEvaluation,
) -> SourcePromptVariantEvaluationResponse:
    return SourcePromptVariantEvaluationResponse(
        variant_id=summary.variant_id,
        assigned_count=summary.assigned_count,
        success_count=summary.success_count,
        failed_count=summary.failed_count,
        parse_warnings_count=summary.parse_warnings_count,
        success_rate=summary.success_rate,
        warning_rate=summary.warning_rate,
    )


def _to_prompt_evaluation_summary_response(
    summary: ConversionPromptEvaluationSummary,
) -> SourcePromptEvaluationSummaryResponse:
    return SourcePromptEvaluationSummaryResponse(
        registry_version=summary.registry_version,
        experiment_id=summary.experiment_id,
        assignment_unit=summary.assignment_unit,
        total_assigned_count=summary.total_assigned_count,
        successful_count=summary.successful_count,
        failed_count=summary.failed_count,
        parse_warnings_count=summary.parse_warnings_count,
        best_variant_id=summary.best_variant_id,
        variants=[
            _to_prompt_variant_evaluation_response(item) for item in summary.variants
        ],
    )


def _to_hugo_failed_item_response(
    failed_item: SourceHugoNormalizationFailedItem,
) -> SourceHugoNormalizationFailedItemResponse:
    return SourceHugoNormalizationFailedItemResponse(
        source_path=failed_item.source_path,
        error_code=failed_item.error_code,
        message=failed_item.message,
    )


def _to_staging_scope_summary_response(
    summary: SourceStagingScopeSummary,
) -> SourceStagingScopeSummaryResponse:
    return SourceStagingScopeSummaryResponse(
        product_id=summary.product_id,
        programming_language=summary.programming_language,
        version=summary.version,
        doc_locale=summary.doc_locale,
        source_kind=summary.source_kind,
        manifest_path=summary.manifest_path,
        documents_count=summary.documents_count,
        chunk_records_count=summary.chunk_records_count,
    )


def _to_hugo_result_response(
    result: SourceHugoNormalizationResult,
) -> SourceHugoNormalizationResultResponse:
    return SourceHugoNormalizationResultResponse(
        repo_id=result.repo_id,
        source_kind=result.source_kind,
        parsed_pages_count=result.parsed_pages_count,
        parse_warnings_count=result.parse_warnings_count,
        review_artifact_path=result.review_artifact_path,
        staging_repository_manifest_path=result.staging_repository_manifest_path,
        staging_replay_used=result.staging_replay_used,
        staging_scopes=[
            _to_staging_scope_summary_response(item) for item in result.staging_scopes
        ],
        pages=[_to_hugo_page_response(page) for page in result.pages],
        chunk_records=[
            _to_chunk_record_response(chunk_record) for chunk_record in result.chunk_records
        ],
        indexing_summary=_to_index_publish_summary_response(result.indexing_summary),
        failed_items=[
            _to_hugo_failed_item_response(failed_item) for failed_item in result.failed_items
        ],
        metadata_quarantine=_to_metadata_quarantine_summary_response(
            result.metadata_quarantine
        ),
        prompt_evaluation=_to_prompt_evaluation_summary_response(
            result.prompt_evaluation
        ),
        canonical_url_mapping=_to_canonical_url_mapping_summary_response(
            result.canonical_url_mapping
        ),
        # `or 0` defends against deserialised operations from disk where the
        # field was absent from the JSON record — the generic dataclass
        # deserialiser in operation_state_store.py:_deserialize_value passes
        # `None` for missing keys, overriding the dataclass default of 0.
        canonical_documents_count=result.canonical_documents_count or 0,
        chunk_records_count=result.chunk_records_count or 0,
    )


def _to_hugo_operation_response(
    operation: SourceHugoNormalizationOperation,
) -> SourceHugoNormalizationOperationResponse:
    return SourceHugoNormalizationOperationResponse(
        operation_id=operation.operation_id,
        job_id=operation.operation_id,
        status=operation.status,
        repo_ids=list(operation.repo_ids),
        mode=operation.mode,
        requested_mode=operation.requested_mode,
        conversion_backend=operation.conversion_backend,
        prompt_registry_version=operation.prompt_registry_version,
        prompt_experiment_id=operation.prompt_experiment_id,
        dry_run=operation.dry_run,
        force_full_reindex=operation.force_full_reindex,
        request_id=operation.request_id,
        idempotency_key=operation.idempotency_key,
        idempotency_scope=operation.idempotency_scope,
        idempotency_reused=operation.idempotency_reused,
        idempotency_expires_at=operation.idempotency_expires_at,
        attempt_count=operation.attempt_count,
        max_attempts=operation.max_attempts,
        next_retry_at=operation.next_retry_at,
        last_error_kind=operation.last_error_kind,
        cancel_requested_at=operation.cancel_requested_at,
        cancelled_at=operation.cancelled_at,
        resumable=operation.resumable,
        logs=[
            SourceOperationLogLineResponse(stream=log_line.stream, line=log_line.line)
            for log_line in operation.logs
        ],
        results=[_to_hugo_result_response(result) for result in operation.results],
        started_at=operation.started_at,
        finished_at=operation.finished_at,
    )


def _build_onboarding_bootstrap_response(
    *,
    layout_detection_requested: bool,
    validate_only_requested: bool,
    layout_detection_operation: SourceLayoutDetectionOperation | None,
    validate_only_operation: SourceHugoNormalizationOperation | None,
    warnings: list[str],
) -> SourceRepositoriesOnboardProductBootstrapResponse:
    status = "not_requested"
    if layout_detection_requested or validate_only_requested:
        statuses = {
            operation.status.value
            for operation in (layout_detection_operation, validate_only_operation)
            if operation is not None
        }
        if warnings or "failed" in statuses:
            status = "completed_with_warnings"
        elif statuses and statuses == {"completed"}:
            status = "completed"
        else:
            status = "partial"
    return SourceRepositoriesOnboardProductBootstrapResponse(
        status=status,
        layout_detection_requested=layout_detection_requested,
        validate_only_requested=validate_only_requested,
        layout_detection_operation=(
            _to_layout_detection_response(layout_detection_operation)
            if layout_detection_operation is not None
            else None
        ),
        validate_only_operation=(
            _to_hugo_operation_response(validate_only_operation)
            if validate_only_operation is not None
            else None
        ),
        warnings=list(warnings),
    )


@router.post(
    "/admin/v1/source-repositories/onboard-product",
    response_model=SourceRepositoriesOnboardProductResponse,
)
def onboard_source_repositories_product(
    payload: SourceRepositoriesOnboardProductRequest,
    request: Request,
) -> SourceRepositoriesOnboardProductResponse:
    """Create docs/apiref source-repository entries for one new product."""
    _authorize_superuser_mutation(request=request)
    source_registry = _get_source_registry_service(request)
    registry_path = source_registry.registry_path
    workspace_root = source_registry.workspace_root

    try:
        registry_payload = _load_registry_payload(registry_path)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    source_roots_by_kind = _extract_source_roots_by_kind(registry_payload)
    docs_root = source_roots_by_kind.get("docs")
    apiref_root = source_roots_by_kind.get("apiref")
    if docs_root is None or apiref_root is None:
        raise HTTPException(
            status_code=500,
            detail="Invalid registry: docs/apiref source roots are required.",
        )

    repositories_payload = registry_payload.get("repositories")
    if not isinstance(repositories_payload, list):
        raise HTTPException(
            status_code=500,
            detail="Invalid registry: `repositories` must be an array.",
        )

    docs_repo_id = f"{payload.product_id}.docs"
    apiref_repo_id = f"{payload.product_id}.apiref"
    existing_repo_ids: set[str] = set()
    for item in repositories_payload:
        if isinstance(item, dict):
            repo_id = item.get("repo_id")
            if isinstance(repo_id, str) and repo_id.strip():
                existing_repo_ids.add(repo_id.strip())
    conflicted_repo_ids = sorted(
        repo_id for repo_id in (docs_repo_id, apiref_repo_id) if repo_id in existing_repo_ids
    )
    if conflicted_repo_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": "Repository ids already exist in registry.",
                    "details": {"repo_ids": conflicted_repo_ids},
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    docs_submodule_path = (docs_root / payload.product_family_dir).as_posix()
    apiref_submodule_path = (apiref_root / payload.product_family_dir).as_posix()
    docs_local_path = (workspace_root / docs_submodule_path).resolve()
    apiref_local_path = (workspace_root / apiref_submodule_path).resolve()
    docs_local_path_created = not docs_local_path.exists()
    apiref_local_path_created = not apiref_local_path.exists()
    docs_local_path.mkdir(parents=True, exist_ok=True)
    apiref_local_path.mkdir(parents=True, exist_ok=True)

    product_name = payload.product_name or payload.product_family_dir
    now_utc = datetime.now(tz=UTC).isoformat()
    default_ingestion = {
        "latest_stable_only": True,
        "enabled": True,
        "triggers": ["webhook", "admin_button"],
        "incremental_diff_preferred": True,
        "fallback_strategy": "full_reindex",
    }
    default_layout = {
        "status": "pending",
        "detector_version": "layout-detector.v1",
        "detected_at_utc": now_utc,
        "layout_type": "unknown",
        "confidence": 0.0,
        "algorithm_metrics": {},
        "dimensions": [],
        "sample_markdown_paths": [],
        "notes": [
            "Repository was onboarded from admin UI.",
            "Run layout detection before first production publish.",
        ],
    }
    onboarding_hints = {
        "programming_languages": list(payload.programming_languages),
    }

    created_repositories = [
        {
            "repo_id": docs_repo_id,
            "product_id": payload.product_id,
            "product_name": product_name,
            "product_family": payload.product_family,
            "product_family_dir": payload.product_family_dir,
            "source_kind": "docs",
            "format": "hugo-md",
            "git": {
                "provider": "github",
                "url": payload.docs_git_url,
                "submodule_path": docs_submodule_path,
                "default_branch": payload.docs_default_branch,
            },
            "layout_detection": dict(default_layout),
            "ingestion": dict(default_ingestion),
            "onboarding_hints": dict(onboarding_hints),
        },
        {
            "repo_id": apiref_repo_id,
            "product_id": payload.product_id,
            "product_name": product_name,
            "product_family": payload.product_family,
            "product_family_dir": payload.product_family_dir,
            "source_kind": "apiref",
            "format": "hugo-md",
            "git": {
                "provider": "github",
                "url": payload.apiref_git_url,
                "submodule_path": apiref_submodule_path,
                "default_branch": payload.apiref_default_branch,
            },
            "layout_detection": dict(default_layout),
            "ingestion": dict(default_ingestion),
            "onboarding_hints": dict(onboarding_hints),
        },
    ]

    repositories_payload.extend(created_repositories)
    try:
        _write_registry_payload(registry_path, registry_payload)
        request.app.state.source_registry_service = SourceRegistryService(
            registry_path=registry_path,
            workspace_root=workspace_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    bootstrap_repo_ids = (docs_repo_id, apiref_repo_id)
    bootstrap_warnings: list[str] = []
    layout_detection_requested = (
        payload.auto_run_layout_detection or payload.auto_run_validate_only
    )
    validate_only_requested = payload.auto_run_validate_only
    layout_detection_operation: SourceLayoutDetectionOperation | None = None
    validate_only_operation: SourceHugoNormalizationOperation | None = None

    if layout_detection_requested:
        try:
            layout_detection_operation = _get_layout_detection_orchestrator(request).run(
                repo_ids=bootstrap_repo_ids
            )
            if layout_detection_operation.status is SourceLayoutDetectionStatus.FAILED:
                bootstrap_warnings.append(
                    "Auto layout detection finished with failures. "
                    "Review layout logs before production publish."
                )
        except Exception as exc:  # pragma: no cover
            bootstrap_warnings.append(
                f"Auto layout detection failed to start: {exc.__class__.__name__}: {exc}"
            )

    if validate_only_requested:
        try:
            validate_only_operation = _get_hugo_normalization_orchestrator(request).run(
                repo_ids=bootstrap_repo_ids,
                mode=IngestionRunMode.VALIDATE_ONLY,
                dry_run=True,
            )
            if validate_only_operation.status is SourceHugoNormalizationStatus.FAILED:
                bootstrap_warnings.append(
                    "Validate-Only bootstrap finished with failures. "
                    "Review normalization logs and staging results."
                )
        except Exception as exc:  # pragma: no cover
            bootstrap_warnings.append(
                f"Validate-Only bootstrap failed to start: {exc.__class__.__name__}: {exc}"
            )

    bootstrap = _build_onboarding_bootstrap_response(
        layout_detection_requested=layout_detection_requested,
        validate_only_requested=validate_only_requested,
        layout_detection_operation=layout_detection_operation,
        validate_only_operation=validate_only_operation,
        warnings=bootstrap_warnings,
    )
    next_steps = [
        "Run Source Sync (mode=sync or update) for new repo_ids to initialize submodules.",
        (
            "Layout detection and Validate-Only bootstrap were started automatically. "
            "Review bootstrap results below."
            if bootstrap.status != "not_requested"
            else "Run Layout Detection and verify detected dimensions."
        ),
        (
            "Inspect Validate-Only output. If it is clean, Trigger Publish is the next safe step."
            if validate_only_requested
            else "Run Validate-Only ingestion before first Publish."
        ),
    ]
    if bootstrap.status == "completed_with_warnings":
        next_steps.append(
            "Bootstrap reported warnings. Inspect operation logs before production publish."
        )

    return SourceRepositoriesOnboardProductResponse(
        product_id=payload.product_id,
        product_family=payload.product_family,
        product_family_dir=payload.product_family_dir,
        created_repo_ids=[docs_repo_id, apiref_repo_id],
        repositories=[
            SourceRepositoriesOnboardedRepoResponse(
                repo_id=docs_repo_id,
                source_kind="docs",
                git_url=payload.docs_git_url,
                default_branch=payload.docs_default_branch,
                submodule_path=docs_submodule_path,
                local_path_created=docs_local_path_created,
            ),
            SourceRepositoriesOnboardedRepoResponse(
                repo_id=apiref_repo_id,
                source_kind="apiref",
                git_url=payload.apiref_git_url,
                default_branch=payload.apiref_default_branch,
                submodule_path=apiref_submodule_path,
                local_path_created=apiref_local_path_created,
            ),
        ],
        programming_languages=list(payload.programming_languages),
        registry_path=registry_path.as_posix(),
        next_steps=next_steps,
        bootstrap=bootstrap,
    )


@router.post("/admin/v1/source-repositories/sync", response_model=SourceSyncOperationResponse)
def trigger_source_repositories_sync(
    payload: SourceRepositoriesSyncTriggerRequest,
    request: Request,
) -> SourceSyncOperationResponse:
    """Trigger one source sync operation for all repositories or selected repo ids."""
    repo_ids = payload.resolved_repo_ids()
    _authorize_ingestion_mutation(request=request, repo_ids=repo_ids)
    orchestrator = _get_orchestrator(request)
    dispatcher = _get_task_dispatcher(request)
    operation = orchestrator.run(
        mode=payload.mode,
        repo_ids=repo_ids,
        execute_immediately=False,
    )
    operation = dispatcher.dispatch_source_sync(
        orchestrator=orchestrator,
        operation_id=operation.operation_id,
    )
    return _to_response(operation)


@router.get("/admin/v1/source-repositories/sync", response_model=list[SourceSyncOperationResponse])
def list_source_repositories_sync_operations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SourceSyncOperationResponse]:
    """List recent source sync operations with statuses and logs."""
    orchestrator = _get_orchestrator(request)
    operations = orchestrator.list_operations(limit=limit)
    return [_to_response(operation) for operation in operations]


@router.get(
    "/admin/v1/source-repositories/sync/{operation_id}",
    response_model=SourceSyncOperationResponse,
)
def get_source_repositories_sync_operation(
    operation_id: str,
    request: Request,
) -> SourceSyncOperationResponse:
    """Fetch a source sync operation by operation id."""
    orchestrator = _get_orchestrator(request)
    try:
        operation = orchestrator.get_operation(operation_id)
    except SourceSyncOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(operation)


@router.post(
    "/admin/v1/source-repositories/layout-detection",
    response_model=SourceLayoutDetectionOperationResponse,
)
def trigger_source_repositories_layout_detection(
    payload: SourceLayoutDetectionTriggerRequest,
    request: Request,
) -> SourceLayoutDetectionOperationResponse:
    """Trigger one source layout detection operation with optional repo filtering."""
    repo_ids = payload.resolved_repo_ids()
    _authorize_ingestion_mutation(request=request, repo_ids=repo_ids)
    orchestrator = _get_layout_detection_orchestrator(request)
    dispatcher = _get_task_dispatcher(request)
    operation = orchestrator.run(repo_ids=repo_ids, execute_immediately=False)
    operation = dispatcher.dispatch_layout_detection(
        orchestrator=orchestrator,
        operation_id=operation.operation_id,
    )
    return _to_layout_detection_response(operation)


@router.get(
    "/admin/v1/source-repositories/layout-detection",
    response_model=list[SourceLayoutDetectionOperationResponse],
)
def list_source_repositories_layout_detection_operations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SourceLayoutDetectionOperationResponse]:
    """List recent source layout detection operations with statuses, logs, and results."""
    orchestrator = _get_layout_detection_orchestrator(request)
    operations = orchestrator.list_operations(limit=limit)
    return [_to_layout_detection_response(operation) for operation in operations]


@router.get(
    "/admin/v1/source-repositories/layout-detection/{operation_id}",
    response_model=SourceLayoutDetectionOperationResponse,
)
def get_source_repositories_layout_detection_operation(
    operation_id: str,
    request: Request,
) -> SourceLayoutDetectionOperationResponse:
    """Fetch one source layout detection operation by operation id."""
    orchestrator = _get_layout_detection_orchestrator(request)
    try:
        operation = orchestrator.get_operation(operation_id)
    except SourceLayoutDetectionOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_layout_detection_response(operation)


@router.post(
    "/admin/v1/source-repositories/layout-detection/{repo_id}/override",
    response_model=SourceLayoutDetectionResultResponse,
)
def set_source_repositories_layout_detection_override(
    repo_id: str,
    payload: SourceLayoutManualOverrideRequest,
    request: Request,
) -> SourceLayoutDetectionResultResponse:
    """Persist manual layout override for one repository and return effective metadata."""
    normalized_repo_id = repo_id.strip()
    if not normalized_repo_id:
        raise HTTPException(status_code=400, detail="repo_id must not be empty.")
    _authorize_ingestion_mutation(request=request, repo_ids=(normalized_repo_id,))
    orchestrator = _get_layout_detection_orchestrator(request)
    try:
        result = orchestrator.set_manual_override(
            repo_id=normalized_repo_id,
            override_payload=payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_layout_detection_result_response(result)


@router.post(
    "/admin/v1/source-repositories/hugo-normalize",
    response_model=SourceHugoNormalizationOperationResponse,
)
def trigger_source_repositories_hugo_normalization(
    payload: SourceHugoNormalizationTriggerRequest,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Trigger one Stage-A Hugo parser + normalizer operation with optional repo filtering."""
    return _trigger_hugo_normalization_operation(payload=payload, request=request)


@router.post(
    "/admin/v1/ingestion/trigger",
    response_model=SourceHugoNormalizationOperationResponse,
)
def trigger_ingestion_operation(
    payload: SourceHugoNormalizationTriggerRequest,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Trigger one ingestion operation using future /admin/v1/ingestion contract path."""
    return _trigger_hugo_normalization_operation(payload=payload, request=request)


@router.post(
    "/admin/v1/ingestion/reindex",
    response_model=SourceHugoNormalizationOperationResponse,
)
def trigger_ingestion_reindex_operation(
    payload: SourceHugoNormalizationTriggerRequest,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Trigger forced full reindex under /admin/v1/ingestion contract path.

    The `/reindex` endpoint semantically requests a complete rebuild from
    source, so it implicitly bypasses staging replay. Callers who need the
    replay fast-path should use `/trigger` with `force_full_reindex=True`
    and leave `bypass_staging_replay` at its default `False`.
    """
    forced_payload = payload.model_copy(
        update={
            "force_full_reindex": True,
            "bypass_staging_replay": True,
        }
    )
    return _trigger_hugo_normalization_operation(payload=forced_payload, request=request)


def _trigger_hugo_normalization_operation(
    *,
    payload: SourceHugoNormalizationTriggerRequest,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    repo_ids = payload.resolved_repo_ids()
    _authorize_ingestion_mutation(request=request, repo_ids=repo_ids)
    orchestrator = _get_hugo_normalization_orchestrator(request)
    dispatcher = _get_task_dispatcher(request)
    request_id = getattr(request.state, "request_id", None)
    try:
        operation = orchestrator.run(
            repo_ids=repo_ids,
            mode=payload.mode,
            partial_publish_threshold_pct=payload.partial_publish_threshold_pct,
            metadata_quarantine_policy=payload.metadata_quarantine_policy,
            request_id=request_id,
            idempotency_key=payload.idempotency_key,
            dry_run=payload.dry_run,
            force_full_reindex=payload.force_full_reindex,
            bypass_staging_replay=payload.bypass_staging_replay,
            execute_immediately=False,
        )
        operation = dispatcher.dispatch_ingestion(
            orchestrator=orchestrator,
            operation_id=operation.operation_id,
        )
    except IngestionIdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": str(exc),
                    "details": {},
                    "request_id": request_id,
                }
            },
        ) from exc
    return _to_hugo_operation_response(operation)


@router.get(
    "/admin/v1/source-repositories/hugo-normalize",
    response_model=list[SourceHugoNormalizationOperationResponse],
)
def list_source_repositories_hugo_normalization_operations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SourceHugoNormalizationOperationResponse]:
    """List recent Stage-A Hugo parser + normalizer operations."""
    return _list_hugo_normalization_operations(request=request, limit=limit)


@router.get(
    "/admin/v1/ingestion/jobs",
    response_model=list[SourceHugoNormalizationOperationResponse],
)
def list_ingestion_operations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SourceHugoNormalizationOperationResponse]:
    """List recent ingestion operations under /admin/v1/ingestion group."""
    return _list_hugo_normalization_operations(request=request, limit=limit)


def _list_hugo_normalization_operations(
    *,
    request: Request,
    limit: int,
) -> list[SourceHugoNormalizationOperationResponse]:
    orchestrator = _get_hugo_normalization_orchestrator(request)
    operations = orchestrator.list_operations(limit=limit)
    return [_to_hugo_operation_response(operation) for operation in operations]


@router.get(
    "/admin/v1/source-repositories/hugo-normalize/{operation_id}",
    response_model=SourceHugoNormalizationOperationResponse,
)
def get_source_repositories_hugo_normalization_operation(
    operation_id: str,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Fetch one Stage-A Hugo parser + normalizer operation by operation id."""
    return _get_hugo_normalization_operation(operation_id=operation_id, request=request)


@router.get(
    "/admin/v1/ingestion/jobs/{operation_id}",
    response_model=SourceHugoNormalizationOperationResponse,
)
def get_ingestion_operation(
    operation_id: str,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Fetch one ingestion operation by operation id under /admin/v1/ingestion group."""
    return _get_hugo_normalization_operation(operation_id=operation_id, request=request)


def _get_hugo_normalization_operation(
    *,
    operation_id: str,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    orchestrator = _get_hugo_normalization_orchestrator(request)
    try:
        operation = orchestrator.get_operation(operation_id)
    except SourceHugoNormalizationOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_hugo_operation_response(operation)


@router.post(
    "/admin/v1/source-repositories/review-artifact:preview",
    response_model=SourceReviewArtifactPreviewResponse,
)
def preview_ingestion_review_artifact(
    payload: SourceReviewArtifactPreviewRequest,
    request: Request,
) -> SourceReviewArtifactPreviewResponse:
    """Load one persisted review artifact JSON for operator inspection."""
    artifact_path, relative_artifact_path = _resolve_workspace_preview_path(
        request=request,
        pointer_value=payload.artifact_path,
        pointer_kind="artifact_path",
        allowed_roots=_ARTIFACT_PREVIEW_ROOTS,
        allowed_suffixes=frozenset({".json"}),
    )
    artifact_payload = _read_json_object(artifact_path, pointer_kind="review artifact")
    return SourceReviewArtifactPreviewResponse(
        artifact_path=relative_artifact_path,
        payload=artifact_payload,
    )


@router.post(
    "/admin/v1/source-repositories/raw-markdown:preview",
    response_model=SourceRawMarkdownPreviewResponse,
)
def preview_source_raw_markdown(
    payload: SourceRawMarkdownPreviewRequest,
    request: Request,
) -> SourceRawMarkdownPreviewResponse:
    """Load one raw markdown source file for side-by-side review."""
    markdown_path, relative_markdown_path = _resolve_workspace_preview_path(
        request=request,
        pointer_value=payload.source_path,
        pointer_kind="source_path",
        allowed_roots=_SOURCE_PREVIEW_ROOTS,
        allowed_suffixes=frozenset({".md", ".markdown"}),
    )
    try:
        raw_markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read source markdown `{relative_markdown_path}`.",
        ) from exc
    return SourceRawMarkdownPreviewResponse(
        source_path=relative_markdown_path,
        size_bytes=len(raw_markdown.encode("utf-8")),
        line_count=len(raw_markdown.splitlines()),
        raw_markdown=raw_markdown,
    )


@router.post(
    "/admin/v1/source-repositories/staging-manifest:preview",
    response_model=SourceStagingManifestPreviewResponse,
)
def preview_staging_manifest(
    payload: SourceStagingManifestPreviewRequest,
    request: Request,
) -> SourceStagingManifestPreviewResponse:
    """Load one staging manifest with embedded normalized-document and chunk previews."""
    manifest_path, relative_manifest_path = _resolve_workspace_preview_path(
        request=request,
        pointer_value=payload.manifest_path,
        pointer_kind="manifest_path",
        allowed_roots=_STAGING_PREVIEW_ROOTS,
        allowed_suffixes=frozenset({".json"}),
    )
    manifest_payload = _read_json_object(manifest_path, pointer_kind="staging manifest")
    manifest_kind = (
        "repository"
        if "scope_manifests" in manifest_payload
        else "scope"
        if "scope" in manifest_payload
        else "unknown"
    )
    documents_preview, documents_truncated = _preview_staged_documents(
        request=request,
        manifest_payload=manifest_payload,
        max_documents=payload.max_documents,
    )
    chunk_objects_preview, chunk_objects_truncated, chunk_records_truncated = (
        _preview_staged_chunk_objects(
            request=request,
            manifest_payload=manifest_payload,
            max_chunk_objects=payload.max_chunk_objects,
            max_chunk_records_per_object=payload.max_chunk_records_per_object,
        )
    )
    return SourceStagingManifestPreviewResponse(
        manifest_path=relative_manifest_path,
        manifest_kind=manifest_kind,
        payload=manifest_payload,
        documents_preview=documents_preview,
        chunk_objects_preview=chunk_objects_preview,
        documents_truncated=documents_truncated,
        chunk_objects_truncated=chunk_objects_truncated,
        chunk_records_truncated=chunk_records_truncated,
    )


@router.post(
    "/admin/v1/ingestion/jobs/{operation_id}:cancel",
    response_model=SourceHugoNormalizationOperationResponse,
    tags=["admin-source-repositories"],
)
def cancel_ingestion_operation(
    operation_id: str,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Request cancellation for ingestion operation."""
    orchestrator = _get_hugo_normalization_orchestrator(request)
    try:
        existing = orchestrator.get_operation(operation_id)
    except SourceHugoNormalizationOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _authorize_ingestion_mutation(request=request, repo_ids=existing.repo_ids)
    updated = orchestrator.cancel_operation(
        operation_id=operation_id,
        request_id=request.headers.get("x-request-id"),
    )
    return _to_hugo_operation_response(updated)


@router.post(
    "/admin/v1/ingestion/jobs/{operation_id}:retry",
    response_model=SourceHugoNormalizationOperationResponse,
    tags=["admin-source-repositories"],
)
def retry_ingestion_operation(
    operation_id: str,
    payload: IngestionJobRetryRequest,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Retry failed/retry-scheduled ingestion operation."""
    orchestrator = _get_hugo_normalization_orchestrator(request)
    try:
        existing = orchestrator.get_operation(operation_id)
    except SourceHugoNormalizationOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _authorize_ingestion_mutation(request=request, repo_ids=existing.repo_ids)
    try:
        updated = orchestrator.retry_operation(
            operation_id=operation_id,
            request_id=request.headers.get("x-request-id"),
            force=payload.force,
            execute_immediately=False,
        )
        updated = _get_task_dispatcher(request).dispatch_ingestion(
            orchestrator=orchestrator,
            operation_id=updated.operation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_hugo_operation_response(updated)


@router.post(
    "/admin/v1/ingestion/jobs/{operation_id}:resume",
    response_model=SourceHugoNormalizationOperationResponse,
    tags=["admin-source-repositories"],
)
def resume_ingestion_operation(
    operation_id: str,
    request: Request,
) -> SourceHugoNormalizationOperationResponse:
    """Resume cancelled/failed ingestion operation."""
    orchestrator = _get_hugo_normalization_orchestrator(request)
    try:
        existing = orchestrator.get_operation(operation_id)
    except SourceHugoNormalizationOperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _authorize_ingestion_mutation(request=request, repo_ids=existing.repo_ids)
    try:
        updated = orchestrator.resume_operation(
            operation_id=operation_id,
            request_id=request.headers.get("x-request-id"),
            execute_immediately=False,
        )
        updated = _get_task_dispatcher(request).dispatch_ingestion(
            orchestrator=orchestrator,
            operation_id=updated.operation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_hugo_operation_response(updated)
