from __future__ import annotations

import json
from pathlib import Path

from adcs.ops import ObservabilityControlPlane


def test_observability_control_plane_uses_dedicated_canary_policy_file(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "observability.json"
    config_path.write_text(
        json.dumps(
            {
                "drilldown_links": {
                    "grafana_dashboard_url": "https://grafana.example.local/d/adcs-overview",
                },
                "alert_rules": [
                    {
                        "rule_id": "latency-breach",
                        "severity": "critical",
                        "description": "Latency exceeded threshold.",
                        "window_minutes": 10,
                        "threshold": "p95 > 1200ms",
                    }
                ],
                "canary_policy": {
                    "enabled": False,
                    "initial_traffic_pct": 5,
                    "full_traffic_pct": 100,
                    "analysis_window_minutes": 10,
                    "max_error_rate_pct": 2.5,
                    "max_latency_p95_ms": 1500,
                    "auto_rollback": False,
                },
            }
        ),
        encoding="utf-8",
    )
    canary_policy_path = tmp_path / "canary.json"
    canary_policy_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "initial_traffic_pct": 15,
                "full_traffic_pct": 100,
                "analysis_window_minutes": 20,
                "max_error_rate_pct": 0.5,
                "max_latency_p95_ms": 900,
                "auto_rollback": True,
            }
        ),
        encoding="utf-8",
    )
    smoke_report_path = tmp_path / "smoke.json"
    smoke_report_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    canary_report_path = tmp_path / "canary-report.json"
    canary_report_path.write_text(
        json.dumps({"decision": "promote", "reason": "smoke_checks_passed"}),
        encoding="utf-8",
    )

    service = ObservabilityControlPlane(
        config_path=config_path,
        canary_policy_path=canary_policy_path,
        smoke_report_path=smoke_report_path,
        canary_report_path=canary_report_path,
    )

    links = service.load_links(traces_enabled=True)
    alerts = service.load_alert_rules()
    policy = service.load_canary_policy()
    smoke = service.load_smoke_summary()

    assert links.grafana_dashboard_url == "https://grafana.example.local/d/adcs-overview"
    assert len(alerts) == 1
    assert alerts[0].rule_id == "latency-breach"
    assert policy.enabled is True
    assert policy.initial_traffic_pct == 15
    assert policy.max_latency_p95_ms == 900
    assert policy.latest_decision == "promote"
    assert policy.latest_reason == "smoke_checks_passed"
    assert smoke.status == "pass"
