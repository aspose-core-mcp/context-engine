"""The engine boots and validates external registrations without bundled plugins."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from adcs.plugins.catalog import PluginCatalog
from adcs.retrieval.profiles import load_profiles

ROOT = Path(__file__).resolve().parents[1]


def test_default_catalog_has_no_plugins_or_profiles():
    path = ROOT / "config/product-platform-plugins.json"
    catalog = PluginCatalog(path)
    assert catalog.plugins == {}
    assert catalog.compositions == {}
    assert load_profiles(str(path)) == {}
    with pytest.raises(ValueError, match="not enabled"):
        catalog.extractor("example.sample.net")


def test_explicit_empty_catalog_can_initialize_serving_scopes():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from adcs.mcp.product_scope import TOTAL_NET_SCOPE; "
            "assert TOTAL_NET_SCOPE.members == ()",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "ADCS_PRODUCT_PLUGIN_CATALOG": str(ROOT / "config/product-platform-plugins.json"),
        },
    )
    assert result.returncode == 0, result.stderr


def test_external_manifest_registration_and_removal(tmp_path):
    plugin = tmp_path / "external" / "sample"
    plugin.mkdir(parents=True)
    manifest = {
        "contract": "adcs.extraction.v1",
        "plugin_id": "example.sample.net",
        "version": "1.0.0",
        "product_id": "example.sample",
        "language": "net",
        "title": "Sample",
        "worker": ["{python}", "-I", "{plugin_dir}/worker.py"],
        "sources": {
            "docs": {
                "repo_id": "example.sample.net.docs",
                "path": "sources/sample",
                "prefix": "net",
                "layout": {},
                "canonical_base_url": "https://example.com/docs",
                "url": "https://example.com/docs.git",
                "branch": "main",
            }
        },
    }
    (plugin / "plugin.json").write_text(json.dumps(manifest))
    config = tmp_path / "engine" / "catalog.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"plugins": ["../external/sample/plugin.json"], "compositions": []})
    )
    catalog = PluginCatalog(config)
    assert catalog.extractor("example.sample.net").version == "1.0.0"
    assert catalog.command("example.sample.net")[-1] == str(plugin / "worker.py")
    config.write_text(json.dumps({"plugins": [], "compositions": []}))
    assert PluginCatalog(config).plugins == {}
    assert (plugin / "plugin.json").exists()


def test_retrieval_profile_schema_matches_engine_model():
    from adcs.retrieval.profiles import RetrievalProfile

    schema = json.loads((ROOT / "contracts/retrieval-profile/v1/profile.schema.json").read_text())
    schema.pop("$schema")
    assert schema == RetrievalProfile.model_json_schema()
