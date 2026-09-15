"""Admin API authentication and product-scope authorization utilities."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Cookie, Header, HTTPException, Request
from sqlalchemy import Engine, create_engine, text

from adcs.config import AdminKeysSource, Settings

_log = logging.getLogger(__name__)

_ALL_SCOPES = "*"


@dataclass(frozen=True, slots=True)
class AdminKeyPrincipal:
    """Authenticated admin principal used by API handlers.

    ``tenant_id`` carries the principal's tenant scope. Defaults to the
    constant ``"default"`` so existing single-tenant deployments keep
    working unchanged — every legacy admin key implicitly belongs to
    the default tenant. Tenant-aware code paths (Redis namespacing,
    retrieval lane filtering, audit log routing) read this field
    instead of embedding the literal string.
    """

    key_id: str
    is_superuser: bool
    product_scopes: tuple[str, ...]
    scopes: tuple[str, ...]
    source: str
    effective_role: str
    owner_email: str = "system@local"
    tenant_id: str = "default"


@dataclass(frozen=True, slots=True)
class AdminKeyMetadata:
    """Safe key metadata returned by admin lifecycle APIs."""

    key_id: str
    key_prefix: str
    is_superuser: bool
    enabled: bool
    product_scopes: tuple[str, ...]
    scopes: tuple[str, ...]
    source: str
    effective_role: str
    owner_email: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str = "default"


@dataclass(frozen=True, slots=True)
class AdminKeyAuditRecord:
    """Audit trail entry for admin key lifecycle operations."""

    audit_id: str
    action: str
    target_key_id: str
    actor_key_id: str
    request_id: str | None
    reason: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _AdminKeyRecord:
    key_id: str
    token: str
    key_prefix: str
    is_superuser: bool
    enabled: bool
    product_scopes: tuple[str, ...]
    scopes: tuple[str, ...]
    source: str
    owner_email: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str = "default"


@dataclass(frozen=True, slots=True)
class _AdminSessionRecord:
    token: str
    key_id: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


class AdminAuthError(PermissionError):
    """Authorization error with explicit status/code for API serialization."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class _RedisSessionStore:
    """Persist admin sessions in Redis so they survive server restarts."""

    _SESSION_PREFIX = "adcs:session:"

    def __init__(self, *, redis_url: str) -> None:
        import redis as _redis_lib

        self._redis: _redis_lib.Redis = _redis_lib.Redis.from_url(
            redis_url, decode_responses=False, socket_connect_timeout=3
        )
        self._available = True
        try:
            self._redis.ping()
        except Exception:
            _log.warning("Redis not reachable — sessions will fall back to in-memory only")
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _key(self, token: str) -> str:
        return f"{self._SESSION_PREFIX}{token}"

    def put(self, session: _AdminSessionRecord) -> None:
        if not self._available:
            return
        try:
            ttl = int((session.expires_at - datetime.now(tz=UTC)).total_seconds())
            if ttl <= 0:
                return
            payload = json.dumps(
                {
                    "token": session.token,
                    "key_id": session.key_id,
                    "created_at": session.created_at.isoformat(),
                    "expires_at": session.expires_at.isoformat(),
                    "last_seen_at": session.last_seen_at.isoformat(),
                }
            )
            self._redis.setex(self._key(session.token), ttl, payload.encode())
        except Exception:
            _log.debug("Redis session put failed", exc_info=True)

    def get(self, token: str) -> _AdminSessionRecord | None:
        if not self._available:
            return None
        try:
            raw: bytes | None = self._redis.get(self._key(token))  # type: ignore[assignment]
            if raw is None:
                return None
            data = json.loads(raw.decode())
            return _AdminSessionRecord(
                token=data["token"],
                key_id=data["key_id"],
                created_at=datetime.fromisoformat(data["created_at"]),
                expires_at=datetime.fromisoformat(data["expires_at"]),
                last_seen_at=datetime.fromisoformat(data["last_seen_at"]),
            )
        except Exception:
            _log.debug("Redis session get failed", exc_info=True)
            return None

    def delete(self, token: str) -> None:
        if not self._available:
            return
        try:
            self._redis.delete(self._key(token))
        except Exception:
            _log.debug("Redis session delete failed", exc_info=True)

    def touch(self, session: _AdminSessionRecord) -> None:
        """Update last_seen_at without changing TTL."""
        self.put(session)


class AdminAuthService:
    """Authenticate admin keys and enforce product-scoped write permissions."""

    def __init__(self, *, settings: Settings) -> None:
        self._lock = Lock()
        self._sessions_by_token: dict[str, _AdminSessionRecord] = {}
        self._audit_records: list[AdminKeyAuditRecord] = []
        self._redis_store = _RedisSessionStore(redis_url=settings.redis_url)
        self._pg_store: PostgresAdminKeyStore | None = None
        try:
            self._pg_store = PostgresAdminKeyStore(postgres_dsn=settings.postgres_dsn)
            _log.info("PostgreSQL admin key store initialized")
        except Exception:
            _log.warning(
                "PostgreSQL admin key store unavailable — keys will not persist across restarts",
                exc_info=True,
            )
        # Load seed keys from env/json config
        seed_records = _load_admin_key_records(settings=settings)
        self._records_by_id: dict[str, _AdminKeyRecord] = {
            record.key_id: record for record in seed_records
        }
        # Seed env/json keys into Postgres if available
        if self._pg_store is not None:
            for record in seed_records:
                self._pg_store.upsert_key(record)
            # Load all keys from Postgres (includes previously created keys)
            for pg_record in self._pg_store.load_all_keys():
                if pg_record.key_id not in self._records_by_id:
                    self._records_by_id[pg_record.key_id] = pg_record

    def authenticate(self, *, api_key: str | None) -> AdminKeyPrincipal:
        if api_key is None or not api_key.strip():
            raise AdminAuthError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Missing `x-api-key` header.",
            )
        normalized_key = api_key.strip()
        with self._lock:
            # compare_digest, not `==`: the built-in comparison short-circuits on
            # the first differing byte, which leaks key material through response
            # timing. The loop deliberately checks every record instead of
            # stopping early, so the work done does not depend on which key matched.
            record = None
            for item in self._records_by_id.values():
                if hmac.compare_digest(item.token, normalized_key):
                    record = item
        if record is None:
            raise AdminAuthError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid admin API key.",
            )
        if not record.enabled:
            raise AdminAuthError(
                status_code=403,
                code="FORBIDDEN",
                message="Admin API key is disabled.",
            )
        return self._principal_from_record(record)

    def authenticate_request(
        self,
        *,
        api_key: str | None,
        session_token: str | None,
    ) -> AdminKeyPrincipal:
        if api_key is not None and api_key.strip():
            return self.authenticate(api_key=api_key)
        if session_token is not None and session_token.strip():
            return self.authenticate_session(session_token=session_token)
        raise AdminAuthError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing admin credentials (`x-api-key` or session cookie).",
        )

    def create_session(
        self,
        *,
        key_id: str,
        ttl_seconds: int,
    ) -> str:
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        token = _generate_admin_session_token()
        record = _AdminSessionRecord(
            token=token,
            key_id=key_id,
            created_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
        with self._lock:
            self._purge_expired_sessions_locked(now=now)
            self._sessions_by_token[token] = record
        self._redis_store.put(record)
        return token

    def authenticate_session(self, *, session_token: str) -> AdminKeyPrincipal:
        now = datetime.now(tz=UTC)
        normalized = session_token.strip()
        if not normalized:
            raise AdminAuthError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid admin session cookie.",
            )
        with self._lock:
            self._purge_expired_sessions_locked(now=now)
            session = self._sessions_by_token.get(normalized)
            # Recover session from Redis if not found in memory (e.g. after restart).
            if session is None:
                session = self._redis_store.get(normalized)
                if session is not None and session.expires_at > now:
                    self._sessions_by_token[normalized] = session
                else:
                    session = None
            if session is None:
                raise AdminAuthError(
                    status_code=401,
                    code="UNAUTHORIZED",
                    message="Admin session cookie is invalid or expired.",
                )
            key_record = self._records_by_id.get(session.key_id)
            if key_record is None:
                self._sessions_by_token.pop(normalized, None)
                self._redis_store.delete(normalized)
                raise AdminAuthError(
                    status_code=401,
                    code="UNAUTHORIZED",
                    message="Admin session cookie is invalid or expired.",
                )
            if not key_record.enabled:
                self._sessions_by_token.pop(normalized, None)
                self._redis_store.delete(normalized)
                raise AdminAuthError(
                    status_code=403,
                    code="FORBIDDEN",
                    message="Admin API key is disabled.",
                )
            updated = replace(session, last_seen_at=now)
            self._sessions_by_token[normalized] = updated
        self._redis_store.touch(updated)
        principal = self._principal_from_record(key_record)
        return replace(principal, source=f"{principal.source}:session_cookie")

    def revoke_session(self, *, session_token: str | None) -> None:
        if session_token is None:
            return
        normalized = session_token.strip()
        if not normalized:
            return
        with self._lock:
            self._sessions_by_token.pop(normalized, None)
        self._redis_store.delete(normalized)

    def _principal_from_record(self, record: _AdminKeyRecord) -> AdminKeyPrincipal:
        return AdminKeyPrincipal(
            key_id=record.key_id,
            is_superuser=record.is_superuser,
            product_scopes=record.product_scopes,
            scopes=record.scopes,
            source=record.source,
            effective_role=_derive_effective_role(record=record),
            owner_email=getattr(record, "owner_email", "system@local"),
            tenant_id=getattr(record, "tenant_id", "default"),
        )

    def _purge_expired_sessions_locked(self, *, now: datetime) -> None:
        expired_tokens = tuple(
            token
            for token, session in self._sessions_by_token.items()
            if session.expires_at <= now
        )
        for token in expired_tokens:
            self._sessions_by_token.pop(token, None)

    def list_key_metadata(self) -> tuple[AdminKeyMetadata, ...]:
        with self._lock:
            records = tuple(self._records_by_id.values())
        ordered = sorted(records, key=lambda item: (item.created_at, item.key_id))
        return tuple(_to_metadata(item) for item in ordered)

    def get_key_metadata(self, *, key_id: str) -> AdminKeyMetadata | None:
        with self._lock:
            record = self._records_by_id.get(key_id)
        if record is None:
            return None
        return _to_metadata(record)

    def get_internal_record(self, *, key_id: str) -> _AdminKeyRecord | None:
        with self._lock:
            return self._records_by_id.get(key_id)

    def create_key(
        self,
        *,
        is_superuser: bool,
        product_scopes: tuple[str, ...],
        scopes: tuple[str, ...],
        enabled: bool,
        owner_email: str,
        actor_key_id: str,
        request_id: str | None,
        reason: str | None,
        tenant_id: str = "default",
    ) -> tuple[AdminKeyMetadata, str]:
        now = datetime.now(tz=UTC)
        token = _generate_admin_api_key_token()
        key_id = str(uuid4())
        normalized_product_scopes = _normalize_string_tuple(product_scopes)
        normalized_scopes = _normalize_string_tuple(scopes)
        if is_superuser:
            normalized_scopes = _ensure_superuser_scopes(normalized_scopes)
        elif not normalized_product_scopes:
            msg = "Non-superuser key must include at least one product scope."
            raise ValueError(msg)
        normalized_tenant_id = (tenant_id or "default").strip()
        if not normalized_tenant_id:
            normalized_tenant_id = "default"
        record = _AdminKeyRecord(
            key_id=key_id,
            token=token,
            key_prefix=_build_key_prefix(token),
            is_superuser=is_superuser,
            enabled=enabled,
            product_scopes=normalized_product_scopes,
            scopes=normalized_scopes,
            source="admin_api",
            owner_email=owner_email.strip(),
            created_at=now,
            updated_at=now,
            tenant_id=normalized_tenant_id,
        )
        with self._lock:
            self._records_by_id[key_id] = record
        if self._pg_store is not None:
            self._pg_store.upsert_key(record)
        self._append_audit(
            action="create",
            target_key_id=record.key_id,
            actor_key_id=actor_key_id,
            request_id=request_id,
            reason=reason,
            before=None,
            after=_metadata_payload(record),
        )
        return _to_metadata(record), token

    def set_key_enabled(
        self,
        *,
        key_id: str,
        enabled: bool,
        actor_key_id: str,
        request_id: str | None,
        reason: str | None,
    ) -> AdminKeyMetadata:
        with self._lock:
            record = self._records_by_id.get(key_id)
            if record is None:
                raise KeyError(key_id)
            before_payload = _metadata_payload(record)
            if record.enabled == enabled:
                return _to_metadata(record)
            updated = replace(record, enabled=enabled, updated_at=datetime.now(tz=UTC))
            self._records_by_id[key_id] = updated
        if self._pg_store is not None:
            self._pg_store.upsert_key(updated)
        self._append_audit(
            action="enable" if enabled else "disable",
            target_key_id=key_id,
            actor_key_id=actor_key_id,
            request_id=request_id,
            reason=reason,
            before=before_payload,
            after=_metadata_payload(updated),
        )
        return _to_metadata(updated)

    def update_key_scopes(
        self,
        *,
        key_id: str,
        product_scopes: tuple[str, ...],
        scopes: tuple[str, ...],
        actor_key_id: str,
        request_id: str | None,
        reason: str | None,
    ) -> AdminKeyMetadata:
        with self._lock:
            record = self._records_by_id.get(key_id)
            if record is None:
                raise KeyError(key_id)
            normalized_product_scopes = _normalize_string_tuple(product_scopes)
            normalized_scopes = _normalize_string_tuple(scopes)
            if record.is_superuser:
                normalized_scopes = _ensure_superuser_scopes(normalized_scopes)
            elif not normalized_product_scopes:
                msg = "Non-superuser key must include at least one product scope."
                raise ValueError(msg)
            before_payload = _metadata_payload(record)
            updated = replace(
                record,
                product_scopes=normalized_product_scopes,
                scopes=normalized_scopes,
                updated_at=datetime.now(tz=UTC),
            )
            self._records_by_id[key_id] = updated
        if self._pg_store is not None:
            self._pg_store.upsert_key(updated)
        self._append_audit(
            action="update_scopes",
            target_key_id=key_id,
            actor_key_id=actor_key_id,
            request_id=request_id,
            reason=reason,
            before=before_payload,
            after=_metadata_payload(updated),
        )
        return _to_metadata(updated)

    def list_key_audit(self, *, limit: int = 100) -> tuple[AdminKeyAuditRecord, ...]:
        with self._lock:
            entries = tuple(self._audit_records)
        ordered = sorted(entries, key=lambda item: (item.created_at, item.audit_id), reverse=True)
        return tuple(ordered[: max(1, min(limit, 500))])

    def authorize_mutation(
        self,
        *,
        principal: AdminKeyPrincipal,
        required_scope: str,
        target_product_ids: tuple[str, ...],
        destructive: bool = False,
    ) -> None:
        if principal.is_superuser:
            return

        if not self.has_scope(principal=principal, scope=required_scope):
            raise AdminAuthError(
                status_code=403,
                code="FORBIDDEN",
                message=f"Missing required scope: {required_scope}.",
            )
        if destructive and not self.has_scope(principal=principal, scope="write:destructive"):
            raise AdminAuthError(
                status_code=403,
                code="FORBIDDEN",
                message="Missing required scope: write:destructive.",
            )
        denied_products = tuple(
            product_id
            for product_id in target_product_ids
            if product_id not in principal.product_scopes
        )
        if denied_products:
            raise AdminAuthError(
                status_code=403,
                code="FORBIDDEN",
                message=(
                    "Product scope violation: key does not grant write access to "
                    f"{', '.join(denied_products)}."
                ),
            )

    def has_scope(self, *, principal: AdminKeyPrincipal, scope: str) -> bool:
        return (
            principal.is_superuser
            or _ALL_SCOPES in principal.scopes
            or scope in principal.scopes
        )

    def _append_audit(
        self,
        *,
        action: str,
        target_key_id: str,
        actor_key_id: str,
        request_id: str | None,
        reason: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        entry = AdminKeyAuditRecord(
            audit_id=str(uuid4()),
            action=action,
            target_key_id=target_key_id,
            actor_key_id=actor_key_id,
            request_id=request_id,
            reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
            before=before,
            after=after,
            created_at=datetime.now(tz=UTC),
        )
        with self._lock:
            self._audit_records.append(entry)


def _hash_token(token: str) -> str:
    """Return a SHA-256 hex digest of the token for safe Postgres storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PostgresAdminKeyStore:
    """PostgreSQL-backed persistence for admin API keys.

    Stores token HASH only (SHA-256).  The raw token is never persisted.
    Used as a source-of-truth backing store; the in-memory dict in
    ``AdminAuthService`` acts as a read-through cache.
    """

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

    def _ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS admin_api_keys (
                        key_id TEXT PRIMARY KEY,
                        token_hash TEXT NOT NULL,
                        owner_email TEXT NOT NULL DEFAULT 'system@local',
                        scopes_json JSONB NOT NULL DEFAULT '[]',
                        product_scopes_json JSONB NOT NULL DEFAULT '[]',
                        is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        source TEXT NOT NULL DEFAULT 'admin_api',
                        reason TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_admin_api_keys_owner_email
                    ON admin_api_keys (owner_email)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_admin_api_keys_token_hash
                    ON admin_api_keys (token_hash)
                    """
                )
            )

    def upsert_key(self, record: _AdminKeyRecord) -> None:
        """Insert or update a key record in Postgres (token stored as hash)."""
        token_hash = _hash_token(record.token)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO admin_api_keys (
                        key_id, token_hash, owner_email, scopes_json,
                        product_scopes_json, is_superuser, enabled,
                        source, created_at, updated_at
                    )
                    VALUES (
                        :key_id, :token_hash, :owner_email,
                        CAST(:scopes_json AS JSONB),
                        CAST(:product_scopes_json AS JSONB),
                        :is_superuser, :enabled, :source,
                        :created_at, :updated_at
                    )
                    ON CONFLICT (key_id) DO UPDATE SET
                        token_hash = EXCLUDED.token_hash,
                        owner_email = EXCLUDED.owner_email,
                        scopes_json = EXCLUDED.scopes_json,
                        product_scopes_json = EXCLUDED.product_scopes_json,
                        is_superuser = EXCLUDED.is_superuser,
                        enabled = EXCLUDED.enabled,
                        source = EXCLUDED.source,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "key_id": record.key_id,
                    "token_hash": token_hash,
                    "owner_email": record.owner_email,
                    "scopes_json": json.dumps(list(record.scopes)),
                    "product_scopes_json": json.dumps(list(record.product_scopes)),
                    "is_superuser": record.is_superuser,
                    "enabled": record.enabled,
                    "source": record.source,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
            )

    def load_all_keys(self) -> tuple[_AdminKeyRecord, ...]:
        """Load all keys from Postgres.

        Returns records with ``token`` set to the *hash* (not the raw token).
        These records can be used for metadata but NOT for raw-token authentication.
        Seed/env keys are matched by ``key_id`` and overwritten in memory with
        the full token during startup.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        key_id, token_hash, owner_email, scopes_json,
                        product_scopes_json, is_superuser, enabled,
                        source, created_at, updated_at
                    FROM admin_api_keys
                    ORDER BY created_at ASC
                    """
                )
            ).mappings().all()
        return tuple(_map_pg_key_row(row) for row in rows)

    def delete_key(self, key_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM admin_api_keys WHERE key_id = :key_id"),
                {"key_id": key_id},
            )

    def export_all_metadata(self) -> list[dict[str, object]]:
        """Export all keys as JSON-safe metadata dicts (no tokens)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        key_id, owner_email, scopes_json,
                        product_scopes_json, is_superuser, enabled,
                        source, created_at, updated_at
                    FROM admin_api_keys
                    ORDER BY created_at ASC
                    """
                )
            ).mappings().all()
        result: list[dict[str, object]] = []
        for row in rows:
            scopes = json.loads(row["scopes_json"]) if isinstance(row["scopes_json"], str) else row["scopes_json"]  # noqa: E501
            product_scopes = json.loads(row["product_scopes_json"]) if isinstance(row["product_scopes_json"], str) else row["product_scopes_json"]  # noqa: E501
            created_at = row["created_at"]
            updated_at = row["updated_at"]
            result.append(
                {
                    "key_id": str(row["key_id"]),
                    "owner_email": str(row["owner_email"]),
                    "scopes": list(scopes) if isinstance(scopes, list) else [],
                    "product_scopes": (
                        list(product_scopes) if isinstance(product_scopes, list) else []
                    ),
                    "is_superuser": bool(row["is_superuser"]),
                    "enabled": bool(row["enabled"]),
                    "source": str(row["source"]),
                    "created_at": (
                        created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)  # noqa: E501
                    ),
                    "updated_at": (
                        updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at)  # noqa: E501
                    ),
                }
            )
        return result


def _map_pg_key_row(row: object) -> _AdminKeyRecord:
    """Map a Postgres row to an _AdminKeyRecord.

    The ``token`` field is set to the hash since the raw token is not stored.
    Records loaded from PG are only usable for metadata; for authentication the
    in-memory cache (populated at key creation time) holds the raw token.
    """
    if not isinstance(row, Mapping):
        msg = "Unexpected admin key row type."
        raise TypeError(msg)

    scopes_raw = row.get("scopes_json")
    scopes = json.loads(scopes_raw) if isinstance(scopes_raw, str) else scopes_raw
    product_scopes_raw = row.get("product_scopes_json")
    product_scopes = (
        json.loads(product_scopes_raw)
        if isinstance(product_scopes_raw, str)
        else product_scopes_raw
    )
    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    if not isinstance(created_at, datetime):
        msg = "Invalid admin key created_at."
        raise TypeError(msg)
    if not isinstance(updated_at, datetime):
        msg = "Invalid admin key updated_at."
        raise TypeError(msg)

    return _AdminKeyRecord(
        key_id=str(row.get("key_id")),
        token=str(row.get("token_hash")),  # hash, not raw
        key_prefix="pg_hash",
        is_superuser=bool(row.get("is_superuser")),
        enabled=bool(row.get("enabled")),
        product_scopes=tuple(product_scopes) if isinstance(product_scopes, list) else (),
        scopes=tuple(scopes) if isinstance(scopes, list) else (),
        source=str(row.get("source", "admin_api")),
        owner_email=str(row.get("owner_email", "system@local")),
        created_at=created_at,
        updated_at=updated_at,
    )


def get_admin_auth_service(request: Request) -> AdminAuthService:
    service = getattr(request.app.state, "admin_auth_service", None)
    if not isinstance(service, AdminAuthService):
        msg = "Admin auth service is not configured."
        raise RuntimeError(msg)
    return service


async def require_admin_principal(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    adcs_admin_session: Annotated[
        str | None,
        Cookie(alias="adcs_admin_session"),
    ] = None,
) -> AdminKeyPrincipal:
    service = get_admin_auth_service(request)
    settings = getattr(request.app.state, "settings", None)
    session_cookie_name = (
        settings.admin_session_cookie_name
        if isinstance(settings, Settings)
        else "adcs_admin_session"
    )
    cookie_token = request.cookies.get(session_cookie_name) or adcs_admin_session
    try:
        principal = service.authenticate_request(
            api_key=x_api_key,
            session_token=cookie_token,
        )
    except AdminAuthError as exc:
        raise _to_http_exception(request=request, error=exc) from exc
    request.state.admin_principal = principal
    return principal


def _to_http_exception(*, request: Request, error: AdminAuthError) -> HTTPException:
    request_id = getattr(request.state, "request_id", None)
    return HTTPException(
        status_code=error.status_code,
        detail={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": {},
                "request_id": request_id,
            }
        },
    )


def _load_admin_key_records(*, settings: Settings) -> tuple[_AdminKeyRecord, ...]:
    if settings.admin_keys_source is AdminKeysSource.JSON_DEV:
        return _load_json_dev_records(settings.admin_keys_json_path)
    return (_load_env_record(settings=settings),)


def _load_env_record(*, settings: Settings) -> _AdminKeyRecord:
    token = settings.admin_api_key.get_secret_value().strip()
    if not token:
        msg = "ADCS_API_KEY must not be empty."
        raise ValueError(msg)
    now = datetime.now(tz=UTC)
    return _AdminKeyRecord(
        key_id="env-admin-key",
        token=token,
        key_prefix=_build_key_prefix(token),
        is_superuser=True,
        enabled=True,
        product_scopes=(),
        scopes=(_ALL_SCOPES,),
        source="env",
        owner_email="system@local",
        created_at=now,
        updated_at=now,
    )


def _load_json_dev_records(json_path: Path) -> tuple[_AdminKeyRecord, ...]:
    if not json_path.exists():
        msg = f"Admin keys JSON file was not found: {json_path}"
        raise ValueError(msg)
    if not json_path.is_file():
        msg = f"Admin keys JSON path must be a file: {json_path}"
        raise ValueError(msg)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = "Admin keys JSON root must be an object."
        raise ValueError(msg)
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list):
        msg = "Admin keys JSON must include `keys` array."
        raise ValueError(msg)

    records: list[_AdminKeyRecord] = []
    seen_key_ids: set[str] = set()
    for index, item in enumerate(raw_keys):
        context = f"keys[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object.")

        key_id = _read_non_empty_string(item, "key_id", context)
        if key_id in seen_key_ids:
            raise ValueError(f"{context}.key_id must be unique.")
        seen_key_ids.add(key_id)
        token = _read_non_empty_string(item, "token", context)
        is_superuser = _read_bool(item, "is_superuser", context)
        enabled = _read_bool(item, "enabled", context)
        scopes = _read_string_tuple(item, "scopes", context)
        product_scopes = _read_string_tuple(item, "product_scopes", context)
        owner_email = item.get("owner_email", "system@local")
        if not isinstance(owner_email, str) or not owner_email.strip():
            owner_email = "system@local"
        now = datetime.now(tz=UTC)

        records.append(
            _AdminKeyRecord(
                key_id=key_id,
                token=token,
                key_prefix=_build_key_prefix(token),
                is_superuser=is_superuser,
                enabled=enabled,
                product_scopes=product_scopes,
                scopes=scopes or ((_ALL_SCOPES,) if is_superuser else ()),
                source="json_dev",
                owner_email=owner_email.strip(),
                created_at=now,
                updated_at=now,
            )
        )

    return tuple(records)


def _to_metadata(record: _AdminKeyRecord) -> AdminKeyMetadata:
    return AdminKeyMetadata(
        key_id=record.key_id,
        key_prefix=record.key_prefix,
        is_superuser=record.is_superuser,
        enabled=record.enabled,
        product_scopes=record.product_scopes,
        scopes=record.scopes,
        source=record.source,
        effective_role=_derive_effective_role(record=record),
        owner_email=record.owner_email,
        created_at=record.created_at,
        updated_at=record.updated_at,
        tenant_id=getattr(record, "tenant_id", "default"),
    )


def _metadata_payload(record: _AdminKeyRecord) -> dict[str, object]:
    metadata = _to_metadata(record)
    return {
        "key_id": metadata.key_id,
        "key_prefix": metadata.key_prefix,
        "is_superuser": metadata.is_superuser,
        "enabled": metadata.enabled,
        "product_scopes": list(metadata.product_scopes),
        "scopes": list(metadata.scopes),
        "source": metadata.source,
        "effective_role": metadata.effective_role,
        "owner_email": metadata.owner_email,
        "created_at": metadata.created_at.isoformat(),
        "updated_at": metadata.updated_at.isoformat(),
    }


def _build_key_prefix(token: str) -> str:
    normalized = token.strip()
    if not normalized:
        return "empty"
    return normalized[: min(12, len(normalized))]


def _generate_admin_api_key_token() -> str:
    return "adcs_" + secrets.token_urlsafe(32)


def _generate_admin_session_token() -> str:
    return "sess_" + secrets.token_urlsafe(48)


def _normalize_string_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _ensure_superuser_scopes(scopes: tuple[str, ...]) -> tuple[str, ...]:
    if _ALL_SCOPES in scopes:
        return scopes
    return (_ALL_SCOPES, *scopes)


def _derive_effective_role(*, record: _AdminKeyRecord) -> str:
    if record.is_superuser:
        return "superuser"
    if "write:destructive" in record.scopes or "write:settings" in record.scopes:
        return "product-owner"
    if "write:ingestion" in record.scopes:
        return "operator"
    return "viewer"


def _read_non_empty_string(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string.")
    return value.strip()


def _read_bool(payload: dict[str, Any], key: str, context: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be boolean.")
    return value


def _read_string_tuple(payload: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
    raw_value = payload.get(key, [])
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ValueError(f"{context}.{key} must be an array of strings.")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.{key}[{index}] must be a non-empty string.")
        value = item.strip()
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)
