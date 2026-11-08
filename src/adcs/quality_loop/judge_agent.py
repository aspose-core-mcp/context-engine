"""JudgeAgent — scores recent query_docs responses on four dimensions.

The judge is the entry point of the loop. It consumes
:class:`QueryResponseSample` records (drawn from a sampler that the
Coordinator wires up) and emits one :class:`QualityVerdict` per sample.

The scoring model is intentionally **deterministic and rule-based**, not
LLM-judged. Three reasons:

1. The audit log must be reproducible. Replaying an old verdict against
   the same sample must produce the same score.
2. The judge runs on every cycle (potentially hourly); LLM cost would
   be unbounded.
3. The loop complements, rather than replaces, the existing
   :mod:`adcs.quality_gates.golden_eval` LLM-judge gate: golden_eval runs
   at release time over a curated dataset; the loop runs continuously
   over production samples.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from adcs.quality_loop.models import (
    QualityVerdict,
    VerdictDimension,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueryResponseSample:
    """One observation the judge scores.

    Built by the Coordinator from a recent query_docs response. Carries
    only the fields the judge actually inspects — not the full response
    body — so the audit log stays compact.
    """

    sample_id: str
    captured_at: str
    product_id: str
    programming_language: str
    requested_version: str | None
    strict_version: bool
    query: str
    candidates: tuple[dict[str, Any], ...]  # subset of citation metadata
    confidence_score: float | None  # the service's self-reported confidence
    # Optional: the prompt-pack variant the response was generated under.
    # Populated by the conversion pipeline when the prompt registry is
    # enabled. Lets the DiagnosisAgent detect cross-variant performance
    # drift and propose ADJUST_PROMPT_VARIANT remediations.
    prompt_pack_version: str | None = None


@dataclass
class JudgeAgentConfig:
    """Tunables for the deterministic scoring rules."""

    minimum_citations: int = 1
    citation_match_score: float = 1.0
    citation_missing_penalty: float = 0.5
    fqn_consistency_required: bool = False
    confidence_overconfidence_band: float = 0.15
    score_low_threshold: float = 0.7


@dataclass
class JudgeAgent:
    """Scores a batch of samples; emits one QualityVerdict per sample.

    Statelessness: the judge holds no state across batches. All
    parameterisation comes through ``config``; all I/O is on the
    parameter list. The Coordinator may overwrite
    ``config.score_low_threshold`` from the live :class:`CalibrationState`
    before each cycle so the AdaptiveAgent's threshold drift takes effect.
    """

    config: JudgeAgentConfig = field(default_factory=JudgeAgentConfig)

    def apply_calibration(self, *, score_low_threshold: float) -> None:
        """Overwrite the score-low threshold from external calibration."""
        self.config = JudgeAgentConfig(
            minimum_citations=self.config.minimum_citations,
            citation_match_score=self.config.citation_match_score,
            citation_missing_penalty=self.config.citation_missing_penalty,
            fqn_consistency_required=self.config.fqn_consistency_required,
            confidence_overconfidence_band=self.config.confidence_overconfidence_band,
            score_low_threshold=score_low_threshold,
        )

    def score_batch(
        self, *, samples: tuple[QueryResponseSample, ...], cycle_id: str
    ) -> tuple[QualityVerdict, ...]:
        verdicts: list[QualityVerdict] = []
        for sample in samples:
            verdicts.append(self._score_one(sample=sample, cycle_id=cycle_id))
        logger.info(
            "JudgeAgent scored %d samples (cycle=%s)", len(verdicts), cycle_id
        )
        return tuple(verdicts)

    def _score_one(
        self, *, sample: QueryResponseSample, cycle_id: str
    ) -> QualityVerdict:
        notes: list[str] = []
        per_dim: dict[str, float] = {}

        per_dim[VerdictDimension.CITATION_ACCURACY.value] = self._score_citation(
            sample=sample, notes=notes
        )
        per_dim[VerdictDimension.VERSION_MATCH.value] = self._score_version(
            sample=sample, notes=notes
        )
        per_dim[VerdictDimension.SYMBOL_FQN_CONSISTENCY.value] = self._score_fqn(
            sample=sample, notes=notes
        )
        per_dim[VerdictDimension.CONFIDENCE_CALIBRATION.value] = self._score_confidence(
            sample=sample,
            citation_score=per_dim[VerdictDimension.CITATION_ACCURACY.value],
            notes=notes,
        )

        overall = sum(per_dim.values()) / len(per_dim)

        return QualityVerdict(
            sample_id=sample.sample_id,
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            product_id=sample.product_id,
            programming_language=sample.programming_language,
            version=sample.requested_version,
            overall_score=round(overall, 4),
            per_dimension={k: round(v, 4) for k, v in per_dim.items()},
            notes=tuple(notes),
            prompt_pack_version=sample.prompt_pack_version,
        )

    # ---------- per-dimension scoring rules -------------------------------

    def _score_citation(
        self, *, sample: QueryResponseSample, notes: list[str]
    ) -> float:
        cites = [c for c in sample.candidates if c.get("canonical_url")]
        if len(cites) >= self.config.minimum_citations:
            return self.config.citation_match_score
        notes.append(
            f"only {len(cites)} candidate(s) carry canonical_url; "
            f"required >= {self.config.minimum_citations}"
        )
        return self.config.citation_match_score - self.config.citation_missing_penalty

    def _score_version(
        self, *, sample: QueryResponseSample, notes: list[str]
    ) -> float:
        if not sample.strict_version or sample.requested_version is None:
            return 1.0
        for c in sample.candidates:
            if c.get("version") != sample.requested_version:
                notes.append(
                    f"strict_version={sample.requested_version!r} but a candidate "
                    f"reports version={c.get('version')!r}"
                )
                return 0.0
        return 1.0

    def _score_fqn(
        self, *, sample: QueryResponseSample, notes: list[str]
    ) -> float:
        # Symbol-FQN consistency only matters when the response set has > 1
        # candidate sharing a chunk_id (which would indicate dedup leak).
        seen_chunks: dict[str, str] = {}
        for c in sample.candidates:
            chunk_id = c.get("chunk_id")
            fqn = c.get("symbol_fqn") or ""
            if not isinstance(chunk_id, str) or not chunk_id:
                continue
            if chunk_id in seen_chunks and seen_chunks[chunk_id] != fqn:
                notes.append(
                    f"chunk_id={chunk_id!r} appears with conflicting symbol_fqn"
                )
                return 0.0
            seen_chunks[chunk_id] = fqn
        return 1.0

    def _score_confidence(
        self,
        *,
        sample: QueryResponseSample,
        citation_score: float,
        notes: list[str],
    ) -> float:
        if sample.confidence_score is None:
            return 1.0
        # Overconfidence: high reported confidence but poor citation evidence.
        if (
            sample.confidence_score > 0.9
            and citation_score < self.config.citation_match_score
        ):
            notes.append(
                f"overconfident: reported {sample.confidence_score:.2f} but citation "
                f"score only {citation_score:.2f}"
            )
            return max(0.0, 1.0 - self.config.confidence_overconfidence_band)
        # Underconfidence: low reported confidence on a perfectly-cited result
        # is also a calibration miss but a less-bad one.
        if (
            sample.confidence_score < 0.4
            and citation_score >= self.config.citation_match_score
        ):
            notes.append(
                f"underconfident: reported {sample.confidence_score:.2f} but citations clean"
            )
            return 1.0 - (self.config.confidence_overconfidence_band / 2)
        return 1.0


def make_sample_id() -> str:
    return f"sample-{uuid.uuid4().hex[:12]}"
