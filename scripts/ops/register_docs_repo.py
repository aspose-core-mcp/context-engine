#!/usr/bin/env python
"""Register a Documentation / API-Reference repo in the source registry.

Inserts a new repository entry into ``config/source-repositories.yaml`` without
reformatting the rest of the file (it splices the entry in just before the first
top-level key that follows ``repositories:``), then validates the registry still
loads. Idempotent: a repo_id that is already present is left untouched.

This is the "make ingestion work for any repo" onboarding helper — combine it
with a clone of the source into ``source-repo-docs/<family_dir>`` and an
ingestion run (the orchestrator skips unregistered repos rather than crashing,
so registering is the one required step).

Usage:
  PYTHONPATH=src .venv/bin/python scripts/ops/register_docs_repo.py \
      --product-id aspose.3d --product-name Aspose.3D --family-dir Aspose.3D \
      --git-url https://github.com/aspose-3d/Aspose.3D-Doc-md.git \
      --layout-type doc_locale/programming_language/content

Note: docs repos use `-Documentation` for most products but `-Doc-md` for some
(e.g. Cells, 3D); pass the verified --git-url explicitly.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from adcs.ingestion.source_registry import SourceRegistryService

_REGISTRY = Path("config/source-repositories.yaml")
_TOP_LEVEL_KEY = re.compile(r"^[a-z_][a-z0-9_]*:")


def build_entry(
    *,
    product_id: str,
    product_name: str,
    family_dir: str,
    git_url: str,
    layout_type: str,
    source_kind: str,
) -> dict[str, object]:
    return {
        "repo_id": f"{product_id}.{source_kind}",
        "product_id": product_id,
        "product_name": product_name,
        "product_family": product_id.split(".", 1)[0],
        "product_family_dir": family_dir,
        "source_kind": source_kind,
        "format": "hugo-md",
        "git": {
            "provider": "github",
            "url": git_url,
            "submodule_path": f"source-repo-{source_kind}/{family_dir}",
            "default_branch": "master",
        },
        "layout_detection": {
            "status": "detected",
            "detector_version": "layout-detector.v1",
            "layout_type": layout_type,
            "confidence": 0.9,
        },
        "ingestion": {
            "latest_stable_only": True,
            "enabled": True,
            "triggers": ["webhook", "admin_button"],
            "incremental_diff_preferred": True,
            "fallback_strategy": "full_reindex",
        },
    }


def insert_entry(registry_path: Path, entry: dict[str, object]) -> bool:
    """Splice ``entry`` into the repositories list; return False if already present."""
    text = registry_path.read_text(encoding="utf-8")
    if f"repo_id: {entry['repo_id']}\n" in text:
        return False
    lines = text.splitlines(keepends=True)
    repos_idx = next(i for i, ln in enumerate(lines) if ln.startswith("repositories:"))
    # End of the repositories list = first top-level key after it (or EOF).
    end_idx = len(lines)
    for i in range(repos_idx + 1, len(lines)):
        if _TOP_LEVEL_KEY.match(lines[i]):
            end_idx = i
            break
    block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True)
    if not block.endswith("\n"):
        block += "\n"
    lines.insert(end_idx, block)
    registry_path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--family-dir", required=True)
    parser.add_argument("--git-url", required=True)
    parser.add_argument(
        "--layout-type", default="doc_locale/programming_language/content"
    )
    parser.add_argument("--source-kind", default="docs", choices=["docs", "apiref"])
    parser.add_argument("--registry", default=str(_REGISTRY))
    args = parser.parse_args()

    registry_path = Path(args.registry)
    entry = build_entry(
        product_id=args.product_id,
        product_name=args.product_name,
        family_dir=args.family_dir,
        git_url=args.git_url,
        layout_type=args.layout_type,
        source_kind=args.source_kind,
    )
    inserted = insert_entry(registry_path, entry)
    print(f"{'inserted' if inserted else 'already present'}: {entry['repo_id']}")

    # Validate the registry still loads.
    service = SourceRegistryService(
        registry_path=registry_path, workspace_root=Path(".")
    )
    repo = service.get_repository(str(entry["repo_id"]))
    print(f"validated: {repo.repo_id} ({len(service.list_repositories())} repos total)")


if __name__ == "__main__":
    main()
