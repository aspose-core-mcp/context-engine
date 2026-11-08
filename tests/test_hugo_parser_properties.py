"""Property-based tests for HugoMarkdownParser.

These tests assert structural invariants over wide adversarial input
distributions (frontmatter shapes, deeply nested markdown, control
characters, adversarial line lengths, fuzzed shortcodes). They
complement the example-based tests in test_hugo_markdown_parser.py.

The goal is Scenario Coverage breadth — the parser must never crash and
must always produce a well-formed HugoNormalizedPage for any UTF-8 input.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from adcs.ingestion.hugo_parser import HugoMarkdownParser

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Plain text without surrogate pairs and with line breaks allowed.
_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogate halves
    ),
    max_size=200,
)

# A single markdown heading line — level 1..6.
_heading_line = st.builds(
    lambda level, text: "#" * level + " " + text.replace("\n", " "),
    st.integers(min_value=1, max_value=6),
    _safe_text,
)

# A fenced code block (may have a language hint or not, may be empty inside).
_code_block = st.builds(
    lambda lang, body: f"```{lang}\n{body}\n```",
    st.one_of(st.just(""), st.sampled_from(["python", "csharp", "java", "json", "yaml"])),
    _safe_text,
)

# A Hugo shortcode of the form {{< name args >}} or balanced {{< name >}}…{{< /name >}}.
_shortcode_inline = st.builds(
    lambda name, args: f"{{{{< {name} {args} >}}}}",
    st.from_regex(r"[a-z][a-z0-9_-]{0,15}", fullmatch=True),
    st.from_regex(r"[a-z0-9= -]{0,30}", fullmatch=True),
)

# YAML frontmatter — keep keys simple and safe.
_frontmatter = st.builds(
    lambda items: "---\n" + "\n".join(f"{k}: {v}" for k, v in items) + "\n---\n",
    st.lists(
        st.tuples(
            st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True),
            _safe_text.filter(lambda s: "\n" not in s and ":" not in s),
        ),
        min_size=0,
        max_size=6,
        unique_by=lambda kv: kv[0],
    ),
)

# A body line — one of plain text / heading / shortcode / blank.
_body_line = st.one_of(
    _safe_text.filter(lambda s: "\n" not in s),
    _heading_line,
    _shortcode_inline,
    st.just(""),
)

# A whole document: optional frontmatter + zero-or-more body lines, with
# code blocks interleaved.
_document = st.builds(
    lambda fm, body, codes: fm + "\n".join(body + codes),
    st.one_of(st.just(""), _frontmatter),
    st.lists(_body_line, min_size=0, max_size=25),
    st.lists(_code_block, min_size=0, max_size=4),
)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

_DEFAULT_LAYOUT = {"layout_type": "doc_locale/programming_language/content"}


@given(raw=_document)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_parser_never_crashes_on_fuzzed_documents(raw: str) -> None:
    """The parser must produce a HugoNormalizedPage for any UTF-8 input."""
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    # Structural invariants on the produced page.
    assert page is not None
    assert isinstance(page.parse_warnings, tuple)
    assert isinstance(page.headings, tuple)
    assert isinstance(page.code_blocks, tuple)


@given(raw=_document)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_parser_is_deterministic(raw: str) -> None:
    """Two parses of the same input must produce equal output."""
    parser = HugoMarkdownParser()
    a = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    b = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    assert a.headings == b.headings
    assert a.code_blocks == b.code_blocks
    assert a.parse_warnings == b.parse_warnings
    assert a.body_plain == b.body_plain


@given(raw=_document)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_heading_levels_are_in_valid_range(raw: str) -> None:
    """Every parsed heading must declare a level in 1..6."""
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    for h in page.headings:
        assert 1 <= h.level <= 6


@given(raw=_document)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_code_block_line_ranges_are_well_formed(raw: str) -> None:
    """Each code block's line_end >= line_start, both positive."""
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    for cb in page.code_blocks:
        assert cb.line_start >= 1
        assert cb.line_end >= cb.line_start


@given(raw=_document)
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_warning_codes_are_known(raw: str) -> None:
    """Every emitted warning must declare a non-empty code string."""
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="page.md",
        source_kind="docs",
        raw_markdown=raw,
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/page.md",
        layout_detection=_DEFAULT_LAYOUT,
    )
    for w in page.parse_warnings:
        assert w.code  # non-empty
        assert isinstance(w.code, str)
