"""Tests for stripping locale/sdk/version segments from symbol_fqn.

Locale/SDK/version directory segments must not leak into symbol_fqn.
"""
from __future__ import annotations

from adcs.ingestion import dimension_vocabulary as dv
from adcs.ingestion.hugo_parser import HugoNormalizedPage
from adcs.ingestion.normalized_document import _resolve_symbol_fqn

# ---------------------------------------------------------------------------
# Helper that mirrors the strip logic used inside _resolve_symbol_fqn
# ---------------------------------------------------------------------------

def strip_structural(fqn: str) -> str:
    parts = [p for p in fqn.split(".") if dv.classify_segment(p) is None]
    return ".".join(parts)


def test_strip_helper_removes_locale_and_sdk_words() -> None:
    assert strip_structural("Aspose.Slides.Content.Androidjava.English") == "Aspose.Slides.Content"


def test_strip_helper_preserves_real_namespace_fqns() -> None:
    # real API FQNs must be untouched
    assert strip_structural("aspose.slides.charts.chart") == "aspose.slides.charts.chart"
    assert strip_structural("com.aspose.slides.android") == "com.aspose.slides.android"
    assert strip_structural("Aspose.Pdf.Generator.Section") == "Aspose.Pdf.Generator.Section"


# ---------------------------------------------------------------------------
# Tests against the real _resolve_symbol_fqn code path
# ---------------------------------------------------------------------------

def _make_page(source_path: str, source_kind: str = "apiref") -> HugoNormalizedPage:
    """Construct a minimal HugoNormalizedPage for FQN resolution tests."""
    return HugoNormalizedPage(
        repo_id="test-repo",
        source_path=source_path,
        source_kind=source_kind,
        product_id=None,
        product_family=None,
        programming_language=None,
        doc_locale=None,
        title="",
        metadata={},
        body_plain="",
        headings=(),
        code_blocks=(),
        parse_warnings=(),
        is_index_page=False,
    )


def test_resolve_symbol_fqn_strips_androidjava_and_english() -> None:
    """Slides-like path with sdk+locale dir segments AFTER namespace must not leak."""
    # Real bug pattern: namespace segment is dotted (aspose.slides), then layout
    # dirs (androidjava/english) appear before the actual class directory.
    page = _make_page(
        "aspose.slides/androidjava/english/Chart/_index.md"
    )
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for this apiref page"
    assert "Androidjava" not in fqn, f"SDK segment leaked into FQN: {fqn!r}"
    assert "English" not in fqn, f"Locale segment leaked into FQN: {fqn!r}"
    # The namespace + class token should survive
    assert "Aspose.Slides" in fqn
    assert "Chart" in fqn


def test_resolve_symbol_fqn_strips_cells_locale_and_java() -> None:
    """Cells pattern: aspose.cells/English/Java/ClassName → no English/Java in FQN."""
    page = _make_page("aspose.cells/English/Java/CellsException/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for aspose.cells path"
    assert "English" not in fqn, f"Locale segment leaked into FQN: {fqn!r}"
    assert "Java" not in fqn, f"SDK segment leaked into FQN: {fqn!r}"
    assert "CellsException" in fqn


def test_resolve_symbol_fqn_unchanged_for_normal_path() -> None:
    """A clean apiref path without structural segments must be unaffected."""
    # Simulate: aspose.slides/Shape/Method/_index.md
    page = _make_page("aspose.slides/Shape/Method/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None
    # No structural segments to strip; FQN should contain Shape and Method
    assert "Shape" in fqn
    assert "Method" in fqn


def test_resolve_symbol_fqn_strips_version_segment() -> None:
    """Version directory segments (e.g. 'v24.3') must not appear in FQN."""
    # path: aspose.slides/v24.3/Chart/_index.md — version dir between ns and class
    page = _make_page("aspose.slides/v24.3/Chart/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None
    assert "V24" not in fqn and "v24" not in fqn, f"Version leaked into FQN: {fqn!r}"
    assert "Chart" in fqn


# ---------------------------------------------------------------------------
# Position-aware strip — real API tokens that LOOK like structural markers
# must be preserved once the leading structural zone ends.
# ---------------------------------------------------------------------------


def test_resolve_symbol_fqn_preserves_node_class_after_structural_leading() -> None:
    """CAD-like path: english/net are structural layout dirs BEFORE the dotted
    namespace; 'node' is a real class token AFTER the dotted namespace.

    Real corpus shape:
      Aspose.CAD/english/net/aspose.cad.fileformats.glb/node/_index.md
    Expected FQN: Aspose.Cad.Fileformats.Glb.Node  (Node preserved)
    """
    page = _make_page(
        "Aspose.CAD/english/net/aspose.cad.fileformats.glb/node/_index.md"
    )
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for CAD node path"
    assert "English" not in fqn, f"Locale 'english' leaked into FQN: {fqn!r}"
    assert "Net" not in fqn, f"SDK 'net' leaked into FQN: {fqn!r}"
    assert fqn.endswith(".Node"), f"Expected FQN to end with .Node but got: {fqn!r}"


def test_resolve_symbol_fqn_preserves_ruby_property_after_structural_leading() -> None:
    """PDF-like path: english/net are structural; 'ruby' is a real property token.

    Path: aspose.pdf.logicalstructure/english/net/structuretypestandard/ruby/_index.md
    Expected FQN ends with ...StructuretypeStandard.Ruby (ruby preserved)
    """
    page = _make_page(
        "aspose.pdf.logicalstructure/english/net/structuretypestandard/ruby/_index.md"
    )
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for PDF ruby path"
    assert "English" not in fqn, f"Locale 'english' leaked into FQN: {fqn!r}"
    assert fqn.endswith(".Ruby"), f"Expected FQN to end with .Ruby but got: {fqn!r}"


def test_resolve_symbol_fqn_preserves_id_property() -> None:
    """HTML-like path: 'id' is a real DOM property, not a locale (Indonesian).

    Path: aspose.html.dom/english/net/htmlelement/id/_index.md
    Expected FQN ends with ...Htmlelement.Id (id preserved)
    """
    page = _make_page("aspose.html.dom/english/net/htmlelement/id/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for HTML id path"
    assert "English" not in fqn, f"Locale 'english' leaked into FQN: {fqn!r}"
    assert fqn.endswith(".Id"), f"Expected FQN to end with .Id but got: {fqn!r}"


def test_resolve_symbol_fqn_preserves_is_property() -> None:
    """HTML-like path: 'is' is a real DOM property, not a locale (Icelandic).

    Path: aspose.html.dom/english/net/htmlelement/is/_index.md
    Expected FQN ends with ...Htmlelement.Is (is preserved)
    """
    page = _make_page("aspose.html.dom/english/net/htmlelement/is/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for HTML is path"
    assert "English" not in fqn, f"Locale 'english' leaked into FQN: {fqn!r}"
    assert fqn.endswith(".Is"), f"Expected FQN to end with .Is but got: {fqn!r}"


def test_resolve_symbol_fqn_still_strips_leading_english_net_androidjava() -> None:
    """Structural leading dirs (english, net, androidjava) must still be stripped.

    Path: aspose.slides/androidjava/english/presentation/_index.md
    Expected FQN: Aspose.Slides.Presentation  (no Androidjava or English)
    """
    page = _make_page("aspose.slides/androidjava/english/presentation/_index.md")
    fqn = _resolve_symbol_fqn(page)
    assert fqn is not None, "Expected a non-None FQN for slides presentation path"
    assert "Androidjava" not in fqn, f"SDK 'androidjava' leaked into FQN: {fqn!r}"
    assert "English" not in fqn, f"Locale 'english' leaked into FQN: {fqn!r}"
    assert fqn.endswith(".Presentation"), f"Expected FQN to end with .Presentation: {fqn!r}"
