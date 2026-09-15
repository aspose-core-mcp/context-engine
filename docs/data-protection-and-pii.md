# Data Protection and PII Controls

This document describes the data-protection controls ADCS implements in code: keyed hashing (pseudonymisation) of client IP addresses and query text, and PII masking of application logs. Both live in [`src/adcs/ops/privacy.py`](../src/adcs/ops/privacy.py) and are covered by [`tests/test_privacy.py`](../tests/test_privacy.py).

## Scope

The public MCP and REST surfaces are anonymous: there are no end-user accounts, usernames, or emails (see [`rbac-and-audit.md`](rbac-and-audit.md)). Indirect identifiers can still reach operational data; these controls apply to them:

| Data | Control | Where it is applied |
|------|---------|---------------------|
| Client IP address | Pseudonymised as `ip_hash` via `keyed_hash(..., purpose="ip_hash")` | `src/adcs/api/abuse_guard.py`, `src/adcs/api/public_docs_query.py`, `src/adcs/api/admin_system.py` |
| Query text | Grouped by `query_fingerprint`, a keyed hash of the lower-cased normalized query (`purpose="query_fingerprint"`) | `src/adcs/retrieval/query_planner.py` |
| Log records of the `adcs.*` logger tree | Masked by `PIIMaskingFilter` before output | `src/adcs/ops/logging_config.py` |

## Keyed Hashing

`keyed_hash(value, *, purpose)` returns an HMAC-SHA256 hex digest.

- **Key.** The key is `ADCS_HASH_SECRET` combined with the `purpose` string. Mixing the purpose into the key separates the pseudonym spaces: the `ip_hash` and the `query_fingerprint` of the same string differ, so one cannot be used to confirm the other.
- **Why keyed.** An unsalted SHA-256 of an IPv4 address is not a pseudonym: the keyspace is 2³², so the whole table can be enumerated in seconds and the stored value is effectively a reversible encoding of the address.
- **Missing key.** If `ADCS_HASH_SECRET` is unset or blank, `keyed_hash` falls back to an unkeyed SHA-256 of `"<purpose>:<value>"` and logs a single warning per process instead of failing. A missing key must not take an environment down, but it must not pass silently either.
- **Profile guard.** `Settings` (`src/adcs/config/settings.py`) refuses to start the `staging` and `prod` profiles when `ADCS_HASH_SECRET` is empty; the `dev` profile allows it and relies on the warning above.
- **Environment lookup.** `keyed_hash` reads `ADCS_HASH_SECRET` from the process environment at call time rather than through `Settings`, so it does not depend on settings construction succeeding. Every process that computes these hashes needs the variable in its real environment: a value that exists only in `.env.local` satisfies the `Settings` check but is not seen by the hashing code.
- **Rotation.** There is no built-in rotation. Changing `ADCS_HASH_SECRET` changes every pseudonym, so hashes computed before and after a rotation cannot be joined.

## PII Masking Rule Pack

`mask_pii(text)` replaces sensitive patterns with stable placeholders. It covers seven baseline classes:

| Class | Pattern | Replacement |
|-------|---------|-------------|
| Credential query parameters | `password`, `passwd`, `pwd`, `token`, `secret`, `api_key` / `api-key` / `apikey`, `access_key` / `access-key` / `accesskey`, `auth` (case-insensitive) | `<name>=[param-redacted]` |
| Email addresses | `local@domain.tld` | `[email-redacted]` |
| JWTs | three dot-separated segments starting with `eyJ` | `[jwt-redacted]` |
| API keys | tokens prefixed `sk`, `pk`, `rk`, `ghp`, `gho`, or `xoxb`/`xoxa`/`xoxp`/`xoxr`/`xoxs`, followed by `-` or `_` and at least 8 characters; `Bearer <token>` | `[apikey-redacted]` |
| IP addresses | IPv6 and IPv4 | `[ip-redacted]` |
| Banking identifiers | IBAN-shaped strings and card-shaped digit runs (13–19 digits, optionally grouped) | `[bank-redacted]` |
| Phone numbers | a leading `+` (E.164), or at least three separator-delimited digit groups | `[phone-redacted]` |

Order matters. Credential query parameters are redacted first; then the rules run in the order email → JWT → API key → IPv6 → IPv4 → bank → phone, so JWTs and API keys are matched before the generic digit-run rules, which would otherwise claim parts of them. A bare digit run is deliberately **not** treated as a phone number, so identifiers such as `snap-00000042` survive masking.

### Logging filter

`PIIMaskingFilter` applies `mask_pii` to a record's message and to every string argument (positional or mapping-style). `configure_logging()` in `src/adcs/ops/logging_config.py` installs it on the JSON stdout handler of the `adcs` logger, so it covers every `adcs.*` record regardless of which module emitted it — including the MCP gateway, which logs up to 500 characters of raw tool arguments at INFO. The API application calls `configure_logging()` at startup (`src/adcs/api/main.py`); other entry points need to call it to get the same masking. Loggers outside the `adcs` tree are not reconfigured.

### Rule-pack versioning

`PII_RULES_VERSION` (currently `"2026-07-30.1"`) identifies the active pattern set. Bump it whenever the patterns change so that replayed events can record which rules were in force; the constant is not attached to log records automatically.

### Tests

`tests/test_privacy.py` checks both directions on purpose: every baseline class is masked, **and** technical log lines survive masking. Over-masking is its own failure — an early version of the phone pattern matched snapshot ids such as `snap-00000042`, which would have made operational logs unreadable, since snapshot and chunk ids appear in nearly every line. The tests also cover keyed-hash stability and purpose separation, that the key changes the digest, the missing-secret warning, the logging filter, and rule-pack versioning.

## Configuration Summary

| Setting | Default | Effect |
|---------|---------|--------|
| `ADCS_HASH_SECRET` | empty | HMAC key for `ip_hash` and `query_fingerprint`; required when `ADCS_ENV` is `staging` or `prod` |
| `ADCS_ENV` | `dev` | Selects the profile (`dev`, `staging`, `prod`) whose validation rules apply |
| `ADCS_LOG_LEVEL` | `info` | Level for the `adcs` logger tree; masking applies to every record the handler emits |

## Related Documents

- [`rbac-and-audit.md`](rbac-and-audit.md) — admin roles, audit trail, and PII handling in audit records
- [`secrets-handling.md`](secrets-handling.md) — how `ADCS_HASH_SECRET` and other secrets are supplied
