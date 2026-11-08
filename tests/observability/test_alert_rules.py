"""Structural validation for Prometheus alert rules.

Every alert in ``infra/observability/prometheus/adcs-alerts.yaml`` is
verified against the project's alerting policy:

* the file parses as a Prometheus rule-group YAML;
* every alert declares a valid ``severity`` label (sev1..sev4);
* Sev1 and Sev2 alerts must carry a ``runbook_url`` annotation
  (they demand prompt action, so they need the playbook link);
* every ``runbook_url`` resolves to a heading that exists in the linked
  runbook file;
* every metric an expression queries is a family the service exports;
* alert names are unique across the file;
* every alert has a non-empty ``expr`` and a parseable ``for`` duration
  (when ``for`` is set);
* every group declares a valid ``interval`` (when set).

These are deterministic checks that always run in CI. The companion
firing test (test_alert_firing_promtool.py) runs only when ``promtool``
is on PATH and replays synthetic metric series through Prometheus's own
rule evaluator to confirm that the configured alerts actually fire under
the SLO breach conditions they target.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from adcs.api.ingestion_slis import render_ingestion_slis
from adcs.api.metrics import InMemoryMetrics
from adcs.indexing.index_models import SnapshotStatus
from adcs.ops.critical_events import InMemoryCriticalEventStore

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTS_PATH = REPO_ROOT / "infra" / "observability" / "prometheus" / "adcs-alerts.yaml"

_VALID_SEVERITIES = frozenset({"sev1", "sev2", "sev3", "sev4"})
_DURATION_RE = re.compile(r"^\d+(ms|[smhd])$")
_RUNBOOK_URL_PREFIX = "https://github.com/aspose-core-mcp/context-engine/blob/main/"
_PROMQL_KEYWORDS = frozenset(
    {
        "and",
        "or",
        "unless",
        "by",
        "without",
        "on",
        "ignoring",
        "group_left",
        "group_right",
        "offset",
        "bool",
        "inf",
        "nan",
    }
)
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")


def _load_rules_file() -> dict[str, Any]:
    return yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))


def _iter_alerts() -> list[dict[str, Any]]:
    payload = _load_rules_file()
    alerts: list[dict[str, Any]] = []
    for group in payload.get("groups", []):
        for rule in group.get("rules", []):
            if "alert" in rule:
                alerts.append({"_group": group.get("name", "<unnamed>"), **rule})
    return alerts


def _markdown_anchors(path: Path) -> set[str]:
    """Return the GitHub-style anchors of every heading outside code fences."""
    anchors: set[str] = set()
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            slug = re.sub(r"[^\w\- ]", "", match.group(1).strip().lower())
            anchors.add(slug.replace(" ", "-"))
    return anchors


def _metric_names(expr: str) -> set[str]:
    """Extract the metric names a PromQL expression selects."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", "", text
    )
    names: set[str] = set()
    for match in re.finditer(r"(?<![\w.])[A-Za-z_:][A-Za-z0-9_:]*", text):
        if text[match.end():].lstrip().startswith("("):
            continue  # function or aggregation operator
        if match.group(0).lower() in _PROMQL_KEYWORDS:
            continue
        names.add(match.group(0))
    return names


def _exported_metric_families() -> set[str]:
    """Metric families rendered at /metrics once every series is populated."""
    metrics = InMemoryMetrics()
    metrics.observe_request(method="GET", path="/healthz", status_code=200, latency_seconds=0.1)
    metrics.observe_retrieval_stage("rerank", 0.1)
    snapshot = SimpleNamespace(status=SnapshotStatus.ACTIVE, created_at=datetime.now(tz=UTC))
    registry = SimpleNamespace(list_snapshots=lambda **_: (snapshot,))
    exposition = metrics.render_prometheus() + render_ingestion_slis(
        snapshot_registry=registry,
        critical_event_store=InMemoryCriticalEventStore(),
    )
    return {
        line.split()[2] for line in exposition.splitlines() if line.startswith("# TYPE ")
    }


def test_alerts_file_exists_and_parses_as_yaml() -> None:
    """The alerts YAML must exist and load without errors."""
    assert ALERTS_PATH.exists(), f"missing alerts file at {ALERTS_PATH}"
    payload = _load_rules_file()
    assert isinstance(payload, dict), "alerts file root must be a mapping"
    assert "groups" in payload, "alerts file must declare a 'groups' key"
    assert isinstance(payload["groups"], list)
    assert payload["groups"], "alerts file declares no rule groups"


def test_every_alert_declares_a_recognised_severity() -> None:
    """Every alert rule must carry a severity label in {sev1..sev4}."""
    for alert in _iter_alerts():
        labels = alert.get("labels", {})
        assert "severity" in labels, (
            f"alert {alert['alert']} in group {alert['_group']} has no "
            f"severity label"
        )
        assert labels["severity"] in _VALID_SEVERITIES, (
            f"alert {alert['alert']} severity={labels['severity']!r} not in "
            f"{sorted(_VALID_SEVERITIES)}"
        )


def test_sev1_alerts_carry_a_runbook_url_annotation() -> None:
    """Sev1 alerts demand immediate action — they must link to a playbook."""
    for alert in _iter_alerts():
        severity = alert.get("labels", {}).get("severity")
        if severity != "sev1":
            continue
        annotations = alert.get("annotations", {})
        assert annotations.get("runbook_url"), (
            f"Sev1 alert {alert['alert']} missing 'runbook_url' annotation"
        )


def test_sev2_alerts_carry_a_runbook_url_annotation() -> None:
    """Sev2 alerts need a playbook link for triage."""
    for alert in _iter_alerts():
        severity = alert.get("labels", {}).get("severity")
        if severity != "sev2":
            continue
        annotations = alert.get("annotations", {})
        assert annotations.get("runbook_url"), (
            f"Sev2 alert {alert['alert']} missing 'runbook_url' annotation"
        )


def test_runbook_urls_resolve_to_existing_headings() -> None:
    """A runbook link must point at a file and heading that exist in this repo."""
    for alert in _iter_alerts():
        url = alert.get("annotations", {}).get("runbook_url")
        if not url:
            continue
        assert url.startswith(_RUNBOOK_URL_PREFIX), (
            f"alert {alert['alert']} runbook_url {url!r} does not point into "
            f"this repository"
        )
        relative_path, _, anchor = url[len(_RUNBOOK_URL_PREFIX):].partition("#")
        target = REPO_ROOT / relative_path
        assert target.is_file(), (
            f"alert {alert['alert']} runbook_url points at missing file {relative_path}"
        )
        if anchor:
            assert anchor in _markdown_anchors(target), (
                f"alert {alert['alert']} runbook_url anchor #{anchor} has no "
                f"matching heading in {relative_path}"
            )


def test_alert_expressions_query_exported_metrics() -> None:
    """A rule over a metric the service never exports can never fire."""
    families = _exported_metric_families()
    for alert in _iter_alerts():
        for name in _metric_names(alert["expr"]):
            exported = name in families or any(
                name.endswith(suffix) and name[: -len(suffix)] in families
                for suffix in _HISTOGRAM_SUFFIXES
            )
            assert exported, (
                f"alert {alert['alert']} queries {name!r}, which /metrics does not "
                f"export"
            )


def test_every_alert_has_a_summary_annotation() -> None:
    """The summary annotation is what the alertmanager renders as the title."""
    for alert in _iter_alerts():
        annotations = alert.get("annotations", {})
        assert annotations.get("summary"), (
            f"alert {alert['alert']} missing 'summary' annotation"
        )


def test_alert_names_are_unique_within_the_file() -> None:
    """No two alerts may share the same name — alertmanager keys on it."""
    names = [a["alert"] for a in _iter_alerts()]
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"duplicate alert names: {sorted(duplicates)}"


def test_alert_for_durations_are_well_formed() -> None:
    """When `for` is set, it must be a duration string Prometheus accepts."""
    for alert in _iter_alerts():
        for_value = alert.get("for")
        if for_value is None:
            continue
        assert isinstance(for_value, str), (
            f"alert {alert['alert']} 'for' must be a string, got "
            f"{type(for_value).__name__}"
        )
        assert _DURATION_RE.match(for_value), (
            f"alert {alert['alert']} 'for'={for_value!r} is not a valid "
            f"Prometheus duration (e.g. 30s, 5m, 1h, 24h)"
        )


def test_alert_expressions_are_non_empty_strings() -> None:
    """Every alert must declare an expression Prometheus can evaluate."""
    for alert in _iter_alerts():
        expr = alert.get("expr")
        assert isinstance(expr, str) and expr.strip(), (
            f"alert {alert['alert']} has empty or non-string 'expr'"
        )


def test_alert_groups_declare_a_valid_interval() -> None:
    """Group-level `interval` (when set) must be a Prometheus duration."""
    payload = _load_rules_file()
    for group in payload["groups"]:
        interval = group.get("interval")
        if interval is None:
            continue
        assert isinstance(interval, str) and _DURATION_RE.match(interval), (
            f"group {group.get('name')!r} interval={interval!r} not a valid "
            f"Prometheus duration"
        )


def test_burn_rate_alerts_present_for_api_availability_slo() -> None:
    """Multi-window burn-rate alerts must exist for the availability SLO.

    Threshold alerts alone react late to slow error-budget consumption;
    burn-rate alerts catch it while budget remains.
    """
    names = {a["alert"] for a in _iter_alerts()}
    burn_alerts = {n for n in names if "Burn" in n or "burn" in n}
    assert burn_alerts, (
        "no SLO burn-rate alerts found — define multi-window burn-rate "
        "alerts on at least one SLO"
    )


def test_sev1_alert_count_is_low() -> None:
    """Sev1 should be reserved for signals that need immediate action.

    A Sev1 spam problem produces alert fatigue; aim for ≤ 5 Sev1 alerts.
    """
    sev1_count = sum(
        1
        for a in _iter_alerts()
        if a.get("labels", {}).get("severity") == "sev1"
    )
    assert sev1_count <= 5, (
        f"too many Sev1 alerts ({sev1_count}); Sev1 should be reserved for "
        f"signals that need immediate action to avoid alert fatigue"
    )
