#!/usr/bin/env python3
"""Verify multi-product registry readiness for scale-out operation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adcs.config import EnvironmentProfile
from adcs.indexing import load_index_topology_policy
from adcs.ingestion.source_registry import SourceRegistryService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify registry diversity and topology readiness for multi-product operation."
    )
    parser.add_argument(
        "--registry",
        default="config/source-repositories.yaml",
        help="Path to source registry YAML/JSON file.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root used to resolve source repository paths.",
    )
    parser.add_argument(
        "--topology-config",
        default="config/index-topology-policy.json",
        help="Path to index topology policy JSON file.",
    )
    parser.add_argument(
        "--profile",
        default=EnvironmentProfile.DEV.value,
        help="Topology profile to validate (dev/staging/prod).",
    )
    parser.add_argument(
        "--min-products",
        type=int,
        default=4,
        help="Minimum number of registered products required to pass.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/scale/multi-product-readiness.json",
        help="Path to JSON report output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = SourceRegistryService(
        registry_path=Path(args.registry),
        workspace_root=Path(args.workspace_root),
    )
    policy = load_index_topology_policy(
        profile=args.profile,
        config_path=Path(args.topology_config),
    )

    repositories = service.list_repositories()
    products: dict[str, set[str]] = {}
    product_families: set[str] = set()
    detected_layout_repo_count = 0
    for repository in repositories:
        products.setdefault(repository.product_id, set()).add(repository.source_kind)
        product_families.add(repository.product_family)
        if isinstance(repository.layout_detection, dict):
            if str(repository.layout_detection.get("status", "")).strip() == "detected":
                detected_layout_repo_count += 1

    fully_paired_products = sorted(
        product_id for product_id, kinds in products.items() if {"docs", "apiref"}.issubset(kinds)
    )
    report = {
        "registry_path": str(Path(args.registry).resolve()),
        "workspace_root": str(Path(args.workspace_root).resolve()),
        "topology_profile": policy.profile,
        "registered_products_total": len(products),
        "registered_product_families_total": len(product_families),
        "fully_paired_products_total": len(fully_paired_products),
        "fully_paired_products": fully_paired_products,
        "repositories_total": len(repositories),
        "repositories_with_detected_layout_total": detected_layout_repo_count,
        "topology": {
            "qdrant": {
                "shard_number": policy.qdrant.shard_number,
                "replication_factor": policy.qdrant.replication_factor,
                "write_consistency_factor": policy.qdrant.write_consistency_factor,
            },
            "opensearch": {
                "number_of_shards": policy.opensearch.number_of_shards,
                "number_of_replicas": policy.opensearch.number_of_replicas,
                "refresh_interval": policy.opensearch.refresh_interval,
            },
            "compaction": {
                "enabled": policy.compaction.enabled,
                "max_inactive_snapshots_per_scope": (
                    policy.compaction.max_inactive_snapshots_per_scope
                ),
                "stale_snapshot_retention_days": (
                    policy.compaction.stale_snapshot_retention_days
                ),
            },
            "storage_tiering": {
                "latest_stable_tier": policy.storage_tiering.latest_stable_tier,
                "archive_tier": policy.storage_tiering.archive_tier,
            },
        },
    }

    failures: list[str] = []
    if len(products) < args.min_products:
        failures.append(
            f"registered_products_total={len(products)} is below required minimum {args.min_products}"
        )
    if len(fully_paired_products) < args.min_products:
        failures.append(
            "fully_paired_products_total="
            f"{len(fully_paired_products)} is below required minimum {args.min_products}"
        )
    if detected_layout_repo_count != len(repositories):
        failures.append(
            "repositories_with_detected_layout_total="
            f"{detected_layout_repo_count} does not match repositories_total={len(repositories)}"
        )

    report["status"] = "passed" if not failures else "failed"
    report["failures"] = failures

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    if failures:
        for failure in failures:
            print(f"[fail] {failure}")
        print(f"[info] Report written to: {output_path}")
        return 1

    print(
        "[pass] "
        f"products={len(products)} fully_paired={len(fully_paired_products)} "
        f"layouts={detected_layout_repo_count}/{len(repositories)} profile={policy.profile}"
    )
    print(f"[info] Report written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
