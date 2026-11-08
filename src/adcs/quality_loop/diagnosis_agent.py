"""DiagnosisAgent — clusters low-score verdicts and assigns a root cause.

Consumes :class:`QualityVerdict` records and emits one
:class:`DiagnosisReport` per detectable cluster. The taxonomy is fixed
(see :class:`DiagnosisRootCause`) so the downstream ProposalAgent has a
deterministic mapping from cause to typed proposal action.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

from adcs.quality_loop.models import (
    DiagnosisReport,
    DiagnosisRootCause,
    QualityVerdict,
    VerdictDimension,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class DiagnosisAgentConfig:
    """Tunables for the clustering + classification rules."""

    score_low_threshold: float = 0.7
    minimum_cluster_size: int = 3
    minimum_low_ratio: float = 0.4  # ≥ this fraction must be low-score in scope
    confidence_strong: float = 0.85
    confidence_weak: float = 0.55
    # Prompt-variant drift detection.
    #
    # When two or more prompt-pack variants are present in the cycle's
    # verdicts, the agent flags one as under-performing if its mean
    # score lags the best-performing variant by at least
    # ``prompt_variant_min_mean_gap`` AND the underperforming variant
    # carries at least ``prompt_variant_min_samples`` observations.
    # The detector only fires when ≥ 2 distinct variants are present.
    prompt_variant_min_mean_gap: float = 0.10
    prompt_variant_min_samples: int = 3


@dataclass
class DiagnosisAgent:
    """Stateless. Re-clusters every cycle from the current verdict batch."""

    config: DiagnosisAgentConfig

    def __init__(self, config: DiagnosisAgentConfig | None = None) -> None:
        self.config = config or DiagnosisAgentConfig()

    def apply_calibration(
        self,
        *,
        score_low_threshold: float,
        minimum_low_ratio: float,
    ) -> None:
        """Overwrite the threshold + ratio from external calibration."""
        self.config = DiagnosisAgentConfig(
            score_low_threshold=score_low_threshold,
            minimum_cluster_size=self.config.minimum_cluster_size,
            minimum_low_ratio=minimum_low_ratio,
            confidence_strong=self.config.confidence_strong,
            confidence_weak=self.config.confidence_weak,
        )

    def diagnose_batch(
        self, *, verdicts: tuple[QualityVerdict, ...], cycle_id: str
    ) -> tuple[DiagnosisReport, ...]:
        if not verdicts:
            logger.info("DiagnosisAgent: no verdicts in cycle=%s", cycle_id)
            return ()

        if len(verdicts) < self.config.minimum_cluster_size:
            return (self._insufficient_sample(cycle_id=cycle_id, verdicts=verdicts),)

        # Try the most-specific cluster first (product+language+version),
        # then fall back to broader patterns.
        reports: list[DiagnosisReport] = []
        reports.extend(self._cluster_by_scope(cycle_id=cycle_id, verdicts=verdicts))
        reports.extend(self._detect_version_mismatch(cycle_id=cycle_id, verdicts=verdicts))
        reports.extend(self._detect_lane_imbalance(cycle_id=cycle_id, verdicts=verdicts))
        reports.extend(
            self._detect_prompt_variant_underperformance(
                cycle_id=cycle_id, verdicts=verdicts
            )
        )

        if not reports:
            reports.append(self._no_pattern(cycle_id=cycle_id, verdicts=verdicts))

        logger.info(
            "DiagnosisAgent emitted %d reports (cycle=%s)", len(reports), cycle_id
        )
        return tuple(reports)

    # -------- clustering ---------------------------------------------------

    def _cluster_by_scope(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> list[DiagnosisReport]:
        scope_buckets: dict[tuple[str, str, str | None], list[QualityVerdict]] = (
            defaultdict(list)
        )
        for v in verdicts:
            scope_buckets[(v.product_id, v.programming_language, v.version)].append(v)

        out: list[DiagnosisReport] = []
        for (product, lang, version), bucket in scope_buckets.items():
            if len(bucket) < self.config.minimum_cluster_size:
                continue
            low = [v for v in bucket if v.is_low_score(self.config.score_low_threshold)]
            ratio = len(low) / len(bucket)
            if ratio < self.config.minimum_low_ratio:
                continue
            confidence = self._confidence_from_ratio(ratio=ratio, sample_count=len(bucket))
            scope = {"product_id": product, "programming_language": lang}
            if version is not None:
                scope["version"] = version
            rationale = (
                f"{len(low)}/{len(bucket)} verdicts ({ratio:.0%}) below threshold "
                f"{self.config.score_low_threshold:.2f} for "
                f"product={product}, language={lang}"
                + (f", version={version}" if version is not None else "")
            )
            out.append(
                DiagnosisReport(
                    diagnosis_id=_make_diagnosis_id(),
                    cycle_id=cycle_id,
                    emitted_at=utc_iso(),
                    root_cause=DiagnosisRootCause.SCOPED_PRODUCT_LANGUAGE_REGRESSION,
                    affected_scope=scope,
                    sample_count=len(bucket),
                    low_score_count=len(low),
                    confidence=confidence,
                    rationale=rationale,
                )
            )
        return out

    def _detect_version_mismatch(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> list[DiagnosisReport]:
        # Pattern: a sub-axis (version_match) is below threshold for many
        # samples even though overall score may not be low. This
        # indicates strict_version filter not honoured.
        version_failures = [
            v
            for v in verdicts
            if v.per_dimension.get(VerdictDimension.VERSION_MATCH.value, 1.0) < 0.5
        ]
        if len(version_failures) < self.config.minimum_cluster_size:
            return []
        scope = {
            "version_match_failures": str(len(version_failures)),
            "sample_size": str(len(verdicts)),
        }
        ratio = len(version_failures) / len(verdicts)
        return [
            DiagnosisReport(
                diagnosis_id=_make_diagnosis_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                root_cause=DiagnosisRootCause.VERSION_FILTER_MISMATCH,
                affected_scope=scope,
                sample_count=len(verdicts),
                low_score_count=len(version_failures),
                confidence=self._confidence_from_ratio(
                    ratio=ratio, sample_count=len(verdicts)
                ),
                rationale=(
                    f"{len(version_failures)} samples have version_match score < 0.5; "
                    "strict_version filter may not be honoured"
                ),
            )
        ]

    def _detect_lane_imbalance(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> list[DiagnosisReport]:
        # Pattern: low citation_accuracy concentrated in one product+language.
        # Often indicates one of the retrieval lanes is degraded for that
        # scope (e.g. a stale OpenSearch alias).
        low_citation = [
            v
            for v in verdicts
            if v.per_dimension.get(VerdictDimension.CITATION_ACCURACY.value, 1.0) < 0.6
        ]
        if len(low_citation) < self.config.minimum_cluster_size:
            return []

        # Count by scope to find the dominant cluster
        scope_counts: Counter[tuple[str, str]] = Counter(
            (v.product_id, v.programming_language) for v in low_citation
        )
        dominant_scope, dominant_count = scope_counts.most_common(1)[0]
        if dominant_count < self.config.minimum_cluster_size:
            return []
        ratio = dominant_count / len(low_citation)
        return [
            DiagnosisReport(
                diagnosis_id=_make_diagnosis_id(),
                cycle_id=cycle_id,
                emitted_at=utc_iso(),
                root_cause=DiagnosisRootCause.LANE_IMBALANCE,
                affected_scope={
                    "product_id": dominant_scope[0],
                    "programming_language": dominant_scope[1],
                },
                sample_count=len(verdicts),
                low_score_count=dominant_count,
                confidence=self._confidence_from_ratio(
                    ratio=ratio, sample_count=len(low_citation)
                ),
                rationale=(
                    f"{dominant_count}/{len(low_citation)} low-citation samples concentrate "
                    f"in {dominant_scope[0]}/{dominant_scope[1]}; one lane likely degraded"
                ),
            )
        ]

    def _detect_prompt_variant_underperformance(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> list[DiagnosisReport]:
        # Pattern: ≥ 2 distinct prompt-pack variants are present in the
        # cycle and one variant's mean overall_score lags the best
        # variant by more than ``prompt_variant_min_mean_gap``. This is
        # the self-evolving-prompt detector that closes the loop
        # between the prompt registry and the AdaptiveAgent — without
        # it, the ADJUST_PROMPT_VARIANT path stays dead code.
        variant_scores: dict[str, list[float]] = defaultdict(list)
        for v in verdicts:
            if v.prompt_pack_version is None:
                continue
            variant_scores[v.prompt_pack_version].append(v.overall_score)

        eligible = {
            variant: scores
            for variant, scores in variant_scores.items()
            if len(scores) >= self.config.prompt_variant_min_samples
        }
        if len(eligible) < 2:
            return []

        variant_means = {
            variant: sum(scores) / len(scores) for variant, scores in eligible.items()
        }
        best_variant = max(variant_means, key=lambda k: variant_means[k])
        best_mean = variant_means[best_variant]

        out: list[DiagnosisReport] = []
        for variant, mean_score in variant_means.items():
            if variant == best_variant:
                continue
            gap = best_mean - mean_score
            if gap < self.config.prompt_variant_min_mean_gap:
                continue
            low_count = sum(
                1
                for s in eligible[variant]
                if s < self.config.score_low_threshold
            )
            low_fraction = low_count / len(eligible[variant])
            # Scope keys MUST match the ones the ProposalAgent reads from
            # diagnosis.affected_scope when emitting ADJUST_PROMPT_VARIANT:
            # ``prompt_pack_version`` + ``candidate_prompt_pack_version`` +
            # ``low_score_fraction``. Misnaming these breaks the wire.
            scope = {
                "prompt_pack_version": variant,
                "candidate_prompt_pack_version": best_variant,
                "mean_gap": f"{gap:.4f}",
                "low_score_fraction": f"{low_fraction:.4f}",
            }
            ratio = min(1.0, gap / 0.3)  # 0.3 = "very large gap"
            confidence = self._confidence_from_ratio(
                ratio=ratio, sample_count=len(eligible[variant])
            )
            rationale = (
                f"prompt_pack_version={variant!r} mean overall_score="
                f"{mean_score:.3f} (n={len(eligible[variant])}) lags best variant "
                f"{best_variant!r} mean={best_mean:.3f} "
                f"(n={len(eligible[best_variant])}) by {gap:.3f}"
            )
            out.append(
                DiagnosisReport(
                    diagnosis_id=_make_diagnosis_id(),
                    cycle_id=cycle_id,
                    emitted_at=utc_iso(),
                    root_cause=DiagnosisRootCause.PROMPT_VARIANT_UNDERPERFORMING,
                    affected_scope=scope,
                    sample_count=len(eligible[variant]),
                    low_score_count=low_count,
                    confidence=confidence,
                    rationale=rationale,
                )
            )
        return out

    # -------- helpers ------------------------------------------------------

    def _insufficient_sample(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> DiagnosisReport:
        return DiagnosisReport(
            diagnosis_id=_make_diagnosis_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            root_cause=DiagnosisRootCause.INSUFFICIENT_SAMPLE_SIZE,
            affected_scope={},
            sample_count=len(verdicts),
            low_score_count=sum(
                1 for v in verdicts if v.is_low_score(self.config.score_low_threshold)
            ),
            confidence=1.0,
            rationale=(
                f"only {len(verdicts)} verdicts in batch; need "
                f">= {self.config.minimum_cluster_size} for clustering"
            ),
        )

    def _no_pattern(
        self, *, cycle_id: str, verdicts: tuple[QualityVerdict, ...]
    ) -> DiagnosisReport:
        return DiagnosisReport(
            diagnosis_id=_make_diagnosis_id(),
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            root_cause=DiagnosisRootCause.NO_PATTERN,
            affected_scope={},
            sample_count=len(verdicts),
            low_score_count=sum(
                1 for v in verdicts if v.is_low_score(self.config.score_low_threshold)
            ),
            confidence=1.0,
            rationale="no scope cluster crossed minimum_low_ratio threshold",
        )

    def _confidence_from_ratio(self, *, ratio: float, sample_count: int) -> float:
        # Bigger samples and stronger ratios -> higher confidence.
        size_factor = min(1.0, sample_count / 10.0)
        ratio_factor = min(1.0, ratio / 0.8)
        score = 0.4 + 0.6 * size_factor * ratio_factor
        if score >= self.config.confidence_strong:
            return self.config.confidence_strong
        return max(self.config.confidence_weak, score)


def _make_diagnosis_id() -> str:
    return f"diag-{uuid.uuid4().hex[:12]}"
