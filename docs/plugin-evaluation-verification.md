# Plugin evaluation verification — 5 October 2026

Branch: `evaluation/product-platform-plugin-architecture`, based on pilot `d00ac79`.

- Affected regression suites: **230 passed, 3 skipped**. Includes 20 new plugin tests,
  existing ingestion orchestration/admin, publication, snapshots, and Words/TeX/Total MCP.
- The three skipped cases require `ADCS_TEST_POSTGRES_DSN`; live PostgreSQL was not used.
- Each standalone package's stdlib unittest suite passed (docs and API fixture subtests).
- Both wheels built offline and installed independently into their own `.venv`.
  Installed `python -I -m <plugin>.worker` extraction passed, with ADCS and the sibling
  plugin verified absent from each environment.
- A separate test verifies a worker can import a dependency present only in its
  dedicated virtual environment. Interpreter symlinks are preserved by the launcher.
- Affected-code mypy and repository source/test/plugin Ruff checks passed.
- `git diff --check` passed.

Behavior verified: Words and TeX stage independently; docs and API can run separately;
product-specific theme changes do not propagate across packages; a third plugin loads
without engine changes; scope/provenance and contract mismatches are rejected; worker
failure and timeout are surfaced; fixture publication keeps docs/API snapshots active
and leaves an existing other-product snapshot unchanged; plugin API symbols reach an
in-memory structured store without the engine's legacy extraction heuristics.

Validation uses fixtures and in-memory storage. No real corpus ingestion, external
publication, service deployment, Git commit/push or MR merge was performed. Full-corpus
extraction quality, live backend publication and concurrent ownership remain separate
acceptance work. See `product-platform-plugins.md` for exact implementation boundaries.

## Publication preparation — 7 October 2026

The affected regression suites were rerun before committing the reference
implementation: 230 passed and 3 PostgreSQL-dependent cases skipped. Ruff and
changed-code mypy passed; both package-local unittest suites passed again.
The ZIP handoff, generated output, virtual environments, credentials, downloaded
corpora and build artifacts are excluded from the publication commit. The earlier
5 October statements above describe the original verification session.

## Repository publication review — 8 October 2026

The earlier sections are historical evidence for their stated revisions. For the
`aspose-product-mcp-plugins` handoff, the affected plugin, queued-job, retrieval-profile,
namespace, conversion, canonical URL, query-planning and context-packing suites
passed: **128 pytest tests**, plus **18 Words and 1 TeX standalone unittest tests**.
`git diff --check` also passed. This was a focused regression run, not the full suite.

The VM container image previously built successfully, Compose configuration and
non-root volume permissions passed checks, and the live API/MCP health checks
passed. Full Words corpus validation subsequently passed; documentation publication
completed and API publication was running at the handoff check. See
[DEPLOYMENT.md](../DEPLOYMENT.md) for operation IDs and live status commands.

The publication review updated portable setup commands, separated the dated
workflow examination from current behavior, documented VM progress monitoring,
and checked publication candidates for matches to local credentials and common
private-key/token patterns. Runtime credentials, corpora, indexes and logs are
excluded. These checks do not establish complete end-to-end retrieval acceptance.
