from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache

ADMIN_HEADERS = {"x-api-key": "replace-me"}

_ROW_KEYS = {
    "product_id",
    "product_name",
    "family",
    "docs_chunks",
    "apiref_symbols",
    "docs_repo",
    "apiref_repo",
    "gaps",
}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_product_coverage_lists_every_registered_product() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/product-coverage", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    rows = payload["rows"]
    assert rows, "expected one coverage row per registered product"

    product_ids = {row["product_id"] for row in rows}
    # Registry-driven: real catalog products + the newly-registered apiref repos.
    assert {"aspose.words", "aspose.llm", "aspose.drawing", "aspose.gis"} <= product_ids

    for row in rows:
        assert _ROW_KEYS <= set(row)
        assert isinstance(row["gaps"], list)
        assert row["docs_chunks"] >= 0
        assert row["apiref_symbols"] >= 0
        assert row["family"] in {"aspose", "groupdocs"}

    summary = payload["summary"]
    assert summary["total_products"] == len(rows)
    assert summary["products_with_docs"] == sum(1 for r in rows if r["docs_chunks"] > 0)
    assert summary["products_with_apiref"] == sum(1 for r in rows if r["apiref_symbols"] > 0)
    assert payload["generated_at"]


def test_product_coverage_requires_admin_auth() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/admin/v1/product-coverage")

    assert response.status_code in (401, 403)
