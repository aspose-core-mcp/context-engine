"""Retrieval profiles accept Java package identities without widening product scope."""

import pytest
from pydantic import ValidationError

from adcs.retrieval.profiles import RetrievalProfile


def _profile(*symbols, excluded=()):
    return {
        "schema_version": 1,
        "profile_id": "aspose.words.java.retrieval",
        "version": "1.0.0",
        "product_id": "aspose.words",
        "language": "java",
        "excluded_namespaces": list(excluded),
        "rules": [{
            "rule_id": "classic-mail-merge",
            "all_terms": ["mail", "merge"],
            "preferred_symbols": list(symbols),
        }],
    }


def test_java_package_symbols_are_accepted():
    profile = RetrievalProfile.model_validate(_profile(
        "com.aspose.words.MailMerge.execute",
        excluded=["com.aspose.words.MailMerger"],
    ))
    assert profile.targets("mail merge") == ("com.aspose.words.MailMerge.execute",)
    assert not profile.allows("com.aspose.words.MailMerger.execute")
    assert profile.allows("com.aspose.words.MailMerge.execute")


def test_dotnet_style_identities_remain_valid():
    RetrievalProfile.model_validate(_profile("Aspose.Words.MailMerging.MailMerge.Execute"))


@pytest.mark.parametrize("symbol", [
    "com.aspose.cells.Workbook.save",
    "org.aspose.words.Document",
    "com.aspose.wordsx.Document",
    "com.Document",
])
def test_java_prefix_is_still_product_scoped(symbol):
    with pytest.raises(ValidationError):
        RetrievalProfile.model_validate(_profile(symbol))


def test_excluded_preferred_symbol_is_rejected():
    with pytest.raises(ValidationError):
        RetrievalProfile.model_validate(_profile(
            "com.aspose.words.MailMerger.execute", excluded=["com.aspose.words.MailMerger"],
        ))
