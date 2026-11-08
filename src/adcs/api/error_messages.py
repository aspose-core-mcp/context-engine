"""Sanitisation for exception text that reaches public error bodies.

The public REST and MCP surfaces interpolate ``str(exc)`` into response bodies
on many code paths, several of them unauthenticated. Deliberate service-layer
messages ("product not found") are useful to a caller; incidental ones are not —
a SQLAlchemy driver error carries the DSN, and a Pydantic error carries the
server's source path and line number.

The rule here: the caller sees the exception text only when it looks like a
message written for a caller. Anything else is replaced with a stable fallback,
and the real text is always logged server-side against the request id so
operators lose nothing.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Markers that make a message internal regardless of anything else.
_INTERNAL_MARKERS: tuple[str, ...] = (
    "traceback",
    "errors.pydantic.dev",
    "sqlalchemy",
    "psycopg",
    "asyncpg",
    "urllib3",
    "site-packages",
    "/app/src/",
    "object at 0x",
    "connection refused",
    "postgresql://",
    "postgresql+",
    "amqp://",
    "redis://",
    "http://localhost",
    "https://localhost",
)

# A filesystem path with a file extension, e.g. `/app/src/adcs/api/x.py` or
# `C:\svc\x.py`. Bare URLs in a message are fine; source paths are not.
_PATH_PATTERN = re.compile(r"(?:/[\w.\-]+){2,}\.\w{1,5}\b|[A-Za-z]:\\[\\\w.\-]+")

# Anything longer than this is a dump rather than a message.
_MAX_PUBLIC_MESSAGE_LENGTH = 300


def is_public_safe(message: str) -> bool:
    """Return True when `message` can be shown to an unauthenticated caller."""
    if not message or not message.strip():
        return False
    if len(message) > _MAX_PUBLIC_MESSAGE_LENGTH:
        return False
    if "\n" in message:
        # Multi-line text is a stack, a repr or a validation dump — never a
        # sentence written for the caller.
        return False
    lowered = message.casefold()
    if any(marker in lowered for marker in _INTERNAL_MARKERS):
        return False
    return not _PATH_PATTERN.search(message)


def public_error_message(
    exc: BaseException,
    *,
    fallback: str,
    request_id: str | None = None,
    context: str = "",
) -> str:
    """Return caller-safe text for `exc`, falling back when it looks internal.

    The unredacted text is logged either way, so choosing the fallback hides the
    detail from the caller without hiding it from whoever is debugging.
    """
    raw = str(exc)
    if is_public_safe(raw):
        return raw
    logger.warning(
        "suppressed internal error detail in public response "
        "(request_id=%s context=%s type=%s): %s",
        request_id,
        context or "-",
        type(exc).__name__,
        raw,
    )
    return fallback
