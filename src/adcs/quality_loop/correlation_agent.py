"""CrossCycleCorrelationAgent — the 6th agent.

The other five agents (Judge / Diagnose / Propose / Guard / Adaptive)
are intentionally stateless across cycles — each cycle's audit-log
entries are sufficient to replay it without referring to any prior
cycle. That invariant keeps the audit-log machinery clean and any
single cycle deterministically reproducible from disk.

The CrossCycleCorrelationAgent restores cross-cycle awareness
*without* breaking that invariant. It does not carry any in-agent
mutable state. Instead it reads the CycleSummary records the
Coordinator has already committed (one ``summary`` message per past
cycle in the audit log + the persisted last-summary.json), computes
deterministic trend metrics from them, and emits exactly one typed
:class:`CorrelationReport` per invocation.

The report flows into the audit log and surfaces in the admin UI; it
is informational and does not itself mutate calibration. A subsequent
iteration may feed it into the AdaptiveAgent's decision priority list.

With it, the loop reflects on its own trajectory rather than only on
the present cycle.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from adcs.quality_loop.models import (
    CorrelationReport,
    CorrelationTrend,
    CycleSummary,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class CrossCycleCorrelationAgentConfig:
    """Tunables for the correlation logic.

    All thresholds are deterministic. The agent has no learned weights
    and no per-cycle internal state — the same input produces the same
    report on every invocation.
    """

    # Number of most-recent cycles to include in the trend analysis.
    # Default 12 cycles ≈ half a day at hourly cadence.
    history_window: int = 12

    # Minimum cycles before a trend can be reported as non-INSUFFICIENT_DATA.
    min_cycles_for_trend: int = 4

    # Threshold (in standard deviations of the value series) above which
    # a delta between the older-half mean and the newer-half mean is
    # classified as RISING or FALLING. Otherwise STABLE.
    trend_threshold_stddevs: float = 0.5

    # Rejection-rate floor above which the agent recommends proactive
    # guard-cap tightening.
    rejection_rate_warning_threshold: float = 0.20

    # Number of consecutive clean cycles after which the agent suggests
    # the operator may relax non-safety thresholds.
    clean_streak_relax_recommendation: int = 10

    # Adaptation-density (mutations per cycle) above which the agent
    # recommends pausing adaptation or widening hard bounds.
    high_adaptation_density_threshold: float = 0.80


class CrossCycleCorrelationAgent:
    """Stateless reader of recent CycleSummary records.

    The agent emits exactly one :class:`CorrelationReport` per call to
    :meth:`correlate`. With fewer than ``min_cycles_for_trend`` summaries
    available, the report still emits — its trend fields are set to
    :data:`CorrelationTrend.INSUFFICIENT_DATA` and the recommendations
    surface the gap so the operator knows why.
    """

    def __init__(
        self, config: CrossCycleCorrelationAgentConfig | None = None
    ) -> None:
        self.config = config or CrossCycleCorrelationAgentConfig()

    def correlate(
        self,
        *,
        cycle_id: str,
        recent_summaries: Sequence[CycleSummary],
    ) -> CorrelationReport:
        """Compute trends from the recent N cycles and emit a typed report."""
        # Oldest first; cap to the configured window.
        examined = sorted(recent_summaries, key=lambda s: s.started_at)
        if len(examined) > self.config.history_window:
            examined = examined[-self.config.history_window :]
        n = len(examined)

        if n < self.config.min_cycles_for_trend:
            sample_trend = CorrelationTrend.INSUFFICIENT_DATA
            duration_trend = CorrelationTrend.INSUFFICIENT_DATA
        else:
            sample_trend = self._classify(
                [float(s.samples_processed) for s in examined]
            )
            duration_trend = self._classify(
                [s.duration_seconds for s in examined]
            )

        rejections = sum(
            1 for s in examined if s.outcome_counts.get("rejected", 0) > 0
        )
        rejection_rate = rejections / n if n > 0 else 0.0

        rejection_velocity = 0
        for s in reversed(examined):
            if s.outcome_counts.get("rejected", 0) > 0:
                break
            rejection_velocity += 1

        adaptation_density = (
            sum(s.adaptations_applied for s in examined) / n if n > 0 else 0.0
        )
        mean_duration = (
            statistics.mean(s.duration_seconds for s in examined) if n > 0 else 0.0
        )

        recommendations = self._recommend(
            n=n,
            sample_trend=sample_trend,
            duration_trend=duration_trend,
            rejection_rate=rejection_rate,
            rejection_velocity=rejection_velocity,
            adaptation_density=adaptation_density,
        )

        report = CorrelationReport(
            report_id=f"corr-{uuid.uuid4().hex[:12]}",
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            cycles_examined=n,
            earliest_cycle_started_at=examined[0].started_at if n > 0 else None,
            latest_cycle_started_at=examined[-1].started_at if n > 0 else None,
            sample_volume_trend=sample_trend,
            duration_trend=duration_trend,
            rejection_rate=round(rejection_rate, 4),
            rejection_velocity_cycles=rejection_velocity,
            adaptation_density=round(adaptation_density, 4),
            mean_duration_seconds=round(mean_duration, 4),
            recommendations=recommendations,
        )
        logger.info(
            "CrossCycleCorrelationAgent: cycle=%s examined=%d rej=%.2f "
            "trend=(samples=%s,duration=%s)",
            cycle_id,
            n,
            rejection_rate,
            sample_trend.value,
            duration_trend.value,
        )
        return report

    def _classify(self, values: Sequence[float]) -> CorrelationTrend:
        """Classify a value series as RISING / FALLING / STABLE.

        Compares the mean of the most recent half against the older half;
        the delta is normalised by the overall population stddev. Above
        ``trend_threshold_stddevs`` in either direction → RISING / FALLING.
        Within the band → STABLE. A degenerate series (zero stddev) is
        STABLE by construction.
        """
        if len(values) < 2:
            return CorrelationTrend.STABLE

        half = len(values) // 2
        older = list(values[:half])
        newer = list(values[half:])
        if not older or not newer:
            return CorrelationTrend.STABLE

        older_mean = statistics.mean(older)
        newer_mean = statistics.mean(newer)
        overall_stddev = statistics.pstdev(values)
        if overall_stddev == 0.0:
            return CorrelationTrend.STABLE

        delta_in_stddevs = (newer_mean - older_mean) / overall_stddev
        threshold = self.config.trend_threshold_stddevs
        if delta_in_stddevs > threshold:
            return CorrelationTrend.RISING
        if delta_in_stddevs < -threshold:
            return CorrelationTrend.FALLING
        return CorrelationTrend.STABLE

    def _recommend(
        self,
        *,
        n: int,
        sample_trend: CorrelationTrend,
        duration_trend: CorrelationTrend,
        rejection_rate: float,
        rejection_velocity: int,
        adaptation_density: float,
    ) -> tuple[str, ...]:
        """Deterministic recommendation rules.

        Each rule is independent — multiple recommendations can fire in
        one report. With no rules triggered, returns a single "nominal"
        recommendation so the report is never empty.
        """
        hints: list[str] = []
        if n < self.config.min_cycles_for_trend:
            hints.append(
                f"cycle history below threshold ({n} < "
                f"{self.config.min_cycles_for_trend}); trends suppressed "
                f"until more cycles accumulate"
            )
            return tuple(hints)

        if rejection_rate > self.config.rejection_rate_warning_threshold:
            hints.append(
                f"rejection rate {rejection_rate:.2f} exceeds "
                f"{self.config.rejection_rate_warning_threshold:.2f} over "
                f"{n} cycles; recommend tightening guard cap proactively"
            )
        if rejection_velocity >= self.config.clean_streak_relax_recommendation:
            hints.append(
                f"{rejection_velocity} clean cycles since last rejection; "
                f"safe window — operator may relax non-safety thresholds"
            )
        if duration_trend is CorrelationTrend.RISING:
            hints.append(
                "cycle duration trending upward; investigate sampler "
                "latency or per-agent regressions"
            )
        if sample_trend is CorrelationTrend.FALLING:
            hints.append(
                "sample volume trending downward; verify query traffic "
                "or sampler health"
            )
        if adaptation_density > self.config.high_adaptation_density_threshold:
            hints.append(
                f"adaptation density {adaptation_density:.2f} mutations per "
                f"cycle is unusually high; consider widening hard bounds or "
                f"pausing adaptation"
            )
        if not hints:
            hints.append("trends within nominal range; no action needed")
        return tuple(hints)
