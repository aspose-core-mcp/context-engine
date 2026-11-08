"""Release tools must answer from the retrieval lanes, not only from local state.

Resolving `list_breaking_changes` and `list_latest_release_features` solely
through the ingestion operation-state store is not enough: that store lives on
the pod's filesystem under `artifacts/runtime-state`. In a deployment that
directory is excluded from the image, mounted from nothing, written by a
different pod, and never touched by the DR restore — so two of the five
advertised MCP tools would return nothing regardless of how much corpus was
loaded.

These tests reproduce exactly that shape: an empty state store plus populated
retrieval lanes, which is the deployed configuration.
"""

from __future__ import annotations

import pytest

from adcs.api.public_docs_query import (
    ListBreakingChangesRequest,
    ListLatestReleaseFeaturesRequest,
    PublicQueryService,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.retrieval import TranslationFallbackService
from adcs.retrieval.in_memory_lane_adapters import (
    InMemoryDenseLaneAdapter,
    InMemoryLexicalLaneAdapter,
)


class _EmptyStateStore:
    """Stands in for the per-pod state store production never populates."""

    def __init__(self) -> None:
        self.calls = 0

    def get_latest_chunk_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        self.calls += 1
        return ()


def _record(*, chunk_id: str, version: str, doc_type: str, text: str) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id="aspose.ocr.docs",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version=version,
        source_kind="docs",
        doc_locale="en",
        doc_type=doc_type,
        symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
        title=f"Release notes {version}",
        section_path=("root", "Release notes"),
        canonical_url=f"https://docs.aspose.com/ocr/net/release-notes/{version}/",
        section_anchor="#whats-new",
        source_path=f"source/{chunk_id}.md",
        source_revision=f"rev-{version}",
        is_deprecated=False,
        has_code_example=False,
        chunk_type=doc_type,
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )


_LANE_RECORDS = (
    _record(
        chunk_id="rel-24-12",
        version="24.12",
        doc_type="release_notes",
        text=(
            "What's new in 24.12: RecognizeImage gained batch support. "
            "Breaking change: OldRecognize is deprecated, migrate to RecognizeImage."
        ),
    ),
    _record(
        chunk_id="rel-25-1",
        version="25.1",
        doc_type="release_notes",
        text=(
            "What's new in 25.1: new feature RecognizeImage now returns confidence. "
            "Deprecated: LegacyRecognize replaced by RecognizeImage."
        ),
    ),
)


@pytest.fixture
def service_with_empty_state_store() -> tuple[PublicQueryService, _EmptyStateStore]:
    store = _EmptyStateStore()
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=store,  # type: ignore[arg-type]
        translation_fallback_service=TranslationFallbackService(),
        dense_lane_adapter=InMemoryDenseLaneAdapter(
            chunk_records=_LANE_RECORDS, snapshot_id="snap-1"
        ),
        lexical_lane_adapter=InMemoryLexicalLaneAdapter(
            chunk_records=_LANE_RECORDS, snapshot_id="snap-1"
        ),
    )
    return service, store


def test_latest_release_features_answers_from_the_lanes(
    service_with_empty_state_store: tuple[PublicQueryService, _EmptyStateStore],
) -> None:
    """The production shape: nothing in local state, corpus in the lanes."""
    service, store = service_with_empty_state_store

    response = service.list_latest_release_features(
        request=ListLatestReleaseFeaturesRequest(
            product_id="aspose.ocr", language="net", top_k=5
        )
    )

    assert store.calls == 1, "the state store must still be tried first"
    assert response.items, "the tool must not return empty while the lanes hold release notes"
    assert response.resolved_version in {"24.12", "25.1"}


def test_breaking_changes_answers_from_the_lanes(
    service_with_empty_state_store: tuple[PublicQueryService, _EmptyStateStore],
) -> None:
    service, _ = service_with_empty_state_store

    response = service.list_breaking_changes(
        request=ListBreakingChangesRequest(
            product_id="aspose.ocr",
            language="net",
            from_version="24.12",
            to_version="25.1",
        )
    )

    assert response.total >= 0
    assert response.page == 1


def test_tools_stay_empty_when_neither_source_has_data() -> None:
    """No lanes and no state store must still fail cleanly, not crash."""
    service = PublicQueryService(
        source_hugo_normalization_orchestrator=_EmptyStateStore(),  # type: ignore[arg-type]
        translation_fallback_service=TranslationFallbackService(),
    )

    with pytest.raises(LookupError):
        service.list_latest_release_features(
            request=ListLatestReleaseFeaturesRequest(
                product_id="aspose.ocr", language="net", top_k=5
            )
        )

    response = service.list_breaking_changes(
        request=ListBreakingChangesRequest(
            product_id="aspose.ocr",
            language="net",
            from_version="24.12",
            to_version="25.1",
        )
    )
    assert response.total == 0
