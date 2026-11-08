# Quick start

## Verify the engine checkout

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
PYTHONPATH=src python -m pytest -q tests/test_engine_only_catalog.py
```

No product plugin is registered by default. Start with the [external-plugin guide](docs/engine-only.md) when you are ready to ingest content.

## Local API development

From the activated environment:

```sh
cp .env.example .env.local
make infra-up
make run
```

Review and configure `.env.local` and the Compose environment before starting services. Run `make run-worker` in a separate activated terminal when using background ingestion. The API uses port 8080 by default; check `/healthz`. A healthy API can have empty indexes.

For containers on a Linux VM, use [deployment setup](docs/linux-vm-deployment.md). Do not use local development defaults as production credentials.

## Query published content

After plugin installation and publication, send requests to your configured endpoint. Configure client authentication according to [deployment guidance](DEPLOYMENT.md). Product-scoped MCP route details are documented in [MCP-SERVER.md](MCP-SERVER.md).

**TODO: WORDS_NET_MCP_PUBLIC_REPOSITORY_URL** — product deployment guide.
**TODO: COPILOT_CLIENT_PUBLIC_REPOSITORY_URL** — Copilot client setup.
