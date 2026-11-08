# Contract Tests (Pact)

Consumer-driven contract tests using [Pact](https://docs.pact.io/) and a [self-hosted Pact Broker](../../infra/pact-broker/README.md).

## Status

This is a **stub** demonstrating the pattern. One consumer test (`query_docs`) and one provider verifier are wired up. Extending to other MCP tools is straightforward:

1. Copy `tests/contracts/consumer/test_query_docs_consumer.py`
2. Adjust path, body, and expected response
3. Run `make test-contracts-consumer` to regenerate the pact file
4. Provider verifier will pick it up automatically

## Layout

```
tests/contracts/
├── consumer/           # Consumer pact tests (generate ./pacts/*.json)
│   └── test_query_docs_consumer.py
└── provider/           # Provider verification against published pacts
    └── verify_adcs_provider.py
infra/pact-broker/      # Self-hosted broker (docker-compose)
pacts/                  # Generated pact files (gitignored except samples)
```

## Install

`pact-python` is **optional** (extras), keeping the standard `[dev]` install slim:

```bash
pip install -e ".[dev,contracts]"
```

If `pact-python` is not installed, the tests `pytest.skip()` themselves.

## Run consumer tests

```bash
make test-contracts-consumer
# Generates ./pacts/ai-ide-consumer-adcs-mcp-gateway.json
```

## Publish to broker

```bash
make pact-broker-up   # starts the local broker; credentials live in infra/pact-broker/.env
pact-broker publish ./pacts \
  --consumer-app-version=$(git rev-parse --short HEAD) \
  --broker-base-url=http://localhost:9292 \
  --broker-username=pactbroker --broker-password=pactbroker  # default from .env.example
```

## Run provider verification

Provider verifier runs against a live ADCS API (test environment recommended):

```bash
# Start ADCS API in another terminal
make run

# In this terminal (verifies ./pacts/ai-ide-consumer-adcs-mcp-gateway.json):
make test-contracts-provider ADCS_API_URL=http://localhost:8080
```

To verify the pacts stored in a broker instead of the local pact file, call the verifier directly:

```bash
PYTHONPATH=./src python3 tests/contracts/provider/verify_adcs_provider.py \
  --broker-url http://localhost:9292 \
  --provider-url http://localhost:8080
```

## CI integration

CI configuration is not included in this repository. A typical setup uses two jobs:

1. **Consumer contracts** (test stage):
   - `pip install -e ".[dev,contracts]"`
   - `make test-contracts-consumer`
   - keep `pacts/` as a build artifact (or publish it to the broker)
2. **Provider verification** (later stage, against a running API):
   - `pip install -e ".[dev,contracts]"`
   - start the backend (for example `make run &`) and wait until `/healthz` responds
   - `make test-contracts-provider`

## When pact-python is not available

Tests skip gracefully:

```python
pact = pytest.importorskip("pact")
```

This keeps the standard `make test` green even without contract extras installed.

## See also

- [`infra/pact-broker/README.md`](../../infra/pact-broker/README.md)
- [Pact docs](https://docs.pact.io/)
- [pact-python docs](https://pact-foundation.github.io/pact-python/)
