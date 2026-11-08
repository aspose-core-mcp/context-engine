"""Retrieval planning package for scope-aware query execution."""

from adcs.retrieval.context_packer import (
    ContextCitation,
    ContextPacker,
    ContextPackResult,
    PackedContextItem,
    PackedExecutableSnippet,
    RetrievalQualitySummary,
)
from adcs.retrieval.filter_resolver import FilterResolver, normalize_version_hint
from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.in_memory_lane_adapters import (
    InMemoryDenseLaneAdapter,
    InMemoryLexicalLaneAdapter,
)
from adcs.retrieval.models import (
    FilterDebugMetadata,
    QueryNormalizationResult,
    QueryPlan,
    QueryPlanDebugMetadata,
    QueryPlannerInput,
    ResolvedRetrievalFilters,
    RetrievalFilterRoute,
    ScopedIndexRecord,
)
from adcs.retrieval.query_planner import QueryPlanner, normalize_query
from adcs.retrieval.release_catalog import ReleaseCatalog, ReleaseCatalogEntry
from adcs.retrieval.remote_lane_adapters import (
    OpenSearchLexicalLaneAdapter,
    QdrantDenseLaneAdapter,
)
from adcs.retrieval.reranker import (
    AdvancedHeuristicReranker,
    CandidateReranker,
    DeterministicReranker,
    RerankerBackend,
    build_candidate_reranker,
)
from adcs.retrieval.retrieval_models import (
    DenseLaneAdapter,
    HybridCandidate,
    HybridRetrievalResult,
    HybridScoringConfig,
    LaneCandidate,
    LexicalLaneAdapter,
    RetrievalCandidateMetadata,
    RetrievalExecutableSnippet,
)
from adcs.retrieval.translation_fallback import (
    TRANSLATION_DEPENDENCY_UNAVAILABLE,
    LocalizedResponse,
    QueryTranslationMetadata,
    TranslatedQuery,
    TranslationClient,
    TranslationConfigError,
    TranslationDependencyUnavailableError,
    TranslationFallbackService,
    TranslationLlmConfig,
    load_translation_llm_config,
)

__all__ = [
    "ContextCitation",
    "ContextPackResult",
    "ContextPacker",
    "AdvancedHeuristicReranker",
    "CandidateReranker",
    "DenseLaneAdapter",
    "DeterministicReranker",
    "FilterDebugMetadata",
    "FilterResolver",
    "HybridCandidate",
    "HybridRetrievalResult",
    "HybridRetriever",
    "HybridScoringConfig",
    "InMemoryDenseLaneAdapter",
    "InMemoryLexicalLaneAdapter",
    "LaneCandidate",
    "LexicalLaneAdapter",
    "OpenSearchLexicalLaneAdapter",
    "PackedContextItem",
    "PackedExecutableSnippet",
    "QdrantDenseLaneAdapter",
    "QueryNormalizationResult",
    "QueryPlan",
    "QueryPlanDebugMetadata",
    "QueryPlanner",
    "QueryPlannerInput",
    "QueryTranslationMetadata",
    "ReleaseCatalog",
    "ReleaseCatalogEntry",
    "RerankerBackend",
    "RetrievalCandidateMetadata",
    "RetrievalExecutableSnippet",
    "RetrievalQualitySummary",
    "ResolvedRetrievalFilters",
    "RetrievalFilterRoute",
    "ScopedIndexRecord",
    "TRANSLATION_DEPENDENCY_UNAVAILABLE",
    "TranslatedQuery",
    "TranslationClient",
    "TranslationConfigError",
    "TranslationDependencyUnavailableError",
    "TranslationFallbackService",
    "TranslationLlmConfig",
    "LocalizedResponse",
    "load_translation_llm_config",
    "build_candidate_reranker",
    "normalize_query",
    "normalize_version_hint",
]
