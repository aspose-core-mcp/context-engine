"""D-03 — Both lanes outage drill.

Scenario: BOTH Qdrant and OpenSearch are unavailable simultaneously
(catastrophic infrastructure failure). The retriever's contract under
``tests/test_hybrid_retriever.py::test_async_retrieve_returns_empty_when_both_lanes_raise``
is to return an empty result envelope — no exception escapes — so the API
returns a clean 200 with zero candidates rather than a 500.

This is the absolute floor of the degraded-mode contract: no panic, no
crash, just an honest "we couldn't find anything" the caller can act on.
"""

from __future__ import annotations

import logging
from typing import Any

from scripts.chaos.drills._fixtures import (
    PassThroughReranker,
    StubDenseLaneAdapter,
    StubLexicalLaneAdapter,
    make_plan,
)
from scripts.chaos.drills.base import DrillResult, DrillTimer, utc_iso

from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.retrieval_models import HybridScoringConfig

DRILL_ID = "D-03"
DRILL_NAME = "both_lanes_outage"
SCENARIO = (
    "Catastrophic — Qdrant AND OpenSearch both unavailable. "
    "Retriever must return an empty envelope without raising, so the public "
    "query_docs returns a clean empty result rather than a 500."
)
RTO_TARGET = 5.0
RPO_TARGET = 0.0


def run() -> DrillResult:
    started = utc_iso()
    timer = DrillTimer()

    plan = make_plan()
    dense = StubDenseLaneAdapter(raise_on_search=True)
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
            "result_size": len(result.candidates),
            "warning_records": len(log_capture),
        }

        if result.dense_candidates_count == 0 and result.lexical_candidates_count == 0:
            verified.append("both lane counts == 0 (outage acknowledged)")
        else:
            failures.append("expected both lane counts to be 0")

        if len(result.candidates) == 0:
            verified.append("len(candidates) == 0 (clean empty envelope, no crash)")
        else:
            failures.append("expected zero candidates")

        warning_count = sum(
            1 for record in log_capture
            if "lane failed" in record.getMessage().lower()
        )
        if warning_count >= 2:
            verified.append(
                f"WARNING logs emitted for both lanes ({warning_count} records)"
            )
        else:
            failures.append(f"expected 2 warning logs, got {warning_count}")

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )
        else:
            verified.append(
                f"rto_observed={rto_observed * 1000:.2f}ms within target {RTO_TARGET}s"
            )

        outcome = "PASS" if not failures else "DEGRADED"
    except Exception as exc:
        # CRITICAL: an exception escaping here means the API would return 500.
        failures.append(
            f"drill raised: {exc!r} — degraded-mode contract VIOLATED, "
            "exception escaped HybridRetriever"
        )
        outcome = "FAIL"
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
            "1. HybridRetriever.retrieve calls dense_lane_adapter.search → catches",
            "2. WARNING logged for dense lane",
            "3. HybridRetriever.retrieve calls lexical_lane_adapter.search → catches",
            "4. WARNING logged for lexical lane",
            "5. _fuse_and_rerank called with two empty tuples",
            "6. Returns HybridRetrievalResult with zero candidates — no exception",
            "7. Public query_docs returns 200 OK with empty candidate list",
            "8. Operator sees both warnings and pages Sev1 incident commander",
        ],
    )
