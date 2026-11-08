from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from adcs.ingestion.hugo_parser import (
    HugoCodeBlock,
    HugoHeading,
    HugoNormalizedPage,
    HugoParseWarning,
)
from adcs.ingestion.normalized_document import (
    HugoToNormalizedDocumentConverter,
    NormalizedDocumentValidator,
    resolve_git_submodule_revision,
)


def _make_page() -> HugoNormalizedPage:
    return HugoNormalizedPage(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
        source_kind="docs",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title="Getting Started",
        metadata={"title": "Getting Started", "url": "/ocr/net/getting-started/"},
        body_plain="Welcome to getting started.",
        headings=(HugoHeading(level=2, text="Introduction", line_hint=5),),
        code_blocks=(
            HugoCodeBlock(
                language="bash",
                code="pip install aspose-ocr-python-net",
                line_start=10,
                line_end=12,
            ),
        ),
        parse_warnings=(
            HugoParseWarning(
                code="HTML_EMBED_DETECTED",
                message="Inline `<script>` embed is not supported in baseline parser.",
                line_hint=15,
            ),
        ),
        is_index_page=True,
    )


def _make_apiref_page(
    *,
    title: str,
    metadata: dict | None = None,
    headings: tuple[HugoHeading, ...] = (),
    source_path: str = (
        "source-repo-apiref/Aspose.Slides/english/net/"
        "aspose.slides/presentation/save/_index.md"
    ),
) -> HugoNormalizedPage:
    return HugoNormalizedPage(
        repo_id="aspose.slides.apiref",
        source_path=source_path,
        source_kind="apiref",
        product_id="aspose.slides",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title=title,
        metadata=metadata or {"title": title},
        body_plain="void Save(string fileName, SaveFormat format)",
        headings=headings,
        code_blocks=(),
        parse_warnings=(),
        is_index_page=False,
    )


def test_resolve_symbol_kind_from_title_suffix() -> None:
    converter = HugoToNormalizedDocumentConverter()
    cases = {
        "Presentation Class": "class",
        "Save Method": "method",
        "SaveFormat Enumeration": "enum",
        "IShape Interface": "interface",
        "BackgroundColor Property": "property",
        "Point Structure": "struct",
    }
    for title, expected_kind in cases.items():
        doc = converter.convert_page(
            page=_make_apiref_page(title=title), source_revision="rev1"
        )
        assert doc.document.symbol_kind == expected_kind, title


def test_resolve_symbol_kind_from_heading_suffix() -> None:
    """Real Aspose apiref pages title classes as 'Class X' (leading keyword) and
    members as 'X.Y' (no keyword), so the title-suffix heuristic yields nothing.
    The reliable signal is the first H2 symbol heading — 'X class', 'X.Y method',
    'X enumeration' — whose trailing keyword names the kind."""
    converter = HugoToNormalizedDocumentConverter()
    cases = [
        ("Class AsposeLLMApi", "AsposeLLMApi class", "class"),
        ("AsposeLLMApi.GetDefaultPreset", "AsposeLLMApi.GetDefaultPreset method", "method"),
        ("Class PDF3DView", "PDF3DView class", "class"),
        ("SquigglyAnnotation.Accept", "SquigglyAnnotation.Accept method", "method"),
        ("Enum SaveFormat", "SaveFormat enumeration", "enum"),
        ("AsposeLLMApi.DefaultPreset", "AsposeLLMApi.DefaultPreset property", "property"),
        ("AsposeLLMApi", "AsposeLLMApi constructor", "constructor"),
    ]
    for title, heading, expected in cases:
        doc = converter.convert_page(
            page=_make_apiref_page(
                title=title,
                headings=(HugoHeading(level=2, text=heading, line_hint=1),),
            ),
            source_revision="rev1",
        )
        assert doc.document.symbol_kind == expected, f"{title} / {heading}"


def test_resolve_symbol_kind_section_headings_do_not_false_match() -> None:
    """The plural section headings inside a class page ('Methods', 'Properties',
    'Constructors') must NOT be mistaken for a kind; only the singular symbol
    heading counts."""
    converter = HugoToNormalizedDocumentConverter()
    doc = converter.convert_page(
        page=_make_apiref_page(
            title="Class AsposeLLMApi",
            headings=(
                HugoHeading(level=2, text="AsposeLLMApi class", line_hint=1),
                HugoHeading(level=2, text="Constructors", line_hint=5),
                HugoHeading(level=2, text="Properties", line_hint=9),
                HugoHeading(level=2, text="Methods", line_hint=13),
            ),
        ),
        source_revision="rev1",
    )
    assert doc.document.symbol_kind == "class"


def test_resolve_symbol_kind_front_matter_overrides_title() -> None:
    converter = HugoToNormalizedDocumentConverter()
    doc = converter.convert_page(
        page=_make_apiref_page(
            title="Save Method",  # title says method
            metadata={"title": "Save Method", "symbol_kind": "property"},  # FM wins
        ),
        source_revision="rev1",
    )
    assert doc.document.symbol_kind == "property"


def test_resolve_symbol_kind_namespace_page() -> None:
    converter = HugoToNormalizedDocumentConverter()
    # A namespace-level apiref page (no resolvable symbol_fqn → api_reference_namespace)
    doc = converter.convert_page(
        page=_make_apiref_page(
            title="Aspose.Slides Namespace",
            source_path="source-repo-apiref/Aspose.Slides/english/net/_index.md",
        ),
        source_revision="rev1",
    )
    assert doc.document.symbol_kind == "namespace"


def test_resolve_symbol_kind_fallback_for_unknown_apiref() -> None:
    converter = HugoToNormalizedDocumentConverter()
    doc = converter.convert_page(
        page=_make_apiref_page(title="Some Inscrutable Heading"),
        source_revision="rev1",
    )
    assert doc.document.symbol_kind == "symbol"  # apiref always non-null kind


def test_resolve_symbol_kind_is_none_for_docs() -> None:
    converter = HugoToNormalizedDocumentConverter()
    doc = converter.convert_page(page=_make_page(), source_revision="rev1")
    assert doc.document.symbol_kind is None


def test_converter_fills_mandatory_fields_and_provenance() -> None:
    converter = HugoToNormalizedDocumentConverter()
    validator = NormalizedDocumentValidator()
    page = _make_page()

    normalized_document = converter.convert_page(
        page=page,
        source_revision="revision-abc123",
    )
    validator.validate_or_raise(normalized_document, input_source_path=page.source_path)

    assert normalized_document.document.repo_id == "aspose.ocr.docs"
    assert normalized_document.document.source_path == page.source_path
    assert normalized_document.document.source_revision == "revision-abc123"
    assert normalized_document.document.title == "Getting Started"
    assert normalized_document.document.canonical_url.endswith("/ocr/net/getting-started/")
    assert normalized_document.chunks


def test_converter_emits_citation_ready_chunk_fields() -> None:
    converter = HugoToNormalizedDocumentConverter()
    normalized_document = converter.convert_page(
        page=_make_page(),
        source_revision="revision-abc123",
    )

    first_chunk = normalized_document.chunks[0]
    assert first_chunk.title == "Getting Started"
    assert first_chunk.canonical_url
    assert first_chunk.section_anchor.startswith("#")
    assert first_chunk.citations
    assert first_chunk.citations[0].canonical_url == first_chunk.canonical_url
    assert first_chunk.citations[0].source_path == normalized_document.document.source_path


def test_converter_is_deterministic_for_same_input() -> None:
    converter = HugoToNormalizedDocumentConverter()
    page = _make_page()

    first = converter.convert_page(page=page, source_revision="revision-abc123")
    second = converter.convert_page(page=page, source_revision="revision-abc123")

    assert first == second


def test_resolve_git_submodule_revision_uses_git_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_path = Path("/tmp/source-repo-docs/Aspose.OCR")

    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["git", "rev-parse", "HEAD"]
        assert cwd == expected_path
        assert capture_output is True
        assert text is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="abcdef1234567890\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    revision = resolve_git_submodule_revision(submodule_path=expected_path)
    assert revision == "abcdef1234567890"


def test_resolve_git_submodule_revision_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(
        command: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, capture_output, text, check
        return subprocess.CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(ValueError, match="Failed to resolve source revision"):
        resolve_git_submodule_revision(submodule_path=Path("/tmp/not-a-repo"))
