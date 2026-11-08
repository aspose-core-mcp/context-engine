# Single-VM deployment

This guide uses the engine-only `docker-compose.vm.yml`. Product extraction plugins and their sources are not bundled. Review [deployment requirements](../DEPLOYMENT.md) first.

## Prepare the engine

Obtain this repository, then run from its root on a Linux host with Docker and Compose available:

```sh
cp .env.vm.example .env.vm
```

Fill every required credential and embedding setting in `.env.vm`. Generate independent values for `ADCS_API_KEY`, `ADCS_HASH_SECRET`, `POSTGRES_PASSWORD`, and `RABBITMQ_PASSWORD`; the example recommends URL-safe hex values. Set a reachable embedding API base URL and model. `localhost` inside a container refers to that container.

Review memory limits and `ADCS_API_BIND_ADDRESS`; the default API binding is loopback. Configure TLS and authentication at the deployment boundary before exposing it to clients.

## Start the engine services

```sh
sh scripts/deploy/vm.sh config --quiet
sh scripts/deploy/vm.sh up -d --build
sh scripts/deploy/vm.sh ps
sh scripts/deploy/vm.sh logs --tail 100 api worker
```

The wrapper fixes the Compose project name to `adcs-vm` and reads `.env.vm`. Use a consistent project identity to retain volume associations. The stack starts with an empty plugin catalog and no product corpus.

## Add product content

Follow [external-plugin integration](engine-only.md). Provision a pinned plugin checkout and its Python environment, sources, and cache. Add container mounts or build-time provisioning for the catalog and plugin assets required by the API and worker. Paths in the catalog and worker command must resolve inside the containers.

The supplied engine template does not provide those product-specific mounts. Do not invoke a historical bundled-plugin preparation command.

**TODO: WORDS_NET_MCP_PUBLIC_REPOSITORY_URL** — finalized Words deployment composition.
**TODO: WORDS_NET_PLUGIN_PUBLIC_REPOSITORY_URL** — source and cache preparation.

Validate extraction, publish explicitly, then verify retrieval against the actual indexed content. Health checks alone do not prove ingestion succeeded.
