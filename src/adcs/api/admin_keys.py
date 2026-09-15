"""Admin API endpoints for admin key lifecycle management."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from adcs.api.admin_auth import (
    AdminAuthError,
    AdminAuthService,
    AdminKeyAuditRecord,
    AdminKeyMetadata,
    AdminKeyPrincipal,
    get_admin_auth_service,
    require_admin_principal,
)

_ALL_SCOPES = "*"
_WRITE_SCOPE_PREFIX = "write:"

router = APIRouter(
    tags=["admin-keys"],
    dependencies=[Depends(require_admin_principal)],
)


class AdminKeyResponse(BaseModel):
    key_id: str
    key_prefix: str
    is_superuser: bool
    enabled: bool
    product_scopes: list[str]
    scopes: list[str]
    source: str
    effective_role: str
    owner_email: str
    created_at: datetime
    updated_at: datetime


class AdminKeyCreateRequest(BaseModel):
    is_superuser: bool = False
    enabled: bool = True
    product_scopes: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    owner_email: str = Field(..., min_length=1, max_length=320)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("owner_email")
    @classmethod
    def _validate_owner_email(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "@" not in normalized:
            msg = "owner_email must be a valid email address."
            raise ValueError(msg)
        return normalized

    @field_validator("product_scopes", "scopes")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized_item = item.strip()
            if not normalized_item or normalized_item in seen:
                continue
            seen.add(normalized_item)
            normalized.append(normalized_item)
        return normalized

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AdminKeyCreateResponse(BaseModel):
    key: AdminKeyResponse
    api_key: str


class AdminKeyToggleRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AdminKeyScopesUpdateRequest(BaseModel):
    product_scopes: list[str]
    scopes: list[str]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("product_scopes", "scopes")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized_item = item.strip()
            if not normalized_item or normalized_item in seen:
                continue
            seen.add(normalized_item)
            normalized.append(normalized_item)
        return normalized

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AdminKeyAuditResponse(BaseModel):
    audit_id: str
    action: str
    target_key_id: str
    actor_key_id: str
    request_id: str | None
    reason: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    created_at: datetime


def _principal(request: Request) -> AdminKeyPrincipal:
    principal = getattr(request.state, "admin_principal", None)
    if not isinstance(principal, AdminKeyPrincipal):
        msg = "Admin principal is not attached to request context."
        raise RuntimeError(msg)
    return principal


def _auth_service(request: Request) -> AdminAuthService:
    return get_admin_auth_service(request)


def _to_http_exception(request: Request, error: AdminAuthError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": {},
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def _to_key_response(metadata: AdminKeyMetadata) -> AdminKeyResponse:
    return AdminKeyResponse(
        key_id=metadata.key_id,
        key_prefix=metadata.key_prefix,
        is_superuser=metadata.is_superuser,
        enabled=metadata.enabled,
        product_scopes=list(metadata.product_scopes),
        scopes=list(metadata.scopes),
        source=metadata.source,
        effective_role=metadata.effective_role,
        owner_email=metadata.owner_email,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
    )


def _to_audit_response(item: AdminKeyAuditRecord) -> AdminKeyAuditResponse:
    return AdminKeyAuditResponse(
        audit_id=item.audit_id,
        action=item.action,
        target_key_id=item.target_key_id,
        actor_key_id=item.actor_key_id,
        request_id=item.request_id,
        reason=item.reason,
        before=item.before,
        after=item.after,
        created_at=item.created_at,
    )


def _enforce_write_scope_grant_policy(
    *,
    principal: AdminKeyPrincipal,
    granted_scopes: tuple[str, ...],
) -> None:
    if principal.is_superuser:
        return
    if _ALL_SCOPES in granted_scopes:
        raise AdminAuthError(
            status_code=403,
            code="FORBIDDEN",
            message="Only superuser may grant wildcard scope `*`.",
        )
    for scope in granted_scopes:
        if not scope.startswith(_WRITE_SCOPE_PREFIX):
            continue
        if scope in principal.scopes:
            continue
        raise AdminAuthError(
            status_code=403,
            code="FORBIDDEN",
            message=f"Cannot grant scope `{scope}` without having it.",
        )


def _enforce_target_manageability(
    *,
    principal: AdminKeyPrincipal,
    target: AdminKeyMetadata,
) -> None:
    if principal.is_superuser:
        return
    if target.is_superuser:
        raise AdminAuthError(
            status_code=403,
            code="FORBIDDEN",
            message="Only superuser can manage superuser keys.",
        )
    if not target.product_scopes:
        raise AdminAuthError(
            status_code=403,
            code="FORBIDDEN",
            message="Key has no product scope; only superuser can manage it.",
        )
    denied_products = tuple(
        product_id
        for product_id in target.product_scopes
        if product_id not in principal.product_scopes
    )
    if denied_products:
        raise AdminAuthError(
            status_code=403,
            code="FORBIDDEN",
            message=(
                "Product scope violation: key does not grant write access to "
                f"{', '.join(denied_products)}."
            ),
        )


@router.get("/admin/v1/keys", response_model=list[AdminKeyResponse])
def list_admin_keys(request: Request) -> list[AdminKeyResponse]:
    service = _auth_service(request)
    items = service.list_key_metadata()
    return [_to_key_response(item) for item in items]


@router.post("/admin/v1/keys", response_model=AdminKeyCreateResponse)
def create_admin_key(
    payload: AdminKeyCreateRequest,
    request: Request,
) -> AdminKeyCreateResponse:
    principal = _principal(request)
    service = _auth_service(request)
    target_product_ids = tuple(payload.product_scopes)
    try:
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=target_product_ids,
            destructive=False,
        )
        if payload.is_superuser and not principal.is_superuser:
            raise AdminAuthError(
                status_code=403,
                code="FORBIDDEN",
                message="Only superuser can create superuser keys.",
            )
        _enforce_write_scope_grant_policy(
            principal=principal,
            granted_scopes=tuple(payload.scopes),
        )
        metadata, api_key = service.create_key(
            is_superuser=payload.is_superuser,
            product_scopes=tuple(payload.product_scopes),
            scopes=tuple(payload.scopes),
            enabled=payload.enabled,
            owner_email=payload.owner_email,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=payload.reason,
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminKeyCreateResponse(key=_to_key_response(metadata), api_key=api_key)


@router.post("/admin/v1/keys/{key_id}:disable", response_model=AdminKeyResponse)
def disable_admin_key(
    key_id: str,
    payload: AdminKeyToggleRequest,
    request: Request,
) -> AdminKeyResponse:
    principal = _principal(request)
    service = _auth_service(request)
    target = service.get_key_metadata(key_id=key_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Admin key `{key_id}` was not found.")
    try:
        _enforce_target_manageability(principal=principal, target=target)
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=tuple(target.product_scopes),
            destructive=False,
        )
        if target.key_id == principal.key_id:
            raise AdminAuthError(
                status_code=400,
                code="INVALID_OPERATION",
                message="Cannot disable the currently authenticated key.",
            )
        updated = service.set_key_enabled(
            key_id=key_id,
            enabled=False,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=payload.reason,
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request, exc) from exc
    return _to_key_response(updated)


@router.post("/admin/v1/keys/{key_id}:enable", response_model=AdminKeyResponse)
def enable_admin_key(
    key_id: str,
    payload: AdminKeyToggleRequest,
    request: Request,
) -> AdminKeyResponse:
    principal = _principal(request)
    service = _auth_service(request)
    target = service.get_key_metadata(key_id=key_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Admin key `{key_id}` was not found.")
    try:
        _enforce_target_manageability(principal=principal, target=target)
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=tuple(target.product_scopes),
            destructive=False,
        )
        updated = service.set_key_enabled(
            key_id=key_id,
            enabled=True,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=payload.reason,
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request, exc) from exc
    return _to_key_response(updated)


@router.patch("/admin/v1/keys/{key_id}/scopes", response_model=AdminKeyResponse)
def update_admin_key_scopes(
    key_id: str,
    payload: AdminKeyScopesUpdateRequest,
    request: Request,
) -> AdminKeyResponse:
    principal = _principal(request)
    service = _auth_service(request)
    target = service.get_key_metadata(key_id=key_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Admin key `{key_id}` was not found.")
    try:
        _enforce_target_manageability(principal=principal, target=target)
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=tuple(target.product_scopes),
            destructive=False,
        )
        if payload.product_scopes:
            service.authorize_mutation(
                principal=principal,
                required_scope="write:settings",
                target_product_ids=tuple(payload.product_scopes),
                destructive=False,
            )
        if target.key_id == principal.key_id and not payload.scopes:
            raise AdminAuthError(
                status_code=400,
                code="INVALID_OPERATION",
                message="Current key cannot drop all scopes.",
            )
        _enforce_write_scope_grant_policy(
            principal=principal,
            granted_scopes=tuple(payload.scopes),
        )
        updated = service.update_key_scopes(
            key_id=key_id,
            product_scopes=tuple(payload.product_scopes),
            scopes=tuple(payload.scopes),
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=payload.reason,
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_key_response(updated)


@router.get("/admin/v1/keys/audit", response_model=list[AdminKeyAuditResponse])
def list_admin_key_audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AdminKeyAuditResponse]:
    service = _auth_service(request)
    entries = service.list_key_audit(limit=limit)
    return [_to_audit_response(item) for item in entries]


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


class AdminKeyRotateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


@router.post("/admin/v1/keys/{key_id}:rotate", response_model=AdminKeyCreateResponse)
def rotate_admin_key(
    key_id: str,
    payload: AdminKeyRotateRequest,
    request: Request,
) -> AdminKeyCreateResponse:
    """Rotate an admin key: create a replacement with same scopes, disable the old one."""
    principal = _principal(request)
    service = _auth_service(request)
    target = service.get_key_metadata(key_id=key_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Admin key `{key_id}` was not found.")
    try:
        _enforce_target_manageability(principal=principal, target=target)
        service.authorize_mutation(
            principal=principal,
            required_scope="write:settings",
            target_product_ids=tuple(target.product_scopes),
            destructive=False,
        )
        # Create replacement key with same attributes
        new_metadata, new_api_key = service.create_key(
            is_superuser=target.is_superuser,
            product_scopes=target.product_scopes,
            scopes=target.scopes,
            enabled=True,
            owner_email=target.owner_email,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=f"rotation: replaces {key_id}"
            + (f" ({payload.reason})" if payload.reason else ""),
        )
        # Disable old key
        service.set_key_enabled(
            key_id=key_id,
            enabled=False,
            actor_key_id=principal.key_id,
            request_id=getattr(request.state, "request_id", None),
            reason=f"rotation: replaced by {new_metadata.key_id}"
            + (f" ({payload.reason})" if payload.reason else ""),
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request, exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminKeyCreateResponse(key=_to_key_response(new_metadata), api_key=new_api_key)


# ---------------------------------------------------------------------------
# Key export / import
# ---------------------------------------------------------------------------


class AdminKeyExportItem(BaseModel):
    key_id: str
    owner_email: str
    is_superuser: bool
    enabled: bool
    product_scopes: list[str]
    scopes: list[str]
    source: str
    created_at: datetime
    updated_at: datetime


class AdminKeyImportItem(BaseModel):
    is_superuser: bool = False
    enabled: bool = True
    product_scopes: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    owner_email: str = Field(..., min_length=1, max_length=320)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("owner_email")
    @classmethod
    def _validate_owner_email(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "@" not in normalized:
            msg = "owner_email must be a valid email address."
            raise ValueError(msg)
        return normalized

    @field_validator("product_scopes", "scopes")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized_item = item.strip()
            if not normalized_item or normalized_item in seen:
                continue
            seen.add(normalized_item)
            normalized.append(normalized_item)
        return normalized


class AdminKeyImportResponse(BaseModel):
    keys: list[AdminKeyCreateResponse]


@router.get("/admin/v1/keys:export", response_model=list[AdminKeyExportItem])
def export_admin_keys(request: Request) -> list[AdminKeyExportItem]:
    """Export all key metadata (no tokens) for backup or migration."""
    service = _auth_service(request)
    items = service.list_key_metadata()
    return [
        AdminKeyExportItem(
            key_id=item.key_id,
            owner_email=item.owner_email,
            is_superuser=item.is_superuser,
            enabled=item.enabled,
            product_scopes=list(item.product_scopes),
            scopes=list(item.scopes),
            source=item.source,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@router.post("/admin/v1/keys:import", response_model=AdminKeyImportResponse)
def import_admin_keys(
    payload: list[AdminKeyImportItem],
    request: Request,
) -> AdminKeyImportResponse:
    """Import key definitions and create new keys. Returns new tokens (shown once)."""
    principal = _principal(request)
    service = _auth_service(request)
    results: list[AdminKeyCreateResponse] = []
    for item in payload:
        try:
            service.authorize_mutation(
                principal=principal,
                required_scope="write:settings",
                target_product_ids=tuple(item.product_scopes),
                destructive=False,
            )
            if item.is_superuser and not principal.is_superuser:
                raise AdminAuthError(
                    status_code=403,
                    code="FORBIDDEN",
                    message="Only superuser can import superuser keys.",
                )
            _enforce_write_scope_grant_policy(
                principal=principal,
                granted_scopes=tuple(item.scopes),
            )
            metadata, api_key = service.create_key(
                is_superuser=item.is_superuser,
                product_scopes=tuple(item.product_scopes),
                scopes=tuple(item.scopes),
                enabled=item.enabled,
                owner_email=item.owner_email,
                actor_key_id=principal.key_id,
                request_id=getattr(request.state, "request_id", None),
                reason=item.reason or "imported",
            )
            results.append(
                AdminKeyCreateResponse(key=_to_key_response(metadata), api_key=api_key)
            )
        except AdminAuthError as exc:
            raise _to_http_exception(request, exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminKeyImportResponse(keys=results)
