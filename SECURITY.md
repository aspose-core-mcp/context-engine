# Security Policy

For Aspose's corporate information on customer data and security, see
[Customer Data and Security](https://about.aspose.com/security/customer-data-and-security/).
This document provides security guidance specific to Context Engine.

## Supported versions

No versioned release has been published yet. Security fixes are currently applied
to the `main` branch.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub instead:
[**Security → Report a vulnerability**](https://github.com/aspose-core-mcp/context-engine/security/advisories/new),
or e-mail [security@aspose.com](mailto:security@aspose.com).

Please include:

- a description of the issue and its impact;
- steps to reproduce or a proof of concept;
- the affected component (MCP gateway, public REST API, admin API, admin UI,
  ingestion pipeline, container images or deployment manifests);
- the commit or version you tested.

The maintainers will acknowledge the report, keep you informed while it is
investigated, and coordinate disclosure once a fix is available. Reporters are
credited unless they prefer to remain anonymous.

## Security model in brief

- **Public retrieval API.** MCP tools and `/v1/` REST endpoints are read-only and
  need no authentication. Abuse protection is configurable through
  `ADCS_ABUSE_GUARD_MODE` (`observe-only` or `enforce`).
- **Admin API.** Requires an `x-api-key` header. Keys are product-scoped or
  superuser, with scopes such as `read:analytics`, `read:logs`, `write:settings`,
  `write:ingestion` and `write:destructive`.
- **WebMCP.** The browser adapter is feature-flagged (`ADCS_WEBMCP_ENABLED=false`
  by default); write tools require explicit confirmation and are audited.
- **Secrets.** The repository contains no credentials. `.env.example` files hold
  placeholders only; deployments supply real values from a secret store — see
  [docs/secrets-handling.md](docs/secrets-handling.md).
