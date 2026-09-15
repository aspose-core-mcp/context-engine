"""Property-based tests for retrieval query normalization.

Fuzzes `normalize_query` over wide adversarial query distributions and
asserts the structural invariants the rest of the retrieval stack
depends on (length bound, finite intent set, determinism,
empty-input → empty-result behaviour, symbol-candidate provenance).

Complements the example-based tests in test_query_planner.py.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.query_planner import _MAX_QUERY_LENGTH, normalize_query

_VALID_INTENTS = frozenset(
    {
        "symbol_lookup",
        "release_notes",
        "troubleshooting",
        "how_to",
        "general_reference",
    }
)


# A safe-character text strategy: excludes surrogate halves and null bytes.
_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters=("\x00",),
    ),
    max_size=500,
)

# Inputs that look like API-ish queries — boost the symbol-lookup intent path.
_apiish_text = st.from_regex(
    r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){0,4}(\(\))?",
    fullmatch=True,
)

# Inputs that include version tokens — exercise release_notes path.
_versionish_text = st.from_regex(
    r"(?:upgrade |migrate to |breaking |new in |what's new in |release )"
    r"(?:v|version )?[0-9]{1,2}(?:\.[0-9]{1,3}){0,2}",
    fullmatch=True,
)

_query = st.one_of(_safe_text, _apiish_text, _versionish_text)


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalize_query_never_raises(query: str) -> None:
    """normalize_query must accept any safe-character input without raising."""
    result = normalize_query(query)
    assert result is not None


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalized_query_length_is_bounded(query: str) -> None:
    """The normalized_query length must never exceed _MAX_QUERY_LENGTH."""
    result = normalize_query(query)
    assert len(result.normalized_query) <= _MAX_QUERY_LENGTH


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_intent_is_in_valid_set(query: str) -> None:
    """The classified intent must always be one of the five known values."""
    result = normalize_query(query)
    assert result.intent in _VALID_INTENTS


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_normalize_query_is_deterministic(query: str) -> None:
    """Two normalizations of the same query must produce identical output."""
    a = normalize_query(query)
    b = normalize_query(query)
    assert a == b


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_whitespace_padding_is_idempotent(query: str) -> None:
    """Leading/trailing whitespace must not affect the normalized result."""
    bare = normalize_query(query)
    padded = normalize_query(f"   \n  {query}\t\n  ")
    assert bare.normalized_query == padded.normalized_query
    assert bare.intent == padded.intent
    assert bare.symbol_candidates == padded.symbol_candidates


@given(blank=st.sampled_from(["", " ", "\t", "\n", "   \n\t  "]))
def test_blank_input_yields_empty_normalized_query(blank: str) -> None:
    """Whitespace-only input must produce an empty normalized_query."""
    result = normalize_query(blank)
    assert result.normalized_query == ""
    assert result.intent == "general_reference"
    assert result.symbol_candidates == ()
    assert result.detected_version_tokens == ()


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_symbol_candidates_are_substrings(query: str) -> None:
    """Every extracted symbol must appear as a substring of the normalized query."""
    result = normalize_query(query)
    for sym in result.symbol_candidates:
        assert sym in result.normalized_query, (
            f"Symbol candidate {sym!r} is not a substring of normalized_query "
            f"{result.normalized_query!r}"
        )


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_symbol_lookup_intent_requires_symbol_candidate(query: str) -> None:
    """If intent is symbol_lookup, there must be at least one symbol candidate."""
    result = normalize_query(query)
    if result.intent == "symbol_lookup":
        assert len(result.symbol_candidates) >= 1


@given(query=_query)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_reason_codes_are_strings_and_non_empty(query: str) -> None:
    """Every intent_reason_code must be a non-empty string."""
    result = normalize_query(query)
    for code in result.intent_reason_codes:
        assert isinstance(code, str) and code
