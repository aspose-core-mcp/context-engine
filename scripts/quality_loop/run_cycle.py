#!/usr/bin/env python3
"""Run one cycle of the ADCS quality-improvement loop.

This is the entry point invoked by the Makefile target
``quality-loop-cycle``. The script:

1. Builds the four agents with their default configs.
2. Wires a sample provider — by default, a small synthetic provider
   that produces a deterministic sample set so the cycle is
   CI-runnable without depending on live query traffic.
3. Runs one cycle and writes the audit log + summary.

Production deployments swap out the synthetic sample provider for one
that pulls from real query_docs telemetry (see ``--samples-source``
argument; ``synthetic`` is the only currently-implemented backend).

Exit codes:
  0  — cycle completed successfully (regardless of decisions inside)
  1  — coordinator itself raised
  2  — invalid invocation
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from adcs.quality_loop import (
    Coordinator,
    CoordinatorConfig,
    DiagnosisAgent,
    GuardAgent,
    JudgeAgent,
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.judge_agent import make_sample_id
from adcs.quality_loop.models import utc_iso
from adcs.quality_loop.sample_providers import (
    LOG_TAIL_ENV_VAR,
    StructuredLogSampleProvider,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = REPO_ROOT / "reports" / "quality-loop" / "audit-log.jsonl"
DEFAULT_SUMMARY = REPO_ROOT / "reports" / "quality-loop" / "last-summary.json"
DEFAULT_DETAIL_DIR = REPO_ROOT / "reports" / "quality-loop" / "cycles"
DEFAULT_CALIBRATION = (
    REPO_ROOT / "reports" / "quality-loop" / "calibration-state.json"
)


def synthetic_provider() -> tuple[QueryResponseSample, ...]:
    """Deterministic sample set used for CI smoke + first-run baseline.

    Mixes good and bad responses so every agent path is exercised on
    every cycle. The set deliberately includes:

    - 1 clean response (citation present, version match, calibrated confidence)
    - 1 missing-citation response (citation_accuracy < 1.0)
    - 1 version-mismatch response (strict_version filter not honoured)
    - 1 overconfident response (high confidence, poor citations)
    - 2 low-citation responses concentrated in one product+language
      (so DiagnosisAgent can detect a scope cluster)
    """
    captured = utc_iso()
    return (
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="net",
            requested_version="25.1",
            strict_version=True,
            query="how to OCR a PDF in C# Aspose",
            candidates=(
                {
                    "canonical_url": "https://docs.aspose.com/ocr/net/recognize/",
                    "version": "25.1",
                    "chunk_id": "ocr-net-recognize-001",
                    "symbol_fqn": "Aspose.OCR.AsposeOcr.Recognize",
                },
            ),
            confidence_score=0.85,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="net",
            requested_version="25.1",
            strict_version=True,
            query="aspose ocr image to text",
            candidates=(
                {
                    "canonical_url": "",
                    "version": "25.1",
                    "chunk_id": "ocr-net-image-002",
                },
            ),
            confidence_score=0.92,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="net",
            requested_version="25.1",
            strict_version=True,
            query="recognize handwritten text",
            candidates=(
                {
                    "canonical_url": "https://docs.aspose.com/ocr/net/handwritten/",
                    "version": "24.5",
                    "chunk_id": "ocr-net-handwritten-003",
                },
            ),
            confidence_score=0.78,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="net",
            requested_version="25.1",
            strict_version=True,
            query="ocr azure storage",
            candidates=(),
            confidence_score=0.95,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="java",
            requested_version="25.1",
            strict_version=True,
            query="ocr a multi-page PDF in Java",
            candidates=(
                {"canonical_url": "", "version": "25.1", "chunk_id": "ocr-java-multipage-004"},
            ),
            confidence_score=0.83,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="java",
            requested_version="25.1",
            strict_version=True,
            query="batch ocr java",
            candidates=(),
            confidence_score=0.65,
        ),
        QueryResponseSample(
            sample_id=make_sample_id(),
            captured_at=captured,
            product_id="aspose.ocr",
            programming_language="java",
            requested_version="25.1",
            strict_version=True,
            query="ocr language detection",
            candidates=(
                {"canonical_url": "", "version": "25.1", "chunk_id": "ocr-java-lang-005"},
            ),
            confidence_score=0.71,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=DEFAULT_AUDIT,
        help="Append-only JSONL audit log (committed in CI).",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY,
        help="Last-cycle summary JSON (gitignored).",
    )
    parser.add_argument(
        "--cycle-detail-dir",
        type=Path,
        default=DEFAULT_DETAIL_DIR,
        help="Per-cycle detail JSONs (gitignored).",
    )
    parser.add_argument(
        "--calibration-state",
        type=Path,
        default=DEFAULT_CALIBRATION,
        help=(
            "Persisted calibration state file (committed). The AdaptiveAgent "
            "reads + mutates it across cycles to drift agent thresholds."
        ),
    )
    parser.add_argument(
        "--no-adaptive",
        action="store_true",
        help=(
            "Disable adaptive calibration (run frozen agents only). Useful for "
            "deterministic test fixtures where state must not drift."
        ),
    )
    parser.add_argument(
        "--samples-source",
        choices=["synthetic", "structured-log"],
        default="synthetic",
        help=(
            "Where samples come from. 'synthetic' is the deterministic "
            "CI-smoke set; 'structured-log' tails the JSONL query-response "
            "log named by $QUALITY_LOOP_LOG_TAIL_PATH and falls back to "
            "synthetic when that env var is unset."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress info-level logs.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = CoordinatorConfig(
        audit_log_path=args.audit_log,
        summary_path=args.summary_path,
        cycle_detail_dir=args.cycle_detail_dir,
        calibration_state_path=(
            None if args.no_adaptive else args.calibration_state
        ),
    )

    if args.samples_source == "synthetic":
        sample_provider = synthetic_provider
    elif args.samples_source == "structured-log":
        log_provider = StructuredLogSampleProvider.from_env()
        if log_provider is None:
            logging.warning(
                "%s unset; falling back to the synthetic provider.",
                LOG_TAIL_ENV_VAR,
            )
            sample_provider = synthetic_provider
        else:
            sample_provider = log_provider
    else:  # pragma: no cover — argparse already filters
        msg = f"unknown samples-source {args.samples_source!r}"
        raise ValueError(msg)

    try:
        coord = Coordinator(
            config=config,
            judge=JudgeAgent(),
            diagnoser=DiagnosisAgent(),
            proposer=ProposalAgent(),
            guard=GuardAgent(),
            sample_provider=sample_provider,
        )
        summary = coord.run_cycle()
    except Exception as exc:  # pragma: no cover — defensive guard
        logging.exception("Coordinator raised: %s", exc)
        return 1

    print(f"\nADCS quality-loop cycle {summary.cycle_id}")
    print("=" * 70)
    print(f"  samples processed:  {summary.samples_processed}")
    print(f"  verdicts emitted:   {summary.verdicts_emitted}")
    print(f"  diagnoses emitted:  {summary.diagnoses_emitted}")
    print(f"  proposals emitted:  {summary.proposals_emitted}")
    print(f"  decisions emitted:  {summary.decisions_emitted}")
    print(f"  outcomes:           {summary.outcome_counts}")
    print(f"  adaptations:        {summary.adaptations_applied}")
    print(f"  duration:           {summary.duration_seconds:.3f}s")
    print(f"\naudit log:    {args.audit_log}")
    print(f"summary:      {args.summary_path}")
    if not args.no_adaptive:
        print(f"calibration:  {args.calibration_state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
