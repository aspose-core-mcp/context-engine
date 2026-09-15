"""Ingestion SLIs, derived from persisted state at scrape time.

Two of the SLIs — `index_freshness_lag` and `ingestion_partial_publish_ratio`
— are produced by ingestion, which runs in the worker pod. That process serves
no HTTP and therefore has no `/metrics`, so the obvious fix is a second metrics
endpoint plus a Service and a ServiceMonitor in the deployment manifests.

This module takes the other route: the API derives both from state ingestion
already writes to Postgres (`index_snapshots`, `critical_events`). No new
deployment surface, no schema change and no new scrape target — a derived gauge
shows up immediately on the existing `/metrics` and in the admin observability
page.

Everything here runs inside a scrape. A metrics endpoint that fails when the
database is unhappy is worse than useless, because that is exactly when someone
is reading it — so failures are reported *as a metric* and the rest of the
output is unaffected.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from adcs.indexing.index_models import SnapshotRecord, SnapshotStatus

logger = logging.getLogger("adcs.api.ingestion_slis")

# Emitted when the numerator exists but the run count does not, so a dashboard
# cannot mistake "no data" for "zero partial publishes".
_PARTIAL_PUBLISH_EVENT = "partial_publish"


class _SnapshotSource(Protocol):
    def list_snapshots(
        self,
        *,
        product_id: str | None = ...,
        programming_language: str | None = ...,
        version: str | None = ...,
    ) -> tuple[SnapshotRecord, ...]: ...


class _EventSource(Protocol):
    def count_events_by_type(self) -> dict[str, int]: ...


def _freshness_lines(snapshots: tuple[SnapshotRecord, ...], *, now: datetime) -> list[str]:
    active = [record for record in snapshots if record.status is SnapshotStatus.ACTIVE]
    lines = [
        "# HELP adcs_index_snapshots_total Snapshots recorded by the registry.",
        "# TYPE adcs_index_snapshots_total gauge",
        f"adcs_index_snapshots_total {len(snapshots)}",
        "# HELP adcs_index_active_snapshots Snapshots currently serving traffic.",
        "# TYPE adcs_index_active_snapshots gauge",
        f"adcs_index_active_snapshots {len(active)}",
    ]
    if not active:
        # No series at all rather than a zero: zero seconds of lag is what a
        # perfectly fresh index reports, and an empty index is the opposite.
        return lines

    ages = [
        (now - _as_utc(record.created_at)).total_seconds()
        for record in active
    ]
    lines.extend(
        [
            "# HELP adcs_index_freshness_seconds "
            "Age of the stalest active snapshot (SLI index_freshness_lag).",
            "# TYPE adcs_index_freshness_seconds gauge",
            f"adcs_index_freshness_seconds {max(ages):.3f}",
            "# HELP adcs_index_freshness_newest_seconds "
            "Age of the freshest active snapshot.",
            "# TYPE adcs_index_freshness_newest_seconds gauge",
            f"adcs_index_freshness_newest_seconds {min(ages):.3f}",
        ]
    )
    return lines


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _publish_event_lines(counts: dict[str, int]) -> list[str]:
    lines = [
        "# HELP adcs_ingestion_publish_events_total "
        "Critical events emitted by the publish pipeline, by type.",
        "# TYPE adcs_ingestion_publish_events_total counter",
    ]
    # Always emit the partial-publish series, even at zero: it is the numerator
    # of an SLI, and an absent series reads as "healthy" on a dashboard exactly
    # as convincingly as a zero one, so absence must never stand in for zero.
    materialized = dict(counts)
    materialized.setdefault(_PARTIAL_PUBLISH_EVENT, 0)
    for event_type, count in sorted(materialized.items()):
        lines.append(f'adcs_ingestion_publish_events_total{{event_type="{event_type}"}} {count}')
    return lines


def render_ingestion_slis(
    *,
    snapshot_registry: _SnapshotSource | None,
    critical_event_store: _EventSource | None,
    now: datetime | None = None,
) -> str:
    """Render the ingestion-sourced SLI series.

    `ingestion_partial_publish_ratio` is not emitted as a ratio. The numerator
    (partial-publish events) is persisted; the denominator is not — no event is
    written for a clean run, and `index_snapshots` counts snapshots rather than
    publish attempts. Publishing a ratio computed from a proxy denominator would
    look authoritative and be wrong, so both counters are exposed and the
    division is left to whoever knows what window they mean:

        adcs_ingestion_publish_events_total{event_type="partial_publish"}
          / adcs_index_snapshots_total
    """
    moment = now or datetime.now(tz=UTC)
    lines: list[str] = []
    errors = 0

    if snapshot_registry is not None:
        try:
            lines.extend(_freshness_lines(snapshot_registry.list_snapshots(), now=moment))
        except Exception:  # pragma: no cover - defensive; exercised via the error test
            logger.exception("index freshness SLI collection failed")
            errors += 1

    if critical_event_store is not None:
        try:
            lines.extend(_publish_event_lines(critical_event_store.count_events_by_type()))
        except Exception:  # pragma: no cover - defensive; exercised via the error test
            logger.exception("publish-event SLI collection failed")
            errors += 1

    lines.extend(
        [
            "# HELP adcs_ingestion_sli_collection_errors "
            "Collectors that raised during this scrape. Non-zero means the "
            "series above are stale or absent, not that the system is healthy.",
            "# TYPE adcs_ingestion_sli_collection_errors gauge",
            f"adcs_ingestion_sli_collection_errors {errors}",
        ]
    )
    return "\n".join(lines) + "\n"
