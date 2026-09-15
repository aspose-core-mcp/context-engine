"""LLMJudgeAgent — self-reflection over the deterministic Judge.

The five reactive agents (Judge / Diagnose / Propose / Guard / Adapt)
already score, classify, and gate per-cycle activity. The deterministic
Judge produces an authoritative numeric verdict per sample under a
fixed rubric. The loop becomes self-improving when it also
*judges its own judgment* — when
it has a second, independent scoring path that the deterministic Judge
can be checked against, with persistent disagreement surfaced for
human review of the rubric itself.

This module is that second scoring path. It is a *shadow* over the
deterministic Judge:

* it runs on a subset of samples per cycle (cost control);
* it produces the same shape of verdict (overall_score + per-dimension
  + rationale);
* it does **not** alter the cycle's authoritative verdicts — those
  remain the deterministic ones, by policy;
* it emits a single typed :class:`JudgeAgreementReport` per cycle
  summarising agreement rate, mean absolute delta, and a bounded list
  of disagreement details.

The actual LLM call is abstracted behind the :class:`LLMJudgeClient`
Protocol. Production wires it to an OpenAI-compatible LLM endpoint;
tests inject a deterministic stub for reproducibility. The agent
itself is stateless across cycles.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from adcs.quality_loop.judge_agent import QueryResponseSample
from adcs.quality_loop.models import (
    JudgeAgreementReport,
    JudgeDisagreement,
    QualityVerdict,
    utc_iso,
)

logger = logging.getLogger(__name__)


class LLMJudgeClient(Protocol):
    """Adapter for an LLM-backed judge."""

    def judge(
        self, *, sample: QueryResponseSample
    ) -> tuple[float, dict[str, float], str]:
        """Score one sample.

        Returns (overall_score in [0,1], per_dimension_scores dict,
        rationale text). The agent does not interpret the rationale —
        it surfaces it verbatim in the disagreement report so a human
        reviewer can compare reasoning.
        """


@dataclass
class LLMJudgeAgentConfig:
    """Tunables for the shadow-judge agent.

    Designed for cost control: even a cheap LLM call is many orders of
    magnitude more expensive than the deterministic rule evaluation, so
    the agent samples aggressively. The disagreement tolerance is the
    delta below which two verdicts are considered to agree.
    """

    sampling_rate: float = 0.2
    max_samples_per_cycle: int = 10
    disagreement_tolerance: float = 0.15
    max_disagreements_recorded: int = 5


@dataclass
class LLMJudgeAgent:
    """Stateless shadow judge over the deterministic Judge's verdicts.

    One :meth:`compare` call per cycle. The agent has no memory across
    cycles — each invocation reads the cycle's samples and the
    deterministic verdicts produced by the JudgeAgent, calls the
    injected ``LLMJudgeClient`` on a subset, and emits exactly one
    :class:`JudgeAgreementReport`. The report flows into the audit
    log; disagreement queue is downstream operator infra (admin UI).
    """

    client: LLMJudgeClient
    config: LLMJudgeAgentConfig

    def __init__(
        self,
        *,
        client: LLMJudgeClient,
        config: LLMJudgeAgentConfig | None = None,
    ) -> None:
        self.client = client
        self.config = config or LLMJudgeAgentConfig()

    def compare(
        self,
        *,
        cycle_id: str,
        samples: Sequence[QueryResponseSample],
        deterministic_verdicts: Sequence[QualityVerdict],
    ) -> JudgeAgreementReport:
        """Score a subset via LLM, compare to deterministic, emit a report."""
        verdict_by_sample = {v.sample_id: v for v in deterministic_verdicts}
        subset = self._select_subset(samples=samples)

        agreements = 0
        disagreements = 0
        deltas: list[float] = []
        disagreement_details: list[JudgeDisagreement] = []

        for sample in subset:
            det_verdict = verdict_by_sample.get(sample.sample_id)
            if det_verdict is None:
                # No deterministic verdict to compare against; skip.
                continue
            llm_score, llm_dimensions, llm_rationale = self.client.judge(
                sample=sample
            )
            delta = abs(llm_score - det_verdict.overall_score)
            deltas.append(delta)
            if delta < self.config.disagreement_tolerance:
                agreements += 1
            else:
                disagreements += 1
                if (
                    len(disagreement_details)
                    < self.config.max_disagreements_recorded
                ):
                    disagreement_details.append(
                        JudgeDisagreement(
                            sample_id=sample.sample_id,
                            deterministic_score=det_verdict.overall_score,
                            llm_score=llm_score,
                            delta=round(delta, 4),
                            deterministic_dimensions=dict(det_verdict.per_dimension),
                            llm_dimensions=dict(llm_dimensions),
                            llm_rationale=llm_rationale,
                        )
                    )

        compared = agreements + disagreements
        # Empty-subset case: 100% agreement is vacuously true, mean delta is 0.
        agreement_rate = agreements / compared if compared > 0 else 1.0
        mean_delta = sum(deltas) / len(deltas) if deltas else 0.0

        report = JudgeAgreementReport(
            report_id=f"agree-{uuid.uuid4().hex[:12]}",
            cycle_id=cycle_id,
            emitted_at=utc_iso(),
            samples_compared=compared,
            agreements=agreements,
            disagreements=disagreements,
            agreement_rate=round(agreement_rate, 4),
            mean_absolute_delta=round(mean_delta, 4),
            disagreement_details=tuple(disagreement_details),
        )
        logger.info(
            "LLMJudgeAgent: cycle=%s compared=%d agree=%.2f mean_delta=%.3f",
            cycle_id,
            compared,
            agreement_rate,
            mean_delta,
        )
        return report

    def _select_subset(
        self, *, samples: Sequence[QueryResponseSample]
    ) -> tuple[QueryResponseSample, ...]:
        """Deterministic subset selection: sort by sample_id, take first N.

        Using a sorted prefix rather than random sampling keeps the
        cycle replayable from disk alone — the same input samples
        always produce the same shadow-judge comparisons.
        """
        if not samples:
            return ()
        cap_by_rate = max(1, int(len(samples) * self.config.sampling_rate))
        n = min(cap_by_rate, self.config.max_samples_per_cycle, len(samples))
        sorted_samples = sorted(samples, key=lambda s: s.sample_id)
        return tuple(sorted_samples[:n])
