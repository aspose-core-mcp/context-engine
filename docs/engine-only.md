# Engine-only checkout

This branch separates the engine from the bundled Words/.NET and TeX/.NET
extractors. `config/product-platform-plugins.json` starts with no registered
plugins and no compositions. Plugin directories and the Total composition file
are absent. Existing uncommitted engine fixes from the source checkout were
carried over; plugin implementation changes and local deployment/evaluation
artifacts remain in the original checkout.

## Setup

Use Python 3.12 or newer:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export PYTHONPATH="$PWD/src"
.venv/bin/python -m pytest -q tests/test_engine_only_catalog.py
```

The API and worker Dockerfiles no longer copy bundled plugins. The VM Compose
file no longer prepares Words sources or mounts a Words-specific source volume.
Runtime database, authentication and embedding configuration is still required
as documented by the engine's deployment configuration.

## Adding external plugins later

Deploy a pinned plugin checkout separately, then add its manifest path to the
catalog's `plugins` array. Paths are relative to the catalog file, or absolute.
The catalog loader does not clone repositories or install packages. Supply the
plugin interpreter with the ingestion CLI's `--python` option when needed.
Source paths in each manifest remain relative to the ingestion workspace.
Add compositions only after all their members are registered.

`ADCS_PRODUCT_PLUGIN_CATALOG` selects composition configuration for the existing
MCP scopes. `ADCS_RETRIEVAL_PLUGIN_CATALOG` selects retrieval profiles. When used,
point both at the intended deployment catalog. An explicitly empty catalog is
supported. Restart services after configuration changes.

## Scope and remaining work

This separation does not implement dynamic HTTP routes, an enabled flag, remote
plugin installation, or hot reload. Legacy Words/TeX/Total endpoint definitions
and the legacy source registry remain engine compatibility features; an empty
plugin catalog does not disable those endpoints or erase indexed data. Without
`ADCS_PRODUCT_PLUGIN_CATALOG`, legacy Total membership remains unchanged.
Those behaviors belong to the subsequent configuration-only engine work.

The existing plugin integration tests in test_product_platform_plugins.py,
test_plugin_queue.py and test_retrieval_profiles.py require external plugin
checkouts at their former paths and the corresponding catalog registration.
They explicitly skip when Words is absent; namespace boundary tests importing
these helpers skip as well. They are retained for later cross-repository testing.
New engine-only tests exercise empty startup and external manifest registration
without any product extractor. Older plugin workflow documents are historical
instructions for the combined checkout, not the initial engine-only deployment.

## Git handoff

This is branch `feature/engine-only` in a linked worktree. Git history and remote
configuration are shared with the original checkout. Historical commits still
contain the old plugin files; only the new branch's working tree removes them.
Do not recursively initialize the legacy documentation submodules for this split.
Review and commit the changes, including the required trailer:

```text
Co-authored-by: Codex <codex@openai.com>
```

Select the intended GitLab project before pushing; existing remotes are inherited
and have not been changed. No remote repository or merge request is created by
this local separation.

## Separation verification

The focused engine-only, retrieval, symbol-resolution and legacy MCP endpoint
suite completed with 212 tests passed and four plugin-dependent modules skipped.
Lint passed for the separation's runtime/test changes; Git whitespace checks and
VM Compose YAML parsing passed. Docker images and live database-backed deployment
were not built or exercised during this separation.
