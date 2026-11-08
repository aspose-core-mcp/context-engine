# Continuous Quality-Improvement Multi-Agent Loop

ADCS runs a continuous, multi-agent quality-improvement loop alongside the
serving stack. **Seven cooperating agents** (six always-on, plus an
optional shadow LLM judge that activates whenever it's wired) inspect
recent `query_docs` responses, correlate trends across cycles, diagnose
patterns in low-quality results, propose remediations, and gate the
proposals through a strict safety policy. **The default mode is
read-only** — nothing destructive auto-executes. The loop complements the
existing single-shot quality gates in `src/adcs/quality_gates/`.

## Why this exists, in one paragraph

The release-time `golden_eval` LLM-judge already verifies that a curated query
set passes acceptance gates. But it runs only at release; production traffic
drifts in ways the golden set cannot catch (a new product version, an upstream
docs reshuffle, a regression that escapes a partial publish). The
quality-improvement loop watches *production* responses on a continuous
schedule, scores them deterministically, looks for patterns, and proposes
the smallest reasonable fix — opening an incident at the conservative end,
queuing a fusion-weight tweak for human approval at the other. Every message
between agents is persisted to an append-only JSONL audit log so the loop's
reasoning is fully reproducible.

## The seven agents

| Agent | Consumes | Emits | Job |
|-------|----------|-------|-----|
| **CrossCycleCorrelationAgent** | recent `CycleSummary[]` from disk | `CorrelationReport` (1 per cycle) | Read-only trend analysis across the last N cycles (default 12). Computes sample-volume trend, duration trend, rejection rate, rejection velocity, adaptation density, and emits deterministic recommendations. **The loop's only cross-cycle awareness lives here — all other agents are cycle-local.** The report is threaded into AdaptiveAgent.adapt() so cross-cycle trends can drive proactive calibration mutations. |
| **JudgeAgent** | `QueryResponseSample[]` | `QualityVerdict[]` | Score each sample on citation accuracy, version match, FQN consistency, confidence calibration. Deterministic rules, **not** LLM-judged — the deterministic verdict stays authoritative end-to-end. |
| **LLMJudgeAgent** *(optional shadow)* | `QueryResponseSample[]` + deterministic `QualityVerdict[]` | `JudgeAgreementReport` (1 per cycle when wired) | Optional shadow LLM judge. Runs only when injected via `Coordinator(llm_judge=…)`. Compares an LLM-assigned score against the deterministic verdict on a sampled subset (default 20%, cap 10/cycle). **Does not alter cycle verdicts** — produces a single agreement report so sustained disagreement above tolerance flags rubric drift. |
| **DiagnosisAgent** | `QualityVerdict[]` | `DiagnosisReport[]` | Cluster low-score samples by scope; assign one root cause from a fixed taxonomy. Detectors: scoped product/language regression, version-filter mismatch, lane imbalance, and (when `prompt_pack_version` is present on the verdicts) cross-variant prompt under-performance — the last one is the trigger that drives the self-evolving-prompts surface. |
| **ProposalAgent** | `DiagnosisReport[]` | `RemediationProposal[]` | One-to-one mapping from root cause to typed action (open incident, adjust fusion weights, rollback snapshot, adjust prompt variant, track anomaly). |
| **GuardAgent** | `RemediationProposal[]` | `GuardDecision[]` | Apply the safety policy. Auto-approve tracking; queue everything else for human approval. |
| **AdaptiveAgent** | `QualityVerdict[]` + `GuardDecision[]` + `CorrelationReport` + previous `CalibrationState` | `AdaptationEvent` (≤1 per cycle) + new `CalibrationState` | Drift the agents' tunable parameters within hard bounds based on observed cycle outcomes and cross-cycle trends. **This is what makes the loop adaptive rather than a fixed multi-agent pipeline.** |

The Coordinator drives the seven agents in fixed order
(Correlate → Judge → LLMJudge[opt] → Diagnose → Propose → Guard → Adapt)
over an in-memory message bus and persists every message to the JSONL
audit log. The CrossCycleCorrelationAgent runs first; its report does
not gate the cycle but **is** threaded into the AdaptiveAgent's
adapt() call at the end so trends drive proactive calibration
mutations. The shadow LLMJudgeAgent runs immediately after the
deterministic Judge when wired; it emits a single agreement report and
otherwise leaves the verdict batch untouched. The AdaptiveAgent runs
at end of cycle and writes the updated calibration state to
`reports/quality-loop/calibration-state.json` (the default
`--calibration-state` path of `run_cycle.py`) so the next cycle starts
from the new tuning.

```
[Correlate] ──CorrelationReport──┐
recent CycleSummary[]            │  (read-only on the in-cycle agents; fed into Adapt below)
                                 │
samples ──► [Judge] ──verdicts──►├──► [LLMJudge?] ──agreement──► (audit log)
                  │              │           │
                  │              │           └── shadow only; does not mutate verdicts
                  │              ▼
                  │   [Diagnose] ──diagnoses──► [Propose] ──proposals──► [Guard] ──decisions──► [Adapt]
                  │           │                         │                       │                  ▲
                  │           │                         │                       │                  │
                  └───────────┴──── all messages ───────┴───────────────────────┘                  │
                                            │                                                      │
                                            ▼                                                      │
                              reports/quality-loop/audit-log.jsonl                                 │
                                       (generated, append-only)                                    │
                                                                                                   │
                              CorrelationReport ─────────────────────────────────────────────────► │
                              (trends drive proactive calibration mutations)
```

## Safety policy (the hard invariants)

These three invariants are encoded in `GuardAgent` and verified by the test
suite. Any change requires a deliberate test update first — the test failure
is intentional friction.

1. **`ROLLBACK_SNAPSHOT` always requires human approval.** No flag can override
   this. A loop-initiated rollback could destroy days of work; humans only.
2. **`ADJUST_FUSION_WEIGHTS` requires human approval in default safe mode.**
   It can be auto-approved only when (a) the operator has flipped the
   `permit_auto_fusion_weight_adjust` feature flag explicitly, AND (b) the
   per-proposal confidence is ≥ 0.95, AND (c) blast radius is within the
   configured cap. All three conditions must hold; missing any one queues
   for human approval.
3. **Blast radius above `absolute_blast_cap` is REJECTED outright,** regardless
   of action. The cap protects against runaway loops that would propose a
   fleet-wide change.

In addition, `OPEN_INCIDENT` always queues for human approval (the loop just
signals; a human triages). `ADJUST_PROMPT_VARIANT` (self-evolving-prompt
surface) always queues for human approval — there is no feature flag for
auto-approval, because prompt switches are LLM-behavioural changes that
operators must review before applying.

| Action | Default safe mode | With `permit_auto_fusion_weight_adjust=True` |
|--------|-------------------|-----------------------------------------------|
| `TRACK_ANOMALY` | auto-approved (within blast cap) | same |
| `OPEN_INCIDENT` | needs human | needs human |
| `ADJUST_FUSION_WEIGHTS` | needs human | auto if confidence ≥ 0.95 AND within blast cap |
| `ADJUST_PROMPT_VARIANT` | needs human | **still** needs human (no flag) |
| `ROLLBACK_SNAPSHOT` | needs human | **still** needs human |

## Adaptive calibration

The AdaptiveAgent reads four tunables from the persistent calibration
state and applies at most one bounded mutation per cycle:

| Tunable | Hard bounds | What triggers a change |
|---------|-------------|------------------------|
| `judge.score_low_threshold` | 0.50 – 0.85 | Low-score sample fraction far from target (0.30) |
| `diagnosis.minimum_low_ratio` | 0.20 – 0.70 | (Reserved for future trigger; bounded) |
| `proposal.high_confidence_floor` | 0.70 – 0.95 | Auto-approval rate far from target (0.60) |
| `guard.auto_approve_blast_cap` | 25 – 500 | Tightens (×0.5) on any REJECTED outcome; relaxes (+10) per cycle after 5 clean cycles |

Mutation priority (highest urgency first):

1. **Any REJECTED outcome** → halve `guard.auto_approve_blast_cap`. Most
   urgent: blast-radius drift can compromise the safety guarantees.
2. **Trend-aware proactive tightening** — when the `CorrelationReport`
   shows a sustained rejection-rate ≥ `proactive_tighten_rejection_rate`
   (default 0.20) and the cap is not at its hard minimum, halve the cap
   even if the current cycle alone did not produce a rejection. This
   cross-cycle reflex means calibration is no longer purely reactive to a
   single cycle.
3. **Sustained clean streak** (≥ 5 cycles since last rejection) → relax
   the cap by `+10` toward baseline.
4. **Judge threshold drift**: low-score fraction outside `target ± 0.10`
   → raise or lower the threshold by `±0.01`.
5. **Proposal floor drift**: auto-approval rate outside `target ± 0.20`
   → raise or lower the floor by `±0.01`.
6. Otherwise `NO_OP`.

Every mutation is recorded as an `AdaptationEvent` in the audit log, so
the calibration trajectory is fully reproducible from the JSONL
file alone.

**Things the AdaptiveAgent CANNOT mutate** (intentional, encoded as
test-asserted invariants):

- The `absolute_blast_cap` (the hard ceiling that rejects fleet-wide
  proposals outright).
- The `permit_auto_fusion_weight_adjust` feature flag (operator-only).
- The `permit_auto_rollback` flag (rollback always needs a human;
  the flag exists only for tests, never auto-enabled).
- The set of `auto_approved_actions` (only `TRACK_ANOMALY` is in it;
  expanding this set requires a deliberate code change + test update).

## Operating mode

The loop runs **read-only**. Every proposal except `TRACK_ANOMALY` is
queued as `NEEDS_HUMAN_APPROVAL`, and the queue is read from the audit log;
the loop itself never applies a queued proposal. The current calibration
state and recent adaptation events are exposed read-only at
`GET /v1/admin/quality-loop/calibration`
([`src/adcs/api/admin_quality_loop.py`](../src/adcs/api/admin_quality_loop.py)).

Fusion-weight adjustments can be auto-approved by setting
`permit_auto_fusion_weight_adjust=True` in `GuardAgentConfig`, subject to the
confidence and blast-radius conditions above. Snapshot rollbacks, incidents
and prompt-variant switches always stay human-only.

## Outputs

All outputs are generated at runtime by `scripts/quality_loop/run_cycle.py`;
the paths below are its defaults (override with `--audit-log`,
`--summary-path`, `--cycle-detail-dir`, and `--calibration-state`).

| Path | Contents | Cadence |
|------|----------|---------|
| `reports/quality-loop/audit-log.jsonl` | Append-only audit log | every cycle |
| `reports/quality-loop/calibration-state.json` | Calibration state read and rewritten by the adaptive step | every cycle (unless run with `--no-adaptive`) |
| `reports/quality-loop/last-summary.json` | Last cycle summary | every cycle |
| `reports/quality-loop/cycles/<cycle-id>/detail.json` | Per-cycle detail (worth keeping as a CI artifact) | every cycle |

The JSONL log is the primary audit surface. Every agent
message has a stable `message_type` tag so an external tool can replay any
cycle: `CorrelationReport`, `QueryResponseSample`, `QualityVerdict`,
`JudgeAgreementReport`, `DiagnosisReport`, `RemediationProposal`,
`GuardDecision`, `AdaptationEvent`, `CycleSummary`.

## Running locally

```bash
# Single cycle with synthetic samples (CI-runnable, no infra)
make quality-loop-cycle

# Quiet variant for CI
make quality-loop-cycle-quiet

# Direct invocation with overrides
PYTHONPATH=./src python3 scripts/quality_loop/run_cycle.py \
    --audit-log /tmp/audit.jsonl \
    --summary-path /tmp/summary.json \
    --cycle-detail-dir /tmp/cycles
```

The synthetic sample provider is deliberately diverse: clean responses,
missing-citation responses, version-mismatch responses, overconfident
responses, and a scope-clustered low-score batch — so every agent path is
exercised on every cycle.

## CI integration

Run the cycle as a **scheduled** CI job (for example hourly) that can also be
triggered on demand, and keep its outputs as build artifacts. The loop is
read-only and is not a gate: its findings never fail a build.

The loop is intentionally **not** run on every pull request — it consumes
recent traffic samples; running it on a hot pipeline would produce noise. The
scheduled + on-demand pattern matches the chaos drill suite's design
([`infra/chaos/README.md`](../infra/chaos/README.md)).

## How the loop integrates with existing systems

The loop is **deliberately independent** of production traffic — it does not
intercept `query_docs` requests or sit in any hot path. It reads samples
from a configurable provider. Two providers ship today:

* **synthetic** (default) — the deterministic CI-smoke fixture set.
* **structured-log** —
  [`StructuredLogSampleProvider`](../src/adcs/quality_loop/sample_providers/structured_log_provider.py)
  tails a JSONL log of already-recorded `query_docs` responses named by
  `$QUALITY_LOOP_LOG_TAIL_PATH`, maps the most recent N records into
  samples, and is selected via `run_cycle.py --samples-source
  structured-log` (falling back to synthetic when the env var is unset).

Both read an already-written source **after the fact** — the loop never
intercepts a live request, so a failure here can never affect serving.

| Existing system | Touch point | Risk if loop breaks |
|-----------------|-------------|---------------------|
| `src/adcs/api/main.py` (query_docs) | None | **Zero.** Loop reads samples after the fact. |
| `src/adcs/quality_gates/golden_eval.py` | None — they coexist | Zero. Different cadence, different surface. |
| `src/adcs/indexing/snapshot_registry.py` | Read-only via rollback proposal action | **Zero in safe mode.** Rollback always needs human approval. |
| `src/adcs/retrieval/hybrid_retriever.py` | Read-only via fusion-weight adjust proposal | **Zero in safe mode.** Adjust always needs human approval. |
| `src/adcs/api/admin_quality_loop.py` | Read-only view of calibration state and adaptation events | Zero. The endpoint never mutates loop state. |

## Anti-patterns to avoid

- **Don't** add an action that mutates production data without first
  encoding the policy in `GuardAgentConfig` AND adding a unit test that
  verifies the new action's gating behaviour. The default-deny test
  pattern in `tests/quality_loop/test_guard_agent.py` is the template.
- **Don't** make the deterministic Judge or any downstream agent
  (Diagnose / Propose / Guard / Adapt) call out to an LLM. The loop's
  value depends on every cycle being deterministically replayable from
  the audit log; an LLM call inside the verdict-producing path would
  break that. The shadow LLMJudgeAgent is the *only* sanctioned LLM
  call in the cycle, and even it never alters the verdict batch the
  diagnoser sees — its agreement report is observational only.
- **Don't** carry state across cycles inside the agents. Trend analysis
  belongs in a separate downstream consumer of the JSONL log, not in the
  agents themselves.
- **Don't** suppress emissions. Every cycle should emit at least a
  `CycleSummary`, even if there are no samples — silent cycles look
  identical to broken cycles in the audit log.

## Shadow LLM judge (self-reflection)

Alongside the deterministic Judge, the `LLMJudgeAgent` runs as a
*shadow* over a subset of samples per cycle (default 20% sampling rate,
hard cap of 10 samples/cycle to control cost). It calls an injected
`LLMJudgeClient` and compares the LLM's scores against the
deterministic verdict. `LLMJudgeClient` is a protocol: production wires it
to an OpenAI-compatible LLM gateway, and tests inject a deterministic stub.

The Coordinator runs the shadow judge automatically when an
`LLMJudgeAgent` is injected (constructor kwarg ``llm_judge=``). When
none is wired, the cycle skips the step silently and runs the six
always-on agents — so the shadow is opt-in per deployment without
breaking any existing caller. The agreement report is published to the
audit log under topic ``judge_agreement`` and counted in
`CycleSummary.llm_judge_reports_emitted`.

The output is one `JudgeAgreementReport` per cycle containing
`agreement_rate`, `mean_absolute_delta`, and a bounded list of
`JudgeDisagreement` records. The shadow does **not** alter cycle
verdicts — the deterministic Judge stays authoritative. Sustained
disagreement above the configured `disagreement_tolerance` (default
0.15) is the signal that the rubric needs human review.

In effect, the loop is no longer just judging samples; it is also judging
its own judgment. See
[`src/adcs/quality_loop/llm_judge_agent.py`](../src/adcs/quality_loop/llm_judge_agent.py).

## Audit-log replay (explainability)

Every typed message a cycle produces is persisted to the JSONL audit
log under topic + cycle_id. The
[`adcs.quality_loop.audit_replay`](../src/adcs/quality_loop/audit_replay.py)
module reconstructs any past cycle from that log alone:

```python
from adcs.quality_loop import replay_cycle, list_cycle_ids

cycles = list_cycle_ids(audit_log_path="reports/quality-loop/audit-log.jsonl")
view = replay_cycle(audit_log_path="reports/quality-loop/audit-log.jsonl",
                    cycle_id=cycles[-1])
# view.samples / view.verdicts / view.diagnoses / view.proposals /
# view.decisions / view.adaptations / view.correlation_reports /
# view.judge_agreement_reports / view.summary
```

No hidden in-memory state. The replay accepts both topic-tagged
entries (the current InMemoryMessageBus format) and the legacy
`message_type`-tagged entries so older audit logs remain inspectable.
Unknown topics are kept in `raw_entry_count` so a future agent that
publishes to a new topic does not break older readers — the replay
is forwards-compatible.

## Related

- [`docs/orchestration-boundaries.md`](orchestration-boundaries.md) — state machines, control flow protocol, extension points (formal contract)
- [`src/adcs/quality_gates/`](../src/adcs/quality_gates/) — release-time
  quality gates that the loop complements
- [`scripts/quality_loop/run_cycle.py`](../scripts/quality_loop/run_cycle.py) — CLI entry point; writes the audit log, summary, and calibration state under `reports/quality-loop/` by default
- [`tests/quality_loop/`](../tests/quality_loop/) — per-agent + integration tests
- [`infra/chaos/README.md`](../infra/chaos/README.md) — sister CI pattern (scheduled + on-demand + append-only log)
