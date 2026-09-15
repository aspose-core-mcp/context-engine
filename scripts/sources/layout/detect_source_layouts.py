#!/usr/bin/env python3
"""Detect source layout for Hugo repositories and update registry YAML/JSON."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
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

sys.path.insert(0, str(ROOT_DIR / "src"))
from adcs.ingestion import dimension_vocabulary as _dv  # noqa: E402


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Registry file not found: {path}")
    raw_payload = path.read_text(encoding="utf-8")
    suffix = path.suffix.casefold()
    if suffix == ".json":
        payload = json.loads(raw_payload)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_payload)
    else:
        raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json")
    if not isinstance(payload, dict):
        raise ValueError("Registry payload must be an object")
    return payload


def write_registry(path: Path, payload: dict[str, Any]) -> None:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        mirror_path = path.with_suffix(".yaml")
        if mirror_path.exists():
            mirror_path.write_text(
                yaml.safe_dump(
                    payload,
                    sort_keys=False,
                    allow_unicode=False,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
            print(f"[info] Registry mirror updated: {mirror_path}")
    elif suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(
                payload,
                sort_keys=False,
                allow_unicode=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        mirror_path = path.with_suffix(".json")
        if mirror_path.exists():
            mirror_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            print(f"[info] Registry mirror updated: {mirror_path}")
    else:
        raise ValueError("Unsupported registry extension. Use .yaml/.yml or .json")


def score_level(values: set[str]) -> dict[str, float]:
    if not values:
        return {"doc_locale": 0.0, "programming_language": 0.0, "version": 0.0}
    n = float(len(values))
    counts: dict[str, int] = {"doc_locale": 0, "programming_language": 0, "version": 0}
    for value in values:
        dim = _dv.classify_segment(value)
        if dim in counts:
            counts[dim] += 1
    return {dim: counts[dim] / n for dim in counts}


ACCEPT_THRESHOLD = 0.50
TIE_MARGIN = 0.20
_STRUCTURAL = ("doc_locale", "programming_language", "version")


def assemble_schema(levels: list[set[str]]) -> dict[str, Any]:
    dimensions: list[dict[str, Any]] = []
    used: set[str] = set()
    uncertain = False
    namespace_started = False
    for idx, values in enumerate(levels):
        scores = score_level(values)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_dim, top_score = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        if namespace_started:
            continue  # everything past the first namespace level is namespace
        if top_score < ACCEPT_THRESHOLD or top_dim in used:
            # not a (new) structural dimension at this level
            if not used and all(score == 0.0 for score in scores.values()):
                dimensions.append({"semantic": "content_group", "depth": idx + 1})
                continue
            dimensions.append({"semantic": "namespace", "depth": idx + 1})
            namespace_started = True
            continue
        if top_score - runner < TIE_MARGIN and runner >= ACCEPT_THRESHOLD:
            uncertain = True
        dimensions.append({"semantic": top_dim, "depth": idx + 1})
        used.add(top_dim)
    if not dimensions or dimensions[-1]["semantic"] != "namespace":
        dimensions.append({"semantic": "namespace", "depth": len(levels) + 1})
    layout_type = "/".join(d["semantic"] for d in dimensions)
    return {"dimensions": dimensions, "layout_type": layout_type, "uncertain": uncertain}


def collect_layout_vectors(repo_root: Path) -> tuple[list[tuple[str, ...]], list[str]]:
    vectors: list[tuple[str, ...]] = []
    samples: list[str] = []

    for md_file in sorted(repo_root.rglob("*.md")):
        if not md_file.is_file():
            continue
        rel = md_file.relative_to(repo_root)
        samples.append(str(rel))
        parts = rel.parts[:-1]
        if parts:
            vectors.append(parts)

    return vectors, samples[:25]


def summarize_levels_n(vectors: list[tuple[str, ...]], max_depth: int = 6) -> list[set[str]]:
    """Return the set of directory names at each level 0..max_depth-1."""
    depth = min(max_depth, max((len(v) for v in vectors), default=0))
    levels: list[set[str]] = [set() for _ in range(depth)]
    for parts in vectors:
        for idx in range(min(len(parts), depth)):
            levels[idx].add(parts[idx])
    return levels


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def detect_layout(repo: dict[str, Any]) -> dict[str, Any]:
    submodule_path = ROOT_DIR / repo["git"]["submodule_path"]

    if not submodule_path.exists():
        return {
            "status": "pending_checkout",
            "detector_version": "layout-detector.v2",
            "detected_at_utc": datetime.now(UTC).isoformat(),
            "layout_type": "pending_checkout",
            "confidence": 0.0,
            "algorithm_metrics": {
                "directory_vectors_count": 0,
                "level_scores": [],
                "uncertain": False,
            },
            "dimensions": [],
            "sample_markdown_paths": [],
            "uncertain": False,
            "notes": [
                f"Submodule worktree is not materialized locally for `{repo['repo_id']}`.",
                "Run source-sync/source-update or materialized onboarding before layout detection.",
            ],
        }

    vectors, sample_markdown_paths = collect_layout_vectors(submodule_path)
    levels = summarize_levels_n(vectors)
    schema = assemble_schema(levels)
    confidence = clamp(
        0.55
        + (0.15 if not schema["uncertain"] else 0.0)
        + (0.15 if any(d["semantic"] in _STRUCTURAL for d in schema["dimensions"]) else 0.0)
        + (0.10 if len(vectors) >= 100 else 0.0),
        0.05, 0.99,
    )
    algorithm_metrics = {
        "directory_vectors_count": len(vectors),
        "level_scores": [score_level(lv) for lv in levels],
        "uncertain": schema["uncertain"],
    }
    return {
        "status": "detected",
        "detector_version": "layout-detector.v2",
        "detected_at_utc": datetime.now(UTC).isoformat(),
        "layout_type": schema["layout_type"],
        "confidence": round(confidence, 3),
        "algorithm_metrics": algorithm_metrics,
        "dimensions": schema["dimensions"],
        "sample_markdown_paths": sample_markdown_paths,
        "uncertain": schema["uncertain"],
        "notes": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect source folder layout and update source-repositories YAML/JSON"
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to source registry YAML/JSON file",
    )
    parser.add_argument(
        "--repo-id",
        action="append",
        dest="repo_ids",
        help="Optional repo_id filter (can be passed multiple times)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write detected layout back to registry YAML/JSON",
    )
    return parser.parse_args()


def select_repositories(
    repositories: list[dict[str, Any]], repo_ids: set[str] | None
) -> list[dict[str, Any]]:
    if not repo_ids:
        return repositories
    selected = [repo for repo in repositories if repo.get("repo_id") in repo_ids]
    selected_ids = {repo.get("repo_id") for repo in selected}
    missing = repo_ids - selected_ids
    if missing:
        raise ValueError(f"Unknown repo_id in registry: {sorted(missing)}")
    return selected


def main() -> int:
    args = parse_args()
    registry_path = Path(args.registry)

    try:
        payload = load_registry(registry_path)
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            raise ValueError("Invalid registry: `repositories` must be an array")
        selected = select_repositories(repositories, set(args.repo_ids) if args.repo_ids else None)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"[error] {error}")
        return 1

    print(f"[ok] Loaded registry: {registry_path}")
    print(f"[ok] Repositories selected: {', '.join(repo['repo_id'] for repo in selected)}")

    for repo in selected:
        detection = detect_layout(repo)
        repo["layout_detection"] = detection
        print(
            "[detected]",
            repo["repo_id"],
            "->",
            detection["layout_type"],
            f"(confidence={detection['confidence']})",
        )

    if args.write:
        write_registry(registry_path, payload)
        print(f"[ok] Registry updated: {registry_path}")
    else:
        print("[info] Dry mode: run with --write to persist layout detection into registry file")

    return 0


if __name__ == "__main__":
    sys.exit(main())
