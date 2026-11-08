"""Tests for LLM-assisted verification of uncertain layout detections."""

from adcs.ingestion.llm_runtime_policy import IngestionLLMBackend
from adcs.ingestion.source_layout_detection_orchestrator import _apply_llm_assisted_enrichment

# IngestionLLMBackend has no .LLM member; use the real non-DETERMINISTIC member.
_LLM = IngestionLLMBackend.OPENAI_COMPATIBLE


class _Verifier:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = 0

    def verify(self, *, detection: dict) -> dict:
        self.calls += 1
        return self.response


def test_certain_detection_skips_llm() -> None:
    v = _Verifier({"verdict": "confirm"})
    det = {"uncertain": False, "dimensions": [], "confidence": 0.9}
    out = _apply_llm_assisted_enrichment(detection=det, backend=_LLM, verifier=v)
    assert v.calls == 0
    assert out["confidence"] == 0.9


def test_uncertain_correct_adopts_corrected_dimensions() -> None:
    corrected = [
        {"semantic": "programming_language", "depth": 1},
        {"semantic": "doc_locale", "depth": 2},
        {"semantic": "namespace", "depth": 3},
    ]
    v = _Verifier(
        {
            "verdict": "correct",
            "dimensions": corrected,
            "layout_type": "programming_language/doc_locale/namespace",
        }
    )
    det = {"uncertain": True, "dimensions": [], "confidence": 0.4}
    out = _apply_llm_assisted_enrichment(detection=det, backend=_LLM, verifier=v)
    assert v.calls == 1
    assert out["dimensions"] == corrected
    assert out["uncertain"] is False


def test_uncertain_cannot_determine_stays_unresolved() -> None:
    v = _Verifier({"verdict": "cannot_determine"})
    det = {"uncertain": True, "dimensions": [], "confidence": 0.4}
    out = _apply_llm_assisted_enrichment(detection=det, backend=_LLM, verifier=v)
    assert out["uncertain"] is True
    assert out.get("schema_unresolvable") is True


def test_uncertain_confirm_clears_uncertain() -> None:
    v = _Verifier({"verdict": "confirm"})
    det = {
        "uncertain": True,
        "dimensions": [{"semantic": "namespace", "depth": 1}],
        "confidence": 0.4,
    }
    out = _apply_llm_assisted_enrichment(detection=det, backend=_LLM, verifier=v)
    assert v.calls == 1
    assert out["uncertain"] is False
    assert out.get("schema_unresolvable") is None
