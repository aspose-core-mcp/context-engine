"""Readiness helpers for critical runtime dependencies."""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

from adcs.config import PersistenceBackend, RetrievalBackend, Settings
from adcs.runtime import ResolvedRuntimeAdapters

DependencyResults = dict[str, tuple[bool, str]]
_NOT_REQUIRED_REASON = "not_required_for_current_runtime"


def _extract_host_port(url: str, default_port: int) -> tuple[str | None, int]:
    parsed = urlsplit(url)
    return parsed.hostname, parsed.port or default_port


def _tcp_reachable(
    url: str,
    default_port: int,
    *,
    timeout_seconds: float,
) -> tuple[bool, str]:
    host, port = _extract_host_port(url, default_port)
    if not host:
        return False, "missing host"

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, "reachable"
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        return False, reason[:160]


def resolve_required_dependencies(
    adapter_modes: ResolvedRuntimeAdapters | None,
) -> dict[str, bool]:
    if adapter_modes is None:
        return {
            "postgres": True,
            "redis": True,
            "qdrant": True,
            "opensearch": True,
        }

    requires_persistence = adapter_modes.persistence_backend is not PersistenceBackend.MEMORY
    requires_retrieval = adapter_modes.retrieval_backend is not RetrievalBackend.MEMORY
    requires_runtime_infra = requires_persistence or requires_retrieval
    return {
        "postgres": requires_persistence,
        "redis": requires_runtime_infra,
        "qdrant": requires_retrieval,
        "opensearch": requires_retrieval,
    }


def check_dependencies(
    settings: Settings,
    *,
    adapter_modes: ResolvedRuntimeAdapters | None = None,
    timeout_seconds: float = 0.5,
) -> DependencyResults:
    """Check reachability for critical dependencies required for readiness."""
    required = resolve_required_dependencies(adapter_modes)
    return {
        "postgres": (
            _tcp_reachable(settings.postgres_dsn, 5432, timeout_seconds=timeout_seconds)
            if required["postgres"]
            else (True, _NOT_REQUIRED_REASON)
        ),
        "redis": (
            _tcp_reachable(settings.redis_url, 6379, timeout_seconds=timeout_seconds)
            if required["redis"]
            else (True, _NOT_REQUIRED_REASON)
        ),
        "qdrant": (
            _tcp_reachable(settings.qdrant_url, 6333, timeout_seconds=timeout_seconds)
            if required["qdrant"]
            else (True, _NOT_REQUIRED_REASON)
        ),
        "opensearch": _tcp_reachable(
            settings.opensearch_url,
            9200,
            timeout_seconds=timeout_seconds,
        )
        if required["opensearch"]
        else (True, _NOT_REQUIRED_REASON),
    }


def build_readiness_response(results: DependencyResults) -> tuple[int, dict[str, object]]:
    """Return HTTP status and body from dependency readiness checks."""
    dependencies: dict[str, dict[str, str]] = {}
    all_ready = True

    for dependency, (is_ready, reason) in results.items():
        dependency_status = "ready" if is_ready else "not_ready"
        dependencies[dependency] = {"status": dependency_status, "reason": reason}
        all_ready = all_ready and is_ready

    return (
        200 if all_ready else 503,
        {
            "status": "ready" if all_ready else "not_ready",
            "dependencies": dependencies,
        },
    )
