from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_admin_observability_summary_reports_mcp_and_abuse_guard_metrics() -> None:
    app = create_app()
    metrics = app.state.metrics
    metrics.observe_mcp_negotiation(
        requested_revision="2020-01-01",
        negotiated_revision="2025-11-25",
        fallback_reason="unknown_revision",
        fallback_applied=True,
    )
    metrics.observe_mcp_negotiation(
        requested_revision="2025-11-25",
        negotiated_revision="2025-11-25",
        fallback_reason="none",
        fallback_applied=False,
    )
    metrics.observe_abuse_guard_decision(mode="observe_only", decision="allowed")
    metrics.observe_abuse_guard_decision(
        mode="observe_only",
        decision="threshold_exceeded_observe_only",
    )

    with TestClient(app) as client:
        response = client.get("/admin/v1/observability/summary", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["mcp_negotiation_total"] == 2
    assert payload["mcp_negotiation_fallback_total"] == 1
    assert payload["mcp_fallback_by_reason"]["unknown_revision"] == 1
    assert payload["mcp_sessions_by_revision"]["2025-11-25"] == 2
    assert payload["abuse_guard_decisions_by_mode"]["observe_only"]["allowed"] == 1
    assert (
        payload["abuse_guard_decisions_by_mode"]["observe_only"][
            "threshold_exceeded_observe_only"
        ]
        == 1
    )
    assert payload["abuse_guard_settings"]["mode"] in {"observe-only", "enforce"}
    assert payload["trace_policy"]["enabled"] is False
    assert payload["trace_policy"]["backend"] == "disabled"
    assert payload["trace_policy"]["service_name"] == "adcs-api"
    assert payload["drilldown_links"]["grafana_dashboard_url"]
    assert isinstance(payload["alert_rules"], list)
    assert len(payload["alert_rules"]) >= 1
    assert payload["latest_deploy_smoke"]["status"] in {"unknown", "pass", "fail"}
    assert payload["canary_policy"]["enabled"] is True
    assert payload["canary_policy"]["initial_traffic_pct"] == 10
