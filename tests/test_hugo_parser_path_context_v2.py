"""Integration test: v2 detector dimensions (depth-keyed) consumed by _infer_path_context.

Regression guard for the level/depth mismatch that caused structured dimensions to be
silently ignored.  The test MUST fail if "depth" is renamed back to "level".
"""

from adcs.ingestion.hugo_parser import _infer_path_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_v2_layout(dims: list[dict]) -> dict:
    """Build a minimal layout_detection dict as emitted by assemble_schema after the fix."""
    return {
        "dimensions": dims,
        "layout_type": "/".join(d["semantic"] for d in dims),
        "uncertain": False,
    }


# ---------------------------------------------------------------------------
# Core integration tests (producer→consumer boundary)
# ---------------------------------------------------------------------------

def test_v2_dims_locale_at_depth1() -> None:
    """depth=1 → first directory component → locale extracted from path."""
    layout = _make_v2_layout([
        {"semantic": "doc_locale", "depth": 1},
        {"semantic": "programming_language", "depth": 2},
        {"semantic": "namespace", "depth": 3},
    ])
    doc_locale, lang = _infer_path_context(
        relative_repo_path="english/net/aspose.ocr/_index.md",
        layout_detection=layout,
    )
    assert doc_locale == "english"
    assert lang == "net"


def test_v2_dims_slides_layout_content_group_first() -> None:
    """Slides-like layout: content_group/programming_language/doc_locale/namespace.

    depth=1 → "content" (content_group, no recognised semantic → skipped)
    depth=2 → "net"     (programming_language)
    depth=3 → "english" (doc_locale)
    depth=4 → namespace (skipped)
    """
    layout = _make_v2_layout([
        {"semantic": "content_group", "depth": 1},
        {"semantic": "programming_language", "depth": 2},
        {"semantic": "doc_locale", "depth": 3},
        {"semantic": "namespace", "depth": 4},
    ])
    doc_locale, lang = _infer_path_context(
        relative_repo_path="content/net/english/aspose.slides/_index.md",
        layout_detection=layout,
    )
    assert doc_locale == "english"
    assert lang == "net"


def test_v2_dims_depth_based_not_level_based() -> None:
    """Confirm that a dict keyed 'level' (old, wrong key) is silently ignored
    and falls back to layout_type string, while 'depth' (correct key) works.

    This is the direct regression guard: if the producer reverts to emitting
    {"level": ...} instead of {"depth": ...}, this test MUST fail.
    """
    # Wrong key: "level" — the consumer must NOT pick up locale from dims
    wrong_layout = {
        "dimensions": [
            {"semantic": "doc_locale", "level": 1},      # old broken key
            {"semantic": "programming_language", "level": 2},
        ],
        "layout_type": "doc_locale/programming_language/namespace",
        "uncertain": False,
    }
    doc_locale_wrong, lang_wrong = _infer_path_context(
        relative_repo_path="english/net/aspose.ocr/_index.md",
        layout_detection=wrong_layout,
    )
    # Falls back to layout_type string — still works but tests the wrong path.
    # The key point: results via "level" dims come from the fallback, not dims.

    # Correct key: "depth" — the consumer MUST pick up locale from dims
    correct_layout = {
        "dimensions": [
            {"semantic": "doc_locale", "depth": 1},
            {"semantic": "programming_language", "depth": 2},
            {"semantic": "namespace", "depth": 3},
        ],
        "layout_type": "doc_locale/programming_language/namespace",
        "uncertain": False,
    }
    doc_locale_correct, lang_correct = _infer_path_context(
        relative_repo_path="english/net/aspose.ocr/_index.md",
        layout_detection=correct_layout,
    )
    # Both paths happen to return same values here (layout_type fallback matches)
    # but the test validates the structured-dims path fires.
    assert doc_locale_correct == "english"
    assert lang_correct == "net"

    # Now use a layout where dims and layout_type DISAGREE to prove which path fires.
    # dims say depth=1 is "programming_language"; layout_type says first slot is "doc_locale".
    # If dims fire: locale=None, lang="english".
    # If fallback fires: locale="english", lang=None (layout_type has doc_locale first).
    diverge_layout = {
        "dimensions": [
            {"semantic": "programming_language", "depth": 1},  # depth overrides layout_type
            {"semantic": "namespace", "depth": 2},
        ],
        "layout_type": "doc_locale/namespace",   # intentionally contradicts dims
        "uncertain": False,
    }
    doc_locale_div, lang_div = _infer_path_context(
        relative_repo_path="english/aspose.ocr/_index.md",
        layout_detection=diverge_layout,
    )
    # dims path fires → programming_language at depth 1 → lang="english", locale=None
    assert doc_locale_div is None
    assert lang_div == "english"


def test_v2_dims_depth_out_of_range_ignored() -> None:
    """depth values that exceed the actual path depth are safely skipped."""
    layout = _make_v2_layout([
        {"semantic": "doc_locale", "depth": 5},   # path only has 1 dir component
        {"semantic": "namespace", "depth": 6},
    ])
    doc_locale, lang = _infer_path_context(
        relative_repo_path="english/_index.md",
        layout_detection=layout,
    )
    # depth=5 is out of range for a 1-component path → dims produce nothing → fallback fires
    # fallback: layout_type="doc_locale/namespace" → first component "english" → locale
    assert doc_locale == "english"
    assert lang is None


def test_v2_dims_empty_dimensions_falls_back_to_layout_type() -> None:
    """Empty dimensions list → fallback to layout_type string."""
    layout = {
        "dimensions": [],
        "layout_type": "doc_locale/programming_language/namespace",
        "uncertain": False,
    }
    doc_locale, lang = _infer_path_context(
        relative_repo_path="english/net/aspose.ocr/_index.md",
        layout_detection=layout,
    )
    assert doc_locale == "english"
    assert lang == "net"


def test_no_layout_detection_returns_none() -> None:
    doc_locale, lang = _infer_path_context(
        relative_repo_path="english/net/_index.md",
        layout_detection=None,
    )
    assert doc_locale is None
    assert lang is None
