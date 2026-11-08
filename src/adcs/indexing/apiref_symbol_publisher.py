"""Publish API-reference symbols from canonical staging into the symbol store.

This is the ingestion-side writer for the structured API-reference path
(ADR-011). It reads a canonical staging snapshot and materialises
one :class:`ApiRefSymbol` row per API-reference symbol page, then activates
the snapshot atomically.

Why it reads *both* staging streams:

* ``iter_chunk_records`` carries the clean facet decomposition — StageD
  chunking splits a symbol page into typed chunks (``api_signature``,
  ``api_parameters``, ``api_returns``, ``api_remarks``, ``api_example``),
  which map directly onto the structured columns/payload.
* ``iter_canonical_documents`` carries ``symbol_kind`` (class/method/...),
  the one field that lives on the document and *not* on chunk records. A
  small ``symbol_fqn → kind`` map is built first.

RAM stays bounded: the kind map is one short string per symbol, and facet
aggregation is a streaming group-by on ``source_path`` (chunk records are
emitted sorted by ``source_path``, so all chunks of one page arrive
contiguously). Rows are flushed to the store in batches.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from adcs.indexing.apiref_symbol_store import (
    ApiRefScope,
    ApiRefSymbol,
    ApiRefSymbolStore,
)
from adcs.ingestion.chunking import StageDChunkRecord
from adcs.ingestion.normalized_document import NormalizedDocument
from adcs.ingestion.staging_store import StagingSnapshotTier

_DOC_LOCALE_ALIASES = {"english": "en", "en-gb": "en", "en-us": "en"}
_APIREF = "apiref"
_SYMBOL_DOC_TYPE = "api_reference_symbol"
_NAMESPACE_DOC_TYPE = "api_reference_namespace"


def _normalize_locale(doc_locale: str) -> str:
    key = (doc_locale or "").strip().lower()
    if key in _DOC_LOCALE_ALIASES:
        return _DOC_LOCALE_ALIASES[key]
    if not key or key == "unknown":
        return "en"
    return key


def _leaf_name(member_fqn: str) -> str:
    return member_fqn.rsplit(".", 1)[-1] if member_fqn else member_fqn


def _parent_fqn(member_fqn: str) -> str | None:
    if "." not in member_fqn:
        return None
    return member_fqn.rsplit(".", 1)[0]


def _first_sentence(text: str, *, max_len: int = 280) -> str | None:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    for delimiter in (". ", "\n"):
        idx = cleaned.find(delimiter)
        if 0 < idx <= max_len:
            return cleaned[: idx + (1 if delimiter == ". " else 0)].strip()
    return cleaned[:max_len].strip()


@dataclass(frozen=True, slots=True)
class ApiRefPublishResult:
    """Outcome of publishing one or more apiref repositories."""

    snapshot_id: str
    repos: tuple[str, ...]
    symbols_written: int
    pages_seen: int
    namespaces_skipped: int
    scopes_activated: tuple[ApiRefScope, ...]


class StagingChunkSource(Protocol):
    """Structural view of the staging store used by the publisher.

    :class:`adcs.ingestion.staging_store.FileSystemCanonicalStagingStore`
    satisfies this protocol.
    """

    def iter_canonical_documents(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[NormalizedDocument]: ...

    def iter_chunk_records(
        self,
        *,
        repo_id: str,
        source_kind: str,
        source_revision: str | None = None,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
    ) -> Iterator[StageDChunkRecord]: ...


class ApiRefSymbolPublisher:
    """Aggregate staged apiref chunks into symbol rows and activate them."""

    def __init__(
        self,
        *,
        store: ApiRefSymbolStore,
        staging: StagingChunkSource,
        batch_size: int = 500,
        english_only: bool = True,
    ) -> None:
        self._store = store
        self._staging = staging
        self._batch_size = max(1, batch_size)
        self._english_only = english_only

    def publish(
        self,
        *,
        repo_ids: Sequence[str],
        snapshot_id: str,
        snapshot_tier: StagingSnapshotTier | str = StagingSnapshotTier.PUBLISH,
        activate: bool = True,
    ) -> ApiRefPublishResult:
        symbols_written = 0
        pages_seen = 0
        namespaces_skipped = 0
        scopes_seen: set[ApiRefScope] = set()
        buffer: list[ApiRefSymbol] = []

        def _flush() -> None:
            nonlocal symbols_written
            if buffer:
                symbols_written += self._store.upsert_symbols(buffer)
                buffer.clear()

        for repo_id in repo_ids:
            kind_map = self._build_kind_map(repo_id=repo_id, snapshot_tier=snapshot_tier)
            for page_chunks in self._iter_pages(repo_id=repo_id, snapshot_tier=snapshot_tier):
                pages_seen += 1
                symbol = self._symbol_from_page(
                    page_chunks=page_chunks,
                    snapshot_id=snapshot_id,
                    kind_map=kind_map,
                )
                if symbol is None:
                    if page_chunks[0].doc_type == _NAMESPACE_DOC_TYPE:
                        namespaces_skipped += 1
                    continue
                if self._english_only and symbol.locale != "en":
                    # v1 serves English only. apiref staging is already
                    # English-only via doc_locale_filter; this is a defensive
                    # drop of any non-EN symbol that slips through. Non-EN stays
                    # in staging for a future multilingual release.
                    continue
                scopes_seen.add(
                    ApiRefScope(
                        product=symbol.product,
                        language=symbol.language,
                        version=symbol.version,
                        locale=symbol.locale,
                    )
                )
                buffer.append(symbol)
                if len(buffer) >= self._batch_size:
                    _flush()
        _flush()

        activated: tuple[ApiRefScope, ...] = ()
        if activate:
            for scope in scopes_seen:
                self._store.flip_active_snapshot(scope=scope, snapshot_id=snapshot_id)
            activated = tuple(sorted(scopes_seen, key=_scope_sort_key))

        return ApiRefPublishResult(
            snapshot_id=snapshot_id,
            repos=tuple(repo_ids),
            symbols_written=symbols_written,
            pages_seen=pages_seen,
            namespaces_skipped=namespaces_skipped,
            scopes_activated=activated,
        )

    def _build_kind_map(
        self, *, repo_id: str, snapshot_tier: StagingSnapshotTier | str
    ) -> dict[str, str]:
        kind_map: dict[str, str] = {}
        for document in self._staging.iter_canonical_documents(
            repo_id=repo_id, source_kind=_APIREF, snapshot_tier=snapshot_tier
        ):
            meta = document.document
            if meta.symbol_fqn and meta.symbol_kind:
                kind_map[meta.symbol_fqn] = meta.symbol_kind
        return kind_map

    def _iter_pages(
        self, *, repo_id: str, snapshot_tier: StagingSnapshotTier | str
    ) -> Iterator[list[StageDChunkRecord]]:
        """Yield chunk records grouped by source_path (one apiref page each)."""
        current_path: str | None = None
        group: list[StageDChunkRecord] = []
        for record in self._staging.iter_chunk_records(
            repo_id=repo_id, source_kind=_APIREF, snapshot_tier=snapshot_tier
        ):
            if current_path is not None and record.source_path != current_path:
                if group:
                    yield group
                group = []
            current_path = record.source_path
            group.append(record)
        if group:
            yield group

    def _symbol_from_page(
        self,
        *,
        page_chunks: list[StageDChunkRecord],
        snapshot_id: str,
        kind_map: dict[str, str],
    ) -> ApiRefSymbol | None:
        head = page_chunks[0]
        if head.doc_type != _SYMBOL_DOC_TYPE or not head.symbol_fqn:
            return None
        member_fqn = head.symbol_fqn
        member_name = _leaf_name(member_fqn)
        resolved_kind = kind_map.get(member_fqn) or _kind_from_title(head.title) or "symbol"

        facets: dict[str, list[str]] = {}
        examples: list[str] = []
        for chunk in page_chunks:
            text = chunk.text.strip()
            if not text:
                continue
            if chunk.chunk_type == "api_example":
                examples.append(text)
            else:
                facets.setdefault(chunk.chunk_type, []).append(text)

        # Stage-D chunking groups small pages: a real symbol page usually
        # collapses into ONE chunk — `api_signature` for methods (signature +
        # prose + param table all concatenated) or `api_remarks` for
        # classes/properties. So extract the clean declaration line out of the
        # signature block and treat the remainder as the description, rather
        # than storing the whole blob as the signature.
        sig_block = _join(facets.get("api_signature"))
        sep_parameters = _join(facets.get("api_parameters"))
        sep_returns = _join(facets.get("api_returns"))
        sep_remarks = _join(facets.get("api_remarks"))

        signature: str | None = None
        block_description: str | None = None
        if sig_block:
            signature, block_description = _split_signature_block(sig_block)
        if signature is None:
            # Most legacy pages collapse into a single api_example/api_remarks
            # chunk (not api_signature), so the declaration line never reaches
            # sig_block. It is still present verbatim in the page text
            # (``public class Box : Primitive``, ``public double Height { get; }``);
            # recover just the signature from it, leaving description/summary
            # untouched. Pages with a real api_signature chunk are unaffected.
            # Scan the non-example page text FIRST, and all of it: on
            # Words-style class pages the fenced declaration lands in an
            # api_parameters chunk while api_signature carries the Remarks
            # prose, and the staging iterator does not guarantee which chunk
            # heads the page — while examples hold a name-matching demo usage
            # that would win the scan (demo code stored as the signature).
            # Examples are scanned last, and only for declarations
            # (the usage guard in _scan_declaration_line drops assignments).
            non_example_text = "\n".join(
                text for texts in facets.values() for text in texts
            )
            for candidate_text in (sig_block, non_example_text, head.text, *examples):
                if not candidate_text:
                    continue
                fallback_signature = _scan_declaration_line(
                    candidate_text, name=member_name, kind=resolved_kind
                )
                if fallback_signature:
                    signature = fallback_signature
                    break

        description = sep_remarks or block_description
        summary = (_first_sentence(description) if description else None) or (head.title or None)

        body = _join(
            [text for text in (sig_block, sep_parameters, sep_returns, sep_remarks) if text]
        )

        payload: dict[str, object] = {}
        # Persist the section anchor so get_symbol_doc citations served from the
        # structured store carry canonical_url + section_anchor (non-negotiable
        # citation rule), matching the legacy dense path.
        if head.section_anchor:
            payload["section_anchor"] = head.section_anchor
        if signature:
            payload["signature"] = signature
        if sep_parameters:
            payload["parameters"] = sep_parameters
        if sep_returns:
            payload["returns"] = sep_returns
        if description:
            payload["remarks"] = description
        if examples:
            payload["examples"] = examples
        if body:
            payload["body"] = body

        return ApiRefSymbol(
            snapshot_id=snapshot_id,
            product=head.product_id,
            language=head.programming_language,
            version=head.version,
            locale=_normalize_locale(head.doc_locale),
            kind=resolved_kind,
            member_fqn=member_fqn,
            name=member_name,
            parent_fqn=_parent_fqn(member_fqn),
            signature=signature,
            canonical_url=head.canonical_url,
            is_deprecated=any(chunk.is_deprecated for chunk in page_chunks),
            summary=summary,
            payload=payload,
        )


def _join(texts: list[str] | None) -> str | None:
    if not texts:
        return None
    return "\n\n".join(texts)


# Trailing title word → canonical kind (Aspose apiref convention). Mirrors
# normalized_document._SYMBOL_KIND_ALIASES; used as a fallback when staging
# predates the `symbol_kind` document field (old snapshots), recovering the
# kind from the chunk record's page title (e.g. "Save Method" → method).
_TITLE_KIND_ALIASES = {
    "namespace": "namespace",
    "class": "class",
    "interface": "interface",
    "enum": "enum",
    "enumeration": "enum",
    "struct": "struct",
    "structure": "struct",
    "method": "method",
    "function": "method",
    "constructor": "constructor",
    "property": "property",
    "field": "field",
    "delegate": "delegate",
    "event": "event",
}


def _kind_from_title(title: str | None) -> str | None:
    tokens = (title or "").strip().lower().split()
    if not tokens:
        return None
    return _TITLE_KIND_ALIASES.get(tokens[-1])


_SIGNATURE_MODIFIERS = frozenset(
    {
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "virtual",
        "override",
        "abstract",
        "sealed",
        "async",
        "def",
        "func",
        "fun",
        "class",
        "interface",
        "enum",
        "struct",
        "void",
    }
)


def _split_signature_block(block: str) -> tuple[str | None, str]:
    """Split a merged API block into (declaration line, description remainder).

    The Stage-D chunker concatenates a symbol page's signature, prose, and
    parameter table into one block. The declaration line is the first line
    that either contains a balanced call ``(...)`` or starts with a known
    declaration modifier; everything after it is the description.
    """
    lines = block.splitlines()
    for index, raw in enumerate(lines):
        candidate = raw.strip().rstrip(";")
        if not candidate:
            continue
        lowered = candidate.casefold()
        is_signature = ("(" in candidate and ")" in candidate) or any(
            lowered.startswith(f"{modifier} ") for modifier in _SIGNATURE_MODIFIERS
        )
        if is_signature and not lowered.startswith(_ACCESS_MODIFIERS):
            # ``auto doc = System::MakeObject<...>()`` — a C++ example line at
            # the top of a collapsed block has balanced parens but is usage,
            # not the declaration; let the name/kind-aware scanner decide.
            if _USAGE_LINE_RE.search(candidate):
                break
        if is_signature:
            remainder = "\n".join(lines[index + 1 :]).strip()
            return candidate, remainder
        break
    return None, block.strip()


# Identifier suffix of example/demo classes embedded in code samples — Aspose's
# example repos name them e.g. ``WorkbookMethodSaveWithStreamSaveFormatDemo``.
_DEMO_SUFFIX_RE = re.compile(r"(?:demo|example|sample)s?$", re.IGNORECASE)
# A type declaration: ``public class Box``, ``internal enum E``, ``struct S``.
_TYPE_DECL_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|sealed|abstract|partial|new)\s+)*"
    r"(?:class|interface|enum|struct)\s+([A-Za-z_]\w*)",
    re.IGNORECASE,
)
# The identifier immediately preceding a call/parameter list ``(``.
_CALL_NAME_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")
_SYMBOL_TYPE_KINDS = frozenset({"class", "interface", "enum", "struct"})
_SYMBOL_MEMBER_KINDS = frozenset({"method", "constructor", "property", "field", "event"})


def _classify_declaration(line: str) -> tuple[str | None, str | None]:
    """Parse a declaration line into ``(identifier, category)``.

    ``identifier`` is the declared name; ``category`` is ``"type"`` (class /
    interface / enum / struct) or ``"member"`` (method / constructor / property /
    field / ...). Either is ``None`` when the line cannot be parsed.
    """
    type_match = _TYPE_DECL_RE.match(line)
    if type_match:
        return type_match.group(1), "type"
    call_match = _CALL_NAME_RE.search(line)
    if call_match:
        return call_match.group(1), "member"
    # Property/field: the last bare identifier before a body/initializer.
    head = line.split("{", 1)[0].split("=", 1)[0]
    tokens = re.findall(r"[A-Za-z_]\w*", head)
    if tokens:
        return tokens[-1], "member"
    return None, None


def _scan_declaration_line(
    text: str, *, name: str | None = None, kind: str | None = None
) -> str | None:
    """Find the symbol's *own* declaration line anywhere in a page's text.

    Unlike :func:`_split_signature_block` (which requires the declaration to be
    the first content line), this scans the whole block. Legacy pages collapse
    into one ``api_example`` chunk whose example code declares a demo/example
    *class* (``public class WorkbookMethodSaveWithStreamSaveFormatDemo``) before
    — or instead of — the symbol's real declaration, so a naive
    "first access-modifier line" rule picks the demo class.

    Candidate lines start with an access modifier or contain a balanced
    ``(...)`` call (markdown table/link rows skipped). The symbol's ``name`` and
    ``kind`` disambiguate which candidate is the symbol's own declaration:

    * **Pass 1** returns the line whose declared identifier *is* ``name``,
      preferring a real declaration (access modifier) over a bare usage call.
      The demo class never matches the symbol name, so this defeats it.
    * **Pass 2** is the coverage fallback for declarations that don't textually
      match ``name`` (constructors, indexers, casing quirks): the first line
      that is neither an example/demo artifact (identifier ending in
      ``Demo``/``Example``/``Sample``) nor a ``kind`` contradiction (a *type*
      declaration for a *member* symbol, or vice-versa).

    With no ``name``/``kind`` (back-compat), Pass 1 is skipped and Pass 2 still
    drops example artifacts. HTML entities are unescaped and the trailing Hugo
    heading anchor (`` {#constructor} ``) is stripped.
    """
    name_cf = name.casefold() if name else None
    # (clean_line, has_access_modifier, declared_identifier, category)
    candidates: list[tuple[str, bool, str | None, str | None]] = []
    for raw in text.splitlines():
        candidate = raw.strip().rstrip(";")
        if not candidate or "|" in candidate or "](" in candidate:
            continue  # blank, markdown table row, or markdown link
        has_modifier = candidate.casefold().startswith(_ACCESS_MODIFIERS)
        if not (has_modifier or ("(" in candidate and ")" in candidate)):
            continue
        if not has_modifier and _USAGE_LINE_RE.search(candidate):
            # ``DocumentBuilder builder = new DocumentBuilder(doc)`` is example
            # usage, not a declaration — but its declared-identifier parse
            # matches the symbol name, so without this guard it wins Pass 1
            # whenever the page's real declaration is out of scan reach.
            continue
        clean = _ANCHOR_RE.sub("", html.unescape(candidate).replace("\xa0", " ")).strip()
        identifier, category = _classify_declaration(clean)
        candidates.append((clean, has_modifier, identifier, category))

    if not candidates:
        return None

    if name_cf is not None:
        # Pass 1: the symbol's own declaration; real declaration before bare call.
        for require_modifier in (True, False):
            for clean, has_modifier, identifier, _category in candidates:
                if identifier is None or identifier.casefold() != name_cf:
                    continue
                if require_modifier and not has_modifier:
                    continue
                return clean

    # Pass 2: first line that is not an example artifact or a kind contradiction.
    for clean, _has_modifier, identifier, category in candidates:
        if identifier is not None and _DEMO_SUFFIX_RE.search(identifier):
            continue
        if category == "member" and kind in _SYMBOL_TYPE_KINDS:
            continue
        if category == "type" and kind in _SYMBOL_MEMBER_KINDS:
            continue
        return clean

    return None


_ACCESS_MODIFIERS = ("public ", "protected ", "internal ", "private ")
# Example-usage shapes: an assignment/instantiation is never a declaration.
_USAGE_LINE_RE = re.compile(
    r"=\s*new\s+[A-Za-z_]"          # C#/Java instantiation
    r"|^[A-Za-z_][\w.<>\[\]]*\s+[a-z_]\w*\s*="  # typed local: Document doc = ...
    r"|^[a-z_][\w.]*\s*="            # python/js bare assignment: builder = aw.X(...)
)
_ANCHOR_RE = re.compile(r"\s*\{#[^}]*\}\s*$")


def _scope_sort_key(scope: ApiRefScope) -> tuple[str, str, str, str]:
    return (scope.product, scope.language, scope.version, scope.locale)
