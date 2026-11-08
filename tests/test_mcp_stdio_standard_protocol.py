from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from adcs.api.main import create_app
from adcs.mcp.stdio_server import MCPStdioTransport

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _transport() -> MCPStdioTransport:
    app = create_app()
    return MCPStdioTransport(gateway=app.state.mcp_tool_gateway)


def _initialize(transport: MCPStdioTransport) -> dict:
    response = transport.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
    )
    assert response is not None
    return response


def test_initialize_with_protocol_version_returns_mcp_result() -> None:
    response = _initialize(_transport())

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    result = response["result"]
    assert result["serverInfo"] == {"name": "adcs-mcp", "version": "v1"}
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}


def test_notifications_are_not_answered() -> None:
    transport = _transport()
    _initialize(transport)

    line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert transport.process_line(line) is None


def test_ping_and_tools_list() -> None:
    transport = _transport()
    _initialize(transport)

    assert transport.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"}) == {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {},
    }
    tools_response = transport.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert tools_response is not None
    tools = {tool["name"]: tool for tool in tools_response["result"]["tools"]}
    assert {"resolve_product", "query_docs"} <= set(tools)
    assert all("inputSchema" in tool for tool in tools.values())


def test_tools_call_returns_text_and_structured_content() -> None:
    transport = _transport()
    _initialize(transport)

    response = transport.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "resolve_product", "arguments": {"query": "Aspose.OCR for .NET"}},
        }
    )
    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["product_id"] == "aspose.ocr"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_tools_call_opens_a_session_when_initialize_was_skipped() -> None:
    response = _transport().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "resolve_product", "arguments": {"query": "Aspose.OCR"}},
        }
    )
    assert response is not None
    assert response["result"]["structuredContent"]["product_id"] == "aspose.ocr"


def test_tools_call_errors_use_numeric_jsonrpc_codes() -> None:
    transport = _transport()
    _initialize(transport)

    missing_name = transport.handle_message(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"arguments": {}}}
    )
    assert missing_name is not None
    assert missing_name["error"]["code"] == -32602
    assert missing_name["error"]["data"]["adcs_code"] == "INVALID_ARGUMENT"


def test_stdout_carries_only_protocol_messages() -> None:
    """Start-up logs must not reach stdout, which MCP clients parse line by line."""
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT / "src"),
        "ADCS_ENV": "dev",
        "ADCS_API_KEY": "replace-me",
        "ADCS_ADMIN_KEYS_SOURCE": "env",
        "ADCS_PERSISTENCE_BACKEND": "auto",
        "ADCS_RETRIEVAL_BACKEND": "auto",
        "ADCS_EMBEDDING_BACKEND": "deterministic",
    }
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "adcs.mcp.stdio_server"],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    messages = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert [message.get("id") for message in messages] == [1, 2]
    assert all(message.get("jsonrpc") == "2.0" for message in messages)
