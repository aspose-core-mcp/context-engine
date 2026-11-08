#!/usr/bin/env python3
"""Validate and sync source git submodules from registry config."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"Could not locate repository root from: {start}")


ROOT_DIR = find_repo_root(Path(__file__).resolve().parent)
DEFAULT_REGISTRY = ROOT_DIR / "config" / "source-repositories.yaml"
if not DEFAULT_REGISTRY.exists():
    DEFAULT_REGISTRY = ROOT_DIR / "config" / "source-repositories.json"


def run_command(cmd: list[str], cwd: Path, dry_run: bool) -> None:
    printable = " ".join(cmd)
    print(f"[cmd] ({cwd}) {printable}")
    if dry_run:
        return
    subprocess.run(cmd, cwd=cwd, check=True)


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Registry file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw_payload = handle.read()
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return json.loads(raw_payload)
    if suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("Registry payload must be a YAML object")
        return payload
    raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json")


def load_registered_submodule_paths(root_dir: Path) -> set[str]:
    gitmodules_path = root_dir / ".gitmodules"
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


def validate_registry_entries(
    repositories: list[dict[str, Any]], source_root_paths: set[str]
) -> list[dict[str, Any]]:
    required_top = (
        "repo_id",
        "product_id",
        "product_family",
        "product_family_dir",
        "source_kind",
        "git",
    )
    required_git = ("url", "submodule_path", "default_branch")

    validated: list[dict[str, Any]] = []
    seen_repo_ids: set[str] = set()
    registered_submodule_paths = load_registered_submodule_paths(ROOT_DIR)

    for repo in repositories:
        for field in required_top:
            if field not in repo:
                raise ValueError(f"Repository entry missing required field: {field}")

        repo_id = repo["repo_id"]
        if not isinstance(repo_id, str) or not repo_id:
            raise ValueError("Repository `repo_id` must be a non-empty string")
        if repo_id in seen_repo_ids:
            raise ValueError(f"Duplicate repository id: {repo_id}")
        seen_repo_ids.add(repo_id)

        git_meta = repo.get("git")
        if not isinstance(git_meta, dict):
            raise ValueError(f"`git` must be an object for repository: {repo_id}")
        for field in required_git:
            if field not in git_meta:
                raise ValueError(f"Repository `{repo_id}` git metadata missing: {field}")

        submodule_path = ROOT_DIR / git_meta["submodule_path"]
        submodule_path_rel = Path(git_meta["submodule_path"])
        materialization_state = ""
        raw_state = git_meta.get("materialization_state")
        if isinstance(raw_state, str):
            materialization_state = raw_state.strip()
        if not submodule_path.exists():
            if not (
                materialization_state == "lazy_registered"
                and submodule_path_rel.as_posix() in registered_submodule_paths
            ):
                raise ValueError(
                    f"Repository `{repo_id}` submodule path does not exist: {submodule_path}"
                )
        if str(submodule_path_rel.parent).replace("\\", "/") not in source_root_paths:
            raise ValueError(
                f"Repository `{repo_id}` submodule path parent is not declared in `source_roots`: "
                f"{submodule_path_rel.parent}"
            )
        if submodule_path_rel.name != repo["product_family_dir"]:
            raise ValueError(
                f"Repository `{repo_id}` submodule path tail must match `product_family_dir`: "
                f"{submodule_path_rel.name} != {repo['product_family_dir']}"
            )

        validated.append(repo)

    return validated


def select_repositories(
    repositories: list[dict[str, Any]], repo_ids: set[str] | None
) -> list[dict[str, Any]]:
    if not repo_ids:
        return repositories

    selected = [repo for repo in repositories if repo["repo_id"] in repo_ids]
    selected_ids = {repo["repo_id"] for repo in selected}
    missing = repo_ids - selected_ids
    if missing:
        raise ValueError(f"Requested repo_id not found in registry: {sorted(missing)}")
    return selected


def sync_submodule(repo: dict[str, Any], dry_run: bool) -> None:
    path = repo["git"]["submodule_path"]
    run_command(["git", "submodule", "sync", "--", path], ROOT_DIR, dry_run)
    run_command(["git", "submodule", "update", "--init", "--recursive", "--", path], ROOT_DIR, dry_run)


def update_submodule(repo: dict[str, Any], dry_run: bool) -> None:
    path = repo["git"]["submodule_path"]
    branch = repo["git"]["default_branch"]
    full_path = ROOT_DIR / path

    sync_submodule(repo, dry_run)
    run_command(["git", "fetch", "origin", branch], full_path, dry_run)
    run_command(["git", "checkout", branch], full_path, dry_run)
    run_command(["git", "pull", "--ff-only", "origin", branch], full_path, dry_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync source submodules from registry")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to source registry YAML/JSON file",
    )
    parser.add_argument(
        "--mode",
        choices=("validate", "sync", "update"),
        default="validate",
        help="validate only, sync current commits, or update to remote branch heads",
    )
    parser.add_argument(
        "--repo-id",
        action="append",
        dest="repo_ids",
        help="Optional repo_id filter (can be passed multiple times)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = load_registry(Path(args.registry))
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            raise ValueError("Invalid registry: `repositories` must be an array")

        source_roots = payload.get("source_roots")
        if not isinstance(source_roots, list) or not source_roots:
            raise ValueError("Invalid registry: `source_roots` must be a non-empty array")
        source_root_paths: set[str] = set()
        for item in source_roots:
            if not isinstance(item, dict) or "path" not in item:
                raise ValueError("Invalid registry: each source_roots item must include `path`")
            root_path = ROOT_DIR / item["path"]
            if not root_path.exists():
                raise ValueError(f"Source root path does not exist: {root_path}")
            source_root_paths.add(str(Path(item["path"]).as_posix()))

        validated = validate_registry_entries(repositories, source_root_paths)
        selected = select_repositories(validated, set(args.repo_ids) if args.repo_ids else None)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"[error] {error}")
        return 1

    print(f"[ok] Registry is valid. Repositories loaded: {len(validated)}")
    print(f"[ok] Selected repositories: {', '.join(repo['repo_id'] for repo in selected)}")

    if args.mode == "validate":
        return 0

    for repo in selected:
        print(f"[info] Processing {repo['repo_id']} ({repo['source_kind']})")
        if args.mode == "sync":
            sync_submodule(repo, args.dry_run)
        elif args.mode == "update":
            update_submodule(repo, args.dry_run)

    print(f"[ok] Mode `{args.mode}` completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
