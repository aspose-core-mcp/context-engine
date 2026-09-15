"""Keyed hashing and PII masking.

These tests back the two controls described in
`docs/data-protection-and-pii.md`. They are deliberately split between "does
it mask" and "does it avoid masking things that matter", because an over-eager
rule pack destroys the usefulness of logs just as effectively as a missing one
hides a leak.
"""

from __future__ import annotations

import logging

import pytest

from adcs.ops.privacy import PII_RULES_VERSION, PIIMaskingFilter, keyed_hash, mask_pii


@pytest.mark.parametrize(
    ("raw", "expected_marker"),
    [
        ("contact user@example.com for help", "[email-redacted]"),
        ("call +1 415 555 0198 now", "[phone-redacted]"),
        ("client 192.168.1.10 connected", "[ip-redacted]"),
        ("v6 2001:0db8:85a3:0000:0000:8a2e:0370:7334 seen", "[ip-redacted]"),
        ("auth eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123XYZ", "[jwt-redacted]"),
        ("key sk-abcdef0123456789 leaked", "[apikey-redacted]"),
        ("Bearer abcdef0123456789xyz", "[apikey-redacted]"),
        ("iban DE89370400440532013000 payment", "[bank-redacted]"),
        ("card 4111 1111 1111 1111 charged", "[bank-redacted]"),
        ("GET /x?password=hunter2", "[param-redacted]"),
    ],
)
def test_all_seven_baseline_classes_are_masked(raw: str, expected_marker: str) -> None:
    masked = mask_pii(raw)
    assert expected_marker in masked
    # The sensitive substring itself must be gone, not merely annotated.
    for secret in ("user@example.com", "192.168.1.10", "hunter2", "sk-abcdef0123456789"):
        if secret in raw:
            assert secret not in masked


@pytest.mark.parametrize(
    "raw",
    [
        "Aspose.OCR 25.1 RecognizeImage returns 8 results",
        "snapshot snap-00000042 promoted in 1200 ms",
        "order 12345 shipped",
        "product aspose.words language net version 24.12",
        "chunk-000123 indexed, latency 1200 ms",
        "top_k 8 version 25.1",
    ],
)
def test_technical_log_lines_survive_masking(raw: str) -> None:
    """Over-masking is its own failure: unreadable logs stop being used."""
    assert mask_pii(raw) == raw


def test_keyed_hash_is_stable_and_separated_by_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADCS_HASH_SECRET", "unit-test-secret")

    assert keyed_hash("192.168.0.1", purpose="ip_hash") == keyed_hash(
        "192.168.0.1", purpose="ip_hash"
    )
    # Same input under two purposes must not collide, or one pseudonym could be
    # used to confirm the other.
    assert keyed_hash("192.168.0.1", purpose="ip_hash") != keyed_hash(
        "192.168.0.1", purpose="query_fingerprint"
    )


def test_the_key_actually_changes_the_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this, the 'keyed' hash would be keyed in name only.

    An unsalted SHA-256 of an IPv4 address covers a 2**32 keyspace and is
    enumerable in seconds, which is what keyed hashing exists to prevent.
    """
    import hashlib

    monkeypatch.setenv("ADCS_HASH_SECRET", "secret-one")
    first = keyed_hash("192.168.0.1", purpose="ip_hash")
    monkeypatch.setenv("ADCS_HASH_SECRET", "secret-two")
    second = keyed_hash("192.168.0.1", purpose="ip_hash")

    assert first != second, "changing the key must change the digest"
    plain = hashlib.sha256(b"192.168.0.1").hexdigest()
    assert first != plain, "a keyed digest must not equal the bare SHA-256"


def test_missing_secret_warns_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An absent secret must not take an environment down, nor pass in silence."""
    monkeypatch.delenv("ADCS_HASH_SECRET", raising=False)
    monkeypatch.setattr("adcs.ops.privacy._UNKEYED_WARNING_EMITTED", False)
    # create_app() elsewhere in the suite runs configure_logging(), which stops the
    # `adcs` logger tree from propagating to the root logger that caplog listens on.
    monkeypatch.setattr(logging.getLogger("adcs"), "propagate", True)

    with caplog.at_level(logging.WARNING, logger="adcs.ops.privacy"):
        digest = keyed_hash("192.168.0.1", purpose="ip_hash")

    assert digest, "hashing must still work without a key"
    assert any("ADCS_HASH_SECRET" in record.message for record in caplog.records)


def test_logging_filter_masks_message_and_args() -> None:
    """The filter sits on the handler, so it covers every adcs.* record."""
    filt = PIIMaskingFilter()
    record = logging.LogRecord(
        name="adcs.api.mcp",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="tool arguments: %s",
        args=("email=user@example.com ip=192.168.1.10",),
        exc_info=None,
    )
    assert filt.filter(record) is True
    rendered = record.getMessage()
    assert "user@example.com" not in rendered
    assert "192.168.1.10" not in rendered
    assert "[email-redacted]" in rendered


def test_rule_pack_is_versioned() -> None:
    """Replayed events need to record which rules were active."""
    assert PII_RULES_VERSION
    assert PII_RULES_VERSION[0].isdigit()
