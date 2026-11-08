"""Optional tracing bootstrap with OpenTelemetry-compatible settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adcs.config import Settings


@dataclass(slots=True)
class RequestSpanContext:
    """Context manager wrapper that exposes the active trace id when available."""

    _context_manager: Any | None
    _span: Any | None
    trace_id: str | None = None

    def __enter__(self) -> Any:
        return self._span

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._context_manager is None or self._span is None:
            return
        if exc is not None:
            self._span.record_exception(exc)
            self._span.set_attribute("error", True)
        self._context_manager.__exit__(exc_type, exc, tb)


@dataclass(frozen=True, slots=True)
class TracingService:
    """Lightweight wrapper around optional OpenTelemetry request spans."""

    enabled: bool
    service_name: str
    sample_ratio: float
    error_sample_ratio: float
    slow_request_threshold_ms: int
    otlp_endpoint: str | None = None
    backend: str = "disabled"
    _tracer: Any | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> TracingService:
        if not settings.tracing_enabled:
            return cls(
                enabled=False,
                service_name=settings.tracing_service_name,
                sample_ratio=settings.tracing_sample_ratio,
                error_sample_ratio=settings.tracing_error_sample_ratio,
                slow_request_threshold_ms=settings.tracing_slow_request_threshold_ms,
                otlp_endpoint=settings.tracing_otlp_endpoint,
                backend="disabled",
            )

        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        except ImportError:
            return cls(
                enabled=False,
                service_name=settings.tracing_service_name,
                sample_ratio=settings.tracing_sample_ratio,
                error_sample_ratio=settings.tracing_error_sample_ratio,
                slow_request_threshold_ms=settings.tracing_slow_request_threshold_ms,
                otlp_endpoint=settings.tracing_otlp_endpoint,
                backend="missing_dependency",
            )

        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.tracing_service_name}),
            sampler=TraceIdRatioBased(settings.tracing_sample_ratio),
        )
        if settings.tracing_otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.tracing_otlp_endpoint)
                )
            )
            backend = "otlp_http"
        else:
            backend = "otel_no_exporter"
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer(settings.tracing_service_name)
        return cls(
            enabled=True,
            service_name=settings.tracing_service_name,
            sample_ratio=settings.tracing_sample_ratio,
            error_sample_ratio=settings.tracing_error_sample_ratio,
            slow_request_threshold_ms=settings.tracing_slow_request_threshold_ms,
            otlp_endpoint=settings.tracing_otlp_endpoint,
            backend=backend,
            _tracer=tracer,
        )

    def start_request_span(
        self,
        *,
        name: str,
        attributes: dict[str, Any],
    ) -> RequestSpanContext:
        """Start one request span or return a no-op context manager."""
        if not self.enabled or self._tracer is None:
            return RequestSpanContext(_context_manager=None, _span=None, trace_id=None)
        context_manager = self._tracer.start_as_current_span(name)
        span = context_manager.__enter__()
        for key, value in attributes.items():
            span.set_attribute(key, value)
        span_context = span.get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.trace_id else None
        return RequestSpanContext(
            _context_manager=context_manager,
            _span=span,
            trace_id=trace_id,
        )
