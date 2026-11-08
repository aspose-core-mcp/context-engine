"""Tests for the tenant_id backfill migration.

Runs against in-memory SQLite. The migration is contract-tested
against six scenarios:

* table absent (skipped with reason);
* table present, column absent → ADD COLUMN + auto-backfill;
* table present, column present, no NULL rows → no-op (idempotent);
* table present, column present, NULL rows → backfill only;
* mixed legacy + new rows → only NULLs touched;
* report aggregates per-table outcomes correctly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from adcs.admin.tenant_migration import (
    DEFAULT_TENANT_TABLES,
    TableMigrationOutcome,
    TenantMigrationReport,
    run_tenant_backfill,
)


def _make_engine():
    return create_engine("sqlite:///:memory:")


# ---------------------------------------------------------------------------
# Default-target list shape
# ---------------------------------------------------------------------------


def test_default_target_list_includes_known_admin_tables() -> None:
    """The default list covers every tenant-aware table the codebase
    currently materialises through `_ensure_schema`."""
    assert "admin_audit" in DEFAULT_TENANT_TABLES
    assert "admin_keys" in DEFAULT_TENANT_TABLES
    assert "ingestion_jobs" in DEFAULT_TENANT_TABLES


# ---------------------------------------------------------------------------
# Migration scenarios
# ---------------------------------------------------------------------------


def test_table_absent_is_skipped_with_reason() -> None:
    engine = _make_engine()
    report = run_tenant_backfill(
        engine=engine, table_names=("never_existed",)
    )
    assert report.tables_inspected == 1
    assert report.tables_changed == 0
    assert report.rows_backfilled_total == 0
    outcome = report.per_table[0]
    assert isinstance(outcome, TableMigrationOutcome)
    assert outcome.existed is False
    assert outcome.column_added is False
    assert outcome.rows_backfilled == 0
    assert outcome.skipped_reason == "table does not exist"


def test_table_without_tenant_id_column_gets_column_and_backfill() -> None:
    """Pre-existing tenant-blind table is migrated cleanly."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_audit (id TEXT, action TEXT)"))
        conn.execute(text("INSERT INTO legacy_audit VALUES ('r1', 'open')"))
        conn.execute(text("INSERT INTO legacy_audit VALUES ('r2', 'close')"))

    report = run_tenant_backfill(
        engine=engine, table_names=("legacy_audit",)
    )

    outcome = report.per_table[0]
    assert outcome.existed is True
    assert outcome.column_added is True
    # ADD COLUMN ... DEFAULT applies the default to existing rows on SQLite,
    # so the UPDATE step finds no NULLs to backfill. The column-added flag
    # is what the operator reads to confirm the migration touched the table.
    assert outcome.rows_backfilled == 0
    assert outcome.skipped_reason is None

    # Verify every row now carries the default tenant_id
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, tenant_id FROM legacy_audit ORDER BY id")
        ).all()
    assert rows == [("r1", "default"), ("r2", "default")]


def test_running_twice_is_idempotent() -> None:
    """Second run after a clean migration must be a no-op."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_audit (id TEXT, action TEXT)"))
        conn.execute(text("INSERT INTO legacy_audit VALUES ('r1', 'x')"))

    first = run_tenant_backfill(engine=engine, table_names=("legacy_audit",))
    second = run_tenant_backfill(engine=engine, table_names=("legacy_audit",))

    assert first.per_table[0].column_added is True
    assert second.per_table[0].column_added is False
    assert second.per_table[0].rows_backfilled == 0
    assert second.tables_changed == 0


def test_backfill_only_when_column_exists_with_nulls() -> None:
    """If the column was added out-of-band with NULLs, the migration backfills them."""
    engine = _make_engine()
    with engine.begin() as conn:
        # Create the table WITH the column but no default — rows arrive with NULL
        conn.execute(
            text(
                "CREATE TABLE manual_audit ("
                "  id TEXT, action TEXT, tenant_id TEXT"
                ")"
            )
        )
        conn.execute(
            text("INSERT INTO manual_audit (id, action) VALUES ('r1', 'x')")
        )
        conn.execute(
            text(
                "INSERT INTO manual_audit (id, action, tenant_id) "
                "VALUES ('r2', 'x', 't-acme')"
            )
        )

    report = run_tenant_backfill(
        engine=engine, table_names=("manual_audit",)
    )

    outcome = report.per_table[0]
    assert outcome.existed is True
    assert outcome.column_added is False  # column was already there
    assert outcome.rows_backfilled == 1   # only the NULL row touched

    # Verify the non-NULL row was preserved
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, tenant_id FROM manual_audit ORDER BY id")
        ).all()
    assert rows == [("r1", "default"), ("r2", "t-acme")]


def test_named_tenant_id_is_preserved_across_migration() -> None:
    """Already-tagged rows must NOT be overwritten by the backfill."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE quality_reviews ("
                "  id TEXT, tenant_id TEXT, status TEXT"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO quality_reviews VALUES "
                "('r1', 't-acme', 'open'), "
                "('r2', NULL, 'open'), "
                "('r3', 't-beta', 'open')"
            )
        )

    run_tenant_backfill(engine=engine, table_names=("quality_reviews",))

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, tenant_id FROM quality_reviews ORDER BY id")
        ).all()
    assert rows == [
        ("r1", "t-acme"),
        ("r2", "default"),
        ("r3", "t-beta"),
    ]


def test_report_aggregates_multiple_tables() -> None:
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t1 (id TEXT)"))
        conn.execute(text("INSERT INTO t1 VALUES ('a'), ('b')"))
        conn.execute(text("CREATE TABLE t2 (id TEXT, tenant_id TEXT)"))
        conn.execute(text("INSERT INTO t2 VALUES ('c', NULL), ('d', NULL)"))

    report = run_tenant_backfill(
        engine=engine, table_names=("t1", "t2", "t-missing")
    )
    assert report.tables_inspected == 3
    # t1 added column (counts as changed); t2 backfilled NULLs (counts as changed);
    # t-missing does not exist (no change)
    assert report.tables_changed == 2
    # t1 used DEFAULT clause so no UPDATE was needed; t2 needed UPDATE for 2 rows
    assert report.rows_backfilled_total == 2


def test_report_serialises_to_dict() -> None:
    """Report.to_dict produces JSON-friendly output for operator runs."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE x (id TEXT)"))
    report = run_tenant_backfill(engine=engine, table_names=("x",))
    payload = report.to_dict()
    assert payload["default_tenant_id"] == "default"
    assert payload["tables_inspected"] == 1
    assert isinstance(payload["per_table"], list)
    assert payload["per_table"][0]["table_name"] == "x"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_custom_default_tenant_id_is_honoured() -> None:
    """Override is respected for staged migrations that need a non-default tenant."""
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE x (id TEXT)"))
        conn.execute(text("INSERT INTO x VALUES ('row-1')"))

    report = run_tenant_backfill(
        engine=engine,
        table_names=("x",),
        default_tenant_id="t-acme",
    )
    assert report.default_tenant_id == "t-acme"
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, tenant_id FROM x")).all()
    assert rows == [("row-1", "t-acme")]


def test_empty_target_list_yields_empty_report() -> None:
    engine = _make_engine()
    report = run_tenant_backfill(engine=engine, table_names=())
    assert isinstance(report, TenantMigrationReport)
    assert report.tables_inspected == 0
    assert report.tables_changed == 0
    assert report.rows_backfilled_total == 0
    assert report.per_table == ()


# ---------------------------------------------------------------------------
# Smoke: default target list runs cleanly against an empty engine
# ---------------------------------------------------------------------------


def test_default_target_list_runs_cleanly_against_empty_engine() -> None:
    """No tables exist → every entry skipped → no errors → empty report."""
    engine = _make_engine()
    report = run_tenant_backfill(engine=engine)
    assert report.tables_inspected == len(DEFAULT_TENANT_TABLES)
    assert report.tables_changed == 0
    assert report.rows_backfilled_total == 0
    for outcome in report.per_table:
        assert outcome.existed is False
        assert outcome.skipped_reason == "table does not exist"


@pytest.mark.parametrize("ddl_quotes", [True, False])
def test_handles_basic_ddl_variants(ddl_quotes: bool) -> None:
    """Smoke: same migration path for two trivial DDL variants."""
    engine = _make_engine()
    if ddl_quotes:
        ddl = 'CREATE TABLE "audit_v2" (id TEXT)'
        target = "audit_v2"
    else:
        ddl = "CREATE TABLE audit_v3 (id TEXT)"
        target = "audit_v3"
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text(f"INSERT INTO {target} VALUES ('row-1')"))
    report = run_tenant_backfill(engine=engine, table_names=(target,))
    assert report.per_table[0].existed is True


def test_backfill_refuses_an_unsafe_table_identifier() -> None:
    """A table name cannot be bound as a parameter, so it must be validated.

    Every caller passes a name from DEFAULT_TENANT_TABLES today, which makes the
    interpolation safe by convention only — wiring this to an admin request would
    turn it into an injection with nothing in the code objecting.
    """
    from adcs.admin.tenant_migration import _assert_safe_identifier

    for safe in ("query_events", "admin_api_keys", "_legacy_audit", "t1"):
        assert _assert_safe_identifier(safe) == safe

    for unsafe in (
        "query_events; DROP TABLE admin_api_keys",
        "query_events WHERE 1=1",
        'admin"keys',
        "public.query_events",
        "",
        "1_starts_with_digit",
    ):
        with pytest.raises(ValueError, match="unsafe table identifier"):
            _assert_safe_identifier(unsafe)
