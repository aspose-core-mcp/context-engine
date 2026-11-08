# Architecture

ADCS (Aspose Developer Context Service) is a Context7-style retrieval platform that delivers version-aware, citation-backed Aspose and GroupDocs documentation to AI-IDEs and AI assistants via MCP and REST APIs.

This document is a top-level architectural overview; architecture decisions are indexed in [`adr/README.md`](adr/README.md). Visual diagrams: [`svg-architecture.html`](svg-architecture.html) (system topology), [`svg-retrieval-modes.html`](svg-retrieval-modes.html) (the three retrieval modes — symbol-first, task/how-to, migration), [`svg-sdk-languages.html`](svg-sdk-languages.html) (SDK language coverage map).

## Three-Plane Model

ADCS separates concerns across three execution planes, each scaled and operated independently.

### Control Plane
- Source registry management — `config/source-repositories.yaml`
- Ingestion scheduling and orchestration — `src/adcs/ingestion/source_*_orchestrator.py`
- Snapshot lifecycle (publish/rollback/cleanup) — `src/adcs/indexing/publish_orchestrator.py`, `src/adcs/ops/snapshot_*`
- Admin policy engine, RBAC, audit — `src/adcs/api/admin_*.py`
- Configuration history with rollback — `src/adcs/admin/config_history.py`

### Data Plane
- Document parsing and normalization — `src/adcs/ingestion/hugo_parser.py`, `normalized_document.py`
- Chunking and embedding generation — `src/adcs/ingestion/chunking.py`, `src/adcs/indexing/embedding_provider.py`. Embeddings come from an OpenAI-compatible embedding API (`ADCS_EMBEDDING_BACKEND=openai_compatible`, endpoint `ADCS_EMBEDDING_API_URL`); an `ollama` backend is also available. The settings default is the local `deterministic` backend, which the `prod` profile refuses to start with (`src/adcs/config/settings.py`).
- Vector index (Qdrant) and lexical index (OpenSearch) writers — `src/adcs/indexing/vector_index_writer.py`, `lexical_index_writer.py`
- Metadata store (PostgreSQL) — SQLAlchemy-backed stores owned by each component, e.g. `src/adcs/indexing/snapshot_registry.py`, `src/adcs/ingestion/job_repository.py`, `src/adcs/indexing/apiref_symbol_store.py`
- Background workers (Celery) — `src/adcs/worker/`

### API Plane
- Public REST endpoints — `src/adcs/api/main.py`
- MCP HTTP gateway — `src/adcs/api/mcp_gateway.py`
- MCP stdio server — `src/adcs/mcp/stdio_server.py`
- WebMCP browser adapter (optional, feature-flagged) — `src/adcs/api/webmcp_*.py`
- Admin API endpoints — `src/adcs/api/admin_*.py`

## 15 Core Components

| # | Component | Responsibility | Key files |
|---|-----------|----------------|-----------|
| 1 | Source Connectors | Git/file adapters | `src/adcs/ingestion/source_adapters.py` |
| 2 | Ingestion Orchestrator | Pipeline scheduling | `src/adcs/ingestion/source_*_orchestrator.py` |
| 3 | Parser & Normalizer | Markdown → normalized doc | `src/adcs/ingestion/hugo_parser.py`, `normalized_document.py` |
| 4 | Chunker | Structure-aware segmentation (300–900 tokens) | `src/adcs/ingestion/chunking.py` |
| 5 | Embedding Service | Vector generation via an OpenAI-compatible embedding API (settings default: deterministic local backend) | `src/adcs/indexing/embedding_provider.py`, `src/adcs/config/settings.py` |
| 6 | Index Store | Vector (Qdrant) + lexical (OpenSearch) | `src/adcs/indexing/vector_index_writer.py`, `lexical_index_writer.py` |
| 7 | Metadata Store | Versions, symbols, aliases, audit | PostgreSQL stores, e.g. `src/adcs/indexing/snapshot_registry.py`, `src/adcs/indexing/apiref_symbol_store.py` |
| 8 | Retrieval API | Hybrid search + reranking | `src/adcs/retrieval/` |
| 9 | MCP Gateway | 5 core MCP tools, plus 4 structured API-reference tools backed by the Postgres symbol store | `src/adcs/api/mcp_gateway.py`, `src/adcs/mcp/tool_gateway.py` |
| 10 | MCP Compatibility Layer | Revision negotiation (3 protocol versions) | `src/adcs/mcp/revision_negotiation.py` |
| 11 | Admin API | Management plane (RBAC + audit) | `src/adcs/api/admin_*.py` |
| 12 | WebMCP Adapter | Optional browser channel | `src/adcs/api/webmcp_*.py` |
| 13 | Translation Adapter | Detect → translate → retrieve → reverse-translate | `src/adcs/retrieval/translation_fallback.py` |
| 14 | Notification Service | SMTP for critical events | `src/adcs/ops/critical_events.py`, `notifications.py` |
| 15 | Observability | Prometheus metrics, structured logs, optional request tracing | `src/adcs/api/metrics.py`, `src/adcs/ops/metrics.py`, `src/adcs/ops/logging_config.py`, `src/adcs/ops/tracing.py` |

## Layered Data Flow

```
Layer 0: Raw Sources         (git submodules: source-repo-apiref/, source-repo-docs/)
   ↓ ingestion orchestrator
Layer 1: Normalized Staging  (data-apiref/, data-docs/, schema: adcs.normalized_document.v1)
   ↓ embedding + atomic publish
Layer 2: Indexes             (Qdrant collections + OpenSearch indices)
   ↓ hybrid search
API Plane:                   (MCP tools / REST endpoints)
```

## Sequence: `query_docs` Tool

1. Client invokes MCP tool or REST endpoint
2. Gateway applies abuse guards and rate limits — `src/adcs/api/abuse_guard.py`
3. Retrieval API normalizes query and filters
4. Translation fallback if non-English — `src/adcs/retrieval/translation_fallback.py`
5. Hybrid search (vector + lexical lanes fused) — `src/adcs/retrieval/hybrid_retriever.py`
6. Reranker re-orders top-N — `src/adcs/retrieval/reranker.py`
7. Strict version filter applied if `strict_version=true`
8. Context packer assembles final response — `src/adcs/retrieval/context_packer.py`
9. Citations attached (canonical_url, section_anchor, source_revision)

## Sequence: Documentation Update

1. Cron or webhook triggers source sync — `src/adcs/ingestion/source_sync_orchestrator.py`
2. Orchestrator creates `operation_id` for idempotency
3. Layout detection identifies dimensions — `src/adcs/ingestion/source_layout_detection_orchestrator.py`
4. Parser → chunker → embedding → staging — `src/adcs/ingestion/source_hugo_normalization_orchestrator.py`
5. Quality gates evaluate the staged corpus — `src/adcs/quality_gates/`
6. Semantic review gate (2-reviewer + PO tie-break for major changes) — `src/adcs/admin/quality_reviews.py`
7. Atomic snapshot switch promotes staging → active — `src/adcs/indexing/publish_orchestrator.py`
8. Audit trail recorded — `src/adcs/ops/snapshot_rollback_audit.py`

## Version Isolation

- Indexes keyed by `product:language:version:snapshot_id`
- `strict_version=true` mode never mixes versions
- `latest` resolved through policy table
- Atomic snapshot switches enable zero-downtime reindexing

## Observability Architecture

- **Metrics**: the API serves Prometheus metrics at `/metrics` — HTTP request counts and latency histograms, retrieval-quality ratios (`adcs_citation_missing_ratio`, `adcs_retrieval_confidence_low_ratio`), MCP revision negotiation, abuse-guard decisions, and snapshot and publish SLIs read from PostgreSQL at scrape time — `src/adcs/api/metrics.py`, `src/adcs/ops/metrics.py`, `src/adcs/api/ingestion_slis.py`
- **Alerting**: Prometheus alert rules over those metrics in [`infra/observability/prometheus/adcs-alerts.yaml`](../infra/observability/prometheus/adcs-alerts.yaml)
- **Logs**: structured JSON on stdout with PII masking — `src/adcs/ops/logging_config.py`; see [data protection](data-protection-and-pii.md)
- **Tracing**: optional. With the `tracing` extra installed and `ADCS_TRACING_ENABLED=true`, the request middleware opens one span per HTTP request and exports it over OTLP/HTTP when `ADCS_TRACING_OTLP_ENDPOINT` is set — `src/adcs/ops/tracing.py`
- **Admin summary**: `GET /admin/v1/observability/summary` reports MCP negotiation and abuse-guard counters, the tracing configuration, the latest deploy smoke result and the alert-rule and canary settings from `config/observability-control-plane.json` and `config/canary-policy.json` — `src/adcs/api/admin_observability.py`

## Failure Domains and Degradation Modes

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Vector backend or embedding endpoint down | Dense-lane error or lane timeout (`ADCS_HYBRID_LANE_TIMEOUT_SECONDS`); the query embedding makes a single attempt with a 10 s timeout, while ingestion retries with backoff | Lexical-only results from `hybrid_retriever.py` |
| Lexical backend down | Lexical-lane error or lane timeout | Dense-only results from `hybrid_retriever.py` |
| Translation LLM unavailable | Detection failures open a circuit breaker | Query served untranslated with a warning — `translation_fallback.py` |
| Ingestion partial failure | Error ratio above `ADCS_INGESTION_PARTIAL_PUBLISH_THRESHOLD_PCT` (default 30 %) | Block publish; last good snapshot stays active |
| Critical event | SMTP notification | See `src/adcs/ops/critical_events.py` |

## Related Documents

- [Orchestration boundaries](orchestration-boundaries.md) — state machines, control flow, extension points
- [Quality loop](quality-loop.md) — continuous quality-improvement agents
- [RBAC and audit](rbac-and-audit.md) — security architecture
- [Observability](../infra/observability/README.md) — metrics and alert rules
- [Test coverage matrix](test-coverage-matrix.md) — verification mapping
- [Architecture decision records](adr/README.md) — decision registry, including [ADR-011](adr/011-low-ram-retrieval-storage-and-harness.md), which revisits the vector DB selection
