from __future__ import annotations

from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.mcp.stdio_server import MCPStdioTransport


def test_mcp_revision_metrics_export_sessions_fail_ratio_and_fallback_counters() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})
        client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-10-01"})
        client.post("/mcp/v1/initialize", json={"protocol_revision": "invalid"})

        metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    text = metrics_response.text
    assert 'mcp_sessions_by_revision{revision="2025-11-25"} 2' in text
    assert 'mcp_sessions_by_revision{revision="2025-06-18"} 1' in text
    assert "mcp_negotiation_total 3" in text
    assert "mcp_negotiation_fail_ratio 0.666666667" in text
    assert (
        'mcp_negotiation_fallback_total{fallback_reason="unknown_revision",'
        'negotiated_revision="2025-06-18",requested_revision="2025-10-01"} 1'
    ) in text
    assert (
        'mcp_negotiation_fallback_total{fallback_reason="invalid_revision_format",'
        'negotiated_revision="2025-11-25",requested_revision="invalid"} 1'
    ) in text


def test_mcp_revision_metrics_include_stdio_initialize_fallback() -> None:
    app = create_app()
    gateway = app.state.mcp_tool_gateway
    transport = MCPStdioTransport(gateway=gateway)
    transport.handle_message({"id": "init-1", "method": "initialize", "params": {}})

    with TestClient(app) as client:
        metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    text = metrics_response.text
    # The handshake is counted...
    assert "mcp_negotiation_total 1" in text
    assert 'mcp_sessions_by_revision{revision="2025-11-25"} 1' in text
    # ...but NOT as a fallback. Serving the primary target to a client that sent
    # no protocolVersion is the documented negotiation outcome, and none of the
    # three fallback reasons covers it. Counting it would move
    # mcp_negotiation_fail_ratio against its SLO on correct handshakes.
    assert "mcp_negotiation_fail_ratio 0.000000000" in text
    assert 'fallback_reason="missing_requested_revision"' not in text
