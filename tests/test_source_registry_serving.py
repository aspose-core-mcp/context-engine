from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from adcs.ingestion.source_registry import (
    SourceRegistryService,
    SourceRegistryValidationError,
)

_REPO = Path(__file__).resolve().parents[1]
_REGISTRY = _REPO / "config" / "source-repositories.yaml"


def _serving_workspace(tmp_path: Path) -> Path:
    """A workspace with the source ROOT dirs present but no submodule checkouts.

    Mirrors a serving node: it has the registry + .gitmodules but not the 37 GB
    of source submodules.
    """
    shutil.copy(_REPO / ".gitmodules", tmp_path / ".gitmodules")
    (tmp_path / "source-repo-docs").mkdir()
    (tmp_path / "source-repo-apiref").mkdir()
    return tmp_path


def test_serving_skips_submodule_existence(tmp_path: Path) -> None:
    service = SourceRegistryService(
        registry_path=_REGISTRY,
        workspace_root=_serving_workspace(tmp_path),
        validate_submodule_paths=False,
    )
    assert service.list_repositories()  # loads despite missing submodule dirs


def test_default_requires_submodule_paths(tmp_path: Path) -> None:
    with pytest.raises(SourceRegistryValidationError):
        SourceRegistryService(
            registry_path=_REGISTRY,
            workspace_root=_serving_workspace(tmp_path),
            validate_submodule_paths=True,
        )


def test_env_flag_controls_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADCS_VALIDATE_SOURCE_SUBMODULES", "false")
    service = SourceRegistryService(
        registry_path=_REGISTRY, workspace_root=_serving_workspace(tmp_path)
    )
    assert service.list_repositories()
