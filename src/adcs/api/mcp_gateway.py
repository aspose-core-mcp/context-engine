"""ADCS MCP server — HTTP transport (streamable-http + SSE).

This module is the **HTTP MCP server gateway** for ADCS. It mounts under
``/mcp`` on the public FastAPI app and serves the Model Context Protocol
over HTTP for hosted/remote AI-IDE clients. The implementation is a
custom JSON-RPC layer — ADCS does not depend on the external ``mcp`` /
``FastMCP`` Python SDK.

Supported MCP transports here:

* ``streamable-http`` — POST request → JSON response (one round-trip)
* ``sse`` — POST request → Server-Sent Events stream (multi-message)

Protocol revision handshake supports ``2025-11-25``, ``2025-06-18``,
and ``2024-11-05``; mismatches are reconciled by
:func:`adcs.mcp.revision_negotiation.negotiate_mcp_revision`.

Companion stdio MCP server lives in :mod:`adcs.mcp.stdio_server`; tool
dispatch in :mod:`adcs.mcp.tool_gateway`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from adcs.api.abuse_guard import AbuseGuardDecision, AbuseGuardService
from adcs.api.error_codes import (
    DEPENDENCY_UNAVAILABLE,
    HTTP_STATUS_BY_CODE,
    INVALID_ARGUMENT,
    NOT_FOUND,
    RATE_LIMITED,
    TIMEOUT,
)
from adcs.api.error_messages import public_error_message
from adcs.api.metrics import InMemoryMetrics
from adcs.mcp.product_scope import (
    TEX_NET_SCOPE,
    TOTAL_NET_SCOPE,
    WORDS_NET_SCOPE,
    MCPProductGroup,
    MCPProductScope,
)
from adcs.mcp.tool_gateway import MCPToolError

logger = logging.getLogger("adcs.mcp_gateway")

router = APIRouter(tags=["mcp-gateway"])


class MCPInitializeRequest(BaseModel):
    protocol_revision: str | None = None


class MCPInitializeResponseModel(BaseModel):
    session_id: str
    negotiated_revision: str
    fallback_applied: bool
    fallback_reason: str
    capabilities: dict[str, Any]


class MCPToolCallRequest(BaseModel):
    session_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallResponseModel(BaseModel):
    result: dict[str, Any]


class MCPStreamableHttpRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/mcp/v1/initialize", response_model=MCPInitializeResponseModel)
async def mcp_initialize(
    request_payload: MCPInitializeRequest,
    request: Request,
) -> MCPInitializeResponseModel:
    return await _initialize_payload(request_payload=request_payload, request=request)


@router.post(
    "/mcp/v1/streamable-http/initialize",
    response_model=MCPInitializeResponseModel,
)
async def mcp_streamable_http_initialize(
    request_payload: MCPInitializeRequest,
    request: Request,
) -> MCPInitializeResponseModel:
    """Streamable-HTTP alias for MCP initialize."""
    return await _initialize_payload(request_payload=request_payload, request=request)


@router.post("/mcp/v1/sse/initialize")
async def mcp_sse_initialize(
    request_payload: MCPInitializeRequest,
    request: Request,
) -> StreamingResponse:
    """SSE transport adapter for MCP initialize."""
    try:
        payload = await _initialize_payload(request_payload=request_payload, request=request)
    except HTTPException as exc:
        return _sse_error_response(detail=exc.detail)
    return _sse_response(event="initialize", payload=payload.model_dump())


@router.post("/mcp/v1/tools/{tool_name}", response_model=MCPToolCallResponseModel)
async def mcp_call_tool(
    tool_name: str,
    request_payload: MCPToolCallRequest,
    request: Request,
) -> MCPToolCallResponseModel:
    return await _tool_call_payload(
        tool_name=tool_name,
        request_payload=request_payload,
        request=request,
    )


@router.post(
    "/mcp/v1/streamable-http/tools/{tool_name}",
    response_model=MCPToolCallResponseModel,
)
async def mcp_streamable_http_call_tool(
    tool_name: str,
    request_payload: MCPToolCallRequest,
    request: Request,
) -> MCPToolCallResponseModel:
    """Streamable-HTTP alias for MCP tool call."""
    return await _tool_call_payload(
        tool_name=tool_name,
        request_payload=request_payload,
        request=request,
    )


@router.post("/mcp/v1/sse/tools/{tool_name}")
async def mcp_sse_call_tool(
    tool_name: str,
    request_payload: MCPToolCallRequest,
    request: Request,
) -> StreamingResponse:
    """SSE transport adapter for MCP tool call."""
    try:
        payload = await _tool_call_payload(
            tool_name=tool_name,
            request_payload=request_payload,
            request=request,
        )
    except HTTPException as exc:
        return _sse_error_response(detail=exc.detail)
    return _sse_response(event="tool_result", payload=payload.model_dump())


@router.get("/total/net/mcp/v1/streamable-http")
@router.get("/tex/net/mcp/v1/streamable-http")
@router.get("/words/net/mcp/v1/streamable-http")
@router.get("/mcp/v1/streamable-http")
async def mcp_streamable_http_sse(request: Request) -> StreamingResponse:
    """GET handler for MCP Streamable HTTP SSE stream.

    Per the MCP spec (2025-03-26), servers supporting streamable-http MUST
    respond to GET with either text/event-stream or 405.  Some clients
    (e.g. Qwen CLI) attempt GET first and treat 405 as a connection failure.
    This handler keeps an SSE stream open until the client disconnects.
    """
    logger.info("MCP SSE stream opened by client")

    async def _keepalive() -> AsyncIterator[bytes]:
        import asyncio as _asyncio

        # Send an initial comment so the client knows the stream is alive.
        yield b": ok\n\n"
        try:
            while True:
                await _asyncio.sleep(30)
                yield b": keepalive\n\n"
        except _asyncio.CancelledError:
            return

    return StreamingResponse(
        _keepalive(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/total/net/mcp/v1/streamable-http", response_model=None)
async def total_net_streamable_http(
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> Response:
    request.state.mcp_product_scope = TOTAL_NET_SCOPE
    return await mcp_streamable_http_jsonrpc(request_payload=request_payload, request=request)


@router.post("/tex/net/mcp/v1/streamable-http", response_model=None)
async def tex_net_streamable_http(
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> Response:
    request.state.mcp_product_scope = TEX_NET_SCOPE
    return await mcp_streamable_http_jsonrpc(request_payload=request_payload, request=request)


@router.post("/words/net/mcp/v1/streamable-http", response_model=None)
async def words_net_streamable_http(
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> Response:
    # Scope is selected by the route, never by client headers or session tokens.
    request.state.mcp_product_scope = WORDS_NET_SCOPE
    return await mcp_streamable_http_jsonrpc(request_payload=request_payload, request=request)


@router.post("/mcp/v1/streamable-http", response_model=None)
async def mcp_streamable_http_jsonrpc(
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> Response:
    method = request_payload.method.strip()

    if method == "initialize":
        return await _streamable_initialize(request_payload=request_payload, request=request)

    if method == "notifications/initialized":
        return _streamable_notification_response()

    if method == "ping":
        return _streamable_success_response(
            request_id=request_payload.id,
            result={},
        )

    if method == "tools/list":
        return await _streamable_tools_list(request_payload=request_payload, request=request)

    if method == "tools/call":
        return await _streamable_tools_call(request_payload=request_payload, request=request)

    if method.startswith("tools/"):
        tool_name = method.removeprefix("tools/").strip()
        return await _streamable_tools_call(
            request_payload=request_payload,
            request=request,
            tool_name_override=tool_name,
        )

    return _streamable_error_response(
        request_id=request_payload.id,
        code=INVALID_ARGUMENT,
        message=f"Unsupported streamable-http method: {method!r}",
        details={"method": method},
    )


async def _initialize_payload(
    *,
    request_payload: MCPInitializeRequest,
    request: Request,
) -> MCPInitializeResponseModel:
    _enforce_abuse_guard(request)
    gateway = request.app.state.mcp_tool_gateway
    response = gateway.initialize(requested_revision=request_payload.protocol_revision)
    return MCPInitializeResponseModel(
        session_id=response.session_id,
        negotiated_revision=response.negotiated_revision,
        fallback_applied=response.fallback_applied,
        fallback_reason=response.fallback_reason.value,
        capabilities=response.capabilities,
    )


async def _tool_call_payload(
    *,
    tool_name: str,
    request_payload: MCPToolCallRequest,
    request: Request,
) -> MCPToolCallResponseModel:
    _enforce_abuse_guard(request)
    logger.info(
        "MCP tool_call: tool=%s args=%s session=%s",
        tool_name,
        json.dumps(request_payload.arguments, ensure_ascii=False, default=str)[:500],
        request_payload.session_id[:12],
    )
    gateway = request.app.state.mcp_tool_gateway
    try:
        result = await asyncio.to_thread(
            gateway.call_tool,
            session_id=request_payload.session_id,
            tool_name=tool_name,
            arguments=request_payload.arguments,
            scope=getattr(request.state, "mcp_product_scope", None),
        )
    except KeyError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:NOT_FOUND",
            ),
        ) from exc
    except (MCPToolError, ValueError) as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[INVALID_ARGUMENT],
            code=INVALID_ARGUMENT,
            message=public_error_message(
                exc,
                fallback="The request could not be processed as given.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:INVALID_ARGUMENT",
            ),
        ) from exc
    except LookupError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:NOT_FOUND",
            ),
        ) from exc
    except RuntimeError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message=public_error_message(
                exc,
                fallback="A required backend is unavailable. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:DEPENDENCY_UNAVAILABLE",
            ),
        ) from exc
    except TimeoutError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[TIMEOUT],
            code=TIMEOUT,
            message=public_error_message(
                exc,
                fallback="The request timed out. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:TIMEOUT",
            ),
        ) from exc

    return MCPToolCallResponseModel(result=result)


def _server_name(request: Request) -> str:
    scope = getattr(request.state, "mcp_product_scope", None)
    if scope is None:
        return "adcs-mcp"
    return f"{scope.product_id.replace('.', '-')}-{scope.language}-mcp"


async def _streamable_initialize(
    *,
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> JSONResponse:
    try:
        protocol_revision = _extract_streamable_protocol_revision(request_payload.params)
    except ValueError:
        return _streamable_error_response(
            request_id=request_payload.id,
            code=INVALID_ARGUMENT,
            message="protocolVersion must be a string when provided.",
            details={"field": "protocolVersion"},
        )

    try:
        initialize_payload = await _initialize_payload(
            request_payload=MCPInitializeRequest(protocol_revision=protocol_revision),
            request=request,
        )
    except HTTPException as exc:
        return _streamable_error_from_http_exception(request_id=request_payload.id, exc=exc)

    return _streamable_success_response(
        request_id=request_payload.id,
        result={
            "protocolVersion": initialize_payload.negotiated_revision,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": _server_name(request),
                "version": "v1",
            },
            "session_id": initialize_payload.session_id,
            "negotiated_revision": initialize_payload.negotiated_revision,
            "fallback_applied": initialize_payload.fallback_applied,
            "fallback_reason": initialize_payload.fallback_reason,
        },
        headers={"mcp-session-id": initialize_payload.session_id},
    )


async def _streamable_tools_list(
    *,
    request_payload: MCPStreamableHttpRequest,
    request: Request,
) -> JSONResponse:
    try:
        session_id = await _ensure_streamable_session(
            request=request,
            params=request_payload.params,
        )
    except HTTPException as exc:
        return _streamable_error_from_http_exception(request_id=request_payload.id, exc=exc)

    scope = getattr(request.state, "mcp_product_scope", None)
    manifest = _streamable_tools_manifest(
        language_enum=[scope.language] if scope else _served_language_enum(request)
    )
    if scope is not None:
        manifest = _scoped_tools_manifest(
            manifest, scope=scope,
            supported_tools=request.app.state.mcp_tool_gateway.supported_tools(),
        )
    return _streamable_success_response(
        request_id=request_payload.id,
        result={"tools": manifest},
        headers={"mcp-session-id": session_id},
    )


def _served_language_enum(request: Request) -> list[str] | None:
    """Served language tokens for the tool-schema enum, or None if unavailable.

    Never raises into tools/list: a store hiccup just omits the enum (the schema
    stays a plain string and the server still normalises on call).
    """
    service = getattr(request.app.state, "apiref_symbol_service", None)
    if service is None:
        return None
    try:
        return service.vocabulary().all_languages() or None
    except Exception:
        logger.warning("Could not build served language enum for tools/list", exc_info=True)
        return None


async def _streamable_tools_call(
    *,
    request_payload: MCPStreamableHttpRequest,
    request: Request,
    tool_name_override: str | None = None,
) -> JSONResponse:
    params = request_payload.params
    tool_name = _extract_streamable_tool_name(params=params, tool_name_override=tool_name_override)
    if tool_name is None:
        return _streamable_error_response(
            request_id=request_payload.id,
            code=INVALID_ARGUMENT,
            message="tools/call requires `name` string parameter.",
            details={"field": "name"},
        )

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _streamable_error_response(
            request_id=request_payload.id,
            code=INVALID_ARGUMENT,
            message="arguments must be an object.",
            details={"field": "arguments"},
        )

    try:
        session_id = await _ensure_streamable_session(request=request, params=params)
        payload = await _tool_call_payload(
            tool_name=tool_name,
            request_payload=MCPToolCallRequest(session_id=session_id, arguments=arguments),
            request=request,
        )
    except HTTPException as exc:
        return _streamable_error_from_http_exception(request_id=request_payload.id, exc=exc)

    text_result = json.dumps(payload.result, ensure_ascii=True, separators=(",", ":"))
    return _streamable_success_response(
        request_id=request_payload.id,
        result={
            "result": payload.result,
            "structuredContent": payload.result,
            "content": [{"type": "text", "text": text_result}],
            "isError": False,
        },
        headers={"mcp-session-id": session_id},
    )


async def _ensure_streamable_session(*, request: Request, params: dict[str, Any]) -> str:
    requested = params.get("session_id")
    if isinstance(requested, str) and requested.strip():
        _ensure_mcp_session_exists(request=request, session_id=requested)
        return requested

    header_session_id = request.headers.get("mcp-session-id")
    if header_session_id and header_session_id.strip():
        _ensure_mcp_session_exists(request=request, session_id=header_session_id)
        return header_session_id

    try:
        protocol_revision = _extract_streamable_protocol_revision(params)
    except ValueError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[INVALID_ARGUMENT],
            code=INVALID_ARGUMENT,
            message=public_error_message(
                exc,
                fallback="The request could not be processed as given.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:INVALID_ARGUMENT",
            ),
        ) from exc

    initialize_payload = await _initialize_payload(
        request_payload=MCPInitializeRequest(protocol_revision=protocol_revision),
        request=request,
    )
    return initialize_payload.session_id


def _ensure_mcp_session_exists(*, request: Request, session_id: str) -> None:
    gateway = request.app.state.mcp_tool_gateway
    try:
        gateway.get_session(session_id=session_id)
    except KeyError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="mcp_gateway:NOT_FOUND",
            ),
        ) from exc


def _extract_streamable_protocol_revision(params: dict[str, Any]) -> str | None:
    protocol_version = params.get("protocolVersion")
    if protocol_version is None:
        protocol_version = params.get("protocol_revision")
    if protocol_version is None:
        return None
    if isinstance(protocol_version, str):
        value = protocol_version.strip()
        return value or None
    msg = "protocolVersion must be a string when provided."
    raise ValueError(msg)


def _extract_streamable_tool_name(
    *,
    params: dict[str, Any],
    tool_name_override: str | None,
) -> str | None:
    if tool_name_override is not None and tool_name_override.strip():
        return tool_name_override.strip()
    tool_name_value = params.get("name")
    if tool_name_value is None:
        tool_name_value = params.get("tool_name")
    if isinstance(tool_name_value, str):
        value = tool_name_value.strip()
        return value or None
    return None


# Shared, forgiving input schemas for the structured symbol tools: the server
# normalises product/language and defaults version, so the model can emit
# natural tokens and omit the version.
_VERSION_SCHEMA = {
    "type": "string",
    "description": "Version; defaults to 'latest-stable'. Omit unless targeting a version.",
}
_LANGUAGE_SCHEMA = {
    "type": "string",
    "description": (
        "SDK programming language. Use 'net' for C#/.NET. When an enum is shown, "
        "pick one of those served tokens; aliases (csharp, c#, dotnet, python) are "
        "also normalised server-side."
    ),
}
_PRODUCT_ID_SCHEMA = {
    "type": "string",
    "description": (
        "Product id, e.g. 'aspose.cells'. A bare name ('cells') or a close typo is "
        "accepted and normalised to the served product."
    ),
}


def _streamable_tools_manifest(
    *, language_enum: list[str] | None = None
) -> list[dict[str, Any]]:
    # When the served language tokens are known, constrain the structured
    # tools' `language` to that enum so a weak model is steered to 'net' rather
    # than 'csharp'. Aliases are still normalised server-side for clients that
    # do not validate against the advertised schema.
    language_schema: dict[str, Any] = (
        {**_LANGUAGE_SCHEMA, "enum": language_enum} if language_enum else _LANGUAGE_SCHEMA
    )
    return [
        {
            "name": "resolve_product",
            "description": (
                "Resolve a product name or alias into the canonical product_id and "
                "default SDK language. Call this FIRST before any other tool. "
                "Example: 'Aspose.OCR' → product_id='aspose.ocr', language='net'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": True,
            },
        },
        {
            "name": "query_docs",
            "description": (
                "Search Aspose documentation for guides, how-to articles, and API "
                "reference pages. Use this to understand how an API works before "
                "writing code. Make focused queries like 'create pivot table from "
                "data range' rather than broad queries like 'features'. "
                "Call MULTIPLE times for different aspects of your task."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Focused natural-language query describing what you need. "
                            "Be specific: 'batch OCR with preprocessing filters' is "
                            "better than 'OCR'."
                        ),
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Canonical product ID from resolve_product.",
                    },
                    "language": {
                        "type": "string",
                        "description": "SDK language: 'net', 'java', 'cpp', 'python', etc.",
                    },
                },
                "required": ["query", "product_id", "language"],
                "additionalProperties": True,
            },
        },
        {
            "name": "get_symbol_doc",
            "description": (
                "Look up the exact API signature, parameters, return type, and usage "
                "examples for a specific class or method. Use this to verify EVERY "
                "class/method you plan to use — do NOT guess signatures. "
                "Examples: 'BarcodeGenerator', 'RecognitionSettings', 'Document.Save', "
                "'PivotTable.AddFieldToArea'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Canonical product ID from resolve_product.",
                    },
                    "language": {
                        "type": "string",
                        "description": "SDK language: 'net', 'java', 'cpp', etc.",
                    },
                    "symbol_fqn": {
                        "type": "string",
                        "description": (
                            "Class or method name to look up, e.g. 'RecognitionSettings', "
                            "'AsposeOcr.Recognize', 'Workbook'."
                        ),
                    },
                },
                "required": ["product_id", "language", "symbol_fqn"],
                "additionalProperties": True,
            },
        },
        {
            "name": "list_breaking_changes",
            "description": (
                "List breaking API changes and deprecations between two product "
                "versions. Use when migrating code or targeting a specific version."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "language": {"type": "string"},
                    "from_version": {"type": "string"},
                    "to_version": {"type": "string"},
                },
                "required": ["product_id", "language", "from_version", "to_version"],
                "additionalProperties": True,
            },
        },
        {
            "name": "list_latest_release_features",
            "description": (
                "List new features, improvements, and migration hints from the "
                "latest (or specified) release of a product SDK."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "language": {"type": "string"},
                    "version": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["product_id", "language"],
                "additionalProperties": True,
            },
        },
        {
            "name": "aspose_lookup",
            "description": (
                "PREFERRED one-shot API lookup. Give a natural-language query (and, "
                "if you know them, product_id and language) and get grounded symbols "
                "back in a SINGLE call — no need to chain resolve_product → search → "
                "get_symbol. If the query names an exact dotted symbol (e.g. "
                "'Aspose.Cells.Workbook.Save') you get its full signature and all "
                "overloads; otherwise you get the top matching classes/methods WITH "
                "their signatures inline. product_id and language are optional: omit "
                "them and just name the product in the query (e.g. 'save a workbook "
                "as pdf in Aspose.Cells for C#') if unsure — they are normalised "
                "server-side. The response echoes resolved_product_id / "
                "resolved_language so you can see how it was interpreted."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What you need: a concept ('pivot table from range'), a "
                            "class/method name ('BarcodeGenerator'), or an exact dotted "
                            "FQN ('Aspose.Cells.Workbook.Save'). May also name the "
                            "product and language in prose."
                        ),
                    },
                    "product_id": _PRODUCT_ID_SCHEMA,
                    "language": language_schema,
                    "version": _VERSION_SCHEMA,
                    "limit": {"type": "integer", "description": "Max matches (default 10)."},
                },
                "required": ["query"],
                "additionalProperties": True,
            },
        },
        {
            "name": "get_symbol",
            "description": (
                "Exact API-reference symbol lookup from the structured symbol store "
                "(precise, non-vector). Returns ALL overloads of a fully-qualified "
                "member with signature, summary, parameters, returns, and examples. "
                "Use to verify the exact signature of a class/method before using it. "
                "member_fqn is dotted and case-insensitive, e.g. "
                "'Aspose.Cells.Workbook.Save' or 'aspose.email.MapiMessage'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": _PRODUCT_ID_SCHEMA,
                    "language": language_schema,
                    "version": _VERSION_SCHEMA,
                    "symbol_fqn": {"type": "string", "description": "Dotted FQN of the symbol."},
                },
                "required": ["product_id", "language", "symbol_fqn"],
                "additionalProperties": True,
            },
        },
        {
            "name": "list_members",
            "description": (
                "List the direct members (methods, properties, fields, nested types) of "
                "a class or namespace from the structured symbol store. Use to discover "
                "what operations a type offers. parent_fqn is the dotted class/namespace, "
                "e.g. 'Aspose.Cells.Workbook' or 'aspose.email.mapi'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": _PRODUCT_ID_SCHEMA,
                    "language": language_schema,
                    "version": _VERSION_SCHEMA,
                    "parent_fqn": {"type": "string", "description": "Dotted class/namespace FQN."},
                },
                "required": ["product_id", "language", "parent_fqn"],
                "additionalProperties": True,
            },
        },
        {
            "name": "search_symbols",
            "description": (
                "Search API symbols by name or concept (prefix/fuzzy + full-text) in the "
                "structured symbol store. Use to find the right class/method when you "
                "don't know the exact name, e.g. query 'Workbook', 'save as pdf', "
                "'pivot table'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": _PRODUCT_ID_SCHEMA,
                    "language": language_schema,
                    "version": _VERSION_SCHEMA,
                    "query": {"type": "string", "description": "Name or concept to search for."},
                    "limit": {"type": "integer", "description": "Max results (default 20)."},
                },
                "required": ["product_id", "language", "query"],
                "additionalProperties": True,
            },
        },
    ]


def _scoped_tools_manifest(
    manifest: list[dict[str, Any]], *, scope: MCPProductScope | MCPProductGroup,
    supported_tools: tuple[str, ...],
) -> list[dict[str, Any]]:
    tools = [tool for tool in manifest if tool["name"] in supported_tools]
    for tool in tools:
        schema = tool["inputSchema"]
        for field, value in (("product_id", scope.product_id), ("language", scope.language)):
            schema["properties"][field] = {
                "type": "string", "enum": [value], "default": value,
                "description": f"Fixed by this endpoint; omit or use {value!r}.",
            }
        schema["required"] = [
            field for field in schema.get("required", [])
            if field not in {"product_id", "language"}
        ]
        tool["description"] = f"{scope.title} only. " + tool["description"]
        if tool["name"] == "resolve_product":
            tool["description"] = f"Return this endpoint's fixed scope: {scope.title}."
            schema["required"] = []
            schema["properties"]["query"]["description"] = (
                "Optional context; does not change this endpoint's fixed scope."
            )
        elif tool["name"] == "aspose_lookup":
            tool["description"] = (
                f"Look up API symbols and signatures for {scope.title}. "
                "Provide a natural-language query or dotted symbol name. "
                "Product and SDK language are fixed by this endpoint."
            )
    if isinstance(scope, MCPProductGroup):
        for tool in tools:
            schema = tool["inputSchema"]
            schema["properties"]["product_id"] = {
                "type": "string", "enum": [member.product_id for member in scope.members],
                "description": "Omit to query all configured products, or select one product.",
            }
            tool["description"] = (
                f"{tool['name']} for {scope.title}: "
                + ", ".join(member.title for member in scope.members) + ". "
                "Omit product_id to query all members: results_by_product contains one "
                "product_id and result (or not_found) per product. "
                "Limits and pagination apply per product. Select product_id for "
                "the normal single-product response."
            )
            if tool["name"] == "resolve_product":
                tool["description"] = (
                    "List this endpoint's allowed products and fixed .NET language. "
                    "Select product_id to return one product's scope. "
                    "Optional query text does not change the allowed products."
                )
    return tools


def _streamable_notification_response() -> Response:
    return Response(status_code=202)


def _streamable_success_response(
    *,
    request_id: str | int | None,
    result: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        },
        headers=headers,
    )


def _streamable_error_from_http_exception(
    *,
    request_id: str | int | None,
    exc: HTTPException,
) -> JSONResponse:
    detail: dict[str, Any] = {}
    if isinstance(exc.detail, dict):
        detail = exc.detail
    error = detail.get("error", {}) if isinstance(detail, dict) else {}
    code = error.get("code", "INTERNAL")
    message = error.get("message", str(exc.detail))
    details = error.get("details", {})
    return _streamable_error_response(
        request_id=request_id,
        code=str(code),
        message=str(message),
        details=details if isinstance(details, dict) else {},
    )


def _streamable_error_response(
    *,
    request_id: str | int | None,
    code: str,
    message: str,
    details: dict[str, Any],
) -> JSONResponse:
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": _streamable_error_code(code),
                "message": message,
                "data": {"adcs_code": code, "details": details},
            },
        }
    )


def _streamable_error_code(code: str) -> int:
    if code == INVALID_ARGUMENT:
        return -32602
    if code == NOT_FOUND:
        return -32004
    if code == RATE_LIMITED:
        return -32029
    return -32603


def _sse_response(*, event: str, payload: dict[str, Any]) -> StreamingResponse:
    body = _format_sse_event(event=event, payload=payload)

    async def _stream() -> AsyncIterator[bytes]:
        yield body

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _sse_error_response(*, detail: object) -> StreamingResponse:
    payload: dict[str, Any]
    if isinstance(detail, dict):
        payload = detail
    else:
        payload = {
            "error": {
                "code": "INTERNAL",
                "message": str(detail),
                "details": {},
                "request_id": None,
            }
        }
    return _sse_response(event="error", payload=payload)


def _abuse_guard_service(request: Request) -> AbuseGuardService | None:
    service = getattr(request.app.state, "abuse_guard_service", None)
    if isinstance(service, AbuseGuardService):
        return service
    return None


def _observe_abuse_guard_decision(*, request: Request, decision: AbuseGuardDecision) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, InMemoryMetrics):
        metrics.observe_abuse_guard_decision(
            mode=decision.mode.value,
            decision=decision.reason,
        )


def _enforce_abuse_guard(request: Request) -> AbuseGuardDecision | None:
    service = _abuse_guard_service(request)
    if service is None:
        return None
    decision = service.evaluate_request(request=request)
    _observe_abuse_guard_decision(request=request, decision=decision)
    if decision.blocked:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[RATE_LIMITED],
            code=RATE_LIMITED,
            message="Request throttled by abuse guard policy.",
        )
    return decision


def _format_sse_event(*, event: str, payload: dict[str, Any]) -> bytes:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return f"event: {event}\ndata: {serialized}\n\n".encode()


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    request_id = getattr(request.state, "request_id", None)
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            }
        },
    )
