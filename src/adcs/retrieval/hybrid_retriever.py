"""Hybrid retrieval orchestration for dense/lexical fusion and reranking."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence

from adcs.retrieval.models import QueryPlan
from adcs.retrieval.reranker import CandidateReranker, DeterministicReranker
from adcs.retrieval.retrieval_models import (
    DenseLaneAdapter,
    HybridCandidate,
    HybridRetrievalResult,
    HybridScoringConfig,
    LaneCandidate,
    LexicalLaneAdapter,
    RetrievalCandidateMetadata,
)

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Run dense + lexical retrieval, fuse scores, then rerank top candidates."""

    def __init__(
        self,
        *,
        dense_lane_adapter: DenseLaneAdapter,
        lexical_lane_adapter: LexicalLaneAdapter,
        scoring_config: HybridScoringConfig | None = None,
        reranker: CandidateReranker | None = None,
    ) -> None:
        self._dense_lane_adapter = dense_lane_adapter
        self._lexical_lane_adapter = lexical_lane_adapter
        self._scoring_config = scoring_config or HybridScoringConfig()
        self._reranker = reranker or DeterministicReranker()

    def retrieve(self, *, plan: QueryPlan) -> HybridRetrievalResult:
        """Execute hybrid retrieval and return reranked top-k candidates."""
        dense_candidates: tuple[LaneCandidate, ...] = ()
        lexical_candidates: tuple[LaneCandidate, ...] = ()
        try:
            dense_candidates = self._dense_lane_adapter.search(
                plan=plan,
                limit=self._scoring_config.candidate_pool_size,
            )
        except Exception:
            logger.warning("Dense lane failed, continuing with lexical only", exc_info=True)
        try:
            lexical_candidates = self._lexical_lane_adapter.search(
                plan=plan,
                limit=self._scoring_config.candidate_pool_size,
            )
        except Exception:
            logger.warning("Lexical lane failed, continuing with dense only", exc_info=True)
        return self._fuse_and_rerank(
            plan=plan,
            dense_candidates=dense_candidates,
            lexical_candidates=lexical_candidates,
        )

    async def async_retrieve(self, *, plan: QueryPlan) -> HybridRetrievalResult:
        """Non-blocking hybrid retrieval for async callers.

        If the lane adapters expose ``async_search``, those are called
        concurrently.  Otherwise the synchronous ``search`` methods are
        offloaded to a thread pool via ``asyncio.to_thread`` so they
        never block the event loop.

        When one lane fails, results from the surviving lane are still
        returned so a single-backend outage does not break the whole query.
        """
        pool_size = self._scoring_config.candidate_pool_size
        dense_adapter = self._dense_lane_adapter
        lexical_adapter = self._lexical_lane_adapter

        dense_coro = (
            dense_adapter.async_search(plan=plan, limit=pool_size)
            if hasattr(dense_adapter, "async_search")
            else asyncio.to_thread(dense_adapter.search, plan=plan, limit=pool_size)
        )
        lexical_coro = (
            lexical_adapter.async_search(plan=plan, limit=pool_size)
            if hasattr(lexical_adapter, "async_search")
            else asyncio.to_thread(lexical_adapter.search, plan=plan, limit=pool_size)
        )
        timeout = self._scoring_config.lane_timeout_seconds
        results = await asyncio.gather(
            asyncio.wait_for(dense_coro, timeout=timeout),
            asyncio.wait_for(lexical_coro, timeout=timeout),
            return_exceptions=True,
        )
        dense_result, lexical_result = results

        dense_candidates: tuple[LaneCandidate, ...]
        lexical_candidates: tuple[LaneCandidate, ...]

        if isinstance(dense_result, BaseException):
            logger.warning(
                "Dense lane failed, continuing with lexical only: %s", dense_result
            )
            dense_candidates = ()
        else:
            dense_candidates = dense_result

        if isinstance(lexical_result, BaseException):
            logger.warning(
                "Lexical lane failed, continuing with dense only: %s", lexical_result
            )
            lexical_candidates = ()
        else:
            lexical_candidates = lexical_result

        return self._fuse_and_rerank(
            plan=plan,
            dense_candidates=dense_candidates,
            lexical_candidates=lexical_candidates,
        )

    def _fuse_and_rerank(
        self,
        *,
        plan: QueryPlan,
        dense_candidates: tuple[LaneCandidate, ...],
        lexical_candidates: tuple[LaneCandidate, ...],
    ) -> HybridRetrievalResult:
        """Shared fusion and reranking logic used by both sync and async paths."""
        dense_by_chunk = _best_candidate_per_chunk(candidates=dense_candidates)
        lexical_by_chunk = _best_candidate_per_chunk(candidates=lexical_candidates)

        dense_normalized_scores = _normalize_lane_scores(candidates_by_chunk=dense_by_chunk)
        lexical_normalized_scores = _normalize_lane_scores(candidates_by_chunk=lexical_by_chunk)

        fused_candidates = _fuse_candidates(
            dense_by_chunk=dense_by_chunk,
            lexical_by_chunk=lexical_by_chunk,
            dense_normalized_scores=dense_normalized_scores,
            lexical_normalized_scores=lexical_normalized_scores,
            dense_weight=self._scoring_config.normalized_dense_weight,
            lexical_weight=self._scoring_config.normalized_lexical_weight,
        )
        rerank_pool = tuple(
            sorted(
                fused_candidates,
                key=lambda candidate: (-candidate.blended_score, candidate.metadata.candidate_id),
            )
        )[: self._scoring_config.candidate_pool_size]

        reranked_candidates = self._reranker.rerank(
            plan=plan,
            candidates=rerank_pool,
            limit=min(self._scoring_config.rerank_top_k, len(rerank_pool)),
        )

        return HybridRetrievalResult(
            query_fingerprint=plan.query_fingerprint,
            normalized_query=plan.normalized_query,
            candidates=reranked_candidates,
            dense_candidates_count=len(dense_by_chunk),
            lexical_candidates_count=len(lexical_by_chunk),
            fused_candidates_count=len(rerank_pool),
            dense_weight=self._scoring_config.normalized_dense_weight,
            lexical_weight=self._scoring_config.normalized_lexical_weight,
        )


def _best_candidate_per_chunk(
    *, candidates: Sequence[LaneCandidate]
) -> dict[str, LaneCandidate]:
    best_by_chunk: dict[str, LaneCandidate] = {}
    for candidate in candidates:
        chunk_id = candidate.metadata.chunk_id
        current_best = best_by_chunk.get(chunk_id)
        if current_best is None:
            best_by_chunk[chunk_id] = candidate
            continue
        if candidate.raw_score > current_best.raw_score:
            best_by_chunk[chunk_id] = candidate
            continue
        if (
            candidate.raw_score == current_best.raw_score
            and candidate.metadata.candidate_id < current_best.metadata.candidate_id
        ):
            best_by_chunk[chunk_id] = candidate
    return best_by_chunk


def _normalize_lane_scores(
    *, candidates_by_chunk: Mapping[str, LaneCandidate]
) -> dict[str, float]:
    if not candidates_by_chunk:
        return {}

    raw_scores = tuple(candidate.raw_score for candidate in candidates_by_chunk.values())
    min_raw_score = min(raw_scores)
    max_raw_score = max(raw_scores)
    if max_raw_score == min_raw_score:
        return {chunk_id: 1.0 for chunk_id in candidates_by_chunk}

    score_range = max_raw_score - min_raw_score
    return {
        chunk_id: (candidate.raw_score - min_raw_score) / score_range
        for chunk_id, candidate in candidates_by_chunk.items()
    }


def _fuse_candidates(
    *,
    dense_by_chunk: Mapping[str, LaneCandidate],
    lexical_by_chunk: Mapping[str, LaneCandidate],
    dense_normalized_scores: Mapping[str, float],
    lexical_normalized_scores: Mapping[str, float],
    dense_weight: float,
    lexical_weight: float,
) -> tuple[HybridCandidate, ...]:
    all_chunk_ids = tuple(sorted(set(dense_by_chunk).union(lexical_by_chunk)))
    fused_candidates: list[HybridCandidate] = []
    for chunk_id in all_chunk_ids:
        dense_candidate = dense_by_chunk.get(chunk_id)
        lexical_candidate = lexical_by_chunk.get(chunk_id)
        metadata = _select_metadata(
            dense_candidate=dense_candidate,
            lexical_candidate=lexical_candidate,
        )

        dense_normalized_score = dense_normalized_scores.get(chunk_id, 0.0)
        lexical_normalized_score = lexical_normalized_scores.get(chunk_id, 0.0)
        blended_score = (
            dense_normalized_score * dense_weight
            + lexical_normalized_score * lexical_weight
        )
        fused_candidates.append(
            HybridCandidate(
                metadata=metadata,
                dense_raw_score=(
                    dense_candidate.raw_score if dense_candidate is not None else None
                ),
                lexical_raw_score=(
                    lexical_candidate.raw_score if lexical_candidate is not None else None
                ),
                dense_normalized_score=dense_normalized_score,
                lexical_normalized_score=lexical_normalized_score,
                blended_score=blended_score,
                rerank_score=blended_score,
            )
        )
    return tuple(fused_candidates)


def _select_metadata(
    *,
    dense_candidate: LaneCandidate | None,
    lexical_candidate: LaneCandidate | None,
) -> RetrievalCandidateMetadata:
    if dense_candidate is not None:
        return dense_candidate.metadata
    if lexical_candidate is not None:
        return lexical_candidate.metadata
    msg = "At least one lane candidate must exist for metadata selection."
    raise ValueError(msg)
