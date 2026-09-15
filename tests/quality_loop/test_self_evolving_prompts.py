"""Tests for the ADJUST_PROMPT_VARIANT self-evolving-prompt surface.

The quality loop's A8/A9 movement adds a typed action through which the
loop can recommend switching the active prompt-pack variant when one
under-performs. This test surface covers:

* the new ProposalAction enum value and `is_destructive` classification;
* the new DiagnosisRootCause enum value;
* ProposalAgent's mapping from PROMPT_VARIANT_UNDERPERFORMING diagnosis
  to an ADJUST_PROMPT_VARIANT proposal with the expected payload shape;
* GuardAgent's policy: ADJUST_PROMPT_VARIANT *always* routes to
  NEEDS_HUMAN_APPROVAL, even with a 100% confidence and a small blast
  radius;
* GuardAgent's hard ceiling: an oversized prompt-variant proposal is
  still REJECTED outright.
"""

from __future__ import annotations

from adcs.quality_loop.guard_agent import GuardAgent, GuardAgentConfig
from adcs.quality_loop.models import (
    DiagnosisReport,
    DiagnosisRootCause,
    GuardOutcome,
    ProposalAction,
    RemediationProposal,
)
from adcs.quality_loop.proposal_agent import ProposalAgent


def _make_diagnosis(
    *,
    root_cause: DiagnosisRootCause = DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING,
    confidence: float = 0.92,
    affected_count: int = 5,
    sample_count: int = 20,
    scope: dict[str, object] | None = None,
) -> DiagnosisReport:
    return DiagnosisReport(
        diagnosis_id="diag-test-1",
        cycle_id="cycle-test",
        emitted_at="2026-06-01T00:00:00Z",
        root_cause=root_cause,
        affected_scope=dict(
            scope
            or {
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "prompt_pack_version": "v1",
                "candidate_prompt_pack_version": "v2",
                "low_score_fraction": "0.45",
            }
        ),
        sample_count=sample_count,
        low_score_count=affected_count,
        confidence=confidence,
        rationale="variant v1 lags v2 by 0.20 on low-score fraction over 50 cycles",
    )


def _make_proposal(
    *,
    action: ProposalAction = ProposalAction.ADJUST_PROMPT_VARIANT,
    blast_radius: int = 50,
    confidence: float = 0.9,
) -> RemediationProposal:
    return RemediationProposal(
        proposal_id="prop-test-1",
        cycle_id="cycle-test",
        emitted_at="2026-06-01T00:00:00Z",
        diagnosis_id="diag-test-1",
        action=action,
        payload={
            "underperforming_variant_id": "v1",
            "candidate_variant_id": "v2",
        },
        blast_radius=blast_radius,
        confidence=confidence,
        rationale="test",
    )


# ---------------------------------------------------------------------------
# Enum invariants
# ---------------------------------------------------------------------------


def test_adjust_prompt_variant_is_in_proposal_action_enum() -> None:
    assert ProposalAction.ADJUST_PROMPT_VARIANT.value == "adjust_prompt_variant"


def test_prompt_variant_underperforming_is_in_root_cause_enum() -> None:
    assert (
        DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING.value
        == "prompt_variant_underperforming"
    )


def test_adjust_prompt_variant_proposal_is_destructive() -> None:
    """Prompt switches change LLM behaviour — must be classified destructive."""
    proposal = _make_proposal(action=ProposalAction.ADJUST_PROMPT_VARIANT)
    assert proposal.is_destructive() is True


# ---------------------------------------------------------------------------
# ProposalAgent: PROMPT_VARIANT_UNDERPERFORMING → ADJUST_PROMPT_VARIANT
# ---------------------------------------------------------------------------


def test_proposal_agent_maps_prompt_underperforming_to_prompt_switch() -> None:
    agent = ProposalAgent()
    diagnosis = _make_diagnosis()
    proposals = agent.propose_batch(
        diagnoses=(diagnosis,), cycle_id="cycle-test"
    )
    assert len(proposals) == 1
    assert proposals[0].action is ProposalAction.ADJUST_PROMPT_VARIANT


def test_proposal_agent_payload_contains_variant_ids() -> None:
    agent = ProposalAgent()
    diagnosis = _make_diagnosis()
    proposal = agent.propose_batch(
        diagnoses=(diagnosis,), cycle_id="cycle-test"
    )[0]
    payload = proposal.payload
    assert payload["underperforming_variant_id"] == "v1"
    assert payload["candidate_variant_id"] == "v2"
    assert "scope" in payload
    assert "rationale" in payload


def test_proposal_agent_emits_higher_blast_radius_for_prompt_switch() -> None:
    """Prompt switches affect every query under the variant scope —
    blast radius should be larger than for a tracking action."""
    agent = ProposalAgent()
    diagnosis = _make_diagnosis()
    proposal = agent.propose_batch(
        diagnoses=(diagnosis,), cycle_id="cycle-test"
    )[0]
    track_diagnosis = _make_diagnosis(
        root_cause=DiagnosisRootCause.NO_PATTERN,
    )
    track_proposal = agent.propose_batch(
        diagnoses=(track_diagnosis,), cycle_id="cycle-test"
    )[0]
    assert proposal.blast_radius > track_proposal.blast_radius


# ---------------------------------------------------------------------------
# GuardAgent: ADJUST_PROMPT_VARIANT always NEEDS_HUMAN_APPROVAL
# ---------------------------------------------------------------------------


def test_guard_routes_prompt_variant_to_human_approval_by_default() -> None:
    guard = GuardAgent()
    decisions = guard.gate_batch(
        proposals=(_make_proposal(),), cycle_id="cycle-test"
    )
    assert len(decisions) == 1
    assert decisions[0].outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL
    assert "ADJUST_PROMPT_VARIANT" in decisions[0].rationale


def test_guard_does_not_auto_approve_prompt_variant_at_perfect_confidence() -> None:
    """Even with confidence 1.0 and blast radius 0, prompt switches require human."""
    guard = GuardAgent()
    proposal = _make_proposal(blast_radius=0, confidence=1.0)
    decisions = guard.gate_batch(proposals=(proposal,), cycle_id="cycle-test")
    assert decisions[0].outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_guard_does_not_auto_approve_prompt_variant_with_fusion_flag_on() -> None:
    """The fusion-weight feature flag must NOT leak permission to prompt switches."""
    guard = GuardAgent(
        GuardAgentConfig(
            permit_auto_fusion_weight_adjust=True,
        )
    )
    proposal = _make_proposal(blast_radius=10, confidence=0.99)
    decisions = guard.gate_batch(proposals=(proposal,), cycle_id="cycle-test")
    assert decisions[0].outcome is GuardOutcome.NEEDS_HUMAN_APPROVAL


def test_guard_rejects_prompt_variant_above_absolute_blast_cap() -> None:
    """An oversized prompt-variant proposal still hits the REJECTED ceiling."""
    guard = GuardAgent(GuardAgentConfig(absolute_blast_cap=1000))
    proposal = _make_proposal(blast_radius=5000, confidence=0.9)
    decisions = guard.gate_batch(proposals=(proposal,), cycle_id="cycle-test")
    assert decisions[0].outcome is GuardOutcome.REJECTED
    assert "absolute_cap" in " ".join(decisions[0].policy_violations)


def test_guard_does_not_treat_prompt_variant_as_tracking() -> None:
    """ADJUST_PROMPT_VARIANT must NOT be in the auto_approved_actions set."""
    config = GuardAgentConfig()
    assert ProposalAction.ADJUST_PROMPT_VARIANT not in config.auto_approved_actions
