"""Admin endpoints for the quality-loop calibration surface.

Exposes the current :class:`CalibrationState` and the last N
:class:`AdaptationEvent` records from the committed JSONL audit log
so an operator can visually inspect drift across cycles and decide
whether to widen / tighten bounds, pause adaptation, or roll back
the calibration to a prior snapshot.

The endpoints are read-only — they expose state, they never mutate
it. Mutation of the live calibration state happens only through the
AdaptiveAgent inside a running cycle, and only within hard bounds.
The admin UI surfaces what's there; humans review.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from adcs.api.admin_auth import require_admin_principal

router = APIRouter(
    prefix="/v1/admin/quality-loop",
    tags=["admin-quality-loop"],
    dependencies=[Depends(require_admin_principal)],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CalibrationStateResponse(BaseModel):
    """Current calibration state (subset of CalibrationState)."""

    judge_low_threshold: float
    diagnosis_min_low_ratio: float
    proposal_high_confidence_floor: float
    guard_auto_approve_blast_cap: int
    cycle_count: int
    cycles_since_last_rejection: int


class CalibrationBoundsResponse(BaseModel):
    """Hard min/max bounds the AdaptiveAgent cannot exceed."""

    judge_low_threshold_min: float
    judge_low_threshold_max: float
    diagnosis_min_low_ratio_min: float
    diagnosis_min_low_ratio_max: float
    proposal_high_confidence_floor_min: float
    proposal_high_confidence_floor_max: float
    guard_auto_approve_blast_cap_min: int
    guard_auto_approve_blast_cap_max: int


class AdaptationEventResponse(BaseModel):
    """One AdaptationEvent record extracted from the JSONL audit log."""

    event_id: str
    cycle_id: str
    emitted_at: str
    kind: str
    parameter_name: str
    previous_value: float
    new_value: float
    delta: float
    rationale: str


class CalibrationDriftResponse(BaseModel):
    """Composite payload the admin UI fetches in one round-trip."""

    state: CalibrationStateResponse
    bounds: CalibrationBoundsResponse
    recent_adaptations: list[AdaptationEventResponse]
    recent_adaptation_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _QualityLoopArtifacts:
    """Disk locations the endpoint reads from."""

    calibration_state_path: Path
    audit_log_path: Path


def _artifacts() -> _QualityLoopArtifacts:
    """Resolve the quality-loop artefact paths from env, with safe defaults.

    Overridable via ``ADCS_QUALITY_LOOP_REPORTS_DIR`` so tests can point
    the endpoint at an isolated tmpdir; the default
    ``reports/quality-loop/`` matches the layout the Coordinator writes.
    """
    base = Path(
        os.environ.get("ADCS_QUALITY_LOOP_REPORTS_DIR", "reports/quality-loop")
    )
    return _QualityLoopArtifacts(
        calibration_state_path=base / "calibration-state.json",
        audit_log_path=base / "audit-log.jsonl",
    )


def _read_calibration_state(path: Path) -> dict[str, Any]:
    """Read calibration-state.json. Missing file → defaults."""
    if not path.exists():
        return {
            "judge_low_threshold": 0.70,
            "diagnosis_min_low_ratio": 0.40,
            "proposal_high_confidence_floor": 0.85,
            "guard_auto_approve_blast_cap": 100,
            "cycle_count": 0,
            "cycles_since_last_rejection": 0,
            "bounds": {
                "judge_low_threshold_min": 0.50,
                "judge_low_threshold_max": 0.85,
                "diagnosis_min_low_ratio_min": 0.20,
                "diagnosis_min_low_ratio_max": 0.70,
                "proposal_high_confidence_floor_min": 0.70,
                "proposal_high_confidence_floor_max": 0.95,
                "guard_auto_approve_blast_cap_min": 25,
                "guard_auto_approve_blast_cap_max": 500,
            },
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_recent_adaptations(
    audit_log_path: Path, *, limit: int
) -> list[dict[str, Any]]:
    """Scan the JSONL audit log; return the last N AdaptationEvent rows.

    The audit log is append-only with one JSON object per line. We only
    parse rows tagged ``message_type == "AdaptationEvent"``. Malformed
    lines (mid-write or corrupted) are silently skipped — one bad row
    must not break the endpoint.
    """
    if not audit_log_path.exists():
        return []
    found: list[dict[str, Any]] = []
    with audit_log_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = payload.get("message_type") or payload.get("topic")
            if kind == "AdaptationEvent" or payload.get("event_id", "").startswith(
                "adapt-"
            ):
                found.append(payload)
    return found[-limit:] if limit > 0 else found


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/calibration", response_model=CalibrationDriftResponse)
async def get_calibration_drift(
    limit: int = Query(default=50, ge=1, le=500),
) -> CalibrationDriftResponse:
    """Return the current calibration state + the last N adaptation events.

    Used by the admin UI's Quality-Loop Calibration page to visualise
    drift across cycles. Read-only — operators inspect; they do not
    mutate state through this endpoint.
    """
    arts = _artifacts()
    try:
        raw_state = _read_calibration_state(arts.calibration_state_path)
        recent = _scan_recent_adaptations(arts.audit_log_path, limit=limit)
    except OSError as exc:  # filesystem error
        raise HTTPException(
            status_code=503,
            detail=f"quality-loop artefacts unavailable: {exc}",
        ) from exc

    bounds = raw_state.get("bounds", {})
    state = CalibrationStateResponse(
        judge_low_threshold=float(raw_state["judge_low_threshold"]),
        diagnosis_min_low_ratio=float(raw_state["diagnosis_min_low_ratio"]),
        proposal_high_confidence_floor=float(
            raw_state["proposal_high_confidence_floor"]
        ),
        guard_auto_approve_blast_cap=int(raw_state["guard_auto_approve_blast_cap"]),
        cycle_count=int(raw_state.get("cycle_count", 0)),
        cycles_since_last_rejection=int(
            raw_state.get("cycles_since_last_rejection", 0)
        ),
    )
    bounds_response = CalibrationBoundsResponse(
        judge_low_threshold_min=float(bounds.get("judge_low_threshold_min", 0.50)),
        judge_low_threshold_max=float(bounds.get("judge_low_threshold_max", 0.85)),
        diagnosis_min_low_ratio_min=float(
            bounds.get("diagnosis_min_low_ratio_min", 0.20)
        ),
        diagnosis_min_low_ratio_max=float(
            bounds.get("diagnosis_min_low_ratio_max", 0.70)
        ),
        proposal_high_confidence_floor_min=float(
            bounds.get("proposal_high_confidence_floor_min", 0.70)
        ),
        proposal_high_confidence_floor_max=float(
            bounds.get("proposal_high_confidence_floor_max", 0.95)
        ),
        guard_auto_approve_blast_cap_min=int(
            bounds.get("guard_auto_approve_blast_cap_min", 25)
        ),
        guard_auto_approve_blast_cap_max=int(
            bounds.get("guard_auto_approve_blast_cap_max", 500)
        ),
    )
    adaptations: list[AdaptationEventResponse] = []
    for row in recent:
        try:
            adaptations.append(
                AdaptationEventResponse(
                    event_id=row["event_id"],
                    cycle_id=row["cycle_id"],
                    emitted_at=row["emitted_at"],
                    kind=row.get("kind", ""),
                    parameter_name=row.get("parameter_name", ""),
                    previous_value=float(row.get("previous_value", 0.0)),
                    new_value=float(row.get("new_value", 0.0)),
                    delta=float(row.get("delta", 0.0)),
                    rationale=row.get("rationale", ""),
                )
            )
        except (KeyError, ValueError, TypeError):
            # Skip incomplete rows; the audit log is append-only and may
            # contain partial writes during an in-progress cycle.
            continue

    return CalibrationDriftResponse(
        state=state,
        bounds=bounds_response,
        recent_adaptations=adaptations,
        recent_adaptation_count=len(adaptations),
    )
