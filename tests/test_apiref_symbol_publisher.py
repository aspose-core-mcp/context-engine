from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from adcs.indexing.apiref_symbol_publisher import ApiRefSymbolPublisher
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import (
    NormalizedDocument,
    NormalizedDocumentMetadata,
)
from adcs.ingestion.staging_store import StagingSnapshotTier

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")


def _chunk(
    *,
    source_path: str,
    symbol_fqn: str | None,
    chunk_type: str,
    text: str,
    doc_type: str = "api_reference_symbol",
    title: str = "",
    is_deprecated: bool = False,
    doc_locale: str = "english",
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=f"{source_path}:{chunk_type}",
        repo_id="aspose.slides.apiref",
        product_id="aspose.slides",
        product_family="aspose",
        programming_language="net",
        version="24.1",
        source_kind="apiref",
        doc_locale=doc_locale,
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=title or (symbol_fqn or "").rsplit(".", 1)[-1],
        section_path=("root",),
        canonical_url=f"https://ref.aspose.com/{symbol_fqn or 'ns'}",
        section_anchor="#main",
        source_path=source_path,
        source_revision="rev1",
        is_deprecated=is_deprecated,
        has_code_example=(chunk_type == "api_example"),
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum="x",
    )


def _doc(*, symbol_fqn: str | None, symbol_kind: str | None, doc_type: str) -> NormalizedDocument:
    return NormalizedDocument(
        schema="adcs.normalized_document.v1",
        document=NormalizedDocumentMetadata(
            repo_id="aspose.slides.apiref",
            product_id="aspose.slides",
            product_family="aspose",
            source_kind="apiref",
            programming_language="net",
            doc_locale="english",
            version="24.1",
            title=(symbol_fqn or "ns").rsplit(".", 1)[-1],
            doc_type=doc_type,
            canonical_url=f"https://ref.aspose.com/{symbol_fqn or 'ns'}",
            source_path="p",
            source_revision="rev1",
            symbol_fqn=symbol_fqn,
            symbol_kind=symbol_kind,
        ),
        chunks=(),
        warnings=(),
    )


class _FakeStaging:
    """In-memory staging source grouped/sorted by source_path."""

    def __init__(
        self,
        *,
        documents: list[NormalizedDocument],
        chunks: list[StageDChunkRecord],
    ) -> None:
        self._documents = documents
        self._chunks = chunks

    def iter_canonical_documents(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]:
        del repo_id, source_revision, snapshot_tier
        if source_kind != "apiref":
            return iter(())
        return iter(self._documents)

    def iter_chunk_records(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        del repo_id, source_revision, snapshot_tier
        if source_kind != "apiref":
            return iter(())
        return iter(self._chunks)


def _corpus_staging() -> _FakeStaging:
    documents = [
        _doc(
            symbol_fqn="aspose.slides.Presentation",
            symbol_kind="class",
            doc_type="api_reference_symbol",
        ),
        _doc(
            symbol_fqn="aspose.slides.Presentation.Save",
            symbol_kind="method",
            doc_type="api_reference_symbol",
        ),
        _doc(
            symbol_fqn="aspose.slides.Presentation.Slides",
            symbol_kind="property",
            doc_type="api_reference_symbol",
        ),
        _doc(symbol_fqn=None, symbol_kind="namespace", doc_type="api_reference_namespace"),
    ]
    # Grouped/sorted by source_path (as the staging store emits them).
    chunks = [
        # Page: class Presentation
        _chunk(
            source_path="a_presentation",
            symbol_fqn="aspose.slides.Presentation",
            chunk_type="api_remarks",
            text="Represents a PowerPoint presentation. It holds slides.",
        ),
        # Page: namespace (skipped)
        _chunk(
            source_path="b_namespace",
            symbol_fqn=None,
            chunk_type="api_remarks",
            text="Namespace overview.",
            doc_type="api_reference_namespace",
        ),
        # Page: Save overload #1
        _chunk(
            source_path="c_save",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_signature",
            text="void Save(string fileName)",
        ),
        _chunk(
            source_path="c_save",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_parameters",
            text="fileName: target path",
        ),
        _chunk(
            source_path="c_save",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_remarks",
            text="Saves the presentation to a file.",
        ),
        _chunk(
            source_path="c_save",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_example",
            text='pres.Save("out.pptx");',
        ),
        # Page: Save overload #2 (same FQN, different page/signature)
        _chunk(
            source_path="d_save2",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_signature",
            text="void Save(Stream stream, SaveFormat format)",
        ),
        _chunk(
            source_path="d_save2",
            symbol_fqn="aspose.slides.Presentation.Save",
            chunk_type="api_remarks",
            text="Saves the presentation to a stream.",
        ),
        # Page: property Slides
        _chunk(
            source_path="e_slides",
            symbol_fqn="aspose.slides.Presentation.Slides",
            chunk_type="api_remarks",
            text="Returns the collection of slides.",
        ),
    ]
    return _FakeStaging(documents=documents, chunks=chunks)


def test_publish_aggregates_pages_into_symbols() -> None:
    store = InMemoryApiRefSymbolStore()
    publisher = ApiRefSymbolPublisher(store=store, staging=_corpus_staging())
    result = publisher.publish(repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1")

    assert result.pages_seen == 5
    assert result.namespaces_skipped == 1
    assert result.symbols_written == 4  # class + 2 Save overloads + Slides
    assert SCOPE in result.scopes_activated

    # Class kind comes from the document kind-map.
    pres = store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE)
    assert len(pres) == 1
    assert pres[0].kind == "class"
    assert pres[0].parent_fqn == "aspose.slides"
    assert pres[0].name == "Presentation"
    assert pres[0].summary == "Represents a PowerPoint presentation."
    # The section anchor must be carried into the payload so get_symbol_doc
    # citations served from the structured store keep canonical_url + anchor.
    assert pres[0].payload["section_anchor"] == "#main"


def test_publish_keeps_overloads_as_distinct_rows() -> None:
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=_corpus_staging()).publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1"
    )
    saves = store.get_symbol(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)
    assert len(saves) == 2
    assert {s.signature for s in saves} == {
        "void Save(string fileName)",
        "void Save(Stream stream, SaveFormat format)",
    }
    # Facets are aggregated into the payload.
    with_params = next(s for s in saves if s.signature == "void Save(string fileName)")
    assert with_params.payload["parameters"] == "fileName: target path"
    assert with_params.payload["examples"] == ['pres.Save("out.pptx");']

    overloads = store.list_overloads(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)
    assert len(overloads) == 2


def test_publish_supports_all_query_patterns_end_to_end() -> None:
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=_corpus_staging()).publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1"
    )
    members = store.list_members(parent_fqn="aspose.slides.Presentation", scope=SCOPE)
    assert [m.name for m in members] == ["Save", "Save", "Slides"]
    assert {s.name for s in store.search_symbols(pattern="Pres", scope=SCOPE)} == {"Presentation"}
    fts = store.fts_search(query="stream", scope=SCOPE)
    assert any("stream" in (s.summary or "").lower() for s in fts)


def test_publish_without_activate_leaves_snapshot_invisible() -> None:
    store = InMemoryApiRefSymbolStore()
    publisher = ApiRefSymbolPublisher(store=store, staging=_corpus_staging())
    result = publisher.publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1", activate=False
    )
    assert result.symbols_written == 4
    assert result.scopes_activated == ()
    # Not activated → queries see nothing until an explicit flip.
    assert store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE) == ()
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    assert len(store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE)) == 1


def test_publish_small_batch_size_still_writes_all() -> None:
    store = InMemoryApiRefSymbolStore()
    publisher = ApiRefSymbolPublisher(store=store, staging=_corpus_staging(), batch_size=1)
    result = publisher.publish(repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1")
    assert result.symbols_written == 4
    assert len(store.list_members(parent_fqn="aspose.slides.Presentation", scope=SCOPE)) == 3


def test_publish_falls_back_to_symbol_kind_when_map_missing() -> None:
    # Chunk records present, but no canonical document → kind unknown → "symbol".
    staging = _FakeStaging(
        documents=[],
        chunks=[
            _chunk(
                source_path="x",
                symbol_fqn="aspose.slides.Mystery",
                chunk_type="api_remarks",
                text="Undocumented kind.",
            )
        ],
    )
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1"
    )
    rows = store.get_symbol(member_fqn="aspose.slides.Mystery", scope=SCOPE)
    assert len(rows) == 1
    assert rows[0].kind == "symbol"


def test_publish_derives_kind_from_title_when_document_missing() -> None:
    # Older staging: chunk records exist but the canonical document carries
    # no symbol_kind (kind map empty). The publisher recovers the kind from the
    # chunk record's page title suffix ("Presentation Class" → class).
    staging = _FakeStaging(
        documents=[],
        chunks=[
            _chunk(
                source_path="pres",
                symbol_fqn="aspose.slides.Presentation",
                chunk_type="api_remarks",
                text="Represents a presentation.",
                title="Presentation Class",
            ),
            _chunk(
                source_path="save",
                symbol_fqn="aspose.slides.Presentation.Save",
                chunk_type="api_signature",
                text="void Save(string fileName)",
                title="Save Method",
            ),
        ],
    )
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="snap-1"
    )
    assert store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE)[0].kind == "class"
    assert (
        store.get_symbol(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)[0].kind
        == "method"
    )


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_publish_end_to_end_into_postgres() -> None:
    # Full ingestion path: staging chunks → publisher → live Postgres store.
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    store.ping()
    result = ApiRefSymbolPublisher(store=store, staging=_corpus_staging()).publish(
        repo_ids=["aspose.slides.apiref"], snapshot_id="pub-e2e"
    )
    assert result.symbols_written == 4
    assert SCOPE in result.scopes_activated

    saves = store.get_symbol(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)
    assert len(saves) == 2
    members = store.list_members(parent_fqn="aspose.slides.Presentation", scope=SCOPE)
    assert [m.name for m in members] == ["Save", "Save", "Slides"]
    assert any(s.name == "Presentation" for s in store.search_symbols(pattern="Pres", scope=SCOPE))
    assert store.fts_search(query="stream", scope=SCOPE)
