# Aspose Context Engine

Shared ingestion, indexing, and retrieval infrastructure for documentation-backed AI assistants. The engine normalizes extracted content, builds searchable indexes, resolves API symbols, and serves citation-backed context through REST and MCP interfaces.

This repository contains the engine. Product-specific extraction plugins are installed separately. The default catalog in `config/product-platform-plugins.json` has empty `plugins` and `compositions` arrays; no product corpus or published indexes are bundled.

[Quick start](quick-start-guide.md) · [External plugins](docs/engine-only.md) · [Deployment](DEPLOYMENT.md) · [MCP interfaces](MCP-SERVER.md)

> **Recommended: plugin-based ingestion**
>
> For new deployments, use an external product plugin to configure source repositories, extraction, and retrieval policies. Start with the [plugin integration guide](docs/engine-only.md). Use the published Words/.NET or TeX/.NET plugin and server listed below; each server supplies its product registration catalog.
>
> The built-in source-registry and source-submodule ingestion workflow is retained as a **legacy workflow** for existing deployments. Its source configuration is separate from plugin manifests. See the [legacy source-registry tools](scripts/README.md#sources--registry-legacy-workflow).

## Project family

The shared engine supports product-specific plugins and MCP deployments. Words components are maintained under **aspose-words-mcp** and TeX components under **aspose-tex-mcp**.

| Repository | Responsibility |
| --- | --- |
| [context-engine](https://github.com/aspose-core-mcp/context-engine) **(this repository)** | Shared ingestion, indexing, retrieval, and MCP infrastructure |
| [Words/.NET plugin](https://github.com/aspose-words-mcp/net-plugin) | Words extraction and product-specific retrieval profile |
| [Words/.NET server](https://github.com/aspose-words-mcp/net-server) | Pinned engine/plugin deployment and registration |
| [Words Copilot agent](https://github.com/aspose-words-mcp/net-client-copilot-agent) | Copilot agent, C# compilation checks, and showcase |
| [TeX/.NET plugin](https://github.com/aspose-tex-mcp/net-plugin) | TeX extraction using default engine retrieval behavior |
| [TeX/.NET server](https://github.com/aspose-tex-mcp/net-server) | Pinned engine/plugin deployment and registration |
| [Words/Java plugin](https://github.com/aspose-words-mcp/java-plugin) | Words/Java extraction and product-specific retrieval profile |
| [Words/Java server](https://github.com/aspose-words-mcp/java-server) | Pinned engine/plugin deployment and registration |
| [TeX/Java plugin](https://github.com/aspose-tex-mcp/java-plugin) | TeX/Java extraction and product-specific retrieval profile |
| [TeX/Java server](https://github.com/aspose-tex-mcp/java-server) | Pinned engine/plugin deployment and registration |
| [Total/.NET server](https://github.com/aspose-total-mcp/net-server) | Shared engine deployment aggregating Words and TeX; no separate Total corpus |

All three servers include client connection guides. A dedicated TeX Copilot custom-agent repository is not yet published.

## How the components fit together

```text
Source repositories → external extraction plugin → engine ingestion and indexes
                                                         ↓
AI client ← MCP / REST interface ← retrieval and API-symbol lookup
```

The engine includes hybrid dense/lexical retrieval, citation metadata, structured API lookup, snapshot publication, background jobs, and an optional admin UI. Actual results depend on configured stores, registered plugins, and published content.

## Developer setup

Use Python 3.12 or newer. From this repository root:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
PYTHONPATH=src python -m pytest -q tests/test_engine_only_catalog.py
```

This focused check exercises engine-only catalog behavior without downloading product sources. For broader development checks, run `make lint`, `make typecheck`, and `make test`. The admin UI requires Node.js 22 or newer. See [CONTRIBUTING.md](CONTRIBUTING.md).

Do not initialize the legacy source submodules recursively for the external-plugin workflow. Prepare only the sources required by your selected plugin.

## Add product content

For a product deployment, follow the [Words server ingestion guide](https://github.com/aspose-words-mcp/net-server/blob/main/docs/ingestion.md) or [TeX server ingestion guide](https://github.com/aspose-tex-mcp/net-server/blob/main/docs/ingestion.md). Their catalogs already register the respective plugin; manual registration below applies to custom engine deployments. For both products in one engine, use the [Total server ingestion guide](https://github.com/aspose-total-mcp/net-server/blob/main/docs/ingestion.md), which keeps their workspaces separate.

1. Obtain a compatible external plugin checkout and prepare its source repositories and examples.
2. Register its manifest in an engine catalog.
3. Validate extraction using `adcs-platform-ingest` with explicit catalog, workspace, and plugin-interpreter paths.
4. Configure runtime stores and embeddings, then publish indexed content explicitly.
5. Configure serving and any optional retrieval profile, then connect an MCP or REST client.

See [the external-plugin guide](docs/engine-only.md) for commands and catalog examples. Plugin registration does not download sources, install dependencies, or publish data.

## Deployment

Local development uses `docker-compose.integration.yml`; the single-VM template is `docker-compose.vm.yml`. Kubernetes templates and operational runbooks are under `infra/`. Configure credentials, embeddings, storage, and external plugin mounts for your environment before deployment. [Deployment guidance](DEPLOYMENT.md) distinguishes these options.

No hosted endpoint is provided or claimed by this checkout. Use the address of your deployment.

## Compatibility boundaries

Legacy Words/.NET, TeX/.NET, and Total/.NET route definitions and the all-product source registry remain in the engine for compatibility. An empty plugin catalog does not disable those routes or remove previously indexed data. Dynamic route registration, automatic remote plugin installation, and hot reload are not supplied by the engine-only split.

Some integration tests require separately installed product plugins and skip when those plugins are absent. A passing engine-only test does not validate a deployed product corpus.

## Repository map

| Path | Responsibility |
| --- | --- |
| `src/adcs/plugins/` | Manifest loading, extraction contract, ingestion CLI, queued jobs |
| `src/adcs/ingestion/`, `src/adcs/indexing/` | Normalization, staging, embeddings, publication |
| `src/adcs/retrieval/` | Retrieval planning, ranking, and context packing |
| `src/adcs/api/`, `src/adcs/mcp/` | REST and MCP gateways |
| `src/adcs/worker/` | Background task runtime |
| `config/` | Catalogs and runtime policies |
| `frontend/admin/` | Optional administration UI |
| `infra/` | Deployment templates and operations guidance |
| `tests/` | Regression and integration tests |

## Documentation and provenance

- [Architecture](docs/architecture.md)
- [External plugins and ingestion](docs/engine-only.md)
- [MCP transports and tools](MCP-SERVER.md)
- [Public-release preparation](docs/public-release.md)
- [Security reporting](SECURITY.md)

The engine derives from the MIT-licensed Aspose Context Engine / ADCS project. Historical design records and changelog entries remain for provenance; they do not establish deployment status or product availability for this checkout. Existing GitHub Actions checks are retained for Python, the admin UI, and container builds.

## License

[MIT](LICENSE) © Aspose Pty Ltd. Preserve existing attribution and bundled third-party notices. Source corpora and downloaded examples retain their upstream terms. Aspose and GroupDocs product names remain trademarks of their respective owners.
