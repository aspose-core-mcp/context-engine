"""Unit tests for the helpers and pure functions in adcs.api.admin_auth.

Written to lift admin_auth.py line coverage from 73.71% to ≥80%.

These tests target:
- pure helpers (_hash_token, _build_key_prefix, _generate_*, _normalize_string_tuple,
  _ensure_superuser_scopes, _derive_effective_role, _read_*)
- _to_metadata / _metadata_payload / _map_pg_key_row
- _load_json_dev_records (multiple invalid-input branches)
- _load_env_record (empty token)
- AdminAuthService methods that don't require Postgres / Redis
  (create_key, set_key_enabled, update_key_scopes, list_key_audit, has_scope,
  authorize_mutation)
- _RedisSessionStore happy + error paths via in-memory Redis stub
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adcs.api.admin_auth import (
    AdminAuthError,
    AdminAuthService,
    AdminKeyAuditRecord,
    AdminKeyMetadata,
    AdminKeyPrincipal,
    PostgresAdminKeyStore,
    _AdminKeyRecord,
    _AdminSessionRecord,
    _build_key_prefix,
    _derive_effective_role,
    _ensure_superuser_scopes,
    _generate_admin_api_key_token,
    _generate_admin_session_token,
    _hash_token,
    _load_env_record,
    _load_json_dev_records,
    _map_pg_key_row,
    _metadata_payload,
    _normalize_string_tuple,
    _read_bool,
    _read_non_empty_string,
    _read_string_tuple,
    _RedisSessionStore,
    _to_metadata,
)
from adcs.config import AdminKeysSource, clear_settings_cache, get_settings

# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_hash_token_is_deterministic_sha256_hex() -> None:
    h = _hash_token("hello")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    assert h == _hash_token("hello")
    assert h != _hash_token("hello!")


def test_build_key_prefix_truncates_long_tokens_to_12() -> None:
    long_token = "adcs_aaaaaaaaaaaaaaaa"
    assert _build_key_prefix(long_token) == "adcs_aaaaaaa"


def test_build_key_prefix_returns_token_when_short() -> None:
    assert _build_key_prefix("xyz") == "xyz"


def test_build_key_prefix_handles_empty_via_strip() -> None:
    assert _build_key_prefix("   ") == "empty"
    assert _build_key_prefix("") == "empty"


def test_generate_admin_api_key_token_starts_with_adcs_prefix() -> None:
    token = _generate_admin_api_key_token()
    assert token.startswith("adcs_")
    assert len(token) > 20  # sanity


def test_generate_admin_session_token_starts_with_sess_prefix() -> None:
    token = _generate_admin_session_token()
    assert token.startswith("sess_")
    assert len(token) > 20


def test_normalize_string_tuple_strips_dedupes_drops_empty() -> None:
    assert _normalize_string_tuple(("a", " a ", "b", "", "  ", "c", "B")) == (
        "a",
        "b",
        "c",
        "B",
    )


def test_normalize_string_tuple_empty() -> None:
    assert _normalize_string_tuple(()) == ()


def test_ensure_superuser_scopes_adds_wildcard_when_missing() -> None:
    assert _ensure_superuser_scopes(("read:logs",)) == ("*", "read:logs")


def test_ensure_superuser_scopes_keeps_input_when_wildcard_present() -> None:
    assert _ensure_superuser_scopes(("*", "read:logs")) == ("*", "read:logs")


@pytest.mark.parametrize(
    ("is_superuser", "scopes", "expected_role"),
    [
        (True, (), "superuser"),
        (False, ("write:destructive",), "product-owner"),
        (False, ("write:settings",), "product-owner"),
        (False, ("write:ingestion",), "operator"),
        (False, ("read:logs",), "viewer"),
        (False, (), "viewer"),
    ],
)
def test_derive_effective_role_for_each_combination(
    is_superuser: bool, scopes: tuple[str, ...], expected_role: str
) -> None:
    record = _make_key_record(is_superuser=is_superuser, scopes=scopes)
    assert _derive_effective_role(record=record) == expected_role


def test_read_non_empty_string_happy_path() -> None:
    assert _read_non_empty_string({"k": "  v  "}, "k", "ctx") == "v"


@pytest.mark.parametrize(
    "bad",
    [
        {},  # missing
        {"k": ""},  # empty
        {"k": "   "},  # whitespace only
        {"k": 42},  # not a string
        {"k": None},
    ],
)
def test_read_non_empty_string_rejects_invalid_inputs(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"ctx\.k must be a non-empty string"):
        _read_non_empty_string(bad, "k", "ctx")


def test_read_bool_happy_path() -> None:
    assert _read_bool({"enabled": True}, "enabled", "ctx") is True
    assert _read_bool({"enabled": False}, "enabled", "ctx") is False


@pytest.mark.parametrize("bad_value", ["yes", 1, 0, None])
def test_read_bool_rejects_non_bool(bad_value: object) -> None:
    with pytest.raises(ValueError, match="must be boolean"):
        _read_bool({"enabled": bad_value}, "enabled", "ctx")


def test_read_string_tuple_default_when_missing_or_none() -> None:
    assert _read_string_tuple({}, "key", "ctx") == ()
    assert _read_string_tuple({"key": None}, "key", "ctx") == ()


def test_read_string_tuple_happy_strips_dedupes() -> None:
    payload = {"scopes": ["a", " a ", "b"]}
    assert _read_string_tuple(payload, "scopes", "ctx") == ("a", "b")


def test_read_string_tuple_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="must be an array of strings"):
        _read_string_tuple({"scopes": "not-a-list"}, "scopes", "ctx")


@pytest.mark.parametrize("bad", [None, 5, "", "  ", True])
def test_read_string_tuple_rejects_non_string_element(bad: object) -> None:
    with pytest.raises(ValueError, match=r"\[0\] must be a non-empty string"):
        _read_string_tuple({"scopes": [bad]}, "scopes", "ctx")


# ---------------------------------------------------------------------------
# _to_metadata / _metadata_payload / _map_pg_key_row
# ---------------------------------------------------------------------------


def test_to_metadata_includes_effective_role() -> None:
    record = _make_key_record(is_superuser=True)
    meta = _to_metadata(record)
    assert isinstance(meta, AdminKeyMetadata)
    assert meta.effective_role == "superuser"
    assert meta.key_id == record.key_id


def test_metadata_payload_contains_iso_timestamps_and_lists() -> None:
    record = _make_key_record(scopes=("write:ingestion",), product_scopes=("aspose.ocr",))
    payload = _metadata_payload(record)
    assert payload["scopes"] == ["write:ingestion"]
    assert payload["product_scopes"] == ["aspose.ocr"]
    # ISO8601 round-trip
    datetime.fromisoformat(str(payload["created_at"]))
    datetime.fromisoformat(str(payload["updated_at"]))


def test_map_pg_key_row_happy() -> None:
    now = datetime.now(tz=UTC)
    row = {
        "key_id": "k1",
        "token_hash": "deadbeef",
        "owner_email": "ops@example.com",
        "scopes_json": '["read:logs"]',
        "product_scopes_json": '["aspose.ocr"]',
        "is_superuser": False,
        "enabled": True,
        "source": "admin_api",
        "created_at": now,
        "updated_at": now,
    }
    rec = _map_pg_key_row(row)
    assert rec.key_id == "k1"
    assert rec.token == "deadbeef"
    assert rec.scopes == ("read:logs",)
    assert rec.product_scopes == ("aspose.ocr",)
    assert rec.key_prefix == "pg_hash"


def test_map_pg_key_row_handles_dict_scopes_already_parsed() -> None:
    now = datetime.now(tz=UTC)
    row = {
        "key_id": "k2",
        "token_hash": "h",
        "owner_email": "x@y",
        "scopes_json": ["a"],  # already a list
        "product_scopes_json": ["p"],
        "is_superuser": True,
        "enabled": True,
        "source": "admin_api",
        "created_at": now,
        "updated_at": now,
    }
    rec = _map_pg_key_row(row)
    assert rec.scopes == ("a",)
    assert rec.product_scopes == ("p",)


def test_map_pg_key_row_rejects_non_mapping() -> None:
    with pytest.raises(TypeError, match="Unexpected admin key row type"):
        _map_pg_key_row(["not", "a", "mapping"])


def test_map_pg_key_row_rejects_invalid_created_at() -> None:
    row = {
        "key_id": "k1",
        "token_hash": "h",
        "owner_email": "x@y",
        "scopes_json": "[]",
        "product_scopes_json": "[]",
        "is_superuser": False,
        "enabled": True,
        "source": "admin_api",
        "created_at": "not-a-datetime",
        "updated_at": datetime.now(tz=UTC),
    }
    with pytest.raises(TypeError, match="Invalid admin key created_at"):
        _map_pg_key_row(row)


def test_map_pg_key_row_rejects_invalid_updated_at() -> None:
    row = {
        "key_id": "k1",
        "token_hash": "h",
        "owner_email": "x@y",
        "scopes_json": "[]",
        "product_scopes_json": "[]",
        "is_superuser": False,
        "enabled": True,
        "source": "admin_api",
        "created_at": datetime.now(tz=UTC),
        "updated_at": "not-a-datetime",
    }
    with pytest.raises(TypeError, match="Invalid admin key updated_at"):
        _map_pg_key_row(row)


# ---------------------------------------------------------------------------
# _load_json_dev_records / _load_env_record
# ---------------------------------------------------------------------------


def _write_keys(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_key_dict(
    *,
    key_id: str = "k1",
    token: str = "tok-1",
    is_superuser: bool = False,
    enabled: bool = True,
    scopes: list[str] | None = None,
    product_scopes: list[str] | None = None,
    owner_email: str | None = "ops@example.com",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key_id": key_id,
        "token": token,
        "is_superuser": is_superuser,
        "enabled": enabled,
        "scopes": scopes or [],
        "product_scopes": product_scopes or [],
    }
    if owner_email is not None:
        item["owner_email"] = owner_email
    return item


def test_load_json_dev_records_happy(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(
        p,
        {
            "keys": [
                _make_key_dict(key_id="k1", token="t1"),
                _make_key_dict(
                    key_id="k2", token="t2", is_superuser=True, scopes=[]
                ),
            ]
        },
    )
    records = _load_json_dev_records(p)
    assert len(records) == 2
    assert records[0].key_id == "k1"
    assert records[1].is_superuser is True
    # a superuser gets '*' when scopes are empty
    assert records[1].scopes == ("*",)


def test_load_json_dev_records_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="was not found"):
        _load_json_dev_records(tmp_path / "missing.json")


def test_load_json_dev_records_path_is_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be a file"):
        _load_json_dev_records(tmp_path)


def test_load_json_dev_records_root_not_object(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, ["not", "an", "object"])
    with pytest.raises(ValueError, match="root must be an object"):
        _load_json_dev_records(p)


def test_load_json_dev_records_keys_not_array(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {"keys": "not-an-array"})
    with pytest.raises(ValueError, match=r"`keys` array"):
        _load_json_dev_records(p)


def test_load_json_dev_records_item_not_object(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(p, {"keys": ["scalar"]})
    with pytest.raises(ValueError, match=r"keys\[0\] must be an object"):
        _load_json_dev_records(p)


def test_load_json_dev_records_duplicate_key_id(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(
        p,
        {
            "keys": [
                _make_key_dict(key_id="dup", token="a"),
                _make_key_dict(key_id="dup", token="b"),
            ]
        },
    )
    with pytest.raises(ValueError, match="key_id must be unique"):
        _load_json_dev_records(p)


def test_load_json_dev_records_default_owner_email_when_blank(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    _write_keys(
        p,
        {
            "keys": [
                _make_key_dict(key_id="k1", token="t1", owner_email="   "),
                _make_key_dict(key_id="k2", token="t2", owner_email=None),
            ]
        },
    )
    records = _load_json_dev_records(p)
    assert records[0].owner_email == "system@local"
    assert records[1].owner_email == "system@local"


def test_load_env_record_rejects_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_API_KEY", "   ")
    clear_settings_cache()
    settings = get_settings()
    with pytest.raises(ValueError, match="ADCS_API_KEY must not be empty"):
        _load_env_record(settings=settings)


# ---------------------------------------------------------------------------
# _RedisSessionStore — uses an in-memory fake; no real Redis required.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Just enough Redis surface for _RedisSessionStore tests."""

    def __init__(self, *, fail_on_op: str | None = None) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.fail_on_op = fail_on_op

    def ping(self) -> bool:
        if self.fail_on_op == "ping":
            raise ConnectionError("redis ping failed")
        return True

    def setex(self, key: str, ttl: int, value: bytes) -> None:
        if self.fail_on_op == "setex":
            raise ConnectionError("redis setex failed")
        self.store[key] = value
        self.ttls[key] = ttl

    def get(self, key: str) -> bytes | None:
        if self.fail_on_op == "get":
            raise ConnectionError("redis get failed")
        return self.store.get(key)

    def delete(self, key: str) -> None:
        if self.fail_on_op == "delete":
            raise ConnectionError("redis delete failed")
        self.store.pop(key, None)
        self.ttls.pop(key, None)


def _make_session(
    token: str = "sess_xyz",
    *,
    expires_in_seconds: int = 60,
    key_id: str = "k1",
) -> _AdminSessionRecord:
    now = datetime.now(tz=UTC)
    from datetime import timedelta as _td

    return _AdminSessionRecord(
        token=token,
        key_id=key_id,
        created_at=now,
        expires_at=now + _td(seconds=expires_in_seconds),
        last_seen_at=now,
    )


def _build_redis_store_with(fake: _FakeRedis) -> _RedisSessionStore:
    """Construct _RedisSessionStore bypassing the real Redis import."""
    store = _RedisSessionStore.__new__(_RedisSessionStore)
    store._redis = fake  # type: ignore[attr-defined]
    store._available = True  # type: ignore[attr-defined]
    try:
        fake.ping()
    except Exception:
        store._available = False  # type: ignore[attr-defined]
    return store


def test_redis_session_store_unavailable_when_ping_fails() -> None:
    fake = _FakeRedis(fail_on_op="ping")
    store = _build_redis_store_with(fake)
    assert store.available is False
    # Operations are silent no-ops
    store.put(_make_session())
    assert store.get("sess_xyz") is None
    store.delete("sess_xyz")


def test_redis_session_store_put_get_delete_round_trip() -> None:
    fake = _FakeRedis()
    store = _build_redis_store_with(fake)
    sess = _make_session(token="sess_1")
    store.put(sess)
    assert "adcs:session:sess_1" in fake.store

    fetched = store.get("sess_1")
    assert fetched is not None
    assert fetched.token == "sess_1"
    assert fetched.key_id == "k1"

    store.delete("sess_1")
    assert "adcs:session:sess_1" not in fake.store


def test_redis_session_store_get_missing_returns_none() -> None:
    fake = _FakeRedis()
    store = _build_redis_store_with(fake)
    assert store.get("nope") is None


def test_redis_session_store_put_skips_when_ttl_non_positive() -> None:
    fake = _FakeRedis()
    store = _build_redis_store_with(fake)
    expired = _make_session(expires_in_seconds=-10)
    store.put(expired)
    assert fake.store == {}


def test_redis_session_store_put_handles_redis_error_silently() -> None:
    fake = _FakeRedis(fail_on_op="setex")
    store = _build_redis_store_with(fake)
    sess = _make_session()
    # Must not raise
    store.put(sess)


def test_redis_session_store_get_handles_redis_error_silently() -> None:
    fake = _FakeRedis(fail_on_op="get")
    store = _build_redis_store_with(fake)
    assert store.get("sess_xyz") is None


def test_redis_session_store_delete_handles_redis_error_silently() -> None:
    fake = _FakeRedis(fail_on_op="delete")
    store = _build_redis_store_with(fake)
    # Must not raise
    store.delete("sess_xyz")


def test_redis_session_store_touch_calls_put() -> None:
    fake = _FakeRedis()
    store = _build_redis_store_with(fake)
    sess = _make_session(token="sess_touch")
    store.touch(sess)
    assert "adcs:session:sess_touch" in fake.store


def test_redis_session_store_key_prefix() -> None:
    fake = _FakeRedis()
    store = _build_redis_store_with(fake)
    assert store._key("abc") == "adcs:session:abc"


# ---------------------------------------------------------------------------
# AdminAuthService method tests (in-memory; PG fallback path).
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AdminAuthService:
    """Build an AdminAuthService using a tmp JSON keys file.

    Postgres + Redis init fail silently (env defaults are unreachable in tests),
    so the service falls back to its in-memory cache. That keeps the unit-test
    surface focused on the service's own code paths.
    """
    keys_path = tmp_path / "admin_keys.json"
    _write_keys(
        keys_path,
        {
            "keys": [
                _make_key_dict(
                    key_id="seed-superuser",
                    token="seed-su-token",
                    is_superuser=True,
                ),
                _make_key_dict(
                    key_id="seed-operator",
                    token="seed-op-token",
                    scopes=["write:ingestion"],
                    product_scopes=["aspose.ocr"],
                ),
                _make_key_dict(
                    key_id="seed-disabled",
                    token="seed-disabled-token",
                    enabled=False,
                    scopes=["read:logs"],
                    product_scopes=["aspose.ocr"],
                ),
            ]
        },
    )
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))
    # Bogus Postgres/Redis URLs so init falls back.
    monkeypatch.setenv("ADCS_POSTGRES_DSN", "postgresql+psycopg://ghost@127.0.0.1:1/none")
    monkeypatch.setenv("ADCS_REDIS_URL", "redis://127.0.0.1:1/0")
    clear_settings_cache()
    return AdminAuthService(settings=get_settings())


def test_authenticate_rejects_missing_key(auth_service: AdminAuthService) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate(api_key=None)
    assert exc.value.status_code == 401
    assert exc.value.code == "UNAUTHORIZED"


def test_authenticate_rejects_invalid_key(auth_service: AdminAuthService) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate(api_key="nope")
    assert exc.value.status_code == 401


def test_authenticate_rejects_disabled_key(auth_service: AdminAuthService) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate(api_key="seed-disabled-token")
    assert exc.value.status_code == 403


def test_authenticate_request_uses_api_key_when_present(
    auth_service: AdminAuthService,
) -> None:
    principal = auth_service.authenticate_request(
        api_key="seed-su-token", session_token=None
    )
    assert principal.is_superuser is True


def test_authenticate_request_rejects_when_no_credentials(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate_request(api_key=None, session_token=None)
    assert exc.value.status_code == 401


def test_create_session_and_authenticate_session_round_trip(
    auth_service: AdminAuthService,
) -> None:
    token = auth_service.create_session(key_id="seed-superuser", ttl_seconds=60)
    assert token.startswith("sess_")
    principal = auth_service.authenticate_session(session_token=token)
    assert principal.key_id == "seed-superuser"
    assert principal.source.endswith(":session_cookie")


def test_authenticate_session_rejects_blank_token(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate_session(session_token="   ")
    assert exc.value.status_code == 401


def test_authenticate_session_rejects_unknown_token(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(AdminAuthError) as exc:
        auth_service.authenticate_session(session_token="sess_unknown")
    assert exc.value.status_code == 401


def test_revoke_session_silent_on_blank_or_none(
    auth_service: AdminAuthService,
) -> None:
    auth_service.revoke_session(session_token=None)
    auth_service.revoke_session(session_token="   ")
    # No exceptions; no state corrupted
    token = auth_service.create_session(key_id="seed-superuser", ttl_seconds=60)
    auth_service.revoke_session(session_token=token)
    with pytest.raises(AdminAuthError):
        auth_service.authenticate_session(session_token=token)


def test_create_key_superuser_normalises_scopes(
    auth_service: AdminAuthService,
) -> None:
    metadata, token = auth_service.create_key(
        is_superuser=True,
        product_scopes=(),
        scopes=("read:logs",),
        enabled=True,
        owner_email="alice@example.com",
        actor_key_id="seed-superuser",
        request_id=None,
        reason="initial bootstrap",
    )
    assert metadata.is_superuser is True
    assert "*" in metadata.scopes
    assert token.startswith("adcs_")


def test_create_key_non_superuser_requires_product_scope(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(ValueError, match="must include at least one product scope"):
        auth_service.create_key(
            is_superuser=False,
            product_scopes=(),
            scopes=("write:ingestion",),
            enabled=True,
            owner_email="ops@example.com",
            actor_key_id="seed-superuser",
            request_id=None,
            reason=None,
        )


def test_set_key_enabled_emits_audit(auth_service: AdminAuthService) -> None:
    audits_before = len(auth_service.list_key_audit())
    metadata = auth_service.set_key_enabled(
        key_id="seed-disabled",
        enabled=True,
        actor_key_id="seed-superuser",
        request_id="req-1",
        reason="re-enable for test",
    )
    assert metadata.enabled is True
    audits = auth_service.list_key_audit()
    assert len(audits) == audits_before + 1
    assert audits[0].action == "enable"


def test_set_key_enabled_no_op_when_state_matches(
    auth_service: AdminAuthService,
) -> None:
    audits_before = len(auth_service.list_key_audit())
    metadata = auth_service.set_key_enabled(
        key_id="seed-operator",  # already enabled
        enabled=True,
        actor_key_id="seed-superuser",
        request_id=None,
        reason=None,
    )
    assert metadata.enabled is True
    # No audit recorded
    assert len(auth_service.list_key_audit()) == audits_before


def test_set_key_enabled_unknown_key_raises_keyerror(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(KeyError):
        auth_service.set_key_enabled(
            key_id="missing",
            enabled=False,
            actor_key_id="seed-superuser",
            request_id=None,
            reason=None,
        )


def test_update_key_scopes_normalises_and_audits(
    auth_service: AdminAuthService,
) -> None:
    metadata = auth_service.update_key_scopes(
        key_id="seed-operator",
        product_scopes=("aspose.ocr", " aspose.ocr ", "groupdocs.parser"),
        scopes=("write:ingestion",),
        actor_key_id="seed-superuser",
        request_id=None,
        reason="add second product",
    )
    assert metadata.product_scopes == ("aspose.ocr", "groupdocs.parser")
    assert "write:ingestion" in metadata.scopes


def test_update_key_scopes_non_superuser_requires_product_scope(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(ValueError):
        auth_service.update_key_scopes(
            key_id="seed-operator",
            product_scopes=(),
            scopes=("write:ingestion",),
            actor_key_id="seed-superuser",
            request_id=None,
            reason=None,
        )


def test_update_key_scopes_unknown_key_raises_keyerror(
    auth_service: AdminAuthService,
) -> None:
    with pytest.raises(KeyError):
        auth_service.update_key_scopes(
            key_id="missing",
            product_scopes=("aspose.ocr",),
            scopes=("write:ingestion",),
            actor_key_id="seed-superuser",
            request_id=None,
            reason=None,
        )


def test_authorize_mutation_allows_superuser(auth_service: AdminAuthService) -> None:
    principal = auth_service.authenticate(api_key="seed-su-token")
    auth_service.authorize_mutation(
        principal=principal,
        required_scope="write:destructive",
        target_product_ids=("aspose.ocr",),
        destructive=True,
    )  # must not raise


def test_authorize_mutation_rejects_missing_scope(
    auth_service: AdminAuthService,
) -> None:
    principal = auth_service.authenticate(api_key="seed-op-token")
    with pytest.raises(AdminAuthError, match="Missing required scope: write:destructive"):
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:destructive",
            target_product_ids=("aspose.ocr",),
            destructive=False,
        )


def test_authorize_mutation_rejects_destructive_without_destructive_scope(
    auth_service: AdminAuthService,
) -> None:
    principal = auth_service.authenticate(api_key="seed-op-token")
    with pytest.raises(AdminAuthError, match="write:destructive"):
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=("aspose.ocr",),
            destructive=True,
        )


def test_authorize_mutation_rejects_product_scope_violation(
    auth_service: AdminAuthService,
) -> None:
    principal = auth_service.authenticate(api_key="seed-op-token")
    with pytest.raises(AdminAuthError, match="Product scope violation"):
        auth_service.authorize_mutation(
            principal=principal,
            required_scope="write:ingestion",
            target_product_ids=("groupdocs.parser",),
        )


def test_has_scope_for_wildcard_principal() -> None:
    principal = AdminKeyPrincipal(
        key_id="x",
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("*",),
        source="json_dev",
        effective_role="superuser",
    )
    # Build a service via fixture is overkill — we only need has_scope behavior.
    # Instead exercise via a minimal stub.
    from adcs.api.admin_auth import AdminAuthService as _Svc

    assert _Svc.has_scope(_Svc, principal=principal, scope="anything")  # type: ignore[arg-type]


def test_list_key_audit_orders_newest_first(auth_service: AdminAuthService) -> None:
    auth_service.set_key_enabled(
        key_id="seed-disabled",
        enabled=True,
        actor_key_id="seed-superuser",
        request_id=None,
        reason=None,
    )
    auth_service.set_key_enabled(
        key_id="seed-disabled",
        enabled=False,
        actor_key_id="seed-superuser",
        request_id=None,
        reason=None,
    )
    audits = auth_service.list_key_audit(limit=10)
    actions = [a.action for a in audits]
    assert actions[:2] == ["disable", "enable"]


def test_list_key_metadata_ordered(auth_service: AdminAuthService) -> None:
    metadata = auth_service.list_key_metadata()
    key_ids = [m.key_id for m in metadata]
    assert "seed-superuser" in key_ids
    assert "seed-operator" in key_ids
    assert "seed-disabled" in key_ids


def test_get_key_metadata_known_and_unknown(auth_service: AdminAuthService) -> None:
    assert auth_service.get_key_metadata(key_id="seed-superuser") is not None
    assert auth_service.get_key_metadata(key_id="missing") is None


def test_get_internal_record_known_and_unknown(auth_service: AdminAuthService) -> None:
    assert auth_service.get_internal_record(key_id="seed-superuser") is not None
    assert auth_service.get_internal_record(key_id="missing") is None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_key_record(
    *,
    key_id: str = "k1",
    token: str = "tok",
    is_superuser: bool = False,
    enabled: bool = True,
    scopes: tuple[str, ...] = (),
    product_scopes: tuple[str, ...] = (),
    owner_email: str = "ops@example.com",
) -> _AdminKeyRecord:
    now = datetime.now(tz=UTC)
    return _AdminKeyRecord(
        key_id=key_id,
        token=token,
        key_prefix=_build_key_prefix(token),
        is_superuser=is_superuser,
        enabled=enabled,
        product_scopes=product_scopes,
        scopes=scopes,
        source="json_dev",
        owner_email=owner_email,
        created_at=now,
        updated_at=now,
    )


# Suppress unused-import warning for typing-only helpers.
_ = (Iterable, AdminKeyAuditRecord, PostgresAdminKeyStore, AdminKeysSource)
