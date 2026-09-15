from __future__ import annotations

import pytest

from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _default_test_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic regardless of local .env/.env.local values."""
    monkeypatch.setenv("ADCS_ENV", "dev")
    monkeypatch.setenv("ADCS_API_KEY", "replace-me")
    monkeypatch.setenv("ADCS_ADMIN_KEYS_SOURCE", "env")
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "auto")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "auto")
    # Pin the embedding backend too. Otherwise, on any machine whose .env.local
    # selects `openai_compatible`, the suite calls a live LLM endpoint for real:
    # tests that trigger a reindex embed live, at real cost, with 5 retries and
    # exponential backoff, and `make test` passes or hangs depending on that
    # third-party endpoint's latency (for example a >20-minute hang in
    # `test_webmcp_trigger_reindex_happy_path`).
    monkeypatch.setenv("ADCS_EMBEDDING_BACKEND", "deterministic")
    clear_settings_cache()
    yield
    clear_settings_cache()
