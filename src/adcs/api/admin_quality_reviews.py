"""Admin API endpoints for semantic quality reviews and approval workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.admin import (
    InMemorySemanticReviewService,
    SemanticReviewActionError,
    SemanticReviewApprovalMode,
    SemanticReviewBlockingErrorType,
    SemanticReviewCandidateItem,
    SemanticReviewGuidedFixPlan,
    SemanticReviewPublishGateDecision,
    SemanticReviewRunNotFoundError,
    SemanticReviewRunOrigin,
    SemanticReviewRunRecord,
)
from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)

router = APIRouter(
    tags=["admin-quality-reviews"],
    dependencies=[Depends(require_admin_principal)],
)

class QualityReviewPolicyPresetPayload(TypedDict):
    display_name: str
    description: str
    sample_size: int
    threshold_score: float
    approval_mode: SemanticReviewApprovalMode


_QUALITY_REVIEW_POLICY_PRESETS: dict[str, QualityReviewPolicyPresetPayload] = {
    "balanced_default": {
        "display_name": "Balanced Default",
        "description": "Default balanced policy for routine product releases.",
        "sample_size": 60,
        "threshold_score": 4.3,
        "approval_mode": "human_approve_all",
    },
    "strict_release": {
        "display_name": "Strict Release",
        "description": "Higher confidence gate for high-risk release candidates.",
        "sample_size": 120,
        "threshold_score": 4.6,
        "approval_mode": "human_approve_all",
    },
    "throughput_auto": {
        "display_name": "Throughput Auto",
        "description": "Faster autonomous mode for frequent low-risk revisions.",
        "sample_size": 40,
        "threshold_score": 4.1,
        "approval_mode": "auto_approve",
    },
}


class QualityReviewRunItemRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4000)
    stratum: str = Field(min_length=1, max_length=200)
    simulated_score: float | None = Field(default=None, ge=0, le=5)
    simulated_blocking_error_type: SemanticReviewBlockingErrorType | None = None
    review_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("source_path", "stratum")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class CreateQualityReviewRunRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, max_length=120)
    source_revision: str = Field(min_length=1, max_length=200)
    trigger_type: Literal["major_change", "manual"] = "major_change"
    items: list[QualityReviewRunItemRequest] = Field(min_length=1, max_length=500)

    @field_validator("product_id", "source_revision")
    @classmethod
    def _normalize_required_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized

    @field_validator("version")
    @classmethod
    def _normalize_optional_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized if normalized else None


class PatchQualityReviewPolicyRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=200)
    sample_size: int | None = Field(default=None, ge=1, le=500)
    threshold_score: float | None = Field(default=None, ge=0, le=5)
    approval_mode: SemanticReviewApprovalMode | None = None

    @field_validator("product_id")
    @classmethod
    def _normalize_product_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "product_id must not be empty."
            raise ValueError(msg)
        return normalized


class ApplyQualityReviewPolicyPresetRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=200)
    preset_id: str = Field(min_length=1, max_length=80)

    @field_validator("product_id", "preset_id")
    @classmethod
    def _normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "Field must not be empty."
            raise ValueError(msg)
        return normalized


class RejectQualityReviewRunRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "reason must not be empty."
            raise ValueError(msg)
        return normalized


class BatchApproveQualityReviewRunsRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=200)

    @field_validator("run_ids")
    @classmethod
    def _normalize_run_ids(cls, values: list[str]) -> list[str]:
        normalized_values = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_values.append(normalized)
        if not normalized_values:
            msg = "run_ids must include at least one valid run id."
            raise ValueError(msg)
        return normalized_values


class BatchRejectQualityReviewRunsRequest(BatchApproveQualityReviewRunsRequest):
    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def _normalize_reject_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "reason must not be empty."
            raise ValueError(msg)
        return normalized


class QualityReviewPolicyResponse(BaseModel):
    product_id: str
    sample_size: int
    sampling_strategy: str
    score_scale: str
    threshold_score: float
    approval_mode: SemanticReviewApprovalMode
    updated_by: str
    updated_at: datetime


class QualityReviewRunSummaryResponse(BaseModel):
    sampled_count: int
    evaluated_count: int
    overall_score: float
    threshold_score: float
    pass_gates: bool


class QualityReviewScoreMatrixRowResponse(BaseModel):
    stratum: str
    sampled_count: int
    evaluated_count: int
    avg_score: float | None
    blocking_count: int


class QualityReviewBlockingFindingResponse(BaseModel):
    item_id: str
    source_path: str
    stratum: str
    blocking_error_type: SemanticReviewBlockingErrorType
    score: float
    review_notes: str | None


class QualityReviewReviewerVoteResponse(BaseModel):
    vote_id: str
    run_id: str
    reviewer_slot: str
    actor_key_id: str | None
    decision: str
    notes: str | None
    created_at: datetime


class QualityReviewApprovalTrailResponse(BaseModel):
    approval_id: str
    run_id: str
    actor_type: str
    actor_key_id: str | None
    action: str
    reason: str | None
    request_id: str | None
    created_at: datetime


class QualityReviewStatusTransitionResponse(BaseModel):
    transition_id: str
    run_id: str
    from_status: str
    to_status: str
    actor_type: str
    actor_key_id: str | None
    reason: str
    request_id: str | None
    created_at: datetime


class QualityReviewPublishGateTrailResponse(BaseModel):
    gate_decision_id: str
    run_id: str
    trigger_type: str
    decision: SemanticReviewPublishGateDecision
    reason_codes: list[str]
    operation_id: str | None
    request_id: str | None
    created_at: datetime


class QualityReviewItemResponse(BaseModel):
    item_id: str
    source_path: str
    stratum: str
    score: float
    blocking_error_type: SemanticReviewBlockingErrorType | None
    review_notes: str | None
    created_at: datetime


class QualityReviewRunOriginResponse(BaseModel):
    source: str
    request_id: str | None
    issue_id: str | None
    issue_type: str | None
    severity: str | None
    raw_query: str | None
    suspected_fault_domain: str | None
    suspected_fault_reason: str | None
    recommendation_title: str | None
    recommendation_detail: str | None


class QualityReviewGuidedFixStepResponse(BaseModel):
    step_id: str
    title: str
    detail: str
    target_section: str
    action_kind: str


class QualityReviewGuidedFixPlanResponse(BaseModel):
    summary: str
    priority: str
    owner_hint: str
    next_step: str
    actions: list[QualityReviewGuidedFixStepResponse]


class QualityReviewRunResponse(BaseModel):
    run_id: str
    product_id: str
    version: str | None
    source_revision: str
    trigger_type: str
    status: str
    fail_fast_triggered: bool
    blocking_error_count: int
    artifact_path: str
    created_by: str
    created_by_key_id: str | None
    created_at: datetime
    finished_at: datetime | None
    policy: QualityReviewPolicyResponse
    summary: QualityReviewRunSummaryResponse
    score_matrix: list[QualityReviewScoreMatrixRowResponse]
    blocking_findings: list[QualityReviewBlockingFindingResponse]
    reviewer_votes: list[QualityReviewReviewerVoteResponse]
    approval_trail: list[QualityReviewApprovalTrailResponse]
    status_transitions: list[QualityReviewStatusTransitionResponse]
    publish_gate_trail: list[QualityReviewPublishGateTrailResponse]
    items: list[QualityReviewItemResponse]
    origin: QualityReviewRunOriginResponse | None = None
    guided_fix_plan: QualityReviewGuidedFixPlanResponse | None = None


class QualityReviewPolicyPresetResponse(BaseModel):
    preset_id: str
    display_name: str
    description: str
    sample_size: int
    threshold_score: float
    approval_mode: SemanticReviewApprovalMode


class QualityReviewBatchActionItemResponse(BaseModel):
    run_id: str
    status: Literal["applied", "failed"]
    message: str | None = None
    run: QualityReviewRunResponse | None = None


class QualityReviewBatchActionResponse(BaseModel):
    action: Literal["approve_all", "reject"]
    requested_count: int
    processed_count: int
    applied_count: int
    failed_count: int
    results: list[QualityReviewBatchActionItemResponse]


class QualityReviewRunDiffResponse(BaseModel):
    baseline_run_id: str
    candidate_run_id: str
    product_id: str
    status_before: str
    status_after: str
    status_changed: bool
    overall_score_delta: float
    threshold_delta: float
    blocking_error_delta: int
    pass_gates_before: bool
    pass_gates_after: bool
    approval_mode_before: SemanticReviewApprovalMode
    approval_mode_after: SemanticReviewApprovalMode
    approval_mode_changed: bool
    fail_fast_before: bool
    fail_fast_after: bool
    fail_fast_changed: bool
    source_revision_before: str
    source_revision_after: str
    source_revision_changed: bool
    blocking_findings_added: list[str]
    blocking_findings_resolved: list[str]


def _get_review_service(request: Request) -> InMemorySemanticReviewService:
    service = getattr(request.app.state, "semantic_review_service", None)
    if not isinstance(service, InMemorySemanticReviewService):
        msg = "Semantic review service is not configured."
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


def _extract_http_exception_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return "Operation is not allowed for the current admin key."


def _blocking_finding_keys(run: SemanticReviewRunRecord) -> set[str]:
    return {
        f"{finding.blocking_error_type}:{finding.source_path}:{finding.stratum}"
        for finding in run.blocking_findings
    }


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


def _to_policy_response(policy: object) -> QualityReviewPolicyResponse:
    return QualityReviewPolicyResponse(
        product_id=str(getattr(policy, "product_id")),
        sample_size=int(getattr(policy, "sample_size")),
        sampling_strategy=str(getattr(policy, "sampling_strategy")),
        score_scale=str(getattr(policy, "score_scale")),
        threshold_score=float(getattr(policy, "threshold_score")),
        approval_mode=getattr(policy, "approval_mode"),
        updated_by=str(getattr(policy, "updated_by")),
        updated_at=getattr(policy, "updated_at"),
    )


def _to_run_origin_response(origin: SemanticReviewRunOrigin) -> QualityReviewRunOriginResponse:
    return QualityReviewRunOriginResponse(
        source=origin.source,
        request_id=origin.request_id,
        issue_id=origin.issue_id,
        issue_type=origin.issue_type,
        severity=origin.severity,
        raw_query=origin.raw_query,
        suspected_fault_domain=origin.suspected_fault_domain,
        suspected_fault_reason=origin.suspected_fault_reason,
        recommendation_title=origin.recommendation_title,
        recommendation_detail=origin.recommendation_detail,
    )


def _to_guided_fix_plan_response(
    plan: SemanticReviewGuidedFixPlan,
) -> QualityReviewGuidedFixPlanResponse:
    return QualityReviewGuidedFixPlanResponse(
        summary=plan.summary,
        priority=plan.priority,
        owner_hint=plan.owner_hint,
        next_step=plan.next_step,
        actions=[
            QualityReviewGuidedFixStepResponse(
                step_id=action.step_id,
                title=action.title,
                detail=action.detail,
                target_section=action.target_section,
                action_kind=action.action_kind,
            )
            for action in plan.actions
        ],
    )



def _observe_failfast_block(*, request: Request, run: SemanticReviewRunRecord) -> None:
    """Record a fail-fast block against the semantic-review fail-fast SLI.

    The SLI targets zero blocks for an approved release candidate and had no
    metric under any name, so the only way to know it had been tripped was to
    read the review record.
    """
    if not run.fail_fast_triggered:
        return
    metrics = getattr(request.app.state, "metrics", None)
    observe = getattr(metrics, "observe_semantic_review_failfast", None)
    if observe is not None:
        observe()


def _to_run_response(run: SemanticReviewRunRecord) -> QualityReviewRunResponse:
    return QualityReviewRunResponse(
        run_id=run.run_id,
        product_id=run.product_id,
        version=run.version,
        source_revision=run.source_revision,
        trigger_type=run.trigger_type,
        status=run.status,
        fail_fast_triggered=run.fail_fast_triggered,
        blocking_error_count=run.blocking_error_count,
        artifact_path=run.artifact_path,
        created_by=run.created_by,
        created_by_key_id=run.created_by_key_id,
        created_at=run.created_at,
        finished_at=run.finished_at,
        policy=_to_policy_response(run.policy),
        summary=QualityReviewRunSummaryResponse(
            sampled_count=run.summary.sampled_count,
            evaluated_count=run.summary.evaluated_count,
            overall_score=run.summary.overall_score,
            threshold_score=run.summary.threshold_score,
            pass_gates=run.summary.pass_gates,
        ),
        score_matrix=[
            QualityReviewScoreMatrixRowResponse(
                stratum=row.stratum,
                sampled_count=row.sampled_count,
                evaluated_count=row.evaluated_count,
                avg_score=row.avg_score,
                blocking_count=row.blocking_count,
            )
            for row in run.score_matrix
        ],
        blocking_findings=[
            QualityReviewBlockingFindingResponse(
                item_id=finding.item_id,
                source_path=finding.source_path,
                stratum=finding.stratum,
                blocking_error_type=finding.blocking_error_type,
                score=finding.score,
                review_notes=finding.review_notes,
            )
            for finding in run.blocking_findings
        ],
        reviewer_votes=[
            QualityReviewReviewerVoteResponse(
                vote_id=vote.vote_id,
                run_id=vote.run_id,
                reviewer_slot=vote.reviewer_slot,
                actor_key_id=vote.actor_key_id,
                decision=vote.decision,
                notes=vote.notes,
                created_at=vote.created_at,
            )
            for vote in run.reviewer_votes
        ],
        approval_trail=[
            QualityReviewApprovalTrailResponse(
                approval_id=action.approval_id,
                run_id=action.run_id,
                actor_type=action.actor_type,
                actor_key_id=action.actor_key_id,
                action=action.action,
                reason=action.reason,
                request_id=action.request_id,
                created_at=action.created_at,
            )
            for action in run.approval_trail
        ],
        status_transitions=[
            QualityReviewStatusTransitionResponse(
                transition_id=transition.transition_id,
                run_id=transition.run_id,
                from_status=transition.from_status,
                to_status=transition.to_status,
                actor_type=transition.actor_type,
                actor_key_id=transition.actor_key_id,
                reason=transition.reason,
                request_id=transition.request_id,
                created_at=transition.created_at,
            )
            for transition in run.status_transitions
        ],
        publish_gate_trail=[
            QualityReviewPublishGateTrailResponse(
                gate_decision_id=decision.gate_decision_id,
                run_id=decision.run_id,
                trigger_type=decision.trigger_type,
                decision=decision.decision,
                reason_codes=list(decision.reason_codes),
                operation_id=decision.operation_id,
                request_id=decision.request_id,
                created_at=decision.created_at,
            )
            for decision in run.publish_gate_trail
        ],
        items=[
            QualityReviewItemResponse(
                item_id=item.item_id,
                source_path=item.source_path,
                stratum=item.stratum,
                score=item.score,
                blocking_error_type=item.blocking_error_type,
                review_notes=item.review_notes,
                created_at=item.created_at,
            )
            for item in run.items
        ],
        origin=_to_run_origin_response(run.origin) if run.origin is not None else None,
        guided_fix_plan=(
            _to_guided_fix_plan_response(run.guided_fix_plan)
            if run.guided_fix_plan is not None
            else None
        ),
    )


def _build_policy_preset_response(
    *,
    preset_id: str,
    payload: QualityReviewPolicyPresetPayload,
) -> QualityReviewPolicyPresetResponse:
    return QualityReviewPolicyPresetResponse(
        preset_id=preset_id,
        display_name=payload["display_name"],
        description=payload["description"],
        sample_size=payload["sample_size"],
        threshold_score=payload["threshold_score"],
        approval_mode=payload["approval_mode"],
    )


def _resolve_policy_preset_or_400(*, preset_id: str) -> QualityReviewPolicyPresetPayload:
    normalized = preset_id.strip().casefold()
    preset = _QUALITY_REVIEW_POLICY_PRESETS.get(normalized)
    if preset is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown quality review preset `{preset_id}`.",
        )
    return preset


@router.post("/admin/v1/quality-reviews/runs", response_model=QualityReviewRunResponse)
def create_quality_review_run(
    payload: CreateQualityReviewRunRequest,
    request: Request,
) -> QualityReviewRunResponse:
    _authorize_write_for_product(request, product_id=payload.product_id)
    service = _get_review_service(request)
    try:
        run = service.create_run(
            product_id=payload.product_id,
            version=payload.version,
            source_revision=payload.source_revision,
            trigger_type=payload.trigger_type,
            created_by="agent",
            created_by_key_id=None,
            request_id=getattr(request.state, "request_id", None),
            items=tuple(
                SemanticReviewCandidateItem(
                    source_path=item.source_path,
                    stratum=item.stratum,
                    simulated_score=item.simulated_score,
                    simulated_blocking_error_type=item.simulated_blocking_error_type,
                    review_notes=item.review_notes,
                )
                for item in payload.items
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _observe_failfast_block(request=request, run=run)
    return _to_run_response(run)


@router.get("/admin/v1/quality-reviews/runs", response_model=list[QualityReviewRunResponse])
def list_quality_review_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
    product_id: str | None = None,
) -> list[QualityReviewRunResponse]:
    service = _get_review_service(request)
    runs = service.list_runs(limit=limit, product_id=product_id)
    return [_to_run_response(run) for run in runs]


@router.get("/admin/v1/quality-reviews/runs/{run_id}", response_model=QualityReviewRunResponse)
def get_quality_review_run(
    run_id: str,
    request: Request,
) -> QualityReviewRunResponse:
    service = _get_review_service(request)
    try:
        run = service.get_run(run_id)
    except SemanticReviewRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Quality review run `{run_id}` was not found.",
        ) from exc
    return _to_run_response(run)


@router.get(
    "/admin/v1/quality-reviews/runs:diff",
    response_model=QualityReviewRunDiffResponse,
)
def diff_quality_review_runs(
    request: Request,
    baseline_run_id: str = Query(min_length=1, max_length=120),
    candidate_run_id: str = Query(min_length=1, max_length=120),
) -> QualityReviewRunDiffResponse:
    service = _get_review_service(request)
    baseline_id = baseline_run_id.strip()
    candidate_id = candidate_run_id.strip()
    if baseline_id == candidate_id:
        raise HTTPException(
            status_code=400,
            detail="baseline_run_id and candidate_run_id must be different.",
        )
    try:
        baseline = service.get_run(baseline_id)
        candidate = service.get_run(candidate_id)
    except SemanticReviewRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if baseline.product_id != candidate.product_id:
        raise HTTPException(
            status_code=400,
            detail="Diff is supported only for runs within the same product_id.",
        )

    baseline_findings = _blocking_finding_keys(baseline)
    candidate_findings = _blocking_finding_keys(candidate)
    return QualityReviewRunDiffResponse(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        product_id=candidate.product_id,
        status_before=baseline.status,
        status_after=candidate.status,
        status_changed=baseline.status != candidate.status,
        overall_score_delta=round(
            candidate.summary.overall_score - baseline.summary.overall_score,
            3,
        ),
        threshold_delta=round(
            candidate.summary.threshold_score - baseline.summary.threshold_score,
            3,
        ),
        blocking_error_delta=candidate.blocking_error_count - baseline.blocking_error_count,
        pass_gates_before=baseline.summary.pass_gates,
        pass_gates_after=candidate.summary.pass_gates,
        approval_mode_before=baseline.policy.approval_mode,
        approval_mode_after=candidate.policy.approval_mode,
        approval_mode_changed=baseline.policy.approval_mode != candidate.policy.approval_mode,
        fail_fast_before=baseline.fail_fast_triggered,
        fail_fast_after=candidate.fail_fast_triggered,
        fail_fast_changed=baseline.fail_fast_triggered != candidate.fail_fast_triggered,
        source_revision_before=baseline.source_revision,
        source_revision_after=candidate.source_revision,
        source_revision_changed=baseline.source_revision != candidate.source_revision,
        blocking_findings_added=sorted(candidate_findings - baseline_findings),
        blocking_findings_resolved=sorted(baseline_findings - candidate_findings),
    )


@router.post(
    "/admin/v1/quality-reviews/runs/{run_id}:approve-all",
    response_model=QualityReviewRunResponse,
)
def approve_all_quality_review_run(
    run_id: str,
    request: Request,
) -> QualityReviewRunResponse:
    service = _get_review_service(request)
    try:
        run = service.get_run(run_id)
    except SemanticReviewRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Quality review run `{run_id}` was not found.",
        ) from exc

    _authorize_write_for_product(request, product_id=run.product_id)
    principal = _get_admin_principal(request)
    try:
        approved = service.approve_all(
            run_id=run_id,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
        )
    except SemanticReviewActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_run_response(approved)


@router.post(
    "/admin/v1/quality-reviews/runs:batch-approve-all",
    response_model=QualityReviewBatchActionResponse,
)
def batch_approve_all_quality_review_runs(
    payload: BatchApproveQualityReviewRunsRequest,
    request: Request,
) -> QualityReviewBatchActionResponse:
    service = _get_review_service(request)
    principal = _get_admin_principal(request)
    request_id = getattr(request.state, "request_id", None)

    results: list[QualityReviewBatchActionItemResponse] = []
    for run_id in payload.run_ids:
        try:
            run = service.get_run(run_id)
        except SemanticReviewRunNotFoundError:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=f"Run `{run_id}` was not found.",
                )
            )
            continue

        try:
            _authorize_write_for_product(request, product_id=run.product_id)
        except HTTPException as exc:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=_extract_http_exception_message(exc),
                )
            )
            continue

        try:
            approved = service.approve_all(
                run_id=run_id,
                actor_key_id=principal.key_id,
                request_id=request_id,
            )
        except SemanticReviewActionError as exc:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=str(exc),
                )
            )
            continue
        results.append(
            QualityReviewBatchActionItemResponse(
                run_id=run_id,
                status="applied",
                run=_to_run_response(approved),
            )
        )

    applied_count = sum(1 for item in results if item.status == "applied")
    return QualityReviewBatchActionResponse(
        action="approve_all",
        requested_count=len(payload.run_ids),
        processed_count=len(results),
        applied_count=applied_count,
        failed_count=len(results) - applied_count,
        results=results,
    )


@router.post(
    "/admin/v1/quality-reviews/runs/{run_id}:reject",
    response_model=QualityReviewRunResponse,
)
def reject_quality_review_run(
    run_id: str,
    payload: RejectQualityReviewRunRequest,
    request: Request,
) -> QualityReviewRunResponse:
    service = _get_review_service(request)
    try:
        run = service.get_run(run_id)
    except SemanticReviewRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Quality review run `{run_id}` was not found.",
        ) from exc

    _authorize_write_for_product(request, product_id=run.product_id)
    principal = _get_admin_principal(request)
    try:
        rejected = service.reject(
            run_id=run_id,
            actor_key_id=principal.key_id,
            reason=payload.reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except SemanticReviewActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_run_response(rejected)


@router.post(
    "/admin/v1/quality-reviews/runs:batch-reject",
    response_model=QualityReviewBatchActionResponse,
)
def batch_reject_quality_review_runs(
    payload: BatchRejectQualityReviewRunsRequest,
    request: Request,
) -> QualityReviewBatchActionResponse:
    service = _get_review_service(request)
    principal = _get_admin_principal(request)
    request_id = getattr(request.state, "request_id", None)

    results: list[QualityReviewBatchActionItemResponse] = []
    for run_id in payload.run_ids:
        try:
            run = service.get_run(run_id)
        except SemanticReviewRunNotFoundError:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=f"Run `{run_id}` was not found.",
                )
            )
            continue

        try:
            _authorize_write_for_product(request, product_id=run.product_id)
        except HTTPException as exc:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=_extract_http_exception_message(exc),
                )
            )
            continue

        try:
            rejected = service.reject(
                run_id=run_id,
                actor_key_id=principal.key_id,
                reason=payload.reason,
                request_id=request_id,
            )
        except SemanticReviewActionError as exc:
            results.append(
                QualityReviewBatchActionItemResponse(
                    run_id=run_id,
                    status="failed",
                    message=str(exc),
                )
            )
            continue

        results.append(
            QualityReviewBatchActionItemResponse(
                run_id=run_id,
                status="applied",
                run=_to_run_response(rejected),
            )
        )

    applied_count = sum(1 for item in results if item.status == "applied")
    return QualityReviewBatchActionResponse(
        action="reject",
        requested_count=len(payload.run_ids),
        processed_count=len(results),
        applied_count=applied_count,
        failed_count=len(results) - applied_count,
        results=results,
    )


@router.patch("/admin/v1/quality-reviews/policy", response_model=QualityReviewPolicyResponse)
def patch_quality_review_policy(
    payload: PatchQualityReviewPolicyRequest,
    request: Request,
) -> QualityReviewPolicyResponse:
    if (
        payload.sample_size is None
        and payload.threshold_score is None
        and payload.approval_mode is None
    ):
        raise HTTPException(
            status_code=400,
            detail="At least one policy field must be provided for patch.",
        )

    _authorize_write_for_product(request, product_id=payload.product_id)
    principal = _get_admin_principal(request)
    service = _get_review_service(request)
    try:
        policy = service.patch_policy(
            product_id=payload.product_id,
            updated_by=principal.key_id,
            sample_size=payload.sample_size,
            threshold_score=payload.threshold_score,
            approval_mode=payload.approval_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_policy_response(policy)


@router.get(
    "/admin/v1/quality-reviews/policy-presets",
    response_model=list[QualityReviewPolicyPresetResponse],
)
def list_quality_review_policy_presets() -> list[QualityReviewPolicyPresetResponse]:
    return [
        _build_policy_preset_response(preset_id=preset_id, payload=payload)
        for preset_id, payload in sorted(_QUALITY_REVIEW_POLICY_PRESETS.items())
    ]


@router.post(
    "/admin/v1/quality-reviews/policy:apply-preset",
    response_model=QualityReviewPolicyResponse,
)
def apply_quality_review_policy_preset(
    payload: ApplyQualityReviewPolicyPresetRequest,
    request: Request,
) -> QualityReviewPolicyResponse:
    _authorize_write_for_product(request, product_id=payload.product_id)
    principal = _get_admin_principal(request)
    service = _get_review_service(request)
    preset = _resolve_policy_preset_or_400(preset_id=payload.preset_id)
    policy = service.patch_policy(
        product_id=payload.product_id,
        updated_by=principal.key_id,
        sample_size=preset["sample_size"],
        threshold_score=preset["threshold_score"],
        approval_mode=preset["approval_mode"],
    )
    return _to_policy_response(policy)
