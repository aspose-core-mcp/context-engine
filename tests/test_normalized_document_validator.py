from __future__ import annotations

from dataclasses import replace

import pytest

from adcs.ingestion.normalized_document import (
    NormalizedChunk,
    NormalizedCitation,
    NormalizedDocument,
    NormalizedDocumentMetadata,
    NormalizedDocumentValidationError,
    NormalizedDocumentValidator,
)


def _make_valid_document() -> NormalizedDocument:
    return NormalizedDocument(
        schema="adcs.normalized_document.v1",
        document=NormalizedDocumentMetadata(
            repo_id="aspose.ocr.docs",
            product_id="aspose.ocr",
            product_family="aspose",
            source_kind="docs",
            programming_language="net",
            doc_locale="english",
            version="latest-stable",
            title="Overview",
            doc_type="index_overview",
            canonical_url="https://docs.aspose.com/ocr/net/",
            source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
            source_revision="revision-abc123",
        ),
        chunks=(
            NormalizedChunk(
                chunk_key="chunk-1",
                section_path=("Overview",),
                section_anchor="#overview",
                chunk_type="guide_overview",
                text="Overview text",
                citations=(
                    NormalizedCitation(
                        canonical_url="https://docs.aspose.com/ocr/net/",
                        source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
                        title="Overview",
                        section_anchor="#overview",
                    ),
                ),
                title="Overview",
                canonical_url="https://docs.aspose.com/ocr/net/",
            ),
        ),
        warnings=(),
    )


def test_normalized_document_validator_accepts_valid_document() -> None:
    validator = NormalizedDocumentValidator()
    normalized_document = _make_valid_document()

    errors = validator.validate(
        normalized_document,
        input_source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
    )

    assert errors == ()


def test_normalized_document_validator_rejects_invalid_cases() -> None:
    validator = NormalizedDocumentValidator()
    invalid_document = _make_valid_document()
    invalid_document = NormalizedDocument(
        schema=invalid_document.schema,
        document=replace(invalid_document.document, canonical_url=""),
        chunks=(
            NormalizedChunk(
                chunk_key="chunk-1",
                section_path=("Overview",),
                section_anchor="#overview",
                chunk_type="invalid_chunk_type",
                text="Overview text",
                citations=(
                    NormalizedCitation(
                        canonical_url="",
                        source_path="source-repo-docs/Aspose.OCR/english/net/_index.md",
                        title="Overview",
                        section_anchor="#overview",
                    ),
                ),
                title="Overview",
                canonical_url="",
            ),
        ),
        warnings=(),
    )

    errors = validator.validate(
        invalid_document,
        input_source_path="source-repo-docs/Aspose.OCR/english/net/other.md",
    )
    assert any("document.canonical_url" in error for error in errors)
    assert any("chunk_type" in error for error in errors)
    assert any("citations[0].canonical_url" in error for error in errors)
    assert any(
        "document.source_path must exactly match input source path" in error
        for error in errors
    )

    with pytest.raises(NormalizedDocumentValidationError):
        validator.validate_or_raise(
            invalid_document,
            input_source_path="source-repo-docs/Aspose.OCR/english/net/other.md",
        )
