# Words/.NET API deployment

Copied from the Linux VM's `DEPLOYMENT.md` and expanded for repository handoff.
This is a dated deployment record, not a live status dashboard.

| Setting | Value |
| --- | --- |
| VM | `192.0.2.10` (private network) |
| SSH user | `deploy` |
| Directory | `/home/deploy/context-engine` |
| Compose project | `adcs-vm` |
| API | `http://192.0.2.10:18082` |
| Words/.NET MCP | `http://192.0.2.10:18082/words/net/mcp/v1/streamable-http` |
| Services | API, worker, PostgreSQL, Valkey, RabbitMQ, Qdrant, OpenSearch |

For a fresh deployment, follow [the Linux VM guide](docs/linux-vm-deployment.md).
The deployed code was copied from this worktree before GitLab publication; do not
assume the running image automatically follows GitLab commits.

## Verified on 8 October 2026

- All seven services started healthy; API health and Words MCP initialization passed.
- Embedding connectivity from the VM passed with the configured model, returning 4,096 dimensions.
- Full-corpus validation passed for Words documentation and API reference.
- Documentation publication completed. API-reference publication was still running
  at the last check for this handoff; complete retrieval acceptance remains pending.
- Other deployments on the VM were left running.

The VM has 8 CPUs and approximately 32 GiB RAM. This deployment uses a 12 GiB
worker limit and 2 GiB API limit. Measured validation was primarily sequential
CPU work, with no observed memory-limit or CPU-throttling events.

## Check progress

From a Mac:

```sh
ssh deploy@192.0.2.10
```

Then on the VM:

```sh
cd ~/adcs-vm
sudo sh scripts/deploy/vm.sh ps
tail -n 30 ingestion-pipeline.log
sudo sh scripts/deploy/vm.sh exec -T worker python -m adcs.plugins.cli \
  --job-status f907e9ea-8e6a-469c-b351-32b5f4398af3
sudo sh scripts/deploy/vm.sh exec -T worker python -m adcs.plugins.cli \
  --job-status 70ae8860-ad2d-42a8-b694-90c7a1404c68
```

The first operation is documentation; the second is API reference. These IDs are
specific to the initial deployment. The worker processes publication sequentially.
`tail -n 30` prints once and returns to the prompt. `tail -f` watches continuously;
Ctrl+C stops the viewer only. Queued jobs continue after SSH disconnects.

The initial VM has a one-off `finish-ingestion.sh` supervisor and
`ingestion-pipeline.log`. It waits for validation, submits publication, monitors
job records, restarts the API after both succeed, and saves `words-query-check.json`.
That supervisor is specific to the original validation process and is not a
reusable ingestion command. Do not rerun it. Fresh deployments should use the
CLI workflow in the Linux VM guide. Do not use `/proc` file-descriptor counters
as a stable monitoring interface: process IDs and open files change between jobs.

## Configuration and persistence

Runtime secrets are in the VM's `.env.vm` with mode 600. The embedding URL, model
and credential came from the operator's local configuration; API/database/broker
secrets were generated for this deployment. No credentials are stored here.
Only the API is published, bound to the private IP on port 18082. HTTP access is
for the private network; use HTTPS termination for a public deployment.

Application state, sources and store data use named Docker volumes. Never use
`down -v` unless intentionally deleting this deployment's data. Wait for active
publication to finish before updating the image or restarting the worker.

Evidence on the VM: `build.log`, `startup.log`, `prepare-words.log`,
`validate-words.log`, `publication-jobs.json`, `ingestion-status.json`, and
`ingestion-pipeline.log`. These files and source corpora stay outside Git.
