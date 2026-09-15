from __future__ import annotations

import json
import time
import urllib.request
from typing import Any
from urllib import error

import pytest

from adcs.config import EmbeddingBackend, clear_settings_cache, get_settings
from adcs.indexing.embedding_provider import (
    DeterministicLocalEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from adcs.runtime.components import build_embedding_provider


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


class _Response:
    def __init__(self, vectors: list[list[float]]) -> None:
        self._body = json.dumps(
            {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]}
        ).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _provider(**kwargs: Any) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        base_url="http://embeddings.invalid/v1", model="test-model", api_key="", **kwargs
    )


def _record_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return sleeps


def test_single_attempt_provider_fails_without_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _record_sleeps(monkeypatch)
    calls: list[float] = []

    def refuse(req: object, *, timeout: float, context: object) -> _Response:
        calls.append(timeout)
        raise error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(RuntimeError, match="after 1 attempt"):
        _provider(max_retries=1, timeout_seconds=10.0).embed_texts(texts=("query",))

    assert calls == [10.0]
    assert sleeps == []


def test_retrying_provider_backs_off_between_attempts_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _record_sleeps(monkeypatch)
    attempts = 0

    def refuse(req: object, *, timeout: float, context: object) -> _Response:
        nonlocal attempts
        attempts += 1
        raise error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(RuntimeError, match="after 3 attempt"):
        _provider(max_retries=3, retry_backoff_base_seconds=2.0).embed_texts(texts=("a",))

    assert attempts == 3
    assert sleeps == [2.0, 4.0]


def test_retrying_provider_recovers_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _record_sleeps(monkeypatch)
    outcomes: list[Exception | _Response] = [
        error.URLError("reset"),
        _Response([[0.1, 0.2]]),
    ]

    def flaky(req: object, *, timeout: float, context: object) -> _Response:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", flaky)

    vectors = _provider(retry_backoff_base_seconds=1.0).embed_texts(texts=("a",))

    assert vectors == ((0.1, 0.2),)
    assert sleeps == [1.0]


def test_max_retries_must_allow_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        _provider(max_retries=0)


def test_embedding_progress_never_reaches_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def respond(req: urllib.request.Request, *, timeout: float, context: object) -> _Response:
        assert isinstance(req.data, bytes)
        texts = json.loads(req.data)["input"]
        return _Response([[1.0] for _ in texts])

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    provider = _provider(batch_size=2)

    provider.embed_texts(texts=("one",))
    single = capsys.readouterr()
    provider.embed_texts(texts=("one", "two", "three"))
    multi = capsys.readouterr()

    # stdout carries the MCP stdio protocol, so progress goes to stderr, and only for
    # multi-batch runs.
    assert single.out == "" and single.err == ""
    assert multi.out == "" and "embed: 3/3" in multi.err


def test_query_provider_fails_fast_and_ingestion_provider_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_EMBEDDING_BACKEND", EmbeddingBackend.OPENAI_COMPATIBLE.value)
    monkeypatch.setenv("ADCS_EMBEDDING_API_URL", "http://embeddings.invalid/v1")
    settings = get_settings()

    ingestion = build_embedding_provider(settings)
    query = build_embedding_provider(settings, for_queries=True)

    assert isinstance(ingestion, OpenAICompatibleEmbeddingProvider)
    assert isinstance(query, OpenAICompatibleEmbeddingProvider)
    assert (ingestion._max_retries, ingestion._timeout) == (5, 30.0)
    assert (query._max_retries, query._timeout) == (1, 10.0)


def test_query_provider_for_ollama_uses_a_short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_EMBEDDING_BACKEND", EmbeddingBackend.OLLAMA.value)
    settings = get_settings()

    ingestion = build_embedding_provider(settings)
    query = build_embedding_provider(settings, for_queries=True)

    assert isinstance(ingestion, OllamaEmbeddingProvider)
    assert isinstance(query, OllamaEmbeddingProvider)
    assert (ingestion._timeout, query._timeout) == (300.0, 10.0)


def test_deterministic_backend_needs_no_network_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_EMBEDDING_BACKEND", EmbeddingBackend.DETERMINISTIC.value)
    settings = get_settings()

    assert isinstance(build_embedding_provider(settings), DeterministicLocalEmbeddingProvider)
    assert isinstance(
        build_embedding_provider(settings, for_queries=True), DeterministicLocalEmbeddingProvider
    )
