from __future__ import annotations

from pathlib import Path

from adcs.retrieval import (
    ContextPacker,
    HybridCandidate,
    HybridRetrievalResult,
    QueryPlanner,
    QueryPlannerInput,
    ReleaseCatalog,
    RetrievalCandidateMetadata,
    RetrievalExecutableSnippet,
)


def test_context_packer_emits_top_k_citations_and_confidence() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="How to install Aspose OCR?",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    retrieval_result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint,
        normalized_query=plan.normalized_query,
        candidates=(
            _hybrid_candidate(
                candidate_id="A",
                title="Install Guide",
                text="Install package using NuGet and initialize OCR engine.",
                rerank_score=0.95,
                dense_score=1.0,
                lexical_score=1.0,
            ),
            _hybrid_candidate(
                candidate_id="B",
                title="Quickstart",
                text="Quickstart example with image recognition flow.",
                rerank_score=0.42,
                dense_score=0.7,
                lexical_score=0.2,
            ),
        ),
        dense_candidates_count=2,
        lexical_candidates_count=2,
        fused_candidates_count=2,
        dense_weight=0.55,
        lexical_weight=0.45,
    )
    packer = ContextPacker(default_top_k=8, excerpt_limit_chars=80)

    packed = packer.pack(plan=plan, retrieval_result=retrieval_result, top_k=1)

    assert packed.confidence_level == "high"
    assert packed.warnings == ()
    assert packed.fallback_reason is None
    assert packed.clarification_questions == ()
    assert packed.quality.intent == "how_to"
    assert packed.quality.intent_subtype == "installation"
    assert packed.quality.completeness_status == "partial"
    assert "example_or_usage" in packed.quality.completeness_missing_signals
    assert packed.quality.freshness_source == "version_heuristic"
    assert packed.quality.overall_score > 0.6
    assert len(packed.items) == 1
    first_item = packed.items[0]
    assert first_item.candidate_id == "A"
    assert first_item.citation.title == "Install Guide"
    assert first_item.citation.canonical_url.endswith("/a")
    assert first_item.citation.section_anchor == "#section-a"
    assert first_item.citation.score == 0.95


def test_context_packer_returns_low_confidence_fallback_metadata() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="unknown request",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    retrieval_result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint,
        normalized_query=plan.normalized_query,
        candidates=(
            _hybrid_candidate(
                candidate_id="L",
                title="Generic Page",
                text="General docs page.",
                rerank_score=0.10,
                dense_score=0.0,
                lexical_score=0.0,
            ),
        ),
        dense_candidates_count=1,
        lexical_candidates_count=1,
        fused_candidates_count=1,
        dense_weight=0.55,
        lexical_weight=0.45,
    )
    packer = ContextPacker()

    packed = packer.pack(plan=plan, retrieval_result=retrieval_result)

    assert packed.confidence_level == "low"
    assert packed.warnings == ("LOW_CONFIDENCE",)
    assert packed.fallback_reason == "low_confidence_best_effort"
    assert len(packed.clarification_questions) == 3
    assert packed.quality.intent == "general_reference"
    assert packed.quality.intent_subtype is None
    assert packed.quality.overall_score < 0.3


def test_context_packer_exposes_snippet_metadata_in_packed_context() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="Aspose.OCR.AsposeOcr.RecognizeImage",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    retrieval_result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint,
        normalized_query=plan.normalized_query,
        candidates=(
            _hybrid_candidate(
                candidate_id="S",
                title="RecognizeImage Example",
                text='var result = ocr.RecognizeImage("sample.png");',
                rerank_score=0.91,
                dense_score=1.0,
                lexical_score=0.8,
                source_kind="apiref",
                doc_type="api_signature",
                symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                executable_snippets=(
                    RetrievalExecutableSnippet(
                        snippet_id="snippet-1",
                        language="csharp",
                        code='var result = ocr.RecognizeImage("sample.png");',
                        parent_canonical_url=(
                            "https://docs.aspose.com/ocr/net/asposeocr/recognizeimage/"
                        ),
                        parent_section_anchor="#recognizeimage",
                        parent_symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
                    ),
                ),
            ),
        ),
        dense_candidates_count=1,
        lexical_candidates_count=1,
        fused_candidates_count=1,
        dense_weight=0.55,
        lexical_weight=0.45,
    )
    packer = ContextPacker(default_top_k=4, excerpt_limit_chars=400)

    packed = packer.pack(plan=plan, retrieval_result=retrieval_result)

    assert len(packed.items) == 1
    assert len(packed.items[0].snippets) == 1
    snippet = packed.items[0].snippets[0]
    assert snippet.language == "csharp"
    assert snippet.parent_section_anchor == "#recognizeimage"
    assert snippet.parent_symbol_fqn == "Aspose.OCR.AsposeOcr.RecognizeImage"
    assert packed.quality.symbol_match_score == 1.0
    assert packed.quality.completeness_status == "complete"
    assert packed.quality.intent_subtype == "symbol_reference"


def test_context_packer_uses_release_catalog_for_freshness_source() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="latest stable migration notes for Aspose OCR",
            product_id="aspose.ocr",
            programming_language="net",
            strict_version=False,
        )
    )
    retrieval_result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint,
        normalized_query=plan.normalized_query,
        candidates=(
            _hybrid_candidate(
                candidate_id="L",
                title="Latest stable migration notes",
                text="Latest stable migration guidance.",
                rerank_score=0.95,
                dense_score=1.0,
                lexical_score=1.0,
                doc_type="release_note",
                version="latest-stable",
            ),
        ),
        dense_candidates_count=1,
        lexical_candidates_count=1,
        fused_candidates_count=1,
        dense_weight=0.55,
        lexical_weight=0.45,
    )
    packer = ContextPacker(
        release_catalog=ReleaseCatalog.from_config_file(
            config_path=Path("config/release_catalog.json")
        )
    )

    packed = packer.pack(plan=plan, retrieval_result=retrieval_result)

    assert packed.quality.freshness_source == "release_catalog"


def _hybrid_candidate(
    *,
    candidate_id: str,
    title: str,
    text: str,
    rerank_score: float,
    dense_score: float,
    lexical_score: float,
    source_kind: str = "docs",
    doc_type: str = "guide_step",
    symbol_fqn: str | None = None,
    version: str = "25.1",
    executable_snippets: tuple[RetrievalExecutableSnippet, ...] = (),
) -> HybridCandidate:
    metadata = RetrievalCandidateMetadata(
        candidate_id=candidate_id,
        chunk_id=f"chunk-{candidate_id}",
        snapshot_id="snap-00000001",
        product_id="aspose.ocr",
        programming_language="net",
        version=version,
        source_kind=source_kind,
        doc_type=doc_type,
        doc_locale="en",
        symbol_fqn=symbol_fqn,
        title=title,
        canonical_url=f"https://docs.aspose.com/ocr/net/{candidate_id.lower()}",
        section_anchor=f"#section-{candidate_id.lower()}",
        source_revision="revision-abc123",
        repo_id="aspose.ocr.docs",
        text=text,
        checksum=f"checksum-{candidate_id}",
        executable_snippets=executable_snippets,
    )
    return HybridCandidate(
        metadata=metadata,
        dense_raw_score=dense_score,
        lexical_raw_score=lexical_score,
        dense_normalized_score=dense_score,
        lexical_normalized_score=lexical_score,
        blended_score=(dense_score + lexical_score) / 2.0,
        rerank_score=rerank_score,
    )


def test_token_budget_drops_lowest_ranked_items_and_says_so() -> None:
    """Total context tokens are capped, not only the per-excerpt size.

    With no total budget the packer has no idea how much it returns: the default
    top_k of 8 already produces roughly 6k tokens against a documented default of
    3500, and top_k=20 blows past the 12000 maximum.
    """
    from adcs.retrieval.context_packer import (
        ContextCitation,
        PackedContextItem,
        _apply_token_budget,
    )

    def _item(index: int, chars: int) -> PackedContextItem:
        return PackedContextItem(
            candidate_id=f"c{index}",
            excerpt="x" * chars,
            citation=ContextCitation(
                title="t",
                canonical_url="https://example.invalid/doc",
                section_anchor="#a",
                source_revision="rev",
                score=1.0,
            ),
        )

    # Eight items of ~1000 tokens each against a 3500-token budget.
    kept, truncated = _apply_token_budget(
        items=tuple(_item(i, 4000) for i in range(8)), max_total_tokens=3500
    )
    assert len(kept) == 3
    assert truncated is True, "dropping ranked results must be reported, not silent"
    assert [item.candidate_id for item in kept] == ["c0", "c1", "c2"], "keep the top-ranked"

    # Everything fits: nothing dropped, no warning.
    kept_all, truncated_all = _apply_token_budget(
        items=tuple(_item(i, 100) for i in range(3)), max_total_tokens=3500
    )
    assert len(kept_all) == 3
    assert truncated_all is False

    # One oversized chunk must be trimmed, never turned into an empty answer.
    kept_big, truncated_big = _apply_token_budget(
        items=(_item(0, 40_000), _item(1, 100)), max_total_tokens=3500
    )
    assert len(kept_big) == 1
    assert truncated_big is True
    assert len(kept_big[0].excerpt) <= 3500 * 4 + 3

    assert _apply_token_budget(items=(), max_total_tokens=3500) == ((), False)


def test_context_packer_reserves_budget_for_the_best_api_reference_candidate() -> None:
    """A documentation-heavy rank list must still return API context when present."""
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="How do I convert a Word document to PDF?",
            product_id="aspose.words",
            programming_language="net",
        )
    )
    documentation_text = "d" * 500  # 125 estimated tokens per excerpt.
    api_text = "public void Save(string fileName)\nSave a Word document to PDF. " + "a" * 430
    candidates = tuple(
        _hybrid_candidate(
            candidate_id=f"docs-{index}",
            title=f"Documentation {index}",
            text=documentation_text,
            rerank_score=1.0 - (index / 10),
            dense_score=0.8,
            lexical_score=0.8,
        )
        for index in range(1, 5)
    ) + (
        _hybrid_candidate(
            candidate_id="api-convert",
            title="Aspose.Words.Document.Save",
            text=api_text,
            rerank_score=0.5,
            dense_score=0.7,
            lexical_score=0.7,
            source_kind="apiref",
            doc_type="api_signature",
            symbol_fqn="Aspose.Words.Document.Save",
        ),
    )
    retrieval_result = HybridRetrievalResult(
        query_fingerprint=plan.query_fingerprint,
        normalized_query=plan.normalized_query,
        candidates=candidates,
        dense_candidates_count=len(candidates),
        lexical_candidates_count=len(candidates),
        fused_candidates_count=len(candidates),
        dense_weight=0.55,
        lexical_weight=0.45,
    )

    packed = ContextPacker(max_total_tokens=256).pack(
        plan=plan,
        retrieval_result=retrieval_result,
        top_k=5,
    )

    # Two 125-token excerpts fit in a 256-token budget, while a third does not. The second
    # packed item must therefore be the best API result, rather than docs-2.
    assert [item.candidate_id for item in packed.items] == ["docs-1", "api-convert"]
    assert packed.warnings == ("CONTEXT_TOKEN_BUDGET_TRUNCATED",)


def test_packer_clamps_a_budget_above_the_documented_maximum() -> None:
    """An operator setting is clamped, not rejected — the documented max is 12000."""
    from adcs.retrieval.context_packer import ContextPacker

    packer = ContextPacker(max_total_tokens=999_999)
    assert packer._max_total_tokens == 12000

    try:
        ContextPacker(max_total_tokens=10)
    except ValueError as exc:
        assert "max_total_tokens" in str(exc)
    else:  # pragma: no cover - guard must reject a nonsensical budget
        raise AssertionError("a budget below the floor must be rejected")
