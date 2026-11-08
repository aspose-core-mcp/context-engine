"""Unit tests for DiagnosisAgent — clusters verdicts and assigns root causes."""

from __future__ import annotations

from adcs.quality_loop import DiagnosisAgent
from adcs.quality_loop.models import (
    DiagnosisRootCause,
    QualityVerdict,
    VerdictDimension,
)


def _verdict(
    *,
    sample_id: str,
    overall: float,
    product: str = "aspose.ocr",
    language: str = "net",
    version: str | None = "25.1",
    citation: float | None = None,
    version_match: float = 1.0,
) -> QualityVerdict:
    per_dim = {
        VerdictDimension.CITATION_ACCURACY.value: (
            citation if citation is not None else overall
        ),
        VerdictDimension.VERSION_MATCH.value: version_match,
        VerdictDimension.SYMBOL_FQN_CONSISTENCY.value: 1.0,
        VerdictDimension.CONFIDENCE_CALIBRATION.value: 1.0,
    }
    return QualityVerdict(
        sample_id=sample_id,
        cycle_id="cycle-test",
        emitted_at="2026-05-04T00:00:00Z",
        product_id=product,
        programming_language=language,
        version=version,
        overall_score=overall,
        per_dimension=per_dim,
    )


def test_empty_verdicts_emits_nothing() -> None:
    assert DiagnosisAgent().diagnose_batch(verdicts=(), cycle_id="cycle-test") == ()


def test_insufficient_sample_size_emits_one_diagnosis() -> None:
    verdicts = (
        _verdict(sample_id="s1", overall=0.5),
        _verdict(sample_id="s2", overall=0.4),
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")

    assert len(reports) == 1
    assert reports[0].root_cause is DiagnosisRootCause.INSUFFICIENT_SAMPLE_SIZE


def test_no_pattern_when_all_high_score() -> None:
    verdicts = tuple(
        _verdict(sample_id=f"s{i}", overall=0.95) for i in range(10)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")

    assert any(r.root_cause is DiagnosisRootCause.NO_PATTERN for r in reports)


def test_scoped_regression_detected_when_low_concentrated_in_one_scope() -> None:
    verdicts = tuple(
        _verdict(
            sample_id=f"low-{i}",
            overall=0.3,
            product="aspose.ocr",
            language="net",
        )
        for i in range(5)
    ) + tuple(
        _verdict(
            sample_id=f"clean-{i}",
            overall=0.95,
            product="aspose.ocr",
            language="java",
        )
        for i in range(5)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")

    scoped = [
        r for r in reports
        if r.root_cause is DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION
    ]
    assert scoped, "expected a scoped regression diagnosis"
    assert scoped[0].affected_scope["product_id"] == "aspose.ocr"
    assert scoped[0].affected_scope["programming_language"] == "net"
    assert scoped[0].low_score_count == 5


def test_version_filter_mismatch_pattern_detected() -> None:
    verdicts = tuple(
        _verdict(sample_id=f"v-{i}", overall=0.7, version_match=0.0)
        for i in range(4)
    ) + tuple(
        _verdict(sample_id=f"clean-{i}", overall=0.9) for i in range(6)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")

    assert any(
        r.root_cause is DiagnosisRootCause.VERSION_FILTER_MISMATCH for r in reports
    )


def test_lane_imbalance_detected_when_low_citation_concentrated() -> None:
    # 5 low-citation samples in aspose.ocr/net; 2 elsewhere -> dominant cluster
    verdicts = tuple(
        _verdict(
            sample_id=f"lic-{i}",
            overall=0.65,
            product="aspose.ocr",
            language="net",
            citation=0.5,
        )
        for i in range(5)
    ) + tuple(
        _verdict(
            sample_id=f"other-{i}",
            overall=0.65,
            product="aspose.ocr",
            language="java",
            citation=0.5,
        )
        for i in range(2)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")

    lane_reports = [
        r for r in reports if r.root_cause is DiagnosisRootCause.LANE_IMBALANCE
    ]
    assert lane_reports
    assert lane_reports[0].affected_scope["product_id"] == "aspose.ocr"


def test_diagnosis_serialises_to_json_dict() -> None:
    verdicts = tuple(
        _verdict(sample_id=f"s{i}", overall=0.3) for i in range(5)
    )
    reports = DiagnosisAgent().diagnose_batch(verdicts=verdicts, cycle_id="cycle-test")
    payload = reports[0].to_dict()

    assert payload["message_type"] == "DiagnosisReport"
    assert "root_cause" in payload
    assert isinstance(payload["affected_scope"], dict)
