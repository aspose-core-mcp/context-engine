"""Run the tool-aware non-streaming proxy.

Point an OpenAI-compatible coding client at this proxy instead of the upstream
so tool-bearing requests are forced non-streamed:

    ADCS_PROXY_UPSTREAM_BASE_URL=https://llm.example.com/v1 \\
    ADCS_PROXY_API_KEY=$OPENAI_API_KEY \\
    python -m adcs.llm_proxy --host 0.0.0.0 --port 8088

Then set the client's ``OPENAI_BASE_URL`` to ``http://<host>:8088/v1``.

Upstream base/key fall back to the standard ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``
env vars, then to a local OpenAI-compatible default. No secrets are persisted.
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from adcs.llm_proxy.tool_aware_proxy import create_proxy_app

_DEFAULT_UPSTREAM = "http://localhost:11434/v1"


def _resolve_upstream_base_url() -> str:
    return (
        os.environ.get("ADCS_PROXY_UPSTREAM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or _DEFAULT_UPSTREAM
    )


def _resolve_api_key() -> str | None:
    return os.environ.get("ADCS_PROXY_API_KEY") or os.environ.get("OPENAI_API_KEY")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool-aware non-streaming LLM proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()

    app = create_proxy_app(
        upstream_base_url=_resolve_upstream_base_url(),
        api_key=_resolve_api_key(),
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
