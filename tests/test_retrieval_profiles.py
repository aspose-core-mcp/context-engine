"""Plugin-owned policy stays scoped and cannot override explicit API requests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adcs.plugins.catalog import PluginManifest
from adcs.retrieval.profiles import RetrievalProfile, load_profiles, profile_for

ROOT = Path(__file__).resolve().parents[1]

if not (ROOT / "plugins/words-net/plugin.json").is_file():
    pytest.skip(
        "Requires separately installed Words plugin; see docs/engine-only.md",
        allow_module_level=True,
    )


def test_words_profile_only_applies_to_words_net():
    profile = profile_for("aspose.words", "net")
    assert profile is not None
    assert profile_for("aspose.cells", "net") is None
    assert profile_for("aspose.words", "java") is None
    assert profile_for("aspose.tex", "net") is None
    assert profile.targets("mail merge with DataTable") == (
        "Aspose.Words.MailMerging.MailMerge.Execute",
    )
    assert profile.targets("mail merge with regions and DataTable") == (
        "Aspose.Words.MailMerging.MailMerge.ExecuteWithRegions",
    )
    for query in (
        "mail merge to images",
        "mail merge with LowCode",
        "mail merge using Aspose.Words.LowCode.MailMerger.Execute",
    ):
        assert profile.targets(query) == ()
    assert profile.explain("mail merge")["matched_rules"] == ["classic-mail-merge"]


def test_profile_validation_rejects_wrong_schema_and_cross_product_targets():
    raw = json.loads((ROOT / "plugins/words-net/retrieval-profile.json").read_text())
    raw["schema_version"] = 2
    with pytest.raises(ValidationError):
        RetrievalProfile.model_validate(raw)
    raw["schema_version"] = 1
    raw["rules"][0]["preferred_symbols"] = ["Aspose.Cells.Workbook.Save"]
    with pytest.raises(ValidationError):
        RetrievalProfile.model_validate(raw)


def test_catalog_rejects_profile_escape_and_scope_mismatch(tmp_path):
    raw = json.loads((ROOT / "plugins/words-net/plugin.json").read_text())
    raw["retrieval_profile"] = "../profile.json"
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(raw)
    raw["retrieval_profile"] = "profile.json"
    (tmp_path / "plugin.json").write_text(json.dumps(raw))
    profile = json.loads((ROOT / "plugins/words-net/retrieval-profile.json").read_text())
    profile["language"] = "java"
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"plugins": ["plugin.json"]}))
    with pytest.raises(ValueError, match="scope"):
        load_profiles(str(catalog))


def test_profile_retrieves_overloads_missing_from_search_and_preserves_scope():
    from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol
    from adcs.retrieval.two_source_retriever import ApiRefRetriever

    scope = ApiRefScope(product="aspose.words", language="net", version="25.4", locale="en")
    target = "Aspose.Words.MailMerging.MailMerge.Execute"

    def symbol(signature):
        return ApiRefSymbol(
            snapshot_id="s",
            product=scope.product,
            language=scope.language,
            version=scope.version,
            locale=scope.locale,
            kind="method",
            member_fqn=target,
            name="Execute",
            parent_fqn=None,
            signature=signature,
            canonical_url="https://reference.aspose.com/",
            is_deprecated=False,
            summary="Execute mail merge",
            payload={},
        )

    class Store:
        def get_symbol(self, *, member_fqn, scope):
            assert scope.version == "25.4" and scope.locale == "en"
            assert member_fqn == target
            return [
                symbol("public void Execute(DataRow row)"),
                symbol("public void Execute(DataTable table)"),
            ]

        def search_symbols(self, **kwargs):
            return []

        def fts_search(self, **kwargs):
            return []

    lane = ApiRefRetriever(store=Store())
    hits = lane.search(query="mail merge with DataTable", scope=scope, limit=2)
    assert len(hits) == 2
    assert hits[0].signature == "public void Execute(DataTable table)"
    assert lane.search(query="mail merge to images", scope=scope, limit=2) == ()
    assert lane.search(query=target, scope=scope, limit=2) == ()  # exact lookup is separate


def test_missing_preferred_symbol_falls_back_to_generic_results():
    from adcs.indexing.apiref_symbol_store import ApiRefScope, ApiRefSymbol
    from adcs.retrieval.two_source_retriever import ApiRefRetriever

    scope = ApiRefScope(product="aspose.words", language="net", version="25.4", locale="en")
    fallback = ApiRefSymbol(
        snapshot_id="s",
        product=scope.product,
        language=scope.language,
        version=scope.version,
        locale=scope.locale,
        kind="class",
        member_fqn="Aspose.Words.MailMerge",
        name="MailMerge",
        parent_fqn=None,
        signature="public class MailMerge",
        canonical_url="https://reference.aspose.com/",
        is_deprecated=False,
        summary="Mail merge functionality.",
        payload={},
    )

    class Store:
        def get_symbol(self, **kwargs):
            return []

        def search_symbols(self, **kwargs):
            return [fallback]

        def fts_search(self, **kwargs):
            return []

    assert ApiRefRetriever(store=Store()).search(
        query="mail merge",
        scope=scope,
        limit=10,
    ) == (fallback,)


def test_committed_profile_schema_matches_model():
    schema = json.loads((ROOT / "contracts/retrieval-profile/v1/profile.schema.json").read_text())
    schema.pop("$schema")
    assert schema == RetrievalProfile.model_json_schema()
