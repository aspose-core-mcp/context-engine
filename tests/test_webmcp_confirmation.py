from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.api.webmcp_confirmation import WebMCPConfirmationError, WebMCPConfirmationService
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_webmcp_confirmation_issue_requires_admin_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_reindex",
                "reason": "reindex requested",
                "intent": {"repo_id": "aspose.ocr.docs"},
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_webmcp_confirmation_issue_returns_token_and_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    monkeypatch.setenv("ADCS_WEBMCP_CONFIRM_TTL_SECONDS", "420")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_reindex",
                "reason": "product owner approval",
                "intent": {"repo_ids": ["aspose.ocr.docs"]},
            },
            headers={"x-api-key": "replace-me"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["confirm_token"].startswith("wmcp_cf_")
    assert payload["tool_name"] == "web_trigger_reindex"
    assert payload["reason"] == "product owner approval"
    assert payload["ttl_seconds"] == 420
    assert payload["intent_fingerprint"]
    assert payload["expires_at"] > payload["issued_at"]


def test_webmcp_confirmation_issue_rejects_unknown_write_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_unknown_write",
                "reason": "invalid write tool",
                "intent": {"product_id": "aspose.ocr"},
            },
            headers={"x-api-key": "replace-me"},
        )

    assert response.status_code == 400
    payload = response.json()["detail"]["error"]
    assert payload["code"] == "VALIDATION_ERROR"
    assert "supported_tools" in payload["details"]


def test_confirmation_service_rejects_missing_token() -> None:
    service = WebMCPConfirmationService(ttl_seconds=60)
    with pytest.raises(WebMCPConfirmationError) as exc_info:
        service.consume(
            confirm_token=None,
            tool_name="web_trigger_reindex",
            reason="missing token test",
            intent_payload={"repo_id": "aspose.ocr.docs"},
        )
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"


def test_confirmation_service_rejects_expired_token() -> None:
    service = WebMCPConfirmationService(ttl_seconds=1)
    issued_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
    issued = service.issue(
        tool_name="web_trigger_reindex",
        reason="expired token test",
        intent_payload={"repo_id": "aspose.ocr.docs"},
        now=issued_at,
    )
    with pytest.raises(WebMCPConfirmationError) as exc_info:
        service.consume(
            confirm_token=issued.confirm_token,
            tool_name="web_trigger_reindex",
            reason="expired token test",
            intent_payload={"repo_id": "aspose.ocr.docs"},
            now=issued_at + timedelta(seconds=2),
        )
    assert exc_info.value.code == "CONFIRMATION_EXPIRED"


def test_confirmation_service_rejects_replayed_token() -> None:
    service = WebMCPConfirmationService(ttl_seconds=60)
    issued_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
    issued = service.issue(
        tool_name="web_trigger_reindex",
        reason="replay test",
        intent_payload={"repo_id": "aspose.ocr.docs"},
        now=issued_at,
    )
    consumed = service.consume(
        confirm_token=issued.confirm_token,
        tool_name="web_trigger_reindex",
        reason="replay test",
        intent_payload={"repo_id": "aspose.ocr.docs"},
        request_id="req-1",
        now=issued_at + timedelta(seconds=1),
    )
    assert consumed.consumed_request_id == "req-1"
    with pytest.raises(WebMCPConfirmationError) as exc_info:
        service.consume(
            confirm_token=issued.confirm_token,
            tool_name="web_trigger_reindex",
            reason="replay test",
            intent_payload={"repo_id": "aspose.ocr.docs"},
            request_id="req-2",
            now=issued_at + timedelta(seconds=2),
        )
    assert exc_info.value.code == "CONFIRMATION_REPLAYED"


def test_confirmation_service_rejects_payload_mismatch() -> None:
    service = WebMCPConfirmationService(ttl_seconds=60)
    issued_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)
    issued = service.issue(
        tool_name="web_trigger_reindex",
        reason="mismatch test",
        intent_payload={"repo_id": "aspose.ocr.docs"},
        now=issued_at,
    )
    with pytest.raises(WebMCPConfirmationError) as exc_info:
        service.consume(
            confirm_token=issued.confirm_token,
            tool_name="web_trigger_reindex",
            reason="different reason",
            intent_payload={"repo_id": "aspose.ocr.docs"},
            now=issued_at + timedelta(seconds=1),
        )
    assert exc_info.value.code == "CONFIRMATION_MISMATCH"
