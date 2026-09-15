from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adcs.api import readiness
from adcs.api.main import create_app
from adcs.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_healthz_returns_process_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_200_when_all_dependencies_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    def _all_ready(*_args: object, **_kwargs: object) -> readiness.DependencyResults:
        return {
            "postgres": (True, "reachable"),
            "redis": (True, "reachable"),
            "qdrant": (True, "reachable"),
            "opensearch": (True, "reachable"),
        }

    monkeypatch.setattr(readiness, "check_dependencies", _all_ready)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["postgres"] == {"status": "ready", "reason": "reachable"}
    assert body["dependencies"]["redis"] == {"status": "ready", "reason": "reachable"}
    assert body["dependencies"]["qdrant"] == {"status": "ready", "reason": "reachable"}
    assert body["dependencies"]["opensearch"] == {"status": "ready", "reason": "reachable"}


def test_readyz_returns_503_when_dependency_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    def _qdrant_down(*_args: object, **_kwargs: object) -> readiness.DependencyResults:
        return {
            "postgres": (True, "reachable"),
            "redis": (True, "reachable"),
            "qdrant": (False, "connection refused"),
            "opensearch": (True, "reachable"),
        }

    monkeypatch.setattr(readiness, "check_dependencies", _qdrant_down)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["qdrant"] == {
        "status": "not_ready",
        "reason": "connection refused",
    }


def test_readyz_marks_dependencies_not_required_for_memory_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_PERSISTENCE_BACKEND", "memory")
    monkeypatch.setenv("ADCS_RETRIEVAL_BACKEND", "memory")
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    for dependency in ("postgres", "redis", "qdrant", "opensearch"):
        assert body["dependencies"][dependency] == {
            "status": "ready",
            "reason": "not_required_for_current_runtime",
        }


def test_request_id_is_propagated_and_generated() -> None:
    app = create_app()
    with TestClient(app) as client:
        response_with_incoming = client.get("/", headers={"X-Request-ID": "req-123"})
        response_without_incoming = client.get("/healthz")

    assert response_with_incoming.status_code == 200
    assert response_with_incoming.headers["X-Request-ID"] == "req-123"
    assert response_with_incoming.headers["X-Trace-ID"] == "req-123"
    assert response_without_incoming.status_code == 200
    assert response_without_incoming.headers["X-Request-ID"]
    assert response_without_incoming.headers["X-Trace-ID"]


def test_metrics_endpoint_exposes_baseline_metrics() -> None:
    app = create_app()
    with TestClient(app) as client:
        client.get("/")
        client.get("/healthz")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "adcs_http_requests_total" in response.text
    assert 'adcs_http_requests_total{method="GET",path="/",status="200"}' in response.text
    assert 'adcs_http_requests_total{method="GET",path="/healthz",status="200"}' in response.text
    assert "adcs_http_request_latency_seconds_sum" in response.text
    assert "adcs_http_request_latency_seconds_count" in response.text


def test_metrics_endpoint_exposes_latency_histogram_buckets() -> None:
    """p95 must be derivable from /metrics — the latency SLO is stated as a p95.

    `_sum`/`_count` alone cannot express a quantile, so without histogram
    buckets the headline latency SLO is unverifiable in a deployment.
    """
    app = create_app()
    with TestClient(app) as client:
        client.get("/healthz")
        response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "# TYPE adcs_http_request_duration_seconds histogram" in body
    # The SLO boundary itself must be a bucket edge, or p95 vs 1200 ms is an
    # interpolation rather than a measurement.
    assert 'adcs_http_request_duration_seconds_bucket{le="1.2"' in body
    assert 'adcs_http_request_duration_seconds_bucket{le="+Inf"' in body
    assert "adcs_http_request_duration_seconds_count" in body

    bucket_lines = [
        line
        for line in body.splitlines()
        if line.startswith("adcs_http_request_duration_seconds_bucket")
        and 'path="/healthz"' in line
    ]
    values = [int(line.rsplit(" ", 1)[1]) for line in bucket_lines]
    assert values == sorted(values), "histogram buckets must be cumulative"
    assert values[-1] >= 1


def test_metrics_expose_confidence_and_citation_slis() -> None:
    """The confidence and citation SLIs are exported as metrics.

    `retrieval_confidence_low_ratio` and `citation_missing_ratio` are headline
    SLIs; without a metric the release gate could only obtain them by running a
    script by hand in a deployment. The series are seeded at zero so "measured
    and healthy" is distinguishable from "not measured at all".
    """
    app = create_app()
    with TestClient(app) as client:
        before = client.get("/metrics").text
        # Seeded before any traffic — an absent series reads as healthy.
        assert 'adcs_retrieval_responses_total{confidence_level="low"} 0' in before
        assert "adcs_retrieval_confidence_low_ratio 0.000000000" in before
        assert "adcs_citation_missing_ratio 0.000000000" in before

        client.post(
            "/v1/docs:query",
            json={
                "query": "How to use RecognizeImage?",
                "product_id": "aspose.ocr",
                "language": "net",
                "query_locale": "en",
                "top_k": 2,
            },
        )
        after = client.get("/metrics").text

    served = {
        level: int(line.rsplit(" ", 1)[1])
        for level in ("low", "medium", "high")
        for line in after.splitlines()
        if line.startswith(f'adcs_retrieval_responses_total{{confidence_level="{level}"}}')
    }
    assert sum(served.values()) == 1, f"exactly one response should be counted: {served}"
    assert "# TYPE adcs_retrieval_confidence_low_ratio gauge" in after
    assert "# TYPE adcs_citation_missing_ratio gauge" in after


def test_configure_logging_applies_the_configured_level() -> None:
    """ADCS_LOG_LEVEL is applied, not just parsed and reported."""
    import logging

    from adcs.ops.logging_config import JsonLogFormatter, configure_logging

    configure_logging(level="warning")
    adcs_logger = logging.getLogger("adcs")
    assert adcs_logger.level == logging.WARNING
    assert adcs_logger.handlers, "the adcs logger must own a handler"
    assert isinstance(adcs_logger.handlers[0].formatter, JsonLogFormatter)

    configure_logging(level="debug")
    assert logging.getLogger("adcs").level == logging.DEBUG


def test_json_log_formatter_merges_prerendered_payloads() -> None:
    """The request middleware already emits JSON; it must stay flat, not nested."""
    import json as json_module
    import logging

    from adcs.ops.logging_config import JsonLogFormatter

    formatter = JsonLogFormatter()
    payload = {"event": "request_finish", "request_id": "r-1", "status": 200}
    record = logging.LogRecord(
        name="adcs.api.requests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=json_module.dumps(payload),
        args=(),
        exc_info=None,
    )
    rendered = json_module.loads(formatter.format(record))
    assert rendered["request_id"] == "r-1", "request_id must stay queryable at the top level"
    assert rendered["status"] == 200
    assert "message" not in rendered

    plain = logging.LogRecord(
        name="adcs.demo",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="plain text",
        args=(),
        exc_info=None,
    )
    plain.product_id = "aspose.ocr"
    rendered_plain = json_module.loads(formatter.format(plain))
    assert rendered_plain["message"] == "plain text"
    assert rendered_plain["product_id"] == "aspose.ocr"


def test_the_three_metric_sources_declare_disjoint_families() -> None:
    """/metrics concatenates all three sources, so a shared name breaks the scrape.

    `adcs_http_requests_total` and `adcs_http_request_duration_seconds` were
    declared in src/adcs/ops/metrics.py *and* src/adcs/api/metrics.py. The former
    emits nothing while prometheus_client is absent, so the collision was
    invisible — installing the dependency, which is the obvious way to "fix"
    telemetry, would have emitted two `# TYPE` lines for one family and taken
    /metrics from partial to rejected-by-Prometheus.

    This check is static so it holds whether or not the optional dependency is
    installed in the environment running the tests.
    """
    import re
    from pathlib import Path

    from adcs.api.metrics import InMemoryMetrics

    ops_source = Path(__file__).resolve().parents[1] / "src" / "adcs" / "ops" / "metrics.py"
    ops_families = set(re.findall(r'"((?:adcs|mcp)_[a-z_]+)"', ops_source.read_text()))

    registry = InMemoryMetrics()
    registry.observe_request(
        method="GET", path="/healthz", status_code=200, latency_seconds=0.1
    )
    registry.observe_mcp_negotiation(
        requested_revision="2025-11-25",
        negotiated_revision="2025-11-25",
        fallback_reason="none",
        fallback_applied=False,
    )
    stdlib_families = {
        line.split()[2]
        for line in registry.render_prometheus().splitlines()
        if line.startswith("# TYPE ")
    }

    # Third source, added with the ingestion SLIs: derived from Postgres at
    # scrape time rather than accumulated in a registry.
    from adcs.api.ingestion_slis import render_ingestion_slis
    from adcs.ops.critical_events import InMemoryCriticalEventStore

    ingestion_families = {
        line.split()[2]
        for line in render_ingestion_slis(
            snapshot_registry=None, critical_event_store=InMemoryCriticalEventStore()
        ).splitlines()
        if line.startswith("# TYPE ")
    }

    sources = {
        "ops/metrics.py": ops_families,
        "api/metrics.py": stdlib_families,
        "api/ingestion_slis.py": ingestion_families,
    }
    for left, right in (
        ("ops/metrics.py", "api/metrics.py"),
        ("ops/metrics.py", "api/ingestion_slis.py"),
        ("api/metrics.py", "api/ingestion_slis.py"),
    ):
        overlap = sources[left] & sources[right]
        assert not overlap, (
            f"{left} and {right} declare these families and /metrics concatenates "
            f"them, so the scrape would carry duplicate TYPE lines: {sorted(overlap)}"
        )
