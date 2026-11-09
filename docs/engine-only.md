# External plugins and engine integration

> **Recommended ingestion workflow for new deployments**
>
> Use an external product plugin and the `adcs-platform-ingest` commands in this guide. The plugin manifest defines its source repositories and extraction settings, and its retrieval profile supplies product-specific retrieval policies. For Aspose.Words for .NET, follow [net-plugin source preparation](https://github.com/aspose-words-mcp/net-plugin/blob/main/docs/source-preparation.md) and [net-server deployment](https://github.com/aspose-words-mcp/net-server).
>
> The built-in source-registry/submodule workflow is **legacy**, retained for existing deployments. Its `config/source-repositories.yaml`, JSON counterpart, and source entries in `.gitmodules` are separate from plugin manifests; editing those files does not update a plugin's source configuration. The legacy label does not announce removal or a change in support. See the [legacy source-registry tools](../scripts/README.md#sources--registry-legacy-workflow).

The default `config/product-platform-plugins.json` is intentionally empty. Plugins and compositions are deployed separately. This guide is the entry point for the standalone engine; older combined-repository examples may refer to bundled plugins that are no longer present.

## Obtain a plugin

[aspose-words-mcp/net-plugin](https://github.com/aspose-words-mcp/net-plugin)

Use a pinned checkout of a plugin implementing `adcs.extraction.v1`. Install its interpreter dependencies in its own environment and prepare source repositories and any Gist cache according to that plugin's guide.

The engine catalog loader does not clone repositories or install packages. Source paths in a plugin manifest are relative to the ingestion workspace, not to the catalog.

## Register a manifest

A deployment catalog can contain:

```json
{
  "plugins": ["/absolute/path/to/net-plugin/plugin.json"],
  "compositions": []
}
```

Manifest paths may be absolute or relative to the catalog file. Add compositions only after registering all their members. Keep the checked-in default empty; use a deployment-specific catalog for your installation.

## Validate and publish

From an activated engine environment, replace all `/absolute/path/to/` values:

```sh
adcs-platform-ingest aspose.words.net \
  --catalog /absolute/path/to/catalog.json \
  --workspace /absolute/path/to/net-plugin \
  --python /absolute/path/to/net-plugin/.venv/bin/python
```

Without `--stage` or `--publish`, the CLI validates extraction; it can still write operation/review metadata. `--stage` writes review staging. `--publish` explicitly publishes through configured runtime stores. These modes are mutually exclusive. Use `--source-kind docs` or `--source-kind apiref` to select one source; the default is both.

Configure backing stores and embeddings before publication. After validation succeeds, repeat the invocation with `--publish` when you intend to update published data. `--enqueue` submits durable jobs; inspect them with `--job-status OPERATION_ID` using the same workspace. See `adcs-platform-ingest --help` for the implemented options.

## Configure serving

- `ADCS_RETRIEVAL_PLUGIN_CATALOG`: absolute path to the catalog containing retrieval profiles.
- `ADCS_PRODUCT_PLUGIN_CATALOG`: catalog used for composition configuration by the compatibility MCP scopes.

Set both explicitly to the intended deployment catalog when using these features. Restart services after changing configuration. For containers, the catalog, plugin manifest/profile files, source checkout, and interpreter paths must be valid inside the relevant containers; host paths are not automatically available there.

An empty catalog does not disable compatibility routes or erase indexed data. Without an explicit product catalog, legacy Total membership remains unchanged. Plugin registration does not dynamically create new HTTP routes.

## Validation boundaries

`tests/test_engine_only_catalog.py` exercises empty startup and external registration without product implementations. Product integration suites may skip when external plugins are absent. Run those suites with your pinned plugins and validate actual retrieved citations before releasing a product deployment.
