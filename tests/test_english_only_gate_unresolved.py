import pytest

from adcs.ingestion.english_only_gate import EnglishOnlyGateError, enforce_english_only_gate


def test_unresolved_or_uncertain_layout_blocks():
    detection = {"layout_type": "programming_language/doc_locale/namespace",
                 "dimensions": [{"semantic": "programming_language"}],
                 "schema_unresolvable": True}
    with pytest.raises(EnglishOnlyGateError):
        enforce_english_only_gate(repo_id="r", layout_detection=detection,
                                  discovered_locales=(), english_doc_count=5)


def test_uncertain_layout_blocks():
    detection = {"layout_type": "programming_language/doc_locale/namespace",
                 "dimensions": [{"semantic": "programming_language"}],
                 "uncertain": True}
    with pytest.raises(EnglishOnlyGateError):
        enforce_english_only_gate(repo_id="r", layout_detection=detection,
                                  discovered_locales=(), english_doc_count=5)
