"""Drill protocol + result schema shared by every chaos drill module.

A drill is a deterministic Python procedure that:

1. Captures a baseline (the system's nominal behaviour).
2. Injects a fault (raises an exception inside an adapter, blocks a port,
   delays a coroutine, corrupts a snapshot pointer, etc.).
3. Observes the system's degraded-mode response.
4. Verifies the recovery contract (RTO + RPO + the textual contract every
   drill ships in its ``recovery_steps``).
5. Removes the fault and asserts the system returns to nominal.
6. Returns a :class:`DrillResult` that the runner serialises into
   ``reports/chaos/``.

The schema is intentionally JSON-friendly. Every field is a primitive,
sequence of primitives, or mapping of primitives so the JSONL audit log
is easily machine-readable for downstream auditors.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

DrillOutcome = Literal["PASS", "DEGRADED", "FAIL", "ERROR"]


@dataclass(frozen=True)
class DrillResult:
    """JSON-serialisable record of a single drill run.

    ``outcome`` semantics:

    - ``PASS`` — system handled the fault inside both RTO + RPO targets and
      every entry in ``verified[]`` was satisfied.
    - ``DEGRADED`` — system handled the fault but at least one verification
      missed (e.g. recovery slower than RTO target).
    - ``FAIL`` — system did not handle the fault as documented (outage
      escaped the degraded-mode contract). Treated as P2-blocking.
    - ``ERROR`` — the drill itself raised; the result is inconclusive.
    """

    drill_id: str
    drill_name: str
    scenario: str
    started_at: str  # ISO-8601 UTC
    completed_at: str
    duration_seconds: float
    rto_target_seconds: float
    rto_observed_seconds: float
    rpo_target_seconds: float
    rpo_observed_seconds: float
    outcome: DrillOutcome
    verified: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    telemetry: dict[str, Any] = field(default_factory=dict)
    recovery_steps: list[str] = field(default_factory=list)
    evidence_artifact: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DrillTimer:
    """Tiny stopwatch used by every drill for RTO observation."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self._start


def utc_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_evidence(result: DrillResult, *, root: Path) -> Path:
    """Write a per-drill detail JSON under ``reports/chaos/drills/<id>/``.

    The file path is also stored on the returned :class:`DrillResult`'s
    ``evidence_artifact`` attribute, so the runner's append-only JSONL log
    (committed) cross-references each detail file (gitignored).
    """
    detail_dir = root / "drills" / result.drill_id
    detail_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = result.started_at.replace(":", "").replace("-", "")
    detail_path = detail_dir / f"{safe_ts}.json"
    detail_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return detail_path
