"""In-memory semantic review runtime with approval workflow and artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

SemanticReviewRunStatus = Literal[
    "running",
    "awaiting_approval",
    "approved",
    "rejected",
    "blocked",
]
SemanticReviewApprovalMode = Literal["human_approve_all", "auto_approve"]
SemanticReviewTriggerType = Literal["major_change", "manual"]
SemanticReviewCreatedBy = Literal["agent", "admin_key"]
SemanticReviewBlockingErrorType = Literal[
    "hallucinated_api_member",
    "invalid_signature_or_parameters_or_returns",
    "citation_or_source_path_loss",
]
SemanticReviewApprovalAction = Literal["submit", "approve_all", "auto_approve", "reject"]
SemanticReviewActorType = Literal["agent", "admin_key"]
SemanticReviewReviewerSlot = Literal["reviewer_1", "reviewer_2", "product_owner_tie_break"]
SemanticReviewReviewerDecision = Literal["approve", "reject"]
SemanticReviewPublishGateDecision = Literal["allow_publish", "block_publish"]
SemanticReviewOriginSource = Literal["manual", "issue_handoff"]
SemanticReviewFixPlanPriority = Literal["high", "medium", "low"]

_DEFAULT_SAMPLE_SIZE = 60
_DEFAULT_THRESHOLD_SCORE = 4.3
_RISK_BASED_STRATUM_ORDER = {
    "apiref_symbol_rich": 0,
    "docs_shortcode": 1,
    "docs_html_embed": 2,
}

_REASON_SCORE_BELOW_THRESHOLD = "semantic_review_score_below_threshold"
_REASON_BLOCKING_FINDING_PRESENT = "semantic_review_blocking_finding_present"
_REASON_MISSING_REQUIRED_APPROVAL = "semantic_review_missing_required_approval"
_REASON_REVIEW_RUN_MISSING = "semantic_review_run_missing"


class SemanticReviewRunNotFoundError(KeyError):
    """Raised when semantic review run does not exist."""


class SemanticReviewActionError(ValueError):
    """Raised for invalid approval workflow actions."""


@dataclass(frozen=True, slots=True)
class SemanticReviewPolicy:
    product_id: str
    sample_size: int
    sampling_strategy: Literal["risk_based"]
    score_scale: Literal["0..5"]
    threshold_score: float
    approval_mode: SemanticReviewApprovalMode
    updated_by: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewCandidateItem:
    source_path: str
    stratum: str
    simulated_score: float | None = None
    simulated_blocking_error_type: SemanticReviewBlockingErrorType | None = None
    review_notes: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticReviewItemRecord:
    item_id: str
    source_path: str
    stratum: str
    score: float
    blocking_error_type: SemanticReviewBlockingErrorType | None
    review_notes: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewBlockingFinding:
    item_id: str
    source_path: str
    stratum: str
    blocking_error_type: SemanticReviewBlockingErrorType
    score: float
    review_notes: str | None


@dataclass(frozen=True, slots=True)
class SemanticReviewScoreMatrixRow:
    stratum: str
    sampled_count: int
    evaluated_count: int
    avg_score: float | None
    blocking_count: int


@dataclass(frozen=True, slots=True)
class SemanticReviewReviewerVote:
    vote_id: str
    run_id: str
    reviewer_slot: SemanticReviewReviewerSlot
    actor_key_id: str | None
    decision: SemanticReviewReviewerDecision
    notes: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewApprovalTrailRecord:
    approval_id: str
    run_id: str
    actor_type: SemanticReviewActorType
    actor_key_id: str | None
    action: SemanticReviewApprovalAction
    reason: str | None
    request_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewStatusTransitionRecord:
    transition_id: str
    run_id: str
    from_status: SemanticReviewRunStatus
    to_status: SemanticReviewRunStatus
    actor_type: SemanticReviewActorType
    actor_key_id: str | None
    reason: str
    request_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewPublishGateTrailRecord:
    gate_decision_id: str
    run_id: str
    trigger_type: SemanticReviewTriggerType
    decision: SemanticReviewPublishGateDecision
    reason_codes: tuple[str, ...]
    operation_id: str | None
    request_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticReviewPublishGateEvaluation:
    trigger_type: SemanticReviewTriggerType
    decision: SemanticReviewPublishGateDecision
    reason_codes: tuple[str, ...]
    run_id: str | None
    run_status: SemanticReviewRunStatus | None
    approval_mode: SemanticReviewApprovalMode
    overall_score: float | None
    threshold_score: float
    fail_fast_triggered: bool
    blocking_error_count: int
    status_transitions: tuple[SemanticReviewStatusTransitionRecord, ...]


@dataclass(frozen=True, slots=True)
class SemanticReviewRunSummary:
    sampled_count: int
    evaluated_count: int
    overall_score: float
    threshold_score: float
    pass_gates: bool


@dataclass(frozen=True, slots=True)
class SemanticReviewRunOrigin:
    source: SemanticReviewOriginSource
    request_id: str | None
    issue_id: str | None
    issue_type: str | None
    severity: str | None
    raw_query: str | None
    suspected_fault_domain: str | None
    suspected_fault_reason: str | None
    recommendation_title: str | None
    recommendation_detail: str | None


@dataclass(frozen=True, slots=True)
class SemanticReviewFixPlanStep:
    step_id: str
    title: str
    detail: str
    target_section: str
    action_kind: str


@dataclass(frozen=True, slots=True)
class SemanticReviewGuidedFixPlan:
    summary: str
    priority: SemanticReviewFixPlanPriority
    owner_hint: str
    next_step: str
    actions: tuple[SemanticReviewFixPlanStep, ...]


@dataclass(frozen=True, slots=True)
class SemanticReviewRunRecord:
    run_id: str
    product_id: str
    version: str | None
    source_revision: str
    trigger_type: SemanticReviewTriggerType
    policy: SemanticReviewPolicy
    status: SemanticReviewRunStatus
    summary: SemanticReviewRunSummary
    fail_fast_triggered: bool
    blocking_error_count: int
    artifact_path: str
    created_by: SemanticReviewCreatedBy
    created_by_key_id: str | None
    created_at: datetime
    finished_at: datetime | None
    score_matrix: tuple[SemanticReviewScoreMatrixRow, ...]
    blocking_findings: tuple[SemanticReviewBlockingFinding, ...]
    reviewer_votes: tuple[SemanticReviewReviewerVote, ...]
    approval_trail: tuple[SemanticReviewApprovalTrailRecord, ...]
    status_transitions: tuple[SemanticReviewStatusTransitionRecord, ...]
    publish_gate_trail: tuple[SemanticReviewPublishGateTrailRecord, ...]
    items: tuple[SemanticReviewItemRecord, ...]
    origin: SemanticReviewRunOrigin | None = None
    guided_fix_plan: SemanticReviewGuidedFixPlan | None = None


class InMemorySemanticReviewService:
    """Store semantic review runs with deterministic evaluation and approvals."""

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._lock = Lock()
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self._artifact_root = (self._workspace_root / "artifacts" / "semantic-review").resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, SemanticReviewRunRecord] = {}
        self._run_order: list[str] = []
        self._policies: dict[str, SemanticReviewPolicy] = {}

    def get_policy(self, *, product_id: str) -> SemanticReviewPolicy:
        normalized_product_id = _normalize_product_id(product_id)
        with self._lock:
            existing = self._policies.get(normalized_product_id)
            if existing is not None:
                return existing
            created = _default_policy(product_id=normalized_product_id)
            self._policies[normalized_product_id] = created
            return created

    def patch_policy(
        self,
        *,
        product_id: str,
        updated_by: str,
        sample_size: int | None = None,
        threshold_score: float | None = None,
        approval_mode: SemanticReviewApprovalMode | None = None,
    ) -> SemanticReviewPolicy:
        normalized_product_id = _normalize_product_id(product_id)
        normalized_updated_by = updated_by.strip()
        if not normalized_updated_by:
            msg = "updated_by must not be empty."
            raise ValueError(msg)

        with self._lock:
            current = self._policies.get(normalized_product_id) or _default_policy(
                product_id=normalized_product_id
            )
            next_sample_size = current.sample_size if sample_size is None else int(sample_size)
            next_threshold_score = (
                current.threshold_score if threshold_score is None else float(threshold_score)
            )
            next_approval_mode = current.approval_mode if approval_mode is None else approval_mode

            if next_sample_size < 1 or next_sample_size > 500:
                msg = "sample_size must be in range [1, 500]."
                raise ValueError(msg)
            if next_threshold_score < 0 or next_threshold_score > 5:
                msg = "threshold_score must be in range [0, 5]."
                raise ValueError(msg)

            patched = SemanticReviewPolicy(
                product_id=normalized_product_id,
                sample_size=next_sample_size,
                sampling_strategy="risk_based",
                score_scale="0..5",
                threshold_score=round(next_threshold_score, 3),
                approval_mode=next_approval_mode,
                updated_by=normalized_updated_by,
                updated_at=datetime.now(tz=UTC),
            )
            self._policies[normalized_product_id] = patched
            return patched

    def create_run(
        self,
        *,
        product_id: str,
        version: str | None,
        source_revision: str,
        trigger_type: SemanticReviewTriggerType,
        created_by: SemanticReviewCreatedBy,
        created_by_key_id: str | None,
        request_id: str | None,
        items: tuple[SemanticReviewCandidateItem, ...],
        origin: SemanticReviewRunOrigin | None = None,
        guided_fix_plan: SemanticReviewGuidedFixPlan | None = None,
    ) -> SemanticReviewRunRecord:
        normalized_product_id = _normalize_product_id(product_id)
        normalized_revision = source_revision.strip()
        normalized_version = (
            version.strip()
            if isinstance(version, str) and version.strip()
            else None
        )
        if not normalized_revision:
            msg = "source_revision must not be empty."
            raise ValueError(msg)
        if not items:
            msg = "items must not be empty."
            raise ValueError(msg)

        policy = self.get_policy(product_id=normalized_product_id)
        run_id = str(uuid4())
        created_at = datetime.now(tz=UTC)
        sampled_candidates = _sample_candidates(items=items, sample_size=policy.sample_size)

        evaluated_items: list[SemanticReviewItemRecord] = []
        fail_fast_triggered = False
        for candidate in sampled_candidates:
            evaluated_item = _evaluate_candidate(
                run_id=run_id,
                source_revision=normalized_revision,
                candidate=candidate,
            )
            evaluated_items.append(evaluated_item)
            if evaluated_item.blocking_error_type is not None:
                fail_fast_triggered = True
                break

        blocking_findings = tuple(
            SemanticReviewBlockingFinding(
                item_id=item.item_id,
                source_path=item.source_path,
                stratum=item.stratum,
                blocking_error_type=item.blocking_error_type,
                score=item.score,
                review_notes=item.review_notes,
            )
            for item in evaluated_items
            if item.blocking_error_type is not None
        )
        score_matrix = _build_score_matrix(
            sampled_candidates=sampled_candidates,
            evaluated_items=tuple(evaluated_items),
        )
        overall_score = round(
            sum(item.score for item in evaluated_items) / len(evaluated_items),
            3,
        )
        pass_gates = not blocking_findings and overall_score >= policy.threshold_score
        summary = SemanticReviewRunSummary(
            sampled_count=len(sampled_candidates),
            evaluated_count=len(evaluated_items),
            overall_score=overall_score,
            threshold_score=policy.threshold_score,
            pass_gates=pass_gates,
        )

        reviewer_votes = _build_default_reviewer_votes(
            run_id=run_id,
            overall_score=overall_score,
            threshold_score=policy.threshold_score,
            blocking_count=len(blocking_findings),
        )

        approval_trail: list[SemanticReviewApprovalTrailRecord] = [
            _new_approval_trail(
                run_id=run_id,
                actor_type="agent",
                actor_key_id=None,
                action="submit",
                reason="Semantic review submitted by autonomous agent run.",
                request_id=request_id,
            )
        ]

        if blocking_findings:
            status: SemanticReviewRunStatus = "blocked"
        elif overall_score < policy.threshold_score:
            status = "rejected"
            approval_trail.append(
                _new_approval_trail(
                    run_id=run_id,
                    actor_type="agent",
                    actor_key_id=None,
                    action="reject",
                    reason=(
                        f"Overall score {overall_score:.3f} is below threshold "
                        f"{policy.threshold_score:.3f}."
                    ),
                    request_id=request_id,
                )
            )
        elif policy.approval_mode == "auto_approve":
            status = "approved"
            approval_trail.append(
                _new_approval_trail(
                    run_id=run_id,
                    actor_type="agent",
                    actor_key_id=None,
                    action="auto_approve",
                    reason="Auto-approved because all gates passed.",
                    request_id=request_id,
                )
            )
        else:
            status = "awaiting_approval"

        initial_status_transition = _new_status_transition(
            run_id=run_id,
            from_status="running",
            to_status=status,
            actor_type="agent",
            actor_key_id=None,
            reason=_build_initial_status_reason(
                status=status,
                overall_score=overall_score,
                threshold_score=policy.threshold_score,
                blocking_error_count=len(blocking_findings),
                approval_mode=policy.approval_mode,
            ),
            request_id=request_id,
        )

        finished_at = datetime.now(tz=UTC)
        artifact_path = _build_artifact_path(
            artifact_root=self._artifact_root,
            product_id=normalized_product_id,
            created_at=created_at,
            run_id=run_id,
        )
        run = SemanticReviewRunRecord(
            run_id=run_id,
            product_id=normalized_product_id,
            version=normalized_version,
            source_revision=normalized_revision,
            trigger_type=trigger_type,
            policy=policy,
            status=status,
            summary=summary,
            fail_fast_triggered=fail_fast_triggered,
            blocking_error_count=len(blocking_findings),
            artifact_path=artifact_path,
            created_by=created_by,
            created_by_key_id=created_by_key_id,
            created_at=created_at,
            finished_at=finished_at,
            score_matrix=score_matrix,
            blocking_findings=blocking_findings,
            reviewer_votes=reviewer_votes,
            approval_trail=tuple(approval_trail),
            status_transitions=(initial_status_transition,),
            publish_gate_trail=(),
            items=tuple(evaluated_items),
            origin=origin,
            guided_fix_plan=guided_fix_plan,
        )

        _write_artifact(artifact_root=self._artifact_root, run=run)
        with self._lock:
            self._runs[run_id] = run
            self._run_order.append(run_id)
        return run

    def list_runs(
        self,
        *,
        limit: int = 20,
        product_id: str | None = None,
    ) -> tuple[SemanticReviewRunRecord, ...]:
        clamped_limit = max(1, min(limit, 500))
        normalized_product_id = (
            _normalize_product_id(product_id)
            if isinstance(product_id, str) and product_id.strip()
            else None
        )
        with self._lock:
            ordered_runs = [self._runs[run_id] for run_id in reversed(self._run_order)]
        if normalized_product_id is not None:
            ordered_runs = [run for run in ordered_runs if run.product_id == normalized_product_id]
        return tuple(ordered_runs[:clamped_limit])

    def get_run(self, run_id: str) -> SemanticReviewRunRecord:
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            msg = "run_id must not be empty."
            raise ValueError(msg)
        with self._lock:
            run = self._runs.get(normalized_run_id)
        if run is None:
            raise SemanticReviewRunNotFoundError(normalized_run_id)
        return run

    def evaluate_publish_gate(
        self,
        *,
        product_id: str,
        version: str | None,
        source_revision: str,
        trigger_type: SemanticReviewTriggerType = "major_change",
    ) -> SemanticReviewPublishGateEvaluation:
        normalized_product_id = _normalize_product_id(product_id)
        normalized_version = _normalize_optional_version(version)
        normalized_source_revision = source_revision.strip()
        if not normalized_source_revision:
            msg = "source_revision must not be empty."
            raise ValueError(msg)

        policy = self.get_policy(product_id=normalized_product_id)
        matched_run = self._resolve_latest_relevant_run(
            product_id=normalized_product_id,
            version=normalized_version,
            source_revision=normalized_source_revision,
            trigger_type=trigger_type,
        )
        if matched_run is None:
            reason_codes: list[str] = [_REASON_REVIEW_RUN_MISSING]
            if policy.approval_mode == "human_approve_all":
                reason_codes.append(_REASON_MISSING_REQUIRED_APPROVAL)
            return SemanticReviewPublishGateEvaluation(
                trigger_type=trigger_type,
                decision="block_publish",
                reason_codes=tuple(reason_codes),
                run_id=None,
                run_status=None,
                approval_mode=policy.approval_mode,
                overall_score=None,
                threshold_score=policy.threshold_score,
                fail_fast_triggered=False,
                blocking_error_count=0,
                status_transitions=(),
            )

        reason_codes = []
        if matched_run.summary.overall_score < matched_run.summary.threshold_score:
            reason_codes.append(_REASON_SCORE_BELOW_THRESHOLD)
        if matched_run.fail_fast_triggered or matched_run.blocking_error_count > 0:
            reason_codes.append(_REASON_BLOCKING_FINDING_PRESENT)
        if (
            matched_run.policy.approval_mode == "human_approve_all"
            and matched_run.status != "approved"
        ):
            reason_codes.append(_REASON_MISSING_REQUIRED_APPROVAL)

        decision: SemanticReviewPublishGateDecision = (
            "allow_publish" if not reason_codes else "block_publish"
        )
        return SemanticReviewPublishGateEvaluation(
            trigger_type=trigger_type,
            decision=decision,
            reason_codes=tuple(reason_codes),
            run_id=matched_run.run_id,
            run_status=matched_run.status,
            approval_mode=matched_run.policy.approval_mode,
            overall_score=matched_run.summary.overall_score,
            threshold_score=matched_run.summary.threshold_score,
            fail_fast_triggered=matched_run.fail_fast_triggered,
            blocking_error_count=matched_run.blocking_error_count,
            status_transitions=matched_run.status_transitions,
        )

    def record_publish_gate_decision(
        self,
        *,
        run_id: str,
        trigger_type: SemanticReviewTriggerType,
        decision: SemanticReviewPublishGateDecision,
        reason_codes: tuple[str, ...],
        operation_id: str | None,
        request_id: str | None,
    ) -> SemanticReviewRunRecord:
        current = self.get_run(run_id)
        trail = list(current.publish_gate_trail)
        trail.append(
            SemanticReviewPublishGateTrailRecord(
                gate_decision_id=str(uuid4()),
                run_id=current.run_id,
                trigger_type=trigger_type,
                decision=decision,
                reason_codes=tuple(reason_codes),
                operation_id=operation_id,
                request_id=request_id,
                created_at=datetime.now(tz=UTC),
            )
        )
        updated = replace(current, publish_gate_trail=tuple(trail))
        return self._replace_run(updated)

    def approve_all(
        self,
        *,
        run_id: str,
        actor_key_id: str,
        request_id: str | None,
    ) -> SemanticReviewRunRecord:
        normalized_actor_key_id = actor_key_id.strip()
        if not normalized_actor_key_id:
            msg = "actor_key_id must not be empty."
            raise ValueError(msg)
        current = self.get_run(run_id)
        if current.status == "blocked":
            msg = "Blocked run cannot be manually approved."
            raise SemanticReviewActionError(msg)
        if current.status == "rejected":
            msg = "Rejected run cannot be approved without re-run."
            raise SemanticReviewActionError(msg)
        if current.status == "approved":
            return current
        if current.status != "awaiting_approval":
            msg = f"Run status `{current.status}` does not allow approve-all."
            raise SemanticReviewActionError(msg)

        trail = list(current.approval_trail)
        trail.append(
            _new_approval_trail(
                run_id=current.run_id,
                actor_type="admin_key",
                actor_key_id=normalized_actor_key_id,
                action="approve_all",
                reason="Manual approve-all from admin API.",
                request_id=request_id,
            )
        )

        votes = list(current.reviewer_votes)
        votes.append(
            SemanticReviewReviewerVote(
                vote_id=str(uuid4()),
                run_id=current.run_id,
                reviewer_slot="product_owner_tie_break",
                actor_key_id=normalized_actor_key_id,
                decision="approve",
                notes="Manual approve-all action.",
                created_at=datetime.now(tz=UTC),
            )
        )
        transitions = list(current.status_transitions)
        transitions.append(
            _new_status_transition(
                run_id=current.run_id,
                from_status=current.status,
                to_status="approved",
                actor_type="admin_key",
                actor_key_id=normalized_actor_key_id,
                reason="Manual approve-all from admin API.",
                request_id=request_id,
            )
        )

        updated = replace(
            current,
            status="approved",
            finished_at=datetime.now(tz=UTC),
            approval_trail=tuple(trail),
            reviewer_votes=tuple(votes),
            status_transitions=tuple(transitions),
        )
        return self._replace_run(updated)

    def reject(
        self,
        *,
        run_id: str,
        actor_key_id: str,
        reason: str,
        request_id: str | None,
    ) -> SemanticReviewRunRecord:
        normalized_actor_key_id = actor_key_id.strip()
        normalized_reason = reason.strip()
        if not normalized_actor_key_id:
            msg = "actor_key_id must not be empty."
            raise ValueError(msg)
        if not normalized_reason:
            msg = "reason must not be empty."
            raise ValueError(msg)

        current = self.get_run(run_id)
        if current.status == "rejected":
            return current

        trail = list(current.approval_trail)
        trail.append(
            _new_approval_trail(
                run_id=current.run_id,
                actor_type="admin_key",
                actor_key_id=normalized_actor_key_id,
                action="reject",
                reason=normalized_reason,
                request_id=request_id,
            )
        )
        votes = list(current.reviewer_votes)
        votes.append(
            SemanticReviewReviewerVote(
                vote_id=str(uuid4()),
                run_id=current.run_id,
                reviewer_slot="product_owner_tie_break",
                actor_key_id=normalized_actor_key_id,
                decision="reject",
                notes=normalized_reason,
                created_at=datetime.now(tz=UTC),
            )
        )
        transitions = list(current.status_transitions)
        transitions.append(
            _new_status_transition(
                run_id=current.run_id,
                from_status=current.status,
                to_status="rejected",
                actor_type="admin_key",
                actor_key_id=normalized_actor_key_id,
                reason=normalized_reason,
                request_id=request_id,
            )
        )

        updated = replace(
            current,
            status="rejected",
            finished_at=datetime.now(tz=UTC),
            approval_trail=tuple(trail),
            reviewer_votes=tuple(votes),
            status_transitions=tuple(transitions),
        )
        return self._replace_run(updated)

    def _replace_run(self, run: SemanticReviewRunRecord) -> SemanticReviewRunRecord:
        _write_artifact(artifact_root=self._artifact_root, run=run)
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def _resolve_latest_relevant_run(
        self,
        *,
        product_id: str,
        version: str | None,
        source_revision: str,
        trigger_type: SemanticReviewTriggerType,
    ) -> SemanticReviewRunRecord | None:
        with self._lock:
            candidates = tuple(self._runs.values())

        filtered = [
            run
            for run in candidates
            if run.product_id == product_id
            and run.source_revision == source_revision
            and run.trigger_type == trigger_type
        ]
        if not filtered:
            return None

        if version is None:
            version_candidates = [run for run in filtered if run.version is None]
            if version_candidates:
                filtered = version_candidates
        else:
            version_key = version.casefold()
            exact = [
                run
                for run in filtered
                if isinstance(run.version, str) and run.version.casefold() == version_key
            ]
            if exact:
                filtered = exact
            else:
                wildcard = [run for run in filtered if run.version is None]
                if wildcard:
                    filtered = wildcard

        ordered = sorted(
            filtered,
            key=lambda run: (run.created_at, run.run_id),
            reverse=True,
        )
        return ordered[0]


def _normalize_product_id(product_id: str) -> str:
    normalized = product_id.strip().casefold()
    if not normalized:
        msg = "product_id must not be empty."
        raise ValueError(msg)
    return normalized


def _normalize_optional_version(version: str | None) -> str | None:
    if version is None:
        return None
    normalized = version.strip()
    if not normalized:
        return None
    return normalized


def _build_initial_status_reason(
    *,
    status: SemanticReviewRunStatus,
    overall_score: float,
    threshold_score: float,
    blocking_error_count: int,
    approval_mode: SemanticReviewApprovalMode,
) -> str:
    if status == "blocked":
        return (
            f"Fail-fast blocking finding detected ({blocking_error_count}) "
            f"for approval_mode={approval_mode}."
        )
    if status == "rejected":
        return (
            f"Overall score {overall_score:.3f} below threshold "
            f"{threshold_score:.3f}."
        )
    if status == "approved":
        return (
            f"All hard gates passed with score {overall_score:.3f} "
            f"for approval_mode={approval_mode}."
        )
    return "Awaiting explicit manual approve-all action."


def _default_policy(*, product_id: str) -> SemanticReviewPolicy:
    return SemanticReviewPolicy(
        product_id=product_id,
        sample_size=_DEFAULT_SAMPLE_SIZE,
        sampling_strategy="risk_based",
        score_scale="0..5",
        threshold_score=_DEFAULT_THRESHOLD_SCORE,
        approval_mode="human_approve_all",
        updated_by="system-default",
        updated_at=datetime.now(tz=UTC),
    )


def _sample_candidates(
    *,
    items: tuple[SemanticReviewCandidateItem, ...],
    sample_size: int,
) -> tuple[SemanticReviewCandidateItem, ...]:
    ordered = sorted(
        items,
        key=lambda item: (
            _RISK_BASED_STRATUM_ORDER.get(item.stratum.strip().casefold(), 100),
            item.source_path.strip().casefold(),
        ),
    )
    return tuple(ordered[:sample_size])


def _evaluate_candidate(
    *,
    run_id: str,
    source_revision: str,
    candidate: SemanticReviewCandidateItem,
) -> SemanticReviewItemRecord:
    now = datetime.now(tz=UTC)
    normalized_path = candidate.source_path.strip()
    normalized_stratum = candidate.stratum.strip().casefold() or "unclassified"
    if not normalized_path:
        msg = "source_path must not be empty."
        raise ValueError(msg)

    score = (
        _deterministic_score(
            source_revision=source_revision,
            source_path=normalized_path,
            stratum=normalized_stratum,
        )
        if candidate.simulated_score is None
        else round(max(0.0, min(float(candidate.simulated_score), 5.0)), 3)
    )

    blocking_error_type = candidate.simulated_blocking_error_type
    if blocking_error_type is None:
        lowered = normalized_path.casefold()
        if "hallucinated" in lowered:
            blocking_error_type = "hallucinated_api_member"
        elif "invalid-signature" in lowered:
            blocking_error_type = "invalid_signature_or_parameters_or_returns"
        elif "citation-loss" in lowered:
            blocking_error_type = "citation_or_source_path_loss"

    return SemanticReviewItemRecord(
        item_id=str(uuid4()),
        source_path=normalized_path,
        stratum=normalized_stratum,
        score=score,
        blocking_error_type=blocking_error_type,
        review_notes=candidate.review_notes,
        created_at=now,
    )


def _deterministic_score(
    *,
    source_revision: str,
    source_path: str,
    stratum: str,
) -> float:
    digest = hashlib.sha256(
        f"{source_revision}|{source_path}|{stratum}".encode()
    ).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    score = 3.0 + (ratio * 2.0)
    return round(max(0.0, min(score, 5.0)), 3)


def _build_score_matrix(
    *,
    sampled_candidates: tuple[SemanticReviewCandidateItem, ...],
    evaluated_items: tuple[SemanticReviewItemRecord, ...],
) -> tuple[SemanticReviewScoreMatrixRow, ...]:
    sampled_counts: dict[str, int] = {}
    evaluated_counts: dict[str, int] = {}
    score_sums: dict[str, float] = {}
    blocking_counts: dict[str, int] = {}

    for candidate in sampled_candidates:
        stratum = candidate.stratum.strip().casefold() or "unclassified"
        sampled_counts[stratum] = sampled_counts.get(stratum, 0) + 1
    for item in evaluated_items:
        evaluated_counts[item.stratum] = evaluated_counts.get(item.stratum, 0) + 1
        score_sums[item.stratum] = score_sums.get(item.stratum, 0.0) + item.score
        if item.blocking_error_type is not None:
            blocking_counts[item.stratum] = blocking_counts.get(item.stratum, 0) + 1

    all_strata = sorted(
        set(sampled_counts) | set(evaluated_counts),
        key=lambda stratum: (_RISK_BASED_STRATUM_ORDER.get(stratum, 100), stratum),
    )
    rows: list[SemanticReviewScoreMatrixRow] = []
    for stratum in all_strata:
        evaluated_count = evaluated_counts.get(stratum, 0)
        avg_score = None
        if evaluated_count > 0:
            avg_score = round(score_sums[stratum] / evaluated_count, 3)
        rows.append(
            SemanticReviewScoreMatrixRow(
                stratum=stratum,
                sampled_count=sampled_counts.get(stratum, 0),
                evaluated_count=evaluated_count,
                avg_score=avg_score,
                blocking_count=blocking_counts.get(stratum, 0),
            )
        )
    return tuple(rows)


def _build_default_reviewer_votes(
    *,
    run_id: str,
    overall_score: float,
    threshold_score: float,
    blocking_count: int,
) -> tuple[SemanticReviewReviewerVote, ...]:
    created_at = datetime.now(tz=UTC)
    votes: list[SemanticReviewReviewerVote] = []
    if blocking_count > 0:
        decisions: tuple[SemanticReviewReviewerDecision, SemanticReviewReviewerDecision] = (
            "reject",
            "reject",
        )
    elif overall_score >= threshold_score:
        decisions = ("approve", "approve")
    else:
        decisions = ("reject", "approve")

    votes.append(
        SemanticReviewReviewerVote(
            vote_id=str(uuid4()),
            run_id=run_id,
            reviewer_slot="reviewer_1",
            actor_key_id=None,
            decision=decisions[0],
            notes="Deterministic agent reviewer vote.",
            created_at=created_at,
        )
    )
    votes.append(
        SemanticReviewReviewerVote(
            vote_id=str(uuid4()),
            run_id=run_id,
            reviewer_slot="reviewer_2",
            actor_key_id=None,
            decision=decisions[1],
            notes="Deterministic agent reviewer vote.",
            created_at=created_at,
        )
    )
    if decisions[0] != decisions[1]:
        tie_break: SemanticReviewReviewerDecision = (
            "approve" if overall_score >= threshold_score else "reject"
        )
        votes.append(
            SemanticReviewReviewerVote(
                vote_id=str(uuid4()),
                run_id=run_id,
                reviewer_slot="product_owner_tie_break",
                actor_key_id=None,
                decision=tie_break,
                notes="Deterministic tie-break vote from autonomous workflow.",
                created_at=created_at,
            )
        )
    return tuple(votes)


def _new_approval_trail(
    *,
    run_id: str,
    actor_type: SemanticReviewActorType,
    actor_key_id: str | None,
    action: SemanticReviewApprovalAction,
    reason: str | None,
    request_id: str | None,
) -> SemanticReviewApprovalTrailRecord:
    return SemanticReviewApprovalTrailRecord(
        approval_id=str(uuid4()),
        run_id=run_id,
        actor_type=actor_type,
        actor_key_id=actor_key_id,
        action=action,
        reason=reason,
        request_id=request_id,
        created_at=datetime.now(tz=UTC),
    )


def _new_status_transition(
    *,
    run_id: str,
    from_status: SemanticReviewRunStatus,
    to_status: SemanticReviewRunStatus,
    actor_type: SemanticReviewActorType,
    actor_key_id: str | None,
    reason: str,
    request_id: str | None,
) -> SemanticReviewStatusTransitionRecord:
    return SemanticReviewStatusTransitionRecord(
        transition_id=str(uuid4()),
        run_id=run_id,
        from_status=from_status,
        to_status=to_status,
        actor_type=actor_type,
        actor_key_id=actor_key_id,
        reason=reason,
        request_id=request_id,
        created_at=datetime.now(tz=UTC),
    )


def _build_artifact_path(
    *,
    artifact_root: Path,
    product_id: str,
    created_at: datetime,
    run_id: str,
) -> str:
    del artifact_root
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"semantic-review/{product_id}/{timestamp}-{run_id}.json"


def _write_artifact(*, artifact_root: Path, run: SemanticReviewRunRecord) -> None:
    relative_path = run.artifact_path.removeprefix("semantic-review/").lstrip("/")
    absolute_path = artifact_root / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run.run_id,
        "product_id": run.product_id,
        "version": run.version,
        "source_revision": run.source_revision,
        "trigger_type": run.trigger_type,
        "policy": {
            "sample_size": run.policy.sample_size,
            "sampling_strategy": run.policy.sampling_strategy,
            "score_scale": run.policy.score_scale,
            "threshold_score": run.policy.threshold_score,
            "approval_mode": run.policy.approval_mode,
            "updated_by": run.policy.updated_by,
            "updated_at": run.policy.updated_at.isoformat(),
        },
        "status": run.status,
        "summary": {
            "sampled_count": run.summary.sampled_count,
            "evaluated_count": run.summary.evaluated_count,
            "overall_score": run.summary.overall_score,
            "threshold_score": run.summary.threshold_score,
            "pass_gates": run.summary.pass_gates,
        },
        "fail_fast_triggered": run.fail_fast_triggered,
        "blocking_error_count": run.blocking_error_count,
        "created_by": run.created_by,
        "created_by_key_id": run.created_by_key_id,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at is not None else None,
        "artifact_path": run.artifact_path,
        "origin": (
            {
                "source": run.origin.source,
                "request_id": run.origin.request_id,
                "issue_id": run.origin.issue_id,
                "issue_type": run.origin.issue_type,
                "severity": run.origin.severity,
                "raw_query": run.origin.raw_query,
                "suspected_fault_domain": run.origin.suspected_fault_domain,
                "suspected_fault_reason": run.origin.suspected_fault_reason,
                "recommendation_title": run.origin.recommendation_title,
                "recommendation_detail": run.origin.recommendation_detail,
            }
            if run.origin is not None
            else None
        ),
        "guided_fix_plan": (
            {
                "summary": run.guided_fix_plan.summary,
                "priority": run.guided_fix_plan.priority,
                "owner_hint": run.guided_fix_plan.owner_hint,
                "next_step": run.guided_fix_plan.next_step,
                "actions": [
                    {
                        "step_id": action.step_id,
                        "title": action.title,
                        "detail": action.detail,
                        "target_section": action.target_section,
                        "action_kind": action.action_kind,
                    }
                    for action in run.guided_fix_plan.actions
                ],
            }
            if run.guided_fix_plan is not None
            else None
        ),
        "score_matrix": [
            {
                "stratum": row.stratum,
                "sampled_count": row.sampled_count,
                "evaluated_count": row.evaluated_count,
                "avg_score": row.avg_score,
                "blocking_count": row.blocking_count,
            }
            for row in run.score_matrix
        ],
        "blocking_findings": [
            {
                "item_id": finding.item_id,
                "source_path": finding.source_path,
                "stratum": finding.stratum,
                "blocking_error_type": finding.blocking_error_type,
                "score": finding.score,
                "review_notes": finding.review_notes,
            }
            for finding in run.blocking_findings
        ],
        "reviewer_votes": [
            {
                "vote_id": vote.vote_id,
                "run_id": vote.run_id,
                "reviewer_slot": vote.reviewer_slot,
                "actor_key_id": vote.actor_key_id,
                "decision": vote.decision,
                "notes": vote.notes,
                "created_at": vote.created_at.isoformat(),
            }
            for vote in run.reviewer_votes
        ],
        "approval_trail": [
            {
                "approval_id": action.approval_id,
                "run_id": action.run_id,
                "actor_type": action.actor_type,
                "actor_key_id": action.actor_key_id,
                "action": action.action,
                "reason": action.reason,
                "request_id": action.request_id,
                "created_at": action.created_at.isoformat(),
            }
            for action in run.approval_trail
        ],
        "status_transitions": [
            {
                "transition_id": transition.transition_id,
                "run_id": transition.run_id,
                "from_status": transition.from_status,
                "to_status": transition.to_status,
                "actor_type": transition.actor_type,
                "actor_key_id": transition.actor_key_id,
                "reason": transition.reason,
                "request_id": transition.request_id,
                "created_at": transition.created_at.isoformat(),
            }
            for transition in run.status_transitions
        ],
        "publish_gate_trail": [
            {
                "gate_decision_id": decision.gate_decision_id,
                "run_id": decision.run_id,
                "trigger_type": decision.trigger_type,
                "decision": decision.decision,
                "reason_codes": list(decision.reason_codes),
                "operation_id": decision.operation_id,
                "request_id": decision.request_id,
                "created_at": decision.created_at.isoformat(),
            }
            for decision in run.publish_gate_trail
        ],
        "items": [
            {
                "item_id": item.item_id,
                "source_path": item.source_path,
                "stratum": item.stratum,
                "score": item.score,
                "blocking_error_type": item.blocking_error_type,
                "review_notes": item.review_notes,
                "created_at": item.created_at.isoformat(),
            }
            for item in run.items
        ],
    }
    absolute_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
