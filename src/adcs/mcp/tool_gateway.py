"""ADCS MCP server — tool dispatch core.

Tool-dispatch core for the ADCS Model Context Protocol server. This
module maps incoming MCP ``tools/call`` requests to the five public
retrieval contracts (``resolve_product``, ``query_docs``,
``get_symbol_doc``, ``list_breaking_changes``,
``list_latest_release_features``). The same dispatch is shared by both
the stdio MCP server (:mod:`adcs.mcp.stdio_server`) and the HTTP MCP
gateway (:mod:`adcs.api.mcp_gateway`).

ADCS implements MCP tool dispatch directly — no dependency on the
external ``mcp`` / ``FastMCP`` Python SDK. The contract surface is
purpose-built for the retrieval domain and stays in lockstep with the
REST endpoints under ``/v1/`` (MCP/REST parity is a project invariant).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from adcs.api.apiref_symbol_query import (
    ApiRefSymbolService,
    GetSymbolRequest,
    ListMembersRequest,
    LookupRequest,
    SearchSymbolsRequest,
)
from adcs.api.public_docs_query import (
    GetSymbolDocRequest,
    ListBreakingChangesRequest,
    ListLatestReleaseFeaturesRequest,
    PublicQueryService,
    QueryDocsRequest,
    ResolveProductRequest,
)
from adcs.mcp.product_scope import MCPProductGroup, MCPProductScope
from adcs.mcp.revision_negotiation import (
    MCPFallbackReason,
    MCPRevisionNegotiationResult,
    negotiate_mcp_revision,
)

# MCP sessions are stateless: `initialize` issues a self-describing token that
# any replica can decode, so no shared session store is required. The prefix is
# versioned so the payload shape can evolve without breaking older tokens.
_SESSION_TOKEN_PREFIX = "mcps1"
_SESSION_TOKEN_VERSION = 1


class MCPToolError(ValueError):
    """Raised for unsupported tools or invalid MCP payloads."""


@dataclass(frozen=True, slots=True)
class MCPSessionContext:
    """Session context fixed to one negotiated MCP revision."""

    session_id: str
    negotiated_revision: str
    requested_revision: str | None
    fallback_applied: bool
    fallback_reason: MCPFallbackReason
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MCPInitializeResponse:
    """Initialize response payload exposed by MCP gateway."""

    session_id: str
    negotiated_revision: str
    fallback_applied: bool
    fallback_reason: MCPFallbackReason
    capabilities: dict[str, Any]


class MCPToolGateway:
    """In-process MCP tool gateway with revision negotiation and parity dispatch."""

    def __init__(
        self,
        *,
        public_query_service: PublicQueryService,
        supported_revisions: tuple[str, ...],
        primary_revision: str,
        negotiation_observer: Callable[[MCPRevisionNegotiationResult], None] | None = None,
        apiref_symbol_service: ApiRefSymbolService | None = None,
    ) -> None:
        self._public_query_service = public_query_service
        self._apiref_symbol_service = apiref_symbol_service
        self._supported_revisions = supported_revisions
        self._primary_revision = primary_revision
        self._negotiation_observer = negotiation_observer

    def initialize(self, *, requested_revision: str | None) -> MCPInitializeResponse:
        """Negotiate one session revision and issue a self-describing session token."""
        negotiation = negotiate_mcp_revision(
            requested_revision=requested_revision,
            supported_revisions=self._supported_revisions,
            primary_revision=self._primary_revision,
        )
        if self._negotiation_observer is not None:
            self._negotiation_observer(negotiation)
        session = _build_session_context(negotiation)
        return MCPInitializeResponse(
            session_id=session.session_id,
            negotiated_revision=session.negotiated_revision,
            fallback_applied=session.fallback_applied,
            fallback_reason=session.fallback_reason,
            capabilities={
                "tools": list(self.supported_tools()),
                "supported_revisions": list(self._supported_revisions),
            },
        )

    def supported_tools(self) -> tuple[str, ...]:
        tools = [
            "resolve_product",
            "query_docs",
            "get_symbol_doc",
            "list_breaking_changes",
            "list_latest_release_features",
        ]
        if self._apiref_symbol_service is not None:
            # Structured API-reference tools backed by the Postgres symbol store
            # (ADR-011). ``aspose_lookup`` is the single forgiving entry point
            # that collapses resolve→search→get into one call.
            tools.extend(("aspose_lookup", "get_symbol", "list_members", "search_symbols"))
        return tuple(tools)

    def get_session(self, *, session_id: str) -> MCPSessionContext:
        """Rebuild session context from the token issued by :meth:`initialize`.

        Sessions are deliberately **stateless**: the token carries the negotiated
        revision, so any replica can serve any tool call. Holding sessions in
        process memory meant that with more than one replica a tool call routed
        to a different pod than ``initialize`` failed with "session not found"
        (about half of all calls with two replicas), and the map also grew
        without bound because nothing ever evicted it.
        """
        try:
            return _decode_session_token(session_id)
        except (ValueError, KeyError, TypeError) as exc:
            msg = f"MCP session `{session_id}` was not found."
            raise KeyError(msg) from exc

    def call_tool(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        scope: MCPProductScope | MCPProductGroup | None = None,
    ) -> dict[str, Any]:
        """Dispatch one MCP tool call after session/revision negotiation."""
        self.get_session(session_id=session_id)
        if isinstance(scope, MCPProductGroup):
            selected = scope.select(arguments)
            if len(selected) == 1:
                return self.call_tool(
                    session_id=session_id, tool_name=tool_name,
                    arguments=arguments, scope=selected[0],
                )
            if tool_name == "resolve_product":
                return {
                    "product_id": None,
                    "language": scope.language,
                    "products": [member.product_id for member in selected],
                    "message": (
                        "Select product_id to narrow a call, or omit it to query all members."
                    ),
                }
            if tool_name not in self.supported_tools():
                raise MCPToolError(f"Unsupported MCP tool: {tool_name!r}")
            results: list[dict[str, Any]] = []
            for member in selected:
                try:
                    member_result = self.call_tool(
                        session_id=session_id, tool_name=tool_name,
                        arguments={**arguments, "product_id": member.product_id},
                        scope=member,
                    )
                    results.append({"product_id": member.product_id, "result": member_result})
                except LookupError:
                    # A missing symbol/release in one product must not hide the
                    # other product's results. Backend and validation errors propagate.
                    results.append({"product_id": member.product_id, "not_found": True})
            return {"language": scope.language, "results_by_product": results}
        if scope is not None:
            arguments = scope.apply(arguments)
            if tool_name == "resolve_product":
                return {
                    "product_id": scope.product_id,
                    "language": scope.language,
                    "aliases": [scope.product_id],
                    "confidence": 1.0,
                    "candidates": [{"product_id": scope.product_id, "confidence": 1.0}],
                }

        if tool_name == "resolve_product":
            resolve_request = ResolveProductRequest.model_validate(arguments)
            result = self._public_query_service.resolve_product(query=resolve_request.query)
            return {
                "product_id": result.product_id,
                "language": result.language,
                "aliases": list(result.aliases),
                "confidence": result.confidence,
                "candidates": [
                    {"product_id": c.product_id, "confidence": c.confidence}
                    for c in result.candidates
                ],
            }
        if tool_name == "query_docs":
            query_request = QueryDocsRequest.model_validate(arguments)
            # MCP consumers rarely specify version — relax strict mode to avoid
            # unnecessary fallback round-trips and empty results.
            if query_request.strict_version and query_request.version is None:
                query_request.strict_version = False
            query_response = self._public_query_service.query_docs(
                request=query_request, allow_language_fallback=scope is None
            )
            query_result = query_response.model_dump()
            # Inject usage guidance so LLM consumers make follow-up symbol lookups
            symbols_mentioned: list[str] = []
            for item in query_response.results:
                if item.title and item.title not in symbols_mentioned:
                    symbols_mentioned.append(item.title)
            if symbols_mentioned:
                query_result["_hint"] = (
                    "Call get_symbol_doc for each class/method you plan to use: "
                    + ", ".join(symbols_mentioned[:5])
                )
            # Warn about cross-language fallback
            warnings = query_response.warnings or []
            if "cross_language_fallback" in warnings:
                query_result["_warning"] = (
                    "These results are from a different SDK language. "
                    "Adapt class names and patterns to your target language. "
                    "Method signatures may differ — verify with get_symbol_doc."
                )
            return query_result
        if tool_name == "get_symbol_doc":
            symbol_request = GetSymbolDocRequest.model_validate(arguments)
            symbol_response = self._public_query_service.get_symbol_doc(request=symbol_request)
            return symbol_response.model_dump()
        if tool_name == "list_breaking_changes":
            changes_request = ListBreakingChangesRequest.model_validate(arguments)
            changes_response = self._public_query_service.list_breaking_changes(
                request=changes_request
            )
            return changes_response.model_dump()
        if tool_name == "list_latest_release_features":
            release_request = ListLatestReleaseFeaturesRequest.model_validate(arguments)
            release_response = self._public_query_service.list_latest_release_features(
                request=release_request
            )
            return release_response.model_dump()

        if tool_name in ("aspose_lookup", "get_symbol", "list_members", "search_symbols"):
            if self._apiref_symbol_service is None:
                msg = f"MCP tool {tool_name!r} requires a configured API-reference symbol store."
                raise MCPToolError(msg)
            return self._call_apiref_tool(
                tool_name=tool_name, arguments=arguments, strict_scope=scope is not None
            )

        msg = f"Unsupported MCP tool: {tool_name!r}"
        raise MCPToolError(msg)

    def _call_apiref_tool(
        self, *, tool_name: str, arguments: dict[str, Any], strict_scope: bool = False
    ) -> dict[str, Any]:
        service = self._apiref_symbol_service
        assert service is not None  # guarded by caller
        if tool_name == "aspose_lookup":
            return service.lookup(
                request=LookupRequest.model_validate(arguments), strict_scope=strict_scope
            ).model_dump()
        if tool_name == "get_symbol":
            return service.get_symbol(
                request=GetSymbolRequest.model_validate(arguments), strict_scope=strict_scope
            ).model_dump()
        if tool_name == "list_members":
            return service.list_members(
                request=ListMembersRequest.model_validate(arguments), strict_scope=strict_scope
            ).model_dump()
        return service.search_symbols(
            request=SearchSymbolsRequest.model_validate(arguments), strict_scope=strict_scope
        ).model_dump()


def _encode_session_token(session: MCPSessionContext) -> str:
    """Encode session context into an opaque, self-describing token.

    Clients treat this as an opaque string, exactly as they did the previous
    UUID, so the public contract is unchanged.
    """
    payload = {
        "v": _SESSION_TOKEN_VERSION,
        "nonce": str(uuid4()),
        "rev": session.negotiated_revision,
        "req": session.requested_revision,
        "fb": session.fallback_applied,
        "fr": str(session.fallback_reason),
        "ts": session.created_at.isoformat(),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{_SESSION_TOKEN_PREFIX}.{encoded}"


def _decode_session_token(session_id: str) -> MCPSessionContext:
    """Inverse of :func:`_encode_session_token`; raises on any malformed token."""
    prefix, _, encoded = session_id.partition(".")
    if prefix != _SESSION_TOKEN_PREFIX or not encoded:
        msg = "unrecognised MCP session token"
        raise ValueError(msg)
    padded = encoded + "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    if not isinstance(payload, dict):
        msg = "malformed MCP session token payload"
        raise ValueError(msg)
    return MCPSessionContext(
        session_id=session_id,
        negotiated_revision=str(payload["rev"]),
        requested_revision=payload["req"],
        fallback_applied=bool(payload["fb"]),
        fallback_reason=MCPFallbackReason(payload["fr"]),
        created_at=datetime.fromisoformat(str(payload["ts"])),
    )


def _build_session_context(
    negotiation: MCPRevisionNegotiationResult,
) -> MCPSessionContext:
    draft = MCPSessionContext(
        session_id="",
        negotiated_revision=negotiation.negotiated_revision,
        requested_revision=negotiation.requested_revision,
        fallback_applied=negotiation.fallback_applied,
        fallback_reason=negotiation.fallback_reason,
        created_at=datetime.now(tz=UTC),
    )
    return replace(draft, session_id=_encode_session_token(draft))
