"""Property-based tests for context_packer pure helpers.

Asserts the structural invariants of the pure scoring helpers (clamp,
release-version rank ordering, intent → required-signals mapping).
These are the deterministic numeric components of the context-packer's
quality score; they are exercised on every retrieval response.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.retrieval.context_packer import (
    _clamp,
    _release_version_rank,
    _required_signals_for_intent,
)

_VALID_INTENTS = frozenset(
    {
        "symbol_lookup",
        "release_notes",
        "troubleshooting",
        "how_to",
        "general_reference",
    }
)


@given(value=st.floats(allow_nan=False, allow_infinity=False))
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_clamp_maps_into_unit_interval(value: float) -> None:
    """Any finite float clamps into [0, 1]."""
    clamped = _clamp(value)
    assert 0.0 <= clamped <= 1.0


@given(value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
def test_clamp_is_identity_inside_unit_interval(value: float) -> None:
    """Values already in [0, 1] are returned unchanged."""
    assert _clamp(value) == value


def test_clamp_clamps_boundary_values() -> None:
    """Concrete boundary behaviour."""
    assert _clamp(-100.0) == 0.0
    assert _clamp(100.0) == 1.0
    assert _clamp(0.0) == 0.0
    assert _clamp(1.0) == 1.0
    assert _clamp(0.5) == 0.5


@given(version=st.from_regex(r"v?\d{1,3}(\.\d{1,3}){0,3}", fullmatch=True))
def test_release_version_rank_returns_four_tuple_for_numeric_strings(
    version: str,
) -> None:
    """Numeric version strings always rank to a 4-tuple of ints."""
    rank = _release_version_rank(version)
    assert rank is not None
    assert len(rank) == 4
    for component in rank:
        assert isinstance(component, int)
        assert component >= 0


@given(
    a=st.from_regex(r"\d{1,3}\.\d{1,3}", fullmatch=True),
    b=st.from_regex(r"\d{1,3}\.\d{1,3}", fullmatch=True),
)
def test_release_version_rank_is_total_ordering_under_string_eq(
    a: str, b: str
) -> None:
    """If two version strings are equal their ranks must be equal."""
    if a == b:
        assert _release_version_rank(a) == _release_version_rank(b)


def test_release_version_rank_orders_known_examples() -> None:
    """Concrete ordering checks against the rubric the freshness score uses."""
    assert _release_version_rank("v25.1") < _release_version_rank("v25.2")
    assert _release_version_rank("25") < _release_version_rank("25.0.1")
    assert _release_version_rank("v25.1.3") < _release_version_rank("v25.1.4")


def test_release_version_rank_handles_non_numeric_strings() -> None:
    """Strings with no digits return None; partial-numeric extracts digits."""
    assert _release_version_rank("") is None
    assert _release_version_rank("latest") is None
    assert _release_version_rank("v25-beta") is not None  # extracts the 25


@given(intent=st.sampled_from(sorted(_VALID_INTENTS)))
def test_required_signals_always_includes_citations(intent: str) -> None:
    """citations is required for every intent — it's the rubric floor."""
    signals = _required_signals_for_intent(intent=intent, intent_subtype=None)
    assert "citations" in signals


@given(intent=st.text(max_size=50))
def test_required_signals_for_unknown_intent_falls_back_to_citations_only(
    intent: str,
) -> None:
    """Unknown intent defaults to ('citations',)."""
    if intent in _VALID_INTENTS:
        return
    signals = _required_signals_for_intent(intent=intent, intent_subtype=None)
    assert signals == ("citations",)


def test_required_signals_for_symbol_lookup_includes_api_reference() -> None:
    """symbol_lookup needs API reference + symbol match."""
    signals = _required_signals_for_intent(intent="symbol_lookup", intent_subtype=None)
    assert "api_reference" in signals
    assert "symbol_match" in signals


def test_required_signals_for_release_notes_includes_version_scope() -> None:
    """release_notes always includes version_scope."""
    signals = _required_signals_for_intent(intent="release_notes", intent_subtype=None)
    assert "release_note" in signals
    assert "version_scope" in signals


def test_required_signals_for_how_to_installation_includes_installation_step() -> None:
    """how_to installation subtype includes installation_step."""
    signals = _required_signals_for_intent(
        intent="how_to", intent_subtype="installation"
    )
    assert "installation_step" in signals
    assert "guide_or_task" in signals


@given(intent=st.sampled_from(sorted(_VALID_INTENTS)))
def test_required_signals_are_unique(intent: str) -> None:
    """The required-signals tuple must not contain duplicates."""
    signals = _required_signals_for_intent(intent=intent, intent_subtype=None)
    assert len(signals) == len(set(signals))
