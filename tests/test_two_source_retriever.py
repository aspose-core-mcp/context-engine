from __future__ import annotations

from collections.abc import Sequence

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
)
from adcs.retrieval.retrieval_models import HybridCandidate, RetrievalCandidateMetadata
from adcs.retrieval.two_source_retriever import (
    ApiRefRetriever,
    TwoSourceRetriever,
    api_search_queries,
    looks_like_fqn,
)

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")


def test_question_expansion_is_bounded_and_preserves_identifiers():
    query = "How do I convert a Word document to PDF?"
    assert api_search_queries(query) == (query, "convert", "Word", "document", "PDF")
    assert api_search_queries("Aspose.Words.Document.Save") == ("Aspose.Words.Document.Save",)
    assert len(api_search_queries("one two three four five six seven")) <= 5


def test_question_candidates_interleave_terms_without_losing_overloads():
    class Store:
        def __init__(self):
            self.calls = []

        def search_symbols(self, *, pattern, scope, limit):
            assert scope == SCOPE
            self.calls.append(pattern)
            if pattern == "PDF":
                return [_sym(member_fqn="PdfSaveOptions", name="PdfSaveOptions")]
            if pattern == "document":
                return [
                    _sym(member_fqn="Document.Save", name="Save", signature="Save(string)"),
                    _sym(member_fqn="Document.Save", name="Save", signature="Save(Stream)"),
                ]
            return []

        def fts_search(self, *, query, scope, limit):
            return self.search_symbols(pattern=query, scope=scope, limit=limit)

    store = Store()
    hits = ApiRefRetriever(store=store).search(
        query="How do I convert a Word document to PDF?", scope=SCOPE, limit=3
    )
    assert len(hits) == 3
    assert {s.signature for s in hits if s.name == "Save"} == {"Save(string)", "Save(Stream)"}
    assert any(s.name == "PdfSaveOptions" for s in hits)
    assert len(store.calls) <= 10


def _doc(*, chunk_id: str, title: str, url: str, text: str) -> HybridCandidate:
    meta = RetrievalCandidateMetadata(
        candidate_id=chunk_id,
        chunk_id=chunk_id,
        snapshot_id="docs-snap",
        product_id="aspose.slides",
        programming_language="net",
        version="24.1",
        source_kind="docs",
        doc_type="guide",
        doc_locale="en",
        symbol_fqn=None,
        title=title,
        canonical_url=url,
        section_anchor="#main",
        source_revision="rev1",
        repo_id="aspose.slides.docs",
        text=text,
        checksum="x",
    )
    return HybridCandidate(
        metadata=meta,
        dense_raw_score=0.9,
        lexical_raw_score=0.8,
        dense_normalized_score=1.0,
        lexical_normalized_score=1.0,
        blended_score=1.0,
        rerank_score=1.0,
    )


class _FakeDocsLane:
    def __init__(self, candidates: Sequence[HybridCandidate]) -> None:
        self._candidates = tuple(candidates)

    def search(self, *, query: str, limit: int) -> Sequence[HybridCandidate]:
        del query
        return self._candidates[:limit]


def _sym(
    *,
    member_fqn: str,
    name: str,
    kind: str = "method",
    parent_fqn: str | None = None,
    signature: str | None = None,
    summary: str | None = None,
    url: str | None = None,
) -> ApiRefSymbol:
    return ApiRefSymbol(
        snapshot_id="apiref-snap",
        product=SCOPE.product,
        language=SCOPE.language,
        version=SCOPE.version,
        locale=SCOPE.locale,
        kind=kind,
        member_fqn=member_fqn,
        name=name,
        parent_fqn=parent_fqn,
        signature=signature,
        canonical_url=url or f"https://ref.aspose.com/{member_fqn}",
        is_deprecated=False,
        summary=summary,
        payload={},
    )


def _seed_apiref() -> InMemoryApiRefSymbolStore:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(
        [
            _sym(
                member_fqn="aspose.slides.Presentation",
                name="Presentation",
                kind="class",
                parent_fqn="aspose.slides",
                summary="Represents a presentation that you can save.",
            ),
            _sym(
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(string fileName, SaveFormat format)",
                summary="Saves the presentation to a file.",
            ),
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="apiref-snap")
    return store


# --- looks_like_fqn ---------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("aspose.slides.Presentation.Save", True),
        ("Presentation.Save", True),
        ("aspose.slides.Presentation.Save()", True),
        ("how to save a presentation", False),
        ("Presentation", False),  # no dot
        ("save.the file", False),  # space
        ("aspose..slides", False),  # empty segment
    ],
)
def test_looks_like_fqn(query: str, expected: bool) -> None:
    assert looks_like_fqn(query) is expected


# --- fan-out + RRF ----------------------------------------------------------


def test_fans_out_to_both_sources() -> None:
    docs = _FakeDocsLane(
        [
            _doc(
                chunk_id="d1",
                title="Saving presentations",
                url="https://docs.aspose.com/slides/net/save/",
                text="To save a presentation call Save.",
            )
        ]
    )
    retriever = TwoSourceRetriever(
        docs_lane=docs, apiref_lane=ApiRefRetriever(store=_seed_apiref())
    )
    result = retriever.retrieve(query="save presentation", scope=SCOPE, limit=10)

    assert result.docs_count == 1
    assert result.apiref_count >= 1
    sources = {h.source for h in result.hits}
    assert sources == {"docs", "apiref"}
    assert not result.exact_symbol_hit


def test_rrf_ranks_earlier_results_higher() -> None:
    docs = _FakeDocsLane(
        [
            _doc(chunk_id=f"d{i}", title=f"t{i}", url=f"https://docs/{i}", text="save")
            for i in range(1, 4)
        ]
    )
    retriever = TwoSourceRetriever(
        docs_lane=docs, apiref_lane=ApiRefRetriever(store=InMemoryApiRefSymbolStore())
    )
    result = retriever.retrieve(query="save", scope=SCOPE, limit=10)
    docs_hits = [h for h in result.hits if h.source == "docs"]
    scores = [h.rrf_score for h in docs_hits]
    # Rank 1 → 1/(60+1) > rank 2 → 1/(60+2) > rank 3.
    assert scores == sorted(scores, reverse=True)
    assert docs_hits[0].rrf_score == pytest.approx(1.0 / 61)


# --- exact-FQN short-circuit ------------------------------------------------


def test_exact_fqn_short_circuits_to_top() -> None:
    docs = _FakeDocsLane([_doc(chunk_id="d1", title="t", url="https://docs/1", text="x")])
    retriever = TwoSourceRetriever(
        docs_lane=docs, apiref_lane=ApiRefRetriever(store=_seed_apiref())
    )
    result = retriever.retrieve(query="aspose.slides.Presentation.Save", scope=SCOPE, limit=10)
    assert result.exact_symbol_hit
    top = result.hits[0]
    assert top.is_exact_symbol
    assert top.source == "apiref"
    assert top.apiref_symbol is not None
    assert top.apiref_symbol.member_fqn == "aspose.slides.Presentation.Save"


def test_exact_hit_guaranteed_even_if_outside_search_pool() -> None:
    # apiref search returns nothing (empty fts/name), but exact lookup hits.
    class _EmptySearchLane:
        def __init__(self, store: InMemoryApiRefSymbolStore) -> None:
            self._inner = ApiRefRetriever(store=store)

        def lookup_exact(self, *, member_fqn, scope):
            return self._inner.lookup_exact(member_fqn=member_fqn, scope=scope)

        def search(self, *, query, scope, limit):
            return ()

    docs = _FakeDocsLane([])
    retriever = TwoSourceRetriever(docs_lane=docs, apiref_lane=_EmptySearchLane(_seed_apiref()))
    result = retriever.retrieve(query="aspose.slides.Presentation.Save", scope=SCOPE, limit=10)
    assert result.hits
    assert result.hits[0].is_exact_symbol
    assert result.hits[0].apiref_symbol is not None


# --- cross-source dedup -----------------------------------------------------


def test_dedup_merges_shared_canonical_url_and_sums_rrf() -> None:
    shared = "https://ref.aspose.com/aspose.slides.Presentation.Save"
    docs = _FakeDocsLane([_doc(chunk_id="d1", title="Save", url=shared, text="Save docs page")])
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(
        [
            _sym(
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                signature="void Save(string fileName)",
                summary="Saves to a file.",
                url=shared,
            )
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="apiref-snap")
    retriever = TwoSourceRetriever(docs_lane=docs, apiref_lane=ApiRefRetriever(store=store))
    result = retriever.retrieve(query="save file", scope=SCOPE, limit=10)

    merged = [h for h in result.hits if h.canonical_url == shared]
    assert len(merged) == 1  # one merged hit, not two
    # RRF score is the sum of docs rank-1 and apiref rank-1 contributions.
    assert merged[0].rrf_score == pytest.approx(2.0 / 61)
    # Representative prefers the structured apiref record.
    assert merged[0].source == "apiref"


def test_mail_merge_relevance_beats_early_fuzzy_performer_before_limit():
    unrelated = _sym(member_fqn="Aspose.Words.Bibliography.Contributorcollection.Performer",
                     name="Performer")
    relevant = [
        _sym(member_fqn="Aspose.Words.Mailmerging.Mailmerge.Execute", name="Execute",
             signature=signature)
        for signature in ("Execute(DataTable)", "Execute(string[], object[])")
    ]

    class Store:
        def search_symbols(self, *, pattern, scope, limit):
            return [unrelated] if pattern != "merge" else relevant

        def fts_search(self, *, query, scope, limit):
            return []

    query = "How do I perform mail merge in Aspose.Words for .NET?"
    assert api_search_queries(query) == (query, "mail", "merge")
    hits = ApiRefRetriever(store=Store()).search(query=query, scope=SCOPE, limit=2)
    assert list(hits) == relevant


@pytest.mark.parametrize('product,owner,operation', [
    ('Words', 'MailMerge', 'Execute'), ('Cells', 'Cells', 'ImportData'),
])
def test_generic_ranking_prefers_requested_parameter_and_output(product, owner, operation):
    from adcs.retrieval.two_source_retriever import _api_relevance

    def candidate(name, parameters):
        return _sym(member_fqn=f'Aspose.{product}.{owner}.{name}', name=name,
                    signature=f'public void {name}({parameters})')

    basic = candidate(operation, 'DataTable table')
    other_type = candidate(operation, 'DataSet data')
    images = candidate(operation + 'ToImages', 'DataTable table, ImageOptions options')
    query = f'How do I use {owner} with a DataTable in Aspose.{product} for .NET?'
    assert sorted([images, other_type, basic], key=lambda s: _api_relevance(s, query),
                  reverse=True)[0] == basic
    image_query = query + ' Output images.'
    assert _api_relevance(images, image_query) > _api_relevance(basic, image_query)


def test_generic_ranking_searches_beyond_output_limit_and_keeps_scope():
    scope = ApiRefScope(product='aspose.cells', language='net', version='25.4', locale='en')
    unrelated = _sym(member_fqn='Aspose.Cells.Cells.ImportDataToImages',
                     name='Importdatatoimages',
                     signature='public void ImportDataToImages(DataTable table, Options options)')
    relevant = _sym(member_fqn='Aspose.Cells.Cells.ImportData', name='Importdata',
                   signature='public void ImportData(DataTable table)')

    class Store:
        def search_symbols(self, *, pattern, scope, limit):
            assert scope.product == 'aspose.cells'
            assert scope.language == 'net' and scope.version == '25.4'
            assert 2 <= limit <= 150
            return [unrelated, relevant][:limit]

        def fts_search(self, *, query, scope, limit):
            return []

    hits = ApiRefRetriever(store=Store()).search(
        query='How do I import data from DataTable in Aspose.Cells?', scope=scope, limit=1,
    )
    assert list(hits) == [relevant]


def test_namespace_classes_are_scoped_and_do_not_use_fuzzy_search():
    from dataclasses import replace

    class Store:
        def list_members(self, *, parent_fqn, scope):
            assert parent_fqn == "Aspose.Slides.Export"
            assert scope == SCOPE
            return (
                replace(_sym(member_fqn=parent_fqn + ".PdfOptions", name="PdfOptions"),
                        kind="class"),
                replace(_sym(member_fqn=parent_fqn + ".SaveFormat", name="SaveFormat"),
                        kind="enum"),
            )

    lane = ApiRefRetriever(store=Store())
    hits = lane.search(query="What classes are in the Aspose.Slides.Export namespace?",
                       scope=SCOPE, limit=10)
    assert [h.name for h in hits] == ["PdfOptions"]
    hits = lane.search(query="List types in Aspose.Slides.Export namespace", scope=SCOPE, limit=1)
    assert len(hits) == 1
    assert not lane.search(query="List classes in Aspose.Words.AI namespace", scope=SCOPE, limit=10)


def test_namespace_listing_detection_is_narrow():
    from adcs.retrieval.two_source_retriever import namespace_listing_target

    assert namespace_listing_target(
        "List types in Acme.Documents.Export namespace"
    ) == "Acme.Documents.Export"
    assert namespace_listing_target("Explain Acme.Documents.Export namespace") is None
    assert namespace_listing_target(
        "Compare classes in Acme.Documents.A and Acme.Documents.B namespace"
    ) is None
    assert namespace_listing_target("Acme.Documents.Export") is None


def test_empty_namespace_does_not_fall_back_to_unrelated_apis():
    class Store:
        def list_members(self, *, parent_fqn, scope):
            return ()

    assert not ApiRefRetriever(store=Store()).search(
        query="List classes in Aspose.Slides.Missing namespace", scope=SCOPE, limit=10,
    )
