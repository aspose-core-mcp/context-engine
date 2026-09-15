"""Unit tests for JudgeAgent — the entry-point scorer of the quality loop."""

from __future__ import annotations

from adcs.quality_loop import JudgeAgent, QueryResponseSample
from adcs.quality_loop.judge_agent import JudgeAgentConfig
from adcs.quality_loop.models import VerdictDimension


def _sample(
    *,
    candidates: tuple[dict[str, object], ...],
    confidence_score: float | None = 0.85,
    requested_version: str | None = "25.1",
    strict_version: bool = True,
) -> QueryResponseSample:
    return QueryResponseSample(
        sample_id="s-1",
        captured_at="2026-05-04T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version=requested_version,
        strict_version=strict_version,
        query="how to ocr",
        candidates=candidates,
        confidence_score=confidence_score,
    )


def test_perfect_response_scores_one() -> None:
    sample = _sample(
        candidates=(
            {
                "canonical_url": "https://docs.aspose.com/ocr/net/",
                "version": "25.1",
                "chunk_id": "c1",
                "symbol_fqn": "Aspose.OCR.Recognize",
            },
        )
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert len(verdicts) == 1
    assert verdicts[0].overall_score == 1.0
    assert all(v == 1.0 for v in verdicts[0].per_dimension.values())


def test_missing_citation_lowers_citation_dimension() -> None:
    sample = _sample(
        candidates=(
            {"canonical_url": "", "version": "25.1", "chunk_id": "c1"},
        )
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert (
        verdicts[0].per_dimension[VerdictDimension.CITATION_ACCURACY.value]
        < 1.0
    )
    assert verdicts[0].overall_score < 1.0


def test_version_mismatch_zeroes_version_dimension_when_strict() -> None:
    sample = _sample(
        candidates=(
            {
                "canonical_url": "https://docs.aspose.com/ocr/net/",
                "version": "24.5",  # mismatch
                "chunk_id": "c1",
            },
        ),
        requested_version="25.1",
        strict_version=True,
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert verdicts[0].per_dimension[VerdictDimension.VERSION_MATCH.value] == 0.0


def test_version_mismatch_ignored_when_strict_version_off() -> None:
    sample = _sample(
        candidates=(
            {
                "canonical_url": "https://docs.aspose.com/ocr/net/",
                "version": "24.5",
                "chunk_id": "c1",
            },
        ),
        strict_version=False,
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert verdicts[0].per_dimension[VerdictDimension.VERSION_MATCH.value] == 1.0


def test_overconfidence_lowers_calibration_dimension() -> None:
    sample = _sample(
        candidates=(
            {"canonical_url": "", "version": "25.1", "chunk_id": "c1"},
        ),
        confidence_score=0.95,  # high confidence on bad citation
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert (
        verdicts[0].per_dimension[VerdictDimension.CONFIDENCE_CALIBRATION.value]
        < 1.0
    )


def test_chunk_id_with_conflicting_fqn_zeroes_fqn_dimension() -> None:
    sample = _sample(
        candidates=(
            {
                "canonical_url": "https://x",
                "version": "25.1",
                "chunk_id": "c1",
                "symbol_fqn": "A.B",
            },
            {
                "canonical_url": "https://y",
                "version": "25.1",
                "chunk_id": "c1",
                "symbol_fqn": "C.D",  # conflict: same chunk, different FQN
            },
        )
    )
    verdicts = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")

    assert (
        verdicts[0].per_dimension[VerdictDimension.SYMBOL_FQN_CONSISTENCY.value]
        == 0.0
    )


def test_low_score_threshold_classifier() -> None:
    # Empty candidates -> citation 0.5, version 1.0, fqn 1.0, calibration 1.0,
    # overall 0.875 (above the default 0.7 threshold).
    sample = _sample(
        candidates=(),
        confidence_score=None,
    )
    verdict = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")[0]
    assert not verdict.is_low_score(threshold=0.7)

    config = JudgeAgentConfig(score_low_threshold=0.95)
    assert verdict.is_low_score(threshold=config.score_low_threshold)


def test_verdict_serialises_to_json_dict() -> None:
    sample = _sample(
        candidates=({"canonical_url": "https://x", "version": "25.1", "chunk_id": "c1"},)
    )
    verdict = JudgeAgent().score_batch(samples=(sample,), cycle_id="cycle-test")[0]
    payload = verdict.to_dict()

    assert payload["message_type"] == "QualityVerdict"
    assert payload["product_id"] == "aspose.ocr"
    assert isinstance(payload["per_dimension"], dict)
    assert isinstance(payload["notes"], list)


def test_empty_batch_returns_empty_tuple() -> None:
    assert JudgeAgent().score_batch(samples=(), cycle_id="cycle-test") == ()
