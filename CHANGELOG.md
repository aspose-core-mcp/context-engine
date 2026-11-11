# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `/words/java/mcp/v1/streamable-http` product-scoped MCP endpoint (Aspose.Words
  for Java; aliases `java`, `jvm`). Content comes from a separately registered plugin.
- `/tex/java/mcp/v1/streamable-http` product-scoped MCP endpoint (Aspose.TeX for
  Java; aliases `java`, `jvm`). Content comes from the separately registered
  `aspose.tex.java` plugin.

### Changed

- Retrieval profiles accept Java package identities (`com.<product>.`) for
  preferred symbols, in addition to `<product>.`.

## [0.1.0] - 2026-09-15

Initial public release of the engine behind [Aspose.MCP](https://mcp.aspose.com).

### Added

- MCP server over streamable HTTP, SSE and stdio, with protocol revision
  negotiation for `2025-11-25`, `2025-06-18` and `2024-11-05`.
- Nine public retrieval tools: `resolve_product`, `query_docs`, `get_symbol_doc`,
  `list_breaking_changes`, `list_latest_release_features`, `aspose_lookup`,
  `get_symbol`, `list_members` and `search_symbols`, each with a `/v1/` REST
  counterpart.
- Hybrid retrieval — Qdrant dense vectors fused with OpenSearch BM25 — with
  version-aware filtering, `strict_version` mode and mandatory citations.
- Ingestion pipeline for Hugo-based documentation and API-reference repositories,
  with a normalized document contract, staging store and atomic snapshot publishing.
- Source registry covering 42 Aspose and GroupDocs products.
- Structured API-reference symbol store in PostgreSQL.
- Admin API and a Next.js admin console.
- Docker images, a Docker Compose stack, a Helm chart, a Prometheus `/metrics`
  endpoint and alert rules.
