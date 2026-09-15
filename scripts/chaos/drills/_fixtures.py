"""Tiny fixtures shared across drill modules.

These mirror the structures used by ``tests/test_hybrid_retriever.py`` so the
drills exercise the same retrieval contracts the unit tests verify. Keeping
the fixtures in their own module avoids each drill recreating the same
boilerplate.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from adcs.retrieval.models import QueryPlan, QueryPlannerInput
from adcs.retrieval.query_planner import QueryPlanner
from adcs.retrieval.retrieval_models import (
    HybridCandidate,
    LaneCandidate,
    RetrievalCandidateMetadata,
)


def make_plan(*, query: str = "OCR quickstart") -> QueryPlan:
    return QueryPlanner().plan(
        request=QueryPlannerInput(
            query=query,
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )


def make_metadata(*, candidate_id: str, chunk_id: str) -> RetrievalCandidateMetadata:
    return RetrievalCandidateMetadata(
        candidate_id=candidate_id,
        chunk_id=chunk_id,
        snapshot_id="snapshot-25.1",
        product_id="aspose.ocr",
        programming_language="net",
        version="25.1",
        source_kind="apiref",
        doc_type="api_method",
        doc_locale="en",
        symbol_fqn=None,
        title=f"chunk-{chunk_id}",
        canonical_url=f"https://docs.aspose.com/ocr/net/{chunk_id}/",
        section_anchor="#main",
        source_revision="chaos-drill-fixture",
        repo_id="aspose.ocr.docs",
        text=f"chunk text for {chunk_id}",
        checksum=f"checksum-{chunk_id}",
    )


def lane_candidate(*, candidate_id: str, chunk_id: str, raw_score: float) -> LaneCandidate:
    return LaneCandidate(
        metadata=make_metadata(candidate_id=candidate_id, chunk_id=chunk_id),
        raw_score=raw_score,
    )


class StubDenseLaneAdapter:
    """Mirrors ``tests/test_hybrid_retriever.py::_StubDenseLaneAdapter``.

    ``raise_on_search`` injects the fault — used by drill D-01 to simulate
    a Qdrant outage. ``delay_seconds`` injects latency — used by drill
    D-04 to simulate a slow lane that should hit ``lane_timeout_seconds``.
    """

    def __init__(
        self,
        *,
        candidates: Sequence[LaneCandidate] = (),
        raise_on_search: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self._candidates = tuple(candidates)
        self._raise_on_search = raise_on_search
        self._delay_seconds = delay_seconds
        self.search_calls = 0

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        self.search_calls += 1
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)
        if self._raise_on_search:
            msg = "Qdrant connection refused (chaos drill)"
            raise RuntimeError(msg)
        return self._candidates[:limit]


class StubLexicalLaneAdapter:
    """Mirrors ``tests/test_hybrid_retriever.py::_StubLexicalLaneAdapter``."""

    def __init__(
        self,
        *,
        candidates: Sequence[LaneCandidate] = (),
        raise_on_search: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self._candidates = tuple(candidates)
        self._raise_on_search = raise_on_search
        self._delay_seconds = delay_seconds
        self.search_calls = 0

    def search(self, *, plan: QueryPlan, limit: int) -> tuple[LaneCandidate, ...]:
        del plan
        self.search_calls += 1
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)
        if self._raise_on_search:
            msg = "OpenSearch connection refused (chaos drill)"
            raise RuntimeError(msg)
        return self._candidates[:limit]


class AsyncStubDenseLaneAdapter:
    """Async-native dense lane stub.

    Production lane adapters expose ``async_search``; ``HybridRetriever``
    prefers it whenever ``hasattr(adapter, 'async_search')``. Using
    ``await asyncio.sleep`` (rather than ``time.sleep``) makes the slow
    path properly cancellable by ``asyncio.wait_for``.
    """

    def __init__(
        self,
        *,
        candidates: Sequence[LaneCandidate] = (),
        raise_on_search: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self._candidates = tuple(candidates)
        self._raise_on_search = raise_on_search
        self._delay_seconds = delay_seconds
        self.search_calls = 0

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        del plan
        self.search_calls += 1
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        if self._raise_on_search:
            msg = "Qdrant connection refused (chaos drill, async)"
            raise RuntimeError(msg)
        return self._candidates[:limit]


class AsyncStubLexicalLaneAdapter:
    """Async-native lexical lane stub (mirrors ``AsyncStubDenseLaneAdapter``)."""

    def __init__(
        self,
        *,
        candidates: Sequence[LaneCandidate] = (),
        raise_on_search: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self._candidates = tuple(candidates)
        self._raise_on_search = raise_on_search
        self._delay_seconds = delay_seconds
        self.search_calls = 0

    async def async_search(
        self, *, plan: QueryPlan, limit: int
    ) -> tuple[LaneCandidate, ...]:
        del plan
        self.search_calls += 1
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        if self._raise_on_search:
            msg = "OpenSearch connection refused (chaos drill, async)"
            raise RuntimeError(msg)
        return self._candidates[:limit]


class PassThroughReranker:
    def rerank(
        self,
        *,
        plan: QueryPlan,
        candidates: Sequence[HybridCandidate],
        limit: int,
    ) -> tuple[HybridCandidate, ...]:
        del plan
        return tuple(candidates[:limit])
