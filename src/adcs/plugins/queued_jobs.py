"""Durable plugin ingestion submissions for shared-filesystem Celery workers.

Only registered plugin parameters are persisted; queue messages never contain
shell commands. Filesystem locks support cooperating Mac/Linux workers on the
same host/shared POSIX filesystem. This is not a multi-host lease service.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from celery import Celery

from adcs.plugins.catalog import PluginCatalog
from adcs.plugins.extraction import PlatformExtractionBackend

TASK_NAME = "adcs.plugins.ingestion.execute"
QUEUE_NAME = "adcs.ingestion"
_TERMINAL = {"completed", "failed", "stale", "needs_attention"}


class PluginJobBusy(RuntimeError):
    """Another worker holds this job/source/publication lock."""


def _root(workspace: Path) -> Path:
    return workspace.resolve() / "artifacts/plugin-jobs"


def _path(workspace: Path, operation_id: str) -> Path:
    UUID(operation_id)  # reject traversal and malformed IDs
    return _root(workspace) / f"{operation_id}.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4()}.tmp")
    try:
        with temporary.open("x") as stream:
            json.dump(payload, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_job(workspace: Path, operation_id: str) -> dict:
    job = json.loads(_path(workspace, operation_id).read_text())
    if (
        job["operation_id"] != operation_id
        or Path(job["workspace"]).resolve() != workspace.resolve()
    ):
        raise ValueError("Plugin job identity/workspace mismatch")
    return job


@contextmanager
def _lock(workspace: Path, key: str):
    path = _root(workspace) / "locks" / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PluginJobBusy(key) from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _revision(root: Path) -> str:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    if git("status", "--porcelain"):
        raise ValueError(f"Queued ingestion requires a clean source checkout: {root}")
    return git("rev-parse", "HEAD")


def _fingerprint(catalog: PluginCatalog, plugin_id: str) -> str:
    root = catalog.directories[plugin_id]
    digest = hashlib.sha256(catalog.extractor(plugin_id).model_dump_json().encode())
    for path in sorted({*root.glob("*.py"), *(root / "src").rglob("*.py")}):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    # External example content is part of the extraction input when present.
    cache = root / "sources/gist-examples.json"
    if cache.exists():
        digest.update(cache.read_bytes())
    return digest.hexdigest()


def _publisher() -> Celery:
    # Avoid importing celery_app: its bootstrap initializes runtime stores.
    from adcs.config import get_settings

    settings = get_settings()
    return Celery("adcs-plugin-submitter", broker=settings.rabbitmq_url, backend=settings.redis_url)


def dispatch_job(job: dict, publisher=None) -> dict:
    workspace = Path(job["workspace"])
    with _lock(workspace, "job:" + job["operation_id"]):
        job = read_job(workspace, job["operation_id"])
        if job["status"] not in {"prepared", "queued", "dispatch_failed"}:
            raise ValueError("Only unstarted plugin jobs can be resubmitted")
        job.update(status="queued", error=None)
        _write(_path(workspace, job["operation_id"]), job)
        try:
            (publisher or _publisher()).send_task(
                TASK_NAME,
                kwargs={"operation_id": job["operation_id"], "workspace": str(workspace)},
                queue=QUEUE_NAME,
                task_id=job["operation_id"],
                serializer="json",
            )
        except Exception as exc:
            # Delivery may be uncertain; same-ID redispatch is safe for this worker.
            job.update(status="dispatch_failed", error=type(exc).__name__)
            _write(_path(workspace, job["operation_id"]), job)
        return job


def enqueue_sources(
    *,
    catalog,
    plugin_id,
    catalog_path,
    workspace,
    kinds,
    python,
    timeout,
    stage,
    publish,
    publisher=None,
) -> list[dict]:
    from adcs.indexing.index_models import IngestionRunMode
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.plugins.cli import registry_payload

    submission_options = {}
    if publish:
        from adcs.config import get_settings

        settings = get_settings()
        if "apiref" in kinds and not settings.apiref_structured_store_enabled:
            raise ValueError(
                "API reference publication requires a configured structured symbol store"
            )
        # This policy is frozen in the operation by run(), so resolve it at
        # submission just as the synchronous CLI does, without opening stores.
        submission_options["metadata_quarantine_policy"] = (
            settings.ingestion_metadata_quarantine_policy
        )
    workspace = workspace.resolve()
    interpreter = str(Path(python or sys.executable).expanduser().absolute())
    if not Path(interpreter).is_file():
        raise ValueError("Plugin interpreter does not exist")
    backend = PlatformExtractionBackend(catalog, plugin_id, python=interpreter, timeout=timeout)
    prepared = []
    try:
        # Validate all requested inputs before creating/submitting any source job.
        revisions = {
            kind: _revision(workspace / backend.manifest.sources[kind].path) for kind in kinds
        }
        fingerprint = _fingerprint(catalog, plugin_id)
        for kind in kinds:
            registry_path = _root(workspace) / "registries" / f"{uuid4()}.json"
            _write(registry_path, registry_payload(backend, [kind]))
            service = SourceHugoNormalizationOrchestrationService(
                workspace_root=workspace,
                registry_path=registry_path,
                extraction_backend=backend,
                **submission_options,
            )
            operation = service.run(
                repo_ids=[backend.manifest.sources[kind].repo_id],
                execute_immediately=False,
                mode=IngestionRunMode.PUBLISH if publish else IngestionRunMode.VALIDATE_ONLY,
                dry_run=not (stage or publish),
            )
            job = dict(
                schema_version=1,
                operation_id=operation.operation_id,
                status="prepared",
                plugin_id=plugin_id,
                plugin_version=backend.manifest.version,
                source_kind=kind,
                repo_id=backend.manifest.sources[kind].repo_id,
                source_revision=revisions[kind],
                fingerprint=fingerprint,
                catalog=str(Path(catalog_path).resolve()),
                workspace=str(workspace),
                registry=str(registry_path),
                python=interpreter,
                timeout=timeout,
                stage=stage,
                publish=publish,
                created_ns=time.time_ns(),
                error=None,
            )
            _write(_path(workspace, operation.operation_id), job)
            prepared.append(job)
    finally:
        backend.close()
    return [dispatch_job(job, publisher) for job in prepared]


def _execute(job: dict) -> dict:
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.plugins.cli import runtime_options_for

    workspace = Path(job["workspace"])
    catalog = PluginCatalog(job["catalog"])
    if _fingerprint(catalog, job["plugin_id"]) != job["fingerprint"]:
        raise ValueError("Plugin/extraction inputs changed since submission; submit a new job")
    source = catalog.extractor(job["plugin_id"]).sources[job["source_kind"]]
    if _revision(workspace / source.path) != job["source_revision"]:
        raise ValueError("Source revision changed since submission; submit a new job")
    backend = PlatformExtractionBackend(
        catalog, job["plugin_id"], python=job["python"], timeout=job["timeout"]
    )
    try:
        service = SourceHugoNormalizationOrchestrationService(
            workspace_root=workspace,
            registry_path=job["registry"],
            extraction_backend=backend,
            **runtime_options_for(publish=job["publish"], kinds=[job["source_kind"]]),
        )
        operation = service.get_operation(job["operation_id"])
        if operation.status.value == "running":
            return {
                "status": "needs_attention",
                "error": "Interrupted operation; inspect before retry",
            }
        if operation.status.value == "completed":
            return {
                "status": "needs_attention",
                "error": "Operation completed before job checkpoint",
            }
        operation = service.execute_operation(operation_id=job["operation_id"])
        if job["stage"] or job["publish"]:
            backend.export_symbols(
                workspace / "artifacts/plugin-extraction" / job["plugin_id"] / job["operation_id"]
            )
        success = (
            operation.status.value == "completed"
            and len(operation.results) == 1
            and all(
                not r.failed_items
                and r.parsed_pages_count > 0
                and (not job["publish"] or r.indexing_summary.decision.value == "full_publish")
                for r in operation.results
            )
        )
        return {
            "status": "completed" if success else "failed",
            "operation_status": operation.status.value,
            "error": None if success else "Inspect persisted ingestion operation results",
        }
    finally:
        backend.close()


def execute_job(*, operation_id: str, workspace: str) -> dict:
    root = Path(workspace).resolve()
    with _lock(root, "job:" + operation_id):
        job = read_job(root, operation_id)
        if job["status"] in _TERMINAL:
            return job
        if job["status"] == "running":
            job.update(status="needs_attention", error="Worker interrupted; inspect before retry")
            _write(_path(root, operation_id), job)
            return job
        # Queued publications are deliberately serialized workspace-wide because
        # snapshot/staging state is shared. Non-publication jobs lock their source.
        key = "publication" if job["publish"] else "source:" + job["repo_id"]
        with _lock(root, key), _lock(root, "plugin:" + job["plugin_id"]):
            watermark = (
                _root(root)
                / "latest"
                / (hashlib.sha256(job["repo_id"].encode()).hexdigest() + ".json")
            )
            if job["publish"] and watermark.exists():
                if json.loads(watermark.read_text())["created_ns"] > job["created_ns"]:
                    job.update(status="stale", error="A newer publication job has already started")
                    _write(_path(root, operation_id), job)
                    return job
            if job["publish"]:
                _write(watermark, {"created_ns": job["created_ns"], "operation_id": operation_id})
            job.update(status="running", started_ns=time.time_ns())
            _write(_path(root, operation_id), job)
            try:
                job.update(_execute(job))
            except Exception as exc:
                job.update(
                    status="failed",
                    error=(str(exc) if isinstance(exc, ValueError) else type(exc).__name__),
                )
            job["finished_ns"] = time.time_ns()
            _write(_path(root, operation_id), job)
            return job
