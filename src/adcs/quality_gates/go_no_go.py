"""Unified release go/no-go gate summary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_go_no_go_summary(
    *,
    phase: str,
    evaluation_summary: dict[str, Any],
    perf_summary: dict[str, Any],
    release_readiness_summary: dict[str, Any],
    dr_smoke_summary: dict[str, Any],
    helm_packaging_summary: dict[str, Any],
) -> dict[str, Any]:
    normalized_phase = _normalize_quality_phase(phase)

    checks = [
        _check_result(
            check_id="evaluation_blocking_status",
            status=_status_from_blocking(evaluation_summary.get("blocking_status")),
            details=f"blocking_status={evaluation_summary.get('blocking_status', 'unknown')}",
        ),
        _check_result(
            check_id="perf_blocking_status",
            status=_status_from_blocking(perf_summary.get("blocking_status")),
            details=f"blocking_status={perf_summary.get('blocking_status', 'unknown')}",
        ),
        _check_result(
            check_id="release_readiness_blocking_status",
            status=_status_from_blocking(release_readiness_summary.get("blocking_status")),
            details=(
                f"blocking_status={release_readiness_summary.get('blocking_status', 'unknown')}; "
                f"readiness_status={release_readiness_summary.get('readiness_status', 'unknown')}"
            ),
        ),
        _check_result(
            check_id="dr_recovery_smoke",
            status=(
                "pass"
                if str(dr_smoke_summary.get("status", "")).casefold() == "passed"
                else "fail"
            ),
            details=f"status={dr_smoke_summary.get('status', 'unknown')}",
        ),
        _check_result(
            check_id="k8s_helm_packaging",
            status=(
                "pass"
                if str(helm_packaging_summary.get("status", "")).casefold() == "pass"
                else "fail"
            ),
            details=f"status={helm_packaging_summary.get('status', 'unknown')}",
        ),
    ]

    blocking_fails = tuple(item["check_id"] for item in checks if item["status"] == "fail")
    decision = "go" if not blocking_fails else "no-go"

    return {
        "generated_at": _utc_now_iso(),
        "phase": normalized_phase,
        "decision": decision,
        "blocking_status": "pass" if decision == "go" else "fail",
        "failed_checks": blocking_fails,
        "checks": checks,
    }


def render_go_no_go_human_report(summary: dict[str, Any]) -> str:
    checks = summary.get("checks", [])
    if not isinstance(checks, list):
        checks = []

    lines = [
        f"ADCS Release Go/No-Go ({summary.get('phase', 'unknown')})",
        f"generated_at: {summary.get('generated_at', 'unknown')}",
        f"decision: {summary.get('decision', 'unknown')}",
        f"blocking_status: {summary.get('blocking_status', 'unknown')}",
        "checks:",
    ]

    for item in checks:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('check_id', 'unknown')}: {item.get('status', 'unknown')} "
            f"({item.get('details', '')})"
        )

    failed_checks = summary.get("failed_checks", ())
    if isinstance(failed_checks, (tuple, list)) and failed_checks:
        lines.append(f"failed_checks: {', '.join(str(item) for item in failed_checks)}")

    return "\n".join(lines) + "\n"


def _status_from_blocking(raw: object) -> str:
    return "pass" if str(raw).casefold() == "pass" else "fail"


def _check_result(*, check_id: str, status: str, details: str) -> dict[str, str]:
    normalized_status = "pass" if status == "pass" else "fail"
    return {
        "check_id": check_id,
        "status": normalized_status,
        "details": details,
    }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _normalize_quality_phase(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"mvp", "preprod", "ga"}:
        return normalized
    msg = "quality phase must be one of: mvp, preprod, ga."
    raise ValueError(msg)
