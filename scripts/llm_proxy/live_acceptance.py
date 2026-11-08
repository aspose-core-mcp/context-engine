#!/usr/bin/env python3
"""Live acceptance for the tool-aware proxy: measure streamed vs non-streamed empty rate.

Sends N identical tool-bearing chat-completions to the real endpoint, once
streamed and once non-streamed, and reports the empty-response rate of each. This
re-validates the premise the tool-aware proxy exploits (streamed+tools drops the
body; non-streamed does not) against a live OpenAI-compatible endpoint.

    OPENAI_BASE_URL=https://llm.example.com/v1 \\
    OPENAI_API_KEY=<chat-key> \\
    python scripts/llm_proxy/live_acceptance.py --model <model-id> --n 8

No secrets are printed or persisted. Exit code is non-zero if the non-streamed
path shows any empties (the proxy would not help) — useful as a CI gate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

# Import the same emptiness check the proxy uses, so the gate matches behaviour.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from adcs.llm_proxy.tool_aware_proxy import completion_looks_empty  # noqa: E402

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_symbols",
            "description": "Search Aspose API symbols by name or concept.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]
_MESSAGES = [
    {"role": "user", "content": "Find the Aspose.Cells class that saves a workbook to PDF."}
]


def _request_body(*, model: str, stream: bool) -> dict[str, Any]:
    return {
        "model": model,
        "messages": _MESSAGES,
        "tools": _TOOLS,
        "tool_choice": "auto",
        "stream": stream,
    }


def _streamed_is_empty(client: httpx.Client, url: str, headers: dict[str, str], body: dict) -> bool:
    content = ""
    saw_tool_call = False
    with client.stream("POST", url, json=body, headers=headers) as response:
        if response.status_code >= 400:
            return True
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                content += delta.get("content") or ""
                if delta.get("tool_calls"):
                    saw_tool_call = True
    return not (content.strip() or saw_tool_call)


def _nonstreamed_is_empty(client: httpx.Client, url: str, headers: dict, body: dict) -> bool:
    response = client.post(url, json=body, headers=headers)
    if response.status_code >= 400:
        return True
    return completion_looks_empty(response.json())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    args = parser.parse_args()

    base_url = (args.base_url or "").rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        print("error: set OPENAI_BASE_URL (or --base-url) and OPENAI_API_KEY", file=sys.stderr)
        return 2

    url = f"{base_url}/chat/completions"
    headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
    client = httpx.Client(timeout=args.timeout, verify=not args.insecure)

    streamed_empty = 0
    nonstreamed_empty = 0
    try:
        for index in range(args.n):
            streamed_body = _request_body(model=args.model, stream=True)
            nonstreamed_body = _request_body(model=args.model, stream=False)
            if _streamed_is_empty(client, url, headers, streamed_body):
                streamed_empty += 1
            if _nonstreamed_is_empty(client, url, headers, nonstreamed_body):
                nonstreamed_empty += 1
            print(f"  [{index + 1}/{args.n}] streamed_empty={streamed_empty} "
                  f"nonstreamed_empty={nonstreamed_empty}")
    finally:
        client.close()

    print(f"\nstreamed+tools   empty: {streamed_empty}/{args.n} "
          f"({100 * streamed_empty / args.n:.0f}%)")
    print(f"nonstreamed+tools empty: {nonstreamed_empty}/{args.n} "
          f"({100 * nonstreamed_empty / args.n:.0f}%)")
    if nonstreamed_empty:
        print("FAIL: non-streamed path shows empties — the proxy would not fully help.")
        return 1
    print("PASS: non-streamed path eliminates empties (tool-aware proxy premise holds).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
