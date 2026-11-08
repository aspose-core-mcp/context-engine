from __future__ import annotations

from adcs.indexing.index_models import LexicalIndexRecord
from adcs.retrieval import FilterResolver, QueryPlannerInput


def _make_lexical_record(*, version: str) -> LexicalIndexRecord:
    return LexicalIndexRecord(
        chunk_id=f"chunk-{version}",
        text="OCR setup guide",
        snapshot_id="snap-00000001",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        version=version,
        source_kind="docs",
        doc_type="guide_step",
        doc_locale="en",
        symbol_fqn=None,
        title="OCR setup guide",
        canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
        section_anchor="#install",
        source_revision="revision-abc123",
        repo_id="aspose.ocr.docs",
        checksum=f"checksum-{version}",
    )


def _make_lexical_record_with_locale(*, version: str, doc_locale: str) -> LexicalIndexRecord:
    return LexicalIndexRecord(
        chunk_id=f"chunk-{version}-{doc_locale}",
        text="OCR setup guide",
        snapshot_id="snap-00000001",
        product_id="aspose.ocr",
        product_family="aspose",
        programming_language="net",
        version=version,
        source_kind="docs",
        doc_type="guide_step",
        doc_locale=doc_locale,
        symbol_fqn=None,
        title="OCR setup guide",
        canonical_url="https://docs.aspose.com/ocr/net/getting-started/",
        section_anchor="#install",
        source_revision="revision-abc123",
        repo_id="aspose.ocr.docs",
        checksum=f"checksum-{version}-{doc_locale}",
    )


def test_filter_resolver_resolves_strict_filters_and_locale_fallback() -> None:
    resolver = FilterResolver()

    filters = resolver.resolve(
        request=QueryPlannerInput(
            query="How do I process OCR pages?",
            product_id=" Aspose OCR ",
            programming_language="C#",
            version="v25.1",
            doc_locale="de-DE",
            strict_version=True,
        )
    )

    assert filters.product_id == "aspose.ocr"
    assert filters.programming_language == "net"
    assert filters.preferred_version == "25.1"
    assert filters.strict_version_value == "25.1"
    assert filters.locale_routing_order == ("de", "en")
    assert [route.doc_locale for route in filters.routes] == ["de", "en"]
    assert [route.version for route in filters.routes] == ["25.1", "25.1"]
    assert filters.debug.strict_version_enforced is True
    assert filters.debug.locale_fallback_to_en_enabled is True


def test_filter_resolver_uses_default_locale_and_soft_version_when_not_strict() -> None:
    resolver = FilterResolver()

    filters = resolver.resolve(
        request=QueryPlannerInput(
            query="install package",
            product_id="aspose.ocr",
            programming_language=".NET",
            version="25.x",
            strict_version=False,
        )
    )

    assert filters.product_id == "aspose.ocr"
    assert filters.programming_language == "net"
    assert filters.preferred_version == "25"
    assert filters.strict_version_value is None
    assert filters.locale_routing_order == ("en",)
    assert [route.version for route in filters.routes] == [None]
    assert filters.debug.locale_fallback_to_en_enabled is False


def test_filter_resolver_strict_mode_blocks_cross_version_leakage() -> None:
    resolver = FilterResolver()
    records = (
        _make_lexical_record(version="25.1"),
        _make_lexical_record(version="24.12"),
    )

    strict_filters = resolver.resolve(
        request=QueryPlannerInput(
            query="ocr setup",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    strict_matches = resolver.filter_records_for_route(
        records=records,
        route=strict_filters.routes[0],
        strict_version=strict_filters.strict_version,
    )
    assert [record.version for record in strict_matches] == ["25.1"]

    non_strict_filters = resolver.resolve(
        request=QueryPlannerInput(
            query="ocr setup",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=False,
        )
    )
    non_strict_matches = resolver.filter_records_for_route(
        records=records,
        route=non_strict_filters.routes[0],
        strict_version=non_strict_filters.strict_version,
    )
    assert [record.version for record in non_strict_matches] == ["25.1", "24.12"]


def test_filter_resolver_treats_unknown_doc_locale_as_default_en_fallback() -> None:
    resolver = FilterResolver()
    records = (
        _make_lexical_record_with_locale(version="25.1", doc_locale="unknown"),
        _make_lexical_record_with_locale(version="25.1", doc_locale="en"),
    )

    filters = resolver.resolve(
        request=QueryPlannerInput(
            query="ocr setup",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    matches = resolver.filter_records_for_route(
        records=records,
        route=filters.routes[0],
        strict_version=filters.strict_version,
    )
    assert sorted(record.doc_locale for record in matches) == ["en", "unknown"]


def test_filter_resolver_unknown_doc_locale_skips_non_default_locale_route() -> None:
    resolver = FilterResolver()
    records = (_make_lexical_record_with_locale(version="25.1", doc_locale="unknown"),)
    filters = resolver.resolve(
        request=QueryPlannerInput(
            query="ocr setup",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="de",
            strict_version=True,
        )
    )
    de_matches = resolver.filter_records_for_route(
        records=records,
        route=filters.routes[0],
        strict_version=filters.strict_version,
    )
    en_matches = resolver.filter_records_for_route(
        records=records,
        route=filters.routes[1],
        strict_version=filters.strict_version,
    )
    assert de_matches == ()
    assert len(en_matches) == 1


def test_filter_resolver_record_locale_alias_english_matches_en_route() -> None:
    resolver = FilterResolver()
    records = (_make_lexical_record_with_locale(version="25.1", doc_locale="english"),)
    filters = resolver.resolve(
        request=QueryPlannerInput(
            query="ocr setup",
            product_id="aspose.ocr",
            programming_language="net",
            version="25.1",
            doc_locale="en",
            strict_version=True,
        )
    )
    matches = resolver.filter_records_for_route(
        records=records,
        route=filters.routes[0],
        strict_version=filters.strict_version,
    )
    assert len(matches) == 1
