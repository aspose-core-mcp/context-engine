from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_admin_keys(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "superuser-key",
                        "token": "superuser-token",
                        "is_superuser": True,
                        "enabled": True,
                        "product_scopes": [],
                        "scopes": ["*"],
                    },
                    {
                        "key_id": "product-owner-key",
                        "token": "product-owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:settings", "write:ingestion"],
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _configure_json_dev_keys(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    keys_path = tmp_path / "admin_keys.json"
    _write_admin_keys(keys_path)
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def test_admin_keys_create_disable_and_audit_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": ["write:ingestion"],
                "owner_email": "operator@example.com",
                "reason": "create operator key",
            },
        )
        assert created.status_code == 200
        created_body = created.json()
        created_key_id = created_body["key"]["key_id"]
        created_api_key = created_body["api_key"]
        assert created_api_key.startswith("adcs_")
        assert created_body["key"]["owner_email"] == "operator@example.com"

        listed = client.get("/admin/v1/keys", headers={"x-api-key": "superuser-token"})
        assert listed.status_code == 200
        assert any(item["key_id"] == created_key_id for item in listed.json())

        session_before_disable = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": created_api_key},
        )
        assert session_before_disable.status_code == 200
        assert session_before_disable.json()["key_id"] == created_key_id

        disabled = client.post(
            f"/admin/v1/keys/{created_key_id}:disable",
            headers={"x-api-key": "superuser-token"},
            json={"reason": "incident response"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        session_after_disable = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": created_api_key},
        )
        assert session_after_disable.status_code == 403
        assert session_after_disable.json()["detail"]["error"]["code"] == "FORBIDDEN"

        audit = client.get("/admin/v1/keys/audit", headers={"x-api-key": "superuser-token"})
        assert audit.status_code == 200
        actions_for_key = [
            item["action"] for item in audit.json() if item["target_key_id"] == created_key_id
        ]
        assert "create" in actions_for_key
        assert "disable" in actions_for_key


def test_admin_keys_scope_guard_for_product_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        product_scope_violation = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "product-owner-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["groupdocs.parser"],
                "scopes": ["write:ingestion"],
                "owner_email": "test@example.com",
            },
        )
        assert product_scope_violation.status_code == 403
        assert (
            "Product scope violation"
            in product_scope_violation.json()["detail"]["error"]["message"]
        )

        superuser_violation = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "product-owner-token"},
            json={
                "is_superuser": True,
                "enabled": True,
                "product_scopes": [],
                "scopes": ["*"],
                "owner_email": "test@example.com",
            },
        )
        assert superuser_violation.status_code == 403
        assert "Only superuser can create superuser keys." in (
            superuser_violation.json()["detail"]["error"]["message"]
        )

        write_escalation_violation = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "product-owner-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": ["write:destructive"],
                "owner_email": "test@example.com",
            },
        )
        assert write_escalation_violation.status_code == 403
        assert "Cannot grant scope `write:destructive`" in (
            write_escalation_violation.json()["detail"]["error"]["message"]
        )


def test_admin_keys_update_scopes_and_enable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": [],
                "owner_email": "viewer@example.com",
            },
        )
        assert created.status_code == 200
        key_id = created.json()["key"]["key_id"]
        issued_key = created.json()["api_key"]

        session_before = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": issued_key},
        )
        assert session_before.status_code == 200
        assert session_before.json()["scopes"] == []

        updated_scopes = client.patch(
            f"/admin/v1/keys/{key_id}/scopes",
            headers={"x-api-key": "product-owner-token"},
            json={
                "product_scopes": ["aspose.ocr"],
                "scopes": ["write:ingestion"],
                "reason": "delegation update",
            },
        )
        assert updated_scopes.status_code == 200
        assert updated_scopes.json()["scopes"] == ["write:ingestion"]

        disabled = client.post(
            f"/admin/v1/keys/{key_id}:disable",
            headers={"x-api-key": "product-owner-token"},
            json={"reason": "temporary block"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        enabled = client.post(
            f"/admin/v1/keys/{key_id}:enable",
            headers={"x-api-key": "product-owner-token"},
            json={"reason": "restore access"},
        )
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True


def test_admin_keys_rotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        # Create a key to rotate
        created = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": ["write:ingestion"],
                "owner_email": "rotate@example.com",
                "reason": "key to rotate",
            },
        )
        assert created.status_code == 200
        old_key_id = created.json()["key"]["key_id"]
        old_api_key = created.json()["api_key"]

        # Rotate the key
        rotated = client.post(
            f"/admin/v1/keys/{old_key_id}:rotate",
            headers={"x-api-key": "superuser-token"},
            json={"reason": "quarterly rotation"},
        )
        assert rotated.status_code == 200
        rotated_body = rotated.json()
        new_key_id = rotated_body["key"]["key_id"]
        new_api_key = rotated_body["api_key"]

        assert new_key_id != old_key_id
        assert new_api_key != old_api_key
        assert rotated_body["key"]["owner_email"] == "rotate@example.com"
        assert rotated_body["key"]["enabled"] is True
        assert rotated_body["key"]["scopes"] == ["write:ingestion"]
        assert rotated_body["key"]["product_scopes"] == ["aspose.ocr"]

        # Old key should be disabled
        old_key_meta = client.get(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
        )
        old_key = next(
            item for item in old_key_meta.json() if item["key_id"] == old_key_id
        )
        assert old_key["enabled"] is False

        # New key should work
        session_check = client.get(
            "/admin/v1/system/session",
            headers={"x-api-key": new_api_key},
        )
        assert session_check.status_code == 200


def test_admin_keys_export_and_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        # Create a key first
        client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": ["write:ingestion"],
                "owner_email": "export@example.com",
            },
        )

        # Export
        exported = client.get(
            "/admin/v1/keys:export",
            headers={"x-api-key": "superuser-token"},
        )
        assert exported.status_code == 200
        export_data = exported.json()
        assert len(export_data) >= 3  # 2 seed + 1 created
        # Should not contain api_key / token
        for item in export_data:
            assert "api_key" not in item
            assert "token" not in item
            assert "owner_email" in item

        # Import
        imported = client.post(
            "/admin/v1/keys:import",
            headers={"x-api-key": "superuser-token"},
            json=[
                {
                    "is_superuser": False,
                    "enabled": True,
                    "product_scopes": ["aspose.ocr"],
                    "scopes": ["write:ingestion"],
                    "owner_email": "imported@example.com",
                    "reason": "imported key",
                },
                {
                    "is_superuser": False,
                    "enabled": True,
                    "product_scopes": ["aspose.ocr"],
                    "scopes": [],
                    "owner_email": "imported2@example.com",
                },
            ],
        )
        assert imported.status_code == 200
        imported_keys = imported.json()["keys"]
        assert len(imported_keys) == 2
        assert imported_keys[0]["key"]["owner_email"] == "imported@example.com"
        assert imported_keys[1]["key"]["owner_email"] == "imported2@example.com"
        # Each imported key should have a valid api_key
        assert imported_keys[0]["api_key"].startswith("adcs_")
        assert imported_keys[1]["api_key"].startswith("adcs_")


def test_admin_keys_create_requires_owner_email(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        # Missing owner_email should fail (app returns 400 via custom error handler)
        response = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": [],
            },
        )
        assert response.status_code in (400, 422)

        # Invalid email should fail
        response = client.post(
            "/admin/v1/keys",
            headers={"x-api-key": "superuser-token"},
            json={
                "is_superuser": False,
                "enabled": True,
                "product_scopes": ["aspose.ocr"],
                "scopes": [],
                "owner_email": "not-an-email",
            },
        )
        assert response.status_code in (400, 422)
