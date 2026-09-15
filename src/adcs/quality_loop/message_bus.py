"""In-memory message bus + JSONL audit sink for the quality loop.

Keeping the bus in-memory by default makes the loop CI-runnable with no
infra dependency. The audit sink is the only persistent surface — every
message that flows through the bus is also appended (sorted, single
line) to the configured JSONL file. That file is committed to the repo
so external auditors can inspect the loop's decision history.

A future phase may swap the in-memory bus for Redis pub/sub or a
proper task queue without touching agent code, because every agent
talks to the bus through the :class:`MessageBus` Protocol.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class AuditSink(Protocol):
    """Sink that an audit-grade message bus writes to."""

    def append(self, record: dict[str, Any]) -> None:
        """Persist a record. Must be append-only."""


class MessageBus(Protocol):
    """Minimal pub/sub the agents share."""

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish ``payload`` on ``topic``; sink is notified too."""

    def drain(self, topic: str) -> tuple[dict[str, Any], ...]:
        """Return all messages on ``topic`` and clear them.

        Drain semantics (rather than subscribe-callbacks) make each agent
        idempotent: it processes whatever is queued at run time.
        """


# ---------------------------------------------------------------------------
# JsonlAuditSink
# ---------------------------------------------------------------------------


class JsonlAuditSink:
    """Append-only JSONL file sink. The committed audit log."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")


class _NullAuditSink:
    """Used by tests that don't care about persistence."""

    def append(self, record: dict[str, Any]) -> None:
        del record


# ---------------------------------------------------------------------------
# InMemoryMessageBus
# ---------------------------------------------------------------------------


@dataclass
class InMemoryMessageBus:
    """In-memory pub/sub. Drain-style consumption.

    The bus does not deduplicate or order messages beyond insertion
    order. Agents relying on ordering must impose it themselves (the
    Coordinator enforces a fixed agent execution order, so this is
    fine for the single-cycle case).
    """

    sink: AuditSink

    def __post_init__(self) -> None:
        self._topics: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @classmethod
    def with_null_sink(cls) -> InMemoryMessageBus:
        return cls(sink=_NullAuditSink())

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        # Audit is recorded with the topic so the JSONL is self-describing.
        record = {"topic": topic, **payload}
        self._topics[topic].append(payload)
        self.sink.append(record)

    def drain(self, topic: str) -> tuple[dict[str, Any], ...]:
        items = tuple(self._topics.get(topic, ()))
        self._topics[topic] = []
        return items

    def peek(self, topic: str) -> tuple[dict[str, Any], ...]:
        """Read without draining. Useful in tests."""
        return tuple(self._topics.get(topic, ()))

    def topics(self) -> tuple[str, ...]:
        return tuple(self._topics)
