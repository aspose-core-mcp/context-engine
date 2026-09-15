"""The public error vocabulary is closed, and both transports draw from it.

Three drifts had accumulated because the codes were string literals at ~30
raise sites with nothing tying them together:

* ``SERVICE_UNAVAILABLE`` was emitted where the error vocabulary says
  ``DEPENDENCY_UNAVAILABLE`` — the documented code appeared in no error path.
* ``THROTTLED`` and ``RATE_LIMITED`` both named one condition.
* A backend timeout answered ``TIMEOUT`` on MCP and ``SERVICE_UNAVAILABLE`` on
  REST. The two tests that covered it asserted the divergence rather than
  catching it.

The static scan below is the durable part: a new literal in a public error path
fails here rather than reaching a client.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from adcs.api.error_codes import (
    HTTP_STATUS_BY_CODE,
    PUBLIC_ERROR_CODES,
    WEBMCP_ADAPTER_CODES,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "adcs"

# The modules that answer unauthenticated callers. Admin endpoints carry their
# own operational vocabulary (SNAPSHOT_*, BACKUP_*) and are out of scope: they
# are behind x-api-key and not part of the public error vocabulary.
_PUBLIC_SURFACE = (
    "api/public_docs_query.py",
    "api/mcp_gateway.py",
    "api/apiref_symbols.py",
    "mcp/stdio_server.py",
)


def _literal_codes(path: Path) -> dict[str, int]:
    """Return ``{code_literal: lineno}`` for error-raising calls in `path`."""
    found: dict[str, int] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if "error" not in name.lower():
            continue
        for keyword in node.keywords:
            if keyword.arg not in {"code", "error_code"}:
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, str
            ):
                found[keyword.value.value] = keyword.value.lineno
    return found


@pytest.mark.parametrize("module", _PUBLIC_SURFACE)
def test_public_surface_emits_no_undeclared_code(module: str) -> None:
    path = _SRC / module
    offenders = {
        code: lineno
        for code, lineno in _literal_codes(path).items()
        if code not in PUBLIC_ERROR_CODES
    }
    assert not offenders, (
        f"{module} emits error codes that are not in the public error vocabulary: "
        f"{offenders}. Add them to adcs.api.error_codes, or map "
        "them onto an existing code."
    )


def test_webmcp_adapter_codes_are_declared_not_accidental() -> None:
    """The adapter may add codes, but only ones this repo has written down."""
    path = _SRC / "api" / "webmcp_gateway.py"
    allowed = PUBLIC_ERROR_CODES | WEBMCP_ADAPTER_CODES
    offenders = {
        code: lineno
        for code, lineno in _literal_codes(path).items()
        if code not in allowed
    }
    assert not offenders, f"undeclared WebMCP codes: {offenders}"


def test_every_code_has_exactly_one_http_status() -> None:
    assert set(HTTP_STATUS_BY_CODE) == set(PUBLIC_ERROR_CODES)


def test_timeout_and_dependency_unavailable_are_not_the_same_code() -> None:
    """They share a status but not a meaning, and callers retry them differently."""
    from adcs.api.error_codes import DEPENDENCY_UNAVAILABLE, TIMEOUT

    assert TIMEOUT != DEPENDENCY_UNAVAILABLE
    assert HTTP_STATUS_BY_CODE[TIMEOUT] == HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE]


# ---------------------------------------------------------------------------
# Behavioural parity: the same failure, both transports, same code.
# ---------------------------------------------------------------------------


def _build_app():  # type: ignore[no-untyped-def]
    from tests.test_error_handling_hardening import _build_app as build

    return build()


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (RuntimeError("retrieval backend down"), "DEPENDENCY_UNAVAILABLE"),
        (TimeoutError("query timed out after 5s"), "TIMEOUT"),
    ],
)
def test_rest_and_mcp_answer_the_same_failure_with_the_same_code(
    exception: Exception, expected_code: str
) -> None:
    rest_app = _build_app()
    rest_app.state.public_query_service.query_docs = MagicMock(side_effect=exception)
    with TestClient(rest_app) as client:
        rest = client.post(
            "/v1/docs:query",
            json={
                "query": "How to recognize text?",
                "product_id": "aspose.ocr",
                "language": "net",
            },
        )

    mcp_app = _build_app()
    mcp_app.state.public_query_service.query_docs = MagicMock(side_effect=exception)
    with TestClient(mcp_app) as client:
        session = client.post(
            "/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"}
        ).json()
        mcp = client.post(
            "/mcp/v1/tools/query_docs",
            json={
                "session_id": session["session_id"],
                "arguments": {
                    "query": "How to recognize text?",
                    "product_id": "aspose.ocr",
                    "language": "net",
                },
            },
        )

    rest_error = rest.json()["detail"]["error"]
    mcp_error = mcp.json()["detail"]["error"]
    assert rest_error["code"] == mcp_error["code"] == expected_code
    assert rest.status_code == mcp.status_code == HTTP_STATUS_BY_CODE[expected_code]
