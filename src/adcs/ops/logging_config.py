"""Logging bootstrap for the ADCS runtime.

Applies `ADCS_LOG_LEVEL` and a JSON handler to the `adcs` logger tree, so what
reaches stdout does not depend on whichever handler the process host (uvicorn,
celery) happens to install.

The request middleware already emits structured JSON with a `request_id`. This
module makes that reliable rather than incidental, and gives every other `adcs.*`
logger the same shape so a log pipeline sees one format instead of two.
"""

from __future__ import annotations

import json
import logging
import logging.config
from datetime import UTC, datetime
from typing import Any

_ROOT_LOGGER_NAME = "adcs"

# Attributes LogRecord always carries; anything else was attached by the caller
# via `extra=` and is worth forwarding to the log pipeline.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Render one JSON object per record.

    A message that is already a JSON object is merged into the envelope rather
    than nested inside it, so the request middleware's payload keeps its
    top-level `request_id`, `path` and `status` instead of becoming an escaped
    string under `message`.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
        }

        rendered = record.getMessage()
        merged = False
        if rendered.startswith("{") and rendered.endswith("}"):
            try:
                inner = json.loads(rendered)
            except ValueError:
                inner = None
            if isinstance(inner, dict):
                payload.update(inner)
                merged = True
        if not merged:
            payload["message"] = rendered

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["exc_type"] = exc_type.__name__ if exc_type else "Exception"
            # The formatted traceback is deliberately omitted: these records are
            # shipped to a log pipeline, and public error bodies already carry a
            # request_id that ties an incident back to this line.
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(*, level: str = "info") -> None:
    """Apply the JSON handler and the configured level to the `adcs` namespace.

    Only the `adcs` logger tree is touched. Reconfiguring the root logger would
    fight with whatever the process host (uvicorn, celery, pytest) has already
    installed, and the goal here is that our own records are well-formed and
    obey the configured level — not to own the process's logging.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"adcs_json": {"()": f"{__name__}.JsonLogFormatter"}},
            # PII masking (docs/data-protection-and-pii.md) runs on the handler, so
            # it applies to every adcs.* record regardless of which module emitted
            # it — the MCP gateway logs up to 500 characters of raw tool arguments
            # at INFO.
            "filters": {"adcs_pii": {"()": "adcs.ops.privacy.PIIMaskingFilter"}},
            "handlers": {
                "adcs_stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "adcs_json",
                    "filters": ["adcs_pii"],
                    "stream": "ext://sys.stdout",
                }
            },
            "loggers": {
                _ROOT_LOGGER_NAME: {
                    "handlers": ["adcs_stdout"],
                    "level": level.upper(),
                    "propagate": False,
                }
            },
        }
    )
