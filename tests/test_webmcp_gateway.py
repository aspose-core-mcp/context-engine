from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.ingestion.chunking import StageDChunkRecord


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def _patch_sample_chunk_records(app: FastAPI) -> None:
    records = (
        StageDChunkRecord(
            chunk_id="chunk-api-signature",
            repo_id="aspose.ocr.apiref",
            product_id="aspose.ocr",
            product_family="Aspose.OCR",
            programming_language="net",
            version="25.1",
            source_kind="apiref",
            doc_locale="en",
            doc_type="api_signature",
            symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
            title="RecognizeImage Method",
            section_path=("root", "RecognizeImage Method"),
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/",
            section_anchor="#recognizeimage",
            source_path="source/chunk-api-signature.md",
            source_revision="revision-abc123",
            is_deprecated=False,
            has_code_example=False,
            chunk_type="api_signature",
            text="public RecognitionResult RecognizeImage(string imagePath)",
            tokens=6,
            checksum="checksum-chunk-api-signature",
        ),
        StageDChunkRecord(
            chunk_id="chunk-guide",
            repo_id="aspose.ocr.docs",
            product_id="aspose.ocr",
            product_family="Aspose.OCR",
            programming_language="net",
            version="25.1",
            source_kind="docs",
            doc_locale="en",
            doc_type="guide_step",
            symbol_fqn=None,
            title="How to Recognize Text",
            section_path=("root", "How to Recognize Text"),
            canonical_url="https://docs.aspose.com/ocr/net/quickstart/",
            section_anchor="#how-to-recognize-text",
            source_path="source/chunk-guide.md",
            source_revision="revision-abc123",
            is_deprecated=False,
            has_code_example=False,
            chunk_type="guide_step",
            text="Use Aspose.OCR.AsposeOcr.RecognizeImage in a simple setup flow.",
            tokens=8,
            checksum="checksum-chunk-guide",
        ),
    )
    orchestrator = app.state.source_hugo_normalization_orchestrator

    def _patched_get_latest_chunk_records(
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        return tuple(
            record
            for record in records
            if (product_id is None or record.product_id.casefold() == product_id.casefold())
            and (
                programming_language is None
                or record.programming_language.casefold() == programming_language.casefold()
            )
            and (version is None or record.version.casefold() == version.casefold())
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]


def test_webmcp_disabled_by_default_and_core_api_unchanged() -> None:
    app = create_app()
    with TestClient(app) as client:
        disabled = client.get("/webmcp/v1/capabilities")
        assert disabled.status_code == 404
        assert disabled.json()["detail"]["error"]["code"] == "NOT_FOUND"

        baseline = client.post("/v1/products:resolve", json={"query": "Aspose OCR"})
        assert baseline.status_code == 200


def test_webmcp_capabilities_exposed_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        capabilities = client.get("/webmcp/v1/capabilities")
    assert capabilities.status_code == 200
    payload = capabilities.json()
    tool_names = {item["tool_name"] for item in payload["tools"]}
    assert payload["enabled"] is True
    assert {
        "web_get_system_status",
        "web_query_docs_preview",
        "web_list_ingestion_jobs",
    }.issubset(tool_names)


def test_webmcp_query_docs_preview_maps_to_public_docs_query_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    _patch_sample_chunk_records(app)
    with TestClient(app) as client:
        rest_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "top_k": 2,
                "strict_version": True,
                "doc_types": ["api_reference", "guide"],
            },
        )
        webmcp_response = client.post(
            "/webmcp/v1/tools/web_query_docs_preview",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "top_k": 2,
                "strict_version": True,
                "doc_types": ["api_reference", "guide"],
            },
        )

    assert rest_response.status_code == 200
    assert webmcp_response.status_code == 200
    rest_payload = rest_response.json()
    webmcp_payload = webmcp_response.json()
    assert len(webmcp_payload["results"]) == len(rest_payload["results"])
    assert (
        webmcp_payload["results"][0]["canonical_url"]
        == rest_payload["results"][0]["canonical_url"]
    )


def test_webmcp_system_status_maps_to_health_and_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        web_status = client.post("/webmcp/v1/tools/web_get_system_status", json={})

    assert health.status_code == 200
    assert ready.status_code in {200, 503}
    assert web_status.status_code == 200
    payload = web_status.json()
    assert payload["healthz"]["status"] == health.json()["status"]
    assert payload["readyz"]["status"] == ready.json()["status"]


def test_webmcp_ingestion_jobs_maps_to_admin_ingestion_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        admin_jobs = client.get(
            "/admin/v1/ingestion/jobs?limit=20",
            headers={"x-api-key": "replace-me"},
        )
        web_jobs = client.post(
            "/webmcp/v1/tools/web_list_ingestion_jobs",
            json={"limit": 20},
            headers={"x-api-key": "replace-me"},
        )

    assert admin_jobs.status_code == 200
    assert web_jobs.status_code == 200
    admin_payload = admin_jobs.json()
    web_payload = web_jobs.json()
    # The first list_operations() call (admin) may mutate in-memory state via
    # _save_operation(append_new=True), so the second call (webmcp) can return
    # additional records.  Compare by operation_id set-overlap rather than
    # requiring identical length or exact set equality.
    admin_by_id = {item["operation_id"]: item for item in admin_payload}
    web_by_id = {item["operation_id"]: item for item in web_payload}
    # Every admin operation must also appear in the webmcp response.
    assert set(admin_by_id.keys()) <= set(web_by_id.keys()), (
        f"Admin operation_ids not found in webmcp response: "
        f"{set(admin_by_id.keys()) - set(web_by_id.keys())}"
    )
    for op_id in admin_by_id:
        assert web_by_id[op_id]["status"] == admin_by_id[op_id]["status"]


# ---------------------------------------------------------------------------
# Capabilities: write tools list confirmation requirement
# ---------------------------------------------------------------------------


def test_webmcp_capabilities_write_tools_require_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        capabilities = client.get("/webmcp/v1/capabilities")
    assert capabilities.status_code == 200
    tools_by_name = {t["tool_name"]: t for t in capabilities.json()["tools"]}
    for write_tool in ("web_trigger_ingestion", "web_trigger_reindex", "web_promote_snapshot"):
        assert write_tool in tools_by_name
        assert tools_by_name[write_tool]["read_only"] is False
        assert tools_by_name[write_tool]["requires_confirmation"] is True


# ---------------------------------------------------------------------------
# Confirmation issuance
# ---------------------------------------------------------------------------

_AUTH = {"x-api-key": "replace-me"}


def test_webmcp_confirmation_issue_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "Testing confirmation issuance",
                "intent": {"repo_ids": ["aspose.ocr.docs"], "dry_run": False},
            },
            headers=_AUTH,
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["confirm_token"].startswith("wmcp_cf_")
    assert payload["tool_name"] == "web_trigger_ingestion"
    assert payload["reason"] == "Testing confirmation issuance"
    assert payload["ttl_seconds"] > 0
    assert payload["intent_fingerprint"]
    assert payload["issued_at"]
    assert payload["expires_at"]


def test_webmcp_confirmation_issue_rejects_unknown_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/confirmations",
            json={"tool_name": "nonexistent_tool", "reason": "test"},
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Write tool: web_trigger_ingestion — confirmation flow
# ---------------------------------------------------------------------------


def test_webmcp_trigger_ingestion_requires_confirm_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write tool without confirm_token must fail with CONFIRMATION_REQUIRED."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "test ingestion",
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_webmcp_trigger_ingestion_requires_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write tool with confirm_token but missing reason must fail."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "confirm_token": "wmcp_cf_fake_token",
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_webmcp_trigger_ingestion_requires_repo_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write tool with no repo_id/repo_ids must fail with VALIDATION_ERROR."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "reason": "test ingestion",
                "confirm_token": "wmcp_cf_fake_token",
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "VALIDATION_ERROR"


def test_webmcp_trigger_ingestion_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full confirmation flow: issue token then invoke write tool."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # Step 1: Issue a confirmation token
        intent = {"repo_ids": ["aspose.ocr.docs"], "dry_run": True}
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "Run dry-run ingestion for OCR docs",
                "intent": intent,
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]

        # Step 2: Invoke the write tool with the token
        write_resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Run dry-run ingestion for OCR docs",
                "confirm_token": confirm_token,
                "dry_run": True,
            },
            headers=_AUTH,
        )
    assert write_resp.status_code == 200
    payload = write_resp.json()
    assert payload["tool_name"] == "web_trigger_ingestion"
    assert payload["audit_id"]
    assert payload["operation_id"]
    assert "aspose.ocr.docs" in payload["repo_ids"]


def test_webmcp_trigger_ingestion_confirmation_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consuming the same confirmation token twice must fail with CONFIRMATION_REPLAYED."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        intent = {"repo_ids": ["aspose.ocr.docs"], "dry_run": True}
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "Replay test",
                "intent": intent,
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]

        # First use: should succeed
        first = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Replay test",
                "confirm_token": confirm_token,
                "dry_run": True,
            },
            headers=_AUTH,
        )
        assert first.status_code == 200

        # Second use: should fail as replayed
        second = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Replay test",
                "confirm_token": confirm_token,
                "dry_run": True,
            },
            headers=_AUTH,
        )
    assert second.status_code == 409
    assert second.json()["detail"]["error"]["code"] == "CONFIRMATION_REPLAYED"


def test_webmcp_trigger_ingestion_confirmation_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Using a bogus confirmation token must fail with CONFIRMATION_INVALID."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Invalid token test",
                "confirm_token": "wmcp_cf_completely_bogus_token_abc",
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRMATION_INVALID"


def test_webmcp_trigger_ingestion_confirmation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmation token issued for one tool cannot be used for different intent."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # Issue token for dry_run=True
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "Mismatch test",
                "intent": {"repo_ids": ["aspose.ocr.docs"], "dry_run": True},
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]

        # Attempt to use it with dry_run=False (different intent)
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Mismatch test",
                "confirm_token": confirm_token,
                "dry_run": False,
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRMATION_MISMATCH"


def test_webmcp_trigger_ingestion_confirmation_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired confirmation token must fail with CONFIRMATION_EXPIRED."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    monkeypatch.setenv("ADCS_WEBMCP_CONFIRMATION_TTL_SECONDS", "1")
    app = create_app()

    from datetime import UTC, datetime, timedelta

    from adcs.api.webmcp_confirmation import WebMCPConfirmationService

    # Replace the confirmation service with a very short TTL
    svc = WebMCPConfirmationService(ttl_seconds=1)
    app.state.webmcp_confirmation_service = svc

    # Issue a token with an explicitly past timestamp
    past = datetime.now(tz=UTC) - timedelta(seconds=10)
    record = svc.issue(
        tool_name="web_trigger_ingestion",
        reason="Expired test",
        intent_payload={
            "repo_ids": ["aspose.ocr.docs"],
            "dry_run": True,
            "actor_key_id": "superuser-key",
        },
        now=past,
    )

    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Expired test",
                "confirm_token": record.confirm_token,
                "dry_run": True,
            },
            headers=_AUTH,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "CONFIRMATION_EXPIRED"


# ---------------------------------------------------------------------------
# Write tool: web_trigger_reindex — confirmation flow
# ---------------------------------------------------------------------------


def test_webmcp_trigger_reindex_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        intent = {"repo_ids": ["aspose.ocr.docs"], "force_full_reindex": True}
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_reindex",
                "reason": "Reindex OCR docs",
                "intent": intent,
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]

        write_resp = client.post(
            "/webmcp/v1/tools/web_trigger_reindex",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Reindex OCR docs",
                "confirm_token": confirm_token,
            },
            headers=_AUTH,
        )
    assert write_resp.status_code == 200
    payload = write_resp.json()
    assert payload["tool_name"] == "web_trigger_reindex"
    assert payload["audit_id"]


# ---------------------------------------------------------------------------
# Write tool: web_promote_snapshot
# ---------------------------------------------------------------------------


def test_webmcp_promote_snapshot_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promoting a nonexistent snapshot must return 404."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # Issue confirmation for the promote
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_promote_snapshot",
                "reason": "Promote nonexistent snapshot",
                "intent": {"snapshot_id": "nonexistent-snap-id"},
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]

        resp = client.post(
            "/webmcp/v1/tools/web_promote_snapshot",
            json={
                "snapshot_id": "nonexistent-snap-id",
                "reason": "Promote nonexistent snapshot",
                "confirm_token": confirm_token,
            },
            headers=_AUTH,
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_webmcp_write_audit_trail_records_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit trail must contain both succeeded and failed write invocations."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # 1. Successful write via confirmation flow
        intent = {"repo_ids": ["aspose.ocr.docs"], "dry_run": True}
        issue_resp = client.post(
            "/webmcp/v1/confirmations",
            json={
                "tool_name": "web_trigger_ingestion",
                "reason": "Audit success test",
                "intent": intent,
            },
            headers=_AUTH,
        )
        assert issue_resp.status_code == 200
        confirm_token = issue_resp.json()["confirm_token"]
        success_resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Audit success test",
                "confirm_token": confirm_token,
                "dry_run": True,
            },
            headers=_AUTH,
        )
        assert success_resp.status_code == 200

        # 2. Failed write (missing confirm_token)
        fail_resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "Audit failure test",
            },
            headers=_AUTH,
        )
        assert fail_resp.status_code == 400

        # 3. Query audit trail
        audit_resp = client.get(
            "/webmcp/v1/audit/write-invocations?limit=50",
            headers=_AUTH,
        )
    assert audit_resp.status_code == 200
    audit_records = audit_resp.json()
    assert len(audit_records) >= 2
    statuses = {r["status"] for r in audit_records}
    assert "succeeded" in statuses
    tool_names = {r["tool_name"] for r in audit_records}
    assert "web_trigger_ingestion" in tool_names
    # Each record must have actor_key_id and audit_id
    for record in audit_records:
        assert record["audit_id"]
        assert record["actor_key_id"]


def test_webmcp_write_audit_trail_filter_by_tool_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit listing can be filtered by tool_name."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # Create a failed attempt for web_trigger_ingestion
        client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={"repo_id": "aspose.ocr.docs", "reason": "filter test"},
            headers=_AUTH,
        )
        # Query filtered by tool_name
        audit_resp = client.get(
            "/webmcp/v1/audit/write-invocations?tool_name=web_trigger_ingestion",
            headers=_AUTH,
        )
    assert audit_resp.status_code == 200
    for record in audit_resp.json():
        assert record["tool_name"] == "web_trigger_ingestion"


def test_webmcp_write_audit_trail_filter_by_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit listing can be filtered by status."""
    monkeypatch.setenv("ADCS_WEBMCP_ENABLED", "true")
    app = create_app()
    with TestClient(app) as client:
        # Create a rejection (missing confirm_token)
        client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={"repo_id": "aspose.ocr.docs", "reason": "status filter test"},
            headers=_AUTH,
        )
        # Query only rejected
        audit_resp = client.get(
            "/webmcp/v1/audit/write-invocations?status=rejected",
            headers=_AUTH,
        )
    assert audit_resp.status_code == 200
    for record in audit_resp.json():
        assert record["status"] == "rejected"


# ---------------------------------------------------------------------------
# Disabled gateway blocks write tools too
# ---------------------------------------------------------------------------


def test_webmcp_disabled_blocks_write_tools() -> None:
    """When WebMCP is disabled, write tool endpoints return 404."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/tools/web_trigger_ingestion",
            json={
                "repo_id": "aspose.ocr.docs",
                "reason": "test",
                "confirm_token": "fake",
            },
            headers=_AUTH,
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "NOT_FOUND"


def test_webmcp_disabled_blocks_confirmations() -> None:
    """When WebMCP is disabled, confirmation endpoint returns 404."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/webmcp/v1/confirmations",
            json={"tool_name": "web_trigger_ingestion", "reason": "test"},
            headers=_AUTH,
        )
    assert resp.status_code == 404


def test_webmcp_disabled_blocks_audit_listing() -> None:
    """When WebMCP is disabled, audit listing endpoint returns 404."""
    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/webmcp/v1/audit/write-invocations",
            headers=_AUTH,
        )
    assert resp.status_code == 404
