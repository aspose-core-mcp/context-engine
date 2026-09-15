"""Prometheus metrics instrumentation for ADCS.

Uses ``prometheus_client`` when available; falls back to lightweight stubs
that expose the same recording API so the rest of the codebase can call
``inc()`` / ``observe()`` / ``labels()`` unconditionally.

Key SLO-aligned metrics:
  - query_docs p95 <= 1 200 ms
  - get_symbol_doc p95 <= 800 ms
  - API 5xx rate < 1 %
  - citation_missing_ratio < 2 %
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detect prometheus_client availability
# ---------------------------------------------------------------------------

_HAS_PROMETHEUS = False
try:
    import prometheus_client as _pc  # noqa: F401

    _HAS_PROMETHEUS = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Stub types so the module works without prometheus_client installed.
# When the real library is present the stubs are never instantiated —
# ``_make_counter`` / ``_make_histogram`` return real objects instead.
# ---------------------------------------------------------------------------


class _StubChild:
    """Mimics a labelled metric child (returned by ``.labels()``)."""

    def inc(self, amount: float = 1) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass


class _StubMetric:
    """Mimics a top-level Counter / Histogram."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def labels(self, *args: Any, **kwargs: Any) -> _StubChild:
        return _StubChild()

    def inc(self, amount: float = 1) -> None:
        pass

    def observe(self, amount: float) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_counter(
    name: str,
    documentation: str,
    labelnames: Sequence[str] | None = None,
) -> Any:
    if _HAS_PROMETHEUS:
        import prometheus_client

        return prometheus_client.Counter(
            name, documentation, list(labelnames or []),
        )
    return _StubMetric()


def _make_histogram(
    name: str,
    documentation: str,
    labelnames: Sequence[str] | None = None,
    buckets: Sequence[float] | None = None,
) -> Any:
    if _HAS_PROMETHEUS:
        import prometheus_client

        kwargs: dict[str, Any] = {}
        if buckets is not None:
            kwargs["buckets"] = list(buckets)
        return prometheus_client.Histogram(
            name, documentation, list(labelnames or []), **kwargs,
        )
    return _StubMetric()


# ---------------------------------------------------------------------------
# Histogram bucket presets aligned with SLO targets
# ---------------------------------------------------------------------------

# API latency: p95 targets range from 0.8 s to 1.2 s
_HTTP_DURATION_BUCKETS: Sequence[float] = (
    0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 1.2, 2.5, 5.0, 10.0,
)

# Retrieval latency: symbol lookups target p95 <= 0.8 s
_RETRIEVAL_DURATION_BUCKETS: Sequence[float] = (
    0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.8, 1.2, 2.5, 5.0,
)

# Embedding calls are typically fast but can spike under load
_EMBEDDING_DURATION_BUCKETS: Sequence[float] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5,
)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

# The HTTP request counter and duration histogram deliberately do NOT live here.
# src/adcs/api/metrics.py owns adcs_http_requests_total and
# adcs_http_request_duration_seconds, and /metrics concatenates both registries —
# declaring them in both places would emit two `# TYPE` lines for one family, which
# Prometheus rejects, so installing prometheus_client would break /metrics. The
# stdlib registry owns them because
# it works with no optional dependency at all; this registry keeps only the
# families that one does not provide.

retrieval_query_total: Any = _make_counter(
    "adcs_retrieval_query_total",
    "Total retrieval queries executed.",
    ["mode", "product_id"],
)

retrieval_latency_seconds: Any = _make_histogram(
    "adcs_retrieval_latency_seconds",
    "Retrieval query latency in seconds.",
    ["mode"],
    buckets=_RETRIEVAL_DURATION_BUCKETS,
)

embedding_requests_total: Any = _make_counter(
    "adcs_embedding_requests_total",
    "Total embedding requests.",
    ["status"],
)

embedding_latency_seconds: Any = _make_histogram(
    "adcs_embedding_latency_seconds",
    "Embedding request latency in seconds.",
    buckets=_EMBEDDING_DURATION_BUCKETS,
)

ingestion_chunks_total: Any = _make_counter(
    "adcs_ingestion_chunks_total",
    "Total ingestion chunks processed.",
    ["product_id", "status"],
)


# ---------------------------------------------------------------------------
# Helper: render /metrics response body
# ---------------------------------------------------------------------------


def render_metrics() -> str:
    """Return Prometheus text exposition of all registered metrics.

    When ``prometheus_client`` is not installed the function returns an
    empty string so the ``/metrics`` endpoint still responds cleanly.
    """
    if not _HAS_PROMETHEUS:
        return ""
    import prometheus_client

    return prometheus_client.generate_latest(prometheus_client.REGISTRY).decode("utf-8")
