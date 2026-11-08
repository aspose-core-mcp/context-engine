"""Typed message contracts that flow between the four quality-loop agents.

Every message is frozen, slot-allocated, and serialisable to JSON via
``to_dict()`` so the audit log can persist the entire cycle history with
no information loss. The shape is intentionally narrow — each agent
emits exactly one variant — so downstream consumers can pattern-match
on the type.

Message flow:

    QueryResponseSample  --judge-->     QualityVerdict
    QualityVerdict       --diagnose-->  DiagnosisReport
    DiagnosisReport      --propose-->   RemediationProposal
    RemediationProposal  --guard-->     GuardDecision

The Coordinator records *every* message at every transition into the
JSONL audit log so an auditor can replay any cycle end-to-end.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# JudgeAgent output
# ---------------------------------------------------------------------------


class VerdictDimension(StrEnum):
    """The four sub-scores the JudgeAgent computes for every sampled response."""

    CITATION_ACCURACY = "citation_accuracy"
    VERSION_MATCH = "version_match"
    SYMBOL_FQN_CONSISTENCY = "symbol_fqn_consistency"
    CONFIDENCE_CALIBRATION = "confidence_calibration"


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """Score for one sampled query_docs response.

    ``overall_score`` is the unweighted mean of the per-dimension scores.
    Scores are 0..1 where 1.0 is perfect; the score-low threshold is set
    by the judge config (typically 0.7).
    """

    sample_id: str
    cycle_id: str
    emitted_at: str
    product_id: str
    programming_language: str
    version: str | None
    overall_score: float
    per_dimension: dict[str, float]
    notes: tuple[str, ...] = ()
    # Optional: which prompt-pack variant produced the underlying response.
    # Threaded from the QueryResponseSample so the DiagnosisAgent can
    # compare variants and surface PROMPT_VARIANT_UNDERPERFORMING when
    # one variant lags peers across the cycle batch.
    prompt_pack_version: str | None = None

    def is_low_score(self, threshold: float = 0.7) -> bool:
        return self.overall_score < threshold

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["per_dimension"] = dict(self.per_dimension)
        payload["notes"] = list(self.notes)
        payload["message_type"] = "QualityVerdict"
        return payload


# ---------------------------------------------------------------------------
# DiagnosisAgent output
# ---------------------------------------------------------------------------


class DiagnosisRootCause(StrEnum):
    """Fixed taxonomy of root causes the DiagnosisAgent can identify.

    A finite taxonomy is critical for the GuardAgent — proposed actions
    are only generated for known causes; anything else escalates to a
    human via an ``OPEN_INCIDENT`` proposal.
    """

    SCOPED_PRODUCT_LANGUAGE_REGRESSION = "scoped_product_language_regression"
    VERSION_FILTER_MISMATCH = "version_filter_mismatch"
    LANE_IMBALANCE = "lane_imbalance"
    RECENT_SNAPSHOT_REGRESSION = "recent_snapshot_regression"
    PROMPT_VARIANT_UNDERPERFORMING = "prompt_variant_underperforming"
    INSUFFICIENT_SAMPLE_SIZE = "insufficient_sample_size"
    NO_PATTERN = "no_pattern"


@dataclass(frozen=True, slots=True)
class DiagnosisReport:
    """One DiagnosisAgent verdict over a batch of QualityVerdict[]."""

    diagnosis_id: str
    cycle_id: str
    emitted_at: str
    root_cause: DiagnosisRootCause
    affected_scope: dict[str, str]  # e.g. {"product_id": "aspose.ocr", "language": "net"}
    sample_count: int
    low_score_count: int
    confidence: float  # 0..1; how sure the agent is about the root cause
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["root_cause"] = self.root_cause.value
        payload["affected_scope"] = dict(self.affected_scope)
        payload["message_type"] = "DiagnosisReport"
        return payload


# ---------------------------------------------------------------------------
# ProposalAgent output
# ---------------------------------------------------------------------------


class ProposalAction(StrEnum):
    """Allowed actions the ProposalAgent can emit.

    Tracking actions (TRACK_*) auto-approve under the guard; mutating
    actions (ADJUST_*, ROLLBACK_*) always require human approval.
    OPEN_INCIDENT is non-mutating but queues for a human triager. The
    set is intentionally small and audit-friendly — every new action
    requires an explicit GuardAgent policy branch + a test.

    ``ADJUST_PROMPT_VARIANT`` is the self-evolving-prompt surface: when
    the DiagnosisAgent identifies a specific prompt-pack variant as
    under-performing, ProposalAgent can emit a proposal to switch the
    active variant. GuardAgent ALWAYS routes this to human approval —
    prompt switches are LLM-behavioural changes and operators choose
    them, not the loop.
    """

    TRACK_ANOMALY = "track_anomaly"
    OPEN_INCIDENT = "open_incident"
    ADJUST_FUSION_WEIGHTS = "adjust_fusion_weights"
    ROLLBACK_SNAPSHOT = "rollback_snapshot"
    ADJUST_PROMPT_VARIANT = "adjust_prompt_variant"


@dataclass(frozen=True, slots=True)
class RemediationProposal:
    """One ProposalAgent emission keyed to one DiagnosisReport.

    ``blast_radius`` is the Coordinator's machine-readable signal of how
    many production assets the action would affect (queries / users /
    snapshots). The GuardAgent's policy keys on this number plus
    ``action`` to decide auto vs. human approval.
    """

    proposal_id: str
    cycle_id: str
    emitted_at: str
    diagnosis_id: str
    action: ProposalAction
    payload: dict[str, Any]
    blast_radius: int
    confidence: float
    rationale: str

    def is_destructive(self) -> bool:
        return self.action in {
            ProposalAction.ADJUST_FUSION_WEIGHTS,
            ProposalAction.ROLLBACK_SNAPSHOT,
            ProposalAction.ADJUST_PROMPT_VARIANT,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["payload"] = dict(self.payload)
        payload["message_type"] = "RemediationProposal"
        return payload


# ---------------------------------------------------------------------------
# GuardAgent output
# ---------------------------------------------------------------------------


class GuardOutcome(StrEnum):
    AUTO_APPROVED = "auto_approved"
    NEEDS_HUMAN_APPROVAL = "needs_human_approval"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class GuardDecision:
    """The terminal message in a single quality-loop cycle.

    ``outcome=AUTO_APPROVED`` permits the Coordinator (or a downstream
    actuator agent in a future phase) to apply the action immediately.
    ``NEEDS_HUMAN_APPROVAL`` opens a queue entry that an operator
    reviews via the admin UI. ``REJECTED`` closes the loop with no
    further action.
    """

    decision_id: str
    cycle_id: str
    emitted_at: str
    proposal_id: str
    outcome: GuardOutcome
    rationale: str
    policy_violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        payload["policy_violations"] = list(self.policy_violations)
        payload["message_type"] = "GuardDecision"
        return payload


# ---------------------------------------------------------------------------
# AdaptiveAgent output (see calibration.py + adaptive_agent.py)
# ---------------------------------------------------------------------------


class AdaptationKind(StrEnum):
    """Bounded mutations the AdaptiveAgent is permitted to apply per cycle.

    Each kind has hard min/max bounds enforced by ``calibration.py`` and a
    rate-limit of one mutation per cycle, so the system can never oscillate
    or drift unboundedly.
    """

    JUDGE_LOW_THRESHOLD_RAISE = "judge_low_threshold_raise"
    JUDGE_LOW_THRESHOLD_LOWER = "judge_low_threshold_lower"
    DIAGNOSIS_MIN_LOW_RATIO_RAISE = "diagnosis_min_low_ratio_raise"
    DIAGNOSIS_MIN_LOW_RATIO_LOWER = "diagnosis_min_low_ratio_lower"
    PROPOSAL_HIGH_CONFIDENCE_FLOOR_RAISE = "proposal_high_confidence_floor_raise"
    PROPOSAL_HIGH_CONFIDENCE_FLOOR_LOWER = "proposal_high_confidence_floor_lower"
    GUARD_BLAST_CAP_TIGHTEN = "guard_blast_cap_tighten"
    GUARD_BLAST_CAP_RELAX = "guard_blast_cap_relax"
    NO_OP = "no_op"


@dataclass(frozen=True, slots=True)
class AdaptationEvent:
    """One bounded mutation the AdaptiveAgent applied to calibration state.

    The audit log carries the full sequence of these events so an
    auditor can replay the calibration trajectory end-to-end.
    """

    event_id: str
    cycle_id: str
    emitted_at: str
    kind: AdaptationKind
    parameter_name: str
    previous_value: float
    new_value: float
    delta: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["message_type"] = "AdaptationEvent"
        return payload


# ---------------------------------------------------------------------------
# Cycle summary (aggregated by Coordinator)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeDisagreement:
    """One sample where the LLM judge disagrees with the deterministic judge.

    Recorded in the JudgeAgreementReport so operators can review the
    rubric — the loop's own scoring methodology becomes self-reflective.
    """

    sample_id: str
    deterministic_score: float
    llm_score: float
    delta: float
    deterministic_dimensions: dict[str, float]
    llm_dimensions: dict[str, float]
    llm_rationale: str


@dataclass(frozen=True, slots=True)
class JudgeAgreementReport:
    """Cross-validation report from the LLMJudgeAgent.

    The LLMJudgeAgent is a *shadow* over the deterministic JudgeAgent —
    it scores a subset of the same samples using an LLM and compares
    against the deterministic verdict. Sustained disagreement above the
    tolerance is the signal that the rubric needs human review.

    Emitting this report is the self-reflection indicator: the loop
    is no longer just judging samples, it is also *judging its own
    judgment*. The deterministic Judge remains authoritative — LLM
    disagreement does not change the cycle's verdicts, only feeds a
    human-review queue.
    """

    report_id: str
    cycle_id: str
    emitted_at: str
    samples_compared: int
    agreements: int
    disagreements: int
    agreement_rate: float
    mean_absolute_delta: float
    disagreement_details: tuple[JudgeDisagreement, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["disagreement_details"] = [
            {**asdict(d)} for d in self.disagreement_details
        ]
        return payload


class CorrelationTrend(StrEnum):
    """Direction of a metric trend across recent cycles."""

    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class CorrelationReport:
    """Cross-cycle trend analysis emitted by the CrossCycleCorrelationAgent.

    The five reactive/adaptive agents (Judge / Diagnose / Propose / Guard /
    Adaptive) are intentionally stateless across cycles — each cycle's
    audit-log entries are sufficient to replay it without referring to any
    prior cycle. The CrossCycleCorrelationAgent restores cross-cycle
    awareness *without* breaking that invariant: it reads only from the
    on-disk CycleSummary records the Coordinator has already committed,
    computes deterministic trend metrics, and emits one typed report per
    cycle.

    The report goes to the audit log and is consumed by downstream
    observers (admin UI, operator inspection, future AdaptiveAgent
    enhancements). It is informational — it does not itself mutate
    calibration or take action.

    This message type moves the loop beyond per-cycle calibration
    mutations: the system now reflects on its own trajectory rather than
    only on the current cycle.
    """

    report_id: str
    cycle_id: str
    emitted_at: str
    cycles_examined: int
    earliest_cycle_started_at: str | None
    latest_cycle_started_at: str | None
    sample_volume_trend: CorrelationTrend
    duration_trend: CorrelationTrend
    rejection_rate: float
    rejection_velocity_cycles: int
    adaptation_density: float
    mean_duration_seconds: float
    recommendations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sample_volume_trend"] = self.sample_volume_trend.value
        payload["duration_trend"] = self.duration_trend.value
        payload["recommendations"] = list(self.recommendations)
        return payload


@dataclass(frozen=True, slots=True)
class CycleSummary:
    """Aggregated output of one Coordinator cycle.

    Persists alongside the audit log under
    ``reports/quality-loop/last-summary.json`` (gitignored). The CI gate
    reads this to flag any cycle where the loop itself failed or where a
    REJECTED outcome indicates something the GuardAgent could not
    classify.
    """

    cycle_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    samples_processed: int
    verdicts_emitted: int
    diagnoses_emitted: int
    proposals_emitted: int
    decisions_emitted: int
    adaptations_applied: int = 0
    correlation_reports_emitted: int = 0
    llm_judge_reports_emitted: int = 0
    outcome_counts: dict[str, int] = field(default_factory=dict)
    audit_log_path: str | None = None
    calibration_state_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome_counts"] = dict(self.outcome_counts)
        return payload
