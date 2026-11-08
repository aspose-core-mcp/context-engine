"""Release metadata catalog used by retrieval freshness and explainability."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReleaseCatalogEntry:
    """Resolved release metadata for one product/language/version tuple."""

    product_id: str
    programming_language: str
    version: str
    published_at: datetime
    channel: str
    label: str | None = None


class ReleaseCatalog:
    """Read-only release metadata lookup used by retrieval runtime."""

    def __init__(self, *, entries: tuple[ReleaseCatalogEntry, ...]) -> None:
        # Deduplicate by casefolded (product, language, version) key to
        # keep ``_entries`` and ``_by_key`` consistent. Without this, a
        # caller iterating ``_entries`` could observe an entry that
        # ``resolve()`` will never return (because the dict-comprehension
        # below would have overwritten it with a later collision).
        # Last-wins is deterministic and matches the from_config_file
        # convention of treating later YAML rows as overrides.
        deduped: dict[tuple[str, str, str], ReleaseCatalogEntry] = {}
        for entry in entries:
            key = (
                entry.product_id.casefold(),
                entry.programming_language.casefold(),
                entry.version.casefold(),
            )
            deduped[key] = entry
        self._entries = tuple(deduped.values())
        self._by_key = deduped

    @classmethod
    def from_config_file(cls, *, config_path: Path) -> ReleaseCatalog:
        if not config_path.exists():
            return cls(entries=())
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            msg = "Release catalog config must be a JSON object."
            raise ValueError(msg)
        raw_entries = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            msg = "Release catalog `entries` must be a JSON array."
            raise ValueError(msg)
        entries: list[ReleaseCatalogEntry] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            published_at = _parse_published_at(raw_entry.get("published_at"))
            entries.append(
                ReleaseCatalogEntry(
                    product_id=_required_str(raw_entry, "product_id"),
                    programming_language=_required_str(raw_entry, "programming_language"),
                    version=_required_str(raw_entry, "version"),
                    published_at=published_at,
                    channel=_optional_str(raw_entry.get("channel")) or "stable",
                    label=_optional_str(raw_entry.get("label")),
                )
            )
        return cls(entries=tuple(entries))

    def resolve(
        self,
        *,
        product_id: str,
        programming_language: str,
        version: str | None,
    ) -> ReleaseCatalogEntry | None:
        normalized_product = product_id.casefold()
        normalized_language = programming_language.casefold()
        normalized_version = (version or "").strip().casefold()
        if normalized_version:
            exact = self._by_key.get(
                (normalized_product, normalized_language, normalized_version)
            )
            if exact is not None:
                return exact
        if normalized_version in {"", "latest-stable"}:
            latest_alias = self._by_key.get(
                (normalized_product, normalized_language, "latest-stable")
            )
            if latest_alias is not None:
                return latest_alias
            return self.latest_for(
                product_id=product_id,
                programming_language=programming_language,
            )
        return None

    def latest_for(
        self,
        *,
        product_id: str,
        programming_language: str,
    ) -> ReleaseCatalogEntry | None:
        matches = [
            entry
            for entry in self._entries
            if entry.product_id.casefold() == product_id.casefold()
            and entry.programming_language.casefold() == programming_language.casefold()
        ]
        if not matches:
            return None
        return max(matches, key=lambda entry: (entry.published_at, entry.version))

    def has_entries(self) -> bool:
        return bool(self._entries)


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Release catalog entry field `{key}` must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_published_at(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        msg = "Release catalog entry `published_at` must be a non-empty ISO datetime string."
        raise ValueError(msg)
    normalized = value.strip()
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
