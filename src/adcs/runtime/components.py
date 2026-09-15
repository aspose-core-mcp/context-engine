"""Shared runtime component bootstrap for API and worker processes."""

from __future__ import annotations

from dataclasses import dataclass

from adcs.admin import (
    AnalyticsService,
    InMemoryAnalyticsService,
    PostgresAnalyticsService,
)
from adcs.config import EmbeddingBackend, PersistenceBackend, RetrievalBackend, Settings
from adcs.indexing import (
    DeterministicLocalEmbeddingProvider,
    EmbeddingProvider,
    IndexPublishOrchestrator,
    IndexTopologyPolicy,
    InMemoryLexicalIndexWriter,
    InMemorySnapshotRegistry,
    InMemoryVectorIndexWriter,
    LexicalIndexWriter,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    OpenSearchLexicalIndexWriter,
    PostgresSnapshotRegistry,
    QdrantVectorIndexWriter,
    SnapshotRegistry,
    VectorIndexWriter,
    load_index_topology_policy,
)
from adcs.ingestion.job_repository import (
    IngestionJobRepository,
    InMemoryIngestionJobRepository,
    PostgresIngestionJobRepository,
)
from adcs.ops import (
    CriticalEventStore,
    InMemoryCriticalEventStore,
    InMemorySnapshotCleanupAuditStore,
    InMemorySnapshotRollbackAuditStore,
    PostgresCriticalEventStore,
    PostgresSnapshotCleanupAuditStore,
    PostgresSnapshotRollbackAuditStore,
    SnapshotCleanupAuditStore,
    SnapshotRollbackAuditStore,
)
from adcs.retrieval import (
    DenseLaneAdapter,
    LexicalLaneAdapter,
    OpenSearchLexicalLaneAdapter,
    QdrantDenseLaneAdapter,
)
from adcs.runtime import ResolvedRuntimeAdapters, resolve_runtime_adapters


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    adapter_modes: ResolvedRuntimeAdapters
    topology_policy: IndexTopologyPolicy
    embedding_provider: EmbeddingProvider
    critical_event_store: CriticalEventStore
    cleanup_audit_store: SnapshotCleanupAuditStore
    rollback_audit_store: SnapshotRollbackAuditStore
    ingestion_job_repository: IngestionJobRepository
    snapshot_registry: SnapshotRegistry
    index_publish_orchestrator: IndexPublishOrchestrator
    analytics_service: AnalyticsService
    dense_lane_adapter: DenseLaneAdapter | None
    lexical_lane_adapter: LexicalLaneAdapter | None
    lexical_index_writer: LexicalIndexWriter


_QUERY_EMBEDDING_TIMEOUT_SECONDS = 10.0


def build_embedding_provider(settings: Settings, *, for_queries: bool = False) -> EmbeddingProvider:
    """Embedding provider for ingestion, or a fail-fast one for query-time embeddings."""
    if settings.embedding_backend is EmbeddingBackend.OLLAMA:
        return OllamaEmbeddingProvider(
            model=settings.embedding_model,
            ollama_url=settings.ollama_url,
            timeout_seconds=_QUERY_EMBEDDING_TIMEOUT_SECONDS if for_queries else 300.0,
        )
    if settings.embedding_backend is EmbeddingBackend.OPENAI_COMPATIBLE:
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_api_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            timeout_seconds=_QUERY_EMBEDDING_TIMEOUT_SECONDS if for_queries else 30.0,
            max_retries=1 if for_queries else 5,
        )
    return DeterministicLocalEmbeddingProvider()


def build_runtime_components(settings: Settings) -> RuntimeComponents:
    """Build persistence/retrieval runtime adapters shared by API and workers."""
    adapter_modes = resolve_runtime_adapters(settings=settings)
    topology_policy = load_index_topology_policy(
        profile=settings.env_profile.value,
        config_path=settings.index_topology_policy_config_path,
    )

    critical_event_store: CriticalEventStore
    cleanup_audit_store: SnapshotCleanupAuditStore
    rollback_audit_store: SnapshotRollbackAuditStore
    ingestion_job_repository: IngestionJobRepository
    snapshot_registry: SnapshotRegistry
    analytics_service: AnalyticsService
    if adapter_modes.persistence_backend is PersistenceBackend.POSTGRES:
        critical_event_store = PostgresCriticalEventStore(postgres_dsn=settings.postgres_dsn)
        cleanup_audit_store = PostgresSnapshotCleanupAuditStore(
            postgres_dsn=settings.postgres_dsn
        )
        rollback_audit_store = PostgresSnapshotRollbackAuditStore(
            postgres_dsn=settings.postgres_dsn
        )
        snapshot_registry = PostgresSnapshotRegistry(postgres_dsn=settings.postgres_dsn)
        ingestion_job_repository = PostgresIngestionJobRepository(
            postgres_dsn=settings.postgres_dsn
        )
        analytics_service = PostgresAnalyticsService(postgres_dsn=settings.postgres_dsn)
        critical_event_store.ping()
        cleanup_audit_store.ping()
        rollback_audit_store.ping()
        snapshot_registry.ping()
        ingestion_job_repository.ping()
        analytics_service.ping()
    else:
        critical_event_store = InMemoryCriticalEventStore()
        cleanup_audit_store = InMemorySnapshotCleanupAuditStore()
        rollback_audit_store = InMemorySnapshotRollbackAuditStore()
        snapshot_registry = InMemorySnapshotRegistry()
        ingestion_job_repository = InMemoryIngestionJobRepository()
        analytics_service = InMemoryAnalyticsService()

    # Ingestion embeds large batches and retries transient failures with backoff. A query
    # embeds one short text inside a user request, so its provider fails fast and the
    # hybrid retriever answers from the lexical lane instead of waiting through retries.
    embedding_provider = build_embedding_provider(settings)
    query_embedding_provider = build_embedding_provider(settings, for_queries=True)

    dense_lane_adapter: DenseLaneAdapter | None = None
    lexical_lane_adapter: LexicalLaneAdapter | None = None
    vector_index_writer: VectorIndexWriter
    lexical_index_writer: LexicalIndexWriter
    if adapter_modes.retrieval_backend is RetrievalBackend.QDRANT_OPENSEARCH:
        vector_index_writer = QdrantVectorIndexWriter(
            qdrant_url=settings.qdrant_url,
            topology_policy=topology_policy,
            # The write lane must target the same collection the read lane serves
            # from. Hardcoded names (e.g. the retired docs_dense_v1) would send new
            # vectors into a collection nobody queries once its alias is dropped,
            # and make retention purges no-ops.
            docs_collection=settings.docs_vector_collection,
            apiref_collection=settings.apiref_vector_collection,
        )
        lexical_index_writer = OpenSearchLexicalIndexWriter(
            opensearch_url=settings.opensearch_url,
            topology_policy=topology_policy,
        )
        # When API Reference is served from the Postgres structured store
        # (ADR-011), the docs hybrid lane is docs-only: the
        # apiref_dense_v1 / apiref_lex_v1_active collections are retired and
        # apiref is fused in from Postgres at the query layer. When
        # the flag is off, both lanes keep the legacy dual-collection behaviour.
        if settings.apiref_structured_store_enabled:
            dense_lane_adapter = QdrantDenseLaneAdapter(
                qdrant_url=settings.qdrant_url,
                embedding_provider=query_embedding_provider,
                # The dense docs collection name is settings-driven
                # (``DOCS_VECTOR_COLLECTION``, default ``docs_dense_en_v1``) so the
                # serving lane, the admin coverage counters, and the DR
                # backup/restore bundle all agree on one name. Overriding the alias
                # back to ``docs_dense_v1`` restores the legacy behaviour.
                collection_names=(settings.docs_vector_collection,),
            )
            lexical_lane_adapter = OpenSearchLexicalLaneAdapter(
                opensearch_url=settings.opensearch_url,
                index_aliases=("docs_lex_v1_active",),
            )
        else:
            dense_lane_adapter = QdrantDenseLaneAdapter(
                qdrant_url=settings.qdrant_url,
                embedding_provider=query_embedding_provider,
            )
            lexical_lane_adapter = OpenSearchLexicalLaneAdapter(
                opensearch_url=settings.opensearch_url
            )
    else:
        vector_index_writer = InMemoryVectorIndexWriter(topology_policy=topology_policy)
        lexical_index_writer = InMemoryLexicalIndexWriter(topology_policy=topology_policy)

    from pathlib import Path

    _workspace_root = Path(__file__).resolve().parents[3]
    checkpoint_dir = _workspace_root / "logs" / "publish_checkpoints"

    index_publish_orchestrator = IndexPublishOrchestrator(
        embedding_provider=embedding_provider,
        vector_index_writer=vector_index_writer,
        lexical_index_writer=lexical_index_writer,
        snapshot_registry=snapshot_registry,
        checkpoint_dir=checkpoint_dir,
    )
    return RuntimeComponents(
        adapter_modes=adapter_modes,
        topology_policy=topology_policy,
        embedding_provider=embedding_provider,
        critical_event_store=critical_event_store,
        cleanup_audit_store=cleanup_audit_store,
        rollback_audit_store=rollback_audit_store,
        ingestion_job_repository=ingestion_job_repository,
        snapshot_registry=snapshot_registry,
        index_publish_orchestrator=index_publish_orchestrator,
        analytics_service=analytics_service,
        dense_lane_adapter=dense_lane_adapter,
        lexical_lane_adapter=lexical_lane_adapter,
        lexical_index_writer=lexical_index_writer,
    )
