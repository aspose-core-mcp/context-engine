"""Idempotency + atomic snapshot cutover for the symbol store.

Runs on both the in-memory store and (opt-in) live Postgres, so the
ON CONFLICT upsert and the active-snapshot pointer semantics are verified
against the real database, not only the in-memory model.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    ApiRefSymbolStore,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)

_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")


@pytest.fixture(params=["inmemory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[ApiRefSymbolStore]:
    if request.param == "postgres":
        if _PG_DSN is None:
            pytest.skip("ADCS_TEST_POSTGRES_DSN not set")
        yield PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)
    else:
        yield InMemoryApiRefSymbolStore()


def _sym(
    *,
    scope: ApiRefScope,
    snapshot_id: str,
    member_fqn: str,
    signature: str | None = None,
    summary: str | None = None,
) -> ApiRefSymbol:
    return ApiRefSymbol(
        snapshot_id=snapshot_id,
        product=scope.product,
        language=scope.language,
        version=scope.version,
        locale=scope.locale,
        kind="method",
        member_fqn=member_fqn,
        name=member_fqn.rsplit(".", 1)[-1],
        parent_fqn=member_fqn.rsplit(".", 1)[0],
        signature=signature,
        canonical_url=f"https://ref/{member_fqn}",
        is_deprecated=False,
        summary=summary,
        payload={},
    )


def test_reupsert_is_idempotent(store: ApiRefSymbolStore) -> None:
    scope = ApiRefScope(product="sem.idem", language="net", version="1", locale="en")
    symbol = _sym(
        scope=scope,
        snapshot_id="s1",
        member_fqn="sem.idem.Doc.Save",
        signature="void Save()",
        summary="First.",
    )
    # Upsert the same (snapshot, scope, fqn, signature) twice → one row.
    store.upsert_symbols([symbol])
    store.upsert_symbols([symbol])
    store.flip_active_snapshot(scope=scope, snapshot_id="s1")
    rows = store.get_symbol(member_fqn="sem.idem.Doc.Save", scope=scope)
    assert len(rows) == 1
    assert rows[0].summary == "First."

    # ON CONFLICT DO UPDATE: re-upsert under the same key updates in place.
    updated = _sym(
        scope=scope,
        snapshot_id="s1",
        member_fqn="sem.idem.Doc.Save",
        signature="void Save()",
        summary="Second.",
    )
    store.upsert_symbols([updated])
    rows = store.get_symbol(member_fqn="sem.idem.Doc.Save", scope=scope)
    assert len(rows) == 1
    assert rows[0].summary == "Second."


def test_atomic_snapshot_cutover(store: ApiRefSymbolStore) -> None:
    scope = ApiRefScope(product="sem.cut", language="net", version="1", locale="en")
    old = _sym(scope=scope, snapshot_id="A", member_fqn="sem.cut.Old", summary="old")
    store.upsert_symbols([old])
    store.flip_active_snapshot(scope=scope, snapshot_id="A")
    assert len(store.get_symbol(member_fqn="sem.cut.Old", scope=scope)) == 1

    # Stage snapshot B (different content); not yet active.
    new = _sym(scope=scope, snapshot_id="B", member_fqn="sem.cut.New", summary="new")
    store.upsert_symbols([new])
    assert store.get_symbol(member_fqn="sem.cut.New", scope=scope) == ()
    assert len(store.get_symbol(member_fqn="sem.cut.Old", scope=scope)) == 1

    # Atomic flip: B becomes visible, A disappears in one switch.
    store.flip_active_snapshot(scope=scope, snapshot_id="B")
    assert len(store.get_symbol(member_fqn="sem.cut.New", scope=scope)) == 1
    assert store.get_symbol(member_fqn="sem.cut.Old", scope=scope) == ()


def test_overloads_share_fqn_distinct_signatures(store: ApiRefSymbolStore) -> None:
    # Two overloads (same fqn, different signature) are distinct rows and both
    # survive the UNIQUE(snapshot, scope, fqn, signature) constraint.
    scope = ApiRefScope(product="sem.ovl", language="net", version="1", locale="en")
    store.upsert_symbols(
        [
            _sym(
                scope=scope,
                snapshot_id="o1",
                member_fqn="sem.ovl.Doc.Save",
                signature="void Save()",
            ),
            _sym(
                scope=scope,
                snapshot_id="o1",
                member_fqn="sem.ovl.Doc.Save",
                signature="void Save(Stream s)",
            ),
        ]
    )
    store.flip_active_snapshot(scope=scope, snapshot_id="o1")
    rows = store.get_symbol(member_fqn="sem.ovl.Doc.Save", scope=scope)
    assert len(rows) == 2
    assert {r.signature for r in rows} == {"void Save()", "void Save(Stream s)"}
