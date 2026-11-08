"""Strict-version isolation through the real retrieval lanes.

`tests/test_strict_version_isolation.py` already covers this guarantee, but via
the operation-state store: it patches `get_latest_chunk_records` and disables the
Qdrant path. That is not how production answers a query — production goes through
the dense and lexical lane adapters, where the version predicate is applied by
`FilterResolver.record_matches_route` rather than by the caller.

On its own, that covers a path production does not use. These tests drive
the same requests through the in-memory lane adapters, which run the real filter
resolver, over a corpus holding two versions of one product.
"""

from __future__ import annotations

import pytest

from adcs.api.public_docs_query import PublicQueryService, QueryDocsRequest
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.retrieval import TranslationFallbackService
from adcs.retrieval.in_memory_lane_adapters import (
    InMemoryDenseLaneAdapter,
    InMemoryLexicalLaneAdapter,
)

_OLD = "24.12"
_NEW = "25.1"
_ABSENT = "23.4"


def _record(*, chunk_id: str, version: str) -> StageDChunkRecord:
    text = (
        "Call AsposeOcr.RecognizeImage to recognize text from one image. "
        f"Applies to release {version}."
    )
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
        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
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


_RECORDS = (
    _record(chunk_id="chunk-old", version=_OLD),
    _record(chunk_id="chunk-new", version=_NEW),
)
_VERSION_BY_CHUNK = {record.chunk_id: record.version for record in _RECORDS}


class _EmptyStateStore:
    """Forces every answer through the lanes, as production does."""

    def get_latest_chunk_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return ()


@pytest.fixture
def service() -> PublicQueryService:
    return PublicQueryService(
        source_hugo_normalization_orchestrator=_EmptyStateStore(),  # type: ignore[arg-type]
        translation_fallback_service=TranslationFallbackService(),
        dense_lane_adapter=InMemoryDenseLaneAdapter(
            chunk_records=_RECORDS, snapshot_id="snap-1"
        ),
        lexical_lane_adapter=InMemoryLexicalLaneAdapter(
            chunk_records=_RECORDS, snapshot_id="snap-1"
        ),
    )


def _versions_served(service: PublicQueryService, *, version: str, strict: bool) -> set[str]:
    response = service.query_docs(
        request=QueryDocsRequest(
            query="How do I recognize text from an image?",
            product_id="aspose.ocr",
            language="net",
            version=version,
            query_locale="en",
            top_k=5,
            strict_version=strict,
        )
    )
    return {_VERSION_BY_CHUNK[item.chunk_id] for item in response.results}


def test_lane_path_serves_only_the_requested_version(service: PublicQueryService) -> None:
    """The version predicate is applied in the lane, not by the caller."""
    assert _versions_served(service, version=_OLD, strict=True) == {_OLD}
    assert _versions_served(service, version=_NEW, strict=True) == {_NEW}


def test_lane_path_returns_nothing_for_an_absent_version(service: PublicQueryService) -> None:
    """An empty strict scope stays empty on the path production actually uses."""
    assert _versions_served(service, version=_ABSENT, strict=True) == set()


def test_lane_path_allows_cross_version_only_when_asked(service: PublicQueryService) -> None:
    served = _versions_served(service, version=_ABSENT, strict=False)
    assert served, "a non-strict request should still be answerable from other versions"
    assert served <= {_OLD, _NEW}


def test_mcp_transport_enforces_the_same_isolation(service: PublicQueryService) -> None:
    """MCP must not be a way around the guarantee.

    The gateway rewrites strict_version when no version is given, so the two
    transports have already disagreed about version handling once.
    """
    from adcs.mcp.tool_gateway import MCPToolGateway

    gateway = MCPToolGateway(
        public_query_service=service,
        supported_revisions=("2025-11-25", "2025-06-18", "2024-11-05"),
        primary_revision="2025-11-25",
    )
    session = gateway.initialize(requested_revision="2025-11-25")
    result = gateway.call_tool(
        session_id=session.session_id,
        tool_name="query_docs",
        arguments={
            "query": "How do I recognize text from an image?",
            "product_id": "aspose.ocr",
            "language": "net",
            "version": _OLD,
            "query_locale": "en",
            "top_k": 5,
            "strict_version": True,
        },
    )
    served = {_VERSION_BY_CHUNK[item["chunk_id"]] for item in result["results"]}
    assert served == {_OLD}, f"MCP leaked other versions: {served}"
