# Public repositories and release maintenance

The shared engine is published at [aspose-core-mcp/context-engine](https://github.com/aspose-core-mcp/context-engine).

## Words/.NET companions

- [net-plugin](https://github.com/aspose-words-mcp/net-plugin): documentation/API extraction and retrieval profile.
- [net-server](https://github.com/aspose-words-mcp/net-server): pinned engine/plugin composition, setup and ingestion helpers.
- [net-copilot-client-agent](https://github.com/aspose-words-mcp/net-copilot-client-agent): Copilot agent, compilation checks and showcase.

## Release conventions

The package and import name remain `adcs`. The default plugin catalog stays empty; product registration belongs to a deployment. Preserve license and third-party attribution. Configure deployment secrets and environments separately from the public repository.

The public history retains the original author attribution, with historical private deployment details sanitized. Future releases should preserve that history. Server deployments pin explicit engine and plugin commits; publishing an engine update does not automatically change existing deployments.

The source registry and `.gitmodules` retain legacy upstream definitions for compatibility tooling. Do not initialize all submodules for the external-plugin workflow. Historical design records may describe the former combined repository; use the root README, deployment guide and [external-plugin guide](engine-only.md) for current setup.
