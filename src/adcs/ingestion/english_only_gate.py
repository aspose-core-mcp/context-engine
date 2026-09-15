"""Strict English-only ingestion gate.

Enforces two fatal (severity-1) preconditions before a repository is ingested
for the English-only release:

* Rule 1 - an English version of the content must be locatable. If none is
  found, ingestion must not proceed.
* Rule 2 - the ``doc_locale`` + ``programming_language`` schema must be
  determinable from the repository layout. If it cannot be resolved, ingestion
  must not proceed.

Violations are surfaced to the admin UI and structured logs by the
orchestrator, which raises :class:`EnglishOnlyGateError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from adcs.ingestion.dimension_vocabulary import is_non_english_locale, normalize_locale


class EnglishOnlyGateReason(StrEnum):
    """Machine-readable reason codes for English-only gate violations."""

    ENGLISH_VERSION_MISSING = "english_version_missing"
    SCHEMA_DIMENSIONS_UNRESOLVABLE = "schema_dimensions_unresolvable"


@dataclass(frozen=True, slots=True)
class EnglishOnlyGateViolation:
    """One fatal English-only gate violation for a repository."""

    repo_id: str
    reason_code: str
    message: str


class EnglishOnlyGateError(ValueError):
    """Fatal (severity-1) English-only gate violation; ingestion must halt."""

    def __init__(self, repo_id: str, violations: Sequence[EnglishOnlyGateViolation]) -> None:
        self.repo_id = repo_id
        self.violations: tuple[EnglishOnlyGateViolation, ...] = tuple(violations)
        reasons = ", ".join(sorted({violation.reason_code for violation in self.violations}))
        super().__init__(
            f"English-only ingestion gate failed for `{repo_id}`: {reasons or 'unknown'}."
        )


def evaluate_english_only_gate(
    *,
    repo_id: str,
    layout_detection: Mapping[str, object] | None,
    discovered_locales: Sequence[str],
    english_doc_count: int,
) -> tuple[EnglishOnlyGateViolation, ...]:
    """Return fatal gate violations for a repository (empty tuple == pass)."""
    violations: list[EnglishOnlyGateViolation] = []

    if not _is_schema_resolvable(layout_detection):
        violations.append(
            EnglishOnlyGateViolation(
                repo_id=repo_id,
                reason_code=EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value,
                message=(
                    "The doc_locale + programming_language schema could not be "
                    "determined from the repository layout; English-only ingestion "
                    "cannot proceed."
                ),
            )
        )

    if english_doc_count <= 0:
        violations.append(
            EnglishOnlyGateViolation(
                repo_id=repo_id,
                reason_code=EnglishOnlyGateReason.ENGLISH_VERSION_MISSING.value,
                message=(
                    "No English documents were located for this repository; "
                    "English-only ingestion cannot proceed."
                ),
            )
        )

    return tuple(violations)


def enforce_english_only_gate(
    *,
    repo_id: str,
    layout_detection: Mapping[str, object] | None,
    discovered_locales: Sequence[str],
    english_doc_count: int,
) -> None:
    """Raise :class:`EnglishOnlyGateError` if any fatal gate violation is found."""
    violations = evaluate_english_only_gate(
        repo_id=repo_id,
        layout_detection=layout_detection,
        discovered_locales=discovered_locales,
        english_doc_count=english_doc_count,
    )
    if violations:
        raise EnglishOnlyGateError(repo_id, violations)


def summarize_english_documents(
    relative_paths: Iterable[Sequence[str]],
) -> tuple[int, tuple[str, ...]]:
    """Return ``(english_doc_count, sorted non-English locales)`` for discovered paths.

    A repo-relative path is English iff none of its segments is a known
    non-English locale code.
    """
    english_count = 0
    non_english: set[str] = set()
    for parts in relative_paths:
        locale = _first_non_english_locale(parts)
        if locale is None:
            english_count += 1
        else:
            non_english.add(locale)
    return english_count, tuple(sorted(non_english))


def enforce_english_only_for_repository(
    *,
    repo_id: str,
    layout_detection: Mapping[str, object] | None,
    relative_paths: Iterable[Sequence[str]],
) -> None:
    """Enforce the English-only gate for a repository's discovered files."""
    english_count, non_english_locales = summarize_english_documents(relative_paths)
    enforce_english_only_gate(
        repo_id=repo_id,
        layout_detection=layout_detection,
        discovered_locales=non_english_locales,
        english_doc_count=english_count,
    )


def _first_non_english_locale(parts: Sequence[str]) -> str | None:
    for segment in parts:
        if is_non_english_locale(segment):
            return normalize_locale(segment)
    return None


def _is_schema_resolvable(layout_detection: Mapping[str, object] | None) -> bool:
    """Return True if the repository's locale handling is determinable.

    Determined when EITHER a ``programming_language`` semantic is present, OR
    the layout declares no ``doc_locale`` dimension at all. An absent
    ``doc_locale`` dimension means the tree is English-only — the parser's
    :func:`adcs.ingestion.hugo_parser._infer_path_context` defaults such a
    layout's locale to ``"english"`` — which is itself a determined state even
    without a programming language (e.g. a guide-only docs repo). An
    uncertain/unresolvable layout, or a layout that DECLARES a ``doc_locale``
    dimension yet has no resolvable programming language, is not determinable.
    """
    if not isinstance(layout_detection, Mapping):
        return False
    if bool(layout_detection.get("schema_unresolvable")) or bool(layout_detection.get("uncertain")):
        return False

    has_programming_language = False
    declares_locale = False

    dimensions = layout_detection.get("dimensions")
    if isinstance(dimensions, Sequence) and not isinstance(dimensions, (str, bytes, bytearray)):
        for dimension in dimensions:
            if isinstance(dimension, Mapping):
                semantic = dimension.get("semantic")
                if semantic == "programming_language":
                    has_programming_language = True
                elif semantic == "doc_locale":
                    declares_locale = True

    layout_type = layout_detection.get("layout_type")
    if isinstance(layout_type, str):
        if "programming_language" in layout_type:
            has_programming_language = True
        if any(segment.strip() == "doc_locale" for segment in layout_type.split("/")):
            declares_locale = True

    # A programming_language semantic fully determines the schema.
    if has_programming_language:
        return True
    # No doc_locale dimension declared => English-only by the parser's default
    # => determined even without a programming language. Mirrors
    # hugo_parser._layout_declares_locale so the gate and parser agree.
    return not declares_locale
