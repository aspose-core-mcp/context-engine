"""Tests for the audit-log replay utility (A8 Explainability).

Two flavours of input are covered:

1. **Synthetic JSONL** — handcrafted lines exercising every typed
   message variant, both the ``topic``-tagged path and the legacy
   ``message_type`` path.
2. **End-to-end** — drive a real Coordinator, capture its
   reports/quality-loop/audit-log.jsonl, then replay one of the
   cycle ids back into a CycleReplay and verify each agent's output
   appears in the right field.
"""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import (
    Coordinator,
    CoordinatorConfig,
    DiagnosisAgent,
    GuardAgent,
    JudgeAgent,
    LLMJudgeAgent,
    ProposalAgent,
    QueryResponseSample,
)
from adcs.quality_loop.audit_replay import (
    CycleReplay,
    list_cycle_ids,
    replay_cycle,
)
from adcs.quality_loop.judge_agent import make_sample_id


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Empty / missing-file behaviour
# ---------------------------------------------------------------------------


def test_replay_missing_file_returns_empty_view(tmp_path: Path) -> None:
    replay = replay_cycle(
        audit_log_path=tmp_path / "missing.jsonl", cycle_id="c1"
    )
    assert isinstance(replay, CycleReplay)
    assert replay.cycle_id == "c1"
    assert replay.raw_entry_count == 0
    assert replay.samples == ()
    assert replay.summary is None


def test_replay_unknown_cycle_returns_empty_view(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "verdicts", "cycle_id": "c1", "sample_id": "s1"},
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="never-existed")
    assert replay.raw_entry_count == 0
    assert replay.verdicts == ()


def test_list_cycle_ids_missing_file_returns_empty() -> None:
    assert list_cycle_ids(audit_log_path=Path("/nope/never.jsonl")) == ()


# ---------------------------------------------------------------------------
# Synthetic JSONL: topic-tagged and message_type-tagged paths
# ---------------------------------------------------------------------------


def test_replay_topic_tagged_entries(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "samples", "cycle_id": "c1", "sample_id": "s1"},
            {"topic": "verdicts", "cycle_id": "c1", "sample_id": "s1"},
            {"topic": "diagnoses", "cycle_id": "c1", "diagnosis_id": "d1"},
            {"topic": "proposals", "cycle_id": "c1", "proposal_id": "p1"},
            {"topic": "decisions", "cycle_id": "c1", "proposal_id": "p1"},
            {"topic": "adaptations", "cycle_id": "c1", "event_id": "a1"},
            {"topic": "correlations", "cycle_id": "c1", "report_id": "cr1"},
            {"topic": "judge_agreement", "cycle_id": "c1", "report_id": "ag1"},
            {
                "message_type": "CycleSummary",
                "cycle_id": "c1",
                "duration_seconds": 0.1,
            },
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    assert replay.raw_entry_count == 9
    assert len(replay.samples) == 1
    assert len(replay.verdicts) == 1
    assert len(replay.diagnoses) == 1
    assert len(replay.proposals) == 1
    assert len(replay.decisions) == 1
    assert len(replay.adaptations) == 1
    assert len(replay.correlation_reports) == 1
    assert len(replay.judge_agreement_reports) == 1
    assert replay.summary is not None
    assert replay.summary["duration_seconds"] == 0.1


def test_replay_message_type_tagged_entries_legacy_path(tmp_path: Path) -> None:
    """Older audit logs tagged by `message_type` only. Replay must accept both."""
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"message_type": "QueryResponseSample", "cycle_id": "c1"},
            {"message_type": "QualityVerdict", "cycle_id": "c1"},
            {"message_type": "DiagnosisReport", "cycle_id": "c1"},
            {"message_type": "RemediationProposal", "cycle_id": "c1"},
            {"message_type": "GuardDecision", "cycle_id": "c1"},
            {"message_type": "AdaptationEvent", "cycle_id": "c1"},
            {"message_type": "CorrelationReport", "cycle_id": "c1"},
            {"message_type": "JudgeAgreementReport", "cycle_id": "c1"},
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    assert len(replay.samples) == 1
    assert len(replay.verdicts) == 1
    assert len(replay.diagnoses) == 1
    assert len(replay.proposals) == 1
    assert len(replay.decisions) == 1
    assert len(replay.adaptations) == 1
    assert len(replay.correlation_reports) == 1
    assert len(replay.judge_agreement_reports) == 1


# ---------------------------------------------------------------------------
# Cross-cycle isolation
# ---------------------------------------------------------------------------


def test_replay_filters_to_requested_cycle_id(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "verdicts", "cycle_id": "c1", "sample_id": "s1"},
            {"topic": "verdicts", "cycle_id": "c2", "sample_id": "s2"},
            {"topic": "verdicts", "cycle_id": "c1", "sample_id": "s3"},
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    assert len(replay.verdicts) == 2
    assert {v["sample_id"] for v in replay.verdicts} == {"s1", "s3"}


def test_list_cycle_ids_returns_unique_first_appearance_order(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "verdicts", "cycle_id": "c-alpha"},
            {"topic": "verdicts", "cycle_id": "c-zeta"},
            {"topic": "verdicts", "cycle_id": "c-alpha"},  # dup
            {"topic": "verdicts", "cycle_id": "c-beta"},
            {"topic": "verdicts", "cycle_id": "c-zeta"},  # dup
        ],
    )
    assert list_cycle_ids(audit_log_path=log) == (
        "c-alpha",
        "c-zeta",
        "c-beta",
    )


# ---------------------------------------------------------------------------
# Robustness: malformed / blank lines
# ---------------------------------------------------------------------------


def test_malformed_lines_are_skipped_silently(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        fh.write("not-json-at-all\n")
        fh.write("\n")
        fh.write(json.dumps({"topic": "verdicts", "cycle_id": "c1"}) + "\n")
        fh.write("{ broken json\n")
        fh.write(json.dumps({"topic": "decisions", "cycle_id": "c1"}) + "\n")
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    assert len(replay.verdicts) == 1
    assert len(replay.decisions) == 1


def test_entries_without_cycle_id_are_ignored(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "verdicts"},  # no cycle_id
            {"topic": "verdicts", "cycle_id": "c1"},
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    assert len(replay.verdicts) == 1


def test_entries_with_unknown_topic_skip_classification(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    _write_jsonl(
        log,
        [
            {"topic": "future-topic-not-yet-classified", "cycle_id": "c1"},
            {"topic": "verdicts", "cycle_id": "c1"},
        ],
    )
    replay = replay_cycle(audit_log_path=log, cycle_id="c1")
    # The unknown-topic row is still counted in raw_entry_count but not
    # classified into any bucket — this is the forwards-compatible path
    # so a future agent can publish to a new topic without breaking
    # replay on older readers.
    assert replay.raw_entry_count == 2
    assert len(replay.verdicts) == 1
    assert replay.summary is None


# ---------------------------------------------------------------------------
# End-to-end: replay a real Coordinator cycle
# ---------------------------------------------------------------------------


class _MirrorClient:
    def judge(self, *, sample: QueryResponseSample):
        return 0.9, {}, "mirror-stub"


def _sample() -> QueryResponseSample:
    return QueryResponseSample(
        sample_id=make_sample_id(),
        captured_at="2026-06-02T00:00:00Z",
        product_id="aspose.ocr",
        programming_language="net",
        requested_version="25.1",
        strict_version=True,
        query="recognize image",
        candidates=(
            {
                "canonical_url": "https://docs.aspose.com/ocr/net/",
                "version": "25.1",
                "chunk_id": "c1",
                "symbol_fqn": "Aspose.OCR.Recognize",
            },
        ),
        confidence_score=0.85,
    )


def test_real_coordinator_cycle_round_trips_through_replay(
    tmp_path: Path,
) -> None:
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
    )
    samples = tuple(_sample() for _ in range(2))
    coord = Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
        llm_judge=LLMJudgeAgent(client=_MirrorClient()),
    )
    summary = coord.run_cycle()

    # The replay should reconstruct exactly what the Coordinator emitted
    replay = replay_cycle(
        audit_log_path=config.audit_log_path, cycle_id=summary.cycle_id
    )
    assert replay.cycle_id == summary.cycle_id
    assert len(replay.samples) == summary.samples_processed
    assert len(replay.verdicts) == summary.verdicts_emitted
    assert len(replay.diagnoses) == summary.diagnoses_emitted
    assert len(replay.proposals) == summary.proposals_emitted
    assert len(replay.decisions) == summary.decisions_emitted
    # CrossCycleCorrelationAgent always runs (default-on) → 1 report
    assert len(replay.correlation_reports) == 1
    # LLMJudgeAgent ran (we wired it) → 1 agreement report
    assert len(replay.judge_agreement_reports) == 1
    assert replay.summary is not None


def test_list_cycle_ids_against_real_coordinator(tmp_path: Path) -> None:
    """Driving the Coordinator twice produces two distinct cycle ids in the log."""
    config = CoordinatorConfig(
        audit_log_path=tmp_path / "audit.jsonl",
        summary_path=tmp_path / "summary.json",
    )
    samples = (_sample(),)
    coord = Coordinator(
        config=config,
        judge=JudgeAgent(),
        diagnoser=DiagnosisAgent(),
        proposer=ProposalAgent(),
        guard=GuardAgent(),
        sample_provider=lambda: samples,
    )
    s1 = coord.run_cycle()
    s2 = coord.run_cycle()
    ids = list_cycle_ids(audit_log_path=config.audit_log_path)
    assert s1.cycle_id in ids
    assert s2.cycle_id in ids
    assert ids.index(s1.cycle_id) < ids.index(s2.cycle_id)
