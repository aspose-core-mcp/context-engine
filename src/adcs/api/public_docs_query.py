"""Public REST endpoints with MCP-tool parity for documentation retrieval."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol, TypedDict
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from adcs.admin import AnalyticsService
from adcs.admin.tenancy import DEFAULT_TENANT_ID
from adcs.api.abuse_guard import AbuseGuardDecision, AbuseGuardService
from adcs.api.error_codes import (
    DEPENDENCY_UNAVAILABLE,
    HTTP_STATUS_BY_CODE,
    INVALID_ARGUMENT,
    NOT_FOUND,
    RATE_LIMITED,
    TIMEOUT,
)
from adcs.api.error_messages import public_error_message
from adcs.api.metrics import InMemoryMetrics
from adcs.indexing import SnapshotRegistry
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    ApiRefSymbolStore,
)
from adcs.indexing.index_models import SnapshotStatus
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.source_registry import SourceRegistryService
from adcs.ops.privacy import keyed_hash
from adcs.retrieval import (
    CandidateReranker,
    ContextPacker,
    DenseLaneAdapter,
    HybridCandidate,
    HybridRetrievalResult,
    HybridRetriever,
    HybridScoringConfig,
    InMemoryDenseLaneAdapter,
    InMemoryLexicalLaneAdapter,
    LexicalLaneAdapter,
    QueryPlan,
    QueryPlanner,
    QueryPlannerInput,
    ReleaseCatalog,
    RetrievalCandidateMetadata,
    TranslationFallbackService,
    build_candidate_reranker,
    normalize_version_hint,
)
from adcs.retrieval.response_cache import ResponseCache, build_cache_key
from adcs.retrieval.tenant_lane_adapter import TenantAwareLaneAdapter
from adcs.retrieval.two_source_retriever import ApiRefRetriever, looks_like_fqn

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public-docs-query"])

# How many API-reference symbols to pull from the Postgres store per query for
# the two-source fan-out before the shared reranker interleaves them with docs.
_APIREF_FANOUT_POOL = 20


class _ExplainabilityPayload(TypedDict):
    reranker_backend: str
    intent_subtype: str | None
    freshness_source: str
    why_top_result: list[str]
    why_version: str | None
    why_fallback: str | None


class ResolveProductRequest(BaseModel):
    query: str = Field(min_length=1)


class ResolveProductCandidate(BaseModel):
    product_id: str
    confidence: float


class ResolveProductResponse(BaseModel):
    product_id: str
    language: str | None
    aliases: list[str]
    confidence: float
    # Ranked alternatives on a weak/ambiguous match (additive, optional). Lets a
    # caller see other plausible products instead of trusting a single answer.
    candidates: list[ResolveProductCandidate] = Field(default_factory=list)


class QueryDocsRequest(BaseModel):
    query: str = Field(min_length=1)
    product_id: str | None = None
    language: str | None = None
    version: str | None = None
    query_locale: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)
    strict_version: bool = True
    doc_types: list[str] = Field(default_factory=list)
    include_examples: bool = True
    debug: bool = False


class QueryDocsResultItem(BaseModel):
    class ExecutableSnippet(BaseModel):
        snippet_id: str
        language: str
        code: str
        parent_canonical_url: str
        parent_section_anchor: str
        parent_symbol_fqn: str | None

    chunk_id: str
    title: str
    excerpt: str
    canonical_url: str
    section_anchor: str
    score: float
    source_revision: str
    executable_snippets: list[ExecutableSnippet]


class QueryDocsResponse(BaseModel):
    class Quality(BaseModel):
        overall_score: float
        coverage_score: float
        freshness_score: float
        freshness_source: str
        citation_density_score: float
        symbol_match_score: float
        intent: str
        intent_subtype: str | None = None
        completeness_status: str
        completeness_missing_signals: list[str] = Field(default_factory=list)

    class Explainability(BaseModel):
        reranker_backend: str
        intent_subtype: str | None = None
        freshness_source: str
        why_top_result: list[str] = Field(default_factory=list)
        why_version: str | None = None
        why_fallback: str | None = None

    class VersionResolution(BaseModel):
        requested_version: str | None = None
        preferred_version: str | None = None
        resolved_version: str | None = None
        available_versions: list[str] = Field(default_factory=list)
        prefers_latest_stable: bool = False
        strict_version_enforced: bool = False
        fallback_applied: bool = False
        fallback_reason: str | None = None

    query_id: str
    request_id: str
    mode: str
    query_locale_detected: str
    translation_fallback_applied: bool
    confidence: float
    confidence_level: str
    fallback_reason: str | None = None
    version_resolution: VersionResolution
    clarification_questions: list[str] = Field(default_factory=list)
    quality: Quality
    results: list[QueryDocsResultItem]
    warnings: list[str]
    api_guardrails: list[str] = Field(default_factory=list)
    explainability: Explainability
    debug: dict[str, object] | None = None


class QueryFeedbackRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=120)
    rating: str = Field(min_length=1, max_length=40)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)


class QueryFeedbackResponse(BaseModel):
    feedback_id: str
    request_id: str
    rating: str
    reason_codes: list[str]
    updated_existing: bool
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    created_at: str
    updated_at: str


class QueryIssueRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=120)
    issue_type: str = Field(min_length=1, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)


class QueryIssueResponse(BaseModel):
    issue_id: str
    request_id: str
    issue_type: str
    updated_existing: bool
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    created_at: str
    updated_at: str


class QueryReproCitationResponse(BaseModel):
    title: str
    canonical_url: str
    section_anchor: str
    score: float
    source_revision: str
    executable_snippets_count: int


class QueryReproScopeResponse(BaseModel):
    request_id: str
    endpoint: str
    tool: str
    raw_query: str
    product_id: str | None = None
    programming_language: str | None = None
    doc_locale: str | None = None
    captured_at: str


class QueryReproOriginalResponse(BaseModel):
    outcome: str
    retrieval_mode: str | None = None
    result_count: int
    confidence: float
    latency_ms: int
    zero_result_reason: str | None = None
    fallback_reason: str | None = None
    warning_codes: list[str] = Field(default_factory=list)


class QueryReproLinkedSignalsResponse(BaseModel):
    total_feedback: int
    latest_feedback_rating: str | None = None
    total_issue_reports: int
    issue_types: list[str] = Field(default_factory=list)
    last_feedback_at: str | None = None
    last_issue_at: str | None = None


class QueryReproReplayResponse(BaseModel):
    mode: str
    query_locale_detected: str
    translation_fallback_applied: bool
    confidence: float
    confidence_level: str
    fallback_reason: str | None = None
    result_count: int
    warnings: list[str] = Field(default_factory=list)
    version_resolution: QueryDocsResponse.VersionResolution
    quality: QueryDocsResponse.Quality
    clarification_questions: list[str] = Field(default_factory=list)
    api_guardrails: list[str] = Field(default_factory=list)
    citations: list[QueryReproCitationResponse] = Field(default_factory=list)


class QueryReproPackResponse(BaseModel):
    request_id: str
    share_url: str
    generated_at: str
    assumptions: list[str] = Field(default_factory=list)
    handoff_notes: list[str] = Field(default_factory=list)
    scope: QueryReproScopeResponse
    original: QueryReproOriginalResponse
    replay: QueryReproReplayResponse
    linked_signals: QueryReproLinkedSignalsResponse


class GetSymbolDocRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    version: str | None = None
    symbol_fqn: str = Field(min_length=1)


class SymbolParameterResponse(BaseModel):
    name: str
    type: str
    description: str


class SymbolExampleResponse(BaseModel):
    language: str
    code: str


class SymbolCitationResponse(BaseModel):
    canonical_url: str
    section_anchor: str


class SymbolSignatureVariantResponse(BaseModel):
    signature: str
    source_kind: str
    chunk_type: str
    is_deprecated: bool
    citation: SymbolCitationResponse


class GetSymbolDocResponse(BaseModel):
    symbol_fqn: str
    signature: str
    summary: str
    parameters: list[SymbolParameterResponse]
    returns: str
    examples: list[SymbolExampleResponse]
    citations: list[SymbolCitationResponse]
    deprecated: bool
    signature_variants: list[SymbolSignatureVariantResponse]
    guardrails: list[str]


class ListBreakingChangesRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    from_version: str
    to_version: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class BreakingChangeCitationResponse(BaseModel):
    canonical_url: str
    section_anchor: str


class BreakingChangeItemResponse(BaseModel):
    type: str
    symbol_fqn: str | None
    from_version: str | None = None
    to_version: str | None = None
    description: str
    migration_hint: str
    citation: BreakingChangeCitationResponse


class ListBreakingChangesResponse(BaseModel):
    items: list[BreakingChangeItemResponse]
    page: int
    page_size: int
    total: int


class ListLatestReleaseFeaturesRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    version: str | None = None
    top_k: int = Field(default=12, ge=1, le=50)


class ReleaseFeatureCitationResponse(BaseModel):
    canonical_url: str
    section_anchor: str


class ReleaseFeatureItemResponse(BaseModel):
    kind: str
    summary: str
    symbol_fqn: str | None
    version: str
    source_kind: str
    citation: ReleaseFeatureCitationResponse


class ListLatestReleaseFeaturesResponse(BaseModel):
    product_id: str
    language: str
    resolved_version: str
    items: list[ReleaseFeatureItemResponse]
    guardrails: list[str]


@dataclass(frozen=True, slots=True)
class _ProductCandidate:
    product_id: str
    confidence: float


@dataclass(frozen=True, slots=True)
class _ProductResolution:
    product_id: str
    language: str | None
    aliases: tuple[str, ...]
    confidence: float
    candidates: tuple[_ProductCandidate, ...] = ()


@dataclass(frozen=True, slots=True)
class _VersionResolution:
    requested_version: str | None
    preferred_version: str | None
    resolved_version: str | None
    available_versions: tuple[str, ...]
    prefers_latest_stable: bool
    strict_version_enforced: bool
    fallback_applied: bool
    fallback_reason: str | None


class RetrievalSettingsLookup(Protocol):
    """Minimal read view of the per-product retrieval settings.

    Declared structurally so the query path does not import the admin service
    (and so a test can pass a stub). Only `resolve` is needed here — the query
    path never writes settings.
    """

    def resolve(self, *, product_id: str) -> object: ...


class PublicQueryService:
    """Public query service used by REST/MCP parity endpoints."""

    def __init__(
        self,
        *,
        source_hugo_normalization_orchestrator: SourceHugoNormalizationOrchestrationService,
        translation_fallback_service: TranslationFallbackService,
        source_registry_service: SourceRegistryService | None = None,
        dense_lane_adapter: DenseLaneAdapter | None = None,
        lexical_lane_adapter: LexicalLaneAdapter | None = None,
        candidate_reranker: CandidateReranker | None = None,
        release_catalog: ReleaseCatalog | None = None,
        qdrant_url: str | None = None,
        scoring_config: HybridScoringConfig | None = None,
        snapshot_registry: SnapshotRegistry | None = None,
        apiref_symbol_store: ApiRefSymbolStore | None = None,
        retrieval_settings_service: RetrievalSettingsLookup | None = None,
        response_cache: ResponseCache[QueryDocsResponse] | None = None,
        stage_observer: Callable[[str, float], None] | None = None,
    ) -> None:
        # Per-stage retrieval timings are computed on every query and exported
        # as component metrics rather than only written to one INFO log line,
        # which nothing aggregates. Injected as a plain callback so the service
        # keeps no metrics dependency and stays constructible in tests without one.
        self._stage_observer = stage_observer
        self._source_hugo_normalization_orchestrator = source_hugo_normalization_orchestrator
        self._translation_fallback_service = translation_fallback_service
        self._source_registry_service = source_registry_service or SourceRegistryService()
        self._query_planner = QueryPlanner()
        self._release_catalog = release_catalog
        self._context_packer = ContextPacker(release_catalog=release_catalog)
        self._dense_lane_adapter = dense_lane_adapter
        self._lexical_lane_adapter = lexical_lane_adapter
        self._candidate_reranker = candidate_reranker or build_candidate_reranker(
            backend="advanced_heuristic",
            release_catalog=release_catalog,
        )
        self._scoring_config = scoring_config
        self._qdrant_url = qdrant_url.rstrip("/") if qdrant_url else None
        self._qdrant_symbol_collection = "apiref_dense_v1"
        self._qdrant_timeout_seconds = 3.0
        self._snapshot_registry = snapshot_registry
        # Postgres structured symbol store (ADR-011). When present,
        # get_symbol_doc prefers it over the legacy apiref_dense_v1 collection,
        # falling back to dense lookup when the symbol is absent — so the cutover
        # is safe while the structured store is only partially populated.
        self._apiref_symbol_store = apiref_symbol_store
        # Per-product retrieval settings. The admin API lets an operator PATCH
        # these and writes the change to the audit trail, but the service was
        # injected nowhere — so every operator adjustment was an audited no-op
        # and the low-confidence gate ran on a hardcoded 0.15 while the settings
        # said 0.35.
        self._retrieval_settings_service = retrieval_settings_service
        # Retrieval response cache. None disables it entirely, which is how
        # every existing test path behaves unless it opts in.
        self._response_cache = response_cache

    # Retained as the value used when no settings service is wired (tests and
    # embedded runtimes). best_effort_with_warning is the default posture, so
    # this stays deliberately low: it suppresses only results that are
    # near-worthless, not merely uncertain ones.
    _DEFAULT_SUPPRESSION_THRESHOLD = 0.15

    def _resolve_max_context_tokens(self, *, product_id: str | None) -> int | None:
        """Per-product total-token cap, or None to use the packer default."""
        service = self._retrieval_settings_service
        if service is None or not product_id:
            return None
        try:
            record = service.resolve(product_id=product_id)
            value = getattr(record, "max_context_tokens", None)
        except Exception:
            return None
        if isinstance(value, int) and value > 0:
            return value
        return None

    def _resolve_suppression_threshold(self, *, product_id: str | None) -> float:
        service = self._retrieval_settings_service
        if service is None or not product_id:
            return self._DEFAULT_SUPPRESSION_THRESHOLD
        try:
            record = service.resolve(product_id=product_id)
            threshold = getattr(record, "low_confidence_threshold", None)
        except Exception:
            logger.warning(
                "retrieval settings lookup failed for product=%s; using default threshold",
                product_id,
            )
            return self._DEFAULT_SUPPRESSION_THRESHOLD
        if isinstance(threshold, (int, float)) and 0.0 <= float(threshold) <= 1.0:
            return float(threshold)
        return self._DEFAULT_SUPPRESSION_THRESHOLD

    def resolve_product(self, *, query: str) -> _ProductResolution:
        repositories = self._source_registry_service.list_repositories()
        unique_products = sorted(
            {(repository.product_id, repository.product_family) for repository in repositories}
        )
        if not unique_products:
            return _ProductResolution(
                product_id="unknown",
                language=_detect_language_hint(query),
                aliases=(),
                confidence=0.0,
            )

        scored = sorted(
            (
                (
                    _product_match_score(
                        query=query,
                        product_id=product_id,
                        product_family=product_family,
                    ),
                    product_id,
                    product_family,
                )
                for product_id, product_family in unique_products
            ),
            # Highest score first; break ties by product_id ascending so the
            # result is deterministic and never depends on the alphabetical
            # *maximum* — the old `max((score, product_id))` sent every floor-tie
            # query to the last product_id (`groupdocs.watermark`).
            key=lambda item: (-item[0], item[1]),
        )
        language = _detect_language_hint(query)
        best_score, best_product_id, best_product_family = scored[0]

        # Candidates: everything that scored above the no-signal floor, ranked.
        # They let a caller (and its LLM) see alternatives instead of trusting a
        # single answer on a weak match.
        candidates = tuple(
            _ProductCandidate(product_id=product_id, confidence=score)
            for score, product_id, _family in scored
            if score > _PRODUCT_MATCH_FLOOR
        )[:5]

        # No tier matched anything: return the explicit unknown sentinel rather
        # than a definitive — and arbitrary — wrong product.
        if best_score <= _PRODUCT_MATCH_FLOOR:
            return _ProductResolution(
                product_id="unknown",
                language=language,
                aliases=(),
                confidence=best_score,
                candidates=(),
            )

        return _ProductResolution(
            product_id=best_product_id,
            language=language,
            aliases=(best_product_id, best_product_family),
            confidence=best_score,
            candidates=candidates,
        )

    def query_docs(
        self,
        *,
        request: QueryDocsRequest,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> QueryDocsResponse:
        """Run the public retrieval pipeline for one tenant.

        ``tenant_id`` scopes every retrieval lane: candidates whose
        ``metadata.tenant_id`` does not match are dropped before they
        reach the reranker, context packer, or the response surface
        (see :class:`TenantAwareLaneAdapter`). It defaults to
        ``"default"`` so single-tenant deployments and existing callers
        that pass no tenant keep their current behaviour — the default
        tenant sees only ``tenant_id == "default"`` candidates, which is
        every legacy chunk (the metadata default).
        """
        t0 = perf_counter()
        cache_key = build_cache_key(
            tenant_id=tenant_id,
            query=request.query,
            product_id=request.product_id,
            language=request.language,
            version=request.version,
            query_locale=request.query_locale,
            top_k=request.top_k,
            strict_version=request.strict_version,
            doc_types=tuple(request.doc_types),
            include_examples=request.include_examples,
            debug=request.debug,
        )
        cached = self._response_cache.get(cache_key) if self._response_cache else None
        if cached is not None:
            # Re-stamp the identifiers. request_id is the key the feedback and
            # issue endpoints deduplicate on, so replaying one would make two
            # callers collide on each other's records — the retrieval result is
            # shareable, the identity of the request is not.
            return cached.model_copy(
                update={"query_id": str(uuid4()), "request_id": str(uuid4())}
            )

        resolved_product = self.resolve_product(query=request.query)
        product_id = request.product_id or resolved_product.product_id
        programming_language = request.language or resolved_product.language

        translated_query = self._translation_fallback_service.prepare_query(
            query=request.query,
            requested_locale=request.query_locale,
        )
        t_translate = perf_counter()
        plan = self._query_planner.plan(
            request=QueryPlannerInput(
                query=translated_query.retrieval_query,
                product_id=product_id,
                programming_language=programming_language,
                version=request.version,
                doc_locale=request.query_locale,
                strict_version=request.strict_version,
            )
        )
        plan = self._annotate_plan_with_active_snapshots(
            plan=plan,
            product_id=product_id,
            programming_language=programming_language,
            version=request.version,
            strict_version=request.strict_version,
        )
        t_plan = perf_counter()

        retrieval_result = self._run_retrieval(
            plan=plan,
            requested_doc_types=request.doc_types,
            include_examples=request.include_examples,
            tenant_id=tenant_id,
        )
        t_retrieve = perf_counter()

        # Graceful degradation: when retrieval returned zero results, retry
        # without the language filter so that products indexed with
        # programming_language="unknown" still return useful results.
        # This applies even when language was explicitly provided — some
        # products only have cross-language docs in the index.
        language_was_explicit = bool(request.language)
        _cross_language_fallback = False
        if not retrieval_result.candidates and programming_language:
            logger.info(
                "language_fallback product=%s lang=%s query=%s",
                product_id, programming_language, request.query[:80],
            )
            plan = self._query_planner.plan(
                request=QueryPlannerInput(
                    query=translated_query.retrieval_query,
                    product_id=product_id,
                    programming_language=None,
                    version=request.version,
                    doc_locale=request.query_locale,
                    strict_version=request.strict_version,
                )
            )
            plan = self._annotate_plan_with_active_snapshots(
                plan=plan,
                product_id=product_id,
                programming_language=None,
                version=request.version,
                strict_version=request.strict_version,
            )
            retrieval_result = self._run_retrieval(
                plan=plan,
                requested_doc_types=request.doc_types,
                include_examples=request.include_examples,
                tenant_id=tenant_id,
            )
            # Tag cross-language fallback — checked later when building warnings.
            _cross_language_fallback = language_was_explicit and bool(
                retrieval_result.candidates
            )

        # An empty strict-version result is the correct answer, not a condition to
        # recover from: strict_version forbids returning other versions, with no
        # exception, so a caller never receives APIs from a version it did not
        # ask for. Callers that will accept nearest-available content request it
        # up front with strict_version=false, which drops the version predicate
        # before the first retrieval. The empty scope is reported to the caller
        # through the strict_version_no_match warning below.
        strict_version_no_match = (
            not retrieval_result.candidates and request.strict_version and bool(request.version)
        )
        if strict_version_no_match:
            logger.info(
                "strict_version_no_match product=%s version=%s query=%s",
                product_id, request.version, request.query[:80],
            )

        # Two-source fan-out (ADR-011): documentation comes from the
        # Qdrant/OpenSearch hybrid lane above; structured API-reference symbols
        # come from the Postgres symbol store and are fused in here. This is what
        # lets the apiref_dense_v1 Qdrant lane be retired.
        # No-op (docs-only behaviour preserved) when the structured store is
        # unavailable or has no symbols for the resolved scope.
        retrieval_result = self._fuse_apiref_symbols(
            retrieval_result=retrieval_result,
            plan=plan,
            query=translated_query.retrieval_query,
            product_id=product_id,
            programming_language=programming_language,
            version=request.version,
        )

        packed_context = self._context_packer.pack(
            plan=plan,
            retrieval_result=retrieval_result,
            top_k=request.top_k,
            # Per-product cap from the admin settings, so `max_context_tokens`
            # is an operator control rather than another inert field.
            max_total_tokens=self._resolve_max_context_tokens(product_id=product_id),
        )
        t_pack = perf_counter()
        version_resolution = _resolve_version_resolution(
            plan=plan,
            candidates=retrieval_result.candidates,
        )

        # Confidence gate: suppress low-confidence results to avoid feeding
        # misleading partial context to AI consumers that causes hallucinations
        # worse than no retrieval at all. The threshold comes from the product's
        # retrieval settings, which an operator can change through the admin API;
        # it used to be a hardcoded 0.15 while those settings said 0.35, so the
        # knob was inert and the effective policy was invisible.
        suppression_threshold = self._resolve_suppression_threshold(product_id=product_id)
        if (
            packed_context.confidence_level == "low"
            and packed_context.confidence < suppression_threshold
            and packed_context.items
        ):
            logger.info(
                "confidence_gate product=%s query=%s confidence=%.3f — suppressing %d results",
                product_id, request.query[:60],
                packed_context.confidence, len(packed_context.items),
            )
            from dataclasses import replace as _dc_replace
            packed_context = _dc_replace(
                packed_context,
                items=(),
                fallback_reason="low_confidence_suppressed",
            )

        warnings = list(translated_query.metadata.warning_reasons)
        if _cross_language_fallback:
            _append_warning(warnings, "cross_language_fallback")
        if not retrieval_result.candidates:
            _append_warning(warnings, "no_index_data")
        if strict_version_no_match:
            _append_warning(warnings, "strict_version_no_match")
        for warning in packed_context.warnings:
            _append_warning(warnings, warning)
        if packed_context.fallback_reason is not None:
            _append_warning(warnings, packed_context.fallback_reason)
        if version_resolution.fallback_applied and version_resolution.fallback_reason is not None:
            _append_warning(warnings, "version_fallback_applied")
            _append_warning(warnings, version_resolution.fallback_reason)
        if packed_context.quality.completeness_status != "complete":
            _append_warning(warnings, "answer_incomplete")

        response_items: list[QueryDocsResultItem] = []
        for item in packed_context.items:
            localized_excerpt = self._translation_fallback_service.localize_answer(
                answer_text=item.excerpt,
                translated_query=translated_query,
            )
            for warning in localized_excerpt.warning_reasons:
                _append_warning(warnings, warning)
            response_items.append(
                QueryDocsResultItem(
                    chunk_id=item.candidate_id,
                    title=item.citation.title,
                    excerpt=localized_excerpt.answer_text,
                    canonical_url=item.citation.canonical_url,
                    section_anchor=item.citation.section_anchor,
                    score=item.citation.score,
                    source_revision=item.citation.source_revision,
                    executable_snippets=[
                        QueryDocsResultItem.ExecutableSnippet(
                            snippet_id=snippet.snippet_id,
                            language=snippet.language,
                            code=snippet.code,
                            parent_canonical_url=snippet.parent_canonical_url,
                            parent_section_anchor=snippet.parent_section_anchor,
                            parent_symbol_fqn=snippet.parent_symbol_fqn,
                        )
                        for snippet in item.snippets
                    ],
                )
            )
        api_guardrails = _extract_api_guardrails(
            excerpts=[item.excerpt for item in packed_context.items]
        )
        explainability = _build_explainability(
            plan=plan,
            candidates=retrieval_result.candidates,
            version_resolution=version_resolution,
            packed_context=packed_context,
            reranker_backend=self._candidate_reranker.backend_name,
        )

        t_end = perf_counter()
        self._observe_stage("translate", t_translate - t0)
        self._observe_stage("plan", t_plan - t_translate)
        self._observe_stage("retrieve", t_retrieve - t_plan)
        self._observe_stage("pack", t_pack - t_retrieve)
        self._observe_stage("total", t_end - t0)
        logger.info(
            "query_docs product=%s lang=%s intent=%s results=%d confidence=%.2f "
            "translate_ms=%.1f plan_ms=%.1f retrieve_ms=%.1f pack_ms=%.1f total_ms=%.1f",
            product_id,
            plan.filters.programming_language,
            plan.intent,
            len(response_items),
            packed_context.confidence,
            (t_translate - t0) * 1000,
            (t_plan - t_translate) * 1000,
            (t_retrieve - t_plan) * 1000,
            (t_pack - t_retrieve) * 1000,
            (t_end - t0) * 1000,
        )

        response = QueryDocsResponse(
            query_id=str(uuid4()),
            request_id=str(uuid4()),
            mode=_resolve_retrieval_mode(plan),
            query_locale_detected=translated_query.metadata.query_locale_detected,
            translation_fallback_applied=translated_query.metadata.translation_fallback_applied,
            confidence=packed_context.confidence,
            confidence_level=packed_context.confidence_level,
            fallback_reason=packed_context.fallback_reason or version_resolution.fallback_reason,
            version_resolution=QueryDocsResponse.VersionResolution(
                requested_version=version_resolution.requested_version,
                preferred_version=version_resolution.preferred_version,
                resolved_version=version_resolution.resolved_version,
                available_versions=list(version_resolution.available_versions),
                prefers_latest_stable=version_resolution.prefers_latest_stable,
                strict_version_enforced=version_resolution.strict_version_enforced,
                fallback_applied=version_resolution.fallback_applied,
                fallback_reason=version_resolution.fallback_reason,
            ),
            clarification_questions=list(packed_context.clarification_questions),
            quality=QueryDocsResponse.Quality(
                overall_score=packed_context.quality.overall_score,
                coverage_score=packed_context.quality.coverage_score,
                freshness_score=packed_context.quality.freshness_score,
                freshness_source=packed_context.quality.freshness_source,
                citation_density_score=packed_context.quality.citation_density_score,
                symbol_match_score=packed_context.quality.symbol_match_score,
                intent=packed_context.quality.intent,
                intent_subtype=packed_context.quality.intent_subtype,
                completeness_status=packed_context.quality.completeness_status,
                completeness_missing_signals=list(
                    packed_context.quality.completeness_missing_signals
                ),
            ),
            results=response_items,
            warnings=warnings,
            api_guardrails=api_guardrails,
            explainability=QueryDocsResponse.Explainability(
                reranker_backend=explainability["reranker_backend"],
                intent_subtype=explainability["intent_subtype"],
                freshness_source=explainability["freshness_source"],
                why_top_result=list(explainability["why_top_result"]),
                why_version=explainability["why_version"],
                why_fallback=explainability["why_fallback"],
            ),
            debug=_to_debug_payload(plan) if request.debug else None,
        )
        if self._response_cache is not None:
            self._response_cache.put(cache_key, response)
        return response

    def _resolve_active_snapshot_ids(
        self,
        *,
        product_id: str | None,
        programming_language: str | None,
        version: str | None,
        strict_version: bool,
    ) -> tuple[str, ...] | None:
        """Resolve the set of currently-active snapshot ids for a query scope.

        Returns:
            - ``None`` in three cases, all of which mean "no active-snapshot
              filtering for this query":
                1. The snapshot registry was not wired (legacy/test path).
                2. The caller did not provide a ``product_id`` (wide scope).
                3. The registry has zero entries for the requested scope.
                   This happens when data is provisioned out-of-band of the
                   registry (e.g., live integration tests that point at real
                   Qdrant/OpenSearch but keep the registry in memory). In
                   that case the registry is not authoritative for this
                   scope, so falling back to unfiltered retrieval is safer
                   than returning zero results.
            - A possibly-empty ``tuple`` of active snapshot ids otherwise.
              An empty tuple means "this scope has snapshots, but none are
              active right now" — e.g., a rollback that orphaned all heads.
              Retrieval then correctly returns zero results instead of
              serving stale inactive-snapshot points.

        Why the filter is needed: Qdrant uses deterministic chunk-id point
        ids so re-publishing the same chunk overwrites in place, but chunks
        that exist in an old snapshot and not in the new one become orphan
        points tagged with the old (now inactive) ``snapshot_id``. Without a
        query-time filter the dense lane would happily return those orphan
        points, especially after a rollback where the newest active snapshot
        is older than the previous head. Filtering by the current active set
        resolved from the registry gives us the same atomicity the OpenSearch
        lane already has via its per-snapshot indices + alias.
        """
        if self._snapshot_registry is None:
            return None
        if product_id is None:
            return None
        effective_version = version if (strict_version and version) else None
        snapshots = self._snapshot_registry.list_snapshots(
            product_id=product_id,
            programming_language=programming_language,
            version=effective_version,
        )
        if not snapshots:
            # Registry has no knowledge of this scope — do not enforce.
            # See the docstring: out-of-band data provisioning means the
            # registry is not authoritative for this query.
            return None
        return tuple(
            sorted(
                {
                    snapshot.snapshot_id
                    for snapshot in snapshots
                    if snapshot.status is SnapshotStatus.ACTIVE
                }
            )
        )

    def _annotate_plan_with_active_snapshots(
        self,
        *,
        plan: QueryPlan,
        product_id: str | None,
        programming_language: str | None,
        version: str | None,
        strict_version: bool,
    ) -> QueryPlan:
        """Rewrite plan routes with the resolved set of active snapshot ids.

        No-op when the registry is unavailable or the scope is not resolvable.
        """
        active_ids = self._resolve_active_snapshot_ids(
            product_id=product_id,
            programming_language=programming_language,
            version=version,
            strict_version=strict_version,
        )
        if active_ids is None:
            return plan
        new_routes = tuple(
            _dataclass_replace(route, active_snapshot_ids=active_ids)
            for route in plan.filters.routes
        )
        new_filters = _dataclass_replace(plan.filters, routes=new_routes)
        return _dataclass_replace(plan, filters=new_filters)

    def _observe_stage(self, stage: str, seconds: float) -> None:
        """Report one stage duration, never letting telemetry fail a query."""
        if self._stage_observer is None:
            return
        try:
            self._stage_observer(stage, seconds)
        except Exception:  # pragma: no cover - defensive
            logger.exception("stage observer failed for stage=%s", stage)

    def _run_retrieval(
        self,
        *,
        plan: QueryPlan,
        requested_doc_types: Sequence[str],
        include_examples: bool,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> HybridRetrievalResult:
        if self._dense_lane_adapter is not None and self._lexical_lane_adapter is not None:
            retriever = HybridRetriever(
                dense_lane_adapter=TenantAwareLaneAdapter(
                    inner=self._dense_lane_adapter, tenant_id=tenant_id
                ),
                lexical_lane_adapter=TenantAwareLaneAdapter(
                    inner=self._lexical_lane_adapter, tenant_id=tenant_id
                ),
                reranker=self._candidate_reranker,
                scoring_config=self._scoring_config,
            )
            retrieval_result = retriever.retrieve(plan=plan)
            return _filter_retrieval_result(
                retrieval_result=retrieval_result,
                requested_doc_types=requested_doc_types,
                include_examples=include_examples,
            )

        chunk_records = self._source_hugo_normalization_orchestrator.get_latest_chunk_records(
            product_id=plan.filters.product_id,
            programming_language=plan.filters.programming_language,
            version=None,
        )
        filtered_chunk_records = tuple(
            record
            for record in chunk_records
            if _chunk_matches_doc_type_filter(
                chunk_record=record,
                requested_doc_types=requested_doc_types,
                include_examples=include_examples,
            )
        )
        dense_adapter = InMemoryDenseLaneAdapter(
            chunk_records=filtered_chunk_records,
            snapshot_id="snapshot-local",
        )
        lexical_adapter = InMemoryLexicalLaneAdapter(
            chunk_records=filtered_chunk_records,
            snapshot_id="snapshot-local",
        )
        retriever = HybridRetriever(
            dense_lane_adapter=TenantAwareLaneAdapter(
                inner=dense_adapter, tenant_id=tenant_id
            ),
            lexical_lane_adapter=TenantAwareLaneAdapter(
                inner=lexical_adapter, tenant_id=tenant_id
            ),
            reranker=self._candidate_reranker,
            scoring_config=self._scoring_config,
        )
        return retriever.retrieve(plan=plan)

    def _fuse_apiref_symbols(
        self,
        *,
        retrieval_result: HybridRetrievalResult,
        plan: QueryPlan,
        query: str,
        product_id: str | None,
        programming_language: str | None,
        version: str | None,
    ) -> HybridRetrievalResult:
        """Fuse Postgres API-reference symbols into the docs retrieval result.

        Implements the two-source fan-out (ADR-011): documentation is served
        by the Qdrant/OpenSearch hybrid lane; API-reference symbols by
        the structured Postgres store (no vectors). Matching symbols are turned
        into :class:`HybridCandidate`s and re-scored together with the docs
        candidates by the *same* reranker, so one coherent ranking flows into the
        context packer (and quality/explainability) unchanged.

        Returns the input untouched — preserving every docs-only code path and
        test — when the structured store is absent or the resolved scope has no
        symbols.
        """
        apiref_candidates = self._apiref_symbol_candidates(
            query=query,
            product_id=product_id,
            programming_language=programming_language,
            version=version,
            limit=_APIREF_FANOUT_POOL,
        )
        if not apiref_candidates:
            return retrieval_result
        combined = (*retrieval_result.candidates, *apiref_candidates)
        reranked = self._candidate_reranker.rerank(
            plan=plan,
            candidates=combined,
            limit=len(combined),
        )
        return _dataclass_replace(
            retrieval_result,
            candidates=tuple(reranked),
            fused_candidates_count=len(reranked),
        )

    def _apiref_symbol_candidates(
        self,
        *,
        query: str,
        product_id: str | None,
        programming_language: str | None,
        version: str | None,
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        """Resolve API-reference symbols for a query from the Postgres store.

        Scopes to ``product/language/version`` (apiref is English-only for v1).
        The apiref corpus is versioned independently of docs — it is loaded under
        a single ``latest-stable`` snapshot, not the numeric release versions used
        for documentation — so the active apiref version for the scope is the
        authoritative one and is preferred over any docs ``version`` the caller
        passed (which would otherwise never match). The requested version is only
        a fallback for scopes with no active snapshot. Blends name + full-text
        search (via the shared :class:`ApiRefRetriever`) and pins an exact-FQN
        match when the query is a bare dotted symbol path. Defensive: never raises
        into the docs query.
        """
        store = self._apiref_symbol_store
        if store is None or not product_id or not programming_language:
            return ()
        locale = "en"
        concrete_version = (
            store.resolve_active_version(
                product=product_id, language=programming_language, locale=locale
            )
            or version
        )
        if not concrete_version:
            return ()
        scope = ApiRefScope(
            product=product_id,
            language=programming_language,
            version=concrete_version,
            locale=locale,
        )
        lane = ApiRefRetriever(store=store)
        try:
            symbols = list(lane.search(query=query, scope=scope, limit=limit))
            if looks_like_fqn(query):
                exact = lane.lookup_exact(
                    member_fqn=query.strip().removesuffix("()"), scope=scope
                )
                seen = {(sym.member_fqn, sym.signature or "") for sym in symbols}
                symbols = [
                    *(s for s in exact if (s.member_fqn, s.signature or "") not in seen),
                    *symbols,
                ]
        except Exception:
            logger.warning("apiref_fanout_failed product=%s", product_id, exc_info=True)
            return ()
        return tuple(
            self._apiref_symbol_to_candidate(symbol=symbol, rank=rank)
            for rank, symbol in enumerate(symbols)
        )

    @staticmethod
    def _apiref_symbol_to_candidate(
        *, symbol: ApiRefSymbol, rank: int
    ) -> HybridCandidate:
        """Adapt a structured symbol row to a reranker-ready hybrid candidate."""
        signature = (symbol.signature or "").strip()
        summary = (symbol.summary or "").strip()
        if signature and summary:
            text = f"{signature}\n\n{summary}"
        else:
            text = signature or summary or symbol.name
        anchor = symbol.payload.get("section_anchor")
        section_anchor = anchor if isinstance(anchor, str) else ""
        revision = symbol.payload.get("source_revision")
        source_revision = (
            revision if isinstance(revision, str) and revision else symbol.snapshot_id
        )
        metadata = RetrievalCandidateMetadata(
            candidate_id=f"apiref:{symbol.member_fqn}:{symbol.signature or ''}:{rank}",
            chunk_id=f"apiref:{symbol.member_fqn}",
            snapshot_id=symbol.snapshot_id,
            product_id=symbol.product,
            programming_language=symbol.language,
            version=symbol.version,
            source_kind="apiref",
            doc_type="api_reference_symbol",
            doc_locale=symbol.locale,
            symbol_fqn=symbol.member_fqn,
            title=symbol.member_fqn,
            canonical_url=symbol.canonical_url or "",
            section_anchor=section_anchor,
            source_revision=source_revision,
            repo_id=f"{symbol.product}.apiref",
            text=text,
            checksum="",
        )
        # Gentle rank-based prior; the shared reranker layers query-overlap,
        # symbol-match, and intent signals on top, so content relevance — not this
        # seed — decides the final interleave with docs candidates.
        prior = max(0.05, 0.55 - 0.03 * rank)
        return HybridCandidate(
            metadata=metadata,
            dense_raw_score=prior,
            lexical_raw_score=None,
            dense_normalized_score=prior,
            lexical_normalized_score=0.0,
            blended_score=prior,
            rerank_score=prior,
        )

    def _qdrant_symbol_lookup(
        self,
        *,
        symbol_fqn: str,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        """Query Qdrant apiref collection for chunks matching a symbol FQN.

        Tries exact match first (case-insensitive), then suffix/prefix match.
        Returns an empty tuple when Qdrant is unavailable or has no matches.
        """
        if not self._qdrant_url:
            return ()

        # --- build strategies: exact first, then suffix, then prefix ---
        strategies: list[dict[str, object]] = []

        # 1) exact match (case-insensitive via match-text for keyword fields)
        strategies.append(
            {"key": "symbol_fqn", "match": {"value": symbol_fqn}},
        )

        # Pin symbol lookups to currently-active snapshots so we never
        # resurface a stale symbol payload from an inactive snapshot.
        active_snapshot_clause: dict[str, object] | None = None
        if self._snapshot_registry is not None and product_id is not None:
            active_ids = self._resolve_active_snapshot_ids(
                product_id=product_id,
                programming_language=programming_language,
                version=version,
                strict_version=version is not None,
            )
            if active_ids is not None:
                from adcs.retrieval.remote_lane_adapters import (
                    _NO_ACTIVE_SNAPSHOT_SENTINEL,
                )
                active_list = list(active_ids) or [_NO_ACTIVE_SNAPSHOT_SENTINEL]
                if len(active_list) == 1:
                    active_snapshot_clause = {
                        "key": "snapshot_id",
                        "match": {"value": active_list[0]},
                    }
                else:
                    active_snapshot_clause = {
                        "key": "snapshot_id",
                        "match": {"any": active_list},
                    }

        # We'll try strategies in order and return on first success.
        for strategy_filter in strategies:
            must_clauses: list[dict[str, object]] = [strategy_filter]
            if product_id is not None:
                must_clauses.append(
                    {"key": "product_id", "match": {"value": product_id}}
                )
            if programming_language is not None:
                must_clauses.append(
                    {"key": "programming_language", "match": {"value": programming_language}}
                )
            if version is not None:
                must_clauses.append(
                    {"key": "version", "match": {"value": version}}
                )
            if active_snapshot_clause is not None:
                must_clauses.append(active_snapshot_clause)

            payload: dict[str, object] = {
                "filter": {"must": must_clauses},
                "limit": 30,
                "with_payload": True,
            }

            try:
                status_code, body = _qdrant_request_json(
                    url=(
                        f"{self._qdrant_url}/collections/"
                        f"{self._qdrant_symbol_collection}/points/scroll"
                    ),
                    payload=payload,
                    timeout_seconds=self._qdrant_timeout_seconds,
                )
            except RuntimeError:
                logger.warning(
                    "Qdrant symbol lookup unavailable; falling back to state store.",
                    exc_info=True,
                )
                return ()

            if status_code != 200:
                logger.warning(
                    "Qdrant symbol scroll returned status=%d; "
                    "falling back to state store.",
                    status_code,
                )
                return ()

            records = _qdrant_points_to_chunk_records(body)
            if records:
                return records

        # --- suffix / prefix fallback: relax the symbol_fqn filter ---
        # Qdrant keyword match is exact-only, so we scroll broader and
        # filter client-side for suffix/prefix matches.
        symbol_lower = symbol_fqn.casefold()
        must_clauses_broad: list[dict[str, object]] = []
        if product_id is not None:
            must_clauses_broad.append(
                {"key": "product_id", "match": {"value": product_id}}
            )
        if programming_language is not None:
            must_clauses_broad.append(
                {"key": "programming_language", "match": {"value": programming_language}}
            )
        if version is not None:
            must_clauses_broad.append(
                {"key": "version", "match": {"value": version}}
            )
        if active_snapshot_clause is not None:
            must_clauses_broad.append(active_snapshot_clause)

        # Only attempt broad scroll when we have at least one scope filter.
        if must_clauses_broad:
            broad_payload: dict[str, object] = {
                "filter": {"must": must_clauses_broad},
                "limit": 200,
                "with_payload": True,
            }
            try:
                status_code, body = _qdrant_request_json(
                    url=(
                        f"{self._qdrant_url}/collections/"
                        f"{self._qdrant_symbol_collection}/points/scroll"
                    ),
                    payload=broad_payload,
                    timeout_seconds=self._qdrant_timeout_seconds,
                )
            except RuntimeError:
                return ()

            if status_code == 200:
                all_records = _qdrant_points_to_chunk_records(body)
                # 1. exact full-FQN match (highest precision)
                exact_matches = tuple(
                    r for r in all_records
                    if r.symbol_fqn
                    and r.symbol_fqn.casefold() == symbol_lower
                )
                if exact_matches:
                    return exact_matches
                # 2. exact last-segment match (e.g. query "RecognitionSettings"
                #    matches "Aspose.OCR.RecognitionSettings" but not
                #    "DocumentRecognitionSettings" unless its last segment is
                #    also exactly "RecognitionSettings")
                query_tail = symbol_lower.rsplit(".", 1)[-1]
                segment_matches = tuple(
                    r for r in all_records
                    if r.symbol_fqn
                    and r.symbol_fqn.casefold().rsplit(".", 1)[-1] == query_tail
                )
                if segment_matches:
                    # prefer shortest FQN — most direct class, not subclass
                    return tuple(
                        sorted(segment_matches, key=lambda r: len(r.symbol_fqn or ""))
                    )
                # 3. suffix match (fallback for nested names)
                suffix_matches = tuple(
                    r for r in all_records
                    if r.symbol_fqn
                    and r.symbol_fqn.casefold().endswith(symbol_lower)
                )
                if suffix_matches:
                    return tuple(
                        sorted(suffix_matches, key=lambda r: len(r.symbol_fqn or ""))
                    )
                # 4. prefix match
                prefix_matches = tuple(
                    r for r in all_records
                    if r.symbol_fqn
                    and r.symbol_fqn.casefold().startswith(symbol_lower)
                )
                if prefix_matches:
                    return prefix_matches

        return ()

    def _structured_get_symbol_doc(
        self, *, request: GetSymbolDocRequest
    ) -> GetSymbolDocResponse | None:
        """Resolve a symbol from the Postgres structured store (ADR-011).

        Returns ``None`` — so the caller falls back to the legacy dense path —
        when the structured store is unavailable, the scope has no active
        version, or the symbol is not present. This keeps the cutover safe while
        the structured store is only partially populated: products already
        migrated answer from Postgres, the rest still answer from the legacy path.

        ``version`` is optional on the public contract and MCP callers rarely
        know a concrete SDK version. Resolve the scope's active version when the
        request omits one instead of giving up: the legacy fallback targets the
        RETIRED ``apiref_dense_v1`` collection, so bailing out here would make
        ``get_symbol_doc`` answer NOT_FOUND for symbols that are present in
        Postgres.
        """
        store = self._apiref_symbol_store
        if store is None:
            return None
        version = request.version or store.resolve_active_version(
            product=request.product_id,
            language=request.language,
        )
        if not version:
            return None
        scope = ApiRefScope(
            product=request.product_id,
            language=request.language,
            version=version,
        )
        overloads = tuple(store.get_symbol(member_fqn=request.symbol_fqn, scope=scope))
        if not overloads:
            return None

        def _anchor(symbol: ApiRefSymbol) -> str:
            value = symbol.payload.get("section_anchor")
            return value if isinstance(value, str) else ""

        primary = overloads[0]
        signature = primary.signature or primary.member_fqn
        signature_parameters, signature_returns = _parse_signature_contract(signature)
        returns_payload = primary.payload.get("returns")
        returns = (
            returns_payload
            if isinstance(returns_payload, str) and returns_payload
            else signature_returns
        )
        summary = (primary.summary or "")[:480].strip()

        example_codes: list[str] = []
        for symbol in overloads:
            payload_examples = symbol.payload.get("examples")
            if isinstance(payload_examples, list):
                example_codes.extend(
                    item for item in payload_examples if isinstance(item, str)
                )
        examples = [
            SymbolExampleResponse(language=request.language, code=code)
            for code in dict.fromkeys(example_codes)
        ][:3]

        signature_variants = [
            SymbolSignatureVariantResponse(
                signature=symbol.signature,
                source_kind="apiref",
                chunk_type=symbol.kind or "symbol",
                is_deprecated=symbol.is_deprecated,
                citation=SymbolCitationResponse(
                    canonical_url=symbol.canonical_url or "",
                    section_anchor=_anchor(symbol),
                ),
            )
            for symbol in overloads
            if symbol.signature
        ]
        citations = _dedupe_citations(
            citations=[variant.citation for variant in signature_variants]
            + [
                SymbolCitationResponse(
                    canonical_url=primary.canonical_url or "",
                    section_anchor=_anchor(primary),
                )
            ]
        )
        deprecated = any(symbol.is_deprecated for symbol in overloads)
        guardrails = _build_symbol_guardrails(
            symbol_fqn=primary.member_fqn,
            signature_variants=signature_variants,
            deprecated=deprecated,
        )
        return GetSymbolDocResponse(
            symbol_fqn=primary.member_fqn,
            signature=signature,
            summary=summary,
            parameters=signature_parameters,
            returns=returns,
            examples=examples,
            citations=citations,
            deprecated=deprecated,
            signature_variants=signature_variants,
            guardrails=guardrails,
        )

    def get_symbol_doc(self, *, request: GetSymbolDocRequest) -> GetSymbolDocResponse:
        # Preferred path: the Postgres structured symbol store (ADR-011). Falls
        # through to the legacy dense path when the structured store is
        # unavailable or has no match for this symbol.
        structured = self._structured_get_symbol_doc(request=request)
        if structured is not None:
            return structured

        # Legacy path: query Qdrant directly for symbol lookup.
        matching = self._qdrant_symbol_lookup(
            symbol_fqn=request.symbol_fqn,
            product_id=request.product_id,
            programming_language=request.language,
            version=request.version,
        )

        # Fallback: use state store if Qdrant returned nothing.
        if not matching:
            records = self._source_hugo_normalization_orchestrator.get_latest_chunk_records(
                product_id=request.product_id,
                programming_language=request.language,
                version=request.version,
            )
            symbol = request.symbol_fqn.casefold()
            matching = tuple(
                record
                for record in records
                if record.symbol_fqn and record.symbol_fqn.casefold() == symbol
            )
            if not matching:
                matching = tuple(
                    record
                    for record in records
                    if record.symbol_fqn
                    and record.symbol_fqn.casefold().endswith(symbol)
                )

        if not matching:
            raise LookupError(f"Symbol `{request.symbol_fqn}` was not found.")

        preferred_locale = "en"
        ordered_matching = tuple(
            sorted(
                matching,
                key=lambda item: _symbol_record_preference_key(
                    chunk_record=item,
                    preferred_locale=preferred_locale,
                ),
            )
        )
        primary = ordered_matching[0]
        primary_locale = _normalize_doc_locale_value(primary.doc_locale)
        signature = _extract_signature_line(primary.text, fallback=primary.title)
        signature_parameters, signature_returns = _parse_signature_contract(signature)
        summary = primary.text[:480].strip()
        same_locale_examples = [
            record
            for record in ordered_matching
            if record.chunk_type == "api_example"
            and _normalize_doc_locale_value(record.doc_locale) == primary_locale
        ]
        fallback_examples = [
            record
            for record in ordered_matching
            if record.chunk_type == "api_example"
            and _normalize_doc_locale_value(record.doc_locale) != primary_locale
        ]
        examples = [
            SymbolExampleResponse(language=request.language, code=record.text)
            for record in (*same_locale_examples, *fallback_examples)
        ][:3]
        signature_variants = _build_signature_variants(ordered_matching=ordered_matching)
        citations = _dedupe_citations(
            citations=[
                variant.citation for variant in signature_variants
            ]
            + [
            SymbolCitationResponse(
                canonical_url=primary.canonical_url,
                section_anchor=primary.section_anchor,
            )
            ]
        )
        deprecated = any(record.is_deprecated for record in ordered_matching)
        guardrails = _build_symbol_guardrails(
            symbol_fqn=primary.symbol_fqn or request.symbol_fqn,
            signature_variants=signature_variants,
            deprecated=deprecated,
        )
        return GetSymbolDocResponse(
            symbol_fqn=primary.symbol_fqn or request.symbol_fqn,
            signature=signature,
            summary=summary,
            parameters=signature_parameters,
            returns=signature_returns,
            examples=examples,
            citations=citations,
            deprecated=deprecated,
            signature_variants=signature_variants,
            guardrails=guardrails,
        )

    # Query used to pull release/migration content out of the retrieval lanes.
    # These two tools have no user query of their own, so the lanes need one.
    _RELEASE_LANE_QUERY = (
        "release notes what's new breaking changes deprecated migration guide"
    )

    def _release_records_from_retrieval(
        self,
        *,
        product_id: str,
        language: str,
        version: str | None,
    ) -> tuple[StageDChunkRecord, ...]:
        """Read release/migration chunks from the retrieval lanes.

        list_breaking_changes and list_latest_release_features resolved their
        data solely through the ingestion operation-state store, which lives on
        the pod's filesystem under artifacts/runtime-state. In a containerised
        deployment that directory is excluded from the image, mounted from nothing,
        written by a different pod, and never restored by DR — so both tools
        returned nothing no matter how much corpus was loaded.

        The retrieval lanes hold the same chunks, are the path deployments
        actually serve from, and are covered by the DR restore. Used as a
        fallback so a workstation with a populated state store keeps its
        behaviour unchanged.
        """
        if self._dense_lane_adapter is None and self._lexical_lane_adapter is None:
            return ()
        try:
            plan = self._query_planner.plan(
                request=QueryPlannerInput(
                    query=self._RELEASE_LANE_QUERY,
                    product_id=product_id,
                    programming_language=language,
                    version=version,
                    doc_locale=None,
                    strict_version=version is not None,
                )
            )
            plan = self._annotate_plan_with_active_snapshots(
                plan=plan,
                product_id=product_id,
                programming_language=language,
                version=version,
                strict_version=version is not None,
            )
            # No doc-type filter here on purpose: that filter understands only
            # "api_reference" and "guide" and matches on source_kind, so asking it
            # for release notes silently matches nothing. Release selection is
            # _filter_release_feature_records' job, and it already keys on
            # doc_type and text.
            retrieval_result = self._run_retrieval(
                plan=plan,
                requested_doc_types=[],
                include_examples=False,
            )
        except Exception:  # a lane failure must not mask the tool
            logger.warning(
                "release-note lane lookup failed product=%s language=%s version=%s",
                product_id,
                language,
                version,
            )
            return ()
        return tuple(
            _candidate_to_chunk_record(candidate) for candidate in retrieval_result.candidates
        )

    def list_breaking_changes(
        self,
        *,
        request: ListBreakingChangesRequest,
    ) -> ListBreakingChangesResponse:
        from_records = self._source_hugo_normalization_orchestrator.get_latest_chunk_records(
            product_id=request.product_id,
            programming_language=request.language,
            version=request.from_version,
        )
        if not from_records:
            from_records = self._release_records_from_retrieval(
                product_id=request.product_id,
                language=request.language,
                version=request.from_version,
            )
        to_records = self._source_hugo_normalization_orchestrator.get_latest_chunk_records(
            product_id=request.product_id,
            programming_language=request.language,
            version=request.to_version,
        )
        if not to_records:
            to_records = self._release_records_from_retrieval(
                product_id=request.product_id,
                language=request.language,
                version=request.to_version,
            )
        items = _build_breaking_changes_diff_items(
            from_records=from_records,
            to_records=to_records,
            from_version=request.from_version,
            to_version=request.to_version,
        )
        start = (request.page - 1) * request.page_size
        end = start + request.page_size
        paged_items = items[start:end]
        return ListBreakingChangesResponse(
            items=paged_items,
            page=request.page,
            page_size=request.page_size,
            total=len(items),
        )

    def list_latest_release_features(
        self,
        *,
        request: ListLatestReleaseFeaturesRequest,
    ) -> ListLatestReleaseFeaturesResponse:
        records = self._source_hugo_normalization_orchestrator.get_latest_chunk_records(
            product_id=request.product_id,
            programming_language=request.language,
            version=request.version,
        )
        if not records:
            records = self._release_records_from_retrieval(
                product_id=request.product_id,
                language=request.language,
                version=request.version,
            )
        if not records:
            raise LookupError(
                "No records were found for selected product/language/version scope."
            )

        release_records = _filter_release_feature_records(
            records=records,
            requested_version=request.version,
        )
        if not release_records:
            raise LookupError("No release or migration notes were found in selected scope.")

        items = _build_release_feature_items(
            records=release_records,
            top_k=request.top_k,
        )
        if not items:
            raise LookupError("Release notes were found but no actionable features were extracted.")

        resolved_version = _resolve_latest_version(
            records=release_records,
            requested_version=request.version,
        )
        return ListLatestReleaseFeaturesResponse(
            product_id=request.product_id,
            language=request.language,
            resolved_version=resolved_version,
            items=items,
            guardrails=[
                (
                    f"Prefer APIs listed for version `{resolved_version}`; avoid legacy aliases "
                    "unless migration notes explicitly require them."
                ),
                "For exact signatures always call `get_symbol_doc` before writing code.",
                (
                    "If upgrading from older version, call `list_breaking_changes` "
                    "and apply migration hints."
                ),
            ],
        )


@router.post("/v1/products:resolve", response_model=ResolveProductResponse)
async def resolve_product(
    request_payload: ResolveProductRequest,
    request: Request,
) -> ResolveProductResponse:
    started_at = perf_counter()
    guard_decision = _enforce_abuse_guard(request)
    service = _public_query_service(request)
    resolved = service.resolve_product(query=request_payload.query)
    response = ResolveProductResponse(
        product_id=resolved.product_id,
        language=resolved.language,
        aliases=list(resolved.aliases),
        confidence=resolved.confidence,
        candidates=[
            ResolveProductCandidate(product_id=c.product_id, confidence=c.confidence)
            for c in resolved.candidates
        ],
    )
    _record_analytics(
        request=request,
        endpoint="rest.products.resolve",
        tool="resolve_product",
        raw_query=request_payload.query,
        product_id=response.product_id,
        programming_language=response.language,
        doc_locale=None,
        confidence=response.confidence,
        latency_ms=_elapsed_ms(started_at),
        hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
        fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
    )
    return response


@router.post("/v1/docs:query", response_model=QueryDocsResponse)
async def query_docs(request_payload: QueryDocsRequest, request: Request) -> QueryDocsResponse:
    started_at = perf_counter()
    guard_decision = _enforce_abuse_guard(request)
    service = _public_query_service(request)
    tenant_id = _resolve_request_tenant(request)
    # Debug is privileged. The endpoint is unauthenticated, so an unprivileged
    # caller asking for debug would otherwise get the normalised query, intent
    # reason codes, snapshot/locale routing order and the effective filters.
    # Drop the flag rather than rejecting the request: the answer itself is
    # public, only the explanation is not.
    if request_payload.debug and not _is_privileged_caller(request):
        request_payload = request_payload.model_copy(update={"debug": False})
    endpoint_timeout = getattr(
        getattr(request.app, "state", None), "endpoint_timeout_seconds", 30.0
    )
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                service.query_docs,
                request=request_payload,
                tenant_id=tenant_id,
            ),
            timeout=endpoint_timeout,
        )
    except LookupError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:NOT_FOUND",
            ),
        ) from exc
    except TimeoutError as exc:
        # Split out from the RuntimeError branch below: folding it in made REST
        # answer a timeout with DEPENDENCY_UNAVAILABLE while MCP answered the
        # same failure with TIMEOUT.
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[TIMEOUT],
            code=TIMEOUT,
            message=public_error_message(
                exc,
                fallback="The request timed out. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:TIMEOUT",
            ),
        ) from exc
    except RuntimeError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message=public_error_message(
                exc,
                fallback="A required backend is unavailable. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:DEPENDENCY_UNAVAILABLE",
            ),
        ) from exc
    request_id = str(getattr(request.state, "request_id", None) or uuid4())
    response.query_id = request_id
    response.request_id = request_id
    if (
        guard_decision is not None
        and guard_decision.exceeded
        and not guard_decision.blocked
    ):
        _append_warning(response.warnings, "abuse_guard_threshold_exceeded_observe_only")
    result_count = len(response.results)
    outcome = _derive_query_docs_outcome(
        confidence=response.confidence,
        fallback_reason=response.fallback_reason,
        result_count=result_count,
        warnings=response.warnings,
    )
    zero_result_reason = _derive_zero_result_reason(
        result_count=result_count,
        warnings=response.warnings,
    )
    fallback_reason = response.fallback_reason or _derive_fallback_reason(
        warnings=response.warnings
    )
    _record_analytics(
        request=request,
        endpoint="rest.docs.query",
        tool="query_docs",
        raw_query=request_payload.query,
        product_id=request_payload.product_id,
        programming_language=request_payload.language,
        doc_locale=request_payload.query_locale,
        confidence=response.confidence,
        latency_ms=_elapsed_ms(started_at),
        hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
        fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
        outcome=outcome,
        retrieval_mode=response.mode,
        result_count=result_count,
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        warning_codes=response.warnings,
    )
    _observe_retrieval_slis(request=request, response=response)
    return response


@router.post("/v1/docs:feedback", response_model=QueryFeedbackResponse)
async def submit_query_feedback(
    payload: QueryFeedbackRequest,
    request: Request,
) -> QueryFeedbackResponse:
    _enforce_abuse_guard(request)
    analytics_service = _analytics_service(request)
    if analytics_service is None:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message="Analytics service is not configured.",
        )
    actor_identity = _feedback_actor_identity(request)
    try:
        record, updated_existing = analytics_service.record_usefulness_feedback(
            request_id=payload.request_id,
            actor_identity=actor_identity,
            rating=payload.rating,
            reason_codes=payload.reason_codes,
        )
    except LookupError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message="request_id was not found in analytics history.",
        ) from exc
    except ValueError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[INVALID_ARGUMENT],
            code=INVALID_ARGUMENT,
            message=public_error_message(
                exc,
                fallback="The feedback payload could not be processed as given.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:INVALID_FEEDBACK",
            ),
        ) from exc
    return QueryFeedbackResponse(
        feedback_id=record.feedback_id,
        request_id=record.request_id,
        rating=record.rating,
        reason_codes=list(record.reason_codes),
        updated_existing=updated_existing,
        product_id=record.product_id,
        programming_language=record.programming_language,
        doc_locale=record.doc_locale,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


@router.post("/v1/docs:issues", response_model=QueryIssueResponse)
async def submit_query_issue(
    payload: QueryIssueRequest,
    request: Request,
) -> QueryIssueResponse:
    _enforce_abuse_guard(request)
    analytics_service = _analytics_service(request)
    if analytics_service is None:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message="Analytics service is not configured.",
        )
    actor_identity = _feedback_actor_identity(request)
    try:
        record, updated_existing = analytics_service.record_issue_report(
            request_id=payload.request_id,
            actor_identity=actor_identity,
            issue_type=payload.issue_type,
            notes=payload.notes,
        )
    except LookupError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message="request_id was not found in analytics history.",
        ) from exc
    except ValueError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[INVALID_ARGUMENT],
            code=INVALID_ARGUMENT,
            message=public_error_message(
                exc,
                fallback="The issue report could not be processed as given.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:INVALID_ISSUE_REPORT",
            ),
        ) from exc

    return QueryIssueResponse(
        issue_id=record.issue_id,
        request_id=record.request_id,
        issue_type=record.issue_type,
        updated_existing=updated_existing,
        product_id=record.product_id,
        programming_language=record.programming_language,
        doc_locale=record.doc_locale,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


@router.get("/v1/docs:repro-pack", response_model=QueryReproPackResponse)
async def get_query_repro_pack(
    request_id: str,
    request: Request,
) -> QueryReproPackResponse:
    _enforce_abuse_guard(request)
    analytics_service = _analytics_service(request)
    if analytics_service is None:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message="Analytics service is not configured.",
        )
    query_record = analytics_service.get_record(request_id)
    if query_record is None:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message="request_id was not found in analytics history.",
        )
    if query_record.tool != "query_docs":
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[INVALID_ARGUMENT],
            code=INVALID_ARGUMENT,
            message="Only query_docs request_id values can be exported as repro packs.",
        )

    replay_request = QueryDocsRequest(
        query=query_record.raw_query,
        product_id=query_record.product_id,
        language=query_record.programming_language,
        query_locale=query_record.doc_locale,
        strict_version=False,
        include_examples=True,
        top_k=5,
    )
    replay_response = _public_query_service(request).query_docs(request=replay_request)
    feedback_records = analytics_service.list_usefulness_feedback(
        request_id=query_record.request_id
    )
    issue_records = analytics_service.list_issue_reports(
        request_id=query_record.request_id
    )

    return QueryReproPackResponse(
        request_id=query_record.request_id,
        share_url=_build_public_repro_share_url(
            request=request,
            request_id=query_record.request_id,
        ),
        generated_at=datetime.now(tz=UTC).isoformat(),
        assumptions=_build_public_repro_assumptions(query_record=query_record),
        handoff_notes=_build_public_repro_handoff_notes(query_record=query_record),
        scope=QueryReproScopeResponse(
            request_id=query_record.request_id,
            endpoint=query_record.endpoint,
            tool=query_record.tool,
            raw_query=query_record.raw_query,
            product_id=query_record.product_id,
            programming_language=query_record.programming_language,
            doc_locale=query_record.doc_locale,
            captured_at=query_record.created_at.isoformat(),
        ),
        original=QueryReproOriginalResponse(
            outcome=query_record.outcome,
            retrieval_mode=query_record.retrieval_mode,
            result_count=query_record.result_count,
            confidence=query_record.confidence,
            latency_ms=query_record.latency_ms,
            zero_result_reason=query_record.zero_result_reason,
            fallback_reason=query_record.fallback_reason,
            warning_codes=list(query_record.warning_codes),
        ),
        replay=QueryReproReplayResponse(
            mode=replay_response.mode,
            query_locale_detected=replay_response.query_locale_detected,
            translation_fallback_applied=replay_response.translation_fallback_applied,
            confidence=replay_response.confidence,
            confidence_level=replay_response.confidence_level,
            fallback_reason=replay_response.fallback_reason,
            result_count=len(replay_response.results),
            warnings=list(replay_response.warnings),
            version_resolution=replay_response.version_resolution,
            quality=replay_response.quality,
            clarification_questions=list(replay_response.clarification_questions),
            api_guardrails=list(replay_response.api_guardrails),
            citations=[
                QueryReproCitationResponse(
                    title=item.title,
                    canonical_url=item.canonical_url,
                    section_anchor=item.section_anchor,
                    score=item.score,
                    source_revision=item.source_revision,
                    executable_snippets_count=len(item.executable_snippets),
                )
                for item in replay_response.results[:5]
            ],
        ),
        linked_signals=QueryReproLinkedSignalsResponse(
            total_feedback=len(feedback_records),
            latest_feedback_rating=feedback_records[0].rating if feedback_records else None,
            total_issue_reports=len(issue_records),
            issue_types=sorted({record.issue_type for record in issue_records}),
            last_feedback_at=(
                feedback_records[0].updated_at.isoformat()
                if feedback_records
                else None
            ),
            last_issue_at=issue_records[0].updated_at.isoformat() if issue_records else None,
        ),
    )


@router.post("/v1/symbols:get", response_model=GetSymbolDocResponse)
async def get_symbol_doc(
    request_payload: GetSymbolDocRequest,
    request: Request,
) -> GetSymbolDocResponse:
    started_at = perf_counter()
    guard_decision = _enforce_abuse_guard(request)
    service = _public_query_service(request)
    try:
        response = service.get_symbol_doc(request=request_payload)
        _record_analytics(
            request=request,
            endpoint="rest.symbols.get",
            tool="get_symbol_doc",
            raw_query=request_payload.symbol_fqn,
            product_id=request_payload.product_id,
            programming_language=request_payload.language,
            doc_locale=None,
            confidence=1.0,
            latency_ms=_elapsed_ms(started_at),
            hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
            fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
        )
        return response
    except LookupError as exc:
        _record_analytics(
            request=request,
            endpoint="rest.symbols.get",
            tool="get_symbol_doc",
            raw_query=request_payload.symbol_fqn,
            product_id=request_payload.product_id,
            programming_language=request_payload.language,
            doc_locale=None,
            confidence=0.0,
            latency_ms=_elapsed_ms(started_at),
            hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
            fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
        )
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:NOT_FOUND",
            ),
        ) from exc


@router.post("/v1/changes:list", response_model=ListBreakingChangesResponse)
async def list_breaking_changes(
    request_payload: ListBreakingChangesRequest,
    request: Request,
) -> ListBreakingChangesResponse:
    started_at = perf_counter()
    guard_decision = _enforce_abuse_guard(request)
    service = _public_query_service(request)
    try:
        response = service.list_breaking_changes(request=request_payload)
    except LookupError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:NOT_FOUND",
            ),
        ) from exc
    except TimeoutError as exc:
        # Split out from the RuntimeError branch below: folding it in made REST
        # answer a timeout with DEPENDENCY_UNAVAILABLE while MCP answered the
        # same failure with TIMEOUT.
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[TIMEOUT],
            code=TIMEOUT,
            message=public_error_message(
                exc,
                fallback="The request timed out. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:TIMEOUT",
            ),
        ) from exc
    except RuntimeError as exc:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[DEPENDENCY_UNAVAILABLE],
            code=DEPENDENCY_UNAVAILABLE,
            message=public_error_message(
                exc,
                fallback="A required backend is unavailable. Retry shortly.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:DEPENDENCY_UNAVAILABLE",
            ),
        ) from exc
    _record_analytics(
        request=request,
        endpoint="rest.changes.list",
        tool="list_breaking_changes",
        raw_query=f"{request_payload.from_version}->{request_payload.to_version}",
        product_id=request_payload.product_id,
        programming_language=request_payload.language,
        doc_locale=None,
        confidence=1.0 if response.items else 0.5,
        latency_ms=_elapsed_ms(started_at),
        hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
        fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
    )
    return response


@router.post("/v1/releases:latest", response_model=ListLatestReleaseFeaturesResponse)
async def list_latest_release_features(
    request_payload: ListLatestReleaseFeaturesRequest,
    request: Request,
) -> ListLatestReleaseFeaturesResponse:
    started_at = perf_counter()
    guard_decision = _enforce_abuse_guard(request)
    service = _public_query_service(request)
    try:
        response = service.list_latest_release_features(request=request_payload)
    except LookupError as exc:
        _record_analytics(
            request=request,
            endpoint="rest.releases.latest",
            tool="list_latest_release_features",
            raw_query=request_payload.version or "latest",
            product_id=request_payload.product_id,
            programming_language=request_payload.language,
            doc_locale=None,
            confidence=0.0,
            latency_ms=_elapsed_ms(started_at),
            hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
            fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
        )
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[NOT_FOUND],
            code=NOT_FOUND,
            message=public_error_message(
                exc,
                fallback="The requested resource was not found.",
                request_id=getattr(request.state, "request_id", None),
                context="public_docs_query:NOT_FOUND",
            ),
        ) from exc

    _record_analytics(
        request=request,
        endpoint="rest.releases.latest",
        tool="list_latest_release_features",
        raw_query=request_payload.version or "latest",
        product_id=request_payload.product_id,
        programming_language=request_payload.language,
        doc_locale=None,
        confidence=1.0 if response.items else 0.5,
        latency_ms=_elapsed_ms(started_at),
        hashed_ip=guard_decision.hashed_ip if guard_decision is not None else None,
        fingerprint=guard_decision.fingerprint if guard_decision is not None else None,
    )
    return response


def _public_query_service(request: Request) -> PublicQueryService:
    return request.app.state.public_query_service


def _is_privileged_caller(request: Request) -> bool:
    """Return True when the caller presents a valid admin API key.

    Used only to decide whether the debug payload may be returned. The endpoint
    itself stays unauthenticated: a missing or invalid key simply means no debug,
    never a rejected query.
    """
    api_key = request.headers.get("x-api-key")
    if not api_key or not api_key.strip():
        return False
    try:
        from adcs.api.admin_auth import (
            AdminAuthError,
            get_admin_auth_service,
        )

        get_admin_auth_service(request).authenticate(api_key=api_key)
    except AdminAuthError:
        return False
    except Exception:
        return False
    return True


def _resolve_request_tenant(request: Request) -> str:
    """Resolve the tenant scope for a public query.

    Public endpoints are unauthenticated, so there is no admin principal
    to read a tenant from. A multi-tenant deployment routes tenants via
    the ``x-tenant-id`` request header — set by the edge proxy after it
    authenticates the tenant, never trusted from an anonymous client in
    a single-tenant deployment. An absent or blank header resolves to
    the default tenant, preserving single-tenant behaviour and keeping
    every existing caller unchanged.
    """
    header_value = request.headers.get("x-tenant-id")
    if header_value is None:
        return DEFAULT_TENANT_ID
    normalized = header_value.strip()
    return normalized or DEFAULT_TENANT_ID


def _analytics_service(request: Request) -> AnalyticsService | None:
    service = getattr(request.app.state, "analytics_service", None)
    if isinstance(service, AnalyticsService):
        return service
    return None


def _abuse_guard_service(request: Request) -> AbuseGuardService | None:
    service = getattr(request.app.state, "abuse_guard_service", None)
    if isinstance(service, AbuseGuardService):
        return service
    return None


def _observe_retrieval_slis(*, request: Request, response: QueryDocsResponse) -> None:
    """Record the confidence and citation SLIs for one served response.

    Both are headline retrieval SLIs; recording them per response exposes them
    as metrics instead of requiring a separate measurement run.
    """
    metrics = getattr(request.app.state, "metrics", None)
    if not isinstance(metrics, InMemoryMetrics):
        return
    missing = sum(
        1
        for item in response.results
        if not item.canonical_url.strip() or not item.section_anchor.strip()
    )
    metrics.observe_retrieval_response(
        confidence_level=response.confidence_level,
        results_total=len(response.results),
        results_missing_citation=missing,
    )


def _observe_abuse_guard_decision(*, request: Request, decision: AbuseGuardDecision) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, InMemoryMetrics):
        metrics.observe_abuse_guard_decision(
            mode=decision.mode.value,
            decision=decision.reason,
        )


def _enforce_abuse_guard(request: Request) -> AbuseGuardDecision | None:
    service = _abuse_guard_service(request)
    if service is None:
        return None
    decision = service.evaluate_request(request=request)
    _observe_abuse_guard_decision(request=request, decision=decision)
    if decision.blocked:
        raise _error_response(
            request=request,
            status_code=HTTP_STATUS_BY_CODE[RATE_LIMITED],
            code=RATE_LIMITED,
            message="Request throttled by abuse guard policy.",
        )
    return decision


def _record_analytics(
    *,
    request: Request,
    endpoint: str,
    tool: str,
    raw_query: str,
    product_id: str | None,
    programming_language: str | None,
    doc_locale: str | None,
    confidence: float,
    latency_ms: int,
    hashed_ip: str | None = None,
    fingerprint: str | None = None,
    outcome: str | None = None,
    retrieval_mode: str | None = None,
    result_count: int | None = None,
    zero_result_reason: str | None = None,
    fallback_reason: str | None = None,
    warning_codes: Sequence[str] | None = None,
) -> None:
    analytics_service = _analytics_service(request)
    if analytics_service is None:
        return

    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    analytics_service.record_query(
        request_id=str(request_id),
        endpoint=endpoint,
        tool=tool,
        raw_query=raw_query,
        product_id=product_id,
        programming_language=programming_language,
        doc_locale=doc_locale,
        hashed_ip=hashed_ip or _hash_client_ip(request),
        fingerprint=fingerprint or request.headers.get("x-adcs-fingerprint"),
        latency_ms=latency_ms,
        confidence=confidence,
        outcome=outcome,
        retrieval_mode=retrieval_mode,
        result_count=result_count,
        zero_result_reason=zero_result_reason,
        fallback_reason=fallback_reason,
        warning_codes=warning_codes,
    )


def _hash_client_ip(request: Request) -> str | None:
    client = request.client
    if client is None or not client.host.strip():
        return None
    return keyed_hash(client.host, purpose="ip_hash")


def _feedback_actor_identity(request: Request) -> str:
    fingerprint = request.headers.get("x-adcs-fingerprint")
    normalized_fingerprint = fingerprint.strip() if fingerprint else ""
    if normalized_fingerprint:
        return f"fingerprint:{normalized_fingerprint}"
    hashed_ip = _hash_client_ip(request)
    if hashed_ip:
        return f"hashed_ip:{hashed_ip}"
    return "anonymous:unknown"


def _build_public_repro_share_url(*, request: Request, request_id: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/integrations?shared_request_id={request_id}"


def _build_public_repro_assumptions(*, query_record: object) -> list[str]:
    assumptions = [
        (
            "This repro pack replays the current public retrieval state and never "
            "writes a new analytics event."
        ),
        (
            "Only public-safe fields are included here; admin-only analytics, "
            "IP hashes, fingerprints, and issue notes are intentionally excluded."
        ),
        (
            "Version hints are not stored in analytics history, so the replay "
            "resolves the best current scope from the saved product and SDK language."
        ),
    ]
    doc_locale = getattr(query_record, "doc_locale", None)
    if not doc_locale:
        assumptions.append(
            "No explicit query locale was stored for the original request, so replay "
            "falls back to automatic locale detection."
        )
    programming_language = getattr(query_record, "programming_language", None)
    if not programming_language:
        assumptions.append(
            "No explicit SDK language was stored for the original request, so replay "
            "relies on current product resolution heuristics."
        )
    return assumptions


def _build_public_repro_handoff_notes(*, query_record: object) -> list[str]:
    request_id = str(getattr(query_record, "request_id", "unknown"))
    product_id = getattr(query_record, "product_id", None) or "auto"
    programming_language = getattr(query_record, "programming_language", None) or "auto"
    return [
        (
            "Share this pack or its stable link whenever support needs the exact "
            f"request_id `{request_id}` for follow-up."
        ),
        (
            "Support should first confirm whether the current replay for "
            f"`{product_id}` / `{programming_language}` still reproduces the "
            "original problem."
        ),
        (
            "If replay no longer matches the original outcome, compare warnings, "
            "fallback reasons, and top citations to isolate freshness, coverage, "
            "or ranking drift."
        ),
    ]


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _derive_query_docs_outcome(
    *,
    confidence: float,
    fallback_reason: str | None,
    result_count: int,
    warnings: Sequence[str],
) -> str:
    normalized_warnings = {warning.strip().casefold() for warning in warnings}
    if result_count <= 0:
        return "no_results"
    if fallback_reason == "low_confidence_best_effort":
        return "low_confidence"
    if "low_confidence_best_effort" in normalized_warnings or confidence < 0.35:
        return "low_confidence"
    return "success"


def _derive_zero_result_reason(
    *,
    result_count: int,
    warnings: Sequence[str],
) -> str | None:
    if result_count > 0:
        return None
    normalized_warnings = {warning.strip().casefold() for warning in warnings}
    if "no_index_data" in normalized_warnings:
        return "no_index_data"
    if "product_scope_missing" in normalized_warnings:
        return "product_scope_missing"
    if "version_scope_missing" in normalized_warnings:
        return "version_scope_missing"
    if "translation_dependency_unavailable" in normalized_warnings:
        return "translation_dependency_unavailable"
    return "empty_after_ranking"


def _derive_fallback_reason(*, warnings: Sequence[str]) -> str | None:
    normalized_warnings = {warning.strip().casefold() for warning in warnings}
    if "low_confidence_best_effort" in normalized_warnings:
        return "low_confidence_best_effort"
    if "translation_dependency_unavailable" in normalized_warnings:
        return "translation_dependency_unavailable"
    if "abuse_guard_threshold_exceeded_observe_only" in normalized_warnings:
        return "abuse_guard_observe_only"
    return None


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    request_id = getattr(request.state, "request_id", None)
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": {},
                "request_id": request_id,
            }
        },
    )


def _detect_language_hint(query: str) -> str | None:
    lowered = query.casefold()
    # Order matters: compound languages must precede their simple constituents
    # to avoid e.g. "python-net" matching as "python" or "net".
    language_aliases = (
        ("python-net", ("python-net", "python.net", "pythonnet")),
        ("python-java", ("python-java", "python.java", "pythonjava")),
        ("nodejs-cpp", ("nodejs-cpp", "nodejscpp", "nodejs")),
        ("javascript-cpp", ("javascript-cpp", "javascriptcpp")),
        ("go-cpp", ("go-cpp", "gocpp")),
        ("androidjava", ("androidjava", "android-java")),
        ("net", (".net", "dotnet", "c#", "csharp")),
        ("java", ("java",)),
        ("python", ("python", "py ")),
        ("cpp", ("c++", "cpp")),
    )
    for canonical, aliases in language_aliases:
        if any(alias in lowered for alias in aliases):
            return canonical
    return None


def _normalize_product_token(text: str) -> str:
    """Collapse dots, hyphens, underscores, and whitespace into a single canonical form."""
    return re.sub(r"[\s.\-_]+", " ", text.casefold()).strip()


_PRODUCT_MATCH_FLOOR = 0.25


def _product_match_score(*, query: str, product_id: str, product_family: str) -> float:
    lowered = query.casefold()
    product_id_lowered = product_id.casefold()
    product_family_lowered = product_family.casefold()

    # --- Tier 1: literal product_id appears in query (e.g. "aspose.ocr" in "aspose.ocr java") ---
    if product_id_lowered in lowered:
        return 0.99

    # --- Tier 2: normalized exact match  -----------------------------------------------
    # Collapse separators so "aspose ocr" ≡ "aspose.ocr" ≡ "aspose-ocr".
    normalized_query = _normalize_product_token(lowered)
    normalized_product_id = _normalize_product_token(product_id_lowered)

    # Full normalised product_id found inside the normalised query → near-exact match.
    if normalized_product_id in normalized_query:
        return 0.97

    # --- Tier 3: all product_id parts present (order-insensitive) -----------------------
    product_parts = tuple(part for part in normalized_product_id.split() if part)
    query_parts = frozenset(part for part in normalized_query.split() if part)
    if product_parts and all(part in normalized_query for part in product_parts):
        return 0.85

    # --- Tier 3b: distinctive product segment present (product_id minus family) ---------
    # A real user types the bare product word — "ocr", "pdf", "words" — without
    # the vendor prefix. That is the *distinctive* segment of the product_id
    # (product_id parts minus the family parts). Matching it resolves the product
    # (bare tokens used to fall through to the 0.25 floor and then get
    # misrouted by an alphabetical tiebreak). Require a whole-token match so a
    # substring like "arc" in "barcode" does not spuriously match.
    family_parts = frozenset(
        part for part in _normalize_product_token(product_family_lowered).split() if part
    )
    distinctive_parts = tuple(part for part in product_parts if part not in family_parts)
    if distinctive_parts and all(part in query_parts for part in distinctive_parts):
        return 0.80

    # --- Tier 4: product family match (broad, low priority) -----------------------------
    if product_family_lowered in lowered:
        return 0.60

    return 0.25


def _resolve_retrieval_mode(plan: QueryPlan) -> str:
    if plan.intent == "symbol_lookup":
        return "symbol"
    if plan.intent == "release_notes":
        return "migration"
    return "task"


def _chunk_matches_doc_type_filter(
    *,
    chunk_record: StageDChunkRecord,
    requested_doc_types: Sequence[str],
    include_examples: bool,
) -> bool:
    if not include_examples and chunk_record.chunk_type == "api_example":
        return False
    if not requested_doc_types:
        return True

    normalized_doc_types = {doc_type.strip().casefold() for doc_type in requested_doc_types}
    if "api_reference" in normalized_doc_types and chunk_record.source_kind == "apiref":
        return True
    if "guide" in normalized_doc_types and chunk_record.source_kind == "docs":
        return True
    return False


_SIGNATURE_MODIFIERS = {
    "public",
    "private",
    "protected",
    "internal",
    "static",
    "virtual",
    "override",
    "abstract",
    "sealed",
    "async",
    "extern",
    "partial",
    "new",
}
_SYMBOL_TOKEN_RE = re.compile(r"^[A-Za-z_@][A-Za-z0-9_@]*$")
_REPLACED_SYMBOL_PATTERN = re.compile(
    r"(?P<old>[A-Za-z_][A-Za-z0-9_\.]+)\s+(?:has\s+been\s+)?(?:replaced|renamed)\s+"
    r"(?:by|to)\s+(?P<new>[A-Za-z_][A-Za-z0-9_\.]+)",
    flags=re.IGNORECASE,
)
_USE_INSTEAD_PATTERN = re.compile(
    r"use\s+(?P<new>[A-Za-z_][A-Za-z0-9_\.]+)\s+instead\s+of\s+"
    r"(?P<old>[A-Za-z_][A-Za-z0-9_\.]+)",
    flags=re.IGNORECASE,
)
_DEPRECATED_MIGRATION_PATTERN = re.compile(
    r"(?P<old>[A-Za-z_][A-Za-z0-9_\.]+)\s+(?:is|was)?\s*deprecated.*?"
    r"(?:migrate|switch|move)\s+to\s+(?P<new>[A-Za-z_][A-Za-z0-9_\.]+)",
    flags=re.IGNORECASE,
)
_REMOVED_SYMBOL_PATTERN = re.compile(
    r"(?P<old>[A-Za-z_][A-Za-z0-9_\.]+)\s+(?:is|was)?\s*removed",
    flags=re.IGNORECASE,
)


def _extract_signature_line(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        candidate = line.strip().rstrip(";")
        if not candidate:
            continue
        lowered = candidate.casefold()
        if "(" in candidate and ")" in candidate:
            return candidate
        if any(lowered.startswith(f"{modifier} ") for modifier in _SIGNATURE_MODIFIERS):
            return candidate
    normalized_fallback = fallback.strip()
    return normalized_fallback or "unknown"


def _parse_signature_contract(
    signature: str,
) -> tuple[list[SymbolParameterResponse], str]:
    cleaned = signature.strip().rstrip(";")
    if not cleaned or "(" not in cleaned or ")" not in cleaned:
        return ([], "unknown")
    try:
        prefix, suffix = cleaned.split("(", maxsplit=1)
        parameters_block, _ = suffix.split(")", maxsplit=1)
    except ValueError:
        return ([], "unknown")

    prefix_tokens = [token for token in prefix.strip().split() if token]
    without_modifiers = [
        token
        for token in prefix_tokens
        if token.casefold() not in _SIGNATURE_MODIFIERS
    ]
    if len(without_modifiers) < 2:
        return (_parse_signature_parameters(parameters_block), "unknown")
    return_type = without_modifiers[-2]
    if not return_type:
        return_type = "unknown"
    return (_parse_signature_parameters(parameters_block), return_type)


def _parse_signature_parameters(parameters_block: str) -> list[SymbolParameterResponse]:
    parameters: list[SymbolParameterResponse] = []
    for item in _split_signature_parameters(parameters_block):
        normalized = item.strip()
        if not normalized:
            continue
        if "=" in normalized:
            normalized = normalized.split("=", maxsplit=1)[0].strip()
        tokens = [token for token in normalized.split() if token]
        if not tokens:
            continue
        if len(tokens) == 1:
            parameter_type = "unknown"
            parameter_name = tokens[0].lstrip("@")
        else:
            parameter_type = " ".join(tokens[:-1])
            parameter_name = tokens[-1].lstrip("@")
        if not _SYMBOL_TOKEN_RE.fullmatch(parameter_name):
            parameter_name = tokens[-1]
        parameters.append(
            SymbolParameterResponse(
                name=parameter_name,
                type=parameter_type,
                description="Parameter parsed from API signature.",
            )
        )
    return parameters


def _split_signature_parameters(parameters_block: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth_angle = 0
    depth_round = 0
    for char in parameters_block:
        if char == "<":
            depth_angle += 1
        elif char == ">":
            depth_angle = max(0, depth_angle - 1)
        elif char == "(":
            depth_round += 1
        elif char == ")":
            depth_round = max(0, depth_round - 1)

        if char == "," and depth_angle == 0 and depth_round == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        items.append("".join(current))
    return items


def _build_signature_variants(
    *,
    ordered_matching: Sequence[StageDChunkRecord],
) -> list[SymbolSignatureVariantResponse]:
    variants: list[SymbolSignatureVariantResponse] = []
    seen: set[tuple[str, str, str]] = set()
    for record in ordered_matching:
        if not record.symbol_fqn:
            continue
        signature = _extract_signature_line(record.text, fallback=record.title)
        if not signature or signature == "unknown":
            continue
        key = (
            signature.casefold(),
            record.canonical_url,
            record.section_anchor,
        )
        if key in seen:
            continue
        seen.add(key)
        variants.append(
            SymbolSignatureVariantResponse(
                signature=signature,
                source_kind=record.source_kind,
                chunk_type=record.chunk_type,
                is_deprecated=record.is_deprecated,
                citation=SymbolCitationResponse(
                    canonical_url=record.canonical_url,
                    section_anchor=record.section_anchor,
                ),
            )
        )
        if len(variants) >= 8:
            break
    return variants


def _build_symbol_guardrails(
    *,
    symbol_fqn: str,
    signature_variants: Sequence[SymbolSignatureVariantResponse],
    deprecated: bool,
) -> list[str]:
    rules = [
        (
            f"Use only members/signatures present for `{symbol_fqn}` in "
            "`signature` and `signature_variants`."
        ),
        "Prefer `latest-stable` APIs and avoid unknown properties or methods.",
        "If a required member is missing, call `list_breaking_changes` before coding.",
    ]
    if deprecated:
        rules.append(
            "Symbol is marked deprecated in retrieved data; prefer non-deprecated alternatives."
        )
    if not signature_variants:
        rules.append(
            "No signature variants were found; keep usage minimal and verify against citations."
        )
    return rules


def _dedupe_citations(
    *,
    citations: Sequence[SymbolCitationResponse],
) -> list[SymbolCitationResponse]:
    deduped: list[SymbolCitationResponse] = []
    seen: set[tuple[str, str]] = set()
    for citation in citations:
        key = (citation.canonical_url, citation.section_anchor)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _extract_api_guardrails(*, excerpts: Sequence[str]) -> list[str]:
    extracted = _extract_release_note_hints(excerpts=excerpts)
    rules: list[str] = []
    seen: set[str] = set()
    for rule in [*extracted, *_default_api_guardrails()]:
        normalized = rule.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        rules.append(rule)
        if len(rules) >= 6:
            break
    return rules


def _extract_release_note_hints(*, excerpts: Sequence[str]) -> list[str]:
    hints: list[str] = []
    for excerpt in excerpts:
        for pattern in (
            _REPLACED_SYMBOL_PATTERN,
            _USE_INSTEAD_PATTERN,
            _DEPRECATED_MIGRATION_PATTERN,
        ):
            for match in pattern.finditer(excerpt):
                old_symbol = match.groupdict().get("old", "").strip()
                new_symbol = match.groupdict().get("new", "").strip()
                if not old_symbol or not new_symbol:
                    continue
                hints.append(
                    f"Prefer `{new_symbol}` instead of deprecated/legacy `{old_symbol}`."
                )
        for match in _REMOVED_SYMBOL_PATTERN.finditer(excerpt):
            removed_symbol = match.groupdict().get("old", "").strip()
            if not removed_symbol:
                continue
            hints.append(
                f"Avoid `{removed_symbol}` in new code: it is marked as removed."
            )
    return hints


def _default_api_guardrails() -> list[str]:
    return [
        "ONLY use classes, methods, and enum values that appear in the retrieved documentation.",
        "If a class or method is NOT in the retrieved results, call get_symbol_doc to verify it.",
        "Do NOT invent API members that were not returned by documentation tools.",
        "Use `get_symbol_doc` for exact signature and supported members before coding.",
        "Use `list_breaking_changes` when migrating between versions.",
    ]


def _normalize_doc_locale_value(doc_locale: str | None) -> str:
    if doc_locale is None:
        return "unknown"
    normalized = doc_locale.strip().casefold().replace("_", "-")
    if not normalized:
        return "unknown"
    locale_aliases = {
        "english": "en",
        "en-us": "en",
        "en-gb": "en",
        "unknown": "unknown",
        "und": "unknown",
        "none": "unknown",
        "n/a": "unknown",
        "na": "unknown",
    }
    aliased = locale_aliases.get(normalized)
    if aliased is not None:
        return aliased
    if len(normalized) == 2:
        return normalized
    if "-" in normalized:
        prefix = normalized.split("-", maxsplit=1)[0]
        if len(prefix) == 2:
            return prefix
    return normalized


def _symbol_record_preference_key(
    *,
    chunk_record: StageDChunkRecord,
    preferred_locale: str,
) -> tuple[int, int, str]:
    locale_value = _normalize_doc_locale_value(chunk_record.doc_locale)
    if locale_value == preferred_locale:
        locale_rank = 0
    elif locale_value == "unknown":
        locale_rank = 1
    else:
        locale_rank = 2
    source_kind_rank = 0 if chunk_record.source_kind == "apiref" else 1
    return (
        locale_rank,
        source_kind_rank,
        chunk_record.source_path,
    )


def _candidate_matches_doc_type_filter(
    *,
    source_kind: str,
    doc_type: str,
    requested_doc_types: Sequence[str],
    include_examples: bool,
) -> bool:
    if not include_examples and doc_type == "api_example":
        return False
    if not requested_doc_types:
        return True

    normalized_doc_types = {item.strip().casefold() for item in requested_doc_types}
    if "api_reference" in normalized_doc_types and source_kind == "apiref":
        return True
    if "guide" in normalized_doc_types and source_kind == "docs":
        return True
    return False


def _filter_retrieval_result(
    *,
    retrieval_result: HybridRetrievalResult,
    requested_doc_types: Sequence[str],
    include_examples: bool,
) -> HybridRetrievalResult:
    filtered_candidates = tuple(
        candidate
        for candidate in retrieval_result.candidates
        if _candidate_matches_doc_type_filter(
            source_kind=candidate.metadata.source_kind,
            doc_type=candidate.metadata.doc_type,
            requested_doc_types=requested_doc_types,
            include_examples=include_examples,
        )
    )
    return HybridRetrievalResult(
        query_fingerprint=retrieval_result.query_fingerprint,
        normalized_query=retrieval_result.normalized_query,
        candidates=filtered_candidates,
        dense_candidates_count=retrieval_result.dense_candidates_count,
        lexical_candidates_count=retrieval_result.lexical_candidates_count,
        fused_candidates_count=len(filtered_candidates),
        dense_weight=retrieval_result.dense_weight,
        lexical_weight=retrieval_result.lexical_weight,
    )



def _candidate_to_chunk_record(candidate: HybridCandidate) -> StageDChunkRecord:
    """Adapt a retrieval candidate to the record shape the builders expect.

    Only the fields those builders read are meaningful here; the rest carry
    faithful values from the candidate or benign defaults. `is_deprecated` is
    derived from the text because the retrieval payload does not carry the flag,
    and the breaking-changes diff uses it purely as a hint.
    """
    meta = candidate.metadata
    lowered = meta.text.casefold()
    return StageDChunkRecord(
        chunk_id=meta.chunk_id,
        repo_id=meta.repo_id,
        product_id=meta.product_id,
        product_family=meta.product_id,
        programming_language=meta.programming_language,
        version=meta.version,
        source_kind=meta.source_kind,
        doc_locale=meta.doc_locale,
        doc_type=meta.doc_type,
        symbol_fqn=meta.symbol_fqn,
        title=meta.title,
        section_path=(meta.title,),
        canonical_url=meta.canonical_url,
        section_anchor=meta.section_anchor,
        source_path=meta.canonical_url,
        source_revision=meta.source_revision,
        is_deprecated="deprecated" in lowered,
        has_code_example=bool(meta.executable_snippets),
        chunk_type=meta.doc_type,
        text=meta.text,
        tokens=len(meta.text.split()),
        checksum=meta.checksum,
    )

def _filter_release_feature_records(
    *,
    records: Sequence[StageDChunkRecord],
    requested_version: str | None,
) -> tuple[StageDChunkRecord, ...]:
    scoped_records = tuple(
        record
        for record in records
        if _is_release_feature_chunk(record)
        and _version_matches(record.version, requested_version)
    )
    if requested_version is not None:
        return scoped_records

    resolved_latest = _resolve_latest_version(records=scoped_records, requested_version=None)
    return tuple(
        record for record in scoped_records if _version_matches(record.version, resolved_latest)
    )


def _resolve_latest_version(
    *,
    records: Sequence[StageDChunkRecord],
    requested_version: str | None,
) -> str:
    if requested_version is not None:
        return requested_version
    versions = sorted(
        {record.version for record in records},
        key=_release_version_sort_key,
    )
    if not versions:
        return "latest"
    return versions[-1]


def _release_version_sort_key(version: str) -> tuple[int, int, int, int, str]:
    tokens = re.findall(r"\d+", version)
    numbers = [int(token) for token in tokens[:4]]
    while len(numbers) < 4:
        numbers.append(-1)
    return (numbers[0], numbers[1], numbers[2], numbers[3], version.casefold())


def _version_matches(candidate: str, requested: str | None) -> bool:
    if requested is None:
        return True
    normalized_candidate = normalize_version_hint(candidate)
    normalized_requested = normalize_version_hint(requested)
    if normalized_candidate is not None and normalized_requested is not None:
        return normalized_candidate == normalized_requested
    return candidate.casefold() == requested.casefold()


def _is_release_feature_chunk(record: StageDChunkRecord) -> bool:
    normalized_doc_type = record.doc_type.casefold()
    if normalized_doc_type in {"release_note", "release_notes", "migration_note"}:
        return True
    text = record.text.casefold()
    return any(
        keyword in text
        for keyword in (
            "what's new",
            "whats new",
            "new feature",
            "breaking change",
            "deprecated",
            "migrate",
            "replaced by",
            "use instead",
        )
    )


def _build_release_feature_items(
    *,
    records: Sequence[StageDChunkRecord],
    top_k: int,
) -> list[ReleaseFeatureItemResponse]:
    deduped: list[ReleaseFeatureItemResponse] = []
    seen: set[tuple[str, str, str]] = set()

    ordered_records = sorted(
        records,
        key=lambda record: (
            _release_version_sort_key(record.version),
            _release_feature_record_priority(record),
            record.canonical_url,
            record.section_anchor,
            record.chunk_id,
        ),
        reverse=True,
    )
    for record in ordered_records:
        hints = _extract_release_note_hints(excerpts=[record.text])
        candidates: list[tuple[str, str]] = []
        if hints:
            for hint in hints:
                candidates.append((_infer_release_feature_kind(hint), hint))
        else:
            candidates.append((_infer_release_feature_kind(record.text), _first_line(record)))

        for kind, summary in candidates:
            dedupe_key = (
                kind,
                summary.casefold(),
                f"{record.canonical_url}#{record.section_anchor}",
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(
                ReleaseFeatureItemResponse(
                    kind=kind,
                    summary=summary,
                    symbol_fqn=record.symbol_fqn,
                    version=record.version,
                    source_kind=record.source_kind,
                    citation=ReleaseFeatureCitationResponse(
                        canonical_url=record.canonical_url,
                        section_anchor=record.section_anchor,
                    ),
                )
            )
            if len(deduped) >= top_k:
                return sorted(deduped, key=_release_feature_item_sort_key)
    return sorted(deduped, key=_release_feature_item_sort_key)


def _infer_release_feature_kind(text: str) -> str:
    normalized = text.casefold()
    if "prefer `" in normalized and "instead of" in normalized:
        return "replacement"
    if "avoid `" in normalized or "removed" in normalized:
        return "removal"
    if "deprecated" in normalized:
        return "deprecation"
    if "breaking" in normalized or "migration" in normalized:
        return "breaking_change"
    return "feature"


def _release_feature_record_priority(record: StageDChunkRecord) -> int:
    normalized_doc_type = record.doc_type.casefold()
    if normalized_doc_type in {"release_note", "release_notes"}:
        return 0
    if normalized_doc_type == "migration_note":
        return 1
    if record.symbol_fqn:
        return 2
    return 3


def _release_feature_item_sort_key(
    item: ReleaseFeatureItemResponse,
) -> tuple[int, tuple[int, int, int, int, str], str]:
    kind_priority = {
        "replacement": 0,
        "deprecation": 1,
        "removal": 2,
        "breaking_change": 3,
        "feature": 4,
    }
    return (
        kind_priority.get(item.kind, 99),
        _release_version_sort_key(item.version),
        item.summary.casefold(),
    )


def _is_breaking_change_chunk(chunk_record: StageDChunkRecord) -> bool:
    text = chunk_record.text.casefold()
    return (
        "breaking" in text
        or "deprecated" in text
        or "migration" in text
        or chunk_record.doc_type in {"release_note", "release_notes", "migration_note"}
    )


def _build_breaking_changes_diff_items(
    *,
    from_records: Sequence[StageDChunkRecord],
    to_records: Sequence[StageDChunkRecord],
    from_version: str,
    to_version: str,
) -> list[BreakingChangeItemResponse]:
    from_by_symbol = _index_symbol_records(from_records)
    to_by_symbol = _index_symbol_records(to_records)

    items: list[BreakingChangeItemResponse] = []

    for symbol_key in sorted(from_by_symbol):
        from_record = from_by_symbol[symbol_key]
        to_record = to_by_symbol.get(symbol_key)
        if to_record is None:
            items.append(
                BreakingChangeItemResponse(
                    type="symbol_removed",
                    symbol_fqn=from_record.symbol_fqn,
                    from_version=from_version,
                    to_version=to_version,
                    description=(
                        f"Symbol removed between {from_version} and {to_version}: "
                        f"{_first_line(from_record)}"
                    ),
                    migration_hint="Search release notes for replacement symbol.",
                    citation=BreakingChangeCitationResponse(
                        canonical_url=from_record.canonical_url,
                        section_anchor=from_record.section_anchor,
                    ),
                )
            )
            continue

        if from_record.checksum != to_record.checksum:
            items.append(
                BreakingChangeItemResponse(
                    type="symbol_changed",
                    symbol_fqn=to_record.symbol_fqn or from_record.symbol_fqn,
                    from_version=from_version,
                    to_version=to_version,
                    description=(
                        f"Symbol changed between {from_version} and {to_version}: "
                        f"{_first_line(from_record)} -> {_first_line(to_record)}"
                    ),
                    migration_hint="Review updated signature and migration guidance.",
                    citation=BreakingChangeCitationResponse(
                        canonical_url=to_record.canonical_url,
                        section_anchor=to_record.section_anchor,
                    ),
                )
            )

    for symbol_key in sorted(to_by_symbol):
        to_record = to_by_symbol[symbol_key]
        previous_record = from_by_symbol.get(symbol_key)
        if not to_record.is_deprecated:
            continue
        if previous_record is not None and previous_record.is_deprecated:
            continue
        items.append(
            BreakingChangeItemResponse(
                type="symbol_deprecated",
                symbol_fqn=to_record.symbol_fqn,
                from_version=from_version,
                to_version=to_version,
                description=(
                    f"Symbol deprecated in {to_version}: "
                    f"{to_record.symbol_fqn or _first_line(to_record)}"
                ),
                migration_hint="Migrate to replacement API before removal.",
                citation=BreakingChangeCitationResponse(
                    canonical_url=to_record.canonical_url,
                    section_anchor=to_record.section_anchor,
                ),
            )
        )

    note_records = sorted(
        (record for record in to_records if _is_breaking_change_chunk(record)),
        key=lambda record: (
            record.canonical_url,
            record.section_anchor,
            record.chunk_id,
        ),
    )
    for record in note_records:
        items.append(
            BreakingChangeItemResponse(
                type="breaking_change_note",
                symbol_fqn=record.symbol_fqn,
                from_version=from_version,
                to_version=to_version,
                description=record.text[:280].strip(),
                migration_hint="Review release notes and migration guidance.",
                citation=BreakingChangeCitationResponse(
                    canonical_url=record.canonical_url,
                    section_anchor=record.section_anchor,
                ),
            )
        )

    deduplicated = _deduplicate_breaking_change_items(items)
    return sorted(deduplicated, key=_breaking_change_item_sort_key)


def _index_symbol_records(
    records: Sequence[StageDChunkRecord],
) -> dict[str, StageDChunkRecord]:
    indexed: dict[str, StageDChunkRecord] = {}
    for record in records:
        symbol_fqn = _normalized_symbol_key(record.symbol_fqn)
        if symbol_fqn is None:
            continue
        current = indexed.get(symbol_fqn)
        if current is None or _symbol_record_sort_key(record) < _symbol_record_sort_key(current):
            indexed[symbol_fqn] = record
    return indexed


def _normalized_symbol_key(symbol_fqn: str | None) -> str | None:
    if symbol_fqn is None:
        return None
    normalized = symbol_fqn.strip().casefold()
    if not normalized:
        return None
    return normalized


def _symbol_record_sort_key(record: StageDChunkRecord) -> tuple[int, str, str, str]:
    return (
        0 if record.chunk_type == "api_signature" else 1,
        record.canonical_url,
        record.section_anchor,
        record.chunk_id,
    )


def _first_line(record: StageDChunkRecord) -> str:
    lines = [line.strip() for line in record.text.splitlines() if line.strip()]
    if lines:
        return lines[0][:140]
    return record.title[:140]


def _deduplicate_breaking_change_items(
    items: Sequence[BreakingChangeItemResponse],
) -> list[BreakingChangeItemResponse]:
    deduplicated: list[BreakingChangeItemResponse] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for item in items:
        dedupe_key = (
            item.type,
            item.symbol_fqn,
            item.citation.canonical_url,
            item.citation.section_anchor,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduplicated.append(item)
    return deduplicated


def _breaking_change_item_sort_key(item: BreakingChangeItemResponse) -> tuple[int, str, str, str]:
    type_priority = {
        "symbol_removed": 0,
        "symbol_changed": 1,
        "symbol_deprecated": 2,
        "breaking_change_note": 3,
    }
    return (
        type_priority.get(item.type, 99),
        (item.symbol_fqn or "").casefold(),
        item.citation.canonical_url,
        item.citation.section_anchor,
    )


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _resolve_version_resolution(
    *,
    plan: QueryPlan,
    candidates: Sequence[HybridCandidate],
) -> _VersionResolution:
    available_versions = tuple(
        dict.fromkeys(
            normalize_version_hint(candidate.metadata.version)
            or candidate.metadata.version.casefold()
            for candidate in candidates
            if candidate.metadata.version.strip()
        )
    )
    resolved_version = (
        available_versions[0]
        if available_versions
        else plan.filters.preferred_version
    )
    preferred_version = plan.filters.preferred_version
    fallback_reason: str | None = None
    fallback_applied = False

    if (
        not plan.filters.strict_version
        and preferred_version is not None
        and resolved_version is not None
        and preferred_version not in available_versions
    ):
        fallback_applied = True
        fallback_reason = "version_fallback_nearest_available"
    elif (
        not plan.filters.strict_version
        and plan.prefers_latest_stable
        and resolved_version is not None
        and available_versions
    ):
        latest_available = max(available_versions, key=_release_version_sort_key)
        if resolved_version != latest_available:
            fallback_applied = True
            fallback_reason = "version_fallback_latest_stable"

    return _VersionResolution(
        requested_version=plan.debug.filter_debug.requested_version,
        preferred_version=preferred_version,
        resolved_version=resolved_version,
        available_versions=available_versions,
        prefers_latest_stable=plan.prefers_latest_stable,
        # Report whether a version predicate was actually applied, not whether the
        # caller asked for one. Built from the raw request flag, this returned
        # `true` for a request carrying no version at all — and because the MCP
        # gateway rewrites that flag, the two transports answered opposite values
        # for identical calls. `filter_debug` records what the resolver
        # really did, and is what the debug payload already reports.
        strict_version_enforced=plan.debug.filter_debug.strict_version_enforced,
        fallback_applied=fallback_applied,
        fallback_reason=fallback_reason,
    )


def _to_debug_payload(plan: QueryPlan) -> dict[str, object]:
    return {
        "raw_query": plan.debug.raw_query,
        "normalized_query": plan.debug.normalized_query,
        "removed_noise_prefixes": list(plan.debug.removed_noise_prefixes),
        "symbol_candidates": list(plan.debug.symbol_candidates),
        "intent": plan.debug.intent,
        "intent_subtype": plan.debug.intent_subtype,
        "intent_reason_codes": list(plan.debug.intent_reason_codes),
        "detected_version_tokens": list(plan.debug.detected_version_tokens),
        "prefers_latest_stable": plan.debug.prefers_latest_stable,
        "filters": {
            "requested_product_id": plan.debug.filter_debug.requested_product_id,
            "requested_programming_language": (
                plan.debug.filter_debug.requested_programming_language
            ),
            "requested_version": plan.debug.filter_debug.requested_version,
            "requested_doc_locale": plan.debug.filter_debug.requested_doc_locale,
            "effective_product_id": plan.debug.filter_debug.effective_product_id,
            "effective_programming_language": (
                plan.debug.filter_debug.effective_programming_language
            ),
            "preferred_version": plan.debug.filter_debug.preferred_version,
            "strict_version_value": plan.debug.filter_debug.strict_version_value,
            "strict_version_enforced": plan.debug.filter_debug.strict_version_enforced,
            "locale_routing_order": list(plan.debug.filter_debug.locale_routing_order),
            "locale_fallback_to_en_enabled": (
                plan.debug.filter_debug.locale_fallback_to_en_enabled
            ),
        },
    }


def _build_explainability(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
    version_resolution: _VersionResolution,
    packed_context: object,
    reranker_backend: str,
) -> _ExplainabilityPayload:
    why_top_result: list[str] = []
    if candidates:
        top_candidate = candidates[0]
        if plan.symbol_candidates and top_candidate.metadata.symbol_fqn:
            top_symbol = top_candidate.metadata.symbol_fqn.casefold()
            if any(top_symbol == symbol.casefold() for symbol in plan.symbol_candidates):
                why_top_result.append("exact_symbol_match")
        if top_candidate.metadata.source_kind == "docs" and plan.intent == "how_to":
            why_top_result.append("guide_priority_for_how_to")
        if top_candidate.metadata.source_kind == "apiref" and plan.intent == "symbol_lookup":
            why_top_result.append("api_reference_priority_for_symbol_lookup")
        if top_candidate.metadata.doc_type.casefold() in {
            "release_note",
            "release_notes",
            "migration_note",
        }:
            why_top_result.append("release_note_candidate")
        if top_candidate.metadata.version:
            why_top_result.append(f"top_candidate_version={top_candidate.metadata.version}")
    else:
        why_top_result.append("no_candidates")

    why_version = None
    if version_resolution.fallback_applied and version_resolution.fallback_reason is not None:
        why_version = version_resolution.fallback_reason
    elif version_resolution.resolved_version is not None:
        why_version = f"resolved_version={version_resolution.resolved_version}"

    freshness_source = "version_heuristic"
    quality = getattr(packed_context, "quality", None)
    if quality is not None and getattr(quality, "freshness_source", None):
        freshness_source = str(quality.freshness_source)

    return {
        "reranker_backend": reranker_backend,
        "intent_subtype": plan.intent_subtype,
        "freshness_source": freshness_source,
        "why_top_result": why_top_result,
        "why_version": why_version,
        "why_fallback": getattr(packed_context, "fallback_reason", None),
    }


# ---------------------------------------------------------------------------
# Qdrant direct-symbol-lookup helpers
# ---------------------------------------------------------------------------


def _qdrant_request_json(
    *,
    url: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> tuple[int, object]:
    """Send a JSON POST to Qdrant and return ``(status_code, parsed_body)``."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return response.status, _qdrant_decode_json(raw)
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, _qdrant_decode_json(raw)
    except urllib_error.URLError as exc:
        msg = f"Qdrant request failed for {url}: {exc.reason}"
        raise RuntimeError(msg) from exc


def _qdrant_decode_json(raw_body: str) -> object:
    if not raw_body.strip():
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body


def _qdrant_points_to_chunk_records(
    body: object,
) -> tuple[StageDChunkRecord, ...]:
    """Convert a Qdrant scroll response body into ``StageDChunkRecord`` tuples."""
    if not isinstance(body, dict):
        return ()
    result = body.get("result")
    if not isinstance(result, dict):
        return ()
    points = result.get("points")
    if not isinstance(points, list):
        return ()

    records: list[StageDChunkRecord] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        p = point.get("payload")
        if not isinstance(p, dict):
            continue
        records.append(
            StageDChunkRecord(
                chunk_id=_qdrant_str(p.get("chunk_id"), ""),
                repo_id=_qdrant_str(p.get("repo_id"), ""),
                product_id=_qdrant_str(p.get("product_id"), ""),
                product_family=_qdrant_str(p.get("product_family"), ""),
                programming_language=_qdrant_str(p.get("programming_language"), ""),
                version=_qdrant_str(p.get("version"), ""),
                source_kind=_qdrant_str(p.get("source_kind"), ""),
                doc_locale=_qdrant_str(p.get("doc_locale"), "en"),
                doc_type=_qdrant_str(p.get("doc_type"), ""),
                symbol_fqn=_qdrant_nullable_str(p.get("symbol_fqn")),
                title=_qdrant_str(p.get("title"), ""),
                section_path=tuple(
                    str(s) for s in p.get("section_path", ()) if isinstance(s, str)
                )
                or ("root",),
                canonical_url=_qdrant_str(p.get("canonical_url"), ""),
                section_anchor=_qdrant_str(p.get("section_anchor"), ""),
                source_path=_qdrant_str(p.get("source_path"), ""),
                source_revision=_qdrant_str(p.get("source_revision"), ""),
                is_deprecated=bool(p.get("is_deprecated", False)),
                has_code_example=bool(p.get("has_code_example", False)),
                chunk_type=_qdrant_str(p.get("chunk_type"), ""),
                text=_qdrant_str(p.get("text"), ""),
                tokens=int(p.get("tokens", 0)) if p.get("tokens") is not None else 0,
                checksum=_qdrant_str(p.get("checksum"), ""),
            )
        )
    return tuple(records)


def _qdrant_str(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    s = str(value)
    return s if s else fallback


def _qdrant_nullable_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if s else None
