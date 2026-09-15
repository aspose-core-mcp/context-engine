"""Public status page API.

Provides incidents, maintenance windows, and component metadata that the
public-facing status page UI consumes. The base health/readiness signal is
served by ``GET /v1/status`` in ``admin_system.py``; this module supplements
it with announcement-style content.

Configuration source: ``config/status-page-config.json`` (read fresh per
request — small file, low latency).

The status page is a self-hosted, in-repo surface rendered by the admin UI.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

# Resolve config path relative to repository root (4 levels up from this file).
_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "status-page-config.json"


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


class StatusComponent(BaseModel):
    id: str
    name: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)


class StatusComponentRuntime(StatusComponent):
    """Component with current operational state derived from system signals."""

    state: Literal["operational", "degraded", "partial_outage", "major_outage", "unknown"] = (
        "unknown"
    )
    note: str = ""


class IncidentUpdate(BaseModel):
    timestamp: datetime
    state: Literal[
        "investigating", "identified", "monitoring", "resolved", "scheduled", "in_progress"
    ]
    message: str


class Incident(BaseModel):
    id: str
    title: str
    severity: Literal["sev1", "sev2", "sev3", "sev4"]
    affected_components: list[str] = Field(default_factory=list)
    started_at: datetime
    resolved_at: datetime | None = None
    public_message: str = ""
    updates: list[IncidentUpdate] = Field(default_factory=list)


class MaintenanceWindow(BaseModel):
    id: str
    title: str
    affected_components: list[str] = Field(default_factory=list)
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    public_message: str = ""


class Announcement(BaseModel):
    id: str
    title: str
    severity: Literal["info", "warning", "critical"] = "info"
    posted_at: datetime
    expires_at: datetime | None = None
    body: str = ""


class StatusPagePayload(BaseModel):
    """Top-level response for /v1/status/page."""

    overall_state: Literal["operational", "degraded", "partial_outage", "major_outage"]
    overall_message: str
    components: list[StatusComponentRuntime]
    active_incidents: list[Incident]
    recent_incidents: list[Incident]
    upcoming_maintenance: list[MaintenanceWindow]
    active_maintenance: list[MaintenanceWindow]
    announcements: list[Announcement]
    generated_at: datetime
    config_version: str = "v1"


# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------


router = APIRouter(tags=["public-status-page"])


def _load_config() -> dict[str, object]:
    if not _CONFIG_PATH.exists():
        return {
            "components": [],
            "maintenance_windows": [],
            "announcements": [],
            "incidents": [],
        }
    loaded = json.loads(_CONFIG_PATH.read_text())
    if isinstance(loaded, dict):
        return loaded
    return {}


def _as_list(value: object) -> list[object]:
    """Defensively coerce a config value to a list of opaque entries."""
    if isinstance(value, list):
        # mypy: each element typed as object; we type-narrow at use site
        return list(value)
    return []


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        # accept "2026-04-29T10:00:00Z" or with offset
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (TypeError, ValueError):
        return None


def _classify_overall(
    components: list[StatusComponentRuntime], active_incidents: list[Incident]
) -> tuple[str, str]:
    if active_incidents:
        worst_sev = min(i.severity for i in active_incidents)
        if worst_sev == "sev1":
            return "major_outage", "Major incident in progress."
        if worst_sev == "sev2":
            return "partial_outage", "Partial outage — incident in progress."
        return "degraded", "Degraded service — non-critical incident in progress."
    if any(c.state in {"major_outage", "partial_outage"} for c in components):
        return "partial_outage", "One or more components are not fully operational."
    if any(c.state == "degraded" for c in components):
        return "degraded", "Degraded performance reported."
    return "operational", "All systems operational."


@router.get("/v1/status/page", response_model=StatusPagePayload)
def get_public_status_page(request: Request) -> StatusPagePayload:
    """Return the full status-page payload (components + incidents + maintenance)."""
    # Unauthenticated and config-file backed, so it was invisible even to
    # observe-mode telemetry while remaining trivially floodable.
    from adcs.api.public_docs_query import _enforce_abuse_guard

    _enforce_abuse_guard(request)
    config = _load_config()
    now = datetime.now(tz=UTC)

    # Components — for now we mark all as "operational"; a future iteration
    # will derive component state from real health-check data.
    components: list[StatusComponentRuntime] = []
    for raw in _as_list(config.get("components")):
        if not isinstance(raw, dict):
            continue
        depends_raw = raw.get("depends_on")
        depends_on = [str(x) for x in depends_raw] if isinstance(depends_raw, list) else []
        components.append(
            StatusComponentRuntime(
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                description=str(raw.get("description", "")),
                depends_on=depends_on,
                state="operational",
                note="",
            )
        )

    # Incidents
    active_incidents: list[Incident] = []
    recent_incidents: list[Incident] = []
    for raw in _as_list(config.get("incidents")):
        if not isinstance(raw, dict):
            continue
        try:
            affected_raw = raw.get("affected_components")
            affected = (
                [str(x) for x in affected_raw] if isinstance(affected_raw, list) else []
            )
            updates_raw = raw.get("updates")
            updates = (
                [
                    IncidentUpdate(
                        timestamp=_parse_dt(u.get("timestamp")) or now,
                        state=u.get("state", "investigating"),
                        message=str(u.get("message", "")),
                    )
                    for u in updates_raw
                    if isinstance(u, dict)
                ]
                if isinstance(updates_raw, list)
                else []
            )
            incident = Incident(
                id=str(raw.get("id", "")),
                title=str(raw.get("title", "")),
                severity=raw.get("severity", "sev3"),
                affected_components=affected,
                started_at=_parse_dt(raw.get("started_at")) or now,
                resolved_at=_parse_dt(raw.get("resolved_at")),
                public_message=str(raw.get("public_message", "")),
                updates=updates,
            )
        except Exception:
            continue
        if incident.resolved_at is None:
            active_incidents.append(incident)
        else:
            recent_incidents.append(incident)
    recent_incidents.sort(key=lambda i: i.started_at, reverse=True)
    recent_incidents = recent_incidents[:10]

    # Maintenance windows
    upcoming: list[MaintenanceWindow] = []
    active: list[MaintenanceWindow] = []
    for raw in _as_list(config.get("maintenance_windows")):
        if not isinstance(raw, dict):
            continue
        try:
            mw_affected_raw = raw.get("affected_components")
            mw_affected = (
                [str(x) for x in mw_affected_raw]
                if isinstance(mw_affected_raw, list)
                else []
            )
            window = MaintenanceWindow(
                id=str(raw.get("id", "")),
                title=str(raw.get("title", "")),
                affected_components=mw_affected,
                scheduled_start=_parse_dt(raw.get("scheduled_start")) or now,
                scheduled_end=_parse_dt(raw.get("scheduled_end")) or now,
                actual_start=_parse_dt(raw.get("actual_start")),
                actual_end=_parse_dt(raw.get("actual_end")),
                public_message=str(raw.get("public_message", "")),
            )
        except Exception:
            continue
        if window.actual_end is not None:
            continue  # finished
        if window.actual_start is not None or (
            window.scheduled_start <= now <= window.scheduled_end
        ):
            active.append(window)
        elif window.scheduled_start > now:
            upcoming.append(window)

    # Announcements (drop expired)
    announcements: list[Announcement] = []
    for raw in _as_list(config.get("announcements")):
        if not isinstance(raw, dict):
            continue
        try:
            ann = Announcement(
                id=str(raw.get("id", "")),
                title=str(raw.get("title", "")),
                severity=raw.get("severity", "info"),
                posted_at=_parse_dt(raw.get("posted_at")) or now,
                expires_at=_parse_dt(raw.get("expires_at")),
                body=str(raw.get("body", "")),
            )
        except Exception:
            continue
        if ann.expires_at is not None and ann.expires_at < now:
            continue
        announcements.append(ann)

    overall_state, overall_message = _classify_overall(components, active_incidents)

    return StatusPagePayload(
        overall_state=overall_state,  # type: ignore[arg-type]
        overall_message=overall_message,
        components=components,
        active_incidents=active_incidents,
        recent_incidents=recent_incidents,
        upcoming_maintenance=upcoming,
        active_maintenance=active,
        announcements=announcements,
        generated_at=now,
    )
