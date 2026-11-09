# Public repositories and release maintenance

The shared engine is published at [aspose-core-mcp/context-engine](https://github.com/aspose-core-mcp/context-engine).

## Words/.NET companions

- [net-plugin](https://github.com/aspose-words-mcp/net-plugin): documentation/API extraction and retrieval profile.
- [net-server](https://github.com/aspose-words-mcp/net-server): pinned engine/plugin composition, setup and ingestion helpers.
- [net-copilot-client-agent](https://github.com/aspose-words-mcp/net-copilot-client-agent): Copilot agent, compilation checks and showcase.

## TeX/.NET companions

- [net-plugin](https://github.com/aspose-tex-mcp/net-plugin): documentation/API extraction with no retrieval profile; default engine retrieval behavior applies.
- [net-server](https://github.com/aspose-tex-mcp/net-server): pinned engine/plugin deployment with TeX registration and scoped MCP verification.
- [Client setup](https://github.com/aspose-tex-mcp/net-server/blob/main/docs/clients.md): generic MCP client configuration. A dedicated TeX Copilot custom-agent repository is not yet published.

Both product servers already register their plugins in deployment-specific catalogs. Manual registration is only needed for custom deployments. Their setup and CI verify component integration; source ingestion and publication remain explicit deployment steps.

## Total/.NET deployment

[aspose-total-mcp/net-server](https://github.com/aspose-total-mcp/net-server) combines the public Words and TeX plugins in one engine with an `aspose.total.net` serving composition. Its catalog already registers both members. It currently covers Words and TeX only; it does not supply another extraction plugin or corpus.

Ingest each product separately using the deployment's isolated `workspaces/words` and `workspaces/tex` directories. This avoids the plugins' shared relative API-reference path. The Total endpoint queries both member scopes, or a selected product, against shared runtime stores. Follow its [ingestion](https://github.com/aspose-total-mcp/net-server/blob/main/docs/ingestion.md) and [client guides](https://github.com/aspose-total-mcp/net-server/blob/main/docs/clients.md).

## Release conventions

The package and import name remain `adcs`. The default plugin catalog stays empty; product registration belongs to a deployment. Preserve license and third-party attribution. Configure deployment secrets and environments separately from the public repository.

The public history retains the original author attribution, with historical private deployment details sanitized. Future releases should preserve that history. Server deployments pin explicit engine and plugin commits; publishing an engine update does not automatically change existing deployments.

The source registry and `.gitmodules` retain legacy upstream definitions for compatibility tooling. Do not initialize all submodules for the external-plugin workflow. Historical design records may describe the former combined repository; use the root README, deployment guide and [external-plugin guide](engine-only.md) for current setup.
