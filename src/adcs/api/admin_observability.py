"""Admin observability summary endpoints (MCP, tracing, and canary control plane)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from adcs.api.abuse_guard import AbuseGuardService
from adcs.api.admin_auth import require_admin_principal
from adcs.api.metrics import InMemoryMetrics
from adcs.config import AbuseGuardMode
from adcs.ops import ObservabilityControlPlane
from adcs.ops.tracing import TracingService

router = APIRouter(
    tags=["admin-observability"],
    dependencies=[Depends(require_admin_principal)],
)


class MCPFallbackBreakdownRow(BaseModel):
    requested_revision: str
    negotiated_revision: str
    fallback_reason: str
    count: int


class AbuseGuardDecisionBreakdownRow(BaseModel):
    mode: str
    decision: str
    count: int


class AbuseGuardRuntimeSettingsResponse(BaseModel):
    mode: AbuseGuardMode
    allowlist_size: int
    requests_per_ip_per_minute: int
    requests_per_fingerprint_per_minute: int
    requests_global_per_minute: int
    debug_header_enabled: bool
    updated_by: str
    updated_at: datetime


class TracePolicySummaryResponse(BaseModel):
    enabled: bool
    service_name: str
    sample_ratio: float
    error_sample_ratio: float
    slow_request_threshold_ms: int
    backend: str
    otlp_endpoint: str | None


class DrilldownLinksResponse(BaseModel):
    grafana_dashboard_url: str | None
    loki_logs_url_template: str | None
    tempo_trace_url_template: str | None
    traces_enabled: bool


class AlertRuleSummaryResponse(BaseModel):
    rule_id: str
    severity: str
    description: str
    window_minutes: int
    threshold: str


class DeploySmokeCheckResponse(BaseModel):
    check_id: str
    status: str
    detail: str


class DeploySmokeSummaryResponse(BaseModel):
    status: str
    target_base_url: str | None
    started_at: str | None
    finished_at: str | None
    checks: list[DeploySmokeCheckResponse]


class CanaryPolicySummaryResponse(BaseModel):
    enabled: bool
    initial_traffic_pct: int
    full_traffic_pct: int
    analysis_window_minutes: int
    max_error_rate_pct: float
    max_latency_p95_ms: int
    auto_rollback: bool
    latest_decision: str | None
    latest_reason: str | None


class AdminObservabilitySummaryResponse(BaseModel):
    mcp_negotiation_total: int
    mcp_negotiation_fallback_total: int
    mcp_negotiation_fail_ratio: float
    mcp_sessions_by_revision: dict[str, int]
    mcp_fallback_by_reason: dict[str, int]
    mcp_fallback_breakdown: list[MCPFallbackBreakdownRow]
    abuse_guard_decisions_by_mode: dict[str, dict[str, int]]
    abuse_guard_decisions_breakdown: list[AbuseGuardDecisionBreakdownRow]
    abuse_guard_settings: AbuseGuardRuntimeSettingsResponse
    trace_policy: TracePolicySummaryResponse
    drilldown_links: DrilldownLinksResponse
    alert_rules: list[AlertRuleSummaryResponse]
    latest_deploy_smoke: DeploySmokeSummaryResponse
    canary_policy: CanaryPolicySummaryResponse
    request_id: str | None
    generated_at: datetime


def _metrics(request: Request) -> InMemoryMetrics:
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        msg = "Metrics service is not configured."
        raise RuntimeError(msg)
    return metrics


def _abuse_guard_service(request: Request) -> AbuseGuardService:
    service = getattr(request.app.state, "abuse_guard_service", None)
    if not isinstance(service, AbuseGuardService):
        msg = "Abuse guard service is not configured."
        raise RuntimeError(msg)
    return service


def _tracing_service(request: Request) -> TracingService:
    service = getattr(request.app.state, "tracing_service", None)
    if not isinstance(service, TracingService):
        msg = "Tracing service is not configured."
        raise RuntimeError(msg)
    return service


def _observability_control_plane(request: Request) -> ObservabilityControlPlane:
    service = getattr(request.app.state, "observability_control_plane", None)
    if not isinstance(service, ObservabilityControlPlane):
        msg = "Observability control plane is not configured."
        raise RuntimeError(msg)
    return service


@router.get(
    "/admin/v1/observability/summary",
    response_model=AdminObservabilitySummaryResponse,
)
def get_admin_observability_summary(request: Request) -> AdminObservabilitySummaryResponse:
    metrics_snapshot = _metrics(request).observability_snapshot()
    abuse_guard_snapshot = _abuse_guard_service(request).snapshot()
    tracing_service = _tracing_service(request)
    control_plane = _observability_control_plane(request)
    mcp_negotiation_total = cast(int, metrics_snapshot["mcp_negotiation_total"])
    mcp_negotiation_fallback_total = cast(
        int, metrics_snapshot["mcp_negotiation_fallback_total"]
    )
    mcp_negotiation_fail_ratio = cast(float, metrics_snapshot["mcp_negotiation_fail_ratio"])
    mcp_sessions_by_revision = cast(dict[str, int], metrics_snapshot["mcp_sessions_by_revision"])
    mcp_fallback_by_reason = cast(dict[str, int], metrics_snapshot["mcp_fallback_by_reason"])
    mcp_fallback_breakdown = cast(
        list[dict[str, object]], metrics_snapshot["mcp_fallback_breakdown"]
    )
    abuse_guard_decisions_by_mode = cast(
        dict[str, dict[str, int]], metrics_snapshot["abuse_guard_decisions_by_mode"]
    )
    abuse_guard_decisions_breakdown = cast(
        list[dict[str, object]], metrics_snapshot["abuse_guard_decisions_breakdown"]
    )
    drilldown_links = control_plane.load_links(traces_enabled=tracing_service.enabled)
    alert_rules = control_plane.load_alert_rules()
    latest_deploy_smoke = control_plane.load_smoke_summary()
    canary_policy = control_plane.load_canary_policy()

    return AdminObservabilitySummaryResponse(
        mcp_negotiation_total=mcp_negotiation_total,
        mcp_negotiation_fallback_total=mcp_negotiation_fallback_total,
        mcp_negotiation_fail_ratio=mcp_negotiation_fail_ratio,
        mcp_sessions_by_revision=mcp_sessions_by_revision,
        mcp_fallback_by_reason=mcp_fallback_by_reason,
        mcp_fallback_breakdown=[
            MCPFallbackBreakdownRow.model_validate(item) for item in mcp_fallback_breakdown
        ],
        abuse_guard_decisions_by_mode=abuse_guard_decisions_by_mode,
        abuse_guard_decisions_breakdown=[
            AbuseGuardDecisionBreakdownRow.model_validate(item)
            for item in abuse_guard_decisions_breakdown
        ],
        abuse_guard_settings=AbuseGuardRuntimeSettingsResponse(
            mode=abuse_guard_snapshot.mode,
            allowlist_size=len(abuse_guard_snapshot.allowlist),
            requests_per_ip_per_minute=abuse_guard_snapshot.requests_per_ip_per_minute,
            requests_per_fingerprint_per_minute=(
                abuse_guard_snapshot.requests_per_fingerprint_per_minute
            ),
            requests_global_per_minute=abuse_guard_snapshot.requests_global_per_minute,
            debug_header_enabled=abuse_guard_snapshot.debug_header_enabled,
            updated_by=abuse_guard_snapshot.updated_by,
            updated_at=abuse_guard_snapshot.updated_at,
        ),
        trace_policy=TracePolicySummaryResponse(
            enabled=tracing_service.enabled,
            service_name=tracing_service.service_name,
            sample_ratio=tracing_service.sample_ratio,
            error_sample_ratio=tracing_service.error_sample_ratio,
            slow_request_threshold_ms=tracing_service.slow_request_threshold_ms,
            backend=tracing_service.backend,
            otlp_endpoint=tracing_service.otlp_endpoint,
        ),
        drilldown_links=DrilldownLinksResponse.model_validate(asdict(drilldown_links)),
        alert_rules=[
            AlertRuleSummaryResponse.model_validate(asdict(item)) for item in alert_rules
        ],
        latest_deploy_smoke=DeploySmokeSummaryResponse(
            status=latest_deploy_smoke.status,
            target_base_url=latest_deploy_smoke.target_base_url,
            started_at=latest_deploy_smoke.started_at,
            finished_at=latest_deploy_smoke.finished_at,
            checks=[
                DeploySmokeCheckResponse.model_validate(asdict(check))
                for check in latest_deploy_smoke.checks
            ],
        ),
        canary_policy=CanaryPolicySummaryResponse.model_validate(asdict(canary_policy)),
        request_id=getattr(request.state, "request_id", None),
        generated_at=datetime.now(tz=UTC),
    )
