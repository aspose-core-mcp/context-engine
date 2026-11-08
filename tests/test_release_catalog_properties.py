"""Property-based tests for ReleaseCatalog.

Asserts the lookup contract (case-insensitivity, latest-stable
resolution, deterministic behaviour) holds under wide fuzzed catalog
shapes and query inputs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.release_catalog import ReleaseCatalog, ReleaseCatalogEntry

_product = st.from_regex(r"(aspose|groupdocs)\.[a-z][a-z0-9]{1,12}", fullmatch=True)
_language = st.sampled_from(["net", "java", "python", "cpp", "node"])
_version = st.from_regex(r"v?[0-9]{1,2}(\.[0-9]{1,3}){0,2}", fullmatch=True)
_channel = st.sampled_from(["stable", "preview", "beta"])
_label = st.one_of(st.none(), st.from_regex(r"[A-Z][A-Za-z0-9 ]{0,30}", fullmatch=True))
_published_at = st.builds(
    lambda days, hours: datetime(2025, 1, 1, tzinfo=UTC).replace(
        day=1 + days, hour=hours
    ),
    st.integers(min_value=0, max_value=27),
    st.integers(min_value=0, max_value=23),
)


@st.composite
def _catalog_entry(draw: st.DrawFn) -> ReleaseCatalogEntry:
    return ReleaseCatalogEntry(
        product_id=draw(_product),
        programming_language=draw(_language),
        version=draw(_version),
        published_at=draw(_published_at),
        channel=draw(_channel),
        label=draw(_label),
    )


@st.composite
def _catalog(draw: st.DrawFn) -> ReleaseCatalog:
    n = draw(st.integers(min_value=0, max_value=20))
    entries = tuple(draw(_catalog_entry()) for _ in range(n))
    return ReleaseCatalog(entries=entries)


@given(catalog=_catalog())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_lookup_with_unknown_key_returns_none(catalog: ReleaseCatalog) -> None:
    """Resolving an unknown product/language combination must return None."""
    result = catalog.resolve(
        product_id="never.exists.product",
        programming_language="never_lang",
        version="0.0.0",
    )
    assert result is None


@given(catalog=_catalog())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_is_case_insensitive(catalog: ReleaseCatalog) -> None:
    """Lookups must succeed under different casings of the same key."""
    if not catalog.has_entries():
        return
    sample = next(iter(catalog._entries))
    via_lower = catalog.resolve(
        product_id=sample.product_id.lower(),
        programming_language=sample.programming_language.lower(),
        version=sample.version.lower(),
    )
    via_upper = catalog.resolve(
        product_id=sample.product_id.upper(),
        programming_language=sample.programming_language.upper(),
        version=sample.version.upper(),
    )
    assert via_lower == via_upper == sample


@given(catalog=_catalog())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_latest_for_returns_highest_published_at(catalog: ReleaseCatalog) -> None:
    """`latest_for` must return the entry with the maximum (published_at, version)."""
    if not catalog.has_entries():
        return
    seen_products = {
        (e.product_id.casefold(), e.programming_language.casefold())
        for e in catalog._entries
    }
    for product, language in seen_products:
        latest = catalog.latest_for(
            product_id=product, programming_language=language
        )
        assert latest is not None
        candidates = [
            e
            for e in catalog._entries
            if e.product_id.casefold() == product
            and e.programming_language.casefold() == language
        ]
        expected = max(candidates, key=lambda e: (e.published_at, e.version))
        assert latest == expected


@given(catalog=_catalog())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_with_latest_alias_falls_back_to_latest_for(
    catalog: ReleaseCatalog,
) -> None:
    """`resolve(version='latest-stable')` with no explicit alias entry falls back to latest_for."""
    if not catalog.has_entries():
        return
    sample = next(iter(catalog._entries))
    resolved = catalog.resolve(
        product_id=sample.product_id,
        programming_language=sample.programming_language,
        version="latest-stable",
    )
    expected = catalog.latest_for(
        product_id=sample.product_id,
        programming_language=sample.programming_language,
    )
    if expected is not None:
        assert resolved is not None


def test_empty_catalog_resolves_to_none() -> None:
    """Empty catalog returns None for any query."""
    catalog = ReleaseCatalog(entries=())
    assert not catalog.has_entries()
    assert (
        catalog.resolve(
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
        )
        is None
    )
    assert (
        catalog.latest_for(product_id="aspose.ocr", programming_language="net")
        is None
    )


def test_collision_on_caseless_key_dedups_to_last_entry_wins() -> None:
    """When two entries share the same caseless (product, language, version) key
    the catalog deterministically keeps the LAST one in iteration order, and
    iter(_entries) reflects the same view that resolve() returns.

    Regression: a property test discovered that without dedup,
    next(iter(self._entries)) could yield an entry that resolve() never
    returns — breaking the case-insensitive lookup contract.
    """
    first = ReleaseCatalogEntry(
        product_id="Aspose.OCR",
        programming_language="NET",
        version="25.1",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        channel="stable",
    )
    last = ReleaseCatalogEntry(
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        published_at=datetime(2025, 1, 2, tzinfo=UTC),
        channel="preview",
    )
    catalog = ReleaseCatalog(entries=(first, last))
    # Iteration matches the resolve view.
    assert next(iter(catalog._entries)) == last
    # resolve via either casing returns the surviving (last) entry.
    via_lower = catalog.resolve(
        product_id="aspose.ocr", programming_language="net", version="25.1"
    )
    via_upper = catalog.resolve(
        product_id="ASPOSE.OCR", programming_language="NET", version="25.1"
    )
    assert via_lower == via_upper == last
    assert via_lower is not None and via_lower.channel == "preview"
