import pytest
from pydantic import ValidationError

from adcs.api.main import create_app
from adcs.config import (
    AbuseGuardMode,
    EnvironmentProfile,
    QualityGatePhase,
    RerankerBackend,
    clear_settings_cache,
    get_settings,
)
from adcs.worker.celery_app import create_celery_app


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_settings_supports_profiles_and_csv_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_ENV", "staging")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "staging-key-123")
    monkeypatch.setenv("ADCS_MCP_SUPPORTED_REVISIONS", "2025-11-25,2025-06-18,2024-11-05")
    monkeypatch.setenv("ADCS_ABUSE_GUARD_MODE", "observe-only")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ADCS_INGESTION_RETRY_MAX_ATTEMPTS", "6")
    monkeypatch.setenv("ADCS_INGESTION_RETRY_BACKOFF_BASE_SECONDS", "4")
    monkeypatch.setenv("ADCS_INGESTION_RETRY_BACKOFF_MAX_SECONDS", "32")
    monkeypatch.setenv("ADCS_INGESTION_PUBLISH_SAFETY_MIN_COVERAGE_PCT", "55")

    settings = get_settings()

    assert settings.env_profile is EnvironmentProfile.STAGING
    assert settings.abuse_guard_mode is AbuseGuardMode.OBSERVE_ONLY
    assert settings.mcp_supported_revisions == ("2025-11-25", "2025-06-18", "2024-11-05")
    assert settings.ingestion_retry_max_attempts == 6
    assert settings.ingestion_retry_backoff_base_seconds == 4
    assert settings.ingestion_retry_backoff_max_seconds == 32
    assert settings.ingestion_publish_safety_min_coverage_pct == 55.0
    assert str(settings.ingestion_llm_policy_config_path).endswith("ingestion_llm_policy.json")
    assert str(settings.ingestion_prompt_registry_config_path).endswith(
        "ingestion_prompt_registry.json"
    )
    assert settings.quality_gate_phase is QualityGatePhase.MVP
    assert settings.reranker_backend is RerankerBackend.ADVANCED_HEURISTIC
    assert settings.safe_summary()["admin_api_key"] == "********"
    assert settings.safe_summary()["ingestion_publish_safety_min_coverage_pct"] == 55.0
    assert str(settings.release_catalog_config_path).endswith("release_catalog.json")


def test_settings_rejects_dev_json_keys_source_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_ENV", "prod")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "prod-key-123")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "json_dev")

    with pytest.raises(ValidationError):
        get_settings()


def test_api_startup_fails_fast_on_invalid_profile_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_ENV", "staging")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "replace-me")

    with pytest.raises(RuntimeError, match="Invalid ADCS runtime configuration"):
        create_app()


def test_worker_startup_fails_fast_on_invalid_profile_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_ENV", "staging")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "replace-me")

    with pytest.raises(RuntimeError, match="Invalid ADCS runtime configuration"):
        create_celery_app()
