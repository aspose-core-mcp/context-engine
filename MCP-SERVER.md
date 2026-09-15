# ADCS as an MCP Server

ADCS is a **Model Context Protocol (MCP) server**. AI IDEs and assistants — Claude Code,
Cursor, Claude Desktop, VS Code, Codex CLI, Qwen Code and any other MCP-compatible
client — connect to it to get versioned, citation-backed Aspose and GroupDocs
documentation in real time.

This page is a one-page locator: where the server lives in the code, which transports
and protocol revisions it supports, and which tools it exposes. For the project
overview, see [README.md](README.md).

A public instance runs at **`https://mcp.aspose.com/mcp/v1/streamable-http`**.

## Server entry points

| Transport | Endpoint or command | Code |
|-----------|---------------------|------|
| Streamable HTTP | `/mcp/v1/streamable-http` | [`src/adcs/api/mcp_gateway.py`](src/adcs/api/mcp_gateway.py) |
| SSE | `/mcp/v1/sse/initialize`, `/mcp/v1/sse/tools/{tool_name}` | [`src/adcs/api/mcp_gateway.py`](src/adcs/api/mcp_gateway.py) |
| stdio (JSON-RPC over stdin/stdout) | `adcs-mcp-stdio` console script | [`src/adcs/mcp/stdio_server.py`](src/adcs/mcp/stdio_server.py) |

The HTTP transports are served by the API process (`make run`, the Docker images or the
Helm chart). All transports share one tool-dispatch core,
[`src/adcs/mcp/tool_gateway.py`](src/adcs/mcp/tool_gateway.py).

## Custom JSON-RPC implementation — by design

ADCS implements the protocol directly over JSON-RPC and does not depend on the `mcp`,
`FastMCP` or `@modelcontextprotocol` SDKs:

- the tool surface is purpose-built for documentation retrieval — stable contracts rather
  than general-purpose dynamic capability discovery;
- the same dispatch core backs the REST API under `/v1/`, which keeps MCP and REST in
  functional parity;
- no MCP SDK dependency keeps the supply chain small.

Scanners that detect MCP servers by SDK imports will therefore not match this codebase;
the modules above are the server.

## Protocol revisions

| Revision | Notes |
|----------|-------|
| `2025-11-25` | Latest |
| `2025-06-18` | Stable |
| `2024-11-05` | Backwards compatibility |

The revision is negotiated during the `initialize` handshake, with automatic fallback to
the nearest supported one — see
[`src/adcs/mcp/revision_negotiation.py`](src/adcs/mcp/revision_negotiation.py). The
supported set is configurable through `ADCS_MCP_SUPPORTED_REVISIONS`.

## Tools

Five core tools are always available:

| Tool | What it does | REST counterpart |
|------|--------------|------------------|
| `resolve_product` | Resolves a product name or alias to the canonical `product_id` and default SDK language. Call it first. | `POST /v1/products:resolve` |
| `query_docs` | Hybrid search over guides, how-to articles and API reference pages, filtered by product, language and version. | `POST /v1/docs:query` |
| `get_symbol_doc` | Exact signature, parameters, return type and examples for a class or method. | `POST /v1/symbols:get` |
| `list_breaking_changes` | Breaking API changes and deprecations between two versions. | `POST /v1/changes:list` |
| `list_latest_release_features` | New features, improvements and migration hints from the latest (or a given) release. | `POST /v1/releases:latest` |

Four more tools are backed by the structured API-reference symbol store in PostgreSQL.
Enable it with `APIREF_STRUCTURED_STORE_ENABLED=true`; without it, calls to these tools
return an error saying the store is not configured:

| Tool | What it does | REST counterpart |
|------|--------------|------------------|
| `aspose_lookup` | One-shot lookup: a natural-language query returns grounded symbols with their signatures in a single call. | `POST /v1/symbols/structured:lookup` |
| `get_symbol` | All overloads of a fully qualified member, with signature, parameters, returns and examples. | `POST /v1/symbols/structured:get` |
| `list_members` | Direct members (methods, properties, fields, nested types) of a class or namespace. | `POST /v1/symbols/structured:members` |
| `search_symbols` | Prefix/fuzzy and full-text search over API symbols. | `POST /v1/symbols/structured:search` |

Tool names, descriptions and input schemas are declared in
[`src/adcs/api/mcp_gateway.py`](src/adcs/api/mcp_gateway.py). MCP and REST share the same
semantics and error model.

## Connecting a client

Claude Code:

```bash
claude mcp add --transport http aspose-docs https://mcp.aspose.com/mcp/v1/streamable-http
```

Cursor (`.cursor/mcp.json`) and other clients that accept a JSON server list:

```json
{
  "mcpServers": {
    "aspose-docs": {
      "url": "https://mcp.aspose.com/mcp/v1/streamable-http"
    }
  }
}
```

For a self-hosted instance, replace the URL with `http://<host>:8080/mcp/v1/streamable-http`,
or run the stdio server locally with `"command": "adcs-mcp-stdio"`. The admin console's
**Integrations** page generates ready-to-paste configurations for several clients.

## Access model

The MCP tools are part of the public, read-only API: no authentication is required, and
abuse protection is configurable (`ADCS_ABUSE_GUARD_MODE`). Write operations are never
exposed over the standard MCP server; they exist only in the admin API (`x-api-key`) and
in the feature-flagged WebMCP adapter, which requires explicit confirmation.
