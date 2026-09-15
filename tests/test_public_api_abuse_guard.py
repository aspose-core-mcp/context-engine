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


def _set_default_abuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ABUSE_REQUESTS_GLOBAL_PER_MINUTE", "1")
    monkeypatch.setenv("ADCS_ABUSE_REQUESTS_PER_IP_PER_MINUTE", "10")
    monkeypatch.setenv("ADCS_ABUSE_REQUESTS_PER_FINGERPRINT_PER_MINUTE", "10")


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
                        "key_id": "super-key",
                        "token": "super-token",
                        "is_superuser": True,
                        "enabled": True,
                        "product_scopes": [],
                        "scopes": ["*"],
                    },
                    {
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:settings"],
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_JSON_PATH", str(keys_path))


def test_abuse_guard_enforce_blocks_public_rest_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "enforce")
    app = create_app()

    with TestClient(app) as client:
        first = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})
        second = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["code"] == "RATE_LIMITED"


def test_abuse_guard_observe_only_does_not_block_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "observe-only")
    app = create_app()

    with TestClient(app) as client:
        first = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})
        second = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_abuse_guard_allowlist_bypasses_enforce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "enforce")
    monkeypatch.setenv("ADCS_ABUSE_GUARD_ALLOWLIST", "trusted-fp")
    app = create_app()

    with TestClient(app) as client:
        first = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
            headers={"x-adcs-fingerprint": "trusted-fp"},
        )
        second = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
            headers={"x-adcs-fingerprint": "trusted-fp"},
        )
        third = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
            headers={"x-adcs-fingerprint": "trusted-fp"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200


def test_abuse_guard_applies_to_mcp_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "enforce")
    app = create_app()

    with TestClient(app) as client:
        first = client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})
        second = client.post("/mcp/v1/initialize", json={"protocol_revision": "2025-11-25"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["error"]["code"] == "RATE_LIMITED"


def test_abuse_guard_debug_header_bypasses_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "enforce")
    app = create_app()

    with TestClient(app) as client:
        first = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
            headers={"x-adcs-debug": "1"},
        )
        second = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
            headers={"x-adcs-debug": "1"},
        )
        third = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
        )
        fourth = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert fourth.status_code == 429


def test_admin_can_read_and_patch_abuse_guard_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_default_abuse_env(monkeypatch)
    app = create_app()

    with TestClient(app) as client:
        current = client.get(
            "/admin/v1/settings/public-api/abuse-guard",
            headers={"x-api-key": "replace-me"},
        )
        assert current.status_code == 200
        assert current.json()["mode"] == "observe-only"

        patched = client.patch(
            "/admin/v1/settings/public-api/abuse-guard",
            json={
                "mode": "enforce",
                "allowlist": ["trusted-fp", "trusted-fp"],
                "requests_global_per_minute": 1,
                "requests_per_ip_per_minute": 5,
                "requests_per_fingerprint_per_minute": 5,
                "debug_header_enabled": False,
            },
            headers={"x-api-key": "replace-me"},
        )
        assert patched.status_code == 200
        assert patched.json()["mode"] == "enforce"
        assert patched.json()["allowlist"] == ["trusted-fp"]

        first = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})
        second = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})
        assert first.status_code == 200
        assert second.status_code == 429


def test_non_superuser_cannot_patch_abuse_guard_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_default_abuse_env(monkeypatch)
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        denied = client.patch(
            "/admin/v1/settings/public-api/abuse-guard",
            json={"mode": "enforce"},
            headers={"x-api-key": "owner-token"},
        )

    assert denied.status_code == 403


def test_client_ip_comes_from_forwarded_chain_when_proxies_are_trusted() -> None:
    """Behind a proxy, distinct callers must land in distinct buckets.

    Keying on the socket peer put every caller behind the nginx ingress into one
    bucket, so enforcing the 120/ip/min limit would have throttled the entire
    public API at a single client's rate.
    """
    from starlette.requests import Request

    from adcs.api.abuse_guard import _extract_client_host

    def _request(*, xff: str | None, peer: str = "10.0.0.7") -> Request:
        headers: list[tuple[bytes, bytes]] = []
        if xff is not None:
            headers.append((b"x-forwarded-for", xff.encode()))
        return Request(
            {
                "type": "http",
                "headers": headers,
                "client": (peer, 12345),
                "method": "POST",
                "path": "/v1/docs:query",
            }
        )

    # One trusted proxy: the caller is the entry before the proxy's own.
    assert (
        _extract_client_host(_request(xff="203.0.113.9, 10.0.0.7"), trusted_proxy_hops=1)
        == "203.0.113.9"
    )
    assert (
        _extract_client_host(_request(xff="198.51.100.4, 10.0.0.7"), trusted_proxy_hops=1)
        == "198.51.100.4"
    )

    # Default configuration must ignore the header entirely: with no proxy in
    # front, trusting it would let any caller forge its own identity.
    assert _extract_client_host(_request(xff="1.2.3.4"), trusted_proxy_hops=0) == "10.0.0.7"

    # A chain shorter than the configured hop count falls back to the peer
    # rather than trusting a caller-supplied value.
    assert _extract_client_host(_request(xff="1.2.3.4"), trusted_proxy_hops=2) == "10.0.0.7"
    assert _extract_client_host(_request(xff=None), trusted_proxy_hops=1) == "10.0.0.7"


def test_every_public_route_consults_the_abuse_guard() -> None:
    """No public endpoint may bypass the guard.

    Seven public routes never called it — the four unauthenticated
    /v1/symbols/structured:* Postgres routes plus docs:feedback,
    docs:repro-pack and status/page — so their traffic was invisible even to
    observe-mode telemetry and could not be throttled at all.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "adcs" / "api"
    public_prefixes = ("/v1/docs", "/v1/products", "/v1/symbols", "/v1/changes", "/v1/releases",
                       "/v1/status/page")
    unguarded: list[str] = []

    for module in src.glob("*.py"):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = [
                arg.value
                for deco in node.decorator_list
                if isinstance(deco, ast.Call)
                for arg in deco.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            paths = [r for r in routes if r.startswith(public_prefixes)]
            if not paths:
                continue
            calls = {
                sub.func.id
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            }
            if "_enforce_abuse_guard" not in calls:
                unguarded.extend(f"{module.name}:{p}" for p in paths)

    assert not unguarded, f"public routes bypassing the abuse guard: {sorted(unguarded)}"
