from __future__ import annotations

import json

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


@pytest.fixture
def sample_retrieval_catalog(tmp_path, monkeypatch):
    """Exercise engine policy with a minimal external plugin, not an installed product."""
    from adcs.retrieval.profiles import load_profiles

    profile = {
        "schema_version": 1, "profile_id": "test-words-policy", "version": "1",
        "product_id": "aspose.words", "language": "net",
        "excluded_namespaces": ["Aspose.Words.LowCode"],
        "rules": [{
            "rule_id": "test-word-to-pdf", "all_terms": ["pdf"],
            "any_terms": ["doc", "docx", "word", "document"],
            "any_phrases": ["to pdf", "as pdf"],
            "preferred_symbols": ["Aspose.Words.Document.Save"],
        }],
    }
    manifest = {
        "contract": "adcs.extraction.v1", "plugin_id": "aspose.words.net",
        "version": "1.0.0", "product_id": "aspose.words", "language": "net",
        "title": "Test fixture", "worker": ["{python}", "worker.py"],
        "sources": {"docs": {
            "repo_id": "test.docs", "path": "sources/docs", "prefix": "net",
            "layout": {}, "canonical_base_url": "https://example.com/docs",
            "url": "https://example.com/docs.git", "branch": "main",
        }},
        "retrieval_profile": "profile.json",
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    (tmp_path / "plugin.json").write_text(json.dumps(manifest))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"plugins": ["plugin.json"], "compositions": []}))
    monkeypatch.setenv("ADCS_RETRIEVAL_PLUGIN_CATALOG", str(catalog))
    load_profiles.cache_clear()
    yield
    load_profiles.cache_clear()
