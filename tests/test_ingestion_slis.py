"""Ingestion-sourced SLIs on /metrics.

The failure this guards against is not a missing number — it is a *plausible*
one. An absent series and a zero series look identical on a dashboard, and both
read as "healthy"; that is how "0% errors" in a release report came to mean "we
observed no errors" rather than "there were none". So the tests below care as
much about which series appear at zero as about the values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from adcs.api.ingestion_slis import render_ingestion_slis
from adcs.indexing.index_models import SnapshotRecord, SnapshotStatus
from adcs.ops.critical_events import (
    CriticalEventSeverity,
    CriticalEventType,
    InMemoryCriticalEventStore,
)

_NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _snapshot(*, snapshot_id: str, status: SnapshotStatus, age: timedelta) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        product_id="aspose.ocr",
        programming_language="net",
        version="latest-stable",
        source_kind="docs",
        source_revision="abc123",
        status=status,
        indexed_chunks_count=100,
        created_at=_NOW - age,
    )


class _Registry:
    def __init__(self, *records: SnapshotRecord) -> None:
        self._records = records

    def list_snapshots(self, **_: object) -> tuple[SnapshotRecord, ...]:
        return self._records


class _BrokenRegistry:
    def list_snapshots(self, **_: object) -> tuple[SnapshotRecord, ...]:
        raise RuntimeError("connection to server failed")


def _series(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, _, value = line.partition(" ")
        values[name] = value
    return values


def test_freshness_reports_the_stalest_active_snapshot() -> None:
    registry = _Registry(
        _snapshot(snapshot_id="a", status=SnapshotStatus.ACTIVE, age=timedelta(minutes=10)),
        _snapshot(snapshot_id="b", status=SnapshotStatus.ACTIVE, age=timedelta(days=16)),
        # An inactive snapshot older than both must not drag the SLI down: it
        # serves no traffic, so its age says nothing about content freshness.
        _snapshot(snapshot_id="c", status=SnapshotStatus.INACTIVE, age=timedelta(days=400)),
    )
    series = _series(
        render_ingestion_slis(snapshot_registry=registry, critical_event_store=None, now=_NOW)
    )

    assert float(series["adcs_index_freshness_seconds"]) == pytest.approx(
        timedelta(days=16).total_seconds()
    )
    assert float(series["adcs_index_freshness_newest_seconds"]) == pytest.approx(600.0)
    assert series["adcs_index_active_snapshots"] == "2"
    assert series["adcs_index_snapshots_total"] == "3"


def test_no_active_snapshot_emits_no_freshness_series() -> None:
    """Zero lag is what a perfect index reports; an empty index is the opposite."""
    registry = _Registry(
        _snapshot(snapshot_id="a", status=SnapshotStatus.INACTIVE, age=timedelta(days=1))
    )
    series = _series(
        render_ingestion_slis(snapshot_registry=registry, critical_event_store=None, now=_NOW)
    )

    assert "adcs_index_freshness_seconds" not in series
    assert series["adcs_index_active_snapshots"] == "0"


def test_partial_publish_series_exists_even_at_zero() -> None:
    store = InMemoryCriticalEventStore()
    series = _series(
        render_ingestion_slis(
            snapshot_registry=None, critical_event_store=store, now=_NOW
        )
    )

    assert (
        series['adcs_ingestion_publish_events_total{event_type="partial_publish"}'] == "0"
    )


def test_partial_publish_events_are_counted_by_type() -> None:
    store = InMemoryCriticalEventStore()
    for _ in range(3):
        store.emit(
            severity=CriticalEventSeverity.WARNING,
            event_type=CriticalEventType.PARTIAL_PUBLISH,
            message="partial publish",
        )
    store.emit(
        severity=CriticalEventSeverity.CRITICAL,
        event_type=CriticalEventType.PUBLISH_BLOCKED,
        message="blocked",
    )

    series = _series(
        render_ingestion_slis(
            snapshot_registry=None, critical_event_store=store, now=_NOW
        )
    )
    assert series['adcs_ingestion_publish_events_total{event_type="partial_publish"}'] == "3"
    assert series['adcs_ingestion_publish_events_total{event_type="publish_blocked"}'] == "1"


def test_count_by_type_is_not_capped_by_the_list_limit() -> None:
    """`list_events` returns 20 by default; a lifetime counter must not."""
    store = InMemoryCriticalEventStore()
    for _ in range(25):
        store.emit(
            severity=CriticalEventSeverity.WARNING,
            event_type=CriticalEventType.PARTIAL_PUBLISH,
            message="partial publish",
        )

    assert len(store.list_events()) == 20
    assert store.count_events_by_type()["partial_publish"] == 25


def test_a_failing_collector_degrades_instead_of_breaking_the_scrape() -> None:
    """The one moment /metrics matters most is when a backend is unhappy."""
    store = InMemoryCriticalEventStore()
    rendered = render_ingestion_slis(
        snapshot_registry=_BrokenRegistry(), critical_event_store=store, now=_NOW
    )
    series = _series(rendered)

    assert series["adcs_ingestion_sli_collection_errors"] == "1"
    # The healthy collector still reported.
    assert 'adcs_ingestion_publish_events_total{event_type="partial_publish"}' in series
    # And nothing leaked the driver's message into the exposition text.
    assert "connection to server failed" not in rendered


def test_collection_errors_series_is_always_present() -> None:
    series = _series(
        render_ingestion_slis(snapshot_registry=None, critical_event_store=None, now=_NOW)
    )
    assert series["adcs_ingestion_sli_collection_errors"] == "0"


def test_output_is_valid_prometheus_exposition() -> None:
    store = InMemoryCriticalEventStore()
    registry = _Registry(
        _snapshot(snapshot_id="a", status=SnapshotStatus.ACTIVE, age=timedelta(minutes=5))
    )
    rendered = render_ingestion_slis(
        snapshot_registry=registry, critical_event_store=store, now=_NOW
    )

    assert rendered.endswith("\n")
    declared: dict[str, str] = {}
    for line in rendered.splitlines():
        if line.startswith("# TYPE "):
            _, _, rest = line.partition("# TYPE ")
            name, _, kind = rest.partition(" ")
            assert name not in declared, f"duplicate TYPE for {name}: Prometheus rejects the scrape"
            declared[name] = kind
    assert declared


# ---------------------------------------------------------------------------
# Retrieval stage timings. Separate concern, same finding:
# the numbers already existed and went only to a log line.
# ---------------------------------------------------------------------------


def test_retrieval_stage_histogram_is_absent_until_something_is_observed() -> None:
    from adcs.api.metrics import InMemoryMetrics

    rendered = InMemoryMetrics().render_prometheus()
    assert "adcs_retrieval_stage_duration_seconds" not in rendered


def test_retrieval_stage_histogram_reports_per_stage_series() -> None:
    from adcs.api.metrics import InMemoryMetrics

    registry = InMemoryMetrics()
    registry.observe_retrieval_stage("retrieve", 0.4)
    registry.observe_retrieval_stage("retrieve", 1.5)
    registry.observe_retrieval_stage("pack", 0.05)

    series = _series(registry.render_prometheus())
    assert series['adcs_retrieval_stage_duration_seconds_count{stage="retrieve"}'] == "2"
    assert series['adcs_retrieval_stage_duration_seconds_count{stage="pack"}'] == "1"
    assert float(series['adcs_retrieval_stage_duration_seconds_sum{stage="retrieve"}']) == (
        pytest.approx(1.9)
    )
    # 0.4 s falls under the 0.5 bound, 1.5 s does not.
    assert series['adcs_retrieval_stage_duration_seconds_bucket{le="0.5",stage="retrieve"}'] == "1"
    assert series['adcs_retrieval_stage_duration_seconds_bucket{le="+Inf",stage="retrieve"}'] == "2"


def test_a_failing_stage_observer_cannot_fail_a_query() -> None:
    """Telemetry is not worth an error the caller can see."""
    from adcs.api.public_docs_query import PublicQueryService

    def _explode(stage: str, seconds: float) -> None:
        raise RuntimeError("metrics backend down")

    service = PublicQueryService.__new__(PublicQueryService)
    service._stage_observer = _explode  # type: ignore[attr-defined]
    service._observe_stage("retrieve", 0.1)  # type: ignore[attr-defined]
