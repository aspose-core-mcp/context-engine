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


def _configure_json_dev_keys(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    keys_path = tmp_path / "admin_keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:settings"],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def test_retrieval_settings_rollback_restores_previous_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        first_update = client.patch(
            "/admin/v1/settings/retrieval/aspose.ocr",
            json={
                "top_k": 12,
                "max_context_tokens": 4096,
                "excerpt_char_limit": 900,
                "low_confidence_threshold": 0.42,
                "clarification_policy": "always_prompt",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert first_update.status_code == 200

        second_update = client.patch(
            "/admin/v1/settings/retrieval/aspose.ocr",
            json={
                "top_k": 5,
                "max_context_tokens": 4096,
                "excerpt_char_limit": 700,
                "low_confidence_threshold": 0.25,
                "clarification_policy": "ask_user_followup",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert second_update.status_code == 200
        assert second_update.json()["top_k"] == 5

        history = client.get(
            "/admin/v1/config/history?product_id=aspose.ocr&config_scope=retrieval_settings",
            headers={"x-api-key": "owner-token"},
        )
        assert history.status_code == 200
        history_items = history.json()
        assert history_items

        rolled_change_id = history_items[0]["change_id"]
        rollback = client.post(
            "/admin/v1/config/rollback",
            json={"change_id": rolled_change_id, "reason": "rollback test"},
            headers={"x-api-key": "owner-token"},
        )
        assert rollback.status_code == 200

        settings_after = client.get(
            "/admin/v1/settings/retrieval/aspose.ocr",
            headers={"x-api-key": "owner-token"},
        )
        assert settings_after.status_code == 200
        assert settings_after.json()["top_k"] == 12


def test_language_alias_rollback_restores_previous_mapping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        create_alias = client.post(
            "/admin/v1/registries/languages/aliases",
            json={
                "product_id": "aspose.ocr",
                "external_language_id": "dotnet",
                "canonical_lang_id": "net",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert create_alias.status_code == 200

        update_alias = client.post(
            "/admin/v1/registries/languages/aliases",
            json={
                "product_id": "aspose.ocr",
                "external_language_id": "dotnet",
                "canonical_lang_id": "java",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert update_alias.status_code == 200
        assert update_alias.json()["canonical_lang_id"] == "java"

        history = client.get(
            "/admin/v1/config/history?product_id=aspose.ocr&config_scope=language_alias",
            headers={"x-api-key": "owner-token"},
        )
        assert history.status_code == 200
        history_items = history.json()
        assert history_items

        rollback = client.post(
            "/admin/v1/config/rollback",
            json={"change_id": history_items[0]["change_id"], "reason": "restore alias"},
            headers={"x-api-key": "owner-token"},
        )
        assert rollback.status_code == 200

        aliases = client.get(
            "/admin/v1/registries/languages/aliases?product_id=aspose.ocr",
            headers={"x-api-key": "owner-token"},
        )
        assert aliases.status_code == 200
        assert aliases.json()[0]["canonical_lang_id"] == "net"
