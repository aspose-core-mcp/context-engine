from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adcs.api.main import create_app
from adcs.ingestion.chunking import StageDChunkRecord


@pytest.fixture
def app_with_public_records() -> FastAPI:
    app = create_app()
    records = _sample_chunk_records()
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
            if _scope_match(record.product_id, product_id)
            and _scope_match(record.programming_language, programming_language)
            and _scope_match(record.version, version)
        )

    orchestrator.get_latest_chunk_records = _patched_get_latest_chunk_records  # type: ignore[method-assign]
    # Disable Qdrant direct lookup so the test exercises the state-store fallback path.
    app.state.public_query_service._qdrant_url = None  # type: ignore[attr-defined]
    return app


def test_resolve_product_endpoint_returns_contract_shape(app_with_public_records: FastAPI) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/products:resolve",
            json={"query": "Aspose.OCR for .NET"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["language"] == "net"
    assert "aspose.ocr" in payload["aliases"]
    assert isinstance(payload["confidence"], float)


def test_query_docs_endpoint_returns_parity_contract(app_with_public_records: FastAPI) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
                "top_k": 2,
                "strict_version": True,
                "doc_types": ["api_reference", "guide"],
                "include_examples": True,
                "debug": True,
            },
            # The debug payload is privileged; the endpoint itself stays
            # unauthenticated. Anonymous callers get `debug: null`, so
            # exercising the debug contract needs a key. The dedicated gating
            # test lives in
            # tests/test_error_handling_hardening.py.
            headers={"x-api-key": "replace-me"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_id"]
    assert payload["request_id"]
    assert payload["mode"] in {"task", "symbol", "migration"}
    assert payload["query_locale_detected"] == "en"
    assert payload["translation_fallback_applied"] is False
    assert isinstance(payload["confidence"], float)
    assert payload["confidence_level"] in {"low", "medium", "high"}
    assert "fallback_reason" in payload
    assert "version_resolution" in payload
    assert isinstance(payload["clarification_questions"], list)
    assert payload["quality"]["intent"] in {
        "symbol_lookup",
        "how_to",
        "troubleshooting",
        "release_notes",
        "general_reference",
    }
    assert "freshness_source" in payload["quality"]
    assert payload["quality"]["overall_score"] >= 0.0
    assert payload["version_resolution"]["preferred_version"] == "25.1"
    assert payload["version_resolution"]["strict_version_enforced"] is True
    assert isinstance(payload["results"], list)
    assert payload["results"]
    assert payload["api_guardrails"]
    assert payload["explainability"]["reranker_backend"] in {
        "deterministic",
        "advanced_heuristic",
    }
    first = payload["results"][0]
    assert first["chunk_id"]
    assert first["canonical_url"]
    assert "score" in first
    assert payload["debug"]["intent"] == payload["quality"]["intent"]
    assert payload["debug"]["intent_subtype"] == payload["quality"]["intent_subtype"]
    assert "intent_reason_codes" in payload["debug"]
    assert "detected_version_tokens" in payload["debug"]
    assert payload["debug"] is not None


def test_query_docs_feedback_endpoint_accepts_request_id_and_deduplicates(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-public-feedback"},
        )

        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        first_feedback = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "partially_useful",
                "reason_codes": ["incomplete_answer"],
            },
            headers={"x-adcs-fingerprint": "fp-public-feedback"},
        )
        second_feedback = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "not_useful",
                "reason_codes": ["outdated_version"],
            },
            headers={"x-adcs-fingerprint": "fp-public-feedback"},
        )

    assert first_feedback.status_code == 200
    first_payload = first_feedback.json()
    assert first_payload["updated_existing"] is False
    assert first_payload["request_id"] == request_id

    assert second_feedback.status_code == 200
    second_payload = second_feedback.json()
    assert second_payload["updated_existing"] is True
    assert second_payload["rating"] == "not_useful"
    assert second_payload["reason_codes"] == ["outdated_version"]


def test_query_docs_issue_endpoint_accepts_request_id_and_deduplicates(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-public-issue"},
        )

        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        first_issue = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "missing_docs",
                "notes": "No migration note was cited.",
            },
            headers={"x-adcs-fingerprint": "fp-public-issue"},
        )
        second_issue = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "wrong_docs",
                "notes": "The cited answer points to the wrong SDK flow.",
            },
            headers={"x-adcs-fingerprint": "fp-public-issue"},
        )

    assert first_issue.status_code == 200
    first_payload = first_issue.json()
    assert first_payload["updated_existing"] is False
    assert first_payload["request_id"] == request_id
    assert first_payload["issue_type"] == "missing_docs"

    assert second_issue.status_code == 200
    second_payload = second_issue.json()
    assert second_payload["updated_existing"] is True
    assert second_payload["issue_type"] == "wrong_docs"


def test_query_docs_repro_pack_returns_public_safe_replay_payload(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        query_response = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "query_locale": "en",
            },
            headers={"x-adcs-fingerprint": "fp-public-repro"},
        )
        assert query_response.status_code == 200
        request_id = query_response.json()["request_id"]

        feedback_response = client.post(
            "/v1/docs:feedback",
            json={
                "request_id": request_id,
                "rating": "useful",
                "reason_codes": [],
            },
            headers={"x-adcs-fingerprint": "fp-public-repro"},
        )
        assert feedback_response.status_code == 200

        issue_response = client.post(
            "/v1/docs:issues",
            json={
                "request_id": request_id,
                "issue_type": "wrong_docs",
                "notes": "The cited answer skipped one API detail.",
            },
            headers={"x-adcs-fingerprint": "fp-public-repro"},
        )
        assert issue_response.status_code == 200

        repro_response = client.get(
            "/v1/docs:repro-pack",
            params={"request_id": request_id},
        )

    assert repro_response.status_code == 200
    payload = repro_response.json()
    assert payload["request_id"] == request_id
    assert payload["share_url"].endswith(f"/integrations?shared_request_id={request_id}")
    assert payload["scope"]["raw_query"] == "How do I use RecognizeImage?"
    assert payload["original"]["outcome"] in {"success", "low_confidence", "no_results"}
    assert payload["replay"]["citations"]
    assert payload["linked_signals"]["total_feedback"] == 1
    assert payload["linked_signals"]["total_issue_reports"] == 1
    assert payload["linked_signals"]["issue_types"] == ["wrong_docs"]
    keys = _collect_json_keys(payload)
    assert "hashed_ip" not in keys
    assert "fingerprint" not in keys
    assert "actor_identity" not in keys
    assert "notes" not in keys
    serialized = json.dumps(payload)
    assert "The cited answer skipped one API detail." not in serialized


def test_query_docs_reports_non_strict_version_fallback_resolution(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/docs:query",
            json={
                "query": "latest stable migration notes for Aspose OCR 26.0",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "26.0",
                "query_locale": "en",
                "top_k": 3,
                "strict_version": False,
                "debug": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version_resolution"]["fallback_applied"] is True
    assert payload["version_resolution"]["fallback_reason"] == "version_fallback_nearest_available"
    assert "version_fallback_applied" in payload["warnings"]


def test_query_docs_extracts_release_guardrails_from_migration_note(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/docs:query",
            json={
                "query": "breaking change OldRecognize migrate",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
                "top_k": 5,
                "strict_version": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert any("RecognizeImage" in item for item in payload["api_guardrails"])


def test_query_docs_reports_translation_dependency_warning_when_unavailable(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/docs:query",
            json={
                "query": "Wie erkenne ich Text?",
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "query_locale": "de",
                "top_k": 2,
                "strict_version": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_locale_detected"] == "de"
    assert payload["translation_fallback_applied"] is False
    assert "translation_dependency_unavailable" in payload["warnings"]


def test_query_docs_reports_completeness_and_fallback_for_empty_scope(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/docs:query",
            json={
                "query": "How do I use Aspose.Words mail merge?",
                "product_id": "aspose.words",
                "language": "net",
                "version": "25.1",
                "query_locale": "en",
                "top_k": 3,
                "strict_version": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"] == []
    assert payload["fallback_reason"] == "no_candidates"
    assert payload["clarification_questions"]
    assert "no_index_data" in payload["warnings"]
    assert "answer_incomplete" in payload["warnings"]
    assert payload["quality"]["completeness_status"] == "insufficient"
    assert payload["quality"]["coverage_score"] == 0.0


def test_get_symbol_doc_endpoint_returns_not_found_error_shape(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/symbols:get",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "symbol_fqn": "Aspose.OCR.Missing.Symbol",
            },
        )

    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"]["error"]["code"] == "NOT_FOUND"
    assert payload["detail"]["error"]["request_id"]


def test_get_symbol_doc_endpoint_returns_symbol_payload(app_with_public_records: FastAPI) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/symbols:get",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "version": "25.1",
                "symbol_fqn": "Aspose.OCR.AsposeOcr.RecognizeImage",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol_fqn"] == "Aspose.OCR.AsposeOcr.RecognizeImage"
    assert payload["signature"]
    assert "citations" in payload
    assert payload["returns"] == "RecognitionResult"
    assert payload["parameters"][0]["name"] == "imagePath"
    assert payload["parameters"][0]["type"] == "string"
    assert payload["signature_variants"]
    assert payload["guardrails"]


def test_list_breaking_changes_endpoint_returns_paginated_items(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/changes:list",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "from_version": "25.0",
                "to_version": "25.1",
                "page": 1,
                "page_size": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert isinstance(payload["total"], int)
    assert isinstance(payload["items"], list)


def test_list_latest_release_features_endpoint_returns_release_items(
    app_with_public_records: FastAPI,
) -> None:
    with TestClient(app_with_public_records) as client:
        response = client.post(
            "/v1/releases:latest",
            json={
                "product_id": "aspose.ocr",
                "language": "net",
                "top_k": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == "aspose.ocr"
    assert payload["language"] == "net"
    assert payload["resolved_version"] == "25.1"
    assert payload["items"]
    assert payload["guardrails"]
    first = payload["items"][0]
    assert first["kind"] in {
        "feature",
        "replacement",
        "deprecation",
        "removal",
        "breaking_change",
    }
    assert first["summary"]
    assert first["citation"]["canonical_url"]


def _collect_json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value.keys())
        for item in value.values():
            keys.update(_collect_json_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_collect_json_keys(item))
        return keys
    return set()


def _sample_chunk_records() -> tuple[StageDChunkRecord, ...]:
    return (
        _record(
            chunk_id="chunk-api-signature",
            source_kind="apiref",
            doc_type="api_signature",
            symbol_fqn="Aspose.OCR.AsposeOcr.RecognizeImage",
            title="RecognizeImage Method",
            text=(
                "public RecognitionResult RecognizeImage(string imagePath)\n"
                "Recognize text from one image."
            ),
            canonical_url="https://reference.aspose.com/ocr/net/asposeocr/recognizeimage/",
            section_anchor="#recognizeimage",
            chunk_type="api_signature",
        ),
        _record(
            chunk_id="chunk-guide",
            source_kind="docs",
            doc_type="guide_step",
            symbol_fqn=None,
            title="How to Recognize Text",
            text="Use Aspose.OCR.AsposeOcr.RecognizeImage in a simple setup flow.",
            canonical_url="https://docs.aspose.com/ocr/net/quickstart/",
            section_anchor="#how-to-recognize-text",
            chunk_type="guide_step",
        ),
        _record(
            chunk_id="chunk-breaking",
            source_kind="docs",
            doc_type="release_notes",
            symbol_fqn="Aspose.OCR.LegacyAPI.OldRecognize",
            title="Breaking Changes in 25.1",
            text="Breaking change: OldRecognize is deprecated, migrate to RecognizeImage.",
            canonical_url="https://docs.aspose.com/ocr/net/release-notes/25-1/",
            section_anchor="#breaking-changes",
            chunk_type="migration_note",
        ),
    )


def _record(
    *,
    chunk_id: str,
    source_kind: str,
    doc_type: str,
    symbol_fqn: str | None,
    title: str,
    text: str,
    canonical_url: str,
    section_anchor: str,
    chunk_type: str,
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id=f"aspose.ocr.{source_kind}",
        product_id="aspose.ocr",
        product_family="Aspose.OCR",
        programming_language="net",
        version="25.1",
        source_kind=source_kind,
        doc_locale="en",
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=title,
        section_path=("root", title),
        canonical_url=canonical_url,
        section_anchor=section_anchor,
        source_path=f"source/{chunk_id}.md",
        source_revision="revision-abc123",
        is_deprecated=doc_type == "release_notes",
        has_code_example=False,
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum=f"checksum-{chunk_id}",
    )


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()


def test_admin_retrieval_settings_reach_the_query_path() -> None:
    """An operator's change must affect retrieval, not just the audit trail.

    The per-product retrieval settings service is exposed over the admin API and
    records every change, but it was injected into nothing — the query path ran a
    hardcoded 0.15 suppression threshold while the settings said 0.35, so every
    operator adjustment was an audited no-op.
    """
    from adcs.api.public_docs_query import PublicQueryService

    class _Stub:
        def __init__(self, threshold: float) -> None:
            self._threshold = threshold
            self.calls: list[str] = []

        def resolve(self, *, product_id: str):  # type: ignore[no-untyped-def]
            self.calls.append(product_id)
            return type("R", (), {"low_confidence_threshold": self._threshold})()

    stub = _Stub(0.42)
    service = PublicQueryService.__new__(PublicQueryService)
    service._retrieval_settings_service = stub  # type: ignore[attr-defined]
    assert service._resolve_suppression_threshold(product_id="aspose.ocr") == 0.42
    assert stub.calls == ["aspose.ocr"], "the settings service must actually be consulted"

    # No service wired (embedded runtimes, tests) falls back to the documented default.
    service._retrieval_settings_service = None  # type: ignore[attr-defined]
    assert service._resolve_suppression_threshold(product_id="aspose.ocr") == 0.15

    # A broken settings backend must never take the query down with it.
    class _Broken:
        def resolve(self, *, product_id: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("settings store unavailable")

    service._retrieval_settings_service = _Broken()  # type: ignore[attr-defined]
    assert service._resolve_suppression_threshold(product_id="aspose.ocr") == 0.15

    # Out-of-range values are ignored rather than trusted.
    service._retrieval_settings_service = _Stub(7.5)  # type: ignore[attr-defined]
    assert service._resolve_suppression_threshold(product_id="aspose.ocr") == 0.15
