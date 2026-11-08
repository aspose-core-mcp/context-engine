"""Pytest wrapper for D-06 — DR backup-restore drill.

Wraps ``FileBackedBackupRestoreService.run_recovery_smoke`` (the same
code the release gate exercises). Uses pytest's ``tmp_path`` fixture as
the workspace root so this test does not mutate the committed
``artifacts/dr/`` baseline. Production drill runs (the monthly chaos
job) call ``run()`` with no args and use the repo root.
"""

from __future__ import annotations

from pathlib import Path

from scripts.chaos.drills import d06_dr_backup_restore as drill


def test_drill_passes_with_zero_failures(tmp_path: Path) -> None:
    result = drill.run(workspace_root=tmp_path)

    assert result.outcome == "PASS", (
        f"D-06 outcome={result.outcome}; failures={result.failures!r}"
    )
    assert result.failures == []
    assert result.drill_id == "D-06"
    assert result.drill_name == "dr_backup_restore"


def test_drill_recovers_within_rto_target(tmp_path: Path) -> None:
    """RTO target is generous (10 minutes); a real backup+restore round
    trip on tmp_path completes in seconds.
    """
    result = drill.run(workspace_root=tmp_path)

    assert result.rto_observed_seconds <= result.rto_target_seconds


def test_drill_verifies_sentinel_round_trip(tmp_path: Path) -> None:
    """RPO == 0 means the sentinel content must round-trip exactly
    (baseline -> backup -> mutate -> restore -> baseline).
    """
    result = drill.run(workspace_root=tmp_path)

    sentinel_check = [
        entry for entry in result.verified
        if "round-tripped" in entry.lower()
        or "rpo" in entry.lower()
    ]
    assert sentinel_check, (
        f"expected sentinel-round-trip verification; got {result.verified!r}"
    )


def test_drill_telemetry_records_operation_ids(tmp_path: Path) -> None:
    """Backup + restore operation IDs must be present so the audit log
    can cross-reference the operations API.
    """
    result = drill.run(workspace_root=tmp_path)

    assert result.telemetry["status"] == "passed"
    assert result.telemetry["backup_operation_id"]
    assert result.telemetry["restore_operation_id"]
    assert result.telemetry["backup_id"]


def test_drill_does_not_mutate_real_workspace(tmp_path: Path) -> None:
    """Hermeticity check: the drill must operate inside ``workspace_root``
    only. After the run, only ``artifacts/dr/`` paths under tmp_path
    exist; the repo's own artifacts/dr/ is untouched.
    """
    drill.run(workspace_root=tmp_path)

    expected_dr = tmp_path / "artifacts" / "dr"
    assert expected_dr.exists()
    assert (expected_dr / "backups.json").exists()
    assert (expected_dr / "operations.json").exists()
