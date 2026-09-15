"""D-04 — Slow lane / timeout drill.

Scenario: the dense lane returns successfully but takes longer than the
configured ``HybridScoringConfig.lane_timeout_seconds``. The async path
in ``HybridRetriever.async_retrieve`` wraps each lane in
``asyncio.wait_for`` so the slow lane is cancelled with a TimeoutError
and the survivor lane's result is returned.

This drill exercises the timeout-tolerance contract that prevents one
slow backend from holding up every public API request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from scripts.chaos.drills._fixtures import (
    AsyncStubDenseLaneAdapter,
    AsyncStubLexicalLaneAdapter,
    PassThroughReranker,
    lane_candidate,
    make_plan,
)
from scripts.chaos.drills.base import DrillResult, DrillTimer, utc_iso

from adcs.retrieval.hybrid_retriever import HybridRetriever
from adcs.retrieval.retrieval_models import HybridScoringConfig

DRILL_ID = "D-04"
DRILL_NAME = "lane_timeout"
SCENARIO = (
    "Dense lane responds slowly (exceeds lane_timeout_seconds). "
    "Async retriever must cancel the slow lane and serve the survivor's "
    "results within timeout + small overhead."
)
LANE_TIMEOUT = 0.10  # tight bound for the drill so it stays CI-fast
SLOW_DELAY = 0.30  # comfortably above the timeout
RTO_TARGET = 1.0  # seconds — generous to absorb event-loop scheduling jitter
RPO_TARGET = 0.0


def run() -> DrillResult:
    started = utc_iso()
    timer = DrillTimer()

    plan = make_plan()
    # Async stubs are properly cancellable by asyncio.wait_for; the sync
    # stubs would block the underlying thread executor and ``asyncio.run``
    # would wait for it to drain on cleanup, defeating the timeout test.
    dense = AsyncStubDenseLaneAdapter(delay_seconds=SLOW_DELAY)
    lexical_payload = (
        lane_candidate(candidate_id="lex-a", chunk_id="chunk-a", raw_score=50.0),
    )
    lexical = AsyncStubLexicalLaneAdapter(candidates=lexical_payload)

    retriever = HybridRetriever(
        dense_lane_adapter=dense,
        lexical_lane_adapter=lexical,
        scoring_config=HybridScoringConfig(
            candidate_pool_size=10,
            rerank_top_k=10,
            lane_timeout_seconds=LANE_TIMEOUT,
        ),
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
        result = asyncio.run(retriever.async_retrieve(plan=plan))
        rto_observed = rto_timer.elapsed()

        telemetry = {
            "dense_candidates_count": result.dense_candidates_count,
            "lexical_candidates_count": result.lexical_candidates_count,
            "result_size": len(result.candidates),
            "warning_records": len(log_capture),
            "lane_timeout_seconds": LANE_TIMEOUT,
            "slow_delay_seconds": SLOW_DELAY,
        }

        if result.dense_candidates_count == 0:
            verified.append("dense_candidates_count == 0 (timed out as expected)")
        else:
            failures.append(
                f"dense_candidates_count={result.dense_candidates_count}, "
                "expected 0 — slow lane was not cancelled"
            )

        if result.lexical_candidates_count > 0:
            verified.append(
                "lexical lane survived and contributed candidates"
            )
        else:
            failures.append("survivor lane returned 0 candidates")

        # Total observed time should be bounded by the slow delay; the contract
        # is that we don't WAIT the full SLOW_DELAY — we cancel earlier.
        if rto_observed < SLOW_DELAY:
            verified.append(
                f"rto_observed={rto_observed * 1000:.1f}ms < slow_delay "
                f"({SLOW_DELAY * 1000:.0f}ms) — cancellation worked"
            )
        else:
            failures.append(
                f"rto_observed={rto_observed:.3f}s >= slow_delay {SLOW_DELAY}s — "
                "slow lane was waited on instead of being cancelled"
            )

        if rto_observed > RTO_TARGET:
            failures.append(
                f"rto_observed={rto_observed:.3f}s exceeded target {RTO_TARGET}s"
            )

        outcome = "PASS" if not failures else "DEGRADED"
    except Exception as exc:
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
            "1. async_retrieve wraps both lane coros in asyncio.wait_for(timeout=lane_timeout_seconds)",  # noqa: E501
            "2. Slow lane exceeds timeout → asyncio.TimeoutError raised",
            "3. asyncio.gather(return_exceptions=True) captures the exception",
            "4. WARNING logged: 'Dense lane failed, continuing with lexical only'",
            "5. dense_candidates set to empty tuple",
            "6. _fuse_and_rerank receives lexical-only candidates",
            "7. Public API receives a result inside lane_timeout_seconds + small overhead",
        ],
    )
