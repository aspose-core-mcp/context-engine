from __future__ import annotations

import re

from adcs.ingestion.chunking import StageDChunkingPolicy
from adcs.ingestion.hugo_parser import HugoCodeBlock, HugoHeading, HugoNormalizedPage
from adcs.ingestion.normalized_document import HugoToNormalizedDocumentConverter

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


def _make_api_page() -> HugoNormalizedPage:
    signature = "public RecognitionResult RecognizeImage(string imagePath, OcrInput input)"
    parameter_table = [
        "| Parameter | Type | Description |",
        "| --- | --- | --- |",
        "| imagePath | string | Path to image. |",
        "| input | OcrInput | Runtime OCR options. |",
    ]
    narrative_paragraphs = [
        " ".join(f"api_note_a_{idx}" for idx in range(280)),
        " ".join(f"api_note_b_{idx}" for idx in range(280)),
        " ".join(f"api_note_c_{idx}" for idx in range(280)),
        " ".join(f"api_note_d_{idx}" for idx in range(280)),
    ]
    code_lines = [
        "var ocr = new AsposeOcr();",
        'var result = ocr.RecognizeImage("sample.png");',
        "Console.WriteLine(result.Text);",
    ]
    body_lines = [
        signature,
        *parameter_table,
        "Returns recognized text for the image payload.",
        "",
        narrative_paragraphs[0],
        "",
        narrative_paragraphs[1],
        "",
        *code_lines,
        "",
        narrative_paragraphs[2],
        "",
        narrative_paragraphs[3],
    ]
    return HugoNormalizedPage(
        repo_id="aspose.ocr.apiref",
        source_path=(
            "source-repo-apiref/Aspose.OCR/english/net/aspose.ocr/asposeocr/recognizeimage/_index.md"
        ),
        source_kind="apiref",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title="RecognizeImage Method",
        metadata={
            "title": "RecognizeImage Method",
            "symbol_fqn": "Aspose.OCR.AsposeOcr.RecognizeImage",
            "version": "25.1",
        },
        body_plain="\n".join(body_lines),
        headings=(HugoHeading(level=2, text="RecognizeImage", line_hint=3),),
        code_blocks=(
            HugoCodeBlock(
                language="csharp",
                code="\n".join(code_lines),
                line_start=80,
                line_end=84,
            ),
        ),
        parse_warnings=(),
        is_index_page=True,
    )


def _make_docs_page() -> HugoNormalizedPage:
    paragraphs = [" ".join(f"docs_para_{p}_{idx}" for idx in range(420)) for p in range(4)]
    body_lines: list[str] = []
    for paragraph in paragraphs:
        body_lines.append(paragraph)
        body_lines.append("")
    return HugoNormalizedPage(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/getting-started/_index.md",
        source_kind="docs",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title="Getting Started",
        metadata={"title": "Getting Started", "version": "25.1"},
        body_plain="\n".join(body_lines),
        headings=(HugoHeading(level=2, text="Overview", line_hint=2),),
        code_blocks=(),
        parse_warnings=(),
        is_index_page=True,
    )


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _suffix_prefix_overlap_size(previous_tokens: list[str], next_tokens: list[str]) -> int:
    max_size = min(len(previous_tokens), len(next_tokens))
    for size in range(max_size, 0, -1):
        if previous_tokens[-size:] == next_tokens[:size]:
            return size
    return 0


def test_stage_d_chunking_preserves_api_structural_units() -> None:
    page = _make_api_page()
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    normalized_document = converter.convert_page(page=page, source_revision="revision-abc123")

    _, chunk_records = policy.chunk_document(page=page, normalized_document=normalized_document)

    signature = "public RecognitionResult RecognizeImage(string imagePath, OcrInput input)"
    table_blob = (
        "| Parameter | Type | Description |\n"
        "| --- | --- | --- |\n"
        "| imagePath | string | Path to image. |\n"
        "| input | OcrInput | Runtime OCR options. |"
    )
    code_blob = (
        "var ocr = new AsposeOcr();\n"
        'var result = ocr.RecognizeImage("sample.png");\n'
        "Console.WriteLine(result.Text);"
    )

    signature_hits = [record for record in chunk_records if signature in record.text]
    table_hits = [record for record in chunk_records if table_blob in record.text]
    code_hits = [record for record in chunk_records if code_blob in record.text]

    assert len(signature_hits) == 1
    assert len(table_hits) == 1
    assert len(code_hits) == 1


def test_stage_d_chunking_targets_api_token_range() -> None:
    page = _make_api_page()
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    normalized_document = converter.convert_page(page=page, source_revision="revision-abc123")

    _, chunk_records = policy.chunk_document(page=page, normalized_document=normalized_document)

    assert len(chunk_records) >= 2
    assert all(300 <= record.tokens <= 900 for record in chunk_records)


def test_stage_d_chunking_is_deterministic() -> None:
    page = _make_api_page()
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    normalized_document = converter.convert_page(page=page, source_revision="revision-abc123")

    first_document, first_records = policy.chunk_document(
        page=page,
        normalized_document=normalized_document,
    )
    second_document, second_records = policy.chunk_document(
        page=page,
        normalized_document=normalized_document,
    )

    assert first_document == second_document
    assert first_records == second_records


def test_stage_d_chunking_applies_overlap_only_for_narrative_docs() -> None:
    page = _make_docs_page()
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    normalized_document = converter.convert_page(page=page, source_revision="revision-abc123")

    _, chunk_records = policy.chunk_document(page=page, normalized_document=normalized_document)

    assert len(chunk_records) >= 2
    first_tokens = _tokenize(chunk_records[0].text)
    second_tokens = _tokenize(chunk_records[1].text)
    overlap_size = _suffix_prefix_overlap_size(first_tokens, second_tokens)
    overlap_ratio = overlap_size / len(first_tokens)

    assert overlap_size > 0
    assert 0.10 <= overlap_ratio <= 0.15


def test_stage_d_chunking_extracts_executable_snippet_metadata_with_parent_link() -> None:
    page = _make_api_page()
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    normalized_document = converter.convert_page(page=page, source_revision="revision-abc123")

    _, chunk_records = policy.chunk_document(page=page, normalized_document=normalized_document)

    snippets = [
        snippet
        for chunk_record in chunk_records
        for snippet in chunk_record.executable_snippets
    ]
    assert len(snippets) == 1

    snippet = snippets[0]
    assert snippet.language == "csharp"
    assert snippet.parent_canonical_url == normalized_document.document.canonical_url
    assert snippet.parent_section_anchor == normalized_document.chunks[0].section_anchor
    assert snippet.parent_symbol_fqn == normalized_document.document.symbol_fqn
    assert "RecognizeImage" in snippet.code
