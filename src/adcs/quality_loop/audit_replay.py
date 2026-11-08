"""Audit-log replay utility for the quality loop.

Every cycle persists every typed message it produces to the JSONL
audit log (``reports/quality-loop/audit-log.jsonl``). This module
turns that log back into a typed view of a cycle: given a cycle id,
it walks the log, pulls every message tagged with that cycle_id,
and assembles a :class:`CycleReplay` with all the agents' outputs
in chronological order.

The audit-log replay is the explainability anchor: any past
cycle's decisions are fully reconstructible from disk alone, with
no hidden in-memory state. An auditor can answer
"why did the loop tighten the guard cap on cycle X?" by reading
the replay's adaptation event and the correlation report that
preceded it.

The module is intentionally pure-Python (no DB / no Pydantic
runtime) so it remains usable offline against a downloaded copy of
the log — for example by an external auditor or by post-incident
triage.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CycleReplay:
    """Typed view of one cycle reconstructed from the audit log.

    Every field corresponds to one message-type emitted by an agent.
    Empty tuples mean the agent did not run for that cycle (e.g.,
    ``correlation_reports`` is empty when no CrossCycleCorrelationAgent
    was wired into the Coordinator).
    """

    cycle_id: str
    samples: tuple[dict, ...] = field(default_factory=tuple)
    verdicts: tuple[dict, ...] = field(default_factory=tuple)
    diagnoses: tuple[dict, ...] = field(default_factory=tuple)
    proposals: tuple[dict, ...] = field(default_factory=tuple)
    decisions: tuple[dict, ...] = field(default_factory=tuple)
    adaptations: tuple[dict, ...] = field(default_factory=tuple)
    correlation_reports: tuple[dict, ...] = field(default_factory=tuple)
    judge_agreement_reports: tuple[dict, ...] = field(default_factory=tuple)
    summary: dict | None = None
    raw_entry_count: int = 0


_TOPIC_FIELDS: dict[str, str] = {
    "samples": "samples",
    "verdicts": "verdicts",
    "diagnoses": "diagnoses",
    "proposals": "proposals",
    "decisions": "decisions",
    "adaptations": "adaptations",
    "correlations": "correlation_reports",
    "judge_agreement": "judge_agreement_reports",
}

# Some agents tag their entries with `message_type` rather than `topic`;
# the replay accepts either path so audit logs written with the older
# `message_type` tag still parse.
_MESSAGE_TYPE_TO_FIELD: dict[str, str] = {
    "QueryResponseSample": "samples",
    "QualityVerdict": "verdicts",
    "DiagnosisReport": "diagnoses",
    "RemediationProposal": "proposals",
    "GuardDecision": "decisions",
    "AdaptationEvent": "adaptations",
    "CorrelationReport": "correlation_reports",
    "JudgeAgreementReport": "judge_agreement_reports",
}


def replay_cycle(*, audit_log_path: Path, cycle_id: str) -> CycleReplay:
    """Reconstruct a single cycle from the JSONL audit log.

    Reads the file line-by-line, filters entries by ``cycle_id``,
    classifies each entry by its ``topic`` (when present) or
    ``message_type`` (the legacy tag), and returns a typed
    :class:`CycleReplay`.

    Returns an empty replay (all tuples empty, summary None) when the
    log does not exist or the cycle id is unknown — the caller can
    distinguish via :attr:`CycleReplay.raw_entry_count`.

    Malformed JSON lines are skipped silently — the log is append-only
    and may contain partial writes mid-cycle. The replay degrades
    gracefully rather than failing on a single bad row.
    """
    buckets: dict[str, list[dict]] = {field: [] for field in _TOPIC_FIELDS.values()}
    summary: dict | None = None
    entry_count = 0

    for entry in _iter_entries(path=audit_log_path):
        if entry.get("cycle_id") != cycle_id:
            continue
        entry_count += 1
        field_name = _classify(entry)
        if field_name is not None:
            buckets[field_name].append(entry)
            continue
        if entry.get("message_type") == "CycleSummary":
            summary = entry

    return CycleReplay(
        cycle_id=cycle_id,
        samples=tuple(buckets["samples"]),
        verdicts=tuple(buckets["verdicts"]),
        diagnoses=tuple(buckets["diagnoses"]),
        proposals=tuple(buckets["proposals"]),
        decisions=tuple(buckets["decisions"]),
        adaptations=tuple(buckets["adaptations"]),
        correlation_reports=tuple(buckets["correlation_reports"]),
        judge_agreement_reports=tuple(buckets["judge_agreement_reports"]),
        summary=summary,
        raw_entry_count=entry_count,
    )


def list_cycle_ids(*, audit_log_path: Path) -> tuple[str, ...]:
    """Return every distinct cycle_id present in the audit log.

    Order is first-appearance (oldest cycle first); duplicates within
    a cycle are collapsed. Useful for the admin UI's cycle picker.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in _iter_entries(path=audit_log_path):
        cycle_id = entry.get("cycle_id")
        if not isinstance(cycle_id, str) or cycle_id in seen:
            continue
        seen.add(cycle_id)
        ordered.append(cycle_id)
    return tuple(ordered)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_entries(*, path: Path) -> Iterator[dict]:
    """Yield each well-formed JSON object in the JSONL file.

    Missing file → empty iterator. Malformed lines → skipped silently.
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _classify(entry: dict) -> str | None:
    """Return the target field name for a typed entry, or None.

    Two channels are supported: the topic name the InMemoryMessageBus
    writes (``topic="verdicts"``) and the legacy ``message_type`` tag
    that the older agents used. The CycleSummary message has its own
    field (the ``summary`` attribute on CycleReplay) and is handled by
    the caller, so we return ``None`` for it here.
    """
    topic = entry.get("topic")
    if isinstance(topic, str) and topic in _TOPIC_FIELDS:
        return _TOPIC_FIELDS[topic]
    message_type = entry.get("message_type")
    if isinstance(message_type, str) and message_type in _MESSAGE_TYPE_TO_FIELD:
        return _MESSAGE_TYPE_TO_FIELD[message_type]
    return None
