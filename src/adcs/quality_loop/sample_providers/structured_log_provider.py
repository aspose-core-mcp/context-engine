"""Production sample provider: read a structured query-response log tail.

The quality loop's default ``synthetic_provider`` emits a fixed,
deterministic batch — fine for CI smoke and the first-run baseline, but
it never reflects real traffic. This provider closes that gap: it reads
the tail of a structured JSONL log of recorded ``query_docs`` responses
and maps each line into a :class:`QueryResponseSample` the Coordinator
can score.

It is the Phase 2 production sample source referenced in
``docs/quality-loop.md`` — deliberately **read-only and out of band**.
It never intercepts a live request; it reads an already-written log
after the fact, so a failure here can never affect serving.

Log contract (one JSON object per line; unknown keys ignored)::

    {
      "query": "how to OCR a PDF in C#",        # or "raw_query"
      "product_id": "aspose.ocr",
      "programming_language": "net",
      "requested_version": "25.1",               # or "version"; optional
      "strict_version": true,                    # optional, default false
      "candidates": [                            # optional, default []
        {"canonical_url": "...", "version": "25.1",
         "chunk_id": "...", "symbol_fqn": "..."}
      ],
      "confidence_score": 0.85,                  # or "confidence"; optional
      "captured_at": "2026-06-02T00:00:00Z",     # optional; default now
      "prompt_pack_version": "v-stable"          # optional
    }

Robustness mirrors the audit-log replay utility: a missing file yields
an empty batch, malformed lines are skipped, and a line missing the
minimum identifying fields (query + product_id + programming_language)
is dropped rather than producing a degenerate sample. Only the most
recent ``max_samples`` valid records are returned, newest last.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from adcs.quality_loop.judge_agent import QueryResponseSample, make_sample_id
from adcs.quality_loop.models import utc_iso

#: Environment variable naming the JSONL log the provider tails.
LOG_TAIL_ENV_VAR = "QUALITY_LOOP_LOG_TAIL_PATH"
DEFAULT_MAX_SAMPLES = 50


@dataclass
class StructuredLogSampleProvider:
    """Callable sample provider over a structured query-response log.

    Satisfies the Coordinator's ``SampleProvider`` type
    (``Callable[[], tuple[QueryResponseSample, ...]]``) via ``__call__``.
    """

    log_path: Path
    max_samples: int = DEFAULT_MAX_SAMPLES

    def __post_init__(self) -> None:
        if self.max_samples < 1:
            msg = "max_samples must be >= 1"
            raise ValueError(msg)

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        max_samples: int = DEFAULT_MAX_SAMPLES,
    ) -> StructuredLogSampleProvider | None:
        """Build from ``QUALITY_LOOP_LOG_TAIL_PATH``; None when unset.

        Returning None lets the caller fall back to the synthetic
        provider without special-casing — a deployment that has not yet
        wired a production log simply keeps the CI-smoke behaviour.
        """
        source = env if env is not None else os.environ
        raw_path = source.get(LOG_TAIL_ENV_VAR)
        if not raw_path or not raw_path.strip():
            return None
        return cls(log_path=Path(raw_path.strip()), max_samples=max_samples)

    def __call__(self) -> tuple[QueryResponseSample, ...]:
        records = self._read_tail_records()
        samples: list[QueryResponseSample] = []
        for record in records:
            sample = _record_to_sample(record)
            if sample is not None:
                samples.append(sample)
        return tuple(samples)

    def _read_tail_records(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        valid: list[dict] = []
        for raw_line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                valid.append(payload)
        # Newest-last: keep the final max_samples records.
        return valid[-self.max_samples :]


def _coerce_candidates(value: object) -> tuple[dict, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _coerce_confidence(value: object) -> float | None:
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _record_to_sample(record: dict) -> QueryResponseSample | None:
    """Map one log record to a sample, or None when unusable.

    The minimum identifying fields are ``query`` (or ``raw_query``),
    ``product_id`` and ``programming_language``. A record missing any of
    them cannot be scored meaningfully and is dropped.
    """
    query = record.get("query") or record.get("raw_query")
    product_id = record.get("product_id")
    programming_language = record.get("programming_language")
    if not (
        isinstance(query, str)
        and query.strip()
        and isinstance(product_id, str)
        and product_id.strip()
        and isinstance(programming_language, str)
        and programming_language.strip()
    ):
        return None

    requested_version = record.get("requested_version")
    if requested_version is None:
        requested_version = record.get("version")
    if requested_version is not None and not isinstance(requested_version, str):
        requested_version = str(requested_version)

    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        sample_id = make_sample_id()

    captured_at = record.get("captured_at") or record.get("emitted_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        captured_at = utc_iso()

    prompt_pack_version = record.get("prompt_pack_version")
    if prompt_pack_version is not None and not isinstance(prompt_pack_version, str):
        prompt_pack_version = str(prompt_pack_version)

    confidence = _coerce_confidence(
        record.get("confidence_score", record.get("confidence"))
    )

    return QueryResponseSample(
        sample_id=sample_id,
        captured_at=captured_at,
        product_id=product_id,
        programming_language=programming_language,
        requested_version=requested_version,
        strict_version=bool(record.get("strict_version", False)),
        query=query,
        candidates=_coerce_candidates(record.get("candidates")),
        confidence_score=confidence,
        prompt_pack_version=prompt_pack_version,
    )
