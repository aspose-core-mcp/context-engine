"""Embedding provider interfaces and implementations."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import urllib.request
from collections.abc import Sequence
from typing import Any, Protocol
from urllib import error

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Contract for Stage-E embedding providers."""

    def embed_texts(self, *, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Return one embedding vector per input text."""


class OllamaEmbeddingProvider:
    """Production embedding provider using Ollama REST API.

    Adaptively batches texts to stay within the model's context window.
    Uses num_ctx=32768 via API options for extended context support.
    """

    _MAX_TEXT_CHARS = 4500  # safe even for worst-case tokenization (spaced HTML tags)
    _MAX_BATCH_CHARS = 4500  # one text per batch for safety
    _NUM_CTX = 32768  # context window hint passed to Ollama API

    def __init__(
        self,
        *,
        model: str = "nomic-embed-text",
        ollama_url: str = "http://localhost:11434",
        timeout_seconds: float = 300.0,
    ) -> None:
        self._model = model
        self._url = f"{ollama_url}/api/embed"
        self._timeout = timeout_seconds
        self._dimensions: int | None = None

    def embed_texts(self, *, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        import time as _t

        max_chars = self._MAX_TEXT_CHARS
        safe_texts = [t[:max_chars] if len(t) > max_chars else t for t in texts]
        total = len(safe_texts)
        all_vectors: list[tuple[float, ...]] = []
        batch: list[str] = []
        batch_chars = 0
        t0 = _t.monotonic()
        for text in safe_texts:
            text_len = len(text)
            if batch and (batch_chars + text_len) > self._MAX_BATCH_CHARS:
                all_vectors.extend(self._embed_batch(batch=batch))
                done = len(all_vectors)
                elapsed = _t.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(
                    f"\r  embed: {done}/{total} ({done*100//total}%) "
                    f"| {rate:.1f} chunks/s | ETA {eta:.0f}s",
                    end="", flush=True, file=sys.stderr,
                )
                batch = []
                batch_chars = 0
            batch.append(text)
            batch_chars += text_len
        if batch:
            all_vectors.extend(self._embed_batch(batch=batch))
        if total > 1:
            elapsed = _t.monotonic() - t0
            rate = total / elapsed if elapsed > 0 else 0
            print(
                f"\r  embed: {total}/{total} (100%) "
                f"| {rate:.1f} chunks/s | done",
                flush=True, file=sys.stderr,
            )
        return tuple(all_vectors)

    _CONTEXT_RETRY_FACTOR = 0.6  # truncate to 60% on context overflow

    def _embed_batch(self, *, batch: list[str]) -> list[tuple[float, ...]]:
        status, result = self._embed_batch_raw(batch=batch)
        if status == "ok":
            return result
        # Context overflow — retry each text individually with truncation
        logger.warning(
            "Batch embed failed, retrying %d texts individually",
            len(batch),
        )
        results: list[tuple[float, ...]] = []
        for text in batch:
            results.append(self._embed_single_safe(text=text))
        return results

    def _embed_single_safe(self, *, text: str) -> tuple[float, ...]:
        current = text
        for _attempt in range(4):
            status, result = self._embed_batch_raw(batch=[current])
            if status == "ok":
                return result[0]
            new_len = int(len(current) * self._CONTEXT_RETRY_FACTOR)
            logger.warning(
                "Text %d chars exceeds context, truncating to %d",
                len(current),
                new_len,
            )
            current = current[:new_len]
        status, result = self._embed_batch_raw(batch=[current])
        if status != "ok":
            msg = f"Embedding failed after repeated truncation ({len(current)} chars)"
            raise RuntimeError(msg)
        return result[0]

    def _embed_batch_raw(
        self, *, batch: list[str]
    ) -> tuple[str, list[tuple[float, ...]]]:
        payload = json.dumps({
            "model": self._model,
            "input": batch,
            "options": {"num_ctx": self._NUM_CTX},
        }).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
        except error.HTTPError as exc:
            if exc.code == 400:
                exc.read()  # consume response body
                return ("context_overflow", [])
            raise
        embeddings = data["embeddings"]
        if len(embeddings) != len(batch):
            msg = (
                f"Ollama returned {len(embeddings)} embeddings "
                f"for {len(batch)} inputs."
            )
            raise ValueError(msg)
        result = [tuple(float(v) for v in vec) for vec in embeddings]
        if self._dimensions is None and result:
            self._dimensions = len(result[0])
            logger.info(
                "Ollama embedding model=%s dimensions=%d",
                self._model,
                self._dimensions,
            )
        return ("ok", result)


class OpenAICompatibleEmbeddingProvider:
    """Embedding provider using OpenAI-compatible /v1/embeddings API."""

    _MAX_TEXT_CHARS = 8000
    _DEFAULT_BATCH_SIZE = 8

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        batch_size: int | None = None,
        max_text_chars: int | None = None,
        max_retries: int = 5,
        retry_backoff_base_seconds: float = 10.0,
    ) -> None:
        if max_retries < 1:
            msg = "max_retries must be >= 1."
            raise ValueError(msg)
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base_seconds
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._batch_size = batch_size or self._DEFAULT_BATCH_SIZE
        self._max_text_chars = max_text_chars or self._MAX_TEXT_CHARS
        self._dimensions: int | None = None

    def embed_texts(
        self, *, texts: Sequence[str]
    ) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        import time as _t

        max_c = self._max_text_chars
        safe = [t[:max_c] if len(t) > max_c else t for t in texts]
        total = len(safe)
        all_vecs: list[tuple[float, ...]] = []
        t0 = _t.monotonic()
        for start in range(0, total, self._batch_size):
            batch = safe[start : start + self._batch_size]
            all_vecs.extend(self._call_api(batch=batch))
            if total <= self._batch_size:
                continue
            done = len(all_vecs)
            elapsed = _t.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            pct = done * 100 // total
            print(
                f"\r  embed: {done}/{total} ({pct}%) "
                f"| {rate:.1f} chunks/s | ETA {eta:.0f}s",
                end="",
                flush=True,
                file=sys.stderr,
            )
        if total > self._batch_size:
            print(flush=True, file=sys.stderr)  # newline after progress
        return tuple(all_vecs)

    def _call_api(
        self, *, batch: list[str]
    ) -> list[tuple[float, ...]]:
        import time as _time

        body: dict[str, Any] = {"model": self._model, "input": batch}
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = json.dumps(body).encode()
        # The request carries the embedding API key, so the certificate must be
        # verified: without it any on-path party can present its own certificate
        # and harvest the key together with the user's query text (see
        # docs/data-protection-and-pii.md). certifi is used for the same reason as
        # in translation_fallback — the python.org macOS build ships no system CA
        # store.
        ctx = None
        if self._url.startswith("https"):
            import ssl

            try:
                import certifi

                ctx = ssl.create_default_context(cafile=certifi.where())
            except (ImportError, OSError):
                ctx = ssl.create_default_context()

        last_exc: Exception | None = None
        import socket

        prev_default_timeout = socket.getdefaulttimeout()
        for attempt in range(self._max_retries):
            req = urllib.request.Request(
                self._url,
                data=payload,
                headers=headers,
                method="POST",
            )
            try:
                socket.setdefaulttimeout(self._timeout)
                with urllib.request.urlopen(
                    req, timeout=self._timeout, context=ctx
                ) as resp:
                    data = json.loads(resp.read())
                break
            except (
                error.HTTPError, error.URLError, TimeoutError,
                ConnectionResetError, OSError,
            ) as exc:
                last_exc = exc
                code = getattr(exc, "code", None)
                if isinstance(exc, error.HTTPError):
                    exc.read()  # consume body
                if attempt + 1 >= self._max_retries:
                    logger.warning(
                        "Embedding API error (attempt %d/%d, code=%s): %s",
                        attempt + 1,
                        self._max_retries,
                        code,
                        str(exc)[:120],
                    )
                    continue
                wait = self._retry_backoff_base * (2 ** attempt)
                logger.warning(
                    "Embedding API error (attempt %d/%d, code=%s): %s. "
                    "Retrying in %.0fs",
                    attempt + 1,
                    self._max_retries,
                    code,
                    str(exc)[:120],
                    wait,
                )
                _time.sleep(wait)
        else:
            socket.setdefaulttimeout(prev_default_timeout)
            msg = f"Embedding API failed after {self._max_retries} attempt(s)"
            raise RuntimeError(msg) from last_exc

        socket.setdefaulttimeout(prev_default_timeout)
        items = sorted(data["data"], key=lambda d: d["index"])
        result = [tuple(float(v) for v in item["embedding"]) for item in items]
        if self._dimensions is None and result:
            self._dimensions = len(result[0])
            logger.info(
                "OpenAI-compatible embedding model=%s dimensions=%d",
                self._model,
                self._dimensions,
            )
        return result


class DeterministicLocalEmbeddingProvider:
    """Deterministic local embedding provider for dev/tests."""

    def __init__(self, *, embedding_dimensions: int = 24) -> None:
        if embedding_dimensions < 1:
            msg = "embedding_dimensions must be >= 1."
            raise ValueError(msg)
        self._embedding_dimensions = embedding_dimensions

    def embed_texts(self, *, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed_one(text=text) for text in texts)

    def _embed_one(self, *, text: str) -> tuple[float, ...]:
        values: list[float] = []
        for index in range(self._embedding_dimensions):
            digest = hashlib.sha256(f"{index}|{text}".encode()).digest()
            numerator = int.from_bytes(digest[:8], "big", signed=False)
            ratio = numerator / float((1 << 64) - 1)
            values.append((ratio * 2.0) - 1.0)
        return tuple(values)
