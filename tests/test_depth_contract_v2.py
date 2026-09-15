"""End-to-end producer/consumer depth-contract guard.

This is the regression test for the depth contract shared by the layout
detector and the Hugo parser:

* PRODUCER (layout detector) — ``scripts/sources/layout/detect_source_layouts.py``
  ``assemble_schema`` emits **1-based** dimension dicts of the shape
  ``{"semantic": <str>, "depth": idx + 1}`` (where ``idx`` is the 0-based level
  index), plus a trailing ``{"semantic": "namespace", "depth": len(levels)+1}``.

* CONSUMER (Hugo parser) — ``src/adcs/ingestion/hugo_parser.py``
  ``_infer_path_context`` reads each dim's ``depth`` and computes
  ``idx = depth_val - 1`` to index into ``Path(relative_repo_path).parts[:-1]``
  (i.e. it assumes a **1-based** depth).

Unlike ``test_hugo_parser_path_context_v2.py`` (which feeds *hand-built* dim
dicts), this test feeds the **REAL** ``assemble_schema`` output verbatim into
``_infer_path_context``.  That is what makes it a true producer→consumer
contract test: it fails if EITHER side drifts off the shared 1-based base —

* if the producer reverts to 0-based (``depth: idx``) or renames ``depth`` ->
  ``level``, the real emitted dims no longer line up with the consumer's
  ``idx = depth_val - 1`` indexing, and locale/programming_language tagging
  collapses to None / wrong values;
* if the consumer stops subtracting 1 (treats depth as 0-based) the same
  misalignment occurs.

If this test ever needs to change to keep passing, the depth contract between
producer and consumer has been broken — that is the signal it exists to raise.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from adcs.ingestion.hugo_parser import _infer_path_context

# ---------------------------------------------------------------------------
# Load the REAL producer module (cwd-independent: derived from this file).
# Mirrors the loader pattern in tests/test_layout_detector_assemble.py.
# ---------------------------------------------------------------------------
_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "sources"
    / "layout"
    / "detect_source_layouts.py"
)
_SPEC = importlib.util.spec_from_file_location("detect_source_layouts", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
det = importlib.util.module_from_spec(_SPEC)
sys.modules["detect_source_layouts"] = det
_SPEC.loader.exec_module(det)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _real_schema(vectors: list[tuple[str, ...]]) -> dict[str, Any]:
    """Run the REAL producer pipeline (summarize_levels_n -> assemble_schema)."""
    levels = det.summarize_levels_n(vectors)
    return det.assemble_schema(levels)


def _layout_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Shape the producer output into the layout_detection dict the parser reads."""
    return {
        "dimensions": schema["dimensions"],
        "layout_type": schema["layout_type"],
        "uncertain": schema["uncertain"],
    }


def _shift_depth(schema: dict[str, Any], delta: int) -> dict[str, Any]:
    """Copy the REAL dims but shift every depth by ``delta`` (regression probe)."""
    return {
        "dimensions": [
            {**dim, "depth": dim["depth"] + delta} for dim in schema["dimensions"]
        ],
        "layout_type": schema["layout_type"],
        "uncertain": schema["uncertain"],
    }


# Faithful Layer-0 directory vectors for a nested locale-first SDK layout.
# Shape per vector = directory parts (NO trailing filename), exactly what
# collect_layout_vectors feeds summarize_levels_n in detect_source_layouts.py.
_LOCALE_FIRST_VECTORS: list[tuple[str, ...]] = [
    ("english", "python", "aspose", "ocr", "quickstart"),
    ("german", "python", "aspose", "ocr", "intro"),
    ("french", "net", "aspose", "ocr", "intro"),
    ("russian", "cpp", "aspose", "ocr", "guide"),
]

# Faithful slides-style layout: a leading non-semantic content group, then the
# programming language, then the locale, then namespace dirs.
_SLIDES_VECTORS: list[tuple[str, ...]] = [
    ("content", "net", "english", "aspose.slides"),
    ("content", "net", "chinese", "aspose.slides"),
    ("content", "cpp", "english", "aspose.slides.charts"),
    ("content", "java", "german", "aspose.slides"),
]


# ---------------------------------------------------------------------------
# 1. Producer emits 1-based depth (sentinel for a 0-based / "level" revert).
# ---------------------------------------------------------------------------
def test_producer_assemble_schema_emits_one_based_depth() -> None:
    """assemble_schema must emit 1-based {'semantic','depth'} dims.

    Pins the producer half of the contract: depths start at 1 (never 0), the
    key is ``depth`` (never ``level``), and the structural dims occupy
    consecutive 1-based depths matching their directory position.
    """
    schema = _real_schema(_LOCALE_FIRST_VECTORS)
    dims = schema["dimensions"]

    # Exact shape produced by the v2 detector for this layout. The first
    # non-structural directory level ("aspose") becomes the namespace at the
    # 1-based depth of its own level (level index 2 -> depth 3); deeper levels
    # are folded into it.
    assert [(d["semantic"], d["depth"]) for d in dims] == [
        ("doc_locale", 1),
        ("programming_language", 2),
        ("namespace", 3),
    ]

    # Structural invariants the consumer relies on.
    for dim in dims:
        assert "depth" in dim, "producer must key dims by 'depth' (1-based), not 'level'"
        assert "level" not in dim, "producer reverted to a 'level' key — contract broken"
        assert isinstance(dim["depth"], int)
        assert dim["depth"] >= 1, "depth is 1-based; a value < 1 means a 0-based revert"

    # The structural (non-namespace) dims must be 1-based and contiguous: the
    # i-th structural dim sits at depth i+1, so its consumer index (depth-1)
    # lands on directory component i. A 0-based revert would start this at 0.
    structural = [d for d in dims if d["semantic"] != "namespace"]
    assert [d["depth"] for d in structural] == list(
        range(1, len(structural) + 1)
    ), "structural dims must occupy contiguous 1-based depths starting at 1"

    # The trailing dim is always a namespace, at a 1-based depth (never 0).
    assert dims[-1]["semantic"] == "namespace"
    assert dims[-1]["depth"] >= 1


# ---------------------------------------------------------------------------
# 2. REAL producer output -> consumer: locale-first layout tags correctly.
# ---------------------------------------------------------------------------
def test_real_schema_locale_first_tags_locale_and_language() -> None:
    """Feed verbatim assemble_schema output into _infer_path_context.

    depth=1 -> parts[0] -> doc_locale; depth=2 -> parts[1] -> programming_language.
    Both MUST be non-None and correctly extracted from the path.
    """
    schema = _real_schema(_LOCALE_FIRST_VECTORS)
    layout = _layout_from_schema(schema)

    doc_locale, programming_language = _infer_path_context(
        relative_repo_path="russian/cpp/aspose/ocr/recognize-image.md",
        layout_detection=layout,
    )

    assert doc_locale is not None, "1-based depth contract broke: locale lost"
    assert programming_language is not None, "1-based depth contract broke: language lost"
    assert doc_locale == "russian"
    assert programming_language == "cpp"


# ---------------------------------------------------------------------------
# 3. REAL producer output -> consumer: slides-style layout tags correctly.
# ---------------------------------------------------------------------------
def test_real_schema_slides_layout_tags_locale_and_language() -> None:
    """Slides layout (content_group/programming_language/doc_locale/namespace).

    The leading content_group dim is non-semantic (skipped by the consumer),
    yet because depth is 1-based the language at depth=2 -> parts[1] and the
    locale at depth=3 -> parts[2] still land on the correct path components.
    """
    schema = _real_schema(_SLIDES_VECTORS)
    # Guard the producer ordering/depths for this layout explicitly.
    assert [(d["semantic"], d["depth"]) for d in schema["dimensions"]] == [
        ("content_group", 1),
        ("programming_language", 2),
        ("doc_locale", 3),
        ("namespace", 4),
    ]
    layout = _layout_from_schema(schema)

    doc_locale, programming_language = _infer_path_context(
        relative_repo_path="content/net/english/aspose.slides/recognize.md",
        layout_detection=layout,
    )

    assert doc_locale is not None
    assert programming_language is not None
    assert doc_locale == "english"
    assert programming_language == "net"


# ---------------------------------------------------------------------------
# 4. Directionality lock: a 0-based shift of the SAME real dims must break.
# ---------------------------------------------------------------------------
def test_zero_based_depth_shift_breaks_tagging() -> None:
    """Pin the *direction* of the 1-based contract.

    Take the REAL producer dims and shift every depth down by one (simulating a
    producer revert to ``depth: idx`` i.e. 0-based).  Fed through the consumer's
    ``idx = depth_val - 1`` indexing this MUST misalign:

    * the locale dim (now depth=0 -> idx=-1) is dropped by the ``idx < 0`` guard,
      so it never tags a path component;
    * the language dim (now depth=1 -> idx=0) slides onto parts[0] ("russian"),
      the wrong component.

    Because this layout *declares* a doc_locale dimension, the consumer's
    structural locale default is None (not "english"); the dims branch returns
    early once programming_language is set, so the misaligned result is
    (None, "russian") — provably different from the correct ("russian", "cpp").
    If both sides were 0-based this misalignment would instead be the "correct"
    path — hence asserting the shifted result differs from the true result locks
    the directionality of the contract.
    """
    schema = _real_schema(_LOCALE_FIRST_VECTORS)
    rel = "russian/cpp/aspose/ocr/recognize-image.md"

    correct = _infer_path_context(
        relative_repo_path=rel,
        layout_detection=_layout_from_schema(schema),
    )
    shifted = _infer_path_context(
        relative_repo_path=rel,
        layout_detection=_shift_depth(schema, -1),
    )

    # The contract is directional: 1-based and 0-based readings MUST diverge.
    assert correct == ("russian", "cpp")
    assert shifted != correct
    # Exact current-behavior pin for the 0-based misalignment: locale dropped
    # (idx=-1 guard), language mis-slid onto parts[0].
    assert shifted == (None, "russian")
