"""Hugo Markdown parser and page-level normalizer for ingestion Stage-A/B bridge."""

from __future__ import annotations

import html
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WARNING_CODE_HTML_EMBED_DETECTED = "HTML_EMBED_DETECTED"
WARNING_CODE_UNSUPPORTED_SHORTCODE = "UNSUPPORTED_HUGO_SHORTCODE"
WARNING_CODE_SHORTCODE_MISMATCH = "SHORTCODE_MISMATCHED_CLOSE"
WARNING_CODE_SHORTCODE_UNCLOSED = "SHORTCODE_UNCLOSED"
WARNING_CODE_UNCLOSED_CODE_FENCE = "UNCLOSED_CODE_FENCE"
WARNING_CODE_YAML_FRONT_MATTER_UNSUPPORTED = "YAML_FRONT_MATTER_UNSUPPORTED_LINE"
WARNING_CODE_FRONT_MATTER_CLOSE_INLINE = "HUGO_FRONT_MATTER_CLOSE_INLINE_CONTENT"
FATAL_CODE_FRONT_MATTER_UNCLOSED = "HUGO_FRONT_MATTER_UNCLOSED"
FATAL_CODE_FRONT_MATTER_TOML_PARSE_ERROR = "HUGO_FRONT_MATTER_TOML_PARSE_ERROR"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SHORTCODE_RE = re.compile(r"{{([<%])\s*(/?)([A-Za-z0-9_-]+)(?:\s+[^{}]*)?\s*([>%])}}")
_SCRIPT_STYLE_START_RE = re.compile(r"<\s*(script|style)\b", re.IGNORECASE)
_SCRIPT_STYLE_END_TEMPLATE = r"</\s*{tag}\s*>"
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_LANGUAGE_TOKEN_RE = re.compile(r"^[a-z0-9#+-]+$")

_SUPPORTED_SHORTCODES = frozenset({"alert", "tabs", "tab"})
_FENCE_LANGUAGE_ALIASES = {
    "c#": "csharp",
    "cs": "csharp",
    "csharp": "csharp",
    "vb": "vb",
    "vbnet": "vb",
    "visual-basic": "vb",
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "c++": "cpp",
    "cpp": "cpp",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
}
_PROGRAMMING_LANGUAGE_SNIPPET_FALLBACKS = {
    "net": "csharp",
    "dotnet": "csharp",
    "python-net": "python",
    "python-java": "python",
    "nodejs-cpp": "javascript",
}


@dataclass(frozen=True, slots=True)
class HugoParseWarning:
    code: str
    message: str
    line_hint: int | None
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class HugoHeading:
    level: int
    text: str
    line_hint: int


@dataclass(frozen=True, slots=True)
class HugoCodeBlock:
    language: str | None
    code: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class HugoNormalizedPage:
    repo_id: str
    source_path: str
    source_kind: str
    product_id: str | None
    product_family: str | None
    programming_language: str | None
    doc_locale: str | None
    title: str
    metadata: dict[str, Any]
    body_plain: str
    headings: tuple[HugoHeading, ...]
    code_blocks: tuple[HugoCodeBlock, ...]
    parse_warnings: tuple[HugoParseWarning, ...]
    is_index_page: bool


class HugoParseFatalError(ValueError):
    """Fatal parse error that should fail Stage-A parse operation."""

    def __init__(self, *, code: str, message: str, line_hint: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.line_hint = line_hint


class HugoMarkdownParser:
    """Parse Hugo markdown files into deterministic page-level normalized models."""

    def parse_document(
        self,
        *,
        repo_id: str,
        source_path: str,
        source_kind: str,
        raw_markdown: str,
        product_id: str | None = None,
        product_family: str | None = None,
        relative_repo_path: str | None = None,
        layout_detection: dict[str, Any] | None = None,
    ) -> HugoNormalizedPage:
        front_matter, body_lines, body_start_line, warnings = self._extract_front_matter(
            raw_markdown
        )
        metadata = self._normalize_metadata(front_matter)
        if source_kind == "apiref":
            metadata = {k: _unescape_prose(v) if isinstance(v, str) else v
                        for k, v in metadata.items()}

        relative_path = relative_repo_path or Path(source_path).name
        doc_locale, programming_language = _infer_path_context(
            relative_repo_path=relative_path,
            layout_detection=layout_detection,
        )

        headings: list[HugoHeading] = []
        code_blocks: list[HugoCodeBlock] = []
        body_plain_lines: list[str] = []

        shortcode_stack: list[tuple[str, int]] = []
        inside_code = False
        code_start_line = 0
        code_language: str | None = None
        code_lines: list[str] = []

        active_html_embed: str | None = None
        for offset, body_line in enumerate(body_lines):
            line_number = body_start_line + offset
            stripped = body_line.strip()

            if active_html_embed is not None:
                end_re = re.compile(
                    _SCRIPT_STYLE_END_TEMPLATE.format(tag=re.escape(active_html_embed)),
                    re.IGNORECASE,
                )
                if end_re.search(body_line):
                    active_html_embed = None
                continue

            if stripped.startswith("```"):
                if inside_code:
                    code_blocks.append(
                        HugoCodeBlock(
                            language=code_language,
                            code="\n".join(code_lines),
                            line_start=code_start_line,
                            line_end=line_number,
                        )
                    )
                    inside_code = False
                    code_start_line = 0
                    code_language = None
                    code_lines = []
                else:
                    inside_code = True
                    code_start_line = line_number
                    fence_info = stripped[3:].strip()
                    code_language = _resolve_snippet_language(
                        fence_info=fence_info if fence_info else None,
                        programming_language=programming_language,
                    )
                    code_lines = []
                continue

            if inside_code:
                if source_kind == "apiref":
                    # Generator artifacts, not general C# escape decoding: regexes,
                    # paths, string escapes and operators must remain executable.
                    body_line = re.sub(r"\\(?=</?summary>)", "", body_line)
                    body_line = re.sub(r"\\(?=\.(?:docx?|pdf|rtf)\b)", "", body_line)
                code_lines.append(body_line)
                body_plain_lines.append(body_line.rstrip())
                continue

            script_or_style_match = _SCRIPT_STYLE_START_RE.search(body_line)
            if script_or_style_match:
                tag_name = script_or_style_match.group(1).lower()
                warnings.append(
                    HugoParseWarning(
                        code=WARNING_CODE_HTML_EMBED_DETECTED,
                        message=f"Inline `<{tag_name}>` embed is not supported in baseline parser.",
                        line_hint=line_number,
                    )
                )
                end_re = re.compile(
                    _SCRIPT_STYLE_END_TEMPLATE.format(tag=re.escape(tag_name)),
                    re.IGNORECASE,
                )
                if end_re.search(body_line) is None:
                    active_html_embed = tag_name
                continue

            line_without_shortcodes = self._strip_shortcodes_and_collect_warnings(
                line=body_line,
                line_number=line_number,
                warnings=warnings,
                shortcode_stack=shortcode_stack,
            )

            if source_kind == "apiref":
                line_without_shortcodes = _unescape_prose(line_without_shortcodes)
            # Remove presentation HTML only outside fenced code (XML examples survive).
            line_without_shortcodes = re.sub(
                r"</?(?:img|div|span|p|br|a|strong|em|ul|ol|li|h[1-6])\b[^>]*>",
                "", line_without_shortcodes, flags=re.IGNORECASE,
            )
            heading_match = _HEADING_RE.match(line_without_shortcodes.strip())
            if heading_match is not None:
                heading_text = heading_match.group(2).strip()
                headings.append(
                    HugoHeading(
                        level=len(heading_match.group(1)),
                        text=heading_text,
                        line_hint=line_number,
                    )
                )
                body_plain_lines.append(re.sub(r"\s*\{#[\w:.-]+\}\s*$", "", heading_text))
                continue

            body_plain_lines.append(line_without_shortcodes.rstrip())

        if inside_code:
            code_blocks.append(
                HugoCodeBlock(
                    language=code_language,
                    code="\n".join(code_lines),
                    line_start=code_start_line,
                    line_end=body_start_line + len(body_lines) - 1,
                )
            )
            warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_UNCLOSED_CODE_FENCE,
                    message="Code fence is not closed before end-of-file.",
                    line_hint=code_start_line,
                )
            )

        for shortcode_name, line_hint in shortcode_stack:
            warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_SHORTCODE_UNCLOSED,
                    message=f"Shortcode `{shortcode_name}` is not closed.",
                    line_hint=line_hint,
                )
            )

        normalized_warnings = tuple(
            sorted(
                warnings,
                key=lambda item: (
                    item.line_hint is None,
                    item.line_hint if item.line_hint is not None else 0,
                    item.code,
                    item.message,
                ),
            )
        )

        title = _derive_title(
            metadata=metadata,
            headings=headings,
            source_path=source_path,
        )

        return HugoNormalizedPage(
            repo_id=repo_id,
            source_path=source_path,
            source_kind=source_kind,
            product_id=product_id,
            product_family=product_family,
            programming_language=programming_language,
            doc_locale=doc_locale,
            title=title,
            metadata=metadata,
            body_plain="\n".join(body_plain_lines).strip(),
            headings=tuple(headings),
            code_blocks=tuple(code_blocks),
            parse_warnings=normalized_warnings,
            is_index_page=Path(relative_path).name == "_index.md",
        )

    def _extract_front_matter(
        self,
        raw_markdown: str,
    ) -> tuple[dict[str, Any], list[str], int, list[HugoParseWarning]]:
        lines = raw_markdown.splitlines()
        if not lines:
            return {}, [], 1, []

        first_line = lines[0].strip()
        if first_line not in {"---", "+++"}:
            return {}, lines, 1, []

        closing = _find_closing_front_matter(lines=lines, delimiter=first_line)
        if closing is None:
            raise HugoParseFatalError(
                code=FATAL_CODE_FRONT_MATTER_UNCLOSED,
                message="Front matter opening delimiter is not closed.",
                line_hint=1,
            )
        closing_index, trailing_body = closing

        front_matter_lines = lines[1:closing_index]
        body_lines = lines[closing_index + 1 :]
        body_start_line = closing_index + 2
        inline_close_warnings: list[HugoParseWarning] = []
        if trailing_body:
            # The closing delimiter was glued to body content on its own line;
            # re-inject that content as the first body line so it is not lost.
            body_lines = [trailing_body, *body_lines]
            body_start_line = closing_index + 1
            inline_close_warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_FRONT_MATTER_CLOSE_INLINE,
                    message=(
                        "Front matter closing delimiter has trailing inline "
                        "content; recovered it as body."
                    ),
                    line_hint=closing_index + 1,
                )
            )
        if first_line == "---":
            metadata, warnings = _parse_yaml_front_matter(front_matter_lines, line_offset=2)
            return metadata, body_lines, body_start_line, [*inline_close_warnings, *warnings]

        try:
            metadata_raw = tomllib.loads("\n".join(front_matter_lines))
        except tomllib.TOMLDecodeError as exc:
            raise HugoParseFatalError(
                code=FATAL_CODE_FRONT_MATTER_TOML_PARSE_ERROR,
                message=f"TOML front matter parse failed: {exc}.",
                line_hint=2,
            ) from exc
        if not isinstance(metadata_raw, dict):
            raise HugoParseFatalError(
                code=FATAL_CODE_FRONT_MATTER_TOML_PARSE_ERROR,
                message="TOML front matter must decode into an object.",
                line_hint=2,
            )
        return metadata_raw, body_lines, body_start_line, inline_close_warnings

    def _normalize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in sorted(metadata):
            normalized[str(key)] = _normalize_metadata_value(metadata[key])
        return normalized

    def _strip_shortcodes_and_collect_warnings(
        self,
        *,
        line: str,
        line_number: int,
        warnings: list[HugoParseWarning],
        shortcode_stack: list[tuple[str, int]],
    ) -> str:
        matches = list(_SHORTCODE_RE.finditer(line))
        if not matches:
            return line

        for match in matches:
            open_marker = match.group(1)
            close_marker = match.group(4)
            if (open_marker, close_marker) not in {("<", ">"), ("%", "%")}:
                warnings.append(
                    HugoParseWarning(
                        code=WARNING_CODE_UNSUPPORTED_SHORTCODE,
                        message="Shortcode marker pair is not supported.",
                        line_hint=line_number,
                    )
                )
                continue

            shortcode_name = match.group(3).lower()
            is_closing = match.group(2) == "/"
            if shortcode_name not in _SUPPORTED_SHORTCODES:
                warnings.append(
                    HugoParseWarning(
                        code=WARNING_CODE_UNSUPPORTED_SHORTCODE,
                        message=f"Unsupported shortcode `{shortcode_name}` encountered.",
                        line_hint=line_number,
                    )
                )
                continue

            if is_closing:
                if not shortcode_stack or shortcode_stack[-1][0] != shortcode_name:
                    warnings.append(
                        HugoParseWarning(
                            code=WARNING_CODE_SHORTCODE_MISMATCH,
                            message=f"Mismatched closing shortcode `{shortcode_name}`.",
                            line_hint=line_number,
                        )
                    )
                    continue
                shortcode_stack.pop()
                continue

            shortcode_stack.append((shortcode_name, line_number))

        return _SHORTCODE_RE.sub("", line).rstrip()


def _find_closing_front_matter(lines: list[str], delimiter: str) -> tuple[int, str] | None:
    """Locate the closing front-matter delimiter.

    Returns ``(closing_index, trailing_body)`` or ``None`` if no close is found.

    A well-formed document closes the front matter with the delimiter alone on
    its line, in which case ``trailing_body`` is empty. Some upstream Hugo API
    references glue the closing delimiter to inline content on the same line —
    e.g. a line that is the closing ``---`` immediately followed by an opening
    triple-backtick code fence. To avoid discarding hundreds of otherwise-valid
    API symbol pages, such a line is still treated as the close and the trailing
    content (the code fence in the example) is returned so the caller can
    re-inject it as the first body line. A run of delimiter characters (e.g.
    ``----``, a horizontal rule / setext underline) is never treated as the
    close.
    """
    for idx, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped == delimiter:
            return idx, ""
        if stripped.startswith(delimiter):
            remainder = stripped[len(delimiter) :]
            # Only a close when real content follows — not a longer dash/plus run.
            if remainder and remainder[0] != delimiter[0]:
                return idx, remainder
    return None


def _parse_yaml_front_matter(
    lines: list[str],
    *,
    line_offset: int,
) -> tuple[dict[str, Any], list[HugoParseWarning]]:
    metadata: dict[str, Any] = {}
    warnings: list[HugoParseWarning] = []

    active_list_key: str | None = None
    for idx, line in enumerate(lines):
        line_number = line_offset + idx
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- "):
            if active_list_key is None:
                warnings.append(
                    HugoParseWarning(
                        code=WARNING_CODE_YAML_FRONT_MATTER_UNSUPPORTED,
                        message="List value without a preceding key is ignored.",
                        line_hint=line_number,
                    )
                )
                continue
            current_value = metadata.get(active_list_key)
            if not isinstance(current_value, list):
                current_value = []
                metadata[active_list_key] = current_value
            current_value.append(_parse_scalar_value(stripped[2:].strip()))
            continue

        active_list_key = None
        if line.startswith((" ", "\t")):
            warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_YAML_FRONT_MATTER_UNSUPPORTED,
                    message="Nested YAML structures are not supported in baseline parser.",
                    line_hint=line_number,
                )
            )
            continue

        if ":" not in stripped:
            warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_YAML_FRONT_MATTER_UNSUPPORTED,
                    message="Unsupported YAML front matter line format.",
                    line_hint=line_number,
                )
            )
            continue

        key, raw_value = stripped.split(":", maxsplit=1)
        normalized_key = key.strip()
        normalized_value = raw_value.strip()
        if not normalized_key:
            warnings.append(
                HugoParseWarning(
                    code=WARNING_CODE_YAML_FRONT_MATTER_UNSUPPORTED,
                    message="Empty YAML key is not supported.",
                    line_hint=line_number,
                )
            )
            continue

        if not normalized_value:
            metadata[normalized_key] = []
            active_list_key = normalized_key
            continue

        metadata[normalized_key] = _parse_scalar_value(normalized_value)

    return metadata, warnings


def _parse_scalar_value(value: str) -> Any:
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1]
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar_value(part.strip()) for part in inner.split(",")]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "~"}:
        return None
    if _INT_RE.fullmatch(value):
        return int(value)
    if _FLOAT_RE.fullmatch(value):
        return float(value)
    return value


def _normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized_dict: dict[str, Any] = {}
        for key in sorted(value):
            normalized_dict[str(key)] = _normalize_metadata_value(value[key])
        return normalized_dict
    if isinstance(value, list):
        return [_normalize_metadata_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_metadata_value(item) for item in value]
    if hasattr(value, "isoformat") and callable(value.isoformat):  # datetime/date/time from TOML.
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _derive_title(
    *,
    metadata: dict[str, Any],
    headings: list[HugoHeading],
    source_path: str,
) -> str:
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if headings:
        return headings[0].text
    return Path(source_path).stem


def _resolve_snippet_language(*, fence_info: str | None, programming_language: str | None) -> str:
    normalized_fence_language = _normalize_fence_language(fence_info)
    if normalized_fence_language is not None:
        return normalized_fence_language
    normalized_programming_language = _normalize_programming_language(programming_language)
    if normalized_programming_language is not None:
        return normalized_programming_language
    return "unknown"


def _normalize_fence_language(fence_info: str | None) -> str | None:
    if not fence_info or not fence_info.strip():
        return None
    first_token = fence_info.strip().split(maxsplit=1)[0]
    first_token = first_token.split("{", maxsplit=1)[0].strip()
    if not first_token:
        return None
    normalized = first_token.casefold().replace("_", "-")
    aliased = _FENCE_LANGUAGE_ALIASES.get(normalized)
    if aliased is not None:
        return aliased
    if _LANGUAGE_TOKEN_RE.fullmatch(normalized):
        return normalized
    return None


def _normalize_programming_language(programming_language: str | None) -> str | None:
    if programming_language is None:
        return None
    normalized = programming_language.strip().casefold().replace("_", "-")
    if not normalized:
        return None
    fallback = _PROGRAMMING_LANGUAGE_SNIPPET_FALLBACKS.get(normalized)
    if fallback is not None:
        return fallback
    return _FENCE_LANGUAGE_ALIASES.get(normalized, normalized)


def _layout_declares_locale(layout_detection: dict[str, Any]) -> bool:
    """True if the layout declares a ``doc_locale`` dimension.

    Checked via the structured ``dimensions`` array first, then the flat
    ``layout_type`` string (mirroring :func:`_infer_path_context`'s precedence).
    """
    dimensions = layout_detection.get("dimensions")
    if isinstance(dimensions, list):
        for dim in dimensions:
            if isinstance(dim, dict) and dim.get("semantic") == "doc_locale":
                return True
    layout_type = layout_detection.get("layout_type")
    if isinstance(layout_type, str):
        if any(segment.strip() == "doc_locale" for segment in layout_type.split("/")):
            return True
    return False


def _infer_path_context(
    *,
    relative_repo_path: str,
    layout_detection: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not relative_repo_path:
        return None, None

    if not isinstance(layout_detection, dict):
        return None, None

    # A layout that declares no doc_locale dimension is structurally
    # single-locale: Aspose/GroupDocs localize via locale sub-dirs, so a
    # locale-less repo (e.g. ``programming_language/content``) is English.
    # Default to "english" rather than leaving it unknown — the strict
    # english-only embed gate drops unknown locales, silently losing ALL the
    # content of such a repo (e.g. aspose.llm.docs would index 0 vectors).
    locale_default = None if _layout_declares_locale(layout_detection) else "english"

    parts = Path(relative_repo_path).parts[:-1]
    if not parts:
        return locale_default, None

    doc_locale: str | None = None
    programming_language: str | None = None

    # Prefer structured dimensions array — it captures all detected depth levels
    # accurately, unlike the lossy layout_type string.
    dimensions = layout_detection.get("dimensions")
    if isinstance(dimensions, list) and dimensions:
        for dim in dimensions:
            if not isinstance(dim, dict):
                continue
            depth_val = dim.get("depth")
            semantic = dim.get("semantic")
            if not isinstance(depth_val, int) or not isinstance(semantic, str):
                continue
            idx = depth_val - 1  # dimensions use 1-based depth
            if idx < 0 or idx >= len(parts):
                continue
            raw_value = parts[idx].strip().lower().replace("_", "-")
            if semantic == "doc_locale":
                doc_locale = raw_value
            elif semantic == "programming_language":
                programming_language = raw_value
        if doc_locale is not None or programming_language is not None:
            resolved_locale = doc_locale if doc_locale is not None else locale_default
            return resolved_locale, programming_language

    # Fallback: parse the flat layout_type string for repos without dimensions.
    layout_type = None
    candidate = layout_detection.get("layout_type")
    if isinstance(candidate, str) and candidate.strip():
        layout_type = candidate.strip()
    if layout_type is None:
        return None, None

    semantics = [segment.strip() for segment in layout_type.split("/") if segment.strip()]
    for depth, semantic in enumerate(semantics):
        if depth >= len(parts):
            break
        raw_value = parts[depth].strip().lower().replace("_", "-")
        if semantic == "doc_locale":
            doc_locale = raw_value
        elif semantic == "programming_language":
            programming_language = raw_value

    resolved_locale = doc_locale if doc_locale is not None else locale_default
    return resolved_locale, programming_language


def _unescape_prose(text: str) -> str:
    """Decode Markdown punctuation escapes in narrative, never C# literals."""
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", html.unescape(text))
