from __future__ import annotations

import pytest

from adcs.api.main import create_app
from adcs.config import clear_settings_cache
from adcs.retrieval import OpenSearchLexicalLaneAdapter, QdrantDenseLaneAdapter


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_create_app_uses_configured_remote_retrieval_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "memory")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "qdrant_opensearch")

    app = create_app()

    assert app.state.adapter_modes.persistence_backend.value == "memory"
    assert app.state.adapter_modes.retrieval_backend.value == "qdrant_opensearch"
    service = app.state.public_query_service
    assert isinstance(service._dense_lane_adapter, QdrantDenseLaneAdapter)
    assert isinstance(service._lexical_lane_adapter, OpenSearchLexicalLaneAdapter)
    assert service._candidate_reranker.backend_name == "advanced_heuristic"
