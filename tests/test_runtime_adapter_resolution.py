from __future__ import annotations

import pytest
from pydantic import ValidationError

from adcs.config import (
    EnvironmentProfile,
    PersistenceBackend,
    RetrievalBackend,
    Settings,
    clear_settings_cache,
)
from adcs.runtime import resolve_runtime_adapters


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_auto_runtime_adapters_resolve_to_memory_in_test_runtime() -> None:
    settings = Settings()

    resolved = resolve_runtime_adapters(settings=settings, is_test_runtime=True)

    assert resolved.persistence_backend is PersistenceBackend.MEMORY
    assert resolved.retrieval_backend is RetrievalBackend.MEMORY
    assert resolved.is_test_runtime is True


def test_auto_runtime_adapters_resolve_to_real_backends_outside_test_runtime() -> None:
    settings = Settings()

    resolved = resolve_runtime_adapters(settings=settings, is_test_runtime=False)

    assert resolved.persistence_backend is PersistenceBackend.POSTGRES
    assert resolved.retrieval_backend is RetrievalBackend.QDRANT_OPENSEARCH
    assert resolved.is_test_runtime is False


def test_explicit_backend_overrides_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "memory")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "memory")
    settings = Settings()

    resolved = resolve_runtime_adapters(settings=settings, is_test_runtime=False)

    assert resolved.persistence_backend is PersistenceBackend.MEMORY
    assert resolved.retrieval_backend is RetrievalBackend.MEMORY


def test_staging_runtime_rejects_memory_persistence_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_ENV", "staging")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "staging-key-123")
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "memory")
    settings = Settings()

    with pytest.raises(RuntimeError, match="must not use in-memory persistence backend"):
        resolve_runtime_adapters(settings=settings, is_test_runtime=False)


def test_prod_runtime_rejects_memory_retrieval_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_ENV", "prod")
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-hash-secret")
    monkeypatch.setenv("ADCS_API_KEY", "prod-key-123")
    monkeypatch.setenv("ADCS_EMBEDDING_BACKEND", "ollama")
    monkeypatch.setenv("ADCS_EMBEDDING_API_URL", "http://localhost:11434")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "memory")

    with pytest.raises(ValidationError, match="memory is not allowed for prod profile"):
        Settings()


def test_dev_runtime_can_use_memory_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "memory")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "memory")
    settings = Settings()

    resolved = resolve_runtime_adapters(settings=settings, is_test_runtime=False)

    assert settings.env_profile is EnvironmentProfile.DEV
    assert resolved.persistence_backend is PersistenceBackend.MEMORY
    assert resolved.retrieval_backend is RetrievalBackend.MEMORY
