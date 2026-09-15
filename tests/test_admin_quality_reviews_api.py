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
                        "key_id": "owner-key",
                        "token": "owner-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": ["write:settings"],
                    },
                    {
                        "key_id": "viewer-key",
                        "token": "viewer-token",
                        "is_superuser": False,
                        "enabled": True,
                        "product_scopes": ["aspose.ocr"],
                        "scopes": [],
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


def _default_run_payload() -> dict[str, object]:
    return {
        "product_id": "aspose.ocr",
        "version": "24.1",
        "source_revision": "rev-e007",
        "trigger_type": "major_change",
        "items": [
            {
                "source_path": "apiref/aspose.ocr/symbol-rich.md",
                "stratum": "apiref_symbol_rich",
                "simulated_score": 4.8,
            },
            {
                "source_path": "docs/aspose.ocr/shortcode.md",
                "stratum": "docs_shortcode",
                "simulated_score": 4.6,
            },
            {
                "source_path": "docs/aspose.ocr/html.md",
                "stratum": "docs_html_embed",
                "simulated_score": 4.7,
            },
        ],
    }


def test_quality_review_human_approval_flow_and_artifact_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        run_response = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        assert run_response.status_code == 200
        run_payload = run_response.json()
        assert run_payload["created_by"] == "agent"
        assert run_payload["status"] == "awaiting_approval"
        assert run_payload["summary"]["overall_score"] >= 4.3

        artifact_path = Path.cwd() / "artifacts" / run_payload["artifact_path"]
        assert artifact_path.exists()

        approve_response = client.post(
            f"/admin/v1/quality-reviews/runs/{run_payload['run_id']}:approve-all",
            headers={"x-api-key": "owner-token"},
        )
        assert approve_response.status_code == 200
        approved_payload = approve_response.json()
        assert approved_payload["status"] == "approved"
        assert any(
            action["action"] == "approve_all"
            for action in approved_payload["approval_trail"]
        )


def test_quality_review_auto_approve_mode_and_fail_fast_blocking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        policy_response = client.patch(
            "/admin/v1/quality-reviews/policy",
            json={
                "product_id": "aspose.ocr",
                "approval_mode": "auto_approve",
                "sample_size": 60,
                "threshold_score": 4.3,
            },
            headers={"x-api-key": "owner-token"},
        )
        assert policy_response.status_code == 200
        assert policy_response.json()["approval_mode"] == "auto_approve"

        auto_run = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        assert auto_run.status_code == 200
        auto_payload = auto_run.json()
        assert auto_payload["status"] == "approved"
        assert any(action["action"] == "auto_approve" for action in auto_payload["approval_trail"])

        blocked_run_payload = _default_run_payload()
        blocked_run_payload["items"] = [
            {
                "source_path": "apiref/aspose.ocr/hallucinated-symbol.md",
                "stratum": "apiref_symbol_rich",
                "simulated_score": 4.9,
                "simulated_blocking_error_type": "hallucinated_api_member",
            },
            {
                "source_path": "docs/aspose.ocr/shortcode.md",
                "stratum": "docs_shortcode",
                "simulated_score": 4.9,
            },
        ]
        blocked_run = client.post(
            "/admin/v1/quality-reviews/runs",
            json=blocked_run_payload,
            headers={"x-api-key": "owner-token"},
        )
        assert blocked_run.status_code == 200
        blocked_payload = blocked_run.json()
        assert blocked_payload["status"] == "blocked"
        assert blocked_payload["fail_fast_triggered"] is True
        assert blocked_payload["blocking_error_count"] == 1
        assert all(
            action["action"] != "auto_approve"
            for action in blocked_payload["approval_trail"]
        )


def test_quality_review_reject_endpoint_and_approval_trail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        run_response = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        assert run_response.status_code == 200
        run_id = run_response.json()["run_id"]

        reject_response = client.post(
            f"/admin/v1/quality-reviews/runs/{run_id}:reject",
            json={"reason": "Manual QA rejection from UI"},
            headers={"x-api-key": "owner-token"},
        )
        assert reject_response.status_code == 200
        rejected_payload = reject_response.json()
        assert rejected_payload["status"] == "rejected"
        assert any(action["action"] == "reject" for action in rejected_payload["approval_trail"])


def test_quality_review_scope_and_product_scope_enforcement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        missing_scope = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "viewer-token"},
        )
        assert missing_scope.status_code == 403
        assert "Missing required scope" in missing_scope.json()["detail"]["error"]["message"]

        product_scope_violation = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "foreign-owner-token"},
        )
        assert product_scope_violation.status_code == 403
        assert "Product scope violation" in (
            product_scope_violation.json()["detail"]["error"]["message"]
        )

        read_allowed = client.get(
            "/admin/v1/quality-reviews/runs?limit=5",
            headers={"x-api-key": "viewer-token"},
        )
        assert read_allowed.status_code == 200


def test_quality_review_batch_actions_support_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        run_a = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        run_b = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        assert run_a.status_code == 200
        assert run_b.status_code == 200
        run_ids = [run_a.json()["run_id"], run_b.json()["run_id"]]

        batch_approve = client.post(
            "/admin/v1/quality-reviews/runs:batch-approve-all",
            json={"run_ids": run_ids + ["missing-run-id"]},
            headers={"x-api-key": "owner-token"},
        )
        assert batch_approve.status_code == 200
        approve_payload = batch_approve.json()
        assert approve_payload["requested_count"] == 3
        assert approve_payload["applied_count"] == 2
        assert approve_payload["failed_count"] == 1

        batch_reject = client.post(
            "/admin/v1/quality-reviews/runs:batch-reject",
            json={"run_ids": run_ids, "reason": "Batch reject from test"},
            headers={"x-api-key": "owner-token"},
        )
        assert batch_reject.status_code == 200
        reject_payload = batch_reject.json()
        assert reject_payload["requested_count"] == 2
        assert reject_payload["applied_count"] == 2
        assert reject_payload["failed_count"] == 0
        assert all(item["run"]["status"] == "rejected" for item in reject_payload["results"])


def test_quality_review_diff_and_policy_preset_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_json_dev_keys(monkeypatch=monkeypatch, tmp_path=tmp_path)
    app = create_app()

    with TestClient(app) as client:
        baseline = client.post(
            "/admin/v1/quality-reviews/runs",
            json=_default_run_payload(),
            headers={"x-api-key": "owner-token"},
        )
        assert baseline.status_code == 200
        baseline_payload = baseline.json()

        blocked_payload = _default_run_payload()
        blocked_payload["source_revision"] = "rev-e008"
        blocked_payload["items"] = [
            {
                "source_path": "apiref/aspose.ocr/hallucinated-symbol.md",
                "stratum": "apiref_symbol_rich",
                "simulated_score": 4.9,
                "simulated_blocking_error_type": "hallucinated_api_member",
            },
            {
                "source_path": "docs/aspose.ocr/shortcode.md",
                "stratum": "docs_shortcode",
                "simulated_score": 4.9,
            },
        ]
        candidate = client.post(
            "/admin/v1/quality-reviews/runs",
            json=blocked_payload,
            headers={"x-api-key": "owner-token"},
        )
        assert candidate.status_code == 200
        candidate_payload = candidate.json()

        diff_response = client.get(
            "/admin/v1/quality-reviews/runs:diff",
            params={
                "baseline_run_id": baseline_payload["run_id"],
                "candidate_run_id": candidate_payload["run_id"],
            },
            headers={"x-api-key": "owner-token"},
        )
        assert diff_response.status_code == 200
        diff_payload = diff_response.json()
        assert diff_payload["status_before"] == baseline_payload["status"]
        assert diff_payload["status_after"] == candidate_payload["status"]
        assert diff_payload["status_changed"] is True
        assert diff_payload["blocking_findings_added"]

        presets = client.get(
            "/admin/v1/quality-reviews/policy-presets",
            headers={"x-api-key": "owner-token"},
        )
        assert presets.status_code == 200
        preset_ids = {item["preset_id"] for item in presets.json()}
        assert "balanced_default" in preset_ids
        assert "strict_release" in preset_ids
        assert "throughput_auto" in preset_ids

        apply_preset = client.post(
            "/admin/v1/quality-reviews/policy:apply-preset",
            json={"product_id": "aspose.ocr", "preset_id": "strict_release"},
            headers={"x-api-key": "owner-token"},
        )
        assert apply_preset.status_code == 200
        policy_payload = apply_preset.json()
        assert policy_payload["sample_size"] == 120
        assert policy_payload["threshold_score"] == 4.6
        assert policy_payload["approval_mode"] == "human_approve_all"
