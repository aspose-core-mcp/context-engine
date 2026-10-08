# Independent product-platform extraction plugins

This evaluation implements separate Words/.NET and TeX/.NET extraction packages.
Each owns source discovery, docs and API theme handling, parsing, normalization,
semantic chunking and structured API signature/facet extraction. Workers import
neither ADCS nor a sibling product package. The host validates their JSON output
and retains scheduling, quarantine, URL remapping, staging, indexing and serving.

## Start here

From this worktree, use Python 3.12+ with the engine dependencies installed.
From the repository root, create an engine environment first:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
export PYTHONPATH="$PWD/src"
ENGINE_PYTHON="$PWD/.venv/bin/python"

# Create separate dependency environments for the two extractors (no network).
"$ENGINE_PYTHON" -m venv --without-pip plugins/words-net/.venv
"$ENGINE_PYTHON" -m venv --without-pip plugins/tex-net/.venv

# Run either package's own contract tests without the engine installed there.
plugins/words-net/.venv/bin/python -m unittest discover -s plugins/words-net/tests
plugins/tex-net/.venv/bin/python -m unittest discover -s plugins/tex-net/tests

# Validate one source only. TeX checkout/store/worker is not required.
"$ENGINE_PYTHON" -m adcs.plugins.cli aspose.words.net --source-kind docs \
  --python plugins/words-net/.venv/bin/python

# Extract both Words sources into REVIEW staging (no live publication).
"$ENGINE_PYTHON" -m adcs.plugins.cli aspose.words.net --source-kind both --stage \
  --python plugins/words-net/.venv/bin/python

# Independently extract TeX.
"$ENGINE_PYTHON" -m adcs.plugins.cli aspose.tex.net --stage \
  --python plugins/tex-net/.venv/bin/python
```

The source repositories must exist before ingestion. This worktree does not
contain a copy of the original ingested corpus or its running databases.
`--workspace /path/to/source-workspace` chooses both source and engine state
locations; use a disposable workspace for evaluation. It does not clone sources.
Default validation may write operation/review metadata, but never publishes.

The explicit `--publish` option uses the engine's configured runtime adapters,
embedding provider and stores. API publication requires
`APIREF_STRUCTURED_STORE_ENABLED=true` and its database configuration.
Inspect settings before using publication against any shared deployment.
`--stage` and `--publish` are mutually exclusive. The CLI returns nonzero for a
failed operation, missing result, failed page, empty extraction or blocked/partial
publication. Read the full operation result for per-repository outcomes; docs and
API publication is not one distributed atomic transaction.

## Package and configuration boundaries

- `plugins/words-net`: independently installable package, manifest, workers and fixtures.
- `plugins/tex-net`: equivalent package with no shared extractor imports.
- `config/product-platform-plugins.json`: explicit registration; adding a package
  on disk does not automatically enable it.
- `compositions/total-net.json`: explicit member IDs; owns no sources or extractor.
- `src/adcs/plugins`: validated catalog, subprocess boundary and engine CLI.
- `contracts/plugin-extraction/v1`: wire response and manifest JSON schemas.

Each plugin has its own `pyproject.toml`, version, docs/API entry points, tests and
MIT attribution. The current workers use only the standard library. Future plugin
dependencies belong in that package's environment, not the host or sibling package.
For an installed package, configure its worker command as an absolute interpreter
followed by `-I -m adcs_words_net.worker` (or `adcs_tex_net.worker`). Source-checkout
launchers also work; `{plugin_dir}` and `{python}` are expanded without a shell.
The `--python` option selects a dedicated environment. Without it, a separate
process uses the host interpreter; that provides process separation, not a separate
dependency installation. The environments created above supply both.

Manifests declare one product/platform identity and a map of docs/apiref sources.
Their repo IDs include the platform, e.g. `aspose.words.net.docs`, so operation,
staging and incremental state do not reuse the legacy family-wide repository IDs.
Current evaluation source prefixes are `net` for docs and `english/net` for API.
These match the examined local sparse checkouts; other themes/layouts require
updating that plugin's source policy. Missing/empty configured prefixes fail
explicitly, with no fallback to scanning all languages. Discovery and the host both
reject paths escaping the selected source directory.

## Wire contract: adcs.extraction.v1

One worker process accepts one JSON request on stdin and emits one JSON response
on stdout. Diagnostics belong on stderr. Discovery returns relative Markdown paths;
extraction receives the source text, path, layout and immutable source revision.

Every request supplies `contract`, `plugin_id`, `product_id`, `language`,
`source_kind` and `operation` (`discover` or `extract`). Discovery additionally
supplies `repo_root` and `source_prefix`. Extraction supplies `repo_id`,
`product_family`, `source_path`, `relative_repo_path`, `layout_detection`,
`raw_markdown`, `source_revision`, `canonical_base_url` and `source_prefix`.
The host supplies the configured prefix so a plugin can derive canonical page
paths independently of the local checkout directory. The Words worker also
accepts older requests without this field using its original per-source prefixes.

Response envelope:

```json
{
  "contract": "adcs.extraction.v1",
  "plugin_id": "aspose.words.net",
  "plugin_version": "0.1.0",
  "result": {
    "page": {},
    "normalized_document": {},
    "chunk_records": [],
    "symbols": []
  }
}
```

The placeholders above illustrate shape only. See the JSON schema for fields:
- `normalized_document` uses `adcs.normalized_document.v1` with citations and warnings.
- `page` is the existing page-data shape required by the engine's metadata gates;
  this compatibility representation does not require the plugin to use Hugo parsing.
- `chunk_records` are already semantically extracted by the plugin. The engine
  validates/stages them without re-running its own semantic chunker.
- `symbols` contain independently extracted structured API records. The plugin
  leaves `snapshot_id` empty; the engine assigns the actual publication snapshot.
  The host writes these records without its legacy signature extraction or FQN repair.

An error response contains `error: {type, message}` instead of `result` and exits
nonzero. The host rejects incompatible contracts/versions, malformed output,
out-of-scope products/platforms/paths, changed revisions and inconsistent records.
Workers have a per-call timeout and output-size check. Service secrets and
PYTHONPATH are not forwarded. This is trusted-plugin process isolation, not an OS
security sandbox for hostile code. The initial protocol starts a process per file;
measure corpus throughput before introducing a persistent-worker protocol.

Only symbols from pages accepted by engine validation are retained. They are
spooled to disk and exported under
`artifacts/plugin-extraction/<plugin-id>/<operation-id>/<repo-id>.jsonl` during
stage/publish runs, alongside the effective plugin manifest and version. Structured-store publication activates a scope after its rows
are written. A structured-store error fails a plugin operation instead of being
silently swallowed. A failure after another source publishes requires reviewing
that source's existing receipt; it does not roll the other source back automatically.

## Total and existing MCP endpoints

Total reuses member data and dispatch; requesting Total ingestion is rejected.
The existing Words, TeX and Total endpoint URLs are preserved. To use the explicit
composition file for Total's serving membership, start the API with:

```sh
export ADCS_PRODUCT_PLUGIN_CATALOG="$PWD/config/product-platform-plugins.json"
```

Without this setting, existing deployments retain the pilot's original two-member
serving configuration. The ingestion CLI always uses the explicitly selected
catalog. A new plugin can be registered/extracted without an engine edit; this
iteration does not dynamically add a standalone HTTP route for every new plugin.
Existing Total error/partial-result behavior remains the pilot's behavior.

## Provenance and limitations

Independent extractor implementations were seeded from MIT-licensed pilot d00ac79:
parser, converter, vocabulary, semantic chunker and signature helpers. They are
separate owned copies; future changes are reviewed per product rather than silently
shared. Each plugin additionally handles a leading BOM and paired highlight examples
in its fixtures. Corpus-wide Hugo shortcode, overload, citation and retrieval
remediation remains subject to the separately tracked issues; fixtures do not
certify the full Words or TeX corpus.

The source-kind snapshot prerequisite was copied from upstream MR !1, commit
0534897a4bde4e4e01fd0ddf7140c2d9ba3866f4: `snapshot_registry.py`,
`publish_orchestrator.py` and the coexistence regression. This local integration
does not merge that MR or certify PostgreSQL/concurrency deployment acceptance.

Plugin runs deliberately force fresh extraction and bypass staging/checkpoint
reuse until cache keys include extractor version and policy. Stable content source
revisions remain unchanged. There is no hot reload, remote plugin installation,
repository-wide cross-worker lock, container orchestrator or new admin UI in this
iteration. Use the dedicated CLI/backend for plugins; existing admin ingestion
continues its original path. Separate process/interpreter execution is implemented;
container deployment and real-store integration remain deployment evaluation work.

## Verification

Run focused plugin, publication and endpoint regressions:

```sh
"$ENGINE_PYTHON" -m pytest -q tests/test_product_platform_plugins.py \
  tests/test_snapshot_source_kind_coexistence.py \
  tests/test_words_net_mcp.py tests/test_tex_net_mcp.py tests/test_total_net_mcp.py
```

Tests cover separate sources, standalone worker environments, independent theme
changes, scope/provenance rejection, failed/time-limited workers, third-plugin
registration, and docs/API publication preserving an existing other-product
snapshot. Live PostgreSQL/Qdrant/OpenSearch services are not required for these tests.

## Queued plugin ingestion through the CLI

Add `--enqueue` to submit one job per selected source to the existing RabbitMQ /
Celery infrastructure. `--source-kind both` creates two independent jobs.
Submission persists the operation and plugin execution parameters, sends only the
operation ID and absolute workspace path, and prints a small JSON job summary.
Extraction and publication happen in the worker. The synchronous CLI remains available.

This first implementation supports workers on the same Mac/Linux host with the
same absolute workspace, catalog, source and Python-environment paths. All source
checkouts must be clean Git repositories. The job records the source commit and
a fingerprint of the plugin manifest, local Python source and optional gist cache;
the worker rejects changed inputs. Keep checkouts, plugin code and environments
unchanged until their jobs finish. Installed dependency versions and arbitrary
external plugin assets are not fingerprinted.

Use one ingestion worker process initially. Publication jobs also take a
workspace-wide filesystem lock; jobs for the same plugin serialize. These locks
coordinate this new plugin task only: do not run synchronous ingestion, admin
ingestion, source sync, or another workspace publishing to the same stores at the
same time. This is not distributed scheduling across independent workspaces.

RabbitMQ, Redis and the configured publication stores must already be available.
Use the same environment settings as the current direct publication command.
Ensure the broker's consumer acknowledgement timeout allows the longest complete
source ingestion: acknowledgement happens after execution, not at task receipt.
The API does not need to run. Restart an existing worker to load the new task.

In the worker terminal:

```sh
cd /path/to/aspose-product-mcp-plugins
export ENGINE_PYTHON="$PWD/.venv/bin/python"
export PYTHONPATH="$PWD/src"
"$ENGINE_PYTHON" -m celery -A adcs.worker.celery_app:celery_app worker \
  -Q adcs.ingestion --concurrency=1 --prefetch-multiplier=1 --loglevel=INFO
```

In a separate submission terminal:

```sh
cd /path/to/aspose-product-mcp-plugins
export ENGINE_PYTHON="$PWD/.venv/bin/python"
export PYTHONPATH="$PWD/src"
"$ENGINE_PYTHON" -m adcs.plugins.cli aspose.words.net \
  --python "$PWD/plugins/words-net/.venv/bin/python" \
  --source-kind both --publish --enqueue
```

Replace `--publish` with `--stage` for staging only. Omit both for validation
without staging or publication. Repeat submission with another registered plugin
ID and its own Python environment to build the backlog; no engine registration
code or new Celery task is needed for each plugin.

Copy an `operation_id` from the submission JSON to inspect progress:

```sh
"$ENGINE_PYTHON" -m adcs.plugins.cli --job-status OPERATION_ID
```

Job state lives in `artifacts/plugin-jobs/<operation-id>.json`; detailed operation
results/logs are in `artifacts/runtime-state/ingestion/<operation-id>.json`.
Symbol exports retain the existing
`artifacts/plugin-extraction/<plugin-id>/<operation-id>/` location.
Treat this shared state as trusted operational data and retain it while jobs exist.
It is the plugin queue's status record; existing generic admin ingestion retry
and resume actions do not reconstruct plugins and must not be used for these jobs.

If broker submission fails, the CLI exits nonzero and retains the operation ID.
Redispatch the same unstarted job without creating another operation:

```sh
"$ENGINE_PYTHON" -m adcs.plugins.cli --resubmit OPERATION_ID
```

Only `prepared`, `queued` and `dispatch_failed` jobs can be resubmitted.
Duplicate completed deliveries return the saved result. Lock contention retries
after 15 seconds. Extraction/publication failures are terminal `failed`, not
automatically retried. Interrupted execution becomes `needs_attention`; inspect
the operation and publication receipts before submitting a fresh job.
A `running` status can remain until redelivery after worker loss; it is not a heartbeat.
If a newer publication for the same source has already started, an older job
becomes `stale`, even if the newer attempt later fails. This conservatively prevents
out-of-order publication. Documentation and API jobs are independent, not one
atomic transaction.

For 100+ plugins this supplies a durable backlog and controlled sequential
processing. Multi-host leases, immutable checkout management, automatic failure
recovery, bulk scheduling and an administrative queue UI remain separate work.
