"""Coordinator — runs one full quality-loop cycle.

The Coordinator is the only stateful piece of the loop. It:

1. (Optional) Loads recent :class:`CycleSummary` records from disk and
   runs the :class:`CrossCycleCorrelationAgent` to emit a typed
   :class:`CorrelationReport` for this cycle — restoring cross-cycle
   awareness without breaking per-cycle replay.
2. Pulls a batch of :class:`QueryResponseSample` from the configured
   sampler (the sampler is injected; production wires it to the
   real query_docs response stream, tests wire it to a fixture).
3. Drives the four reactive agents in fixed order
   (Judge → Diagnose → Propose → Guard) over a shared
   :class:`InMemoryMessageBus`.
4. Runs the AdaptiveAgent at end of cycle, optionally mutating the
   shared :class:`CalibrationState` within hard bounds.
5. Persists every message + a per-cycle :class:`CycleSummary` to the
   audit log so each cycle is end-to-end replayable.

Statelessness of the reactive agents: Judge / Diagnose / Propose /
Guard / Adaptive carry no memory of prior cycles. Cross-cycle
awareness lives only in the :class:`CrossCycleCorrelationAgent`,
which reads from already-persisted on-disk artefacts and emits one
typed observation per cycle. Auditors can read either the JSONL log
or the per-cycle correlation report for trend history.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from adcs.quality_loop.adaptive_agent import AdaptiveAgent
from adcs.quality_loop.calibration import CalibrationState
from adcs.quality_loop.correlation_agent import CrossCycleCorrelationAgent
from adcs.quality_loop.diagnosis_agent import DiagnosisAgent
from adcs.quality_loop.guard_agent import GuardAgent
from adcs.quality_loop.judge_agent import JudgeAgent, QueryResponseSample
from adcs.quality_loop.llm_judge_agent import LLMJudgeAgent
from adcs.quality_loop.message_bus import InMemoryMessageBus, JsonlAuditSink
from adcs.quality_loop.models import CycleSummary, GuardOutcome, utc_iso
from adcs.quality_loop.proposal_agent import ProposalAgent

logger = logging.getLogger(__name__)


# Sampler is "any callable that returns a tuple of samples". Production
# implementations may pull from a Redis ring buffer, a sqlite table, or
# the live query_docs response stream. Tests inject a fixed tuple.
SampleProvider = Callable[[], tuple[QueryResponseSample, ...]]


@dataclass
class CoordinatorConfig:
    audit_log_path: Path
    summary_path: Path
    calibration_state_path: Path | None = None
    cycle_detail_dir: Path | None = None  # optional per-cycle JSON
    cycle_id_prefix: str = "cycle"


@dataclass
class Coordinator:
    """Runs one cycle of correlate → judge → llm-judge → diagnose → propose → guard → adapt."""

    config: CoordinatorConfig
    judge: JudgeAgent
    diagnoser: DiagnosisAgent
    proposer: ProposalAgent
    guard: GuardAgent
    sample_provider: SampleProvider
    adaptive: AdaptiveAgent | None = None
    correlation: CrossCycleCorrelationAgent | None = None
    llm_judge: LLMJudgeAgent | None = None
    bus: InMemoryMessageBus = field(init=False)

    def __post_init__(self) -> None:
        sink = JsonlAuditSink(path=self.config.audit_log_path)
        self.bus = InMemoryMessageBus(sink=sink)
        if self.adaptive is None:
            self.adaptive = AdaptiveAgent()
        if self.correlation is None:
            self.correlation = CrossCycleCorrelationAgent()
        # NB: ``llm_judge`` is intentionally NOT defaulted — it requires an
        # injected LLMJudgeClient (production wires an OpenAI-compatible LLM;
        # tests inject a stub). When None, the shadow-judge step is skipped
        # silently and the cycle behaves as the legacy 6-agent flow.

    # -----------------------------------------------------------------
    # Cycle orchestration
    # -----------------------------------------------------------------

    def run_cycle(self) -> CycleSummary:
        cycle_id = self._make_cycle_id()
        started_at = utc_iso()
        timer_start = time.perf_counter()

        # ---- Load calibration state and apply to agents ------------------
        calibration_state: CalibrationState | None = None
        if self.config.calibration_state_path is not None:
            calibration_state = CalibrationState.load_or_default(
                self.config.calibration_state_path
            )
            self.judge.apply_calibration(
                score_low_threshold=calibration_state.judge_low_threshold
            )
            self.diagnoser.apply_calibration(
                score_low_threshold=calibration_state.judge_low_threshold,
                minimum_low_ratio=calibration_state.diagnosis_min_low_ratio,
            )
            self.proposer.apply_calibration(
                high_confidence_floor=calibration_state.proposal_high_confidence_floor
            )
            self.guard.apply_calibration(
                auto_approve_blast_cap=calibration_state.guard_auto_approve_blast_cap
            )

        logger.info("Coordinator: starting cycle=%s", cycle_id)

        # ---- Cross-cycle correlation (read-only trend analysis) ----------
        # The CrossCycleCorrelationAgent reads recent CycleSummary records
        # from `cycle_detail_dir` (if configured) and emits a typed report
        # describing multi-cycle trends. The report is also fed into the
        # AdaptiveAgent's adapt() call below so trends drive calibration
        # mutations (not just emit observability).
        correlation_reports_emitted = 0
        correlation_report = None
        if self.correlation is not None:
            recent = self._load_recent_summaries()
            correlation_report = self.correlation.correlate(
                cycle_id=cycle_id, recent_summaries=recent
            )
            self.bus.publish(
                "correlations",
                {
                    **correlation_report.to_dict(),
                    "message_type": "CorrelationReport",
                },
            )
            correlation_reports_emitted = 1

        samples = self.sample_provider()
        # Persist sample provenance to the audit log explicitly.
        for s in samples:
            self.bus.publish(
                "samples",
                {
                    "message_type": "QueryResponseSample",
                    "cycle_id": cycle_id,
                    "sample_id": s.sample_id,
                    "captured_at": s.captured_at,
                    "product_id": s.product_id,
                    "programming_language": s.programming_language,
                    "requested_version": s.requested_version,
                    "strict_version": s.strict_version,
                    "candidate_count": len(s.candidates),
                    "confidence_score": s.confidence_score,
                },
            )

        verdicts = self.judge.score_batch(samples=samples, cycle_id=cycle_id)
        for v in verdicts:
            self.bus.publish("verdicts", v.to_dict())

        # ---- Shadow LLM judge (self-reflection) --------------------------
        # Runs on a subset of samples per cycle and emits exactly one
        # JudgeAgreementReport summarising agreement between the LLM and
        # the deterministic Judge. Does NOT alter verdicts — purely for
        # rubric self-review. Skipped when no LLMJudgeAgent is wired.
        llm_judge_reports_emitted = 0
        if self.llm_judge is not None:
            agreement = self.llm_judge.compare(
                cycle_id=cycle_id,
                samples=samples,
                deterministic_verdicts=verdicts,
            )
            self.bus.publish(
                "judge_agreement",
                {**agreement.to_dict(), "message_type": "JudgeAgreementReport"},
            )
            llm_judge_reports_emitted = 1

        diagnoses = self.diagnoser.diagnose_batch(verdicts=verdicts, cycle_id=cycle_id)
        for d in diagnoses:
            self.bus.publish("diagnoses", d.to_dict())

        proposals = self.proposer.propose_batch(diagnoses=diagnoses, cycle_id=cycle_id)
        for p in proposals:
            self.bus.publish("proposals", p.to_dict())

        decisions = self.guard.gate_batch(proposals=proposals, cycle_id=cycle_id)
        for dec in decisions:
            self.bus.publish("decisions", dec.to_dict())

        # ---- Run AdaptiveAgent at end of cycle ----------------------------
        adaptations_applied = 0
        if calibration_state is not None and self.adaptive is not None:
            new_state, event = self.adaptive.adapt(
                state=calibration_state,
                verdicts=verdicts,
                decisions=decisions,
                cycle_id=cycle_id,
                correlation=correlation_report,
            )
            had_rejection = any(
                d.outcome is GuardOutcome.REJECTED for d in decisions
            )
            new_state = new_state.with_cycle_completed(had_rejection=had_rejection)
            if event is not None:
                adaptations_applied = 1
                self.bus.publish("adaptations", event.to_dict())
            assert self.config.calibration_state_path is not None
            new_state.persist(self.config.calibration_state_path)

        completed_at = utc_iso()
        duration = round(time.perf_counter() - timer_start, 4)

        outcome_counts: Counter[str] = Counter(d.outcome.value for d in decisions)
        summary = CycleSummary(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            samples_processed=len(samples),
            verdicts_emitted=len(verdicts),
            diagnoses_emitted=len(diagnoses),
            proposals_emitted=len(proposals),
            decisions_emitted=len(decisions),
            adaptations_applied=adaptations_applied,
            correlation_reports_emitted=correlation_reports_emitted,
            llm_judge_reports_emitted=llm_judge_reports_emitted,
            outcome_counts=dict(outcome_counts),
            audit_log_path=str(self.config.audit_log_path),
            calibration_state_path=(
                str(self.config.calibration_state_path)
                if self.config.calibration_state_path is not None
                else None
            ),
        )

        # Cycle summary is persisted alongside the audit log.
        self.bus.publish("summary", {**summary.to_dict(), "message_type": "CycleSummary"})
        self._write_summary(summary)
        if self.config.cycle_detail_dir is not None:
            self._write_cycle_detail(summary, cycle_id)

        logger.info(
            "Coordinator: cycle=%s complete (%d samples, %d decisions, %.3fs)",
            cycle_id,
            len(samples),
            len(decisions),
            duration,
        )
        return summary

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _make_cycle_id(self) -> str:
        return f"{self.config.cycle_id_prefix}-{uuid.uuid4().hex[:12]}"

    def _load_recent_summaries(self) -> tuple[CycleSummary, ...]:
        """Scan ``cycle_detail_dir`` and parse each detail.json into a CycleSummary.

        Returns an empty tuple if ``cycle_detail_dir`` is not configured or
        contains no usable detail files. Files that fail to parse are
        logged at WARNING and skipped — one bad detail file must not break
        the current cycle.
        """
        if self.config.cycle_detail_dir is None:
            return ()
        root = self.config.cycle_detail_dir
        if not root.exists():
            return ()
        loaded: list[CycleSummary] = []
        for detail_path in sorted(root.glob("*/detail.json")):
            try:
                payload = json.loads(detail_path.read_text(encoding="utf-8"))
                summary_dict = payload.get("summary", {})
                if not summary_dict:
                    continue
                loaded.append(
                    CycleSummary(
                        cycle_id=summary_dict["cycle_id"],
                        started_at=summary_dict["started_at"],
                        completed_at=summary_dict["completed_at"],
                        duration_seconds=float(summary_dict["duration_seconds"]),
                        samples_processed=int(summary_dict["samples_processed"]),
                        verdicts_emitted=int(summary_dict["verdicts_emitted"]),
                        diagnoses_emitted=int(summary_dict["diagnoses_emitted"]),
                        proposals_emitted=int(summary_dict["proposals_emitted"]),
                        decisions_emitted=int(summary_dict["decisions_emitted"]),
                        adaptations_applied=int(
                            summary_dict.get("adaptations_applied", 0)
                        ),
                        correlation_reports_emitted=int(
                            summary_dict.get("correlation_reports_emitted", 0)
                        ),
                        outcome_counts=dict(summary_dict.get("outcome_counts", {})),
                        audit_log_path=summary_dict.get("audit_log_path"),
                        calibration_state_path=summary_dict.get(
                            "calibration_state_path"
                        ),
                    )
                )
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Coordinator: skipping unreadable cycle detail %s (%s)",
                    detail_path,
                    exc,
                )
        return tuple(loaded)

    def _write_summary(self, summary: CycleSummary) -> None:
        self.config.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.summary_path.write_text(
            json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_cycle_detail(self, summary: CycleSummary, cycle_id: str) -> None:
        assert self.config.cycle_detail_dir is not None
        target = self.config.cycle_detail_dir / cycle_id
        target.mkdir(parents=True, exist_ok=True)
        detail = {
            "summary": summary.to_dict(),
            "verdicts": list(self.bus.peek("verdicts")),
            "diagnoses": list(self.bus.peek("diagnoses")),
            "proposals": list(self.bus.peek("proposals")),
            "decisions": list(self.bus.peek("decisions")),
        }
        (target / "detail.json").write_text(
            json.dumps(detail, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
