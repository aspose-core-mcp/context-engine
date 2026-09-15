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
                    {
                        "key_id": "foreign-owner-key",
                        "token": "foreign-owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["groupdocs.parser"],
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


def test_admin_registries_and_retrieval_settings_scope_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        upsert_language = client.post(
            "/admin/v1/registries/languages",
            json={"lang_id": "python-net", "display_name": "Python via .NET", "enabled": True},
            headers={"x-api-key": "super-token"},
        )
        assert upsert_language.status_code == 200
        assert upsert_language.json()["lang_id"] == "python-net"

        alias_upsert = client.post(
            "/admin/v1/registries/languages/aliases",
            json={
                "product_id": "aspose.ocr",
                "external_language_id": "dotnet",
                "canonical_lang_id": "net",
            },
            headers={"x-api-key": "owner-token"},
        )
        assert alias_upsert.status_code == 200

        alias_scope_violation = client.post(
            "/admin/v1/registries/languages/aliases",
            json={
                "product_id": "aspose.ocr",
                "external_language_id": "dotnet-2",
                "canonical_lang_id": "net",
            },
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert alias_scope_violation.status_code == 403

        patch_settings = client.patch(
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
        assert patch_settings.status_code == 200
        assert patch_settings.json()["top_k"] == 12

        patch_scope_violation = client.patch(
            "/admin/v1/settings/retrieval/aspose.ocr",
            json={
                "top_k": 9,
                "max_context_tokens": 4096,
                "excerpt_char_limit": 800,
                "low_confidence_threshold": 0.4,
                "clarification_policy": "always_prompt",
            },
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert patch_scope_violation.status_code == 403


def test_admin_analytics_slices_and_sql_explorer_endpoints() -> None:
    app = create_app()
    with TestClient(app) as client:
        resolve_response = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR for .NET"},
            headers={"x-adcs-fingerprint": "fp-test-001"},
        )
        assert resolve_response.status_code == 200

        slices = client.get(
            "/admin/v1/analytics/slices",
            headers={"x-api-key": "replace-me"},
        )
        assert slices.status_code == 200
        payload = slices.json()
        assert payload["total_requests"] >= 1
        assert payload["by_endpoint"]["rest.products.resolve"] >= 1
        assert "by_outcome" in payload
        assert "by_retrieval_mode" in payload
        assert "by_zero_result_reason" in payload
        assert "by_fallback_reason" in payload
        assert "by_warning_code" in payload

        forecast = client.get(
            "/admin/v1/analytics/capacity-forecast",
            headers={"x-api-key": "replace-me"},
        )
        assert forecast.status_code == 200
        forecast_payload = forecast.json()
        assert forecast_payload["filtered_requests_total"] >= 1
        assert "projected_requests_next_24h" in forecast_payload
        assert "saturation_risk" in forecast_payload

        sql_query = client.post(
            "/admin/v1/analytics/sql:query",
            json={
                "sql": (
                    "SELECT endpoint, COUNT(*) AS requests "
                    "FROM analytics_queries GROUP BY endpoint"
                ),
                "max_rows": 100,
            },
            headers={"x-api-key": "replace-me"},
        )
        assert sql_query.status_code == 200
        assert sql_query.json()["columns"] == ["endpoint", "requests"]
        assert sql_query.json()["row_count"] >= 1

        sql_export = client.post(
            "/admin/v1/analytics/sql:export",
            json={"sql": "SELECT endpoint FROM analytics_queries", "max_rows": 10},
            headers={"x-api-key": "replace-me"},
        )
        assert sql_export.status_code == 200
        assert "endpoint" in sql_export.json()["csv_payload"]

        rejected_non_select = client.post(
            "/admin/v1/analytics/sql:query",
            json={"sql": "DELETE FROM analytics_queries", "max_rows": 10},
            headers={"x-api-key": "replace-me"},
        )
        assert rejected_non_select.status_code == 400

        rejected_multi_statement = client.post(
            "/admin/v1/analytics/sql:query",
            json={"sql": "SELECT endpoint FROM analytics_queries; SELECT 1", "max_rows": 10},
            headers={"x-api-key": "replace-me"},
        )
        assert rejected_multi_statement.status_code == 400

        rejected_invalid_sql = client.post(
            "/admin/v1/analytics/sql:query",
            json={"sql": "SELECT FROM analytics_queries", "max_rows": 10},
            headers={"x-api-key": "replace-me"},
        )
        assert rejected_invalid_sql.status_code == 400


def test_admin_analytics_tracks_query_docs_zero_result_reasons() -> None:
    app = create_app()
    with TestClient(app) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use OCR API?",
                "product_id": "missing.product",
                "language": "net",
                "query_locale": "en",
            },
        )
        assert query_response.status_code == 200
        query_payload = query_response.json()
        assert query_payload["results"] == []
        assert "no_index_data" in query_payload["warnings"]

        slices = client.get(
            "/admin/v1/analytics/slices",
            params={"tool": "query_docs", "outcome": "no_results"},
            headers={"x-api-key": "replace-me"},
        )
        assert slices.status_code == 200
        payload = slices.json()
        assert payload["total_requests"] >= 1
        assert payload["by_outcome"]["no_results"] >= 1
        assert payload["by_zero_result_reason"]["no_index_data"] >= 1
        assert payload["by_warning_code"]["no_index_data"] >= 1

        zero_results = client.get(
            "/admin/v1/analytics/zero-results",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert zero_results.status_code == 200
        zero_payload = zero_results.json()
        assert zero_payload["without_useful_result_requests"] >= 1
        assert zero_payload["by_zero_result_reason"]["no_index_data"] >= 1
        assert len(zero_payload["clusters"]) >= 1
        assert zero_payload["clusters"][0]["recommendation_title"]

        forecast = client.get(
            "/admin/v1/analytics/capacity-forecast",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert forecast.status_code == 200
        forecast_payload = forecast.json()
        assert forecast_payload["projected_requests_next_24h"] >= 1
        assert forecast_payload["hottest_products"][0]["product_id"] == "missing.product"


def test_admin_analytics_exposes_public_adoption_funnel() -> None:
    app = create_app()
    with TestClient(app) as client:
        resolve_ready = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR for .NET"},
            headers={"x-adcs-fingerprint": "fp-adoption-ready"},
        )
        assert resolve_ready.status_code == 200

        self_test_ready = client.get(
            "/v1/integrations/self-test",
            params={
                "product_id": "aspose.ocr",
                "programming_language": "net",
                "client_id": "cursor",
                "transport": "streamable-http",
            },
            headers={"x-adcs-fingerprint": "fp-adoption-ready"},
        )
        assert self_test_ready.status_code == 200

        query_ready = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use the latest OCR table recognition API?",
                "product_id": "aspose.ocr",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-adoption-ready"},
        )
        assert query_ready.status_code == 200
        ready_request_id = query_ready.json()["request_id"]

        feedback_ready = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": ready_request_id,
                "rating": "useful",
                "reason_codes": [],
            },
            headers={"x-adcs-fingerprint": "fp-adoption-ready"},
        )
        assert feedback_ready.status_code == 200

        resolve_only = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose OCR latest release"},
            headers={"x-adcs-fingerprint": "fp-adoption-resolve-only"},
        )
        assert resolve_only.status_code == 200

        self_test_blocked = client.get(
            "/v1/integrations/self-test",
            params={
                "product_id": "missing.product",
                "programming_language": "net",
                "client_id": "qwen-code",
                "transport": "streamable-http",
            },
            headers={"x-adcs-fingerprint": "fp-adoption-blocked"},
        )
        assert self_test_blocked.status_code == 200

        query_blocked = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use the latest OCR table recognition API?",
                "product_id": "missing.product",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-adoption-blocked"},
        )
        assert query_blocked.status_code == 200
        blocked_request_id = query_blocked.json()["request_id"]

        issue_blocked = client.post(
            "/v1/docs:issues",
            json={
                "request_id": blocked_request_id,
                "issue_type": "missing_docs",
                "notes": "No usable content was returned.",
            },
            headers={"x-adcs-fingerprint": "fp-adoption-blocked"},
        )
        assert issue_blocked.status_code == 200

        response = client.get(
            "/admin/v1/analytics/public-funnel",
            headers={"x-api-key": "replace-me"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["filtered_sessions_total"] >= 3
        assert payload["by_product_id"]["aspose.ocr"] >= 1
        assert payload["by_programming_language"]["net"] >= 1
        assert payload["by_client_id"]["cursor"] >= 1
        assert payload["by_client_id"]["qwen-code"] >= 1
        assert payload["stages"][0]["stage_id"] == "resolve"
        assert payload["stages"][0]["sessions"] >= 2
        assert payload["stages"][1]["stage_id"] == "self_test"
        assert payload["stages"][1]["sessions"] >= 2
        assert payload["stages"][2]["stage_id"] == "query"
        assert payload["stages"][2]["sessions"] >= 2
        assert payload["stages"][3]["stage_id"] == "feedback"
        assert payload["stages"][3]["sessions"] >= 1
        assert payload["stages"][4]["stage_id"] == "issue"
        assert payload["stages"][4]["sessions"] >= 1
        assert payload["top_dropoffs"]
        assert payload["top_dropoffs"][0]["dropoff_id"] in {
            "resolved_without_self_test",
            "query_zero_result_without_followup",
        }
        aspose_scope = next(
            item
            for item in payload["scopes"]
            if item["product_id"] == "aspose.ocr" and item["client_id"] == "cursor"
        )
        assert aspose_scope["query_sessions"] >= 1
        assert aspose_scope["feedback_sessions"] >= 1

        qwen_only = client.get(
            "/admin/v1/analytics/public-funnel",
            params={"client_id": "qwen-code"},
            headers={"x-api-key": "replace-me"},
        )
        assert qwen_only.status_code == 200
        qwen_payload = qwen_only.json()
        assert qwen_payload["filtered_sessions_total"] >= 1
        assert set(qwen_payload["by_client_id"]) == {"qwen-code"}


def test_admin_analytics_exposes_freshness_watchlist() -> None:
    app = create_app()
    with TestClient(app) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use the latest OCR table recognition API?",
                "product_id": "aspose.ocr",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-watchlist-1"},
        )
        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        feedback_response = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "not_useful",
                "reason_codes": ["outdated_version", "no_examples"],
            },
            headers={"x-adcs-fingerprint": "fp-watchlist-1"},
        )
        assert feedback_response.status_code == 200

        issue_response = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "outdated_docs",
                "notes": "The latest stable guidance looks stale.",
            },
            headers={"x-adcs-fingerprint": "fp-watchlist-1"},
        )
        assert issue_response.status_code == 200

        response = client.get(
            "/admin/v1/analytics/freshness-watchlist",
            params={"product_id": "aspose.ocr", "programming_language": "net", "limit": 10},
            headers={"x-api-key": "replace-me"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["filtered_scopes_total"] >= 1
        assert "aspose.ocr" in payload["by_product_id"]
        assert "net" in payload["by_programming_language"]
        assert payload["by_source_kind"]
        matching_item = next(
            item for item in payload["items"] if item["product_id"] == "aspose.ocr"
        )
        assert matching_item["source_kind"] in {"docs", "apiref"}
        assert matching_item["risk_level"] in {"low", "medium", "high"}
        assert matching_item["risk_score"] >= 0
        assert matching_item["primary_reason"]
        assert matching_item["recommended_action"]
        assert matching_item["service_status"]
        assert matching_item["issue_reports_30d"] >= 1
        assert isinstance(matching_item["fix_plan"], list)


def test_admin_analytics_exposes_usefulness_summary_and_negative_signals() -> None:
    app = create_app()
    with TestClient(app) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage latest stable?",
                "product_id": "aspose.ocr",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-feedback-1"},
        )
        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        feedback_response = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "not_useful",
                "reason_codes": ["outdated_version", "no_examples"],
            },
            headers={"x-adcs-fingerprint": "fp-feedback-1"},
        )
        assert feedback_response.status_code == 200
        assert feedback_response.json()["updated_existing"] is False

        overwrite_response = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "partially_useful",
                "reason_codes": ["incomplete_answer"],
            },
            headers={"x-adcs-fingerprint": "fp-feedback-1"},
        )
        assert overwrite_response.status_code == 200
        assert overwrite_response.json()["updated_existing"] is True

        summary = client.get(
            "/admin/v1/analytics/usefulness",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["total_feedback"] >= 1
        assert summary_payload["partially_useful_feedback"] >= 1
        assert summary_payload["by_reason_code"]["incomplete_answer"] >= 1
        assert summary_payload["recent_negative_signals"][0]["request_id"] == request_id

        signals = client.get(
            "/admin/v1/analytics/usefulness-signals",
            params={"tool": "query_docs", "negative_only": "true"},
            headers={"x-api-key": "replace-me"},
        )
        assert signals.status_code == 200
        signals_payload = signals.json()
        assert signals_payload
        assert signals_payload[0]["rating"] in {"partially_useful", "not_useful"}
        assert signals_payload[0]["request_id"] == request_id


def test_admin_analytics_exposes_issue_review_summary_and_signals() -> None:
    app = create_app()
    with TestClient(app) as client:
        first_query = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use the latest OCR table recognition API?",
                "product_id": "missing.product",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-issue-1"},
        )
        assert first_query.status_code == 200
        first_request_id = first_query.json()["request_id"]

        first_issue = client.post(
            "/v1/docs:issues",
            json={
                "request_id": first_request_id,
                "issue_type": "missing_docs",
                "notes": "The latest stable path returned no implementation guidance.",
            },
            headers={"x-adcs-fingerprint": "fp-issue-1"},
        )
        assert first_issue.status_code == 200

        second_query = client.post(
            "/v1/docs:query",
            json={
                "query": "Show me a migration example for the OCR release.",
                "product_id": "aspose.ocr",
                "language": "java",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-issue-2"},
        )
        assert second_query.status_code == 200
        second_request_id = second_query.json()["request_id"]

        second_issue = client.post(
            "/v1/docs:issues",
            json={
                "request_id": second_request_id,
                "issue_type": "bad_example",
                "notes": "The answer needs a more complete runnable example.",
            },
            headers={"x-adcs-fingerprint": "fp-issue-2"},
        )
        assert second_issue.status_code == 200

        summary = client.get(
            "/admin/v1/analytics/issues",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["total_reports"] >= 2
        assert summary_payload["by_issue_type"]["missing_docs"] >= 1
        assert summary_payload["by_severity"]["critical"] >= 1
        assert summary_payload["recent_reports"][0]["recommendation_title"]

        signals = client.get(
            "/admin/v1/analytics/issue-signals",
            params={"tool": "query_docs", "severity": "critical"},
            headers={"x-api-key": "replace-me"},
        )
        assert signals.status_code == 200
        signals_payload = signals.json()
        assert signals_payload
        assert signals_payload[0]["severity"] == "critical"
        assert signals_payload[0]["request_id"] == first_request_id
        assert signals_payload[0]["issue_type"] == "missing_docs"


def test_admin_request_evidence_replays_without_mutating_analytics_history() -> None:
    app = create_app()
    with TestClient(app) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use the latest OCR table recognition API?",
                "product_id": "missing.product",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-evidence-1"},
        )
        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        feedback_response = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "not_useful",
                "reason_codes": ["incomplete_answer"],
            },
            headers={"x-adcs-fingerprint": "fp-evidence-1"},
        )
        assert feedback_response.status_code == 200

        issue_response = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "missing_docs",
                "notes": "No usable example was returned.",
            },
            headers={"x-adcs-fingerprint": "fp-evidence-1"},
        )
        assert issue_response.status_code == 200

        before_slices = client.get(
            "/admin/v1/analytics/slices",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert before_slices.status_code == 200
        before_total_requests = before_slices.json()["total_requests"]

        evidence_response = client.get(
            "/admin/v1/analytics/request-evidence",
            params={"request_id": request_id},
            headers={"x-api-key": "replace-me"},
        )
        assert evidence_response.status_code == 200
        payload = evidence_response.json()
        assert payload["request_id"] == request_id
        assert payload["original"]["request_id"] == request_id
        assert (
            payload["replay"]["request"]["query"]
            == "How do I use the latest OCR table recognition API?"
        )
        assert payload["replay"]["request"]["product_id"] == "missing.product"
        assert payload["replay"]["response"]["request_id"] == f"replay:{request_id}"
        assert payload["replay"]["outcome"] == "no_results"
        assert payload["diff"]["drift_status"] == "stable"
        assert payload["diff"]["suspected_fault_domain"] == "coverage"
        assert "results" in payload["diff"]["unavailable_original_fields"]
        assert payload["related_issue_reports"][0]["request_id"] == request_id
        assert payload["related_usefulness_feedback"][0]["request_id"] == request_id
        assert payload["copy_context"]["request_id"] == request_id

        after_slices = client.get(
            "/admin/v1/analytics/slices",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert after_slices.status_code == 200
        assert after_slices.json()["total_requests"] == before_total_requests


def test_admin_issue_hotspots_group_repeated_reports_into_prioritized_clusters() -> None:
    app = create_app()
    with TestClient(app) as client:
        first_request_ids: list[str] = []
        for fingerprint in ("fp-hotspot-1", "fp-hotspot-2", "fp-hotspot-3"):
            query_response = client.post(
                "/v1/docs:query",
                json={
                    "query": "How do I use the latest OCR table recognition API?",
                    "product_id": "missing.product",
                    "language": "net",
                    "query_locale": "en",
                },
                headers={"x-adcs-fingerprint": fingerprint},
            )
            assert query_response.status_code == 200
            first_request_ids.append(query_response.json()["request_id"])

        for request_id in first_request_ids:
            issue_response = client.post(
                "/v1/docs:issues",
                json={
                    "request_id": request_id,
                    "issue_type": "missing_docs",
                    "notes": "Missing latest stable OCR coverage.",
                },
                headers={"x-adcs-fingerprint": f"actor-{request_id}"},
            )
            assert issue_response.status_code == 200

        second_query = client.post(
            "/v1/docs:query",
            json={
                "query": "Show me a migration example for the OCR release.",
                "product_id": "aspose.ocr",
                "language": "java",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-hotspot-java"},
        )
        assert second_query.status_code == 200
        second_request_id = second_query.json()["request_id"]

        second_issue = client.post(
            "/v1/docs:issues",
            json={
                "request_id": second_request_id,
                "issue_type": "bad_example",
                "notes": "Returned example is too short.",
            },
            headers={"x-adcs-fingerprint": "fp-hotspot-java"},
        )
        assert second_issue.status_code == 200

        overview = client.get(
            "/admin/v1/analytics/issue-hotspots",
            params={"tool": "query_docs"},
            headers={"x-api-key": "replace-me"},
        )
        assert overview.status_code == 200
        payload = overview.json()
        assert payload["filtered_reports_total"] >= 4
        assert payload["hotspots_total"] >= 2
        assert payload["by_priority"]["highest"] >= 1
        assert payload["clusters"][0]["issue_type"] == "missing_docs"
        assert payload["clusters"][0]["priority"] == "highest"
        assert payload["clusters"][0]["total_reports"] >= 3
        assert payload["clusters"][0]["primary_warning_code"] == "no_index_data"
        assert payload["clusters"][0]["sample_request_ids"]


def test_admin_request_evidence_can_create_guided_fix_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()
    with TestClient(app) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use OCR API from Rust?",
                "product_id": "aspose.ocr",
                "language": "rust",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-fix-draft-1"},
        )
        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        issue_response = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "missing_docs",
                "notes": "Rust coverage is missing from the indexed latest-stable scope.",
            },
            headers={"x-adcs-fingerprint": "fp-fix-draft-1"},
        )
        assert issue_response.status_code == 200

        create_draft = client.post(
            "/admin/v1/analytics/request-evidence:create-fix-draft",
            json={"request_id": request_id},
            headers={"x-api-key": "owner-token"},
        )
        assert create_draft.status_code == 200
        payload = create_draft.json()
        assert payload["request_id"] == request_id
        assert payload["product_id"] == "aspose.ocr"
        assert payload["issue_type"] == "missing_docs"
        assert payload["quality_review_run"]["trigger_type"] == "manual"
        assert payload["quality_review_run"]["origin"]["request_id"] == request_id
        assert payload["quality_review_run"]["origin"]["issue_id"] == payload["issue_id"]
        assert (
            payload["quality_review_run"]["guided_fix_plan"]["summary"]
            == payload["fix_plan"]["summary"]
        )
        assert payload["fix_plan"]["actions"][0]["target_section"] == "analytics"
        assert payload["fix_plan"]["actions"][1]["target_section"] == "ingestion-jobs"

        runs_response = client.get(
            "/admin/v1/quality-reviews/runs",
            params={"product_id": "aspose.ocr"},
            headers={"x-api-key": "owner-token"},
        )
        assert runs_response.status_code == 200
        runs_payload = runs_response.json()
        assert runs_payload[0]["run_id"] == payload["quality_review_run"]["run_id"]
