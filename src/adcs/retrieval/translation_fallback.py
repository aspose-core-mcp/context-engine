"""Language detection and translation fallback orchestration for retrieval."""

from __future__ import annotations

import json
import os
import re
import ssl
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

TRANSLATION_DEPENDENCY_UNAVAILABLE = "translation_dependency_unavailable"
_DEFAULT_TRANSLATION_CONFIG_PATH = Path("config/translation_llm.json")

# Locale-detection circuit breaker and cache. The breaker trips after a
# short run of failures and stays open briefly: long enough to stop paying the
# client timeout on every query while the dependency is down, short enough that
# recovery is picked up within a minute without any operator action.
_DETECTION_FAILURE_THRESHOLD = 3
_DETECTION_CIRCUIT_COOLDOWN_SECONDS = 60.0
# Repeated identical queries are the norm for an IDE assistant retrying a prompt.
_DETECTION_CACHE_MAX_ENTRIES = 512
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$")


class TranslationConfigError(ValueError):
    """Raised when translation_llm.json is missing or invalid."""


class TranslationDependencyUnavailableError(RuntimeError):
    """Raised when translation dependency is unreachable or times out."""


@dataclass(frozen=True, slots=True)
class TranslationLlmConfig:
    """Runtime config for OpenAI-compatible translation dependency."""

    enabled: bool
    base_url: str
    model: str
    api_key_env_var: str | None
    timeout_seconds: float
    temperature: float
    max_tokens: int


@dataclass(frozen=True, slots=True)
class QueryTranslationMetadata:
    """Metadata persisted across retrieval and response localization."""

    query_locale_detected: str
    translation_fallback_applied: bool
    warning_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranslatedQuery:
    """Prepared query payload for retrieval pipeline."""

    original_query: str
    retrieval_query: str
    metadata: QueryTranslationMetadata


@dataclass(frozen=True, slots=True)
class LocalizedResponse:
    """Localized response text returned to caller language."""

    answer_text: str
    warning_reasons: tuple[str, ...]


class TranslationClient(Protocol):
    """Contract used by translation fallback service."""

    def detect_language(self, *, text: str) -> str:
        """Detect request language and return normalized locale."""

    def translate(
        self,
        *,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        """Translate text between languages."""


class OpenAICompatibleTranslationClient:
    """Minimal OpenAI-compatible translation client using stdlib HTTP."""

    def __init__(
        self,
        *,
        config: TranslationLlmConfig,
        api_key: str | None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._ssl_context = _build_ssl_context()

    def detect_language(self, *, text: str) -> str:
        content = self._chat_completion(
            messages=(
                {
                    "role": "system",
                    "content": (
                        "Detect the language of the user text."
                        " Return only ISO-639-1 code in lowercase."
                    ),
                },
                {"role": "user", "content": text},
            ),
            max_tokens=min(256, self._config.max_tokens),
        )
        normalized_locale = _normalize_locale(content.split()[0] if content.split() else content)
        if normalized_locale is None:
            msg = "Translation dependency returned invalid language code."
            raise TranslationDependencyUnavailableError(msg)
        return normalized_locale

    def translate(
        self,
        *,
        text: str,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        if not text:
            return text
        source = source_language or "auto"
        translated = self._chat_completion(
            messages=(
                {
                    "role": "system",
                    "content": (
                        "You are a translation engine for developer docs."
                        " Translate to the target language while preserving API names,"
                        " symbols, version strings, code snippets, and punctuation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {source}\n"
                        f"Target language: {target_language}\n"
                        f"Text:\n{text}"
                    ),
                },
            ),
        )
        if not translated.strip():
            msg = "Translation dependency returned an empty translation."
            raise TranslationDependencyUnavailableError(msg)
        return translated

    def _chat_completion(
        self,
        *,
        messages: tuple[dict[str, str], ...],
        max_tokens: int | None = None,
    ) -> str:
        endpoint = f"{self._config.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": self._config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._config.max_tokens,
            "messages": list(messages),
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request_payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )

        request = urllib_request.Request(
            endpoint,
            data=request_payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(
                request, timeout=self._config.timeout_seconds, context=self._ssl_context,
            ) as response:
                raw_response = response.read()
            parsed = json.loads(raw_response.decode("utf-8"))
            content = _extract_message_content(parsed)
        except (
            json.JSONDecodeError,
            KeyError,
            IndexError,
            OSError,
            TimeoutError,
            TypeError,
            urllib_error.HTTPError,
            urllib_error.URLError,
            ValueError,
        ) as exc:
            msg = "Translation dependency unavailable."
            raise TranslationDependencyUnavailableError(msg) from exc

        if not content.strip():
            msg = "Translation dependency returned empty content."
            raise TranslationDependencyUnavailableError(msg)
        return content.strip()


class TranslationFallbackService:
    """Apply language-detect/translate/reverse-translate fallback policy."""

    def __init__(
        self,
        *,
        supported_locales: tuple[str, ...] = ("en",),
        default_locale: str = "en",
        translation_client: TranslationClient | None = None,
    ) -> None:
        normalized_default_locale = _normalize_locale(default_locale)
        if normalized_default_locale is None:
            msg = "default_locale must be a valid locale value."
            raise ValueError(msg)

        normalized_supported = tuple(
            locale
            for locale in (
                _normalize_locale(raw_locale) for raw_locale in supported_locales
            )
            if locale is not None
        )
        if not normalized_supported:
            normalized_supported = (normalized_default_locale,)
        if normalized_default_locale not in normalized_supported:
            normalized_supported = tuple(sorted({*normalized_supported, normalized_default_locale}))

        self._supported_locales = normalized_supported
        self._default_locale = normalized_default_locale
        self._translation_client = translation_client
        # Locale detection is a synchronous call to an external LLM sitting
        # inside the 1200 ms p95 budget, with an 8 s client timeout: without a
        # bound, one slow upstream would drag every query with it. Two bounds
        # (a cache and a circuit breaker), neither of which changes what is
        # detected.
        #
        # Skipping the LLM for ASCII text was considered and rejected: the
        # heuristic only distinguishes ASCII from non-ASCII, so it would answer
        # "en" for German and French queries and silently disable translation
        # for them.
        self._detection_cache: OrderedDict[str, str | None] = OrderedDict()
        self._detection_failures = 0
        self._detection_circuit_open_until = 0.0

    @classmethod
    def from_config_file(
        cls,
        *,
        config_path: Path | str = _DEFAULT_TRANSLATION_CONFIG_PATH,
        supported_locales: tuple[str, ...] = ("en",),
        default_locale: str = "en",
    ) -> TranslationFallbackService:
        """Construct translation service from translation_llm.json config."""
        config = load_translation_llm_config(config_path=config_path)
        if not config.enabled:
            return cls(
                supported_locales=supported_locales,
                default_locale=default_locale,
                translation_client=None,
            )

        api_key = (
            os.getenv(config.api_key_env_var) if config.api_key_env_var else None
        )
        client = OpenAICompatibleTranslationClient(config=config, api_key=api_key)
        return cls(
            supported_locales=supported_locales,
            default_locale=default_locale,
            translation_client=client,
        )

    def prepare_query(
        self,
        *,
        query: str,
        requested_locale: str | None = None,
    ) -> TranslatedQuery:
        """Detect source locale and optionally translate query to English."""
        warnings: list[str] = []

        detected_locale = _normalize_locale(requested_locale)
        if detected_locale is None:
            detected_locale = self._detect_locale(query=query, warnings=warnings)
        if detected_locale is None:
            detected_locale = "unknown"

        if detected_locale in self._supported_locales:
            return TranslatedQuery(
                original_query=query,
                retrieval_query=query,
                metadata=QueryTranslationMetadata(
                    query_locale_detected=detected_locale,
                    translation_fallback_applied=False,
                    warning_reasons=tuple(warnings),
                ),
            )

        if self._translation_client is None:
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return TranslatedQuery(
                original_query=query,
                retrieval_query=query,
                metadata=QueryTranslationMetadata(
                    query_locale_detected=detected_locale,
                    translation_fallback_applied=False,
                    warning_reasons=tuple(warnings),
                ),
            )

        try:
            translated_query = self._translation_client.translate(
                text=query,
                source_language=detected_locale,
                target_language=self._default_locale,
            )
        except TranslationDependencyUnavailableError:
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return TranslatedQuery(
                original_query=query,
                retrieval_query=query,
                metadata=QueryTranslationMetadata(
                    query_locale_detected=detected_locale,
                    translation_fallback_applied=False,
                    warning_reasons=tuple(warnings),
                ),
            )

        return TranslatedQuery(
            original_query=query,
            retrieval_query=translated_query,
            metadata=QueryTranslationMetadata(
                query_locale_detected=detected_locale,
                translation_fallback_applied=True,
                warning_reasons=tuple(warnings),
            ),
        )

    def localize_answer(
        self,
        *,
        answer_text: str,
        translated_query: TranslatedQuery,
    ) -> LocalizedResponse:
        """Translate retrieval answer back to source locale when needed."""
        warnings = list(translated_query.metadata.warning_reasons)
        query_locale_detected = translated_query.metadata.query_locale_detected

        if (
            not translated_query.metadata.translation_fallback_applied
            or query_locale_detected == self._default_locale
            or query_locale_detected == "unknown"
        ):
            return LocalizedResponse(
                answer_text=answer_text,
                warning_reasons=tuple(warnings),
            )

        if self._translation_client is None:
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return LocalizedResponse(
                answer_text=answer_text,
                warning_reasons=tuple(warnings),
            )

        try:
            localized_answer = self._translation_client.translate(
                text=answer_text,
                source_language=self._default_locale,
                target_language=query_locale_detected,
            )
        except TranslationDependencyUnavailableError:
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return LocalizedResponse(
                answer_text=answer_text,
                warning_reasons=tuple(warnings),
            )

        return LocalizedResponse(
            answer_text=localized_answer,
            warning_reasons=tuple(warnings),
        )

    def _detect_locale(self, *, query: str, warnings: list[str]) -> str | None:
        if self._translation_client is None:
            return _heuristic_detect_locale(query)

        cache_key = query.strip()
        if cache_key in self._detection_cache:
            self._detection_cache.move_to_end(cache_key)
            return self._detection_cache[cache_key]

        now = monotonic()
        if now < self._detection_circuit_open_until:
            # The dependency failed repeatedly; best-effort retrieval without
            # translation is the correct posture, so serve from
            # the heuristic rather than spending the timeout again on every query.
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return _heuristic_detect_locale(query)

        try:
            detected = self._translation_client.detect_language(text=query)
        except TranslationDependencyUnavailableError:
            self._detection_failures += 1
            if self._detection_failures >= _DETECTION_FAILURE_THRESHOLD:
                self._detection_circuit_open_until = now + _DETECTION_CIRCUIT_COOLDOWN_SECONDS
            _append_warning(warnings, TRANSLATION_DEPENDENCY_UNAVAILABLE)
            return _heuristic_detect_locale(query)

        self._detection_failures = 0
        normalized = _normalize_locale(detected)
        self._detection_cache[cache_key] = normalized
        if len(self._detection_cache) > _DETECTION_CACHE_MAX_ENTRIES:
            self._detection_cache.popitem(last=False)
        return normalized


def load_translation_llm_config(
    config_path: Path | str = _DEFAULT_TRANSLATION_CONFIG_PATH,
) -> TranslationLlmConfig:
    """Load translation_llm.json and validate OpenAI-compatible settings."""
    resolved_path = Path(config_path)
    if not resolved_path.exists():
        msg = f"Translation config file not found: {resolved_path}"
        raise TranslationConfigError(msg)
    if not resolved_path.is_file():
        msg = f"Translation config path must be a file: {resolved_path}"
        raise TranslationConfigError(msg)

    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Translation config JSON is invalid: {resolved_path}"
        raise TranslationConfigError(msg) from exc

    if not isinstance(payload, dict):
        msg = "Translation config root must be a JSON object."
        raise TranslationConfigError(msg)

    enabled = _read_bool(payload, "enabled")
    base_url = _read_non_empty_string(payload, "base_url")
    model = _read_non_empty_string(payload, "model")
    api_key_env_var = _read_optional_non_empty_string(payload, "api_key_env_var")
    timeout_seconds = _read_float(payload, "timeout_seconds")
    temperature = _read_float(payload, "temperature")
    max_tokens = _read_int(payload, "max_tokens")

    if timeout_seconds <= 0:
        msg = "translation_llm.timeout_seconds must be greater than 0."
        raise TranslationConfigError(msg)
    if not 0 <= temperature <= 2:
        msg = "translation_llm.temperature must be between 0 and 2."
        raise TranslationConfigError(msg)
    if max_tokens < 1:
        msg = "translation_llm.max_tokens must be >= 1."
        raise TranslationConfigError(msg)
    if not base_url.startswith(("http://", "https://")):
        msg = "translation_llm.base_url must start with http:// or https://."
        raise TranslationConfigError(msg)
    if enabled and not model.strip():
        msg = "translation_llm.model is required when enabled=true."
        raise TranslationConfigError(msg)

    return TranslationLlmConfig(
        enabled=enabled,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key_env_var=api_key_env_var,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _extract_message_content(parsed_payload: dict[str, Any]) -> str:
    choices = parsed_payload["choices"]
    first_choice = choices[0]
    message = first_choice["message"]
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        ]
        return "".join(text_parts)
    # Reasoning models may return content=null when the token budget is
    # consumed entirely by reasoning tokens.  Surface an empty-content
    # error so callers can degrade gracefully.
    if content is None:
        msg = "Translation dependency returned empty content."
        raise ValueError(msg)
    msg = "Unsupported OpenAI response content type."
    raise ValueError(msg)


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context with proper CA certificates.

    Uses ``certifi`` CA bundle when available (needed on macOS with the
    official Python.org installer whose ``ssl`` module does not ship the
    system CA store).  Falls back to the platform default context.
    """
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        ctx = ssl.create_default_context()
    return ctx


def _heuristic_detect_locale(query: str) -> str:
    return "en" if query.isascii() else "unknown"


def _normalize_locale(raw_locale: str | None) -> str | None:
    if raw_locale is None:
        return None
    compact_locale = raw_locale.strip().replace("_", "-").casefold()
    if not compact_locale:
        return None
    language_only = compact_locale.split("-", maxsplit=1)[0]
    if not _LOCALE_RE.fullmatch(language_only):
        return None
    return language_only


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _read_non_empty_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"translation_llm.{key} must be a non-empty string."
        raise TranslationConfigError(msg)
    return value.strip()


def _read_optional_non_empty_string(payload: dict[str, Any], key: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        msg = f"translation_llm.{key} must be a non-empty string when provided."
        raise TranslationConfigError(msg)
    return value.strip()


def _read_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        msg = f"translation_llm.{key} must be a boolean."
        raise TranslationConfigError(msg)
    return value


def _read_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"translation_llm.{key} must be a number."
        raise TranslationConfigError(msg)
    return float(value)


def _read_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"translation_llm.{key} must be an integer."
        raise TranslationConfigError(msg)
    return value
