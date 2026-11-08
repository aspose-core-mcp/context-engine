"""HTTP middleware for request correlation, logging, and metrics."""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from adcs.api.admin_auth import AdminAuthError, AdminKeyPrincipal, get_admin_auth_service
from adcs.api.metrics import InMemoryMetrics
from adcs.api.webmcp_audit import InMemoryWebMCPWriteAuditStore, WebMCPWriteAuditStatus
from adcs.ops.tracing import RequestSpanContext, TracingService

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"
_logger = logging.getLogger("adcs.api.requests")
_WEBMCP_WRITE_TOOL_BY_PATH = {
    "/webmcp/v1/tools/web_trigger_ingestion": "web_trigger_ingestion",
    "/webmcp/v1/tools/web_trigger_reindex": "web_trigger_reindex",
    "/webmcp/v1/tools/web_promote_snapshot": "web_promote_snapshot",
}


def _emit_request_log(
    *,
    event: str,
    method: str,
    path: str,
    status: int | str,
    latency_ms: float,
    request_id: str,
) -> None:
    payload = {
        "event": event,
        "method": method,
        "path": path,
        "status": status,
        "latency_ms": round(latency_ms, 3),
        "request_id": request_id,
    }
    _logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _observe_request_metric(
    request: Request,
    *,
    method: str,
    path: str,
    status_code: int,
    latency_seconds: float,
) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, InMemoryMetrics):
        metrics.observe_request(
            method=method,
            path=path,
            status_code=status_code,
            latency_seconds=latency_seconds,
        )
    # HTTP counters are recorded once, above, into the stdlib registry. Feeding a
    # second prometheus_client copy of the same families duplicated their `# TYPE`
    # lines in the concatenated /metrics output.


def _resolve_actor_key_id_for_webmcp_audit(request: Request) -> str:
    principal = getattr(request.state, "admin_principal", None)
    if isinstance(principal, AdminKeyPrincipal):
        return principal.key_id
    api_key = request.headers.get("x-api-key")
    if api_key is None:
        return "unknown"
    try:
        auth_service = get_admin_auth_service(request)
        resolved = auth_service.authenticate(api_key=api_key)
    except (AdminAuthError, RuntimeError):
        return "unknown"
    return resolved.key_id


def _record_webmcp_validation_audit_if_needed(
    *,
    request: Request,
    response: Response,
) -> None:
    if request.method != "POST":
        return
    tool_name = _WEBMCP_WRITE_TOOL_BY_PATH.get(request.url.path)
    if tool_name is None:
        return
    if response.status_code not in {400, 422}:
        return
    if bool(getattr(request.state, "webmcp_write_audit_recorded", False)):
        return
    store = getattr(request.app.state, "webmcp_write_audit_store", None)
    if not isinstance(store, InMemoryWebMCPWriteAuditStore):
        return
    store.record(
        tool_name=tool_name,
        status=WebMCPWriteAuditStatus.REJECTED,
        actor_key_id=_resolve_actor_key_id_for_webmcp_audit(request),
        request_id=getattr(request.state, "request_id", None),
        reason=None,
        confirm_token=None,
        target={"path": request.url.path, "method": request.method},
        error_code="VALIDATION_ERROR",
    )
    request.state.webmcp_write_audit_recorded = True


async def request_context_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Attach/propagate request id and record baseline telemetry."""
    request_id = request.headers.get(REQUEST_ID_HEADER, "").strip() or str(uuid4())
    request.state.request_id = request_id
    request.state.correlation_id = request_id

    method = request.method
    path = request.url.path
    _emit_request_log(
        event="request_start",
        method=method,
        path=path,
        status="started",
        latency_ms=0.0,
        request_id=request_id,
    )

    started_at = time.perf_counter()
    tracing_service = getattr(request.app.state, "tracing_service", None)
    trace_context = (
        tracing_service.start_request_span(
            name=f"{method} {path}",
            attributes={
                "http.method": method,
                "http.route": path,
                "adcs.request_id": request_id,
            },
        )
        if isinstance(tracing_service, TracingService)
        else RequestSpanContext(_context_manager=None, _span=None, trace_id=None)
    )
    request.state.trace_id = trace_context.trace_id or request_id

    try:
        with trace_context:
            response = await call_next(request)
    except Exception:
        latency_seconds = time.perf_counter() - started_at
        _observe_request_metric(
            request,
            method=method,
            path=path,
            status_code=500,
            latency_seconds=latency_seconds,
        )
        _emit_request_log(
            event="request_finish",
            method=method,
            path=path,
            status=500,
            latency_ms=latency_seconds * 1000.0,
            request_id=request_id,
        )
        raise

    latency_seconds = time.perf_counter() - started_at
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[TRACE_ID_HEADER] = getattr(request.state, "trace_id", request_id)
    _record_webmcp_validation_audit_if_needed(request=request, response=response)
    _observe_request_metric(
        request,
        method=method,
        path=path,
        status_code=response.status_code,
        latency_seconds=latency_seconds,
    )
    _emit_request_log(
        event="request_finish",
        method=method,
        path=path,
        status=response.status_code,
        latency_ms=latency_seconds * 1000.0,
        request_id=request_id,
    )
    return response
