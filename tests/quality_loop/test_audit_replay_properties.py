"""Property-based tests for the audit-log replay utility.

The hand-written tests in ``test_audit_replay.py`` pin specific shapes;
these fuzz the JSONL log over wide inputs and assert the *invariants*
that make the replay an Explainability anchor:

* **Purity** — ``replay_cycle`` is a pure function of the file's bytes:
  calling it twice on the same file yields equal results, with no
  hidden in-memory state.
* **Cycle isolation** — every entry that lands in a bucket (or the
  summary slot) carries the requested ``cycle_id``; entries from other
  cycles never leak in.
* **Malformed tolerance** — interleaving non-JSON lines, blank lines,
  and valid-JSON-but-not-a-dict lines (arrays, numbers, strings) does
  not change the reconstructed view: garbage is skipped silently.
* **Count coherence** — ``raw_entry_count`` equals the number of
  cycle-matched dict entries and is an upper bound on the total bucketed
  entries (summary + unknown-topic rows are counted but unbucketed).
* **``list_cycle_ids``** — returns the unique cycle ids in
  first-appearance order, exactly the set of string cycle ids present.
"""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.quality_loop.audit_replay import (
    CycleReplay,
    list_cycle_ids,
    replay_cycle,
)

# The topic→field contract the replay keys on. Hardcoded here (not
# imported from the module) so a rename in the source is caught as a
# behaviour change rather than silently tracked.
_TOPICS = (
    "samples",
    "verdicts",
    "diagnoses",
    "proposals",
    "decisions",
    "adaptations",
    "correlations",
    "judge_agreement",
)

_LEGACY_MESSAGE_TYPES = (
    "QueryResponseSample",
    "QualityVerdict",
    "DiagnosisReport",
    "RemediationProposal",
    "GuardDecision",
    "AdaptationEvent",
    "CorrelationReport",
    "JudgeAgreementReport",
)

# A small, collision-heavy cycle-id pool so multiple cycles co-exist in
# one log and filtering actually has to do work.
_CYCLE_IDS = ("c1", "c2", "c3")

# Lines that must always be skipped by the reader: non-JSON, blank, and
# valid-JSON-but-not-an-object payloads.
_MALFORMED = (
    "not json at all",
    "",
    "   ",
    "{ broken",
    "[1, 2, 3]",
    "42",
    '"just a string"',
    "null",
    "true",
)

_BUCKET_ATTRS = (
    "samples",
    "verdicts",
    "diagnoses",
    "proposals",
    "decisions",
    "adaptations",
    "correlation_reports",
    "judge_agreement_reports",
)


@st.composite
def _entry(draw: st.DrawFn) -> dict:
    """A single well-formed audit entry (always a JSON object)."""
    kind = draw(
        st.sampled_from(
            ["topic", "legacy", "summary", "unknown_topic", "no_cycle"]
        )
    )
    entry: dict = {"payload": draw(st.integers(min_value=-5, max_value=5))}
    if kind != "no_cycle":
        entry["cycle_id"] = draw(st.sampled_from(_CYCLE_IDS))
    if kind == "topic":
        entry["topic"] = draw(st.sampled_from(_TOPICS))
    elif kind == "legacy":
        entry["message_type"] = draw(st.sampled_from(_LEGACY_MESSAGE_TYPES))
    elif kind == "summary":
        entry["message_type"] = "CycleSummary"
    elif kind == "unknown_topic":
        entry["topic"] = draw(st.sampled_from(["future_topic", "xyz", "v2.metrics"]))
    # kind == "no_cycle": no cycle_id key at all
    return entry


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _interleave(valid: list[str], malformed: list[str]) -> list[str]:
    """Insert malformed lines without reordering the valid lines.

    Bucket ordering is by appearance, so preserving the relative order
    of the valid lines is what lets us assert clean == dirty.
    """
    out: list[str] = []
    mi = 0
    for v in valid:
        if mi < len(malformed):
            out.append(malformed[mi])
            mi += 1
        out.append(v)
    out.extend(malformed[mi:])
    return out


def _buckets(replay: CycleReplay) -> list[tuple[dict, ...]]:
    return [getattr(replay, attr) for attr in _BUCKET_ATTRS]


@given(
    entries=st.lists(_entry(), max_size=40),
    target=st.sampled_from(_CYCLE_IDS),
)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_replay_is_pure_and_isolates_cycle(
    entries: list[dict], target: str, tmp_path: Path
) -> None:
    path = tmp_path / "audit.jsonl"
    _write_lines(path, [json.dumps(e) for e in entries])

    first = replay_cycle(audit_log_path=path, cycle_id=target)
    second = replay_cycle(audit_log_path=path, cycle_id=target)

    # (a) purity — identical results across calls, no hidden state
    assert first == second

    # (b) cycle isolation — nothing from another cycle leaks into a bucket
    for bucket in _buckets(first):
        for entry in bucket:
            assert entry.get("cycle_id") == target
    if first.summary is not None:
        assert first.summary.get("cycle_id") == target

    # (d) count coherence
    bucketed = sum(len(b) for b in _buckets(first))
    assert first.raw_entry_count >= bucketed
    expected_raw = sum(1 for e in entries if e.get("cycle_id") == target)
    assert first.raw_entry_count == expected_raw


@given(
    entries=st.lists(_entry(), max_size=40),
    malformed=st.lists(st.sampled_from(_MALFORMED), max_size=12),
    target=st.sampled_from(_CYCLE_IDS),
)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_malformed_lines_do_not_change_the_view(
    entries: list[dict],
    malformed: list[str],
    target: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    valid_lines = [json.dumps(e) for e in entries]

    _write_lines(path, valid_lines)
    clean = replay_cycle(audit_log_path=path, cycle_id=target)

    _write_lines(path, _interleave(valid_lines, malformed))
    dirty = replay_cycle(audit_log_path=path, cycle_id=target)

    # (c) malformed tolerance — garbage between valid lines is invisible
    assert clean == dirty


@given(entries=st.lists(_entry(), max_size=40))
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_list_cycle_ids_is_unique_first_appearance(
    entries: list[dict], tmp_path: Path
) -> None:
    path = tmp_path / "audit.jsonl"
    _write_lines(path, [json.dumps(e) for e in entries])

    ids = list_cycle_ids(audit_log_path=path)

    # unique
    assert len(ids) == len(set(ids))

    # exactly the set of string cycle ids present in the file
    present = [
        e["cycle_id"] for e in entries if isinstance(e.get("cycle_id"), str)
    ]
    assert set(ids) == set(present)

    # first-appearance order
    seen: set[str] = set()
    expected_order: list[str] = []
    for cid in present:
        if cid not in seen:
            seen.add(cid)
            expected_order.append(cid)
    assert list(ids) == expected_order


@given(entries=st.lists(_entry(), max_size=40))
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_absent_cycle_id_yields_empty_replay(
    entries: list[dict], tmp_path: Path
) -> None:
    path = tmp_path / "audit.jsonl"
    _write_lines(path, [json.dumps(e) for e in entries])

    # _CYCLE_IDS never contains this sentinel.
    replay = replay_cycle(audit_log_path=path, cycle_id="absent-sentinel-cycle")

    assert replay.raw_entry_count == 0
    assert replay.summary is None
    assert all(len(b) == 0 for b in _buckets(replay))
