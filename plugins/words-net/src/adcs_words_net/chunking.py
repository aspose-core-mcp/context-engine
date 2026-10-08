"""Deterministic Stage-D chunking policy for docs and API reference pages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from adcs_words_net.hugo_parser import HugoCodeBlock, HugoNormalizedPage
from adcs_words_net.normalized_document import (
    ALLOWED_CHUNK_TYPES,
    NormalizedChunk,
    NormalizedCitation,
    NormalizedDocument,
)

_API_TARGET_MIN_TOKENS = 300
_API_TARGET_MAX_TOKENS = 900
_DOCS_TARGET_MAX_TOKENS = 780
_NARRATIVE_OVERLAP_RATIO = 0.12

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")
_TABLE_DELIMITER_RE = re.compile(r"^\s*\|?[\s:\-]+\|[\s:\-|]*$")
_SIGNATURE_HINT_RE = re.compile(
    r"(public|private|protected|internal|static|virtual|override|async|def|func|\w+\s*\(.*\))"
)


@dataclass(frozen=True, slots=True)
class StageDChunkRecord:
    """Stage-D chunk payload with citation-ready retrieval metadata."""

    chunk_id: str
    repo_id: str
    product_id: str
    product_family: str
    programming_language: str
    version: str
    source_kind: str
    doc_locale: str
    doc_type: str
    symbol_fqn: str | None
    title: str
    section_path: tuple[str, ...]
    canonical_url: str
    section_anchor: str
    source_path: str
    source_revision: str
    is_deprecated: bool
    has_code_example: bool
    chunk_type: str
    text: str
    tokens: int
    checksum: str
    executable_snippets: tuple[StageDExecutableSnippet, ...] = ()


@dataclass(frozen=True, slots=True)
class StageDExecutableSnippet:
    """Executable snippet metadata extracted from fenced code blocks."""

    snippet_id: str
    language: str
    code: str
    parent_canonical_url: str
    parent_section_anchor: str
    parent_symbol_fqn: str | None = None


@dataclass(frozen=True, slots=True)
class _SemanticUnit:
    text: str
    section_path: tuple[str, ...]
    section_anchor: str
    chunk_type: str
    is_narrative: bool
    snippet_language: str | None = None


@dataclass(frozen=True, slots=True)
class _CodeSpan:
    start: int
    end: int
    code_block: HugoCodeBlock


class StageDChunkingPolicy:
    """Split canonical normalized documents into deterministic Stage-D chunks."""

    def chunk_document(
        self,
        *,
        page: HugoNormalizedPage,
        normalized_document: NormalizedDocument,
    ) -> tuple[NormalizedDocument, tuple[StageDChunkRecord, ...]]:
        base_chunk = normalized_document.chunks[0]
        is_api = normalized_document.document.source_kind == "apiref"
        semantic_units = _extract_semantic_units(
            page=page,
            doc_type=normalized_document.document.doc_type,
            is_api=is_api,
            base_section_path=base_chunk.section_path,
            base_section_anchor=base_chunk.section_anchor,
        )
        if not semantic_units:
            semantic_units = (
                _SemanticUnit(
                    text=normalized_document.document.title,
                    section_path=base_chunk.section_path,
                    section_anchor=base_chunk.section_anchor,
                    chunk_type=base_chunk.chunk_type,
                    is_narrative=True,
                ),
            )

        grouped_units = _group_units_for_chunks(semantic_units=semantic_units, is_api=is_api)
        records = tuple(
            _to_chunk_record(
                unit_group=unit_group,
                index=index,
                normalized_document=normalized_document,
                is_api=is_api,
                previous_unit_group=grouped_units[index - 1] if index > 0 else None,
            )
            for index, unit_group in enumerate(grouped_units)
        )
        chunked_document = replace(
            normalized_document,
            chunks=tuple(_to_normalized_chunk(record=record) for record in records),
        )
        return chunked_document, records


def _extract_semantic_units(
    *,
    page: HugoNormalizedPage,
    doc_type: str,
    is_api: bool,
    base_section_path: tuple[str, ...],
    base_section_anchor: str,
) -> tuple[_SemanticUnit, ...]:
    lines = page.body_plain.splitlines()
    if not lines:
        return ()

    code_spans = _locate_code_spans(lines=lines, code_blocks=page.code_blocks)
    code_span_by_start = {span.start: span for span in code_spans}
    code_line_indexes = {
        line_index for span in code_spans for line_index in range(span.start, span.end)
    }

    units: list[_SemanticUnit] = []
    idx = 0
    unit_index = 0
    while idx < len(lines):
        if idx in code_span_by_start:
            span = code_span_by_start[idx]
            code_index = len([unit for unit in units if unit.chunk_type == "api_example"]) + 1
            code_text = "\n".join(lines[span.start : span.end]).strip()
            if code_text:
                units.append(
                    _SemanticUnit(
                        text=code_text,
                        section_path=(*base_section_path, f"code-{code_index}"),
                        section_anchor=base_section_anchor,
                        chunk_type="api_example" if is_api else "guide_step",
                        is_narrative=False,
                        snippet_language=span.code_block.language or "unknown",
                    )
                )
            idx = span.end
            continue

        line = lines[idx]
        if not line.strip():
            idx += 1
            continue

        if _is_table_start(lines=lines, line_index=idx, code_line_indexes=code_line_indexes):
            table_end = _consume_table(
                lines=lines,
                line_index=idx,
                code_line_indexes=code_line_indexes,
            )
            unit_index += 1
            table_text = "\n".join(lines[idx:table_end]).strip()
            units.append(
                _SemanticUnit(
                    text=table_text,
                    section_path=(*base_section_path, f"unit-{unit_index}"),
                    section_anchor=base_section_anchor,
                    chunk_type=_resolve_table_chunk_type(table_text=table_text, is_api=is_api),
                    is_narrative=False,
                )
            )
            idx = table_end
            continue

        if is_api and _looks_like_signature_start(line):
            signature_end = _consume_signature(lines=lines, line_index=idx)
            unit_index += 1
            signature_text = "\n".join(lines[idx:signature_end]).strip()
            units.append(
                _SemanticUnit(
                    text=signature_text,
                    section_path=(*base_section_path, f"unit-{unit_index}"),
                    section_anchor=base_section_anchor,
                    chunk_type="api_signature",
                    is_narrative=False,
                )
            )
            idx = signature_end
            continue

        paragraph_end = _consume_paragraph(
            lines=lines,
            line_index=idx,
            is_api=is_api,
            code_line_indexes=code_line_indexes,
        )
        paragraph_text = "\n".join(lines[idx:paragraph_end]).strip()
        if paragraph_text:
            unit_index += 1
            units.append(
                _SemanticUnit(
                    text=paragraph_text,
                    section_path=(*base_section_path, f"unit-{unit_index}"),
                    section_anchor=base_section_anchor,
                    chunk_type=_resolve_narrative_chunk_type(
                        text=paragraph_text,
                        doc_type=doc_type,
                        is_api=is_api,
                    ),
                    is_narrative=True,
                )
            )
        idx = paragraph_end

    return tuple(units)


def _group_units_for_chunks(
    *,
    semantic_units: tuple[_SemanticUnit, ...],
    is_api: bool,
) -> tuple[tuple[_SemanticUnit, ...], ...]:
    min_tokens = _API_TARGET_MIN_TOKENS if is_api else 0
    max_tokens = _API_TARGET_MAX_TOKENS if is_api else _DOCS_TARGET_MAX_TOKENS
    groups: list[list[_SemanticUnit]] = []
    current: list[_SemanticUnit] = []
    current_tokens = 0

    for unit in semantic_units:
        unit_tokens = _estimate_tokens(unit.text)
        if current and current_tokens >= min_tokens and current_tokens + unit_tokens > max_tokens:
            groups.append(current)
            current = []
            current_tokens = 0

        if not current and unit_tokens > max_tokens:
            groups.append([unit])
            continue

        current.append(unit)
        current_tokens += unit_tokens

    if current:
        if (
            is_api
            and groups
            and current_tokens < _API_TARGET_MIN_TOKENS
            and _group_tokens(groups[-1]) + current_tokens <= _API_TARGET_MAX_TOKENS
        ):
            groups[-1].extend(current)
        else:
            groups.append(current)

    return tuple(tuple(group) for group in groups)


def _to_chunk_record(
    *,
    unit_group: tuple[_SemanticUnit, ...],
    index: int,
    normalized_document: NormalizedDocument,
    is_api: bool,
    previous_unit_group: tuple[_SemanticUnit, ...] | None,
) -> StageDChunkRecord:
    document = normalized_document.document
    text = "\n\n".join(unit.text for unit in unit_group if unit.text.strip()).strip()
    if (
        not is_api
        and previous_unit_group is not None
        and previous_unit_group[-1].is_narrative
        and unit_group[0].is_narrative
    ):
        overlap_prefix = _overlap_prefix_from_previous(previous_group=previous_unit_group)
        if overlap_prefix:
            text = f"{overlap_prefix}\n\n{text}"

    chunk_type = _resolve_group_chunk_type(unit_group=unit_group, is_api=is_api)
    if chunk_type not in ALLOWED_CHUNK_TYPES:
        chunk_type = "api_remarks" if is_api else "guide_step"

    tokens = _estimate_tokens(text)
    checksum = _sha256(
        "\n".join(
            (
                document.repo_id,
                document.source_path,
                str(index),
                chunk_type,
                text,
            )
        )
    )
    chunk_id = _sha256(f"{document.repo_id}|{document.source_path}|{index}|{checksum}")[:24]
    has_code_example = any(unit.chunk_type == "api_example" for unit in unit_group)
    section_path = unit_group[0].section_path
    section_anchor = unit_group[0].section_anchor
    parent_section_anchor = normalized_document.chunks[0].section_anchor
    executable_snippets = _build_executable_snippets(
        unit_group=unit_group,
        chunk_index=index,
        canonical_url=document.canonical_url,
        source_path=document.source_path,
        repo_id=document.repo_id,
        parent_section_anchor=parent_section_anchor,
        parent_symbol_fqn=document.symbol_fqn,
    )
    return StageDChunkRecord(
        chunk_id=chunk_id,
        repo_id=document.repo_id,
        product_id=document.product_id,
        product_family=document.product_family,
        programming_language=document.programming_language,
        version=document.version,
        source_kind=document.source_kind,
        doc_locale=document.doc_locale,
        doc_type=document.doc_type,
        symbol_fqn=document.symbol_fqn,
        title=document.title,
        section_path=section_path,
        canonical_url=document.canonical_url,
        section_anchor=section_anchor,
        source_path=document.source_path,
        source_revision=document.source_revision,
        is_deprecated=_is_deprecated_metadata(normalized_document),
        has_code_example=has_code_example,
        chunk_type=chunk_type,
        text=text,
        tokens=tokens,
        checksum=checksum,
        executable_snippets=executable_snippets,
    )


def _to_normalized_chunk(*, record: StageDChunkRecord) -> NormalizedChunk:
    citation = NormalizedCitation(
        canonical_url=record.canonical_url,
        source_path=record.source_path,
        title=record.title,
        section_anchor=record.section_anchor,
    )
    return NormalizedChunk(
        chunk_key=record.chunk_id,
        section_path=record.section_path,
        section_anchor=record.section_anchor,
        chunk_type=record.chunk_type,
        text=record.text,
        citations=(citation,),
        title=record.title,
        canonical_url=record.canonical_url,
    )


def _locate_code_spans(
    *,
    lines: list[str],
    code_blocks: tuple[HugoCodeBlock, ...],
) -> tuple[_CodeSpan, ...]:
    normalized_lines = [line.rstrip() for line in lines]
    spans: list[_CodeSpan] = []
    search_start = 0
    for code_block in code_blocks:
        code_lines = [line.rstrip() for line in code_block.code.splitlines()]
        if not code_lines:
            continue
        start_index = _find_subsequence(
            lines=normalized_lines,
            target=code_lines,
            search_start=search_start,
        )
        if start_index is None:
            continue
        end_index = start_index + len(code_lines)
        spans.append(_CodeSpan(start=start_index, end=end_index, code_block=code_block))
        search_start = end_index
    return tuple(spans)


def _find_subsequence(
    *,
    lines: list[str],
    target: list[str],
    search_start: int,
) -> int | None:
    if not target:
        return None
    max_start = len(lines) - len(target)
    for start in range(search_start, max_start + 1):
        if lines[start : start + len(target)] == target:
            return start
    return None


def _is_table_start(
    *,
    lines: list[str],
    line_index: int,
    code_line_indexes: set[int],
) -> bool:
    if line_index in code_line_indexes or line_index + 1 >= len(lines):
        return False
    header = lines[line_index].strip()
    divider = lines[line_index + 1].strip()
    return "|" in header and bool(_TABLE_DELIMITER_RE.match(divider))


def _consume_table(*, lines: list[str], line_index: int, code_line_indexes: set[int]) -> int:
    idx = line_index + 2
    while idx < len(lines):
        if idx in code_line_indexes:
            break
        stripped = lines[idx].strip()
        if not stripped or "|" not in stripped:
            break
        idx += 1
    return idx


def _looks_like_signature_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "|" in stripped or stripped.startswith(("-", "*", "+")):
        return False
    if "(" not in stripped:
        return False
    return bool(_SIGNATURE_HINT_RE.search(stripped))


def _consume_signature(*, lines: list[str], line_index: int) -> int:
    idx = line_index
    balance = 0
    consumed_any = False
    while idx < len(lines):
        stripped = lines[idx].strip()
        if idx > line_index and (not stripped or _is_table_like_row(stripped)):
            break
        balance += stripped.count("(") - stripped.count(")")
        consumed_any = True
        idx += 1
        if consumed_any and balance <= 0 and ")" in stripped:
            break
    return idx


def _is_table_like_row(line: str) -> bool:
    return "|" in line and bool(_TABLE_DELIMITER_RE.match(line))


def _consume_paragraph(
    *,
    lines: list[str],
    line_index: int,
    is_api: bool,
    code_line_indexes: set[int],
) -> int:
    idx = line_index
    while idx < len(lines):
        if idx in code_line_indexes:
            break
        stripped = lines[idx].strip()
        if not stripped:
            break
        if idx != line_index and _is_table_start(
            lines=lines,
            line_index=idx,
            code_line_indexes=code_line_indexes,
        ):
            break
        if idx != line_index and is_api and _looks_like_signature_start(lines[idx]):
            break
        idx += 1
    return idx


def _resolve_table_chunk_type(*, table_text: str, is_api: bool) -> str:
    lowered = table_text.lower()
    if is_api and ("parameter" in lowered or ("name" in lowered and "type" in lowered)):
        return "api_parameters"
    return "table_block"


def _resolve_narrative_chunk_type(*, text: str, doc_type: str, is_api: bool) -> str:
    lowered = text.lower()
    if is_api:
        if "return" in lowered:
            return "api_returns"
        return "api_remarks"
    if doc_type == "release_note":
        return "release_note"
    if doc_type == "index_overview":
        return "guide_overview"
    return "guide_step"


def _resolve_group_chunk_type(*, unit_group: tuple[_SemanticUnit, ...], is_api: bool) -> str:
    group_types = {unit.chunk_type for unit in unit_group}
    if is_api:
        for candidate in (
            "api_signature",
            "api_parameters",
            "api_returns",
            "api_example",
            "api_remarks",
            "table_block",
        ):
            if candidate in group_types:
                return candidate
        return "api_remarks"
    if "release_note" in group_types:
        return "release_note"
    if "guide_overview" in group_types:
        return "guide_overview"
    if "table_block" in group_types:
        return "table_block"
    return "guide_step"


def _overlap_prefix_from_previous(*, previous_group: tuple[_SemanticUnit, ...]) -> str:
    previous_narrative_units = [unit for unit in previous_group if unit.is_narrative]
    if not previous_narrative_units:
        return ""
    tokens = _tokenize(previous_narrative_units[-1].text)
    if not tokens:
        return ""
    overlap_size = max(1, int(len(tokens) * _NARRATIVE_OVERLAP_RATIO))
    return " ".join(tokens[-overlap_size:])


def _group_tokens(group: list[_SemanticUnit]) -> int:
    return sum(_estimate_tokens(unit.text) for unit in group)


def _estimate_tokens(text: str) -> int:
    return len(_tokenize(text))


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_deprecated_metadata(normalized_document: NormalizedDocument) -> bool:
    title = normalized_document.document.title.lower()
    return "[deprecated]" in title or title.startswith("deprecated ")


def _build_executable_snippets(
    *,
    unit_group: tuple[_SemanticUnit, ...],
    chunk_index: int,
    canonical_url: str,
    source_path: str,
    repo_id: str,
    parent_section_anchor: str,
    parent_symbol_fqn: str | None,
) -> tuple[StageDExecutableSnippet, ...]:
    snippets: list[StageDExecutableSnippet] = []
    snippet_ordinal = 0
    for unit in unit_group:
        if unit.snippet_language is None:
            continue
        snippet_ordinal += 1
        snippet_id = _sha256(
            "|".join(
                (
                    repo_id,
                    source_path,
                    str(chunk_index),
                    unit.section_anchor,
                    str(snippet_ordinal),
                    unit.snippet_language,
                    unit.text,
                )
            )
        )[:24]
        snippets.append(
            StageDExecutableSnippet(
                snippet_id=snippet_id,
                language=unit.snippet_language,
                code=unit.text,
                parent_canonical_url=canonical_url,
                parent_section_anchor=parent_section_anchor,
                parent_symbol_fqn=parent_symbol_fqn,
            )
        )
    return tuple(snippets)
