"""Forgiving input vocabulary for the structured apiref tools.

Weak coding models address the MCP with the wrong tokens (``product_id="cells"``,
``language="csharp"``) and the exact-match symbol store returns nothing — a silent
dead end. This module normalises ``product_id`` and ``language`` onto the
*served* vocabulary and supplies "did-you-mean" suggestions, so a natural
imperfect call still grounds, in one round-trip.

Pure and data-driven: the served vocabulary (``{product: {languages}}``) is passed
in by the caller (built from ``ApiRefSymbolStore.known_vocabulary()``), so this
module has no I/O and auto-tracks whatever is actually loaded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches

# Aliases onto the served programming-language tokens. Anything not served falls
# through to the per-product default (see ``normalize_language``).
_LANGUAGE_ALIASES: dict[str, str] = {
    "csharp": "net",
    "c#": "net",
    "cs": "net",
    "dotnet": "net",
    ".net": "net",
    "netcore": "net",
    "net-core": "net",
    "net core": "net",
    "py": "python-net",
    "python": "python-net",
    "python3": "python-net",
    "c++": "cpp",
    "cplusplus": "cpp",
    "js": "nodejs-cpp",
    "javascript": "nodejs-cpp",
    "node": "nodejs-cpp",
    "nodejs": "nodejs-cpp",
}

# Families a bare product name (``cells``) may belong to.
_FAMILIES: tuple[str, ...] = ("aspose", "groupdocs")

# Only these product families are real client products. Everything else that the
# store may carry (test fixtures such as ``rest.pg``, ``scale.p0``, ``sem.cut``,
# ``test.nul``) must never be resolved onto or suggested to a client.
_REAL_PRODUCT_FAMILIES: frozenset[str] = frozenset({"aspose", "groupdocs"})


def is_real_product(product: str) -> bool:
    """True for an aspose.*/groupdocs.* product; False for store test fixtures."""
    return product.split(".", 1)[0] in _REAL_PRODUCT_FAMILIES


# Product leaves that are also ordinary English words: a bare ``note``/``page``/
# ``task``/``words`` in free prose rarely means the (niche) Aspose product, so it
# is NOT extracted from a query. A distinctive leaf (cells, slides, barcode, html,
# psd, ocr) is safe to extract. See ``Vocabulary.find_product_in_text``.
_AMBIGUOUS_LEAVES: frozenset[str] = frozenset({"note", "page", "task", "tasks", "words"})

# Surface forms that signal a language inside a natural-language query, longest /
# most-specific first so ``python-net`` wins over ``net``. Each maps through
# ``_LANGUAGE_ALIASES`` / ``normalize_language`` onto a served token.
_LANGUAGE_SURFACES: tuple[str, ...] = (
    "python-net",
    "python3",
    "javascript",
    "cplusplus",
    "nodejs",
    "csharp",
    "dotnet",
    "netcore",
    "python",
    "node",
    "java",
    "cpp",
    "c#",
    "c++",
    ".net",
    "net",
    "js",
    "py",
    "cs",
)

# Keep only the characters that can appear inside a language surface; everything
# else becomes a separator so surfaces match on word boundaries.
_LANGUAGE_TEXT_NOISE = re.compile(r"[^a-z0-9+#.-]+")

# Filler words stripped from a natural-language lookup query before search, so
# the full-text AND-query is not over-constrained by prose. Verbs (save, create,
# convert) are kept — they often match method names.
_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "how",
        "to",
        "in",
        "into",
        "for",
        "of",
        "on",
        "as",
        "with",
        "from",
        "and",
        "or",
        "please",
        "i",
        "me",
        "my",
        "do",
        "want",
        "need",
        "using",
        "use",
    }
)
# Split a query into salient word tokens (keep ``#``/``+`` so ``c#``/``c++`` survive).
_QUERY_TOKEN_SPLIT = re.compile(r"[^a-z0-9#+]+")

_FUZZY_ACCEPT = 0.82  # auto-substitute a product above this similarity
_FUZZY_SUGGEST = 0.5  # offer as a did-you-mean above this similarity
# A fuzzy product match is auto-substituted only when its leaf differs from the
# input by at most this many edits — a single typo (cels→cells). Distinct real
# products (pdf vs psd, distance 2) are NOT swapped silently; they fall through
# to a did-you-mean so a client never gets confident wrong-domain code.
_MAX_TYPO_EDITS = 1


def _leaf(product: str) -> str:
    """Trailing token after the family prefix: ``aspose.psd`` → ``psd``."""
    return product.rsplit(".", 1)[-1] if "." in product else product


def _edit_distance(left: str, right: str) -> int:
    """Levenshtein edit distance (pure, no deps)."""
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _canonical_product_text(raw: str) -> str:
    """Lowercase and collapse separators: ``Aspose-Cells`` → ``aspose.cells``."""
    text = raw.strip().lower()
    for separator in (" ", "-", "_", "/", "::"):
        text = text.replace(separator, ".")
    while ".." in text:
        text = text.replace("..", ".")
    return text.strip(".")


@dataclass(frozen=True)
class Vocabulary:
    """The served ``product → languages`` map, with forgiving normalisation."""

    by_product: dict[str, frozenset[str]]

    @property
    def products(self) -> frozenset[str]:
        return frozenset(self.by_product)

    def languages_for(self, product: str) -> frozenset[str]:
        return self.by_product.get(product, frozenset())

    def all_languages(self) -> list[str]:
        """Sorted union of served languages, for steering tool-schema enums.

        Excludes the ``unknown`` partition so a junk token is never advertised as
        a valid choice. Empty when nothing is loaded (caller then omits the enum).
        """
        languages: set[str] = set()
        for served in self.by_product.values():
            languages.update(served)
        languages.discard("unknown")
        return sorted(languages)

    def _bare_index(self) -> dict[str, str]:
        """Leaf name → full product id (``cells`` → ``aspose.cells``).

        Lets a *bare* typo (``celz``) fuzzy-match against short leaf names rather
        than the long ``aspose.…`` ids, where the family prefix swamps the ratio.
        """
        index: dict[str, str] = {}
        for product in self.by_product:
            leaf = product.split(".", 1)[1] if "." in product else product
            index.setdefault(leaf, product)
        return index

    def normalize_product(self, raw: str) -> str:
        """Best-effort map a raw product id onto a served one.

        Exact → bare-name-with-family → fuzzy on the leaf (bare input) → fuzzy on
        the full id. A fuzzy match is only auto-substituted when its leaf is within
        ``_MAX_TYPO_EDITS`` of the input (a single typo); a distant match to a
        *different* real product (pdf→psd) is rejected so the caller surfaces a
        did-you-mean instead of silently returning wrong-domain symbols. Returns
        the raw canonical text unchanged when nothing matches confidently.
        """
        text = _canonical_product_text(raw)
        if text in self.by_product:
            return text
        input_leaf = _leaf(text)
        if "." not in text:  # bare name → try known families, then fuzzy leaf
            for family in _FAMILIES:
                candidate = f"{family}.{text}"
                if candidate in self.by_product:
                    return candidate
            bare_index = self._bare_index()
            leaf_match = get_close_matches(text, list(bare_index), n=1, cutoff=_FUZZY_ACCEPT)
            if leaf_match and _edit_distance(text, leaf_match[0]) <= _MAX_TYPO_EDITS:
                return bare_index[leaf_match[0]]
        match = get_close_matches(text, list(self.by_product), n=1, cutoff=_FUZZY_ACCEPT)
        if match and _edit_distance(input_leaf, _leaf(match[0])) <= _MAX_TYPO_EDITS:
            return match[0]
        return text

    def closest_products(self, raw: str, *, n: int = 3) -> list[str]:
        text = _canonical_product_text(raw)
        bare_index = self._bare_index()
        leaf = text.rsplit(".", 1)[-1]
        candidates = [
            *get_close_matches(text, list(self.by_product), n=n, cutoff=_FUZZY_SUGGEST),
            *(
                bare_index[match]
                for match in get_close_matches(leaf, list(bare_index), n=n, cutoff=_FUZZY_SUGGEST)
            ),
        ]
        deduped: list[str] = []
        for product in candidates:
            if product not in deduped:
                deduped.append(product)
        return deduped[:n]

    def normalize_language(self, raw: str, *, product: str) -> str:
        """Map a raw language token onto one served for ``product``.

        Exact-served → alias-if-served → the product's sole language → ``net``
        (v1 default) → the alias/raw unchanged.
        """
        available = self.languages_for(product)
        key = raw.strip().lower()
        if key in available:
            return key
        alias = _LANGUAGE_ALIASES.get(key)
        if alias and alias in available:
            return alias
        if len(available) == 1:
            return next(iter(available))
        if "net" in available:
            return "net"
        return alias or key

    def find_product_in_text(self, text: str) -> str | None:
        """Find a served product *named inside* a natural-language query.

        Scans for an adjacent ``family.leaf`` pair (``…in Aspose.Cells for…`` →
        ``aspose.cells``), then for a *distinctive* bare leaf (``…a chart in cells``
        → ``aspose.cells``). Ambiguous common-word leaves (``page``/``note``/
        ``task``/``words``) are skipped so ordinary prose is not mistaken for a
        product. Returns ``None`` when nothing served is named.
        """
        canonical = _canonical_product_text(text)
        tokens = [token for token in canonical.split(".") if token]
        for first, second in zip(tokens, tokens[1:], strict=False):
            candidate = f"{first}.{second}"
            if candidate in self.by_product:
                return candidate
        bare_index = self._bare_index()
        for token in tokens:
            if token in _AMBIGUOUS_LEAVES:
                continue
            product = bare_index.get(token)
            if product is not None:
                return product
        return None

    def find_language_in_text(self, text: str) -> str | None:
        """Find a language surface (``C#``, ``.NET``, ``java``) inside free text.

        Returns the raw surface (e.g. ``"c#"``); feed it through
        :meth:`normalize_language` to land on a served token. ``None`` when no
        recognised surface appears.
        """
        padded = f" {_LANGUAGE_TEXT_NOISE.sub(' ', text.lower())} "
        for surface in _LANGUAGE_SURFACES:
            if f" {surface} " in padded:
                return surface
        return None

    def salient_query(self, text: str, *, product: str | None) -> str:
        """Reduce a natural-language query to its searchable keywords.

        Drops filler words, language surfaces/aliases, and the resolved product's
        own name parts — these would otherwise over-constrain the full-text
        AND-query (``save a workbook as pdf in Aspose.Cells for C#`` →
        ``save workbook pdf``). Falls back to the original text if stripping would
        empty it.
        """
        drops = set(_QUERY_STOPWORDS)
        drops.update(_LANGUAGE_SURFACES)
        drops.update(_LANGUAGE_ALIASES)
        drops.update(_FAMILIES)
        if product:
            drops.update(part for part in product.split(".") if part)
        tokens = [token for token in _QUERY_TOKEN_SPLIT.split(text.lower()) if token]
        kept = [token for token in tokens if token not in drops]
        return " ".join(kept) or text


__all__ = ["Vocabulary"]
