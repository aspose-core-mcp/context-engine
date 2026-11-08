# Secrets Handling Policy

## Principle

No real secret value is ever committed to the repository. Tracked example files contain only safe placeholders. All real values are sourced from runtime secret stores at deploy time.

## What Is Tracked vs Not Tracked

| Path | Tracked? | Contents |
|------|----------|----------|
| `.env.example` | yes | Placeholder values only (`replace-me`, empty strings, localhost defaults) |
| `.env.compose.example` | yes | Placeholder values for docker-compose dev stack |
| `.env.local` | **no** (gitignored) | Real local-dev values |
| `.env.compose.local` | **no** (gitignored) | Real docker-compose local values |
| `infra/helm/adcs/values*.yaml` | yes | Non-sensitive Helm values; sensitive fields use `replace-me` or empty placeholders |
| Real K8s Secrets | **no** | Rendered at deploy time from values supplied by your secret store |

The untracked env files are excluded via `.gitignore`.

## Secret Sources by Environment

### Local Development
- Copy `.env.example` to `.env.local` and fill in real values
- `.env.local` is gitignored; never commit it
- Example workflow:
  ```bash
  cp .env.example .env.local
  # edit .env.local with real values
  make run
  ```
- `ADCS_HASH_SECRET` is read by the hashing code directly from the process environment, so export it rather than relying on `.env.local` alone — see [`docs/data-protection-and-pii.md`](data-protection-and-pii.md)

### CI
- The GitHub Actions workflow (lint, type-check, unit tests, admin UI build, container image builds) needs **no secrets**
- If you add a job that needs one, store it in the CI system's secret store and reference it by variable name — never write a value into a workflow file

#### Integration-test database

Integration tests run against the `postgres:16-alpine` container from
`docker-compose.integration.yml` (`make infra-up`). Its credentials are
**functional placeholders**, not real secrets — the tracked `.env.compose.example`
uses `POSTGRES_USER=adcs`, `POSTGRES_DB=adcs`, and `POSTGRES_PASSWORD=replace-me-local`.
The container is disposable and must not be reachable from outside the host or
job network. If a CI job starts this stack, pass the password from the CI secret
store instead of hard-coding it.

### Kubernetes — Helm

The committed `values.yaml` carries **placeholders only**; real credentials are
supplied at install time and rendered into a single K8s `Secret`:

- `infra/helm/adcs/templates/secret-env.yaml` renders a `Secret`
  `<fullname>-secrets` whose `stringData` keys come from `global.secretEnv.*`:
  `ADCS_API_KEY`, `POSTGRES_DSN`, `RABBITMQ_URL`, `ADCS_HASH_SECRET`,
  `ADCS_EMBEDDING_API_KEY`.
- `infra/helm/adcs/templates/_helpers.tpl` wires the app env to that Secret via
  `valueFrom.secretKeyRef` — never plaintext `value:`.
- Keep the real values in your secret store and pass them at install time,
  either with `--set-string global.secretEnv.<KEY>=...` or through an
  external-secrets mechanism, such as a values file that your secret-management
  tooling renders at deploy time and never commits. The
  [chart README](../infra/helm/adcs/README.md) shows the full command.
- Render manifests for review (`helm template`) **without** the secret values,
  so no rendered file or build artifact contains a cleartext secret.
- Make the deploy step **fail fast** (`: "${VAR:?...}"`) if any secret variable
  is unset — never deploy with empty/placeholder credentials.
- `Settings._validate_profile_constraints` refuses to boot the `prod` profile if
  `POSTGRES_DSN` or `RABBITMQ_URL` still contains a `replace-me` placeholder or a
  default credential (`adcs:adcs@`, `guest:guest@`), and refuses the `staging`
  and `prod` profiles if `ADCS_API_KEY` is `replace-me` or `ADCS_HASH_SECRET` is
  empty — fail-fast, not silent degradation.

> Non-secret service endpoints (`REDIS_URL`, `QDRANT_URL`, `OPENSEARCH_URL`)
> stay as plaintext `global.externalServices` values — they carry no credential.

Whatever the delivery mechanism, the repository-side invariant is the same:
**no secret value is committed here**.

## Categories of Secrets

| Category | Examples | Storage |
|----------|----------|---------|
| API auth | `ADCS_API_KEY` (admin keys) | K8s Secret |
| Database | `POSTGRES_DSN` | K8s Secret |
| Message queue | `RABBITMQ_URL` | K8s Secret |
| Hashing key | `ADCS_HASH_SECRET` (keyed `ip_hash` / `query_fingerprint`) | K8s Secret |
| LLM and embedding API keys | `ADCS_EMBEDDING_API_KEY`, `ADCS_TRANSLATION_LLM_API_KEY`, `ADCS_INGESTION_LLM_API_KEY` | K8s Secret |
| Image pull credentials | Registry credentials referenced by `global.imagePullSecrets` | K8s Secret (created outside the chart) |

## Rotation Policy

| Secret type | Rotation cadence | Trigger |
|-------------|------------------|---------|
| Admin API keys | 90 days | Calendar; immediate on suspected leak |
| Database passwords | 180 days | Calendar; immediate on suspected leak |
| LLM API keys | 90 days | Calendar; immediate on quota anomaly |
| TLS certificates | 90 days (auto-renew) | cert-manager |
| Service-account tokens | 365 days | Calendar |

Rotating admin API keys created through the admin API:

- **Immediate:** `POST /admin/v1/keys/{key_id}:rotate` creates a replacement key with the same scopes, returns its token once, and disables the old key.
- **With an overlap window:** create a new key with the same scopes (`POST /admin/v1/keys`), distribute it through a secure channel, then disable the old key (`POST /admin/v1/keys/{key_id}:disable`) once consumers have switched.

Each step is recorded in the key audit log (`GET /admin/v1/keys/audit`). The bootstrap superuser key in `ADCS_API_KEY` is rotated by changing the secret and redeploying.

## Detection and Response

### Pre-commit
- `.pre-commit-config.yaml` runs `check-added-large-files` from `pre-commit-hooks` (catches accidental binary blobs)
- No secret scanner is configured by default; a `detect-secrets` hook can be added to `.pre-commit-config.yaml`

### CI
- Review pull requests that touch env files, Helm values or configuration for secret values

### Runtime
- Structured logs apply PII masking — see [`docs/data-protection-and-pii.md`](data-protection-and-pii.md)
- The key audit log records every admin API key creation, scope change, enable and disable; a rotation appears as a creation plus a disable, both with a `rotation:` reason

### If a Real Secret Is Committed

1. Rotate it immediately (do not just delete the file — git history persists)
2. Check logs and the key audit log for use of the exposed value — see [`infra/runbooks/incident-response-playbooks.md`](../infra/runbooks/incident-response-playbooks.md)
3. Scrub history with `git filter-repo`
4. Force-push the rewritten history and ask everyone with a clone to re-clone
5. If you find a secret committed to this repository, report it privately as described in [`SECURITY.md`](../SECURITY.md)

## Why `.env.example` Is Safe to Track

- All values in `.env.example` are placeholders (`replace-me`, empty strings, or localhost defaults)
- The file serves as a template; new developers copy it to `.env.local` (gitignored) and fill in real values
- See the header comment block in `.env.example` for in-file clarification

This is a standard industry pattern (used by Django, Rails, FastAPI, Next.js, etc.) and is preferred over leaving the format undocumented.
