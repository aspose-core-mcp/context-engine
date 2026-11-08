from __future__ import annotations

import os

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.retrieval.apiref_recall_eval import (
    ApiRefEvalCase,
    evaluate_apiref_recall,
)
from adcs.retrieval.two_source_retriever import ApiRefRetriever

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")


def _s(member_fqn: str, kind: str, summary: str, signature: str | None = None) -> ApiRefSymbol:
    return ApiRefSymbol(
        snapshot_id="eval",
        product=SCOPE.product,
        language=SCOPE.language,
        version=SCOPE.version,
        locale=SCOPE.locale,
        kind=kind,
        member_fqn=member_fqn,
        name=member_fqn.rsplit(".", 1)[-1],
        parent_fqn=member_fqn.rsplit(".", 1)[0] if "." in member_fqn else None,
        signature=signature,
        canonical_url=f"https://ref.aspose.com/{member_fqn}",
        is_deprecated=False,
        summary=summary,
        payload={},
    )


def _corpus() -> list[ApiRefSymbol]:
    return [
        _s(
            "aspose.slides.Presentation",
            "class",
            "Represents a PowerPoint presentation document you can create load and save.",
        ),
        _s(
            "aspose.slides.Presentation.Save",
            "method",
            "Saves the presentation to a file or a stream in a given format.",
            "void Save(string fileName)",
        ),
        _s(
            "aspose.slides.Presentation.Save",
            "method",
            "Saves the presentation to a stream in a given format.",
            "void Save(Stream stream, SaveFormat format)",
        ),
        _s(
            "aspose.slides.Presentation.Slides",
            "property",
            "Gets the collection of all slides in the presentation.",
        ),
        _s(
            "aspose.slides.Presentation.Dispose",
            "method",
            "Releases all resources used by the presentation.",
        ),
        _s(
            "aspose.slides.SaveFormat",
            "enum",
            "Specifies the output file format used when saving a presentation.",
        ),
        _s("aspose.slides.ISlide", "interface", "Represents a single slide in a presentation."),
        _s("aspose.slides.ISlide.Shapes", "property", "Gets the shapes contained on the slide."),
        _s("aspose.slides.Shape", "class", "Represents a shape object placed on a slide."),
        _s(
            "aspose.slides.Shape.AddTextFrame",
            "method",
            "Adds a new text frame with the given text to the shape.",
        ),
        _s(
            "aspose.slides.ITextFrame",
            "interface",
            "Represents a text frame that holds text on a shape.",
        ),
        _s(
            "aspose.slides.SlideSize",
            "class",
            "Represents the dimensions and orientation of slides.",
        ),
        _s("aspose.slides.IChart", "interface", "Represents a chart placed on a slide."),
        _s("aspose.slides.IChart.ChartData", "property", "Gets the data backing the chart."),
        _s(
            "aspose.slides.PptxOptions",
            "class",
            "Provides options that control how a PPTX file is loaded.",
        ),
        _s(
            "aspose.slides.IAudioFrame",
            "interface",
            "Represents an audio clip embedded on a slide.",
        ),
    ]


def _cases() -> list[ApiRefEvalCase]:
    return [
        # Exact FQN — the canonical symbol-lookup intent.
        ApiRefEvalCase("aspose.slides.Presentation", "aspose.slides.Presentation", "exact_fqn"),
        ApiRefEvalCase(
            "aspose.slides.Presentation.Save", "aspose.slides.Presentation.Save", "exact_fqn"
        ),
        ApiRefEvalCase("aspose.slides.SaveFormat", "aspose.slides.SaveFormat", "exact_fqn"),
        ApiRefEvalCase(
            "aspose.slides.Shape.AddTextFrame", "aspose.slides.Shape.AddTextFrame", "exact_fqn"
        ),
        ApiRefEvalCase("aspose.slides.ISlide", "aspose.slides.ISlide", "exact_fqn"),
        ApiRefEvalCase(
            "aspose.slides.IChart.ChartData", "aspose.slides.IChart.ChartData", "exact_fqn"
        ),
        ApiRefEvalCase("aspose.slides.PptxOptions", "aspose.slides.PptxOptions", "exact_fqn"),
        ApiRefEvalCase("aspose.slides.SlideSize", "aspose.slides.SlideSize", "exact_fqn"),
        # Partial / leaf name — developer typed only the class or member name.
        ApiRefEvalCase("Presentation", "aspose.slides.Presentation", "partial_name"),
        ApiRefEvalCase("SaveFormat", "aspose.slides.SaveFormat", "partial_name"),
        ApiRefEvalCase("AddTextFrame", "aspose.slides.Shape.AddTextFrame", "partial_name"),
        ApiRefEvalCase("SlideSize", "aspose.slides.SlideSize", "partial_name"),
        ApiRefEvalCase("PptxOptions", "aspose.slides.PptxOptions", "partial_name"),
        ApiRefEvalCase("ChartData", "aspose.slides.IChart.ChartData", "partial_name"),
        ApiRefEvalCase("AudioFrame", "aspose.slides.IAudioFrame", "partial_name"),
        ApiRefEvalCase("TextFrame", "aspose.slides.ITextFrame", "partial_name"),
        # Conceptual — prose; relies on full-text over name + summary.
        ApiRefEvalCase(
            "save presentation to file", "aspose.slides.Presentation.Save", "conceptual"
        ),
        ApiRefEvalCase("collection of slides", "aspose.slides.Presentation.Slides", "conceptual"),
        ApiRefEvalCase("output file format", "aspose.slides.SaveFormat", "conceptual"),
        ApiRefEvalCase("add text frame to shape", "aspose.slides.Shape.AddTextFrame", "conceptual"),
        ApiRefEvalCase("release resources", "aspose.slides.Presentation.Dispose", "conceptual"),
        ApiRefEvalCase("data backing the chart", "aspose.slides.IChart.ChartData", "conceptual"),
        ApiRefEvalCase("audio clip embedded on a slide", "aspose.slides.IAudioFrame", "conceptual"),
        ApiRefEvalCase(
            "dimensions and orientation of slides", "aspose.slides.SlideSize", "conceptual"
        ),
    ]


def _seed_inmemory() -> InMemoryApiRefSymbolStore:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(_corpus())
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="eval")
    return store


def test_structured_path_recall_is_strong() -> None:
    retriever = ApiRefRetriever(store=_seed_inmemory())
    report = evaluate_apiref_recall(retriever=retriever, scope=SCOPE, cases=_cases())

    # Exact FQN must be a perfect top-1 (it's an authoritative lookup).
    assert report.per_type_recall_at5["exact_fqn"] == 1.0
    # The structured path should resolve the vast majority within top-5.
    assert report.recall_at[5] >= 0.9, report.misses
    assert report.recall_at[1] >= 0.6
    assert report.mrr >= 0.7
    assert report.total == 24


def test_exact_fqn_is_rank_one() -> None:
    retriever = ApiRefRetriever(store=_seed_inmemory())
    exact_only = [c for c in _cases() if c.query_type == "exact_fqn"]
    report = evaluate_apiref_recall(
        retriever=retriever, scope=SCOPE, cases=exact_only, k_values=(1,)
    )
    assert report.recall_at[1] == 1.0
    assert report.mrr == 1.0
    assert report.misses == ()


def test_empty_cases_report() -> None:
    retriever = ApiRefRetriever(store=_seed_inmemory())
    report = evaluate_apiref_recall(retriever=retriever, scope=SCOPE, cases=[])
    assert report.total == 0
    assert report.mrr == 0.0


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_structured_path_recall_against_real_postgres() -> None:
    pg_scope = ApiRefScope(product="recall.pg", language="net", version="rt", locale="en")
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    # Re-scope the corpus + cases onto an isolated product to avoid clashes.
    corpus = [
        ApiRefSymbol(
            snapshot_id="eval-pg",
            product=pg_scope.product,
            language=pg_scope.language,
            version=pg_scope.version,
            locale=pg_scope.locale,
            kind=s.kind,
            member_fqn=s.member_fqn.replace("aspose.slides", "recall.pg"),
            name=s.name,
            parent_fqn=(
                s.parent_fqn.replace("aspose.slides", "recall.pg") if s.parent_fqn else None
            ),
            signature=s.signature,
            canonical_url=s.canonical_url,
            is_deprecated=s.is_deprecated,
            summary=s.summary,
            payload={},
        )
        for s in _corpus()
    ]
    store.upsert_symbols(corpus)
    store.flip_active_snapshot(scope=pg_scope, snapshot_id="eval-pg")
    cases = [
        ApiRefEvalCase(
            c.query.replace("aspose.slides", "recall.pg"),
            c.expected_member_fqn.replace("aspose.slides", "recall.pg"),
            c.query_type,
        )
        for c in _cases()
    ]
    report = evaluate_apiref_recall(
        retriever=ApiRefRetriever(store=store), scope=pg_scope, cases=cases
    )
    assert report.per_type_recall_at5["exact_fqn"] == 1.0
    assert report.recall_at[5] >= 0.9, report.misses
