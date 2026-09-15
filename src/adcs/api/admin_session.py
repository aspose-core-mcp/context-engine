"""Admin login/logout endpoints for cookie-based admin sessions."""

from __future__ import annotations

import time
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from adcs.api.abuse_guard import _extract_client_host
from adcs.api.admin_auth import AdminAuthError, AdminKeyPrincipal, get_admin_auth_service

router = APIRouter(tags=["admin-system"])

# Login is the one unauthenticated admin surface, and it had no attempt counter,
# lockout or backoff — an online brute-force against the admin key was bounded
# only by network throughput. Track failures per caller and refuse for a
# growing window once the threshold is crossed.
_LOGIN_MAX_FAILURES = 5
_LOGIN_LOCKOUT_BASE_SECONDS = 30.0
_LOGIN_LOCKOUT_MAX_SECONDS = 900.0
_LOGIN_FAILURE_WINDOW_SECONDS = 900.0


class _LoginThrottle:
    """Per-caller failed-login counter with exponential lockout."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._failures: dict[str, tuple[int, float]] = {}

    def retry_after_seconds(self, key: str, *, now: float) -> float:
        """Return remaining lockout for this caller, 0.0 when not locked out."""
        with self._lock:
            entry = self._failures.get(key)
            if entry is None:
                return 0.0
            count, last_failure_at = entry
            if now - last_failure_at > _LOGIN_FAILURE_WINDOW_SECONDS:
                del self._failures[key]
                return 0.0
            if count < _LOGIN_MAX_FAILURES:
                return 0.0
            penalty = min(
                _LOGIN_LOCKOUT_BASE_SECONDS * (2 ** (count - _LOGIN_MAX_FAILURES)),
                _LOGIN_LOCKOUT_MAX_SECONDS,
            )
            remaining = penalty - (now - last_failure_at)
            return max(remaining, 0.0)

    def record_failure(self, key: str, *, now: float) -> None:
        with self._lock:
            count, last_failure_at = self._failures.get(key, (0, now))
            if now - last_failure_at > _LOGIN_FAILURE_WINDOW_SECONDS:
                count = 0
            self._failures[key] = (count + 1, now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def _get_login_throttle(request: Request) -> _LoginThrottle:
    """Return this app's throttle, creating it on first use.

    Kept on app state rather than in a module global so each application
    instance owns its counters — a global would leak lockouts across tests and
    across apps sharing the process.
    """
    throttle = getattr(request.app.state, "admin_login_throttle", None)
    if not isinstance(throttle, _LoginThrottle):
        throttle = _LoginThrottle()
        request.app.state.admin_login_throttle = throttle
    return throttle


def _login_throttle_key(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    hops = getattr(settings, "trusted_proxy_hops", 0) or 0
    return _extract_client_host(request, trusted_proxy_hops=hops) or "unknown"


class AdminSessionLoginRequest(BaseModel):
    """Login payload for creating an admin cookie session."""

    api_key: str = Field(min_length=1, max_length=512)
    remember_device: bool = True

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "api_key must not be empty."
            raise ValueError(msg)
        return normalized


class AdminSessionResponse(BaseModel):
    """Authenticated admin key session for UI role/scopes rendering."""

    key_id: str
    effective_role: str
    is_superuser: bool
    scopes: list[str]
    product_scopes: list[str]
    source: str
    owner_email: str = "system@local"


class AdminSessionLogoutResponse(BaseModel):
    """Logout confirmation response."""

    status: str


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


def _to_session_response(principal: AdminKeyPrincipal) -> AdminSessionResponse:
    return AdminSessionResponse(
        key_id=principal.key_id,
        effective_role=principal.effective_role,
        is_superuser=principal.is_superuser,
        scopes=list(principal.scopes),
        product_scopes=list(principal.product_scopes),
        source=principal.source,
        owner_email=principal.owner_email,
    )


@router.post("/admin/v1/system/session/login", response_model=AdminSessionResponse)
def login_admin_session(
    request: Request,
    payload: AdminSessionLoginRequest,
) -> JSONResponse:
    """Validate admin key and create HTTP-only cookie session."""
    auth_service = get_admin_auth_service(request)
    settings = request.app.state.settings

    login_throttle = _get_login_throttle(request)
    throttle_key = _login_throttle_key(request)
    now = time.monotonic()
    retry_after = login_throttle.retry_after_seconds(throttle_key, now=now)
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many failed login attempts. Try again later.",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    try:
        principal = auth_service.authenticate(api_key=payload.api_key)
    except AdminAuthError as exc:
        login_throttle.record_failure(throttle_key, now=now)
        raise _to_auth_http_exception(request, exc) from exc
    login_throttle.reset(throttle_key)

    ttl_seconds = (
        settings.admin_session_remember_ttl_seconds
        if payload.remember_device
        else settings.admin_session_ttl_seconds
    )
    session_token = auth_service.create_session(
        key_id=principal.key_id,
        ttl_seconds=ttl_seconds,
    )
    body = _to_session_response(principal).model_dump(mode="json")
    response = JSONResponse(content=body)
    if payload.remember_device:
        response.set_cookie(
            key=settings.admin_session_cookie_name,
            value=session_token,
            max_age=ttl_seconds,
            expires=ttl_seconds,
            path="/",
            secure=settings.admin_session_cookie_secure,
            httponly=True,
            samesite=settings.admin_session_cookie_samesite,
        )
    else:
        response.set_cookie(
            key=settings.admin_session_cookie_name,
            value=session_token,
            path="/",
            secure=settings.admin_session_cookie_secure,
            httponly=True,
            samesite=settings.admin_session_cookie_samesite,
        )
    return response


@router.post("/admin/v1/system/session/logout", response_model=AdminSessionLogoutResponse)
def logout_admin_session(request: Request) -> JSONResponse:
    """Revoke current admin cookie session and clear cookie."""
    auth_service = get_admin_auth_service(request)
    settings = request.app.state.settings
    session_token = request.cookies.get(settings.admin_session_cookie_name)
    auth_service.revoke_session(session_token=session_token)
    response = JSONResponse(
        content=AdminSessionLogoutResponse(status="ok").model_dump(mode="json")
    )
    response.delete_cookie(
        key=settings.admin_session_cookie_name,
        path="/",
        secure=settings.admin_session_cookie_secure,
        httponly=True,
        samesite=settings.admin_session_cookie_samesite,
    )
    return response
