# Hugo Conversion Prompt Pack

Versioned prompts for converting Hugo markdown into `adcs.normalized_document.v1`.

## Files
- `system.v1.txt`: strict converter behavior.
- `user.base.v1.txt`: common payload template.
- `user.apiref.v1.txt`: API reference specialization.
- `user.docs.v1.txt`: guides/how-to specialization.
- `eval-rubric.v1.md`: scoring checklist for manual review.
- `MANIFEST.yaml`: authoritative version + sha256 + change-history record for every prompt.

## Change discipline

Every prompt edit must pass `tests/test_prompt_pack_integrity.py`. The test
hashes each file and compares against `MANIFEST.yaml`. If you intentionally
change a prompt, do one of:

1. **Add a new versioned file** (e.g. `system.v2.txt`) and append a new
   manifest entry. The old `v1` file stays committed for replay/audit.
2. **Bump `version` on the existing entry** in `MANIFEST.yaml` and append
   a `change_history` record explaining the change (author, date, rationale).

Then recompute the hash and update the `sha256` field:

```bash
shasum -a 256 prompts/hugo_conversion/<filename>
```

This gives every prompt a tracked lineage rather than silent in-place edits.

## Variants

Prompts are wired into ingestion through conversion variants declared in
[`config/ingestion_prompt_registry.json`](../../config/ingestion_prompt_registry.json)
(path set by `ADCS_INGESTION_PROMPT_REGISTRY_CONFIG_PATH`) and loaded by
[`src/adcs/ingestion/prompt_registry.py`](../../src/adcs/ingestion/prompt_registry.py).
Each variant names its `prompt_pack_version` and the system and user prompt
files it uses. When the registry is enabled and lists several variants, each
source file is assigned to one of them deterministically — a hash of the seed,
experiment id, repository, source kind and path, weighted by `weight_pct` — so
repeated runs convert the same file with the same prompts.
