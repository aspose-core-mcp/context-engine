"""Shared indexing data models for Stage-E/Stage-F pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SnapshotStatus(StrEnum):
    """Snapshot lifecycle status for in-memory registry."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class IngestionRunMode(StrEnum):
    """Ingestion execution mode selected by admin flow."""

    PUBLISH = "publish"
    VALIDATE_ONLY = "validate_only"


class PublishDecision(StrEnum):
    """Final publish policy decision after validation and error-ratio checks."""

    FULL_PUBLISH = "full_publish"
    PARTIAL_PUBLISH = "partial_publish"
    PUBLISH_BLOCKED = "publish_blocked"
    VALIDATE_ONLY = "validate_only"
    NO_CHANGES = "no_changes"


class SemanticGateDecision(StrEnum):
    """Semantic review gate decision prior to publish activation."""

    ALLOW_PUBLISH = "allow_publish"
    BLOCK_PUBLISH = "block_publish"
    NOT_ENFORCED = "not_enforced"


@dataclass(frozen=True, slots=True)
class ConversionGateSummary:
    """Conversion quality-gate summary for ingestion publish decision."""

    phase: str = "mvp"
    enforcement_mode: str = "track_only"
    blocking: bool = False
    reason_codes: tuple[str, ...] = ()
    parse_coverage_pct: float = 100.0
    schema_valid_pct: float = 100.0
    metadata_completeness_pct: float = 100.0
    citation_integrity_pct: float = 100.0
    api_signature_coverage_pct: float | None = None
    api_parameter_coverage_pct: float | None = None
    hallucination_risk_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class PublishSafetyGateSummary:
    """Publish-safety gate summary enforced before snapshot activation."""

    blocking: bool = False
    reason_codes: tuple[str, ...] = ()
    usable_chunk_coverage_pct: float = 100.0
    coverage_threshold_pct: float = 0.0
    parser_critical_failed_items_count: int = 0
    active_scopes_count: int = 0
    empty_usable_scope_detected: bool = False


@dataclass(frozen=True, slots=True)
class CriticalEventSummary:
    """Compact critical event summary for API responses."""

    event_ids: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NotificationDispatchSummary:
    """Compact SMTP dispatch summary for API responses."""

    sent_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True, slots=True)
class SemanticGateStatusTransition:
    """Audit transition snapshot from semantic-review workflow."""

    transition_id: str
    from_status: str
    to_status: str
    actor_type: str
    actor_key_id: str | None
    reason: str
    request_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SemanticGateSummary:
    """Deterministic semantic-review gate metadata for publish output."""

    enforced: bool = False
    trigger_type: str = "major_change"
    decision: SemanticGateDecision = SemanticGateDecision.NOT_ENFORCED
    reason_codes: tuple[str, ...] = ()
    review_run_id: str | None = None
    review_status: str | None = None
    approval_mode: str | None = None
    overall_score: float | None = None
    threshold_score: float | None = None
    fail_fast_triggered: bool = False
    blocking_error_count: int = 0
    status_transitions: tuple[SemanticGateStatusTransition, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexExecutableSnippet:
    """Executable snippet metadata persisted into index lanes."""

    snippet_id: str
    language: str
    code: str
    parent_canonical_url: str
    parent_section_anchor: str
    parent_symbol_fqn: str | None = None


@dataclass(frozen=True, slots=True)
class VectorIndexRecord:
    """Vector-lane index record aligned to Qdrant payload contract."""

    chunk_id: str
    point_id: str
    text: str
    vector: tuple[float, ...]
    snapshot_id: str
    product_id: str
    product_family: str
    programming_language: str
    version: str
    source_kind: str
    doc_type: str
    doc_locale: str
    symbol_fqn: str | None
    title: str
    canonical_url: str
    section_anchor: str
    source_revision: str
    repo_id: str
    checksum: str
    executable_snippets: tuple[IndexExecutableSnippet, ...] = ()


@dataclass(frozen=True, slots=True)
class LexicalIndexRecord:
    """Lexical-lane index record aligned to OpenSearch document contract."""

    chunk_id: str
    text: str
    snapshot_id: str
    product_id: str
    product_family: str
    programming_language: str
    version: str
    source_kind: str
    doc_type: str
    doc_locale: str
    symbol_fqn: str | None
    title: str
    canonical_url: str
    section_anchor: str
    source_revision: str
    repo_id: str
    checksum: str
    executable_snippets: tuple[IndexExecutableSnippet, ...] = ()


@dataclass(frozen=True, slots=True)
class VectorWriteResult:
    """Vector writer execution result."""

    collection_name: str
    written_count: int


@dataclass(frozen=True, slots=True)
class LexicalWriteResult:
    """Lexical writer execution result."""

    index_name: str
    alias_name: str
    written_count: int


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """Snapshot registry record for one publish run."""

    snapshot_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    source_revision: str
    status: SnapshotStatus
    indexed_chunks_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotRollbackOutcome:
    """Atomic snapshot rollback execution result."""

    target_snapshot: SnapshotRecord
    previous_active_snapshot: SnapshotRecord


@dataclass(frozen=True, slots=True)
class IndexPublishSummary:
    """High-level index publish summary returned to orchestration/API."""

    snapshot_id: str
    product_id: str
    programming_language: str
    version: str
    source_kind: str
    source_revision: str
    indexed_chunks_count: int
    vector_records_count: int
    lexical_records_count: int
    vector_collection: str
    lexical_index: str
    lexical_alias: str
    active_snapshot_id: str
    mode: IngestionRunMode = IngestionRunMode.PUBLISH
    dry_run: bool = False
    force_full_reindex: bool = False
    partial_publish_threshold_pct: int = 30
    error_ratio: float = 0.0
    decision: PublishDecision = PublishDecision.FULL_PUBLISH
    publish_blocked_reason: str | None = None
    total_items_count: int = 0
    failed_items_count: int = 0
    metadata_quarantine_policy: str = "best_effort_continue"
    quarantined_items_count: int = 0
    canonical_url_remap_entries_count: int = 0
    canonical_url_remap_applied_count: int = 0
    canonical_url_remap_conflict_count: int = 0
    canonical_url_remap_override_count: int = 0
    event_summary: CriticalEventSummary = field(default_factory=CriticalEventSummary)
    notification_summary: NotificationDispatchSummary = field(
        default_factory=NotificationDispatchSummary
    )
    semantic_gate: SemanticGateSummary = field(default_factory=SemanticGateSummary)
    conversion_gate: ConversionGateSummary = field(default_factory=ConversionGateSummary)
    publish_safety_gate: PublishSafetyGateSummary = field(
        default_factory=PublishSafetyGateSummary
    )
    incremental_mode: str = "full_reindex"
    incremental_detection_strategy: str = "checksum_diff"
    incremental_fallback_reason: str | None = None
    incremental_git_base_revision: str | None = None
    baseline_snapshot_id: str | None = None
    file_total_count: int = 0
    file_new_count: int = 0
    file_changed_count: int = 0
    file_unchanged_count: int = 0
    file_removed_count: int = 0
    chunk_total_count: int = 0
    chunk_new_count: int = 0
    chunk_changed_count: int = 0
    chunk_unchanged_count: int = 0
    chunk_removed_count: int = 0
