from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache

ADMIN_HEADERS = {"x-api-key": "replace-me"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_admin_howto_api_supports_draft_publish_and_public_feed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "ADCS_HOWTO_OVERRIDE_STORE_PATH",
        str(tmp_path / "howto-overrides.json"),
    )
    monkeypatch.setenv(
        "ADCS_HOWTO_ASSET_ROOT",
        str(tmp_path / "howto-assets"),
    )

    app = create_app()
    with TestClient(app) as client:
        draft_response = client.put(
            "/admin/v1/howto/articles/admin-health/draft",
            headers=ADMIN_HEADERS,
            json={
                "entry_label": {"en": "Health", "ru": "Состояние системы"},
                "title": {"en": "Health Runbook", "ru": "Health runbook"},
                "summary": {
                    "en": "Used for health checks.",
                    "ru": "Используется для health checks.",
                },
                "purpose": {"en": ["Confirm readiness"], "ru": ["Подтвердить readiness"]},
                "workflow": {
                    "en": ["Open page", "Review cards"],
                    "ru": ["Открыть страницу", "Проверить карточки"],
                },
                "callouts": [
                    {
                        "id": "callout-1",
                        "level": "warning",
                        "title": {"en": "Stop on red", "ru": "Остановитесь при красном"},
                        "body": {"en": ["Investigate first"], "ru": ["Сначала разберитесь"]},
                    }
                ],
                "commands": [
                    {
                        "id": "command-1",
                        "label": {"en": "Run gates", "ru": "Запустить gates"},
                        "description": {
                            "en": "Useful after large UI changes",
                            "ru": "Полезно после крупных UI-изменений",
                        },
                        "command": "make admin-ui-regression-gates",
                    }
                ],
                "examples": [
                    {
                        "id": "example-1",
                        "title": {"en": "Before publish", "ru": "Перед publish"},
                        "bullets": {"en": ["Check readiness"], "ru": ["Проверьте readiness"]},
                    }
                ],
                "screenshots": [
                    {
                        "id": "shot-1",
                        "src": "/howto/screenshots/admin-health.png",
                        "alt": {"en": "Health screen", "ru": "Экран health"},
                        "caption": {"en": "Health view", "ru": "Экран health"},
                    }
                ],
            },
        )

        assert draft_response.status_code == 200
        draft_payload = draft_response.json()
        assert draft_payload["article_id"] == "admin-health"
        assert draft_payload["draft"]["examples"][0]["id"] == "example-1"
        assert draft_payload["published"] is None

        publish_response = client.post(
            "/admin/v1/howto/articles/admin-health:publish",
            headers=ADMIN_HEADERS,
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["published"]["title"]["en"] == "Health Runbook"

        admin_list_response = client.get(
            "/admin/v1/howto/articles",
            headers=ADMIN_HEADERS,
        )
        assert admin_list_response.status_code == 200
        assert admin_list_response.json()["records"][0]["article_id"] == "admin-health"

        public_response = client.get("/v1/howto/articles")
        assert public_response.status_code == 200
        assert public_response.json()["articles"][0]["article_id"] == "admin-health"
        assert (
            public_response.json()["articles"][0]["published"]["commands"][0]["command"]
            == "make admin-ui-regression-gates"
        )

        clear_response = client.post(
            "/admin/v1/howto/articles/admin-health:clear-published",
            headers=ADMIN_HEADERS,
        )
        assert clear_response.status_code == 200
        assert clear_response.json()["published"] is None


def test_admin_howto_asset_upload_exposes_public_asset_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "ADCS_HOWTO_OVERRIDE_STORE_PATH",
        str(tmp_path / "howto-overrides.json"),
    )
    monkeypatch.setenv(
        "ADCS_HOWTO_ASSET_ROOT",
        str(tmp_path / "howto-assets"),
    )

    app = create_app()
    with TestClient(app) as client:
        upload_response = client.post(
            "/admin/v1/howto/assets:upload",
            headers=ADMIN_HEADERS,
            json={
                "filename": "demo.png",
                "content_base64": base64.b64encode(b"demo-image-bytes").decode("ascii"),
            },
        )

        assert upload_response.status_code == 200
        payload = upload_response.json()
        assert payload["asset_name"].endswith("-demo.png")
        assert payload["size_bytes"] == len(b"demo-image-bytes")

        asset_response = client.get(payload["asset_url"])
        assert asset_response.status_code == 200
        assert asset_response.content == b"demo-image-bytes"
