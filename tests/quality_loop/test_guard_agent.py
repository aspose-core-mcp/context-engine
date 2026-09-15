"""Unit tests for GuardAgent — the safety policy gate.

These tests are the executable expression of the safety policy
documented in ``docs/quality-loop.md``. Any change to the policy must
be reflected here first; the behaviour-first invariant matters because
the GuardAgent is the only thing standing between the loop and a
production mutation.
"""

from __future__ import annotations

from adcs.quality_loop import GuardAgent
from adcs.quality_loop.guard_agent import GuardAgentConfig
from adcs.quality_loop.models import (
    GuardOutcome,
    ProposalAction,
    RemediationProposal,
)


def _proposal(
    *,
    action: ProposalAction,
    blast_radius: int = 50,
    confidence: float = 0.85,
) -> RemediationProposal:
    return RemediationProposal(
        proposal_id="prop-1",
        cycle_id="cycle-test",
        emitted_at="2026-05-04T00:00:00Z",
        diagnosis_id="diag-1",
        action=action,
        payload={"reason": "test"},
        blast_radius=blast_radius,
        confidence=confidence,
        rationale="test rationale",
    )


def test_track_anomaly_auto_approved_within_caps() -> None:
    proposal = _proposal(action=ProposalAction.TRACK_ANOMALY, blast_radius=0)
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.AUTO_APPROVED


def test_open_incident_requires_human_approval() -> None:
    proposal = _proposal(action=ProposalAction.OPEN_INCIDENT)
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_rollback_snapshot_always_requires_human_even_with_high_confidence() -> None:
    """The hard invariant: rollbacks NEVER auto-execute, no matter what."""
    proposal = _proposal(
        action=ProposalAction.ROLLBACK_SNAPSHOT,
        blast_radius=10,
        confidence=0.99,
    )
    config = GuardAgentConfig(permit_auto_rollback=True)  # even with the flag
    decision = GuardAgent(config=config).gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL
    assert "ROLLBACK_SNAPSHOT" in decision.rationale


def test_adjust_fusion_weights_default_safe_mode_requires_human() -> None:
    proposal = _proposal(
        action=ProposalAction.ADJUST_FUSION_WEIGHTS,
        confidence=0.97,
        blast_radius=20,
    )
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_adjust_fusion_weights_auto_approved_when_flag_on_high_conf_low_blast() -> None:
    proposal = _proposal(
        action=ProposalAction.ADJUST_FUSION_WEIGHTS,
        confidence=0.97,
        blast_radius=20,
    )
    config = GuardAgentConfig(
        permit_auto_fusion_weight_adjust=True,
        auto_approve_blast_cap=100,
    )
    decision = GuardAgent(config=config).gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.AUTO_APPROVED


def test_adjust_fusion_weights_low_confidence_still_needs_human_with_flag_on() -> None:
    proposal = _proposal(
        action=ProposalAction.ADJUST_FUSION_WEIGHTS,
        confidence=0.80,  # below 0.95
        blast_radius=20,
    )
    config = GuardAgentConfig(permit_auto_fusion_weight_adjust=True)
    decision = GuardAgent(config=config).gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_blast_radius_above_absolute_cap_rejected() -> None:
    proposal = _proposal(
        action=ProposalAction.TRACK_ANOMALY,
        blast_radius=10_000,
    )
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.REJECTED
    assert decision.policy_violations  # non-empty


def test_blast_radius_above_auto_cap_but_below_absolute_needs_human() -> None:
    proposal = _proposal(
        action=ProposalAction.TRACK_ANOMALY,
        blast_radius=500,  # above default auto cap (100), below absolute (5000)
    )
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]

    assert decision.outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_decision_serialises_to_json_dict() -> None:
    proposal = _proposal(action=ProposalAction.TRACK_ANOMALY, blast_radius=0)
    decision = GuardAgent().gate_batch(
        proposals=(proposal,), cycle_id="cycle-test"
    )[0]
    payload = decision.to_dict()

    assert payload["message_type"] == "GuardDecision"
    assert payload["outcome"] == "auto_approved"
    assert isinstance(payload["policy_violations"], list)
