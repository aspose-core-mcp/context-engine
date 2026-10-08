# Aspose.Words for .NET extractor

This package owns discovery, docs extraction, API extraction normalization, semantic chunking and structured API symbol extraction.
It has no runtime dependency on ADCS or the other product plugin. Its initial
parser/converter/vocabulary are independent copies of the MIT-licensed ADCS
pilot at d00ac79. Keep attribution in LICENSE. Changes are deliberately NOT
synchronized automatically with the engine or sibling package.

Edit docs_extractor.py for docs theme/shortcode handling and
apiref_extractor.py for API reference behavior. The copied parser and converter
are this package's implementation, not imports from the engine. Initial source
prefixes in plugin.json are evaluation configuration; verify them against your
checkout. A layout mismatch fails explicitly; it never expands to another SDK.

Source launcher: `python -I worker.py`. Installed package:
`python -I -m adcs_words_net.worker`. The JSON contract is documented in
../../docs/product-platform-plugins.md. Dependencies and package releases can
be changed independently. Use a dedicated interpreter/container in deployment.

## Source repositories

Maintain independent Git checkouts inside this plugin:

```text
sources/
├── documentation/       # Documentation repository; ingest net/
└── api-reference/       # API Reference repository; ingest english/net/
```

The manifest paths are relative to the ingestion workspace (normally the engine
repository root), not to this README or the plugin directory. Repository URLs,
branches, source prefixes and extraction policies remain in `plugin.json`.
The documentation source uses `sabir-aspose/words-docs-com` on
`API-Reference-Aspose-Link-Update`; API Reference uses
`aspose-words/Aspose.Words-API-References` on `main`.

Run these commands from the engine repository root to populate the sources:

```sh
mkdir -p plugins/words-net/sources
git clone --filter=blob:none --sparse --branch API-Reference-Aspose-Link-Update \
  https://github.com/sabir-aspose/words-docs-com.git \
  plugins/words-net/sources/documentation
git -C plugins/words-net/sources/documentation sparse-checkout set net
git clone --filter=blob:none --sparse --branch main \
  https://github.com/aspose-words/Aspose.Words-API-References.git \
  plugins/words-net/sources/api-reference
git -C plugins/words-net/sources/api-reference sparse-checkout set english/net
```

Before ingestion, record each checkout's `git rev-parse HEAD` and ensure its
working tree is clean. To update a source, run `git pull --ff-only` in that
checkout, then validate extraction before publishing again. Retain the commit
hashes with the ingestion results to reproduce a run.

The host repository ignores `sources/`; extractor commits do not include corpus
content. Python package discovery remains limited to `src`, so source checkouts
are not part of the plugin wheel. Source setup requires no API, Celery or Docker
services. The ingestion CLI reads existing checkouts; it does not clone them.

Canonical bases are `https://docs.aspose.com/words/net` and
`https://reference.aspose.com/words/net`. Pages without a front-matter `url`
use their path relative to the configured source prefix, with `_index.md`
removed (or the `.md` extension removed), and a trailing slash. Local checkout
directories and source prefixes are never appended to the canonical base.
For front-matter overrides, absolute HTTP(S) URLs are preserved. The Words
corpora's `/net/` and `/net/path/` forms resolve under the configured
`/words/net/` base. Already-qualified `/words/net/path/` URLs are not prefixed
again. Other `/path/` forms use the site's origin, and `path/` resolves relative
to the platform base. Query
strings and fragments are preserved. Other URL schemes and protocol-relative
URLs are rejected. An explicit override can therefore point outside `/words/net/`.

Citation anchors use an explicit ID on the first Markdown heading, such as
`# Examples {#examples}`, when present. Otherwise citations use `#` (page top).
Chunks and code snippets share that page-level anchor rather than inventing
chunk-specific fragment IDs. Automatic theme-generated heading IDs require
verification against rendered pages before enabling deeper section links.

API identities retain every path segment after the namespace (for example,
`aspose.words/node/document` is `Aspose.Words.Node.Document`). Code examples
come only from fenced blocks within Examples sections, independently of chunk
grouping. Symbol payloads retain legacy `examples` strings and additionally
provide typed `example_snippets` for serving the code language accurately.
These extraction changes require republishing API Reference to replace the
active data; restarting the API alone cannot repair existing symbol rows.

Structured signatures come from access-modified declarations in fenced blocks
outside Examples sections. Each distinct declaration produces an overload row
with its section anchor and section-local examples. Pages without a matching
declaration retain an empty signature rather than advertising a Markdown heading
or example statement as an API contract.

## Gist examples for documentation

Before validating, staging or publishing documentation, prepare the named Gist
files referenced by the checkout. From the engine repository root:

```sh
PYTHONPATH="$PWD/plugins/words-net/src" \
  plugins/words-net/.venv/bin/python -m adcs_words_net.gist_examples
```

This explicit network operation clones each required public Gist into a temporary
directory and caches only the referenced files in `sources/gist-examples.json`.
Each entry records the Gist commit, source URL, SHA-256 checksum and code. Subsequent
runs reuse validated entries; `--refresh` explicitly updates them. The existing
cache is replaced only after all downloads succeed. Preserve a copy of this cache
with publication records: the documentation Git revision alone does not identify
external example contents. Do not run concurrent cache preparation commands.

Extraction itself stays offline. It converts cached Gist content to fenced code
before parsing, preserving the documentation page as the citation. Missing,
empty or corrupt examples fail extraction instead of silently losing code.
Documentation must be republished to put these snippets into retrieval indexes;
API Reference does not require another publication for this change.

The default cache location belongs to the source-checkout plugin. Installed-package
deployments must provision the cache at `gist_examples.DEFAULT_CACHE`; this
evaluation does not bundle downloaded examples into the wheel. `--cache` selects
a preparation output, but does not change the worker's default cache location.

## Excerpt cleanup publication scope

Republish both `aspose.words.net.docs` (`documentation/net`) and
`aspose.words.net.apiref` (`api-reference/english/net`) after the excerpt cleanup.
Documentation loses presentation HTML and heading IDs from excerpt text while
retaining explicit citation anchors. API narrative decodes Markdown punctuation
escapes; fenced examples repair escaped XML summary tags and document filename
extensions without broadly decoding C# regex/string escapes. API publication
must replace both retrieval chunks and structured symbol payloads. No TeX or
other product source needs publication; restarting services cannot update stored
excerpts. Use the existing configured runtime and Gist cache.

The local Document source already contains plain C#; the regression uses an
escaped variant of its checked-in fixture to cover the reported output. Existing
stored output may predate the current plugin extraction. The mail-merge query's
`partial` / `answer_incomplete` status is a separate serving/completeness outcome;
cleanup does not establish that it is resolved. Recheck it after publication.

## Retrieval profile (serving only)

`retrieval-profile.json`, referenced by `plugin.json`, owns Words/.NET query
preferences. Version 1.0.0 prefers classic `MailMerge.Execute` for mail-merge
questions and `ExecuteWithRegions` when regions are requested. Images and LowCode
requests bypass these preferences, as do explicit qualified type/member queries.
The engine uses scoped exact lookups to add preferred symbols and their overloads
before generic ranking chooses the parameter match. Missing symbols are never
fabricated; ordinary search results remain available.

The shared engine validates the schema, product/platform scope, symbol product
prefixes, and contained file paths. Profiles are optional; other products and
platforms retain generic retrieval. Debug responses identify the profile version,
matched rule IDs, and preferred symbols under `retrieval_trace.retrieval_profile`.
These are candidate-ranking reasons, not a guarantee of final context placement.

In this source checkout the engine uses `config/product-platform-plugins.json`.
An installed deployment can set `ADCS_RETRIEVAL_PLUGIN_CATALOG` to an absolute
catalog path and must provision the referenced plugin manifests and profile files.
An absent default catalog uses generic ranking; an explicitly configured invalid
catalog/profile is an error. Profiles are cached per process: restart the API
when updating them. No extraction or reingestion is needed for profile changes.
This initial profile covers mail merge; other Words operations use generic ranking.

### Namespace eligibility (profile 1.1.0)

The profile-level `excluded_namespaces` list excludes `Aspose.Words.Lowcode`
from Words/.NET API-reference retrieval. This is independent of ranking rules:
explicit LowCode requests, preferred-symbol lookup, structured search/member
listing, and exact symbol lookup cannot override the exclusion. Matching is
case-insensitive and uses namespace boundaries (the exact namespace or its dotted
descendants); similarly named namespaces remain eligible. Preferred symbols that
conflict with an exclusion fail profile validation. The optional field defaults
to an empty list for other profiles and is included in debug profile explanations.

Built-in PostgreSQL and in-memory stores filter before candidate limits. A shared
serving wrapper also filters custom-store results; custom stores may consequently
return fewer than the requested number until they implement pre-limit filtering.
Fusion and context packing enforce API-reference eligibility defensively. Legacy
API-reference namespace pages without a symbol FQN use canonical URL namespace
segments for this check. Documentation filtering is unchanged, including pages
that mention LowCode. No new API-surface identity is introduced.

Restart the API to load this policy and clear its process-local profiles/cache.
No reingestion or data deletion is required: excluded records remain stored but
are unavailable through the normal Words/.NET API-reference retrieval surface.

### PDF conversion and HTML heading cleanup (profile 1.2.0)

The `word-to-pdf` rule targets `Document.Save` and `PdfSaveOptions` for Word,
DOC, DOCX, or document requests containing “to PDF” or “as PDF”. The generic
schema supports optional `any_terms` and `any_phrases` conditions; existing rules
retain their behavior when these fields are omitted. Reverse PDF-to-Word and
non-PDF conversions do not activate this preference. Exact qualified-symbol
queries and namespace exclusions remain authoritative.

The shared reranker now gives matched profile targets an explicit score bonus.
API source-coverage promotion requires task evidence (a profile match, or
query coverage with name/signature evidence), so an unrelated API no longer
receives the reserved second context position solely because it is an API.
Release notes receive an additional penalty on unversioned how-to questions;
release-note and version-specific questions retain their existing treatment.

Restart the API for these serving changes. The separate extractor cleanup removes
HTML h1–h6 presentation tags outside fenced code while retaining their text.
Republish only `aspose.words.net.docs` to replace stored heading remnants; API
Reference does not need republishing for this cleanup. No services or ingestion
were run during implementation.

### Source-backed symbol casing

Lowercase API URL paths still establish symbol identity, but matching page titles
and the first API heading restore source spelling for qualified suffixes such as
`DocumentBuilder.Font`. A recognized declaration outside Examples supplies the
member's exact spelling (for example, `SetTextFormat`), overriding a lowercase
label. Normalized documents, chunks, symbol names, parent names, and overloads
therefore use the same restored identity. Explicit `symbol_fqn` metadata remains
authoritative; segments without source evidence retain the existing path fallback.
Canonical URLs stay unchanged and exact symbol lookup remains case-insensitive.
Republish API Reference to update stored names; restarting alone is insufficient.
