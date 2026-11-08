"""FIX-D-alias: publishing one scope must not drop other scopes from the
shared lexical alias.

The lexical alias ``{source_kind}_lex_v1_active`` is shared across every
per-scope (product/language/version) snapshot index. The alias switch must be
ADDITIVE: adding the new scope's index (and superseding only the same scope's
prior index) — never removing other scopes. Otherwise publishing product B
silently drops product A from lexical serving (the dense lane is immune).

The pure ``_build_alias_actions`` is unit-tested; the end-to-end additive
behaviour is asserted against a real OpenSearch on an isolated synthetic
``source_kind`` (auto-skips when OpenSearch is unreachable, and never touches
the real ``docs_*``/``apiref_*`` aliases).
"""

from __future__ import annotations

import os

import httpx
import pytest

from adcs.indexing.lexical_index_writer import (
    OpenSearchLexicalIndexWriter,
    _build_alias_actions,
)

# --- pure action-builder unit tests (no OpenSearch needed) ---


def test_build_alias_actions_is_add_only_without_superseded() -> None:
    actions = _build_alias_actions(
        index_name="docs_lex_v1_new", alias_name="docs_lex_v1_active", superseded_index=None
    )
    # No remove of any other index — purely additive.
    assert actions == [{"add": {"index": "docs_lex_v1_new", "alias": "docs_lex_v1_active"}}]


def test_build_alias_actions_supersedes_only_same_scope() -> None:
    actions = _build_alias_actions(
        index_name="docs_lex_v1_new",
        alias_name="docs_lex_v1_active",
        superseded_index="docs_lex_v1_old",
    )
    assert actions == [
        {"remove": {"index": "docs_lex_v1_old", "alias": "docs_lex_v1_active"}},
        {"add": {"index": "docs_lex_v1_new", "alias": "docs_lex_v1_active"}},
    ]


def test_build_alias_actions_never_self_removes() -> None:
    actions = _build_alias_actions(
        index_name="docs_lex_v1_x",
        alias_name="docs_lex_v1_active",
        superseded_index="docs_lex_v1_x",
    )
    assert actions == [{"add": {"index": "docs_lex_v1_x", "alias": "docs_lex_v1_active"}}]


# --- live OpenSearch: additive across scopes ---

_OS_URL = os.environ.get("ADCS_OPENSEARCH_URL", "http://localhost:9200").rstrip("/")


def _os_reachable() -> bool:
    try:
        return httpx.get(_OS_URL, timeout=3.0).status_code == 200
    except (httpx.HTTPError, OSError):
        return False


@pytest.mark.live
@pytest.mark.skipif(not _os_reachable(), reason=f"OpenSearch not reachable at {_OS_URL}")
def test_switch_alias_keeps_other_scopes_live() -> None:
    # Isolated synthetic source_kind — never the real docs_*/apiref_* aliases.
    source_kind = "hardentest_alias"
    alias = f"{source_kind}_lex_v1_active"
    scope_a = f"{source_kind}_lex_v1_scopea"
    scope_b = f"{source_kind}_lex_v1_scopeb"
    writer = OpenSearchLexicalIndexWriter(opensearch_url=_OS_URL)
    try:
        writer.write_records(source_kind=source_kind, snapshot_id="scopea", records=[])
        writer.switch_alias(source_kind=source_kind, snapshot_id="scopea")
        writer.write_records(source_kind=source_kind, snapshot_id="scopeb", records=[])
        writer.switch_alias(source_kind=source_kind, snapshot_id="scopeb")

        aliased = set(httpx.get(f"{_OS_URL}/_alias/{alias}", timeout=5.0).json().keys())
        # Both scopes must remain under the alias — publishing scope B must not
        # drop scope A from lexical serving.
        assert scope_a in aliased
        assert scope_b in aliased
    finally:
        httpx.delete(f"{_OS_URL}/{scope_a},{scope_b}", timeout=5.0)
