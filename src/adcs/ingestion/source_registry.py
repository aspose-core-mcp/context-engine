"""Source registry loading and validation service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class SourceRegistryValidationError(ValueError):
    """Raised when source registry YAML/JSON is structurally or semantically invalid."""


class SourceRegistryLookupError(KeyError):
    """Raised when a repository lookup is requested for an unknown repo_id."""


@dataclass(frozen=True, slots=True)
class SourceGitConfig:
    """Validated git metadata for a source repository."""

    url: str
    submodule_path: Path
    default_branch: str


@dataclass(frozen=True, slots=True)
class IngestionScopeConfig:
    """Optional scope filters applied during ingestion file discovery."""

    doc_locale_filter: tuple[str, ...] = ()

    @property
    def has_locale_filter(self) -> bool:
        return len(self.doc_locale_filter) > 0


@dataclass(frozen=True, slots=True)
class SourceRepository:
    """Validated source repository descriptor."""

    repo_id: str
    product_id: str
    product_name: str | None
    product_family: str
    product_family_dir: str
    source_kind: str
    git: SourceGitConfig
    layout_detection: dict[str, Any] | None
    onboarding_programming_languages: tuple[str, ...]
    ingestion_scope: IngestionScopeConfig = IngestionScopeConfig()


@dataclass(frozen=True, slots=True)
class _SourceRoot:
    source_kind: str
    path: Path


class SourceRegistryService:
    """Load and validate source repository registry for runtime ingestion usage."""

    def __init__(
        self,
        registry_path: str | Path | None = None,
        *,
        workspace_root: str | Path | None = None,
        validate_submodule_paths: bool | None = None,
    ) -> None:
        # Serving-only nodes don't carry the source submodules (37 GB); skip the
        # on-disk submodule existence check there. Defaults to env
        # ADCS_VALIDATE_SOURCE_SUBMODULES (true) so every construction honors it.
        self._validate_submodule_paths = (
            _env_flag("ADCS_VALIDATE_SOURCE_SUBMODULES", default=True)
            if validate_submodule_paths is None
            else validate_submodule_paths
        )
        raw_registry_path = (
            Path("config/source-repositories.yaml")
            if registry_path is None
            else Path(registry_path)
        )
        resolved_registry_path = raw_registry_path
        if not resolved_registry_path.is_absolute():
            resolved_registry_path = (Path.cwd() / resolved_registry_path).resolve()
        if registry_path is None and not resolved_registry_path.exists():
            fallback = (Path.cwd() / "config/source-repositories.json").resolve()
            if fallback.exists():
                resolved_registry_path = fallback
        self._registry_path = resolved_registry_path
        self._workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else self._registry_path.parent.parent.resolve()
        )

        self._repositories = self._load_and_validate()
        self._repositories_by_id = {
            repository.repo_id: repository for repository in self._repositories
        }

    def list_repositories(self) -> tuple[SourceRepository, ...]:
        """Return all validated repositories in registry order."""
        return self._repositories

    @property
    def registry_path(self) -> Path:
        """Return resolved path to the primary registry file."""
        return self._registry_path

    @property
    def workspace_root(self) -> Path:
        """Return resolved workspace root used for source path validation."""
        return self._workspace_root

    def list_repo_ids(self) -> tuple[str, ...]:
        """Return validated repository ids in registry order."""
        return tuple(repository.repo_id for repository in self._repositories)

    def get_repository(self, repo_id: str) -> SourceRepository:
        """Return a validated repository descriptor by repo_id."""
        try:
            return self._repositories_by_id[repo_id]
        except KeyError as exc:
            msg = f"Source registry lookup failed: unknown repo_id `{repo_id}`."
            raise SourceRegistryLookupError(msg) from exc

    def _load_and_validate(self) -> tuple[SourceRepository, ...]:
        payload = self._load_registry_payload()

        source_roots_payload = payload.get("source_roots")
        if not isinstance(source_roots_payload, list) or not source_roots_payload:
            msg = "Invalid source registry: `source_roots` must be a non-empty array."
            raise SourceRegistryValidationError(msg)

        repositories_payload = payload.get("repositories")
        if not isinstance(repositories_payload, list):
            msg = "Invalid source registry: `repositories` must be an array."
            raise SourceRegistryValidationError(msg)

        source_roots_by_kind = self._validate_source_roots(source_roots_payload)
        return self._validate_repositories(repositories_payload, source_roots_by_kind)

    def _load_registry_payload(self) -> dict[str, Any]:
        if not self._registry_path.exists():
            msg = f"Invalid source registry: file not found at `{self._registry_path}`."
            raise SourceRegistryValidationError(msg)

        try:
            raw_payload = self._registry_path.read_text(encoding="utf-8")
            suffix = self._registry_path.suffix.casefold()
            if suffix == ".json":
                payload = json.loads(raw_payload)
            elif suffix in {".yaml", ".yml"}:
                payload = yaml.safe_load(raw_payload)
            else:
                msg = (
                    "Invalid source registry: unsupported extension. "
                    "Use `.yaml`, `.yml`, or `.json`."
                )
                raise SourceRegistryValidationError(msg)
        except json.JSONDecodeError as exc:
            msg = (
                "Invalid source registry: JSON decode failed at "
                f"line {exc.lineno}, column {exc.colno}."
            )
            raise SourceRegistryValidationError(msg) from exc
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            if mark is None:
                msg = "Invalid source registry: YAML decode failed."
            else:
                msg = (
                    "Invalid source registry: YAML decode failed at "
                    f"line {mark.line + 1}, column {mark.column + 1}."
                )
            raise SourceRegistryValidationError(msg) from exc

        if not isinstance(payload, dict):
            msg = "Invalid source registry: top-level value must be an object."
            raise SourceRegistryValidationError(msg)

        return payload

    def _validate_source_roots(self, source_roots_payload: list[Any]) -> dict[str, _SourceRoot]:
        source_roots_by_kind: dict[str, _SourceRoot] = {}
        for index, item in enumerate(source_roots_payload):
            context = f"source_roots[{index}]"
            if not isinstance(item, dict):
                msg = f"Invalid source registry: `{context}` must be an object."
                raise SourceRegistryValidationError(msg)

            source_kind = _read_required_non_empty_string(item, "source_kind", context)
            root_path = Path(_read_required_non_empty_string(item, "path", context))
            absolute_root_path = (self._workspace_root / root_path).resolve()
            if not absolute_root_path.exists():
                msg = (
                    "Invalid source registry: "
                    f"`{context}.path` does not exist at `{root_path.as_posix()}`."
                )
                raise SourceRegistryValidationError(msg)

            if source_kind in source_roots_by_kind:
                msg = (
                    "Invalid source registry: duplicate `source_kind` "
                    f"in source_roots: `{source_kind}`."
                )
                raise SourceRegistryValidationError(msg)

            source_roots_by_kind[source_kind] = _SourceRoot(source_kind=source_kind, path=root_path)

        return source_roots_by_kind

    def _validate_repositories(
        self,
        repositories_payload: list[Any],
        source_roots_by_kind: dict[str, _SourceRoot],
    ) -> tuple[SourceRepository, ...]:
        validated_repositories: list[SourceRepository] = []
        seen_repo_ids: set[str] = set()

        # Pre-compute shared lookups once to avoid O(N) re-parsing per repository.
        registered_submodule_paths = self._registered_submodule_paths()
        materialization_states = _extract_materialization_states(repositories_payload)

        for index, item in enumerate(repositories_payload):
            context = f"repositories[{index}]"
            if not isinstance(item, dict):
                msg = f"Invalid source registry: `{context}` must be an object."
                raise SourceRegistryValidationError(msg)

            repo_id = _read_required_non_empty_string(item, "repo_id", context)
            if repo_id in seen_repo_ids:
                msg = f"Invalid source registry: duplicate `repo_id` `{repo_id}`."
                raise SourceRegistryValidationError(msg)
            seen_repo_ids.add(repo_id)

            product_id = _read_required_non_empty_string(item, "product_id", context)
            product_name = _read_optional_non_empty_string(item, "product_name")
            product_family = _read_required_non_empty_string(item, "product_family", context)
            product_family_dir = _read_required_non_empty_string(
                item,
                "product_family_dir",
                context,
            )
            source_kind = _read_required_non_empty_string(item, "source_kind", context)

            source_root = source_roots_by_kind.get(source_kind)
            if source_root is None:
                msg = (
                    "Invalid source registry: repository "
                    f"`{repo_id}` has unknown `source_kind` `{source_kind}`."
                )
                raise SourceRegistryValidationError(msg)

            git_payload = item.get("git")
            if not isinstance(git_payload, dict):
                msg = f"Invalid source registry: `{context}.git` must be an object."
                raise SourceRegistryValidationError(msg)

            git_context = f"{context}.git"
            git_url = _read_required_non_empty_string(git_payload, "url", git_context)
            git_submodule_path = Path(
                _read_required_non_empty_string(git_payload, "submodule_path", git_context)
            )
            git_default_branch = _read_required_non_empty_string(
                git_payload,
                "default_branch",
                git_context,
            )
            layout_detection = _validate_optional_layout_detection(item, context)
            onboarding_programming_languages = _validate_optional_onboarding_languages(
                item,
                context,
            )
            ingestion_scope = _validate_optional_ingestion_scope(item)

            self._validate_submodule_path(
                repo_id=repo_id,
                source_root=source_root,
                product_family_dir=product_family_dir,
                git_submodule_path=git_submodule_path,
                registered_submodule_paths=registered_submodule_paths,
                materialization_state=materialization_states.get(repo_id, ""),
            )

            validated_repositories.append(
                SourceRepository(
                    repo_id=repo_id,
                    product_id=product_id,
                    product_name=product_name,
                    product_family=product_family,
                    product_family_dir=product_family_dir,
                    source_kind=source_kind,
                    git=SourceGitConfig(
                        url=git_url,
                        submodule_path=git_submodule_path,
                        default_branch=git_default_branch,
                    ),
                    layout_detection=layout_detection,
                    onboarding_programming_languages=onboarding_programming_languages,
                    ingestion_scope=ingestion_scope,
                )
            )

        return tuple(validated_repositories)

    def _registered_submodule_paths(self) -> set[str]:
        gitmodules_path = self._workspace_root / ".gitmodules"
        if not gitmodules_path.exists():
            return set()
        registered_paths: set[str] = set()
        current_name: str | None = None
        for raw_line in gitmodules_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("[submodule "):
                current_name = line.split('"')[1]
                continue
            if current_name and line.startswith("path = "):
                registered_paths.add(line.split("=", 1)[1].strip())
        return registered_paths

    def _validate_submodule_path(
        self,
        *,
        repo_id: str,
        source_root: _SourceRoot,
        product_family_dir: str,
        git_submodule_path: Path,
        registered_submodule_paths: set[str],
        materialization_state: str,
    ) -> None:
        if git_submodule_path.is_absolute():
            msg = (
                "Invalid source registry: repository "
                f"`{repo_id}` has absolute `git.submodule_path`; relative path expected."
            )
            raise SourceRegistryValidationError(msg)

        if not git_submodule_path.is_relative_to(source_root.path):
            msg = (
                "Invalid source registry: repository "
                f"`{repo_id}` submodule path `{git_submodule_path.as_posix()}` is not inside "
                f"source root `{source_root.path.as_posix()}` "
                f"for source_kind `{source_root.source_kind}`."
            )
            raise SourceRegistryValidationError(msg)

        absolute_submodule_path = (self._workspace_root / git_submodule_path).resolve()
        if self._validate_submodule_paths and not absolute_submodule_path.exists():
            if (
                materialization_state == "lazy_registered"
                and git_submodule_path.as_posix() in registered_submodule_paths
            ):
                pass
            else:
                msg = (
                    "Invalid source registry: repository "
                    f"`{repo_id}` submodule path does not exist at "
                    f"`{git_submodule_path.as_posix()}`."
                )
                raise SourceRegistryValidationError(msg)

        if git_submodule_path.name != product_family_dir:
            msg = (
                "Invalid source registry: repository "
                f"`{repo_id}` submodule path tail `{git_submodule_path.name}` does not match "
                f"`product_family_dir` `{product_family_dir}`."
            )
            raise SourceRegistryValidationError(msg)


def _read_required_non_empty_string(
    container: dict[str, Any],
    field_name: str,
    context: str,
) -> str:
    value = container.get(field_name)
    if not isinstance(value, str) or not value.strip():
        msg = f"Invalid source registry: `{context}` missing required field `{field_name}`."
        raise SourceRegistryValidationError(msg)
    return value.strip()


def _read_optional_non_empty_string(
    container: dict[str, Any],
    field_name: str,
) -> str | None:
    value = container.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        msg = f"Invalid source registry: `{field_name}` must be a non-empty string when provided."
        raise SourceRegistryValidationError(msg)
    return value.strip()


def _validate_optional_layout_detection(
    container: dict[str, Any],
    context: str,
) -> dict[str, Any] | None:
    layout_detection = container.get("layout_detection")
    if layout_detection is None:
        return None
    if not isinstance(layout_detection, dict):
        msg = f"Invalid source registry: `{context}.layout_detection` must be an object."
        raise SourceRegistryValidationError(msg)

    layout_type = layout_detection.get("layout_type")
    if layout_type is not None and (not isinstance(layout_type, str) or not layout_type.strip()):
        msg = (
            "Invalid source registry: "
            f"`{context}.layout_detection.layout_type` must be a non-empty string when provided."
        )
        raise SourceRegistryValidationError(msg)
    return dict(layout_detection)


def _validate_optional_onboarding_languages(
    container: dict[str, Any],
    context: str,
) -> tuple[str, ...]:
    onboarding_hints = container.get("onboarding_hints")
    if onboarding_hints is None:
        return ()
    if not isinstance(onboarding_hints, dict):
        msg = f"Invalid source registry: `{context}.onboarding_hints` must be an object."
        raise SourceRegistryValidationError(msg)

    raw_languages = onboarding_hints.get("programming_languages")
    if raw_languages is None:
        return ()
    if not isinstance(raw_languages, list):
        msg = (
            "Invalid source registry: "
            f"`{context}.onboarding_hints.programming_languages` must be an array."
        )
        raise SourceRegistryValidationError(msg)

    normalized_languages: list[str] = []
    seen_languages: set[str] = set()
    for index, value in enumerate(raw_languages):
        if not isinstance(value, str) or not value.strip():
            msg = (
                "Invalid source registry: "
                f"`{context}.onboarding_hints.programming_languages[{index}]` must be a "
                "non-empty string."
            )
            raise SourceRegistryValidationError(msg)
        normalized_value = value.strip()
        dedupe_key = normalized_value.casefold()
        if dedupe_key in seen_languages:
            continue
        seen_languages.add(dedupe_key)
        normalized_languages.append(normalized_value)
    return tuple(normalized_languages)


def _validate_optional_ingestion_scope(
    container: dict[str, Any],
) -> IngestionScopeConfig:
    ingestion = container.get("ingestion")
    if not isinstance(ingestion, dict):
        return IngestionScopeConfig()

    raw_locale_filter = ingestion.get("doc_locale_filter")
    if raw_locale_filter is None:
        return IngestionScopeConfig()

    if isinstance(raw_locale_filter, str):
        raw_locale_filter = [raw_locale_filter]

    if not isinstance(raw_locale_filter, list):
        return IngestionScopeConfig()

    locales = tuple(v.strip() for v in raw_locale_filter if isinstance(v, str) and v.strip())
    return IngestionScopeConfig(doc_locale_filter=locales)


def _extract_materialization_states(repositories_payload: list[Any]) -> dict[str, str]:
    """Build a repo_id -> materialization_state lookup from the raw repositories payload."""
    states: dict[str, str] = {}
    for repo in repositories_payload:
        if not isinstance(repo, dict):
            continue
        repo_id = repo.get("repo_id")
        if not isinstance(repo_id, str):
            continue
        git_payload = repo.get("git")
        if not isinstance(git_payload, dict):
            continue
        raw_state = git_payload.get("materialization_state")
        if isinstance(raw_state, str) and raw_state.strip():
            states[repo_id] = raw_state.strip()
    return states
