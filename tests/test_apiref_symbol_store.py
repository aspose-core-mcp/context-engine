from __future__ import annotations

import os

import pytest

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)

SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")


def _symbol(
    *,
    snapshot_id: str = "snap-1",
    kind: str = "method",
    member_fqn: str,
    name: str,
    parent_fqn: str | None = None,
    signature: str | None = None,
    summary: str | None = None,
    is_deprecated: bool = False,
    scope: ApiRefScope = SCOPE,
) -> ApiRefSymbol:
    return ApiRefSymbol(
        snapshot_id=snapshot_id,
        product=scope.product,
        language=scope.language,
        version=scope.version,
        locale=scope.locale,
        kind=kind,
        member_fqn=member_fqn,
        name=name,
        parent_fqn=parent_fqn,
        signature=signature,
        canonical_url=f"https://ref.aspose.com/{member_fqn}",
        is_deprecated=is_deprecated,
        summary=summary,
        payload={"signature": signature, "summary": summary},
    )


def _corpus() -> list[ApiRefSymbol]:
    return [
        _symbol(
            kind="class",
            member_fqn="aspose.slides.Presentation",
            name="Presentation",
            parent_fqn="aspose.slides",
            summary="Represents a PowerPoint presentation.",
        ),
        _symbol(
            kind="method",
            member_fqn="aspose.slides.Presentation.Save",
            name="Save",
            parent_fqn="aspose.slides.Presentation",
            signature="void Save(string fileName, SaveFormat format)",
            summary="Saves the presentation to a file.",
        ),
        _symbol(
            kind="method",
            member_fqn="aspose.slides.Presentation.Save",
            name="Save",
            parent_fqn="aspose.slides.Presentation",
            signature="void Save(Stream stream, SaveFormat format)",
            summary="Saves the presentation to a stream.",
        ),
        _symbol(
            kind="property",
            member_fqn="aspose.slides.Presentation.Slides",
            name="Slides",
            parent_fqn="aspose.slides.Presentation",
            summary="Returns the collection of slides.",
        ),
        _symbol(
            kind="enum",
            member_fqn="aspose.slides.SaveFormat",
            name="SaveFormat",
            parent_fqn="aspose.slides",
            summary="Specifies the output file format.",
        ),
    ]


def _seed(store: InMemoryApiRefSymbolStore) -> InMemoryApiRefSymbolStore:
    store.upsert_symbols(_corpus())
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    return store


# --- active-snapshot semantics ---------------------------------------------


def test_queries_return_empty_until_snapshot_flipped() -> None:
    store = InMemoryApiRefSymbolStore()
    store.upsert_symbols(_corpus())
    # Not yet activated → invisible.
    assert store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE) == ()
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-1")
    assert len(store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE)) == 1


def test_flip_swaps_to_new_snapshot_atomically() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    # Stage a v2 snapshot with a renamed class; old one still active.
    store.upsert_symbols(
        [
            _symbol(
                snapshot_id="snap-2",
                kind="class",
                member_fqn="aspose.slides.PresentationEx",
                name="PresentationEx",
            )
        ]
    )
    assert store.get_symbol(member_fqn="aspose.slides.PresentationEx", scope=SCOPE) == ()
    store.flip_active_snapshot(scope=SCOPE, snapshot_id="snap-2")
    # New snapshot now visible; old rows gone.
    assert len(store.get_symbol(member_fqn="aspose.slides.PresentationEx", scope=SCOPE)) == 1
    assert store.get_symbol(member_fqn="aspose.slides.Presentation", scope=SCOPE) == ()


# --- the five query patterns ------------------------------------------------


def test_get_symbol_returns_all_overloads() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    rows = store.get_symbol(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)
    assert len(rows) == 2
    assert {r.signature for r in rows} == {
        "void Save(string fileName, SaveFormat format)",
        "void Save(Stream stream, SaveFormat format)",
    }


def test_list_members_returns_direct_children_sorted() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    members = store.list_members(parent_fqn="aspose.slides.Presentation", scope=SCOPE)
    names = [m.name for m in members]
    # Save (method) + Slides (property); sorted by (kind, name).
    assert names == ["Save", "Save", "Slides"]
    assert members[0].kind == "method"
    assert members[-1].kind == "property"


def test_search_symbols_prefix_preference() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    results = store.search_symbols(pattern="Sa", scope=SCOPE)
    # "Save" and "SaveFormat" both start with "Sa".
    assert {r.name for r in results} == {"Save", "SaveFormat"}
    # All Save rows precede SaveFormat (shorter/prefix sort is stable by name).
    assert results[0].name == "Save"


def test_fts_search_matches_summary_terms() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    results = store.fts_search(query="stream", scope=SCOPE)
    assert any("stream" in (r.summary or "").lower() for r in results)
    # kind filter narrows results.
    only_enum = store.fts_search(query="format", scope=SCOPE, kind="enum")
    assert all(r.kind == "enum" for r in only_enum)
    assert only_enum and only_enum[0].name == "SaveFormat"


def test_list_overloads_only_methods_sorted_by_signature_length() -> None:
    store = _seed(InMemoryApiRefSymbolStore())
    overloads = store.list_overloads(member_fqn="aspose.slides.Presentation.Save", scope=SCOPE)
    assert len(overloads) == 2
    lengths = [len(o.signature or "") for o in overloads]
    assert lengths == sorted(lengths)
    # A property FQN yields no overloads (kind not in method/constructor).
    assert store.list_overloads(member_fqn="aspose.slides.Presentation.Slides", scope=SCOPE) == ()


# --- strict_version / scope isolation ---------------------------------------


def test_strict_version_isolation() -> None:
    store = InMemoryApiRefSymbolStore()
    v1 = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
    v2 = ApiRefScope(product="aspose.slides", language="net", version="25.6", locale="en")
    store.upsert_symbols(
        [_symbol(member_fqn="aspose.slides.A", name="A", scope=v1, snapshot_id="v1")]
    )
    store.upsert_symbols(
        [_symbol(member_fqn="aspose.slides.B", name="B", scope=v2, snapshot_id="v2")]
    )
    store.flip_active_snapshot(scope=v1, snapshot_id="v1")
    store.flip_active_snapshot(scope=v2, snapshot_id="v2")

    assert len(store.get_symbol(member_fqn="aspose.slides.A", scope=v1)) == 1
    # v1 symbol must not leak into a v2 query.
    assert store.get_symbol(member_fqn="aspose.slides.A", scope=v2) == ()
    assert len(store.get_symbol(member_fqn="aspose.slides.B", scope=v2)) == 1


def test_locale_isolation() -> None:
    store = InMemoryApiRefSymbolStore()
    en = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")
    de = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="de")
    store.upsert_symbols(
        [_symbol(member_fqn="aspose.slides.X", name="X", scope=en, snapshot_id="s")]
    )
    store.flip_active_snapshot(scope=en, snapshot_id="s")
    assert len(store.get_symbol(member_fqn="aspose.slides.X", scope=en)) == 1
    # de locale never activated → isolated.
    assert store.get_symbol(member_fqn="aspose.slides.X", scope=de) == ()


# --- Postgres round-trip (opt-in; requires a live database) -----------------

_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_postgres_round_trip_all_patterns() -> None:
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    store.ping()
    iso = ApiRefScope(product="test.pg", language="net", version="rt", locale="en")
    corpus = [
        _symbol(
            snapshot_id="rt-1",
            kind="class",
            member_fqn="test.pg.Doc",
            name="Doc",
            parent_fqn="test.pg",
            summary="A document.",
            scope=iso,
        ),
        _symbol(
            snapshot_id="rt-1",
            kind="method",
            member_fqn="test.pg.Doc.Save",
            name="Save",
            parent_fqn="test.pg.Doc",
            signature="void Save(string f)",
            summary="Saves to file.",
            scope=iso,
        ),
        _symbol(
            snapshot_id="rt-1",
            kind="method",
            member_fqn="test.pg.Doc.Save",
            name="Save",
            parent_fqn="test.pg.Doc",
            signature="void Save(Stream s, Format fmt)",
            summary="Saves to stream.",
            scope=iso,
        ),
    ]
    store.upsert_symbols(corpus)
    store.flip_active_snapshot(scope=iso, snapshot_id="rt-1")

    assert len(store.get_symbol(member_fqn="test.pg.Doc.Save", scope=iso)) == 2
    assert len(store.list_members(parent_fqn="test.pg.Doc", scope=iso)) == 2
    assert any(r.name == "Doc" for r in store.search_symbols(pattern="Do", scope=iso))
    assert store.fts_search(query="stream", scope=iso)
    overloads = store.list_overloads(member_fqn="test.pg.Doc.Save", scope=iso)
    assert [len(o.signature or "") for o in overloads] == sorted(
        len(o.signature or "") for o in overloads
    )


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_postgres_strips_nul_bytes() -> None:
    # Real apiref code examples embed NUL (U+0000), which Postgres text/jsonb
    # cannot store. The store must strip it rather than raise.
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    iso = ApiRefScope(product="test.nul", language="net", version="rt", locale="en")
    store.upsert_symbols(
        [
            _symbol(
                snapshot_id="nul-1",
                kind="method",
                member_fqn="test.nul.Doc.Save",
                name="Sa\x00ve",
                parent_fqn="test.nul.Doc",
                signature="void Sa\x00ve()",
                summary="Saves\x00 the doc.",
                scope=iso,
            )
        ]
    )
    store.flip_active_snapshot(scope=iso, snapshot_id="nul-1")
    rows = store.get_symbol(member_fqn="test.nul.Doc.Save", scope=iso)
    assert len(rows) == 1
    assert "\x00" not in (rows[0].summary or "")
    assert "\x00" not in (rows[0].signature or "")
    assert "\x00" not in rows[0].name
