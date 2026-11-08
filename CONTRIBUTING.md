# Contributing

Thank you for your interest in improving ADCS, the Aspose Developer Context Service.
This guide covers the development setup, the checks every change must pass, and how
to submit a pull request.

Questions about the project go to Muhammad Sabir
([@sabir-aspose](https://github.com/sabir-aspose),
[muhammad.sabir@aspose.com](mailto:muhammad.sabir@aspose.com)); report bugs and propose
features through GitHub issues.

See [external-plugin setup](docs/engine-only.md) for the standalone engine.

## Prerequisites

- Python 3.12+
- Node.js 22+ (admin UI)
- Docker with Docker Compose (local infrastructure)
- GNU Make

## Development setup

```bash
git clone https://github.com/aspose-core-mcp/context-engine.git
cd context-engine

python3.12 -m venv .venv
source .venv/bin/activate
make install-dev              # editable install with the dev extras

cp .env.example .env.local    # settings are read from .env.local, then .env
make infra-up                 # Postgres, Valkey, RabbitMQ, Qdrant, OpenSearch
make run                      # API + MCP gateway on http://localhost:8080
make run-worker               # Celery worker (separate terminal)
```

Admin UI:

```bash
cd frontend/admin
cp .env.example .env.local    # points the UI at http://localhost:8080
npm ci
npm run dev                   # http://localhost:3000
```

## Checks

Run these before opening a pull request:

```bash
make lint        # ruff over src/ and tests/
make typecheck   # mypy over src/
make test        # pytest; corpus-dependent `live` suites are excluded
```

CI runs the same commands, validates the source registry (`make source-validate`),
type-checks and builds the admin UI, and builds the container images. `make test-live`
runs the suites marked `live`; they need a running stack (Qdrant, OpenSearch, MCP
endpoint) with a loaded corpus.

Some tests execute repository scripts that locate the project root through the `.git`
directory, so run the suite from a git checkout rather than from a source archive.

## Pull requests

- Keep each pull request to a single concern.
- Explain what changed and why, and include a test plan.
- Add or update tests for any behavior change.
- Write commit messages in English, in the imperative mood, with a conventional prefix
  and an optional scope — for example `fix(mcp): handle missing version in strict mode`.

## Project invariants

1. Never return retrieval context without citations (`canonical_url` + anchor).
2. Never mix API versions when `strict_version` is requested.
3. MCP tools and REST endpoints stay in functional parity.
4. New fields in public contracts are optional; never remove or rename public fields
   without a versioned migration.

## Coding standards

- **Python:** ruff (`E`, `F`, `I`, `UP`, `RUF100`) with a line length of 100; mypy with
  `disallow_untyped_defs`. Production code lives in `src/adcs/`, tests in `tests/`.
- **Admin UI:** TypeScript in strict mode (`npm run typecheck`); Playwright for end-to-end
  tests (`npm run test:e2e`).

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
