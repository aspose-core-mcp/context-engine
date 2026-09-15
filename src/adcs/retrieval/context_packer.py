"""Context packing and confidence scoring for retrieval results."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from adcs.retrieval.filter_resolver import normalize_version_hint
from adcs.retrieval.models import QueryPlan
from adcs.retrieval.release_catalog import ReleaseCatalog
from adcs.retrieval.retrieval_models import HybridCandidate, HybridRetrievalResult

_LOW_CONFIDENCE_WARNING = "LOW_CONFIDENCE"
# Emitted when the token budget dropped candidates the ranking would have kept.
# Silent truncation would look identical to "the corpus had nothing more".
_CONTEXT_TRUNCATED_WARNING = "CONTEXT_TOKEN_BUDGET_TRUNCATED"

# Total context tokens: default 3500, hard max 12000.
_MAX_TOTAL_TOKENS = 12000
_MIN_TOTAL_TOKENS = 256
# Characters per token. A deliberate approximation: the packer must not depend on
# a tokenizer for the embedding model in use, and for English technical prose ~4
# is the standard rule of thumb. Being approximate is fine here — the budget is a
# guard against unbounded growth, not an exact accounting.
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class ContextCitation:
    """Citation payload for one packed retrieval item."""

    title: str
    canonical_url: str
    section_anchor: str
    source_revision: str
    score: float


@dataclass(frozen=True, slots=True)
class PackedContextItem:
    """One packed context item with excerpt and citation metadata."""

    candidate_id: str
    excerpt: str
    citation: ContextCitation
    snippets: tuple[PackedExecutableSnippet, ...] = ()


@dataclass(frozen=True, slots=True)
class PackedExecutableSnippet:
    """Snippet payload exposed in packed retrieval context."""

    snippet_id: str
    language: str
    code: str
    parent_canonical_url: str
    parent_section_anchor: str
    parent_symbol_fqn: str | None = None


@dataclass(frozen=True, slots=True)
class ContextPackResult:
    """Final packed context payload for downstream API/MCP response."""

    query_fingerprint: str
    normalized_query: str
    confidence: float
    confidence_level: str
    warnings: tuple[str, ...]
    fallback_reason: str | None
    clarification_questions: tuple[str, ...]
    quality: RetrievalQualitySummary
    items: tuple[PackedContextItem, ...]


@dataclass(frozen=True, slots=True)
class RetrievalQualitySummary:
    """Deterministic retrieval quality breakdown for one response."""

    overall_score: float
    coverage_score: float
    freshness_score: float
    freshness_source: str
    citation_density_score: float
    symbol_match_score: float
    intent: str
    intent_subtype: str | None
    completeness_status: str
    completeness_missing_signals: tuple[str, ...]


class ContextPacker:
    """Build top-k citation-ready context with confidence metadata."""

    def __init__(
        self,
        *,
        default_top_k: int = 8,
        excerpt_limit_chars: int = 3000,
        max_total_tokens: int = 3500,
        release_catalog: ReleaseCatalog | None = None,
    ) -> None:
        if default_top_k < 1:
            msg = "default_top_k must be >= 1."
            raise ValueError(msg)
        if excerpt_limit_chars < 64:
            msg = "excerpt_limit_chars must be >= 64."
            raise ValueError(msg)
        if max_total_tokens < _MIN_TOTAL_TOKENS:
            msg = f"max_total_tokens must be >= {_MIN_TOTAL_TOKENS}."
            raise ValueError(msg)

        self._default_top_k = default_top_k
        self._excerpt_limit_chars = excerpt_limit_chars
        # Total context tokens: default 3500, hard max 12000. The per-excerpt char
        # limit alone does not bound the total: the default top_k of 8 can produce
        # roughly 6k tokens, and top_k=20 would exceed the documented maximum.
        # Values above the cap are clamped rather than rejected — the caller is an
        # operator setting, not a request.
        self._max_total_tokens = min(max_total_tokens, _MAX_TOTAL_TOKENS)
        self._release_catalog = release_catalog

    def pack(
        self,
        *,
        plan: QueryPlan,
        retrieval_result: HybridRetrievalResult,
        top_k: int | None = None,
        max_total_tokens: int | None = None,
    ) -> ContextPackResult:
        """Pack reranked candidates into citation-ready top-k context.

        `max_total_tokens` overrides the instance default for one call, so a
        per-product admin setting reaches the packer without a packer per product.
        """
        effective_top_k = top_k or self._default_top_k
        if effective_top_k < 1:
            msg = "top_k must be >= 1."
            raise ValueError(msg)

        selected_candidates = retrieval_result.candidates[:effective_top_k]
        packed_items, truncated = _apply_token_budget(
            items=tuple(
                _to_packed_item(
                    candidate=candidate,
                    excerpt_limit_chars=self._excerpt_limit_chars,
                )
                for candidate in selected_candidates
            ),
            max_total_tokens=(
                min(max(max_total_tokens, _MIN_TOTAL_TOKENS), _MAX_TOTAL_TOKENS)
                if max_total_tokens is not None
                else self._max_total_tokens
            ),
        )
        # Confidence and quality are computed over the candidates that were
        # actually returned, so a truncated answer does not claim the confidence
        # of a fuller one.
        selected_candidates = selected_candidates[: len(packed_items)]

        confidence, confidence_level = _compute_confidence(
            plan=plan,
            candidates=selected_candidates,
        )
        is_low_confidence = confidence_level == "low"

        return ContextPackResult(
            query_fingerprint=plan.query_fingerprint,
            normalized_query=plan.normalized_query,
            confidence=confidence,
            confidence_level=confidence_level,
            warnings=tuple(
                warning
                for warning, applies in (
                    (_LOW_CONFIDENCE_WARNING, is_low_confidence),
                    (_CONTEXT_TRUNCATED_WARNING, truncated),
                )
                if applies
            ),
            fallback_reason=_fallback_reason(
                candidates=selected_candidates,
                level=confidence_level,
            ),
            clarification_questions=_clarification_questions(plan=plan, level=confidence_level),
            quality=_compute_quality(
                plan=plan,
                candidates=selected_candidates,
                requested_top_k=effective_top_k,
                confidence=confidence,
                release_catalog=self._release_catalog,
            ),
            items=packed_items,
        )


def _apply_token_budget(
    *,
    items: tuple[PackedContextItem, ...],
    max_total_tokens: int,
) -> tuple[tuple[PackedContextItem, ...], bool]:
    """Keep the highest-ranked items that fit the total token budget.

    Returns the surviving items and whether anything was dropped. The first item
    is always kept, with its excerpt shortened if it alone exceeds the budget:
    returning nothing because one chunk was oversized would turn a large answer
    into an empty one, which is worse than a trimmed answer.
    """
    if not items:
        return items, False

    kept: list[PackedContextItem] = []
    spent = 0
    for index, item in enumerate(items):
        cost = _estimate_tokens(item.excerpt)
        if index == 0 and cost > max_total_tokens:
            budget_chars = max_total_tokens * _CHARS_PER_TOKEN
            kept.append(replace(item, excerpt=item.excerpt[:budget_chars].rstrip() + "..."))
            return tuple(kept), len(items) > 1
        if spent + cost > max_total_tokens:
            return tuple(kept), True
        kept.append(item)
        spent += cost
    return tuple(kept), False


def _to_packed_item(*, candidate: HybridCandidate, excerpt_limit_chars: int) -> PackedContextItem:
    excerpt = candidate.metadata.text
    if len(excerpt) > excerpt_limit_chars:
        excerpt = excerpt[:excerpt_limit_chars].rstrip() + "..."
    return PackedContextItem(
        candidate_id=candidate.metadata.candidate_id,
        excerpt=excerpt,
        citation=ContextCitation(
            title=candidate.metadata.title,
            canonical_url=candidate.metadata.canonical_url,
            section_anchor=candidate.metadata.section_anchor,
            source_revision=candidate.metadata.source_revision,
            score=candidate.rerank_score,
        ),
        snippets=tuple(
            PackedExecutableSnippet(
                snippet_id=snippet.snippet_id,
                language=snippet.language,
                code=snippet.code,
                parent_canonical_url=snippet.parent_canonical_url,
                parent_section_anchor=snippet.parent_section_anchor,
                parent_symbol_fqn=snippet.parent_symbol_fqn,
            )
            for snippet in candidate.metadata.executable_snippets
        ),
    )


def _compute_confidence(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
) -> tuple[float, str]:
    if not candidates:
        return 0.0, "low"

    top_candidate = candidates[0]
    second_score = candidates[1].rerank_score if len(candidates) > 1 else 0.0
    score_margin = max(top_candidate.rerank_score - second_score, 0.0)

    lane_agreement_count = sum(
        1
        for candidate in candidates
        if candidate.dense_normalized_score > 0 and candidate.lexical_normalized_score > 0
    )
    lane_agreement_ratio = lane_agreement_count / len(candidates)

    has_symbol_exact_match = _has_symbol_exact_match(plan=plan, candidate=top_candidate)
    confidence = (
        0.40 * _clamp(top_candidate.rerank_score)
        + 0.35 * _clamp(score_margin)
        + 0.15 * lane_agreement_ratio
        + 0.10 * (1.0 if has_symbol_exact_match else 0.0)
    )
    confidence = _clamp(confidence)

    if confidence >= 0.75:
        return confidence, "high"
    if confidence >= 0.45:
        return confidence, "medium"
    return confidence, "low"


def _has_symbol_exact_match(*, plan: QueryPlan, candidate: HybridCandidate) -> bool:
    if not plan.symbol_candidates or not candidate.metadata.symbol_fqn:
        return False
    symbol_fqn = candidate.metadata.symbol_fqn.casefold()
    return any(symbol_fqn == symbol.casefold() for symbol in plan.symbol_candidates)


def _fallback_reason(*, candidates: tuple[HybridCandidate, ...], level: str) -> str | None:
    if level != "low":
        return None
    if not candidates:
        return "no_candidates"
    return "low_confidence_best_effort"


def _clarification_questions(*, plan: QueryPlan, level: str) -> tuple[str, ...]:
    if level != "low":
        return ()

    language_hint = plan.filters.programming_language or "SDK language"
    version_hint = plan.filters.preferred_version or "target version"
    return (
        f"Which {language_hint} binding are you using?",
        f"Can you specify the exact {version_hint} you target?",
        "Do you need API reference details or a task-oriented guide?",
    )


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _compute_quality(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
    requested_top_k: int,
    confidence: float,
    release_catalog: ReleaseCatalog | None,
) -> RetrievalQualitySummary:
    required_signals = _required_signals_for_intent(
        intent=plan.intent,
        intent_subtype=plan.intent_subtype,
    )
    present_signals = _detect_present_signals(plan=plan, candidates=candidates)
    completeness_missing_signals = tuple(
        signal for signal in required_signals if signal not in present_signals
    )
    completeness_status = _completeness_status(
        required_signals=required_signals,
        missing_signals=completeness_missing_signals,
    )

    coverage_score = _coverage_score(
        candidates=candidates,
        requested_top_k=requested_top_k,
        required_signals=required_signals,
        missing_signals=completeness_missing_signals,
    )
    freshness_score, freshness_source = _freshness_score(
        plan=plan,
        candidates=candidates,
        release_catalog=release_catalog,
    )
    citation_density_score = _citation_density_score(candidates=candidates)
    symbol_match_score = _symbol_match_score(plan=plan, candidates=candidates)
    overall_score = _overall_quality_score(
        coverage_score=coverage_score,
        freshness_score=freshness_score,
        citation_density_score=citation_density_score,
        symbol_match_score=symbol_match_score,
        completeness_status=completeness_status,
        confidence=confidence,
    )
    return RetrievalQualitySummary(
        overall_score=overall_score,
        coverage_score=coverage_score,
        freshness_score=freshness_score,
        freshness_source=freshness_source,
        citation_density_score=citation_density_score,
        symbol_match_score=symbol_match_score,
        intent=plan.intent,
        intent_subtype=plan.intent_subtype,
        completeness_status=completeness_status,
        completeness_missing_signals=completeness_missing_signals,
    )


def _required_signals_for_intent(
    *, intent: str, intent_subtype: str | None
) -> tuple[str, ...]:
    if intent == "symbol_lookup":
        return ("citations", "api_reference", "symbol_match")
    if intent == "how_to":
        if intent_subtype == "installation":
            return ("citations", "guide_or_task", "installation_step", "example_or_usage")
        if intent_subtype == "configuration":
            return ("citations", "guide_or_task", "configuration_signal")
        return ("citations", "guide_or_task", "api_reference", "example_or_usage")
    if intent == "troubleshooting":
        if intent_subtype == "runtime_failure":
            return ("citations", "guide_or_task", "api_reference", "mitigation_or_fix")
        if intent_subtype == "quality_issue":
            return ("citations", "guide_or_task", "mitigation_or_fix")
        return ("citations", "guide_or_task", "api_reference")
    if intent == "release_notes":
        if intent_subtype in {"migration", "breaking_change"}:
            return ("citations", "release_note", "version_scope", "mitigation_or_fix")
        return ("citations", "release_note", "version_scope")
    return ("citations",)


def _detect_present_signals(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
) -> set[str]:
    present: set[str] = set()
    if not candidates:
        return present

    if any(_has_citation(candidate) for candidate in candidates):
        present.add("citations")
    if any(_is_api_reference_candidate(candidate) for candidate in candidates):
        present.add("api_reference")
    if any(_is_guide_candidate(candidate) for candidate in candidates):
        present.add("guide_or_task")
    if any(_has_example_signal(candidate) for candidate in candidates):
        present.add("example_or_usage")
    if any(_has_installation_signal(candidate) for candidate in candidates):
        present.add("installation_step")
    if any(_has_configuration_signal(candidate) for candidate in candidates):
        present.add("configuration_signal")
    if any(_has_mitigation_signal(candidate) for candidate in candidates):
        present.add("mitigation_or_fix")
    if any(_has_version_scope_signal(candidate) for candidate in candidates):
        present.add("version_scope")
    if any(_is_release_candidate(candidate) for candidate in candidates):
        present.add("release_note")
    if _symbol_match_score(plan=plan, candidates=candidates) >= 0.85:
        present.add("symbol_match")
    return present


def _completeness_status(
    *,
    required_signals: tuple[str, ...],
    missing_signals: tuple[str, ...],
) -> str:
    if not required_signals:
        return "complete"
    covered_count = len(required_signals) - len(missing_signals)
    if covered_count == len(required_signals):
        return "complete"
    if covered_count == 0:
        return "insufficient"
    coverage_ratio = covered_count / len(required_signals)
    if coverage_ratio >= 0.5:
        return "partial"
    return "insufficient"


def _coverage_score(
    *,
    candidates: tuple[HybridCandidate, ...],
    requested_top_k: int,
    required_signals: tuple[str, ...],
    missing_signals: tuple[str, ...],
) -> float:
    if not candidates:
        return 0.0
    fill_ratio = min(len(candidates) / max(requested_top_k, 1), 1.0)
    required_ratio = (
        (len(required_signals) - len(missing_signals)) / len(required_signals)
        if required_signals
        else fill_ratio
    )
    source_kind_count = len({candidate.metadata.source_kind for candidate in candidates})
    source_diversity = min(source_kind_count / 2.0, 1.0)
    return _clamp((0.45 * fill_ratio) + (0.35 * required_ratio) + (0.20 * source_diversity))


def _freshness_score(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
    release_catalog: ReleaseCatalog | None,
) -> tuple[float, str]:
    if not candidates:
        return 0.0, "none"

    source_revision_ratio = (
        sum(1 for candidate in candidates if candidate.metadata.source_revision.strip())
        / len(candidates)
    )
    if release_catalog is not None and release_catalog.has_entries():
        catalog_score = _freshness_score_from_release_catalog(
            plan=plan,
            candidates=candidates,
            source_revision_ratio=source_revision_ratio,
            release_catalog=release_catalog,
        )
        if catalog_score is not None:
            return catalog_score, "release_catalog"

    preferred_version = normalize_version_hint(plan.filters.preferred_version)
    normalized_versions = [
        normalize_version_hint(candidate.metadata.version) or candidate.metadata.version.casefold()
        for candidate in candidates
        if candidate.metadata.version.strip()
    ]
    unique_versions = {version for version in normalized_versions if version}
    release_versions = tuple(
        version for version in normalized_versions if version != "latest-stable"
    )

    if preferred_version is not None:
        version_ratio = (
            sum(1 for version in normalized_versions if version == preferred_version)
            / len(normalized_versions)
            if normalized_versions
            else 0.0
        )
        mixed_version_penalty = 0.15 if len(unique_versions) > 1 else 0.0
        return _clamp(
            (0.75 * version_ratio)
            + (0.25 * source_revision_ratio)
            - mixed_version_penalty
        ), "version_heuristic"

    if plan.prefers_latest_stable or plan.intent == "release_notes":
        latest_version = _resolve_latest_release_version(release_versions)
        if latest_version is None:
            latest_ratio = 1.0 if normalized_versions else 0.0
        else:
            latest_ratio = (
                sum(1 for version in release_versions if version == latest_version)
                / len(release_versions)
                if release_versions
                else 0.0
            )
        mixed_version_penalty = 0.10 if len(unique_versions) > 1 and latest_ratio < 0.8 else 0.0
        return _clamp(
            (0.70 * latest_ratio)
            + (0.30 * source_revision_ratio)
            - mixed_version_penalty
        ), "version_heuristic"

    if not unique_versions:
        version_score = 0.4
    elif len(unique_versions) == 1:
        version_score = 1.0
    elif len(unique_versions) == 2:
        version_score = 0.75
    else:
        version_score = 0.55
    return _clamp((0.70 * version_score) + (0.30 * source_revision_ratio)), "version_heuristic"


def _freshness_score_from_release_catalog(
    *,
    plan: QueryPlan,
    candidates: tuple[HybridCandidate, ...],
    source_revision_ratio: float,
    release_catalog: ReleaseCatalog,
) -> float | None:
    release_entries = [
        release_catalog.resolve(
            product_id=candidate.metadata.product_id,
            programming_language=candidate.metadata.programming_language,
            version=candidate.metadata.version,
        )
        for candidate in candidates
    ]
    resolved_entries = [entry for entry in release_entries if entry is not None]
    if not resolved_entries:
        return None

    latest_entry = max(
        resolved_entries,
        key=lambda entry: (entry.published_at, entry.version),
    )
    if plan.filters.preferred_version is not None:
        preferred_version = normalize_version_hint(plan.filters.preferred_version)
        version_ratio = (
            sum(
                1
                for entry in resolved_entries
                if (normalize_version_hint(entry.version) or entry.version.casefold())
                == preferred_version
            )
            / len(resolved_entries)
        )
        return _clamp((0.75 * version_ratio) + (0.25 * source_revision_ratio))

    freshness_hits = 0.0
    for entry in resolved_entries:
        age_delta_days = max(
            int((latest_entry.published_at - entry.published_at).total_seconds() // 86400),
            0,
        )
        if age_delta_days <= 0:
            freshness_hits += 1.0
        elif age_delta_days <= 45:
            freshness_hits += 0.75
        elif age_delta_days <= 120:
            freshness_hits += 0.45
        else:
            freshness_hits += 0.20

    freshness_ratio = freshness_hits / len(resolved_entries)
    mixed_version_penalty = 0.10 if len({entry.version for entry in resolved_entries}) > 1 else 0.0
    return _clamp(
        (0.70 * freshness_ratio)
        + (0.30 * source_revision_ratio)
        - mixed_version_penalty
    )


def _citation_density_score(*, candidates: tuple[HybridCandidate, ...]) -> float:
    if not candidates:
        return 0.0
    citation_ready_ratio = (
        sum(1 for candidate in candidates if _has_citation(candidate)) / len(candidates)
    )
    snippet_ratio = (
        sum(1 for candidate in candidates if candidate.metadata.executable_snippets)
        / len(candidates)
    )
    return _clamp((0.80 * citation_ready_ratio) + (0.20 * snippet_ratio))


def _symbol_match_score(*, plan: QueryPlan, candidates: tuple[HybridCandidate, ...]) -> float:
    if not candidates:
        return 0.0
    if not plan.symbol_candidates:
        return 1.0

    top_candidate = candidates[0]
    if _has_symbol_exact_match(plan=plan, candidate=top_candidate):
        return 1.0
    if any(_has_symbol_exact_match(plan=plan, candidate=candidate) for candidate in candidates[1:]):
        return 0.9
    if _has_symbol_related_match(plan=plan, candidate=top_candidate):
        return 0.75
    if any(candidate.metadata.symbol_fqn for candidate in candidates):
        return 0.5
    return 0.0


def _resolve_latest_release_version(versions: tuple[str, ...]) -> str | None:
    ranked_versions = tuple(
        (version, _release_version_rank(version))
        for version in versions
    )
    comparable_versions = tuple(
        (version, rank) for version, rank in ranked_versions if rank is not None
    )
    if not comparable_versions:
        return None
    return max(comparable_versions, key=lambda item: item[1])[0]


def _release_version_rank(version: str) -> tuple[int, int, int, int] | None:
    tokens = re.findall(r"\d+", version)
    if not tokens:
        return None
    numbers = [int(token) for token in tokens[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _overall_quality_score(
    *,
    coverage_score: float,
    freshness_score: float,
    citation_density_score: float,
    symbol_match_score: float,
    completeness_status: str,
    confidence: float,
) -> float:
    overall = (
        (0.40 * coverage_score)
        + (0.25 * freshness_score)
        + (0.25 * citation_density_score)
        + (0.10 * symbol_match_score)
    )
    overall *= 0.30 + (0.70 * confidence)
    if completeness_status == "partial":
        overall -= 0.10
    elif completeness_status == "insufficient":
        overall -= 0.25
    if confidence < 0.45:
        overall = min(overall, 0.35)
    return _clamp(overall)


def _has_citation(candidate: HybridCandidate) -> bool:
    return bool(
        candidate.metadata.canonical_url.strip()
        and candidate.metadata.section_anchor.strip()
        and candidate.metadata.source_revision.strip()
    )


def _is_api_reference_candidate(candidate: HybridCandidate) -> bool:
    metadata = candidate.metadata
    return metadata.source_kind == "apiref" or metadata.doc_type.casefold().startswith("api_")


def _is_guide_candidate(candidate: HybridCandidate) -> bool:
    metadata = candidate.metadata
    normalized_doc_type = metadata.doc_type.casefold()
    return metadata.source_kind == "docs" and not _is_release_doc_type(normalized_doc_type)


def _has_example_signal(candidate: HybridCandidate) -> bool:
    metadata = candidate.metadata
    normalized_doc_type = metadata.doc_type.casefold()
    normalized_title = metadata.title.casefold()
    normalized_text = metadata.text.casefold()
    return bool(
        metadata.executable_snippets
        or "example" in normalized_doc_type
        or "sample" in normalized_doc_type
        or "example" in normalized_title
        or "sample" in normalized_title
        or bool(re.search(r"\bexample\b|\bsample\b", normalized_text))
    )


def _is_release_candidate(candidate: HybridCandidate) -> bool:
    metadata = candidate.metadata
    normalized_doc_type = metadata.doc_type.casefold()
    if _is_release_doc_type(normalized_doc_type):
        return True
    normalized_text = metadata.text.casefold()
    return any(
        keyword in normalized_text
        for keyword in ("breaking", "deprecated", "migration", "migrate", "what's new", "whats new")
    )


def _is_release_doc_type(normalized_doc_type: str) -> bool:
    return normalized_doc_type in {"release_note", "release_notes", "migration_note"}


def _has_installation_signal(candidate: HybridCandidate) -> bool:
    corpus = f"{candidate.metadata.title.casefold()}\n{candidate.metadata.text.casefold()}"
    return any(token in corpus for token in ("install", "nuget", "package"))


def _has_configuration_signal(candidate: HybridCandidate) -> bool:
    corpus = f"{candidate.metadata.title.casefold()}\n{candidate.metadata.text.casefold()}"
    return any(token in corpus for token in ("setting", "option", "config", "configure"))


def _has_mitigation_signal(candidate: HybridCandidate) -> bool:
    corpus = f"{candidate.metadata.title.casefold()}\n{candidate.metadata.text.casefold()}"
    return any(
        token in corpus
        for token in ("fix", "solution", "workaround", "set ", "use ", "configure")
    )


def _has_version_scope_signal(candidate: HybridCandidate) -> bool:
    corpus = f"{candidate.metadata.title.casefold()}\n{candidate.metadata.text.casefold()}"
    return bool(re.search(r"\b\d+\.\d+(?:\.\d+)?\b", corpus))


def _has_symbol_related_match(*, plan: QueryPlan, candidate: HybridCandidate) -> bool:
    symbol_fqn = candidate.metadata.symbol_fqn
    if symbol_fqn is None:
        return False
    normalized_symbol = symbol_fqn.casefold()
    leaf_name = normalized_symbol.rsplit(".", maxsplit=1)[-1]
    return any(
        normalized_symbol.endswith(symbol.casefold())
        or leaf_name == symbol.casefold().rsplit(".", maxsplit=1)[-1]
        for symbol in plan.symbol_candidates
    )
