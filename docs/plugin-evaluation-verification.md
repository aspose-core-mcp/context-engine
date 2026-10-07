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
