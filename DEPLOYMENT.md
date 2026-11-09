# Deployment

Choose a deployment model, configure the engine, then register and publish external product content. This checkout supplies no hosted endpoint, credentials, prepared corpus, or live indexes.

| Model | Entry point |
| --- | --- |
| Local development | [Quick start](quick-start-guide.md), `docker-compose.integration.yml` |
| Single Linux VM | [VM setup](docs/linux-vm-deployment.md), `docker-compose.vm.yml` |
| Kubernetes | Templates and runbooks in `infra/` |

## Runtime requirements

The supplied stack uses PostgreSQL, Valkey, RabbitMQ, Qdrant, and OpenSearch. Configure the corresponding connection settings, engine API credentials, hashing secret, and an embedding provider/model through the appropriate environment template. Keep the embedding model compatible with your indexes; changing it can require reindexing.

The admin UI is optional and has its own frontend environment configuration. Engine health and empty catalog tests do not establish that product content has been published.

## External plugins

Follow [external-plugin integration](docs/engine-only.md). Container deployments need explicit mounts or image provisioning for the deployment catalog and the external plugin's manifest, optional retrieval profile, interpreter, sources, and Gist cache. The engine images do not bundle product plugins. Ensure API and worker processes see the catalog/profile paths they use.

| Product | Plugin | Server setup |
| --- | --- | --- |
| Words/.NET | [net-plugin](https://github.com/aspose-words-mcp/net-plugin) | [net-server](https://github.com/aspose-words-mcp/net-server) |
| TeX/.NET | [net-plugin](https://github.com/aspose-tex-mcp/net-plugin) | [net-server](https://github.com/aspose-tex-mcp/net-server) |

Each server supplies its registration catalog and launch/ingestion wrappers; no edit to the shared engine catalog is required. Words supplies a retrieval profile; TeX uses default retrieval behavior. Both server repositories provide host-Python helpers, not a complete product-specific Compose or Helm deployment. Container deployments still require the mounts and provisioning described above.

## Expose the API

Configure authentication, TLS, and ingress for your environment. Preserve MCP request headers and route paths; SSE requires streaming without proxy response buffering. The VM template binds the API to loopback by default. Do not expose the backing databases directly as part of the client setup.

Verify `/healthz`, authenticated MCP initialization, and real retrieval results with citations after publication. Use your own deployment URL in clients. Historical operational records and sample URLs elsewhere are not a hosted-service commitment.

## Operations

Retain source revisions, plugin revisions, prepared example cache provenance, and ingestion operation IDs with release records. Use the existing `infra/` runbooks for backup, monitoring, and recovery; validate them against your selected deployment. Do not reuse operation IDs or credentials from another environment.
