from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient

from adcs.llm_proxy.tool_aware_proxy import (
    completion_looks_empty,
    completion_to_chunk,
    completion_to_sse,
    create_proxy_app,
    plan_request,
)

_TOOLS = [{"type": "function", "function": {"name": "search_symbols"}}]


def _completion(*, content: str | None = "hi", tool_calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "example-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }


# --- pure: plan_request ---------------------------------------


@pytest.mark.parametrize(
    ("body", "expect_upstream_stream", "expect_rewrap"),
    [
        ({"tools": _TOOLS, "stream": True}, False, True),  # tool + stream → forced non-stream
        ({"tools": _TOOLS, "stream": False}, False, False),  # tool + no stream → non-stream
        ({"stream": True}, True, False),  # no tools → passthrough streaming
        ({"stream": False}, False, False),  # no tools, no stream → passthrough
        ({"tools": [], "stream": True}, True, False),  # empty tools ≠ tool request
    ],
)
def test_plan_request(body: dict, expect_upstream_stream: bool, expect_rewrap: bool) -> None:
    plan = plan_request(body)
    assert plan.upstream_body.get("stream", False) is expect_upstream_stream
    assert plan.rewrap_as_sse is expect_rewrap


def test_plan_request_does_not_mutate_input() -> None:
    body = {"tools": _TOOLS, "stream": True}
    plan_request(body)
    assert body["stream"] is True  # original untouched


# --- pure: SSE re-wrapping --------------------------------------------------


def test_completion_to_chunk_carries_tool_calls_with_index() -> None:
    tool_calls = [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
    chunk = completion_to_chunk(_completion(content=None, tool_calls=tool_calls))
    assert chunk["object"] == "chat.completion.chunk"
    delta = chunk["choices"][0]["delta"]
    assert delta["tool_calls"][0]["index"] == 0
    assert delta["tool_calls"][0]["function"]["name"] == "f"


def test_completion_to_sse_emits_single_chunk_then_done() -> None:
    frames = list(completion_to_sse(_completion(content="ok")))
    assert frames[-1] == b"data: [DONE]\n\n"
    first = json.loads(frames[0].decode().removeprefix("data: ").strip())
    assert first["choices"][0]["delta"]["content"] == "ok"


@pytest.mark.parametrize(
    ("completion", "empty"),
    [
        (_completion(content="hello"), False),
        (_completion(content="", tool_calls=[{"id": "x"}]), False),
        (_completion(content=""), True),
        (_completion(content=None), True),
        ({"choices": []}, True),
    ],
)
def test_completion_looks_empty(completion: dict, empty: bool) -> None:
    assert completion_looks_empty(completion) is empty


# --- app: forwarding via httpx.MockTransport (no network) -------------------


class _Recorder:
    """Captures forwarded requests and serves scripted upstream responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.forwarded: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.forwarded.append(json.loads(request.content))
        return self.responses[min(len(self.forwarded) - 1, len(self.responses) - 1)]


def _client(recorder: _Recorder) -> TestClient:
    transport = httpx.MockTransport(recorder.handler)
    app = create_proxy_app(
        upstream_base_url="https://upstream.test/v1",
        api_key="k",
        client=httpx.AsyncClient(transport=transport),
    )
    return TestClient(app)


def _json_response(completion: dict) -> httpx.Response:
    return httpx.Response(200, json=completion)


def test_tool_request_forced_nonstream_and_rewrapped_as_sse() -> None:
    rec = _Recorder([_json_response(_completion(content="answer"))])
    with _client(rec) as client:
        resp = client.post("/v1/chat/completions", json={"tools": _TOOLS, "stream": True})
    assert resp.status_code == 200
    # The key invariant: upstream NEVER saw a streamed tool request.
    assert rec.forwarded[0]["stream"] is False
    # Client still got a stream it can parse.
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in resp.text
    first = json.loads(resp.text.split("\n")[0].removeprefix("data: ").strip())
    assert first["choices"][0]["delta"]["content"] == "answer"


def test_tool_request_nonstream_client_gets_json() -> None:
    rec = _Recorder([_json_response(_completion(content="answer"))])
    with _client(rec) as client:
        resp = client.post("/v1/chat/completions", json={"tools": _TOOLS, "stream": False})
    assert resp.status_code == 200
    assert rec.forwarded[0]["stream"] is False
    assert resp.json()["choices"][0]["message"]["content"] == "answer"


def _streaming_response(payload: bytes) -> httpx.Response:
    async def _body() -> AsyncIterator[bytes]:
        yield payload

    return httpx.Response(200, content=_body())


def test_non_tool_stream_is_passed_through_as_stream() -> None:
    rec = _Recorder([_streaming_response(b"data: chunk\n\ndata: [DONE]\n\n")])
    with _client(rec) as client:
        resp = client.post("/v1/chat/completions", json={"messages": [], "stream": True})
    assert resp.status_code == 200
    # Passthrough preserves the client's streaming request upstream.
    assert rec.forwarded[0]["stream"] is True
    assert "data: chunk" in resp.text


def test_empty_tool_completion_is_retried_nonstream_once() -> None:
    rec = _Recorder(
        [
            _json_response(_completion(content="")),  # empty → triggers A3 retry
            _json_response(_completion(content="recovered")),
        ]
    )
    with _client(rec) as client:
        resp = client.post("/v1/chat/completions", json={"tools": _TOOLS, "stream": False})
    assert len(rec.forwarded) == 2  # retried exactly once
    assert resp.json()["choices"][0]["message"]["content"] == "recovered"


def test_healthz() -> None:
    rec = _Recorder([_json_response(_completion())])
    with _client(rec) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


# --- entrypoint env resolution (ADCS_PROXY_* before OPENAI_*) ---------------


def test_entrypoint_upstream_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from adcs.llm_proxy import __main__ as entry

    monkeypatch.setenv("ADCS_PROXY_UPSTREAM_BASE_URL", "https://explicit/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://fallback/v1")
    assert entry._resolve_upstream_base_url() == "https://explicit/v1"

    monkeypatch.delenv("ADCS_PROXY_UPSTREAM_BASE_URL")
    assert entry._resolve_upstream_base_url() == "https://fallback/v1"

    monkeypatch.delenv("OPENAI_BASE_URL")
    assert entry._resolve_upstream_base_url() == entry._DEFAULT_UPSTREAM


def test_entrypoint_api_key_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from adcs.llm_proxy import __main__ as entry

    monkeypatch.delenv("ADCS_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert entry._resolve_api_key() is None

    monkeypatch.setenv("OPENAI_API_KEY", "k-fallback")
    assert entry._resolve_api_key() == "k-fallback"

    monkeypatch.setenv("ADCS_PROXY_API_KEY", "k-explicit")
    assert entry._resolve_api_key() == "k-explicit"
