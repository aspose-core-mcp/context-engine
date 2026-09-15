"""Typed models and contracts for hybrid retrieval and reranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from adcs.retrieval.models import QueryPlan


@dataclass(frozen=True, slots=True)
class RetrievalExecutableSnippet:
    """Executable snippet metadata available to retrieval/context layers."""

    snippet_id: str
    language: str
    code: str
    parent_canonical_url: str
    parent_section_anchor: str
    parent_symbol_fqn: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidateMetadata:
    """Metadata required for downstream citation/context packing.

    ``tenant_id`` partitions candidates across tenants. Defaults to
    ``"default"`` so legacy ingestion that has not yet been migrated
    to multi-tenant tagging continues to work — its candidates are
    owned by the default tenant. The tenant boundary is enforced
    upstream by :mod:`adcs.retrieval.tenant_lane_adapter`, which drops
    candidates whose tenant_id does not match the principal's tenant.
    """

    candidate_id: str
    chunk_id: str
    snapshot_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    doc_type: str
    doc_locale: str
    symbol_fqn: str | None
    title: str
    canonical_url: str
    section_anchor: str
    source_revision: str
    repo_id: str
    text: str
    checksum: str
    executable_snippets: tuple[RetrievalExecutableSnippet, ...] = ()
    tenant_id: str = "default"


@dataclass(frozen=True, slots=True)
class LaneCandidate:
    """One candidate returned from one retrieval lane."""

    metadata: RetrievalCandidateMetadata
    raw_score: float


class DenseLaneAdapter(Protocol):
    """Adapter contract for dense/vector lane retrieval."""

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        """Search candidates from dense lane."""


class LexicalLaneAdapter(Protocol):
    """Adapter contract for sparse/lexical lane retrieval."""

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        """Search candidates from lexical lane."""


@dataclass(frozen=True, slots=True)
class HybridScoringConfig:
    """Hybrid score blending and rerank limits."""

    dense_weight: float = 0.55
    lexical_weight: float = 0.45
    candidate_pool_size: int = 50
    rerank_top_k: int = 10
    lane_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.dense_weight < 0 or self.lexical_weight < 0:
            msg = "Lane weights must be non-negative."
            raise ValueError(msg)
        if self.dense_weight == 0 and self.lexical_weight == 0:
            msg = "At least one lane weight must be greater than zero."
            raise ValueError(msg)
        if self.candidate_pool_size < 1:
            msg = "candidate_pool_size must be >= 1."
            raise ValueError(msg)
        if self.rerank_top_k < 1:
            msg = "rerank_top_k must be >= 1."
            raise ValueError(msg)
        if self.lane_timeout_seconds <= 0:
            msg = "lane_timeout_seconds must be > 0."
            raise ValueError(msg)

    @property
    def normalized_dense_weight(self) -> float:
        """Dense lane blending weight normalized to total lane weight sum."""
        total = self.dense_weight + self.lexical_weight
        return self.dense_weight / total

    @property
    def normalized_lexical_weight(self) -> float:
        """Lexical lane blending weight normalized to total lane weight sum."""
        total = self.dense_weight + self.lexical_weight
        return self.lexical_weight / total


@dataclass(frozen=True, slots=True)
class HybridCandidate:
    """Candidate after score normalization, fusion, and rerank."""

    metadata: RetrievalCandidateMetadata
    dense_raw_score: float | None
    lexical_raw_score: float | None
    dense_normalized_score: float
    lexical_normalized_score: float
    blended_score: float
    rerank_score: float


@dataclass(frozen=True, slots=True)
class HybridRetrievalResult:
    """Hybrid retrieval output for downstream context packing."""

    query_fingerprint: str
    normalized_query: str
    candidates: tuple[HybridCandidate, ...]
    dense_candidates_count: int
    lexical_candidates_count: int
    fused_candidates_count: int
    dense_weight: float
    lexical_weight: float
