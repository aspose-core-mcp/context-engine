from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest

from adcs.indexing.apiref_legacy_staging import (
    CanonicalUrlRewritingStaging,
    derive_flat_member_fqn,
    derive_member_fqn_from_url,
    derive_programming_language_from_url,
)
from adcs.indexing.apiref_symbol_publisher import ApiRefSymbolPublisher
from adcs.indexing.apiref_symbol_store import ApiRefScope, InMemoryApiRefSymbolStore
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import (
    NormalizedDocument,
    NormalizedDocumentMetadata,
)
from adcs.ingestion.staging_store import StagingSnapshotTier

SCOPE = ApiRefScope(product="groupdocs.markdown", language="net", version="25.4", locale="en")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://docs.aspose.com/net/groupdocs.markdown/convertoptions/",
            "groupdocs.markdown.convertoptions",
        ),
        (
            "https://docs.aspose.com/net/groupdocs.markdown/convertoptions/maxrows/",
            "groupdocs.markdown.convertoptions.maxrows",
        ),
        (
            "https://docs.aspose.com/cpp/aspose.words.ai/aimodel/checkgrammar/",
            "aspose.words.ai.aimodel.checkgrammar",
        ),
        # leading locale segment ("english") before language is skipped via first-dotted rule
        (
            "https://docs.aspose.com/english/net/aspose.slides/presentation/save/",
            "aspose.slides.presentation.save",
        ),
        ("https://docs.aspose.com/net/groupdocs.markdown/", "groupdocs.markdown"),  # namespace page
        ("https://docs.aspose.com/", None),  # root
        ("https://docs.aspose.com/net/", None),  # language-only page
        ("", None),
    ],
)
def test_derive_member_fqn_from_url(url: str, expected: str | None) -> None:
    assert derive_member_fqn_from_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # Flat cpp-bridge layout: no namespace segment -> product + members,
        # leading language/locale dropped.
        (
            "https://docs.aspose.com/go-cpp/workbook/getdatasorter/",
            "aspose.cells.workbook.getdatasorter",
        ),
        (
            "https://docs.aspose.com/english/cpp/box/getheight/",
            "aspose.cells.box.getheight",
        ),
        # language-root page -> nothing left after the drop -> None.
        ("https://docs.aspose.com/go-cpp/", None),
        ("", None),
    ],
)
def test_derive_flat_member_fqn(url: str, expected: str | None) -> None:
    assert (
        derive_flat_member_fqn(
            url, product_id="aspose.cells", programming_language="go-cpp", doc_locale="english"
        )
        if "go-cpp" in url or not url
        else derive_flat_member_fqn(
            url, product_id="aspose.cells", programming_language="cpp", doc_locale="english"
        )
    ) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://docs.aspose.com/net/aspose.threed/scene/save/", "net"),
        ("https://docs.aspose.com/java/com.aspose.threed/scene/", "java"),
        # locale-prefixed layout (the corpus staged before layout_detection ran)
        ("https://docs.aspose.com/english/net/aspose.threed.entities/box/", "net"),
        ("https://docs.aspose.com/english/python-net/aspose.threed.animation/", "python-net"),
        ("https://docs.aspose.com/nodejs-java/aspose.threed/", "nodejs-java"),
        ("https://docs.aspose.com/english/", None),  # locale-only, no language token
        ("https://docs.aspose.com/", None),  # root
        ("", None),
        (None, None),
    ],
)
def test_derive_programming_language_from_url(url: str | None, expected: str | None) -> None:
    assert derive_programming_language_from_url(url) == expected


def test_wrapper_recovers_language_from_url() -> None:
    """A chunk left as programming_language='unknown' is relabeled from its URL.

    Reproduces the 8 repos whose layout_detection was empty at convert time:
    every page staged as 'unknown', but the canonical_url carries '/net/'.
    """
    broken = _chunk(
        url="https://docs.aspose.com/english/net/aspose.threed.entities/box/",
        title="Box",
        chunk_type="api_signature",
        text="public class Box\n\nA box primitive.",
    )
    broken = replace(broken, programming_language="unknown", doc_locale="english")
    store = InMemoryApiRefSymbolStore()
    staging = CanonicalUrlRewritingStaging(_BrokenStaging([broken]))
    result = ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["groupdocs.markdown.apiref"], snapshot_id="langfix-1"
    )
    assert result.symbols_written == 1
    net_scope = ApiRefScope(
        product="groupdocs.markdown", language="net", version="25.4", locale="en"
    )
    rows = store.get_symbol(member_fqn="aspose.threed.entities.box", scope=net_scope)
    assert len(rows) == 1
    assert rows[0].language == "net"  # recovered from the URL, not the stale 'unknown'


def _chunk(*, url: str, title: str, chunk_type: str, text: str) -> StageDChunkRecord:
    # Mirrors the broken legacy staging: symbol_fqn absent, doc_type=namespace.
    source_path = (
        "source-repo-apiref/GroupDocs.Markdown/english/net/"
        + url.split("/net/", 1)[-1]
        + "_index.md"
    )
    return StageDChunkRecord(
        chunk_id=f"{url}:{chunk_type}",
        repo_id="groupdocs.markdown.apiref",
        product_id="groupdocs.markdown",
        product_family="groupdocs",
        programming_language="net",
        version="25.4",
        source_kind="apiref",
        doc_locale="english",
        doc_type="api_reference_namespace",
        symbol_fqn=None,
        title=title,
        section_path=("root",),
        canonical_url=url,
        section_anchor="#main",
        source_path=source_path,
        source_revision="rev1",
        is_deprecated=False,
        has_code_example=(chunk_type == "api_example"),
        chunk_type=chunk_type,
        text=text,
        tokens=len(text.split()),
        checksum="x",
    )


class _BrokenStaging:
    """Legacy staging: clean canonical_url, but no symbol_fqn (all namespace)."""

    def __init__(self, chunks: list[StageDChunkRecord]) -> None:
        self._chunks = chunks

    def iter_canonical_documents(
        self,
        *,
        repo_id,
        source_kind,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[object]:
        del repo_id, source_revision, snapshot_tier
        return iter(())  # legacy docs lack symbol_kind; publisher uses title fallback

    def iter_chunk_records(
        self,
        *,
        repo_id,
        source_kind,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        del repo_id, source_revision, snapshot_tier
        if source_kind != "apiref":
            return iter(())
        return iter(self._chunks)


def _staging() -> _BrokenStaging:
    base = "https://docs.aspose.com/net/groupdocs.markdown"
    return _BrokenStaging(
        [
            _chunk(
                url=f"{base}/",
                title="GroupDocs.Markdown",
                chunk_type="api_remarks",
                text="The namespace.",
            ),
            _chunk(
                url=f"{base}/convertoptions/",
                title="ConvertOptions",
                chunk_type="api_signature",
                text="public class ConvertOptions\n\nOptions controlling Markdown output.",
            ),
            _chunk(
                url=f"{base}/convertoptions/maxrows/",
                title="MaxRows",
                chunk_type="api_signature",
                text="public int MaxRows { get; set; }\n\nGets or sets the maximum number of rows.",
            ),
        ]
    )


def test_rewriting_wrapper_repairs_fqn_and_publishes() -> None:
    store = InMemoryApiRefSymbolStore()
    staging = CanonicalUrlRewritingStaging(_staging())
    result = ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["groupdocs.markdown.apiref"], snapshot_id="legacy-1"
    )
    # All three pages now become symbols (none skipped as namespace).
    assert result.symbols_written == 3
    assert result.namespaces_skipped == 0

    # Stored lowercase, but a proper-case client query still matches.
    rows = store.get_symbol(member_fqn="GroupDocs.Markdown.ConvertOptions", scope=SCOPE)
    assert len(rows) == 1
    assert rows[0].member_fqn == "groupdocs.markdown.convertoptions"
    assert rows[0].signature == "public class ConvertOptions"

    # Structural: the property is a child of the class (case-insensitive parent).
    members = store.list_members(parent_fqn="groupdocs.markdown.ConvertOptions", scope=SCOPE)
    assert [m.member_fqn for m in members] == ["groupdocs.markdown.convertoptions.maxrows"]


class _CanonicalDocStaging:
    """Staging whose canonical documents carry a fine-grained symbol_kind but a
    locale/repo-polluted symbol_fqn (what the converter emits for repos like
    aspose.llm/drawing/gis), plus a matching chunk record."""

    def __init__(self, doc: NormalizedDocument, chunk: StageDChunkRecord) -> None:
        self._doc = doc
        self._chunk = chunk

    def iter_canonical_documents(
        self,
        *,
        repo_id,
        source_kind,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]:
        del repo_id, source_revision, snapshot_tier
        return iter((self._doc,)) if source_kind == "apiref" else iter(())

    def iter_chunk_records(
        self,
        *,
        repo_id,
        source_kind,
        source_revision=None,
        snapshot_tier=StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        del repo_id, source_revision, snapshot_tier
        return iter((self._chunk,)) if source_kind == "apiref" else iter(())


def test_rewriting_wrapper_repairs_canonical_fqn_so_symbol_kind_survives() -> None:
    """The publisher keys its kind_map by the canonical-document fqn and looks it
    up by the (repaired) chunk-record fqn. If only the chunk fqn is repaired, a
    polluted document fqn misses every lookup and the fine-grained kind collapses
    to generic 'symbol'. The wrapper must repair BOTH."""
    url = "https://docs.aspose.com/net/aspose.llm/asposellmapi/"
    meta = NormalizedDocumentMetadata(
        repo_id="aspose.llm.apiref",
        product_id="aspose.llm",
        product_family="aspose",
        source_kind="apiref",
        programming_language="net",
        doc_locale="english",
        version="",
        title="Class AsposeLLMApi",
        doc_type="api_reference_symbol",
        canonical_url=url,
        source_path="english/net/aspose.llm/asposellmapi/_index.md",
        source_revision="rev",
        symbol_fqn="Aspose.LLM.Aspose.llm.Asposellmapi",  # polluted (repo-dir + ns leak)
        symbol_kind="class",
    )
    doc = NormalizedDocument(
        schema="adcs.normalized_document.v1", document=meta, chunks=(), warnings=()
    )
    chunk = StageDChunkRecord(
        chunk_id=f"{url}:api_signature",
        repo_id="aspose.llm.apiref",
        product_id="aspose.llm",
        product_family="aspose",
        programming_language="net",
        version="25.4",
        source_kind="apiref",
        doc_locale="english",
        doc_type="api_reference_namespace",  # repaired to symbol by the wrapper
        symbol_fqn=None,
        title="Class AsposeLLMApi",
        section_path=("root",),
        canonical_url=url,
        section_anchor="#main",
        source_path="source-repo-apiref/Aspose.LLM/english/net/aspose.llm/asposellmapi/_index.md",
        source_revision="rev",
        is_deprecated=False,
        has_code_example=False,
        chunk_type="api_signature",
        text="public class AsposeLLMApi\n\nHigh-level facade.",
        tokens=5,
        checksum="x",
    )
    staging = CanonicalUrlRewritingStaging(_CanonicalDocStaging(doc, chunk))

    # Unit level: the canonical document fqn is repaired to match the chunk fqn.
    out = next(
        iter(
            staging.iter_canonical_documents(
                repo_id="aspose.llm.apiref", source_kind="apiref"
            )
        )
    ).document
    assert out.symbol_fqn == "aspose.llm.asposellmapi"
    assert out.symbol_kind == "class"

    # End to end: the published symbol keeps the fine-grained kind.
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["aspose.llm.apiref"], snapshot_id="rebuild-1"
    )
    scope = ApiRefScope(product="aspose.llm", language="net", version="25.4", locale="en")
    rows = store.get_symbol(member_fqn="aspose.llm.asposellmapi", scope=scope)
    assert len(rows) == 1
    assert rows[0].kind == "class"


def test_root_and_language_pages_are_skipped() -> None:
    staging = CanonicalUrlRewritingStaging(
        _BrokenStaging(
            [
                _chunk(
                    url="https://docs.aspose.com/",
                    title="API",
                    chunk_type="api_remarks",
                    text="root",
                ),
                _chunk(
                    url="https://docs.aspose.com/net/",
                    title="NET",
                    chunk_type="api_remarks",
                    text="lang",
                ),
            ]
        )
    )
    store = InMemoryApiRefSymbolStore()
    result = ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["groupdocs.markdown.apiref"], snapshot_id="legacy-1"
    )
    assert result.symbols_written == 0  # no namespace segment → not symbols


def test_case_insensitive_lookup_in_store() -> None:
    store = InMemoryApiRefSymbolStore()
    staging = CanonicalUrlRewritingStaging(_staging())
    ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["groupdocs.markdown.apiref"], snapshot_id="legacy-1"
    )
    # Mixed/upper/lower all resolve to the same lowercase-stored row.
    for q in (
        "groupdocs.markdown.convertoptions",
        "GroupDocs.Markdown.ConvertOptions",
        "GROUPDOCS.MARKDOWN.CONVERTOPTIONS",
    ):
        assert len(store.get_symbol(member_fqn=q, scope=SCOPE)) == 1
