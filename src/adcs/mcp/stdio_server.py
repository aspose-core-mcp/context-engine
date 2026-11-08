"""ADCS MCP server — stdio transport (JSON-RPC over stdin/stdout).

This module is the **stdio MCP server entry point** for ADCS. It serves
the Model Context Protocol over a JSON-lines stdio channel so that
AI-IDEs (Claude Code, Cursor, Codex CLI, Antigravity, Qwen-Code, and any
other MCP-compatible client) can call the public ADCS retrieval tools
locally without an HTTP layer.

Standard MCP clients use ``initialize`` (with ``protocolVersion``),
``notifications/initialized``, ``tools/list``, ``tools/call`` and ``ping``.
The ADCS-specific ``tools/<tool_name>`` methods with an explicit
``session_id`` remain available. stdout carries protocol messages only;
logs go to stderr.

The protocol is implemented directly over JSON-RPC; ADCS does not depend
on the external ``mcp`` / ``FastMCP`` Python SDK. Console-script entry:
``adcs-mcp-stdio`` (registered in ``pyproject.toml`` under
``[project.scripts]``).

Companion HTTP MCP server lives in :mod:`adcs.api.mcp_gateway`; tool
dispatch in :mod:`adcs.mcp.tool_gateway`; revision handshake in
:mod:`adcs.mcp.revision_negotiation`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from collections.abc import Callable
from typing import Any, TextIO, cast
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field, ValidationError

from adcs.api.error_codes import (
    DEPENDENCY_UNAVAILABLE,
    INVALID_ARGUMENT,
    NOT_FOUND,
    TIMEOUT,
)
from adcs.api.error_messages import public_error_message
from adcs.indexing.symbol_resolution import SymbolNotFoundError
from adcs.mcp.tool_gateway import MCPToolError, MCPToolGateway

logger = logging.getLogger(__name__)

_SERVER_INFO = {"name": "adcs-mcp", "version": "v1"}


class MCPStdioRequest(BaseModel):
    id: str | int | None = None
    method: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class MCPStdioTransport:
    """Local stdio adapter with one JSON-RPC message per line."""

    def __init__(
        self,
        *,
        gateway: MCPToolGateway,
        language_enum: Callable[[], list[str] | None] | None = None,
    ) -> None:
        self._gateway = gateway
        self._language_enum = language_enum
        self._session_id: str | None = None

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if isinstance(method, str) and method.startswith("notifications/"):
            # Notifications carry no id and must not be answered.
            return None
        try:
            request = MCPStdioRequest.model_validate(message)
        except ValidationError as exc:
            return _error_payload(
                request_id=message.get("id"),
                code=INVALID_ARGUMENT,
                message=public_error_message(
                    exc,
                    fallback="The request could not be processed as given.",
                    context="mcp_stdio:INVALID_ARGUMENT",
                ),
            )

        try:
            return self._dispatch(request)
        except Exception as exc:
            logger.exception(
                "Unexpected error in stdio handle_message: %s", exc,
            )
            return _jsonrpc_error_payload(
                request_id=request.id,
                code=-32603,
                message=f"Internal error: {exc}",
            )

    def _dispatch(self, request: MCPStdioRequest) -> dict[str, Any]:
        method = request.method.strip()
        if method == "initialize":
            return self._initialize(request)
        if method == "ping":
            return _ok_payload(request_id=request.id, result={})
        if method == "tools/list":
            # Imported here: adcs.api.mcp_gateway imports the adcs.mcp package.
            from adcs.api.mcp_gateway import _streamable_tools_manifest

            language_enum = self._language_enum() if self._language_enum else None
            return _ok_payload(
                request_id=request.id,
                result={"tools": _streamable_tools_manifest(language_enum=language_enum)},
            )
        if method == "tools/call":
            return self._standard_tool_call(request)

        if method.startswith("tools/"):
            tool_name = method.removeprefix("tools/").strip()
            if not tool_name:
                return _error_payload(
                    request_id=request.id,
                    code=INVALID_ARGUMENT,
                    message="Tool name is required.",
                )

            session_id = request.params.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                return _error_payload(
                    request_id=request.id,
                    code=INVALID_ARGUMENT,
                    message="session_id is required and must be a non-empty string.",
                )

            arguments = request.params.get("arguments", {})
            if not isinstance(arguments, dict):
                return _error_payload(
                    request_id=request.id,
                    code=INVALID_ARGUMENT,
                    message="arguments must be an object.",
                )

            result, failure = self._call_tool(
                session_id=session_id, tool_name=tool_name, arguments=arguments
            )
            if failure is not None:
                return _error_payload(
                    request_id=request.id, code=failure[0], message=failure[1],
                    details=failure[2] if len(failure) > 2 else None,
                )
            return _ok_payload(request_id=request.id, result={"result": result})

        return _error_payload(
            request_id=request.id,
            code=INVALID_ARGUMENT,
            message=f"Unsupported MCP stdio method: {method!r}",
        )

    def _initialize(self, request: MCPStdioRequest) -> dict[str, Any]:
        # Standard MCP clients send `protocolVersion`; ADCS-specific clients send
        # `protocol_revision` and read the ADCS handshake fields.
        standard = "protocolVersion" in request.params
        field = "protocolVersion" if standard else "protocol_revision"
        protocol_revision_value = request.params.get(field)
        if protocol_revision_value is not None and not isinstance(protocol_revision_value, str):
            return _error_payload(
                request_id=request.id,
                code=INVALID_ARGUMENT,
                message=f"{field} must be a string when provided.",
            )
        response = self._gateway.initialize(requested_revision=protocol_revision_value)
        self._session_id = response.session_id
        handshake = {
            "session_id": response.session_id,
            "negotiated_revision": response.negotiated_revision,
            "fallback_applied": response.fallback_applied,
            "fallback_reason": response.fallback_reason.value,
        }
        if standard:
            result = {
                "protocolVersion": response.negotiated_revision,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": _SERVER_INFO,
                **handshake,
            }
        else:
            result = {**handshake, "capabilities": response.capabilities}
        return _ok_payload(request_id=request.id, result=result)

    def _standard_tool_call(self, request: MCPStdioRequest) -> dict[str, Any]:
        tool_name = request.params.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return _standard_error_payload(
                request_id=request.id,
                code=INVALID_ARGUMENT,
                message="tools/call requires `name` string parameter.",
            )
        arguments = request.params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _standard_error_payload(
                request_id=request.id,
                code=INVALID_ARGUMENT,
                message="arguments must be an object.",
            )
        session_id = request.params.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            session_id = self._current_session()

        result, failure = self._call_tool(
            session_id=session_id, tool_name=tool_name.strip(), arguments=arguments
        )
        if failure is not None:
            return _standard_error_payload(
                request_id=request.id, code=failure[0], message=failure[1],
                details=failure[2] if len(failure) > 2 else None,
            )
        text = json.dumps(result, ensure_ascii=True, separators=(",", ":"))
        return _ok_payload(
            request_id=request.id,
            result={
                "content": [{"type": "text", "text": text}],
                "structuredContent": result,
                "isError": False,
            },
        )

    def _current_session(self) -> str:
        """Session opened by `initialize`, or a new one for clients that skip it."""
        if self._session_id is None:
            self._session_id = self._gateway.initialize(requested_revision=None).session_id
        return self._session_id

    def _call_tool(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, tuple[str, str] | tuple[str, str, dict[str, object]] | None]:
        """Call one tool; return (result, None) or (None, (error_code, message))."""
        try:
            result = self._gateway.call_tool(
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
            )
        except KeyError as exc:
            return None, (
                NOT_FOUND,
                public_error_message(
                    exc,
                    fallback="The requested resource was not found.",
                    context="mcp_stdio:NOT_FOUND",
                ),
            )
        except (MCPToolError, ValueError) as exc:
            return None, (
                INVALID_ARGUMENT,
                public_error_message(
                    exc,
                    fallback="The request could not be processed as given.",
                    context="mcp_stdio:INVALID_ARGUMENT",
                ),
            )
        except SymbolNotFoundError as exc:
            return None, (
                NOT_FOUND,
                public_error_message(
                    exc, fallback="The requested symbol was not found.",
                    context="mcp_stdio:NOT_FOUND",
                ),
                exc.details,
            )
        except LookupError as exc:
            return None, (
                NOT_FOUND,
                public_error_message(
                    exc,
                    fallback="The requested resource was not found.",
                    context="mcp_stdio:NOT_FOUND",
                ),
            )
        except RuntimeError as exc:
            return None, (
                DEPENDENCY_UNAVAILABLE,
                public_error_message(
                    exc,
                    fallback="A required backend is unavailable. Retry shortly.",
                    context="mcp_stdio:DEPENDENCY_UNAVAILABLE",
                ),
            )
        except TimeoutError as exc:
            return None, (
                TIMEOUT,
                public_error_message(
                    exc,
                    fallback="The request timed out. Retry shortly.",
                    context="mcp_stdio:TIMEOUT",
                ),
            )
        return result, None

    def process_line(self, line: str) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            response = _error_payload(
                request_id=None,
                code=INVALID_ARGUMENT,
                message=f"Invalid JSON payload: {exc.msg}",
            )
            return json.dumps(response, ensure_ascii=True, separators=(",", ":"))

        if not isinstance(payload, dict):
            response = _error_payload(
                request_id=None,
                code=INVALID_ARGUMENT,
                message="Top-level payload must be a JSON object.",
            )
            return json.dumps(response, ensure_ascii=True, separators=(",", ":"))

        message_response = self.handle_message(payload)
        if message_response is None:
            return None
        return json.dumps(message_response, ensure_ascii=True, separators=(",", ":"))

    def run(self, *, input_stream: TextIO, output_stream: TextIO) -> int:
        for line in input_stream:
            encoded = self.process_line(line)
            if encoded is None:
                continue
            output_stream.write(encoded)
            output_stream.write("\n")
            output_stream.flush()
        return 0


def build_stdio_transport() -> MCPStdioTransport:
    from adcs.api.main import create_app

    app: FastAPI = create_app()
    gateway = cast(MCPToolGateway, app.state.mcp_tool_gateway)
    symbol_service = getattr(app.state, "apiref_symbol_service", None)

    def _language_enum() -> list[str] | None:
        if symbol_service is None:
            return None
        try:
            languages = symbol_service.vocabulary().all_languages()
        except Exception:
            logger.warning("Could not build served language enum for tools/list", exc_info=True)
            return None
        return list(languages) if languages else None

    return MCPStdioTransport(gateway=gateway, language_enum=_language_enum)


def main() -> int:
    # stdout carries protocol messages only. Building the app configures logging with
    # handlers bound to sys.stdout, so build it while stdout points at stderr: the log
    # handlers, and any stray output during start-up, end up on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        transport = build_stdio_transport()
    return transport.run(input_stream=sys.stdin, output_stream=sys.stdout)


def _ok_payload(*, request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_payload(
    *,
    request_id: str | int | None,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> dict[str, Any]:
    # stdio has no HTTP middleware to mint a request id, so mint one here and log
    # it: the id in the error envelope then matches a server-side log line.
    correlation_id = _log_error(request_id=request_id, code=code)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": correlation_id,
        },
    }


def _standard_error_payload(
    *,
    request_id: str | int | None,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> dict[str, Any]:
    """JSON-RPC error with a numeric code, as the streamable HTTP transport returns."""
    from adcs.api.mcp_gateway import _streamable_error_code

    correlation_id = _log_error(request_id=request_id, code=code)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": _streamable_error_code(code),
            "message": message,
            "data": {"adcs_code": code, "request_id": correlation_id, "details": details or {}},
        },
    }


def _log_error(*, request_id: str | int | None, code: str) -> str:
    correlation_id = str(uuid4())
    logger.warning(
        json.dumps(
            {
                "event": "mcp_stdio_error",
                "request_id": correlation_id,
                "message_id": request_id,
                "code": code,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return correlation_id


def _jsonrpc_error_payload(
    *,
    request_id: str | int | None,
    code: int,
    message: str,
) -> dict[str, Any]:
    """Return a JSON-RPC 2.0 numeric-code error envelope (e.g. -32603 INTERNAL_ERROR)."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
