from __future__ import annotations

import pytest

from adcs.api.apiref_vocabulary import Vocabulary, is_real_product

VOCAB = Vocabulary(
    by_product={
        "aspose.cells": frozenset({"net", "java", "python-net"}),
        "aspose.words": frozenset({"net"}),
        "groupdocs.markdown": frozenset({"net", "java"}),
    }
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aspose.cells", "aspose.cells"),  # exact
        ("cells", "aspose.cells"),  # bare name → family
        ("Aspose.Cells", "aspose.cells"),  # case
        ("aspose-cells", "aspose.cells"),  # separators
        ("aspose cells", "aspose.cells"),
        ("aspose.cels", "aspose.cells"),  # one-char typo → fuzzy
        ("words", "aspose.words"),
        ("totally.unknown", "totally.unknown"),  # nothing matches → unchanged
    ],
)
def test_normalize_product(raw: str, expected: str) -> None:
    assert VOCAB.normalize_product(raw) == expected


@pytest.mark.parametrize(
    ("raw", "product", "expected"),
    [
        ("net", "aspose.cells", "net"),  # exact served
        ("csharp", "aspose.cells", "net"),  # alias → served
        ("c#", "aspose.cells", "net"),
        ("dotnet", "aspose.cells", "net"),
        ("python", "aspose.cells", "python-net"),  # alias to a served flavour
        ("java", "aspose.cells", "java"),  # exact served, not defaulted away
        ("ruby", "aspose.words", "net"),  # unknown + product serves only one → that one
        ("ruby", "aspose.cells", "net"),  # unknown + multi-lang → 'net' default
    ],
)
def test_normalize_language(raw: str, product: str, expected: str) -> None:
    assert VOCAB.normalize_language(raw, product=product) == expected


def test_closest_products_suggests_typo() -> None:
    assert "aspose.cells" in VOCAB.closest_products("aspose.cellz")


# --- #4: never silently substitute a DIFFERENT real product (pdf→psd) ---

_PSD_VOCAB = Vocabulary(
    by_product={"aspose.psd": frozenset({"net"}), "aspose.cells": frozenset({"net"})}
)


def test_normalize_product_does_not_swap_distant_real_product() -> None:
    # aspose.pdf is NOT served; aspose.psd is. A 2-edit leaf gap must NOT auto-swap
    # (would hand a PDF request confident Photoshop symbols). Stays unresolved.
    assert _PSD_VOCAB.normalize_product("aspose.pdf") == "aspose.pdf"
    assert _PSD_VOCAB.normalize_product("pdf") == "pdf"


def test_normalize_product_still_recovers_single_typo() -> None:
    # a genuine one-char typo (distance 1) is still auto-recovered
    assert _PSD_VOCAB.normalize_product("aspose.cels") == "aspose.cells"
    assert _PSD_VOCAB.normalize_product("aspose.psdd") == "aspose.psd"


def test_unresolved_pdf_still_offers_did_you_mean() -> None:
    # fail loud, not silent: the close product is still suggested for the caller to confirm
    assert "aspose.psd" in _PSD_VOCAB.closest_products("aspose.pdf")


def test_closest_products_suggests_bare_typo() -> None:
    # short bare typo must still suggest, via leaf-name matching
    assert "aspose.cells" in VOCAB.closest_products("celz")


def test_languages_for_unknown_product_is_empty() -> None:
    assert VOCAB.languages_for("nope") == frozenset()
    assert "nope" not in VOCAB.products


# --- Extract a product/language named inside a free-text query ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("how to create a chart in Aspose.Cells for C#", "aspose.cells"),
        ("render a doc with GroupDocs.Markdown", "groupdocs.markdown"),
        ("use aspose-cells to save a workbook", "aspose.cells"),  # separator form
        ("how to make a chart in cells", "aspose.cells"),  # #13: distinctive bare leaf
        ("I have many words to say about saving", None),  # 'words' is ambiguous → skipped
        ("just save a document somehow", None),
    ],
)
def test_find_product_in_text(text: str, expected: str | None) -> None:
    assert VOCAB.find_product_in_text(text) == expected


def test_find_product_in_text_skips_ambiguous_common_words() -> None:
    # niche products whose leaves are ordinary words must not be extracted from prose
    vocab = Vocabulary(
        by_product={
            "aspose.page": frozenset({"net"}),
            "aspose.note": frozenset({"net"}),
            "aspose.tasks": frozenset({"net"}),
            "aspose.cells": frozenset({"net"}),
        }
    )
    assert vocab.find_product_in_text("save the page to disk") is None
    assert vocab.find_product_in_text("make a note of this") is None
    assert vocab.find_product_in_text("run background tasks now") is None
    assert vocab.find_product_in_text("open a workbook in cells") == "aspose.cells"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("write some C# code", "c#"),
        ("target .NET please", ".net"),
        ("a Java sample", "java"),
        ("in Python", "python"),
        ("with nodejs", "nodejs"),
        ("plain english prose here", None),
    ],
)
def test_find_language_in_text(text: str, expected: str | None) -> None:
    assert VOCAB.find_language_in_text(text) == expected


def test_find_language_respects_word_boundaries() -> None:
    # 'java' inside 'javascript' must not be mistaken for Java
    assert VOCAB.find_language_in_text("a javascript snippet") == "javascript"


@pytest.mark.parametrize(
    ("text", "product", "expected"),
    [
        # product name + language surface + filler all stripped, verb kept
        (
            "how to save a workbook as pdf in Aspose.Cells for C#",
            "aspose.cells",
            "save workbook pdf",
        ),
        ("save a workbook as pdf", "aspose.cells", "save workbook pdf"),
        ("create a pivot table", None, "create pivot table"),
    ],
)
def test_salient_query(text: str, product: str | None, expected: str) -> None:
    assert VOCAB.salient_query(text, product=product) == expected


def test_salient_query_never_empties() -> None:
    # If everything is filler, fall back to the original text rather than "".
    assert VOCAB.salient_query("how to", product=None) == "how to"


# --- Served-language enum for tool schemas ---


def test_all_languages_sorted_union_excludes_unknown() -> None:
    vocab = Vocabulary(
        by_product={
            "aspose.cells": frozenset({"net", "java", "unknown"}),
            "aspose.words": frozenset({"net", "cpp"}),
        }
    )
    assert vocab.all_languages() == ["cpp", "java", "net"]


def test_all_languages_empty_when_nothing_loaded() -> None:
    assert Vocabulary(by_product={}).all_languages() == []


# --- #8: only real aspose.*/groupdocs.* products, never store test fixtures ---


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("aspose.cells", True),
        ("groupdocs.markdown", True),
        ("rest.pg", False),
        ("scale.p0", False),
        ("sem.cut", False),
        ("test.nul", False),
        ("recall.pg", False),
    ],
)
def test_is_real_product(product: str, expected: bool) -> None:
    assert is_real_product(product) is expected
