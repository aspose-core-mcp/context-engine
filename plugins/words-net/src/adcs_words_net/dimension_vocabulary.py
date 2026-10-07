"""Single source of truth for directory-segment dimension vocabularies.

Used by the layout detector and the English-only gate so locale, programming-
language and version recognition stay consistent. Maximum coverage: ISO codes,
full English names and common variants.
"""

from __future__ import annotations

import re

# Full English name -> ISO 639-1 code. English is the implicit default locale.
_LOCALE_NAME_TO_CODE: dict[str, str] = {
    "english": "en",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "ukrainian": "uk",
    "polish": "pl",
    "czech": "cs",
    "dutch": "nl",
    "swedish": "sv",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "turkish": "tr",
    "arabic": "ar",
    "hebrew": "he",
    "hindi": "hi",
    "indonesian": "id",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "thai": "th",
    "vietnamese": "vi",
    "romanian": "ro",
    "hungarian": "hu",
    "bulgarian": "bg",
    "persian": "fa",
    "malay": "ms",
    "afrikaans": "af",
}
# ISO codes (1- and common 2-part) recognised directly.
_LOCALE_CODES: frozenset[str] = frozenset(
    set(_LOCALE_NAME_TO_CODE.values())
    | {"zh-hans", "zh-hant", "zh-cn", "zh-tw", "en-us", "en-gb", "pt-br"}
)
_ENGLISH_ALIASES: frozenset[str] = frozenset({"en", "english", "eng", "en-us", "en-gb"})

PROGRAMMING_VOCAB: frozenset[str] = frozenset(
    {
        "net",
        "dotnet",
        "java",
        "androidjava",
        "cpp",
        "c",
        "csharp",
        "vb",
        "python",
        "python-net",
        "python-java",
        "python-cpp",
        "node",
        "nodejs",
        "nodejs-cpp",
        "nodejs-java",
        "javascript",
        "javascript-cpp",
        "js",
        "php",
        "php-java",
        "go",
        "go-cpp",
        "rust",
        "rust-cpp",
        "ruby",
        "swift",
        "kotlin",
    }
)
_PROGRAMMING_MARKERS: tuple[str, ...] = (
    "python",
    "node",
    "java",
    "cpp",
    "net",
    "js",
    "csharp",
    "php",
    "rust",
    "golang",
)
_VERSION_RE = re.compile(r"^(v?\d+(\.\d+){0,3}|latest(-stable)?|\d{8}|\d{4}-\d{2}-\d{2})$")


def normalize_token(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def normalize_locale(token: str) -> str | None:
    """Return the ISO code for a locale segment, or None if not a locale."""
    norm = normalize_token(token)
    if norm in _LOCALE_NAME_TO_CODE:
        return _LOCALE_NAME_TO_CODE[norm]
    if norm in _LOCALE_CODES:
        return norm.split("-")[0]
    # A bare 2-letter token is an ISO code ONLY if it isn't a known SDK token
    # (e.g. "go", "js", "vb" are programming languages, not locales).
    if norm in PROGRAMMING_VOCAB:
        return None
    if re.fullmatch(r"[a-z]{2}(-[a-z]{2,4})?", norm):
        return norm.split("-")[0]
    return None


def looks_like_locale(token: str) -> bool:
    return normalize_locale(token) is not None


def is_non_english_locale(token: str) -> bool:
    norm = normalize_token(token)
    if norm in _ENGLISH_ALIASES or norm in ("", "unknown"):
        return False
    code = normalize_locale(norm)
    return code is not None and code != "en"


def looks_like_programming_language(token: str) -> bool:
    norm = normalize_token(token)
    if norm in PROGRAMMING_VOCAB:
        return True
    # Substring match catches compound directory names like "python-net-bridge"
    # that aren't in the explicit vocab set but still denote an SDK variant.
    return any(marker in norm for marker in _PROGRAMMING_MARKERS)


def looks_like_version(token: str) -> bool:
    return _VERSION_RE.fullmatch(normalize_token(token)) is not None


def classify_segment(token: str) -> str | None:
    """Best single dimension for one directory segment, or None (namespace/content)."""
    if looks_like_version(token):
        return "version"
    if looks_like_programming_language(token):
        return "programming_language"
    if looks_like_locale(token):
        return "doc_locale"
    return None
