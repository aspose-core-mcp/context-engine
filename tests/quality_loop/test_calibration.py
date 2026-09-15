"""Unit tests for CalibrationState — bounds, mutators, persistence."""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import CalibrationBounds, CalibrationState


def test_default_state_within_bounds() -> None:
    state = CalibrationState()
    b = state.bounds
    assert (
        b.judge_low_threshold_min
        <= state.judge_low_threshold
        <= b.judge_low_threshold_max
    )
    assert (
        b.diagnosis_min_low_ratio_min
        <= state.diagnosis_min_low_ratio
        <= b.diagnosis_min_low_ratio_max
    )
    assert (
        b.proposal_high_confidence_floor_min
        <= state.proposal_high_confidence_floor
        <= b.proposal_high_confidence_floor_max
    )
    assert (
        b.guard_auto_approve_blast_cap_min
        <= state.guard_auto_approve_blast_cap
        <= b.guard_auto_approve_blast_cap_max
    )


def test_judge_threshold_raise_capped_at_max() -> None:
    state = CalibrationState(judge_low_threshold=0.84)
    new_state = state.with_judge_threshold_raised(step=0.10)
    assert new_state.judge_low_threshold == state.bounds.judge_low_threshold_max


def test_judge_threshold_lower_capped_at_min() -> None:
    state = CalibrationState(judge_low_threshold=0.55)
    new_state = state.with_judge_threshold_lowered(step=0.20)
    assert new_state.judge_low_threshold == state.bounds.judge_low_threshold_min


def test_guard_cap_tighten_halves_value() -> None:
    state = CalibrationState(guard_auto_approve_blast_cap=200)
    new_state = state.with_guard_cap_tightened(factor=0.5)
    assert new_state.guard_auto_approve_blast_cap == 100


def test_guard_cap_tighten_clamps_to_floor() -> None:
    state = CalibrationState(guard_auto_approve_blast_cap=30)
    new_state = state.with_guard_cap_tightened(factor=0.1)
    assert (
        new_state.guard_auto_approve_blast_cap
        == state.bounds.guard_auto_approve_blast_cap_min
    )


def test_guard_cap_relax_clamps_to_ceiling() -> None:
    state = CalibrationState(guard_auto_approve_blast_cap=495)
    new_state = state.with_guard_cap_relaxed(step=20)
    assert (
        new_state.guard_auto_approve_blast_cap
        == state.bounds.guard_auto_approve_blast_cap_max
    )


def test_proposal_floor_raise_capped_at_max() -> None:
    state = CalibrationState(proposal_high_confidence_floor=0.94)
    new_state = state.with_proposal_floor_raised(step=0.05)
    assert (
        new_state.proposal_high_confidence_floor
        == state.bounds.proposal_high_confidence_floor_max
    )


def test_diagnosis_ratio_lower_capped_at_min() -> None:
    state = CalibrationState(diagnosis_min_low_ratio=0.22)
    new_state = state.with_diagnosis_ratio_lowered(step=0.10)
    assert (
        new_state.diagnosis_min_low_ratio
        == state.bounds.diagnosis_min_low_ratio_min
    )


def test_cycle_completed_increments_counters_no_rejection() -> None:
    state = CalibrationState(cycle_count=2, cycles_since_last_rejection=2)
    new_state = state.with_cycle_completed(had_rejection=False)
    assert new_state.cycle_count == 3
    assert new_state.cycles_since_last_rejection == 3


def test_cycle_completed_resets_clean_streak_on_rejection() -> None:
    state = CalibrationState(cycle_count=10, cycles_since_last_rejection=8)
    new_state = state.with_cycle_completed(had_rejection=True)
    assert new_state.cycle_count == 11
    assert new_state.cycles_since_last_rejection == 0


def test_persist_and_reload_round_trip(tmp_path: Path) -> None:
    state = CalibrationState(
        judge_low_threshold=0.78,
        diagnosis_min_low_ratio=0.55,
        proposal_high_confidence_floor=0.92,
        guard_auto_approve_blast_cap=137,
        cycle_count=42,
        cycles_since_last_rejection=7,
    )
    path = tmp_path / "calibration.json"
    state.persist(path)
    loaded = CalibrationState.load_or_default(path)

    assert loaded.judge_low_threshold == state.judge_low_threshold
    assert loaded.diagnosis_min_low_ratio == state.diagnosis_min_low_ratio
    assert (
        loaded.proposal_high_confidence_floor
        == state.proposal_high_confidence_floor
    )
    assert loaded.guard_auto_approve_blast_cap == state.guard_auto_approve_blast_cap
    assert loaded.cycle_count == state.cycle_count
    assert loaded.cycles_since_last_rejection == state.cycles_since_last_rejection


def test_load_or_default_returns_default_for_missing_file(tmp_path: Path) -> None:
    state = CalibrationState.load_or_default(tmp_path / "nonexistent.json")
    assert state == CalibrationState()


def test_load_or_default_returns_default_for_unparsable(tmp_path: Path) -> None:
    path = tmp_path / "garbage.json"
    path.write_text("not json", encoding="utf-8")
    state = CalibrationState.load_or_default(path)
    assert state == CalibrationState()


def test_persisted_file_is_machine_readable_json(tmp_path: Path) -> None:
    state = CalibrationState()
    path = tmp_path / "calibration.json"
    state.persist(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "judge_low_threshold" in payload
    assert "bounds" in payload
    assert payload["cycle_count"] == 0


def test_loading_state_outside_bounds_clamps_back_in() -> None:
    """Defensive: if a corrupted file claims out-of-bounds values, loader clamps."""
    payload = {
        "judge_low_threshold": 999.0,
        "guard_auto_approve_blast_cap": 1_000_000,
    }
    state = CalibrationState.from_dict(payload)
    b = CalibrationBounds()
    assert state.judge_low_threshold == b.judge_low_threshold_max
    assert state.guard_auto_approve_blast_cap == b.guard_auto_approve_blast_cap_max
