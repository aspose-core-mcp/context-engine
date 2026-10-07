# Independent product-platform extraction plugins

This evaluation implements separate Words/.NET and TeX/.NET extraction packages.
Each owns source discovery, docs and API theme handling, parsing, normalization,
semantic chunking and structured API signature/facet extraction. Workers import
neither ADCS nor a sibling product package. The host validates their JSON output
and retains scheduling, quarantine, URL remapping, staging, indexing and serving.

## Start here

From this worktree, use Python 3.12+ with the engine dependencies installed.
For this Mac, the existing environment can run the engine without changing it:

```sh
export PYTHONPATH="$PWD/src"
ENGINE_PYTHON=/path/to/context-engine/.venv/bin/python

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
`raw_markdown`, `source_revision` and `canonical_base_url`.

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
