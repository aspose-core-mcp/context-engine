"""Locale-less english default (parser) vs block-on-uncertain (english-only gate).

This pins the interaction between two independent behaviours that act on the
*same* input shape — a docs layout that declares a
``programming_language`` dimension but **no** ``doc_locale`` dimension:

* parser — :func:`adcs.ingestion.hugo_parser._infer_path_context` defaults
  such a "locale-less" layout's ``doc_locale`` to ``"english"`` (via
  :func:`adcs.ingestion.hugo_parser._layout_declares_locale`). Without this the
  locale is ``None``/unknown and the strict english-only embed gate silently
  drops EVERY chunk of the repo (observed regression: aspose.llm.docs → 0
  vectors despite 280 chunks).
* gate — :func:`adcs.ingestion.english_only_gate.evaluate_english_only_gate`
  BLOCKS with a ``SCHEMA_DIMENSIONS_UNRESOLVABLE`` violation whenever the
  layout is flagged ``uncertain`` or ``schema_unresolvable`` (manual override
  then required).

The danger: a future change to ``_is_schema_resolvable`` could make the
*resolved* locale-less repo (which the parser deliberately tags as english)
trip the gate — silently dropping it — OR make an *uncertain* layout sail
through. Both branches are asserted explicitly so either drift is a
hard failure.

Fixture shapes mirror ``tests/test_english_only_gate_unresolved.py`` and
``tests/test_hugo_markdown_parser.py``
(``test_infer_path_context_defaults_locale_less_layout_to_english``).
"""

from __future__ import annotations

import pytest

from adcs.ingestion.english_only_gate import (
    EnglishOnlyGateError,
    EnglishOnlyGateReason,
    _is_schema_resolvable,
    enforce_english_only_gate,
    evaluate_english_only_gate,
)
from adcs.ingestion.hugo_parser import (
    HugoMarkdownParser,
    _infer_path_context,
    _layout_declares_locale,
)

# A docs layout that declares programming_language but NO doc_locale dimension —
# the exact shape both behaviours act on. Aspose/GroupDocs localize via locale
# sub-dirs, so a repo whose layout has no doc_locale dimension is structurally
# single-locale English (e.g. aspose.llm.docs: ``programming_language/content``).
_LOCALE_LESS_RESOLVED_LAYOUT: dict[str, object] = {
    "layout_type": "programming_language/content",
    "dimensions": [
        {"depth": 1, "semantic": "programming_language", "values_sample": ["net"]},
    ],
}
_RELATIVE_PATH = "net/getting-started/installation/_index.md"


def _uncertain(**flag: bool) -> dict[str, object]:
    """Return the SAME locale-less layout with an uncertainty flag set."""
    layout = dict(_LOCALE_LESS_RESOLVED_LAYOUT)
    layout["dimensions"] = list(_LOCALE_LESS_RESOLVED_LAYOUT["dimensions"])  # type: ignore[arg-type]
    layout.update(flag)
    return layout


# --------------------------------------------------------------------------- #
# Case A — RESOLVED locale-less layout: parser tags english AND gate admits.
# --------------------------------------------------------------------------- #


def test_case_a_resolved_locale_less_layout_declares_no_locale() -> None:
    # Precondition for the whole module: this layout must read as declaring
    # no doc_locale dimension, which is what triggers the english default.
    assert _layout_declares_locale(_LOCALE_LESS_RESOLVED_LAYOUT) is False


def test_case_a_infer_path_context_defaults_locale_to_english() -> None:
    # Parser behaviour: locale-less layout -> doc_locale defaults to "english",
    # programming_language is still parsed from the path.
    doc_locale, programming_language = _infer_path_context(
        relative_repo_path=_RELATIVE_PATH,
        layout_detection=_LOCALE_LESS_RESOLVED_LAYOUT,
    )
    assert doc_locale == "english"
    assert programming_language == "net"


def test_case_a_parse_document_tags_locale_english_end_to_end() -> None:
    # Same default observed through the public parse_document entry point, not
    # just the private helper — this is the value that reaches the chunk model.
    parser = HugoMarkdownParser()
    page = parser.parse_document(
        repo_id="aspose.llm.docs",
        source_path=(
            "source-repo-docs/Aspose.LLM/net/getting-started/installation/_index.md"
        ),
        source_kind="docs",
        raw_markdown="---\ntitle: Installation\n---\nInstall steps.\n",
        product_id="aspose.llm",
        relative_repo_path=_RELATIVE_PATH,
        layout_detection=_LOCALE_LESS_RESOLVED_LAYOUT,
    )
    assert page.doc_locale == "english"
    assert page.programming_language == "net"


def test_case_a_english_only_gate_admits_resolved_locale_less_repo() -> None:
    # The gate must NOT block the repo the parser tags as english: a resolved locale-less
    # layout (programming_language present, no uncertainty flag) emits no
    # violations at all — in particular no SCHEMA_DIMENSIONS_UNRESOLVABLE.
    violations = evaluate_english_only_gate(
        repo_id="aspose.llm.docs",
        layout_detection=_LOCALE_LESS_RESOLVED_LAYOUT,
        discovered_locales=(),
        english_doc_count=5,
    )
    assert violations == ()
    reason_codes = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value not in reason_codes

    # The raising wrapper agrees — no EnglishOnlyGateError for the resolved repo.
    enforce_english_only_gate(
        repo_id="aspose.llm.docs",
        layout_detection=_LOCALE_LESS_RESOLVED_LAYOUT,
        discovered_locales=(),
        english_doc_count=5,
    )


# --------------------------------------------------------------------------- #
# Case B — SAME locale-less layout, flagged uncertain / schema_unresolvable:
#          the gate BLOCKS (manual override required).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("flag", ["uncertain", "schema_unresolvable"])
def test_case_b_uncertain_locale_less_layout_blocks_gate(flag: str) -> None:
    # Gate behaviour wins when the layout is uncertain: even though the layout
    # still carries a programming_language dimension (would otherwise resolve),
    # the uncertainty flag forces a SCHEMA_DIMENSIONS_UNRESOLVABLE block.
    layout = _uncertain(**{flag: True})
    violations = evaluate_english_only_gate(
        repo_id="aspose.llm.docs",
        layout_detection=layout,
        discovered_locales=(),
        english_doc_count=5,
    )
    reason_codes = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value in reason_codes
    # English content is present (count > 0), so the ONLY reason to block is the
    # unresolved schema — not a missing-English violation.
    assert EnglishOnlyGateReason.ENGLISH_VERSION_MISSING.value not in reason_codes


@pytest.mark.parametrize("flag", ["uncertain", "schema_unresolvable"])
def test_case_b_uncertain_locale_less_layout_raises_gate_error(flag: str) -> None:
    # The raising wrapper escalates the same block to a fatal EnglishOnlyGateError
    # (the orchestrator surfaces this as a manual-override-required halt).
    layout = _uncertain(**{flag: True})
    with pytest.raises(EnglishOnlyGateError) as exc_info:
        enforce_english_only_gate(
            repo_id="aspose.llm.docs",
            layout_detection=layout,
            discovered_locales=(),
            english_doc_count=5,
        )
    raised_reasons = {violation.reason_code for violation in exc_info.value.violations}
    assert (
        EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value in raised_reasons
    )


def test_case_b_uncertain_flag_is_the_only_difference_from_case_a() -> None:
    # Guard the premise of the whole module: Case A and Case B differ by
    # exactly the uncertainty flag. If the resolved fixture ever grows an
    # uncertainty flag (or the gate stops keying on it), this asserts loudly.
    resolved = _LOCALE_LESS_RESOLVED_LAYOUT
    uncertain = _uncertain(uncertain=True)

    assert resolved.get("uncertain") is None
    assert resolved.get("schema_unresolvable") is None
    assert uncertain["uncertain"] is True
    # Same structural layout otherwise.
    assert uncertain["layout_type"] == resolved["layout_type"]
    assert uncertain["dimensions"] == resolved["dimensions"]

    # And the gate verdicts genuinely diverge on that single bit.
    admitted = evaluate_english_only_gate(
        repo_id="aspose.llm.docs",
        layout_detection=resolved,
        discovered_locales=(),
        english_doc_count=5,
    )
    blocked = evaluate_english_only_gate(
        repo_id="aspose.llm.docs",
        layout_detection=uncertain,
        discovered_locales=(),
        english_doc_count=5,
    )
    assert admitted == ()
    assert blocked != ()


# --------------------------------------------------------------------------- #
# Case C — RESOLVED locale-less AND language-less layout (e.g. a guide-only docs
#          repo: no doc_locale dimension, no programming_language dimension).
#          The parser admits it (defaulting to english), so the gate must admit
#          it too rather than BLOCK it (no programming_language => unresolvable)
#          and silently drop the repo: a layout that declares no doc_locale
#          dimension is English-only and therefore resolvable, language or not.
# --------------------------------------------------------------------------- #

_LANGUAGE_LESS_RESOLVED_LAYOUT: dict[str, object] = {
    "layout_type": "content_group/content",
    "dimensions": [
        {"depth": 1, "semantic": "content_group", "values_sample": ["guides"]},
    ],
}


def test_case_c_language_less_layout_declares_no_locale() -> None:
    # Neither a doc_locale nor a programming_language dimension is declared.
    assert _layout_declares_locale(_LANGUAGE_LESS_RESOLVED_LAYOUT) is False


def test_case_c_language_less_layout_is_schema_resolvable() -> None:
    # A resolved layout with no doc_locale dimension is English-only and
    # therefore resolvable even without a programming_language. A False here
    # would make the gate drop the guide-only repo.
    assert _is_schema_resolvable(_LANGUAGE_LESS_RESOLVED_LAYOUT) is True


def test_case_c_parser_defaults_language_less_to_english() -> None:
    doc_locale, programming_language = _infer_path_context(
        relative_repo_path="guides/getting-started/_index.md",
        layout_detection=_LANGUAGE_LESS_RESOLVED_LAYOUT,
    )
    assert doc_locale == "english"
    assert programming_language is None


def test_case_c_gate_admits_language_less_english_repo() -> None:
    # Parser admits AND the gate admits — the two agree on the guide-only repo.
    violations = evaluate_english_only_gate(
        repo_id="guides.docs",
        layout_detection=_LANGUAGE_LESS_RESOLVED_LAYOUT,
        discovered_locales=(),
        english_doc_count=5,
    )
    assert violations == ()


@pytest.mark.parametrize("flag", ["uncertain", "schema_unresolvable"])
def test_case_c_uncertain_language_less_layout_still_blocks(flag: str) -> None:
    # The uncertainty guard still applies: a language-less layout that is
    # flagged uncertain/unresolvable still blocks (manual override required).
    layout = dict(_LANGUAGE_LESS_RESOLVED_LAYOUT)
    layout["dimensions"] = list(_LANGUAGE_LESS_RESOLVED_LAYOUT["dimensions"])  # type: ignore[arg-type]
    layout[flag] = True
    violations = evaluate_english_only_gate(
        repo_id="guides.docs",
        layout_detection=layout,
        discovered_locales=(),
        english_doc_count=5,
    )
    reason_codes = {violation.reason_code for violation in violations}
    assert EnglishOnlyGateReason.SCHEMA_DIMENSIONS_UNRESOLVABLE.value in reason_codes
