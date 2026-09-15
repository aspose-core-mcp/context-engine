"""Property-based tests for FilterResolver.

Fuzzes FilterResolver.resolve over wide adversarial input distributions
and asserts the structural invariants downstream retrieval code depends
on (routes always non-empty, deterministic resolution, strict_version
honoured, default-locale routing).

Complements the example-based tests in test_filter_resolver.py.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.filter_resolver import FilterResolver, normalize_version_hint
from adcs.retrieval.models import QueryPlannerInput

_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=80,
)

# Strings that look like product IDs (e.g. "aspose.ocr", "groupdocs.viewer").
_productish = st.from_regex(
    r"(aspose|groupdocs)\.[a-z][a-z0-9]{1,15}", fullmatch=True
)

# Strings that look like programming languages, mixing common aliases.
_languageish = st.sampled_from(
    [
        "net",
        ".NET",
        "Net",
        "java",
        "Java",
        "python",
        "Python",
        "node",
        "nodejs",
        "Node.js",
        "cpp",
        "C++",
        "cxx",
        "python-java",
        "python-net",
        "unknown_lang_xyz",
    ]
)

# Strings that look like version hints — covers the various forms the
# normalizer accepts (major, major.x, vMAJOR.MINOR, "latest").
_versionish = st.one_of(
    st.sampled_from(["latest", "latest-stable", "stable"]),
    st.from_regex(r"v?[0-9]{1,2}", fullmatch=True),
    st.from_regex(r"v?[0-9]{1,2}\.x", fullmatch=True),
    st.from_regex(r"v?[0-9]{1,2}\.[0-9]{1,3}", fullmatch=True),
    st.from_regex(r"v?[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3}", fullmatch=True),
)

# Strings that look like document locales.
_localeish = st.sampled_from(
    ["en", "EN", "english", "ru", "Russian", "zh", "chinese", "de", "german", "unknown_locale"]
)

_request = st.builds(
    QueryPlannerInput,
    query=_safe_text,
    product_id=st.one_of(st.none(), _productish, _safe_text),
    programming_language=st.one_of(st.none(), _languageish, _safe_text),
    version=st.one_of(st.none(), _versionish, _safe_text),
    doc_locale=st.one_of(st.none(), _localeish, _safe_text),
    strict_version=st.booleans(),
)


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_never_raises(request: QueryPlannerInput) -> None:
    """FilterResolver.resolve must accept any QueryPlannerInput without raising."""
    resolver = FilterResolver()
    resolved = resolver.resolve(request=request)
    assert resolved is not None


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_is_deterministic(request: QueryPlannerInput) -> None:
    """Two resolutions of the same request must be equal."""
    resolver = FilterResolver()
    a = resolver.resolve(request=request)
    b = resolver.resolve(request=request)
    assert a.routes == b.routes
    assert a.debug == b.debug


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_routes_are_always_non_empty(request: QueryPlannerInput) -> None:
    """resolve must always emit at least one retrieval route (default-locale fallback)."""
    resolver = FilterResolver()
    resolved = resolver.resolve(request=request)
    assert len(resolved.routes) >= 1


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_default_locale_present_in_routing(request: QueryPlannerInput) -> None:
    """The default locale ('en') must always be one of the routes."""
    resolver = FilterResolver(default_doc_locale="en")
    resolved = resolver.resolve(request=request)
    locales = [r.doc_locale for r in resolved.routes]
    assert "en" in locales


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_strict_version_flag_is_honoured(request: QueryPlannerInput) -> None:
    """When strict_version is False, every route's version must be None.
    When strict_version is True and a version was supplied, it must be
    the normalized version on every route.
    """
    resolver = FilterResolver()
    resolved = resolver.resolve(request=request)
    if not request.strict_version:
        for route in resolved.routes:
            assert route.version is None
    else:
        expected = normalize_version_hint(request.version)
        for route in resolved.routes:
            assert route.version == expected


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_route_locales_are_unique(request: QueryPlannerInput) -> None:
    """Routes must not contain duplicate doc_locale values."""
    resolver = FilterResolver()
    resolved = resolver.resolve(request=request)
    locales = [r.doc_locale for r in resolved.routes]
    assert len(locales) == len(set(locales))


@given(request=_request)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_route_product_and_language_are_consistent_across_routes(
    request: QueryPlannerInput,
) -> None:
    """Within one resolution, every route must agree on product_id and language.
    Locale is the only dimension that varies in the routing fan-out.
    """
    resolver = FilterResolver()
    resolved = resolver.resolve(request=request)
    products = {r.product_id for r in resolved.routes}
    languages = {r.programming_language for r in resolved.routes}
    assert len(products) == 1
    assert len(languages) == 1


@given(version=_versionish)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalize_version_hint_is_idempotent(version: str) -> None:
    """Normalizing an already-normalized version must return the same string."""
    once = normalize_version_hint(version)
    twice = normalize_version_hint(once)
    assert once == twice


def test_normalize_version_hint_blank_is_none() -> None:
    """Empty/None input maps to None."""
    assert normalize_version_hint(None) is None
    assert normalize_version_hint("") is None
    assert normalize_version_hint("   ") is None
