"""Pytest wrappers around the chaos / DR fault-injection drills.

The drill modules under ``scripts/chaos/drills/`` are the source of truth —
they exercise real degraded-mode code paths in ``HybridRetriever``,
``InMemorySnapshotRegistry``, and ``FileBackedBackupRestoreService``. These
pytest tests guard against regressions on every ``make test`` run, so a
broken degraded-mode contract fails the standard CI pipeline rather than
waiting for the monthly chaos schedule.

Each test file mirrors one drill and asserts:

- ``result.outcome == "PASS"``
- ``result.failures`` is empty
- ``result.verified`` contains the runbook-derived contract checks
- ``result.rto_observed_seconds <= result.rto_target_seconds``
"""
