# ADR-011: Low-RAM retrieval — corpus split, storage engine, and fan-out harness

## Status
Accepted.

Revisits **ADR-001** (Vector DB selection) and extends **ADR-004** (Hybrid
retrieval); see the [ADR registry](README.md).

## Context

1. **Two different corpora.** ADCS serves unstructured DOCUMENTATION (semantic
   queries) and structured API REFERENCE (a tree of terse technical strings;
   exact and structural queries). Initially both were indexed as 4096-dim dense
   vectors in Qdrant plus OpenSearch BM25.
2. **Memory budget.** ADR-001 chose Qdrant for a Kubernetes-distributed scale.
   The typical deployment is a single node with a hard RAM budget. At 4096
   dimensions the API-reference vectors alone take about 2.6 GiB (162k symbols),
   and the documentation vectors a similar amount; once the memory cap falls
   below the working set, query latency collapses.
3. **Retrieval quality.** Dense embeddings are systematically weak on exact
   identifiers — symbol names, versions, codes. Reference tools such as
   Sourcegraph, Aider, DevDocs and Dash/Zeal use lexical and structural lookup
   for symbols rather than embeddings.
4. **Existing infrastructure.** ADCS already runs PostgreSQL as its metadata
   store.

## Decision

1. **Split by corpus type.** API reference is removed from dense vectors and
   served from a structured PostgreSQL store: a `symbols` table with full-text
   search, `pg_trgm` similarity and exact FQN lookup, made version-aware through
   `apiref_active_snapshot`
   ([`apiref_symbol_store.py`](../../src/adcs/indexing/apiref_symbol_store.py)).
   Ingestion writes it through `ApiRefSymbolPublisher`
   ([`apiref_symbol_publisher.py`](../../src/adcs/indexing/apiref_symbol_publisher.py)),
   which aggregates the signature, parameter and return chunks of each
   `api_reference_symbol` document into one row. The store is enabled with
   `APIREF_STRUCTURED_STORE_ENABLED=true`.
2. **Storage engine.** Documentation stays on Qdrant (dense) and OpenSearch
   (BM25). pgvector was ruled out for documentation because its HNSW index is
   capped at 2,000 dimensions, which would force truncating the embeddings.
   LanceDB has a much smaller footprint, but its IVF_PQ index is lossy and its
   recall was not validated. Qdrant keeps the memory footprint elastic: with an
   embedding model that supports Matryoshka representations (MRL), vectors can
   be truncated (for example 4096 → 256 dimensions) and renormalised without
   re-embedding.
3. **API-reference retrieval is not vector-based**, so vector-engine limits do
   not apply to it, and its memory use does not grow with the vector budget.
4. **Harness: always fan out to both corpora**, never route a query to only one.
   `query_docs` fuses API-reference symbols from the PostgreSQL store into the
   documentation candidates and reranks them together
   ([`public_docs_query.py`](../../src/adcs/api/public_docs_query.py)).
   [`TwoSourceRetriever`](../../src/adcs/retrieval/two_source_retriever.py)
   provides standalone fusion of the two ranked lists with Reciprocal Rank
   Fusion (k=60), an exact-FQN short-circuit and deduplication by
   `canonical_url`. The MCP surface is multi-tool: `resolve_product`,
   `query_docs`, `get_symbol_doc`, `list_breaking_changes`,
   `list_latest_release_features`, and the structured tools `aspose_lookup`,
   `get_symbol`, `list_members` and `search_symbols`.

## Consequences

1. **Positive.** API reference leaves the vector memory budget, and adding
   products does not grow that budget for API reference. Exact-symbol precision
   improves: symbol lookups hit exact FQNs, names and full-text matches instead
   of nearest neighbours. Recall of the structured path is measured with
   [`apiref_recall_eval.py`](../../src/adcs/retrieval/apiref_recall_eval.py).
   `get_symbol_doc` reads from the structured store first and falls back to the
   dense path only when the store is unavailable or has no match.
2. **Negative / risks.** Ingestion gains a second build artifact (symbol rows),
   covered end to end by `tests/test_apiref_full_chain.py` (Hugo → converter →
   chunker → staging → publisher → store → query) and
   `tests/test_apiref_app_boot.py`. RRF without labeled tuning is a robust
   default rather than an optimum; a tuned convex combination may rank better.
3. **Retiring the dense API-reference indexes.** Once the PostgreSQL store holds
   the symbols, the Qdrant `apiref_dense_v1` collection and the OpenSearch
   `apiref_lex_v1_active` alias are no longer queried and can be removed with
   `scripts/drop_apiref_indexes.py` (dry run by default; it refuses to run until
   the store holds symbols). Rollback is a restore from a Qdrant snapshot of
   `apiref_dense_v1` taken beforehand; no re-embedding is needed.

## References

1. ADR-001 — Vector DB selection (Qdrant), revisited by this ADR; see the [ADR registry](README.md).
2. ADR-004 — Hybrid retrieval, extended by this ADR.
3. [arXiv:2110.06918](https://arxiv.org/abs/2110.06918) and [arXiv:2506.08592](https://arxiv.org/abs/2506.08592) — on the weakness of dense retrieval for exact lexical matches.
