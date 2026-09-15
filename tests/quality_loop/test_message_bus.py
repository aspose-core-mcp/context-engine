"""Unit tests for the in-memory bus + JSONL audit sink."""

from __future__ import annotations

import json
from pathlib import Path

from adcs.quality_loop import InMemoryMessageBus, JsonlAuditSink


def test_publish_appends_to_audit_sink(tmp_path: Path) -> None:
    sink = JsonlAuditSink(path=tmp_path / "audit.jsonl")
    bus = InMemoryMessageBus(sink=sink)

    bus.publish("verdicts", {"sample_id": "s1", "score": 0.9})
    bus.publish("verdicts", {"sample_id": "s2", "score": 0.4})

    lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["topic"] == "verdicts"
    assert parsed[0]["sample_id"] == "s1"


def test_drain_returns_messages_and_clears_topic() -> None:
    bus = InMemoryMessageBus.with_null_sink()
    bus.publish("topic-a", {"x": 1})
    bus.publish("topic-a", {"x": 2})

    drained = bus.drain("topic-a")
    assert len(drained) == 2
    # Second drain returns empty
    assert bus.drain("topic-a") == ()


def test_peek_does_not_clear_topic() -> None:
    bus = InMemoryMessageBus.with_null_sink()
    bus.publish("t", {"k": "v"})

    assert bus.peek("t") == ({"k": "v"},)
    assert bus.peek("t") == ({"k": "v"},)
    assert bus.drain("t") == ({"k": "v"},)


def test_topics_lists_only_published_topics() -> None:
    bus = InMemoryMessageBus.with_null_sink()
    bus.publish("alpha", {})
    bus.publish("beta", {})

    assert set(bus.topics()) == {"alpha", "beta"}


def test_audit_sink_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deeply" / "nested" / "dir"
    sink = JsonlAuditSink(path=nested / "audit.jsonl")

    sink.append({"hello": "world"})

    assert (nested / "audit.jsonl").exists()


def test_audit_sink_preserves_unicode(tmp_path: Path) -> None:
    sink = JsonlAuditSink(path=tmp_path / "audit.jsonl")
    sink.append({"note": "Аспоуз — кириллица сохранена"})

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert "Аспоуз" in parsed["note"]
