"""D-01 — Dense lane (Qdrant) outage drill.

Scenario: the Qdrant primary becomes unavailable and every dense-lane
``search`` call raises. The contract documented in
``infra/runbooks/incident-response-playbooks.md`` (S2A — API latency SLO
breach) and verified by ``tests/test_hybrid_retriever.py`` is that
``HybridRetriever`` continues to return lexical-only results so that the
public ``query_docs`` API never goes hard-down on a single-backend outage.

Expected behaviour:

- ``dense_candidates_count == 0`` in the result envelope.
- ``lexical_candidates_count > 0`` (lexical lane survives).
- ``len(candidates) > 0`` (the user gets *some* citation-backed answer).
- A WARNING log line is emitted by the retriever so the on-call sees it.
- Recovery is instantaneous from the user's POV (no retries needed).
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

DRILL_ID = "D-01"
DRILL_NAME = "dense_lane_outage"
SCENARIO = (
    "Qdrant primary unavailable; dense lane raises on every call. "
    "Hybrid retriever must serve lexical-only results so query_docs stays up."
)
RTO_TARGET = 5.0  # seconds — runbook S2A target
RPO_TARGET = 0.0  # zero data loss; lexical lane has its own copy


def run() -> DrillResult:
    started = utc_iso()
    timer = DrillTimer()

    plan = make_plan()
    dense = StubDenseLaneAdapter(raise_on_search=True)
    lexical_payload = (
        lane_candidate(candidate_id="lex-a", chunk_id="chunk-a", raw_score=50.0),
        lane_candidate(candidate_id="lex-b", chunk_id="chunk-b", raw_score=42.0),
    )
    lexical = StubLexicalLaneAdapter(candidates=lexical_payload)

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

        if result.dense_candidates_count == 0:
            verified.append("dense_candidates_count == 0 (outage acknowledged)")
        else:
            failures.append(
                f"dense_candidates_count={result.dense_candidates_count}, expected 0"
            )

        if result.lexical_candidates_count > 0:
            verified.append(
                f"lexical_candidates_count={result.lexical_candidates_count} "
                "(survivor lane returned candidates)"
            )
        else:
            failures.append("lexical lane returned 0 candidates — degraded mode failed")

        if len(result.candidates) > 0:
            verified.append(
                f"len(candidates)={len(result.candidates)} (user receives citations)"
            )
        else:
            failures.append("retriever returned 0 candidates — public API would fail")

        warning_seen = any(
            "Dense lane failed" in record.getMessage() for record in log_capture
        )
        if warning_seen:
            verified.append("WARNING log emitted: 'Dense lane failed'")
        else:
            failures.append("expected WARNING log not seen")

        if dense.search_calls == 1:
            verified.append("dense lane was actually invoked (fault really fired)")
        else:
            failures.append(
                f"dense.search called {dense.search_calls} times, expected 1"
            )

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )
        else:
            verified.append(
                f"rto_observed={rto_observed * 1000:.2f}ms within target {RTO_TARGET}s"
            )

        outcome = "PASS" if not failures else "DEGRADED"
    except Exception as exc:  # pragma: no cover — drill error path
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
            "1. HybridRetriever.retrieve catches Exception from dense_lane_adapter.search",
            "2. WARNING logged: 'Dense lane failed, continuing with lexical only'",
            "3. dense_candidates set to empty tuple",
            "4. lexical_lane_adapter.search proceeds normally",
            "5. _fuse_and_rerank receives lexical-only candidates and returns degraded result",
            "6. Public query_docs returns citations sourced from OpenSearch",
        ],
    )
