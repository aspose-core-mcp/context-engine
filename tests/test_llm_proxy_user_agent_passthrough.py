from __future__ import annotations

from adcs.llm_proxy.tool_aware_proxy import _forward_headers


class _Req:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_forward_headers_passes_through_user_agent() -> None:
    # A client's User-Agent must survive a hop through the tool-aware proxy.
    tag = "example-client/1.0"
    out = _forward_headers(_Req({"user-agent": tag, "authorization": "Bearer up"}), None)
    assert out["user-agent"] == tag
    assert out["authorization"] == "Bearer up"


def test_forward_headers_without_user_agent_is_unaffected() -> None:
    out = _forward_headers(_Req({}), "injected-key")
    assert "user-agent" not in out
    assert out["authorization"] == "Bearer injected-key"
