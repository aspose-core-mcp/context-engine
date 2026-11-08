from __future__ import annotations

from adcs.quality_gates.go_no_go import build_go_no_go_summary


def test_go_no_go_summary_passes_when_all_gates_are_green() -> None:
    summary = build_go_no_go_summary(
        phase="preprod",
        evaluation_summary={"blocking_status": "pass"},
        perf_summary={"blocking_status": "pass"},
        release_readiness_summary={"blocking_status": "pass", "readiness_status": "ready"},
        dr_smoke_summary={"status": "passed"},
        helm_packaging_summary={"status": "pass"},
    )

    assert summary["decision"] == "go"
    assert summary["blocking_status"] == "pass"
    assert summary["failed_checks"] == ()


def test_go_no_go_summary_fails_when_any_gate_fails() -> None:
    summary = build_go_no_go_summary(
        phase="preprod",
        evaluation_summary={"blocking_status": "pass"},
        perf_summary={"blocking_status": "fail"},
        release_readiness_summary={"blocking_status": "pass", "readiness_status": "ready"},
        dr_smoke_summary={"status": "failed"},
        helm_packaging_summary={"status": "pass"},
    )

    assert summary["decision"] == "no-go"
    assert summary["blocking_status"] == "fail"
    assert "perf_blocking_status" in summary["failed_checks"]
    assert "dr_recovery_smoke" in summary["failed_checks"]
