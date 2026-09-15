from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from adcs.ingestion.source_registry import SourceRegistryService, SourceRegistryValidationError


def _make_valid_registry_payload() -> dict[str, Any]:
    return {
        "source_roots": [
            {"root_id": "apiref-root", "source_kind": "apiref", "path": "source-repo-apiref"},
            {"root_id": "docs-root", "source_kind": "docs", "path": "source-repo-docs"},
        ],
        "repositories": [
            {
                "repo_id": "aspose.ocr.apiref",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "apiref",
                "git": {
                    "url": "https://example.com/aspose.ocr.apiref.git",
                    "submodule_path": "source-repo-apiref/Aspose.OCR",
                    "default_branch": "main",
                },
            },
            {
                "repo_id": "aspose.ocr.docs",
                "product_id": "aspose.ocr",
                "product_family": "aspose",
                "product_family_dir": "Aspose.OCR",
                "source_kind": "docs",
                "git": {
                    "url": "https://example.com/aspose.ocr.docs.git",
                    "submodule_path": "source-repo-docs/Aspose.OCR",
                    "default_branch": "master",
                },
            },
        ],
    }


def _create_source_roots(tmp_path: Path) -> None:
    (tmp_path / "source-repo-apiref" / "Aspose.OCR").mkdir(parents=True)
    (tmp_path / "source-repo-docs" / "Aspose.OCR").mkdir(parents=True)


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def _write_registry_yaml(tmp_path: Path, payload: dict[str, Any]) -> Path:
    registry_path = tmp_path / "config" / "source-repositories.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, default_flow_style=False),
        encoding="utf-8",
    )
    return registry_path


def _write_gitmodules(tmp_path: Path, submodule_paths: list[str]) -> None:
    lines: list[str] = []
    for index, submodule_path in enumerate(submodule_paths):
        name = f"lazy-{index}"
        lines.extend(
            [
                f'[submodule "{name}"]',
                f"\tpath = {submodule_path}",
                f"\turl = https://example.com/{name}.git",
            ]
        )
    (tmp_path / ".gitmodules").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_source_registry_loads_valid_registry_and_lists_repo_ids(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    _create_source_roots(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    service = SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)

    assert service.list_repo_ids() == ("aspose.ocr.apiref", "aspose.ocr.docs")
    assert [repo.repo_id for repo in service.list_repositories()] == [
        "aspose.ocr.apiref",
        "aspose.ocr.docs",
    ]
    assert service.get_repository("aspose.ocr.docs").git.submodule_path == Path(
        "source-repo-docs/Aspose.OCR"
    )


def test_source_registry_rejects_missing_required_repo_field(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    payload["repositories"][0].pop("product_id")
    _create_source_roots(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    with pytest.raises(SourceRegistryValidationError, match=r"missing required field `product_id`"):
        SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)


def test_source_registry_rejects_duplicate_repo_id(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    payload["repositories"][1]["repo_id"] = payload["repositories"][0]["repo_id"]
    _create_source_roots(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    with pytest.raises(SourceRegistryValidationError, match=r"duplicate `repo_id`"):
        SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)


def test_source_registry_rejects_missing_submodule_path(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    payload["repositories"][0]["git"]["submodule_path"] = "source-repo-apiref/Aspose.OCR-MISSING"
    _create_source_roots(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    # Pin ``validate_submodule_paths=True`` explicitly: this test asserts the
    # on-disk existence check fires. Relying on the ambient
    # ``ADCS_VALIDATE_SOURCE_SUBMODULES`` default makes it order-dependent — if an
    # earlier test leaks ``false`` into the process env, the existence check is
    # skipped and the later ``product_family_dir`` tail-match raises instead.
    with pytest.raises(SourceRegistryValidationError, match=r"submodule path does not exist"):
        SourceRegistryService(
            registry_path=registry_path,
            workspace_root=tmp_path,
            validate_submodule_paths=True,
        )


def test_source_registry_rejects_submodule_path_outside_source_root(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    payload["repositories"][1]["git"]["submodule_path"] = "source-repo-apiref/Aspose.OCR"
    _create_source_roots(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    with pytest.raises(SourceRegistryValidationError, match=r"is not inside source root"):
        SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)


def test_source_registry_loads_yaml_registry(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    _create_source_roots(tmp_path)
    registry_path = _write_registry_yaml(tmp_path, payload)

    service = SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)

    assert service.list_repo_ids() == ("aspose.ocr.apiref", "aspose.ocr.docs")


def test_source_registry_accepts_lazy_registered_submodule_path(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    _create_source_roots(tmp_path)
    payload["repositories"][0]["product_family_dir"] = "Aspose.Slides"
    payload["repositories"][0]["git"]["submodule_path"] = "source-repo-apiref/Aspose.Slides"
    payload["repositories"][0]["git"]["materialization_state"] = "lazy_registered"
    _write_gitmodules(tmp_path, ["source-repo-apiref/Aspose.Slides"])
    registry_path = _write_registry_yaml(tmp_path, payload)

    service = SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)

    assert "aspose.ocr.apiref" in service.list_repo_ids()


def _create_source_roots_only(tmp_path: Path) -> None:
    # Roots exist (so source-root validation passes) but the per-repo submodule
    # dirs do NOT — mirrors a serving node without the source submodules.
    (tmp_path / "source-repo-apiref").mkdir(parents=True)
    (tmp_path / "source-repo-docs").mkdir(parents=True)


def test_submodule_validation_can_be_skipped_for_serving(tmp_path: Path) -> None:
    payload = _make_valid_registry_payload()
    _create_source_roots_only(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    # Default validates → missing submodule dirs are rejected.
    with pytest.raises(SourceRegistryValidationError):
        SourceRegistryService(
            registry_path=registry_path, workspace_root=tmp_path, validate_submodule_paths=True
        )

    # Serving mode skips the on-disk submodule check → loads fine.
    service = SourceRegistryService(
        registry_path=registry_path, workspace_root=tmp_path, validate_submodule_paths=False
    )
    assert service.list_repo_ids() == ("aspose.ocr.apiref", "aspose.ocr.docs")


def test_submodule_validation_honors_env_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _make_valid_registry_payload()
    _create_source_roots_only(tmp_path)
    registry_path = _write_registry(tmp_path, payload)

    monkeypatch.setenv("ADCS_VALIDATE_SOURCE_SUBMODULES", "false")
    # No explicit param → env flag controls it.
    service = SourceRegistryService(registry_path=registry_path, workspace_root=tmp_path)
    assert service.list_repo_ids() == ("aspose.ocr.apiref", "aspose.ocr.docs")
