"""Tests for the AdminKeyPrincipal tenant_id field.

The principal's `tenant_id` is the bridge between the auth layer and
the rest of the multi-tenant infrastructure (Redis keyspace, retrieval
lane filter, audit log). This test surface verifies:

* default-value semantics (legacy keys → `"default"`);
* explicit tenant_id propagates from create_key → record → principal → metadata;
* every existing single-arg construction still works (backward compatibility).
"""

from __future__ import annotations

from datetime import UTC, datetime

from adcs.api.admin_auth import (
    AdminKeyMetadata,
    AdminKeyPrincipal,
    _AdminKeyRecord,
)

# ---------------------------------------------------------------------------
# Default-value semantics
# ---------------------------------------------------------------------------


def test_principal_defaults_to_default_tenant() -> None:
    """Legacy AdminKeyPrincipal construction (no tenant_id arg) → default."""
    principal = AdminKeyPrincipal(
        key_id="k-1",
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        source="api",
        effective_role="VIEWER",
    )
    assert principal.tenant_id == "default"


def test_principal_accepts_explicit_tenant_id() -> None:
    principal = AdminKeyPrincipal(
        key_id="k-1",
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        source="api",
        effective_role="VIEWER",
        tenant_id="t-acme",
    )
    assert principal.tenant_id == "t-acme"


def test_metadata_defaults_to_default_tenant() -> None:
    now = datetime.now(tz=UTC)
    metadata = AdminKeyMetadata(
        key_id="k-1",
        key_prefix="adcs_xx",
        is_superuser=False,
        enabled=True,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        source="api",
        effective_role="VIEWER",
        owner_email="x@y.z",
        created_at=now,
        updated_at=now,
    )
    assert metadata.tenant_id == "default"


def test_internal_record_defaults_to_default_tenant() -> None:
    now = datetime.now(tz=UTC)
    record = _AdminKeyRecord(
        key_id="k-1",
        token="adcs_xxxxxxxxxxxxxxxxx",
        key_prefix="adcs_xx",
        is_superuser=False,
        enabled=True,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        source="api",
        owner_email="x@y.z",
        created_at=now,
        updated_at=now,
    )
    assert record.tenant_id == "default"


# ---------------------------------------------------------------------------
# Propagation through admin auth service
# ---------------------------------------------------------------------------


def test_create_key_propagates_explicit_tenant_id_to_metadata() -> None:
    from adcs.api.admin_auth import AdminAuthService
    from adcs.config import get_settings

    settings = get_settings()
    service = AdminAuthService(settings=settings)
    metadata, _token = service.create_key(
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        enabled=True,
        owner_email="x@y.z",
        actor_key_id="bootstrap",
        request_id=None,
        reason=None,
        tenant_id="t-acme",
    )
    assert metadata.tenant_id == "t-acme"


def test_create_key_without_tenant_id_defaults_to_default() -> None:
    from adcs.api.admin_auth import AdminAuthService
    from adcs.config import get_settings

    settings = get_settings()
    service = AdminAuthService(settings=settings)
    metadata, _token = service.create_key(
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        enabled=True,
        owner_email="x@y.z",
        actor_key_id="bootstrap",
        request_id=None,
        reason=None,
    )
    assert metadata.tenant_id == "default"


def test_create_key_normalises_blank_tenant_id_to_default() -> None:
    """Whitespace-only / empty tenant_id collapses to the implicit default."""
    from adcs.api.admin_auth import AdminAuthService
    from adcs.config import get_settings

    settings = get_settings()
    service = AdminAuthService(settings=settings)
    metadata, _token = service.create_key(
        is_superuser=False,
        product_scopes=("aspose.ocr",),
        scopes=("read:analytics",),
        enabled=True,
        owner_email="x@y.z",
        actor_key_id="bootstrap",
        request_id=None,
        reason=None,
        tenant_id="   ",
    )
    assert metadata.tenant_id == "default"
