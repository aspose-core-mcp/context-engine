"""Unit tests for ProposalAgent — maps DiagnosisReport to typed actions."""

from __future__ import annotations

from adcs.quality_loop import ProposalAgent
from adcs.quality_loop.models import (
    DiagnosisReport,
    DiagnosisRootCause,
    ProposalAction,
)


def _diagnosis(
    *,
    root_cause: DiagnosisRootCause,
    confidence: float = 0.85,
    sample_count: int = 10,
    low_score_count: int = 5,
    affected_scope: dict[str, str] | None = None,
) -> DiagnosisReport:
    return DiagnosisReport(
        diagnosis_id="diag-1",
        cycle_id="cycle-test",
        emitted_at="2026-05-04T00:00:00Z",
        root_cause=root_cause,
        affected_scope=affected_scope
        or {"product_id": "aspose.ocr", "programming_language": "net"},
        sample_count=sample_count,
        low_score_count=low_score_count,
        confidence=confidence,
        rationale="test rationale",
    )


def test_high_confidence_scoped_regression_proposes_fusion_adjust() -> None:
    diag = _diagnosis(
        root_cause=DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION,
        confidence=0.9,
    )
    proposals = ProposalAgent().propose_batch(diagnoses=(diag,), cycle_id="cycle-test")

    assert len(proposals) == 1
    assert proposals[0].action is ProposalAction.ADJUST_FUSION_WEIGHTS
    assert proposals[0].is_destructive()


def test_low_confidence_scoped_regression_proposes_open_incident() -> None:
    diag = _diagnosis(
        root_cause=DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION,
        confidence=0.55,
    )
    proposals = ProposalAgent().propose_batch(diagnoses=(diag,), cycle_id="cycle-test")

    assert proposals[0].action is ProposalAction.OPEN_INCIDENT
    assert not proposals[0].is_destructive()


def test_version_mismatch_proposes_open_incident_sev2() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.VERSION_FILTER_MISMATCH)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.action is ProposalAction.OPEN_INCIDENT
    assert proposal.payload["severity"] == "Sev2"


def test_lane_imbalance_proposes_open_incident_sev3() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.LANE_IMBALANCE)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.action is ProposalAction.OPEN_INCIDENT
    assert proposal.payload["severity"] == "Sev3"


def test_recent_snapshot_regression_proposes_rollback() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.RECENT_SNAPSHOT_REGRESSION)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.action is ProposalAction.ROLLBACK_SNAPSHOT
    assert proposal.is_destructive()


def test_no_pattern_proposes_track_anomaly() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.NO_PATTERN)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.action is ProposalAction.TRACK_ANOMALY
    assert proposal.blast_radius == 0
    assert not proposal.is_destructive()


def test_insufficient_sample_proposes_track_anomaly() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.INSUFFICIENT_SAMPLE_SIZE)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.action is ProposalAction.TRACK_ANOMALY


def test_blast_radius_scales_with_low_score_count() -> None:
    small = _diagnosis(
        root_cause=DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION,
        low_score_count=3,
        confidence=0.9,
    )
    large = _diagnosis(
        root_cause=DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION,
        low_score_count=30,
        confidence=0.9,
    )
    p_small = ProposalAgent().propose_batch(
        diagnoses=(small,), cycle_id="cycle-test"
    )[0]
    p_large = ProposalAgent().propose_batch(
        diagnoses=(large,), cycle_id="cycle-test"
    )[0]

    assert p_large.blast_radius > p_small.blast_radius


def test_rollback_blast_radius_amplified() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.RECENT_SNAPSHOT_REGRESSION)
    proposal = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0]
    incident_diag = _diagnosis(root_cause=DiagnosisRootCause.LANE_IMBALANCE)
    incident = ProposalAgent().propose_batch(
        diagnoses=(incident_diag,), cycle_id="cycle-test"
    )[0]

    assert proposal.blast_radius > incident.blast_radius


def test_proposal_serialises_to_json_dict() -> None:
    diag = _diagnosis(root_cause=DiagnosisRootCause.NO_PATTERN)
    payload = ProposalAgent().propose_batch(
        diagnoses=(diag,), cycle_id="cycle-test"
    )[0].to_dict()

    assert payload["message_type"] == "RemediationProposal"
    assert "action" in payload
    assert isinstance(payload["payload"], dict)
