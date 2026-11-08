"""In-memory registries for programming languages, locales, and aliases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True, slots=True)
class ProgrammingLanguageRecord:
    lang_id: str
    display_name: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DocLocaleRecord:
    locale_id: str
    display_name: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LanguageAliasRecord:
    product_id: str
    external_language_id: str
    canonical_lang_id: str
    created_at: datetime


_DEFAULT_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("net", ".NET"),
    ("java", "Java"),
    ("python", "Python"),
    ("cpp", "C++"),
    ("c", "C"),
    ("javascript", "JavaScript"),
    ("typescript", "TypeScript"),
    ("go", "Go"),
    ("rust", "Rust"),
    ("ruby", "Ruby"),
    ("php", "PHP"),
    ("swift", "Swift"),
    ("kotlin", "Kotlin"),
    ("scala", "Scala"),
    ("r", "R"),
    ("dart", "Dart"),
    ("lua", "Lua"),
    ("perl", "Perl"),
    ("objectivec", "Objective-C"),
    ("shell", "Shell / Bash"),
    ("powershell", "PowerShell"),
    ("sql", "SQL"),
    ("matlab", "MATLAB"),
    ("groovy", "Groovy"),
    ("haskell", "Haskell"),
    ("elixir", "Elixir"),
    ("clojure", "Clojure"),
    ("fsharp", "F#"),
    ("vb", "Visual Basic"),
    ("nodejs", "Node.js"),
)

_DEFAULT_LOCALES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("zh", "Chinese (Simplified)"),
    ("zh-hant", "Chinese (Traditional)"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("it", "Italian"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("sv", "Swedish"),
    ("cs", "Czech"),
    ("id", "Indonesian"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
)


class InMemoryRegistryService:
    """Manage dynamic language/locale registries and per-product aliases."""

    def __init__(self) -> None:
        self._lock = Lock()
        now = datetime.now(tz=UTC)
        self._languages: dict[str, ProgrammingLanguageRecord] = {
            lang_id: ProgrammingLanguageRecord(
                lang_id=lang_id,
                display_name=display_name,
                enabled=True,
                created_at=now,
            )
            for lang_id, display_name in _DEFAULT_LANGUAGES
        }
        self._locales: dict[str, DocLocaleRecord] = {
            locale_id: DocLocaleRecord(
                locale_id=locale_id,
                display_name=display_name,
                enabled=True,
                created_at=now,
            )
            for locale_id, display_name in _DEFAULT_LOCALES
        }
        self._aliases: dict[tuple[str, str], LanguageAliasRecord] = {}

    def list_languages(self) -> tuple[ProgrammingLanguageRecord, ...]:
        with self._lock:
            return tuple(sorted(self._languages.values(), key=lambda item: item.lang_id))

    def upsert_language(
        self,
        *,
        lang_id: str,
        display_name: str,
        enabled: bool,
    ) -> ProgrammingLanguageRecord:
        normalized_lang_id = lang_id.strip().casefold()
        normalized_display_name = display_name.strip()
        if not normalized_lang_id:
            msg = "lang_id must not be empty."
            raise ValueError(msg)
        if not normalized_display_name:
            msg = "display_name must not be empty."
            raise ValueError(msg)

        record = ProgrammingLanguageRecord(
            lang_id=normalized_lang_id,
            display_name=normalized_display_name,
            enabled=enabled,
            created_at=datetime.now(tz=UTC),
        )
        with self._lock:
            self._languages[normalized_lang_id] = record
        return record

    def list_locales(self) -> tuple[DocLocaleRecord, ...]:
        with self._lock:
            return tuple(sorted(self._locales.values(), key=lambda item: item.locale_id))

    def upsert_locale(
        self,
        *,
        locale_id: str,
        display_name: str,
        enabled: bool,
    ) -> DocLocaleRecord:
        normalized_locale_id = locale_id.strip().casefold()
        normalized_display_name = display_name.strip()
        if not normalized_locale_id:
            msg = "locale_id must not be empty."
            raise ValueError(msg)
        if not normalized_display_name:
            msg = "display_name must not be empty."
            raise ValueError(msg)

        record = DocLocaleRecord(
            locale_id=normalized_locale_id,
            display_name=normalized_display_name,
            enabled=enabled,
            created_at=datetime.now(tz=UTC),
        )
        with self._lock:
            self._locales[normalized_locale_id] = record
        return record

    def delete_language(self, *, lang_id: str) -> bool:
        normalized = lang_id.strip().casefold()
        if not normalized:
            return False
        with self._lock:
            alias_refs = [
                key for key, rec in self._aliases.items() if rec.canonical_lang_id == normalized
            ]
            if alias_refs:
                products = ", ".join(sorted({k[0] for k in alias_refs}))
                msg = (
                    f"Cannot delete language '{normalized}': "
                    f"it is referenced by aliases in product(s): {products}. "
                    "Delete those aliases first."
                )
                raise ValueError(msg)
            if normalized not in self._languages:
                return False
            del self._languages[normalized]
            return True

    def delete_locale(self, *, locale_id: str) -> bool:
        normalized = locale_id.strip().casefold()
        if not normalized:
            return False
        with self._lock:
            if normalized not in self._locales:
                return False
            del self._locales[normalized]
            return True

    def list_language_aliases(
        self,
        *,
        product_id: str | None = None,
    ) -> tuple[LanguageAliasRecord, ...]:
        with self._lock:
            aliases = list(self._aliases.values())
        if product_id is not None:
            normalized_product_id = product_id.strip().casefold()
            aliases = [item for item in aliases if item.product_id == normalized_product_id]
        return tuple(
            sorted(
                aliases,
                key=lambda item: (
                    item.product_id,
                    item.external_language_id,
                    item.canonical_lang_id,
                ),
            )
        )

    def upsert_language_alias(
        self,
        *,
        product_id: str,
        external_language_id: str,
        canonical_lang_id: str,
    ) -> LanguageAliasRecord:
        normalized_product_id = product_id.strip().casefold()
        normalized_external_language_id = external_language_id.strip().casefold()
        normalized_canonical_lang_id = canonical_lang_id.strip().casefold()
        if not normalized_product_id:
            msg = "product_id must not be empty."
            raise ValueError(msg)
        if not normalized_external_language_id:
            msg = "external_language_id must not be empty."
            raise ValueError(msg)
        if not normalized_canonical_lang_id:
            msg = "canonical_lang_id must not be empty."
            raise ValueError(msg)

        with self._lock:
            if normalized_canonical_lang_id not in self._languages:
                msg = f"canonical_lang_id `{normalized_canonical_lang_id}` was not found."
                raise ValueError(msg)
            record = LanguageAliasRecord(
                product_id=normalized_product_id,
                external_language_id=normalized_external_language_id,
                canonical_lang_id=normalized_canonical_lang_id,
                created_at=datetime.now(tz=UTC),
            )
            self._aliases[(normalized_product_id, normalized_external_language_id)] = record
        return record

    def get_language_alias(
        self,
        *,
        product_id: str,
        external_language_id: str,
    ) -> LanguageAliasRecord | None:
        normalized_product_id = product_id.strip().casefold()
        normalized_external_language_id = external_language_id.strip().casefold()
        if not normalized_product_id or not normalized_external_language_id:
            return None
        with self._lock:
            return self._aliases.get((normalized_product_id, normalized_external_language_id))

    def delete_language_alias(self, *, product_id: str, external_language_id: str) -> bool:
        normalized_product_id = product_id.strip().casefold()
        normalized_external_language_id = external_language_id.strip().casefold()
        if not normalized_product_id or not normalized_external_language_id:
            return False
        with self._lock:
            key = (normalized_product_id, normalized_external_language_id)
            if key not in self._aliases:
                return False
            del self._aliases[key]
            return True
