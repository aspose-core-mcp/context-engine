# Ingestion and retrieval examination — 7 October 2026

Historical review: this records the 7 October state. Queued plugin ingestion and
a Linux VM deployment were subsequently verified; see [deployment notes](../DEPLOYMENT.md)
and the [current plugin workflow](product-platform-plugins.md).

This is a code/configuration trace and offline verification of the evaluation
worktree. No services were started and no retained volumes were changed.

## Ingestion

1. `config/product-platform-plugins.json` registers Words/.NET and TeX/.NET;
   `compositions/total-net.json` combines them for serving, not ingestion.
2. `src/adcs/plugins/cli.py` selects the manifest and docs, apiref or both sources,
   builds a temporary source registry and injects `PlatformExtractionBackend`
   into `SourceHugoNormalizationOrchestrationService`.
3. Each package owns discovery, parsing, normalization, semantic chunking and API
   symbol extraction. The host invokes its worker over JSON stdin/stdout, checks
   contract, identity, scope, paths and revision, and limits call duration/output.
   `--python` selects an independent dependency environment. The default is a
   separate process using the host interpreter.
4. The host applies metadata validation/quarantine, canonical URL mapping and
   publication gates. It stages plugin chunks without re-running the legacy
   semantic chunker. Only accepted pages contribute structured symbols.
   Plugin runs force fresh extraction rather than reuse legacy extraction caches.
5. Default CLI execution validates; `--stage` writes REVIEW staging;
   `--publish` builds the configured runtime stores and publishes. Stage and
   publish export symbols and provenance under `artifacts/plugin-extraction`.
6. Documentation publication embeds chunks into Qdrant and writes OpenSearch
   lexical indexes. Snapshot scope includes product, language, version and source
   kind; lexical alias updates preserve other scopes.
7. Structured API publication skips dense/lexical writes, assigns the publication
   snapshot to plugin symbols, upserts them into PostgreSQL, then activates each
   symbol scope. API publication requires `APIREF_STRUCTURED_STORE_ENABLED=true`.
   This is not a distributed transaction: snapshot registration, index writes,
   staging promotion and symbol activation can fail at different points. A failure
   in a later source does not roll back an already published source.

The admin/API task dispatcher and Celery worker remain the legacy ingestion path.
Starting the worker does not automatically run the registered extraction plugins.

## Retrieval

`runtime/components.py` resolves persistent adapters to PostgreSQL and remote
retrieval to Qdrant/OpenSearch outside tests unless explicitly overridden. Tests
using AUTO select memory adapters. In structured mode, hybrid retrieval reads
documentation indexes only; API symbols enter through PostgreSQL.

`PublicQueryService.query_docs` checks the response cache, resolves product and
language, prepares translation, plans filters and active snapshots, retrieves and
reranks hybrid candidates, optionally retries without a language filter, then
adds structured symbol candidates. It packs context, applies the confidence gate
and emits citations, warnings and version/debug information. Product MCP tools
share the query service. Total dispatches across its members; the explicit plugin
composition is enabled with `ADCS_PRODUCT_PLUGIN_CATALOG`.

The live public query service combines docs and symbol candidates through its
candidate reranker. Do not confuse this with `TwoSourceRetriever`, a separate
harness implementing reciprocal-rank fusion. Symbol lookup prefers the structured
store and can fall back to the legacy dense path. API fan-out prefers the active
API version independently of the requested documentation version.

## Current startup prerequisites

- Docker inspection confirmed zero containers. API/worker and all five Compose
  dependency images remain, but their tags alone do not establish code provenance.
- Retained PostgreSQL/Qdrant/OpenSearch volume sets are named `adcs-github_*`,
  `adcs-local_*` and `words-net_*`. Contents were not inspected. Default Compose
  project naming in this worktree would create another set rather than attach
  these. Select an explicit project/volume mapping before recovery testing.
- The four manifest sources cannot currently be ingested: Words docs
  `source-repo-docs/Words-Net-Custom` is missing; Words API's directory is empty;
  both TeX source directories are missing. Existing source-root directories alone
  do not establish corpus availability. The CLI does not clone sources.
- No local `.env`/`.env.local` was found in this worktree. Compose defaults to
  `.env.compose.example`, which selects remote stores but leaves structured API
  storage disabled and the embedding backend at its deterministic default.
  Configure the intended embedding model/backend consistently for indexing and
  querying; determine the model/dimension used by retained vectors before reuse.
- Both Dockerfiles copy `src` and `config`, but omit `plugins` and `compositions`.
  The catalog cannot resolve its package manifests in those images without
  additional packaging/mounts. Dedicated plugin environments are also not built.
- This worktree's `.git` is a file pointing to the parent checkout's worktree
  metadata. The worker's current `./.git:/app/.git` bind mount does not by itself
  make that absolute host path or submodule git metadata usable in the container.
- PostgreSQL, Qdrant and OpenSearch have named volumes. Redis is configured
  without persistence and RabbitMQ has no declared data volume; their state is
  not restored simply by recreating these Compose services.

A useful live acceptance run first needs materialized sources, a chosen isolated
or recovered volume set, explicit runtime settings, and current plugin-capable
code. Start dependencies first, inspect stored snapshots/indexes/model compatibility,
then run one plugin/source through staging and publication and query it through
REST/MCP. Verify docs/API coexistence and other-product preservation before
expanding the corpus. No live acceptance result is claimed here.

## Verification performed

Using the existing parent checkout Python environment with `PYTHONPATH=src`:

```text
pytest -q tests/test_product_platform_plugins.py
  tests/test_snapshot_source_kind_coexistence.py tests/test_words_net_mcp.py
  tests/test_tex_net_mcp.py tests/test_total_net_mcp.py
  tests/test_public_query_apiref_fanout.py tests/test_two_source_end_to_end.py
193 passed, 1 skipped (5.15 seconds)
```

The skipped test requires `ADCS_TEST_POSTGRES_DSN`. These results verify fixtures
and offline wiring, not existing-volume recovery or full-corpus retrieval quality.
