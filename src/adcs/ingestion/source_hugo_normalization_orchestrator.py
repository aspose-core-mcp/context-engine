"""In-memory orchestration service for Hugo parsing and page normalization."""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from adcs.admin import InMemorySemanticReviewService, SemanticReviewPublishGateEvaluation
from adcs.indexing.apiref_symbol_store import ApiRefSymbolStore
from adcs.indexing.index_models import (
    ConversionGateSummary,
    CriticalEventSummary,
    IndexPublishSummary,
    IngestionRunMode,
    NotificationDispatchSummary,
    PublishDecision,
    PublishSafetyGateSummary,
    SemanticGateDecision,
    SemanticGateStatusTransition,
    SemanticGateSummary,
)
from adcs.indexing.publish_orchestrator import IndexPublishOrchestrator, _is_english_locale
from adcs.ingestion.canonical_url_mapping import (
    CanonicalUrlMappingConflict,
    CanonicalUrlMappingContext,
    CanonicalUrlMappingRegistry,
    FileSystemCanonicalUrlMappingStore,
    extract_metadata_remap_pairs,
)
from adcs.ingestion.chunking import StageDChunkingPolicy, StageDChunkRecord
from adcs.ingestion.english_only_gate import (
    EnglishOnlyGateViolation,
    evaluate_english_only_gate,
    summarize_english_documents,
)
from adcs.ingestion.hugo_parser import (
    FATAL_CODE_FRONT_MATTER_TOML_PARSE_ERROR,
    FATAL_CODE_FRONT_MATTER_UNCLOSED,
    HugoMarkdownParser,
    HugoNormalizedPage,
    HugoParseFatalError,
)
from adcs.ingestion.incremental_state import (
    FileSystemIncrementalStateStore,
    IncrementalBaselineCorruptError,
    IncrementalBaselineState,
    IncrementalChunkDiffPlan,
    IncrementalFileDiffPlan,
    build_chunk_diff_plan,
    build_file_diff_plan,
    checksum_text,
)
from adcs.ingestion.job_repository import (
    IngestionJobRecord,
    IngestionJobRepository,
    InMemoryIngestionJobRepository,
)
from adcs.ingestion.llm_runtime_policy import (
    IngestionLLMBackend,
    IngestionLLMRuntimePolicy,
    IngestionLLMTask,
)
from adcs.ingestion.metadata_quarantine import (
    MetadataQuarantineItem,
    MetadataQuarantinePolicy,
    MetadataQuarantineReasonCode,
    MetadataQuarantineSummary,
    classify_metadata_quarantine,
    normalize_metadata_quarantine_policy,
    summarize_metadata_quarantine,
)
from adcs.ingestion.normalized_document import (
    HugoToNormalizedDocumentConverter,
    NormalizedDocument,
    NormalizedDocumentMetadata,
    NormalizedDocumentValidator,
    resolve_git_submodule_revision,
)
from adcs.ingestion.operation_state_store import (
    FileSystemOperationStateStore,
    OperationMetadataEnvelope,
)
from adcs.ingestion.prompt_registry import (
    ConversionPromptAssignment,
    ConversionPromptEvaluationSummary,
    IngestionPromptRegistry,
)
from adcs.ingestion.review_artifacts import FileSystemIngestionReviewArtifactStore
from adcs.ingestion.source_registry import (
    SourceRegistryLookupError,
    SourceRegistryService,
    SourceRegistryValidationError,
    SourceRepository,
)
from adcs.ingestion.staging_store import (
    CanonicalStagingReplaySnapshot,
    CanonicalStagingScopeSummary,
    CanonicalStagingSnapshotIntegrityError,
    CanonicalStagingWriteResult,
    FileSystemCanonicalStagingStore,
    RepositoryStreamingWriter,
    StagingSnapshotTier,
)
from adcs.ops import (
    CriticalEventPublisher,
    CriticalEventSeverity,
    CriticalEventType,
    InMemoryCriticalEventStore,
    NotificationService,
    NotificationStatus,
    SmtpNotificationDispatch,
)

logger = logging.getLogger(__name__)


# --- Memory profiling (opt-in via env var, no-op otherwise) ---------------
# Enabled by setting ADCS_PROFILE_MEMORY=1. When active, writes per-stage
# resident-set-size + tracemalloc snapshots to ADCS_PROFILE_MEMORY_LOG
# (default: logs/memory_profile.log). Used to measure per-stage memory with
# real numbers rather than estimates.

_MEMORY_PROFILE_ENABLED = os.environ.get("ADCS_PROFILE_MEMORY", "").lower() in (
    "1",
    "true",
    "yes",
)
_MEMORY_PROFILE_LOG_PATH = Path(
    os.environ.get("ADCS_PROFILE_MEMORY_LOG", "logs/memory_profile.log")
)
_MEMORY_GC_INTERVAL = int(os.environ.get("ADCS_INGEST_GC_INTERVAL", "1000"))

# Intra-normalize checkpoint configuration -------------------------------
# When > 0, the parse loop in `_normalize_repository` writes a pickled
# snapshot of in-progress state every N successfully-processed files. On a
# subsequent run for the same (repo_id, source_revision), the snapshot is
# loaded and already-processed files are skipped — turning a mid-parse
# crash from "lose all work" into "lose ≤N files of work".
# Set to 0 to disable.
_INTRA_CHECKPOINT_INTERVAL = int(
    os.environ.get("ADCS_INGEST_INTRA_CHECKPOINT_INTERVAL", "5000")
)
_INTRA_CHECKPOINT_DIR = Path(
    os.environ.get(
        "ADCS_INGEST_INTRA_CHECKPOINT_DIR",
        "logs/normalize_checkpoints",
    )
)
# Bump when the persisted checkpoint shape changes incompatibly — older
# files with a different schema_version are ignored (forces a full reparse
# for that repo, which is the safe default).
#
# Version history:
#   1 — initial, kept full `pages` / `canonical_documents` lists.
#   2 — replaced lists with counts + the gate accumulators.
_INTRA_CHECKPOINT_SCHEMA_VERSION = 2

if _MEMORY_PROFILE_ENABLED:
    import tracemalloc

    if not tracemalloc.is_tracing():
        tracemalloc.start()


def _log_memory_snapshot(tag: str, **extra: Any) -> None:
    """Lightweight per-stage memory snapshot.

    No-op unless ``ADCS_PROFILE_MEMORY=1`` is set in the environment. Failures
    inside this helper are swallowed — profiling must never break ingestion.
    """
    if not _MEMORY_PROFILE_ENABLED:
        return
    try:
        import resource
        import tracemalloc

        # ru_maxrss is kilobytes on Linux, bytes on macOS.
        max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = max_rss / 1024 if sys.platform.startswith("linux") else max_rss / (1024 * 1024)
        current, peak = tracemalloc.get_traced_memory()
        parts = [
            f"ts={datetime.now(UTC).isoformat()}",
            f"pid={os.getpid()}",
            f"tag={tag}",
            f"rss_mb={rss_mb:.1f}",
            f"traced_current_mb={current / 1024 / 1024:.1f}",
            f"traced_peak_mb={peak / 1024 / 1024:.1f}",
        ]
        for key, value in extra.items():
            parts.append(f"{key}={value}")
        _MEMORY_PROFILE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _MEMORY_PROFILE_LOG_PATH.open("a") as f:
            f.write(" ".join(parts) + "\n")
    except Exception as exc:
        logger.debug("Memory profiling snapshot failed: %s", exc)


class SourceHugoNormalizationStatus(StrEnum):
    """Operation execution status for Hugo parse + normalize flow."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


SemanticReviewTriggerType = Literal["major_change", "manual"]
PUBLISH_BLOCKED_REASON_METADATA_QUARANTINE_STRICT = "metadata_quarantine_strict_block"
PUBLISH_BLOCKED_REASON_ENGLISH_ONLY_GATE = "english_only_gate_failed"
PUBLISH_BLOCKED_REASON_SEMANTIC_REVIEW_HARD_GATE = "semantic_review_hard_gate"
PUBLISH_BLOCKED_REASON_ERROR_RATIO_THRESHOLD = "error_ratio_exceeds_threshold"
PUBLISH_BLOCKED_REASON_CONVERSION_HARD_GATE = "conversion_quality_hard_gate"
PUBLISH_BLOCKED_REASON_PUBLISH_SAFETY_GATE = "publish_safety_gate"
INCREMENTAL_FALLBACK_REASON_FORCED_REINDEX = "forced_reindex_requested"
IDEMPOTENCY_SCOPE_SCHEMA = "ingestion-trigger-v1"
QUALITY_GATE_PHASE_MVP = "mvp"
QUALITY_GATE_PHASE_PREPROD = "preprod"
QUALITY_GATE_PHASE_GA = "ga"
INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_DIFF = "checksum_diff"
INCREMENTAL_DETECTION_STRATEGY_GIT_DIFF = "git_diff"
INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_GIT_FALLBACK = "checksum_diff_git_fallback"
PUBLISH_SAFETY_REASON_CRITICAL_PARSER_ERRORS = "critical_parser_errors_present"
PUBLISH_SAFETY_REASON_EMPTY_USABLE_SCOPE = "empty_usable_scope"
PUBLISH_SAFETY_REASON_USABLE_CHUNK_COVERAGE = "usable_chunk_coverage_below_threshold"
_PARSER_CRITICAL_ERROR_CODES = frozenset(
    {
        FATAL_CODE_FRONT_MATTER_UNCLOSED,
        FATAL_CODE_FRONT_MATTER_TOML_PARSE_ERROR,
        "READ_ERROR",
    }
)


class SourceHugoNormalizationOperationNotFoundError(KeyError):
    """Raised when an operation id does not exist in in-memory storage."""


@dataclass(frozen=True, slots=True)
class SourceHugoNormalizationLogLine:
    """Normalized Hugo parse operation log line."""

    stream: str
    line: str


@dataclass(frozen=True, slots=True)
class SourceCanonicalUrlMappingSummary:
    """Canonical URL remap summary for one repository operation result."""

    contexts: tuple[str, ...] = ()
    remap_entries_count: int = 0
    remap_applied_count: int = 0
    remap_conflict_count: int = 0
    remap_override_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceStagingScopeSummary:
    """Scope-level staging manifest summary for review and admin UI."""

    product_id: str
    programming_language: str
    version: str
    doc_locale: str
    source_kind: str
    manifest_path: str
    documents_count: int
    chunk_records_count: int


@dataclass(frozen=True, slots=True)
class SourceHugoNormalizationResult:
    """One repository-level Hugo normalization result.

    Streaming mode (default): the orchestrator persists
    every canonical document to disk inside the parse loop and **does not**
    retain them in process memory. Consumers that need the actual payload
    iterate
    :meth:`FileSystemCanonicalStagingStore.iter_canonical_documents` /
    :meth:`.iter_chunk_records` using :attr:`staging_repository_manifest_path`
    as the entry point. In this mode :attr:`pages` and
    :attr:`canonical_documents` are empty tuples; cardinality lives in
    :attr:`parsed_pages_count` / :attr:`canonical_documents_count` /
    :attr:`chunk_records_count`.

    Legacy in-memory mode is preserved for callers that opt out of
    streaming (``dry_run=True`` short-circuits, no streaming writer is
    opened, lists are populated as before).
    """

    repo_id: str
    source_kind: str
    parsed_pages_count: int
    parse_warnings_count: int
    pages: tuple[HugoNormalizedPage, ...]
    canonical_documents: tuple[NormalizedDocument, ...]
    chunk_records: tuple[StageDChunkRecord, ...]
    indexing_summary: IndexPublishSummary
    review_artifact_path: str | None = None
    staging_repository_manifest_path: str | None = None
    staging_scopes: tuple[SourceStagingScopeSummary, ...] = ()
    staging_replay_used: bool = False
    failed_items: tuple[SourceHugoNormalizationFailedItem, ...] = ()
    metadata_quarantine: MetadataQuarantineSummary = field(
        default_factory=lambda: MetadataQuarantineSummary(
            policy_mode=MetadataQuarantinePolicy.BEST_EFFORT_CONTINUE.value,
            total_count=0,
        )
    )
    prompt_evaluation: ConversionPromptEvaluationSummary = field(
        default_factory=ConversionPromptEvaluationSummary
    )
    canonical_url_mapping: SourceCanonicalUrlMappingSummary = field(
        default_factory=SourceCanonicalUrlMappingSummary
    )
    # Cardinality fields. Always populated; in streaming
    # mode they are the only way to know how many docs / chunks the run
    # produced because the tuples above are empty by design.
    canonical_documents_count: int = 0
    chunk_records_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceHugoNormalizationFailedItem:
    """Per-item parse/normalize/chunk/validation failure."""

    source_path: str
    error_code: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceHugoNormalizationOperation:
    """Source Hugo normalization operation record stored in memory."""

    operation_id: str
    status: SourceHugoNormalizationStatus
    repo_ids: tuple[str, ...]
    logs: tuple[SourceHugoNormalizationLogLine, ...]
    results: tuple[SourceHugoNormalizationResult, ...]
    started_at: datetime | None
    finished_at: datetime | None
    mode: IngestionRunMode = IngestionRunMode.PUBLISH
    requested_mode: IngestionRunMode = IngestionRunMode.PUBLISH
    partial_publish_threshold_pct: int = 30
    metadata_quarantine_policy: str = MetadataQuarantinePolicy.BEST_EFFORT_CONTINUE.value
    semantic_review_trigger_type: SemanticReviewTriggerType = "major_change"
    conversion_backend: str = IngestionLLMBackend.DETERMINISTIC.value
    prompt_registry_version: str = "disabled"
    prompt_experiment_id: str = "conversion.default.v1"
    dry_run: bool = False
    force_full_reindex: bool = False
    bypass_staging_replay: bool = False
    request_id: str | None = None
    idempotency_key: str | None = None
    idempotency_scope: str | None = None
    idempotency_reused: bool = False
    idempotency_expires_at: datetime | None = None
    request_fingerprint: str | None = None
    attempt_count: int = 1
    max_attempts: int = 1
    next_retry_at: datetime | None = None
    last_error_kind: str | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    resumable: bool = False


@dataclass(frozen=True, slots=True)
class _ScannedMarkdownFile:
    """Pre-scanned markdown file metadata for incremental planning.

    The raw markdown body is intentionally **not** stored here to avoid
    keeping the full text of every repository file in memory simultaneously.
    The body is read once during the initial scan to compute the checksum
    and then released; downstream parse stages re-read the file on demand
    via :attr:`markdown_file`. This roughly halves disk I/O cost in exchange
    for ~3-5 GB of RAM savings on a 140k-file repository.
    """

    markdown_file: Path
    source_path: str
    relative_repo_path: str
    checksum: str


@dataclass
class _IntraNormalizeCheckpoint:
    """Periodic snapshot of in-progress :meth:`_normalize_repository` state.

    Written every :data:`_INTRA_CHECKPOINT_INTERVAL` successfully-processed
    files during the parse loop. On a subsequent run for the same
    ``(repo_id, source_revision)`` the snapshot is loaded and files already
    in :attr:`processed_source_paths` are skipped — so a mid-parse crash
    loses ≤ N files of work instead of the entire repository.

    The class is intentionally mutable so the orchestrator can construct it
    in-place at dump time without copying every list element. Pickle is
    used for serialization since the embedded :class:`NormalizedDocument`
    /:class:`HugoNormalizedPage` types are not JSON-serializable.
    """

    schema_version: int
    repo_id: str
    source_revision: str
    processed_source_paths: list[str]
    # `parsed_chunk_records` is still retained because the downstream steps
    # (incremental diff, index publish) take the chunk records as a list.
    parsed_chunk_records: list[StageDChunkRecord]
    failed_items: list[SourceHugoNormalizationFailedItem]
    metadata_quarantine_items: list[MetadataQuarantineItem]
    canonical_mapping_conflicts: list[CanonicalUrlMappingConflict]
    parse_warnings_count: int
    remap_applied_count: int
    remap_override_count: int
    parse_warnings_by_source_path: dict[str, int]
    prompt_assignments: list[ConversionPromptAssignment]
    # Registries carry the in-memory mapping state accumulated by
    # `register_mappings` calls in the parse loop. Without persisting them
    # here, a resume would lose any new mappings the prior partial run had
    # discovered (they are only flushed to disk via store.save() AFTER the
    # parse loop completes).
    canonical_mapping_registries: dict[
        CanonicalUrlMappingContext, CanonicalUrlMappingRegistry
    ]
    # schema_version=2 fields: counters and gate accumulators that stand in
    # for full `pages` / `canonical_documents` lists.
    pages_count: int
    canonical_documents_count: int
    conversion_gate_accumulator: _ConversionGateAccumulator
    publish_safety_gate_accumulator: _PublishSafetyGateAccumulator


def _intra_checkpoint_path(repo_id: str, source_revision: str) -> Path:
    """Disk path for the intra-normalize checkpoint file."""
    safe_revision = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in source_revision
    )[:64]
    return _INTRA_CHECKPOINT_DIR / f"{repo_id}__{safe_revision}.pkl"


def _save_intra_checkpoint(checkpoint: _IntraNormalizeCheckpoint) -> None:
    """Atomically persist ``checkpoint`` via tmp+rename.

    Best-effort: any failure (disk full, permissions, pickle error on an
    unforeseen field type) is logged and swallowed — checkpointing is a
    durability optimization, not a correctness invariant, so it must never
    break the ingest run.
    """
    if _INTRA_CHECKPOINT_INTERVAL <= 0:
        return
    try:
        import pickle

        path = _intra_checkpoint_path(checkpoint.repo_id, checkpoint.source_revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("wb") as f:
            pickle.dump(checkpoint, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp_path.replace(path)
    except Exception as exc:
        logger.warning(
            "Failed to save intra-normalize checkpoint for %s @ %s: %s",
            checkpoint.repo_id,
            checkpoint.source_revision,
            exc,
        )


def _load_intra_checkpoint(
    repo_id: str, source_revision: str
) -> _IntraNormalizeCheckpoint | None:
    """Load checkpoint if it exists and matches the current revision/schema.

    Returns ``None`` (and triggers full reparse) when:
    - the feature is disabled (`_INTRA_CHECKPOINT_INTERVAL <= 0`)
    - the checkpoint file does not exist
    - the file is unreadable or unpicklable
    - the schema_version does not match the current code
    - the repo_id / source_revision do not match
    """
    if _INTRA_CHECKPOINT_INTERVAL <= 0:
        return None
    path = _intra_checkpoint_path(repo_id, source_revision)
    if not path.exists():
        return None
    try:
        import pickle

        with path.open("rb") as f:
            data = pickle.load(f)
    except Exception as exc:
        logger.warning(
            "Failed to load intra-normalize checkpoint at %s: %s — ignoring",
            path,
            exc,
        )
        return None
    if not isinstance(data, _IntraNormalizeCheckpoint):
        logger.warning(
            "Intra-normalize checkpoint at %s has unexpected type %s — ignoring",
            path,
            type(data).__name__,
        )
        return None
    if data.schema_version != _INTRA_CHECKPOINT_SCHEMA_VERSION:
        logger.info(
            "Intra-normalize checkpoint schema mismatch (got %s, want %s) — ignoring",
            data.schema_version,
            _INTRA_CHECKPOINT_SCHEMA_VERSION,
        )
        return None
    if data.repo_id != repo_id or data.source_revision != source_revision:
        return None
    return data


def _delete_intra_checkpoint(repo_id: str, source_revision: str) -> None:
    """Remove the checkpoint after the parse loop completes successfully."""
    if _INTRA_CHECKPOINT_INTERVAL <= 0:
        return
    try:
        _intra_checkpoint_path(repo_id, source_revision).unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Failed to delete intra-normalize checkpoint: %s", exc)


@dataclass(frozen=True, slots=True)
class _IncrementalPlanSelection:
    """Resolved incremental detection strategy and resulting file diff plan."""

    file_diff_plan: IncrementalFileDiffPlan
    detection_strategy: str
    git_base_revision: str | None = None


class SourceHugoNormalizationOrchestrationService:
    """Run Stage-A Hugo parser + normalizer over registry-selected repositories."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        registry_path: str | Path | None = None,
        canonical_base_url: str = "https://docs.aspose.com",
        parser: HugoMarkdownParser | None = None,
        converter: HugoToNormalizedDocumentConverter | None = None,
        validator: NormalizedDocumentValidator | None = None,
        chunking_policy: StageDChunkingPolicy | None = None,
        index_publish_orchestrator: IndexPublishOrchestrator | None = None,
        apiref_symbol_store: ApiRefSymbolStore | None = None,
        source_revision_resolver: Callable[[Path], str] | None = None,
        partial_publish_threshold_pct: int = 30,
        publish_safety_min_coverage_pct: float = 50.0,
        metadata_quarantine_policy: str | MetadataQuarantinePolicy = (
            MetadataQuarantinePolicy.BEST_EFFORT_CONTINUE
        ),
        metadata_quarantine_sample_limit: int = 5,
        english_only_strict: bool = False,
        canonical_url_mapping_store: FileSystemCanonicalUrlMappingStore | None = None,
        critical_event_publisher: CriticalEventPublisher | None = None,
        notification_service: NotificationService | None = None,
        semantic_review_service: InMemorySemanticReviewService | None = None,
        ingestion_job_repository: IngestionJobRepository | None = None,
        incremental_state_store: FileSystemIncrementalStateStore | None = None,
        review_artifact_store: FileSystemIngestionReviewArtifactStore | None = None,
        canonical_staging_store: FileSystemCanonicalStagingStore | None = None,
        operation_state_store: (
            FileSystemOperationStateStore[SourceHugoNormalizationOperation] | None
        ) = None,
        idempotency_ttl_seconds: int = 24 * 60 * 60,
        retry_max_attempts: int = 5,
        retry_backoff_base_seconds: int = 5,
        retry_backoff_max_seconds: int = 120,
        llm_runtime_policy: IngestionLLMRuntimePolicy | None = None,
        prompt_registry: IngestionPromptRegistry | None = None,
        quality_gate_phase: str = QUALITY_GATE_PHASE_MVP,
        docs_english_only_embed: bool = False,
    ) -> None:
        default_workspace_root = Path(__file__).resolve().parents[3]
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else default_workspace_root.resolve()
        )
        default_registry_path = self._workspace_root / "config" / "source-repositories.yaml"
        if not default_registry_path.exists():
            default_registry_path = self._workspace_root / "config" / "source-repositories.json"
        self._registry_path = (
            Path(registry_path).resolve()
            if registry_path is not None
            else default_registry_path.resolve()
        )
        self._canonical_base_url = canonical_base_url.rstrip("/")
        self._parser = parser or HugoMarkdownParser()
        self._converter = converter or HugoToNormalizedDocumentConverter(
            canonical_base_url=self._canonical_base_url
        )
        self._validator = validator or NormalizedDocumentValidator()
        self._chunking_policy = chunking_policy or StageDChunkingPolicy()
        self._index_publish_orchestrator = (
            index_publish_orchestrator or IndexPublishOrchestrator()
        )
        self._apiref_symbol_store = apiref_symbol_store
        self._docs_english_only_embed = docs_english_only_embed
        self._source_revision_resolver = source_revision_resolver or (
            lambda submodule_path: resolve_git_submodule_revision(submodule_path=submodule_path)
        )
        self._partial_publish_threshold_pct = _normalize_threshold_pct(
            partial_publish_threshold_pct
        )
        self._publish_safety_min_coverage_pct = _normalize_percent_float(
            publish_safety_min_coverage_pct
        )
        self._metadata_quarantine_policy = normalize_metadata_quarantine_policy(
            metadata_quarantine_policy
        )
        self._metadata_quarantine_sample_limit = max(1, metadata_quarantine_sample_limit)
        self._english_only_strict = english_only_strict
        self._canonical_url_mapping_store = (
            canonical_url_mapping_store
            or FileSystemCanonicalUrlMappingStore(
                workspace_root=self._workspace_root,
                canonical_base_url=self._canonical_base_url,
            )
        )
        self._critical_event_publisher = critical_event_publisher or InMemoryCriticalEventStore()
        self._notification_service = notification_service or NotificationService()
        self._semantic_review_service = semantic_review_service
        self._ingestion_job_repository = (
            ingestion_job_repository or InMemoryIngestionJobRepository()
        )
        self._incremental_state_store = incremental_state_store or FileSystemIncrementalStateStore(
            workspace_root=self._workspace_root
        )
        self._review_artifact_store = (
            review_artifact_store
            or FileSystemIngestionReviewArtifactStore(
                workspace_root=self._workspace_root
            )
        )
        self._canonical_staging_store = (
            canonical_staging_store
            or FileSystemCanonicalStagingStore(workspace_root=self._workspace_root)
        )
        self._operation_state_store = operation_state_store or FileSystemOperationStateStore(
            namespace="ingestion",
            record_type=SourceHugoNormalizationOperation,
            workspace_root=self._workspace_root,
        )
        self._idempotency_ttl_seconds = max(1, int(idempotency_ttl_seconds))
        self._retry_max_attempts = max(1, int(retry_max_attempts))
        self._retry_backoff_base_seconds = max(1, int(retry_backoff_base_seconds))
        self._retry_backoff_max_seconds = max(
            self._retry_backoff_base_seconds,
            int(retry_backoff_max_seconds),
        )
        self._llm_runtime_policy = llm_runtime_policy or IngestionLLMRuntimePolicy.disabled()
        self._prompt_registry = prompt_registry or IngestionPromptRegistry.disabled()
        self._quality_gate_phase = _normalize_quality_gate_phase(quality_gate_phase)

        self._lock = Lock()
        self._operations: dict[str, SourceHugoNormalizationOperation] = {}
        self._operation_order: list[str] = []

    def _apiref_structured_only(self, repository: object) -> bool:
        """True when apiref is served from the Postgres symbol store, so the
        dense (Qdrant) + lexical (OpenSearch) writes are skipped at publish.

        Active only when an ``apiref_symbol_store`` was injected (i.e.
        ``APIREF_STRUCTURED_STORE_ENABLED``) and the repository is apiref
        (ADR-011).
        """
        return (
            getattr(repository, "source_kind", None) == "apiref"
            and self._apiref_symbol_store is not None
        )

    def _publish_apiref_symbols(self, *, repository: object, snapshot_id: str) -> None:
        """Materialise API-reference symbols into the structured store.

        Opt-in (only when an ``apiref_symbol_store`` was injected) and limited
        to apiref repositories. Runs after the index publish from the same
        staging snapshot. Failures are logged and swallowed — symbol
        publishing must never fail an index publish that already succeeded
        (ADR-011).
        """
        store = self._apiref_symbol_store
        if store is None or getattr(repository, "source_kind", None) != "apiref":
            return
        # Imported lazily: the publisher pulls in adcs.ingestion.chunking, which
        # would re-enter adcs.ingestion's package init during module import.
        from adcs.indexing.apiref_legacy_staging import CanonicalUrlRewritingStaging
        from adcs.indexing.apiref_symbol_publisher import ApiRefSymbolPublisher

        repo_id = getattr(repository, "repo_id", "")
        try:
            # Repair symbol identity from the canonical_url at publish time: the
            # converter's path-derived symbol_fqn leaks the repo-dir / locale /
            # language prefix (e.g. "Aspose.Cells.English.Java.Com.aspose.cells.X").
            # The wrapper rewrites symbol_fqn/doc_type from the clean URL so the
            # store gets correct, queryable FQNs.
            result = ApiRefSymbolPublisher(
                store=store,
                staging=CanonicalUrlRewritingStaging(self._canonical_staging_store),
            ).publish(repo_ids=[repo_id], snapshot_id=snapshot_id or repo_id)
            logger.info(
                "Published %d API-reference symbols for %s (snapshot=%s).",
                result.symbols_written,
                repo_id,
                snapshot_id or repo_id,
            )
        except Exception:
            logger.warning(
                "API-reference symbol publish failed for %s; index publish unaffected.",
                repo_id,
                exc_info=True,
            )

    def run(
        self,
        *,
        repo_ids: Sequence[str] | None = None,
        mode: IngestionRunMode = IngestionRunMode.PUBLISH,
        partial_publish_threshold_pct: int | None = None,
        metadata_quarantine_policy: str | MetadataQuarantinePolicy | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        dry_run: bool = False,
        force_full_reindex: bool = False,
        bypass_staging_replay: bool = False,
        semantic_review_trigger_type: SemanticReviewTriggerType = "major_change",
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        """Execute one Hugo parse + normalize operation and persist result in memory."""
        normalized_repo_ids = _normalize_repo_ids(repo_ids)
        threshold_pct = self._resolve_threshold_pct(partial_publish_threshold_pct)
        resolved_quarantine_policy = self._resolve_metadata_quarantine_policy(
            metadata_quarantine_policy
        )
        normalized_idempotency_key = _normalize_idempotency_key(idempotency_key)
        effective_mode = IngestionRunMode.VALIDATE_ONLY if dry_run else mode
        conversion_backend = self._llm_runtime_policy.resolve_backend(
            task=IngestionLLMTask.CONVERSION
        )
        request_fingerprint = _build_trigger_request_fingerprint(
            repo_ids=normalized_repo_ids,
            mode=effective_mode,
            threshold_pct=threshold_pct,
            metadata_quarantine_policy=resolved_quarantine_policy,
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            semantic_review_trigger_type=semantic_review_trigger_type,
        )
        idempotency_scope = (
            _build_idempotency_scope(
                repo_ids=normalized_repo_ids,
                mode=effective_mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
            )
            if normalized_idempotency_key is not None
            else None
        )
        idempotency_expires_at: datetime | None = None
        operation_id = str(uuid4())
        if normalized_idempotency_key is not None and idempotency_scope is not None:
            claim = self._ingestion_job_repository.claim_idempotency(
                idempotency_key=normalized_idempotency_key,
                idempotency_scope=idempotency_scope,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint,
                expires_at=_now_utc() + timedelta(seconds=self._idempotency_ttl_seconds),
            )
            operation_id = claim.operation_id
            idempotency_expires_at = claim.expires_at
            if claim.reused:
                return replace(
                    self._resolve_existing_operation_for_idempotent_replay(
                        operation_id=operation_id,
                        requested_mode=mode,
                        effective_mode=effective_mode,
                        dry_run=dry_run,
                        force_full_reindex=force_full_reindex,
                        request_id=request_id,
                        idempotency_key=normalized_idempotency_key,
                        idempotency_scope=idempotency_scope,
                        idempotency_expires_at=idempotency_expires_at,
                        request_fingerprint=request_fingerprint,
                    ),
                    idempotency_reused=True,
                )
        operation = SourceHugoNormalizationOperation(
            operation_id=operation_id,
            status=SourceHugoNormalizationStatus.QUEUED,
            repo_ids=normalized_repo_ids,
            logs=(),
            results=(),
            started_at=None,
            finished_at=None,
            mode=effective_mode,
            requested_mode=mode,
            partial_publish_threshold_pct=threshold_pct,
            metadata_quarantine_policy=resolved_quarantine_policy.value,
            semantic_review_trigger_type=semantic_review_trigger_type,
            conversion_backend=conversion_backend.value,
            prompt_registry_version=self._prompt_registry.registry_version,
            prompt_experiment_id=self._prompt_registry.experiment_id,
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            bypass_staging_replay=bypass_staging_replay,
            request_id=request_id,
            idempotency_key=normalized_idempotency_key,
            idempotency_scope=idempotency_scope,
            idempotency_reused=False,
            idempotency_expires_at=idempotency_expires_at,
            request_fingerprint=request_fingerprint,
            attempt_count=0,
            max_attempts=self._retry_max_attempts,
            resumable=True,
        )
        self._save_operation(operation, append_new=True)
        self._persist_job_placeholder(
            operation=operation,
            mode=effective_mode,
            threshold_pct=threshold_pct,
            request_id=request_id,
            error_message=None,
        )
        if not execute_immediately:
            return operation
        return self.execute_operation(operation_id=operation.operation_id)

    def execute_operation(self, *, operation_id: str) -> SourceHugoNormalizationOperation:
        """Execute one queued ingestion operation by id."""
        operation = self.get_operation(operation_id)
        if operation.status in {
            SourceHugoNormalizationStatus.RUNNING,
            SourceHugoNormalizationStatus.COMPLETED,
            SourceHugoNormalizationStatus.CANCELLED,
        }:
            return operation
        return self._execute_operation_attempt(operation=operation)

    def cancel_operation(
        self,
        *,
        operation_id: str,
        request_id: str | None = None,
    ) -> SourceHugoNormalizationOperation:
        """Request cancellation for ingestion operation."""
        operation = self.get_operation(operation_id)
        if operation.status in {
            SourceHugoNormalizationStatus.COMPLETED,
            SourceHugoNormalizationStatus.CANCELLED,
        }:
            return operation

        now = _now_utc()
        resolved_request_id = request_id or operation.request_id
        if operation.status is SourceHugoNormalizationStatus.RUNNING:
            updated = replace(
                operation,
                status=SourceHugoNormalizationStatus.CANCEL_REQUESTED,
                request_id=resolved_request_id,
                cancel_requested_at=now,
                resumable=True,
            )
            error_message = "Cancellation requested."
        else:
            updated = replace(
                operation,
                status=SourceHugoNormalizationStatus.CANCELLED,
                request_id=resolved_request_id,
                cancel_requested_at=now,
                cancelled_at=now,
                finished_at=now,
                resumable=True,
                logs=operation.logs
                + (
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line="[cancelled] operation cancelled before execution.",
                    ),
                ),
            )
            error_message = "Cancelled before execution."

        self._save_operation(updated)
        self._persist_job_placeholder(
            operation=updated,
            mode=updated.mode,
            threshold_pct=updated.partial_publish_threshold_pct,
            request_id=updated.request_id,
            error_message=error_message,
        )
        return updated

    def retry_operation(
        self,
        *,
        operation_id: str,
        request_id: str | None = None,
        force: bool = False,
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        """Retry failed/retry_scheduled operation respecting retry policy."""
        operation = self.get_operation(operation_id)
        if operation.status not in {
            SourceHugoNormalizationStatus.RETRY_SCHEDULED,
            SourceHugoNormalizationStatus.FAILED,
        }:
            msg = "Retry is allowed only for retry_scheduled or failed operations."
            raise ValueError(msg)
        if (
            operation.status is SourceHugoNormalizationStatus.RETRY_SCHEDULED
            and operation.next_retry_at is not None
            and operation.next_retry_at > _now_utc()
            and not force
        ):
            msg = "Retry backoff window is active; use force=true to bypass."
            raise ValueError(msg)
        if operation.attempt_count >= operation.max_attempts:
            msg = "Retry limit reached for this operation."
            raise ValueError(msg)

        queued_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.QUEUED,
            request_id=request_id or operation.request_id,
            finished_at=None,
            next_retry_at=None,
            cancel_requested_at=None,
            cancelled_at=None,
            resumable=True,
        )
        self._save_operation(queued_operation)
        self._persist_job_placeholder(
            operation=queued_operation,
            mode=queued_operation.mode,
            threshold_pct=queued_operation.partial_publish_threshold_pct,
            request_id=queued_operation.request_id,
            error_message=None,
        )
        if not execute_immediately:
            return queued_operation
        return self.execute_operation(operation_id=queued_operation.operation_id)

    def resume_operation(
        self,
        *,
        operation_id: str,
        request_id: str | None = None,
        execute_immediately: bool = True,
    ) -> SourceHugoNormalizationOperation:
        """Resume cancelled/failed operation with reset retry budget."""
        operation = self.get_operation(operation_id)
        if operation.status not in {
            SourceHugoNormalizationStatus.CANCELLED,
            SourceHugoNormalizationStatus.FAILED,
            SourceHugoNormalizationStatus.RETRY_SCHEDULED,
        }:
            msg = "Resume is allowed only for cancelled, failed, or retry_scheduled operations."
            raise ValueError(msg)

        resumed_max_attempts = operation.max_attempts
        if operation.attempt_count >= resumed_max_attempts:
            resumed_max_attempts = operation.attempt_count + self._retry_max_attempts

        queued_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.QUEUED,
            request_id=request_id or operation.request_id,
            finished_at=None,
            next_retry_at=None,
            cancel_requested_at=None,
            cancelled_at=None,
            max_attempts=resumed_max_attempts,
            resumable=True,
        )
        self._save_operation(queued_operation)
        self._persist_job_placeholder(
            operation=queued_operation,
            mode=queued_operation.mode,
            threshold_pct=queued_operation.partial_publish_threshold_pct,
            request_id=queued_operation.request_id,
            error_message=None,
        )
        if not execute_immediately:
            return queued_operation
        return self.execute_operation(operation_id=queued_operation.operation_id)

    def _execute_operation_attempt(
        self,
        *,
        operation: SourceHugoNormalizationOperation,
    ) -> SourceHugoNormalizationOperation:
        if operation.cancel_requested_at is not None:
            cancelled = replace(
                operation,
                status=SourceHugoNormalizationStatus.CANCELLED,
                cancelled_at=_now_utc(),
                finished_at=_now_utc(),
                resumable=True,
                logs=operation.logs
                + (
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line="[cancelled] cancellation request acknowledged before run.",
                    ),
                ),
            )
            self._save_operation(cancelled)
            self._persist_job_placeholder(
                operation=cancelled,
                mode=cancelled.mode,
                threshold_pct=cancelled.partial_publish_threshold_pct,
                request_id=cancelled.request_id,
                error_message="Cancelled before run start.",
            )
            return cancelled

        running_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.RUNNING,
            started_at=operation.started_at or _now_utc(),
            finished_at=None,
            attempt_count=min(operation.max_attempts, operation.attempt_count + 1),
            next_retry_at=None,
            cancel_requested_at=None,
            cancelled_at=None,
            logs=operation.logs
            + (
                SourceHugoNormalizationLogLine(
                    stream="stdout",
                    line=(
                        "[runtime_policy] "
                        f"task=conversion backend={operation.conversion_backend}"
                    ),
                ),
                SourceHugoNormalizationLogLine(
                    stream="stdout",
                    line=(
                        "[prompt_registry] "
                        f"version={operation.prompt_registry_version} "
                        f"experiment={operation.prompt_experiment_id}"
                    ),
                ),
            ),
            resumable=False,
        )
        self._save_operation(running_operation)
        self._persist_job_placeholder(
            operation=running_operation,
            mode=running_operation.mode,
            threshold_pct=running_operation.partial_publish_threshold_pct,
            request_id=running_operation.request_id,
            error_message=None,
        )

        try:
            registry_service = SourceRegistryService(
                registry_path=self._registry_path,
                workspace_root=self._workspace_root,
            )
            repositories, unknown_repo_ids = _select_repositories(
                registry_service, running_operation.repo_ids
            )

            logs: list[SourceHugoNormalizationLogLine] = []
            results: list[SourceHugoNormalizationResult] = []
            # Resilience: an unregistered/mistyped repo_id is skipped (logged), it
            # never aborts the run. The run still completes for the known repos.
            for unknown_id in unknown_repo_ids:
                logs.append(
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=(
                            f"[skipped] repo={unknown_id} is not in the source "
                            "registry — skipped; run continues."
                        ),
                    )
                )
            conversion_backend = _coerce_llm_backend(
                running_operation.conversion_backend
            )
            for repository in repositories:
                if self._is_cancel_requested(operation_id=running_operation.operation_id):
                    cancelled = replace(
                        running_operation,
                        status=SourceHugoNormalizationStatus.CANCELLED,
                        cancel_requested_at=_now_utc(),
                        cancelled_at=_now_utc(),
                        finished_at=_now_utc(),
                        logs=running_operation.logs
                        + (
                            SourceHugoNormalizationLogLine(
                                stream="stderr",
                                line="[cancelled] cancellation request applied during execution.",
                            ),
                        ),
                        resumable=True,
                    )
                    self._save_operation(cancelled)
                    self._persist_job_placeholder(
                        operation=cancelled,
                        mode=cancelled.mode,
                        threshold_pct=cancelled.partial_publish_threshold_pct,
                        request_id=cancelled.request_id,
                        error_message="Cancelled during execution.",
                    )
                    return cancelled

                try:
                    result = self._normalize_repository(
                        repository,
                        mode=running_operation.mode,
                        partial_publish_threshold_pct=(
                            running_operation.partial_publish_threshold_pct
                        ),
                        metadata_quarantine_policy=normalize_metadata_quarantine_policy(
                            running_operation.metadata_quarantine_policy
                        ),
                        operation_id=running_operation.operation_id,
                        request_id=running_operation.request_id,
                        dry_run=running_operation.dry_run,
                        force_full_reindex=running_operation.force_full_reindex,
                        bypass_staging_replay=running_operation.bypass_staging_replay,
                        semantic_review_trigger_type=(
                            running_operation.semantic_review_trigger_type
                        ),
                        conversion_backend=conversion_backend,
                    )
                except OSError:
                    # Transient I/O error: let the batch-level handler apply the
                    # retry/backoff policy rather than silently isolating it.
                    raise
                except Exception as repo_exc:
                    # Resilience: isolate ANY single repo's failure (parse,
                    # validation, or an unexpected error type) — log it and keep
                    # going so one bad repo never aborts the whole batch under any
                    # condition.
                    logs.append(
                        SourceHugoNormalizationLogLine(
                            stream="stderr",
                            line=(
                                f"[skipped] repo={repository.repo_id} failed and was "
                                f"isolated (run continues): {repo_exc!r}"
                            ),
                        )
                    )
                    continue
                results.append(result)
                fallback_reason = result.indexing_summary.incremental_fallback_reason or "none"
                force_reindex_text = str(running_operation.force_full_reindex).lower()
                logs.append(
                    SourceHugoNormalizationLogLine(
                        stream="stdout",
                        line=(
                            f"[ok] repo={repository.repo_id} "
                            f"pages={result.parsed_pages_count} "
                            f"warnings={result.parse_warnings_count} "
                            f"canonical_documents={len(result.canonical_documents)} "
                            f"chunks={len(result.chunk_records)} "
                            f"decision={result.indexing_summary.decision.value} "
                            f"snapshot_id={result.indexing_summary.snapshot_id or 'none'} "
                            f"mode={running_operation.mode.value} "
                            f"dry_run={str(running_operation.dry_run).lower()} "
                            f"force_full_reindex={force_reindex_text} "
                            f"error_ratio={result.indexing_summary.error_ratio:.4f} "
                            f"incremental_mode={result.indexing_summary.incremental_mode} "
                            "incremental_detection="
                            f"{result.indexing_summary.incremental_detection_strategy} "
                            f"files[new={result.indexing_summary.file_new_count},"
                            f"changed={result.indexing_summary.file_changed_count},"
                            f"unchanged={result.indexing_summary.file_unchanged_count},"
                            f"removed={result.indexing_summary.file_removed_count}] "
                            f"chunks[new={result.indexing_summary.chunk_new_count},"
                            f"changed={result.indexing_summary.chunk_changed_count},"
                            f"unchanged={result.indexing_summary.chunk_unchanged_count},"
                            f"removed={result.indexing_summary.chunk_removed_count}] "
                            f"quarantine={result.metadata_quarantine.total_count} "
                            f"remap_applied={result.canonical_url_mapping.remap_applied_count} "
                            f"fallback={fallback_reason} "
                            f"staging_replay={str(result.staging_replay_used).lower()}"
                        ),
                    )
                )

            completed_operation = replace(
                running_operation,
                status=SourceHugoNormalizationStatus.COMPLETED,
                logs=running_operation.logs + tuple(logs),
                results=tuple(results),
                finished_at=_now_utc(),
                last_error_kind=None,
                resumable=False,
            )
            self._save_operation(completed_operation)
            self._persist_job_placeholder(
                operation=completed_operation,
                mode=completed_operation.mode,
                threshold_pct=completed_operation.partial_publish_threshold_pct,
                request_id=completed_operation.request_id,
                error_message=None,
            )
            return completed_operation
        except OSError as exc:
            return self._handle_transient_error(operation=running_operation, error=exc)
        except (
            SourceRegistryValidationError,
            SourceRegistryLookupError,
            HugoParseFatalError,
            ValueError,
        ) as exc:
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.INGESTION_CRITICAL_FAIL,
                message="Ingestion operation failed before publish decision.",
                details={
                    "repo_ids": list(running_operation.repo_ids),
                    "mode": running_operation.mode.value,
                    "requested_mode": running_operation.requested_mode.value,
                    "threshold_pct": running_operation.partial_publish_threshold_pct,
                    "dry_run": running_operation.dry_run,
                    "force_full_reindex": running_operation.force_full_reindex,
                    "attempt_count": running_operation.attempt_count,
                    "max_attempts": running_operation.max_attempts,
                    "error": str(exc),
                },
            )
            notification = self._notification_service.notify_event(event)
            failed_operation = replace(
                running_operation,
                status=SourceHugoNormalizationStatus.FAILED,
                logs=running_operation.logs
                + (
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=f"[error] {exc}",
                    ),
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=(
                            f"[critical_event] event_id={event.event_id} "
                            f"event_type={event.event_type.value}"
                        ),
                    ),
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=(
                            f"[notification] notification_id={notification.notification_id} "
                            f"status={notification.status.value}"
                        ),
                    ),
                ),
                finished_at=_now_utc(),
                last_error_kind="persistent_error",
                resumable=True,
            )
            self._save_operation(failed_operation)
            self._persist_job_placeholder(
                operation=failed_operation,
                mode=failed_operation.mode,
                threshold_pct=failed_operation.partial_publish_threshold_pct,
                request_id=failed_operation.request_id,
                error_message=str(exc),
            )
            return failed_operation

    def _handle_transient_error(
        self,
        *,
        operation: SourceHugoNormalizationOperation,
        error: OSError,
    ) -> SourceHugoNormalizationOperation:
        backoff_seconds = _compute_retry_backoff_seconds(
            attempt_number=operation.attempt_count,
            base_seconds=self._retry_backoff_base_seconds,
            max_seconds=self._retry_backoff_max_seconds,
        )
        if operation.attempt_count < operation.max_attempts:
            retry_at = _now_utc() + timedelta(seconds=backoff_seconds)
            scheduled_operation = replace(
                operation,
                status=SourceHugoNormalizationStatus.RETRY_SCHEDULED,
                finished_at=_now_utc(),
                next_retry_at=retry_at,
                last_error_kind="transient_error",
                resumable=True,
                logs=operation.logs
                + (
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=f"[retry_scheduled] {error}",
                    ),
                    SourceHugoNormalizationLogLine(
                        stream="stderr",
                        line=(
                            f"[retry_backoff] attempt={operation.attempt_count} "
                            f"max_attempts={operation.max_attempts} "
                            f"backoff_seconds={backoff_seconds}"
                        ),
                    ),
                ),
            )
            self._save_operation(scheduled_operation)
            self._persist_job_placeholder(
                operation=scheduled_operation,
                mode=scheduled_operation.mode,
                threshold_pct=scheduled_operation.partial_publish_threshold_pct,
                request_id=scheduled_operation.request_id,
                error_message=str(error),
            )
            return scheduled_operation

        failed_operation = replace(
            operation,
            status=SourceHugoNormalizationStatus.FAILED,
            finished_at=_now_utc(),
            last_error_kind="transient_exhausted",
            resumable=True,
            logs=operation.logs
            + (
                SourceHugoNormalizationLogLine(
                    stream="stderr",
                    line=f"[error] {error}",
                ),
                SourceHugoNormalizationLogLine(
                    stream="stderr",
                    line=(
                        f"[retry_exhausted] attempts={operation.attempt_count} "
                        f"max_attempts={operation.max_attempts}"
                    ),
                ),
            ),
        )
        self._save_operation(failed_operation)
        self._persist_job_placeholder(
            operation=failed_operation,
            mode=failed_operation.mode,
            threshold_pct=failed_operation.partial_publish_threshold_pct,
            request_id=failed_operation.request_id,
            error_message=str(error),
        )
        return failed_operation

    def _is_cancel_requested(self, *, operation_id: str) -> bool:
        with self._lock:
            operation = self._operations.get(operation_id)
        persisted_state = self._operation_state_store.load(operation_id)
        if persisted_state is not None:
            if operation is None or (
                operation.cancel_requested_at != persisted_state.cancel_requested_at
                or operation.status is not persisted_state.status
            ):
                self._save_operation(persisted_state, append_new=True)
            operation = persisted_state
        if operation is None:
            return False
        return (
            operation.cancel_requested_at is not None
            or operation.status is SourceHugoNormalizationStatus.CANCEL_REQUESTED
        )

    def _resolve_existing_operation_for_idempotent_replay(
        self,
        *,
        operation_id: str,
        requested_mode: IngestionRunMode,
        effective_mode: IngestionRunMode,
        dry_run: bool,
        force_full_reindex: bool,
        request_id: str | None,
        idempotency_key: str,
        idempotency_scope: str,
        idempotency_expires_at: datetime | None,
        request_fingerprint: str,
    ) -> SourceHugoNormalizationOperation:
        with self._lock:
            existing_operation = self._operations.get(operation_id)
        if existing_operation is not None:
            return existing_operation

        persisted_state = self._operation_state_store.load(operation_id)
        if persisted_state is not None:
            self._save_operation(persisted_state, append_new=True)
            return persisted_state

        job_record = self._ingestion_job_repository.get(operation_id)
        if job_record is not None:
            resolved_status = _coerce_operation_status(job_record.status)
            resolved_mode = _coerce_ingestion_mode(job_record.mode, fallback=effective_mode)
            return SourceHugoNormalizationOperation(
                operation_id=job_record.operation_id,
                status=resolved_status,
                repo_ids=job_record.repo_ids,
                logs=(),
                results=(),
                started_at=job_record.started_at,
                finished_at=job_record.finished_at,
                mode=resolved_mode,
                requested_mode=requested_mode,
                partial_publish_threshold_pct=job_record.partial_publish_threshold_pct,
                metadata_quarantine_policy=self._metadata_quarantine_policy.value,
                semantic_review_trigger_type="major_change",
                conversion_backend=self._llm_runtime_policy.resolve_backend(
                    task=IngestionLLMTask.CONVERSION
                ).value,
                prompt_registry_version=self._prompt_registry.registry_version,
                prompt_experiment_id=self._prompt_registry.experiment_id,
                dry_run=job_record.dry_run or dry_run,
                force_full_reindex=job_record.force_full_reindex or force_full_reindex,
                request_id=job_record.request_id or request_id,
                idempotency_key=job_record.idempotency_key or idempotency_key,
                idempotency_scope=job_record.idempotency_scope or idempotency_scope,
                idempotency_reused=True,
                idempotency_expires_at=(
                    job_record.idempotency_expires_at or idempotency_expires_at
                ),
                request_fingerprint=job_record.request_fingerprint or request_fingerprint,
                attempt_count=job_record.attempt_count,
                max_attempts=job_record.max_attempts,
                next_retry_at=job_record.next_retry_at,
                last_error_kind=job_record.last_error_kind,
                cancel_requested_at=job_record.cancel_requested_at,
                cancelled_at=job_record.cancelled_at,
                resumable=job_record.resumable,
            )

        return SourceHugoNormalizationOperation(
            operation_id=operation_id,
            status=SourceHugoNormalizationStatus.QUEUED,
            repo_ids=(),
            logs=(),
            results=(),
            started_at=None,
            finished_at=None,
            mode=effective_mode,
            requested_mode=requested_mode,
            partial_publish_threshold_pct=self._partial_publish_threshold_pct,
            metadata_quarantine_policy=self._metadata_quarantine_policy.value,
            semantic_review_trigger_type="major_change",
            conversion_backend=self._llm_runtime_policy.resolve_backend(
                task=IngestionLLMTask.CONVERSION
            ).value,
            prompt_registry_version=self._prompt_registry.registry_version,
            prompt_experiment_id=self._prompt_registry.experiment_id,
            dry_run=dry_run,
            force_full_reindex=force_full_reindex,
            request_id=request_id,
            idempotency_key=idempotency_key,
            idempotency_scope=idempotency_scope,
            idempotency_reused=True,
            idempotency_expires_at=idempotency_expires_at,
            request_fingerprint=request_fingerprint,
            attempt_count=0,
            max_attempts=self._retry_max_attempts,
            resumable=True,
        )

    def get_operation(self, operation_id: str) -> SourceHugoNormalizationOperation:
        """Return one operation by id."""
        with self._lock:
            operation = self._operations.get(operation_id)

        persisted_state = self._operation_state_store.load(operation_id)
        if persisted_state is not None:
            self._save_operation(persisted_state, append_new=True)
            return persisted_state

        if operation is not None:
            return operation

        persisted = self._ingestion_job_repository.get(operation_id)
        if persisted is not None:
            resolved = self._operation_from_job_record(persisted)
            self._save_operation(resolved, append_new=True)
            return resolved

        msg = f"Source Hugo normalization operation `{operation_id}` was not found."
        raise SourceHugoNormalizationOperationNotFoundError(msg)

    def list_operations(
        self,
        *,
        limit: int = 20,
    ) -> tuple[SourceHugoNormalizationOperation, ...]:
        """List recent operations ordered by most recent first."""
        if limit < 1:
            return ()
        with self._lock:
            operation_ids = list(reversed(self._operation_order[-limit:]))
            in_memory = tuple(self._operations[operation_id] for operation_id in operation_ids)
        hydrated: list[SourceHugoNormalizationOperation] = []
        seen_operation_ids: set[str] = set()
        for record in self._operation_state_store.list(limit=limit):
            hydrated.append(record)
            seen_operation_ids.add(record.operation_id)
            self._save_operation(record, append_new=True)
            if len(hydrated) >= limit:
                return tuple(hydrated[:limit])

        for record in in_memory:
            if record.operation_id in seen_operation_ids:
                continue
            hydrated.append(record)
            seen_operation_ids.add(record.operation_id)
            if len(hydrated) >= limit:
                return tuple(hydrated[:limit])

        persisted_records = self._ingestion_job_repository.list(limit=limit)
        for job_record in persisted_records:
            if job_record.operation_id in seen_operation_ids:
                continue
            hydrated_operation = self._operation_from_job_record(job_record)
            hydrated.append(hydrated_operation)
            seen_operation_ids.add(job_record.operation_id)
            self._save_operation(hydrated_operation, append_new=True)
            if len(hydrated) >= limit:
                break
        return tuple(hydrated[:limit])

    def list_operation_metadata(
        self,
        *,
        limit: int = 200,
    ) -> tuple[OperationMetadataEnvelope, ...]:
        """Return lightweight metadata envelopes without loading full operation data.

        This is drastically faster than ``list_operations`` for callers that
        only need operation scalars (status, repo_ids, timestamps) and result
        scope summaries (parse_warnings_count, failed_items_count).
        """
        return self._operation_state_store.list_metadata_envelopes(limit=limit)

    def get_latest_chunk_records(
        self,
        *,
        product_id: str | None = None,
        programming_language: str | None = None,
        version: str | None = None,
    ) -> tuple[StageDChunkRecord, ...]:
        """Return chunk records from the most recent completed operation matching scope.

        Uses a two-phase approach to avoid loading multi-GB JSON state files:
        1. Scan lightweight metadata envelopes to find COMPLETED operation IDs.
        2. Load only the single matching operation's full data on demand.
        """
        # --- Phase 1: check in-memory operations first (instant) ---
        with self._lock:
            operation_ids = tuple(reversed(self._operation_order))
            operations = self._operations.copy()
        for operation_id in operation_ids:
            operation = operations[operation_id]
            if operation.status is not SourceHugoNormalizationStatus.COMPLETED:
                continue
            matching_records = _extract_matching_chunks(
                operation, product_id, programming_language, version
            )
            if matching_records:
                return matching_records

        # --- Phase 2: scan metadata envelopes from disk (reads only tiny sidecar files) ---
        seen_operation_ids = set(operations.keys())
        envelopes = self._operation_state_store.list_metadata_envelopes(limit=100)

        # Split into product-relevant and other envelopes so we check
        # likely matches first, avoiding expensive loads of unrelated data.
        relevant: list[str] = []
        other: list[str] = []
        for envelope in envelopes:
            if envelope.record_id in seen_operation_ids:
                continue
            status_value = envelope.record_scalars.get("status", "")
            if status_value != SourceHugoNormalizationStatus.COMPLETED.value:
                continue

            # Use _result_scope summary (if present) to skip operations that
            # definitely contain no matching chunks — avoids loading multi-GB files.
            result_scope = envelope.record_scalars.get("_result_scope")
            if isinstance(result_scope, list) and product_id:
                if not _scope_summary_may_contain(
                    result_scope, product_id, programming_language
                ):
                    continue

            # Heuristic: prioritise operations whose repo_ids match the product.
            repo_ids = envelope.record_scalars.get("repo_ids", [])
            if not isinstance(repo_ids, list):
                repo_ids = []
            if product_id and _repo_ids_hint_match(repo_ids, product_id):
                relevant.append(envelope.record_id)
            else:
                other.append(envelope.record_id)

        for record_id in (*relevant, *other):
            full_operation = self._operation_state_store.load(record_id)
            if full_operation is None:
                continue
            matching_records = _extract_matching_chunks(
                full_operation, product_id, programming_language, version
            )
            if not matching_records:
                # The persisted state may have had its heavy chunk payload pruned
                # (very large operations); recover the chunks from the canonical
                # staging store, which is the durable home of the payload.
                matching_records = self._recover_chunks_from_staging(
                    operation=full_operation,
                    product_id=product_id,
                    programming_language=programming_language,
                    version=version,
                )
            if matching_records:
                return matching_records

        return ()

    def _recover_chunks_from_staging(
        self,
        *,
        operation: SourceHugoNormalizationOperation,
        product_id: str | None,
        programming_language: str | None,
        version: str | None,
    ) -> tuple[StageDChunkRecord, ...]:
        """Recover scope-matching chunks from staging for a pruned operation.

        When :class:`FileSystemOperationStateStore` pruned the inline
        ``chunk_records`` from a very large persisted operation, the chunks are
        still on disk in the canonical staging store. A pruned result is
        recognised by an empty ``chunk_records`` tuple alongside a positive
        ``chunk_records_count`` and a recorded staging manifest. Iteration is
        one-at-a-time and only scope-matching chunks are retained, so peak memory
        is bounded by the matching subset, not the whole repository.
        """
        matching: list[StageDChunkRecord] = []
        for result in operation.results:
            if result.chunk_records or result.chunk_records_count <= 0:
                continue
            if not result.staging_repository_manifest_path:
                continue
            try:
                for chunk in self._canonical_staging_store.iter_chunk_records(
                    repo_id=result.repo_id,
                    source_kind=result.source_kind,
                    source_revision=result.indexing_summary.source_revision,
                    snapshot_tier=StagingSnapshotTier.PUBLISH,
                ):
                    if (
                        _scope_match(chunk.product_id, product_id)
                        and _scope_match(chunk.programming_language, programming_language)
                        and _scope_match(chunk.version, version)
                    ):
                        matching.append(chunk)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                logger.warning(
                    "Staging recovery failed for pruned operation %s repo %s: %s",
                    operation.operation_id,
                    result.repo_id,
                    exc,
                )
                continue
        return tuple(matching)

    @staticmethod
    def _discover_markdown_files(
        *,
        repo_root: Path,
        repository: SourceRepository,
    ) -> list[Path]:
        """Discover markdown files, applying doc_locale filter when configured.

        When ``ingestion.doc_locale_filter`` is set in the source registry,
        only files under matching locale subdirectories are returned.  This
        dramatically reduces the number of files for apiref repos that ship
        translations (chinese, russian, etc.).

        Supports two common layouts:
        - Flat: ``<repo_root>/<locale>/<lang>/...``
        - Hugo site: ``<repo_root>/content/<lang>/<locale>/...``
        """
        scope = repository.ingestion_scope
        if not scope.has_locale_filter:
            return [p for p in repo_root.rglob("*.md") if p.is_file()]

        locale_set = {v.casefold() for v in scope.doc_locale_filter}
        all_files: list[Path] = []

        # Flat layout: <repo_root>/<locale>/...
        for child in repo_root.iterdir():
            if child.is_dir() and child.name.casefold() in locale_set:
                all_files.extend(p for p in child.rglob("*.md") if p.is_file())

        # Hugo site layout: <repo_root>/content/<lang>/<locale>/...
        content_dir = repo_root / "content"
        if content_dir.is_dir():
            for lang_dir in content_dir.iterdir():
                if not lang_dir.is_dir():
                    continue
                for locale_dir in lang_dir.iterdir():
                    if locale_dir.is_dir() and locale_dir.name.casefold() in locale_set:
                        all_files.extend(
                            p for p in locale_dir.rglob("*.md") if p.is_file()
                        )

        return all_files

    def _normalize_repository(
        self,
        repository: SourceRepository,
        *,
        mode: IngestionRunMode,
        partial_publish_threshold_pct: int,
        metadata_quarantine_policy: MetadataQuarantinePolicy,
        operation_id: str,
        request_id: str | None,
        dry_run: bool,
        force_full_reindex: bool,
        bypass_staging_replay: bool = False,
        semantic_review_trigger_type: SemanticReviewTriggerType = "major_change",
        conversion_backend: IngestionLLMBackend = IngestionLLMBackend.DETERMINISTIC,
    ) -> SourceHugoNormalizationResult:
        repo_root = (self._workspace_root / repository.git.submodule_path).resolve()
        if not repo_root.exists():
            msg = (
                "Cannot normalize repository: source root does not exist at "
                f"`{repository.git.submodule_path.as_posix()}`."
            )
            raise FileNotFoundError(msg)

        _log_memory_snapshot("normalize_repo:start", repo_id=repository.repo_id)
        markdown_files: list[Path] = []
        pages: list[HugoNormalizedPage] = []
        canonical_documents: list[NormalizedDocument] = []
        failed_items: list[SourceHugoNormalizationFailedItem] = []
        metadata_quarantine_items: list[MetadataQuarantineItem] = []
        canonical_mapping_conflicts: list[CanonicalUrlMappingConflict] = []
        parsed_chunk_records: list[StageDChunkRecord] = []
        prompt_assignments: list[ConversionPromptAssignment] = []
        parse_warnings_by_source_path: dict[str, int] = {}
        parse_warnings_count = 0
        remap_applied_count = 0
        remap_override_count = 0
        staging_replay_used = False
        canonical_mapping_registries: dict[
            CanonicalUrlMappingContext, CanonicalUrlMappingRegistry
        ] = {}
        scanned_markdown_files: list[_ScannedMarkdownFile] = []
        event_records: list[str] = []
        event_types: list[str] = []
        english_only_violations: tuple[EnglishOnlyGateViolation, ...] = ()
        notification_dispatches: list[SmtpNotificationDispatch] = []
        # Write canonical documents + chunk records to disk incrementally via a
        # streaming writer during the parse loop. This gives mid-parse crash
        # recovery (the REVIEW-tier staging is durable) without depending on
        # `_finalize_result` running to completion. The PUBLISH-tier snapshot
        # is produced from that REVIEW snapshot when publish succeeds.
        streaming_writer: RepositoryStreamingWriter | None = None
        streaming_writer_close_result: CanonicalStagingWriteResult | None = None
        # Incremental gate-input accumulators so the parse loop does not need
        # to grow `pages` / `canonical_documents` lists in memory.
        # `pages_count` / `canonical_documents_count` retain the cardinality
        # used by `SourceHugoNormalizationResult.parsed_pages_count` and the
        # review artifact. The two lists below are kept (always empty in
        # streaming mode) only to satisfy call sites that still take them as
        # `Sequence` arguments.
        conversion_gate_accumulator = _ConversionGateAccumulator()
        publish_safety_gate_accumulator = _PublishSafetyGateAccumulator()
        pages_count = 0
        canonical_documents_count = 0

        source_revision = self._source_revision_resolver(repo_root)

        baseline_state: IncrementalBaselineState | None = None
        baseline_load_fallback_reason: str | None = None
        try:
            baseline_state = self._incremental_state_store.load(repo_id=repository.repo_id)
        except IncrementalBaselineCorruptError:
            baseline_load_fallback_reason = "baseline_corrupt"

        staging_replay_snapshot: CanonicalStagingReplaySnapshot | None = None
        staging_replay_tier: StagingSnapshotTier | None = None
        # Replay is a performance optimization that reuses previously published
        # staging artifacts for the same source_revision instead of re-parsing.
        # It must be skipped when the caller explicitly asks to regenerate
        # staging (e.g. after a layout-detection change or chunking policy
        # update). `bypass_staging_replay=True` forces a fresh Hugo parse even
        # when `force_full_reindex=True`.
        #
        # Tier preference: PUBLISH is preferred (canonical, validated set), but
        # REVIEW is used as a fallback when a prior run wrote staging but
        # publish never succeeded (e.g. mid-embedding crash). REVIEW staging
        # still carries the fully-normalized canonical_documents / chunk_records
        # for the same source_revision, so it is sufficient for resume.
        if force_full_reindex and not bypass_staging_replay:
            staging_replay_integrity_error: CanonicalStagingSnapshotIntegrityError | None = None
            for candidate_tier in (
                StagingSnapshotTier.PUBLISH,
                StagingSnapshotTier.REVIEW,
            ):
                try:
                    candidate_snapshot = (
                        self._canonical_staging_store.load_repository_snapshot(
                            repo_id=repository.repo_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            snapshot_tier=candidate_tier,
                        )
                    )
                except CanonicalStagingSnapshotIntegrityError as exc:
                    # Keep the last integrity error to surface if no tier loads.
                    staging_replay_integrity_error = exc
                    continue
                if candidate_snapshot is not None:
                    staging_replay_snapshot = candidate_snapshot
                    staging_replay_tier = candidate_tier
                    logger.info(
                        "Loaded staging replay snapshot tier=%s repo=%s revision=%s",
                        candidate_tier.value,
                        repository.repo_id,
                        source_revision,
                    )
                    break
            if (
                staging_replay_snapshot is None
                and staging_replay_integrity_error is not None
            ):
                # All candidate tiers failed integrity — escalate.
                event = self._critical_event_publisher.emit(
                    severity=CriticalEventSeverity.CRITICAL,
                    event_type=CriticalEventType.INGESTION_CRITICAL_FAIL,
                    message="Canonical staging replay snapshot failed integrity checks.",
                    details={
                        "repo_id": repository.repo_id,
                        "source_kind": repository.source_kind,
                        "source_revision": source_revision,
                        "manifest_path": staging_replay_integrity_error.manifest_path,
                        "violations": list(staging_replay_integrity_error.violations),
                        "job_id": operation_id,
                        "request_id": request_id,
                    },
                )
                notification = self._notification_service.notify_event(event)
                event_records.append(event.event_id)
                event_types.append(event.event_type.value)
                notification_dispatches.append(notification)
                failed_items.append(
                    SourceHugoNormalizationFailedItem(
                        source_path=(repository.git.submodule_path / "_staging").as_posix(),
                        error_code="STAGING_REPLAY_INTEGRITY_ERROR",
                        message=str(staging_replay_integrity_error),
                    )
                )
            if staging_replay_snapshot is not None:
                staging_replay_used = True
                # Feed the snapshot through accumulators instead of
                # materialising it as `canonical_documents` / `pages` lists.
                # `parsed_chunk_records` is still retained for the downstream
                # steps (incremental diff, index publish), which take a list.
                for replayed_document in staging_replay_snapshot.canonical_documents:
                    conversion_gate_accumulator.observe_document(replayed_document)
                    canonical_documents_count += 1
                for replayed_chunk in staging_replay_snapshot.chunk_records:
                    publish_safety_gate_accumulator.observe_chunk(replayed_chunk)
                parsed_chunk_records.extend(staging_replay_snapshot.chunk_records)
                _log_memory_snapshot(
                    "normalize_repo:staging_replay_loaded",
                    repo_id=repository.repo_id,
                    tier=staging_replay_tier.value if staging_replay_tier else "unknown",
                    docs=len(staging_replay_snapshot.canonical_documents),
                    chunks=len(staging_replay_snapshot.chunk_records),
                )

        current_file_checksums: dict[str, str]
        if staging_replay_snapshot is not None:
            current_file_checksums = {
                source_path: checksum
                for source_path, checksum in sorted(
                    staging_replay_snapshot.file_checksums.items()
                )
            }
        else:
            markdown_files = sorted(
                self._discover_markdown_files(repo_root=repo_root, repository=repository)
            )
            if self._english_only_strict:
                english_doc_count, non_english_locales = summarize_english_documents(
                    path.relative_to(repo_root).parts for path in markdown_files
                )
                english_only_violations = evaluate_english_only_gate(
                    repo_id=repository.repo_id,
                    layout_detection=repository.layout_detection,
                    discovered_locales=non_english_locales,
                    english_doc_count=english_doc_count,
                )
            for markdown_file in markdown_files:
                relative_repo_path = markdown_file.relative_to(repo_root).as_posix()
                source_path = (repository.git.submodule_path / relative_repo_path).as_posix()
                # Read once for checksum, then release the text. Parse-stage
                # re-reads the file on demand from `markdown_file` to keep peak
                # RAM bounded — see _ScannedMarkdownFile docstring.
                try:
                    raw_markdown = markdown_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raw_markdown = markdown_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError as exc:
                    failed_items.append(
                        SourceHugoNormalizationFailedItem(
                            source_path=source_path,
                            error_code="READ_ERROR",
                            message=str(exc),
                        )
                    )
                    continue
                checksum = checksum_text(raw_markdown)
                del raw_markdown  # explicit release before next iteration
                scanned_markdown_files.append(
                    _ScannedMarkdownFile(
                        markdown_file=markdown_file,
                        source_path=source_path,
                        relative_repo_path=relative_repo_path,
                        checksum=checksum,
                    )
                )
            current_file_checksums = {
                scanned_file.source_path: scanned_file.checksum
                for scanned_file in scanned_markdown_files
            }
            _log_memory_snapshot(
                "normalize_repo:after_scan",
                repo_id=repository.repo_id,
                scanned=len(scanned_markdown_files),
                failed=len(failed_items),
            )

        # Open a streaming staging writer in REVIEW tier. Each
        # successfully-chunked document is appended to disk inside the parse
        # loop, so a mid-parse crash leaves a durable
        # `_repo-staging-review/<repo>/runs/<op>/` snapshot that the next
        # run picks up via the REVIEW-tier fallback in staging_replay.
        if staging_replay_snapshot is None and not dry_run:
            try:
                streaming_writer = (
                    self._canonical_staging_store.open_repository_streaming_write(
                        repo_id=repository.repo_id,
                        product_id=repository.product_id,
                        source_kind=repository.source_kind,
                        source_revision=source_revision,
                        snapshot_tier=StagingSnapshotTier.REVIEW,
                        operation_id=operation_id,
                        file_checksums=current_file_checksums,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to open streaming staging writer for %s @ %s: %s — "
                    "ingestion will continue with the legacy in-memory writer.",
                    repository.repo_id,
                    source_revision,
                    exc,
                )
                streaming_writer = None

        file_diff_fallback_reason = baseline_load_fallback_reason
        if force_full_reindex:
            file_diff_fallback_reason = INCREMENTAL_FALLBACK_REASON_FORCED_REINDEX
        incremental_selection = _select_incremental_file_diff_plan(
            repository=repository,
            source_revision=source_revision,
            current_file_checksums=current_file_checksums,
            baseline_state=baseline_state,
            force_full_reindex=force_full_reindex,
            fallback_reason=file_diff_fallback_reason,
            workspace_root=self._workspace_root,
        )
        file_diff_plan = incremental_selection.file_diff_plan
        files_to_process = set(file_diff_plan.files_to_process)

        def _registry_for_context(
            context: CanonicalUrlMappingContext,
        ) -> CanonicalUrlMappingRegistry:
            registry = canonical_mapping_registries.get(context)
            if registry is None:
                registry = self._canonical_url_mapping_store.load(context=context)
                canonical_mapping_registries[context] = registry
            return registry

        # Intra-normalize checkpoint resume: if a prior partial run for the
        # same source_revision crashed, load its accumulated state so the
        # parse loop only processes files that weren't completed before.
        processed_source_paths: set[str] = set()
        if staging_replay_snapshot is None:
            intra_checkpoint = _load_intra_checkpoint(repository.repo_id, source_revision)
            if intra_checkpoint is not None:
                processed_source_paths.update(intra_checkpoint.processed_source_paths)
                parsed_chunk_records.extend(intra_checkpoint.parsed_chunk_records)
                failed_items.extend(intra_checkpoint.failed_items)
                metadata_quarantine_items.extend(intra_checkpoint.metadata_quarantine_items)
                canonical_mapping_conflicts.extend(
                    intra_checkpoint.canonical_mapping_conflicts
                )
                parse_warnings_count = intra_checkpoint.parse_warnings_count
                remap_applied_count = intra_checkpoint.remap_applied_count
                remap_override_count = intra_checkpoint.remap_override_count
                parse_warnings_by_source_path.update(
                    intra_checkpoint.parse_warnings_by_source_path
                )
                prompt_assignments.extend(intra_checkpoint.prompt_assignments)
                # Restore the in-memory registry state so newly-discovered
                # remap mappings from the prior partial run survive the resume.
                canonical_mapping_registries.update(
                    intra_checkpoint.canonical_mapping_registries
                )
                # Restore counters and gate accumulators (the checkpoint does
                # not store full lists).
                pages_count = intra_checkpoint.pages_count
                canonical_documents_count = intra_checkpoint.canonical_documents_count
                conversion_gate_accumulator.merge(
                    intra_checkpoint.conversion_gate_accumulator
                )
                publish_safety_gate_accumulator.merge(
                    intra_checkpoint.publish_safety_gate_accumulator
                )
                _log_memory_snapshot(
                    "normalize_repo:intra_checkpoint_resumed",
                    repo_id=repository.repo_id,
                    resumed_files=len(processed_source_paths),
                    docs=canonical_documents_count,
                    chunks=len(parsed_chunk_records),
                )

        if staging_replay_snapshot is None:
            _processed_loop_count = 0
            _new_files_since_checkpoint = 0
            for scanned_file in scanned_markdown_files:
                if scanned_file.source_path not in files_to_process:
                    continue
                if scanned_file.source_path in processed_source_paths:
                    # Already handled by an earlier crashed run — skip.
                    continue
                _processed_loop_count += 1
                # Periodic GC + memory snapshot for large repos. Cheap (≤2ms
                # for gc.collect on healthy heaps) but releases pages whose
                # parser-owned refs have already been replaced by downstream
                # chunked_document/page_chunk_records copies.
                if _processed_loop_count % _MEMORY_GC_INTERVAL == 0:
                    gc.collect()
                    _log_memory_snapshot(
                        "normalize_repo:parse_progress",
                        repo_id=repository.repo_id,
                        processed=_processed_loop_count,
                        pages=len(pages),
                        chunks=len(parsed_chunk_records),
                    )
                prompt_assignment = self._prompt_registry.assign(
                    repo_id=repository.repo_id,
                    source_kind=repository.source_kind,
                    source_path=scanned_file.source_path,
                    fallback_backend=conversion_backend,
                )
                prompt_assignments.append(prompt_assignment)
                # Re-read raw markdown lazily — keeps peak RAM bounded by a
                # single file's text rather than the whole repository.
                try:
                    raw_markdown = scanned_file.markdown_file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raw_markdown = scanned_file.markdown_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError as exc:
                    failed_items.append(
                        SourceHugoNormalizationFailedItem(
                            source_path=scanned_file.source_path,
                            error_code="READ_ERROR",
                            message=str(exc),
                        )
                    )
                    continue
                try:
                    page = self._parser.parse_document(
                        repo_id=repository.repo_id,
                        source_path=scanned_file.source_path,
                        source_kind=repository.source_kind,
                        raw_markdown=raw_markdown,
                        product_id=repository.product_id,
                        product_family=repository.product_family,
                        relative_repo_path=scanned_file.relative_repo_path,
                        layout_detection=repository.layout_detection,
                    )
                    # Parser has copied/consumed raw_markdown into the page
                    # structures; explicit release helps the next iteration.
                    del raw_markdown
                    parse_warnings_by_source_path[scanned_file.source_path] = len(
                        page.parse_warnings
                    )
                    page_quarantine_items = classify_metadata_quarantine(
                        page=page,
                        canonical_base_url=self._canonical_base_url,
                        relative_repo_path=scanned_file.relative_repo_path,
                        layout_detection=repository.layout_detection,
                    )
                    if page_quarantine_items:
                        metadata_quarantine_items.extend(page_quarantine_items)
                        failed_items.append(
                            _to_quarantine_failed_item(
                                source_path=scanned_file.source_path,
                                quarantine_items=page_quarantine_items,
                            )
                        )
                        continue

                    normalized_document = self._converter.convert_page(
                        page=page,
                        source_revision=source_revision,
                    )
                    mapping_context = CanonicalUrlMappingContext.from_values(
                        product_id=normalized_document.document.product_id,
                        source_kind=normalized_document.document.source_kind,
                        programming_language=normalized_document.document.programming_language,
                        version=normalized_document.document.version,
                    )
                    mapping_registry = _registry_for_context(mapping_context)
                    try:
                        remap_pairs = extract_metadata_remap_pairs(
                            metadata=page.metadata,
                            resolved_canonical_url=normalized_document.document.canonical_url,
                            canonical_base_url=self._canonical_base_url,
                        )
                    except ValueError as exc:
                        metadata_quarantine_items.append(
                            MetadataQuarantineItem(
                                source_path=scanned_file.source_path,
                                reason_code=(
                                    MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value
                                ),
                                message=str(exc),
                            )
                        )
                        failed_items.append(
                            SourceHugoNormalizationFailedItem(
                                source_path=scanned_file.source_path,
                                error_code=MetadataQuarantineReasonCode.METADATA_SCHEMA_VIOLATION.value,
                                message=str(exc),
                            )
                        )
                        continue
                    remap_conflicts = mapping_registry.register_mappings(
                        remap_pairs=remap_pairs,
                        source_path=scanned_file.source_path,
                    )
                    for conflict in remap_conflicts:
                        if conflict.conflict_type == "override_persisted":
                            remap_override_count += 1
                        else:
                            canonical_mapping_conflicts.append(conflict)
                            metadata_quarantine_items.append(
                                MetadataQuarantineItem(
                                    source_path=scanned_file.source_path,
                                    reason_code=MetadataQuarantineReasonCode.CANONICAL_REMAP_CONFLICT.value,
                                    message=(
                                        f"Conflicting canonical remap for `{conflict.old_url}` "
                                        f"(`{conflict.existing_new_url}` vs "
                                        f"`{conflict.incoming_new_url}`)."
                                    ),
                                )
                            )
                    if any(
                        conflict.conflict_type == "conflicting_mapping"
                        for conflict in remap_conflicts
                    ):
                        failed_items.append(
                            SourceHugoNormalizationFailedItem(
                                source_path=scanned_file.source_path,
                                error_code=MetadataQuarantineReasonCode.CANONICAL_REMAP_CONFLICT.value,
                                message="Conflicting canonical URL remap mapping encountered.",
                            )
                        )
                        continue

                    remapped_document = _apply_canonical_mapping_to_document(
                        normalized_document=normalized_document,
                        mapping_registry=mapping_registry,
                    )
                    if (
                        remapped_document.document.canonical_url
                        != normalized_document.document.canonical_url
                    ):
                        remap_applied_count += 1
                    chunked_document, page_chunk_records = self._chunking_policy.chunk_document(
                        page=page,
                        normalized_document=remapped_document,
                    )
                    self._validator.validate_or_raise(
                        chunked_document,
                        input_source_path=page.source_path,
                    )
                except HugoParseFatalError as exc:
                    failed_items.append(
                        SourceHugoNormalizationFailedItem(
                            source_path=scanned_file.source_path,
                            error_code=exc.code,
                            message=str(exc),
                        )
                    )
                    continue
                except ValueError as exc:
                    metadata_quarantine_items.append(
                        MetadataQuarantineItem(
                            source_path=scanned_file.source_path,
                            reason_code=(
                                MetadataQuarantineReasonCode.NORMALIZED_DOCUMENT_VALIDATION_ERROR.value
                            ),
                            message=str(exc),
                        )
                    )
                    failed_items.append(
                        SourceHugoNormalizationFailedItem(
                            source_path=scanned_file.source_path,
                            error_code="VALIDATION_ERROR",
                            message=str(exc),
                        )
                    )
                    continue

                # Feed accumulators inline instead of growing
                # `pages` / `canonical_documents` lists. The local `page` /
                # `chunked_document` references go out of scope after this
                # iteration and become eligible for GC, dropping peak RSS.
                conversion_gate_accumulator.observe_page(page)
                conversion_gate_accumulator.observe_document(chunked_document)
                pages_count += 1
                canonical_documents_count += 1
                parse_warnings_count += len(page.parse_warnings)
                for emitted_chunk in page_chunk_records:
                    publish_safety_gate_accumulator.observe_chunk(emitted_chunk)
                parsed_chunk_records.extend(page_chunk_records)
                processed_source_paths.add(scanned_file.source_path)
                _new_files_since_checkpoint += 1
                # Stream-write to disk so a mid-parse crash leaves a durable
                # REVIEW-tier staging snapshot the next run can resume from.
                if streaming_writer is not None:
                    try:
                        streaming_writer.append_document(
                            canonical_document=chunked_document,
                            chunk_records=page_chunk_records,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Streaming append for %s failed: %s — continuing with "
                            "in-memory accumulation; legacy snapshot will be "
                            "written at finalize.",
                            scanned_file.source_path,
                            exc,
                        )

                # Atomic intra-normalize checkpoint dump. References the
                # live lists directly (no copy) so memory impact is bounded
                # by pickle's transient working set, not 2× the working
                # state.
                if (
                    _INTRA_CHECKPOINT_INTERVAL > 0
                    and _new_files_since_checkpoint >= _INTRA_CHECKPOINT_INTERVAL
                ):
                    _save_intra_checkpoint(
                        _IntraNormalizeCheckpoint(
                            schema_version=_INTRA_CHECKPOINT_SCHEMA_VERSION,
                            repo_id=repository.repo_id,
                            source_revision=source_revision,
                            processed_source_paths=list(processed_source_paths),
                            parsed_chunk_records=parsed_chunk_records,
                            failed_items=failed_items,
                            metadata_quarantine_items=metadata_quarantine_items,
                            canonical_mapping_conflicts=canonical_mapping_conflicts,
                            parse_warnings_count=parse_warnings_count,
                            remap_applied_count=remap_applied_count,
                            remap_override_count=remap_override_count,
                            parse_warnings_by_source_path=parse_warnings_by_source_path,
                            prompt_assignments=prompt_assignments,
                            canonical_mapping_registries=canonical_mapping_registries,
                            pages_count=pages_count,
                            canonical_documents_count=canonical_documents_count,
                            conversion_gate_accumulator=conversion_gate_accumulator,
                            publish_safety_gate_accumulator=publish_safety_gate_accumulator,
                        )
                    )
                    _new_files_since_checkpoint = 0
                    _log_memory_snapshot(
                        "normalize_repo:intra_checkpoint_saved",
                        repo_id=repository.repo_id,
                        processed=len(processed_source_paths),
                        docs=len(canonical_documents),
                        chunks=len(parsed_chunk_records),
                    )

            # Parse loop done — force a major GC so downstream stages
            # (publish_orchestrator) start with a clean heap.
            gc.collect()
            _log_memory_snapshot(
                "normalize_repo:after_parse",
                repo_id=repository.repo_id,
                pages=len(pages),
                docs=len(canonical_documents),
                chunks=len(parsed_chunk_records),
                failed=len(failed_items),
            )
            # Parse loop reached the end without crashing → the checkpoint is
            # no longer needed. Downstream stages (publish, finalize) have
            # their own recovery mechanisms.
            _delete_intra_checkpoint(repository.repo_id, source_revision)

            # Finalise the streaming writer now that no more documents will
            # arrive. The resulting REVIEW-tier manifest is durable and
            # serves as the resume point for any later run that re-enters
            # the same (repo_id, source_revision) before publish completes.
            if streaming_writer is not None:
                try:
                    streaming_writer_close_result = streaming_writer.close()
                    _log_memory_snapshot(
                        "normalize_repo:streaming_writer_closed",
                        repo_id=repository.repo_id,
                        docs=streaming_writer_close_result.documents_count,
                        chunks=streaming_writer_close_result.chunk_records_count,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to close streaming staging writer for %s @ %s: %s — "
                        "the partial REVIEW-tier snapshot may be missing the manifest "
                        "but legacy write at finalize will still produce a valid one.",
                        repository.repo_id,
                        source_revision,
                        exc,
                    )

        current_chunk_records = _merge_incremental_chunk_records(
            baseline_state=baseline_state,
            file_diff_plan=file_diff_plan,
            parsed_chunk_records=parsed_chunk_records,
        )
        (
            current_chunk_records,
            remapped_chunk_records_count,
        ) = _apply_canonical_mapping_to_chunk_records(
            chunk_records=current_chunk_records,
            mapping_registries=canonical_mapping_registries,
            mapping_store=self._canonical_url_mapping_store,
        )
        remap_applied_count += remapped_chunk_records_count
        for registry in canonical_mapping_registries.values():
            if registry.is_dirty and not dry_run:
                self._canonical_url_mapping_store.save(registry=registry)

        baseline_chunk_records = baseline_state.chunk_records if baseline_state is not None else ()
        chunk_diff_plan = build_chunk_diff_plan(
            previous_chunk_records=baseline_chunk_records,
            current_chunk_records=current_chunk_records,
        )
        baseline_snapshot_id = baseline_state.snapshot_id if baseline_state is not None else None
        metadata_quarantine_summary = summarize_metadata_quarantine(
            policy_mode=metadata_quarantine_policy,
            items=metadata_quarantine_items,
            sample_limit=self._metadata_quarantine_sample_limit,
        )
        canonical_url_mapping_summary = _build_canonical_url_mapping_summary(
            mapping_registries=canonical_mapping_registries,
            conflicts=canonical_mapping_conflicts,
            remap_applied_count=remap_applied_count,
            remap_override_count=remap_override_count,
        )

        total_items_count = len(current_file_checksums)
        failed_items_count = len(failed_items)
        error_ratio = (
            failed_items_count / total_items_count if total_items_count > 0 else 0.0
        )
        prompt_evaluation = self._prompt_registry.evaluate(
            assignments=tuple(prompt_assignments),
            failed_source_paths=tuple(item.source_path for item in failed_items),
            parse_warnings_by_source_path=parse_warnings_by_source_path,
        )
        conversion_gate = _evaluate_conversion_gate(
            phase=self._quality_gate_phase,
            source_kind=repository.source_kind,
            total_items_count=total_items_count,
            failed_items=tuple(failed_items),
            accumulator=conversion_gate_accumulator,
        )
        # `current_chunk_records` here is the merged-incremental view (which
        # may add chunks pulled forward from the baseline state); rebuild
        # the safety accumulator from it so the gate sees the same data as
        # the legacy path. For the streaming-only chunks coming out of the
        # parse loop, `publish_safety_gate_accumulator` already observed
        # them — this re-build is a superset that includes baseline chunks.
        publish_safety_gate = _evaluate_publish_safety_gate(
            total_items_count=total_items_count,
            failed_items=tuple(failed_items),
            chunk_records=current_chunk_records,
            coverage_threshold_pct=self._publish_safety_min_coverage_pct,
        )
        has_canonical_remap_changes = remapped_chunk_records_count > 0

        def _finalize_result(
            *,
            indexing_summary: IndexPublishSummary,
        ) -> SourceHugoNormalizationResult:
            result_failed_items = list(failed_items)
            review_artifact_path: str | None = None
            staging_repository_manifest_path: str | None = None
            staging_scopes: tuple[SourceStagingScopeSummary, ...] = ()
            staging_snapshot_tier = (
                StagingSnapshotTier.PUBLISH
                if mode is IngestionRunMode.PUBLISH
                and indexing_summary.decision
                in {PublishDecision.FULL_PUBLISH, PublishDecision.PARTIAL_PUBLISH}
                else StagingSnapshotTier.REVIEW
            )
            try:
                # When the streaming writer has already produced a
                # REVIEW-tier manifest in this run, reuse it directly for
                # REVIEW-tier finalisation. PUBLISH-tier finalisation
                # (publish succeeded) promotes that REVIEW snapshot by
                # streaming from disk; only an incremental run with a
                # canonical-URL remap falls back to the legacy
                # `write_repository_snapshot` with re-loaded documents.
                if (
                    streaming_writer_close_result is not None
                    and staging_snapshot_tier is StagingSnapshotTier.REVIEW
                ):
                    staging_write_result = streaming_writer_close_result
                elif streaming_writer_close_result is not None and force_full_reindex:
                    # Streaming PUBLISH: a full reindex re-emits every document,
                    # so promote the REVIEW snapshot to PUBLISH by re-streaming
                    # from disk one page at a time — never holding the whole repo
                    # in RAM. This avoids the publish-boundary peak (whole-repo
                    # chunk list + re-materialised documents + the legacy
                    # snapshot's ~3x serialised dicts), which can reach tens of
                    # GB on large apiref re-ingests.
                    staging_write_result = (
                        self._canonical_staging_store.write_publish_snapshot_from_review(
                            repo_id=repository.repo_id,
                            product_id=repository.product_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            file_checksums=current_file_checksums,
                            operation_id=operation_id,
                        )
                    )
                elif (
                    streaming_writer_close_result is not None
                    and remap_applied_count == 0
                ):
                    # Streaming INCREMENTAL PUBLISH: re-stream this run's changed
                    # files from the REVIEW snapshot into PUBLISH, then carry forward
                    # the unchanged files' docs+chunks from the prior PUBLISH snapshot
                    # by streaming (close skip_previous_merge=False). Byte-equivalent
                    # to the legacy write_repository_snapshot but never holds the
                    # whole repo, so the incremental publish-boundary peak stays
                    # bounded. Gated on remap_applied_count == 0: a
                    # canonical-URL remap rewrites chunks AFTER parse, so the
                    # pre-parse REVIEW snapshot would lose it — fall back to the
                    # legacy whole-RAM merge in that (rare) case.
                    staging_write_result = (
                        self._canonical_staging_store.write_publish_snapshot_from_review(
                            repo_id=repository.repo_id,
                            product_id=repository.product_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            file_checksums=current_file_checksums,
                            operation_id=operation_id,
                            skip_previous_merge=False,
                        )
                    )
                elif streaming_writer_close_result is not None:
                    # Incremental PUBLISH with a canonical-URL remap applied this run:
                    # the remap rewrote post-parse chunks, so re-streaming the
                    # pre-parse REVIEW snapshot would lose it — re-materialise from
                    # the REVIEW manifest and merge against the prior snapshot (the
                    # legacy whole-RAM diff path) to stay byte-equivalent.
                    publish_canonical_documents = list(
                        self._canonical_staging_store.iter_canonical_documents(
                            repo_id=repository.repo_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            snapshot_tier=StagingSnapshotTier.REVIEW,
                        )
                    )
                    staging_write_result = (
                        self._canonical_staging_store.write_repository_snapshot(
                            repo_id=repository.repo_id,
                            product_id=repository.product_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            file_checksums=current_file_checksums,
                            canonical_documents=publish_canonical_documents,
                            chunk_records=current_chunk_records,
                            snapshot_tier=staging_snapshot_tier,
                            operation_id=operation_id,
                        )
                    )
                else:
                    # Legacy in-memory write — used when no streaming
                    # writer ran (e.g. dry_run or staging_replay path).
                    staging_write_result = (
                        self._canonical_staging_store.write_repository_snapshot(
                            repo_id=repository.repo_id,
                            product_id=repository.product_id,
                            source_kind=repository.source_kind,
                            source_revision=source_revision,
                            file_checksums=current_file_checksums,
                            canonical_documents=canonical_documents,
                            chunk_records=current_chunk_records,
                            snapshot_tier=staging_snapshot_tier,
                            operation_id=operation_id,
                        )
                    )
                staging_repository_manifest_path = (
                    staging_write_result.repository_manifest_path
                )
                staging_scopes = tuple(
                    SourceStagingScopeSummary(
                        product_id=item.product_id,
                        programming_language=item.programming_language,
                        version=item.version,
                        doc_locale=item.doc_locale,
                        source_kind=item.source_kind,
                        manifest_path=item.manifest_path,
                        documents_count=item.documents_count,
                        chunk_records_count=item.chunk_records_count,
                    )
                    for item in staging_write_result.scope_summaries
                )
            except OSError as exc:
                result_failed_items.append(
                    SourceHugoNormalizationFailedItem(
                        source_path=(repository.git.submodule_path / "_staging").as_posix(),
                        error_code="STAGING_WRITE_ERROR",
                        message=str(exc),
                    )
                )

            # Publish API-reference symbols from the PUBLISH-tier staging snapshot
            # written just above. This MUST run after the staging write: the
            # symbol publisher reads PUBLISH-tier staging, which does not exist
            # earlier in _normalize_repository (only the REVIEW-tier streaming
            # snapshot does). Calling it before this point silently extracts zero
            # symbols. Gated on PUBLISH tier so VALIDATE_ONLY / NO_CHANGES /
            # review-only runs do not publish symbols.
            if staging_snapshot_tier is StagingSnapshotTier.PUBLISH:
                self._publish_apiref_symbols(
                    repository=repository,
                    snapshot_id=indexing_summary.active_snapshot_id
                    or indexing_summary.snapshot_id,
                )

            try:
                review_artifact_path = self._review_artifact_store.write_artifact(
                    operation_id=operation_id,
                    repo_id=repository.repo_id,
                    source_kind=repository.source_kind,
                    source_revision=source_revision,
                    parsed_pages_count=pages_count,
                    parse_warnings_count=parse_warnings_count,
                    normalized_documents_count=canonical_documents_count,
                    chunk_records_count=len(current_chunk_records),
                    file_checksums=current_file_checksums,
                    staging_repository_manifest_path=staging_repository_manifest_path,
                    staging_scope_summaries=tuple(
                        CanonicalStagingScopeSummary(
                            product_id=item.product_id,
                            programming_language=item.programming_language,
                            version=item.version,
                            doc_locale=item.doc_locale,
                            source_kind=item.source_kind,
                            manifest_path=item.manifest_path,
                            documents_count=item.documents_count,
                            chunk_records_count=item.chunk_records_count,
                        )
                        for item in staging_scopes
                    ),
                    staging_replay_used=staging_replay_used,
                    indexing_summary=indexing_summary,
                    failed_items=result_failed_items,
                    metadata_quarantine=metadata_quarantine_summary,
                    canonical_url_mapping=canonical_url_mapping_summary,
                )
            except OSError as exc:
                result_failed_items.append(
                    SourceHugoNormalizationFailedItem(
                        source_path=(repository.git.submodule_path / "_artifact").as_posix(),
                        error_code="REVIEW_ARTIFACT_WRITE_ERROR",
                        message=str(exc),
                    )
                )

            # `pages` / `canonical_documents` tuples are
            # intentionally empty in the streaming path. Counts live in
            # `parsed_pages_count` / the indexing summary; the actual
            # documents are reachable via
            # `FileSystemCanonicalStagingStore.iter_canonical_documents(...)`
            # using `staging_repository_manifest_path` as the entry point.
            return SourceHugoNormalizationResult(
                repo_id=repository.repo_id,
                source_kind=repository.source_kind,
                parsed_pages_count=pages_count,
                parse_warnings_count=parse_warnings_count,
                pages=(),
                canonical_documents=(),
                chunk_records=current_chunk_records,
                indexing_summary=indexing_summary,
                review_artifact_path=review_artifact_path,
                staging_repository_manifest_path=staging_repository_manifest_path,
                staging_scopes=staging_scopes,
                staging_replay_used=staging_replay_used,
                failed_items=tuple(result_failed_items),
                metadata_quarantine=metadata_quarantine_summary,
                prompt_evaluation=prompt_evaluation,
                canonical_url_mapping=canonical_url_mapping_summary,
                canonical_documents_count=canonical_documents_count,
                chunk_records_count=len(current_chunk_records),
            )

        if (
            mode is IngestionRunMode.PUBLISH
            and not file_diff_plan.has_changes
            and not has_canonical_remap_changes
            and failed_items_count == 0
        ):
            no_changes_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.NO_CHANGES,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=SemanticGateSummary(),
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
            )
            indexing_summary = _with_incremental_summary(
                summary=no_changes_summary,
                file_diff_plan=file_diff_plan,
                chunk_diff_plan=chunk_diff_plan,
                detection_strategy=incremental_selection.detection_strategy,
                git_base_revision=incremental_selection.git_base_revision,
                baseline_snapshot_id=baseline_snapshot_id,
                file_total_count=len(current_file_checksums),
                chunk_total_count=len(current_chunk_records),
            )
            self._incremental_state_store.save(
                repo_id=repository.repo_id,
                source_revision=source_revision,
                snapshot_id=baseline_snapshot_id,
                file_checksums=current_file_checksums,
                chunk_records=current_chunk_records,
            )
            return _finalize_result(indexing_summary=indexing_summary)

        semantic_gate_summary = SemanticGateSummary()

        if mode is IngestionRunMode.PUBLISH and publish_safety_gate.blocking:
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.PUBLISH_BLOCKED,
                message="Publish blocked by publish safety gate.",
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "publish_blocked_reason": PUBLISH_BLOCKED_REASON_PUBLISH_SAFETY_GATE,
                    "publish_safety_reason_codes": list(publish_safety_gate.reason_codes),
                    "publish_safety_usable_chunk_coverage_pct": (
                        publish_safety_gate.usable_chunk_coverage_pct
                    ),
                    "publish_safety_coverage_threshold_pct": (
                        publish_safety_gate.coverage_threshold_pct
                    ),
                    "publish_safety_parser_critical_failed_items_count": (
                        publish_safety_gate.parser_critical_failed_items_count
                    ),
                    "publish_safety_active_scopes_count": (
                        publish_safety_gate.active_scopes_count
                    ),
                    "publish_safety_empty_usable_scope_detected": (
                        publish_safety_gate.empty_usable_scope_detected
                    ),
                    "job_id": operation_id,
                    "request_id": request_id,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)
            blocked_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PUBLISH_BLOCKED,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
                publish_blocked_reason=PUBLISH_BLOCKED_REASON_PUBLISH_SAFETY_GATE,
            )
            indexing_summary = _with_incremental_summary(
                summary=blocked_summary,
                file_diff_plan=file_diff_plan,
                chunk_diff_plan=chunk_diff_plan,
                detection_strategy=incremental_selection.detection_strategy,
                git_base_revision=incremental_selection.git_base_revision,
                baseline_snapshot_id=baseline_snapshot_id,
                file_total_count=len(current_file_checksums),
                chunk_total_count=len(current_chunk_records),
            )
            return _finalize_result(indexing_summary=indexing_summary)

        if mode is IngestionRunMode.PUBLISH and conversion_gate.blocking:
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.PUBLISH_BLOCKED,
                message="Publish blocked by conversion quality hard gate.",
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "publish_blocked_reason": PUBLISH_BLOCKED_REASON_CONVERSION_HARD_GATE,
                    "conversion_gate_phase": conversion_gate.phase,
                    "conversion_gate_enforcement_mode": conversion_gate.enforcement_mode,
                    "conversion_gate_reason_codes": list(conversion_gate.reason_codes),
                    "conversion_gate_parse_coverage_pct": conversion_gate.parse_coverage_pct,
                    "conversion_gate_schema_valid_pct": conversion_gate.schema_valid_pct,
                    "conversion_gate_metadata_completeness_pct": (
                        conversion_gate.metadata_completeness_pct
                    ),
                    "conversion_gate_citation_integrity_pct": (
                        conversion_gate.citation_integrity_pct
                    ),
                    "conversion_gate_api_signature_coverage_pct": (
                        conversion_gate.api_signature_coverage_pct
                    ),
                    "conversion_gate_api_parameter_coverage_pct": (
                        conversion_gate.api_parameter_coverage_pct
                    ),
                    "conversion_gate_hallucination_risk_pct": (
                        conversion_gate.hallucination_risk_pct
                    ),
                    "job_id": operation_id,
                    "request_id": request_id,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)
            blocked_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PUBLISH_BLOCKED,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
                publish_blocked_reason=PUBLISH_BLOCKED_REASON_CONVERSION_HARD_GATE,
            )
            indexing_summary = _with_incremental_summary(
                summary=blocked_summary,
                file_diff_plan=file_diff_plan,
                chunk_diff_plan=chunk_diff_plan,
                detection_strategy=incremental_selection.detection_strategy,
                git_base_revision=incremental_selection.git_base_revision,
                baseline_snapshot_id=baseline_snapshot_id,
                file_total_count=len(current_file_checksums),
                chunk_total_count=len(current_chunk_records),
            )
            return _finalize_result(indexing_summary=indexing_summary)

        if mode is IngestionRunMode.PUBLISH and english_only_violations:
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.INGESTION_CRITICAL_FAIL,
                message="Ingestion blocked: strict English-only gate failed.",
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "publish_blocked_reason": PUBLISH_BLOCKED_REASON_ENGLISH_ONLY_GATE,
                    "english_only_gate_reasons": [
                        {"reason_code": violation.reason_code, "message": violation.message}
                        for violation in english_only_violations
                    ],
                    "job_id": operation_id,
                    "request_id": request_id,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)
            blocked_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PUBLISH_BLOCKED,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
                publish_blocked_reason=PUBLISH_BLOCKED_REASON_ENGLISH_ONLY_GATE,
            )
            indexing_summary = _with_incremental_summary(
                summary=blocked_summary,
                file_diff_plan=file_diff_plan,
                chunk_diff_plan=chunk_diff_plan,
                detection_strategy=incremental_selection.detection_strategy,
                git_base_revision=incremental_selection.git_base_revision,
                baseline_snapshot_id=baseline_snapshot_id,
                file_total_count=len(current_file_checksums),
                chunk_total_count=len(current_chunk_records),
            )
            return _finalize_result(indexing_summary=indexing_summary)

        if (
            mode is IngestionRunMode.PUBLISH
            and metadata_quarantine_policy is MetadataQuarantinePolicy.STRICT_BLOCK
            and metadata_quarantine_summary.total_count > 0
        ):
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.PUBLISH_BLOCKED,
                message="Publish blocked by strict metadata quarantine policy.",
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "publish_blocked_reason": (
                        PUBLISH_BLOCKED_REASON_METADATA_QUARANTINE_STRICT
                    ),
                    "metadata_quarantine_policy": metadata_quarantine_policy.value,
                    "metadata_quarantine_count": metadata_quarantine_summary.total_count,
                    "metadata_quarantine_reason_counts": [
                        {"reason_code": item.reason_code, "count": item.count}
                        for item in metadata_quarantine_summary.reason_counts
                    ],
                    "job_id": operation_id,
                    "request_id": request_id,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)
            blocked_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PUBLISH_BLOCKED,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
                publish_blocked_reason=PUBLISH_BLOCKED_REASON_METADATA_QUARANTINE_STRICT,
            )
            indexing_summary = _with_incremental_summary(
                summary=blocked_summary,
                file_diff_plan=file_diff_plan,
                chunk_diff_plan=chunk_diff_plan,
                detection_strategy=incremental_selection.detection_strategy,
                git_base_revision=incremental_selection.git_base_revision,
                baseline_snapshot_id=baseline_snapshot_id,
                file_total_count=len(current_file_checksums),
                chunk_total_count=len(current_chunk_records),
            )
            return _finalize_result(indexing_summary=indexing_summary)

        if (
            mode is IngestionRunMode.PUBLISH
            and semantic_review_trigger_type == "major_change"
            and current_chunk_records
            and file_diff_plan.has_changes
        ):
            semantic_gate_summary = self._evaluate_semantic_gate(
                product_id=repository.product_id,
                version=_resolve_version(chunk_records=current_chunk_records),
                source_revision=source_revision,
                trigger_type=semantic_review_trigger_type,
                operation_id=operation_id,
                request_id=request_id,
            )
            if semantic_gate_summary.decision is SemanticGateDecision.BLOCK_PUBLISH:
                if (
                    self._quality_gate_phase == QUALITY_GATE_PHASE_MVP
                    and semantic_gate_summary.review_run_id is None
                    and "semantic_review_run_missing" in semantic_gate_summary.reason_codes
                ):
                    semantic_gate_summary = replace(
                        semantic_gate_summary,
                        enforced=False,
                        decision=SemanticGateDecision.NOT_ENFORCED,
                    )
                else:
                    event = self._critical_event_publisher.emit(
                        severity=CriticalEventSeverity.CRITICAL,
                        event_type=CriticalEventType.PUBLISH_BLOCKED,
                        message="Publish blocked by semantic review hard gate.",
                        details={
                        "repo_id": repository.repo_id,
                        "product_id": repository.product_id,
                        "mode": mode.value,
                        "publish_blocked_reason": (
                            PUBLISH_BLOCKED_REASON_SEMANTIC_REVIEW_HARD_GATE
                        ),
                        "reason_codes": list(semantic_gate_summary.reason_codes),
                        "semantic_review_run_id": semantic_gate_summary.review_run_id,
                        "semantic_review_status": semantic_gate_summary.review_status,
                        "semantic_review_approval_mode": semantic_gate_summary.approval_mode,
                        "semantic_review_overall_score": semantic_gate_summary.overall_score,
                        "semantic_review_threshold_score": semantic_gate_summary.threshold_score,
                        "semantic_review_fail_fast_triggered": (
                            semantic_gate_summary.fail_fast_triggered
                        ),
                        "semantic_review_blocking_error_count": (
                            semantic_gate_summary.blocking_error_count
                        ),
                        "job_id": operation_id,
                        "request_id": request_id,
                    },
                )
                    notification = self._notification_service.notify_event(event)
                    event_records.append(event.event_id)
                    event_types.append(event.event_type.value)
                    notification_dispatches.append(notification)
                    blocked_summary = _build_non_published_summary(
                        repository=repository,
                        pages=pages,
                        chunk_records=current_chunk_records,
                        source_revision=source_revision,
                        mode=mode,
                        dry_run=dry_run,
                        force_full_reindex=force_full_reindex,
                        threshold_pct=partial_publish_threshold_pct,
                        error_ratio=error_ratio,
                        decision=PublishDecision.PUBLISH_BLOCKED,
                        total_items_count=total_items_count,
                        failed_items_count=failed_items_count,
                        event_summary=CriticalEventSummary(
                            event_ids=tuple(event_records),
                            event_types=tuple(event_types),
                        ),
                        notification_summary=_summarize_notifications(notification_dispatches),
                        semantic_gate=semantic_gate_summary,
                        conversion_gate=conversion_gate,
                        publish_safety_gate=publish_safety_gate,
                        active_snapshot_id=baseline_snapshot_id or "",
                        metadata_quarantine=metadata_quarantine_summary,
                        canonical_url_mapping=canonical_url_mapping_summary,
                        publish_blocked_reason=PUBLISH_BLOCKED_REASON_SEMANTIC_REVIEW_HARD_GATE,
                    )
                    indexing_summary = _with_incremental_summary(
                        summary=blocked_summary,
                        file_diff_plan=file_diff_plan,
                        chunk_diff_plan=chunk_diff_plan,
                        detection_strategy=incremental_selection.detection_strategy,
                        git_base_revision=incremental_selection.git_base_revision,
                        baseline_snapshot_id=baseline_snapshot_id,
                        file_total_count=len(current_file_checksums),
                        chunk_total_count=len(current_chunk_records),
                    )
                    return _finalize_result(indexing_summary=indexing_summary)

        if mode is IngestionRunMode.VALIDATE_ONLY:
            decision = PublishDecision.VALIDATE_ONLY
            indexing_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=decision,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
            )
        elif failed_items_count == 0 and current_chunk_records:
            published_summary = self._index_publish_orchestrator.publish(
                chunk_records=current_chunk_records,
                write_dense_lexical=not self._apiref_structured_only(repository),
                english_only_embed=self._docs_english_only_embed,
            )
            indexing_summary = replace(
                published_summary,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                partial_publish_threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.FULL_PUBLISH,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                metadata_quarantine_policy=metadata_quarantine_summary.policy_mode,
                quarantined_items_count=metadata_quarantine_summary.total_count,
                canonical_url_remap_entries_count=canonical_url_mapping_summary.remap_entries_count,
                canonical_url_remap_applied_count=canonical_url_mapping_summary.remap_applied_count,
                canonical_url_remap_conflict_count=canonical_url_mapping_summary.remap_conflict_count,
                canonical_url_remap_override_count=canonical_url_mapping_summary.remap_override_count,
            )
        elif current_chunk_records and error_ratio <= (partial_publish_threshold_pct / 100):
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.HIGH,
                event_type=CriticalEventType.PARTIAL_PUBLISH,
                message=(
                    "Partial publish accepted because error ratio is within configured threshold."
                ),
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "publish_blocked_reason": PUBLISH_BLOCKED_REASON_ERROR_RATIO_THRESHOLD,
                    "threshold_pct": partial_publish_threshold_pct,
                    "error_ratio": error_ratio,
                    "total_items_count": total_items_count,
                    "failed_items_count": failed_items_count,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)

            published_summary = self._index_publish_orchestrator.publish(
                chunk_records=current_chunk_records,
                write_dense_lexical=not self._apiref_structured_only(repository),
                english_only_embed=self._docs_english_only_embed,
            )
            indexing_summary = replace(
                published_summary,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                partial_publish_threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PARTIAL_PUBLISH,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                metadata_quarantine_policy=metadata_quarantine_summary.policy_mode,
                quarantined_items_count=metadata_quarantine_summary.total_count,
                canonical_url_remap_entries_count=canonical_url_mapping_summary.remap_entries_count,
                canonical_url_remap_applied_count=canonical_url_mapping_summary.remap_applied_count,
                canonical_url_remap_conflict_count=canonical_url_mapping_summary.remap_conflict_count,
                canonical_url_remap_override_count=canonical_url_mapping_summary.remap_override_count,
            )
        else:
            event = self._critical_event_publisher.emit(
                severity=CriticalEventSeverity.CRITICAL,
                event_type=CriticalEventType.PUBLISH_BLOCKED,
                message="Publish blocked because error ratio exceeds configured threshold.",
                details={
                    "repo_id": repository.repo_id,
                    "product_id": repository.product_id,
                    "mode": mode.value,
                    "threshold_pct": partial_publish_threshold_pct,
                    "error_ratio": error_ratio,
                    "total_items_count": total_items_count,
                    "failed_items_count": failed_items_count,
                },
            )
            notification = self._notification_service.notify_event(event)
            event_records.append(event.event_id)
            event_types.append(event.event_type.value)
            notification_dispatches.append(notification)
            indexing_summary = _build_non_published_summary(
                repository=repository,
                pages=pages,
                chunk_records=current_chunk_records,
                source_revision=source_revision,
                mode=mode,
                dry_run=dry_run,
                force_full_reindex=force_full_reindex,
                threshold_pct=partial_publish_threshold_pct,
                error_ratio=error_ratio,
                decision=PublishDecision.PUBLISH_BLOCKED,
                total_items_count=total_items_count,
                failed_items_count=failed_items_count,
                event_summary=CriticalEventSummary(
                    event_ids=tuple(event_records),
                    event_types=tuple(event_types),
                ),
                notification_summary=_summarize_notifications(notification_dispatches),
                semantic_gate=semantic_gate_summary,
                conversion_gate=conversion_gate,
                publish_safety_gate=publish_safety_gate,
                active_snapshot_id=baseline_snapshot_id or "",
                metadata_quarantine=metadata_quarantine_summary,
                canonical_url_mapping=canonical_url_mapping_summary,
                publish_blocked_reason=PUBLISH_BLOCKED_REASON_ERROR_RATIO_THRESHOLD,
            )

        indexing_summary = _with_incremental_summary(
            summary=indexing_summary,
            file_diff_plan=file_diff_plan,
            chunk_diff_plan=chunk_diff_plan,
            detection_strategy=incremental_selection.detection_strategy,
            git_base_revision=incremental_selection.git_base_revision,
            baseline_snapshot_id=baseline_snapshot_id,
            file_total_count=len(current_file_checksums),
            chunk_total_count=len(current_chunk_records),
        )
        if mode is IngestionRunMode.PUBLISH and indexing_summary.decision in {
            PublishDecision.FULL_PUBLISH,
            PublishDecision.PARTIAL_PUBLISH,
        }:
            # When the EN-only embed gate is active only English chunks were
            # actually indexed, so the chunk baseline must record only those —
            # otherwise the baseline would assert non-English chunks are
            # "published" at this snapshot when nothing was written for them. The
            # file checksums stay complete (every locale IS parsed to staging, so
            # files are not re-parsed on an unchanged re-run). A future locale
            # rollout re-publishes the non-English locales from staging
            # (staging-replay), which bypasses the file diff; it is intentionally
            # not triggered by a plain incremental re-run.
            baseline_chunk_records = current_chunk_records
            if self._docs_english_only_embed:
                baseline_chunk_records = tuple(
                    record
                    for record in current_chunk_records
                    if _is_english_locale(record.doc_locale)
                )
            self._incremental_state_store.save(
                repo_id=repository.repo_id,
                source_revision=source_revision,
                snapshot_id=indexing_summary.active_snapshot_id or indexing_summary.snapshot_id,
                file_checksums=current_file_checksums,
                chunk_records=baseline_chunk_records,
            )

        return _finalize_result(indexing_summary=indexing_summary)

    def _resolve_threshold_pct(self, threshold_pct: int | None) -> int:
        if threshold_pct is None:
            return self._partial_publish_threshold_pct
        return _normalize_threshold_pct(threshold_pct)

    def _resolve_metadata_quarantine_policy(
        self,
        policy: str | MetadataQuarantinePolicy | None,
    ) -> MetadataQuarantinePolicy:
        if policy is None:
            return self._metadata_quarantine_policy
        return normalize_metadata_quarantine_policy(policy)

    def _evaluate_semantic_gate(
        self,
        *,
        product_id: str,
        version: str,
        source_revision: str,
        trigger_type: SemanticReviewTriggerType,
        operation_id: str,
        request_id: str | None,
    ) -> SemanticGateSummary:
        if self._semantic_review_service is None:
            return SemanticGateSummary(
                enforced=False,
                trigger_type=trigger_type,
                decision=SemanticGateDecision.NOT_ENFORCED,
            )

        evaluation = self._semantic_review_service.evaluate_publish_gate(
            product_id=product_id,
            version=version,
            source_revision=source_revision,
            trigger_type=trigger_type,
        )
        if evaluation.run_id is not None:
            self._semantic_review_service.record_publish_gate_decision(
                run_id=evaluation.run_id,
                trigger_type=trigger_type,
                decision=evaluation.decision,
                reason_codes=evaluation.reason_codes,
                operation_id=operation_id,
                request_id=request_id,
            )
        return _to_semantic_gate_summary(evaluation)

    def _save_operation(
        self,
        operation: SourceHugoNormalizationOperation,
        *,
        append_new: bool = False,
    ) -> None:
        with self._lock:
            if append_new and operation.operation_id not in self._operation_order:
                self._operation_order.append(operation.operation_id)
            self._operations[operation.operation_id] = operation
        self._operation_state_store.save(
            record_id=operation.operation_id,
            record=operation,
        )

    def _operation_from_job_record(
        self,
        record: IngestionJobRecord,
    ) -> SourceHugoNormalizationOperation:
        return SourceHugoNormalizationOperation(
            operation_id=record.operation_id,
            status=_coerce_operation_status(record.status),
            repo_ids=record.repo_ids,
            logs=(),
            results=(),
            started_at=record.started_at,
            finished_at=record.finished_at,
            mode=_coerce_ingestion_mode(record.mode, fallback=IngestionRunMode.PUBLISH),
            requested_mode=_coerce_ingestion_mode(record.mode, fallback=IngestionRunMode.PUBLISH),
            partial_publish_threshold_pct=record.partial_publish_threshold_pct,
            metadata_quarantine_policy=self._metadata_quarantine_policy.value,
            semantic_review_trigger_type="major_change",
            conversion_backend=self._llm_runtime_policy.resolve_backend(
                task=IngestionLLMTask.CONVERSION
            ).value,
            prompt_registry_version=self._prompt_registry.registry_version,
            prompt_experiment_id=self._prompt_registry.experiment_id,
            dry_run=record.dry_run,
            force_full_reindex=record.force_full_reindex,
            request_id=record.request_id,
            idempotency_key=record.idempotency_key,
            idempotency_scope=record.idempotency_scope,
            idempotency_reused=record.idempotency_reused,
            idempotency_expires_at=record.idempotency_expires_at,
            request_fingerprint=record.request_fingerprint,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            next_retry_at=record.next_retry_at,
            last_error_kind=record.last_error_kind,
            cancel_requested_at=record.cancel_requested_at,
            cancelled_at=record.cancelled_at,
            resumable=record.resumable,
        )

    def _persist_job_placeholder(
        self,
        *,
        operation: SourceHugoNormalizationOperation,
        mode: IngestionRunMode,
        threshold_pct: int,
        request_id: str | None,
        error_message: str | None,
    ) -> None:
        self._ingestion_job_repository.upsert(
            operation_id=operation.operation_id,
            status=operation.status.value,
            repo_ids=operation.repo_ids,
            mode=mode.value,
            partial_publish_threshold_pct=threshold_pct,
            request_id=request_id,
            started_at=operation.started_at,
            finished_at=operation.finished_at,
            error_message=error_message,
            dry_run=operation.dry_run,
            force_full_reindex=operation.force_full_reindex,
            idempotency_key=operation.idempotency_key,
            idempotency_scope=operation.idempotency_scope,
            idempotency_reused=operation.idempotency_reused,
            idempotency_expires_at=operation.idempotency_expires_at,
            request_fingerprint=operation.request_fingerprint,
            attempt_count=operation.attempt_count,
            max_attempts=operation.max_attempts,
            next_retry_at=operation.next_retry_at,
            last_error_kind=operation.last_error_kind,
            cancel_requested_at=operation.cancel_requested_at,
            cancelled_at=operation.cancelled_at,
            resumable=operation.resumable,
        )


@dataclass
class _ConversionGateAccumulator:
    """Streaming aggregator for inputs to :func:`_evaluate_conversion_gate`.

    Populated incrementally inside the `_normalize_repository` parse loop so
    the gate can be evaluated without keeping the full `pages` /
    `canonical_documents` tuples in RAM.
    """

    parsed_source_paths: set[str] = field(default_factory=set)
    citation_total: int = 0
    citation_valid: int = 0
    api_symbol_docs_count: int = 0
    api_signature_hits: int = 0
    api_parameter_hits: int = 0

    def observe_page(self, page: HugoNormalizedPage) -> None:
        self.parsed_source_paths.add(page.source_path)

    def observe_document(self, document: NormalizedDocument) -> None:
        for chunk in document.chunks:
            self.citation_total += 1
            if chunk.citations and all(
                citation.source_path == document.document.source_path
                for citation in chunk.citations
            ):
                self.citation_valid += 1
        if document.document.doc_type == "api_reference_symbol":
            self.api_symbol_docs_count += 1
            chunk_types = {chunk.chunk_type for chunk in document.chunks}
            if "api_signature" in chunk_types:
                self.api_signature_hits += 1
            if "api_parameters" in chunk_types:
                self.api_parameter_hits += 1

    def merge(self, other: _ConversionGateAccumulator) -> None:
        """Combine state from another accumulator (used on intra-checkpoint resume)."""
        self.parsed_source_paths.update(other.parsed_source_paths)
        self.citation_total += other.citation_total
        self.citation_valid += other.citation_valid
        self.api_symbol_docs_count += other.api_symbol_docs_count
        self.api_signature_hits += other.api_signature_hits
        self.api_parameter_hits += other.api_parameter_hits

    @classmethod
    def from_sequences(
        cls,
        *,
        pages: Sequence[HugoNormalizedPage],
        canonical_documents: Sequence[NormalizedDocument],
    ) -> _ConversionGateAccumulator:
        """Build an accumulator from full sequences (legacy / test path)."""
        accumulator = cls()
        for page in pages:
            accumulator.observe_page(page)
        for document in canonical_documents:
            accumulator.observe_document(document)
        return accumulator


@dataclass
class _PublishSafetyGateAccumulator:
    """Streaming aggregator for inputs to :func:`_evaluate_publish_safety_gate`."""

    usable_source_paths: set[str] = field(default_factory=set)
    active_scope_tuples: set[tuple[str, str, str, str]] = field(default_factory=set)

    def observe_chunk(self, chunk_record: StageDChunkRecord) -> None:
        self.usable_source_paths.add(chunk_record.source_path)
        self.active_scope_tuples.add(
            (
                chunk_record.product_id,
                chunk_record.programming_language,
                chunk_record.version,
                chunk_record.source_kind,
            )
        )

    def merge(self, other: _PublishSafetyGateAccumulator) -> None:
        self.usable_source_paths.update(other.usable_source_paths)
        self.active_scope_tuples.update(other.active_scope_tuples)

    @classmethod
    def from_sequence(
        cls, *, chunk_records: Sequence[StageDChunkRecord]
    ) -> _PublishSafetyGateAccumulator:
        accumulator = cls()
        for record in chunk_records:
            accumulator.observe_chunk(record)
        return accumulator


def _evaluate_conversion_gate(
    *,
    phase: str,
    source_kind: str,
    total_items_count: int,
    failed_items: tuple[SourceHugoNormalizationFailedItem, ...],
    pages: tuple[HugoNormalizedPage, ...] = (),
    canonical_documents: tuple[NormalizedDocument, ...] = (),
    accumulator: _ConversionGateAccumulator | None = None,
) -> ConversionGateSummary:
    """Evaluate the conversion-quality hard gate.

    Pass either an ``accumulator`` (preferred, populated incrementally
    during the parse loop) or the legacy ``pages`` / ``canonical_documents``
    sequences from which an accumulator is constructed on the fly.
    """
    if accumulator is None:
        accumulator = _ConversionGateAccumulator.from_sequences(
            pages=pages, canonical_documents=canonical_documents
        )
    normalized_phase = _normalize_quality_gate_phase(phase)
    thresholds = _conversion_gate_thresholds(normalized_phase)

    parsed_count = len(accumulator.parsed_source_paths)
    parse_coverage_pct = (
        100.0
        if total_items_count <= 0
        else (parsed_count / float(total_items_count)) * 100.0
    )

    schema_fail_count = sum(
        1
        for item in failed_items
        if item.error_code in {"VALIDATION_ERROR", "SCHEMA_VALIDATION_FAILED"}
    )
    schema_valid_pct = (
        100.0
        if total_items_count <= 0
        else ((total_items_count - schema_fail_count) / float(total_items_count)) * 100.0
    )

    metadata_fail_count = sum(
        1
        for item in failed_items
        if item.error_code
        in {
            "MISSING_REQUIRED_METADATA",
            "CANONICAL_URL_MISSING",
            "QUARANTINE",
        }
    )
    metadata_completeness_pct = (
        100.0
        if total_items_count <= 0
        else ((total_items_count - metadata_fail_count) / float(total_items_count)) * 100.0
    )

    citation_integrity_pct = (
        100.0
        if accumulator.citation_total <= 0
        else (accumulator.citation_valid / float(accumulator.citation_total)) * 100.0
    )

    api_signature_coverage_pct: float | None = None
    api_parameter_coverage_pct: float | None = None
    if source_kind.strip().casefold() == "apiref" and accumulator.api_symbol_docs_count > 0:
        api_signature_coverage_pct = (
            accumulator.api_signature_hits / float(accumulator.api_symbol_docs_count)
        ) * 100.0
        api_parameter_coverage_pct = (
            accumulator.api_parameter_hits / float(accumulator.api_symbol_docs_count)
        ) * 100.0

    hallucination_flag_count = sum(
        1
        for item in failed_items
        if "HALLUCINATION" in item.error_code or "LOW_CONFIDENCE_CONVERSION" in item.error_code
    )
    hallucination_risk_pct = (
        0.0
        if total_items_count <= 0
        else (hallucination_flag_count / float(total_items_count)) * 100.0
    )

    reason_codes: list[str] = []
    if parse_coverage_pct < thresholds["parse_coverage_pct"]:
        reason_codes.append("parse_coverage_below_threshold")
    if schema_valid_pct < thresholds["schema_valid_pct"]:
        reason_codes.append("schema_valid_below_threshold")
    if metadata_completeness_pct < thresholds["metadata_completeness_pct"]:
        reason_codes.append("metadata_completeness_below_threshold")
    if citation_integrity_pct < thresholds["citation_integrity_pct"]:
        reason_codes.append("citation_integrity_below_threshold")
    if (
        api_signature_coverage_pct is not None
        and api_signature_coverage_pct < thresholds["api_signature_coverage_pct"]
    ):
        reason_codes.append("api_signature_coverage_below_threshold")
    if (
        api_parameter_coverage_pct is not None
        and api_parameter_coverage_pct < thresholds["api_parameter_coverage_pct"]
    ):
        reason_codes.append("api_parameter_coverage_below_threshold")
    if hallucination_risk_pct > thresholds["hallucination_risk_pct_max"]:
        reason_codes.append("hallucination_risk_above_threshold")

    enforcement_mode = (
        "hard_block"
        if normalized_phase in {QUALITY_GATE_PHASE_PREPROD, QUALITY_GATE_PHASE_GA}
        else "track_only"
    )
    blocking = bool(reason_codes) and enforcement_mode == "hard_block"
    return ConversionGateSummary(
        phase=normalized_phase,
        enforcement_mode=enforcement_mode,
        blocking=blocking,
        reason_codes=tuple(reason_codes),
        parse_coverage_pct=round(parse_coverage_pct, 3),
        schema_valid_pct=round(schema_valid_pct, 3),
        metadata_completeness_pct=round(metadata_completeness_pct, 3),
        citation_integrity_pct=round(citation_integrity_pct, 3),
        api_signature_coverage_pct=(
            round(api_signature_coverage_pct, 3)
            if api_signature_coverage_pct is not None
            else None
        ),
        api_parameter_coverage_pct=(
            round(api_parameter_coverage_pct, 3)
            if api_parameter_coverage_pct is not None
            else None
        ),
        hallucination_risk_pct=round(hallucination_risk_pct, 3),
    )


def _conversion_gate_thresholds(phase: str) -> dict[str, float]:
    if phase in {QUALITY_GATE_PHASE_PREPROD, QUALITY_GATE_PHASE_GA}:
        return {
            "parse_coverage_pct": 99.5,
            "schema_valid_pct": 100.0,
            "metadata_completeness_pct": 100.0,
            "citation_integrity_pct": 100.0,
            "api_signature_coverage_pct": 99.0,
            "api_parameter_coverage_pct": 99.0,
            "hallucination_risk_pct_max": 0.5,
        }
    return {
        "parse_coverage_pct": 99.0,
        "schema_valid_pct": 100.0,
        "metadata_completeness_pct": 100.0,
        "citation_integrity_pct": 100.0,
        "api_signature_coverage_pct": 99.0,
        "api_parameter_coverage_pct": 99.0,
        "hallucination_risk_pct_max": 1.0,
    }


def _to_semantic_gate_summary(
    evaluation: SemanticReviewPublishGateEvaluation,
) -> SemanticGateSummary:
    decision = (
        SemanticGateDecision.ALLOW_PUBLISH
        if evaluation.decision == "allow_publish"
        else SemanticGateDecision.BLOCK_PUBLISH
    )
    return SemanticGateSummary(
        enforced=True,
        trigger_type=evaluation.trigger_type,
        decision=decision,
        reason_codes=evaluation.reason_codes,
        review_run_id=evaluation.run_id,
        review_status=evaluation.run_status,
        approval_mode=evaluation.approval_mode,
        overall_score=evaluation.overall_score,
        threshold_score=evaluation.threshold_score,
        fail_fast_triggered=evaluation.fail_fast_triggered,
        blocking_error_count=evaluation.blocking_error_count,
        status_transitions=tuple(
            SemanticGateStatusTransition(
                transition_id=transition.transition_id,
                from_status=transition.from_status,
                to_status=transition.to_status,
                actor_type=transition.actor_type,
                actor_key_id=transition.actor_key_id,
                reason=transition.reason,
                request_id=transition.request_id,
                created_at=transition.created_at,
            )
            for transition in evaluation.status_transitions
        ),
    )


def _select_repositories(
    registry_service: SourceRegistryService,
    repo_ids: tuple[str, ...],
) -> tuple[tuple[SourceRepository, ...], tuple[str, ...]]:
    """Resolve ``repo_ids`` to descriptors, SKIPPING unregistered ids.

    Returns ``(known_repositories, unknown_repo_ids)``. An unregistered or
    mistyped repo_id must never abort the whole run (resilience): the caller logs
    the skipped ids and ingests the rest. Empty input selects all repositories.
    """
    if not repo_ids:
        return registry_service.list_repositories(), ()
    known: list[SourceRepository] = []
    unknown: list[str] = []
    for repo_id in repo_ids:
        try:
            known.append(registry_service.get_repository(repo_id))
        except SourceRegistryLookupError:
            unknown.append(repo_id)
    return tuple(known), tuple(unknown)


def _normalize_repo_ids(repo_ids: Sequence[str] | None) -> tuple[str, ...]:
    if not repo_ids:
        return ()
    normalized_repo_ids: list[str] = []
    seen_repo_ids: set[str] = set()
    for raw_repo_id in repo_ids:
        repo_id = raw_repo_id.strip()
        if not repo_id:
            raise ValueError("repo_ids must not contain empty values.")
        if repo_id in seen_repo_ids:
            continue
        seen_repo_ids.add(repo_id)
        normalized_repo_ids.append(repo_id)
    return tuple(normalized_repo_ids)


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        msg = "idempotency_key must not be empty when provided."
        raise ValueError(msg)
    if len(normalized) > 256:
        msg = "idempotency_key must be <= 256 characters."
        raise ValueError(msg)
    return normalized


def _build_idempotency_scope(
    *,
    repo_ids: tuple[str, ...],
    mode: IngestionRunMode,
    dry_run: bool,
    force_full_reindex: bool,
) -> str:
    payload = {
        "schema": IDEMPOTENCY_SCOPE_SCHEMA,
        "repo_ids": list(repo_ids),
        "mode": mode.value,
        "dry_run": dry_run,
        "force_full_reindex": force_full_reindex,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    scope_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"{IDEMPOTENCY_SCOPE_SCHEMA}:{scope_hash}"


def _build_trigger_request_fingerprint(
    *,
    repo_ids: tuple[str, ...],
    mode: IngestionRunMode,
    threshold_pct: int,
    metadata_quarantine_policy: MetadataQuarantinePolicy,
    dry_run: bool,
    force_full_reindex: bool,
    semantic_review_trigger_type: SemanticReviewTriggerType,
) -> str:
    payload = {
        "repo_ids": list(repo_ids),
        "mode": mode.value,
        "threshold_pct": threshold_pct,
        "metadata_quarantine_policy": metadata_quarantine_policy.value,
        "dry_run": dry_run,
        "force_full_reindex": force_full_reindex,
        "semantic_review_trigger_type": semantic_review_trigger_type,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compute_retry_backoff_seconds(
    *,
    attempt_number: int,
    base_seconds: int,
    max_seconds: int,
) -> int:
    normalized_attempt = max(1, attempt_number)
    factor = 2 ** (normalized_attempt - 1)
    return min(max_seconds, base_seconds * factor)


def _coerce_operation_status(value: str) -> SourceHugoNormalizationStatus:
    try:
        return SourceHugoNormalizationStatus(value)
    except ValueError:
        return SourceHugoNormalizationStatus.QUEUED


def _coerce_ingestion_mode(value: str, *, fallback: IngestionRunMode) -> IngestionRunMode:
    try:
        return IngestionRunMode(value)
    except ValueError:
        return fallback


def _coerce_llm_backend(value: str) -> IngestionLLMBackend:
    try:
        return IngestionLLMBackend(value)
    except ValueError:
        return IngestionLLMBackend.DETERMINISTIC


def _normalize_quality_gate_phase(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {
        QUALITY_GATE_PHASE_MVP,
        QUALITY_GATE_PHASE_PREPROD,
        QUALITY_GATE_PHASE_GA,
    }:
        return normalized
    msg = (
        "quality_gate_phase must be one of: "
        f"{QUALITY_GATE_PHASE_MVP}, {QUALITY_GATE_PHASE_PREPROD}, {QUALITY_GATE_PHASE_GA}."
    )
    raise ValueError(msg)


def _scope_summary_may_contain(
    result_scope: list[Any],
    product_id: str,
    programming_language: str | None,
) -> bool:
    """Check whether the ``_result_scope`` metadata suggests matching chunks.

    Returns ``True`` if any result entry contains the requested ``product_id``
    (and optionally ``programming_language``) in its scope summary.  Returns
    ``True`` on any parse ambiguity so callers always fall through to a full load.
    """
    if not result_scope:
        return False
    target_pid = product_id.casefold()
    for entry in result_scope:
        if not isinstance(entry, dict):
            return True  # Ambiguous — don't skip.
        chunk_count = entry.get("chunk_count", 0)
        if not isinstance(chunk_count, int) or chunk_count == 0:
            continue
        pids = entry.get("product_ids", [])
        if not isinstance(pids, list):
            return True  # Ambiguous.
        pid_match = any(
            isinstance(pid, str) and pid.casefold() == target_pid for pid in pids
        )
        if not pid_match:
            continue
        if programming_language is None:
            return True
        langs = entry.get("programming_languages", [])
        if not isinstance(langs, list):
            return True  # Ambiguous.
        lang_match = any(
            isinstance(lang, str)
            and lang.casefold() == programming_language.casefold()
            for lang in langs
        )
        if lang_match:
            return True
    return False


def _repo_ids_hint_match(repo_ids: list[str], product_id: str) -> bool:
    """Check if any repo_id appears to belong to the given product.

    Repo IDs follow patterns like ``aspose.ocr.docs`` or ``aspose.ocr.apiref``.
    A product_id of ``aspose.ocr`` matches any repo starting with ``aspose.ocr.``.
    This is a lightweight heuristic used to prioritise which full operation files
    to load first.
    """
    prefix = product_id.casefold() + "."
    return any(rid.casefold().startswith(prefix) for rid in repo_ids)


def _extract_matching_chunks(
    operation: SourceHugoNormalizationOperation,
    product_id: str | None,
    programming_language: str | None,
    version: str | None,
) -> tuple[StageDChunkRecord, ...]:
    """Extract chunk records from *operation* that match the given scope filters."""
    matching = tuple(
        chunk_record
        for result in operation.results
        for chunk_record in result.chunk_records
        if _scope_match(chunk_record.product_id, product_id)
        and _scope_match(chunk_record.programming_language, programming_language)
        and _scope_match(chunk_record.version, version)
    )
    return matching


def _scope_match(actual: str, expected: str | None) -> bool:
    if expected is None:
        return True
    return actual.casefold() == expected.casefold()


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _normalize_threshold_pct(value: int) -> int:
    if value < 0 or value > 100:
        msg = "partial_publish_threshold_pct must be in range [0, 100]."
        raise ValueError(msg)
    return value


def _build_non_published_summary(
    *,
    repository: SourceRepository,
    pages: Sequence[HugoNormalizedPage],
    chunk_records: Sequence[StageDChunkRecord],
    source_revision: str,
    mode: IngestionRunMode,
    dry_run: bool,
    force_full_reindex: bool,
    threshold_pct: int,
    error_ratio: float,
    decision: PublishDecision,
    total_items_count: int,
    failed_items_count: int,
    event_summary: CriticalEventSummary,
    notification_summary: NotificationDispatchSummary,
    semantic_gate: SemanticGateSummary,
    conversion_gate: ConversionGateSummary,
    publish_safety_gate: PublishSafetyGateSummary,
    active_snapshot_id: str,
    metadata_quarantine: MetadataQuarantineSummary,
    canonical_url_mapping: SourceCanonicalUrlMappingSummary,
    publish_blocked_reason: str | None = None,
) -> IndexPublishSummary:
    programming_language = _resolve_programming_language(pages=pages, chunk_records=chunk_records)
    version = _resolve_version(chunk_records=chunk_records)
    return IndexPublishSummary(
        snapshot_id="",
        product_id=repository.product_id,
        programming_language=programming_language,
        version=version,
        source_kind=repository.source_kind,
        source_revision=source_revision,
        indexed_chunks_count=0,
        vector_records_count=0,
        lexical_records_count=0,
        vector_collection="",
        lexical_index="",
        lexical_alias="",
        active_snapshot_id=active_snapshot_id,
        mode=mode,
        dry_run=dry_run,
        force_full_reindex=force_full_reindex,
        partial_publish_threshold_pct=threshold_pct,
        error_ratio=error_ratio,
        decision=decision,
        publish_blocked_reason=publish_blocked_reason,
        total_items_count=total_items_count,
        failed_items_count=failed_items_count,
        metadata_quarantine_policy=metadata_quarantine.policy_mode,
        quarantined_items_count=metadata_quarantine.total_count,
        canonical_url_remap_entries_count=canonical_url_mapping.remap_entries_count,
        canonical_url_remap_applied_count=canonical_url_mapping.remap_applied_count,
        canonical_url_remap_conflict_count=canonical_url_mapping.remap_conflict_count,
        canonical_url_remap_override_count=canonical_url_mapping.remap_override_count,
        event_summary=event_summary,
        notification_summary=notification_summary,
        semantic_gate=semantic_gate,
        conversion_gate=conversion_gate,
        publish_safety_gate=publish_safety_gate,
    )


def _to_quarantine_failed_item(
    *,
    source_path: str,
    quarantine_items: Sequence[MetadataQuarantineItem],
) -> SourceHugoNormalizationFailedItem:
    reason_codes = sorted({item.reason_code for item in quarantine_items})
    return SourceHugoNormalizationFailedItem(
        source_path=source_path,
        error_code="QUARANTINE",
        message=f"Quarantined metadata with reason codes: {', '.join(reason_codes)}.",
    )


def _apply_canonical_mapping_to_document(
    *,
    normalized_document: NormalizedDocument,
    mapping_registry: CanonicalUrlMappingRegistry,
) -> NormalizedDocument:
    mapped_document_url = mapping_registry.resolve(normalized_document.document.canonical_url)
    mapped_document_metadata = normalized_document.document
    if mapped_document_url != normalized_document.document.canonical_url:
        mapped_document_metadata = replace(
            normalized_document.document,
            canonical_url=mapped_document_url,
        )

    mapped_chunks = []
    has_chunk_changes = False
    for chunk in normalized_document.chunks:
        mapped_chunk_url = mapping_registry.resolve(chunk.canonical_url)
        mapped_citations = []
        citation_changed = False
        for citation in chunk.citations:
            mapped_citation_url = mapping_registry.resolve(citation.canonical_url)
            if mapped_citation_url != citation.canonical_url:
                citation_changed = True
                mapped_citations.append(replace(citation, canonical_url=mapped_citation_url))
            else:
                mapped_citations.append(citation)
        if mapped_chunk_url != chunk.canonical_url or citation_changed:
            has_chunk_changes = True
            mapped_chunks.append(
                replace(
                    chunk,
                    canonical_url=mapped_chunk_url,
                    citations=tuple(mapped_citations),
                )
            )
        else:
            mapped_chunks.append(chunk)

    if (
        mapped_document_metadata is normalized_document.document
        and not has_chunk_changes
    ):
        return normalized_document

    return replace(
        normalized_document,
        document=NormalizedDocumentMetadata(
            repo_id=mapped_document_metadata.repo_id,
            product_id=mapped_document_metadata.product_id,
            product_family=mapped_document_metadata.product_family,
            source_kind=mapped_document_metadata.source_kind,
            programming_language=mapped_document_metadata.programming_language,
            doc_locale=mapped_document_metadata.doc_locale,
            version=mapped_document_metadata.version,
            title=mapped_document_metadata.title,
            doc_type=mapped_document_metadata.doc_type,
            canonical_url=mapped_document_metadata.canonical_url,
            source_path=mapped_document_metadata.source_path,
            source_revision=mapped_document_metadata.source_revision,
            symbol_fqn=mapped_document_metadata.symbol_fqn,
        ),
        chunks=tuple(mapped_chunks),
    )


def _apply_canonical_mapping_to_chunk_records(
    *,
    chunk_records: Sequence[StageDChunkRecord],
    mapping_registries: dict[CanonicalUrlMappingContext, CanonicalUrlMappingRegistry],
    mapping_store: FileSystemCanonicalUrlMappingStore,
) -> tuple[tuple[StageDChunkRecord, ...], int]:
    mapped_records: list[StageDChunkRecord] = []
    mapped_count = 0
    for record in chunk_records:
        context = CanonicalUrlMappingContext.from_values(
            product_id=record.product_id,
            source_kind=record.source_kind,
            programming_language=record.programming_language,
            version=record.version,
        )
        registry = mapping_registries.get(context)
        if registry is None:
            registry = mapping_store.load(context=context)
            mapping_registries[context] = registry
        mapped_url = registry.resolve(record.canonical_url)
        if mapped_url != record.canonical_url:
            mapped_count += 1
            mapped_records.append(replace(record, canonical_url=mapped_url))
        else:
            mapped_records.append(record)
    return tuple(mapped_records), mapped_count


def _build_canonical_url_mapping_summary(
    *,
    mapping_registries: Mapping[CanonicalUrlMappingContext, CanonicalUrlMappingRegistry],
    conflicts: Sequence[CanonicalUrlMappingConflict],
    remap_applied_count: int,
    remap_override_count: int,
) -> SourceCanonicalUrlMappingSummary:
    remap_conflict_count = sum(
        1 for conflict in conflicts if conflict.conflict_type == "conflicting_mapping"
    )
    return SourceCanonicalUrlMappingSummary(
        contexts=tuple(
            sorted(context.context_id for context in mapping_registries)
        ),
        remap_entries_count=sum(
            registry.entries_count for registry in mapping_registries.values()
        ),
        remap_applied_count=remap_applied_count,
        remap_conflict_count=remap_conflict_count,
        remap_override_count=remap_override_count,
    )


def _merge_incremental_chunk_records(
    *,
    baseline_state: IncrementalBaselineState | None,
    file_diff_plan: IncrementalFileDiffPlan,
    parsed_chunk_records: Sequence[StageDChunkRecord],
) -> tuple[StageDChunkRecord, ...]:
    if baseline_state is None or file_diff_plan.mode == "full_reindex":
        return tuple(sorted(parsed_chunk_records, key=_chunk_sort_key))

    unchanged_source_paths = set(file_diff_plan.files_unchanged)
    baseline_unchanged_chunk_records = [
        chunk_record
        for chunk_record in baseline_state.chunk_records
        if chunk_record.source_path in unchanged_source_paths
    ]
    merged_records = (*baseline_unchanged_chunk_records, *parsed_chunk_records)
    return tuple(sorted(merged_records, key=_chunk_sort_key))


def _with_incremental_summary(
    *,
    summary: IndexPublishSummary,
    file_diff_plan: IncrementalFileDiffPlan,
    chunk_diff_plan: IncrementalChunkDiffPlan,
    detection_strategy: str,
    git_base_revision: str | None,
    baseline_snapshot_id: str | None,
    file_total_count: int,
    chunk_total_count: int,
) -> IndexPublishSummary:
    return replace(
        summary,
        incremental_mode=file_diff_plan.mode,
        incremental_detection_strategy=detection_strategy,
        incremental_fallback_reason=file_diff_plan.fallback_reason,
        incremental_git_base_revision=git_base_revision,
        baseline_snapshot_id=baseline_snapshot_id,
        file_total_count=file_total_count,
        file_new_count=len(file_diff_plan.files_new),
        file_changed_count=len(file_diff_plan.files_changed),
        file_unchanged_count=len(file_diff_plan.files_unchanged),
        file_removed_count=len(file_diff_plan.files_removed),
        chunk_total_count=chunk_total_count,
        chunk_new_count=len(chunk_diff_plan.chunk_ids_new),
        chunk_changed_count=len(chunk_diff_plan.chunk_ids_changed),
        chunk_unchanged_count=len(chunk_diff_plan.chunk_ids_unchanged),
        chunk_removed_count=len(chunk_diff_plan.chunk_ids_removed),
    )


def _chunk_sort_key(record: StageDChunkRecord) -> tuple[str, str, str]:
    return (record.source_path, record.section_anchor, record.chunk_id)


def _resolve_programming_language(
    *,
    pages: Sequence[HugoNormalizedPage],
    chunk_records: Sequence[StageDChunkRecord],
) -> str:
    if chunk_records:
        return chunk_records[0].programming_language
    for page in pages:
        if page.programming_language:
            return page.programming_language
    return "unknown"


def _resolve_version(*, chunk_records: Sequence[StageDChunkRecord]) -> str:
    if not chunk_records:
        return "latest-stable"
    return chunk_records[0].version


def _summarize_notifications(
    dispatches: Sequence[SmtpNotificationDispatch],
) -> NotificationDispatchSummary:
    sent_count = 0
    failed_count = 0
    for dispatch in dispatches:
        if dispatch.status is NotificationStatus.SENT:
            sent_count += 1
        elif dispatch.status is NotificationStatus.FAILED:
            failed_count += 1
    return NotificationDispatchSummary(sent_count=sent_count, failed_count=failed_count)


def _normalize_percent_float(value: float) -> float:
    normalized = float(value)
    if normalized < 0.0 or normalized > 100.0:
        msg = "percent value must be between 0 and 100."
        raise ValueError(msg)
    return round(normalized, 3)


def _evaluate_publish_safety_gate(
    *,
    total_items_count: int,
    failed_items: Sequence[SourceHugoNormalizationFailedItem],
    chunk_records: Sequence[StageDChunkRecord] = (),
    coverage_threshold_pct: float,
    accumulator: _PublishSafetyGateAccumulator | None = None,
) -> PublishSafetyGateSummary:
    """Evaluate the publish-safety hard gate.

    Pass either an ``accumulator`` (preferred, populated incrementally
    during the parse loop) or the legacy ``chunk_records`` sequence from
    which an accumulator is constructed on the fly.
    """
    if accumulator is None:
        accumulator = _PublishSafetyGateAccumulator.from_sequence(
            chunk_records=chunk_records
        )
    parser_critical_failed_items_count = sum(
        1 for item in failed_items if item.error_code in _PARSER_CRITICAL_ERROR_CODES
    )
    usable_chunk_coverage_pct = (
        100.0
        if total_items_count <= 0
        else (len(accumulator.usable_source_paths) / float(total_items_count)) * 100.0
    )
    active_scopes_count = len(accumulator.active_scope_tuples)
    empty_usable_scope_detected = total_items_count > 0 and active_scopes_count == 0

    reason_codes: list[str] = []
    if parser_critical_failed_items_count > 0:
        reason_codes.append(PUBLISH_SAFETY_REASON_CRITICAL_PARSER_ERRORS)
    if empty_usable_scope_detected:
        reason_codes.append(PUBLISH_SAFETY_REASON_EMPTY_USABLE_SCOPE)
    if usable_chunk_coverage_pct < coverage_threshold_pct:
        reason_codes.append(PUBLISH_SAFETY_REASON_USABLE_CHUNK_COVERAGE)

    return PublishSafetyGateSummary(
        blocking=bool(reason_codes),
        reason_codes=tuple(reason_codes),
        usable_chunk_coverage_pct=round(usable_chunk_coverage_pct, 3),
        coverage_threshold_pct=round(coverage_threshold_pct, 3),
        parser_critical_failed_items_count=parser_critical_failed_items_count,
        active_scopes_count=active_scopes_count,
        empty_usable_scope_detected=empty_usable_scope_detected,
    )


def _select_incremental_file_diff_plan(
    *,
    repository: SourceRepository,
    source_revision: str,
    current_file_checksums: Mapping[str, str],
    baseline_state: IncrementalBaselineState | None,
    force_full_reindex: bool,
    fallback_reason: str | None,
    workspace_root: Path,
) -> _IncrementalPlanSelection:
    baseline_file_checksums: Mapping[str, str] | None = (
        None if baseline_state is None else baseline_state.file_checksums_map()
    )
    if force_full_reindex:
        return _IncrementalPlanSelection(
            file_diff_plan=build_file_diff_plan(
                current_file_checksums=current_file_checksums,
                baseline_file_checksums=None,
                fallback_reason=fallback_reason or INCREMENTAL_FALLBACK_REASON_FORCED_REINDEX,
            ),
            detection_strategy=INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_DIFF,
        )
    if baseline_file_checksums is None:
        return _IncrementalPlanSelection(
            file_diff_plan=build_file_diff_plan(
                current_file_checksums=current_file_checksums,
                baseline_file_checksums=None,
                fallback_reason=fallback_reason,
            ),
            detection_strategy=INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_DIFF,
        )

    if baseline_state is not None and baseline_state.source_revision != source_revision:
        git_diff_plan = _try_build_git_diff_file_plan(
            repository=repository,
            workspace_root=workspace_root,
            baseline_revision=baseline_state.source_revision,
            current_revision=source_revision,
            current_file_checksums=current_file_checksums,
            baseline_file_checksums=baseline_file_checksums,
        )
        if git_diff_plan is not None:
            return _IncrementalPlanSelection(
                file_diff_plan=git_diff_plan,
                detection_strategy=INCREMENTAL_DETECTION_STRATEGY_GIT_DIFF,
                git_base_revision=baseline_state.source_revision,
            )
        return _IncrementalPlanSelection(
            file_diff_plan=build_file_diff_plan(
                current_file_checksums=current_file_checksums,
                baseline_file_checksums=baseline_file_checksums,
                fallback_reason=None,
            ),
            detection_strategy=INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_GIT_FALLBACK,
        )

    return _IncrementalPlanSelection(
        file_diff_plan=build_file_diff_plan(
            current_file_checksums=current_file_checksums,
            baseline_file_checksums=baseline_file_checksums,
            fallback_reason=None,
        ),
        detection_strategy=INCREMENTAL_DETECTION_STRATEGY_CHECKSUM_DIFF,
    )


def _try_build_git_diff_file_plan(
    *,
    repository: SourceRepository,
    workspace_root: Path,
    baseline_revision: str,
    current_revision: str,
    current_file_checksums: Mapping[str, str],
    baseline_file_checksums: Mapping[str, str],
) -> IncrementalFileDiffPlan | None:
    repo_root = (workspace_root / repository.git.submodule_path).resolve()
    if not repo_root.exists():
        return None
    if _git_worktree_has_markdown_changes(repo_root=repo_root):
        return None

    diff_completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-status",
            "--find-renames",
            baseline_revision,
            current_revision,
            "--",
            "*.md",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if diff_completed.returncode != 0:
        return None

    repo_prefix = Path(repository.git.submodule_path).as_posix().rstrip("/")
    current_paths = set(current_file_checksums)
    baseline_paths = set(baseline_file_checksums)
    files_new: set[str] = set()
    files_changed: set[str] = set()
    files_removed: set[str] = set()

    for raw_line in diff_completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        if status == "D":
            removed_path = _to_workspace_source_path(
                repo_prefix=repo_prefix,
                relative_repo_path=parts[1],
            )
            if removed_path in baseline_paths:
                files_removed.add(removed_path)
            continue
        if status == "R" and len(parts) >= 3:
            removed_path = _to_workspace_source_path(
                repo_prefix=repo_prefix,
                relative_repo_path=parts[1],
            )
            new_path = _to_workspace_source_path(
                repo_prefix=repo_prefix,
                relative_repo_path=parts[2],
            )
            if removed_path in baseline_paths:
                files_removed.add(removed_path)
            if new_path in current_paths:
                if new_path in baseline_paths:
                    files_changed.add(new_path)
                else:
                    files_new.add(new_path)
            continue

        workspace_path = _to_workspace_source_path(
            repo_prefix=repo_prefix,
            relative_repo_path=parts[-1],
        )
        if workspace_path not in current_paths:
            continue
        if status == "A" or workspace_path not in baseline_paths:
            files_new.add(workspace_path)
        else:
            files_changed.add(workspace_path)

    files_to_process = tuple(sorted(files_new | files_changed))
    files_unchanged = tuple(sorted(current_paths - set(files_to_process)))
    return IncrementalFileDiffPlan(
        mode="incremental",
        fallback_reason=None,
        files_to_process=files_to_process,
        files_new=tuple(sorted(files_new)),
        files_changed=tuple(sorted(files_changed)),
        files_unchanged=files_unchanged,
        files_removed=tuple(sorted(files_removed)),
    )


def _git_worktree_has_markdown_changes(*, repo_root: Path) -> bool:
    status_completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "*.md",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_completed.returncode != 0:
        return True
    return bool(status_completed.stdout.strip())


def _to_workspace_source_path(*, repo_prefix: str, relative_repo_path: str) -> str:
    normalized_relative = relative_repo_path.strip().replace("\\", "/").lstrip("./")
    return f"{repo_prefix}/{normalized_relative}".strip("/")
