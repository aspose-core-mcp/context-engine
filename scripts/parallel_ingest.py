#!/usr/bin/env python3
"""Multi-worker fault-tolerant ingestion.

Env overrides:
  ADCS_INGEST_WORKERS         (default 4)
  ADCS_EMBEDDING_BATCH_SIZE   (default 64)
  ADCS_REPO_TIMEOUT_SECONDS   (default 3600)
"""
from __future__ import annotations
import fcntl, json, os, signal, sys, time
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

LOGS_DIR = ROOT / 'logs'
LOGS_DIR.mkdir(exist_ok=True)
CHECKPOINT = LOGS_DIR / 'ingestion_checkpoint.json'
LOCK_FILE = LOGS_DIR / 'checkpoint.lock'
PROGRESS_LOG = LOGS_DIR / 'parallel_ingest.log'

WORKERS = int(os.environ.get('ADCS_INGEST_WORKERS', '4'))
BATCH_SIZE = int(os.environ.get('ADCS_EMBEDDING_BATCH_SIZE', '64'))
REPO_TIMEOUT = int(os.environ.get('ADCS_REPO_TIMEOUT_SECONDS', '3600'))


def log(tag, msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] [{tag}] {msg}'
    print(line, flush=True)
    try:
        with PROGRESS_LOG.open('a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def with_lock(fn):
    LOCK_FILE.touch(exist_ok=True)
    with LOCK_FILE.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_state():
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text())
        except Exception:
            pass
    return {'completed': [], 'failed': [], 'in_progress_by_worker': {},
            'started_at': None, 'finished_at': None}


def save_state(state):
    CHECKPOINT.write_text(json.dumps(state, indent=2))


class RepoTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise RepoTimeout()


def worker_main(worker_id: int, repo_queue, result_queue):
    # Override batch size before any provider construction
    from adcs.indexing import embedding_provider as _ep
    _ep.OpenAICompatibleEmbeddingProvider._DEFAULT_BATCH_SIZE = BATCH_SIZE

    from adcs.config import clear_settings_cache, get_settings
    from adcs.indexing.index_models import IngestionRunMode
    from adcs.ingestion.source_hugo_normalization_orchestrator import (
        SourceHugoNormalizationOrchestrationService,
    )
    from adcs.runtime.components import build_runtime_components

    clear_settings_cache()
    settings = get_settings()
    rc = build_runtime_components(settings=settings)
    service = SourceHugoNormalizationOrchestrationService(
        index_publish_orchestrator=rc.index_publish_orchestrator,
        ingestion_job_repository=rc.ingestion_job_repository,
    )
    log(f'w{worker_id}', f'ready (batch_size={BATCH_SIZE}, model={settings.embedding_model})')

    while True:
        try:
            item = repo_queue.get(timeout=5)
        except Exception:
            continue
        if item is None:
            log(f'w{worker_id}', 'sentinel received, exiting')
            break

        repo_id, file_count = item
        log(f'w{worker_id}', f'START {repo_id} (~{file_count} files)')
        t0 = time.time()
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(REPO_TIMEOUT)
        try:
            op = service.run(
                repo_ids=(repo_id,),
                mode=IngestionRunMode.PUBLISH,
                # `force_full_reindex=True` enables staging_replay loading
                # in `_normalize_repository`. Combined with the intra-normalize
                # checkpoint, this means a mid-parse crash resumes from the
                # last per-N-files dump and a mid-publish crash resumes from
                # the prior REVIEW-tier staging without re-running normalize.
                force_full_reindex=True,
                execute_immediately=True,
            )
            signal.alarm(0)
            status = op.status.value if hasattr(op.status, 'value') else str(op.status)
            docs = chunks = 0
            for le in op.logs:
                if le.stream == 'stdout' and '[ok]' in le.line:
                    for part in le.line.split():
                        if '=' in part:
                            k, v = part.split('=', 1)
                            if k == 'canonical_documents' and v.isdigit(): docs = int(v)
                            elif k == 'chunks' and v.isdigit(): chunks = int(v)
            elapsed = time.time() - t0
            if status == 'completed':
                result_queue.put(('ok', repo_id, worker_id, docs, chunks, elapsed, None))
                log(f'w{worker_id}', f'OK {repo_id} docs={docs} chunks={chunks} in {elapsed:.0f}s')
            else:
                result_queue.put(('non_ok', repo_id, worker_id, 0, 0, elapsed, f'status={status}'))
                log(f'w{worker_id}', f'NON-OK {repo_id} status={status} in {elapsed:.0f}s')
        except RepoTimeout:
            signal.alarm(0)
            elapsed = time.time() - t0
            result_queue.put(('timeout', repo_id, worker_id, 0, 0, elapsed, 'timeout'))
            log(f'w{worker_id}', f'TIMEOUT {repo_id} after {elapsed:.0f}s')
        except BaseException as e:
            signal.alarm(0)
            elapsed = time.time() - t0
            err = f'{type(e).__name__}: {str(e)[:200]}'
            result_queue.put(('error', repo_id, worker_id, 0, 0, elapsed, err))
            log(f'w{worker_id}', f'EXC {repo_id} {err} (in {elapsed:.0f}s)')


def main():
    from run_full_ingestion import get_available_repos

    def update_init():
        s = load_state()
        if not s.get('started_at'):
            s['started_at'] = datetime.now(tz=timezone.utc).isoformat()
        save_state(s)
        return s

    state = with_lock(update_init)

    available = get_available_repos()
    available.sort(key=lambda x: x[2])
    completed_set = set(state.get('completed', []))
    pending = [(r, fc) for r, _kind, fc in available if r not in completed_set]
    log('main', f'workers={WORKERS} batch={BATCH_SIZE} repo_timeout={REPO_TIMEOUT}s '
                f'available={len(available)} done={len(completed_set)} pending={len(pending)}')
    if not pending:
        log('main', 'nothing to do')
        return

    repo_q = mp.Queue()
    result_q = mp.Queue()

    workers = []
    for i in range(WORKERS):
        p = mp.Process(target=worker_main, args=(i, repo_q, result_q), daemon=False)
        p.start()
        workers.append(p)
    log('main', f'started {WORKERS} workers')

    for repo_id, fc in pending:
        repo_q.put((repo_id, fc))
    for _ in range(WORKERS):
        repo_q.put(None)

    total = len(pending)
    received = 0
    overall_start = time.time()
    while received < total:
        try:
            kind, repo_id, worker_id, docs, chunks, elapsed, err = result_q.get(timeout=60)
        except Exception:
            alive = sum(1 for w in workers if w.is_alive())
            if alive == 0:
                log('main', 'all workers died, exiting')
                break
            continue

        def make_updater(_k=kind, _r=repo_id, _e=err, _t=elapsed):
            def f():
                s = load_state()
                if _k == 'ok':
                    if _r not in s['completed']:
                        s['completed'].append(_r)
                else:
                    s['failed'].append({
                        'repo_id': _r, 'reason': _k, 'error': _e,
                        'elapsed': _t, 'ts': datetime.now(tz=timezone.utc).isoformat(),
                    })
                save_state(s)
            return f
        with_lock(make_updater())

        received += 1
        elapsed_total = time.time() - overall_start
        rate_per_hour = (received / elapsed_total * 3600) if elapsed_total > 0 else 0
        eta_h = (total - received) / rate_per_hour if rate_per_hour > 0 else 0
        log('main', f'progress {received}/{total} ({100*received//total}%) '
                    f'~{rate_per_hour:.1f}repos/h ETA={eta_h:.1f}h — last={kind} {repo_id}')

    for p in workers:
        p.join(timeout=30)
        if p.is_alive():
            p.terminate()

    def finalize():
        s = load_state()
        s['finished_at'] = datetime.now(tz=timezone.utc).isoformat()
        save_state(s)
    with_lock(finalize)
    log('main', f'DONE total_time={(time.time()-overall_start)/60:.1f}m')


if __name__ == '__main__':
    main()
