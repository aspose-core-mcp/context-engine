"""Strict-version isolation over a corpus holding two versions of one product.

Guards a core retrieval guarantee: a request that sets ``strict_version`` must
never be answered with content from a different version. A strict-version test
that stubs retrieval or runs against a single-version corpus cannot tell "the
version filter held" apart from "the scope was empty" — the gap that lets a
silent downgrade at `public_docs_query` go unnoticed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord

_OLD_VERSION = "24.12"
_NEW_VERSION = "25.1"
_ABSENT_VERSION = "23.4"


def _record(*, chunk_id: str, version: str, text: str) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version=version,
        source_kind="docs",
        doc_locale="en",
        doc_type="guide_step",
        symbol_fqn=None,
        title=f"Recognize text ({version})",
        section_path=("root", "Recognize text"),
        canonical_url=f"https://docs.aspose.com/ocr/net/{version}/quickstart/",
        section_anchor="#recognize-text",
        source_path=f"source/{chunk_id}.md",
        source_revision=f"revision-{version}",
        is_deprecated=False,
        has_code_example=False,
        chunk_type="guide_step",
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )


_RECORDS: tuple[StageDChunkRecord, ...] = (
    _record(
        chunk_id="chunk-old",
        version=_OLD_VERSION,
        text="Call AsposeOcr.RecognizeImage to recognize text from one image.",
    ),
    _record(
        chunk_id="chunk-new",
        version=_NEW_VERSION,
        text="Call AsposeOcr.RecognizeImage to recognize text from one image.",
    ),
)


@pytest.fixture
def app_with_two_versions() -> FastAPI:
    app = create_app()
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        # Deliberately version-blind: the store hands back every version it holds,
        # so anything filtered out downstream was filtered by the version
        # predicate under test rather than by the fixture.
        return tuple(
            record
            for record in _RECORDS
            if (product_id is None or record.product_id == product_id.casefold())
            and (
                programming_language is None
                or record.programming_language == programming_language.casefold()
            )
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]
    app.state.public_query_service._qdrant_url = None  # type: ignore[attr-defined]
    return app


def _query(client: TestClient, *, version: str, strict: bool) -> dict[str, object]:
    response = client.post(
        "/v1/docs:query",
        json={
            "query": "How do I recognize text from an image?",
            "product_id": "aspose.ocr",
            "language": "net",
            "version": version,
            "query_locale": "en",
            "top_k": 5,
            "strict_version": strict,
        },
    )
    assert response.status_code == 200
    payload: dict[str, object] = response.json()
    return payload


_VERSION_BY_CHUNK = {record.chunk_id: record.version for record in _RECORDS}


def _versions_in(payload: dict[str, object]) -> set[str]:
    """Map served chunks back to their version.

    Result items carry no ``version`` field, so the version is recovered from the
    chunk id — which also proves the served chunk is one the fixture created
    rather than something synthesised downstream.
    """
    results = payload["results"]
    assert isinstance(results, list)
    return {_VERSION_BY_CHUNK[str(item["chunk_id"])] for item in results}


def test_strict_version_returns_only_the_requested_version(
    app_with_two_versions: FastAPI,
) -> None:
    with TestClient(app_with_two_versions) as client:
        payload = _query(client, version=_OLD_VERSION, strict=True)

    assert _versions_in(payload) == {_OLD_VERSION}, (
        "strict_version must not mix versions"
    )


def test_strict_version_absent_returns_empty_rather_than_other_versions(
    app_with_two_versions: FastAPI,
) -> None:
    """The regression: an empty strict scope must stay empty, not silently downgrade.

    The corpus holds 24.12 and 25.1; asking strictly for 23.4 previously replanned
    with ``strict_version=False`` and served 25.1 content for a request that
    forbade it.
    """
    with TestClient(app_with_two_versions) as client:
        payload = _query(client, version=_ABSENT_VERSION, strict=True)

    assert payload["results"] == []
    assert _versions_in(payload) == set()
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    assert "strict_version_no_match" in warnings


def test_non_strict_version_may_serve_nearest_available(
    app_with_two_versions: FastAPI,
) -> None:
    """Cross-version answers stay available — as an explicit opt-in, not a fallback."""
    with TestClient(app_with_two_versions) as client:
        payload = _query(client, version=_ABSENT_VERSION, strict=False)

    served = _versions_in(payload)
    assert served, "non-strict requests should still be answerable from other versions"
    assert served <= {_OLD_VERSION, _NEW_VERSION}
