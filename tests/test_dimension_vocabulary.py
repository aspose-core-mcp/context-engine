from adcs.ingestion import dimension_vocabulary as dv


def test_full_name_locales_normalize_to_codes():
    assert dv.normalize_locale("english") == "en"
    assert dv.normalize_locale("Chinese") == "zh"
    assert dv.normalize_locale("german") == "de"
    assert dv.normalize_locale("zh-cn") == "zh"
    assert dv.normalize_locale("en-US") == "en"
    assert dv.normalize_locale("aspose.slides") is None


def test_is_non_english_locale_recognizes_full_names():
    for token in ("chinese", "german", "french", "russian", "spanish", "ja", "zh"):
        assert dv.is_non_english_locale(token) is True
    for token in ("english", "en", "unknown", "", "aspose.slides", "net"):
        assert dv.is_non_english_locale(token) is False


def test_classify_segment_picks_one_dimension():
    assert dv.classify_segment("english") == "doc_locale"
    assert dv.classify_segment("python-net") == "programming_language"
    assert dv.classify_segment("latest-stable") == "version"
    assert dv.classify_segment("aspose.slides.charts") is None


def test_programming_language_variants():
    for token in ("net", "cpp", "java", "python-net", "nodejs-cpp", "androidjava", "php-java"):
        assert dv.looks_like_programming_language(token) is True


def test_two_letter_programming_tokens_are_not_locales():
    for token in ("go", "js", "vb"):
        assert dv.normalize_locale(token) is None
        assert dv.is_non_english_locale(token) is False
        assert dv.classify_segment(token) == "programming_language"
