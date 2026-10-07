"""Canonical normalized document model, converter, and deterministic validation."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from adcs_words_net.dimension_vocabulary import classify_segment
from adcs_words_net.hugo_parser import HugoNormalizedPage

NORMALIZED_DOCUMENT_SCHEMA: Final[str] = "adcs.normalized_document.v1"
ALLOWED_CHUNK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "api_signature",
        "api_parameters",
        "api_returns",
        "api_remarks",
        "api_example",
        "guide_step",
        "guide_overview",
        "release_note",
        "table_block",
    }
)

_ALLOWED_WARNING_SEVERITIES: Final[frozenset[str]] = frozenset({"info", "warning", "error"})
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class NormalizedCitation:
    canonical_url: str
    source_path: str
    title: str
    section_anchor: str


@dataclass(frozen=True, slots=True)
class NormalizedChunk:
    chunk_key: str
    section_path: tuple[str, ...]
    section_anchor: str
    chunk_type: str
    text: str
    citations: tuple[NormalizedCitation, ...]
    title: str
    canonical_url: str


@dataclass(frozen=True, slots=True)
class NormalizedWarning:
    code: str
    message: str
    source_path: str
    line_hint: int | None
    severity: str


@dataclass(frozen=True, slots=True)
class NormalizedDocumentMetadata:
    repo_id: str
    product_id: str
    product_family: str
    source_kind: str
    programming_language: str
    doc_locale: str
    version: str
    title: str
    doc_type: str
    canonical_url: str
    source_path: str
    source_revision: str
    symbol_fqn: str | None = None
    # Fine-grained API-reference symbol kind (class/method/property/...).
    # None for non-apiref docs. It is the one field extracted specifically for
    # the Postgres `symbols` table; everything else maps/derives from existing
    # fields.
    symbol_kind: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    schema: str
    document: NormalizedDocumentMetadata
    chunks: tuple[NormalizedChunk, ...]
    warnings: tuple[NormalizedWarning, ...]


class NormalizedDocumentValidationError(ValueError):
    """Raised when canonical normalized document validation fails."""

    def __init__(self, *, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class NormalizedDocumentValidator:
    """Deterministic schema and invariant validator for normalized documents."""

    def validate(
        self,
        normalized_document: NormalizedDocument,
        *,
        input_source_path: str | None = None,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if normalized_document.schema != NORMALIZED_DOCUMENT_SCHEMA:
            errors.append("schema must be `adcs.normalized_document.v1`.")

        document = normalized_document.document
        document_required_fields = {
            "repo_id": document.repo_id,
            "product_id": document.product_id,
            "product_family": document.product_family,
            "source_kind": document.source_kind,
            "programming_language": document.programming_language,
            "doc_locale": document.doc_locale,
            "version": document.version,
            "title": document.title,
            "doc_type": document.doc_type,
            "canonical_url": document.canonical_url,
            "source_path": document.source_path,
            "source_revision": document.source_revision,
        }
        for field_name in sorted(document_required_fields):
            if not _is_non_empty(document_required_fields[field_name]):
                errors.append(f"document.{field_name} is required and must be non-empty.")

        if document.doc_type == "api_reference_symbol" and not _is_non_empty(document.symbol_fqn):
            errors.append(
                "document.symbol_fqn is required when document.doc_type=api_reference_symbol."
            )

        if input_source_path is not None and document.source_path != input_source_path:
            errors.append("document.source_path must exactly match input source path.")

        if not normalized_document.chunks:
            errors.append("chunks must contain at least one chunk.")
        for chunk_index, chunk in enumerate(normalized_document.chunks):
            chunk_path = f"chunks[{chunk_index}]"
            if not _is_non_empty(chunk.chunk_key):
                errors.append(f"{chunk_path}.chunk_key is required and must be non-empty.")
            if not chunk.section_path or any(
                not _is_non_empty(part) for part in chunk.section_path
            ):
                errors.append(f"{chunk_path}.section_path must be a non-empty path.")
            if not _is_non_empty(chunk.section_anchor):
                errors.append(f"{chunk_path}.section_anchor is required and must be non-empty.")
            if chunk.chunk_type not in ALLOWED_CHUNK_TYPES:
                errors.append(
                    f"{chunk_path}.chunk_type `{chunk.chunk_type}` "
                    "is not in allowed chunk_type set."
                )
            if not _is_non_empty(chunk.text):
                errors.append(f"{chunk_path}.text is required and must be non-empty.")
            if not _is_non_empty(chunk.title):
                errors.append(f"{chunk_path}.title is required and must be non-empty.")
            if not _is_non_empty(chunk.canonical_url):
                errors.append(f"{chunk_path}.canonical_url is required and must be non-empty.")
            if not chunk.citations:
                errors.append(f"{chunk_path}.citations must contain at least one citation.")
            for citation_index, citation in enumerate(chunk.citations):
                citation_path = f"{chunk_path}.citations[{citation_index}]"
                if not _is_non_empty(citation.canonical_url):
                    errors.append(
                        f"{citation_path}.canonical_url is required and must be non-empty."
                    )
                if not _is_non_empty(citation.source_path):
                    errors.append(f"{citation_path}.source_path is required and must be non-empty.")
                if input_source_path is not None and citation.source_path != input_source_path:
                    errors.append(
                        f"{citation_path}.source_path must exactly match input source path."
                    )

        for warning_index, warning in enumerate(normalized_document.warnings):
            warning_path = f"warnings[{warning_index}]"
            if not _is_non_empty(warning.code):
                errors.append(f"{warning_path}.code is required and must be non-empty.")
            if not _is_non_empty(warning.message):
                errors.append(f"{warning_path}.message is required and must be non-empty.")
            if not _is_non_empty(warning.source_path):
                errors.append(f"{warning_path}.source_path is required and must be non-empty.")
            if warning.severity not in _ALLOWED_WARNING_SEVERITIES:
                allowed_severities = _sorted_tuple(_ALLOWED_WARNING_SEVERITIES)
                errors.append(f"{warning_path}.severity must be one of {allowed_severities}.")

        return tuple(errors)

    def validate_or_raise(
        self,
        normalized_document: NormalizedDocument,
        *,
        input_source_path: str | None = None,
    ) -> None:
        errors = self.validate(normalized_document, input_source_path=input_source_path)
        if errors:
            raise NormalizedDocumentValidationError(errors=errors)


class HugoToNormalizedDocumentConverter:
    """Convert page-level Hugo normalization output into canonical schema objects."""

    def __init__(self, *, canonical_base_url: str = "https://docs.aspose.com") -> None:
        self._canonical_base_url = canonical_base_url.rstrip("/")

    def convert_page(
        self,
        *,
        page: HugoNormalizedPage,
        source_revision: str,
    ) -> NormalizedDocument:
        canonical_url = _resolve_canonical_url(
            metadata=page.metadata,
            source_path=page.source_path,
            canonical_base_url=self._canonical_base_url,
        )
        symbol_fqn = _resolve_symbol_fqn(page)
        doc_type = _resolve_doc_type(page=page, symbol_fqn=symbol_fqn)
        symbol_kind = _resolve_symbol_kind(page=page, doc_type=doc_type)
        section_anchor = _resolve_section_anchor(page)
        section_path = _resolve_section_path(page)

        document_metadata = NormalizedDocumentMetadata(
            repo_id=page.repo_id,
            product_id=_normalize_or_unknown(page.product_id),
            product_family=_normalize_or_unknown(page.product_family),
            source_kind=_normalize_or_unknown(page.source_kind),
            programming_language=_normalize_or_unknown(page.programming_language),
            doc_locale=_normalize_or_unknown(page.doc_locale),
            version=_resolve_version(page.metadata),
            title=page.title.strip() if page.title.strip() else Path(page.source_path).stem,
            doc_type=doc_type,
            canonical_url=canonical_url,
            source_path=page.source_path,
            source_revision=source_revision,
            symbol_fqn=symbol_fqn,
            symbol_kind=symbol_kind,
        )

        base_chunk_type = _resolve_base_chunk_type(doc_type)
        citation = NormalizedCitation(
            canonical_url=canonical_url,
            source_path=page.source_path,
            title=document_metadata.title,
            section_anchor=section_anchor,
        )
        base_chunk = NormalizedChunk(
            chunk_key=f"{page.repo_id}:{page.source_path}:main",
            section_path=section_path,
            section_anchor=section_anchor,
            chunk_type=base_chunk_type,
            text=page.body_plain if page.body_plain else document_metadata.title,
            citations=(citation,),
            title=document_metadata.title,
            canonical_url=canonical_url,
        )

        code_chunks: list[NormalizedChunk] = []
        for index, code_block in enumerate(page.code_blocks):
            code_anchor = f"{section_anchor}-code-{index + 1}"
            code_chunks.append(
                NormalizedChunk(
                    chunk_key=f"{page.repo_id}:{page.source_path}:code:{index}",
                    section_path=(*section_path, f"code-{index + 1}"),
                    section_anchor=code_anchor,
                    chunk_type="api_example"
                    if doc_type.startswith("api_reference")
                    else "guide_step",
                    text=code_block.code if code_block.code else document_metadata.title,
                    citations=(
                        NormalizedCitation(
                            canonical_url=canonical_url,
                            source_path=page.source_path,
                            title=document_metadata.title,
                            section_anchor=code_anchor,
                        ),
                    ),
                    title=document_metadata.title,
                    canonical_url=canonical_url,
                )
            )

        warnings = tuple(
            NormalizedWarning(
                code=warning.code,
                message=warning.message,
                source_path=page.source_path,
                line_hint=warning.line_hint,
                severity=warning.severity,
            )
            for warning in page.parse_warnings
        )

        return NormalizedDocument(
            schema=NORMALIZED_DOCUMENT_SCHEMA,
            document=document_metadata,
            chunks=(base_chunk, *tuple(code_chunks)),
            warnings=warnings,
        )


def resolve_git_submodule_revision(
    *,
    submodule_path: Path,
    git_executable: str = "git",
) -> str:
    """Resolve source revision from git submodule HEAD."""
    completed = subprocess.run(
        [git_executable, "rev-parse", "HEAD"],
        cwd=submodule_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        msg = (
            f"Failed to resolve source revision for `{submodule_path}` "
            f"(exit_code={completed.returncode}): {stderr or 'no stderr output'}"
        )
        raise ValueError(msg)
    revision = completed.stdout.strip()
    if not revision:
        msg = f"Failed to resolve source revision for `{submodule_path}`: empty git SHA."
        raise ValueError(msg)
    return revision


def _resolve_doc_type(*, page: HugoNormalizedPage, symbol_fqn: str | None) -> str:
    if page.source_kind == "apiref":
        if symbol_fqn is not None:
            return "api_reference_symbol"
        return "api_reference_namespace"

    lowered_source_path = page.source_path.lower()
    lowered_title = page.title.lower()
    if "release-note" in lowered_source_path or "release notes" in lowered_title:
        return "release_note"
    if page.is_index_page:
        return "index_overview"
    return "guide"


_CANONICAL_SYMBOL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "namespace",
        "class",
        "interface",
        "enum",
        "struct",
        "method",
        "constructor",
        "property",
        "field",
        "delegate",
        "event",
    }
)

# Maps front-matter values and trailing title words to a canonical kind.
_SYMBOL_KIND_ALIASES: Final[dict[str, str]] = {
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


def _resolve_symbol_kind(*, page: HugoNormalizedPage, doc_type: str) -> str | None:
    """Resolve the fine-grained API symbol kind (class/method/...).

    Returns ``None`` for non-apiref pages. Strategy (most reliable first):
      1. front-matter (``symbol_kind`` / ``kind`` / ``type`` / ``symbol_type``);
      2. trailing keyword of the first symbol heading ('AsposeLLMApi class',
         'Squiggly.Accept method', 'SaveFormat enumeration', ...);
      3. trailing keyword of the title ('Presentation Class', 'Save Method', ...);
      4. namespace doc_type → 'namespace';
      5. fallback 'symbol' (so apiref rows always have a non-null kind).
    """
    if page.source_kind != "apiref":
        return None

    # 1. front-matter
    for key in ("symbol_kind", "kind", "type", "symbol_type"):
        raw = page.metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            mapped = _SYMBOL_KIND_ALIASES.get(raw.strip().lower())
            if mapped is not None:
                return mapped

    # 2. trailing keyword of the first symbol heading. Real Aspose apiref pages
    #    title classes as "Class X" (leading keyword) and members as "X.Y" (no
    #    keyword), so the title suffix is unreliable — but the H2 symbol heading
    #    is consistently "X class" / "X.Y method" / "X enumeration". Plural
    #    section headings ('Methods', 'Properties') don't collide with the
    #    singular kind aliases, so scanning for the first match is safe.
    for heading in page.headings:
        heading_tokens = heading.text.strip().lower().split()
        if heading_tokens:
            mapped = _SYMBOL_KIND_ALIASES.get(heading_tokens[-1])
            if mapped is not None:
                return mapped

    # 3. trailing keyword of the title (legacy Aspose convention / synthetic)
    title_tokens = (page.title or "").strip().lower().split()
    if title_tokens:
        mapped = _SYMBOL_KIND_ALIASES.get(title_tokens[-1])
        if mapped is not None:
            return mapped

    # 4. namespace doc_type
    if doc_type == "api_reference_namespace":
        return "namespace"

    # 5. fallback — apiref symbol of unknown fine-grained kind
    return "symbol"


def _resolve_base_chunk_type(doc_type: str) -> str:
    if doc_type == "release_note":
        return "release_note"
    if doc_type == "index_overview":
        return "guide_overview"
    if doc_type.startswith("api_reference"):
        return "api_remarks"
    return "guide_step"


def _resolve_section_path(page: HugoNormalizedPage) -> tuple[str, ...]:
    if page.headings:
        return tuple(heading.text for heading in page.headings)
    return (page.title,)


def _resolve_section_anchor(page: HugoNormalizedPage) -> str:
    anchor_source = page.headings[0].text if page.headings else page.title
    return _to_anchor(anchor_source)


def _resolve_version(metadata: dict[str, object]) -> str:
    for key in ("version", "api_version", "product_version"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "latest-stable"


def _resolve_symbol_fqn(page: HugoNormalizedPage) -> str | None:
    metadata_symbol = page.metadata.get("symbol_fqn")
    if isinstance(metadata_symbol, str) and metadata_symbol.strip():
        return metadata_symbol.strip()
    if page.source_kind != "apiref":
        return None

    path_without_file = list(Path(page.source_path).parts[:-1])
    namespace_index = next(
        (
            index
            for index, part in enumerate(path_without_file)
            if "." in part and "aspose" in part.lower()
        ),
        None,
    )
    if namespace_index is None:
        return None
    if namespace_index + 1 >= len(path_without_file):
        return None

    namespace = _pascalize_namespace(path_without_file[namespace_index])
    raw_after_ns = path_without_file[namespace_index + 1 :]
    # Strip directory segments that classify as structural (locale /
    # programming_language / version) — they are layout artefacts that appear
    # in the LEADING zone immediately after the dotted-namespace segment.
    # Structural directories never appear once real namespace/class/method
    # tokens start; therefore we only strip while still in the leading run.
    # The moment we encounter the first segment that does NOT classify as
    # structural we stop stripping and keep ALL subsequent segments verbatim,
    # even if their spelling would match a structural classifier (e.g. `node`
    # → Aspose.CAD Node class, `ruby` → Aspose.PDF Ruby property,
    # `id`/`is` → Aspose.HTML DOM properties).
    in_leading_zone = True
    symbol_parts: list[str] = []
    for raw in raw_after_ns:
        pascalized = _pascalize_token(raw)
        if not pascalized:
            continue
        if in_leading_zone and classify_segment(raw) is not None:
            # Still in the leading structural zone — drop this layout segment.
            continue
        # First real API token (or any token once we left the leading zone).
        in_leading_zone = False
        symbol_parts.append(pascalized)
    if not symbol_parts:
        return None
    return ".".join((namespace, *symbol_parts))


def _resolve_canonical_url(
    *,
    metadata: dict[str, object],
    source_path: str,
    canonical_base_url: str,
) -> str:
    metadata_url = metadata.get("url")
    if isinstance(metadata_url, str) and metadata_url.strip():
        normalized_url = metadata_url.strip()
        if normalized_url.startswith(("https://", "http://")):
            return normalized_url
        if normalized_url.startswith("/"):
            return f"{canonical_base_url}{normalized_url}"
        return f"{canonical_base_url}/{normalized_url}"

    relative_parts = list(Path(source_path).parts)
    if len(relative_parts) >= 3:
        relative_parts = relative_parts[2:]
    if relative_parts and relative_parts[-1] == "_index.md":
        relative_parts = relative_parts[:-1]
    elif relative_parts:
        relative_parts[-1] = Path(relative_parts[-1]).stem

    relative_path = "/".join(relative_parts)
    if relative_path:
        return f"{canonical_base_url}/{relative_path}/"
    return f"{canonical_base_url}/"


def _normalize_or_unknown(value: str | None) -> str:
    if value is None:
        return "unknown"
    stripped = value.strip()
    return stripped if stripped else "unknown"


def _to_anchor(value: str) -> str:
    lowered = value.strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    return f"#{slug}" if slug else "#section"


def _pascalize_namespace(value: str) -> str:
    return ".".join(_pascalize_token(part) for part in value.split("."))


def _pascalize_token(value: str) -> str:
    normalized = value.replace("_", "-")
    parts = [part for part in normalized.split("-") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _is_non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sorted_tuple(values: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(values))
