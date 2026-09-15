"""Full-chain integration: real converter + chunker + staging + publisher + store.

The publisher's other tests feed it hand-built StageDChunkRecords. This test
drives the REAL pipeline end to end — Hugo pages → HugoToNormalizedDocument
Converter → StageDChunkingPolicy → FileSystemCanonicalStagingStore →
ApiRefSymbolPublisher → ApiRefSymbolStore — so it validates the publisher
against the chunker's actual output, including the grouping behaviour that
collapses a small symbol page into a single merged chunk.
"""

from __future__ import annotations

import hashlib
import os
import types
from pathlib import Path

import pytest

from adcs.indexing.apiref_symbol_publisher import ApiRefSymbolPublisher
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    InMemoryApiRefSymbolStore,
    PostgresApiRefSymbolStore,
)
from adcs.ingestion.chunking import StageDChunkingPolicy
from adcs.ingestion.hugo_parser import HugoCodeBlock, HugoNormalizedPage
from adcs.ingestion.normalized_document import HugoToNormalizedDocumentConverter
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
)
from adcs.ingestion.staging_store import FileSystemCanonicalStagingStore

_PG_DSN = os.environ.get("ADCS_TEST_POSTGRES_DSN")
REPO = "aspose.slides.apiref"
SCOPE = ApiRefScope(product="aspose.slides", language="net", version="24.1", locale="en")

_METHOD_BODY = (
    "public void Save(string fileName, SaveFormat format)\n"
    "\n"
    "Saves the presentation to the specified file using the given format.\n"
    "\n"
    "| Parameter | Type | Description |\n"
    "| --- | --- | --- |\n"
    "| fileName | string | The output file path. |\n"
    "| format | SaveFormat | The output format. |\n"
    "\n"
    "Returns nothing; the file is written as a side effect.\n"
)


def _page(
    *,
    source_path: str,
    title: str,
    body: str,
    symbol_fqn: str | None,
    code: str | None = None,
) -> HugoNormalizedPage:
    metadata: dict[str, object] = {"title": title, "version": "24.1"}
    if symbol_fqn is not None:
        metadata["symbol_fqn"] = symbol_fqn
    return HugoNormalizedPage(
        repo_id=REPO,
        source_path=source_path,
        source_kind="apiref",
        product_id="aspose.slides",
        product_family="aspose",
        programming_language="net",
        doc_locale="english",
        title=title,
        metadata=metadata,
        body_plain=body,
        headings=(),
        code_blocks=(
            (HugoCodeBlock(language="csharp", code=code, line_start=0, line_end=0),) if code else ()
        ),
        parse_warnings=(),
        is_index_page=symbol_fqn is None,
    )


def _pages() -> list[HugoNormalizedPage]:
    return [
        _page(
            # Path ends at the namespace dir → no resolvable symbol_fqn →
            # doc_type api_reference_namespace → publisher skips it.
            source_path="source-repo-apiref/slides/english/net/aspose.slides/_index.md",
            title="Aspose.Slides Namespace",
            body="The Aspose.Slides namespace provides classes to work with presentations.",
            symbol_fqn=None,
        ),
        _page(
            source_path="source-repo-apiref/Aspose.Slides/english/net/aspose.slides/presentation/_index.md",
            title="Presentation Class",
            body=(
                "Represents a PowerPoint presentation that you can create, load, "
                "modify and save. It is the root object of the document model."
            ),
            symbol_fqn="Aspose.Slides.Presentation",
        ),
        _page(
            source_path="source-repo-apiref/Aspose.Slides/english/net/aspose.slides/presentation/save/_index.md",
            title="Save Method",
            body=_METHOD_BODY,
            symbol_fqn="Aspose.Slides.Presentation.Save",
            code='pres.Save("out.pptx", SaveFormat.Pptx);',
        ),
        _page(
            source_path="source-repo-apiref/Aspose.Slides/english/net/aspose.slides/presentation/slides/_index.md",
            title="Slides Property",
            body="Gets the collection of all slides contained in the presentation.",
            symbol_fqn="Aspose.Slides.Presentation.Slides",
        ),
    ]


def _ingest_to_staging(workspace_root: Path) -> FileSystemCanonicalStagingStore:
    converter = HugoToNormalizedDocumentConverter()
    policy = StageDChunkingPolicy()
    staging = FileSystemCanonicalStagingStore(workspace_root=workspace_root)

    documents = []
    chunk_records = []
    file_checksums = {}
    for page in _pages():
        document = converter.convert_page(page=page, source_revision="rev1")
        _, records = policy.chunk_document(page=page, normalized_document=document)
        documents.append(document)
        chunk_records.extend(records)
        file_checksums[page.source_path] = hashlib.sha256(page.body_plain.encode()).hexdigest()

    staging.write_repository_snapshot(
        repo_id=REPO,
        source_kind="apiref",
        source_revision="rev1",
        file_checksums=file_checksums,
        canonical_documents=documents,
        chunk_records=chunk_records,
    )
    return staging


def _publish(staging: FileSystemCanonicalStagingStore, store) -> ApiRefScope:
    publisher = ApiRefSymbolPublisher(store=store, staging=staging)
    result = publisher.publish(repo_ids=[REPO], snapshot_id="fullchain-1")
    assert result.namespaces_skipped >= 1  # the namespace page is skipped
    assert result.symbols_written >= 3
    assert result.scopes_activated  # at least one scope activated
    return result.scopes_activated[0]


def _assert_correct(store, scope: ApiRefScope) -> None:
    # Method: clean declaration line, NOT the merged blob; real summary.
    save = store.get_symbol(member_fqn="Aspose.Slides.Presentation.Save", scope=scope)
    assert len(save) == 1
    method = save[0]
    assert method.kind == "method"
    assert method.signature == "public void Save(string fileName, SaveFormat format)"
    assert method.summary == "Saves the presentation to the specified file using the given format."
    # Full content preserved in the payload body (param table survived).
    assert "fileName" in (method.payload.get("body") or "")

    # Class: kind + summary derived from prose.
    pres = store.get_symbol(member_fqn="Aspose.Slides.Presentation", scope=scope)
    assert len(pres) == 1
    assert pres[0].kind == "class"
    assert pres[0].summary.startswith("Represents a PowerPoint presentation")

    # Structural: children of the class. Compare case-insensitively — the
    # canonical-URL repair path (orchestrator) emits lowercase FQNs/names while
    # the direct-publish path keeps the staged casing; lookups are
    # case-insensitive either way.
    members = store.list_members(parent_fqn="Aspose.Slides.Presentation", scope=scope)
    assert {m.name.lower() for m in members} == {"save", "slides"}

    # Search + FTS over the real summaries.
    assert any(
        s.name.lower() == "save" for s in store.search_symbols(pattern="Save", scope=scope)
    )
    assert store.fts_search(query="collection of slides", scope=scope)


def test_full_chain_inmemory(tmp_path: Path) -> None:
    staging = _ingest_to_staging(tmp_path)
    store = InMemoryApiRefSymbolStore()
    scope = _publish(staging, store)
    assert scope == SCOPE
    _assert_correct(store, scope)


@pytest.mark.skipif(_PG_DSN is None, reason="ADCS_TEST_POSTGRES_DSN not set")
def test_full_chain_postgres(tmp_path: Path) -> None:
    staging = _ingest_to_staging(tmp_path)
    store = PostgresApiRefSymbolStore(postgres_dsn=_PG_DSN)  # type: ignore[arg-type]
    scope = _publish(staging, store)
    _assert_correct(store, scope)


def test_orchestrator_publishes_apiref_symbols_when_configured(tmp_path: Path) -> None:
    # The ingestion orchestrator should invoke the symbol publisher from the
    # same staging snapshot when an apiref_symbol_store is injected.
    staging = _ingest_to_staging(tmp_path)
    store = InMemoryApiRefSymbolStore()
    orchestrator = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        canonical_staging_store=staging,
        apiref_symbol_store=store,
    )
    repository = types.SimpleNamespace(source_kind="apiref", repo_id=REPO)
    orchestrator._publish_apiref_symbols(repository=repository, snapshot_id="orch-snap")

    _assert_correct(store, SCOPE)


def test_orchestrator_apiref_wiring_is_noop_without_store(tmp_path: Path) -> None:
    staging = _ingest_to_staging(tmp_path)
    orchestrator = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        canonical_staging_store=staging,
    )
    repository = types.SimpleNamespace(source_kind="apiref", repo_id=REPO)
    # No store configured → no-op, no error.
    orchestrator._publish_apiref_symbols(repository=repository, snapshot_id="x")


def test_orchestrator_apiref_wiring_skips_docs_repos(tmp_path: Path) -> None:
    staging = _ingest_to_staging(tmp_path)
    store = InMemoryApiRefSymbolStore()
    orchestrator = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        canonical_staging_store=staging,
        apiref_symbol_store=store,
    )
    repository = types.SimpleNamespace(source_kind="docs", repo_id="aspose.slides.docs")
    orchestrator._publish_apiref_symbols(repository=repository, snapshot_id="x")
    # docs repos are not symbol-published; store stays empty/inactive.
    assert store.get_symbol(member_fqn="Aspose.Slides.Presentation.Save", scope=SCOPE) == ()
