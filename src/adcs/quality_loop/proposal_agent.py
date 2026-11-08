"""ProposalAgent — turns DiagnosisReport into typed RemediationProposal.

The mapping from root cause to action is deterministic (one to one) so
this agent's emissions are reproducible. Confidence and blast-radius
are passed through from the diagnosis so the GuardAgent can policy-gate
them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from adcs.quality_loop.models import (
    DiagnosisReport,
    DiagnosisRootCause,
    ProposalAction,
    RemediationProposal,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class ProposalAgentConfig:
    """Tunables for action selection + blast-radius estimation.

    ``estimated_queries_per_minute`` is used to translate a scope-level
    diagnosis into a concrete affected-traffic estimate that the
    GuardAgent's policy keys on.
    """

    estimated_queries_per_minute: int = 10
    high_confidence_floor: float = 0.85


@dataclass
class ProposalAgent:
    config: ProposalAgentConfig

    def __init__(self, config: ProposalAgentConfig | None = None) -> None:
        self.config = config or ProposalAgentConfig()

    def apply_calibration(self, *, high_confidence_floor: float) -> None:
        """Overwrite the confidence floor from external calibration."""
        self.config = ProposalAgentConfig(
            estimated_queries_per_minute=self.config.estimated_queries_per_minute,
            high_confidence_floor=high_confidence_floor,
        )

    def propose_batch(
        self, *, diagnoses: tuple[DiagnosisReport, ...], cycle_id: str
    ) -> tuple[RemediationProposal, ...]:
        proposals: list[RemediationProposal] = []
        for diag in diagnoses:
            proposals.append(self._propose_one(diagnosis=diag, cycle_id=cycle_id))
        logger.info(
            "ProposalAgent emitted %d proposals (cycle=%s)",
            len(proposals),
            cycle_id,
        )
        return tuple(proposals)

    def _propose_one(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        if diagnosis.root_cause is DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION:
            return self._propose_scoped_regression(diagnosis=diagnosis, cycle_id=cycle_id)
        if diagnosis.root_cause is DiagnosisRootCause.VERSION_FILTER_MISMATCH:
            return self._propose_open_incident(
                diagnosis=diagnosis,
                cycle_id=cycle_id,
                title="strict_version filter not honoured",
                severity="Sev2",
            )
        if diagnosis.root_cause is DiagnosisRootCause.LANE_IMBALANCE:
            return self._propose_lane_imbalance(diagnosis=diagnosis, cycle_id=cycle_id)
        if diagnosis.root_cause is DiagnosisRootCause.RECENT_SNAPSHOT_REGRESSION:
            return self._propose_rollback(diagnosis=diagnosis, cycle_id=cycle_id)
        if diagnosis.root_cause is DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING:
            return self._propose_prompt_variant_switch(
                diagnosis=diagnosis, cycle_id=cycle_id
            )
        # NO_PATTERN and INSUFFICIENT_SAMPLE_SIZE: track only.
        return self._propose_track_only(diagnosis=diagnosis, cycle_id=cycle_id)

    # -------- per-cause proposal generators -------------------------------

    def _propose_scoped_regression(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        # When confidence is high AND the scope is a single product+language,
        # propose a fusion-weight tweak. Otherwise: track + open incident.
        if diagnosis.confidence >= self.config.high_confidence_floor:
            return RemediationProposal(
                proposal_id=_make_proposal_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                diagnosis_id=diagnosis.diagnosis_id,
                action=ProposalAction.ADJUST_FUSION_WEIGHTS,
                payload={
                    "scope": dict(diagnosis.affected_scope),
                    "suggested_dense_weight_delta": -0.05,
                    "suggested_lexical_weight_delta": +0.05,
                    "reason": diagnosis.rationale,
                },
                blast_radius=self._estimated_blast(diagnosis=diagnosis),
                confidence=diagnosis.confidence,
                rationale=(
                    "scoped regression with strong confidence; modest fusion "
                    "rebalance may restore citation accuracy"
                ),
            )
        return self._propose_open_incident(
            diagnosis=diagnosis,
            cycle_id=cycle_id,
            title=(
                f"scoped regression in "
                f"{diagnosis.affected_scope.get('product_id', '?')}/"
                f"{diagnosis.affected_scope.get('programming_language', '?')}"
            ),
            severity="Sev3",
        )

    def _propose_lane_imbalance(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        # Always open an incident for human triage; lane outages should be
        # diagnosed against live infra, not auto-mitigated.
        return self._propose_open_incident(
            diagnosis=diagnosis,
            cycle_id=cycle_id,
            title=(
                f"suspected lane imbalance for "
                f"{diagnosis.affected_scope.get('product_id', '?')}/"
                f"{diagnosis.affected_scope.get('programming_language', '?')}"
            ),
            severity="Sev3",
        )

    def _propose_rollback(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        return RemediationProposal(
            proposal_id=_make_proposal_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            diagnosis_id=diagnosis.diagnosis_id,
            action=ProposalAction.ROLLBACK_SNAPSHOT,
            payload={
                "scope": dict(diagnosis.affected_scope),
                "reason": diagnosis.rationale,
            },
            blast_radius=self._estimated_blast(diagnosis=diagnosis) * 5,  # rollback affects more
            confidence=diagnosis.confidence,
            rationale=(
                "recent-snapshot regression detected; recommend rollback to N-1 "
                "via runbook S1A.A (always requires human approval)"
            ),
        )

    def _propose_prompt_variant_switch(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        """Self-evolving-prompts surface.

        Emits an ADJUST_PROMPT_VARIANT proposal naming the under-performing
        variant and the candidate replacement variant from the diagnosis
        scope. GuardAgent always routes this to NEEDS_HUMAN_APPROVAL —
        prompt switches are LLM-behavioural changes that operators must
        review before applying. The proposal carries enough payload for
        the admin UI to render a side-by-side variant comparison.
        """
        scope = diagnosis.affected_scope
        return RemediationProposal(
            proposal_id=_make_proposal_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            diagnosis_id=diagnosis.diagnosis_id,
            action=ProposalAction.ADJUST_PROMPT_VARIANT,
            payload={
                "scope": dict(scope),
                "underperforming_variant_id": scope.get(
                    "prompt_pack_version", "unknown"
                ),
                "candidate_variant_id": scope.get(
                    "candidate_prompt_pack_version", "default"
                ),
                "low_score_fraction": scope.get("low_score_fraction"),
                "rationale": diagnosis.rationale,
            },
            # Prompt switches affect every future query under the variant's
            # scope. Treat as a moderate blast radius scaled by the
            # estimated traffic share of the affected scope.
            blast_radius=self._estimated_blast(diagnosis=diagnosis) * 2,
            confidence=diagnosis.confidence,
            rationale=(
                "prompt variant under-performing relative to peers; recommend "
                "switching active variant for the affected scope after operator "
                "review (always requires human approval)"
            ),
        )

    def _propose_open_incident(
        self,
        *,
        diagnosis: DiagnosisReport,
        cycle_id: str,
        title: str,
        severity: str,
    ) -> RemediationProposal:
        return RemediationProposal(
            proposal_id=_make_proposal_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            diagnosis_id=diagnosis.diagnosis_id,
            action=ProposalAction.OPEN_INCIDENT,
            payload={
                "title": title,
                "severity": severity,
                "scope": dict(diagnosis.affected_scope),
                "rationale": diagnosis.rationale,
            },
            blast_radius=self._estimated_blast(diagnosis=diagnosis),
            confidence=diagnosis.confidence,
            rationale=(
                f"non-actuator action: open {severity} incident for human triage"
            ),
        )

    def _propose_track_only(
        self, *, diagnosis: DiagnosisReport, cycle_id: str
    ) -> RemediationProposal:
        return RemediationProposal(
            proposal_id=_make_proposal_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            diagnosis_id=diagnosis.diagnosis_id,
            action=ProposalAction.TRACK_ANOMALY,
            payload={
                "diagnosis_root_cause": diagnosis.root_cause.value,
                "rationale": diagnosis.rationale,
            },
            blast_radius=0,
            confidence=diagnosis.confidence,
            rationale=(
                "informational only; pattern recorded for trend analysis"
            ),
        )

    def _estimated_blast(self, *, diagnosis: DiagnosisReport) -> int:
        # Affected QPS proxy: low-score sample count × estimated QPM.
        return diagnosis.low_score_count * self.config.estimated_queries_per_minute


def _make_proposal_id() -> str:
    return f"prop-{uuid.uuid4().hex[:12]}"
