"""Deterministic canonical URL remap registry for ingestion and publish flows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

_SCHEMA_VERSION = 1

_LEGACY_URL_KEYS = (
    "canonical_url_old",
    "old_canonical_url",
    "legacy_canonical_url",
)
_LEGACY_URL_LIST_KEYS = (
    "canonical_url_aliases",
    "legacy_canonical_urls",
)


@dataclass(frozen=True, slots=True)
class CanonicalUrlMappingContext:
    """Context key for remap registry segregation."""

    product_id: str
    source_kind: str
    programming_language: str
    version: str

    @property
    def context_id(self) -> str:
        return (
            f"{self.product_id}/{self.source_kind}/"
            f"{self.programming_language}/{self.version}"
        )

    @classmethod
    def from_values(
        cls,
        *,
        product_id: str,
        source_kind: str,
        programming_language: str,
        version: str,
    ) -> CanonicalUrlMappingContext:
        return cls(
            product_id=_normalize_context_part(product_id),
            source_kind=_normalize_context_part(source_kind),
            programming_language=_normalize_context_part(programming_language),
            version=_normalize_context_part(version),
        )


@dataclass(frozen=True, slots=True)
class CanonicalUrlMappingConflict:
    """Conflict details for competing old->new canonical URL mappings."""

    context_id: str
    source_path: str
    old_url: str
    existing_new_url: str
    incoming_new_url: str
    conflict_type: str


class CanonicalUrlMappingRegistry:
    """Mutable remap registry with deterministic precedence and conflict handling."""

    def __init__(
        self,
        *,
        context: CanonicalUrlMappingContext,
        canonical_base_url: str,
        initial_mappings: Mapping[str, str] | None = None,
    ) -> None:
        self._context = context
        self._canonical_base_url = canonical_base_url.rstrip("/")
        self._mappings: dict[str, str] = dict(initial_mappings or {})
        self._persisted_keys: set[str] = set(self._mappings)
        self._overridden_persisted_keys: set[str] = set()
        self._dirty = False

    @property
    def context(self) -> CanonicalUrlMappingContext:
        return self._context

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def entries_count(self) -> int:
        return len(self._mappings)

    def mappings(self) -> tuple[tuple[str, str], ...]:
        return tuple((old_url, self._mappings[old_url]) for old_url in sorted(self._mappings))

    def register_mappings(
        self,
        *,
        remap_pairs: Sequence[tuple[str, str]],
        source_path: str,
    ) -> tuple[CanonicalUrlMappingConflict, ...]:
        conflicts: list[CanonicalUrlMappingConflict] = []
        for old_url, new_url in remap_pairs:
            conflict = self.register_mapping(
                old_url=old_url,
                new_url=new_url,
                source_path=source_path,
            )
            if conflict is not None:
                conflicts.append(conflict)
        return tuple(conflicts)

    def register_mapping(
        self,
        *,
        old_url: str,
        new_url: str,
        source_path: str,
    ) -> CanonicalUrlMappingConflict | None:
        normalized_old = normalize_canonical_url(
            old_url,
            canonical_base_url=self._canonical_base_url,
        )
        normalized_new = normalize_canonical_url(
            new_url,
            canonical_base_url=self._canonical_base_url,
        )
        if normalized_old == normalized_new:
            return None

        existing = self._mappings.get(normalized_old)
        if existing is None:
            self._mappings[normalized_old] = normalized_new
            self._dirty = True
            return None
        if existing == normalized_new:
            return None

        # Precedence:
        # 1) First current-run mapping may override persisted value.
        # 2) Subsequent conflicting mappings are rejected as deterministic conflicts.
        conflict_type = "conflicting_mapping"
        if (
            normalized_old in self._persisted_keys
            and normalized_old not in self._overridden_persisted_keys
        ):
            self._mappings[normalized_old] = normalized_new
            self._overridden_persisted_keys.add(normalized_old)
            self._dirty = True
            conflict_type = "override_persisted"

        return CanonicalUrlMappingConflict(
            context_id=self._context.context_id,
            source_path=source_path,
            old_url=normalized_old,
            existing_new_url=existing,
            incoming_new_url=normalized_new,
            conflict_type=conflict_type,
        )

    def resolve(self, url: str) -> str:
        current_url = normalize_canonical_url(
            url,
            canonical_base_url=self._canonical_base_url,
        )
        visited: set[str] = set()
        while current_url in self._mappings:
            if current_url in visited:
                break
            visited.add(current_url)
            next_url = self._mappings[current_url]
            if next_url == current_url:
                break
            current_url = next_url
        return current_url


class FileSystemCanonicalUrlMappingStore:
    """File-backed canonical URL mapping registry store."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        canonical_base_url: str = "https://docs.aspose.com",
    ) -> None:
        self._workspace_root = workspace_root or Path(__file__).resolve().parents[3]
        self._artifact_root = (
            self._workspace_root
            / "artifacts"
            / "runtime-safe"
            / "canonical-url-mapping"
        ).resolve()
        self._legacy_artifact_root = (
            self._workspace_root / "artifacts" / "canonical-url-mapping"
        ).resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._canonical_base_url = canonical_base_url.rstrip("/")
        self._lock = Lock()

    def load(self, *, context: CanonicalUrlMappingContext) -> CanonicalUrlMappingRegistry:
        mapping_path = self._mapping_path(context=context)
        if mapping_path.exists():
            payload = _read_mapping_payload(mapping_path)
        else:
            legacy_mapping_path = self._legacy_mapping_path(context=context)
            if not legacy_mapping_path.exists():
                return CanonicalUrlMappingRegistry(
                    context=context,
                    canonical_base_url=self._canonical_base_url,
                    initial_mappings={},
                )
            payload = _read_mapping_payload(legacy_mapping_path)

        mappings = _parse_mapping_payload(payload)
        return CanonicalUrlMappingRegistry(
            context=context,
            canonical_base_url=self._canonical_base_url,
            initial_mappings=mappings,
        )

    def save(self, *, registry: CanonicalUrlMappingRegistry) -> None:
        mapping_path = self._mapping_path(context=registry.context)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "context": {
                "product_id": registry.context.product_id,
                "source_kind": registry.context.source_kind,
                "programming_language": registry.context.programming_language,
                "version": registry.context.version,
            },
            "mappings": [
                {"old_url": old_url, "new_url": new_url}
                for old_url, new_url in registry.mappings()
            ],
        }
        encoded_payload = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        temporary_path = mapping_path.with_suffix(".tmp")
        with self._lock:
            temporary_path.write_text(encoded_payload, encoding="utf-8")
            temporary_path.replace(mapping_path)

    def _mapping_path(self, *, context: CanonicalUrlMappingContext) -> Path:
        product_id = context.product_id.replace("/", "__")
        source_kind = context.source_kind.replace("/", "__")
        programming_language = context.programming_language.replace("/", "__")
        version = context.version.replace("/", "__")
        return (
            self._artifact_root
            / product_id
            / source_kind
            / programming_language
            / f"{version}.json"
        )

    def _legacy_mapping_path(self, *, context: CanonicalUrlMappingContext) -> Path:
        product_id = context.product_id.replace("/", "__")
        source_kind = context.source_kind.replace("/", "__")
        programming_language = context.programming_language.replace("/", "__")
        version = context.version.replace("/", "__")
        return (
            self._legacy_artifact_root
            / product_id
            / source_kind
            / programming_language
            / f"{version}.json"
        )


def _read_mapping_payload(path: Path) -> object:
    try:
        payload_raw = path.read_text(encoding="utf-8")
        return json.loads(payload_raw)
    except (OSError, json.JSONDecodeError):
        # Safe fallback: treat corrupt payload as missing to keep ingestion deterministic.
        return {}


def extract_metadata_remap_pairs(
    *,
    metadata: Mapping[str, object],
    resolved_canonical_url: str,
    canonical_base_url: str,
) -> tuple[tuple[str, str], ...]:
    """Extract optional old->new remap pairs from metadata/frontmatter."""
    pairs: set[tuple[str, str]] = set()
    normalized_target = normalize_canonical_url(
        resolved_canonical_url,
        canonical_base_url=canonical_base_url,
    )

    for key in _LEGACY_URL_KEYS:
        raw_value = metadata.get(key)
        if raw_value is None:
            continue
        if not isinstance(raw_value, str) or not raw_value.strip():
            msg = f"`{key}` must be a non-empty string when provided."
            raise ValueError(msg)
        pairs.add(
            (
                normalize_canonical_url(raw_value, canonical_base_url=canonical_base_url),
                normalized_target,
            )
        )

    for key in _LEGACY_URL_LIST_KEYS:
        raw_value = metadata.get(key)
        if raw_value is None:
            continue
        if not isinstance(raw_value, list):
            msg = f"`{key}` must be a list of URLs when provided."
            raise ValueError(msg)
        for index, item in enumerate(raw_value):
            if not isinstance(item, str) or not item.strip():
                msg = f"`{key}[{index}]` must be a non-empty string."
                raise ValueError(msg)
            pairs.add(
                (
                    normalize_canonical_url(item, canonical_base_url=canonical_base_url),
                    normalized_target,
                )
            )

    explicit_remap = metadata.get("canonical_url_remap")
    if explicit_remap is None:
        return tuple(sorted(pair for pair in pairs if pair[0] != pair[1]))

    if isinstance(explicit_remap, Mapping):
        for raw_old_url, raw_new_url in explicit_remap.items():
            if not isinstance(raw_old_url, str) or not raw_old_url.strip():
                msg = "`canonical_url_remap` keys must be non-empty strings."
                raise ValueError(msg)
            if not isinstance(raw_new_url, str) or not raw_new_url.strip():
                msg = "`canonical_url_remap` values must be non-empty strings."
                raise ValueError(msg)
            pairs.add(
                (
                    normalize_canonical_url(raw_old_url, canonical_base_url=canonical_base_url),
                    normalize_canonical_url(raw_new_url, canonical_base_url=canonical_base_url),
                )
            )
    elif isinstance(explicit_remap, list):
        for index, item in enumerate(explicit_remap):
            if not isinstance(item, Mapping):
                msg = f"`canonical_url_remap[{index}]` must be an object."
                raise ValueError(msg)
            raw_old_url = item.get("old")
            raw_new_url = item.get("new")
            if not isinstance(raw_old_url, str) or not raw_old_url.strip():
                msg = f"`canonical_url_remap[{index}].old` must be a non-empty string."
                raise ValueError(msg)
            if not isinstance(raw_new_url, str) or not raw_new_url.strip():
                msg = f"`canonical_url_remap[{index}].new` must be a non-empty string."
                raise ValueError(msg)
            pairs.add(
                (
                    normalize_canonical_url(raw_old_url, canonical_base_url=canonical_base_url),
                    normalize_canonical_url(raw_new_url, canonical_base_url=canonical_base_url),
                )
            )
    else:
        msg = "`canonical_url_remap` must be an object or list when provided."
        raise ValueError(msg)

    return tuple(sorted(pair for pair in pairs if pair[0] != pair[1]))


def normalize_canonical_url(url: str, *, canonical_base_url: str) -> str:
    """Normalize canonical URL to deterministic absolute form."""
    normalized = url.strip()
    if not normalized:
        msg = "canonical URL must not be empty."
        raise ValueError(msg)
    if any(character.isspace() for character in normalized):
        msg = f"canonical URL contains whitespace: `{url}`."
        raise ValueError(msg)

    if normalized.startswith(("http://", "https://")):
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = f"canonical URL is invalid: `{url}`."
            raise ValueError(msg)
        path = parsed.path or "/"
        if path != "/" and not path.endswith("/"):
            path = f"{path}/"
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    base_url = canonical_base_url.rstrip("/")
    if normalized.startswith("/"):
        absolute = f"{base_url}{normalized}"
    else:
        absolute = f"{base_url}/{normalized}"
    return normalize_canonical_url(absolute, canonical_base_url=canonical_base_url)


def _parse_mapping_payload(payload: object) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        return {}
    schema_version = payload.get("schema_version")
    if schema_version != _SCHEMA_VERSION:
        return {}

    raw_mappings = payload.get("mappings")
    if not isinstance(raw_mappings, list):
        return {}

    mappings: dict[str, str] = {}
    for item in raw_mappings:
        if not isinstance(item, Mapping):
            continue
        raw_old_url = item.get("old_url")
        raw_new_url = item.get("new_url")
        if not isinstance(raw_old_url, str) or not isinstance(raw_new_url, str):
            continue
        old_url = raw_old_url.strip()
        new_url = raw_new_url.strip()
        if not old_url or not new_url:
            continue
        mappings[old_url] = new_url
    return dict(sorted(mappings.items(), key=lambda entry: entry[0]))


def _normalize_context_part(value: str) -> str:
    normalized = value.strip().casefold()
    return normalized if normalized else "unknown"
