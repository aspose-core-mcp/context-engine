"""In-memory per-product retrieval settings registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True, slots=True)
class RetrievalSettingsRecord:
    product_id: str
    top_k: int
    max_context_tokens: int
    excerpt_char_limit: int
    low_confidence_threshold: float
    clarification_policy: str
    updated_by: str
    updated_at: datetime


class InMemoryRetrievalSettingsService:
    """Store product-level retrieval settings with deterministic defaults."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._settings: dict[str, RetrievalSettingsRecord] = {}

    def get(self, *, product_id: str) -> RetrievalSettingsRecord:
        normalized_product_id = product_id.strip().casefold()
        if not normalized_product_id:
            msg = "product_id must not be empty."
            raise ValueError(msg)
        with self._lock:
            record = self._settings.get(normalized_product_id)
            if record is not None:
                return record
        return RetrievalSettingsRecord(
            product_id=normalized_product_id,
            top_k=8,
            max_context_tokens=8192,
            excerpt_char_limit=1200,
            low_confidence_threshold=0.35,
            clarification_policy="ask_when_low_confidence",
            updated_by="system-default",
            updated_at=datetime.now(tz=UTC),
        )

    def peek(self, *, product_id: str) -> RetrievalSettingsRecord | None:
        normalized_product_id = product_id.strip().casefold()
        if not normalized_product_id:
            return None
        with self._lock:
            return self._settings.get(normalized_product_id)

    def upsert(
        self,
        *,
        product_id: str,
        top_k: int,
        max_context_tokens: int,
        excerpt_char_limit: int,
        low_confidence_threshold: float,
        clarification_policy: str,
        updated_by: str,
    ) -> RetrievalSettingsRecord:
        normalized_product_id = product_id.strip().casefold()
        normalized_policy = clarification_policy.strip()
        normalized_updated_by = updated_by.strip()
        if not normalized_product_id:
            msg = "product_id must not be empty."
            raise ValueError(msg)
        if top_k < 1 or top_k > 50:
            msg = "top_k must be in range [1, 50]."
            raise ValueError(msg)
        if max_context_tokens < 512 or max_context_tokens > 65536:
            msg = "max_context_tokens must be in range [512, 65536]."
            raise ValueError(msg)
        if excerpt_char_limit < 120 or excerpt_char_limit > 5000:
            msg = "excerpt_char_limit must be in range [120, 5000]."
            raise ValueError(msg)
        if low_confidence_threshold < 0 or low_confidence_threshold > 1:
            msg = "low_confidence_threshold must be in range [0, 1]."
            raise ValueError(msg)
        if not normalized_policy:
            msg = "clarification_policy must not be empty."
            raise ValueError(msg)
        if not normalized_updated_by:
            msg = "updated_by must not be empty."
            raise ValueError(msg)

        record = RetrievalSettingsRecord(
            product_id=normalized_product_id,
            top_k=top_k,
            max_context_tokens=max_context_tokens,
            excerpt_char_limit=excerpt_char_limit,
            low_confidence_threshold=low_confidence_threshold,
            clarification_policy=normalized_policy,
            updated_by=normalized_updated_by,
            updated_at=datetime.now(tz=UTC),
        )
        with self._lock:
            self._settings[normalized_product_id] = record
        return record

    def delete(self, *, product_id: str) -> bool:
        normalized_product_id = product_id.strip().casefold()
        if not normalized_product_id:
            return False
        with self._lock:
            if normalized_product_id not in self._settings:
                return False
            del self._settings[normalized_product_id]
            return True
