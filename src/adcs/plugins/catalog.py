"""Explicit, validated plugin registration and composition membership."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    path: str
    prefix: str
    layout: dict[str, object]
    canonical_base_url: str
    url: str
    branch: str = "main"

    @field_validator("path", "prefix")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if not value or Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("Source paths must be relative and contained")
        return value


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["adcs.extraction.v1"]
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    title: str = Field(min_length=1)
    worker: list[str] = Field(min_length=1)
    sources: dict[Literal["docs", "apiref"], SourceDefinition]

    @model_validator(mode="after")
    def valid_sources(self) -> PluginManifest:
        if not self.sources:
            raise ValueError("Extraction plugins require sources")
        ids = [source.repo_id for source in self.sources.values()]
        if len(set(ids)) != len(ids):
            raise ValueError("Source repository identities must be unique")
        return self


class Composition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition_id: str
    language: str
    members: list[str] = Field(min_length=1)
    owns_sources: Literal[False]


class PluginCatalog:
    def __init__(self, path: str | Path) -> None:
        path = Path(path).resolve()
        config = json.loads(path.read_text())
        self.plugins: dict[str, PluginManifest] = {}
        self.directories: dict[str, Path] = {}
        self.compositions: dict[str, Composition] = {}
        repository_ids: set[str] = set()
        for relative in config["plugins"]:
            manifest_path = (path.parent / relative).resolve()
            manifest = PluginManifest.model_validate_json(manifest_path.read_text())
            if manifest.plugin_id in self.plugins:
                raise ValueError("Duplicate plugin identity")
            ids = {source.repo_id for source in manifest.sources.values()}
            if ids & repository_ids:
                raise ValueError("Repository identities must be unique across plugins")
            repository_ids.update(ids)
            self.plugins[manifest.plugin_id] = manifest
            self.directories[manifest.plugin_id] = manifest_path.parent
        for relative in config.get("compositions", []):
            composition = Composition.model_validate_json((path.parent / relative).read_text())
            if composition.composition_id in self.plugins or (
                composition.composition_id in self.compositions
            ):
                raise ValueError("Duplicate composition identity")
            if len(set(composition.members)) != len(composition.members):
                raise ValueError("Duplicate composition member")
            for member in composition.members:
                if member not in self.plugins:
                    raise ValueError(f"Composition requires unregistered plugin: {member}")
                if self.plugins[member].language != composition.language:
                    raise ValueError("Composition cannot mix SDK platforms")
            self.compositions[composition.composition_id] = composition

    def extractor(self, plugin_id: str) -> PluginManifest:
        if plugin_id in self.compositions:
            raise ValueError("An aggregate has no extractor; ingest its members independently")
        if plugin_id not in self.plugins:
            raise ValueError(f"Plugin is not enabled: {plugin_id}")
        return self.plugins[plugin_id]

    def command(self, plugin_id: str, python: str | None = None) -> list[str]:
        manifest = self.extractor(plugin_id)
        return [
            argument.replace(
                "{python}", str(Path(python).expanduser().absolute()) if python else sys.executable
            ).replace("{plugin_dir}", str(self.directories[plugin_id]))
            for argument in manifest.worker
        ]
