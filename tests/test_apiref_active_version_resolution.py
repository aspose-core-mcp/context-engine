"""resolve_active_version must not let a stray numeric version beat latest-stable.

A handful of apiref pages can carry an explicit numeric version in their front
matter (e.g. groupdocs.conversion/net with 1520 symbols under ``latest-stable``
and ONE under ``26.8``), which creates a second active-snapshot pointer. A plain
numeric-aware ``_latest_version`` max then picks ``26.8`` over ``latest-stable``
so scope-exact queries resolve to the sparse 1-symbol version and serve ~0.

``latest-stable`` is the rolling active pointer the whole apiref corpus
publishes under, so it must win whenever present; numeric-max is only the
fallback for scopes that carry numeric versions and no latest-stable.
"""

from __future__ import annotations

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    InMemoryApiRefSymbolStore,
    _latest_version,
)


def test_latest_stable_beats_stray_numeric_version() -> None:
    assert _latest_version({"latest-stable", "26.8"}) == "latest-stable"
    assert _latest_version({"26.8", "latest-stable", "26.5.0"}) == "latest-stable"


def test_numeric_max_still_used_without_latest_stable() -> None:
    assert _latest_version({"24.1", "24.12", "25.1"}) == "25.1"
    assert _latest_version({"9.2", "9.10"}) == "9.10"


def test_empty_is_none() -> None:
    assert _latest_version(set()) is None


def _seed(store: InMemoryApiRefSymbolStore, *, version: str, n: int, snapshot: str) -> None:
    from adcs.indexing.apiref_symbol_store import ApiRefSymbol

    rows = tuple(
        ApiRefSymbol(
            snapshot_id=snapshot, product="groupdocs.conversion", language="net",
            version=version, locale="en", kind="class",
            member_fqn=f"groupdocs.conversion.type{i}", name=f"type{i}",
            parent_fqn="groupdocs.conversion", signature=f"public class Type{i}",
            canonical_url="https://docs.groupdocs.com/net/x/", is_deprecated=False,
            summary=None, payload={},
        )
        for i in range(n)
    )
    store.upsert_symbols(rows)
    store.flip_active_snapshot(
        scope=ApiRefScope(product="groupdocs.conversion", language="net",
                          version=version, locale="en"),
        snapshot_id=snapshot,
    )


def test_store_resolves_latest_stable_when_a_stray_numeric_pointer_exists() -> None:
    """End-to-end on the store: the bulk latest-stable scope stays servable even
    with a stray numeric active pointer present."""
    store = InMemoryApiRefSymbolStore()
    _seed(store, version="latest-stable", n=20, snapshot="snap-a")
    _seed(store, version="26.8", n=1, snapshot="snap-a")

    resolved = store.resolve_active_version(
        product="groupdocs.conversion", language="net", locale="en"
    )
    assert resolved == "latest-stable"

    scope = ApiRefScope(product="groupdocs.conversion", language="net",
                        version=resolved, locale="en")
    members = store.list_members(parent_fqn="groupdocs.conversion", scope=scope)
    assert len(members) == 20
