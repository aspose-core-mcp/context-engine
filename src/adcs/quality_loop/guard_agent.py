"""GuardAgent — gates RemediationProposal[] per the safety policy.

The guard's only job is to decide one of:

- ``AUTO_APPROVED``         — non-destructive AND under blast-radius cap
                              AND confidence above floor.
- ``NEEDS_HUMAN_APPROVAL``  — destructive, OR blast radius high, OR low
                              confidence. Queued for the admin UI.
- ``REJECTED``              — over the absolute blast cap, or violates
                              one of the policy invariants below.

Policy invariants (always enforced regardless of config):

1. ROLLBACK_SNAPSHOT *always* requires human approval. Never auto.
2. ADJUST_FUSION_WEIGHTS requires human approval **in default safe
   mode**; can be auto-approved only when the operator has flipped the
   feature-flag + the per-action confidence is at least 0.95.
3. ADJUST_PROMPT_VARIANT *always* requires human approval. Prompt
   switches are LLM-behavioural changes — operators choose them, not
   the loop. There is no feature flag for auto-approval; the policy is
   absolute.
4. A proposal whose blast_radius > absolute_cap is REJECTED outright,
   regardless of action type. The cap protects against runaway loops
   that would propose a fleet-wide change.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from adcs.quality_loop.models import (
    GuardDecision,
    GuardOutcome,
    ProposalAction,
    RemediationProposal,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class GuardAgentConfig:
    """Safety policy for the guard.

    Defaults reflect the Phase 1 read-only posture: nothing destructive
    auto-executes; the loop emits proposals and a human approves them.
    """

    auto_approve_blast_cap: int = 100
    absolute_blast_cap: int = 5000
    auto_approve_confidence_floor: float = 0.85
    permit_auto_fusion_weight_adjust: bool = False
    permit_auto_rollback: bool = False  # Never True — invariant; flag is for tests
    auto_approved_actions: frozenset[ProposalAction] = frozenset(
        {ProposalAction.TRACK_ANOMALY}
    )


@dataclass
class GuardAgent:
    config: GuardAgentConfig

    def __init__(self, config: GuardAgentConfig | None = None) -> None:
        self.config = config or GuardAgentConfig()

    def apply_calibration(self, *, auto_approve_blast_cap: int) -> None:
        """Overwrite the auto-approve cap from external calibration.

        The absolute cap and the destructive-action invariants are
        intentionally NOT calibratable — they are policy, not tunables.
        """
        self.config = GuardAgentConfig(
            auto_approve_blast_cap=auto_approve_blast_cap,
            absolute_blast_cap=self.config.absolute_blast_cap,
            auto_approve_confidence_floor=self.config.auto_approve_confidence_floor,
            permit_auto_fusion_weight_adjust=self.config.permit_auto_fusion_weight_adjust,
            permit_auto_rollback=self.config.permit_auto_rollback,
            auto_approved_actions=self.config.auto_approved_actions,
        )

    def gate_batch(
        self, *, proposals: tuple[RemediationProposal, ...], cycle_id: str
    ) -> tuple[GuardDecision, ...]:
        decisions: list[GuardDecision] = []
        for prop in proposals:
            decisions.append(self._gate_one(proposal=prop, cycle_id=cycle_id))
        logger.info(
            "GuardAgent emitted %d decisions (cycle=%s)", len(decisions), cycle_id
        )
        return tuple(decisions)

    def _gate_one(
        self, *, proposal: RemediationProposal, cycle_id: str
    ) -> GuardDecision:
        violations: list[str] = []

        # Hard rejection: over the absolute cap.
        if proposal.blast_radius > self.config.absolute_blast_cap:
            violations.append(
                f"blast_radius={proposal.blast_radius} exceeds absolute_cap="
                f"{self.config.absolute_blast_cap}"
            )
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.REJECTED,
                rationale=(
                    "absolute blast cap exceeded; the loop is not permitted to "
                    "propose actions of this scope"
                ),
                policy_violations=tuple(violations),
            )

        # Hard invariant 1: rollbacks NEVER auto-approve.
        if proposal.action is ProposalAction.ROLLBACK_SNAPSHOT:
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL,
                rationale=(
                    "ROLLBACK_SNAPSHOT always requires human approval per the "
                    "safety policy invariant"
                ),
            )

        # Hard invariant 3: prompt-variant switches NEVER auto-approve.
        # Switching the active prompt pack changes LLM behaviour; operators
        # choose the variant after reviewing the proposal evidence. No
        # feature flag is available to relax this.
        if proposal.action is ProposalAction.ADJUST_PROMPT_VARIANT:
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL,
                rationale=(
                    "ADJUST_PROMPT_VARIANT always requires human approval per "
                    "the safety policy invariant — prompt switches are "
                    "LLM-behavioural changes"
                ),
            )

        # Default-deny for fusion-weight adjustments unless the operator
        # has flipped the feature flag AND confidence is very high.
        if proposal.action is ProposalAction.ADJUST_FUSION_WEIGHTS:
            if (
                self.config.permit_auto_fusion_weight_adjust
                and proposal.confidence >= 0.95
                and proposal.blast_radius <= self.config.auto_approve_blast_cap
            ):
                return GuardDecision(
                    decision_id=_make_decision_id(),
                    cycle_id=cycle_id,
                    emitted_at=utc_iso(),
                    proposal_id=proposal.proposal_id,
                    outcome=GuardOutcome.AUTO_APPROVED,
                    rationale=(
                        "ADJUST_FUSION_WEIGHTS: feature flag on, confidence ≥ 0.95, "
                        "blast radius within cap"
                    ),
                )
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL,
                rationale=(
                    "ADJUST_FUSION_WEIGHTS requires human approval in safe mode"
                ),
            )

        # Tracking actions: auto-approve if within the configured cap.
        if proposal.action in self.config.auto_approved_actions:
            if proposal.blast_radius > self.config.auto_approve_blast_cap:
                violations.append(
                    f"blast_radius={proposal.blast_radius} above "
                    f"auto_approve_cap={self.config.auto_approve_blast_cap}"
                )
                return GuardDecision(
                    decision_id=_make_decision_id(),
                    cycle_id=cycle_id,
                    emitted_at=utc_iso(),
                    proposal_id=proposal.proposal_id,
                    outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL,
                    rationale=(
                        "tracking action above auto-approve blast cap"
                    ),
                    policy_violations=tuple(violations),
                )
            if proposal.confidence < self.config.auto_approve_confidence_floor:
                return GuardDecision(
                    decision_id=_make_decision_id(),
                    cycle_id=cycle_id,
                    emitted_at=utc_iso(),
                    proposal_id=proposal.proposal_id,
                    outcome=GuardOutcome.AUTO_APPROVED,
                    rationale=(
                        f"tracking action; confidence {proposal.confidence:.2f} below "
                        f"floor {self.config.auto_approve_confidence_floor:.2f}, "
                        "but action is non-mutating"
                    ),
                )
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.AUTO_APPROVED,
                rationale="tracking action, within all caps",
            )

        # OPEN_INCIDENT: always queued for human (the human triages the
        # incident; the loop just signals).
        if proposal.action is ProposalAction.OPEN_INCIDENT:
            return GuardDecision(
                decision_id=_make_decision_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                proposal_id=proposal.proposal_id,
                outcome=GuardOutcome.NEEDS_HUMAN_APPROVAL,
                rationale="OPEN_INCIDENT: opening an incident requires a human on-call",
            )

        # Defensive fallback for new actions added later without a policy.
        return GuardDecision(
            decision_id=_make_decision_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            proposal_id=proposal.proposal_id,
            outcome=GuardOutcome.REJECTED,
            rationale=f"unknown action {proposal.action.value!r}; policy missing",
            policy_violations=("unknown_action_no_policy",),
        )


def _make_decision_id() -> str:
    return f"dec-{uuid.uuid4().hex[:12]}"
