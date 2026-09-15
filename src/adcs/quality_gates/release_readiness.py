"""Release-readiness summary builder for acceptance/perf gates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_release_readiness_summary(
    *,
    evaluation_summary: dict[str, Any],
    perf_summary: dict[str, Any],
    phase: str = "mvp",
) -> dict[str, Any]:
    normalized_phase = _normalize_quality_phase(phase)
    eval_blocking_ok = evaluation_summary.get("blocking_status") == "pass"
    perf_blocking_ok = perf_summary.get("blocking_status") == "pass"
    target_misses = _collect_target_misses(
        evaluation_summary=evaluation_summary,
        perf_summary=perf_summary,
    )

    if normalized_phase == "mvp":
        blocking_status = "pass" if eval_blocking_ok and perf_blocking_ok else "fail"
        target_enforcement = "track_only"
    else:
        blocking_status = (
            "pass"
            if eval_blocking_ok and perf_blocking_ok and not target_misses
            else "fail"
        )
        target_enforcement = "hard_block"

    eval_cases_total = _nested_int(evaluation_summary, "counts", "cases_total")
    perf_profiles = perf_summary.get("profiles", ())
    if not isinstance(perf_profiles, list):
        perf_profiles = []

    sustained_executed = _profile_state(perf_profiles, profile_id="sustained", key="executed")
    burst_executed = _profile_state(perf_profiles, profile_id="burst", key="executed")
    soak_defined = any(
        isinstance(profile, dict) and profile.get("profile_id") == "soak"
        for profile in perf_profiles
    )

    if blocking_status == "pass":
        if normalized_phase == "mvp":
            readiness_status = "ready_for_mvp_tracking"
        elif normalized_phase == "preprod":
            readiness_status = "ready_for_preprod"
        else:
            readiness_status = "ready_for_ga"
    else:
        readiness_status = "blocked"

    checklist = (
        {
            "check_id": "offline_eval_executed",
            "blocking": True,
            "status": "pass" if eval_cases_total > 0 else "fail",
            "details": f"cases_total={eval_cases_total}",
        },
        {
            "check_id": "perf_sustained_profile_executed",
            "blocking": False,
            "status": "pass" if sustained_executed else "warn",
            "details": "target=50_rps",
        },
        {
            "check_id": "perf_burst_profile_executed",
            "blocking": False,
            "status": "pass" if burst_executed else "warn",
            "details": "target=150_rps",
        },
        {
            "check_id": "perf_soak_profile_defined",
            "blocking": False,
            "status": "pass" if soak_defined else "fail",
            "details": "target_duration=12h",
        },
        {
            "check_id": "functional_regressions_blocking_gate",
            "blocking": True,
            "status": "pass" if blocking_status == "pass" else "fail",
            "details": "mvp_blocks_only_functional_regressions",
        },
        {
            "check_id": "quality_and_perf_targets_tracking",
            "blocking": normalized_phase != "mvp",
            "status": (
                "pass"
                if not target_misses
                else ("warn" if normalized_phase == "mvp" else "fail")
            ),
            "details": (
                "thresholds_tracked_not_hard_blocking_in_mvp"
                if normalized_phase == "mvp"
                else "thresholds_are_hard_blocking_in_preprod_or_ga"
            ),
        },
    )

    return {
        "generated_at": _utc_now_iso(),
        "policy": {
            "phase": normalized_phase,
            "target_enforcement": target_enforcement,
            "functional_regressions_are_blocking": True,
        },
        "blocking_status": blocking_status,
        "readiness_status": readiness_status,
        "target_misses": target_misses,
        "checklist": checklist,
    }


def render_release_readiness_human_report(summary: dict[str, Any]) -> str:
    checklist = summary.get("checklist", ())
    if not isinstance(checklist, (tuple, list)):
        checklist = ()
    target_misses = summary.get("target_misses", ())
    if not isinstance(target_misses, (tuple, list)):
        target_misses = ()

    policy = summary.get("policy", {})
    if not isinstance(policy, dict):
        policy = {}
    phase = policy.get("phase", "unknown")
    lines = [
        f"ADCS Release Readiness ({phase})",
        f"generated_at: {summary.get('generated_at', 'unknown')}",
        f"blocking_status: {summary.get('blocking_status', 'unknown')}",
        f"readiness_status: {summary.get('readiness_status', 'unknown')}",
        "checklist:",
    ]
    for check in checklist:
        if not isinstance(check, dict):
            continue
        lines.append(
            f"- {check.get('check_id', 'unknown')}: "
            f"{check.get('status', 'unknown')} "
            f"(blocking={check.get('blocking', False)})"
        )
    if target_misses:
        lines.append(f"target_misses: {', '.join(str(item) for item in target_misses)}")
    return "\n".join(lines) + "\n"


def _nested_int(payload: dict[str, Any], key: str, nested_key: str) -> int:
    nested = payload.get(key, {})
    if not isinstance(nested, dict):
        return 0
    value = nested.get(nested_key)
    if not isinstance(value, int):
        return 0
    return value


def _profile_state(profiles: list[Any], *, profile_id: str, key: str) -> bool:
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if profile.get("profile_id") != profile_id:
            continue
        return bool(profile.get(key, False))
    return False


def _collect_target_misses(
    *, evaluation_summary: dict[str, Any], perf_summary: dict[str, Any]
) -> tuple[str, ...]:
    misses: list[str] = []

    eval_misses = evaluation_summary.get("target_misses", ())
    if isinstance(eval_misses, (tuple, list)):
        misses.extend(str(item) for item in eval_misses)

    perf_misses = perf_summary.get("target_misses", ())
    if isinstance(perf_misses, (tuple, list)):
        misses.extend(str(item) for item in perf_misses)

    return tuple(misses)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _normalize_quality_phase(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"mvp", "preprod", "ga"}:
        return normalized
    msg = "quality phase must be one of: mvp, preprod, ga."
    raise ValueError(msg)
