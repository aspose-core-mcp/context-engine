from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from adcs.indexing.index_models import IngestionRunMode
from adcs.ingestion.source_hugo_normalization_orchestrator import (
    SourceHugoNormalizationOrchestrationService,
    SourceHugoNormalizationStatus,
)
from adcs.ingestion.source_registry import SourceRegistryService
from adcs.plugins.catalog import PluginCatalog
from adcs.plugins.cli import registry_payload
from adcs.plugins.extraction import ExtractionError, PlatformExtractionBackend

ROOT = Path(__file__).resolve().parents[1]


def backend(product="words", **kwargs):
    return PlatformExtractionBackend(
        PluginCatalog(ROOT / "config/product-platform-plugins.json"),
        f"aspose.{product}.net",
        **kwargs,
    )


def prepare(tmp_path, product="words", kinds=("docs",)):
    worker = backend(product)
    for kind in kinds:
        source = worker.manifest.sources[kind]
        directory = tmp_path / source.path / source.prefix
        directory.mkdir(parents=True)
        if kind == "docs":
            text = (
                "---\ntitle: Product guide\nurl: /guide/\n---\n# Product guide\n"
                "{{< highlight csharp >}}\nvar doc = 1;\n{{< /highlight >}}\n"
            )
        else:
            text = (
                "---\ntitle: Document Class\nsymbol_fqn: Aspose.Words.Document\n"
                "symbol_kind: class\nurl: /api/document/\n---\n"
                "# Document class\n```csharp\npublic class Document {}\n```\n"
            )
        (directory / "_index.md").write_text(text)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(registry_payload(worker, list(kinds))))
    sources = SourceRegistryService(registry, workspace_root=tmp_path).list_repositories()
    return worker, registry, sources


@pytest.mark.parametrize("product", ["words", "tex"])
def test_platform_docs_stage_without_other_product(tmp_path, product):
    worker, registry, sources = prepare(tmp_path, product)
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry,
        extraction_backend=worker,
        source_revision_resolver=lambda _: "source-sha",
    )
    operation = service.run(repo_ids=[sources[0].repo_id], mode=IngestionRunMode.VALIDATE_ONLY)
    assert operation.status == SourceHugoNormalizationStatus.COMPLETED
    assert len(operation.results) == 1
    result = operation.results[0]
    assert result.parsed_pages_count == 1
    assert not result.failed_items
    assert operation.force_full_reindex and operation.bypass_staging_replay
    assert not (tmp_path / worker.manifest.sources["apiref"].path).exists()


@pytest.mark.parametrize("kind", ["docs", "apiref"])
def test_worker_contract_and_bom_metadata(tmp_path, kind):
    worker, _, sources = prepare(tmp_path, kinds=(kind,))
    source = sources[0]
    paths = worker.discover(repo_root=tmp_path / source.git.submodule_path, repository=source)
    relative = paths[0].relative_to(tmp_path / source.git.submodule_path).as_posix()
    source_path = (source.git.submodule_path / relative).as_posix()
    page, document, records = worker.extract(
        repository=source,
        source_path=source_path,
        relative_repo_path=relative,
        raw_markdown="\ufeff" + paths[0].read_text(),
        source_revision="source-sha",
    )
    assert page.product_id == document.document.product_id == "aspose.words"
    assert page.programming_language == "net"
    assert page.metadata["title"] == document.document.title
    assert document.document.source_revision == "source-sha"
    assert page.code_blocks
    assert "title:" not in page.body_plain
    if kind == "apiref":
        assert document.document.symbol_fqn == "Aspose.Words.Document"


def test_discovery_excludes_other_platforms_and_symlinks(tmp_path):
    worker, _, sources = prepare(tmp_path)
    source = sources[0]
    root = tmp_path / source.git.submodule_path
    (root / "java").mkdir()
    (root / "java/other.md").write_text("# Java")
    (root / "net/escape.md").symlink_to(root / "java/other.md")
    paths = worker.discover(repo_root=root, repository=source)
    assert [p.name for p in paths] == ["_index.md"]
    with pytest.raises(ExtractionError, match="scope"):
        worker.source(replace(source, product_id="aspose.tex"))


def test_total_has_members_and_no_extractor():
    catalog = PluginCatalog(ROOT / "config/product-platform-plugins.json")
    assert catalog.compositions["aspose.total.net"].members == [
        "aspose.words.net",
        "aspose.tex.net",
    ]
    with pytest.raises(ValueError, match="aggregate"):
        catalog.extractor("aspose.total.net")


def test_worker_failure_fails_operation(tmp_path):
    worker, registry, sources = prepare(tmp_path)
    worker.command = [sys.executable, "-I", "-c", "raise SystemExit(4)"]
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry,
        extraction_backend=worker,
        source_revision_resolver=lambda _: "source-sha",
    )
    operation = service.run(repo_ids=[sources[0].repo_id], dry_run=True)
    assert operation.status == SourceHugoNormalizationStatus.FAILED
    assert not operation.results


def test_timeout_and_contract_version_rejected():
    worker = backend(timeout=0.05)
    worker.command = [sys.executable, "-I", "-c", "import time; time.sleep(5)"]
    with pytest.raises(ExtractionError, match="timed out"):
        worker.invoke("docs", operation="discover")
    worker.command = [sys.executable, "-I", "-c", 'print(\'{"contract":"adcs.extraction.v99"}\')']
    with pytest.raises(ExtractionError, match="mismatch"):
        worker.invoke("docs", operation="discover")


def test_wrong_scope_output_rejected(tmp_path, monkeypatch):
    worker, _, sources = prepare(tmp_path)
    source = sources[0]
    original = worker.invoke

    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        result["normalized_document"]["document"]["programming_language"] = "java"
        return result

    monkeypatch.setattr(worker, "invoke", corrupt)
    with pytest.raises(ExtractionError, match="scope"):
        worker.extract(
            repository=source,
            source_path=f"{source.git.submodule_path}/net/_index.md",
            relative_repo_path="net/_index.md",
            raw_markdown="---\ntitle: Guide\n---\nHello",
            source_revision="sha",
        )


def test_worker_runs_in_empty_virtualenv_without_engine(tmp_path):
    # A fresh environment contains neither ADCS nor the sibling plugin.
    import venv

    environment = tmp_path / "worker-env"
    venv.EnvBuilder(with_pip=False).create(environment)
    worker = backend(python=str(environment / "bin/python"))
    result = worker.invoke(
        "docs",
        operation="extract",
        repo_id="aspose.words.net.docs",
        product_family="aspose",
        source_path="net/_index.md",
        relative_repo_path="net/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
        raw_markdown="---\ntitle: Independent\n---\nHello",
        source_revision="sha",
        canonical_base_url="https://docs.aspose.com/words",
    )
    assert result["page"]["title"] == "Independent"


def test_plugin_theme_change_does_not_change_sibling(tmp_path):
    import shutil

    plugin = tmp_path / "words-net"
    shutil.copytree(
        ROOT / "plugins/words-net", plugin, ignore=shutil.ignore_patterns(".venv", "__pycache__")
    )
    path = plugin / "src/adcs_words_net/docs_extractor.py"
    path.write_text(
        path.read_text().replace(
            "text = re.sub(",
            'text = text.replace("THEME_TOKEN", "WORDS_THEME")\n    text = re.sub(',
            1,
        )
    )
    request = dict(
        operation="extract",
        repo_id="test",
        product_family="aspose",
        source_path="net/_index.md",
        relative_repo_path="net/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
        raw_markdown="---\ntitle: Theme\n---\nTHEME_TOKEN",
        source_revision="sha",
        canonical_base_url="https://example.com",
    )
    words = backend()
    words.command = [sys.executable, "-I", str(plugin / "worker.py")]
    assert "WORDS_THEME" in words.invoke("docs", **request)["page"]["body_plain"]
    tex = backend("tex")
    assert "THEME_TOKEN" in tex.invoke("docs", **request)["page"]["body_plain"]


def test_cli_rejects_total_without_ingestion():
    completed = subprocess.run(
        [sys.executable, "-m", "adcs.plugins.cli", "aspose.total.net"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    assert completed.returncode != 0
    assert "aggregate has no extractor" in completed.stderr


def test_both_sources_publish_without_overwriting_docs_or_other_product(tmp_path):
    from adcs.indexing.apiref_symbol_store import ApiRefScope, InMemoryApiRefSymbolStore
    from adcs.indexing.publish_orchestrator import IndexPublishOrchestrator
    from adcs.indexing.snapshot_registry import InMemorySnapshotRegistry

    snapshots = InMemorySnapshotRegistry()
    other = snapshots.create_snapshot(
        product_id="aspose.tex",
        programming_language="net",
        version="latest-stable",
        source_kind="docs",
        source_revision="tex-sha",
        indexed_chunks_count=1,
    )
    worker, registry, sources = prepare(tmp_path, kinds=("docs", "apiref"))
    symbols = InMemoryApiRefSymbolStore()
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry,
        extraction_backend=worker,
        source_revision_resolver=lambda _: "source-sha",
        index_publish_orchestrator=IndexPublishOrchestrator(snapshot_registry=snapshots),
        apiref_symbol_store=symbols,
    )
    operation = service.run(repo_ids=[source.repo_id for source in sources])
    assert operation.status == SourceHugoNormalizationStatus.COMPLETED
    assert len(operation.results) == 2
    assert not any(result.failed_items for result in operation.results)
    assert all(
        result.indexing_summary.decision.value == "full_publish" for result in operation.results
    )
    for kind in ("docs", "apiref"):
        assert snapshots.get_active_snapshot(
            product_id="aspose.words",
            programming_language="net",
            version="latest-stable",
            source_kind=kind,
        )
    assert (
        snapshots.get_active_snapshot(
            product_id="aspose.tex",
            programming_language="net",
            version="latest-stable",
            source_kind="docs",
        ).snapshot_id
        == other.snapshot_id
    )
    found = symbols.get_symbol(
        member_fqn="Aspose.Words.Document",
        scope=ApiRefScope(product="aspose.words", language="net", version="latest-stable"),
    )
    assert len(found) == 1
    assert "public class Document" in found[0].signature
    worker.close()


def test_new_plugin_registered_without_engine_edits(tmp_path):
    import shutil

    directory = tmp_path / "new-plugin"
    shutil.copytree(
        ROOT / "plugins/tex-net", directory, ignore=shutil.ignore_patterns(".venv", "__pycache__")
    )
    manifest_path = directory / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["plugin_id"] = "aspose.example.net"
    manifest["product_id"] = "aspose.example"
    for source in manifest["sources"].values():
        source["repo_id"] = source["repo_id"].replace("aspose.tex", "aspose.example")
    manifest_path.write_text(json.dumps(manifest))
    implementation = directory / "src/adcs_tex_net/worker.py"
    implementation.write_text(implementation.read_text().replace("aspose.tex", "aspose.example"))
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"plugins": [str(manifest_path)]}))
    catalog = PluginCatalog(catalog_path)
    assert list(catalog.plugins) == ["aspose.example.net"]
    worker = PlatformExtractionBackend(catalog, "aspose.example.net")
    result = worker.invoke(
        "docs",
        operation="extract",
        repo_id="aspose.example.net.docs",
        product_family="aspose",
        source_path="net/_index.md",
        relative_repo_path="net/_index.md",
        layout_detection={"layout_type": "programming_language/content"},
        raw_markdown="---\ntitle: Third product\n---\nHello",
        source_revision="sha",
        canonical_base_url="https://example.com",
    )
    assert result["normalized_document"]["document"]["product_id"] == "aspose.example"


def test_bad_manifest_contract_and_duplicate_registration(tmp_path):
    manifest = json.loads((ROOT / "plugins/words-net/plugin.json").read_text())
    manifest["contract"] = "adcs.extraction.v2"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"plugins": [str(path)]}))
    with pytest.raises(ValueError, match="adcs.extraction.v1"):
        PluginCatalog(catalog_path)
    manifest["contract"] = "adcs.extraction.v1"
    path.write_text(json.dumps(manifest))
    catalog_path.write_text(json.dumps({"plugins": [str(path), str(path)]}))
    with pytest.raises(ValueError, match="Duplicate plugin"):
        PluginCatalog(catalog_path)


def test_catalog_can_select_total_members_for_serving():
    import os

    code = (
        "from adcs.mcp.product_scope import TOTAL_NET_SCOPE; "
        "assert [s.product_id for s in TOTAL_NET_SCOPE.members] == "
        "['aspose.words', 'aspose.tex']"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "ADCS_PRODUCT_PLUGIN_CATALOG": str(ROOT / "config/product-platform-plugins.json"),
        },
    )
    assert result.returncode == 0, result.stderr


def test_committed_schemas_match_contracts():
    from adcs.plugins.catalog import PluginManifest
    from adcs.plugins.contracts import ExtractionFailure, ExtractionResponse

    for name, model in (
        ("response", ExtractionResponse),
        ("failure", ExtractionFailure),
        ("manifest", PluginManifest),
    ):
        schema = json.loads(
            (ROOT / f"contracts/plugin-extraction/v1/{name}.schema.json").read_text()
        )
        schema.pop("$schema")
        assert schema == model.model_json_schema()


def test_extraction_failure_is_not_successful_operation(tmp_path, monkeypatch):
    worker, registry, sources = prepare(tmp_path)

    def fail(**kwargs):
        raise ExtractionError("Broken product theme")

    monkeypatch.setattr(worker, "extract", fail)
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=tmp_path,
        registry_path=registry,
        extraction_backend=worker,
        source_revision_resolver=lambda _: "source-sha",
    )
    operation = service.run(repo_ids=[sources[0].repo_id], dry_run=True)
    assert operation.status == SourceHugoNormalizationStatus.FAILED


def test_cli_stages_scoped_sources(tmp_path):
    import os

    worker, _, sources = prepare(tmp_path)
    repo = tmp_path / sources[0].git.submodule_path
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "adcs.plugins.cli",
            "aspose.words.net",
            "--source-kind",
            "docs",
            "--stage",
            "--workspace",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["publication"] == "not_requested"
    assert report["operation"]["results"][0]["parsed_pages_count"] == 1
    assert list((tmp_path / "artifacts/plugin-extraction/aspose.words.net").glob("*/*.jsonl"))
    worker.close()


def test_dedicated_interpreter_keeps_its_dependency_environment(tmp_path):
    import venv

    environment = tmp_path / "isolated-env"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "bin/python"
    site = next((environment / "lib").glob("python*/site-packages"))
    (site / "plugin_only_dependency.py").write_text("VALUE = 'private dependency'\n")
    worker = backend(python=str(python))
    # Resolving this executable's symlink would silently switch back to base Python.
    assert worker.command[0] == str(python.absolute())
    worker.command = [
        worker.command[0],
        "-I",
        "-c",
        "import json; from plugin_only_dependency import VALUE; "
        "print(json.dumps({'contract': 'adcs.extraction.v1', "
        "'plugin_id': 'aspose.words.net', 'plugin_version': '0.1.0', "
        "'result': {'files': [VALUE]}}))",
    ]
    assert worker.invoke("docs", operation="discover")["files"] == ["private dependency"]
