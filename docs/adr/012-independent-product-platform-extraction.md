# ADR-012: Independent product-platform extraction

## Status
Proposed for production; implemented on the plugin evaluation branch at the user's request.

## Context
Product-platform themes, shortcodes and API-reference layouts evolve independently.
A shared mandatory parser couples Words/.NET and TeX/.NET changes. Total/.NET should
compose these platforms without another ingestion corpus.

## Decision
Use independently versioned, independently runnable product-platform packages.
Plugins own discovery, parsing, normalization, semantic chunking and symbol extraction.
Use the versioned JSON extraction contract to cross a process boundary. A host
adapter validates scope/provenance and feeds the existing orchestration/staging
pipeline. This is an extension of the existing orchestrator, not a new operation
state machine. Total is an explicit composition with no sources. Dedicated Python
environments isolate optional future parser dependencies.

## Consequences
Product changes and fixtures are independent. The initial copied implementations
increase maintenance size deliberately; only wire contracts are shared. Workers
are trusted subprocesses, not security sandboxes. Per-file startup overhead is
accepted for evaluation. Cache replay is disabled for plugin runs until extraction
fingerprints are part of cache identity. Existing source-kind snapshot isolation is
included as a prerequisite. Existing default ingestion/serving remains compatible.

## Revisit conditions
Corpus performance requires persistent workers; product dependencies require
containers; more platforms require dynamic serving routes; production requires
concurrent repository ownership, deployment verification and reviewed quality gates.

See [implementation guide](../product-platform-plugins.md) for exact scope and limits.
