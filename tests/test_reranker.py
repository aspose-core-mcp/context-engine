from __future__ import annotations

from pathlib import Path

from adcs.retrieval import (
    AdvancedHeuristicReranker,
    DeterministicReranker,
    HybridCandidate,
    QueryPlanner,
    QueryPlannerInput,
    ReleaseCatalog,
    RetrievalCandidateMetadata,
    build_candidate_reranker,
)


def test_deterministic_reranker_prioritizes_exact_symbol_match() -> None:
    planner = QueryPlanner()
    plan = planner.plan(request=QueryPlannerInput(query="Aspose.OCR.Engine.Recognize usage"))
    reranker = DeterministicReranker()

    exact_symbol = _hybrid_candidate(
        candidate_id="A",
        symbol_fqn="aspose.ocr.engine.recognize",
        blended_score=0.5,
        title="API Member",
        text="Method details.",
    )
    generic = _hybrid_candidate(
        candidate_id="B",
        symbol_fqn=None,
        blended_score=0.5,
        title="General Guide",
        text="Setup instructions.",
    )

    ranked = reranker.rerank(plan=plan, candidates=(generic, exact_symbol), limit=2)

    assert tuple(candidate.metadata.candidate_id for candidate in ranked) == ("A", "B")
    assert ranked[0].rerank_score > ranked[1].rerank_score


def test_deterministic_reranker_uses_candidate_id_as_stable_tiebreaker() -> None:
    planner = QueryPlanner()
    plan = planner.plan(request=QueryPlannerInput(query=""))
    reranker = DeterministicReranker()

    candidate_b = _hybrid_candidate(
        candidate_id="b",
        symbol_fqn=None,
        blended_score=0.2,
        title="Doc B",
        text="body",
    )
    candidate_a = _hybrid_candidate(
        candidate_id="a",
        symbol_fqn=None,
        blended_score=0.2,
        title="Doc A",
        text="body",
    )

    ranked = reranker.rerank(plan=plan, candidates=(candidate_b, candidate_a), limit=2)

    assert tuple(candidate.metadata.candidate_id for candidate in ranked) == ("a", "b")


def test_deterministic_reranker_prefers_latest_release_notes_when_requested() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="latest stable migration notes for Aspose OCR",
            product_id="aspose.ocr",
            programming_language="net",
            strict_version=False,
        )
    )
    reranker = DeterministicReranker()

    older_release = _hybrid_candidate(
        candidate_id="old-release",
        symbol_fqn=None,
        blended_score=0.62,
        title="Aspose OCR 24.9 release notes",
        text="Breaking changes and migration guidance.",
        version="24.9",
        doc_type="release_note",
    )
    latest_release = _hybrid_candidate(
        candidate_id="new-release",
        symbol_fqn=None,
        blended_score=0.58,
        title="Aspose OCR 25.1 release notes",
        text="Latest stable migration guidance and release highlights.",
        version="25.1",
        doc_type="release_note",
    )

    ranked = reranker.rerank(plan=plan, candidates=(older_release, latest_release), limit=2)

    assert tuple(candidate.metadata.candidate_id for candidate in ranked) == (
        "new-release",
        "old-release",
    )


def test_advanced_reranker_uses_release_catalog_for_latest_stable_bias() -> None:
    planner = QueryPlanner()
    plan = planner.plan(
        request=QueryPlannerInput(
            query="latest stable migration notes for Aspose OCR",
            product_id="aspose.ocr",
            programming_language="net",
            strict_version=False,
        )
    )
    release_catalog = ReleaseCatalog.from_config_file(
        config_path=Path("config/release_catalog.json")
    )
    reranker = AdvancedHeuristicReranker(release_catalog=release_catalog)

    latest_stable = _hybrid_candidate(
        candidate_id="latest-stable",
        symbol_fqn=None,
        blended_score=0.54,
        title="Aspose OCR latest stable migration notes",
        text="Latest stable migration guidance and release highlights.",
        version="latest-stable",
        doc_type="release_note",
    )
    older_release = _hybrid_candidate(
        candidate_id="old-release",
        symbol_fqn=None,
        blended_score=0.58,
        title="Aspose OCR 24.12 migration notes",
        text="Migration guidance for 24.12.",
        version="24.12",
        doc_type="release_note",
    )

    ranked = reranker.rerank(plan=plan, candidates=(older_release, latest_stable), limit=2)

    assert tuple(candidate.metadata.candidate_id for candidate in ranked) == (
        "latest-stable",
        "old-release",
    )


def test_build_candidate_reranker_refuses_the_unimplemented_openai_backend() -> None:
    """Selecting an unimplemented backend must fail, not silently downgrade.

    The old behaviour logged a warning and returned the *weakest* reranker, so an
    operator who deliberately chose the strongest option got the poorest ranking
    with only a log line to say so — a misconfiguration you would infer from
    ranking quality months later, if at all.
    """
    try:
        build_candidate_reranker(backend="openai_compatible")
    except ValueError as exc:
        message = str(exc)
        assert "not implemented" in message
        # The error has to name the way out, not just the problem.
        assert "advanced_heuristic" in message
    else:  # pragma: no cover - the point of the test
        raise AssertionError("an unimplemented backend must be refused at construction")


def test_build_candidate_reranker_accepts_the_supported_backends() -> None:
    assert build_candidate_reranker(backend="advanced_heuristic").backend_name == (
        "advanced_heuristic"
    )
    assert build_candidate_reranker(backend="deterministic").backend_name == "deterministic"


def _hybrid_candidate(
    *,
    candidate_id: str,
    symbol_fqn: str | None,
    blended_score: float,
    title: str,
    text: str,
    version: str = "25.1",
    doc_type: str = "api_member",
) -> HybridCandidate:
    metadata = RetrievalCandidateMetadata(
        candidate_id=candidate_id,
        chunk_id=f"chunk-{candidate_id}",
        snapshot_id="snap-00000001",
        product_id="aspose.ocr",
        programming_language="net",
        version=version,
        source_kind="apiref",
        doc_type=doc_type,
        doc_locale="en",
        symbol_fqn=symbol_fqn,
        title=title,
        canonical_url="https://reference.aspose.com/ocr/net/",
        section_anchor=f"#{candidate_id}",
        source_revision="revision-abc123",
        repo_id="aspose.ocr.apiref",
        text=text,
        checksum=f"checksum-{candidate_id}",
    )
    return HybridCandidate(
        metadata=metadata,
        dense_raw_score=blended_score,
        lexical_raw_score=blended_score,
        dense_normalized_score=blended_score,
        lexical_normalized_score=blended_score,
        blended_score=blended_score,
        rerank_score=blended_score,
    )
