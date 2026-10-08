# Quick start

For a new Linux VM, follow [the deployment guide](docs/linux-vm-deployment.md).
For the existing private-network VM, see [DEPLOYMENT.md](DEPLOYMENT.md).
For local Python setup and plugin development, see [the plugin guide](docs/product-platform-plugins.md).

After successful ingestion, query the running VM:

```sh
curl --fail-with-body http://192.0.2.10:18082/v1/docs:query \
  -H 'Content-Type: application/json' \
  -d '{"query":"How do I use mail merge with a DataTable in Aspose.Words for .NET?","product_id":"aspose.words","language":"net","query_locale":"en","top_k":10,"include_examples":true}'
```

Use this Words/.NET endpoint in an MCP client:

```text
http://192.0.2.10:18082/words/net/mcp/v1/streamable-http
```

The VM is reachable only from the private network. Replace the host/port for another
installation. Validate meaningful results and citations; a healthy API can still
have empty indexes before publication completes.
