#!/usr/bin/env python3
"""Resilient full-catalog ingestion script with checkpoint/resume.

Runs all available repos through the ingestion pipeline, tracking progress
in a checkpoint file so it can resume after interruptions.

Usage:
    PYTHONPATH=./src nohup python3 scripts/run_full_ingestion.py >> logs/ingestion.log 2>&1 &

Progress is logged to both stdout and logs/ingestion_progress.log.
Checkpoint state is saved to logs/ingestion_checkpoint.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

CHECKPOINT_FILE = LOGS_DIR / "ingestion_checkpoint.json"
PROGRESS_LOG = LOGS_DIR / "ingestion_progress.log"
MAIN_LOG = LOGS_DIR / "ingestion.log"

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingestion_runner")
logger.setLevel(logging.INFO)


def log_progress(msg: str) -> None:
    """Log a progress message to both stdout and the progress log file."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(line + "\n")


def load_checkpoint() -> dict:
    """Load checkpoint state from file."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "in_progress": None, "started_at": None}


def save_checkpoint(state: dict) -> None:
    """Save checkpoint state to file."""
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_available_repos() -> list[tuple[str, str, int]]:
    """Scan source-repo directories for repos with content.

    Returns list of (repo_id, source_kind, file_count).
    """
    project_root = Path(__file__).resolve().parent.parent
    repos: list[tuple[str, str, int]] = []

    for source_kind, dir_name in [("docs", "source-repo-docs"), ("apiref", "source-repo-apiref")]:
        source_dir = project_root / dir_name
        if not source_dir.exists():
            continue
        for product_dir in sorted(source_dir.iterdir()):
            if not product_dir.is_dir():
                continue
            product_name = product_dir.name.lower().replace(".", "")
            # Count .md files
            md_count = sum(1 for _ in product_dir.rglob("*.md"))
            if md_count == 0:
                continue
            # Build repo_id matching source-repositories.yaml convention
            # e.g. Aspose.OCR -> aspose.ocr.docs
            product_id = product_dir.name.lower()
            if not product_id.startswith(("aspose.", "groupdocs.")):
                # Try to fix casing
                name = product_dir.name
                if name.startswith("Aspose"):
                    product_id = "aspose." + name[len("Aspose."):].lower()
                elif name.startswith("GroupDocs"):
                    product_id = "groupdocs." + name[len("GroupDocs."):].lower()
            repo_id = f"{product_id}.{source_kind}"
            repos.append((repo_id, source_kind, md_count))

    return repos


def run_ingestion() -> None:
    """Main ingestion loop with checkpoint/resume."""
    from adcs.config import clear_settings_cache, get_settings
    from adcs.indexing.index_models import IngestionRunMode
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.runtime.components import build_runtime_components

    clear_settings_cache()
    settings = get_settings()
    log_progress(f"Building runtime components (embedding: {settings.embedding_backend.value}, "
                 f"model: {settings.embedding_model})")
    rc = build_runtime_components(settings=settings)

    service = SourceHugoNormalizationOrchestrationService(
        index_publish_orchestrator=rc.index_publish_orchestrator,
        ingestion_job_repository=rc.ingestion_job_repository,
    )

    # Discover available repos
    available_repos = get_available_repos()
    log_progress(f"Found {len(available_repos)} repos with content")

    # Load checkpoint
    state = load_checkpoint()
    completed_set = set(state["completed"])

    # Filter out already completed repos
    pending_repos = [(r, k, c) for r, k, c in available_repos if r not in completed_set]

    if not pending_repos:
        log_progress("All repos already ingested! Nothing to do.")
        return

    total_files = sum(c for _, _, c in pending_repos)
    log_progress(f"Pending: {len(pending_repos)} repos, ~{total_files:,} files total")
    log_progress(f"Already completed: {len(completed_set)} repos")

    if state["started_at"] is None:
        state["started_at"] = datetime.now(tz=timezone.utc).isoformat()

    overall_start = time.time()
    total_chunks_done = 0
    repos_done = 0

    # Sort: smaller repos first for quick wins
    pending_repos.sort(key=lambda x: x[2])

    for idx, (repo_id, source_kind, file_count) in enumerate(pending_repos, 1):
        state["in_progress"] = repo_id
        save_checkpoint(state)

        log_progress(
            f"\n{'='*60}\n"
            f"[{idx}/{len(pending_repos)}] Starting: {repo_id} (~{file_count:,} files)\n"
            f"{'='*60}"
        )

        repo_start = time.time()
        try:
            op = service.run(
                repo_ids=(repo_id,),
                mode=IngestionRunMode.PUBLISH,
                force_full_reindex=True,
                execute_immediately=True,
            )
            elapsed = time.time() - repo_start

            # Extract stats from operation logs
            stats: dict[str, str] = {}
            error_lines: list[str] = []
            for log_entry in op.logs:
                if log_entry.stream == "stdout" and "[ok]" in log_entry.line:
                    for part in log_entry.line.split():
                        if "=" in part:
                            k, v = part.split("=", 1)
                            if k in ("canonical_documents", "chunks"):
                                stats[k] = v
                if log_entry.stream == "stderr":
                    error_lines.append(log_entry.line)

            docs = stats.get("canonical_documents", "?")
            chunks = stats.get("chunks", "?")

            if op.status in ("completed",):
                state["completed"].append(repo_id)
                state["in_progress"] = None
                chunks_int = int(chunks) if chunks != "?" else 0
                total_chunks_done += chunks_int
                repos_done += 1
                log_progress(
                    f"  OK: {repo_id} | docs={docs} chunks={chunks} | "
                    f"{elapsed:.0f}s ({elapsed/60:.1f}m)"
                )
            else:
                state["failed"].append({
                    "repo_id": repo_id,
                    "status": op.status,
                    "elapsed": elapsed,
                    "errors": error_lines[:5],
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                })
                state["in_progress"] = None
                log_progress(
                    f"  FAILED: {repo_id} | status={op.status} | {elapsed:.0f}s"
                )
                for err in error_lines[:3]:
                    log_progress(f"    ERR: {err[:200]}")

        except Exception as exc:
            elapsed = time.time() - repo_start
            state["failed"].append({
                "repo_id": repo_id,
                "status": "exception",
                "error": str(exc)[:500],
                "elapsed": elapsed,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })
            state["in_progress"] = None
            log_progress(f"  EXCEPTION: {repo_id} | {elapsed:.0f}s | {exc!s:.200}")

        save_checkpoint(state)

        # Progress summary after each repo
        overall_elapsed = time.time() - overall_start
        overall_rate = total_chunks_done / overall_elapsed if overall_elapsed > 0 else 0
        remaining_files = sum(c for r, _, c in pending_repos[idx:])
        log_progress(
            f"\n  Progress: {repos_done}/{len(pending_repos)} repos done | "
            f"{total_chunks_done:,} chunks | "
            f"{overall_rate:.1f} chunks/s avg | "
            f"elapsed {overall_elapsed/3600:.1f}h | "
            f"~{remaining_files:,} files remaining"
        )

    # Final summary
    overall_elapsed = time.time() - overall_start
    log_progress(
        f"\n{'='*60}\n"
        f"INGESTION COMPLETE\n"
        f"{'='*60}\n"
        f"Completed: {len(state['completed'])} repos\n"
        f"Failed: {len(state['failed'])} repos\n"
        f"Total chunks: {total_chunks_done:,}\n"
        f"Total time: {overall_elapsed/3600:.1f}h\n"
        f"{'='*60}"
    )

    if state["failed"]:
        log_progress("\nFailed repos:")
        for f in state["failed"]:
            repo = f["repo_id"] if isinstance(f, dict) else f
            log_progress(f"  - {repo}")

    state["finished_at"] = datetime.now(tz=timezone.utc).isoformat()
    save_checkpoint(state)


if __name__ == "__main__":
    log_progress("Starting full ingestion pipeline")
    try:
        run_ingestion()
    except KeyboardInterrupt:
        log_progress("Interrupted by user (Ctrl+C). Progress saved to checkpoint.")
    except Exception as exc:
        log_progress(f"FATAL ERROR: {exc}")
        raise
