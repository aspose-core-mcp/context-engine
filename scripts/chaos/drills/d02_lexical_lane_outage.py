"""D-02 — Lexical lane (OpenSearch) outage drill.

Symmetric counterpart to D-01. The contract from
``tests/test_hybrid_retriever.py::test_sync_retrieve_degrades_when_lexical_lane_fails``
is that the retriever serves vector-only results when OpenSearch is hard-down.
"""

from __future__ import annotations

import logging
from typing import Any

from scripts.chaos.drills._fixtures import (
    PassThroughReranker,
    StubDenseLaneAdapter,
    StubLexicalLaneAdapter,
    lane_candidate,
    make_plan,
)
from scripts.chaos.drills.base import DrillResult, DrillTimer, utc_iso

from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.retrieval_models import HybridScoringConfig

DRILL_ID = "D-02"
DRILL_NAME = "lexical_lane_outage"
SCENARIO = (
    "OpenSearch unavailable; lexical lane raises on every call. "
    "Hybrid retriever must serve vector-only results so query_docs stays up."
)
RTO_TARGET = 5.0
RPO_TARGET = 0.0


def run() -> DrillResult:
    started = utc_iso()
    timer = DrillTimer()

    plan = make_plan()
    dense_payload = (
        lane_candidate(candidate_id="dns-a", chunk_id="chunk-a", raw_score=0.91),
        lane_candidate(candidate_id="dns-b", chunk_id="chunk-b", raw_score=0.83),
    )
    dense = StubDenseLaneAdapter(candidates=dense_payload)
    lexical = StubLexicalLaneAdapter(raise_on_search=True)

    retriever = HybridRetriever(
        dense_lane_adapter=dense,
        lexical_lane_adapter=lexical,
        scoring_config=HybridScoringConfig(candidate_pool_size=10, rerank_top_k=10),
        reranker=PassThroughReranker(),
    )

    log_capture: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = log_capture.append  # type: ignore[method-assign]
    retriever_logger = logging.getLogger("adcs.retrieval.hybrid_retriever")
    retriever_logger.addHandler(handler)
    retriever_logger.setLevel(logging.WARNING)

    failures: list[str] = []
    verified: list[str] = []
    telemetry: dict[str, Any] = {}
    rto_observed = 0.0

    try:
        rto_timer = DrillTimer()
        result = retriever.retrieve(plan=plan)
        rto_observed = rto_timer.elapsed()

        telemetry = {
            "dense_candidates_count": result.dense_candidates_count,
            "lexical_candidates_count": result.lexical_candidates_count,
            "fused_candidates_count": result.fused_candidates_count,
            "result_size": len(result.candidates),
            "warning_records": len(log_capture),
            "dense_search_calls": dense.search_calls,
            "lexical_search_calls": lexical.search_calls,
        }

        if result.lexical_candidates_count == 0:
            verified.append("lexical_candidates_count == 0 (outage acknowledged)")
        else:
            failures.append(
                f"lexical_candidates_count={result.lexical_candidates_count}, expected 0"
            )

        if result.dense_candidates_count > 0:
            verified.append(
                f"dense_candidates_count={result.dense_candidates_count} "
                "(survivor lane returned candidates)"
            )
        else:
            failures.append("dense lane returned 0 candidates — degraded mode failed")

        if len(result.candidates) > 0:
            verified.append(
                f"len(candidates)={len(result.candidates)} (user receives citations)"
            )
        else:
            failures.append("retriever returned 0 candidates — public API would fail")

        warning_seen = any(
            "Lexical lane failed" in record.getMessage() for record in log_capture
        )
        if warning_seen:
            verified.append("WARNING log emitted: 'Lexical lane failed'")
        else:
            failures.append("expected WARNING log not seen")

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )
        else:
            verified.append(
                f"rto_observed={rto_observed * 1000:.2f}ms within target {RTO_TARGET}s"
            )

        outcome = "PASS" if not failures else "DEGRADED"
    except Exception as exc:  # pragma: no cover
        failures.append(f"drill raised: {exc!r}")
        outcome = "ERROR"
        rto_observed = timer.elapsed()
    finally:
        retriever_logger.removeHandler(handler)

    completed = utc_iso()
    duration = timer.elapsed()

    return DrillResult(
        drill_id=DRILL_ID,
        drill_name=DRILL_NAME,
        scenario=SCENARIO,
        started_at=started,
        completed_at=completed,
        duration_seconds=round(duration, 4),
        rto_target_seconds=RTO_TARGET,
        rto_observed_seconds=round(rto_observed, 4),
        rpo_target_seconds=RPO_TARGET,
        rpo_observed_seconds=0.0,
        outcome=outcome,
        verified=verified,
        failures=failures,
        telemetry=telemetry,
        recovery_steps=[
            "1. HybridRetriever.retrieve catches Exception from lexical_lane_adapter.search",
            "2. WARNING logged: 'Lexical lane failed, continuing with dense only'",
            "3. lexical_candidates set to empty tuple",
            "4. dense_lane_adapter.search proceeds normally",
            "5. _fuse_and_rerank receives dense-only candidates and returns degraded result",
            "6. Public query_docs returns citations sourced from Qdrant",
        ],
    )
