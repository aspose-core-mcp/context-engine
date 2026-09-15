from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_interactive_docs_are_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADCS_API_DOCS_ENABLED", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 200


def test_interactive_docs_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_API_DOCS_ENABLED", "true")
    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
