"""API Reference symbol store (structured, non-vector retrieval).

API Reference is structured relational+tree data with a text overlay, not a
blob/vector corpus — exact/lexical/structural retrieval beats dense vectors
for symbol lookup (ADR-011). This module stores one row per
API symbol and serves five access paths without any embedding:

  1. get_symbol(member_fqn)      — exact FQN lookup (all overloads)
  2. list_members(parent_fqn)    — direct children of a namespace/class
  3. search_symbols(pattern)     — prefix/fuzzy name search
  4. fts_search(query)           — full-text over name + summary
  5. list_overloads(member_fqn)  — method/constructor overloads of a name

`member_fqn` is itself a dotted materialized path, so subtree queries are a
prefix match (no tree/closure/graph structure needed). Version-awareness uses
an active-snapshot pointer table for ADR-008-style atomic switching.

Two implementations follow the codebase convention (Protocol + InMemory +
Postgres), mirroring lexical_index_writer / vector_index_writer.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import Engine, create_engine, text


@dataclass(frozen=True, slots=True)
class ApiRefScope:
    """Retrieval scope for version-aware symbol lookup."""

    product: str
    language: str
    version: str
    locale: str = "en"


@dataclass(frozen=True, slots=True)
class ApiRefSymbol:
    """One API-reference symbol row (a class/method/property/...).

    `payload` carries the structured facets (signature, params, returns,
    remarks, examples) aggregated from the symbol document's chunks.
    """

    snapshot_id: str
    product: str
    language: str
    version: str
    locale: str
    kind: str
    member_fqn: str
    name: str
    parent_fqn: str | None = None
    signature: str | None = None
    canonical_url: str | None = None
    is_deprecated: bool = False
    summary: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ApiRefSymbolStore(Protocol):
    """Structured API-reference symbol store (no vectors)."""

    def ping(self) -> None: ...

    def upsert_symbols(self, symbols: Sequence[ApiRefSymbol]) -> int:
        """Insert/replace symbol rows (staging set, not yet active)."""
        ...

    def flip_active_snapshot(self, *, scope: ApiRefScope, snapshot_id: str) -> None:
        """Atomically make `snapshot_id` the active set for `scope`."""
        ...

    def get_symbol(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        """Exact FQN lookup (returns all overloads under the active snapshot)."""
        ...

    def list_members(self, *, parent_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        """Direct children of a namespace/class."""
        ...

    def search_symbols(
        self, *, pattern: str, scope: ApiRefScope, limit: int = 20
    ) -> tuple[ApiRefSymbol, ...]:
        """Prefix/fuzzy search by leaf name."""
        ...

    def fts_search(
        self,
        *,
        query: str,
        scope: ApiRefScope,
        limit: int = 10,
        kind: str | None = None,
    ) -> tuple[ApiRefSymbol, ...]:
        """Full-text search over name + summary (optionally kind-filtered)."""
        ...

    def list_overloads(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        """Method/constructor overloads sharing one member_fqn."""
        ...

    def known_vocabulary(self) -> dict[str, frozenset[str]]:
        """The served ``product → {languages}`` map (active snapshots only).

        Drives input normalisation for the forgiving API-reference lookup; small
        and cheap (it reads the tiny active-snapshot pointer set, not the symbol
        rows).
        """
        ...

    def resolve_active_version(
        self, *, product: str, language: str, locale: str = "en"
    ) -> str | None:
        """The highest active version for a ``product/language/locale`` scope.

        Free-text retrieval (``query_docs``) usually has no explicit version, but
        the scope-exact symbol queries require one. This resolves the latest
        active apiref version (numeric-aware) so the two-source fan-out can scope
        its apiref lane. Returns ``None`` when the scope has no active snapshot.
        """
        ...


def _scope_key(scope: ApiRefScope) -> tuple[str, str, str, str]:
    return (scope.product, scope.language, scope.version, scope.locale)


def _version_order_key(version: str) -> tuple[int, ...]:
    """Numeric-aware sort key for version strings (``25.4`` > ``9.10`` > ``9.2``).

    Each dotted segment contributes its leading integer (0 when non-numeric), so
    ``max`` over a set of versions yields the latest. Tuple comparison handles
    differing component counts (``25.4`` > ``25``).
    """
    parts: list[int] = []
    for segment in version.split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


_ROLLING_ACTIVE_VERSION = "latest-stable"


def _latest_version(versions: set[str]) -> str | None:
    """Pick the active version from a set, numeric-aware; ``None`` when empty.

    ``latest-stable`` is the rolling active pointer the whole apiref corpus
    publishes under, so it wins whenever present. Without this guard a stray
    numeric version — a single page whose front matter leaked an explicit
    version, e.g. ``26.8`` beside ``latest-stable`` — would out-rank it via
    numeric-max, flip the active snapshot to that sparse version, and collapse
    serving for the scope. Numeric-max stays the fallback for scopes that carry
    only numeric versions.
    """
    if not versions:
        return None
    if _ROLLING_ACTIVE_VERSION in versions:
        return _ROLLING_ACTIVE_VERSION
    return max(versions, key=lambda candidate: (_version_order_key(candidate), candidate))


def _strip_nul(value: str | None) -> str | None:
    """Drop NUL (U+0000) — Postgres text/jsonb cannot store it.

    Some apiref code examples embed literal NUL bytes; they would otherwise
    raise psycopg UntranslatableCharacter on insert.
    """
    if value is None:
        return None
    return value.replace("\x00", "")


def _strip_nul_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {key: _strip_nul_obj(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_strip_nul_obj(item) for item in obj]
    return obj


class InMemoryApiRefSymbolStore:
    """In-memory store for unit tests (no database required).

    Implements the same active-snapshot semantics as the Postgres adapter:
    `upsert_symbols` stages rows; `flip_active_snapshot` makes a snapshot
    visible; queries return only rows from the active snapshot for the scope.
    """

    def __init__(self) -> None:
        self._rows: list[ApiRefSymbol] = []
        self._active: dict[tuple[str, str, str, str], str] = {}

    def ping(self) -> None:
        return None

    def upsert_symbols(self, symbols: Sequence[ApiRefSymbol]) -> int:
        for sym in symbols:
            self._rows = [
                r
                for r in self._rows
                if not (
                    r.snapshot_id == sym.snapshot_id
                    and r.product == sym.product
                    and r.language == sym.language
                    and r.version == sym.version
                    and r.locale == sym.locale
                    and r.member_fqn == sym.member_fqn
                    and r.signature == sym.signature
                )
            ]
            self._rows.append(sym)
        return len(symbols)

    def flip_active_snapshot(self, *, scope: ApiRefScope, snapshot_id: str) -> None:
        self._active[_scope_key(scope)] = snapshot_id

    def known_vocabulary(self) -> dict[str, frozenset[str]]:
        accumulator: dict[str, set[str]] = {}
        for product, language, _version, _locale in self._active:
            accumulator.setdefault(product, set()).add(language)
        return {product: frozenset(langs) for product, langs in accumulator.items()}

    def resolve_active_version(
        self, *, product: str, language: str, locale: str = "en"
    ) -> str | None:
        versions = {
            ver
            for prod, lang, ver, loc in self._active
            if prod == product and lang == language and loc == locale
        }
        return _latest_version(versions)

    def _active_rows(self, scope: ApiRefScope) -> list[ApiRefSymbol]:
        active = self._active.get(_scope_key(scope))
        if active is None:
            return []
        return [
            r
            for r in self._rows
            if r.snapshot_id == active
            and r.product == scope.product
            and r.language == scope.language
            and r.version == scope.version
            and r.locale == scope.locale
        ]

    def get_symbol(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        target = member_fqn.casefold()
        return tuple(r for r in self._active_rows(scope) if r.member_fqn.casefold() == target)

    def list_members(self, *, parent_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        target = parent_fqn.casefold()
        rows = [r for r in self._active_rows(scope) if (r.parent_fqn or "").casefold() == target]
        return tuple(sorted(rows, key=lambda r: (r.kind, r.name)))

    def search_symbols(
        self, *, pattern: str, scope: ApiRefScope, limit: int = 20
    ) -> tuple[ApiRefSymbol, ...]:
        p = pattern.lower()
        scored = [
            (r, (0 if r.name.lower().startswith(p) else 1))
            for r in self._active_rows(scope)
            if p in r.name.lower()
        ]
        scored.sort(key=lambda t: (t[1], t[0].name))
        return tuple(r for r, _ in scored[:limit])

    def fts_search(
        self,
        *,
        query: str,
        scope: ApiRefScope,
        limit: int = 10,
        kind: str | None = None,
    ) -> tuple[ApiRefSymbol, ...]:
        terms = [t for t in query.lower().split() if t]
        results: list[tuple[ApiRefSymbol, int]] = []
        for r in self._active_rows(scope):
            if kind is not None and r.kind != kind:
                continue
            hay = (r.name + " " + (r.summary or "")).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                results.append((r, score))
        results.sort(key=lambda t: (-t[1], t[0].name))
        return tuple(r for r, _ in results[:limit])

    def list_overloads(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        target = member_fqn.casefold()
        rows = [
            r
            for r in self._active_rows(scope)
            if r.member_fqn.casefold() == target and r.kind in {"method", "constructor"}
        ]
        return tuple(sorted(rows, key=lambda r: len(r.signature or "")))


class PostgresApiRefSymbolStore:
    """PostgreSQL-backed API-reference symbol store (ADR-011)."""

    _UPSERT_BATCH_SIZE = 1000

    def __init__(
        self,
        *,
        postgres_dsn: str,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self._engine: Engine = create_engine(
            postgres_dsn,
            pool_pre_ping=True,
            connect_args={"connect_timeout": int(connect_timeout_seconds)},
        )
        self._ensure_schema()

    def ping(self) -> None:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    _ACTIVE_SUBQUERY = """
        snapshot_id = (
            SELECT snapshot_id FROM apiref_active_snapshot
            WHERE product=:product AND language=:language
              AND version=:version AND locale=:locale
        )
        AND product=:product AND language=:language
        AND version=:version AND locale=:locale
    """

    def upsert_symbols(self, symbols: Sequence[ApiRefSymbol]) -> int:
        """Insert/replace symbol rows in batched ``executemany`` chunks.

        Rows are sent ``_UPSERT_BATCH_SIZE`` at a time as a single
        ``executemany`` per chunk instead of one round-trip per symbol — orders
        of magnitude faster when loading tens of thousands of symbols (e.g.
        ``aspose.slides.apiref`` ~74k). Per-row ``ON CONFLICT DO UPDATE``
        semantics are preserved: ``executemany`` runs the statement once per
        row, so duplicate conflict keys *within* a batch apply sequentially —
        unlike a single multi-row ``VALUES`` which Postgres rejects with
        "ON CONFLICT DO UPDATE cannot affect row a second time".
        """
        if not symbols:
            return 0
        statement = text(
            """
            INSERT INTO symbols (
                snapshot_id, product, language, version, locale,
                kind, member_fqn, parent_fqn, name, signature,
                canonical_url, is_deprecated, summary, payload
            ) VALUES (
                :snapshot_id, :product, :language, :version, :locale,
                :kind, :member_fqn, :parent_fqn, :name, :signature,
                :canonical_url, :is_deprecated, :summary,
                CAST(:payload AS JSONB)
            )
            ON CONFLICT (snapshot_id, product, language, version,
                         locale, member_fqn, signature)
            DO UPDATE SET
                kind=EXCLUDED.kind, parent_fqn=EXCLUDED.parent_fqn,
                name=EXCLUDED.name, canonical_url=EXCLUDED.canonical_url,
                is_deprecated=EXCLUDED.is_deprecated,
                summary=EXCLUDED.summary, payload=EXCLUDED.payload
            """
        )
        params = [
            {
                "snapshot_id": sym.snapshot_id,
                "product": sym.product,
                "language": sym.language,
                "version": sym.version,
                "locale": sym.locale,
                "kind": sym.kind,
                "member_fqn": sym.member_fqn,
                "parent_fqn": sym.parent_fqn,
                "name": _strip_nul(sym.name),
                "signature": _strip_nul(sym.signature or ""),
                "canonical_url": sym.canonical_url,
                "is_deprecated": sym.is_deprecated,
                "summary": _strip_nul(sym.summary),
                "payload": json.dumps(_strip_nul_obj(sym.payload or {})),
            }
            for sym in symbols
        ]
        with self._engine.begin() as connection:
            for start in range(0, len(params), self._UPSERT_BATCH_SIZE):
                connection.execute(statement, params[start : start + self._UPSERT_BATCH_SIZE])
        return len(symbols)

    def flip_active_snapshot(self, *, scope: ApiRefScope, snapshot_id: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO apiref_active_snapshot
                        (product, language, version, locale, snapshot_id)
                    VALUES (:product, :language, :version, :locale, :snapshot_id)
                    ON CONFLICT (product, language, version, locale)
                    DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id,
                                  activated_at=NOW()
                    """
                ),
                {
                    "product": scope.product,
                    "language": scope.language,
                    "version": scope.version,
                    "locale": scope.locale,
                    "snapshot_id": snapshot_id,
                },
            )

    def known_vocabulary(self) -> dict[str, frozenset[str]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT DISTINCT product, language FROM apiref_active_snapshot")
            ).all()
        accumulator: dict[str, set[str]] = {}
        for product, language in rows:
            accumulator.setdefault(product, set()).add(language)
        return {product: frozenset(langs) for product, langs in accumulator.items()}

    def resolve_active_version(
        self, *, product: str, language: str, locale: str = "en"
    ) -> str | None:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT DISTINCT version FROM apiref_active_snapshot "
                    "WHERE product=:product AND language=:language AND locale=:locale"
                ),
                {"product": product, "language": language, "locale": locale},
            ).all()
        return _latest_version({str(row[0]) for row in rows})

    def _scope_params(self, scope: ApiRefScope) -> dict[str, str]:
        return {
            "product": scope.product,
            "language": scope.language,
            "version": scope.version,
            "locale": scope.locale,
        }

    def _query(self, sql: str, params: dict[str, Any]) -> tuple[ApiRefSymbol, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(sql), params).mappings().all()
        return tuple(
            ApiRefSymbol(
                snapshot_id=r["snapshot_id"],
                product=r["product"],
                language=r["language"],
                version=r["version"],
                locale=r["locale"],
                kind=r["kind"],
                member_fqn=r["member_fqn"],
                name=r["name"],
                parent_fqn=r["parent_fqn"],
                signature=r["signature"] or None,
                canonical_url=r["canonical_url"],
                is_deprecated=bool(r["is_deprecated"]),
                summary=r["summary"],
                payload=r["payload"] or {},
            )
            for r in rows
        )

    _SELECT = (
        "SELECT snapshot_id, product, language, version, locale, kind, "
        "member_fqn, parent_fqn, name, signature, canonical_url, "
        "is_deprecated, summary, payload FROM symbols WHERE "
    )

    def get_symbol(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        # Case-insensitive: clients query proper-case FQNs while URL-derived
        # rows are stored lowercase (ix_symbols_fqn_lower keeps this indexed).
        # Deterministic ORDER BY so overloads return in a stable order and
        # consumers that treat overloads[0] as the primary (get_symbol_doc) get a
        # repeatable signature/summary/citation across requests (mirrors
        # list_overloads; Postgres returns rows in arbitrary order otherwise).
        return self._query(
            self._SELECT
            + self._ACTIVE_SUBQUERY
            + " AND LOWER(member_fqn)=LOWER(:member_fqn)"
            + " ORDER BY length(signature) NULLS LAST, signature NULLS LAST",
            {**self._scope_params(scope), "member_fqn": member_fqn},
        )

    def list_members(self, *, parent_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        return self._query(
            self._SELECT
            + self._ACTIVE_SUBQUERY
            + " AND LOWER(parent_fqn)=LOWER(:parent_fqn) ORDER BY kind, name",
            {**self._scope_params(scope), "parent_fqn": parent_fqn},
        )

    def search_symbols(
        self, *, pattern: str, scope: ApiRefScope, limit: int = 20
    ) -> tuple[ApiRefSymbol, ...]:
        # Trigram similarity (pg_trgm) with prefix preference. Uses the
        # similarity() function rather than the bare `%` operator: under
        # psycopg's pyformat paramstyle a literal `%` in SQL collides with
        # parameter interpolation, so the function form is the safe choice.
        return self._query(
            self._SELECT
            + self._ACTIVE_SUBQUERY
            + " AND (name ILIKE :prefix OR similarity(name, :pattern) > :sim_threshold)"
            + " ORDER BY (name ILIKE :prefix) DESC,"
            + " similarity(name, :pattern) DESC, name LIMIT :limit",
            {
                **self._scope_params(scope),
                "pattern": pattern,
                "prefix": pattern + "%",
                "sim_threshold": 0.3,
                "limit": limit,
            },
        )

    def fts_search(
        self,
        *,
        query: str,
        scope: ApiRefScope,
        limit: int = 10,
        kind: str | None = None,
    ) -> tuple[ApiRefSymbol, ...]:
        kind_clause = " AND kind=:kind" if kind is not None else ""
        params: dict[str, Any] = {
            **self._scope_params(scope),
            "q": query,
            "limit": limit,
        }
        if kind is not None:
            params["kind"] = kind
        return self._query(
            self._SELECT
            + self._ACTIVE_SUBQUERY
            + kind_clause
            + " AND fts @@ websearch_to_tsquery('simple', :q)"
            + " ORDER BY ts_rank(fts, websearch_to_tsquery('simple', :q)) DESC"
            + " LIMIT :limit",
            params,
        )

    def list_overloads(self, *, member_fqn: str, scope: ApiRefScope) -> tuple[ApiRefSymbol, ...]:
        return self._query(
            self._SELECT
            + self._ACTIVE_SUBQUERY
            + " AND LOWER(member_fqn)=LOWER(:member_fqn) AND kind IN ('method','constructor')"
            + " ORDER BY length(signature)",
            {**self._scope_params(scope), "member_fqn": member_fqn},
        )

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS symbols (
                        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        snapshot_id TEXT NOT NULL,
                        product TEXT NOT NULL,
                        language TEXT NOT NULL,
                        version TEXT NOT NULL,
                        locale TEXT NOT NULL DEFAULT 'en',
                        kind TEXT NOT NULL,
                        member_fqn TEXT NOT NULL,
                        parent_fqn TEXT NULL,
                        name TEXT NOT NULL,
                        signature TEXT NOT NULL DEFAULT '',
                        canonical_url TEXT NULL,
                        is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
                        summary TEXT NULL,
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        fts tsvector GENERATED ALWAYS AS (
                            to_tsvector('simple', name || ' ' || COALESCE(summary,''))
                        ) STORED,
                        UNIQUE (snapshot_id, product, language, version,
                                locale, member_fqn, signature)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_fqn "
                    "ON symbols (member_fqn text_pattern_ops)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_parent "
                    "ON symbols (parent_fqn, kind, name)"
                )
            )
            # Case-insensitive exact lookups (clients query proper-case FQNs;
            # URL-derived rows are stored lowercase).
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_fqn_lower ON symbols (LOWER(member_fqn))"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_parent_lower "
                    "ON symbols (LOWER(parent_fqn))"
                )
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_symbols_fts ON symbols USING GIN (fts)")
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_name_trgm "
                    "ON symbols USING GIN (name gin_trgm_ops)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_symbols_scope "
                    "ON symbols (product, language, version, locale)"
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS apiref_active_snapshot (
                        product TEXT NOT NULL,
                        language TEXT NOT NULL,
                        version TEXT NOT NULL,
                        locale TEXT NOT NULL,
                        snapshot_id TEXT NOT NULL,
                        activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (product, language, version, locale)
                    )
                    """
                )
            )


def build_apiref_symbol_store(*, enabled: bool, postgres_dsn: str) -> ApiRefSymbolStore | None:
    """Construct the Postgres symbol store when enabled, else ``None``.

    Shared by the API app and the ingestion worker so both point at one store.
    Degrades to ``None`` (structured tools disabled, ingestion skips symbol
    publishing) if Postgres is unreachable, so the process still starts.
    """
    if not enabled:
        return None
    import logging

    from sqlalchemy.exc import SQLAlchemyError

    log = logging.getLogger(__name__)
    try:
        store: ApiRefSymbolStore = PostgresApiRefSymbolStore(postgres_dsn=postgres_dsn)
    except (SQLAlchemyError, OSError):
        log.warning(
            "API-reference symbol store unavailable; structured tools disabled.",
            exc_info=True,
        )
        return None
    log.info("API-reference structured symbol store enabled (Postgres).")
    return store
