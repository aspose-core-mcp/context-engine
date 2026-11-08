from __future__ import annotations

from adcs.api.apiref_symbol_query import (
    ApiRefSymbolService,
    GetSymbolRequest,
    ListMembersRequest,
    LookupRequest,
    SearchSymbolsRequest,
)
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
)

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")


def _sym(
    *,
    member_fqn: str,
    name: str,
    kind: str = "method",
    parent_fqn: str | None = None,
    signature: str | None = None,
    summary: str | None = None,
    payload: dict | None = None,
) -> ApiRefSymbol:
    return ApiRefSymbol(
        snapshot_id="snap-1",
        product=SCOPE.product,
        language=SCOPE.language,
        version=SCOPE.version,
        locale=SCOPE.locale,
        kind=kind,
        member_fqn=member_fqn,
        name=name,
        parent_fqn=parent_fqn,
        signature=signature,
        canonical_url=f"https://ref.aspose.com/{member_fqn}",
        is_deprecated=False,
        summary=summary,
        payload=payload or {},
    )


def _service() -> ApiRefSymbolService:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(
        [
            _sym(
                member_fqn="aspose.slides.Presentation",
                name="Presentation",
                kind="class",
                parent_fqn="aspose.slides",
                summary="Represents a presentation.",
            ),
            _sym(
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(string fileName)",
                summary="Saves to a file.",
                payload={"parameters": "fileName: path", "examples": ["pres.Save('x');"]},
            ),
            _sym(
                member_fqn="aspose.slides.Presentation.Save",
                name="Save",
                parent_fqn="aspose.slides.Presentation",
                signature="void Save(Stream s, SaveFormat f)",
                summary="Saves to a stream.",
            ),
            _sym(
                member_fqn="aspose.slides.Presentation.Slides",
                name="Slides",
                kind="property",
                parent_fqn="aspose.slides.Presentation",
                summary="Slide collection.",
            ),
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    return ApiRefSymbolService(store=store)


def _base() -> dict:
    return {"product_id": "aspose.slides", "language": "net", "version": "24.1"}


def test_get_symbol_returns_overloads_and_facets() -> None:
    response = _service().get_symbol(
        request=GetSymbolRequest(**_base(), symbol_fqn="aspose.slides.Presentation.Save")
    )
    assert response.found
    assert response.kind == "method"
    assert len(response.overloads) == 2
    with_params = next(o for o in response.overloads if o.signature == "void Save(string fileName)")
    assert with_params.parameters == "fileName: path"
    assert with_params.examples == ["pres.Save('x');"]


def test_get_symbol_not_found() -> None:
    response = _service().get_symbol(
        request=GetSymbolRequest(**_base(), symbol_fqn="aspose.slides.Nope")
    )
    assert response.found is False
    assert response.overloads == []


def test_list_members_sorted() -> None:
    response = _service().list_members(
        request=ListMembersRequest(**_base(), parent_fqn="aspose.slides.Presentation")
    )
    assert [m.name for m in response.members] == ["Save", "Save", "Slides"]
    assert response.members[-1].kind == "property"


def test_search_symbols_returns_matches() -> None:
    response = _service().search_symbols(request=SearchSymbolsRequest(**_base(), query="Pres"))
    assert any(r.name == "Presentation" for r in response.results)


def test_search_symbols_respects_limit() -> None:
    response = _service().search_symbols(
        request=SearchSymbolsRequest(**_base(), query="Save", limit=1)
    )
    assert len(response.results) == 1


# --- Forgiving normalisation + did-you-mean hints ---


def test_b1_wrong_product_and_language_normalize_and_ground() -> None:
    # The exact bad call a weak model emits: bare product + 'csharp'.
    response = _service().search_symbols(
        request=SearchSymbolsRequest(
            product_id="slides", language="csharp", version="24.1", query="Pres"
        )
    )
    assert any(r.name == "Presentation" for r in response.results)  # grounded despite bad input
    assert response.hint is not None
    assert response.hint.resolved_product_id == "aspose.slides"
    assert response.hint.resolved_language == "net"


def test_b1_correct_exact_call_has_no_hint() -> None:
    response = _service().search_symbols(request=SearchSymbolsRequest(**_base(), query="Pres"))
    assert response.hint is None  # nothing was normalised and results were found


def test_b1_near_typo_product_auto_recovers() -> None:
    # A close typo ('slidez') is auto-normalised to the served product.
    response = _service().search_symbols(
        request=SearchSymbolsRequest(
            product_id="slidez", language="net", version="24.1", query="Pres"
        )
    )
    assert any(r.name == "Presentation" for r in response.results)
    assert response.hint is not None and response.hint.resolved_product_id == "aspose.slides"


def test_b7_get_symbol_resolves_bare_name() -> None:
    # The schema invites bare names; 'Presentation' must resolve to the canonical FQN.
    response = _service().get_symbol(request=GetSymbolRequest(**_base(), symbol_fqn="Presentation"))
    assert response.found is True
    assert response.member_fqn == "aspose.slides.Presentation"
    assert response.hint is not None and "Resolved" in (response.hint.message or "")


def test_b7_get_symbol_resolves_partial_fqn() -> None:
    # A partial path ('Presentation.Save') resolves via the tail, not just the leaf.
    response = _service().get_symbol(
        request=GetSymbolRequest(**_base(), symbol_fqn="Presentation.Save")
    )
    assert response.found is True
    assert response.member_fqn == "aspose.slides.Presentation.Save"
    assert len(response.overloads) == 2


def test_b7_get_symbol_unknown_name_actionable_hint() -> None:
    response = _service().get_symbol(request=GetSymbolRequest(**_base(), symbol_fqn="Nope"))
    assert response.found is False
    assert response.hint is not None
    assert "search_symbols" in (response.hint.message or "")


def test_b8_vocabulary_excludes_store_test_fixtures() -> None:
    store = InMemoryApiRefSymbolStore()
    for product in ("aspose.cells", "rest.pg"):
        scope = ApiRefScope(product=product, language="net", version="1", locale="en")
        store.upsert_symbols(
            [
                ApiRefSymbol(
                    snapshot_id="s",
                    product=product,
                    language="net",
                    version="1",
                    locale="en",
                    kind="class",
                    member_fqn=f"{product}.Doc",
                    name="Doc",
                )
            ]
        )
        store.flip_active_snapshot(scope=scope, snapshot_id="s")
    vocabulary = ApiRefSymbolService(store=store).vocabulary()
    assert "aspose.cells" in vocabulary.products
    assert "rest.pg" not in vocabulary.products


def test_search_and_lookup_parity_on_prose() -> None:
    # Same prose query must give the same top result from both tools (parity).
    service = _service()
    query = "how to use a Presentation"
    search = service.search_symbols(request=SearchSymbolsRequest(**_base(), query=query))
    lookup = service.lookup(request=LookupRequest(**_base(), query=query))
    assert search.results and lookup.results
    assert search.results[0].member_fqn == lookup.results[0].member_fqn


def test_hint_excludes_unknown_language() -> None:
    store = InMemoryApiRefSymbolStore()
    for lang in ("net", "unknown"):
        store.upsert_symbols(
            [
                ApiRefSymbol(
                    snapshot_id="s",
                    product="aspose.foo",
                    language=lang,
                    version="1",
                    locale="en",
                    kind="class",
                    member_fqn="aspose.foo.Bar",
                    name="Bar",
                )
            ]
        )
        store.flip_active_snapshot(
            scope=ApiRefScope(product="aspose.foo", language=lang, version="1", locale="en"),
            snapshot_id="s",
        )
    response = ApiRefSymbolService(store=store).get_symbol(
        request=GetSymbolRequest(
            product_id="aspose.foo", language="net", version="1", symbol_fqn="aspose.foo.Missing"
        )
    )
    assert response.found is False
    assert response.hint is not None
    assert "unknown" not in response.hint.available_languages


def _ranking_service() -> ApiRefSymbolService:
    # A canonical top-level class plus identically-named property accessors that
    # the store ranks first by trigram similarity (all names == 'Worksheet').
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(
        [
            _sym(
                member_fqn="aspose.slides.range.worksheet",
                name="Worksheet",
                kind="property",
                parent_fqn="aspose.slides.range",
                signature="public Worksheet Worksheet { get; }",
            ),
            _sym(
                member_fqn="aspose.slides.griddesktop.worksheet",
                name="Worksheet",
                kind="class",
                parent_fqn="aspose.slides.griddesktop",
                signature="public class Worksheet",
            ),
            _sym(
                member_fqn="aspose.slides.worksheet",
                name="Worksheet",
                kind="class",
                parent_fqn="aspose.slides",
                signature="public class Worksheet : IDisposable",
            ),
        ]
    )
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    return ApiRefSymbolService(store=store)


def test_rank_canonical_class_beats_namesake_accessors() -> None:
    # Exact type-name query: the shallowest-FQN canonical class must rank #1,
    # not a nested property accessor or a deeper legacy class of the same name.
    response = _ranking_service().search_symbols(
        request=SearchSymbolsRequest(**_base(), query="Worksheet")
    )
    assert response.results[0].member_fqn == "aspose.slides.worksheet"


def test_rank_concept_query_order_preserved() -> None:
    # No exact-name match → no reordering; the canonical Save overloads still show.
    response = _service().search_symbols(request=SearchSymbolsRequest(**_base(), query="Save"))
    assert response.results  # 'Save' is an exact name here and still grounds
    assert all(r.name == "Save" for r in response.results)


def test_b2_unknown_product_returns_hint() -> None:
    # A product with no plausible match grounds nothing but never returns a silent [].
    response = _service().search_symbols(
        request=SearchSymbolsRequest(
            product_id="totallybogus", language="net", version="24.1", query="Pres"
        )
    )
    assert response.results == []
    assert response.hint is not None
    assert response.hint.message  # actionable guidance, not a silent empty


def test_b1_single_language_product_falls_back_and_grounds() -> None:
    # The product serves only 'net'; a 'java' request falls back to 'net' and finds it.
    response = _service().get_symbol(
        request=GetSymbolRequest(
            product_id="aspose.slides",
            language="java",
            version="24.1",
            symbol_fqn="aspose.slides.Presentation",
        )
    )
    assert response.found is True
    assert response.hint is not None
    assert response.hint.resolved_language == "net"


def test_b2_unserved_language_on_multilang_product_suggests_retry() -> None:
    # A product serving {java, cpp} (no net): a 'python' request can't be served,
    # so the hint suggests an available language to retry with.
    store = InMemoryApiRefSymbolStore()
    for lang in ("java", "cpp"):
        store.upsert_symbols(
            [
                ApiRefSymbol(
                    snapshot_id="s",
                    product="aspose.foo",
                    language=lang,
                    version="1",
                    locale="en",
                    kind="class",
                    member_fqn="aspose.foo.Bar",
                    name="Bar",
                )
            ]
        )
        store.flip_active_snapshot(
            scope=ApiRefScope(product="aspose.foo", language=lang, version="1", locale="en"),
            snapshot_id="s",
        )
    service = ApiRefSymbolService(store=store)
    response = service.get_symbol(
        request=GetSymbolRequest(
            product_id="aspose.foo", language="python", version="1", symbol_fqn="aspose.foo.Missing"
        )
    )
    assert response.found is False
    assert response.hint is not None
    assert response.hint.retry_with is not None
    assert response.hint.retry_with["product_id"] == "aspose.foo"
    assert response.hint.retry_with["language"] in {"cpp", "java"}


# --- Consolidated aspose_lookup (resolve + search/get in one call) ---


def test_b3_lookup_exact_fqn_short_circuits_to_symbol() -> None:
    # Naming an exact dotted FQN returns the full symbol (all overloads), mode=symbol.
    response = _service().lookup(
        request=LookupRequest(
            query="aspose.slides.Presentation.Save",
            product_id="aspose.slides",
            language="net",
            version="24.1",
        )
    )
    assert response.mode == "symbol"
    assert response.symbol is not None and response.symbol.found
    assert len(response.symbol.overloads) == 2
    assert response.results == []


def test_b3_lookup_concept_search_has_inline_signatures() -> None:
    # A concept query with a weak model's bad tokens grounds AND inlines signatures.
    response = _service().lookup(
        request=LookupRequest(
            query="Save", product_id="slides", language="csharp", version="24.1"
        )
    )
    assert response.mode == "search"
    assert response.results  # grounded despite bare product + 'csharp'
    assert any(r.signature for r in response.results)  # signatures inline → no follow-up get
    assert response.resolved_product_id == "aspose.slides"
    assert response.resolved_language == "net"
    assert response.hint is not None  # normalisation was echoed


def test_b3_lookup_extracts_product_and_language_from_query() -> None:
    # No product_id/language args at all: both are extracted from the prose query.
    response = _service().lookup(
        request=LookupRequest(query="how to use Presentation in Aspose.Slides", version="24.1")
    )
    assert response.mode == "search"
    assert any(r.name == "Presentation" for r in response.results)
    assert response.resolved_product_id == "aspose.slides"
    assert response.resolved_language == "net"


def test_b3_lookup_resolves_version_to_active_snapshot() -> None:
    # Omitting the version resolves to the active snapshot version and grounds.
    response = _service().lookup(request=LookupRequest(query="Presentation", product_id="slides"))
    assert response.resolved_version == "24.1"
    assert response.results


def test_lookup_explicit_wrong_version_still_grounds() -> None:
    # A non-matching explicit version is no longer a silent dead-end (#2).
    response = _service().lookup(
        request=LookupRequest(query="Presentation", product_id="slides", version="99.9")
    )
    assert response.results
    assert response.resolved_version == "24.1"


def test_get_symbol_explicit_wrong_version_still_grounds() -> None:
    response = _service().get_symbol(
        request=GetSymbolRequest(
            product_id="aspose.slides",
            language="net",
            version="99.9",
            symbol_fqn="aspose.slides.Presentation",
        )
    )
    assert response.found is True


def test_b3_lookup_unknown_product_never_silent() -> None:
    # Nothing matches → empty, but an actionable hint, never a bare [].
    response = _service().lookup(
        request=LookupRequest(query="Workbook", product_id="totallybogus", version="24.1")
    )
    assert response.results == []
    assert response.symbol is None
    assert response.hint is not None and response.hint.message
