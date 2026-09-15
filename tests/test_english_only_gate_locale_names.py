from adcs.ingestion.english_only_gate import summarize_english_documents


def test_full_name_non_english_locales_are_excluded():
    paths = [
        ("content", "net", "english", "aspose.slides", "x.md"),
        ("content", "net", "chinese", "aspose.slides", "x.md"),
        ("content", "net", "german", "aspose.slides", "x.md"),
        ("content", "cpp", "english", "aspose.slides", "y.md"),
    ]
    english_count, non_english = summarize_english_documents(paths)
    assert english_count == 2
    assert set(non_english) == {"zh", "de"}
