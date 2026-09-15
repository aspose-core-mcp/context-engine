"""Observability and canary rollout control-plane configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DrilldownLinks:
    grafana_dashboard_url: str | None
    loki_logs_url_template: str | None
    tempo_trace_url_template: str | None
    traces_enabled: bool


@dataclass(frozen=True, slots=True)
class AlertRuleSummary:
    rule_id: str
    severity: str
    description: str
    window_minutes: int
    threshold: str


@dataclass(frozen=True, slots=True)
class TracePolicySummary:
    enabled: bool
    service_name: str
    sample_ratio: float
    error_sample_ratio: float
    slow_request_threshold_ms: int
    backend: str
    otlp_endpoint: str | None


@dataclass(frozen=True, slots=True)
class DeploySmokeCheck:
    check_id: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class DeploySmokeSummary:
    status: str
    target_base_url: str | None
    started_at: str | None
    finished_at: str | None
    checks: tuple[DeploySmokeCheck, ...]


@dataclass(frozen=True, slots=True)
class CanaryPolicySummary:
    enabled: bool
    initial_traffic_pct: int
    full_traffic_pct: int
    analysis_window_minutes: int
    max_error_rate_pct: float
    max_latency_p95_ms: int
    auto_rollback: bool
    latest_decision: str | None
    latest_reason: str | None


class ObservabilityControlPlane:
    """Load drill-down metadata, alert pack, and canary/smoke summaries."""

    def __init__(
        self,
        *,
        config_path: Path,
        canary_policy_path: Path,
        smoke_report_path: Path,
        canary_report_path: Path,
    ) -> None:
        self._config_path = config_path
        self._canary_policy_path = canary_policy_path
        self._smoke_report_path = smoke_report_path
        self._canary_report_path = canary_report_path

    def load_links(self, *, traces_enabled: bool) -> DrilldownLinks:
        payload = self._load_config_payload()
        links = payload.get("drilldown_links", {})
        if not isinstance(links, dict):
            links = {}
        return DrilldownLinks(
            grafana_dashboard_url=_optional_string(links.get("grafana_dashboard_url")),
            loki_logs_url_template=_optional_string(links.get("loki_logs_url_template")),
            tempo_trace_url_template=_optional_string(links.get("tempo_trace_url_template")),
            traces_enabled=traces_enabled,
        )

    def load_alert_rules(self) -> tuple[AlertRuleSummary, ...]:
        payload = self._load_config_payload()
        alert_rules = payload.get("alert_rules")
        if not isinstance(alert_rules, list):
            return ()
        rules: list[AlertRuleSummary] = []
        for item in alert_rules:
            if not isinstance(item, dict):
                continue
            rules.append(
                AlertRuleSummary(
                    rule_id=str(item.get("rule_id", "unknown")),
                    severity=str(item.get("severity", "warning")),
                    description=str(item.get("description", "")),
                    window_minutes=int(item.get("window_minutes", 10)),
                    threshold=str(item.get("threshold", "")),
                )
            )
        return tuple(rules)

    def load_smoke_summary(self) -> DeploySmokeSummary:
        payload = self._load_json_payload(self._smoke_report_path)
        checks_payload = payload.get("checks", [])
        checks: list[DeploySmokeCheck] = []
        if isinstance(checks_payload, list):
            for item in checks_payload:
                if not isinstance(item, dict):
                    continue
                checks.append(
                    DeploySmokeCheck(
                        check_id=str(item.get("check_id", "unknown")),
                        status=str(item.get("status", "unknown")),
                        detail=str(item.get("detail", "")),
                    )
                )
        return DeploySmokeSummary(
            status=str(payload.get("status", "unknown")),
            target_base_url=_optional_string(payload.get("target_base_url")),
            started_at=_optional_string(payload.get("started_at")),
            finished_at=_optional_string(payload.get("finished_at")),
            checks=tuple(checks),
        )

    def load_canary_policy(self) -> CanaryPolicySummary:
        policy = self._load_json_payload(self._canary_policy_path)
        if not policy:
            config_payload = self._load_config_payload()
            policy = config_payload.get("canary_policy", {})
        if not isinstance(policy, dict):
            policy = {}
        evaluation_payload = self._load_json_payload(self._canary_report_path)
        return CanaryPolicySummary(
            enabled=bool(policy.get("enabled", True)),
            initial_traffic_pct=int(policy.get("initial_traffic_pct", 10)),
            full_traffic_pct=int(policy.get("full_traffic_pct", 100)),
            analysis_window_minutes=int(policy.get("analysis_window_minutes", 15)),
            max_error_rate_pct=float(policy.get("max_error_rate_pct", 1.0)),
            max_latency_p95_ms=int(policy.get("max_latency_p95_ms", 1200)),
            auto_rollback=bool(policy.get("auto_rollback", True)),
            latest_decision=_optional_string(evaluation_payload.get("decision")),
            latest_reason=_optional_string(evaluation_payload.get("reason")),
        )

    def _load_config_payload(self) -> dict[str, Any]:
        return self._load_json_payload(self._config_path)

    def _load_json_payload(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw_payload, dict):
            return {}
        return raw_payload


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None
