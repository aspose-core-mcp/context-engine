"""Tenant-id backfill migration for legacy SQL tables.

Part of the multi-tenancy implementation. The identity layer, SQL
persistence, retrieval partitioning, Redis namespacing and per-tenant
metrics provide the tenant-aware code paths; this module is
the one-shot migration that brings *existing* SQL rows into the new
identity model: every row in a tenant-aware table either gains a
``tenant_id`` column with default ``"default"`` (column does not yet
exist) or has any NULL value backfilled to ``"default"`` (column was
added by an earlier hand-applied migration).

The script is **idempotent**: running it twice is a no-op the second
time. The migration report makes the diff explicit so an operator can
confirm what actually changed.

Why a single one-shot rather than per-table migrations? The whole
point of this work is *backwards-compatibility*: nothing else in the
codebase changes behaviour when the column appears. Every read path
already accepts the implicit ``"default"`` value.
The migration is the trivial mechanical step that makes the implicit
default *durable*.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Engine, text

from adcs.admin.tenancy import DEFAULT_TENANT_ID

DEFAULT_TENANT_TABLES: tuple[str, ...] = (
    "admin_audit",
    "admin_keys",
    "admin_sessions",
    "ingestion_jobs",
    "snapshot_registry",
    "critical_events",
    "snapshot_rollback_audit",
    "snapshot_cleanup_audit",
    "config_history",
    "howto_overrides",
    "quality_reviews",
)


@dataclass(frozen=True, slots=True)
class TableMigrationOutcome:
    """One table's contribution to the migration report."""

    table_name: str
    existed: bool
    column_added: bool
    rows_backfilled: int
    skipped_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TenantMigrationReport:
    """Aggregate result of running the migration."""

    default_tenant_id: str
    tables_inspected: int
    tables_changed: int
    rows_backfilled_total: int
    per_table: tuple[TableMigrationOutcome, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "default_tenant_id": self.default_tenant_id,
            "tables_inspected": self.tables_inspected,
            "tables_changed": self.tables_changed,
            "rows_backfilled_total": self.rows_backfilled_total,
            "per_table": [
                {
                    "table_name": t.table_name,
                    "existed": t.existed,
                    "column_added": t.column_added,
                    "rows_backfilled": t.rows_backfilled,
                    "skipped_reason": t.skipped_reason,
                }
                for t in self.per_table
            ],
        }


def run_tenant_backfill(
    *,
    engine: Engine,
    table_names: Sequence[str] | None = None,
    default_tenant_id: str = DEFAULT_TENANT_ID,
) -> TenantMigrationReport:
    """Add ``tenant_id`` column to each tenant-aware table; backfill NULLs.

    Idempotent: tables that already have the column with no NULLs are
    a no-op. Tables that do not exist are recorded as
    ``existed=False`` with a skip reason; this is the expected state
    when a deployment has not yet provisioned every admin table.
    """
    targets = tuple(table_names) if table_names is not None else DEFAULT_TENANT_TABLES
    outcomes: list[TableMigrationOutcome] = []

    for table_name in targets:
        outcomes.append(
            _migrate_one(
                engine=engine,
                table_name=table_name,
                default_tenant_id=default_tenant_id,
            )
        )

    changed = sum(1 for o in outcomes if o.column_added or o.rows_backfilled > 0)
    rows = sum(o.rows_backfilled for o in outcomes)
    return TenantMigrationReport(
        default_tenant_id=default_tenant_id,
        tables_inspected=len(outcomes),
        tables_changed=changed,
        rows_backfilled_total=rows,
        per_table=tuple(outcomes),
    )


def _migrate_one(
    *, engine: Engine, table_name: str, default_tenant_id: str
) -> TableMigrationOutcome:
    if not _table_exists(engine=engine, table_name=table_name):
        return TableMigrationOutcome(
            table_name=table_name,
            existed=False,
            column_added=False,
            rows_backfilled=0,
            skipped_reason="table does not exist",
        )

    column_added = False
    if not _column_exists(
        engine=engine, table_name=table_name, column_name="tenant_id"
    ):
        # SQLite (and most backends) reject parameter binding inside DDL,
        # so the DEFAULT literal is inlined. The value comes from a typed
        # constant in adcs.admin.tenancy (validated against a strict slug
        # regex there), so single-quote escaping is the only sanitisation
        # required here.
        escaped_default = default_tenant_id.replace("'", "''")
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN tenant_id TEXT DEFAULT '{escaped_default}'"
                )
            )
        column_added = True

    rows_backfilled = _backfill_nulls(
        engine=engine, table_name=table_name, default_tenant_id=default_tenant_id
    )
    return TableMigrationOutcome(
        table_name=table_name,
        existed=True,
        column_added=column_added,
        rows_backfilled=rows_backfilled,
        skipped_reason=None,
    )


def _assert_safe_identifier(table_name: str) -> str:
    """Reject anything that is not a plain SQL identifier.

    A table name cannot be bound as a parameter, so it is interpolated. Today
    every caller passes a name from DEFAULT_TENANT_TABLES, which makes the
    interpolation safe by convention — one refactor wiring this to an admin
    request would turn it into an injection with nothing in the code objecting.
    Enforce the constraint here instead of relying on who happens to call it.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        msg = f"Refusing to interpolate unsafe table identifier: {table_name!r}"
        raise ValueError(msg)
    return table_name


def _backfill_nulls(
    *, engine: Engine, table_name: str, default_tenant_id: str
) -> int:
    """UPDATE every row with NULL tenant_id to the default."""
    safe_table = _assert_safe_identifier(table_name)
    with engine.begin() as connection:
        result = connection.execute(
            text(
                f"UPDATE {safe_table} SET tenant_id = :default_tenant_id "
                f"WHERE tenant_id IS NULL"
            ),
            {"default_tenant_id": default_tenant_id},
        )
        return result.rowcount or 0


def _table_exists(*, engine: Engine, table_name: str) -> bool:
    """Backend-agnostic table-existence check.

    SQLite has ``sqlite_master``; Postgres has ``information_schema.tables``.
    The helper picks the right query based on the dialect name.
    """
    dialect = engine.dialect.name
    with engine.connect() as connection:
        if dialect == "sqlite":
            row = connection.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name=:name"
                ),
                {"name": table_name},
            ).first()
            return row is not None
        # Postgres + other ANSI-ish backends
        row = connection.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :name"
            ),
            {"name": table_name},
        ).first()
        return row is not None


def _column_exists(
    *, engine: Engine, table_name: str, column_name: str
) -> bool:
    """Backend-agnostic column-existence check."""
    dialect = engine.dialect.name
    with engine.connect() as connection:
        if dialect == "sqlite":
            rows = connection.execute(
                text(f"PRAGMA table_info({table_name})")
            ).all()
            return any(row[1] == column_name for row in rows)
        row = connection.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table_name, "column": column_name},
        ).first()
        return row is not None
