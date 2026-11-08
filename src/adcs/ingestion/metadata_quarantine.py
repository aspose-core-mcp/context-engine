"""Metadata quarantine classifier and summaries for ingestion pipeline."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from adcs.ingestion.canonical_url_mapping import normalize_canonical_url
from adcs.ingestion.hugo_parser import HugoNormalizedPage

_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")

_LEGACY_URL_KEYS = (
    "canonical_url_old",
    "old_canonical_url",
    "legacy_canonical_url",
)
_LEGACY_URL_LIST_KEYS = (
    "canonical_url_aliases",
    "legacy_canonical_urls",
)


class MetadataQuarantinePolicy(StrEnum):
    """Ingestion policy for quarantine handling."""

    BEST_EFFORT_CONTINUE = "best_effort_continue"
    STRICT_BLOCK = "strict_block"


class MetadataQuarantineReasonCode(StrEnum):
    """Reason codes for quarantined metadata items."""

    MISSING_PROGRAMMING_LANGUAGE = "missing_programming_language"
    MISSING_DOC_LOCALE = "missing_doc_locale"
    INVALID_VERSION_FORMAT = "invalid_version_format"
    INVALID_CANONICAL_URL = "invalid_canonical_url"
    METADATA_SCHEMA_VIOLATION = "metadata_schema_violation"
    NORMALIZED_DOCUMENT_VALIDATION_ERROR = "normalized_document_validation_error"
    CANONICAL_REMAP_CONFLICT = "canonical_remap_conflict"


@dataclass(frozen=True, slots=True)
class MetadataQuarantineItem:
    """One quarantined source item with machine-readable reason code."""

    source_path: str
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class MetadataQuarantineReasonCount:
    """Aggregated count for one reason code."""

    reason_code: str
    count: int


@dataclass(frozen=True, slots=True)
class MetadataQuarantineSummary:
    """Compact quarantine summary for orchestration/admin responses."""

    policy_mode: str
    total_count: int
    reason_counts: tuple[MetadataQuarantineReasonCount, ...] = ()
    sample_items: tuple[MetadataQuarantineItem, ...] = ()


def classify_metadata_quarantine(
    *,
    page: HugoNormalizedPage,
    canonical_base_url: str,
    relative_repo_path: str | None = None,
    layout_detection: Mapping[str, object] | None = None,
) -> tuple[MetadataQuarantineItem, ...]:
    """Classify metadata/frontmatter violations into quarantine reason codes."""
    quarantine_items: list[MetadataQuarantineItem] = []
    required_programming_language, required_doc_locale = _resolve_required_fields(
        relative_repo_path=relative_repo_path,
        layout_detection=layout_detection,
    )

    if required_programming_language and not _is_non_empty(page.programming_language):
        quarantine_items.append(
            MetadataQuarantineItem(
                source_path=page.source_path,
                reason_code=MetadataQuarantineReasonCode.MISSING_PROGRAMMING_LANGUAGE.value,
                message="programming_language is missing after layout detection.",
            )
        )

    if required_doc_locale and not _is_non_empty(page.doc_locale):
        quarantine_items.append(
            MetadataQuarantineItem(
                source_path=page.source_path,
                reason_code=MetadataQuarantineReasonCode.MISSING_DOC_LOCALE.value,
                message="doc_locale is missing after layout detection.",
            )
        )

    version_value = _first_existing(
        page.metadata,
        "version",
        "api_version",
        "product_version",
    )
    if version_value is not None:
        if not isinstance(version_value, str) or not version_value.strip():
            quarantine_items.append(
                MetadataQuarantineItem(
                    source_path=page.source_path,
                    reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                    message=(
                        "`version`/`api_version`/`product_version` must be "
                        "a non-empty string when provided."
                    ),
                )
            )
        else:
            normalized_version = version_value.strip()
            if normalized_version != "latest-stable" and not _VERSION_RE.fullmatch(
                normalized_version
            ):
                quarantine_items.append(
                    MetadataQuarantineItem(
                        source_path=page.source_path,
                        reason_code=MetadataQuarantineReasonCode.INVALID_VERSION_FORMAT.value,
                        message=(
                            "version must use `major.minor[.patch]` format or `latest-stable`, "
                            f"got `{normalized_version}`."
                        ),
                    )
                )

    raw_url = page.metadata.get("url")
    if raw_url is not None:
        if not isinstance(raw_url, str):
            quarantine_items.append(
                MetadataQuarantineItem(
                    source_path=page.source_path,
                    reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                    message="`url` must be a string when provided.",
                )
            )
        else:
            try:
                normalize_canonical_url(raw_url, canonical_base_url=canonical_base_url)
            except ValueError as exc:
                quarantine_items.append(
                    MetadataQuarantineItem(
                        source_path=page.source_path,
                        reason_code=MetadataQuarantineReasonCode.INVALID_CANONICAL_URL.value,
                        message=str(exc),
                    )
                )

    for key in _LEGACY_URL_KEYS:
        value = page.metadata.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            quarantine_items.append(
                MetadataQuarantineItem(
                    source_path=page.source_path,
                    reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                    message=f"`{key}` must be a non-empty string when provided.",
                )
            )

    for key in _LEGACY_URL_LIST_KEYS:
        value = page.metadata.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            quarantine_items.append(
                MetadataQuarantineItem(
                    source_path=page.source_path,
                    reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                    message=f"`{key}` must be a list of non-empty URL strings when provided.",
                )
            )
            continue
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                quarantine_items.append(
                    MetadataQuarantineItem(
                        source_path=page.source_path,
                        reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                        message=f"`{key}[{index}]` must be a non-empty URL string.",
                    )
                )

    remap_value = page.metadata.get("canonical_url_remap")
    if remap_value is not None and not isinstance(remap_value, (Mapping, list)):
        quarantine_items.append(
            MetadataQuarantineItem(
                source_path=page.source_path,
                reason_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                message="`canonical_url_remap` must be an object or list when provided.",
            )
        )

    return tuple(quarantine_items)


def summarize_metadata_quarantine(
    *,
    policy_mode: MetadataQuarantinePolicy,
    items: Sequence[MetadataQuarantineItem],
    sample_limit: int = 5,
) -> MetadataQuarantineSummary:
    """Build deterministic summary with counts and sample errors."""
    if sample_limit < 1:
        sample_limit = 1
    ordered_items = tuple(
        sorted(
            items,
            key=lambda item: (item.reason_code, item.source_path, item.message),
        )
    )
    reason_counter = Counter(item.reason_code for item in ordered_items)
    reason_counts = tuple(
        MetadataQuarantineReasonCount(reason_code=reason_code, count=reason_counter[reason_code])
        for reason_code in sorted(reason_counter)
    )
    return MetadataQuarantineSummary(
        policy_mode=policy_mode.value,
        total_count=len(ordered_items),
        reason_counts=reason_counts,
        sample_items=ordered_items[:sample_limit],
    )


def normalize_metadata_quarantine_policy(
    value: str | MetadataQuarantinePolicy | None,
) -> MetadataQuarantinePolicy:
    if value is None:
        return MetadataQuarantinePolicy.BEST_EFFORT_CONTINUE
    if isinstance(value, MetadataQuarantinePolicy):
        return value
    normalized = value.strip().casefold().replace("-", "_")
    try:
        return MetadataQuarantinePolicy(normalized)
    except ValueError as exc:
        msg = (
            "metadata quarantine policy must be one of "
            "`best_effort_continue` or `strict_block`."
        )
        raise ValueError(msg) from exc


def _first_existing(metadata: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in metadata:
            return metadata[key]
    return None


def _is_non_empty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_required_fields(
    *,
    relative_repo_path: str | None,
    layout_detection: Mapping[str, object] | None,
) -> tuple[bool, bool]:
    parts = _relative_directory_parts(relative_repo_path)
    if not parts:
        return False, False

    require_programming_language = False
    require_doc_locale = False

    # Prefer structured dimensions array over flat layout_type string.
    if isinstance(layout_detection, Mapping):
        raw_dimensions = layout_detection.get("dimensions")
        if (
            isinstance(raw_dimensions, Sequence)
            and not isinstance(raw_dimensions, (str, bytes, bytearray))
            and raw_dimensions
        ):
            auxiliary_groups = _read_auxiliary_content_groups(layout_detection)
            for dim in raw_dimensions:
                if not isinstance(dim, Mapping):
                    continue
                depth_val = dim.get("depth")
                semantic = dim.get("semantic")
                if not isinstance(depth_val, int) or not isinstance(semantic, str):
                    continue
                idx = depth_val - 1  # dimensions use 1-based depth
                if idx < 0 or idx >= len(parts):
                    continue
                token = parts[idx]
                if semantic == "programming_language":
                    if token not in auxiliary_groups:
                        require_programming_language = True
                elif semantic == "doc_locale":
                    require_doc_locale = True
            return require_programming_language, require_doc_locale

    # Fallback: parse layout_type string for repos without dimensions.
    layout_type = _read_layout_type(layout_detection)
    if layout_type is None:
        return True, True

    semantics = [segment.strip() for segment in layout_type.split("/") if segment.strip()]
    if not semantics:
        return True, True

    auxiliary_groups = _read_auxiliary_content_groups(layout_detection)
    for depth, semantic in enumerate(semantics):
        if depth >= len(parts):
            break
        token = parts[depth]
        if semantic == "programming_language":
            if token in auxiliary_groups:
                continue
            require_programming_language = True
        elif semantic == "doc_locale":
            require_doc_locale = True

    return require_programming_language, require_doc_locale


def _relative_directory_parts(relative_repo_path: str | None) -> tuple[str, ...]:
    if not isinstance(relative_repo_path, str) or not relative_repo_path.strip():
        return ()
    parts = Path(relative_repo_path).parts[:-1]
    if not parts:
        return ()
    return tuple(_normalize_token(part) for part in parts if part.strip())


def _read_layout_type(layout_detection: Mapping[str, object] | None) -> str | None:
    if not isinstance(layout_detection, Mapping):
        return None
    raw_layout_type = layout_detection.get("layout_type")
    if not isinstance(raw_layout_type, str):
        return None
    stripped_layout_type = raw_layout_type.strip()
    if not stripped_layout_type:
        return None
    return stripped_layout_type


def _read_auxiliary_content_groups(layout_detection: Mapping[str, object] | None) -> set[str]:
    if not isinstance(layout_detection, Mapping):
        return set()
    raw_dimensions = layout_detection.get("dimensions")
    if not isinstance(raw_dimensions, Sequence) or isinstance(
        raw_dimensions, (str, bytes, bytearray)
    ):
        return set()

    auxiliary_tokens: set[str] = set()
    for dimension in raw_dimensions:
        if not isinstance(dimension, Mapping):
            continue
        semantic = dimension.get("semantic")
        if semantic != "auxiliary_content_group":
            continue
        values_sample = dimension.get("values_sample")
        if not isinstance(values_sample, Sequence) or isinstance(
            values_sample, (str, bytes, bytearray)
        ):
            continue
        for raw_value in values_sample:
            if isinstance(raw_value, str) and raw_value.strip():
                auxiliary_tokens.add(_normalize_token(raw_value))
    return auxiliary_tokens


def _normalize_token(value: str) -> str:
    return value.strip().casefold().replace("_", "-")
