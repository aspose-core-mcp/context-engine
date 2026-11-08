# Public release preparation

The public repository is `https://github.com/aspose-core-mcp/context-engine`. Replace companion placeholders when their repositories are available:

- `WORDS_NET_PLUGIN_PUBLIC_REPOSITORY_URL`
- `WORDS_NET_MCP_PUBLIC_REPOSITORY_URL`
- `COPILOT_CLIENT_PUBLIC_REPOSITORY_URL`

The package and import name remain `adcs` for compatibility. Existing license and third-party attribution remain intact. GitHub Actions workflows are inherited; configure any deployment secrets and environments explicitly before enabling deployment workflows in the public repository.

The source registry and `.gitmodules` retain legacy upstream source definitions used by compatibility tooling. Do not initialize all submodules for the external-plugin workflow. Historical design records may refer to the original combined repository; use the root README, deployment guide, and external-plugin guide for current setup.

This public repository starts with a reviewed source snapshot and a fresh Git history. Companion repositories remain separate releases.
