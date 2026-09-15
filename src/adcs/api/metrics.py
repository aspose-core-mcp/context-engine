"""In-memory Prometheus-style metrics for local observability smoke checks."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

# Cumulative histogram boundaries, in seconds. Chosen around the latency target
# (`api_latency_p95_query_docs <= 1200 ms`) so the SLO sits on a bucket edge and
# p95 can be read straight off the exposition — the _sum/_count pair below
# cannot express a quantile at all.
_LATENCY_BUCKETS_SECONDS: tuple[float, ...] = (
    0.05,
    0.1,
    0.25,
    0.5,
    0.8,
    1.0,
    1.2,
    2.0,
    5.0,
)


def _format_bucket_bound(bound: float) -> str:
    return f"{bound:g}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: dict[str, str]) -> str:
    pairs = ",".join(
        f'{key}="{_escape_label(label_value)}"' for key, label_value in sorted(labels.items())
    )
    return "{" + pairs + "}"


class InMemoryMetrics:
    """Collect baseline request counters and latency metrics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_count: dict[tuple[str, str, int], int] = defaultdict(int)
        self._latency_sum_seconds: dict[tuple[str, str], float] = defaultdict(float)
        self._latency_count: dict[tuple[str, str], int] = defaultdict(int)
        # One counter per bucket boundary plus a trailing +Inf slot.
        self._latency_buckets: dict[tuple[str, str], list[int]] = defaultdict(
            lambda: [0] * (len(_LATENCY_BUCKETS_SECONDS) + 1)
        )
        self._mcp_sessions_by_revision: dict[str, int] = defaultdict(int)
        self._mcp_negotiation_total = 0
        self._mcp_negotiation_fallback_total = 0
        self._mcp_negotiation_fallback_by_revision: dict[tuple[str, str, str], int] = defaultdict(
            int
        )
        self._abuse_guard_decisions_total: dict[tuple[str, str], int] = defaultdict(int)
        # Retrieval-quality SLIs (low-confidence share, missing-citation share).
        # Seeded at zero so "no low-confidence answers" is distinguishable from
        # "nothing is being measured" — an absent series reads as healthy on a
        # dashboard.
        self._retrieval_responses_by_confidence: dict[str, int] = {
            "low": 0,
            "medium": 0,
            "high": 0,
        }
        self._retrieval_results_total = 0
        self._retrieval_results_missing_citation_total = 0
        # SLI semantic_review_failfast_block_count, target 0 for an approved
        # release candidate. Seeded so "no blocks" is distinguishable
        # from "not measured".
        self._semantic_review_failfast_blocks = 0
        # Retrieval component metrics. The stage timings are computed on every
        # query; these aggregate them per stage instead of leaving them in a
        # single INFO log line.
        self._retrieval_stage_sum_seconds: dict[str, float] = defaultdict(float)
        self._retrieval_stage_count: dict[str, int] = defaultdict(int)
        self._retrieval_stage_buckets: dict[str, list[int]] = defaultdict(
            lambda: [0] * (len(_LATENCY_BUCKETS_SECONDS) + 1)
        )

    def observe_retrieval_stage(self, stage: str, seconds: float) -> None:
        """Record the duration of one retrieval pipeline stage."""
        with self._lock:
            self._retrieval_stage_sum_seconds[stage] += seconds
            self._retrieval_stage_count[stage] += 1
            buckets = self._retrieval_stage_buckets[stage]
            for index, bound in enumerate(_LATENCY_BUCKETS_SECONDS):
                if seconds <= bound:
                    buckets[index] += 1
            buckets[-1] += 1

    def observe_semantic_review_failfast(self) -> None:
        """Record one semantic-review run blocked by a fail-fast finding."""
        with self._lock:
            self._semantic_review_failfast_blocks += 1

    def observe_retrieval_response(
        self,
        *,
        confidence_level: str,
        results_total: int,
        results_missing_citation: int,
    ) -> None:
        """Track the confidence and citation SLIs for one retrieval response."""
        level = confidence_level if confidence_level in {"low", "medium", "high"} else "low"
        with self._lock:
            self._retrieval_responses_by_confidence[level] += 1
            self._retrieval_results_total += results_total
            self._retrieval_results_missing_citation_total += results_missing_citation

    def observe_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        """Track request-level metrics."""
        counter_key = (method, path, status_code)
        latency_key = (method, path)

        with self._lock:
            self._request_count[counter_key] += 1
            self._latency_sum_seconds[latency_key] += latency_seconds
            self._latency_count[latency_key] += 1
            buckets = self._latency_buckets[latency_key]
            for index, bound in enumerate(_LATENCY_BUCKETS_SECONDS):
                if latency_seconds <= bound:
                    buckets[index] += 1
            buckets[-1] += 1

    def observe_mcp_negotiation(
        self,
        *,
        requested_revision: str | None,
        negotiated_revision: str,
        fallback_reason: str,
        fallback_applied: bool,
    ) -> None:
        """Track MCP revision negotiation usage and fallback telemetry."""
        normalized_requested = requested_revision or "missing"
        fallback_key = (normalized_requested, negotiated_revision, fallback_reason)

        with self._lock:
            self._mcp_sessions_by_revision[negotiated_revision] += 1
            self._mcp_negotiation_total += 1
            if fallback_applied:
                self._mcp_negotiation_fallback_total += 1
                self._mcp_negotiation_fallback_by_revision[fallback_key] += 1

    def observe_abuse_guard_decision(self, *, mode: str, decision: str) -> None:
        """Track abuse-guard decisions by mode."""
        with self._lock:
            self._abuse_guard_decisions_total[(mode, decision)] += 1

    def observability_snapshot(self) -> dict[str, object]:
        """Expose typed snapshot for admin observability dashboard."""
        with self._lock:
            sessions_by_revision_items = sorted(self._mcp_sessions_by_revision.items())
            negotiation_total = self._mcp_negotiation_total
            fallback_total = self._mcp_negotiation_fallback_total
            fallback_items = sorted(self._mcp_negotiation_fallback_by_revision.items())
            abuse_guard_items = sorted(self._abuse_guard_decisions_total.items())

        fallback_by_reason: dict[str, int] = {}
        for (_, _, fallback_reason), count in fallback_items:
            fallback_by_reason[fallback_reason] = fallback_by_reason.get(fallback_reason, 0) + count

        fallback_breakdown: list[dict[str, object]] = [
            {
                "requested_revision": requested_revision,
                "negotiated_revision": negotiated_revision,
                "fallback_reason": fallback_reason,
                "count": count,
            }
            for (requested_revision, negotiated_revision, fallback_reason), count in fallback_items
        ]

        abuse_guard_breakdown: list[dict[str, object]] = [
            {"mode": mode, "decision": decision, "count": count}
            for (mode, decision), count in abuse_guard_items
        ]
        abuse_guard_by_mode: dict[str, dict[str, int]] = {}
        for (mode, decision), count in abuse_guard_items:
            mode_bucket = abuse_guard_by_mode.setdefault(mode, {})
            mode_bucket[decision] = count

        fail_ratio = (
            float(fallback_total) / float(negotiation_total) if negotiation_total > 0 else 0.0
        )
        return {
            "mcp_negotiation_total": negotiation_total,
            "mcp_negotiation_fallback_total": fallback_total,
            "mcp_negotiation_fail_ratio": fail_ratio,
            "mcp_sessions_by_revision": dict(sessions_by_revision_items),
            "mcp_fallback_by_reason": fallback_by_reason,
            "mcp_fallback_breakdown": fallback_breakdown,
            "abuse_guard_decisions_by_mode": abuse_guard_by_mode,
            "abuse_guard_decisions_breakdown": abuse_guard_breakdown,
        }

    def render_prometheus(self) -> str:
        """Render metrics in Prometheus text exposition format."""
        with self._lock:
            request_count_items = sorted(self._request_count.items())
            latency_sum_items = sorted(self._latency_sum_seconds.items())
            latency_count_items = sorted(self._latency_count.items())
            latency_bucket_items = sorted(
                (key, list(buckets)) for key, buckets in self._latency_buckets.items()
            )
            mcp_sessions_by_revision_items = sorted(self._mcp_sessions_by_revision.items())
            mcp_negotiation_total = self._mcp_negotiation_total
            mcp_negotiation_fallback_total = self._mcp_negotiation_fallback_total
            mcp_negotiation_fallback_items = sorted(
                self._mcp_negotiation_fallback_by_revision.items()
            )
            abuse_guard_decisions_total_items = sorted(self._abuse_guard_decisions_total.items())
            retrieval_by_confidence = dict(self._retrieval_responses_by_confidence)
            retrieval_results_total = self._retrieval_results_total
            retrieval_results_missing = self._retrieval_results_missing_citation_total
            failfast_blocks = self._semantic_review_failfast_blocks
            stage_sum_items = sorted(self._retrieval_stage_sum_seconds.items())
            stage_count_items = sorted(self._retrieval_stage_count.items())
            stage_bucket_items = sorted(
                (stage, list(buckets))
                for stage, buckets in self._retrieval_stage_buckets.items()
            )

        lines = [
            "# HELP adcs_http_requests_total Total HTTP requests processed.",
            "# TYPE adcs_http_requests_total counter",
        ]

        for (method, path, status_code), count in request_count_items:
            labels = _format_labels({"method": method, "path": path, "status": str(status_code)})
            lines.append(f"adcs_http_requests_total{labels} {count}")

        lines.extend(
            [
                "# HELP adcs_http_request_latency_seconds_sum "
                "Total HTTP request latency in seconds.",
                "# TYPE adcs_http_request_latency_seconds_sum counter",
            ]
        )
        for (method, path), total_seconds in latency_sum_items:
            labels = _format_labels({"method": method, "path": path})
            lines.append(f"adcs_http_request_latency_seconds_sum{labels} {total_seconds:.9f}")

        lines.extend(
            [
                "# HELP adcs_http_request_latency_seconds_count Total observed HTTP requests.",
                "# TYPE adcs_http_request_latency_seconds_count counter",
            ]
        )
        for (method, path), count in latency_count_items:
            labels = _format_labels({"method": method, "path": path})
            lines.append(f"adcs_http_request_latency_seconds_count{labels} {count}")

        # A separate family from the _sum/_count counters above: re-typing those
        # as a histogram would declare two TYPEs for one name and break the
        # exposition. Query p95 as
        # histogram_quantile(0.95, rate(adcs_http_request_duration_seconds_bucket[5m])).
        lines.extend(
            [
                "# HELP adcs_http_request_duration_seconds "
                "HTTP request latency distribution in seconds.",
                "# TYPE adcs_http_request_duration_seconds histogram",
            ]
        )
        for (method, path), buckets in latency_bucket_items:
            for index, bound in enumerate(_LATENCY_BUCKETS_SECONDS):
                labels = _format_labels(
                    {"method": method, "path": path, "le": _format_bucket_bound(bound)}
                )
                lines.append(f"adcs_http_request_duration_seconds_bucket{labels} {buckets[index]}")
            inf_labels = _format_labels({"method": method, "path": path, "le": "+Inf"})
            lines.append(
                f"adcs_http_request_duration_seconds_bucket{inf_labels} {buckets[-1]}"
            )
        for (method, path), total_seconds in latency_sum_items:
            labels = _format_labels({"method": method, "path": path})
            lines.append(f"adcs_http_request_duration_seconds_sum{labels} {total_seconds:.9f}")
        for (method, path), count in latency_count_items:
            labels = _format_labels({"method": method, "path": path})
            lines.append(f"adcs_http_request_duration_seconds_count{labels} {count}")

        lines.extend(
            [
                "# HELP mcp_sessions_by_revision Total MCP sessions by negotiated revision.",
                "# TYPE mcp_sessions_by_revision counter",
            ]
        )
        for revision, count in mcp_sessions_by_revision_items:
            labels = _format_labels({"revision": revision})
            lines.append(f"mcp_sessions_by_revision{labels} {count}")

        lines.extend(
            [
                "# HELP mcp_negotiation_total Total MCP revision negotiations.",
                "# TYPE mcp_negotiation_total counter",
                f"mcp_negotiation_total {mcp_negotiation_total}",
                "# HELP mcp_negotiation_fallback_total "
                "Total MCP fallback negotiations by requested/agreed revision.",
                "# TYPE mcp_negotiation_fallback_total counter",
            ]
        )
        for (requested_revision, negotiated_revision, fallback_reason), count in (
            mcp_negotiation_fallback_items
        ):
            labels = _format_labels(
                {
                    "requested_revision": requested_revision,
                    "negotiated_revision": negotiated_revision,
                    "fallback_reason": fallback_reason,
                }
            )
            lines.append(f"mcp_negotiation_fallback_total{labels} {count}")

        fail_ratio = (
            float(mcp_negotiation_fallback_total) / float(mcp_negotiation_total)
            if mcp_negotiation_total > 0
            else 0.0
        )
        lines.extend(
            [
                "# HELP mcp_negotiation_fail_ratio MCP negotiation fallback ratio.",
                "# TYPE mcp_negotiation_fail_ratio gauge",
                f"mcp_negotiation_fail_ratio {fail_ratio:.9f}",
            ]
        )
        lines.extend(
            [
                "# HELP adcs_abuse_guard_decisions_total Total abuse-guard decisions.",
                "# TYPE adcs_abuse_guard_decisions_total counter",
            ]
        )
        for (mode, decision), count in abuse_guard_decisions_total_items:
            labels = _format_labels({"mode": mode, "decision": decision})
            lines.append(f"adcs_abuse_guard_decisions_total{labels} {count}")

        lines.extend(
            [
                "# HELP adcs_retrieval_responses_total Retrieval responses by confidence level.",
                "# TYPE adcs_retrieval_responses_total counter",
            ]
        )
        for level, count in sorted(retrieval_by_confidence.items()):
            labels = _format_labels({"confidence_level": level})
            lines.append(f"adcs_retrieval_responses_total{labels} {count}")

        retrieval_total = sum(retrieval_by_confidence.values())
        low_ratio = (
            retrieval_by_confidence.get("low", 0) / retrieval_total if retrieval_total else 0.0
        )
        missing_ratio = (
            retrieval_results_missing / retrieval_results_total if retrieval_results_total else 0.0
        )
        lines.extend(
            [
                "# HELP adcs_retrieval_confidence_low_ratio "
                "Share of retrieval responses reported as low confidence (SLI).",
                "# TYPE adcs_retrieval_confidence_low_ratio gauge",
                f"adcs_retrieval_confidence_low_ratio {low_ratio:.9f}",
                "# HELP adcs_retrieval_results_total Total retrieval results returned.",
                "# TYPE adcs_retrieval_results_total counter",
                f"adcs_retrieval_results_total {retrieval_results_total}",
                "# HELP adcs_retrieval_results_missing_citation_total "
                "Retrieval results returned without a canonical_url or section_anchor.",
                "# TYPE adcs_retrieval_results_missing_citation_total counter",
                f"adcs_retrieval_results_missing_citation_total {retrieval_results_missing}",
                "# HELP adcs_citation_missing_ratio "
                "Share of retrieval results lacking a citation (SLI).",
                "# TYPE adcs_citation_missing_ratio gauge",
                f"adcs_citation_missing_ratio {missing_ratio:.9f}",
                "# HELP adcs_semantic_review_failfast_block_count "
                "Semantic-review runs blocked by a fail-fast finding (SLI).",
                "# TYPE adcs_semantic_review_failfast_block_count counter",
                f"adcs_semantic_review_failfast_block_count {failfast_blocks}",
            ]
        )

        if stage_count_items:
            lines.extend(
                [
                    "# HELP adcs_retrieval_stage_duration_seconds "
                    "Retrieval pipeline stage duration.",
                    "# TYPE adcs_retrieval_stage_duration_seconds histogram",
                ]
            )
            for stage, buckets in stage_bucket_items:
                for index, bound in enumerate(_LATENCY_BUCKETS_SECONDS):
                    bucket_labels = _format_labels(
                        {"stage": stage, "le": _format_bucket_bound(bound)}
                    )
                    lines.append(
                        f"adcs_retrieval_stage_duration_seconds_bucket{bucket_labels} "
                        f"{buckets[index]}"
                    )
                inf_labels = _format_labels({"stage": stage, "le": "+Inf"})
                lines.append(
                    f"adcs_retrieval_stage_duration_seconds_bucket{inf_labels} {buckets[-1]}"
                )
            for stage, total_seconds in stage_sum_items:
                labels = _format_labels({"stage": stage})
                lines.append(
                    f"adcs_retrieval_stage_duration_seconds_sum{labels} {total_seconds:.9f}"
                )
            for stage, count in stage_count_items:
                labels = _format_labels({"stage": stage})
                lines.append(f"adcs_retrieval_stage_duration_seconds_count{labels} {count}")

        return "\n".join(lines) + "\n"
