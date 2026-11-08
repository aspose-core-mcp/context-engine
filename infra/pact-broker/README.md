# Pact Broker (local)

A local, self-hosted Pact Broker for running the ADCS contract tests end to end. It runs with Docker Compose and needs no external account.

## What is the broker?

[Pact Broker](https://docs.pact.io/pact_broker) is the central registry for pacts (consumer-driven contracts). Consumers (AI-IDEs, integrators) publish pacts describing the API behavior they expect. Providers (ADCS API) verify they meet those pacts. The broker tracks compatibility matrices and "can-i-deploy" checks.

## Local development

```bash
# From the repository root: copies infra/pact-broker/.env.example to .env on first run
make pact-broker-up
open http://localhost:9292
```

Or without Make:

```bash
cd infra/pact-broker
cp -n .env.example .env   # DEV-ONLY credentials; never commit .env
docker compose up -d
```

UI credentials: user `pactbroker` with the password from `PACT_BROKER_BASIC_AUTH_PASSWORD` in `.env` (default `pactbroker`); a read-only user `pactread` is also configured. Stop the broker with `make pact-broker-down`.

The broker stores pacts in a Postgres volume (`adcs-pact-broker-postgres-data`).

## Workflow

### Consumer side (e.g., AI-IDE integrator)

1. Define the pact in a test file (see `tests/contracts/consumer/test_query_docs_consumer.py`)
2. `make test-contracts-consumer` runs the consumer test and generates `pacts/{consumer}-{provider}.json`;
   the Pact mock service listens on port 1234 (set `PACT_MOCK_PORT` if that port is taken)
3. Optionally publish to the broker via `pact-broker publish ./pacts --consumer-app-version=$(git rev-parse --short HEAD)`

### Provider side (ADCS API)

1. `make test-contracts-provider` verifies the local pact file against a running API with the Aspose.OCR documentation indexed (`ADCS_API_URL`, default `http://localhost:8080`)
2. With `--broker-url`, the verifier (`tests/contracts/provider/verify_adcs_provider.py`) connects to the broker, fetches all pacts targeting `adcs-mcp-gateway`, and replays each interaction against the live API
3. Results are published back to the broker via the verifier's `--publish-results` flag
4. `pact-broker can-i-deploy` checks compatibility before a release

## Related

- [`tests/contracts/README.md`](../../tests/contracts/README.md) — how to write consumer/provider tests
- [Pact docs](https://docs.pact.io/)
