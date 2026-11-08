"""In-memory dense/lexical lane adapters over Stage-D chunk records."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import cast

from adcs.ingestion.chunking import StageDChunkRecord
from adcs.retrieval.filter_resolver import FilterResolver
from adcs.retrieval.models import QueryPlan, ScopedIndexRecord
from adcs.retrieval.retrieval_models import (
    LaneCandidate,
    RetrievalCandidateMetadata,
    RetrievalExecutableSnippet,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class InMemoryDenseLaneAdapter:
    """Dense-like lane adapter with deterministic semantic-overlap scoring."""

    def __init__(
        self,
        *,
        chunk_records: Sequence[StageDChunkRecord],
        snapshot_id: str,
        filter_resolver: FilterResolver | None = None,
    ) -> None:
        self._chunk_records = tuple(chunk_records)
        self._snapshot_id = snapshot_id
        self._filter_resolver = filter_resolver or FilterResolver()

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        if limit < 1:
            return ()
        return _search_records(
            plan=plan,
            limit=limit,
            chunk_records=self._chunk_records,
            snapshot_id=self._snapshot_id,
            filter_resolver=self._filter_resolver,
            score_fn=_dense_score,
        )


class InMemoryLexicalLaneAdapter:
    """Lexical lane adapter with deterministic token-frequency ranking."""

    def __init__(
        self,
        *,
        chunk_records: Sequence[StageDChunkRecord],
        snapshot_id: str,
        filter_resolver: FilterResolver | None = None,
    ) -> None:
        self._chunk_records = tuple(chunk_records)
        self._snapshot_id = snapshot_id
        self._filter_resolver = filter_resolver or FilterResolver()

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        if limit < 1:
            return ()
        return _search_records(
            plan=plan,
            limit=limit,
            chunk_records=self._chunk_records,
            snapshot_id=self._snapshot_id,
            filter_resolver=self._filter_resolver,
            score_fn=_lexical_score,
        )


def _search_records(
    *,
    plan: QueryPlan,
    limit: int,
    chunk_records: tuple[StageDChunkRecord, ...],
    snapshot_id: str,
    filter_resolver: FilterResolver,
    score_fn: Callable[..., float],
) -> tuple[LaneCandidate, ...]:
    scored_candidates: list[tuple[int, float, StageDChunkRecord]] = []
    seen_chunk_ids: set[str] = set()
    for route_index, route in enumerate(plan.filters.routes):
        filtered = tuple(
            record
            for record in chunk_records
            if filter_resolver.record_matches_route(
                record=cast(ScopedIndexRecord, record),
                route=route,
                strict_version=plan.filters.strict_version,
            )
        )
        for chunk_record in filtered:
            if chunk_record.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_record.chunk_id)
            score = score_fn(plan=plan, chunk_record=chunk_record)
            scored_candidates.append((route_index, score, chunk_record))

    ordered = sorted(
        scored_candidates,
        key=lambda item: (item[0], -item[1], item[2].chunk_id),
    )[:limit]
    return tuple(
        LaneCandidate(
            metadata=_to_retrieval_candidate_metadata(
                chunk_record=chunk_record,
                snapshot_id=snapshot_id,
            ),
            raw_score=raw_score,
        )
        for _, raw_score, chunk_record in ordered
    )


def _dense_score(*, plan: QueryPlan, chunk_record: StageDChunkRecord) -> float:
    query_terms = _tokenize(plan.normalized_query)
    if not query_terms:
        return 0.0

    text_terms = _tokenize(chunk_record.text)
    title_terms = _tokenize(chunk_record.title)
    text_overlap = len(query_terms.intersection(text_terms)) / len(query_terms)
    title_overlap = len(query_terms.intersection(title_terms)) / len(query_terms)
    symbol_bonus = _symbol_bonus(plan=plan, chunk_record=chunk_record)
    return (text_overlap * 0.70) + (title_overlap * 0.20) + symbol_bonus


def _lexical_score(*, plan: QueryPlan, chunk_record: StageDChunkRecord) -> float:
    query_terms = _tokenize(plan.normalized_query)
    if not query_terms:
        return 0.0

    title_value = chunk_record.title.casefold()
    text_value = chunk_record.text.casefold()
    overlap_score = 0.0
    for term in query_terms:
        overlap_score += text_value.count(term) * 1.0
        overlap_score += title_value.count(term) * 1.5

    phrase_bonus = 0.0
    if plan.normalized_query.casefold() in text_value:
        phrase_bonus += 1.0
    if plan.normalized_query.casefold() in title_value:
        phrase_bonus += 1.5
    return (overlap_score / len(query_terms)) + phrase_bonus + _symbol_bonus(
        plan=plan,
        chunk_record=chunk_record,
    )


def _symbol_bonus(*, plan: QueryPlan, chunk_record: StageDChunkRecord) -> float:
    if not plan.symbol_candidates:
        return 0.0
    if not chunk_record.symbol_fqn:
        return 0.0
    symbol_fqn = chunk_record.symbol_fqn.casefold()
    for symbol_candidate in plan.symbol_candidates:
        normalized = symbol_candidate.casefold()
        if symbol_fqn == normalized:
            return 0.25
        if symbol_fqn.endswith(normalized):
            return 0.15
    return 0.0


def _tokenize(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value)}


def _to_retrieval_candidate_metadata(
    *,
    chunk_record: StageDChunkRecord,
    snapshot_id: str,
) -> RetrievalCandidateMetadata:
    return RetrievalCandidateMetadata(
        candidate_id=chunk_record.chunk_id,
        chunk_id=chunk_record.chunk_id,
        snapshot_id=snapshot_id,
        product_id=chunk_record.product_id,
        programming_language=chunk_record.programming_language,
        version=chunk_record.version,
        source_kind=chunk_record.source_kind,
        doc_type=chunk_record.doc_type,
        doc_locale=chunk_record.doc_locale,
        symbol_fqn=chunk_record.symbol_fqn,
        title=chunk_record.title,
        canonical_url=chunk_record.canonical_url,
        section_anchor=chunk_record.section_anchor,
        source_revision=chunk_record.source_revision,
        repo_id=chunk_record.repo_id,
        text=chunk_record.text,
        checksum=chunk_record.checksum,
        executable_snippets=tuple(
            RetrievalExecutableSnippet(
                snippet_id=snippet.snippet_id,
                language=snippet.language,
                code=snippet.code,
                parent_canonical_url=snippet.parent_canonical_url,
                parent_section_anchor=snippet.parent_section_anchor,
                parent_symbol_fqn=snippet.parent_symbol_fqn,
            )
            for snippet in chunk_record.executable_snippets
        ),
    )
