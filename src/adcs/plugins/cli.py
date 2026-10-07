"""Explicit platform extraction/staging entry point; no aggregate ingestion."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from adcs.plugins.catalog import PluginCatalog
from adcs.plugins.extraction import PlatformExtractionBackend


def registry_payload(
    backend: PlatformExtractionBackend, kinds: list[Literal["docs", "apiref"]]
) -> dict:
    manifest = backend.manifest
    repositories = []
    roots = []
    for kind in kinds:
        source = manifest.sources[kind]
        roots.append({"root_id": kind, "source_kind": kind, "path": str(Path(source.path).parent)})
        repositories.append(
            {
                "repo_id": source.repo_id,
                "product_id": manifest.product_id,
                "product_family": "aspose",
                "product_family_dir": Path(source.path).name,
                "source_kind": kind,
                "git": {
                    "url": source.url,
                    "submodule_path": source.path,
                    "default_branch": source.branch,
                },
                "layout_detection": source.layout,
            }
        )
    return {"source_roots": roots, "repositories": repositories}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_id")
    parser.add_argument(
        "--catalog", type=Path, default=Path("config/product-platform-plugins.json")
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--source-kind", choices=("docs", "apiref", "both"), default="both")
    parser.add_argument("--python", help="Dedicated plugin environment's Python executable")
    parser.add_argument("--timeout", type=float, default=60)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--stage", action="store_true", help="Write REVIEW staging only")
    mode_group.add_argument(
        "--publish", action="store_true", help="Publish using configured stores"
    )
    args = parser.parse_args()
    catalog = PluginCatalog(args.catalog)
    backend = PlatformExtractionBackend(
        catalog, args.plugin_id, python=args.python, timeout=args.timeout
    )
    kinds = list(backend.manifest.sources) if args.source_kind == "both" else [args.source_kind]
    if any(kind not in backend.manifest.sources for kind in kinds):
        parser.error("Selected plugin does not implement that source kind")
    from adcs.indexing.index_models import IngestionRunMode
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )

    runtime_options: dict[str, Any] = {}
    if args.publish:
        from adcs.config import get_settings
        from adcs.indexing.apiref_symbol_store import build_apiref_symbol_store
        from adcs.runtime.components import build_runtime_components

        settings = get_settings()
        if "apiref" in kinds and not settings.apiref_structured_store_enabled:
            parser.error("API reference publication requires a configured structured symbol store")
        runtime = build_runtime_components(settings=settings)
        runtime_options = {
            "index_publish_orchestrator": runtime.index_publish_orchestrator,
            "ingestion_job_repository": runtime.ingestion_job_repository,
            "apiref_symbol_store": build_apiref_symbol_store(
                enabled=settings.apiref_structured_store_enabled,
                postgres_dsn=settings.postgres_dsn,
            ),
            "critical_event_publisher": runtime.critical_event_store,
            "publish_safety_min_coverage_pct": settings.ingestion_publish_safety_min_coverage_pct,
            "metadata_quarantine_policy": settings.ingestion_metadata_quarantine_policy,
        }
    with TemporaryDirectory(prefix="adcs-plugin-registry-") as temporary:
        registry = Path(temporary) / "registry.json"
        registry.write_text(json.dumps(registry_payload(backend, kinds)))
        service = SourceHugoNormalizationOrchestrationService(
            workspace_root=args.workspace,
            registry_path=registry,
            extraction_backend=backend,
            **runtime_options,
        )
        operation = service.run(
            repo_ids=[backend.manifest.sources[kind].repo_id for kind in kinds],
            mode=IngestionRunMode.PUBLISH if args.publish else IngestionRunMode.VALIDATE_ONLY,
            dry_run=not (args.stage or args.publish),
        )
    if args.stage or args.publish:
        backend.export_symbols(
            args.workspace
            / "artifacts"
            / "plugin-extraction"
            / backend.manifest.plugin_id
            / operation.operation_id
        )
    backend.close()
    print(
        json.dumps(
            {
                "plugin_id": backend.manifest.plugin_id,
                "plugin_version": backend.manifest.version,
                "contract": backend.manifest.contract,
                "publication": "requested" if args.publish else "not_requested",
                "operation": asdict(operation),
            },
            default=str,
        )
    )
    if (
        operation.status.value != "completed"
        or len(operation.results) != len(kinds)
        or any(
            result.failed_items
            or result.parsed_pages_count == 0
            or (args.publish and result.indexing_summary.decision.value != "full_publish")
            for result in operation.results
        )
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
