from __future__ import annotations

import pytest

from adcs.ingestion.hugo_parser import (
    WARNING_CODE_FRONT_MATTER_CLOSE_INLINE,
    WARNING_CODE_HTML_EMBED_DETECTED,
    WARNING_CODE_UNSUPPORTED_SHORTCODE,
    HugoMarkdownParser,
    HugoParseFatalError,
)


def test_hugo_parser_recovers_front_matter_close_glued_to_code_fence() -> None:
    # Reproduces the 447 Aspose.Slides interface/callback pages whose closing
    # `---` is glued to an opening code fence on the same line (`---` + ```` ``` ````).
    # The page must parse (not raise HUGO_FRONT_MATTER_UNCLOSED), the metadata
    # must be read, and the trailing code fence recovered into the body.
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.slides.apiref",
        source_path="source-repo-apiref/Aspose.Slides/content/androidjava/english/"
        "com.aspose.slides/foreachslidecallback/_index.md",
        source_kind="apiref",
        raw_markdown=(
            "---\n"
            "title: ForEach.ForEachSlideCallback\n"
            "second_title: Aspose.Slides for Android via Java API Reference\n"
            "description: \n"
            "type: docs\n"
            "url: /com.aspose.slides/foreach.foreachslidecallback/\n"
            "---```\n"
            "public static interface ForEach.ForEachSlideCallback\n"
            "```\n"
            "## Methods\n"
        ),
        relative_repo_path="content/androidjava/english/com.aspose.slides/"
        "foreachslidecallback/_index.md",
        layout_detection={"layout_type": "content/doc_locale/programming_language"},
    )

    assert page.title == "ForEach.ForEachSlideCallback"
    assert page.metadata.get("url") == "/com.aspose.slides/foreach.foreachslidecallback/"
    assert WARNING_CODE_FRONT_MATTER_CLOSE_INLINE in {w.code for w in page.parse_warnings}
    # The recovered code fence is parsed as a code block, not lost.
    assert any(
        "public static interface ForEach.ForEachSlideCallback" in block.code
        for block in page.code_blocks
    )


def test_hugo_parser_dash_run_is_not_a_front_matter_close() -> None:
    # A line of four dashes (horizontal rule) must NOT be mistaken for the
    # closing `---`; with no real close the document is still fatally unclosed.
    parser = HugoMarkdownParser()
    with pytest.raises(HugoParseFatalError):
        parser.parse_document(
            repo_id="aspose.ocr.docs",
            source_path="source-repo-docs/Aspose.OCR/net/x.md",
            source_kind="docs",
            raw_markdown="---\ntitle: X\n----\nbody text\n",
            relative_repo_path="net/x.md",
            layout_detection={"layout_type": "programming_language/content"},
        )


def test_hugo_parser_supports_index_and_regular_pages() -> None:
    parser = HugoMarkdownParser()
    layout_detection = {"layout_type": "doc_locale/programming_language/content"}

    index_page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
        source_kind="docs",
        raw_markdown="""---
title: Product Overview
---
## Overview
Welcome!
""",
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/_index.md",
        layout_detection=layout_detection,
    )
    regular_page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/getting-started/install.md",
        source_kind="docs",
        raw_markdown="""---
title: Install Guide
---
## Install
Run setup.
""",
        product_id="aspose.ocr",
        product_family="aspose",
        relative_repo_path="english/net/getting-started/install.md",
        layout_detection=layout_detection,
    )

    assert index_page.is_index_page is True
    assert regular_page.is_index_page is False
    assert index_page.doc_locale == "english"
    assert index_page.programming_language == "net"
    assert index_page.title == "Product Overview"
    assert [heading.text for heading in regular_page.headings] == ["Install"]


def test_hugo_parser_supports_yaml_and_toml_front_matter() -> None:
    parser = HugoMarkdownParser()

    yaml_page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/yaml.md",
        source_kind="docs",
        raw_markdown="""---
title: YAML Page
weight: 10
keywords:
- ocr
- yaml
---
Body.
""",
        relative_repo_path="net/yaml.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    toml_page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/toml.md",
        source_kind="docs",
        raw_markdown="""+++
title = "TOML Page"
weight = 7
keywords = ["ocr", "toml"]
+++
Body.
""",
        relative_repo_path="net/toml.md",
        layout_detection={"layout_type": "programming_language/content"},
    )

    assert yaml_page.metadata["title"] == "YAML Page"
    assert yaml_page.metadata["weight"] == 10
    assert yaml_page.metadata["keywords"] == ["ocr", "yaml"]
    assert toml_page.metadata["title"] == "TOML Page"
    assert toml_page.metadata["weight"] == 7
    assert toml_page.metadata["keywords"] == ["ocr", "toml"]


def test_hugo_parser_handles_supported_shortcodes_in_baseline_mode() -> None:
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/python/getting-started/installation/_index.md",
        source_kind="docs",
        raw_markdown="""---
title: Installation
---
{{< tabs tabID="1" tabTotal="2" >}}
{{< tab tabNum="1" >}}
```bash
pip install aspose-ocr-python-net
```
{{< /tab >}}
{{< /tabs >}}
{{% alert color="primary" %}}
Read release notes.
{{% /alert %}}
""",
        relative_repo_path="python/getting-started/installation/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
    )

    warning_codes = {warning.code for warning in page.parse_warnings}
    assert WARNING_CODE_UNSUPPORTED_SHORTCODE not in warning_codes
    assert "pip install aspose-ocr-python-net" in page.body_plain
    assert "{{<" not in page.body_plain
    assert "{{%" not in page.body_plain


def test_hugo_parser_emits_stable_warning_codes_for_unsupported_constructs() -> None:
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/unsupported.md",
        source_kind="docs",
        raw_markdown="""---
title: Unsupported
---
{{< fancy >}}
text
{{< /fancy >}}
<style>
body { color: red; }
</style>
<script>
console.log("x")
</script>
""",
        relative_repo_path="net/unsupported.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    warning_codes = [warning.code for warning in page.parse_warnings]

    assert WARNING_CODE_UNSUPPORTED_SHORTCODE in warning_codes
    assert WARNING_CODE_HTML_EMBED_DETECTED in warning_codes


def test_hugo_parser_output_is_deterministic_for_same_input() -> None:
    parser = HugoMarkdownParser()
    raw_markdown = """---
title: Determinism
---
## Section A
Text.
```python
print("ok")
```
"""
    page_a = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/determinism.md",
        source_kind="docs",
        raw_markdown=raw_markdown,
        relative_repo_path="net/determinism.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    page_b = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/determinism.md",
        source_kind="docs",
        raw_markdown=raw_markdown,
        relative_repo_path="net/determinism.md",
        layout_detection={"layout_type": "programming_language/content"},
    )

    assert page_a == page_b


def test_hugo_parser_infers_snippet_language_with_deterministic_fallback() -> None:
    parser = HugoMarkdownParser()
    page_with_layout = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/snippets.md",
        source_kind="docs",
        raw_markdown="""---
title: Snippets
---
```c#
Console.WriteLine("one");
```
```
Console.WriteLine("two");
```
```vbnet
Console.WriteLine("three")
```
""",
        relative_repo_path="english/net/snippets.md",
        layout_detection={"layout_type": "doc_locale/programming_language/content"},
    )
    page_without_layout = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/snippets-unknown.md",
        source_kind="docs",
        raw_markdown="""---
title: Unknown Snippet Language
---
```
echo "hello"
```
""",
        relative_repo_path="snippets-unknown.md",
        layout_detection=None,
    )

    assert [block.language for block in page_with_layout.code_blocks] == ["csharp", "csharp", "vb"]
    assert [block.language for block in page_without_layout.code_blocks] == ["unknown"]


def test_infer_path_context_uses_dimensions_for_content_group_layout() -> None:
    """Slides-style layout: content/{programming_language}/{locale}/{namespace}/..."""
    parser = HugoMarkdownParser()
    layout_detection = {
        "layout_type": "content_group/programming_language/namespace",
        "dimensions": [
            {"depth": 1, "semantic": "content_group", "values_sample": ["content"]},
            {"depth": 2, "semantic": "programming_language", "values_sample": ["net", "cpp"]},
        ],
    }
    page = parser.parse_document(
        repo_id="aspose.slides.apiref",
        source_path="source-repo-apiref/Aspose.Slides/content/net/english/aspose.slides/slide/_index.md",
        source_kind="apiref",
        raw_markdown="---\ntitle: Slide\n---\nSlide class.\n",
        product_id="aspose.slides",
        relative_repo_path="content/net/english/aspose.slides/slide/_index.md",
        layout_detection=layout_detection,
    )
    assert page.programming_language == "net"


def test_infer_path_context_dimensions_extracts_locale_and_language() -> None:
    """Standard layout: {locale}/{programming_language}/{namespace}/..."""
    parser = HugoMarkdownParser()
    layout_detection = {
        "layout_type": "doc_locale/programming_language/namespace",
        "dimensions": [
            {"depth": 1, "semantic": "doc_locale", "values_sample": ["english"]},
            {"depth": 2, "semantic": "programming_language", "values_sample": ["net", "java"]},
        ],
    }
    page = parser.parse_document(
        repo_id="aspose.pdf.apiref",
        source_path="source-repo-apiref/Aspose.PDF/english/net/aspose.pdf/page/_index.md",
        source_kind="apiref",
        raw_markdown="---\ntitle: Page\n---\nPage class.\n",
        product_id="aspose.pdf",
        relative_repo_path="english/net/aspose.pdf/page/_index.md",
        layout_detection=layout_detection,
    )
    assert page.doc_locale == "english"
    assert page.programming_language == "net"


def test_infer_path_context_falls_back_to_layout_type_without_dimensions() -> None:
    """Repos without dimensions array should still work via layout_type string."""
    parser = HugoMarkdownParser()
    layout_detection = {"layout_type": "programming_language/content"}
    page = parser.parse_document(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/net/guide.md",
        source_kind="docs",
        raw_markdown="---\ntitle: Guide\n---\nGuide.\n",
        product_id="aspose.ocr",
        relative_repo_path="net/guide.md",
        layout_detection=layout_detection,
    )
    assert page.programming_language == "net"


def test_infer_path_context_defaults_locale_less_layout_to_english() -> None:
    """A layout with no doc_locale dimension is single-locale English.

    Without this default the locale is 'unknown', which the strict
    english-only embed gate drops — silently losing ALL content of such repos
    (regression: aspose.llm.docs ingested 0 vectors despite 280 chunks).
    """
    parser = HugoMarkdownParser()
    layout_detection = {
        "layout_type": "programming_language/content",
        "dimensions": [
            {"depth": 1, "semantic": "programming_language", "values_sample": ["net"]},
        ],
    }
    page = parser.parse_document(
        repo_id="aspose.llm.docs",
        source_path="source-repo-docs/Aspose.LLM/net/getting-started/installation/_index.md",
        source_kind="docs",
        raw_markdown="---\ntitle: Installation\n---\nInstall steps.\n",
        product_id="aspose.llm",
        relative_repo_path="net/getting-started/installation/_index.md",
        layout_detection=layout_detection,
    )
    assert page.doc_locale == "english"
    assert page.programming_language == "net"


def test_infer_path_context_locale_declaring_layout_is_not_defaulted() -> None:
    """A layout that DOES declare doc_locale must parse the real locale, never
    the english default — non-English content stays correctly tagged so the
    english-only gate can drop it."""
    parser = HugoMarkdownParser()
    layout_detection = {
        "layout_type": "doc_locale/programming_language/namespace",
        "dimensions": [
            {"depth": 1, "semantic": "doc_locale", "values_sample": ["english", "german"]},
            {"depth": 2, "semantic": "programming_language", "values_sample": ["net"]},
        ],
    }
    page = parser.parse_document(
        repo_id="aspose.pdf.apiref",
        source_path="source-repo-apiref/Aspose.PDF/german/net/aspose.pdf/page/_index.md",
        source_kind="apiref",
        raw_markdown="---\ntitle: Page\n---\nPage class.\n",
        product_id="aspose.pdf",
        relative_repo_path="german/net/aspose.pdf/page/_index.md",
        layout_detection=layout_detection,
    )
    assert page.doc_locale == "german"
    assert page.programming_language == "net"
