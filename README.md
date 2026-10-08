# Aspose Product MCP Plugins

This is Muhammad Sabir's reference implementation for Imran Anwar to evaluate and
extend into the complete plugin architecture. It provides independent Words/.NET
and TeX/.NET extraction packages with isolated workers and a shared output contract.
Total/.NET composes member data. Extraction remains plugin-owned; common engine
orchestration, staging, indexing and serving remain shared.

This evaluation does not enforce plugin-only ingestion across all entry points,
and remains an evaluation rather than a production release. A Linux VM deployment
now runs the API and queued Words/.NET ingestion; see [deployment notes](DEPLOYMENT.md)
for the dated validation and publication status. It incorporates the
source-kind snapshot prerequisite from upstream MR !1 at `0534897`; it does not
include that MR's other changes or imply that the MR has been merged.
See [setup, architecture, commands and limitations](docs/product-platform-plugins.md)
and [verification evidence](docs/plugin-evaluation-verification.md).

The pilot README below describes the original `d00ac79` baseline; its statements
about excluded snapshot fixes apply to that baseline, not this evaluation branch.

# Aspose Product MCP Pilot

Product-first MCP pilot built on [Aspose Context Engine](https://github.com/aspose-mcp/aspose-context-engine).
Individual Words and TeX scopes are implemented first, then combined through Total.
The initial verified scope is .NET; this is not a production release or a CLI pilot.

| MCP endpoint | Scope |
| --- | --- |
| `/words/net/mcp/v1/streamable-http` | Aspose.Words for .NET |
| `/tex/net/mcp/v1/streamable-http` | Aspose.TeX for .NET |
| `/total/net/mcp/v1/streamable-http` | Words and TeX for .NET, grouped or explicitly selected |

All three support GET SSE and POST JSON-RPC. Product and language restrictions are
server-enforced. Total reuses the individual product dispatch and existing indexes;
it does not ingest duplicate data or call separate product HTTP servers.

The pilot was verified locally on port 8082 against already ingested Words and TeX
content. Local credentials, source checkouts, databases, and runtime evidence are
not included in this repository. Configure and ingest sources for a fresh deployment;
the Git repository alone does not contain the indexed content. The original local
checkout also has ingestion-specific configuration and snapshot lifecycle fixes
that are not included in this endpoint-focused branch.

Validation: 174 endpoint and shared MCP regression tests passed. Live checks verified
documentation and symbol results from both products, explicit product selection,
and rejection of unsupported products and SDK languages. Broader platform coverage,
CLI pilots, catalog publication, and production rollout remain separate work.

The upstream documentation below describes the underlying Context Engine. Its hosted
service references are upstream references, not deployment claims for this pilot.

## Upstream Aspose Context Engine

[![CI](https://github.com/aspose-mcp/aspose-context-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/aspose-mcp/aspose-context-engine/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**ADCS — the Aspose Developer Context Service** — gives AI coding assistants accurate,
version-aware, citation-backed documentation and API reference for Aspose and GroupDocs
SDKs, over the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) and a REST
API. It powers Aspose.MCP, the [hosted server](#use-the-hosted-server) described below.

## Why

AI assistants write code from what they remember about a library. For SDK families that
ship every month, that memory goes stale: methods get renamed, overloads disappear, and
signatures from the Java SDK leak into C# code. The result compiles only in the model's
imagination.

ADCS puts a retrieval layer between the assistant and the official documentation:

- **Version-aware.** Every chunk carries `product_id`, `language` and `version`;
  `strict_version` queries never mix API generations.
- **Language-specific.** .NET, Java, C++, Python and other SDK surfaces are indexed
  separately, so similar-sounding APIs do not cross-contaminate.
- **Hybrid search.** Qdrant dense vectors and OpenSearch BM25 run in parallel and are fused
  (55 % / 45 % by default), then reranked — intent and exact names both count.
- **Exact symbol lookup.** Signatures, parameters, return types and examples by fully
  qualified name.
- **Always cited.** Every result includes `canonical_url`, `section_anchor`,
  `source_revision` and a score, so answers can be verified against the source.

The source registry covers **42 products** — 27 Aspose and 15 GroupDocs product families —
across their documentation and API-reference repositories.

## Use the hosted server

The public instance needs no installation and no API key:

```text
https://mcp.aspose.com/mcp/v1/streamable-http
```

Claude Code:

```bash
claude mcp add --transport http aspose-docs https://mcp.aspose.com/mcp/v1/streamable-http
```

Cursor (`.cursor/mcp.json`) and other clients that accept a JSON server list:

```json
{
  "mcpServers": {
    "aspose-docs": {
      "url": "https://mcp.aspose.com/mcp/v1/streamable-http"
    }
  }
}
```

[MCP-SERVER.md](MCP-SERVER.md) covers transports, protocol revisions and tool details.

## Tools

| Tool | Purpose |
|------|---------|
| `resolve_product` | Map a product name or alias to its canonical ID and default SDK language |
| `query_docs` | Hybrid search over guides and API reference with product, language and version filters |
| `get_symbol_doc` | Exact signature, parameters, return type and examples for a class or method |
| `list_breaking_changes` | Breaking changes and deprecations between two versions |
| `list_latest_release_features` | New features and migration hints from the latest release |
| `aspose_lookup`¹ | One-shot natural-language API lookup with signatures inline |
| `get_symbol`¹ | All overloads of a fully qualified member |
| `list_members`¹ | Members of a class or namespace |
| `search_symbols`¹ | Fuzzy and full-text search over API symbols |

¹ Backed by the PostgreSQL structured symbol store. Enable it with
`APIREF_STRUCTURED_STORE_ENABLED=true`; otherwise calls to these tools return an error
saying the store is not configured.

Every tool has a REST counterpart under `/v1/` — for example `POST /v1/docs:query` — with
the same semantics and error model.

## How it works

```text
 AI IDE / agent ──MCP or REST──▶ API & MCP gateway ──▶ retrieval engine
                                                        query planner → filter resolver
                                                        hybrid retriever → reranker
                                                        context packer (citations)
                                                                 │
                                    Qdrant (dense) · OpenSearch (BM25) · PostgreSQL
                                                                 ▲
 docs & API-reference repos ──▶ ingestion: parse → normalize → chunk → embed
                                → staging store → atomic snapshot publish
```

1. **Ingestion.** Documentation and API-reference repositories (Hugo Markdown, tracked as
   git submodules) are parsed, normalized into the `adcs.normalized_document.v1` contract,
   chunked and embedded.
2. **Publishing.** Chunks land in a staging store first; the publish orchestrator promotes
   them to the vector and lexical indexes with an atomic snapshot switch, so queries never
   see a half-built index and the previous snapshot can be restored.
3. **Retrieval.** Queries are planned, filtered by product, language and version, run
   through both search lanes, fused, reranked and packed with citations. Non-English queries
   can be translated first by an OpenAI-compatible LLM.
4. **Operations.** An admin API and a Next.js console cover health, analytics, ingestion
   jobs, the source registry, snapshots, configuration history and quality reviews.

## Run it yourself

For this plugin checkout on a Linux VM, use the
[API and Words/.NET ingestion deployment guide](docs/linux-vm-deployment.md).
It includes a separate VM Compose profile, persistent storage and queued ingestion.

### Requirements

- Python 3.12+
- Docker with Docker Compose
- GNU Make
- Node.js 22+ for the admin console

### Docker Compose

```bash
git clone https://github.com/aspose-mcp/aspose-context-engine.git
cd aspose-context-engine
make up      # build the API and worker images; start PostgreSQL, Valkey, RabbitMQ, Qdrant, OpenSearch
make smoke   # check that the stack is healthy
```

The API and MCP gateway listen on `http://localhost:8080`; the MCP endpoint is
`http://localhost:8080/mcp/v1/streamable-http`. The stack reads `.env.compose.example`,
which holds placeholders only — for anything beyond a local trial, copy it to
`.env.compose.local`, replace the passwords and run `make up COMPOSE_ENV_FILE=.env.compose.local`.

### Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install-dev
cp .env.example .env.local   # settings load from .env.local, then .env
make infra-up                # infrastructure containers only
make run                     # API on :8080
make run-worker              # Celery worker, in a second terminal
```

Admin console:

```bash
cd frontend/admin
cp .env.example .env.local
npm ci
npm run dev                  # http://localhost:3000
```

The admin API and console authenticate with an `x-api-key`; see `ADCS_API_KEY` and
`ADCS_ADMIN_KEYS_SOURCE` in [`.env.example`](.env.example).

### Load documentation

Sources are registered in [`config/source-repositories.yaml`](config/source-repositories.yaml)
and checked out as git submodules under `source-repo-docs/` and `source-repo-apiref/`. To
index one product, fetch its repositories and run the ingestion script against the running
infrastructure:

```bash
git submodule update --init --depth 1 source-repo-docs/Aspose.OCR source-repo-apiref/Aspose.OCR
PYTHONPATH=./src python3 scripts/run_full_ingestion.py
```

The script ingests every checked-out repository, publishes the result and checkpoints its
progress in `logs/`, so an interrupted run can resume. Ingestion jobs can also be started
from the admin console.

The API caches query responses in-process for up to 15 minutes. If it was already running
while you ingested, restart it so earlier queries see the new content — for the Compose
stack: `docker compose -f docker-compose.integration.yml -p adcs-local restart api`.

Embeddings default to a deterministic local provider intended for development and tests.
For real semantic search, set `ADCS_EMBEDDING_BACKEND` to `openai_compatible` (with
`ADCS_EMBEDDING_API_URL`, `ADCS_EMBEDDING_API_KEY` and `ADCS_EMBEDDING_MODEL`) or to
`ollama` (with `OLLAMA_URL`).

### MCP over stdio

Clients that launch a server as a subprocess can use the `adcs-mcp-stdio` console script
installed with the package. It reads the same settings as the API:

```json
{
  "mcpServers": {
    "adcs": {
      "command": "adcs-mcp-stdio"
    }
  }
}
```

### Kubernetes

A Helm chart lives in [`infra/helm/adcs`](infra/helm/adcs). It runs the `prod` profile,
which refuses placeholder credentials; the [chart README](infra/helm/adcs/README.md) lists
the values you must supply — images, backing services, secrets and an embedding endpoint.
The API exposes Prometheus metrics at `/metrics`; alert rules are in
[`infra/observability`](infra/observability), and operational runbooks in
[`infra/runbooks`](infra/runbooks).

### Clean-room deployments

ADCS runs without any Aspose-hosted service, so it fits isolated and air-gapped
environments:

- **No phone-home.** The service sends no usage telemetry, and LLM and embedding endpoints
  default to local addresses. The Swagger UI and ReDoc pages load their assets from public
  CDNs, so they are off by default (`ADCS_API_DOCS_ENABLED=false`); `/openapi.json` is
  always served.
- **Public build inputs.** Python packages come from PyPI (the container images install
  the hash-pinned set in `constraints.txt`), admin-console packages from npm, and base
  images from Docker Hub — mirror them for offline builds. The admin console's fonts are
  committed to the repository, so no build step downloads them.
- **Your own documentation sources.** The repositories in
  [`config/source-repositories.yaml`](config/source-repositories.yaml) are public GitHub
  repositories; point them and `.gitmodules` at internal mirrors when GitHub is not
  reachable.
- **Local models.** The deterministic embedder works fully offline for evaluation. For real
  semantic search, run an embedding model inside the environment (Ollama or any
  OpenAI-compatible server). Query translation uses the endpoint in
  [`config/translation_llm.json`](config/translation_llm.json); when it is unreachable,
  queries are served untranslated.

## Configuration

The most important settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_DSN` | `postgresql+psycopg://adcs:adcs@localhost:5432/adcs` | Metadata database |
| `QDRANT_URL` | `http://localhost:6333` | Dense vector index |
| `OPENSEARCH_URL` | `http://localhost:9200` | Lexical (BM25) index |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache and rate-limit counters (any Redis-compatible server, such as Valkey) |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672//` | Celery broker (local development default) |
| `ADCS_EMBEDDING_BACKEND` | `deterministic` | `deterministic`, `ollama` or `openai_compatible` |
| `ADCS_HYBRID_DENSE_WEIGHT` / `ADCS_HYBRID_LEXICAL_WEIGHT` | `0.55` / `0.45` | Fusion weights |
| `APIREF_STRUCTURED_STORE_ENABLED` | `false` | Serve API reference from the PostgreSQL symbol store |
| `ADCS_API_DOCS_ENABLED` | `false` | Swagger UI and ReDoc pages (their assets load from public CDNs) |
| `ADCS_WEBMCP_ENABLED` | `false` | Browser (WebMCP) adapter |
| `ADCS_ABUSE_GUARD_MODE` | `observe-only` | Rate limiting: `observe-only` or `enforce` |

The full list is in [`.env.example`](.env.example) and
[`src/adcs/config/settings.py`](src/adcs/config/settings.py). Production credentials
belong in a secret store — see [docs/secrets-handling.md](docs/secrets-handling.md).

## Project layout

```text
src/adcs/
├── api/              FastAPI app: public REST, MCP and WebMCP gateways, admin API
├── mcp/              MCP stdio transport, tool gateway, revision negotiation
├── retrieval/        query planning, hybrid retrieval, reranking, context packing
├── ingestion/        source registry, Hugo parsing, normalization, layout detection, staging
├── indexing/         embedding providers, index writers, snapshot publishing
├── admin/            analytics, registries, configuration history, quality reviews, tenancy
├── quality_gates/    golden-dataset evaluation, performance profiles, release readiness
├── quality_loop/     multi-agent retrieval-quality loop
├── ops/              logging, privacy, backups, critical events, tracing
├── llm_proxy/        tool-aware OpenAI-compatible proxy
├── runtime/          component wiring
├── worker/           Celery app and tasks
└── config/           typed settings
frontend/admin/       Next.js admin console
config/               source registry, retrieval, LLM and quality-gate policies
prompts/              versioned LLM prompts for Hugo conversion
infra/                Helm chart, observability, runbooks, chaos drills, Pact broker
scripts/              ingestion, quality-gate and operations tooling
tests/                pytest suite
docs/                 architecture notes and ADRs
```

## Development

```bash
make lint        # ruff
make typecheck   # mypy
make test        # pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## Documentation

- [MCP-SERVER.md](MCP-SERVER.md) — MCP transports, revisions and tools
- [docs/architecture.md](docs/architecture.md) — components and data flow
- [docs/quality-loop.md](docs/quality-loop.md) — the retrieval-quality loop
- [docs/multi-tenancy.md](docs/multi-tenancy.md) — tenancy model
- [docs/adr/](docs/adr/) — architecture decision records
- [CHANGELOG.md](CHANGELOG.md) — release history

## Third-party licenses

ADCS is MIT-licensed, and everything it needs at runtime is open source:

- **Python dependencies** are permissive (MIT, BSD, Apache-2.0), except `psycopg`
  (LGPL-3.0) and `certifi` (MPL-2.0), which are used unmodified as ordinary libraries.
  Development-only tools add MPL-2.0 packages (`hypothesis`, `pathspec`).
- **Admin console dependencies** are MIT, Apache-2.0, ISC or BSD. Next.js can load the
  optional `sharp` image library, whose `libvips` binaries are LGPL-3.0; the build-time
  browser data in `caniuse-lite` is CC-BY-4.0, and the dev-only `axe-core` is MPL-2.0.
- **Backing services** in the Compose stack: PostgreSQL (PostgreSQL License), Valkey
  (BSD-3-Clause), RabbitMQ (MPL-2.0), Qdrant (Apache-2.0) and OpenSearch (Apache-2.0).
- **Fonts** in the admin console are committed to the repository and are in the public
  domain: Tuffy (public-domain dedication) and NK57 Monospace (CC0 1.0). They carry no
  license conditions and can be redistributed freely, including in commercial products;
  [`frontend/admin/src/fonts/README.md`](frontend/admin/src/fonts/README.md) records their
  sources and checksums.

- **Container images** built from this repository carry the license texts of the packages
  they bundle: `/licenses/` in the Python images and `/app/licenses/` in the admin console
  image. [`scripts/licenses/python_third_party_notices.py`](scripts/licenses/python_third_party_notices.py)
  and [`frontend/admin/scripts/third-party-notices.mjs`](frontend/admin/scripts/third-party-notices.mjs)
  generate them during the build.

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Contact

Questions about the project, and private reports under the
[Code of Conduct](CODE_OF_CONDUCT.md), go to Muhammad Sabir
([@sabir-aspose](https://github.com/sabir-aspose),
[muhammad.sabir@aspose.com](mailto:muhammad.sabir@aspose.com)).

## License

[MIT](LICENSE) © 2025–2026 Aspose Pty Ltd

Aspose, GroupDocs and their product names are trademarks of their respective owners. The
MIT license covers the code in this repository; it does not grant permission to use these
names or logos.

### Aspose.Words for .NET endpoint

The product-scoped MCP endpoint is `/words/net/mcp/v1/streamable-http`
(GET SSE and POST JSON-RPC). It supplies `product_id="aspose.words"` and
`language="net"` for all retrieval tools. Clients can omit these arguments;
conflicting values are rejected. `resolve_product` returns this fixed scope.
Documentation searches do not fall back to other SDK languages, and structured
API lookups keep the same scope even when no Words/.NET data is indexed.
The shared `/mcp/v1/streamable-http` endpoint keeps its existing behavior.

For a deployment at `mcp.aspose.com`, configure clients with:

```json
{
  "mcpServers": {
    "aspose-words-net": {
      "url": "https://mcp.aspose.com/words/net/mcp/v1/streamable-http"
    }
  }
}
```

Deploy the application and allow `/words/net/mcp` through the ingress **without
rewriting the path**. The Helm default MCP ingress includes this prefix;
installations overriding `mcpGateway.ingress.paths` must add it to their list.
Preserve MCP headers and disable response buffering for SSE at the proxy.
This route scopes retrieval, not authentication or access to the shared endpoint.
Only the single-slash URL above is supported.

The same API also serves Aspose.TeX for .NET at
`/tex/net/mcp/v1/streamable-http` (GET SSE and POST JSON-RPC). It fixes
`product_id="aspose.tex"` and `language="net"`, rejects conflicting scope,
and reuses existing TeX indexes with no additional ingestion. Its server name
is `aspose-tex-net-mcp`. Forward `/tex/net/mcp` through the ingress unchanged;
this prefix is included in the default Helm values. Installations overriding
`mcpGateway.ingress.paths` must include it explicitly.

The Total .NET endpoint is `/total/net/mcp/v1/streamable-http` (GET/POST).
Its allowlist is exactly `aspose.words` and `aspose.tex`, with language fixed
at `net`. Omit `product_id` to query both existing indexes; responses contain
`results_by_product`, each with `product_id` and `result`, or `not_found` for
missing symbols/releases. Limits and pagination apply per product, with no
cross-product score comparison. Explicit product selection returns the normal
single-product response. `resolve_product` without a selection lists the two
allowed products; free-text queries do not widen the scope. `aspose.total` is
not a stored product or an accepted product selection. Ingress must forward
`/total/net/mcp` unchanged (included in Helm defaults). No re-ingestion is needed.
