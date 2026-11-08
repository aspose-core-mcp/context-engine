"""Structured API-reference query service (Postgres symbol store).

Serves the three structured API-reference access paths as MCP tools / REST
endpoints, backed by :class:`~adcs.indexing.apiref_symbol_store.ApiRefSymbolStore`
rather than dense vectors (ADR-011):

* ``get_symbol``     — exact FQN lookup, returns all overloads + facets
* ``list_members``   — direct children of a namespace/class
* ``search_symbols`` — prefix/fuzzy name + full-text search

These are additive to the legacy ``get_symbol_doc`` tool (which still reads the
dense ``apiref_dense_v1`` collection).

Version-awareness: each request carries (product_id, language, version,
locale) which maps to an :class:`ApiRefScope`; the store resolves the active
snapshot for that scope. Callers resolve the concrete version first via the
existing ``resolve_product`` / docs-query flow.
"""

from __future__ import annotations

import re
import time

from pydantic import BaseModel, Field

from adcs.api.apiref_vocabulary import Vocabulary, is_real_product
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    ApiRefSymbolStore,
)
from adcs.indexing.symbol_resolution import find_symbol_candidates
from adcs.retrieval.profiles import EligibleSymbolStore, symbol_allowed

_DEFAULT_LOCALE = "en"
_VOCAB_TTL_SECONDS = 60.0
# Candidate pool fetched from the store before reranking. The canonical class for
# a popular leaf name can sit deep in the store's similarity order (behind many
# identically-named property accessors), so we fetch wide, rerank, then trim.
_RANK_POOL = 60

# A dotted identifier (``Aspose.Cells.Workbook.Save``) embedded in a query — the
# signal that the caller named an exact symbol rather than a concept.
_FQN_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def _fqn_candidates(text: str, *, exclude: str) -> list[str]:
    """Dotted-identifier candidates in ``text``, most-qualified first.

    ``exclude`` (the resolved product id) is dropped so a product mention like
    ``aspose.cells`` is not mistaken for a symbol FQN. Used by ``lookup`` to
    short-circuit to an exact symbol when the query names one.
    """
    excluded = exclude.casefold()
    seen: list[str] = []
    for match in _FQN_TOKEN.findall(text):
        token = match.strip(".")
        if token.casefold() == excluded or token in seen:
            continue
        seen.append(token)
    seen.sort(key=lambda token: token.count("."), reverse=True)
    return seen


class ResolutionHint(BaseModel):
    """How a request's product/language were normalised, plus recovery aids.

    Present when the input was normalised (so the caller learns the canonical
    tokens) or when the result was empty (so a weak model can self-correct in one
    more call instead of getting a silent ``[]``).
    """

    resolved_product_id: str
    resolved_language: str
    message: str | None = None
    available_products: list[str] = Field(default_factory=list)
    available_languages: list[str] = Field(default_factory=list)
    retry_with: dict[str, str] | None = None


class GetSymbolRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    version: str = Field(default="latest-stable", min_length=1)
    symbol_fqn: str = Field(min_length=1)
    locale: str = _DEFAULT_LOCALE


class SymbolOverloadResponse(BaseModel):
    signature: str | None
    summary: str | None
    parameters: str | None
    returns: str | None
    remarks: str | None
    examples: list[str]
    canonical_url: str | None
    is_deprecated: bool


class GetSymbolResponse(BaseModel):
    found: bool
    member_fqn: str
    name: str
    kind: str | None
    parent_fqn: str | None
    overloads: list[SymbolOverloadResponse]
    hint: ResolutionHint | None = None
    suggested_symbols: list[dict[str, str]] = Field(default_factory=list)


class SymbolSummaryResponse(BaseModel):
    member_fqn: str
    name: str
    kind: str
    parent_fqn: str | None
    signature: str | None
    summary: str | None
    canonical_url: str | None
    is_deprecated: bool


class ListMembersRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    version: str = Field(default="latest-stable", min_length=1)
    parent_fqn: str = Field(min_length=1)
    locale: str = _DEFAULT_LOCALE


class ListMembersResponse(BaseModel):
    parent_fqn: str
    members: list[SymbolSummaryResponse]
    hint: ResolutionHint | None = None


class SearchSymbolsRequest(BaseModel):
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    version: str = Field(default="latest-stable", min_length=1)
    query: str = Field(min_length=1)
    locale: str = _DEFAULT_LOCALE
    limit: int = Field(default=20, ge=1, le=100)


class SearchSymbolsResponse(BaseModel):
    query: str
    results: list[SymbolSummaryResponse]
    hint: ResolutionHint | None = None


class LookupRequest(BaseModel):
    """One forgiving entry point for API-reference lookup.

    ``query`` is required; ``product_id`` / ``language`` are optional hints — when
    omitted they are extracted from ``query`` itself. Collapses
    resolve→search→get into a single call.
    """

    query: str = Field(min_length=1)
    product_id: str | None = None
    language: str | None = None
    version: str = Field(default="latest-stable", min_length=1)
    locale: str = _DEFAULT_LOCALE
    limit: int = Field(default=10, ge=1, le=100)


class LookupResponse(BaseModel):
    query: str
    mode: str  # "symbol" (exact FQN short-circuit) | "search" (ranked matches)
    resolved_product_id: str
    resolved_language: str
    resolved_version: str
    symbol: GetSymbolResponse | None = None
    results: list[SymbolSummaryResponse] = Field(default_factory=list)
    hint: ResolutionHint | None = None


def _payload_str(symbol: ApiRefSymbol, key: str) -> str | None:
    value = symbol.payload.get(key)
    return value if isinstance(value, str) and value else None


def _payload_examples(symbol: ApiRefSymbol) -> list[str]:
    value = symbol.payload.get("examples")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _overload(symbol: ApiRefSymbol) -> SymbolOverloadResponse:
    return SymbolOverloadResponse(
        signature=symbol.signature,
        summary=symbol.summary,
        parameters=_payload_str(symbol, "parameters"),
        returns=_payload_str(symbol, "returns"),
        remarks=_payload_str(symbol, "remarks"),
        examples=_payload_examples(symbol),
        canonical_url=symbol.canonical_url,
        is_deprecated=symbol.is_deprecated,
    )


def _summary(symbol: ApiRefSymbol) -> SymbolSummaryResponse:
    return SymbolSummaryResponse(
        member_fqn=symbol.member_fqn,
        name=symbol.name,
        kind=symbol.kind,
        parent_fqn=symbol.parent_fqn,
        signature=symbol.signature,
        summary=symbol.summary,
        canonical_url=symbol.canonical_url,
        is_deprecated=symbol.is_deprecated,
    )


def _query_tokens(query: str) -> frozenset[str]:
    return frozenset(token for token in re.split(r"[^a-z0-9#+]+", query.lower()) if token)


def _rank_search_results(symbols: list[ApiRefSymbol], query: str) -> list[ApiRefSymbol]:
    """Surface an exact type-name match's canonical declaration over namesakes.

    When the query names a type exactly (``Worksheet``), the canonical top-level
    class is often buried in the store's similarity order behind many property
    accessors that share the leaf name. This stable rerank lifts exact-name
    matches to the front, shallowest fully-qualified name first (the top-level
    class beats a nested accessor), and preserves the store's order otherwise — so
    a pure concept query (no exact-name hit) is left untouched.
    """
    tokens = _query_tokens(query)

    def sort_key(indexed: tuple[int, ApiRefSymbol]) -> tuple[int, int, int]:
        index, symbol = indexed
        exact = symbol.name.lower() in tokens
        depth = symbol.member_fqn.count(".") if exact else 0
        return (0 if exact else 1, depth, index)

    return [symbol for _, symbol in sorted(enumerate(symbols), key=sort_key)]


class ApiRefSymbolService:
    """Postgres-backed structured API-reference query service."""

    def __init__(self, *, store: ApiRefSymbolStore) -> None:
        self._store = EligibleSymbolStore(store)
        self._vocab_cache: tuple[float, Vocabulary] | None = None

    def _vocabulary(self) -> Vocabulary:
        """Served product→languages map, cached briefly (changes only on flip)."""
        now = time.monotonic()
        if self._vocab_cache is not None and now - self._vocab_cache[0] < _VOCAB_TTL_SECONDS:
            return self._vocab_cache[1]
        # Keep only real client products; store test fixtures (rest.pg, scale.p0…)
        # must never be resolved onto or suggested as a did-you-mean.
        served = {
            product: languages
            for product, languages in self._store.known_vocabulary().items()
            if is_real_product(product)
        }
        vocabulary = Vocabulary(served)
        self._vocab_cache = (now, vocabulary)
        return vocabulary

    def vocabulary(self) -> Vocabulary:
        """Public view of the served vocabulary (used to build tool-schema enums)."""
        return self._vocabulary()

    def _active_version(self, *, product: str, language: str, locale: str, requested: str) -> str:
        """Map any version request onto the scope's active snapshot version.

        The default and most real version strings (``latest-stable``, an SDK
        version like ``24.1``) do not match the registered snapshot version
        verbatim, which made an explicit version a silent total dead-end. Resolve
        to the active version so the query grounds; fall back to the requested
        string only when the scope has no active snapshot (then it surfaces a hint).
        """
        return (
            self._store.resolve_active_version(product=product, language=language, locale=locale)
            or requested
        )

    def _resolve(
        self, request: GetSymbolRequest | ListMembersRequest | SearchSymbolsRequest,
        *, strict_scope: bool = False,
    ) -> tuple[ApiRefScope, Vocabulary, bool]:
        """Normalise product/language onto the served vocabulary."""
        # A fixed vocabulary prevents forgiving normalization from selecting a
        # different SDK when the requested product/language is not indexed yet.
        vocabulary = (
            Vocabulary({request.product_id: frozenset({request.language})})
            if strict_scope else self._vocabulary()
        )
        product = vocabulary.normalize_product(request.product_id)
        language = vocabulary.normalize_language(request.language, product=product)
        locale = request.locale or _DEFAULT_LOCALE
        changed = product != request.product_id or language != request.language
        scope = ApiRefScope(
            product=product,
            language=language,
            version=self._active_version(
                product=product, language=language, locale=locale, requested=request.version
            ),
            locale=locale,
        )
        return scope, vocabulary, changed

    @staticmethod
    def _hint(
        *,
        vocabulary: Vocabulary,
        requested_product: str,
        scope: ApiRefScope,
        changed: bool,
        empty: bool,
    ) -> ResolutionHint | None:
        """Build a did-you-mean hint. None when nothing to say."""
        if not (changed or empty):
            return None
        product_known = scope.product in vocabulary.products
        # Drop the junk 'unknown' partition so a client is never told to retry in,
        # or shown, a non-language (mirrors Vocabulary.all_languages()).
        available = sorted(
            language
            for language in vocabulary.languages_for(scope.product)
            if language != "unknown"
        )
        suggestions = [] if product_known else vocabulary.closest_products(requested_product)
        parts: list[str] = []
        retry: dict[str, str] | None = None
        if changed:
            parts.append(
                f"Interpreted as product_id='{scope.product}', language='{scope.language}'."
            )
        if empty and not product_known:
            parts.append(f"No product matched '{requested_product}'.")
            if suggestions:
                parts.append(f"Did you mean: {', '.join(suggestions)}?")
        elif empty and available and scope.language not in available:
            parts.append(
                f"Language '{scope.language}' is not served for '{scope.product}'; "
                f"available: {', '.join(available)}."
            )
            retry = {"product_id": scope.product, "language": available[0]}
        elif empty:
            parts.append(
                f"No symbol matched in '{scope.product}'. Try search_symbols with a name "
                f"or concept, or list_members on the parent namespace."
            )
        return ResolutionHint(
            resolved_product_id=scope.product,
            resolved_language=scope.language,
            message=" ".join(parts) or None,
            available_products=suggestions,
            available_languages=available if product_known else [],
            retry_with=retry,
        )

    def _resolve_bare_symbol(self, *, symbol_fqn: str, scope: ApiRefScope) -> str | None:
        """Resolve only an unambiguous candidate in the requested scope."""
        return find_symbol_candidates(
            store=self._store, scope=scope, requested=symbol_fqn,
        ).unique_fqn

    def get_symbol(
        self, *, request: GetSymbolRequest, strict_scope: bool = False
    ) -> GetSymbolResponse:
        scope, vocabulary, changed = self._resolve(request, strict_scope=strict_scope)
        overloads = self._store.get_symbol(member_fqn=request.symbol_fqn, scope=scope)
        resolved_fqn: str | None = None
        if not overloads and symbol_allowed(scope.product, scope.language, request.symbol_fqn):
            candidate = self._resolve_bare_symbol(symbol_fqn=request.symbol_fqn, scope=scope)
            if candidate is not None:
                overloads = self._store.get_symbol(member_fqn=candidate, scope=scope)
                resolved_fqn = candidate if overloads else None
        if not overloads:
            return GetSymbolResponse(
                found=False,
                suggested_symbols=find_symbol_candidates(
                    store=self._store, scope=scope, requested=request.symbol_fqn,
                ).suggestions(),
                member_fqn=request.symbol_fqn,
                name=request.symbol_fqn.rsplit(".", 1)[-1],
                kind=None,
                parent_fqn=None,
                overloads=[],
                hint=self._hint(
                    vocabulary=vocabulary,
                    requested_product=request.product_id,
                    scope=scope,
                    changed=changed,
                    empty=True,
                ),
            )
        primary = overloads[0]
        if resolved_fqn is not None:
            hint: ResolutionHint | None = ResolutionHint(
                resolved_product_id=scope.product,
                resolved_language=scope.language,
                message=f"Resolved '{request.symbol_fqn}' to '{primary.member_fqn}'.",
            )
        else:
            hint = self._hint(
                vocabulary=vocabulary,
                requested_product=request.product_id,
                scope=scope,
                changed=changed,
                empty=False,
            )
        return GetSymbolResponse(
            found=True,
            member_fqn=primary.member_fqn,
            name=primary.name,
            kind=primary.kind,
            parent_fqn=primary.parent_fqn,
            overloads=[_overload(symbol) for symbol in overloads],
            hint=hint,
        )

    def list_members(
        self, *, request: ListMembersRequest, strict_scope: bool = False
    ) -> ListMembersResponse:
        scope, vocabulary, changed = self._resolve(request, strict_scope=strict_scope)
        members = self._store.list_members(parent_fqn=request.parent_fqn, scope=scope)
        return ListMembersResponse(
            parent_fqn=request.parent_fqn,
            members=[_summary(symbol) for symbol in members],
            hint=self._hint(
                vocabulary=vocabulary,
                requested_product=request.product_id,
                scope=scope,
                changed=changed,
                empty=not members,
            ),
        )

    def _search_ordered(
        self, *, query: str, scope: ApiRefScope, limit: int
    ) -> list[ApiRefSymbol]:
        """Prefix/fuzzy + full-text hits for ``query``, deduped, reranked, capped.

        Fetches a wider candidate pool than ``limit`` so a buried canonical class
        can be lifted by :func:`_rank_search_results` before the final trim.
        """
        pool = max(limit, _RANK_POOL)
        ordered: list[ApiRefSymbol] = []
        seen: set[str] = set()
        for symbol in (
            *self._store.search_symbols(pattern=query, scope=scope, limit=pool),
            *self._store.fts_search(query=query, scope=scope, limit=pool),
        ):
            key = f"{symbol.member_fqn}|{symbol.signature or ''}"
            if key in seen:
                continue
            seen.add(key)
            ordered.append(symbol)
        return _rank_search_results(ordered, query)[:limit]

    def search_symbols(
        self, *, request: SearchSymbolsRequest, strict_scope: bool = False
    ) -> SearchSymbolsResponse:
        scope, vocabulary, changed = self._resolve(request, strict_scope=strict_scope)
        # Reduce to salient keywords like aspose_lookup does, so the two tools give
        # the same answer for the same query (parity) — a prose query must not
        # ground in one tool and return [] in the other.
        query = vocabulary.salient_query(request.query, product=scope.product)
        ordered = self._search_ordered(query=query, scope=scope, limit=request.limit)
        return SearchSymbolsResponse(
            query=request.query,
            results=[_summary(symbol) for symbol in ordered],
            hint=self._hint(
                vocabulary=vocabulary,
                requested_product=request.product_id,
                scope=scope,
                changed=changed,
                empty=not ordered,
            ),
        )

    def _resolve_lookup_scope(
        self, *, request: LookupRequest, vocabulary: Vocabulary
    ) -> tuple[ApiRefScope, bool]:
        """Resolve product/language from explicit hints *and* the NL query.

        Explicit ``product_id`` wins; otherwise the product is extracted from the
        query text. Language follows the same order, defaulting per product. The
        returned flag marks whether anything was normalised/derived (drives the
        did-you-mean hint).
        """
        raw_product = (request.product_id or "").strip()
        derived_product = False
        if raw_product:
            product = vocabulary.normalize_product(raw_product)
            if product not in vocabulary.products:
                from_text = vocabulary.find_product_in_text(request.query)
                if from_text is not None:
                    product, derived_product = from_text, True
            changed_product = derived_product or product != raw_product
        else:
            from_text = vocabulary.find_product_in_text(request.query)
            product = from_text if from_text is not None else ""
            changed_product = from_text is not None

        raw_language = (request.language or "").strip()
        if raw_language:
            language = vocabulary.normalize_language(raw_language, product=product)
            changed_language = language != raw_language
        else:
            from_text_lang = vocabulary.find_language_in_text(request.query)
            language = vocabulary.normalize_language(from_text_lang or "", product=product)
            changed_language = False  # silent default/derivation, not a correction

        locale = request.locale or _DEFAULT_LOCALE
        scope = ApiRefScope(
            product=product,
            language=language,
            version=self._active_version(
                product=product, language=language, locale=locale, requested=request.version
            ),
            locale=locale,
        )
        return scope, (changed_product or changed_language)

    def lookup(
        self, *, request: LookupRequest, strict_scope: bool = False
    ) -> LookupResponse:
        """Single forgiving entry point: resolve → (exact FQN | search) in one call.

        Collapses the resolve→search→get round-trips so a weak model grounds in
        a single tool call. If the query names an exact dotted FQN, the
        full symbol (all overloads) is returned; otherwise ranked matches with
        their signatures inline — no follow-up ``get_symbol`` needed.
        """
        if strict_scope and (not request.product_id or not request.language):
            raise ValueError("Strict symbol lookup requires product_id and language.")
        vocabulary = (
            Vocabulary({request.product_id: frozenset({request.language})})
            if strict_scope and request.product_id and request.language else self._vocabulary()
        )
        scope, changed = self._resolve_lookup_scope(request=request, vocabulary=vocabulary)

        for candidate in _fqn_candidates(request.query, exclude=scope.product):
            overloads = self._store.get_symbol(member_fqn=candidate, scope=scope)
            if overloads:
                primary = overloads[0]
                symbol = GetSymbolResponse(
                    found=True,
                    member_fqn=primary.member_fqn,
                    name=primary.name,
                    kind=primary.kind,
                    parent_fqn=primary.parent_fqn,
                    overloads=[_overload(item) for item in overloads],
                )
                return LookupResponse(
                    query=request.query,
                    mode="symbol",
                    resolved_product_id=scope.product,
                    resolved_language=scope.language,
                    resolved_version=scope.version,
                    symbol=symbol,
                    hint=self._hint(
                        vocabulary=vocabulary,
                        requested_product=request.product_id or request.query,
                        scope=scope,
                        changed=changed,
                        empty=False,
                    ),
                )

        search_query = vocabulary.salient_query(request.query, product=scope.product)
        ordered = self._search_ordered(query=search_query, scope=scope, limit=request.limit)
        return LookupResponse(
            query=request.query,
            mode="search",
            resolved_product_id=scope.product,
            resolved_language=scope.language,
            resolved_version=scope.version,
            results=[_summary(symbol) for symbol in ordered],
            hint=self._hint(
                vocabulary=vocabulary,
                requested_product=request.product_id or request.query,
                scope=scope,
                changed=changed,
                empty=not ordered,
            ),
        )


__all__ = [
    "ApiRefSymbolService",
    "GetSymbolRequest",
    "GetSymbolResponse",
    "ListMembersRequest",
    "ListMembersResponse",
    "LookupRequest",
    "LookupResponse",
    "SearchSymbolsRequest",
    "SearchSymbolsResponse",
    "SymbolOverloadResponse",
    "SymbolSummaryResponse",
]
