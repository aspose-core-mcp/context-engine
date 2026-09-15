"""Tool-aware non-streaming proxy for the chat endpoint.

Some OpenAI-compatible gateways drop the response body on *streamed* requests
that carry ``tools`` while non-streamed requests succeed. A coding client behind
such a gateway therefore fails to consume MCP tools even when the data is good.

This is a thin OpenAI-compatible reverse proxy that sits in front of the upstream
and forces ``stream=false`` for any ``/v1/chat/completions`` request carrying
``tools``. If the client asked for a stream, the non-streamed completion is
re-emitted as a single SSE chunk so the client is unaffected. Requests without
tools pass through untouched (streaming preserved). An empty tool completion is
retried once non-streamed.

The decision logic (:func:`plan_request`, :func:`completion_to_sse`) is pure and
unit-tested offline; only :func:`create_proxy_app` does I/O, and its HTTP client
is injectable so the whole proxy is testable without a network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

_CHAT_PATH = "/v1/chat/completions"
_RETRYABLE_EMPTY_TRIES = 2  # initial + one retry on an empty completion


def _has_tools(body: Mapping[str, Any]) -> bool:
    """True when the request carries a non-empty ``tools`` array.

    The presence of tools is the signal the endpoint mishandles when streaming;
    ``tool_choice`` alone (without tools) is not a tool-bearing request.
    """
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        return True
    return isinstance(body.get("tool_choice"), dict)


@dataclass(frozen=True)
class ProxyPlan:
    """How one chat-completions request should be forwarded upstream."""

    upstream_body: dict[str, Any]
    client_wants_stream: bool
    has_tools: bool

    @property
    def rewrap_as_sse(self) -> bool:
        """Client asked for a stream but we forced the upstream non-streamed."""
        return self.has_tools and self.client_wants_stream


def plan_request(body: Mapping[str, Any]) -> ProxyPlan:
    """Decide the upstream request shape.

    Tool-bearing requests are forced to ``stream=false`` upstream; everything else
    is forwarded verbatim so normal streaming is preserved.
    """
    has_tools = _has_tools(body)
    client_wants_stream = bool(body.get("stream", False))
    upstream: dict[str, Any] = dict(body)
    if has_tools:
        upstream["stream"] = False
    return ProxyPlan(
        upstream_body=upstream,
        client_wants_stream=client_wants_stream,
        has_tools=has_tools,
    )


def completion_to_chunk(completion: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a full chat completion into a single streaming chunk.

    Each choice's ``message`` becomes a ``delta`` (role + content + tool_calls,
    with per-tool-call ``index`` added for client compatibility).
    """
    choices_out: list[dict[str, Any]] = []
    for index, choice in enumerate(completion.get("choices", [])):
        message = dict(choice.get("message") or {})
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            message["tool_calls"] = [
                {**dict(call), "index": call_index}
                for call_index, call in enumerate(tool_calls)
                if isinstance(call, Mapping)
            ]
        choices_out.append(
            {
                "index": choice.get("index", index),
                "delta": message,
                "finish_reason": choice.get("finish_reason"),
            }
        )
    return {
        "id": completion.get("id", ""),
        "object": "chat.completion.chunk",
        "created": completion.get("created", 0),
        "model": completion.get("model", ""),
        "choices": choices_out,
    }


def completion_to_sse(completion: Mapping[str, Any]) -> Iterator[bytes]:
    """Re-emit a non-streamed completion as OpenAI-style SSE (single chunk)."""
    chunk = completion_to_chunk(completion)
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def completion_looks_empty(completion: Mapping[str, Any]) -> bool:
    """True when a completion carries neither content nor tool calls."""
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        return True
    for choice in choices:
        message = choice.get("message") if isinstance(choice, Mapping) else None
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return False
            if message.get("tool_calls"):
                return False
    return True


def _forward_headers(request: Request, api_key: str | None) -> dict[str, str]:
    """Minimal upstream headers: JSON content + auth (injected or passed through)."""
    headers = {"content-type": "application/json", "accept": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    elif "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    # Preserve the caller's User-Agent through the proxy hop.
    user_agent = request.headers.get("user-agent")
    if user_agent:
        headers["user-agent"] = user_agent
    return headers


def create_proxy_app(
    *,
    upstream_base_url: str,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    request_timeout: float = 120.0,
) -> FastAPI:
    """Build the tool-aware proxy app.

    ``upstream_base_url`` is an OpenAI-compatible base (``…/v1``). When ``client``
    is omitted a pooled :class:`httpx.AsyncClient` is created for the app's
    lifetime; tests inject a client backed by ``httpx.MockTransport``.
    """
    base = upstream_base_url.rstrip("/")
    chat_url = f"{base}/chat/completions"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = client is None
        app.state.http_client = client or httpx.AsyncClient(timeout=request_timeout)
        try:
            yield
        finally:
            if owned:
                await app.state.http_client.aclose()

    app = FastAPI(lifespan=lifespan, title="adcs-llm-tool-aware-proxy")

    async def _post(
        http: httpx.AsyncClient, body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> httpx.Response:
        return await http.post(chat_url, json=dict(body), headers=dict(headers))

    @app.post(_CHAT_PATH)
    async def chat_completions(request: Request) -> Response:
        body = await request.json()
        plan = plan_request(body)
        headers = _forward_headers(request, api_key)
        http: httpx.AsyncClient = request.app.state.http_client

        if not plan.has_tools:
            # Transparent passthrough; preserve streaming for non-tool requests.
            if plan.client_wants_stream:
                return StreamingResponse(
                    _stream_passthrough(http, chat_url, body, headers),
                    media_type="text/event-stream",
                )
            upstream = await _post(http, body, headers)
            return JSONResponse(upstream.json(), status_code=upstream.status_code)

        # Tool-bearing: force non-streaming upstream, retry an empty completion once.
        completion: dict[str, Any] = {}
        status_code = 502
        for _ in range(_RETRYABLE_EMPTY_TRIES):
            upstream = await _post(http, plan.upstream_body, headers)
            status_code = upstream.status_code
            completion = upstream.json()
            if not (upstream.is_success and completion_looks_empty(completion)):
                break

        if plan.rewrap_as_sse and status_code < 400:
            return StreamingResponse(
                _aiter_bytes(completion_to_sse(completion)),
                media_type="text/event-stream",
            )
        return JSONResponse(completion, status_code=status_code)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _aiter_bytes(chunks: Iterator[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _stream_passthrough(
    http: httpx.AsyncClient,
    url: str,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
) -> AsyncIterator[bytes]:
    async with http.stream("POST", url, json=dict(body), headers=dict(headers)) as upstream:
        async for chunk in upstream.aiter_raw():
            yield chunk


__all__ = [
    "ProxyPlan",
    "completion_looks_empty",
    "completion_to_chunk",
    "completion_to_sse",
    "create_proxy_app",
    "plan_request",
]
