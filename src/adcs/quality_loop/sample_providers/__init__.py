"""Sample providers for the quality-loop Coordinator.

A sample provider is any ``Callable[[], tuple[QueryResponseSample, ...]]``.
The CI-smoke default is the synthetic provider in
``scripts/quality_loop/run_cycle.py``; production deployments swap in
:class:`StructuredLogSampleProvider`, which reads a tail of recorded
``query_docs`` responses from a structured JSONL log.
"""

from adcs.quality_loop.sample_providers.structured_log_provider import (
    LOG_TAIL_ENV_VAR,
    StructuredLogSampleProvider,
)

__all__ = [
    "LOG_TAIL_ENV_VAR",
    "StructuredLogSampleProvider",
]
