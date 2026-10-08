# Linux VM deployment: API and Words/.NET ingestion

This profile deploys the current checkout, including the independent product plugins
and retrieval profiles. It runs the API, one Celery ingestion worker, PostgreSQL,
Valkey, RabbitMQ, Qdrant and OpenSearch. No admin frontend or host Python is needed.
This is a single-VM deployment, without high availability.

## 1. Prepare the VM

Install Docker Engine and the Docker Compose plugin using the
[Docker Linux installation instructions](https://docs.docker.com/engine/install/).
As an initial, unbenchmarked allocation for full Words ingestion, use 8 vCPUs,
48 GB RAM and 100 GB of SSD storage; monitor actual usage and adjust. The default
worker cap is 24 GB, API cap is 4 GB, and stores have separate caps. A smaller VM
requires lower caps and may not fit a full publication. Remote embeddings are
required; the VM does not need a GPU when using a separate embedding service.

Set OpenSearch's Linux prerequisite, including persistence across reboot:

```sh
sudo sysctl -w vm.max_map_count=262144
printf 'vm.max_map_count=262144\n' | sudo tee /etc/sysctl.d/99-adcs.conf
```

See the [OpenSearch Docker prerequisites](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/).

Clone the private repository and check out the branch or commit you intend to deploy:

```sh
git clone TODO_COMPONENT_REPOSITORY_URL
cd aspose-product-mcp-plugins
```

The initial implementation is published on `evaluation/product-platform-plugin-architecture`
for merge-request review. Until it is merged, check out that branch before building.
Credentials, source corpora and indexes are not included. Sources are fetched explicitly
after deployment. Run subsequent commands from the repository root.
The existing team VM and its operating commands are recorded in [DEPLOYMENT.md](../DEPLOYMENT.md).

## 2. Configure

```sh
cp .env.vm.example .env.vm
chmod 600 .env.vm
# Run four times and paste separate values into the four secret fields:
openssl rand -hex 32
```

Edit `.env.vm` and fill in:

- `ADCS_API_KEY`: admin API credential.
- `ADCS_HASH_SECRET`: stable private hashing secret.
- `POSTGRES_PASSWORD` and `RABBITMQ_PASSWORD`: distinct URL-safe hex passwords.
- `ADCS_EMBEDDING_API_URL`: reachable OpenAI-compatible base URL ending in `/v1`.
- `ADCS_EMBEDDING_MODEL`: the model served by that endpoint.
- `ADCS_EMBEDDING_API_KEY`: its credential, if required.

Use the same embedding endpoint/model for ingestion and serving. Changing models
requires reindexing. An endpoint at `localhost` points to the container itself;
use a DNS name or IP reachable from Docker. Preparation needs outbound HTTPS to
GitHub and public Gists; ingestion/queries need access to the embedding endpoint.
Compose fails early when required configuration is empty. Do not paste the output
of `compose config` into tickets: it contains resolved secrets.

## 3. Build and start

```sh
sh scripts/deploy/vm.sh config --quiet
sh scripts/deploy/vm.sh build worker
sh scripts/deploy/vm.sh up -d --wait --wait-timeout 300
sh scripts/deploy/vm.sh ps
curl --fail http://127.0.0.1:8080/healthz
```

The API and worker use the same image. App processes run as an unprivileged user;
Docker initializes named volumes from image directories with matching ownership.
The API starts before content is ingested; an empty query result at this point
is expected. For startup failures:

```sh
sh scripts/deploy/vm.sh logs --tail=100 api worker
```

The API binds only `127.0.0.1:8080`. Database ports are not published and their
network is internal. OpenSearch's security plugin is disabled inside this isolated
single-host network; do not attach untrusted containers or publish store ports.
This follows Docker's [loopback port binding](https://docs.docker.com/engine/network/port-publishing/).

For direct private-network access, set `ADCS_API_BIND_ADDRESS` to the VM's private
IP address in `.env.vm` and recreate the API. `ADCS_API_PORT` selects the host port.

For immediate access from your laptop:

```sh
ssh -L 8080:127.0.0.1:8080 USER@VM_HOST
```

Then use `http://localhost:8080/words/net/mcp/v1/streamable-http` in your MCP client.
For a public service, configure the VM's HTTPS reverse proxy to forward
`/words/net/mcp/` to `http://127.0.0.1:8080` without rewriting, preserve MCP request
and response headers, disable SSE buffering, and allow long-lived streams. Keep
admin paths private. Public MCP/query routes are not protected by the admin API key.

## 4. Prepare Words/.NET sources after deployment

```sh
sh scripts/deploy/vm.sh run --rm --no-deps prepare-words
```

This fetches only the two Words repositories configured in `plugins/words-net/plugin.json`,
with sparse checkouts for documentation `net/` and API reference `english/net/`.
It prepares all referenced Gist code examples at the exact cache path used by the
extractor. Sources and examples are stored in the `words_sources` volume and are
read-only to the API and ingestion worker. Existing checkouts are reused without
pulling new revisions. The command checks the origin, clean Git state and source
prefix, and records commits in `sources/preparation.json`. A failed preparation
must be resolved before ingestion; do not prepare or refresh sources while a job runs.

## 5. Validate, then enqueue publication

Validate both sources without publishing:

```sh
sh scripts/deploy/vm.sh exec -T worker python -m adcs.plugins.cli \
  aspose.words.net --source-kind both --timeout 300
```

This may take time on the full API reference. Verify exit status zero and that
both source results contain parsed pages with no failed items. Then enqueue:

```sh
sh scripts/deploy/vm.sh exec -T worker python -m adcs.plugins.cli \
  aspose.words.net --source-kind both --publish --enqueue --timeout 300
```

Validation is synchronous and can take tens of minutes. Run it inside a persistent
terminal session if you intend to disconnect. Queued publication performs fresh
extraction, so validation completion does not mean embedding has finished.

The output contains two job operation IDs, one for each source. These run on the
Celery worker even after your SSH session disconnects; enqueue success is not
publication success. Store both IDs and inspect each:

```sh
sh scripts/deploy/vm.sh exec -T worker python -m adcs.plugins.cli \
  --job-status OPERATION_ID
sh scripts/deploy/vm.sh logs -f --tail=100 worker
```

Wait for **both** jobs to complete successfully; investigate `failed`, `stale` or
`needs_attention` states and the log paths in job records before retrying. The
sources publish separately, not as one transaction. With the structured store enabled, API reference publication writes PostgreSQL
symbols; documentation chunks populate Qdrant and OpenSearch. No TeX content is ingested.
Avoid `scripts/run_full_ingestion.py` for this plugin workflow.

After successful publication, clear the API's in-process cache:

```sh
sh scripts/deploy/vm.sh restart api
curl --fail http://127.0.0.1:8080/healthz
curl --fail-with-body http://127.0.0.1:8080/v1/docs:query \
  -H 'Content-Type: application/json' \
  -d '{"query":"How do I convert a Word document to PDF?","product_id":"aspose.words","language":"net","query_locale":"en","top_k":5,"include_examples":true}'
curl --fail-with-body http://127.0.0.1:8080/v1/symbols:get \
  -H 'Content-Type: application/json' \
  -d '{"product_id":"aspose.words","language":"net","symbol_fqn":"Aspose.Words.Document"}'
```

Confirm meaningful results and Words/.NET citations; HTTP 200 alone does not
prove the corpus was published. Ingestion time, disk usage and embedding cost
depend on corpus size and the embedding provider.

## Persistence and updates

Always use `sh scripts/deploy/vm.sh` so the project name stays `adcs-vm`.
Named volumes preserve source commits, Gist cache, job records, staging data,
database metadata, broker messages and retrieval indexes across container recreation.
Never use `down -v` unless intentionally deleting the deployment's data.

For code updates, wait for ingestion to finish, copy the new code, then run:

```sh
sh scripts/deploy/vm.sh build worker
sh scripts/deploy/vm.sh up -d --wait --wait-timeout 300
```

Image configuration is versioned with the code; runtime edits to files under
`/app/config` are not retained on recreation. Rebuilding preserves sources and
indexes. Serving-only profile changes need an API restart; extraction changes
need source republication. Back up PostgreSQL, Qdrant, OpenSearch and the named
application/source volumes together during a maintenance window with ingestion
stopped. Preserve the private `.env.vm` separately. Do not change DB/broker
passwords in `.env.vm` without also rotating credentials in the existing stores.
