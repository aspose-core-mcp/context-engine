from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_admin_cookie_session_login_and_logout() -> None:
    app = create_app()
    with TestClient(app) as client:
        login = client.post(
            "/admin/v1/system/session/login",
            json={"api_key": "replace-me"},
        )
        assert login.status_code == 200
        assert "set-cookie" in login.headers
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "Max-Age=15552000" in login.headers["set-cookie"]

        session = client.get("/admin/v1/system/session")
        assert session.status_code == 200
        assert session.json()["key_id"] == "env-admin-key"

        logout = client.post("/admin/v1/system/session/logout")
        assert logout.status_code == 200
        assert logout.json()["status"] == "ok"

        session_after_logout = client.get("/admin/v1/system/session")
        assert session_after_logout.status_code == 401
        assert session_after_logout.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_admin_cookie_session_without_remember_is_session_cookie() -> None:
    app = create_app()
    with TestClient(app) as client:
        login = client.post(
            "/admin/v1/system/session/login",
            json={"api_key": "replace-me", "remember_device": False},
        )
        assert login.status_code == 200
        assert "set-cookie" in login.headers
        assert "Max-Age=" not in login.headers["set-cookie"]
        assert "expires=" not in login.headers["set-cookie"].lower()

        session = client.get("/admin/v1/system/session")
        assert session.status_code == 200
        assert session.json()["key_id"] == "env-admin-key"


def test_admin_cookie_session_respects_custom_cookie_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_ADMIN_SESSION_COOKIE_NAME", "custom_adcs_session")
    app = create_app()
    with TestClient(app) as client:
        login = client.post(
            "/admin/v1/system/session/login",
            json={"api_key": "replace-me"},
        )
        assert login.status_code == 200
        assert "custom_adcs_session=" in login.headers["set-cookie"]

        session = client.get("/admin/v1/system/session")
        assert session.status_code == 200
        assert session.json()["effective_role"] == "superuser"


def test_admin_login_locks_out_after_repeated_failures() -> None:
    """Online brute force against the admin key must not be unbounded.

    Login is the only unauthenticated admin surface; without an attempt counter,
    lockout or backoff, guessing the key is limited only by throughput.
    """
    app = create_app()
    with TestClient(app) as client:
        for attempt in range(5):
            denied = client.post(
                "/admin/v1/system/session/login",
                json={"api_key": f"wrong-key-{attempt}"},
            )
            assert denied.status_code == 401, f"attempt {attempt} should be rejected, not throttled"

        locked = client.post(
            "/admin/v1/system/session/login",
            json={"api_key": "wrong-key-6"},
        )
        assert locked.status_code == 429
        assert locked.headers.get("Retry-After")
        assert locked.json()["detail"]["error"]["code"] == "RATE_LIMITED"

        # The lockout is on failures, so a valid key is refused too while it
        # holds — that is the point, and it is why the window is bounded.
        during_lockout = client.post(
            "/admin/v1/system/session/login",
            json={"api_key": "replace-me"},
        )
        assert during_lockout.status_code == 429


def test_admin_login_failure_counter_resets_on_success() -> None:
    """A few typos must not accumulate toward a lockout across a good login."""
    app = create_app()
    with TestClient(app) as client:
        for attempt in range(4):
            assert (
                client.post(
                    "/admin/v1/system/session/login",
                    json={"api_key": f"typo-{attempt}"},
                ).status_code
                == 401
            )

        assert (
            client.post(
                "/admin/v1/system/session/login",
                json={"api_key": "replace-me"},
            ).status_code
            == 200
        )

        # Counter cleared: four more failures stay 401 rather than tripping at
        # the fifth cumulative one.
        for attempt in range(4):
            assert (
                client.post(
                    "/admin/v1/system/session/login",
                    json={"api_key": f"typo-again-{attempt}"},
                ).status_code
                == 401
            )
