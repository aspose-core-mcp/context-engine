"""The one vocabulary of public error codes.

Before this module the codes were string literals scattered across three
gateways, and they had drifted in three separate ways:

* ``SERVICE_UNAVAILABLE`` was emitted everywhere the documented contract says
  ``DEPENDENCY_UNAVAILABLE``; the documented code appeared in no error path at
  all.
* ``THROTTLED`` and ``RATE_LIMITED`` both existed for one condition —
  ``_streamable_error_code`` already had to treat them as synonyms.
* A backend timeout produced ``TIMEOUT`` through the MCP gateway and
  ``SERVICE_UNAVAILABLE`` through REST. Identical failure, different code,
  depending on which transport the caller happened to use — the exact class of
  divergence the parity rule exists to prevent.

Codes are public contract: removing or renaming one is a major-version change.
The rename to ``DEPENDENCY_UNAVAILABLE`` was safe precisely because no published
document ever named the code it replaced.

`tests/test_error_code_vocabulary.py` fails when a new literal shows up in an
error path without a definition here.
"""

from __future__ import annotations

from typing import Final

#: Request could not be understood or failed schema validation.
INVALID_ARGUMENT: Final = "INVALID_ARGUMENT"
#: The addressed resource (product, symbol, session) does not exist.
NOT_FOUND: Final = "NOT_FOUND"
#: Credentials absent or unrecognised.
UNAUTHORIZED: Final = "UNAUTHORIZED"
#: Credentials valid but not scoped to this operation.
FORBIDDEN: Final = "FORBIDDEN"
#: Abuse-guard threshold exceeded in `enforce` mode.
RATE_LIMITED: Final = "RATE_LIMITED"
#: A backend (Qdrant, OpenSearch, Postgres, embedding service) is unreachable.
DEPENDENCY_UNAVAILABLE: Final = "DEPENDENCY_UNAVAILABLE"
#: A backend was reachable but did not answer in time. Distinct from the above
#: because it is retriable on a different timescale and points at load rather
#: than at an outage.
TIMEOUT: Final = "TIMEOUT"
#: Unhandled server-side failure.
INTERNAL: Final = "INTERNAL"

#: Every code the public surface may emit. Both transports draw from this set.
PUBLIC_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        INVALID_ARGUMENT,
        NOT_FOUND,
        UNAUTHORIZED,
        FORBIDDEN,
        RATE_LIMITED,
        DEPENDENCY_UNAVAILABLE,
        TIMEOUT,
        INTERNAL,
    }
)

#: Codes the optional WebMCP browser adapter adds on top. They are a
#: declared superset, not drift: the confirmation handshake and idempotency
#: replay have no analogue on the MCP/REST surface, so collapsing them into the
#: list above would lose the only information the caller can act on.
#:
#: ``VALIDATION_ERROR`` *is* a plain synonym of ``INVALID_ARGUMENT`` and should
#: not have been minted. It is left alone deliberately: the adapter is
#: feature-flagged off by default, and the code is persisted in stored WebMCP
#: audit records, so renaming it would rewrite the meaning of history to fix a
#: name nobody currently reads.
WEBMCP_ADAPTER_CODES: Final[frozenset[str]] = frozenset(
    {
        "VALIDATION_ERROR",
        "CONFIRMATION_REQUIRED",
        "CONFIRMATION_EXPIRED",
        "CONFIRMATION_INVALID",
        "CONFIRMATION_MISMATCH",
        "CONFIRMATION_REPLAYED",
        "IDEMPOTENCY_CONFLICT",
    }
)

#: The HTTP status each code is served with. Kept here rather than at the raise
#: site so REST and MCP cannot answer the same condition with different statuses.
HTTP_STATUS_BY_CODE: Final[dict[str, int]] = {
    INVALID_ARGUMENT: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    RATE_LIMITED: 429,
    INTERNAL: 500,
    DEPENDENCY_UNAVAILABLE: 503,
    TIMEOUT: 503,
}
