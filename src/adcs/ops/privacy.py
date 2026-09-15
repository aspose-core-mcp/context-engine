"""Keyed hashing and PII masking for logs and analytics.

Implements the controls described in `docs/data-protection-and-pii.md`:
`ip_hash` and `query_fingerprint` are HMAC-SHA256 pseudonyms, and a masking
filter runs on every `adcs.*` log record.

An unsalted SHA-256 of an IPv4 address is not a pseudonym. The keyspace is 2³²,
so the whole table can be enumerated in seconds — the stored value is a
reversible encoding of the address, which is exactly what a keyed hash
prevents.

The key comes from `ADCS_HASH_SECRET`. When it is unset the module falls back to
unkeyed hashing and says so once, loudly, rather than refusing to start: an
absent secret must not take an environment down, but it must not pass silently
either.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re

logger = logging.getLogger(__name__)

# Bump when the pattern set changes so replayed events record which rules ran.
PII_RULES_VERSION = "2026-07-30.1"

_UNKEYED_WARNING_EMITTED = False


def _resolve_secret() -> str | None:
    # Imported lazily: this module is used by logging paths that must not depend
    # on settings construction succeeding.
    import os

    secret = os.environ.get("ADCS_HASH_SECRET", "").strip()
    return secret or None


def keyed_hash(value: str, *, purpose: str) -> str:
    """Return an HMAC-SHA256 pseudonym for `value`.

    `purpose` is mixed into the key so an `ip_hash` and a `query_fingerprint` of
    the same string do not collide, which would otherwise let one be used to
    confirm the other.
    """
    secret = _resolve_secret()
    if secret is None:
        global _UNKEYED_WARNING_EMITTED
        if not _UNKEYED_WARNING_EMITTED:
            _UNKEYED_WARNING_EMITTED = True
            logger.warning(
                "ADCS_HASH_SECRET is not set: %s values fall back to unkeyed SHA-256, "
                "which is reversible for small keyspaces such as IPv4",
                purpose,
            )
        return hashlib.sha256(f"{purpose}:{value}".encode()).hexdigest()
    return hmac.new(
        f"{secret}:{purpose}".encode(),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# --------------------------------------------------------------------------- #
# PII masking rule pack — the seven baseline classes listed in
# docs/data-protection-and-pii.md
# --------------------------------------------------------------------------- #

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
# E.164 and common separated forms. A bare digit run is NOT a phone number: a
# looser pattern would mask `snap-00000042` as one and make operational logs
# unreadable — snapshot and chunk ids appear in nearly every line. So a match
# needs either a leading `+` or at least three separator-delimited groups.
_PHONE = re.compile(
    r"(?<![\w.\-])"
    r"(?:\+\d[\d\s().\-]{6,}\d|\(?\d{1,4}\)?(?:[\s().\-]+\d{2,4}){2,})"
    r"(?![\w.\-])"
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b")
_API_KEY = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b"
    r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
# IBAN, and card-shaped digit runs (13-19 digits, optionally grouped).
_BANK = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"
    r"|\b(?:\d[ -]?){12,18}\d\b"
)
_CREDENTIAL_QUERY_PARAM = re.compile(
    r"\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|auth)=([^&\s\"']+)",
    re.IGNORECASE,
)

# Order matters: JWT and API keys are matched before the generic bank/phone
# digit runs, which would otherwise claim parts of them.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_EMAIL, "[email-redacted]"),
    (_JWT, "[jwt-redacted]"),
    (_API_KEY, "[apikey-redacted]"),
    (_IPV6, "[ip-redacted]"),
    (_IPV4, "[ip-redacted]"),
    (_BANK, "[bank-redacted]"),
    (_PHONE, "[phone-redacted]"),
)


def mask_pii(text: str) -> str:
    """Replace the baseline PII patterns with stable placeholders."""
    if not text:
        return text
    masked = _CREDENTIAL_QUERY_PARAM.sub(r"\1=[param-redacted]", text)
    for pattern, replacement in _RULES:
        masked = pattern.sub(replacement, masked)
    return masked


class PIIMaskingFilter(logging.Filter):
    """Logging filter that masks record messages and string args.

    Attached to the `adcs` logger tree so nothing reaches a log pipeline
    unmasked. The MCP gateway, for one, logs up to 500 characters of raw tool
    arguments at INFO.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: mask_pii(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    mask_pii(value) if isinstance(value, str) else value
                    for value in record.args
                )
        return True
