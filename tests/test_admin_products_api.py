from __future__ import annotations

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


def test_admin_products_list_returns_catalog_rows() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/products", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert any(row["product_id"] == "aspose.ocr" for row in payload)
    assert any(row["product_id"] == "aspose.words" for row in payload)
    assert any(row["product_id"] == "aspose.pdf" for row in payload)
    assert any(row["product_id"] == "aspose.email" for row in payload)
    aspose_row = next(row for row in payload if row["product_id"] == "aspose.ocr")
    assert set(aspose_row["source_kinds"]) == {"apiref", "docs"}
    assert aspose_row["repositories_count"] >= 2


def test_admin_products_filter_by_product_id() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/admin/v1/products?product_id=aspose.ocr",
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["product_id"] == "aspose.ocr"
