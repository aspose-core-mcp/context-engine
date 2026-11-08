"""Signature-precision regression tests for the apiref symbol publisher.

Background: signature *coverage* was raised to 96-100% by the
``_scan_declaration_line`` fallback — it scans a collapsed
legacy page for the first access-modifier line when no ``api_signature`` chunk
is present. This is the residual *precision* tail: on example-heavy method
pages the first access-modifier line is a demo/example *class* declaration from
a code sample, not the symbol's own declaration.

Concrete observed case (live Postgres symbol store): querying
``aspose.cells.workbook.save`` (method) returned the signature
``public class WorkbookMethodSaveWithStreamSaveFormatDemo`` — a demo class from
the page's example block — instead of the real ``Workbook.Save(...)`` method
declaration.

These tests exercise the real publisher -> store query path with chunk records
shaped like that corpus, and assert the symbol's own declaration wins.
"""

from __future__ import annotations

from collections.abc import Iterator

from adcs.indexing.apiref_symbol_publisher import (
    ApiRefSymbolPublisher,
    _classify_declaration,
    _scan_declaration_line,
)
from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    InMemoryApiRefSymbolStore,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import (
    NormalizedDocument,
    NormalizedDocumentMetadata,
)
from adcs.ingestion.staging_store import StagingSnapshotTier

SCOPE = ApiRefScope(product="aspose.cells", language="net", version="25.4", locale="en")


def _chunk(
    *,
    source_path: str,
    symbol_fqn: str | None,
    chunk_type: str,
    text: str,
    doc_type: str = "api_reference_symbol",
    title: str = "",
) -> StageDChunkRecord:
    return StageDChunkRecord(
        chunk_id=f"{source_path}:{chunk_type}",
        repo_id="aspose.cells.apiref",
        product_id="aspose.cells",
        product_family="aspose",
        programming_language="net",
        version="25.4",
        source_kind="apiref",
        doc_locale="english",
        doc_type=doc_type,
        symbol_fqn=symbol_fqn,
        title=title or (symbol_fqn or "").rsplit(".", 1)[-1],
        section_path=("root",),
        canonical_url=f"https://docs.aspose.com/net/{(symbol_fqn or 'ns').replace('.', '/')}/",
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


def _doc(*, symbol_fqn: str, symbol_kind: str) -> NormalizedDocument:
    return NormalizedDocument(
        schema="adcs.normalized_document.v1",
        document=NormalizedDocumentMetadata(
            repo_id="aspose.cells.apiref",
            product_id="aspose.cells",
            product_family="aspose",
            source_kind="apiref",
            programming_language="net",
            doc_locale="english",
            version="25.4",
            title=symbol_fqn.rsplit(".", 1)[-1],
            doc_type="api_reference_symbol",
            canonical_url=f"https://docs.aspose.com/net/{symbol_fqn.replace('.', '/')}/",
            source_path="p",
            source_revision="rev1",
            symbol_fqn=symbol_fqn,
            symbol_kind=symbol_kind,
        ),
        chunks=(),
        warnings=(),
    )


class _FakeStaging:
    """In-memory staging source grouped/sorted by source_path."""

    def __init__(
        self,
        *,
        documents: list[NormalizedDocument],
        chunks: list[StageDChunkRecord],
    ) -> None:
        self._documents = documents
        self._chunks = chunks

    def iter_canonical_documents(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: object = None,
        snapshot_tier: object = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]:
        del repo_id, source_revision, snapshot_tier
        return iter(self._documents) if source_kind == "apiref" else iter(())

    def iter_chunk_records(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: object = None,
        snapshot_tier: object = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        del repo_id, source_revision, snapshot_tier
        return iter(self._chunks) if source_kind == "apiref" else iter(())


def _publish(staging: _FakeStaging) -> InMemoryApiRefSymbolStore:
    store = InMemoryApiRefSymbolStore()
    ApiRefSymbolPublisher(store=store, staging=staging).publish(
        repo_ids=["aspose.cells.apiref"], snapshot_id="precision-1"
    )
    return store


# A method page that collapsed into a single api_example chunk (no api_signature
# chunk). The example block declares a demo class FIRST, so the legacy fallback
# (first access-modifier line) wrongly returned the demo class. The symbol's own
# declaration appears further down.
_SAVE_DEMO_PAGE = (
    "Workbook.Save method\n"
    "\n"
    "Saves the workbook to a stream in the given format.\n"
    "\n"
    "public class WorkbookMethodSaveWithStreamSaveFormatDemo\n"
    "{\n"
    "    public static void Run()\n"
    "    {\n"
    "        Workbook workbook = new Workbook();\n"
    '        using var stream = File.Create("out.xlsx");\n'
    "        workbook.Save(stream, SaveFormat.Xlsx);\n"
    "    }\n"
    "}\n"
    "\n"
    "public void Save(Stream stream, SaveFormat saveFormat)\n"
)


def test_method_page_with_demo_class_in_example_picks_method_signature() -> None:
    """Reproduces aspose.cells.workbook.save: a demo class must NOT become the
    method's signature; the symbol's own declaration wins."""
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn="aspose.cells.Workbook.Save", symbol_kind="method")],
        chunks=[
            _chunk(
                source_path="workbook_save",
                symbol_fqn="aspose.cells.Workbook.Save",
                chunk_type="api_example",
                text=_SAVE_DEMO_PAGE,
                title="Save Method",
            )
        ],
    )
    store = _publish(staging)
    rows = store.get_symbol(member_fqn="aspose.cells.Workbook.Save", scope=SCOPE)
    assert len(rows) == 1
    save = rows[0]

    assert save.kind == "method"
    # The bug: signature was the demo class declaration from the example block.
    assert save.signature != "public class WorkbookMethodSaveWithStreamSaveFormatDemo"
    # Precision: a method symbol must not carry a type (class/interface/enum)
    # declaration as its signature.
    assert not (save.signature or "").lstrip().lower().startswith(
        ("public class", "public interface", "public enum", "public struct")
    )
    # The symbol's own declaration is recovered instead.
    assert save.signature == "public void Save(Stream stream, SaveFormat saveFormat)"


def test_method_demo_class_defeated_even_when_kind_unknown() -> None:
    """Real apiref staging often lacks symbol_kind (kind resolves to "symbol").
    Name matching alone must still defeat the demo class — the fix must not
    depend on a correctly-resolved kind."""
    staging = _FakeStaging(
        documents=[],  # no canonical doc -> no kind map -> kind "symbol"
        chunks=[
            _chunk(
                source_path="workbook_save",
                symbol_fqn="aspose.cells.Workbook.Save",
                chunk_type="api_example",
                text=_SAVE_DEMO_PAGE,
                title="Save",  # title gives no kind hint either
            )
        ],
    )
    store = _publish(staging)
    save = store.get_symbol(member_fqn="aspose.cells.Workbook.Save", scope=SCOPE)[0]
    assert save.kind == "symbol"
    assert save.signature == "public void Save(Stream stream, SaveFormat saveFormat)"


def test_real_class_page_signature_unchanged() -> None:
    """A real class page must keep its own ``public class ...`` declaration —
    the precision change must not regress correct class signatures."""
    text = (
        "Box class\n"
        "\n"
        "A box primitive used to build 3D scenes.\n"
        "\n"
        "public class Box : Primitive\n"
        "\n"
        "Box box = new Box();\n"  # a usage line that also references the name
    )
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn="aspose.threed.entities.Box", symbol_kind="class")],
        chunks=[
            _chunk(
                source_path="box",
                symbol_fqn="aspose.threed.entities.Box",
                chunk_type="api_example",
                text=text,
                title="Box Class",
            )
        ],
    )
    store = _publish(staging)
    box = store.get_symbol(member_fqn="aspose.threed.entities.Box", scope=SCOPE)[0]
    assert box.kind == "class"
    # The class's own declaration wins over the bare `new Box()` usage.
    assert box.signature == "public class Box : Primitive"


def test_class_page_with_member_decl_in_example_picks_class_signature() -> None:
    """Mirror of the demo-class bug in the other direction: a class page whose
    example block declares a helper *member* first must still resolve to the
    class's own declaration, not the member."""
    text = (
        "Shape class\n"
        "\n"
        "The base type for drawable shapes.\n"
        "\n"
        "public void Helper()\n"  # a stray member declaration appears first
        "\n"
        "public class Shape : IShape\n"
    )
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn="aspose.diagram.Shape", symbol_kind="class")],
        chunks=[
            _chunk(
                source_path="shape",
                symbol_fqn="aspose.diagram.Shape",
                chunk_type="api_example",
                text=text,
                title="Shape Class",
            )
        ],
    )
    store = _publish(staging)
    shape = store.get_symbol(member_fqn="aspose.diagram.Shape", scope=SCOPE)[0]
    assert shape.kind == "class"
    assert shape.signature == "public class Shape : IShape"


def test_demo_only_page_never_yields_demo_or_type_signature() -> None:
    """When a page has no clean declaration, a demo/example class must never
    become the signature; at worst the symbol's own call is used."""
    text = (
        "Compress method\n"
        "\n"
        "Compresses the document in place.\n"
        "\n"
        "public class PdfMethodCompressDemo\n"
        "{\n"
        "    public static void Run()\n"
        "    {\n"
        "        Document doc = new Document();\n"
        "        doc.Compress();\n"
        "    }\n"
        "}\n"
    )
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn="aspose.pdf.Document.Compress", symbol_kind="method")],
        chunks=[
            _chunk(
                source_path="compress",
                symbol_fqn="aspose.pdf.Document.Compress",
                chunk_type="api_example",
                text=text,
                title="Compress Method",
            )
        ],
    )
    store = _publish(staging)
    sym = store.get_symbol(member_fqn="aspose.pdf.Document.Compress", scope=SCOPE)[0]
    sig = sym.signature or ""
    assert sig != "public class PdfMethodCompressDemo"
    assert not sig.lstrip().lower().startswith("public class")
    assert "Compress" in sig  # the symbol's own call, not the demo wrapper


# --- direct unit tests of the scanner, grounded in real corpus patterns -------


def test_scan_prefers_name_matching_declaration_over_prose_with_parens() -> None:
    # Real case: a property whose prose ("... (i.e. same as geometry's units)")
    # has balanced parens, so the legacy first-match returned the prose line.
    text = (
        "Line thickness in document's measurement units (i.e. same as geometry's units).\n"
        "public double LineThickness { get; }"
    )
    assert (
        _scan_declaration_line(text, name="LineThickness", kind="property")
        == "public double LineThickness { get; }"
    )


def test_scan_drops_cpp_base_class_line_for_class_symbol() -> None:
    # Real case: C++ apiref renders base classes as `public Namespace::Type`
    # lines; that inheritance entry is not the class's own declaration.
    assert _scan_declaration_line("public System::IDisposable", name="Brush", kind="class") is None


def test_scan_picks_symbol_own_declaration_over_earlier_unrelated_one() -> None:
    text = "public void Other()\npublic void Target()"
    assert _scan_declaration_line(text, name="Target", kind="method") == "public void Target()"


def test_scan_without_context_still_drops_demo_but_keeps_real_type() -> None:
    # Back-compat: callers passing no name/kind still never get a demo artifact,
    # and a genuine type declaration is preserved.
    assert _scan_declaration_line("public class WidgetDemo\nDoes things.") is None
    assert _scan_declaration_line("public class Widget : Base") == "public class Widget : Base"


def test_classify_declaration_basic_shapes() -> None:
    assert _classify_declaration("public class Box : Primitive") == ("Box", "type")
    assert _classify_declaration("public void Save(Stream s)") == ("Save", "member")
    assert _classify_declaration("public double Height { get; set; }") == ("Height", "member")
    assert _classify_declaration("workbook.Save(stream, SaveFormat.Xlsx)") == ("Save", "member")


# The Aspose.Words class-page shape: the api_signature
# chunk STARTS with prose ("Provides methods to insert text...") and only then
# carries the fenced declaration. _split_signature_block requires the
# declaration on the FIRST content line, so it bails; the old fallback then
# scanned only head/example texts — which contain a name-matching demo usage
# (``DocumentBuilder builder = new DocumentBuilder(doc)``) — and stored that
# demo line as the class signature for every such page.
_WORDS_CLASS_SIG_BLOCK = (
    "Provides methods to insert text, images and other content.\n"
    "To learn more, visit the documentation article.\n"
    "public class DocumentBuilder\n"
)
_WORDS_CLASS_EXAMPLE = (
    "Document doc = new Document();\n"
    "DocumentBuilder builder = new DocumentBuilder(doc);\n"
    "builder.Write(\"hello\");\n"
)


def test_class_page_with_prose_first_signature_block_recovers_declaration() -> None:
    fqn = "aspose.words.documentbuilder"
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn=fqn, symbol_kind="class")],
        chunks=[
            _chunk(
                source_path="w",
                symbol_fqn=fqn,
                chunk_type="api_signature",
                text=_WORDS_CLASS_SIG_BLOCK,
            ),
            _chunk(
                source_path="w",
                symbol_fqn=fqn,
                chunk_type="api_example",
                text=_WORDS_CLASS_EXAMPLE,
            ),
        ],
    )
    store = _publish(staging)
    rows = store.get_symbol(member_fqn=fqn, scope=SCOPE)
    assert len(rows) == 1
    assert rows[0].signature == "public class DocumentBuilder"


def test_name_matching_demo_usage_never_beats_nothing() -> None:
    """A bare ``X x = new X(...)`` usage is not a declaration.

    When a page has NO real declaration anywhere, storing the demo usage line
    is worse than storing no signature: get_symbol_doc then presents example
    code as the API's signature (the exact defect seen for
    aspose.words.documentbuilder in a deployment).
    """
    fqn = "aspose.words.documentbuilder"
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn=fqn, symbol_kind="class")],
        chunks=[
            _chunk(
                source_path="w2",
                symbol_fqn=fqn,
                chunk_type="api_example",
                text=_WORDS_CLASS_EXAMPLE,
            ),
        ],
    )
    store = _publish(staging)
    rows = store.get_symbol(member_fqn=fqn, scope=SCOPE)
    assert len(rows) == 1
    assert rows[0].signature is None


def test_cpp_usage_line_heading_a_signature_block_is_not_the_declaration() -> None:
    """``auto doc = System::MakeObject<...>()`` heads many collapsed C++ member
    blocks; _split_signature_block used to return it as the declaration (it has
    balanced parens) — 344 words/cpp members shipped example code as their
    signature. The usage guard now sends such blocks to the name-aware scanner."""
    fqn = "aspose.words.drawing.imagedata.setimage"
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn=fqn, symbol_kind="method")],
        chunks=[
            _chunk(
                source_path="cpp1",
                symbol_fqn=fqn,
                chunk_type="api_signature",
                text=(
                    "auto doc = System::MakeObject<Aspose::Words::Document>();\n"
                    "void Aspose::Words::Drawing::ImageData::SetImage(String fileName)\n"
                ),
            ),
        ],
    )
    store = _publish(staging)
    rows = store.get_symbol(member_fqn=fqn, scope=SCOPE)
    assert rows[0].signature == "void Aspose::Words::Drawing::ImageData::SetImage(String fileName)"


def test_declaration_in_parameters_chunk_is_found_regardless_of_chunk_order() -> None:
    """The staging iterator does not guarantee which chunk heads a page: on the
    real Words corpus api_signature carries Remarks prose while the fenced
    declaration lands in an api_parameters chunk. The fallback must scan every
    non-example facet, not just the head chunk."""
    fqn = "aspose.words.documentbuilder"
    staging = _FakeStaging(
        documents=[_doc(symbol_fqn=fqn, symbol_kind="class")],
        chunks=[
            _chunk(
                source_path="w3",
                symbol_fqn=fqn,
                chunk_type="api_signature",
                text="Remarks\n\nDocumentBuilder makes building a Document easier.\n",
            ),
            _chunk(
                source_path="w3",
                symbol_fqn=fqn,
                chunk_type="api_parameters",
                text=(
                    "DocumentBuilder class\n\nProvides methods to insert content.\n\n"
                    "public class DocumentBuilder\n\nConstructors\n"
                ),
            ),
            _chunk(
                source_path="w3",
                symbol_fqn=fqn,
                chunk_type="api_example",
                text=_WORDS_CLASS_EXAMPLE,
            ),
        ],
    )
    store = _publish(staging)
    rows = store.get_symbol(member_fqn=fqn, scope=SCOPE)
    assert rows[0].signature == "public class DocumentBuilder"
