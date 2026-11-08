"""Property-based tests for translation_fallback's pure helpers.

Asserts the heuristic locale detector and the locale normaliser obey
the structural invariants the rest of the retrieval pipeline assumes:

* `_heuristic_detect_locale` returns "en" for ASCII queries and
  "unknown" for non-ASCII;
* `_normalize_locale` is idempotent for already-normalised inputs;
* `_normalize_locale` maps None / blank / whitespace-only to None;
* `_normalize_locale` collapses underscore-separated locales to
  hyphen-separated, then strips the country suffix (en-US → en).
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.translation_fallback import (
    _heuristic_detect_locale,
    _normalize_locale,
)

_ascii_text = st.text(
    alphabet=st.characters(min_codepoint=0, max_codepoint=127),
    max_size=80,
).filter(lambda s: s.isascii())

_unicode_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), min_codepoint=0x80, max_codepoint=0x4FFF
    ),
    min_size=1,
    max_size=40,
)

_locale_well_formed = st.from_regex(r"[a-z]{2}(-[a-z]{2}|_[a-z]{2})?", fullmatch=True)
_locale_messy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=20,
)


@given(query=_ascii_text)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_heuristic_detect_locale_returns_en_for_ascii(query: str) -> None:
    """Any pure-ASCII string (including empty) is classified as English."""
    assert _heuristic_detect_locale(query) == "en"


@given(query=_unicode_text)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_heuristic_detect_locale_returns_unknown_for_non_ascii(query: str) -> None:
    """Any string containing a non-ASCII codepoint is classified as unknown."""
    assert _heuristic_detect_locale(query) == "unknown"


@given(locale=_locale_well_formed)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalize_locale_is_idempotent_on_well_formed_input(locale: str) -> None:
    """Normalising an already-normalised locale must return the same value."""
    once = _normalize_locale(locale)
    twice = _normalize_locale(once)
    assert once == twice


def test_normalize_locale_blank_maps_to_none() -> None:
    """None / empty / whitespace-only inputs collapse to None."""
    assert _normalize_locale(None) is None
    assert _normalize_locale("") is None
    assert _normalize_locale("   ") is None
    assert _normalize_locale("\t\n") is None


@given(locale=_locale_messy)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalize_locale_output_is_lowercase_when_set(locale: str) -> None:
    """When a value is returned it must be a 2-letter lowercase code (language only)."""
    result = _normalize_locale(locale)
    if result is None:
        return
    assert result == result.lower()
    assert result.isalpha()
    assert len(result) == 2


def test_normalize_locale_strips_country_suffix() -> None:
    """en-US, en_us, EN-GB all collapse to 'en' (language only)."""
    assert _normalize_locale("en-US") == "en"
    assert _normalize_locale("en_us") == "en"
    assert _normalize_locale("EN-GB") == "en"
    assert _normalize_locale("zh_CN") == "zh"


def test_normalize_locale_rejects_invalid_inputs() -> None:
    """Numerals, single letters, three-letter codes return None."""
    assert _normalize_locale("123") is None
    assert _normalize_locale("a") is None
    assert _normalize_locale("xyz") is None  # not a 2-letter language code
