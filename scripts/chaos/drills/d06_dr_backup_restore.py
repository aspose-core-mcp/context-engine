"""D-06 — DR backup-restore drill.

Wraps the existing ``FileBackedBackupRestoreService.run_recovery_smoke``
(which is the same code path exercised by
``scripts/checks/k8s/run_dr_recovery_smoke.py`` for the release gate) into
the chaos-drill schema.

The smoke:

1. Writes a sentinel file under ``artifacts/semantic-review/``.
2. Triggers a full control-plane backup.
3. Mutates the sentinel.
4. Triggers a restore from the backup just taken.
5. Verifies the sentinel reverts to its pre-mutation content.

If any stage fails or the sentinel diverges, RTO is technically infinite
(no recovery happened) so the drill outcome is FAIL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.chaos.drills.base import DrillResult, DrillTimer, utc_iso

from adcs.ops import DRSmokeStatus, FileBackedBackupRestoreService

DRILL_ID = "D-06"
DRILL_NAME = "dr_backup_restore"
SCENARIO = (
    "Disaster — control-plane state is destroyed and must be restored from "
    "backup. Drill exercises the same backup -> mutate -> restore -> verify "
    "loop the release gate uses (FileBackedBackupRestoreService.run_recovery_smoke)."  # noqa: E501
)
RTO_TARGET = 600.0  # 10 minutes — generous for a full backup+restore cycle
RPO_TARGET = 0.0  # zero data loss; sentinel must round-trip exactly


def run(*, workspace_root: Path | None = None) -> DrillResult:
    """Run the DR backup-restore drill.

    ``workspace_root`` lets pytest tests redirect the drill to a tmp_path so
    they don't mutate the committed ``artifacts/dr/`` baseline. Production
    suite invocations (``run_drill_suite.py``) call ``run()`` with no args
    and the service defaults to the repo root.
    """
    started = utc_iso()
    timer = DrillTimer()
    failures: list[str] = []
    verified: list[str] = []
    telemetry: dict[str, Any] = {}
    rto_observed = 0.0

    try:
        service = FileBackedBackupRestoreService(workspace_root=workspace_root)
        rto_timer = DrillTimer()
        result = service.run_recovery_smoke(
            requested_by="chaos-drill-d06",
            request_id="chaos-drill-d06",
            reason="chaos_drill_dr_backup_restore",
        )
        rto_observed = rto_timer.elapsed()

        telemetry = {
            "status": result.status.value,
            "backup_operation_id": result.backup_operation_id,
            "restore_operation_id": result.restore_operation_id,
            "backup_id": result.backup_id,
            "details": result.details,
        }

        if result.status is DRSmokeStatus.PASSED:
            verified.append("backup operation completed")
            verified.append("restore operation completed")
            verified.append("sentinel content round-tripped (RPO == 0)")
        else:
            failures.append(
                f"DR smoke status={result.status.value} — details: {result.details}"
            )

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )
        else:
            verified.append(
                f"rto_observed={rto_observed:.2f}s within target {RTO_TARGET}s"
            )

        outcome = "PASS" if not failures else (
            "FAIL" if result.status is not DRSmokeStatus.PASSED else "DEGRADED"
        )
    except Exception as exc:
        failures.append(f"drill raised: {exc!r}")
        outcome = "ERROR"
        rto_observed = timer.elapsed()

    completed = utc_iso()
    duration = timer.elapsed()

    return DrillResult(
        drill_id=DRILL_ID,
        drill_name=DRILL_NAME,
        scenario=SCENARIO,
        started_at=started,
        completed_at=completed,
        duration_seconds=round(duration, 4),
        rto_target_seconds=RTO_TARGET,
        rto_observed_seconds=round(rto_observed, 4),
        rpo_target_seconds=RPO_TARGET,
        rpo_observed_seconds=0.0,
        outcome=outcome,
        verified=verified,
        failures=failures,
        telemetry=telemetry,
        recovery_steps=[
            "1. trigger_backup(scope='full') — captures artifacts/* + reports/quality-gates/*",
            "2. Backup operation reaches BackupOperationStatus.COMPLETED",
            "3. Mutate sentinel file (simulates data loss)",
            "4. trigger_restore(backup_id, validate_only=False)",
            "5. Restore operation reaches BackupOperationStatus.COMPLETED",
            "6. Verify sentinel matches baseline content (RPO check)",
            "7. If any stage fails → DRSmokeResult.status = FAILED, release gate blocks",
        ],
    )
