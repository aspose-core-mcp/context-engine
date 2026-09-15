from __future__ import annotations

import json

from adcs.ingestion.canonical_url_mapping import (
    CanonicalUrlMappingContext,
    FileSystemCanonicalUrlMappingStore,
    extract_metadata_remap_pairs,
)


def test_extract_metadata_remap_pairs_supports_legacy_and_explicit_shapes() -> None:
    remap_pairs = extract_metadata_remap_pairs(
        metadata={
            "canonical_url_old": "/ocr/net/legacy/",
            "canonical_url_aliases": ["/ocr/net/legacy-alias/"],
            "canonical_url_remap": {
                "/ocr/net/old-path/": "/ocr/net/new-path/",
            },
        },
        resolved_canonical_url="/ocr/net/latest/",
        canonical_base_url="https://docs.aspose.com",
    )

    assert (
        "https://docs.aspose.com/ocr/net/legacy/",
        "https://docs.aspose.com/ocr/net/latest/",
    ) in remap_pairs
    assert (
        "https://docs.aspose.com/ocr/net/legacy-alias/",
        "https://docs.aspose.com/ocr/net/latest/",
    ) in remap_pairs
    assert (
        "https://docs.aspose.com/ocr/net/old-path/",
        "https://docs.aspose.com/ocr/net/new-path/",
    ) in remap_pairs


def test_canonical_mapping_registry_applies_precedence_and_conflict_handling(
    tmp_path,
) -> None:
    store = FileSystemCanonicalUrlMappingStore(workspace_root=tmp_path)
    context = CanonicalUrlMappingContext.from_values(
        product_id="aspose.ocr",
        source_kind="docs",
        programming_language="net",
        version="25.1",
    )
    registry = store.load(context=context)
    registry.register_mapping(
        old_url="/ocr/net/legacy/",
        new_url="/ocr/net/persisted/",
        source_path="source/a.md",
    )
    store.save(registry=registry)

    registry = store.load(context=context)
    override_conflict = registry.register_mapping(
        old_url="/ocr/net/legacy/",
        new_url="/ocr/net/latest/",
        source_path="source/b.md",
    )
    assert override_conflict is not None
    assert override_conflict.conflict_type == "override_persisted"
    assert (
        registry.resolve("/ocr/net/legacy/") == "https://docs.aspose.com/ocr/net/latest/"
    )

    conflicting_mapping = registry.register_mapping(
        old_url="/ocr/net/legacy/",
        new_url="/ocr/net/other/",
        source_path="source/c.md",
    )
    assert conflicting_mapping is not None
    assert conflicting_mapping.conflict_type == "conflicting_mapping"
    assert (
        registry.resolve("/ocr/net/legacy/") == "https://docs.aspose.com/ocr/net/latest/"
    )


def test_canonical_mapping_store_round_trips_entries(tmp_path) -> None:
    store = FileSystemCanonicalUrlMappingStore(workspace_root=tmp_path)
    context = CanonicalUrlMappingContext.from_values(
        product_id="aspose.ocr",
        source_kind="docs",
        programming_language="net",
        version="latest-stable",
    )
    registry = store.load(context=context)
    registry.register_mapping(
        old_url="/ocr/net/old/",
        new_url="/ocr/net/new/",
        source_path="source/old.md",
    )
    store.save(registry=registry)

    reloaded_registry = store.load(context=context)
    assert reloaded_registry.entries_count == 1
    assert (
        reloaded_registry.resolve("/ocr/net/old/")
        == "https://docs.aspose.com/ocr/net/new/"
    )


def test_canonical_mapping_store_loads_legacy_path_and_persists_runtime_safe(
    tmp_path,
) -> None:
    legacy_mapping_path = (
        tmp_path
        / "artifacts"
        / "canonical-url-mapping"
        / "aspose.ocr"
        / "docs"
        / "net"
        / "25.1.json"
    )
    legacy_mapping_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_mapping_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mappings": [
                    {
                        "old_url": "https://docs.aspose.com/ocr/net/legacy/",
                        "new_url": "https://docs.aspose.com/ocr/net/current/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = FileSystemCanonicalUrlMappingStore(workspace_root=tmp_path)
    context = CanonicalUrlMappingContext.from_values(
        product_id="aspose.ocr",
        source_kind="docs",
        programming_language="net",
        version="25.1",
    )
    registry = store.load(context=context)
    assert (
        registry.resolve("/ocr/net/legacy/")
        == "https://docs.aspose.com/ocr/net/current/"
    )

    store.save(registry=registry)
    runtime_safe_mapping_path = (
        tmp_path
        / "artifacts"
        / "runtime-safe"
        / "canonical-url-mapping"
        / "aspose.ocr"
        / "docs"
        / "net"
        / "25.1.json"
    )
    assert runtime_safe_mapping_path.exists()
