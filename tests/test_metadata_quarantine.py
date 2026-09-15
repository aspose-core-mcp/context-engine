from __future__ import annotations

import pytest

from adcs.ingestion.hugo_parser import HugoNormalizedPage
from adcs.ingestion.metadata_quarantine import (
    MetadataQuarantinePolicy,
    MetadataQuarantineReasonCode,
    classify_metadata_quarantine,
    normalize_metadata_quarantine_policy,
)


def _make_page(
    *,
    programming_language: str | None,
    doc_locale: str | None,
    metadata: dict[str, object],
) -> HugoNormalizedPage:
    return HugoNormalizedPage(
        repo_id="aspose.ocr.docs",
        source_path="source-repo-docs/Aspose.OCR/english/net/topic.md",
        source_kind="docs",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language=programming_language,
        doc_locale=doc_locale,
        title="Topic",
        metadata=metadata,
        body_plain="Body",
        headings=(),
        code_blocks=(),
        parse_warnings=(),
        is_index_page=False,
    )


def test_metadata_quarantine_classifier_detects_reason_codes() -> None:
    page = _make_page(
        programming_language=None,
        doc_locale=None,
        metadata={
            "version": "v-next",
            "url": "https://docs.aspose.com/ocr net/bad/",
        },
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="english/net/topic.md",
        layout_detection={"layout_type": "doc_locale/programming_language/content"},
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value in reason_codes
    assert MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value in reason_codes
    assert MetadataQuarantineReasonCode.INVALID_VERSION_FORMAT.value in reason_codes
    assert MetadataQuarantineReasonCode.INVALID_CANONICAL_URL.value in reason_codes


def test_metadata_quarantine_allows_docs_layout_without_doc_locale() -> None:
    page = _make_page(
        programming_language="net",
        doc_locale=None,
        metadata={},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="net/getting-started/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value not in reason_codes
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value not in reason_codes


def test_metadata_quarantine_allows_root_readme_without_path_dimensions() -> None:
    page = _make_page(
        programming_language=None,
        doc_locale=None,
        metadata={},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="README.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value not in reason_codes
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value not in reason_codes


def test_metadata_quarantine_allows_auxiliary_content_group_without_programming_language() -> None:
    page = _make_page(
        programming_language=None,
        doc_locale=None,
        metadata={},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="apps/web/_index.md",
        layout_detection={
            "layout_type": "programming_language/content",
            "dimensions": [
                {
                    "depth": 1,
                    "semantic": "auxiliary_content_group",
                    "values_sample": ["apps"],
                }
            ],
        },
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value not in reason_codes
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value not in reason_codes


def test_metadata_quarantine_does_not_require_programming_language_for_locale_root_pages() -> None:
    page = _make_page(
        programming_language=None,
        doc_locale="english",
        metadata={},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="english/_index.md",
        layout_detection={"layout_type": "doc_locale/programming_language/namespace"},
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value not in reason_codes
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value not in reason_codes


def test_metadata_quarantine_requires_language_from_dimensions_at_depth2() -> None:
    """Slides-style: dimensions has programming_language at depth 2 (content_group at depth 1)."""
    page = _make_page(
        programming_language=None,
        doc_locale=None,
        metadata={},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="content/net/english/aspose.slides/slide/_index.md",
        layout_detection={
            "layout_type": "content_group/programming_language/namespace",
            "dimensions": [
                {"depth": 1, "semantic": "content_group", "values_sample": ["content"]},
                {
                    "depth": 2,
                    "semantic": "programming_language",
                    "values_sample": ["net", "cpp", "java"],
                },
            ],
        },
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value in reason_codes


def test_normalize_metadata_quarantine_policy_accepts_aliases_and_rejects_invalid() -> None:
    assert (
        normalize_metadata_quarantine_policy("strict-block")
        is MetadataQuarantinePolicy.STRICT_BLOCK
    )
    assert (
        normalize_metadata_quarantine_policy("best_effort_continue")
        is MetadataQuarantinePolicy.BEST_EFFORT_CONTINUE
    )
    with pytest.raises(ValueError):
        normalize_metadata_quarantine_policy("invalid-policy")


def test_metadata_quarantine_accepts_two_and_three_part_versions() -> None:
    for version in ("26.5", "26.5.0", "latest-stable"):
        page = _make_page(
            programming_language="net",
            doc_locale=None,
            metadata={"version": version},
        )
        items = classify_metadata_quarantine(
            page=page,
            canonical_base_url="https://docs.aspose.com",
            relative_repo_path="net/getting-started/_index.md",
            layout_detection={"layout_type": "programming_language/content"},
        )
        reason_codes = {item.reason_code for item in items}
        assert (
            MetadataQuarantineReasonCode.INVALID_VERSION_FORMAT.value not in reason_codes
        ), f"version {version!r} should be accepted"


def test_metadata_quarantine_still_rejects_non_numeric_version() -> None:
    page = _make_page(
        programming_language="net",
        doc_locale=None,
        metadata={"version": "v-next"},
    )
    items = classify_metadata_quarantine(
        page=page,
        canonical_base_url="https://docs.aspose.com",
        relative_repo_path="net/getting-started/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
    )
    reason_codes = {item.reason_code for item in items}
    assert MetadataQuarantineReasonCode.INVALID_VERSION_FORMAT.value in reason_codes
