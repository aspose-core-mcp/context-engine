"""Repair legacy apiref staging identity from canonical_url.

The apiref staging produced by the original ingestion has broken symbol
identity: aspose repos carry a locale/language-polluted ``symbol_fqn``
(``Aspose.Words.English.Cpp.Aspose.words.ai``) and groupdocs repos carry none
at all (the old derivation was aspose-only), so every page is tagged
``api_reference_namespace``.

The ``canonical_url`` is clean and consistent for every product
(``/<lang>/<namespace>/<type>/<member>/``), so this module rewrites each chunk
record's ``symbol_fqn`` (and ``doc_type``) from the URL and lets the unchanged
:class:`~adcs.indexing.apiref_symbol_publisher.ApiRefSymbolPublisher` build
correct rows. The derived FQN is lowercase (the URL path is lowercase);
lookups are normalised to lowercase accordingly (see ApiRefSymbolService).

This is a load-time shim for the existing corpus; freshly ingested staging
(with a fixed converter) carries a clean ``symbol_fqn`` and needs no wrapper.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import NormalizedDocument
from adcs.ingestion.staging_store import StagingSnapshotTier

# Known apiref programming-language URL segments (the per-language doc trees in
# source-repo-apiref/<Product>/<locale>/<lang>/...). The canonical_url path is
# ``/<lang>/<ns>/...`` or ``/<locale>/<lang>/<ns>/...`` depending on the source
# layout, so the language is whichever segment matches one of these tokens.
_PROGRAMMING_LANGUAGES = frozenset(
    {
        "net",
        "java",
        "cpp",
        "php",
        "python",
        "python-net",
        "python-java",
        "python-cpp",
        "go-cpp",
        "nodejs",
        "nodejs-net",
        "nodejs-cpp",
        "nodejs-java",
        "javascript-cpp",
        "android",
        "androidjava",
        "android-java",
        "reporting-services",
    }
)


def derive_member_fqn_from_url(canonical_url: str | None) -> str | None:
    """Derive a clean dotted member FQN from an apiref canonical_url.

    The path after the host is ``<lang>/<namespace>/<sym...>``; the namespace
    is the first segment containing a dot. Everything from the namespace
    onward is the FQN (lowercase). Returns None for root/language-only pages
    (no namespace segment) — those are not symbols.
    """
    if not canonical_url:
        return None
    after_scheme = canonical_url.split("://", 1)[-1]
    segments = [s for s in after_scheme.split("/")[1:] if s]  # drop host
    for index, segment in enumerate(segments):
        if "." in segment:  # the namespace segment (e.g. aspose.words, groupdocs.markdown)
            return ".".join(segments[index:]).lower()
    return None


def derive_flat_member_fqn(
    canonical_url: str | None,
    *,
    product_id: str | None,
    programming_language: str | None,
    doc_locale: str | None,
) -> str | None:
    """FQN for flat apiref URLs that carry no namespace segment.

    The cpp-bridge language trees (``go-cpp``, ``cpp``, ``nodejs``, ...) expose
    members directly under the language, e.g.
    ``/go-cpp/workbook/getdatasorter/`` — there is no ``aspose.cells``-style
    namespace segment, so :func:`derive_member_fqn_from_url` returns None and
    the (locale/language-polluted) staged ``symbol_fqn`` would otherwise leak
    through. Here the product is the namespace and the leading locale/language
    segments are dropped, yielding ``aspose.cells.workbook.getdatasorter``.
    Returns None for language-root pages (nothing left after the drop).
    """
    if not canonical_url or not product_id:
        return None
    after_scheme = canonical_url.split("://", 1)[-1]
    segments = [s for s in after_scheme.split("/")[1:] if s]  # drop host
    skip = {
        token
        for token in (
            (doc_locale or "").lower(),
            (programming_language or "").lower(),
            "english",
            "en",
        )
        if token
    }
    members = [s for s in segments if s.lower() not in skip]
    if not members:
        return None
    return ".".join((product_id, *members)).lower()


def derive_programming_language_from_url(canonical_url: str | None) -> str | None:
    """Recover the apiref programming language from a canonical_url.

    The path carries the language as a dedicated segment (``/net/…`` or
    ``/english/net/…``). Returns the first segment matching a known
    programming-language token, or None when the URL has none (root/locale-only
    pages) — leaving the record's existing ``programming_language`` untouched.

    This repairs the corpus that was staged before ``layout_detection`` was
    populated for these repos, where every page defaulted to ``unknown``.
    """
    if not canonical_url:
        return None
    after_scheme = canonical_url.split("://", 1)[-1]
    segments = [s for s in after_scheme.split("/")[1:] if s]  # drop host
    for segment in segments:
        token = segment.lower()
        if token in _PROGRAMMING_LANGUAGES:
            return token
    return None


class CanonicalUrlRewritingStaging:
    """Staging wrapper that repairs apiref symbol_fqn/doc_type from canonical_url.

    Satisfies the publisher's ``StagingChunkSource`` protocol. Canonical
    documents pass through unchanged (the publisher only reads ``symbol_kind``
    from them, which the title fallback recovers); chunk records get a
    URL-derived ``symbol_fqn`` and ``doc_type=api_reference_symbol`` so the
    publisher materialises them as symbols. Records whose URL has no namespace
    segment (root/language pages) are left untouched and skipped downstream.
    """

    _SYMBOL_DOC_TYPE = "api_reference_symbol"

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def iter_canonical_documents(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]:
        for document in self._inner.iter_canonical_documents(  # type: ignore[attr-defined]
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=snapshot_tier,
        ):
            meta = document.document
            fqn = derive_member_fqn_from_url(meta.canonical_url)
            if fqn is None:
                fqn = derive_flat_member_fqn(
                    meta.canonical_url,
                    product_id=meta.product_id,
                    programming_language=meta.programming_language,
                    doc_locale=meta.doc_locale,
                )
            language = derive_programming_language_from_url(meta.canonical_url)
            updates: dict[str, object] = {}
            if fqn is not None:
                updates["symbol_fqn"] = fqn
                updates["doc_type"] = self._SYMBOL_DOC_TYPE
            if language is not None and language != meta.programming_language:
                updates["programming_language"] = language
            # The publisher keys its kind_map by the canonical document fqn, then
            # looks it up by the (repaired) chunk-record fqn. Repair the document
            # fqn identically so the two agree — otherwise a locale/repo-polluted
            # document fqn misses every lookup and silently drops the fine-grained
            # symbol_kind to generic "symbol".
            yield replace(document, document=replace(meta, **updates)) if updates else document

    def iter_chunk_records(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]:
        for record in self._inner.iter_chunk_records(  # type: ignore[attr-defined]
            repo_id=repo_id,
            source_kind=source_kind,
            source_revision=source_revision,
            snapshot_tier=snapshot_tier,
        ):
            fqn = derive_member_fqn_from_url(record.canonical_url)
            if fqn is None:
                fqn = derive_flat_member_fqn(
                    record.canonical_url,
                    product_id=record.product_id,
                    programming_language=record.programming_language,
                    doc_locale=record.doc_locale,
                )
            language = derive_programming_language_from_url(record.canonical_url)
            updates: dict[str, object] = {}
            if fqn is not None:
                updates["symbol_fqn"] = fqn
                updates["doc_type"] = self._SYMBOL_DOC_TYPE
            if language is not None and language != record.programming_language:
                updates["programming_language"] = language
            yield replace(record, **updates) if updates else record


__all__ = [
    "CanonicalUrlRewritingStaging",
    "derive_flat_member_fqn",
    "derive_member_fqn_from_url",
    "derive_programming_language_from_url",
]
