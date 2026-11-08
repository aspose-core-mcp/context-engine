"""Consumer-driven contract test for the `query_docs` tool.

Simulates how an AI-IDE consumer (e.g., Cursor MCP client) calls
`POST /v1/docs:query` and what response shape it expects.

Contracts target a
self-hosted Pact Broker (see infra/pact-broker/).

If `pact-python` is not installed (extras `[contracts]`), the test
self-skips so `make test` continues to work for the standard dev install.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# pact-python imports are wrapped — they're only needed when contracts extras
# is installed. CI runs `pip install -e ".[dev,contracts]"` for contract jobs.
pact_lib = pytest.importorskip(
    "pact",
    reason="pact-python not installed — install via `pip install -e .[dev,contracts]`",
)

PACT_DIR = Path(__file__).resolve().parents[3] / "pacts"
# The mock service port; override it when 1234 is taken on the machine.
MOCK_PORT = int(os.environ.get("PACT_MOCK_PORT", "1234"))
PACT_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="module")
def pact():
    p = pact_lib.Consumer("ai-ide-consumer").has_pact_with(
        pact_lib.Provider("adcs-mcp-gateway"),
        host_name="localhost",
        port=MOCK_PORT,
        pact_dir=str(PACT_DIR),
    )
    p.start_service()
    yield p
    p.stop_service()


def test_query_docs_returns_expected_shape(pact) -> None:
    expected = {
        "query_id": pact_lib.Like("550e8400-e29b-41d4-a716-446655440000"),
        "mode": pact_lib.Term(r"symbol-first|task|migration", "task"),
        "confidence": pact_lib.Like(0.85),
        "results": pact_lib.EachLike(
            {
                "title": pact_lib.Like("RecognizeImage Method"),
                "excerpt": pact_lib.Like(
                    "Recognizes text on an image from the specified path."
                ),
                "canonical_url": pact_lib.Like(
                    "https://docs.aspose.com/ocr/net/recognizeimage/"
                ),
                "section_anchor": pact_lib.Like("#recognizeimage"),
                "score": pact_lib.Like(0.91),
                "source_revision": pact_lib.Like("a1b2c3d"),
            }
        ),
    }

    (
        pact.upon_receiving("a query_docs request for OCR text recognition")
        .with_request(
            method="POST",
            path="/v1/docs:query",
            headers={"Content-Type": "application/json"},
            body={
                "query": "How to recognize text from image bytes?",
                "product_id": "aspose.ocr",
                "language": "net",
                "top_k": 5,
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=expected,
        )
    )

    with pact:
        # Real consumer code would invoke its MCP/REST client here. For the
        # stub we issue an httpx call against the Pact mock service.
        import httpx

        response = httpx.post(
            f"http://localhost:{MOCK_PORT}/v1/docs:query",
            json={
                "query": "How to recognize text from image bytes?",
                "product_id": "aspose.ocr",
                "language": "net",
                "top_k": 5,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "query_id" in body
        assert isinstance(body["results"], list)
        assert body["results"], "expected at least one result"
        first = body["results"][0]
        assert {
            "title",
            "excerpt",
            "canonical_url",
            "section_anchor",
            "score",
            "source_revision",
        }.issubset(first.keys())
