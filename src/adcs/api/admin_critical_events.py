"""Admin API endpoints for critical events and notification actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.api.admin_auth import (
    AdminAuthError,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)
from adcs.ingestion.source_registry import SourceRegistryLookupError, SourceRegistryService
from adcs.ops import (
    CriticalEventActionRecord,
    CriticalEventActionType,
    CriticalEventRecord,
    CriticalEventSeverity,
    CriticalEventStore,
    CriticalEventType,
)

_MAX_EVENT_ACTION_DURATION_MINUTES = 30 * 24 * 60
_EVENT_SLA_TARGET_MINUTES: dict[CriticalEventSeverity, int] = {
    CriticalEventSeverity.CRITICAL: 30,
    CriticalEventSeverity.HIGH: 120,
    CriticalEventSeverity.WARNING: 480,
}

router = APIRouter(
    tags=["admin-critical-events"],
    dependencies=[Depends(require_admin_principal)],
)


class CriticalEventSlaResponse(BaseModel):
    """Derived SLA state for one critical event."""

    target_minutes: int
    deadline_at: datetime
    remaining_minutes: int
    overdue: bool


class CriticalEventLifecycleResponse(BaseModel):
    """Derived operational lifecycle state for one critical event."""

    status: str
    effective_severity: CriticalEventSeverity
    owner: str | None
    latest_action: CriticalEventActionType | None
    latest_action_at: datetime | None
    action_count: int
    muted_until: datetime | None
    snoozed_until: datetime | None
    escalation_recommended: bool
    escalation_reason: str | None
    next_action_hint: str


class CriticalEventPostmortemResponse(BaseModel):
    """Postmortem readiness metadata for incident handoff."""

    required: bool
    status: str
    template_markdown: str | None


class CriticalEventResponse(BaseModel):
    """API representation of one critical event."""

    event_id: str
    severity: CriticalEventSeverity
    event_type: CriticalEventType
    message: str
    details: dict[str, object]
    created_at: datetime
    product_ids: list[str]
    sla: CriticalEventSlaResponse
    lifecycle: CriticalEventLifecycleResponse
    postmortem: CriticalEventPostmortemResponse


class CriticalEventActionResponse(BaseModel):
    """API representation of one critical-event action."""

    action_id: str
    event_id: str
    action: CriticalEventActionType
    actor_key_id: str
    request_id: str | None
    payload: dict[str, object]
    created_at: datetime


class _EventActionRequest(BaseModel):
    reason: str | None = Field(default=None, min_length=1, max_length=240)


class _TimedEventActionRequest(_EventActionRequest):
    duration_minutes: int = Field(
        ge=1,
        le=_MAX_EVENT_ACTION_DURATION_MINUTES,
    )

    @field_validator("duration_minutes")
    @classmethod
    def _validate_duration(cls, value: int) -> int:
        if value > _MAX_EVENT_ACTION_DURATION_MINUTES:
            msg = f"duration_minutes must not exceed {_MAX_EVENT_ACTION_DURATION_MINUTES}."
            raise ValueError(msg)
        return value


class _AssignOwnerActionRequest(_EventActionRequest):
    owner: str = Field(min_length=1, max_length=120)

    @field_validator("owner")
    @classmethod
    def _validate_owner(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "owner must not be empty."
            raise ValueError(msg)
        return normalized


class _SeverityOverrideActionRequest(_EventActionRequest):
    severity: CriticalEventSeverity


def _get_event_store(request: Request) -> CriticalEventStore:
    store = getattr(request.app.state, "critical_event_store", None)
    if not isinstance(store, CriticalEventStore):
        msg = "Critical event store is not configured."
        raise RuntimeError(msg)
    return store


def _get_source_registry_service(request: Request) -> SourceRegistryService | None:
    service = getattr(request.app.state, "source_registry_service", None)
    if isinstance(service, SourceRegistryService):
        return service
    return None


def _get_admin_principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _to_auth_http_exception(request: Request, exc: AdminAuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _resolve_event_product_ids(*, request: Request, event: CriticalEventRecord) -> tuple[str, ...]:
    details = event.details
    resolved_product_ids: set[str] = set()
    source_registry = _get_source_registry_service(request)

    product_id = details.get("product_id")
    if isinstance(product_id, str) and product_id.strip():
        resolved_product_ids.add(product_id.strip())

    product_ids = details.get("product_ids")
    if isinstance(product_ids, list):
        for item in product_ids:
            if isinstance(item, str) and item.strip():
                resolved_product_ids.add(item.strip())

    def _resolve_repo(repo_id: str) -> None:
        if source_registry is None:
            return
        try:
            repository = source_registry.get_repository(repo_id)
        except SourceRegistryLookupError:
            return
        resolved_product_ids.add(repository.product_id)

    repo_id = details.get("repo_id")
    if isinstance(repo_id, str) and repo_id.strip():
        _resolve_repo(repo_id.strip())

    repo_ids = details.get("repo_ids")
    if isinstance(repo_ids, list):
        for item in repo_ids:
            if isinstance(item, str) and item.strip():
                _resolve_repo(item.strip())

    return tuple(sorted(resolved_product_ids))


def _authorize_event_action(request: Request, event: CriticalEventRecord) -> None:
    principal = _get_admin_principal(request)
    auth_service = get_admin_auth_service(request)
    target_product_ids = _resolve_event_product_ids(request=request, event=event)
    try:
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=target_product_ids,
            destructive=False,
        )
    except AdminAuthError as exc:
        raise _to_auth_http_exception(request, exc) from exc


def _parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_severity_override(value: object) -> CriticalEventSeverity | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return CriticalEventSeverity(value.strip().casefold())
    except ValueError:
        return None


def _build_next_action_hint(
    *,
    lifecycle_status: str,
    escalation_recommended: bool,
    escalation_reason: str | None,
) -> str:
    if lifecycle_status == "resolved":
        return "Capture follow-up actions and complete the postmortem handoff."
    if lifecycle_status == "snoozed":
        return (
            "Re-check the incident when snooze expires or resolve earlier if "
            "recovery is confirmed."
        )
    if lifecycle_status == "muted":
        return (
            "Monitoring is muted temporarily; keep a human owner assigned and "
            "resolve once stability is confirmed."
        )
    if escalation_recommended and escalation_reason == "sla_deadline_breached":
        return "Escalate immediately, assign an owner if missing, and communicate incident impact."
    if escalation_recommended and escalation_reason == "owner_unassigned":
        return "Assign an incident owner and acknowledge the event before further actions."
    if escalation_recommended and escalation_reason == "acknowledgement_pending":
        return "Acknowledge the incident now and decide whether escalation is required."
    if lifecycle_status == "escalated":
        return (
            "Continue mitigation, keep updates visible, and resolve only after "
            "recovery is verified."
        )
    if lifecycle_status == "acknowledged":
        return (
            "Continue mitigation and resolve after the affected publish or "
            "ingestion flow is stable."
        )
    return "Acknowledge the incident, assign an owner, and decide whether escalation is required."


def _build_postmortem_template(
    *,
    event: CriticalEventRecord,
    product_ids: tuple[str, ...],
    owner: str | None,
    effective_severity: CriticalEventSeverity,
    lifecycle_status: str,
    deadline_at: datetime,
) -> str:
    products = ", ".join(product_ids) if product_ids else "unscoped"
    owner_value = owner or "unassigned"
    return (
        "## Incident Summary\n"
        f"- Event ID: {event.event_id}\n"
        f"- Event Type: {event.event_type.value}\n"
        f"- Effective Severity: {effective_severity.value}\n"
        f"- Products: {products}\n"
        f"- Owner: {owner_value}\n"
        f"- Created At: {event.created_at.isoformat()}\n"
        f"- SLA Deadline: {deadline_at.isoformat()}\n"
        f"- Current Status: {lifecycle_status}\n\n"
        "## Impact\n"
        f"- User-visible impact: {event.message}\n"
        "- Affected workflows:\n"
        "- Affected versions/languages:\n\n"
        "## Detection And Timeline\n"
        "- Detection source:\n"
        "- Key timestamps:\n"
        "- Escalation path:\n\n"
        "## Recovery\n"
        "- Immediate mitigation:\n"
        "- Permanent fix:\n"
        "- Validation evidence:\n\n"
        "## Follow-ups\n"
        "- Owner:\n"
        "- Due date:\n"
        "- Links to commits, incidents, dashboards:\n"
    )


def _derive_event_lifecycle(
    *,
    event: CriticalEventRecord,
    actions: tuple[CriticalEventActionRecord, ...],
    product_ids: tuple[str, ...],
) -> tuple[
    CriticalEventSlaResponse,
    CriticalEventLifecycleResponse,
    CriticalEventPostmortemResponse,
]:
    now = datetime.now(tz=UTC)
    chronological_actions = tuple(
        sorted(actions, key=lambda item: (item.created_at, item.action_id))
    )
    effective_severity = event.severity
    owner: str | None = None
    muted_until: datetime | None = None
    snoozed_until: datetime | None = None
    base_status = "open"
    latest_action: CriticalEventActionType | None = None
    latest_action_at: datetime | None = None

    for action in chronological_actions:
        latest_action = action.action
        latest_action_at = action.created_at
        if action.action is CriticalEventActionType.ASSIGN_OWNER:
            owner_value = action.payload.get("owner")
            if isinstance(owner_value, str) and owner_value.strip():
                owner = owner_value.strip()
            continue
        if action.action is CriticalEventActionType.SEVERITY_OVERRIDE:
            severity_override = _parse_severity_override(action.payload.get("severity"))
            if severity_override is not None:
                effective_severity = severity_override
            continue
        if action.action is CriticalEventActionType.ACKNOWLEDGE:
            base_status = "acknowledged"
            continue
        if action.action is CriticalEventActionType.ESCALATE:
            base_status = "escalated"
            continue
        if action.action is CriticalEventActionType.RESOLVED:
            base_status = "resolved"
            continue
        if action.action is CriticalEventActionType.MUTE:
            muted_until = _parse_optional_datetime(action.payload.get("muted_until"))
            if base_status == "open":
                base_status = "acknowledged"
            continue
        if action.action is CriticalEventActionType.SNOOZE:
            snoozed_until = _parse_optional_datetime(action.payload.get("snoozed_until"))
            if base_status == "open":
                base_status = "acknowledged"

    lifecycle_status = base_status
    if lifecycle_status != "resolved":
        if snoozed_until is not None and snoozed_until > now:
            lifecycle_status = "snoozed"
        elif muted_until is not None and muted_until > now:
            lifecycle_status = "muted"

    sla_target_minutes = _EVENT_SLA_TARGET_MINUTES[effective_severity]
    deadline_at = event.created_at + timedelta(minutes=sla_target_minutes)
    remaining_minutes = int((deadline_at - now).total_seconds() // 60)
    overdue = lifecycle_status != "resolved" and deadline_at < now

    escalation_reason: str | None = None
    escalation_recommended = False
    if lifecycle_status != "resolved" and base_status != "escalated":
        if overdue:
            escalation_recommended = True
            escalation_reason = "sla_deadline_breached"
        elif owner is None and effective_severity in {
            CriticalEventSeverity.CRITICAL,
            CriticalEventSeverity.HIGH,
        }:
            escalation_recommended = True
            escalation_reason = "owner_unassigned"
        elif latest_action is None and effective_severity is CriticalEventSeverity.CRITICAL:
            escalation_recommended = True
            escalation_reason = "acknowledgement_pending"

    next_action_hint = _build_next_action_hint(
        lifecycle_status=lifecycle_status,
        escalation_recommended=escalation_recommended,
        escalation_reason=escalation_reason,
    )
    postmortem_required = (
        effective_severity is CriticalEventSeverity.CRITICAL
        or base_status == "escalated"
        or overdue
    )
    postmortem_status = (
        "ready" if postmortem_required and lifecycle_status == "resolved" else
        "pending_resolution" if postmortem_required else
        "not_required"
    )
    postmortem_template = (
        _build_postmortem_template(
            event=event,
            product_ids=product_ids,
            owner=owner,
            effective_severity=effective_severity,
            lifecycle_status=lifecycle_status,
            deadline_at=deadline_at,
        )
        if postmortem_required
        else None
    )

    sla_response = CriticalEventSlaResponse(
        target_minutes=sla_target_minutes,
        deadline_at=deadline_at,
        remaining_minutes=remaining_minutes,
        overdue=overdue,
    )
    lifecycle_response = CriticalEventLifecycleResponse(
        status=lifecycle_status,
        effective_severity=effective_severity,
        owner=owner,
        latest_action=latest_action,
        latest_action_at=latest_action_at,
        action_count=len(chronological_actions),
        muted_until=muted_until,
        snoozed_until=snoozed_until,
        escalation_recommended=escalation_recommended,
        escalation_reason=escalation_reason,
        next_action_hint=next_action_hint,
    )
    postmortem_response = CriticalEventPostmortemResponse(
        required=postmortem_required,
        status=postmortem_status,
        template_markdown=postmortem_template,
    )
    return sla_response, lifecycle_response, postmortem_response


def _to_event_response(request: Request, event: CriticalEventRecord) -> CriticalEventResponse:
    store = _get_event_store(request)
    product_ids = _resolve_event_product_ids(request=request, event=event)
    actions = store.list_actions(limit=500, event_id=event.event_id)
    sla, lifecycle, postmortem = _derive_event_lifecycle(
        event=event,
        actions=actions,
        product_ids=product_ids,
    )
    return CriticalEventResponse(
        event_id=event.event_id,
        severity=event.severity,
        event_type=event.event_type,
        message=event.message,
        details=dict(event.details),
        created_at=event.created_at,
        product_ids=list(product_ids),
        sla=sla,
        lifecycle=lifecycle,
        postmortem=postmortem,
    )


def _to_action_response(action: CriticalEventActionRecord) -> CriticalEventActionResponse:
    return CriticalEventActionResponse(
        action_id=action.action_id,
        event_id=action.event_id,
        action=action.action,
        actor_key_id=action.actor_key_id,
        request_id=action.request_id,
        payload=dict(action.payload),
        created_at=action.created_at,
    )


def _apply_event_action(
    *,
    request: Request,
    event_id: str,
    action_type: CriticalEventActionType,
    payload: dict[str, object],
) -> CriticalEventActionResponse:
    store = _get_event_store(request)
    event = store.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Critical event `{event_id}` was not found.")

    _authorize_event_action(request, event)
    principal = _get_admin_principal(request)
    action_record = store.apply_action(
        event_id=event_id,
        action=action_type,
        actor_key_id=principal.key_id,
        request_id=getattr(request.state, "request_id", None),
        payload=payload,
    )
    return _to_action_response(action_record)


@router.get("/admin/v1/events/critical", response_model=list[CriticalEventResponse])
def list_critical_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    severity: CriticalEventSeverity | None = None,
    event_type: CriticalEventType | None = None,
    product_id: str | None = None,
) -> list[CriticalEventResponse]:
    """List critical events for admin notification center."""
    store = _get_event_store(request)
    all_events = store.list_events(limit=limit)
    responses: list[CriticalEventResponse] = []
    for event in all_events:
        if severity is not None and event.severity is not severity:
            continue
        if event_type is not None and event.event_type is not event_type:
            continue
        response = _to_event_response(request, event)
        if product_id is not None and product_id not in response.product_ids:
            continue
        responses.append(response)
    return responses


@router.get("/admin/v1/events/critical/actions", response_model=list[CriticalEventActionResponse])
def list_critical_event_actions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    event_id: str | None = None,
) -> list[CriticalEventActionResponse]:
    """List critical-event action audit trail."""
    store = _get_event_store(request)
    actions = store.list_actions(limit=limit, event_id=event_id)
    return [_to_action_response(action) for action in actions]


@router.post(
    "/admin/v1/events/critical/{event_id}:acknowledge",
    response_model=CriticalEventActionResponse,
)
def acknowledge_critical_event(
    event_id: str,
    payload: _EventActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    action_payload: dict[str, object] = {}
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.ACKNOWLEDGE,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:mute",
    response_model=CriticalEventActionResponse,
)
def mute_critical_event(
    event_id: str,
    payload: _TimedEventActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    muted_until = datetime.now(tz=UTC) + timedelta(minutes=payload.duration_minutes)
    action_payload: dict[str, object] = {
        "duration_minutes": payload.duration_minutes,
        "muted_until": muted_until.isoformat(),
    }
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.MUTE,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:snooze",
    response_model=CriticalEventActionResponse,
)
def snooze_critical_event(
    event_id: str,
    payload: _TimedEventActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    snoozed_until = datetime.now(tz=UTC) + timedelta(minutes=payload.duration_minutes)
    action_payload: dict[str, object] = {
        "duration_minutes": payload.duration_minutes,
        "snoozed_until": snoozed_until.isoformat(),
    }
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.SNOOZE,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:assign",
    response_model=CriticalEventActionResponse,
)
def assign_critical_event_owner(
    event_id: str,
    payload: _AssignOwnerActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    action_payload: dict[str, object] = {"owner": payload.owner}
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.ASSIGN_OWNER,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:severity-override",
    response_model=CriticalEventActionResponse,
)
def override_critical_event_severity(
    event_id: str,
    payload: _SeverityOverrideActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    action_payload: dict[str, object] = {"severity": payload.severity.value}
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.SEVERITY_OVERRIDE,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:escalate",
    response_model=CriticalEventActionResponse,
)
def escalate_critical_event(
    event_id: str,
    payload: _EventActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    action_payload: dict[str, object] = {}
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.ESCALATE,
        payload=action_payload,
    )


@router.post(
    "/admin/v1/events/critical/{event_id}:resolve",
    response_model=CriticalEventActionResponse,
)
def resolve_critical_event(
    event_id: str,
    payload: _EventActionRequest,
    request: Request,
) -> CriticalEventActionResponse:
    action_payload: dict[str, object] = {}
    if payload.reason is not None:
        action_payload["reason"] = payload.reason
    return _apply_event_action(
        request=request,
        event_id=event_id,
        action_type=CriticalEventActionType.RESOLVED,
        payload=action_payload,
    )
