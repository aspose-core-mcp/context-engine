"""Adaptive calibration state — the single source of truth for tunable agent
parameters that the :class:`AdaptiveAgent` is permitted to mutate.

The calibration state is persisted to ``reports/quality-loop/calibration-state.json``  # noqa: E501
between cycles so adaptation accumulates over time. Every mutation is
bounded (hard min/max), rate-limited (one mutation kind per cycle), and
recorded as an :class:`AdaptationEvent` in the audit log.

This file makes the adaptation claim falsifiable: the trajectory
of the calibration state across cycles is auditable, the bounds are
testable, and any mutation outside the bounded interval is a bug.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CalibrationBounds:
    """Hard min/max for each tunable. Anything outside is a bug."""

    judge_low_threshold_min: float = 0.50
    judge_low_threshold_max: float = 0.85
    diagnosis_min_low_ratio_min: float = 0.20
    diagnosis_min_low_ratio_max: float = 0.70
    proposal_high_confidence_floor_min: float = 0.70
    proposal_high_confidence_floor_max: float = 0.95
    guard_auto_approve_blast_cap_min: int = 25
    guard_auto_approve_blast_cap_max: int = 500


@dataclass(frozen=True, slots=True)
class CalibrationState:
    """Tunable parameters the AdaptiveAgent reads + mutates.

    Defaults match the agents' static configs; the AdaptiveAgent's job is
    to drift these slowly within bounds based on observed cycle outcomes.
    """

    judge_low_threshold: float = 0.70
    diagnosis_min_low_ratio: float = 0.40
    proposal_high_confidence_floor: float = 0.85
    guard_auto_approve_blast_cap: int = 100
    cycle_count: int = 0
    cycles_since_last_rejection: int = 0
    bounds: CalibrationBounds = field(default_factory=CalibrationBounds)

    # ---- I/O ----------------------------------------------------------------

    @classmethod
    def load_or_default(cls, path: Path) -> CalibrationState:
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.from_dict(payload)

    def persist(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_low_threshold": round(self.judge_low_threshold, 4),
            "diagnosis_min_low_ratio": round(self.diagnosis_min_low_ratio, 4),
            "proposal_high_confidence_floor": round(
                self.proposal_high_confidence_floor, 4
            ),
            "guard_auto_approve_blast_cap": int(self.guard_auto_approve_blast_cap),
            "cycle_count": int(self.cycle_count),
            "cycles_since_last_rejection": int(self.cycles_since_last_rejection),
            "bounds": asdict(self.bounds),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CalibrationState:
        bounds_payload = payload.get("bounds") or {}
        bounds = CalibrationBounds(**bounds_payload) if bounds_payload else CalibrationBounds()
        state = cls(
            judge_low_threshold=float(payload.get("judge_low_threshold", 0.70)),
            diagnosis_min_low_ratio=float(payload.get("diagnosis_min_low_ratio", 0.40)),
            proposal_high_confidence_floor=float(
                payload.get("proposal_high_confidence_floor", 0.85)
            ),
            guard_auto_approve_blast_cap=int(
                payload.get("guard_auto_approve_blast_cap", 100)
            ),
            cycle_count=int(payload.get("cycle_count", 0)),
            cycles_since_last_rejection=int(
                payload.get("cycles_since_last_rejection", 0)
            ),
            bounds=bounds,
        )
        return _clamp_to_bounds(state)

    # ---- Bounded mutators ---------------------------------------------------

    def with_judge_threshold_raised(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(self, judge_low_threshold=self.judge_low_threshold + abs(step))
        )

    def with_judge_threshold_lowered(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(self, judge_low_threshold=self.judge_low_threshold - abs(step))
        )

    def with_diagnosis_ratio_raised(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(self, diagnosis_min_low_ratio=self.diagnosis_min_low_ratio + abs(step))
        )

    def with_diagnosis_ratio_lowered(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(self, diagnosis_min_low_ratio=self.diagnosis_min_low_ratio - abs(step))
        )

    def with_proposal_floor_raised(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(
                self,
                proposal_high_confidence_floor=self.proposal_high_confidence_floor
                + abs(step),
            )
        )

    def with_proposal_floor_lowered(self, *, step: float) -> CalibrationState:
        return _clamp_to_bounds(
            replace(
                self,
                proposal_high_confidence_floor=self.proposal_high_confidence_floor
                - abs(step),
            )
        )

    def with_guard_cap_tightened(self, *, factor: float) -> CalibrationState:
        new_cap = int(self.guard_auto_approve_blast_cap * factor)
        return _clamp_to_bounds(replace(self, guard_auto_approve_blast_cap=new_cap))

    def with_guard_cap_relaxed(self, *, step: int) -> CalibrationState:
        new_cap = self.guard_auto_approve_blast_cap + abs(step)
        return _clamp_to_bounds(replace(self, guard_auto_approve_blast_cap=new_cap))

    # ---- Cycle bookkeeping --------------------------------------------------

    def with_cycle_completed(self, *, had_rejection: bool) -> CalibrationState:
        return replace(
            self,
            cycle_count=self.cycle_count + 1,
            cycles_since_last_rejection=(
                0 if had_rejection else self.cycles_since_last_rejection + 1
            ),
        )


def _clamp_to_bounds(state: CalibrationState) -> CalibrationState:
    b = state.bounds
    return replace(
        state,
        judge_low_threshold=_clip(
            state.judge_low_threshold,
            b.judge_low_threshold_min,
            b.judge_low_threshold_max,
        ),
        diagnosis_min_low_ratio=_clip(
            state.diagnosis_min_low_ratio,
            b.diagnosis_min_low_ratio_min,
            b.diagnosis_min_low_ratio_max,
        ),
        proposal_high_confidence_floor=_clip(
            state.proposal_high_confidence_floor,
            b.proposal_high_confidence_floor_min,
            b.proposal_high_confidence_floor_max,
        ),
        guard_auto_approve_blast_cap=int(
            _clip(
                state.guard_auto_approve_blast_cap,
                b.guard_auto_approve_blast_cap_min,
                b.guard_auto_approve_blast_cap_max,
            )
        ),
    )


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
