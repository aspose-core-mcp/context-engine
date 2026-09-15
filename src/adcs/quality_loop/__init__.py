"""ADCS continuous quality-improvement multi-agent loop.

Wires four cooperating agents around the existing retrieval + quality
gates. Each agent has a distinct role, consumes typed messages from
the previous agent, and emits typed messages for the next:

  JudgeAgent      samples recent query_docs responses; scores each on
                  citation accuracy, version match, FQN consistency,
                  and confidence calibration; emits QualityVerdict[].

  DiagnosisAgent  consumes verdicts; clusters low-score samples by
                  product/language/version/scope; identifies the
                  most likely root cause from a fixed taxonomy;
                  emits DiagnosisReport[].

  ProposalAgent   consumes diagnoses; generates typed remediation
                  proposals (open incident, adjust fusion weights,
                  trigger snapshot rollback); each proposal carries
                  blast radius + confidence; emits RemediationProposal[].

  GuardAgent      consumes proposals; gates each per the safety policy
                  (auto-approve tracking actions, require human
                  approval for destructive ones, reject anything
                  above the configured blast radius); emits
                  GuardDecision[].

The Coordinator runs the cycle and persists every message to
``reports/quality-loop/audit-log.jsonl`` (committed) for tamper-evident
audit. Per-cycle detail goes under ``reports/quality-loop/cycles/<ts>/``
(gitignored, CI artifact).

Default mode is **read-only**: GuardAgent never auto-executes a
destructive proposal. Production roll-out is staged in phases — see
``docs/quality-loop.md``.
"""

from adcs.quality_loop.adaptive_agent import AdaptiveAgent, AdaptiveAgentConfig
from adcs.quality_loop.audit_replay import (
    CycleReplay,
    list_cycle_ids,
    replay_cycle,
)
from adcs.quality_loop.calibration import CalibrationBounds, CalibrationState
from adcs.quality_loop.coordinator import Coordinator, CoordinatorConfig
from adcs.quality_loop.correlation_agent import (
    CrossCycleCorrelationAgent,
    CrossCycleCorrelationAgentConfig,
)
from adcs.quality_loop.diagnosis_agent import DiagnosisAgent
from adcs.quality_loop.guard_agent import GuardAgent
from adcs.quality_loop.judge_agent import JudgeAgent, QueryResponseSample
from adcs.quality_loop.llm_judge_agent import (
    LLMJudgeAgent,
    LLMJudgeAgentConfig,
    LLMJudgeClient,
)
from adcs.quality_loop.message_bus import InMemoryMessageBus, JsonlAuditSink
from adcs.quality_loop.models import (
    AdaptationEvent,
    AdaptationKind,
    CorrelationReport,
    CorrelationTrend,
    CycleSummary,
    DiagnosisReport,
    DiagnosisRootCause,
    GuardDecision,
    GuardOutcome,
    JudgeAgreementReport,
    JudgeDisagreement,
    ProposalAction,
    QualityVerdict,
    RemediationProposal,
)
from adcs.quality_loop.proposal_agent import ProposalAgent

__all__ = [
    "AdaptationEvent",
    "AdaptationKind",
    "AdaptiveAgent",
    "AdaptiveAgentConfig",
    "CalibrationBounds",
    "CalibrationState",
    "Coordinator",
    "CoordinatorConfig",
    "CorrelationReport",
    "CorrelationTrend",
    "CrossCycleCorrelationAgent",
    "CrossCycleCorrelationAgentConfig",
    "CycleReplay",
    "CycleSummary",
    "DiagnosisAgent",
    "DiagnosisReport",
    "DiagnosisRootCause",
    "GuardAgent",
    "GuardDecision",
    "GuardOutcome",
    "InMemoryMessageBus",
    "JsonlAuditSink",
    "JudgeAgent",
    "JudgeAgreementReport",
    "JudgeDisagreement",
    "list_cycle_ids",
    "LLMJudgeAgent",
    "LLMJudgeAgentConfig",
    "LLMJudgeClient",
    "ProposalAction",
    "ProposalAgent",
    "QualityVerdict",
    "QueryResponseSample",
    "RemediationProposal",
    "replay_cycle",
]
