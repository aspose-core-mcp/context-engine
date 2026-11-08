# Runbook: ADCS Backup, Restore, And DR Recovery Smoke

## Purpose

Provide repeatable backup/restore operations for ADCS control-plane artifacts and a deterministic DR smoke check.

## Scope

1. Copied into each backup (paths relative to the workspace root):
   1. `artifacts/config-history`
   2. `artifacts/semantic-review`
   3. `reports/quality-gates`
2. External services (`PostgreSQL`, `Qdrant`, `OpenSearch`) are recorded in each backup manifest as required infrastructure-level backups and must be handled by the backup tooling of the platform that hosts them.

## API Operations

1. Trigger backup:
   1. `POST /admin/v1/system/backups:trigger`
2. List backups:
   1. `GET /admin/v1/system/backups`
3. Trigger restore:
   1. `POST /admin/v1/system/backups/{backup_id}:restore`
4. List operation statuses:
   1. `GET /admin/v1/system/backup-operations`
5. Run DR smoke:
   1. `POST /admin/v1/system/dr:recovery-smoke`

Statuses: `queued`, `running`, `failed`, `completed`.

## Local/CI Smoke

Run:

```bash
make dr-recovery-smoke
```

Artifacts:

1. `reports/dr/recovery-smoke.json`
2. `reports/dr/recovery-smoke.log`

## Recovery Notes

1. Use backup manifests under `artifacts/dr/backups/<backup_id>/manifest.json`.
2. For external services, use the restore procedure of each service:
   1. PostgreSQL PITR / logical dump restore.
   2. Qdrant snapshot restore.
   3. OpenSearch snapshot repository restore.
3. Re-run DR smoke after restore window to confirm control-plane artifacts are recoverable.

## Escalation

1. Treat any `failed` restore operation as a Sev2 incident (see the [incident response playbooks](incident-response-playbooks.md#severity-definitions)).
2. If `dr:recovery-smoke` fails before a release, block the release until the smoke passes.
