"""TTL cache for public retrieval responses.

Without a response cache — only a 256-entry in-process LRU of embeddings — an IDE
assistant re-issuing the same prompt would pay for the full dense + lexical +
rerank + pack pipeline every time.

The dangerous part of a response cache is the key, not the storage. Two failure
modes matter more than the hit rate:

* **Cross-tenant leakage.** Retrieval is tenant-scoped; a key without the tenant
  would serve one tenant's corpus to another. `tenant_id` is therefore the first
  component and is never optional.
* **Privileged content leakage.** The debug payload is privileged. A response
  computed for a caller holding an admin key must never be replayed to an
  anonymous one, so `debug` is part of the key.

The key is deliberately broad: everything that can change the response is in
it, because a key that is too narrow does not slow the service
down, it makes it answer wrong.

The cache is per-process. With more than one replica that lowers the hit rate; it
does not affect correctness, and it avoids putting a network dependency on the
query path.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any

DEFAULT_TTL_SECONDS = 900.0  # 15 minutes
DEFAULT_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class _Entry[T]:
    value: T
    expires_at: float


def build_cache_key(
    *,
    tenant_id: str,
    query: str,
    product_id: str | None,
    language: str | None,
    version: str | None,
    query_locale: str | None,
    top_k: int,
    strict_version: bool,
    doc_types: tuple[str, ...],
    include_examples: bool,
    debug: bool,
) -> str:
    """Return a stable key covering everything that can change the response."""
    payload = {
        "tenant": tenant_id,
        "query": query.strip(),
        "product": (product_id or "").casefold(),
        "language": (language or "").casefold(),
        "version": (version or "").casefold(),
        "locale": (query_locale or "").casefold(),
        "top_k": top_k,
        "strict_version": strict_version,
        # Order must not create distinct keys for the same request.
        "doc_types": sorted(doc_type.casefold() for doc_type in doc_types),
        "include_examples": include_examples,
        "debug": debug,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ResponseCache[T]:
    """Bounded TTL cache with snapshot-scoped invalidation."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        if ttl_seconds <= 0:
            msg = "ttl_seconds must be > 0."
            raise ValueError(msg)
        if max_entries < 1:
            msg = "max_entries must be >= 1."
            raise ValueError(msg)
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._lock = Lock()
        self._entries: OrderedDict[str, _Entry[T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry.value

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._entries[key] = _Entry(value=value, expires_at=monotonic() + self._ttl_seconds)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def invalidate_all(self) -> int:
        """Drop every entry. Called when a publish changes what is served.

        Coarse on purpose: mapping a snapshot to the cached keys it affects means
        tracking which snapshots produced each response, and a publish is rare
        while a stale answer is a correctness bug. Clearing costs a brief dip in
        hit rate; getting the mapping subtly wrong costs wrong answers.
        """
        with self._lock:
            dropped = len(self._entries)
            self._entries.clear()
            return dropped

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"entries": len(self._entries), "ttl_seconds": self._ttl_seconds}
