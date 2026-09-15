"""Tests for the strict English-only ingestion gate (rules 1 & 2).

Rule 1: if no English version is found -> fatal (severity-1), halt ingestion.
Rule 2: if the locale + programming_language schema cannot be determined ->
        fatal, halt ingestion.
"""

from __future__ import annotations

import pytest

from adcs.ingestion.english_only_gate import (
    EnglishOnlyGateError,
    EnglishOnlyGateReason,
    enforce_english_only_for_repository,
    enforce_english_only_gate,
    evaluate_english_only_gate,
    summarize_english_documents,
)

_RESOLVABLE_LAYOUT = {
    "dimensions": [
        {"depth": 1, "semantic": "doc_locale", "values_sample": ["en", "ru"]},
        {"depth": 2, "semantic": "programming_language", "values_sample": ["java", "net"]},
    ]
}


def test_flags_english_version_missing_when_no_english_docs_discovered() -> None:
    violations = evaluate_english_only_gate(
        repo_id="aspose.slides.docs",
        layout_detection=_RESOLVABLE_LAYOUT,
        discovered_locales=("ru", "fr", "ja"),
        english_doc_count=0,
    )

    reasons = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.ENGLISH_VERSION_MISSING.value in reasons


def test_flags_schema_unresolvable_when_layout_detection_missing() -> None:
    violations = evaluate_english_only_gate(
        repo_id="aspose.slides.docs",
        layout_detection=None,
        discovered_locales=("en",),
        english_doc_count=10,
    )

    reasons = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value in reasons


def test_passes_when_schema_resolvable_and_english_present() -> None:
    violations = evaluate_english_only_gate(
        repo_id="aspose.ocr.docs",
        layout_detection=_RESOLVABLE_LAYOUT,
        discovered_locales=("en",),
        english_doc_count=42,
    )

    assert violations == ()


def test_flags_both_reasons_when_english_missing_and_schema_unresolvable() -> None:
    violations = evaluate_english_only_gate(
        repo_id="aspose.slides.docs",
        layout_detection=None,
        discovered_locales=(),
        english_doc_count=0,
    )

    reasons = {violation.reason_code for violation in violations}
    assert reasons == {
        EnglishOnlyGateReason.ENGLISH_VERSION_MISSING.value,
        EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value,
    }


def test_flags_schema_unresolvable_when_programming_language_dimension_absent() -> None:
    layout_without_language = {
        "dimensions": [{"depth": 1, "semantic": "doc_locale", "values_sample": ["en", "ru"]}]
    }

    violations = evaluate_english_only_gate(
        repo_id="aspose.slides.docs",
        layout_detection=layout_without_language,
        discovered_locales=("en",),
        english_doc_count=10,
    )

    reasons = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value in reasons


def test_enforce_raises_with_violations_when_gate_fails() -> None:
    with pytest.raises(EnglishOnlyGateError) as exc_info:
        enforce_english_only_gate(
            repo_id="aspose.slides.docs",
            layout_detection=None,
            discovered_locales=(),
            english_doc_count=0,
        )

    assert exc_info.value.repo_id == "aspose.slides.docs"
    assert exc_info.value.violations  # at least one fatal violation recorded


def test_enforce_is_noop_when_gate_passes() -> None:
    enforce_english_only_gate(
        repo_id="aspose.ocr.docs",
        layout_detection=_RESOLVABLE_LAYOUT,
        discovered_locales=("en",),
        english_doc_count=42,
    )


def test_summarize_counts_english_and_collects_non_english_locales() -> None:
    count, locales = summarize_english_documents(
        [
            ("java", "examine-presentation", "index.md"),
            ("ru", "java", "creating-emails", "index.md"),
            ("net", "licensing", "index.md"),
            ("fr", "java", "math-equations", "index.md"),
        ]
    )

    assert count == 2
    assert locales == ("fr", "ru")


def test_enforce_for_repository_raises_when_no_english_documents() -> None:
    with pytest.raises(EnglishOnlyGateError) as exc_info:
        enforce_english_only_for_repository(
            repo_id="aspose.slides.docs",
            layout_detection=_RESOLVABLE_LAYOUT,
            relative_paths=[("ru", "java", "x.md"), ("fr", "net", "y.md")],
        )

    reasons = {violation.reason_code for violation in exc_info.value.violations}
    assert EnglishOnlyGateReason.ENGLISH_VERSION_MISSING.value in reasons


def test_enforce_for_repository_passes_with_english_and_resolvable_schema() -> None:
    enforce_english_only_for_repository(
        repo_id="aspose.ocr.docs",
        layout_detection=_RESOLVABLE_LAYOUT,
        relative_paths=[("java", "recognize.md"), ("net", "license.md")],
    )
