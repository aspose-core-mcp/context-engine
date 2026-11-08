"""resolve_product must not misroute bare product tokens.

A black-box test showed that every bare product word without a vendor prefix
(``ocr``, ``pdf``, ``words``, ``barcode``) resolved to the SAME wrong product
``groupdocs.watermark`` at confidence 0.25 with no candidates: no tier matched,
all products tied at the 0.25 floor, and the ``max((score, product_id))``
tiebreak then picked the alphabetically-last product_id. ``ocr`` is the MVP
product — sending it to watermark is the worst case. These tests pin the
correct behaviour: the distinctive product segment resolves
its product, a genuine no-match returns ``unknown`` (never a constant wrong
product), and weak matches expose ranked candidates.
"""

from __future__ import annotations

from dataclasses import dataclass

from adcs.api.public_docs_query import PublicQueryService, _product_match_score


@dataclass(frozen=True)
class _Repo:
    product_id: str
    product_family: str


class _FakeRegistry:
    def __init__(self, products: list[tuple[str, str]]) -> None:
        self._repos = [_Repo(pid, fam) for pid, fam in products]

    def list_repositories(self) -> list[_Repo]:
        return list(self._repos)


_PRODUCTS = [
    ("aspose.ocr", "aspose"),
    ("aspose.pdf", "aspose"),
    ("aspose.words", "aspose"),
    ("aspose.barcode", "aspose"),
    ("aspose.cells", "aspose"),
    ("groupdocs.watermark", "groupdocs"),
    ("groupdocs.conversion", "groupdocs"),
    ("groupdocs.signature", "groupdocs"),
]


def _service() -> PublicQueryService:
    svc = PublicQueryService.__new__(PublicQueryService)
    svc._source_registry_service = _FakeRegistry(_PRODUCTS)  # type: ignore[attr-defined]
    return svc


# --- scoring: the distinctive product segment must score above the floor -----

def test_distinctive_segment_scores_above_family_floor() -> None:
    # "ocr" is the distinctive segment of aspose.ocr; it must beat the 0.25 floor.
    hit = _product_match_score(query="ocr", product_id="aspose.ocr", product_family="aspose")
    miss = _product_match_score(query="ocr", product_id="aspose.pdf", product_family="aspose")
    assert hit > miss
    assert hit >= 0.6
    assert miss == 0.25


def test_full_prefixed_match_still_scores_highest() -> None:
    # A vendor-prefixed query must not regress below the distinctive-only match.
    full = _product_match_score(
        query="aspose ocr", product_id="aspose.ocr", product_family="aspose"
    )
    distinctive = _product_match_score(
        query="ocr", product_id="aspose.ocr", product_family="aspose"
    )
    assert full >= distinctive
    assert full >= 0.85


# --- resolution: bare tokens land on the right product ----------------------

def test_bare_ocr_resolves_to_aspose_ocr() -> None:
    r = _service().resolve_product(query="ocr")
    assert r.product_id == "aspose.ocr"


def test_bare_pdf_and_words_resolve_to_their_products() -> None:
    assert _service().resolve_product(query="pdf").product_id == "aspose.pdf"
    assert _service().resolve_product(query="words").product_id == "aspose.words"


def test_vendor_prefixed_query_still_resolves() -> None:
    r = _service().resolve_product(query="aspose ocr")
    assert r.product_id == "aspose.ocr"
    assert r.confidence >= 0.85


def test_genuine_no_match_returns_unknown_not_a_constant_product() -> None:
    # The old bug: "banana" -> groupdocs.watermark. A true no-match must never
    # return a definitive wrong product; it returns the unknown sentinel.
    r = _service().resolve_product(query="banana")
    assert r.product_id == "unknown"
    assert r.confidence < 0.35


def test_no_match_never_silently_picks_alphabetical_max() -> None:
    for query in ("banana", "zzz nonsense", "quantum flux"):
        assert _service().resolve_product(query=query).product_id != "groupdocs.watermark"


# --- candidates surface alternatives on a weak/ambiguous match --------------

def test_weak_match_exposes_ranked_candidates() -> None:
    r = _service().resolve_product(query="ocr")
    assert hasattr(r, "candidates")
    ids = [c.product_id for c in r.candidates]
    assert "aspose.ocr" in ids
    # candidates are ranked by descending confidence
    confs = [c.confidence for c in r.candidates]
    assert confs == sorted(confs, reverse=True)
