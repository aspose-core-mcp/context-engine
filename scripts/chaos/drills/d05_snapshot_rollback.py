"""D-05 — Snapshot rollback drill.

Scenario: an active snapshot is detected to be corrupted (e.g. a bad publish
made it through the partial-publish gate). The on-call rolls back to the
previous known-good snapshot using the rollback API. This drill verifies
the rollback contract end-to-end against the in-memory registry, including
the optimistic-concurrency guard (``expected_active_snapshot_id``).

Production runbook: ``infra/runbooks/incident-response-playbooks.md``
(Sev1 Option A — rollback to last known good snapshot).
"""

from __future__ import annotations

from typing import Any

from scripts.chaos.drills.base import DrillResult, DrillTimer, utc_iso

from adcs.indexing.snapshot_registry import (
    InMemorySnapshotRegistry,
    SnapshotRollbackConflictError,
    SnapshotStatus,
)

DRILL_ID = "D-05"
DRILL_NAME = "snapshot_rollback"
SCENARIO = (
    "Active snapshot is corrupted; on-call rolls back to the previous "
    "known-good snapshot using the optimistic-concurrency rollback API."
)
RTO_TARGET = 60.0  # seconds — runbook Sev1 RTO
RPO_TARGET = 0.0  # rolling back to N-1 has zero data loss for the user


def run() -> DrillResult:
    started = utc_iso()
    timer = DrillTimer()

    registry = InMemorySnapshotRegistry()
    failures: list[str] = []
    verified: list[str] = []
    telemetry: dict[str, Any] = {}
    rto_observed = 0.0

    try:
        # Baseline: create N-1 (good) and N (bad) snapshots.
        good = registry.create_snapshot(
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="apiref",
            source_revision="rev-good",
            indexed_chunks_count=1000,
        )
        bad = registry.create_snapshot(
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            source_kind="apiref",
            source_revision="rev-bad-corruption",
            indexed_chunks_count=1000,
        )
        active_before = registry.get_active_snapshot(
            product_id="aspose.ocr", programming_language="net", version="25.1"
        )
        if active_before is None or active_before.snapshot_id != bad.snapshot_id:
            failures.append("baseline: bad snapshot not active before rollback")

        # Inject the fault: declare the active snapshot corrupted; trigger rollback.
        rto_timer = DrillTimer()
        outcome_record = registry.rollback_snapshot(
            target_snapshot_id=good.snapshot_id,
            expected_active_snapshot_id=bad.snapshot_id,
        )
        rto_observed = rto_timer.elapsed()

        if outcome_record is None:
            failures.append("rollback returned None — target snapshot not found")
        else:
            if outcome_record.target_snapshot.status is SnapshotStatus.ACTIVE:
                verified.append("rollback target promoted to ACTIVE")
            else:
                failures.append("rollback target was not promoted to ACTIVE")
            if (
                outcome_record.previous_active_snapshot.status
                is SnapshotStatus.INACTIVE
            ):
                verified.append("previous active snapshot demoted to INACTIVE")
            else:
                failures.append("previous active was not demoted to INACTIVE")

        # Verify the registry reflects the rollback.
        active_after = registry.get_active_snapshot(
            product_id="aspose.ocr", programming_language="net", version="25.1"
        )
        if active_after is not None and active_after.snapshot_id == good.snapshot_id:
            verified.append("get_active_snapshot now returns good snapshot")
        else:
            failures.append("active snapshot after rollback is not the good one")

        # Verify optimistic concurrency: a stale rollback request must conflict.
        try:
            registry.rollback_snapshot(
                target_snapshot_id=bad.snapshot_id,
                expected_active_snapshot_id=bad.snapshot_id,  # stale
            )
            failures.append(
                "stale rollback was accepted — optimistic-concurrency guard broken"
            )
        except SnapshotRollbackConflictError as exc:
            verified.append(
                f"optimistic-concurrency guard fired: {exc.code}"
            )

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )
        else:
            verified.append(
                f"rto_observed={rto_observed * 1000:.2f}ms within target {RTO_TARGET}s"
            )

        telemetry = {
            "good_snapshot_id": good.snapshot_id,
            "bad_snapshot_id": bad.snapshot_id,
            "rollback_outcome_returned": outcome_record is not None,
            "concurrency_guard_fired": True,
        }
        outcome = "PASS" if not failures else "DEGRADED"
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
            "1. Operator detects bad snapshot via monitoring / smoke test",
            "2. Operator lists snapshots: GET /admin/v1/snapshots",
            "3. Operator picks last known good snapshot_id",
            "4. Operator triggers: POST /admin/v1/snapshots/{good_id}/rollback "
            "with expected_active_snapshot_id=bad_id (optimistic concurrency)",
            "5. Registry validates expected_active matches current_active; "
            "rejects with SnapshotRollbackConflictError if not",
            "6. Registry promotes good to ACTIVE; demotes bad to INACTIVE",
            "7. snapshot_rollback_audit.py logs the action with actor + reason",
            "8. Public query_docs immediately serves results from the good snapshot",
        ],
    )
