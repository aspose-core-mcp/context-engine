"""AdaptiveAgent — the 5th agent that closes the loop on itself.

The first four agents (Judge / Diagnose / Propose / Guard) are
*reactive*: each cycle they read fresh samples, score, cluster,
propose, and gate. They do not learn. The AdaptiveAgent is *meta*: it
inspects the cycle's verdicts + decisions and applies one bounded,
auditable mutation to the shared :class:`CalibrationState` so the next
cycle's parameters are slightly better-tuned.

This is what moves the loop from multi-agent coordination to **adaptive**
behaviour. The adaptation is intentionally conservative
— at most one mutation per cycle, every change clamped to hard bounds,
every change emitted as an :class:`AdaptationEvent` to the audit log.

The adaptation rules are deterministic functions of cycle observations,
*not* learned weights. Reproducibility from the audit log is preserved.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from adcs.quality_loop.calibration import CalibrationState
from adcs.quality_loop.models import (
    AdaptationEvent,
    AdaptationKind,
    CorrelationReport,
    GuardDecision,
    GuardOutcome,
    QualityVerdict,
    utc_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveAgentConfig:
    """Tunables for the adaptation rules.

    The adaptation steps are intentionally tiny: each cycle moves a
    single parameter by a few percent at most. Across hundreds of
    cycles the calibration evolves visibly; across one cycle the
    movement is negligible. This is the right discipline for an
    online tuning loop with no rollback ability.
    """

    judge_threshold_step: float = 0.01
    diagnosis_ratio_step: float = 0.02
    proposal_floor_step: float = 0.01
    guard_cap_tighten_factor: float = 0.5  # halve on rejection
    guard_cap_relax_step: int = 10
    guard_relax_after_clean_cycles: int = 5
    target_low_score_fraction: float = 0.30  # judge tunes towards this
    target_proposal_approval_proxy: float = 0.6
    # Trend-driven proactive tightening: if the CorrelationAgent reports a
    # rejection_rate above this threshold across the recent window, the
    # AdaptiveAgent halves the guard cap proactively *even when the
    # current cycle had no rejection*. This is the cross-cycle reflex
    # that promotes the loop from per-cycle adaptive to trend-aware
    # adaptive — recurring drift is dampened before the next rejection
    # rather than after.
    proactive_tighten_rejection_rate: float = 0.20


@dataclass
class AdaptiveAgent:
    """Stateless w.r.t. cycles; reads observations, returns one mutation."""

    config: AdaptiveAgentConfig

    def __init__(self, config: AdaptiveAgentConfig | None = None) -> None:
        self.config = config or AdaptiveAgentConfig()

    def adapt(
        self,
        *,
        state: CalibrationState,
        verdicts: tuple[QualityVerdict, ...],
        decisions: tuple[GuardDecision, ...],
        cycle_id: str,
        correlation: CorrelationReport | None = None,
    ) -> tuple[CalibrationState, AdaptationEvent | None]:
        """Apply at most one bounded mutation; return new state + event.

        Decision priority (highest urgency first):

        1. If any decision was REJECTED -> tighten the guard cap (most
           urgent: blast-radius drift).
        2. **(trend-aware)** If a CorrelationReport is supplied and its
           recent-window rejection rate exceeds the proactive threshold,
           tighten the cap even when *this* cycle was clean. Promotes
           the loop from per-cycle adaptive to trend-aware adaptive
           — recurring drift is dampened before the next rejection.
        3. If the cycle ran clean (no rejections) for N cycles -> relax
           the guard cap one step toward the baseline.
        4. If the judge's low-score fraction is far from target, raise
           or lower its threshold.
        5. If the diagnosis-to-proposal acceptance proxy looks off,
           adjust the proposal floor.
        6. Otherwise NO_OP for this cycle.
        """
        # 1. Any rejection in this cycle -> tighten cap
        if any(
            d.outcome is GuardOutcome.REJECTED for d in decisions
        ):
            new_state = state.with_guard_cap_tightened(
                factor=self.config.guard_cap_tighten_factor
            )
            event = self._event(
                cycle_id=cycle_id,
                kind=AdaptationKind.GUARD_BLAST_CAP_TIGHTEN,
                parameter_name="guard_auto_approve_blast_cap",
                previous_value=float(state.guard_auto_approve_blast_cap),
                new_value=float(new_state.guard_auto_approve_blast_cap),
                rationale=(
                    "REJECTED outcome observed; halving guard auto-approve cap "
                    "for the next cycle to dampen blast radius drift"
                ),
            )
            return new_state, event

        # 2. Trend-aware proactive tightening — fires when CorrelationAgent
        #    surfaces a rejection rate above the proactive threshold across
        #    the recent window, EVEN IF this specific cycle was clean.
        #    This is the cross-cycle reflex: the loop adapts to
        #    *trajectory*, not only to instant observations.
        if (
            correlation is not None
            and correlation.rejection_rate
            >= self.config.proactive_tighten_rejection_rate
            and state.guard_auto_approve_blast_cap
            > state.bounds.guard_auto_approve_blast_cap_min
        ):
            new_state = state.with_guard_cap_tightened(
                factor=self.config.guard_cap_tighten_factor
            )
            if (
                new_state.guard_auto_approve_blast_cap
                != state.guard_auto_approve_blast_cap
            ):
                event = self._event(
                    cycle_id=cycle_id,
                    kind=AdaptationKind.GUARD_BLAST_CAP_TIGHTEN,
                    parameter_name="guard_auto_approve_blast_cap",
                    previous_value=float(state.guard_auto_approve_blast_cap),
                    new_value=float(new_state.guard_auto_approve_blast_cap),
                    rationale=(
                        f"correlation reports rejection_rate "
                        f"{correlation.rejection_rate:.2f} over "
                        f"{correlation.cycles_examined} cycles "
                        f"(threshold {self.config.proactive_tighten_rejection_rate:.2f}); "
                        f"proactively halving guard cap"
                    ),
                )
                return new_state, event

        # 3. Sustained clean cycles -> relax cap one step
        if (
            state.cycles_since_last_rejection
            >= self.config.guard_relax_after_clean_cycles
            and state.guard_auto_approve_blast_cap
            < state.bounds.guard_auto_approve_blast_cap_max
        ):
            new_state = state.with_guard_cap_relaxed(
                step=self.config.guard_cap_relax_step
            )
            event = self._event(
                cycle_id=cycle_id,
                kind=AdaptationKind.GUARD_BLAST_CAP_RELAX,
                parameter_name="guard_auto_approve_blast_cap",
                previous_value=float(state.guard_auto_approve_blast_cap),
                new_value=float(new_state.guard_auto_approve_blast_cap),
                rationale=(
                    f"{state.cycles_since_last_rejection} clean cycles since last "
                    f"rejection; relaxing guard cap by "
                    f"{self.config.guard_cap_relax_step} toward baseline"
                ),
            )
            return new_state, event

        # 3. Judge threshold drift toward target low-score fraction
        if verdicts:
            low_count = sum(
                1 for v in verdicts if v.is_low_score(state.judge_low_threshold)
            )
            fraction = low_count / len(verdicts)
            target = self.config.target_low_score_fraction
            if fraction > target + 0.10:
                # Too many low-score samples -> the threshold is too strict;
                # lower it so fewer pass as low.
                new_state = state.with_judge_threshold_lowered(
                    step=self.config.judge_threshold_step
                )
                if new_state.judge_low_threshold != state.judge_low_threshold:
                    event = self._event(
                        cycle_id=cycle_id,
                        kind=AdaptationKind.JUDGE_LOW_THRESHOLD_LOWER,
                        parameter_name="judge_low_threshold",
                        previous_value=state.judge_low_threshold,
                        new_value=new_state.judge_low_threshold,
                        rationale=(
                            f"low-score fraction {fraction:.2f} exceeds "
                            f"target {target:.2f}+0.10; lowering judge "
                            f"threshold by {self.config.judge_threshold_step}"
                        ),
                    )
                    return new_state, event
            if fraction < target - 0.10 and len(verdicts) >= 5:
                new_state = state.with_judge_threshold_raised(
                    step=self.config.judge_threshold_step
                )
                if new_state.judge_low_threshold != state.judge_low_threshold:
                    event = self._event(
                        cycle_id=cycle_id,
                        kind=AdaptationKind.JUDGE_LOW_THRESHOLD_RAISE,
                        parameter_name="judge_low_threshold",
                        previous_value=state.judge_low_threshold,
                        new_value=new_state.judge_low_threshold,
                        rationale=(
                            f"low-score fraction {fraction:.2f} below "
                            f"target {target:.2f}-0.10; raising judge "
                            f"threshold by {self.config.judge_threshold_step}"
                        ),
                    )
                    return new_state, event

        # 4. Proposal floor drift based on auto-approval proxy.
        # Auto-approval rate is a (rough) proxy for "agent confidence is
        # well-calibrated against guard policy." If the rate is high, the
        # floor can come down; if low, the floor should rise.
        if decisions:
            auto = sum(
                1 for d in decisions if d.outcome is GuardOutcome.AUTO_APPROVED
            )
            rate = auto / len(decisions)
            target = self.config.target_proposal_approval_proxy
            if rate < target - 0.20 and len(decisions) >= 2:
                new_state = state.with_proposal_floor_raised(
                    step=self.config.proposal_floor_step
                )
                if (
                    new_state.proposal_high_confidence_floor
                    != state.proposal_high_confidence_floor
                ):
                    event = self._event(
                        cycle_id=cycle_id,
                        kind=AdaptationKind.PROPOSAL_HIGH_CONFIDENCE_FLOOR_RAISE,
                        parameter_name="proposal_high_confidence_floor",
                        previous_value=state.proposal_high_confidence_floor,
                        new_value=new_state.proposal_high_confidence_floor,
                        rationale=(
                            f"auto-approval rate {rate:.2f} below "
                            f"target {target:.2f}-0.20; raising proposal "
                            f"floor to demand stronger confidence"
                        ),
                    )
                    return new_state, event
            if rate > target + 0.20:
                new_state = state.with_proposal_floor_lowered(
                    step=self.config.proposal_floor_step
                )
                if (
                    new_state.proposal_high_confidence_floor
                    != state.proposal_high_confidence_floor
                ):
                    event = self._event(
                        cycle_id=cycle_id,
                        kind=AdaptationKind.PROPOSAL_HIGH_CONFIDENCE_FLOOR_LOWER,
                        parameter_name="proposal_high_confidence_floor",
                        previous_value=state.proposal_high_confidence_floor,
                        new_value=new_state.proposal_high_confidence_floor,
                        rationale=(
                            f"auto-approval rate {rate:.2f} above "
                            f"target {target:.2f}+0.20; lowering proposal "
                            f"floor (room for finer-grained proposals)"
                        ),
                    )
                    return new_state, event

        # 5. NO_OP — no movement this cycle.
        logger.debug(
            "AdaptiveAgent: no adaptation triggered for cycle=%s", cycle_id
        )
        return state, None

    def _event(
        self,
        *,
        cycle_id: str,
        kind: AdaptationKind,
        parameter_name: str,
        previous_value: float,
        new_value: float,
        rationale: str,
    ) -> AdaptationEvent:
        return AdaptationEvent(
            event_id=f"adapt-{uuid.uuid4().hex[:12]}",
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            kind=kind,
            parameter_name=parameter_name,
            previous_value=round(previous_value, 4),
            new_value=round(new_value, 4),
            delta=round(new_value - previous_value, 4),
            rationale=rationale,
        )
