#!/usr/bin/env python3
"""Re-ingest apiref repos into the LOCAL Postgres structured store.

Sequential, resumable, marker-driven: a long re-ingest can run detached and
report progress through a marker file instead of a waiting shell.

Why not scripts/parallel_ingest.py: that runner predates ADR-011 and never
injects ``apiref_symbol_store`` into the orchestration service, so apiref
repos take the legacy dense path — they embed chunks and then fail on the
retired ``apiref_dense_v1`` Qdrant write, which per-repo failure isolation
reports as a *completed* run with 0 documents. This driver wires the store exactly
the way the celery worker does, which flips ``_apiref_structured_only`` on:
no embeddings, no Qdrant/OpenSearch, parse -> staging -> Postgres.

Usage:
  APIREF_STRUCTURED_STORE_ENABLED=true PYTHONPATH=./src \
      python3 scripts/ops/reingest_apiref_local.py --repos aspose.words.apiref ...
  ... --all           # every *.apiref repo from the registry
  ... --marker PATH   # default logs/reingest_apiref.marker.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class RepoTimeout(Exception):
    pass


def _alarm(signum: object, frame: object) -> None:
    raise RepoTimeout()


def registry_apiref_repos() -> list[str]:
    import yaml

    reg = yaml.safe_load((ROOT / "config/source-repositories.yaml").read_text())
    out: set[str] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            rid = o.get("repo_id", "")
            if isinstance(rid, str) and rid.endswith(".apiref"):
                out.add(rid)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(reg)
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="*", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--marker", default="logs/reingest_apiref.marker.json")
    ap.add_argument("--timeout", type=int, default=14400)
    args = ap.parse_args()

    marker_path = ROOT / args.marker
    marker_path.parent.mkdir(exist_ok=True)
    state: dict = {"done": [], "failed": [], "current": None, "counts": {}, "started_at": None}
    if marker_path.exists():
        state = json.loads(marker_path.read_text())

    def save() -> None:
        marker_path.write_text(json.dumps(state, indent=2))

    repos = args.repos or (registry_apiref_repos() if args.all else [])
    if not repos:
        raise SystemExit("no repos given (use --repos or --all)")
    pending = [r for r in repos if r not in state["done"]]
    if not state.get("started_at"):
        state["started_at"] = datetime.now(tz=timezone.utc).isoformat()
    print(f"[main] repos={len(repos)} pending={len(pending)}", flush=True)

    from adcs.config import clear_settings_cache, get_settings
    from adcs.indexing.apiref_symbol_store import build_apiref_symbol_store
    from adcs.indexing.index_models import IngestionRunMode
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.runtime.components import build_runtime_components

    import psycopg

    clear_settings_cache()
    settings = get_settings()
    if not settings.apiref_structured_store_enabled:
        raise SystemExit("APIREF_STRUCTURED_STORE_ENABLED must be true for this driver")
    rc = build_runtime_components(settings=settings)
    store = build_apiref_symbol_store(
        enabled=True, postgres_dsn=settings.postgres_dsn
    )
    if store is None:
        raise SystemExit("symbol store unavailable (Postgres down?)")
    service = SourceHugoNormalizationOrchestrationService(
        index_publish_orchestrator=rc.index_publish_orchestrator,
        ingestion_job_repository=rc.ingestion_job_repository,
        apiref_symbol_store=store,
    )

    dsn = settings.postgres_dsn.replace("postgresql+psycopg://", "postgresql://")

    def product_count(product_id: str) -> int:
        try:
            with psycopg.connect(dsn, connect_timeout=8) as conn:
                row = conn.execute(
                    "select count(*) from symbols where product = %s",
                    (product_id,),
                ).fetchone()
                return int(row[0]) if row else 0
        except psycopg.errors.UndefinedTable:
            return 0
        except Exception:
            return -1

    for rid in pending:
        product = rid.removesuffix(".apiref")
        state["current"] = rid
        save()
        # A killed run leaves REVIEW-tier staging that force_full_reindex would
        # re-promote as-is (stale staging) — parse fresh instead.
        for stale in (ROOT / "data-apiref" / product, ROOT / "data-apiref" / rid):
            if stale.exists():
                shutil.rmtree(stale)
        t0 = time.time()
        print(f"[run] START {rid}", flush=True)
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(args.timeout)
        try:
            op = service.run(
                repo_ids=(rid,),
                mode=IngestionRunMode.PUBLISH,
                force_full_reindex=True,
                # The 24h idempotency window would replay earlier operations
                # from the same day verbatim — key each attempt.
                idempotency_key=f"reingest-{rid}-{int(time.time())}",
                bypass_staging_replay=True,
                execute_immediately=True,
            )
            signal.alarm(0)
            skipped = any("[skipped]" in le.line for le in op.logs)
            n = product_count(product)
            status = op.status.value if hasattr(op.status, "value") else str(op.status)
            elapsed = int(time.time() - t0)
            if status == "completed" and not skipped and n > 0:
                state["done"].append(rid)
                state["counts"][product] = n
                print(f"[run] OK {rid} symbols={n} in {elapsed}s", flush=True)
            else:
                reason = next(
                    (le.line for le in op.logs if "[skipped]" in le.line), f"status={status} symbols={n}"
                )
                state["failed"].append({"repo": rid, "reason": reason[:300]})
                print(f"[run] FAIL {rid} in {elapsed}s: {reason[:200]}", flush=True)
        except RepoTimeout:
            signal.alarm(0)
            state["failed"].append({"repo": rid, "reason": "timeout"})
            print(f"[run] TIMEOUT {rid}", flush=True)
        except BaseException as e:  # noqa: BLE001 - isolate any repo failure, keep going
            signal.alarm(0)
            state["failed"].append({"repo": rid, "reason": f"{type(e).__name__}: {str(e)[:200]}"})
            print(f"[run] EXC {rid}: {type(e).__name__}: {str(e)[:200]}", flush=True)
        state["current"] = None
        save()

    state["finished_at"] = datetime.now(tz=timezone.utc).isoformat()
    save()
    print(
        f"[main] DONE done={len(state['done'])} failed={len(state['failed'])} "
        f"total_symbols={sum(state['counts'].values())}",
        flush=True,
    )


if __name__ == "__main__":
    main()
