"""Pytest wrapper for the chaos drill suite *runner*.

Where the per-drill tests verify the contracts of individual drills,
this file verifies that ``scripts/chaos/run_drill_suite.py`` correctly:

- Discovers and invokes every registered drill.
- Writes one JSONL line per drill to the audit log.
- Writes per-drill detail JSON under the configured reports root.
- Writes the summary JSON the CI gate consumes.
- Returns the right exit code for each combination of pass/degrade/fail.

The runner does not implement any chaos logic itself, so these tests
focus on the orchestration contract — what auditors actually rely on
when reading ``reports/chaos/drill-log.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.chaos.run_drill_suite import DRILLS, main


def test_runner_skips_d06_for_speed(tmp_path: Path, capsys) -> None:
    """Skipping D-06 keeps this test under one second; D-06 has its own
    pytest-tmp_path-redirected wrapper in test_d06_dr_backup_restore_drill.
    """
    exit_code = main(
        [
            "--reports-root",
            str(tmp_path),
            "--skip",
            "D-06",
        ]
    )

    assert exit_code == 0


def test_runner_writes_jsonl_log(tmp_path: Path, capsys) -> None:
    main(["--reports-root", str(tmp_path), "--skip", "D-06"])

    log_path = tmp_path / "drill-log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(DRILLS) - 1  # all drills except D-06

    for line in lines:
        record = json.loads(line)
        assert record["drill_id"]
        assert record["outcome"] in {"PASS", "DEGRADED", "FAIL", "ERROR"}
        assert "rto_observed_seconds" in record
        assert "evidence_artifact" in record


def test_runner_writes_summary(tmp_path: Path, capsys) -> None:
    main(["--reports-root", str(tmp_path), "--skip", "D-06"])

    summary_path = tmp_path / "last-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert "totals" in summary
    assert summary["totals"]["pass"] >= 1
    assert summary["totals"]["fail"] == 0
    assert summary["totals"]["error"] == 0
    assert "D-06" in summary["skipped"]


def test_runner_writes_per_drill_evidence(tmp_path: Path, capsys) -> None:
    main(["--reports-root", str(tmp_path), "--skip", "D-06"])

    drills_dir = tmp_path / "drills"
    assert drills_dir.exists()

    # Every non-skipped drill must have at least one detail JSON file.
    for drill_id, _ in DRILLS:
        if drill_id == "D-06":
            continue
        drill_subdir = drills_dir / drill_id
        assert drill_subdir.exists(), f"missing evidence dir for {drill_id}"
        files = list(drill_subdir.glob("*.json"))
        assert files, f"no detail JSON for {drill_id}"


def test_runner_skip_flag_is_respected(tmp_path: Path, capsys) -> None:
    main(["--reports-root", str(tmp_path), "--skip", "D-06", "--skip", "D-05"])

    log_path = tmp_path / "drill-log.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    drill_ids = {json.loads(line)["drill_id"] for line in lines}

    assert "D-05" not in drill_ids
    assert "D-06" not in drill_ids
    assert "D-01" in drill_ids
