"""symbol_fqn stripping on real API-reference repo layouts.

Context
-------
``_resolve_symbol_fqn`` (``src/adcs/ingestion/normalized_document.py``) strips
structural segments driven by ``dimension_vocabulary.classify_segment``.
``tests/test_symbol_fqn_strips_structural_segments.py`` exercises it against
*synthetic* paths.

Three API-reference repos use the ``-References`` / ``-API-Reference``
english-only naming and a
``doc_locale/programming_language/namespace`` on-disk layout (see
``config/source-repositories.yaml``: ``aspose.llm.apiref``,
``aspose.drawing.apiref``, ``aspose.gis.apiref``, all
``layout_type: doc_locale/programming_language/namespace``):

    english/<sdk>/<dotted.aspose.namespace>/<Symbol>/_index.md

These layouts exercise the strip logic on real page paths. ``symbol_fqn`` is
the ``get_symbol_doc`` lookup key, so silent corruption here is high-impact and
invisible in retrieval.

This module pins the ACTUAL behavior of ``_resolve_symbol_fqn`` against
representative page-path shapes from those three repos and asserts two
contracts:

  (1) leading locale / sdk / version directory segments are stripped from the
      FQN (no ``English`` / ``Net`` / ``Python`` / ``V24`` leakage);
  (2) a *real* API token that merely SPELLS like a structural classifier
      (e.g. a class/property literally named ``id`` or a method named
      ``getNode``) — appearing AFTER the first real namespace/class token —
      is preserved verbatim (the leading structural zone has closed).

It also pins, and explicitly flags, a genuine corruption corner the strip
logic exhibits today (see ``test_documents_bug_*`` below): when a
structural-spelling token is the VERY FIRST segment after the dotted-namespace
directory, it is dropped while still in the leading zone and the FQN collapses
to ``None``. That is asserted as current behavior, not endorsed.

The private ``_resolve_symbol_fqn`` is imported exactly as the synthetic test
does.
"""

from __future__ import annotations

import pytest

from adcs.ingestion.dimension_vocabulary import classify_segment
from adcs.ingestion.hugo_parser import HugoNormalizedPage
from adcs.ingestion.normalized_document import _resolve_symbol_fqn


def _apiref_page(
    source_path: str,
    *,
    metadata: dict[str, object] | None = None,
    source_kind: str = "apiref",
) -> HugoNormalizedPage:
    """Build a minimal apiref ``HugoNormalizedPage`` for FQN resolution.

    Only ``source_path`` / ``source_kind`` / ``metadata`` influence
    ``_resolve_symbol_fqn``; everything else is inert filler.
    """
    return HugoNormalizedPage(
        repo_id="merge-apiref-test",
        source_path=source_path,
        source_kind=source_kind,
        product_id=None,
        product_family=None,
        programming_language=None,
        doc_locale=None,
        title="",
        metadata=metadata or {},
        body_plain="",
        headings=(),
        code_blocks=(),
        parse_warnings=(),
        is_index_page=False,
    )


# ---------------------------------------------------------------------------
# Grounding guard: the vocabulary classifications this whole module relies on.
# If dimension_vocabulary drifts, these break first and explain the rest.
# ---------------------------------------------------------------------------


def test_grounding_structural_tokens_classify_as_expected() -> None:
    # Leading-zone structural segments present in the three real layouts.
    assert classify_segment("english") == "doc_locale"
    assert classify_segment("net") == "programming_language"
    assert classify_segment("python") == "programming_language"
    assert classify_segment("java") == "programming_language"
    assert classify_segment("v24.4") == "version"
    # Tokens that SPELL structural but are real API identifiers in these repos.
    # 'node' / 'ruby' are in the programming vocab; 'id' is a bare-2-letter
    # locale-shaped token. classify_segment flags ALL of them — which is
    # exactly why position (leading-zone vs. after-first-real-token) is the
    # only thing that protects them.
    assert classify_segment("node") == "programming_language"
    assert classify_segment("ruby") == "programming_language"
    assert classify_segment("id") == "doc_locale"
    # Substring trap: any token CONTAINING a programming marker also matches.
    assert classify_segment("getnode") == "programming_language"  # contains 'node'
    assert classify_segment("textnode") == "programming_language"  # contains 'node'
    # Genuine namespace/class/method tokens classify as content (None).
    for content_token in ("aspose", "models", "conversation", "graphics", "point", "element"):
        assert classify_segment(content_token) is None, content_token


# ---------------------------------------------------------------------------
# Contract (1): leading locale/sdk/version segments are stripped on the REAL
# english-only doc_locale/programming_language/namespace layouts of the three
# apiref repos (aspose.llm / aspose.drawing / aspose.gis).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_path", "expected_fqn"),
    [
        # aspose.llm.apiref — english/python/<ns>/<class>
        (
            "english/python/aspose.llm.models/LlmModel/_index.md",
            "Aspose.Llm.Models.LlmModel",
        ),
        # aspose.llm.apiref — english/net/<ns-root>/<class>
        (
            "english/net/aspose.llm/Conversation/_index.md",
            "Aspose.Llm.Conversation",
        ),
        # aspose.drawing.apiref — english/net/<ns-root>/<class>
        (
            "english/net/aspose.drawing/Graphics/_index.md",
            "Aspose.Drawing.Graphics",
        ),
        # aspose.drawing.apiref — english/python/<ns>/<class>
        (
            "english/python/aspose.drawing.imaging/ImageFormat/_index.md",
            "Aspose.Drawing.Imaging.ImageFormat",
        ),
        # aspose.gis.apiref — english/net/<ns-root>/<class>
        (
            "english/net/aspose.gis/VectorLayer/_index.md",
            "Aspose.Gis.VectorLayer",
        ),
        # aspose.gis.apiref — english/java/<ns>/<class>
        (
            "english/java/aspose.gis.geometries/Point/_index.md",
            "Aspose.Gis.Geometries.Point",
        ),
    ],
)
def test_leading_locale_sdk_stripped_on_real_layouts(
    source_path: str, expected_fqn: str
) -> None:
    """Leading ``english/<sdk>`` never leak into the FQN; the dotted namespace
    and trailing class token survive, exactly matching the current output."""
    fqn = _resolve_symbol_fqn(_apiref_page(source_path))
    assert fqn == expected_fqn, f"{source_path!r} -> {fqn!r} (expected {expected_fqn!r})"
    # Defensive on the load-bearing invariant: zero structural leakage.
    for leaked in ("English", "Net", "Python", "Java"):
        assert leaked not in fqn, f"structural segment {leaked!r} leaked: {fqn!r}"


def test_leading_version_segment_after_namespace_is_stripped() -> None:
    """A version directory sitting between the dotted namespace and the class
    (``aspose.llm/v24.4/Conversation``) is still in the leading structural zone
    and must be stripped; the class token survives."""
    fqn = _resolve_symbol_fqn(
        _apiref_page("english/net/aspose.llm/v24.4/Conversation/_index.md")
    )
    assert fqn == "Aspose.Llm.Conversation"
    assert "V24" not in fqn and "24" not in fqn, f"version leaked into FQN: {fqn!r}"


def test_class_then_method_page_keeps_both_real_tokens() -> None:
    """A method page (``<class>/<method>``) keeps both real tokens after the
    leading locale/sdk are stripped — this is the common deep-FQN shape that
    feeds get_symbol_doc for method-level lookups."""
    fqn = _resolve_symbol_fqn(
        _apiref_page("english/python/aspose.llm.models/LlmModel/Generate/_index.md")
    )
    assert fqn == "Aspose.Llm.Models.LlmModel.Generate"


def test_namespace_at_root_without_leading_locale_is_unaffected() -> None:
    """Some ``-References`` exports drop the locale/sdk prefix and start at the
    dotted namespace directory. With nothing structural to strip, the FQN is
    formed straight from namespace + class."""
    fqn = _resolve_symbol_fqn(_apiref_page("aspose.gis.geometries/Point/_index.md"))
    assert fqn == "Aspose.Gis.Geometries.Point"


def test_metadata_symbol_fqn_override_wins_over_path_derivation() -> None:
    """An explicit front-matter ``symbol_fqn`` short-circuits all path/strip
    logic and is returned verbatim — independent of the page layout."""
    fqn = _resolve_symbol_fqn(
        _apiref_page(
            "english/net/aspose.gis/VectorLayer/_index.md",
            metadata={"symbol_fqn": "Aspose.GIS.VectorLayer"},
        )
    )
    assert fqn == "Aspose.GIS.VectorLayer"


# ---------------------------------------------------------------------------
# Contract (2): a real API token that SPELLS like a structural classifier,
# appearing AFTER the first real namespace/class token, is preserved verbatim.
# The leading structural zone has already closed, so position protects it even
# though classify_segment() would flag the token in isolation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_path", "expected_fqn", "spelled_like"),
    [
        # 'id' is a bare-2-letter locale-shaped token, but here a real DOM
        # property of an element class -> preserved as '.Id'.
        (
            "english/net/aspose.llm.dom/element/id/_index.md",
            "Aspose.Llm.Dom.Element.Id",
            "doc_locale",
        ),
        # 'java' matches the programming substring marker, but here a real
        # trailing token after a real 'reader' class -> preserved as '.Java'.
        (
            "english/net/aspose.gis.formats/reader/java/_index.md",
            "Aspose.Gis.Formats.Reader.Java",
            "programming_language",
        ),
        # 'getNode' contains the 'node' programming marker, but it is a real
        # method on a real 'Point' class -> preserved as '.GetNode'.
        (
            "english/net/aspose.gis.geometries/Point/getNode/_index.md",
            "Aspose.Gis.Geometries.Point.GetNode",
            "programming_language",
        ),
    ],
)
def test_real_token_spelling_structural_is_preserved_after_first_real_token(
    source_path: str, expected_fqn: str, spelled_like: str
) -> None:
    """The trailing token classifies as structural in isolation, yet must be
    kept because a genuine token already closed the leading zone."""
    # Precondition: the trailing token really would be flagged on its own.
    trailing = source_path.split("/")[-2]  # segment before _index.md
    assert classify_segment(trailing) == spelled_like, (
        f"grounding broke: classify_segment({trailing!r}) != {spelled_like!r}"
    )
    fqn = _resolve_symbol_fqn(_apiref_page(source_path))
    assert fqn == expected_fqn, f"{source_path!r} -> {fqn!r} (expected {expected_fqn!r})"
    # The whole point: the structural-spelling token survived at the tail.
    assert fqn is not None and fqn.split(".")[-1].lower() == trailing.lower()


# ---------------------------------------------------------------------------
# Current-behavior pin (FLAGGED CONCERN, not an endorsement): when a
# structural-spelling token is the FIRST segment after the dotted-namespace
# directory it is dropped while still in the leading zone, and if nothing real
# follows the FQN collapses to None. This silently loses the get_symbol_doc
# key for such symbols. Pinned here as a tripwire so any change to this
# behavior is deliberate.
# ---------------------------------------------------------------------------


def test_documents_bug_first_token_spelling_structural_collapses_to_none() -> None:
    """`aspose.gis.geometries/node` — 'node' is the first post-namespace
    segment, still in the leading zone, so it is stripped and the FQN becomes
    None. This is the silent-corruption corner; asserting CURRENT behavior."""
    fqn = _resolve_symbol_fqn(
        _apiref_page("english/net/aspose.gis.geometries/node/_index.md")
    )
    assert fqn is None  # BUG: real 'Node' class loses its lookup key.


def test_documents_bug_substring_class_then_structural_collapses_to_none() -> None:
    """`aspose.drawing.text/textnode/ruby` — 'textnode' itself matches the
    'node' substring marker, so it is stripped in the leading zone; 'ruby' is
    then also stripped, collapsing the FQN to None. Current behavior pinned."""
    fqn = _resolve_symbol_fqn(
        _apiref_page("english/net/aspose.drawing.text/textnode/ruby/_index.md")
    )
    assert fqn is None  # BUG: compounded structural-spelling strip.
