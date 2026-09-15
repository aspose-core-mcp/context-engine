from __future__ import annotations

import json
from pathlib import Path

import pytest

from adcs.retrieval import (
    TRANSLATION_DEPENDENCY_UNAVAILABLE,
    TranslationConfigError,
    TranslationDependencyUnavailableError,
    TranslationFallbackService,
    load_translation_llm_config,
)


class _StubTranslationClient:
    def __init__(
        self,
        *,
        detected_locale: str = "de",
        translations: dict[tuple[str | None, str, str], str] | None = None,
        fail_translate: bool = False,
    ) -> None:
        self.detected_locale = detected_locale
        self.translations = translations or {}
        self.fail_translate = fail_translate

    def detect_language(self, *, text: str) -> str:
        del text
        return self.detected_locale

    def translate(
        self,
        *,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        if self.fail_translate:
            msg = "translation dependency unavailable"
            raise TranslationDependencyUnavailableError(msg)
        return self.translations[(source_language, target_language, text)]


def test_translation_fallback_detects_translates_and_reverse_translates() -> None:
    client = _StubTranslationClient(
        detected_locale="de",
        translations={
            ("de", "en", "Wie erkenne ich Text?"): "How do I recognize text?",
            ("en", "de", "Use RecognizeImage method."): "Verwenden Sie die RecognizeImage-Methode.",
        },
    )
    service = TranslationFallbackService(
        supported_locales=("en",),
        default_locale="en",
        translation_client=client,
    )

    translated_query = service.prepare_query(query="Wie erkenne ich Text?")

    assert translated_query.retrieval_query == "How do I recognize text?"
    assert translated_query.metadata.query_locale_detected == "de"
    assert translated_query.metadata.translation_fallback_applied is True
    assert translated_query.metadata.warning_reasons == ()

    localized_response = service.localize_answer(
        answer_text="Use RecognizeImage method.",
        translated_query=translated_query,
    )

    assert localized_response.answer_text == "Verwenden Sie die RecognizeImage-Methode."
    assert localized_response.warning_reasons == ()


def test_translation_fallback_degrades_to_best_effort_when_dependency_unavailable() -> None:
    service = TranslationFallbackService(
        supported_locales=("en",),
        default_locale="en",
        translation_client=_StubTranslationClient(
            detected_locale="de",
            fail_translate=True,
        ),
    )

    translated_query = service.prepare_query(query="Wie erkenne ich Text?")

    assert translated_query.retrieval_query == "Wie erkenne ich Text?"
    assert translated_query.metadata.query_locale_detected == "de"
    assert translated_query.metadata.translation_fallback_applied is False
    assert translated_query.metadata.warning_reasons == (
        TRANSLATION_DEPENDENCY_UNAVAILABLE,
    )

    localized_response = service.localize_answer(
        answer_text="Use RecognizeImage method.",
        translated_query=translated_query,
    )

    assert localized_response.answer_text == "Use RecognizeImage method."
    assert localized_response.warning_reasons == (
        TRANSLATION_DEPENDENCY_UNAVAILABLE,
    )


def test_translation_fallback_uses_requested_supported_locale_without_translation() -> None:
    service = TranslationFallbackService(
        supported_locales=("en", "de"),
        default_locale="en",
        translation_client=None,
    )

    translated_query = service.prepare_query(
        query="How to install Aspose OCR?",
        requested_locale="en-US",
    )

    assert translated_query.retrieval_query == "How to install Aspose OCR?"
    assert translated_query.metadata.query_locale_detected == "en"
    assert translated_query.metadata.translation_fallback_applied is False
    assert translated_query.metadata.warning_reasons == ()


def test_load_translation_llm_config_reads_valid_json(tmp_path: Path) -> None:
    config_path = tmp_path / "translation_llm.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "base_url": "http://localhost:11434/v1",
                "model": "oss-120m",
                "api_key_env_var": "ADCS_TRANSLATION_LLM_API_KEY",
                "timeout_seconds": 8.0,
                "temperature": 0.0,
                "max_tokens": 1024,
            }
        ),
        encoding="utf-8",
    )

    config = load_translation_llm_config(config_path=config_path)

    assert config.enabled is True
    assert config.base_url == "http://localhost:11434/v1"
    assert config.model == "oss-120m"
    assert config.api_key_env_var == "ADCS_TRANSLATION_LLM_API_KEY"
    assert config.timeout_seconds == 8.0
    assert config.temperature == 0.0
    assert config.max_tokens == 1024


def test_load_translation_llm_config_rejects_missing_required_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "translation_llm.json"
    config_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

    with pytest.raises(TranslationConfigError):
        load_translation_llm_config(config_path=config_path)


class _CountingClient:
    """Translation client that records calls and can be made to fail."""

    def __init__(self, *, locale: str = "de", fail: bool = False) -> None:
        self.locale = locale
        self.fail = fail
        self.detect_calls = 0

    def detect_language(self, *, text: str) -> str:
        self.detect_calls += 1
        if self.fail:
            raise TranslationDependencyUnavailableError("upstream down")
        return self.locale

    def translate(
        self, *, text: str, target_language: str, source_language: str | None = None
    ) -> str:
        return text


def test_locale_detection_is_cached_per_query() -> None:
    """Detection is a synchronous LLM call inside the p95 budget.

    An IDE assistant retrying the same prompt should not pay for it twice.
    """
    client = _CountingClient(locale="de")
    service = TranslationFallbackService(translation_client=client)

    for _ in range(4):
        service.prepare_query(query="Wie konvertiere ich ein PDF?")

    assert client.detect_calls == 1, "repeat queries must be served from the detection cache"


def test_locale_detection_circuit_opens_after_repeated_failures() -> None:
    """A failing dependency must stop being called on every single query.

    With an 8 s client timeout and no breaker, one slow upstream dragged every
    request with it; best-effort retrieval without translation is the correct
    posture, so serve from the heuristic instead.
    """
    client = _CountingClient(fail=True)
    service = TranslationFallbackService(translation_client=client)

    for index in range(10):
        prepared = service.prepare_query(query=f"Wie konvertiere ich Datei {index}?")
        assert TRANSLATION_DEPENDENCY_UNAVAILABLE in prepared.metadata.warning_reasons

    assert client.detect_calls == 3, (
        f"the breaker should stop calls after 3 failures, got {client.detect_calls}"
    )


def test_ascii_queries_still_reach_the_detector() -> None:
    """Skipping detection for ASCII text would break Latin-script languages.

    The heuristic only distinguishes ASCII from non-ASCII, so treating ASCII as
    English would answer "en" for German and French and silently disable
    translation for them.
    """
    client = _CountingClient(locale="de")
    service = TranslationFallbackService(translation_client=client)

    prepared = service.prepare_query(query="Wie konvertiere ich ein PDF nach Word?")

    assert client.detect_calls == 1
    assert prepared.metadata.query_locale_detected == "de"
