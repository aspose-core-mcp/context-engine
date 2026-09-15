"""SQL persistence for the multi-tenancy identity layer.

Part of the multi-tenancy implementation. The identity-layer
scaffold in :mod:`adcs.admin.tenancy` introduces the typed ``Tenant``
record and the in-memory :class:`TenantRegistry` for tests and unit
work. This module adds the *durable* surface: a SQL-backed repository
that survives process restarts and is shared across all replicas of a
production deployment.

Implementation notes:

* Follows the project's existing persistence pattern (raw SQL through
  SQLAlchemy ``text()``, dataclass record types, Protocol-typed
  repository contract, ``_ensure_schema`` bootstrap on first
  connection) rather than introducing SQLAlchemy ORM declarative
  models. That keeps the migration story uniform across all admin /
  control-plane tables.
* Two repository implementations: :class:`InMemoryTenantRepository`
  (used by unit tests and the agentless local dev profile) and
  :class:`SqlTenantRepository` (Postgres + SQLite-compatible, used by
  the production runtime).
* The default tenant (``tenant_id="default"``) is auto-seeded on first
  bootstrap so existing single-tenant deployments do not need a manual
  migration step before the first request. The seed is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine, text

from adcs.admin.tenancy import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_SLUG,
    Tenant,
)


@dataclass(frozen=True, slots=True)
class TenantRecord:
    """Persisted tenant row, including audit timestamps.

    The non-persisted runtime view is :class:`adcs.admin.tenancy.Tenant`;
    the conversion happens through :meth:`TenantRecord.to_tenant` so the
    business layer never depends on persistence shape.
    """

    tenant_id: str
    slug: str
    display_name: str
    enabled: bool
    notes: str
    created_at: datetime
    updated_at: datetime

    def to_tenant(self) -> Tenant:
        return Tenant(
            tenant_id=self.tenant_id,
            slug=self.slug,
            display_name=self.display_name,
            enabled=self.enabled,
            notes=self.notes,
        )


class TenantAlreadyExistsError(ValueError):
    """Raised when a `create` would collide with an existing tenant_id or slug."""


class TenantRepository(Protocol):
    """Persistence contract for tenant records."""

    def create(
        self,
        *,
        tenant_id: str,
        slug: str,
        display_name: str,
        notes: str = "",
    ) -> TenantRecord:
        """Insert a new tenant. Raises :class:`TenantAlreadyExistsError` on conflict."""

    def get_by_id(self, tenant_id: str) -> TenantRecord | None:
        """Return the tenant with the given id, or None if absent."""

    def get_by_slug(self, slug: str) -> TenantRecord | None:
        """Return the tenant with the given slug, or None if absent."""

    def list(self, *, include_disabled: bool = True) -> tuple[TenantRecord, ...]:
        """Return all tenants, ordered by created_at ascending."""

    def disable(self, tenant_id: str) -> TenantRecord | None:
        """Soft-disable a tenant. Returns the updated record or None if absent."""

    def enable(self, tenant_id: str) -> TenantRecord | None:
        """Re-enable a soft-disabled tenant. Returns the updated record or None."""


def _now() -> datetime:
    return datetime.now(UTC)


def _default_tenant_record() -> TenantRecord:
    now = _now()
    return TenantRecord(
        tenant_id=DEFAULT_TENANT_ID,
        slug=DEFAULT_TENANT_SLUG,
        display_name="Default tenant",
        enabled=True,
        notes=(
            "Implicit single-tenant scope, auto-seeded at first repository "
            "bootstrap. Every record without an explicit tenant_id is owned "
            "by this tenant; the multi-tenant migration assigns concrete "
            "tenant_ids to existing rows."
        ),
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# In-memory repository (tests + local dev)
# ---------------------------------------------------------------------------


class InMemoryTenantRepository:
    """Thread-safe in-memory tenant store."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, TenantRecord] = {}
        self._by_slug: dict[str, str] = {}
        self._order: list[str] = []
        self._seed_default_locked()

    def _seed_default_locked(self) -> None:
        default = _default_tenant_record()
        self._records[default.tenant_id] = default
        self._by_slug[default.slug] = default.tenant_id
        self._order.append(default.tenant_id)

    def create(
        self,
        *,
        tenant_id: str,
        slug: str,
        display_name: str,
        notes: str = "",
    ) -> TenantRecord:
        with self._lock:
            if tenant_id in self._records:
                msg = f"tenant_id {tenant_id!r} already exists"
                raise TenantAlreadyExistsError(msg)
            if slug in self._by_slug:
                msg = f"tenant slug {slug!r} already in use"
                raise TenantAlreadyExistsError(msg)
            now = _now()
            record = TenantRecord(
                tenant_id=tenant_id,
                slug=slug,
                display_name=display_name,
                enabled=True,
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            self._records[tenant_id] = record
            self._by_slug[slug] = tenant_id
            self._order.append(tenant_id)
            return record

    def get_by_id(self, tenant_id: str) -> TenantRecord | None:
        with self._lock:
            return self._records.get(tenant_id)

    def get_by_slug(self, slug: str) -> TenantRecord | None:
        with self._lock:
            tid = self._by_slug.get(slug)
            return self._records.get(tid) if tid else None

    def list(self, *, include_disabled: bool = True) -> tuple[TenantRecord, ...]:
        with self._lock:
            records = [self._records[tid] for tid in self._order]
        if not include_disabled:
            records = [r for r in records if r.enabled]
        return tuple(records)

    def _set_enabled(self, tenant_id: str, *, enabled: bool) -> TenantRecord | None:
        with self._lock:
            existing = self._records.get(tenant_id)
            if existing is None:
                return None
            updated = TenantRecord(
                tenant_id=existing.tenant_id,
                slug=existing.slug,
                display_name=existing.display_name,
                enabled=enabled,
                notes=existing.notes,
                created_at=existing.created_at,
                updated_at=_now(),
            )
            self._records[tenant_id] = updated
            return updated

    def disable(self, tenant_id: str) -> TenantRecord | None:
        return self._set_enabled(tenant_id, enabled=False)

    def enable(self, tenant_id: str) -> TenantRecord | None:
        return self._set_enabled(tenant_id, enabled=True)


# ---------------------------------------------------------------------------
# SQL repository (Postgres in production, SQLite in tests)
# ---------------------------------------------------------------------------


_CREATE_TENANTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id     TEXT        PRIMARY KEY,
    slug          TEXT        NOT NULL UNIQUE,
    display_name  TEXT        NOT NULL,
    enabled       BOOLEAN     NOT NULL DEFAULT TRUE,
    notes         TEXT        NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL
)
"""

# SQLite does not have a native TIMESTAMPTZ type; the storage layer
# encodes timestamps as ISO-8601 strings and the read path parses them
# back. SQLAlchemy handles this for us via the connection's adapter.

_INSERT_TENANT_SQL = """
INSERT INTO tenants (tenant_id, slug, display_name, enabled, notes, created_at, updated_at)
VALUES (:tenant_id, :slug, :display_name, :enabled, :notes, :created_at, :updated_at)
"""

_SELECT_BY_ID_SQL = "SELECT * FROM tenants WHERE tenant_id = :tenant_id"
_SELECT_BY_SLUG_SQL = "SELECT * FROM tenants WHERE slug = :slug"
_SELECT_ALL_SQL = "SELECT * FROM tenants ORDER BY created_at ASC, tenant_id ASC"
_UPDATE_ENABLED_SQL = """
UPDATE tenants
   SET enabled    = :enabled,
       updated_at = :updated_at
 WHERE tenant_id  = :tenant_id
"""


def _row_to_record(row: Any) -> TenantRecord:
    return TenantRecord(
        tenant_id=str(row["tenant_id"]),
        slug=str(row["slug"]),
        display_name=str(row["display_name"]),
        enabled=bool(row["enabled"]),
        notes=str(row["notes"] or ""),
        created_at=_coerce_datetime(row["created_at"]),
        updated_at=_coerce_datetime(row["updated_at"]),
    )


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        # SQLite returns ISO-8601 strings for TIMESTAMPTZ columns.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    msg = f"unexpected timestamp value {value!r}"
    raise ValueError(msg)


class SqlTenantRepository:
    """SQL-backed tenant store. Postgres in production; SQLite for unit tests."""

    def __init__(self, *, engine_or_dsn: str | Engine) -> None:
        if isinstance(engine_or_dsn, str):
            self._engine: Engine = create_engine(engine_or_dsn, pool_pre_ping=True)
        else:
            self._engine = engine_or_dsn
        self._ensure_schema()
        self._seed_default_if_absent()

    def _ensure_schema(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(_CREATE_TENANTS_TABLE_SQL))

    def _seed_default_if_absent(self) -> None:
        if self.get_by_id(DEFAULT_TENANT_ID) is not None:
            return
        default = _default_tenant_record()
        with self._engine.begin() as connection:
            connection.execute(
                text(_INSERT_TENANT_SQL),
                {
                    "tenant_id": default.tenant_id,
                    "slug": default.slug,
                    "display_name": default.display_name,
                    "enabled": default.enabled,
                    "notes": default.notes,
                    "created_at": default.created_at,
                    "updated_at": default.updated_at,
                },
            )

    def create(
        self,
        *,
        tenant_id: str,
        slug: str,
        display_name: str,
        notes: str = "",
    ) -> TenantRecord:
        if self.get_by_id(tenant_id) is not None:
            msg = f"tenant_id {tenant_id!r} already exists"
            raise TenantAlreadyExistsError(msg)
        if self.get_by_slug(slug) is not None:
            msg = f"tenant slug {slug!r} already in use"
            raise TenantAlreadyExistsError(msg)
        now = _now()
        record = TenantRecord(
            tenant_id=tenant_id,
            slug=slug,
            display_name=display_name,
            enabled=True,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        with self._engine.begin() as connection:
            connection.execute(
                text(_INSERT_TENANT_SQL),
                {
                    "tenant_id": record.tenant_id,
                    "slug": record.slug,
                    "display_name": record.display_name,
                    "enabled": record.enabled,
                    "notes": record.notes,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
            )
        return record

    def get_by_id(self, tenant_id: str) -> TenantRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(_SELECT_BY_ID_SQL), {"tenant_id": tenant_id}
            ).mappings().first()
        return _row_to_record(row) if row else None

    def get_by_slug(self, slug: str) -> TenantRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(_SELECT_BY_SLUG_SQL), {"slug": slug}
            ).mappings().first()
        return _row_to_record(row) if row else None

    def list(self, *, include_disabled: bool = True) -> tuple[TenantRecord, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_SELECT_ALL_SQL)).mappings().all()
        records = tuple(_row_to_record(r) for r in rows)
        if not include_disabled:
            records = tuple(r for r in records if r.enabled)
        return records

    def _set_enabled(self, tenant_id: str, *, enabled: bool) -> TenantRecord | None:
        existing = self.get_by_id(tenant_id)
        if existing is None:
            return None
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                text(_UPDATE_ENABLED_SQL),
                {
                    "tenant_id": tenant_id,
                    "enabled": enabled,
                    "updated_at": now,
                },
            )
        return self.get_by_id(tenant_id)

    def disable(self, tenant_id: str) -> TenantRecord | None:
        return self._set_enabled(tenant_id, enabled=False)

    def enable(self, tenant_id: str) -> TenantRecord | None:
        return self._set_enabled(tenant_id, enabled=True)
