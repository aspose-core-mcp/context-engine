"""Deterministic reranking contracts and implementations."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from adcs.retrieval.filter_resolver import normalize_version_hint
from adcs.retrieval.models import QueryPlan
from adcs.retrieval.release_catalog import ReleaseCatalog
from adcs.retrieval.retrieval_models import HybridCandidate

logger = logging.getLogger("adcs.reranker")

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class RerankerBackend(StrEnum):
    """Configured reranker backend selection."""

    DETERMINISTIC = "deterministic"
    ADVANCED_HEURISTIC = "advanced_heuristic"
    OPENAI_COMPATIBLE = "openai_compatible"


class CandidateReranker(Protocol):
    """Contract for reranking fused retrieval candidates."""

    backend_name: str

    def rerank(
        self,
        *,
        plan: QueryPlan,
        candidates: Sequence[HybridCandidate],
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        """Return reranked candidates sorted by descending final score."""


class DeterministicReranker:
    """Stable, no-network reranker suitable for tests and local development."""

    backend_name = RerankerBackend.DETERMINISTIC.value

    def rerank(
        self,
        *,
        plan: QueryPlan,
        candidates: Sequence[HybridCandidate],
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        if limit < 1 or not candidates:
            return ()

        scored_candidates = _score_candidates(
            plan=plan,
            candidates=candidates,
            limit=limit,
            release_catalog=None,
            advanced=False,
        )
        return scored_candidates[:limit]


class AdvancedHeuristicReranker:
    """Second-stage deterministic reranker with release and intent-aware features."""

    backend_name = RerankerBackend.ADVANCED_HEURISTIC.value

    def __init__(self, *, release_catalog: ReleaseCatalog | None = None) -> None:
        self._release_catalog = release_catalog

    def rerank(
        self,
        *,
        plan: QueryPlan,
        candidates: Sequence[HybridCandidate],
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        if limit < 1 or not candidates:
            return ()
        scored_candidates = _score_candidates(
            plan=plan,
            candidates=candidates,
            limit=limit,
            release_catalog=self._release_catalog,
            advanced=True,
        )
        return scored_candidates[:limit]


def build_candidate_reranker(
    *,
    backend: str,
    release_catalog: ReleaseCatalog | None = None,
) -> CandidateReranker:
    """Build configured reranker with safe fallback for unavailable advanced backends."""
    normalized_backend = backend.strip().casefold()
    if normalized_backend == RerankerBackend.ADVANCED_HEURISTIC.value:
        return AdvancedHeuristicReranker(release_catalog=release_catalog)
    if normalized_backend == RerankerBackend.OPENAI_COMPATIBLE.value:
        # Refuse rather than downgrade. This backend is not implemented; silently
        # falling back to the *weakest* reranker would give an operator who
        # deliberately selected the strongest option the poorest ranking, with
        # only a log line to say so.
        #
        # Failing at construction is safe: the default is advanced_heuristic, so
        # only an explicit ADCS_RERANKER_BACKEND setting reaches this line. Anyone
        # who does asked for something that does not exist, and should hear it at
        # startup rather than infer it from ranking quality months later.
        msg = (
            "Reranker backend 'openai_compatible' is not implemented. "
            "Set ADCS_RERANKER_BACKEND to 'advanced_heuristic' (default) or "
            "'deterministic'."
        )
        raise ValueError(msg)
    return DeterministicReranker()


def _score_candidates(
    *,
    plan: QueryPlan,
    candidates: Sequence[HybridCandidate],
    limit: int,
    release_catalog: ReleaseCatalog | None,
    advanced: bool,
) -> tuple[HybridCandidate, ...]:
    query_terms = _tokenize(plan.normalized_query)
    max_release_rank = _max_release_rank(candidates)
    latest_release_entry = _resolve_latest_release_entry(
        plan=plan,
        candidates=candidates,
        release_catalog=release_catalog,
    )
    scored_candidates = tuple(
        replace(
            candidate,
            rerank_score=_compute_rerank_score(
                plan=plan,
                candidate=candidate,
                query_terms=query_terms,
                max_release_rank=max_release_rank,
                release_catalog=release_catalog,
                latest_release_entry=latest_release_entry,
                advanced=advanced,
            ),
        )
        for candidate in candidates
    )
    ordered_candidates = tuple(
        sorted(
            scored_candidates,
            key=lambda candidate: (
                -candidate.rerank_score,
                -candidate.blended_score,
                candidate.metadata.candidate_id,
            ),
        )
    )
    return ordered_candidates[:limit]


def _compute_rerank_score(
    *,
    plan: QueryPlan,
    candidate: HybridCandidate,
    query_terms: set[str],
    max_release_rank: tuple[int, int, int, int] | None,
    release_catalog: ReleaseCatalog | None,
    latest_release_entry: object,
    advanced: bool,
) -> float:
    overlap_score = _query_overlap_score(query_terms=query_terms, candidate=candidate)
    symbol_score = _symbol_match_score(plan=plan, candidate=candidate)
    intent_score = _intent_alignment_score(plan=plan, candidate=candidate)
    freshness_score = _freshness_alignment_score(
        plan=plan,
        candidate=candidate,
        max_release_rank=max_release_rank,
    )
    lane_agreement_bonus = 0.08 if _has_lane_agreement(candidate) else 0.0
    score = (
        candidate.blended_score
        + overlap_score
        + symbol_score
        + intent_score
        + freshness_score
        + lane_agreement_bonus
    )
    if not advanced:
        return score
    return score + _advanced_bonus(
        plan=plan,
        candidate=candidate,
        release_catalog=release_catalog,
        latest_release_entry=latest_release_entry,
    )


def _query_overlap_score(*, query_terms: set[str], candidate: HybridCandidate) -> float:
    if not query_terms:
        return 0.0

    text_terms = _tokenize(candidate.metadata.text)
    title_terms = _tokenize(candidate.metadata.title)
    overlap_count = len(query_terms.intersection(text_terms.union(title_terms)))
    return 0.12 * (overlap_count / len(query_terms))


def _symbol_match_score(*, plan: QueryPlan, candidate: HybridCandidate) -> float:
    if not plan.symbol_candidates:
        return 0.0

    symbol_fqn = (candidate.metadata.symbol_fqn or "").casefold()
    text_value = candidate.metadata.text.casefold()
    best_score = 0.0
    for symbol_candidate in plan.symbol_candidates:
        normalized_symbol = symbol_candidate.casefold()
        if symbol_fqn and symbol_fqn == normalized_symbol:
            best_score = max(best_score, 0.25)
            continue
        if symbol_fqn and symbol_fqn.endswith(normalized_symbol):
            best_score = max(best_score, 0.16)
        elif normalized_symbol in text_value:
            best_score = max(best_score, 0.10)
    return best_score


def _has_lane_agreement(candidate: HybridCandidate) -> bool:
    return candidate.dense_normalized_score > 0 and candidate.lexical_normalized_score > 0


def _intent_alignment_score(*, plan: QueryPlan, candidate: HybridCandidate) -> float:
    normalized_doc_type = candidate.metadata.doc_type.casefold()
    if plan.intent == "release_notes":
        if _is_release_candidate(candidate):
            return 0.12
        if normalized_doc_type in {"api_member", "api_reference"}:
            return 0.03
        return -0.02
    if plan.intent == "symbol_lookup":
        # Symbol lookup: API signature/member docs are critical
        if normalized_doc_type in {"api_signature", "api_member"}:
            return 0.14
        if normalized_doc_type.startswith("api_"):
            return 0.06
        if normalized_doc_type == "index_overview":
            return -0.02  # penalize overview for symbol lookups
        return 0.0
    if plan.intent == "troubleshooting":
        if normalized_doc_type in {"guide", "task", "troubleshooting", "guide_step"}:
            return 0.08
        if normalized_doc_type.startswith("api_"):
            return 0.04
    if plan.intent == "how_to":
        if normalized_doc_type in {"api_signature", "api_member"}:
            return 0.10  # exact API docs are most useful for implementation
        if normalized_doc_type in {"guide", "task", "guide_step"}:
            return 0.08
        if normalized_doc_type == "index_overview":
            return 0.02  # overview pages are least useful for actual coding
        if normalized_doc_type.startswith("api_"):
            return 0.06
    if normalized_doc_type == "index_overview":
        return 0.02
    return 0.0


def _freshness_alignment_score(
    *,
    plan: QueryPlan,
    candidate: HybridCandidate,
    max_release_rank: tuple[int, int, int, int] | None,
) -> float:
    normalized_candidate_version = (
        normalize_version_hint(candidate.metadata.version)
        or candidate.metadata.version.casefold()
    )
    preferred_version = normalize_version_hint(plan.filters.preferred_version)
    if preferred_version is not None:
        if normalized_candidate_version == preferred_version:
            return 0.12
        if plan.filters.strict_version:
            return -0.06
        if normalized_candidate_version.startswith(f"{preferred_version}."):
            return 0.04
        return -0.03

    if plan.prefers_latest_stable:
        release_rank = _release_version_rank(candidate.metadata.version)
        if release_rank is None or max_release_rank is None:
            return 0.02 if _is_release_candidate(candidate) else 0.0
        return _relative_release_rank_boost(
            release_rank=release_rank,
            max_release_rank=max_release_rank,
            max_boost=0.12,
        )

    if plan.intent == "release_notes":
        release_rank = _release_version_rank(candidate.metadata.version)
        if release_rank is None or max_release_rank is None:
            return 0.01
        return _relative_release_rank_boost(
            release_rank=release_rank,
            max_release_rank=max_release_rank,
            max_boost=0.08,
        )
    return 0.0


def _advanced_bonus(
    *,
    plan: QueryPlan,
    candidate: HybridCandidate,
    release_catalog: ReleaseCatalog | None,
    latest_release_entry: object,
) -> float:
    query_value = plan.normalized_query.casefold()
    title_value = candidate.metadata.title.casefold()
    text_value = candidate.metadata.text.casefold()
    subtype_bonus = _intent_subtype_bonus(
        plan=plan,
        title_value=title_value,
        text_value=text_value,
        candidate=candidate,
    )
    phrase_bonus = 0.0
    if query_value and query_value in title_value:
        phrase_bonus += 0.10
    elif query_value and query_value in text_value:
        phrase_bonus += 0.06

    api_signature_bonus = 0.0
    if plan.intent == "symbol_lookup" and candidate.metadata.doc_type.casefold() == "api_signature":
        api_signature_bonus = 0.07

    release_bonus = _release_metadata_bonus(
        plan=plan,
        candidate=candidate,
        release_catalog=release_catalog,
        latest_release_entry=latest_release_entry,
    )
    return subtype_bonus + phrase_bonus + api_signature_bonus + release_bonus


def _intent_subtype_bonus(
    *,
    plan: QueryPlan,
    title_value: str,
    text_value: str,
    candidate: HybridCandidate,
) -> float:
    subtype = plan.intent_subtype
    if subtype is None:
        return 0.0
    corpus = f"{title_value}\n{text_value}"
    if subtype == "installation":
        return (
            0.10
            if any(token in corpus for token in ("install", "nuget", "package"))
            else 0.0
        )
    if subtype == "configuration":
        return (
            0.09
            if any(
                token in corpus for token in ("setting", "option", "config", "configure")
            )
            else 0.0
        )
    if subtype == "implementation":
        return (
            0.07
            if any(
                token in corpus
                for token in ("example", "sample", "recognize", "extract", "usage")
            )
            else 0.0
        )
    if subtype == "runtime_failure":
        return (
            0.10
            if any(
                token in corpus
                for token in ("error", "exception", "fix", "workaround", "retry")
            )
            else 0.0
        )
    if subtype == "quality_issue":
        return (
            0.10
            if any(
                token in corpus
                for token in ("accuracy", "contrast", "deskew", "denoise", "threshold")
            )
            else 0.0
        )
    if subtype == "performance_issue":
        return (
            0.08
            if any(
                token in corpus for token in ("performance", "speed", "latency", "optimiz")
            )
            else 0.0
        )
    if subtype == "migration":
        return 0.12 if _is_release_candidate(candidate) else 0.0
    if subtype == "breaking_change":
        return (
            0.12
            if any(
                token in corpus
                for token in ("breaking", "deprecated", "replacement", "migrate")
            )
            else 0.0
        )
    if subtype == "latest_release":
        return 0.10 if _is_release_candidate(candidate) else 0.0
    return 0.0


def _release_metadata_bonus(
    *,
    plan: QueryPlan,
    candidate: HybridCandidate,
    release_catalog: ReleaseCatalog | None,
    latest_release_entry: object,
) -> float:
    if release_catalog is None or not release_catalog.has_entries():
        return 0.0
    entry = release_catalog.resolve(
        product_id=candidate.metadata.product_id,
        programming_language=candidate.metadata.programming_language,
        version=candidate.metadata.version,
    )
    if entry is None:
        return 0.0
    if plan.filters.preferred_version is not None:
        preferred = normalize_version_hint(plan.filters.preferred_version)
        normalized_version = normalize_version_hint(entry.version) or entry.version.casefold()
        return 0.05 if preferred == normalized_version else 0.0
    if not (plan.prefers_latest_stable or plan.intent == "release_notes"):
        return 0.0
    if not hasattr(latest_release_entry, "published_at"):
        return 0.0
    latest_published_at = latest_release_entry.published_at
    age_delta_days = max(
        int((latest_published_at - entry.published_at).total_seconds() // 86400),
        0,
    )
    if age_delta_days <= 0:
        return 0.16
    if age_delta_days <= 45:
        return 0.10
    if age_delta_days <= 120:
        return 0.05
    return 0.0


def _resolve_latest_release_entry(
    *,
    plan: QueryPlan,
    candidates: Sequence[HybridCandidate],
    release_catalog: ReleaseCatalog | None,
) -> object | None:
    if release_catalog is None or not candidates:
        return None
    product_id = candidates[0].metadata.product_id
    programming_language = candidates[0].metadata.programming_language
    return release_catalog.latest_for(
        product_id=product_id,
        programming_language=programming_language,
    )


def _is_release_candidate(candidate: HybridCandidate) -> bool:
    normalized_doc_type = candidate.metadata.doc_type.casefold()
    if normalized_doc_type in {"release_note", "release_notes", "migration_note"}:
        return True
    normalized_title = candidate.metadata.title.casefold()
    return any(
        keyword in normalized_title
        for keyword in ("release", "what's new", "migration", "breaking")
    )


def _release_version_rank(version: str) -> tuple[int, int, int, int] | None:
    tokens = re.findall(r"\d+", version)
    if not tokens:
        return None
    numbers = [int(token) for token in tokens[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _max_release_rank(
    candidates: Sequence[HybridCandidate],
) -> tuple[int, int, int, int] | None:
    release_ranks = tuple(
        rank
        for rank in (_release_version_rank(candidate.metadata.version) for candidate in candidates)
        if rank is not None
    )
    if not release_ranks:
        return None
    return max(release_ranks)


def _relative_release_rank_boost(
    *,
    release_rank: tuple[int, int, int, int],
    max_release_rank: tuple[int, int, int, int],
    max_boost: float,
) -> float:
    if release_rank == max_release_rank:
        return max_boost
    penalty_steps = sum(
        1
        for release_token, max_token in zip(release_rank, max_release_rank, strict=False)
        if release_token < max_token
    )
    return max(0.0, max_boost - (0.03 * penalty_steps))


def _tokenize(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value)}
