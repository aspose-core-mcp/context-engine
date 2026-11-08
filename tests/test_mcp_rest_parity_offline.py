"""MCP vs REST parity, compared field-by-field without live infrastructure.

The only existing MCP-vs-REST comparison lives in a suite that skips unless
Qdrant and OpenSearch are reachable, and even then it compares `chunk_id` sets
rather than response bodies. That is why a live divergence went unnoticed:
`version_resolution.strict_version_enforced` was built from the raw request flag
on REST and from a flag the MCP gateway rewrites, so the two transports answered
opposite values for identical calls.

These tests run against the in-memory adapters, so they execute in the default
`make test` run rather than being skipped on every developer machine.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord

# Fields whose values legitimately differ per call — comparing them would test
# uuid4, not parity.
_NON_DETERMINISTIC = frozenset({"query_id", "request_id", "latency_ms", "generated_at"})


@pytest.fixture
def app_with_records() -> FastAPI:
    app = create_app()
    records = _sample_records()
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            r
            for r in records
            if (product_id is None or r.product_id == product_id.casefold())
            and (
                programming_language is None
                or r.programming_language == programming_language.casefold()
            )
            and (version is None or r.version == version)
        )

    orchestrator.get_latest_chunk_records = _patched  # type: ignore[method-assign]
    app.state.public_query_service._qdrant_url = None  # type: ignore[attr-defined]
    return app


def _strip(value: Any) -> Any:
    """Drop per-call fields so the comparison is about contract, not identity."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _NON_DETERMINISTIC}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def _mcp_call(client: TestClient, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    initialized = client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})
    assert initialized.status_code == 200
    session_id = initialized.json()["session_id"]
    response = client.post(
        f"/mcp/v1/tools/{tool}",
        json={"session_id": session_id, "arguments": arguments},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


@pytest.mark.parametrize(
    ("tool", "rest_path", "arguments"),
    [
        (
            "resolve_product",
            "/v1/products:resolve",
            {"query": "Aspose.OCR for .NET"},
        ),
        (
            "query_docs",
            "/v1/docs:query",
            {
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
                "top_k": 2,
            },
        ),
    ],
)
def test_mcp_and_rest_return_the_same_body(
    app_with_records: FastAPI,
    tool: str,
    rest_path: str,
    arguments: dict[str, Any],
) -> None:
    """Identical arguments must produce identical payloads on both transports."""
    with TestClient(app_with_records) as client:
        rest = client.post(rest_path, json=arguments)
        assert rest.status_code == 200, rest.text
        rest_body = _strip(rest.json())
        mcp_body = _strip(_mcp_call(client, tool, arguments))

    # The MCP gateway adds consumer hints REST does not carry; they are additive
    # by design, so compare on the shared keys and assert the extras are hints.
    extra_keys = set(mcp_body) - set(rest_body)
    assert all(key.startswith("_") for key in extra_keys), (
        f"MCP added non-hint fields REST does not return: {sorted(extra_keys)}"
    )
    assert set(rest_body) - set(mcp_body) == set(), (
        f"REST returned fields MCP dropped: {sorted(set(rest_body) - set(mcp_body))}"
    )

    for key, rest_value in rest_body.items():
        assert mcp_body[key] == rest_value, (
            f"{tool}: field {key!r} differs — REST={rest_value!r} MCP={mcp_body[key]!r}"
        )


def test_strict_version_enforced_agrees_across_transports(app_with_records: FastAPI) -> None:
    """The field that actually diverged in a deployment.

    Built from the raw request flag, `strict_version_enforced` reported true for
    a call carrying no version at all; the MCP gateway rewrites that flag, so the
    transports reported opposite values for the same request.
    """
    arguments = {
        "query": "How to use RecognizeImage?",
        "product_id": "aspose.ocr",
        "language": "net",
        "query_locale": "en",
        "top_k": 2,
        "strict_version": True,
    }

    with TestClient(app_with_records) as client:
        rest = client.post("/v1/docs:query", json=arguments).json()
        mcp = _mcp_call(client, "query_docs", arguments)

    rest_flag = rest["version_resolution"]["strict_version_enforced"]
    mcp_flag = mcp["version_resolution"]["strict_version_enforced"]
    assert rest_flag == mcp_flag, (
        f"transports disagree on strict_version_enforced: REST={rest_flag} MCP={mcp_flag}"
    )
    # No version was requested, so no version predicate can have been applied.
    assert rest_flag is False


def test_error_envelopes_share_a_shape_across_transports(app_with_records: FastAPI) -> None:
    """A NOT_FOUND must look the same whichever transport produced it."""
    arguments = {
        "product_id": "aspose.doesnotexist",
        "language": "net",
        "top_k": 3,
    }

    with TestClient(app_with_records) as client:
        rest = client.post("/v1/releases:latest", json=arguments)
        initialized = client.post("/mcp/v1/initialize", json={})
        session_id = initialized.json()["session_id"]
        mcp = client.post(
            "/mcp/v1/tools/list_latest_release_features",
            json={"session_id": session_id, "arguments": arguments},
        )

    assert rest.status_code == mcp.status_code, (
        f"status differs: REST={rest.status_code} MCP={mcp.status_code}"
    )

    def _error_of(payload: dict[str, Any]) -> dict[str, Any]:
        # Both transports wrap the error envelope in FastAPI's `detail`.
        inner = payload.get("detail", payload)
        assert isinstance(inner, dict)
        error: dict[str, Any] = inner["error"]
        return error

    rest_error = _error_of(rest.json())
    mcp_error = _error_of(mcp.json())

    assert set(rest_error) == set(mcp_error), (
        f"error envelope keys differ: REST={sorted(rest_error)} MCP={sorted(mcp_error)}"
    )
    assert rest_error["code"] == mcp_error["code"]
    for envelope in (rest_error, mcp_error):
        for field in ("code", "message", "details", "request_id"):
            assert field in envelope, f"error envelope field {field!r} missing from {envelope}"


def _sample_records() -> tuple[StageDChunkRecord, ...]:
    return (
        _record(
            chunk_id="chunk-api-signature",
            source_kind="apiref",
            doc_type="api_signature",
            symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
            title="RecognizeImage Method",
            text=(
                "public RecognitionResult RecognizeImage(string imagePath)\n"
                "Recognize text from one image."
            ),
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/",
            section_anchor="#recognizeimage",
            chunk_type="api_signature",
        ),
        _record(
            chunk_id="chunk-guide",
            source_kind="docs",
            doc_type="guide_step",
            symbol_fqn=None,
            title="How to Recognize Text",
            text="Use Aspose.OCR.AsposeOcr.RecognizeImage in a simple setup flow.",
            canonical_url="https://docs.aspose.com/ocr/net/quickstart/",
            section_anchor="#how-to-recognize-text",
            chunk_type="guide_step",
        ),
    )


def _record(
    *,
    chunk_id: str,
    source_kind: str,
    doc_type: str,
    symbol_fqn: str | None,
    title: str,
    text: str,
    canonical_url: str,
    section_anchor: str,
    chunk_type: str,
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id=f"aspose.ocr.{source_kind}",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version="25.1",
        source_kind=source_kind,
        doc_locale="en",
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=title,
        section_path=("root", title),
        canonical_url=canonical_url,
        section_anchor=section_anchor,
        source_path=f"source/{chunk_id}.md",
        source_revision="revision-abc123",
        is_deprecated=False,
        has_code_example=False,
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )
