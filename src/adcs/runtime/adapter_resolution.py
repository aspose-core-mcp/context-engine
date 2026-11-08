"""Runtime adapter mode resolution for API/worker bootstrap."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from adcs.config import EnvironmentProfile, PersistenceBackend, RetrievalBackend, Settings


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeAdapters:
    """Resolved runtime adapter modes after test/runtime detection."""

    persistence_backend: PersistenceBackend
    retrieval_backend: RetrievalBackend
    is_test_runtime: bool


def resolve_runtime_adapters(
    *,
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    is_test_runtime: bool | None = None,
) -> ResolvedRuntimeAdapters:
    """Resolve adapter modes with deterministic test-runtime fallback."""
    resolved_test_runtime = is_test_runtime
    if resolved_test_runtime is None:
        runtime_environ = environ or os.environ
        resolved_test_runtime = (
            settings.test_mode
            or ("PYTEST_CURRENT_TEST" in runtime_environ)
            or ("PYTEST_VERSION" in runtime_environ)
            or ("pytest" in sys.modules)
        )

    if settings.persistence_backend is PersistenceBackend.AUTO:
        persistence_backend = (
            PersistenceBackend.MEMORY
            if resolved_test_runtime
            else PersistenceBackend.POSTGRES
        )
    else:
        persistence_backend = settings.persistence_backend

    if settings.retrieval_backend is RetrievalBackend.AUTO:
        retrieval_backend = (
            RetrievalBackend.MEMORY
            if resolved_test_runtime
            else RetrievalBackend.QDRANT_OPENSEARCH
        )
    else:
        retrieval_backend = settings.retrieval_backend

    # Production-like profiles must not silently run with in-memory adapters.
    if (
        not resolved_test_runtime
        and settings.env_profile in {EnvironmentProfile.STAGING, EnvironmentProfile.PROD}
    ):
        if persistence_backend is PersistenceBackend.MEMORY:
            msg = (
                "Staging/prod runtime must not use in-memory persistence backend. "
                "Set ADCS_PERSISTENCE_BACKEND=postgres."
            )
            raise RuntimeError(msg)
        if retrieval_backend is RetrievalBackend.MEMORY:
            msg = (
                "Staging/prod runtime must not use in-memory retrieval backend. "
                "Set ADCS_RETRIEVAL_BACKEND=qdrant_opensearch."
            )
            raise RuntimeError(msg)

    return ResolvedRuntimeAdapters(
        persistence_backend=persistence_backend,
        retrieval_backend=retrieval_backend,
        is_test_runtime=resolved_test_runtime,
    )
