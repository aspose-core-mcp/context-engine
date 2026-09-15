"""ADCS MCP server — Model Context Protocol implementation.

This package hosts an MCP server for the Aspose Developer Context Service.
ADCS implements the Model Context Protocol directly over JSON-RPC rather
than depending on the ``mcp`` / ``FastMCP`` Python SDK — the protocol
surface is purpose-built for the retrieval contract (``resolve_product``,
``query_docs``, ``get_symbol_doc``, ``list_breaking_changes``,
``list_latest_release_features``) and runs across three transports:

* **stdio** — JSON-RPC over stdio for local AI-IDE integration
  (entry point: ``adcs-mcp-stdio`` console script, implemented in
  :mod:`adcs.mcp.stdio_server`).
* **streamable-http** + **sse** — HTTP gateway for hosted/remote MCP
  clients (implemented in :mod:`adcs.api.mcp_gateway`).

Protocol revision negotiation supports ``2025-11-25``, ``2025-06-18``,
and ``2024-11-05``; see :mod:`adcs.mcp.revision_negotiation`. The tool
dispatch layer is in :mod:`adcs.mcp.tool_gateway`.

This is a first-class **MCP server component** — not a client, not a
wrapper — exposing the five public retrieval tools through any
MCP-compatible AI-IDE.
"""

from adcs.mcp.revision_negotiation import (
    MCPFallbackReason,
    MCPRevisionNegotiationResult,
    negotiate_mcp_revision,
)
from adcs.mcp.stdio_server import MCPStdioTransport, build_stdio_transport
from adcs.mcp.tool_gateway import (
    MCPInitializeResponse,
    MCPSessionContext,
    MCPToolError,
    MCPToolGateway,
)

__all__ = [
    "MCPFallbackReason",
    "MCPInitializeResponse",
    "MCPRevisionNegotiationResult",
    "MCPStdioTransport",
    "MCPSessionContext",
    "MCPToolError",
    "MCPToolGateway",
    "build_stdio_transport",
    "negotiate_mcp_revision",
]
