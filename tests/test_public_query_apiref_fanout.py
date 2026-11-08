"""query_docs two-source fan-out (ADR-011).

A ``PublicQueryService`` built with an ``apiref_symbol_store`` fuses structured
API-reference symbols (Postgres) into the documentation retrieval result, so
apiref does not need the legacy ``apiref_dense_v1`` Qdrant lane.
Without a store, behaviour is docs-only and unchanged.
"""

from __future__ import annotations

from adcs.api.public_docs_query import PublicQueryService, _candidate_selection_trace
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
)
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.retrieval.models import QueryPlannerInput
from adcs.retrieval.retrieval_models import HybridRetrievalResult
from adcs.retrieval.translation_fallback import TranslationFallbackService

SCOPE = ApiRefScope(product="aspose.cells", language="net", version="25.4", locale="en")


def _symbol(**overrides: object) -> ApiRefSymbol:
    base: dict[str, object] = {
        "snapshot_id": "snap-1",
        "product": "aspose.cells",
        "language": "net",
        "version": "25.4",
        "locale": "en",
        "kind": "class",
        "member_fqn": "aspose.cells.workbook",
        "name": "Workbook",
        "parent_fqn": None,
        "signature": "public class Workbook : IDisposable",
        "canonical_url": "https://reference.aspose.com/cells/net/aspose.cells/workbook/",
        "is_deprecated": False,
        "summary": "The Workbook class is the central object for creating Excel files.",
        "payload": {"section_anchor": "#workbook", "source_revision": "rev-7"},
    }
    base.update(overrides)
    return ApiRefSymbol(**base)  # type: ignore[arg-type]


def _store_with(*symbols: ApiRefSymbol) -> InMemoryApiRefSymbolStore:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(symbols)
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    return store


def _service(store: InMemoryApiRefSymbolStore | None) -> PublicQueryService:
    return PublicQueryService(
        source_hugo_normalization_orchestrator=SourceHugoNormalizationOrchestrationService(),
        translation_fallback_service=TranslationFallbackService(),
        apiref_symbol_store=store,
    )


def _empty_result() -> HybridRetrievalResult:
    return HybridRetrievalResult(
        query_fingerprint="",
        normalized_query="workbook",
        candidates=(),
        dense_candidates_count=0,
        lexical_candidates_count=0,
        fused_candidates_count=0,
        dense_weight=0.55,
        lexical_weight=0.45,
    )


def test_candidate_trace_distinguishes_budget_from_top_k():
    from dataclasses import replace

    candidate = PublicQueryService._apiref_symbol_to_candidate(symbol=_symbol(), rank=0)
    candidates = tuple(
        replace(candidate, metadata=replace(candidate.metadata, candidate_id=f"c{i}"))
        for i in range(3)
    )
    trace = _candidate_selection_trace(candidates=candidates, packed_ids={"c0"}, top_k=2)
    assert [row["selection"] for row in trace] == [
        "packed", "excluded_by_context_budget", "outside_top_k"
    ]
    assert [row["rank"] for row in trace] == [1, 2, 3]


def test_fanout_trace_records_generated_candidates_without_changing_ranking():
    service = _service(_store_with(_symbol()))
    plan = service._query_planner.plan(request=QueryPlannerInput(
        query="Workbook", product_id="aspose.cells", programming_language="net"
    ))
    options = dict(
        retrieval_result=_empty_result(), plan=plan, query="Workbook",
        product_id="aspose.cells", programming_language="net", version=None,
    )
    trace = {}
    traced = service._fuse_apiref_symbols(**options, diagnostic_trace=trace)
    normal = service._fuse_apiref_symbols(**options)
    assert traced == normal
    assert len(trace["api_candidates"]) == 1
    assert trace["api_candidates"][0]["symbol_fqn"] == "aspose.cells.workbook"


def test_resolve_active_version_picks_latest_numeric_aware() -> None:
    store = InMemoryApiRefSymbolStore()
    for version, snap in (("9.10", "a"), ("25.4", "b"), ("9.2", "c")):
        store.flip_active_snapshot(
            scope=ApiRefScope(
                product="aspose.cells", language="net", version=version, locale="en"
            ),
            snapshot_id=snap,
        )
    # 25.4 wins (numeric-aware: 25 > 9; 9.10 > 9.2).
    assert store.resolve_active_version(product="aspose.cells", language="net") == "25.4"
    # Unknown scope -> None.
    assert store.resolve_active_version(product="nope", language="net") is None


def test_apiref_candidates_match_query_and_carry_citation() -> None:
    service = _service(_store_with(_symbol()))
    candidates = service._apiref_symbol_candidates(
        query="Workbook",
        product_id="aspose.cells",
        programming_language="net",
        version=None,  # resolved from the active snapshot
        limit=20,
    )
    assert len(candidates) == 1
    meta = candidates[0].metadata
    assert meta.source_kind == "apiref"
    assert meta.symbol_fqn == "aspose.cells.workbook"
    assert meta.doc_type == "api_reference_symbol"
    # Citation-backed (CLAUDE.md rule #1): canonical_url + anchor + revision.
    assert meta.canonical_url.endswith("/workbook/")
    assert meta.section_anchor == "#workbook"
    assert meta.source_revision == "rev-7"
    assert "public class Workbook" in meta.text


def test_active_apiref_version_preferred_over_docs_version() -> None:
    # Apiref is loaded under a single "latest-stable" snapshot, while docs use
    # numeric release versions. A caller passing a numeric docs version must
    # still get apiref hits: the active apiref version wins.
    ls_scope = ApiRefScope(
        product="aspose.cells", language="net", version="latest-stable", locale="en"
    )
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols([_symbol(version="latest-stable")])
    store.flip_active_snapshot(scope=ls_scope, snapshot_id="snap-1")
    service = _service(store)

    candidates = service._apiref_symbol_candidates(
        query="Workbook",
        product_id="aspose.cells",
        programming_language="net",
        version="25.1",  # a docs version that does NOT match apiref's snapshot
        limit=20,
    )
    assert [c.metadata.symbol_fqn for c in candidates] == ["aspose.cells.workbook"]


def test_apiref_candidates_empty_without_store_or_language() -> None:
    # No store -> no fan-out.
    assert (
        _service(None)._apiref_symbol_candidates(
            query="Workbook",
            product_id="aspose.cells",
            programming_language="net",
            version=None,
            limit=20,
        )
        == ()
    )
    # No language -> apiref scope cannot be built.
    assert (
        _service(_store_with(_symbol()))._apiref_symbol_candidates(
            query="Workbook",
            product_id="aspose.cells",
            programming_language=None,
            version=None,
            limit=20,
        )
        == ()
    )


def test_fuse_adds_apiref_to_docs_result() -> None:
    service = _service(_store_with(_symbol()))
    plan = service._query_planner.plan(
        request=QueryPlannerInput(
            query="Workbook",
            product_id="aspose.cells",
            programming_language="net",
            version=None,
            doc_locale=None,
            strict_version=False,
        )
    )
    fused = service._fuse_apiref_symbols(
        retrieval_result=_empty_result(),
        plan=plan,
        query="Workbook",
        product_id="aspose.cells",
        programming_language="net",
        version=None,
    )
    assert any(c.metadata.symbol_fqn == "aspose.cells.workbook" for c in fused.candidates)
    assert fused.fused_candidates_count == len(fused.candidates) == 1


def test_fuse_is_noop_without_store() -> None:
    service = _service(None)
    plan = service._query_planner.plan(
        request=QueryPlannerInput(
            query="Workbook",
            product_id="aspose.cells",
            programming_language="net",
            version=None,
            doc_locale=None,
            strict_version=False,
        )
    )
    original = _empty_result()
    fused = service._fuse_apiref_symbols(
        retrieval_result=original,
        plan=plan,
        query="Workbook",
        product_id="aspose.cells",
        programming_language="net",
        version=None,
    )
    assert fused is original  # untouched -> docs-only behaviour preserved


def test_exact_fqn_query_pins_symbol() -> None:
    service = _service(_store_with(_symbol()))
    candidates = service._apiref_symbol_candidates(
        query="aspose.cells.workbook",  # bare dotted FQN
        product_id="aspose.cells",
        programming_language="net",
        version=None,
        limit=20,
    )
    assert candidates[0].metadata.symbol_fqn == "aspose.cells.workbook"


def test_mail_merge_question_keeps_relevant_api_candidate_in_fanout():
    scope = ApiRefScope(product="aspose.words", language="net", version="25.4", locale="en")
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols([
        _symbol(product="aspose.words", name="Performer",
                member_fqn="Aspose.Words.Bibliography.Contributorcollection.Performer",
                summary="A performer.", signature="public Contributor Performer { get; set; }"),
        _symbol(product="aspose.words", name="MailMerge",
                member_fqn="Aspose.Words.Document.Mailmerge",
                summary="Returns the mail merge functionality for the document.",
                signature="public MailMerge MailMerge { get; }",
                canonical_url="https://reference.aspose.com/words/net/aspose.words/document/mailmerge/"),
    ])
    store.flip_active_snapshot(scope=scope, snapshot_id="snap-1")
    service = _service(store)
    query = "How do I perform mail merge in Aspose.Words for .NET?"
    plan = service._query_planner.plan(request=QueryPlannerInput(
        query=query, product_id="aspose.words", programming_language="net"
    ))
    trace = {}
    result = service._fuse_apiref_symbols(
        retrieval_result=_empty_result(), plan=plan, query=query,
        product_id="aspose.words", programming_language="net", version=None,
        diagnostic_trace=trace,
    )
    assert plan.intent == "how_to"
    assert trace["api_candidates"][0]["symbol_fqn"] == "Aspose.Words.Document.Mailmerge"
    assert result.candidates[0].metadata.symbol_fqn == "Aspose.Words.Document.Mailmerge"
