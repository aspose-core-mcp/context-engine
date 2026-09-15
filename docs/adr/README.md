# Architecture Decision Records (ADR)

This directory indexes the architecture decision records for ADCS. The registry below summarises each decision and points to the code that implements it; ADR-011 also has a full record in this directory.

## Format

We follow the lightweight ADR format: Context, Decision, Consequences, Status, Revisit Conditions.

## Status Values

- **Proposed** — under discussion
- **Accepted** — current decision in force
- **Superseded** — replaced by a newer ADR (link required)
- **Deprecated** — no longer recommended

## Registry

| ID | Title | Status | Implemented in |
|----|-------|--------|----------------|
| ADR-001 | Vector DB selection (Qdrant vs Milvus vs pgvector) | Accepted (revisited by ADR-011) | [`src/adcs/indexing/vector_index_writer.py`](../../src/adcs/indexing/vector_index_writer.py) |
| ADR-002 | WebMCP integration (feature-flagged browser adapter) | Accepted | [`src/adcs/api/webmcp_gateway.py`](../../src/adcs/api/webmcp_gateway.py), [`webmcp_confirmation.py`](../../src/adcs/api/webmcp_confirmation.py), [`webmcp_audit.py`](../../src/adcs/api/webmcp_audit.py) |
| ADR-003 | MCP revision compatibility (multi-version support) | Accepted | [`src/adcs/mcp/revision_negotiation.py`](../../src/adcs/mcp/revision_negotiation.py) |
| ADR-004 | Hybrid retrieval (vector + lexical fusion) | Accepted (extended by ADR-011) | [`src/adcs/retrieval/hybrid_retriever.py`](../../src/adcs/retrieval/hybrid_retriever.py) |
| ADR-005 | `adcs.normalized_document.v1` ingestion contract | Accepted | [`src/adcs/ingestion/normalized_document.py`](../../src/adcs/ingestion/normalized_document.py) |
| ADR-006 | Hugo conversion pipeline (AI-assisted normalization) | Accepted | [`src/adcs/ingestion/source_hugo_normalization_orchestrator.py`](../../src/adcs/ingestion/source_hugo_normalization_orchestrator.py), [`prompts/hugo_conversion/`](../../prompts/hugo_conversion/README.md) |
| ADR-007 | Admin UI architecture (Next.js console) | Accepted | [`frontend/admin/`](../../frontend/admin/) |
| ADR-008 | Atomic snapshot switching for zero-downtime reindex | Accepted | [`src/adcs/indexing/publish_orchestrator.py`](../../src/adcs/indexing/publish_orchestrator.py), [`snapshot_registry.py`](../../src/adcs/indexing/snapshot_registry.py) |
| ADR-009 | Semantic review gate (2-reviewer + PO tie-break) | Accepted | [`src/adcs/admin/quality_reviews.py`](../../src/adcs/admin/quality_reviews.py) |
| ADR-010 | MCP/REST functional parity invariant | Accepted | [`src/adcs/mcp/tool_gateway.py`](../../src/adcs/mcp/tool_gateway.py); verified by [`tests/test_mcp_rest_parity_offline.py`](../../tests/test_mcp_rest_parity_offline.py), [`tests/test_public_rest_parity.py`](../../tests/test_public_rest_parity.py) |
| ADR-011 | Low-RAM retrieval: corpus split + storage engine + fan-out harness (revisits ADR-001) | Accepted | [`docs/adr/011-low-ram-retrieval-storage-and-harness.md`](011-low-ram-retrieval-storage-and-harness.md) |

## How to Add a New ADR

1. Create `docs/adr/{NNN}-{slug}.md` with the sections listed under Format (Context, Decision, Consequences, Status, Revisit Conditions)
2. Set the status to `Proposed`
3. Add a row to the table above
4. Open a pull request with the `architecture` label
5. Update status to `Accepted` after approval
