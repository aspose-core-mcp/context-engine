"""Recall@k / MRR evaluation for the structured API-reference path.

ADR-011 calls for a recall validation of the Postgres
structured symbol path against the dense (apiref_dense_v1) baseline on real
Aspose API-reference queries, to confirm the research prediction that
exact/lexical/structural retrieval ≥ dense for symbol lookup.

This module provides the reusable harness (recall@k + MRR over a labelled
case set) plus a curated, representative query set. The harness is corpus-
agnostic: point it at any :class:`ApiRefRetriever` + scope. Full-scale
validation over a complete corpus runs the same harness against a populated
Postgres symbol store.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from adcs.indexing.apiref_symbol_store import ApiRefScope
from adcs.retrieval.two_source_retriever import ApiRefRetriever, looks_like_fqn


@dataclass(frozen=True, slots=True)
class ApiRefEvalCase:
    """One labelled retrieval case: a query and its expected target symbol."""

    query: str
    expected_member_fqn: str
    query_type: str  # exact_fqn | partial_name | conceptual


@dataclass(frozen=True, slots=True)
class ApiRefRecallReport:
    """Recall@k + MRR over a labelled case set."""

    total: int
    recall_at: dict[int, float]
    mrr: float
    per_type_recall_at5: dict[str, float]
    misses: tuple[str, ...] = field(default_factory=tuple)


def rank_member_fqns(
    *,
    retriever: ApiRefRetriever,
    query: str,
    scope: ApiRefScope,
    limit: int = 10,
) -> list[str]:
    """Return ranked member_fqns for a query (exact lookup first, then search)."""
    ranked: list[str] = []
    seen: set[str] = set()
    if looks_like_fqn(query):
        for symbol in retriever.lookup_exact(
            member_fqn=query.strip().removesuffix("()"), scope=scope
        ):
            if symbol.member_fqn not in seen:
                seen.add(symbol.member_fqn)
                ranked.append(symbol.member_fqn)
    for symbol in retriever.search(query=query, scope=scope, limit=limit):
        if symbol.member_fqn not in seen:
            seen.add(symbol.member_fqn)
            ranked.append(symbol.member_fqn)
    return ranked


def evaluate_apiref_recall(
    *,
    retriever: ApiRefRetriever,
    scope: ApiRefScope,
    cases: Sequence[ApiRefEvalCase],
    k_values: Sequence[int] = (1, 5, 10),
) -> ApiRefRecallReport:
    """Compute recall@k and MRR for the structured apiref path over `cases`."""
    if not cases:
        return ApiRefRecallReport(
            total=0, recall_at={k: 0.0 for k in k_values}, mrr=0.0, per_type_recall_at5={}
        )

    hits_at: dict[int, int] = {k: 0 for k in k_values}
    reciprocal_rank_sum = 0.0
    per_type_total: dict[str, int] = {}
    per_type_hits5: dict[str, int] = {}
    misses: list[str] = []

    for case in cases:
        ranked = rank_member_fqns(
            retriever=retriever,
            query=case.query,
            scope=scope,
            limit=max(k_values),
        )
        rank = _rank_of(ranked, case.expected_member_fqn)
        per_type_total[case.query_type] = per_type_total.get(case.query_type, 0) + 1
        if rank is None:
            misses.append(case.query)
            continue
        reciprocal_rank_sum += 1.0 / rank
        for k in k_values:
            if rank <= k:
                hits_at[k] += 1
        if rank <= 5:
            per_type_hits5[case.query_type] = per_type_hits5.get(case.query_type, 0) + 1

    total = len(cases)
    return ApiRefRecallReport(
        total=total,
        recall_at={k: hits_at[k] / total for k in k_values},
        mrr=reciprocal_rank_sum / total,
        per_type_recall_at5={
            qtype: per_type_hits5.get(qtype, 0) / count for qtype, count in per_type_total.items()
        },
        misses=tuple(misses),
    )


def _rank_of(ranked: list[str], expected: str) -> int | None:
    """1-based rank of `expected` in `ranked`, or None if absent."""
    for index, member_fqn in enumerate(ranked, start=1):
        if member_fqn == expected:
            return index
    return None


__all__ = [
    "ApiRefEvalCase",
    "ApiRefRecallReport",
    "evaluate_apiref_recall",
    "rank_member_fqns",
]
