"""Queued plugin ingestion with a fake broker and isolated fixture workspace."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from adcs.plugins import queued_jobs as queue
from adcs.plugins.catalog import PluginCatalog

ROOT = Path(__file__).resolve().parents[1]

if not (ROOT / "plugins/words-net/plugin.json").is_file():
    pytest.skip(
        "Requires separately installed Words plugin; see docs/engine-only.md",
        allow_module_level=True,
    )


class Publisher:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def send_task(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.fail:
            raise ConnectionError("broker unavailable")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    raw = json.loads((ROOT / "plugins/words-net/plugin.json").read_text())
    raw["worker"] = ["{python}", "-I", str(ROOT / "plugins/words-net/worker.py")]
    raw.pop("retrieval_profile", None)
    for kind, source in raw["sources"].items():
        source["path"] = "sources/" + kind
        target = tmp_path / source["path"] / source["prefix"] / "_index.md"
        target.parent.mkdir(parents=True)
        target.write_text((ROOT / f"plugins/words-net/tests/fixtures/{kind}.md").read_text())
        repo = tmp_path / source["path"]
        for command in (
            ["git", "init", str(repo)],
            ["git", "-C", str(repo), "add", "."],
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.com",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "fixture",
            ],
        ):
            subprocess.run(command, check=True, capture_output=True)
    (tmp_path / "plugin.json").write_text(json.dumps(raw))
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"plugins": ["plugin.json"]}))
    return dict(
        catalog=PluginCatalog(path),
        plugin_id="aspose.words.net",
        catalog_path=path,
        workspace=tmp_path,
        kinds=["docs", "apiref"],
        python=sys.executable,
        timeout=60,
        stage=True,
        publish=False,
    )


def test_enqueue_persists_two_independent_jobs_without_extracting(setup, monkeypatch):
    monkeypatch.setattr(
        queue.PlatformExtractionBackend,
        "invoke",
        lambda *a, **kw: pytest.fail("Submission invoked extraction"),
    )
    publisher = Publisher()
    jobs = queue.enqueue_sources(**setup, publisher=publisher)
    assert len(jobs) == len(publisher.calls) == 2
    assert {j["source_kind"] for j in jobs} == {"docs", "apiref"}
    for job, (name, message) in zip(jobs, publisher.calls, strict=True):
        assert name == queue.TASK_NAME
        assert message["queue"] == "adcs.ingestion"
        assert set(message["kwargs"]) == {"operation_id", "workspace"}
        assert job["status"] == "queued"
        assert Path(job["registry"]).exists()
        assert (
            setup["workspace"]
            / "artifacts/runtime-state/ingestion"
            / (job["operation_id"] + ".json")
        ).exists()
        assert queue.read_job(setup["workspace"], job["operation_id"]) == job


def test_worker_reconstructs_plugin_and_duplicate_delivery_is_noop(setup):
    jobs = queue.enqueue_sources(**setup, publisher=Publisher())
    for job in jobs:
        result = queue.execute_job(operation_id=job["operation_id"], workspace=job["workspace"])
        assert result["status"] == "completed", result
        assert (
            queue.execute_job(operation_id=job["operation_id"], workspace=job["workspace"])
            == result
        )
        artifact = (
            setup["workspace"]
            / "artifacts/plugin-extraction/aspose.words.net"
            / job["operation_id"]
            / (job["repo_id"] + ".jsonl")
        )
        assert artifact.exists()


def test_failed_broker_delivery_can_resubmit_same_job(setup):
    job = queue.enqueue_sources(**setup, publisher=Publisher(fail=True))[0]
    assert job["status"] == "dispatch_failed"
    resent = queue.dispatch_job(job, Publisher())
    assert resent["status"] == "queued" and resent["operation_id"] == job["operation_id"]


def test_changed_source_is_rejected_before_extraction(setup, monkeypatch):
    job = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    monkeypatch.setattr(queue, "_revision", lambda root: "different-revision")
    result = queue.execute_job(operation_id=job["operation_id"], workspace=job["workspace"])
    assert result["status"] == "failed"
    assert "Source revision changed" in result["error"]


def test_changed_plugin_is_rejected(setup):
    job = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    manifest = setup["workspace"] / "plugin.json"
    raw = json.loads(manifest.read_text())
    raw["version"] = "different"
    manifest.write_text(json.dumps(raw))
    result = queue.execute_job(operation_id=job["operation_id"], workspace=job["workspace"])
    assert result["status"] == "failed" and "inputs changed" in result["error"]


def test_crash_requires_attention_not_blind_republication(setup):
    job = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    job["status"] = "running"
    queue._write(queue._path(setup["workspace"], job["operation_id"]), job)
    result = queue.execute_job(operation_id=job["operation_id"], workspace=job["workspace"])
    assert result["status"] == "needs_attention"
    with pytest.raises(ValueError, match="unstarted"):
        queue.dispatch_job(result, Publisher())


def test_publication_watermark_blocks_older_job(setup, monkeypatch):
    setup.update(kinds=["docs"], publish=True, stage=False)
    older = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    newer = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    calls = []

    def execute(job):
        calls.append(job["operation_id"])
        return {"status": "completed"}

    monkeypatch.setattr(queue, "_execute", execute)
    queue.execute_job(operation_id=newer["operation_id"], workspace=newer["workspace"])
    result = queue.execute_job(operation_id=older["operation_id"], workspace=older["workspace"])
    assert result["status"] == "stale"
    assert calls == [newer["operation_id"]]


def test_lock_contention_is_retryable(tmp_path):
    with queue._lock(tmp_path, "publication"):
        with pytest.raises(queue.PluginJobBusy):
            with queue._lock(tmp_path, "publication"):
                pytest.fail("Lock acquired twice")


def test_job_paths_are_contained(tmp_path):
    with pytest.raises(ValueError):
        queue.read_job(tmp_path, "../outside")
    with pytest.raises(FileNotFoundError):
        queue.read_job(tmp_path, str(uuid4()))


def test_dirty_source_rejected_before_any_submission(setup):
    source = setup["workspace"] / "sources/docs/uncommitted.md"
    source.write_text("changed")
    publisher = Publisher()
    with pytest.raises(ValueError, match="clean source checkout"):
        queue.enqueue_sources(**setup, publisher=publisher)
    assert publisher.calls == []
    assert not (setup["workspace"] / "artifacts/plugin-jobs").exists()


def test_cli_enqueue_and_status(setup, monkeypatch, capsys):
    from adcs.plugins import cli

    publisher = Publisher()
    monkeypatch.setattr(queue, "_publisher", lambda: publisher)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adcs.plugins.cli",
            setup["plugin_id"],
            "--catalog",
            str(setup["catalog_path"]),
            "--workspace",
            str(setup["workspace"]),
            "--python",
            sys.executable,
            "--stage",
            "--enqueue",
        ],
    )
    cli.main()
    output = json.loads(capsys.readouterr().out)
    assert len(output["jobs"]) == 2
    operation_id = output["jobs"][0]["operation_id"]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adcs.plugins.cli",
            "--workspace",
            str(setup["workspace"]),
            "--job-status",
            operation_id,
        ],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "queued"
    assert len(publisher.calls) == 2


def test_cli_resubmit_reports_broker_failure(setup, monkeypatch, capsys):
    from adcs.plugins import cli

    job = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    monkeypatch.setattr(queue, "_publisher", lambda: Publisher(fail=True))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adcs.plugins.cli",
            "--workspace",
            str(setup["workspace"]),
            "--resubmit",
            job["operation_id"],
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "dispatch_failed"


def test_celery_plugin_task_routes_and_retries_contention(monkeypatch):
    from celery.exceptions import Retry

    from adcs.worker.celery_app import celery_app, execute_plugin_ingestion

    assert celery_app.conf.task_routes[queue.TASK_NAME]["queue"] == queue.QUEUE_NAME
    assert execute_plugin_ingestion.acks_late
    assert execute_plugin_ingestion.reject_on_worker_lost
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(queue, "execute_job", execute)
    assert execute_plugin_ingestion.run(operation_id="job", workspace="/shared") == {
        "operation_id": "job",
        "status": "completed",
    }
    assert calls == [{"operation_id": "job", "workspace": "/shared"}]

    def busy(**kwargs):
        raise queue.PluginJobBusy("locked")

    def retry(**kwargs):
        assert kwargs["countdown"] == 15
        raise Retry()

    monkeypatch.setattr(queue, "execute_job", busy)
    monkeypatch.setattr(execute_plugin_ingestion, "retry", retry)
    with pytest.raises(Retry):
        execute_plugin_ingestion.run(operation_id="job", workspace="/shared")


def test_publication_submission_persists_policy_without_opening_stores(setup, monkeypatch):
    from adcs.config import clear_settings_cache
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.runtime import components

    monkeypatch.setenv("ADCS_INGESTION_METADATA_QUARANTINE_POLICY", "strict_block")
    clear_settings_cache()
    monkeypatch.setattr(
        components,
        "build_runtime_components",
        lambda **kwargs: pytest.fail("Submission opened publication stores"),
    )
    setup.update(kinds=["docs"], publish=True, stage=False)
    job = queue.enqueue_sources(**setup, publisher=Publisher())[0]
    service = SourceHugoNormalizationOrchestrationService(
        workspace_root=setup["workspace"],
        registry_path=job["registry"],
    )
    operation = service.get_operation(job["operation_id"])
    assert operation.metadata_quarantine_policy == "strict_block"
    assert operation.mode.value == "publish"
    assert operation.force_full_reindex and operation.bypass_staging_replay
