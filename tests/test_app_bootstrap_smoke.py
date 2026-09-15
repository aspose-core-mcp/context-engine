"""Bootstrap smoke test for ``create_app`` in ``src/adcs/api/main.py``.

``create_app()`` mounts the ``product_coverage`` router (which backs the admin
Catalog Matrix page) in the same body that defines the core ops routes. This
test asserts that the app constructs and that BOTH the product-coverage route
AND the core ops routes are simultaneously mounted and reachable.

Why TestClient status codes and not route introspection:
``create_app`` calls ``app.include_router(...)`` for every sub-router. On
FastAPI 0.138 those mounts are realized as ``_IncludedRouter`` objects that do
NOT expose a ``.path`` attribute, so the otherwise-tempting
``{route.path for route in app.router.routes}`` set-comprehension raises
``AttributeError`` (a FastAPI-version behavior). We deliberately avoid that
pattern and probe behavior through HTTP status codes instead, which keeps this
smoke test independent of FastAPI internals while still proving the routers
are wired.

Backend note: ``conftest._default_test_runtime_env`` sets
``ADCS_PERSISTENCE_BACKEND=auto`` / ``ADCS_RETRIEVAL_BACKEND=auto``; with
``pytest`` in ``sys.modules`` the adapter resolver
(``src/adcs/runtime/adapter_resolution.py``) forces in-memory backends, so
``create_app()`` constructs without a live Qdrant/OpenSearch/Postgres.
``ADCS_VALIDATE_SOURCE_SUBMODULES=false`` is required because serving/CI
checkouts (and any checkout cloned without submodules) don't carry the source
submodules. A module-scoped autouse fixture sets it — and restores the prior
value on teardown — before ``create_app`` builds the source registry, so the
override never leaks into other test modules.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app

# The router mount (admin "Catalog Matrix" / product coverage) under test, plus
# representative core ops routes from the base app body. Asserting all three are
# reachable proves create_app mounts both the included router and the core routes.
PRODUCT_COVERAGE_PATH = "/admin/v1/product-coverage"
CORE_OPS_PATHS = ("/healthz", "/readyz")

# product-coverage is guarded by ``Depends(require_admin_principal)``; with no
# ``x-api-key`` / session cookie the auth dependency raises 401. The contract we
# pin is "the route EXISTS and is mounted" — i.e. anything but 404. We accept
# 200 (somehow authorized) or 401/403 (auth gate fired), and explicitly reject
# 404 (router was not mounted).
_MOUNTED_NOT_404 = {200, 401, 403}


@pytest.fixture(scope="module", autouse=True)
def _disable_submodule_validation() -> None:
    """Turn off on-disk submodule validation for THIS module only, leak-free.

    ``create_app`` builds the source registry, which by default validates that
    each repo's submodule path exists on disk — a check serving/CI checkouts
    can't satisfy. We set ``ADCS_VALIDATE_SOURCE_SUBMODULES=false`` for the
    module's duration and restore the prior value on teardown, so the override
    never escapes into sibling test modules. (An unscoped ``os.environ`` write
    at import time would leak ``false``, flipping the default for
    ``test_source_registry_service`` under full-suite collection order.)
    """
    key = "ADCS_VALIDATE_SOURCE_SUBMODULES"
    previous = os.environ.get(key)
    os.environ[key] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@pytest.fixture(scope="module")
def smoke_client(_disable_submodule_validation: None) -> TestClient:
    """Build the app once and wrap it in a TestClient."""
    app = create_app()
    # Sanity: the bootstrap returns a real FastAPI app instance.
    assert isinstance(app, FastAPI)
    with TestClient(app) as client:
        yield client


def test_create_app_constructs() -> None:
    """``create_app()`` builds a FastAPI instance under the in-memory runtime.

    Submodule validation is disabled by the module-scoped autouse fixture.
    """
    app = create_app()
    assert isinstance(app, FastAPI)


def test_product_coverage_route_is_mounted(smoke_client: TestClient) -> None:
    """GET the product-coverage route returns a mounted status, never 404.

    Unauthenticated, the ``require_admin_principal`` dependency answers 401, so
    a non-404 status proves the ``include_router(product_coverage_router)``
    mount is present.
    """
    response = smoke_client.get(PRODUCT_COVERAGE_PATH)
    assert response.status_code != 404, (
        "product-coverage route missing — include_router(product_coverage_router) is not "
        f"mounted (got {response.status_code})"
    )
    assert response.status_code in _MOUNTED_NOT_404, (
        f"unexpected status for {PRODUCT_COVERAGE_PATH}: {response.status_code}"
    )


def test_product_coverage_requires_admin_auth(smoke_client: TestClient) -> None:
    """Unauthenticated product-coverage is rejected by the admin auth gate (401).

    Pins the CURRENT behavior: the router carries
    ``dependencies=[Depends(require_admin_principal)]`` and
    ``authenticate_request`` raises ``status_code=401`` / ``code="UNAUTHORIZED"``
    when neither an ``x-api-key`` header nor a session cookie is supplied.
    """
    response = smoke_client.get(PRODUCT_COVERAGE_PATH)
    assert response.status_code == 401, (
        f"expected 401 for unauthenticated product-coverage, got {response.status_code}"
    )


@pytest.mark.parametrize("path", CORE_OPS_PATHS)
def test_core_ops_routes_are_mounted(smoke_client: TestClient, path: str) -> None:
    """Core ops routes (``/healthz``, ``/readyz``) coexist with the product-coverage mount.

    These are defined inline in the base ``create_app`` body. Proving they
    respond (non-404) alongside product-coverage shows ``create_app`` mounts
    BOTH rather than one replacing the other.
    """
    response = smoke_client.get(path)
    assert response.status_code != 404, f"core ops route missing: {path}"


def test_healthz_returns_ok_payload(smoke_client: TestClient) -> None:
    """``/healthz`` returns its canonical 200 ``{"status": "ok"}`` body.

    A concrete core-route assertion (beyond non-404) anchors the "core routes
    work" half of the bootstrap check.
    """
    response = smoke_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_bootstrap_union_mounts_both_lines(smoke_client: TestClient) -> None:
    """End-to-end bootstrap check: product-coverage AND a core route together.

    This is the single check that most directly characterizes the bootstrap —
    one TestClient sees both the included admin route (mounted, 401 without
    auth) and a base ops route (200) in the same constructed app.
    """
    coverage = smoke_client.get(PRODUCT_COVERAGE_PATH)
    healthz = smoke_client.get("/healthz")

    assert coverage.status_code in _MOUNTED_NOT_404
    assert coverage.status_code != 404
    assert healthz.status_code == 200
