"""Admin endpoints for public API abuse-guard runtime settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from adcs.admin import InMemoryConfigHistoryService
from adcs.api.abuse_guard import AbuseGuardService, AbuseGuardSettingsSnapshot
from adcs.api.admin_auth import AdminKeyPrincipal, require_admin_principal
from adcs.config import AbuseGuardMode

router = APIRouter(
    tags=["admin-abuse-guard"],
    dependencies=[Depends(require_admin_principal)],
)


class AbuseGuardSettingsResponse(BaseModel):
    mode: AbuseGuardMode
    allowlist: list[str]
    requests_per_ip_per_minute: int
    requests_per_fingerprint_per_minute: int
    requests_global_per_minute: int
    debug_header_enabled: bool
    updated_by: str
    updated_at: str


class PatchAbuseGuardSettingsRequest(BaseModel):
    mode: AbuseGuardMode | None = None
    allowlist: list[str] | None = None
    requests_per_ip_per_minute: int | None = Field(default=None, ge=1)
    requests_per_fingerprint_per_minute: int | None = Field(default=None, ge=1)
    requests_global_per_minute: int | None = Field(default=None, ge=1)
    debug_header_enabled: bool | None = None

    @field_validator("allowlist")
    @classmethod
    def _normalize_allowlist(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            token = item.strip().casefold()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized


def _abuse_guard_service(request: Request) -> AbuseGuardService:
    service = getattr(request.app.state, "abuse_guard_service", None)
    if not isinstance(service, AbuseGuardService):
        msg = "Abuse guard service is not configured."
        raise RuntimeError(msg)
    return service


def _principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _config_history_service(request: Request) -> InMemoryConfigHistoryService | None:
    service = getattr(request.app.state, "config_history_service", None)
    if isinstance(service, InMemoryConfigHistoryService):
        return service
    return None


def _require_superuser(request: Request) -> AdminKeyPrincipal:
    principal = _principal(request)
    if principal.is_superuser:
        return principal
    raise HTTPException(
        status_code=403,
        detail={
            "error": {
                "code": "FORBIDDEN",
                "message": "Only superuser key can mutate abuse-guard settings.",
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _snapshot_payload(snapshot: AbuseGuardSettingsSnapshot) -> dict[str, Any]:
    return {
        "mode": snapshot.mode.value,
        "allowlist": list(snapshot.allowlist),
        "requests_per_ip_per_minute": snapshot.requests_per_ip_per_minute,
        "requests_per_fingerprint_per_minute": snapshot.requests_per_fingerprint_per_minute,
        "requests_global_per_minute": snapshot.requests_global_per_minute,
        "debug_header_enabled": snapshot.debug_header_enabled,
        "updated_by": snapshot.updated_by,
        "updated_at": snapshot.updated_at.isoformat(),
    }


def _to_response(snapshot: AbuseGuardSettingsSnapshot) -> AbuseGuardSettingsResponse:
    return AbuseGuardSettingsResponse(
        mode=snapshot.mode,
        allowlist=list(snapshot.allowlist),
        requests_per_ip_per_minute=snapshot.requests_per_ip_per_minute,
        requests_per_fingerprint_per_minute=snapshot.requests_per_fingerprint_per_minute,
        requests_global_per_minute=snapshot.requests_global_per_minute,
        debug_header_enabled=snapshot.debug_header_enabled,
        updated_by=snapshot.updated_by,
        updated_at=snapshot.updated_at.isoformat(),
    )


@router.get(
    "/admin/v1/settings/public-api/abuse-guard",
    response_model=AbuseGuardSettingsResponse,
)
def get_abuse_guard_settings(request: Request) -> AbuseGuardSettingsResponse:
    snapshot = _abuse_guard_service(request).snapshot()
    return _to_response(snapshot)


@router.patch(
    "/admin/v1/settings/public-api/abuse-guard",
    response_model=AbuseGuardSettingsResponse,
)
def patch_abuse_guard_settings(
    payload: PatchAbuseGuardSettingsRequest,
    request: Request,
) -> AbuseGuardSettingsResponse:
    principal = _require_superuser(request)
    service = _abuse_guard_service(request)
    before = service.snapshot()
    updated = service.update_settings(
        actor_key_id=principal.key_id,
        mode=payload.mode,
        allowlist=tuple(payload.allowlist) if payload.allowlist is not None else None,
        requests_per_ip_per_minute=payload.requests_per_ip_per_minute,
        requests_per_fingerprint_per_minute=payload.requests_per_fingerprint_per_minute,
        requests_global_per_minute=payload.requests_global_per_minute,
        debug_header_enabled=payload.debug_header_enabled,
    )
    history_service = _config_history_service(request)
    if history_service is not None:
        history_service.record_change(
            product_id="global",
            config_scope="public_api_settings",
            config_key="abuse_guard",
            action_type="update_abuse_guard_settings",
            before=_snapshot_payload(before),
            after=_snapshot_payload(updated),
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=None,
            rollback_of_change_id=None,
        )
    return _to_response(updated)
