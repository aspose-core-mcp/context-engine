"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { useCriticalEvents } from "@/hooks/useCriticalEvents";
import type { CriticalEvent } from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import {
  EmptyState,
  ErrorState,
  PermissionDenied,
  ReadonlyBanner,
  Skeleton,
  StaleBadge,
} from "../components/states";
import { ShowMoreRow, Table, TableCard } from "../components/Table";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, SectionKey, StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { usePopover } from "../shell/Popover";
import { useToast } from "../shell/overlays";

// ───────────────────────────────────────────────────────────────── Fixtures ──

type Severity = "crit" | "high" | "warning";

interface EscalationEvent {
  at: string;
  by: string;
  reason: string;
}

interface Incident {
  id: string;
  msg: string;
  type: string;
  sev: Severity;
  /** Auto-computed severity before any operator override (computed vs effective). */
  sevComputed: Severity;
  created: string;
  status: string;
  statusP: StatusVariant;
  owner: string;
  sla: string;
  /** Absolute ISO SLA deadline (surfaced alongside the countdown, not replaced by it). */
  slaDeadline: string;
  over: boolean;
  /** 0–100 SLA budget consumed; drives the red/yellow/green progress bar. */
  slaPct: number;
  products: string;
  next: string;
  pm: boolean;
  /** Postmortem lifecycle: pending_resolution / ready / complete. */
  pmStatus: string;
  /** Latest lifecycle action surfaced on the row to avoid duplicate-action work. */
  latestAction: string;
  latestActionAt: string;
  latestActor: string;
  actionCount: number;
  /** Escalation history (escalation-history drill-down). */
  escalations: EscalationEvent[];
}

const INC: Incident[] = [
  {
    id: "evt-10472",
    msg: "publish_blocked for aspose.cells.apiref",
    type: "publish_blocked",
    sev: "crit",
    sevComputed: "crit",
    created: "today 10:30",
    status: "open",
    statusP: "crit",
    owner: "unassigned",
    sla: "8m",
    slaDeadline: "2026-06-05T10:45:00Z",
    over: true,
    slaPct: 100,
    products: "aspose.cells",
    next: "Acknowledge, assign an owner, and escalate — SLA breached.",
    pm: true,
    pmStatus: "pending_resolution",
    latestAction: "severity-override",
    latestActionAt: "today 10:31",
    latestActor: "su@local",
    actionCount: 2,
    escalations: [
      {
        at: "today 10:31",
        by: "auto-policy",
        reason: "sla_deadline_breached — SLA target exceeded before acknowledgement.",
      },
    ],
  },
  {
    id: "evt-10468",
    msg: "ingestion_failure for aspose.barcode.apiref",
    type: "ingestion_failure",
    sev: "high",
    sevComputed: "high",
    created: "today 09:12",
    status: "acknowledged",
    statusP: "info",
    owner: "su@local",
    sla: "22m",
    slaDeadline: "2026-06-05T09:50:00Z",
    over: false,
    slaPct: 64,
    products: "aspose.barcode",
    next: "Investigate parser failures, then resolve with a summary.",
    pm: false,
    pmStatus: "not_required",
    latestAction: "acknowledge",
    latestActionAt: "today 09:14",
    latestActor: "su@local",
    actionCount: 1,
    escalations: [],
  },
  {
    id: "evt-10455",
    msg: "stale_index freshness lag for aspose.ocr",
    type: "pipeline_disruption",
    sev: "warning",
    sevComputed: "warning",
    created: "today 08:40",
    status: "snoozed",
    statusP: "warn",
    owner: "su@local",
    sla: "1h 40m",
    slaDeadline: "2026-06-05T10:20:00Z",
    over: false,
    slaPct: 28,
    products: "aspose.ocr",
    next: "Revisit after the reingest completes.",
    pm: false,
    pmStatus: "not_required",
    latestAction: "snooze",
    latestActionAt: "today 08:45",
    latestActor: "su@local",
    actionCount: 1,
    escalations: [],
  },
  // Extra fixtures so "Show more" pagination is exercised offline (default visible = 10
  // would never paginate with only 3 rows, so "Show more"/"Show less" stay reachable).
  {
    id: "evt-10441",
    msg: "partial_publish below coverage floor for aspose.words.apiref",
    type: "publish_blocked",
    sev: "high",
    sevComputed: "high",
    created: "today 07:55",
    status: "escalated",
    statusP: "crit",
    owner: "product-owner",
    sla: "4m",
    slaDeadline: "2026-06-05T08:10:00Z",
    over: true,
    slaPct: 100,
    products: "aspose.words",
    next: "Escalated — senior operators notified; resolve when the reingest completes.",
    pm: true,
    pmStatus: "pending_resolution",
    latestAction: "escalate",
    latestActionAt: "today 07:58",
    latestActor: "product-owner",
    actionCount: 3,
    escalations: [
      {
        at: "today 07:58",
        by: "product-owner",
        reason: "owner_unassigned — needed cross-team attention before SLA breach.",
      },
      {
        at: "today 08:02",
        by: "su@local",
        reason: "Coverage floor regression also affects downstream MCP parity checks.",
      },
    ],
  },
  {
    id: "evt-10433",
    msg: "ingestion_critical_fail for aspose.pdf.apiref",
    type: "ingestion_failure",
    sev: "crit",
    sevComputed: "crit",
    created: "yesterday 23:10",
    status: "resolved",
    statusP: "ok",
    owner: "su@local",
    sla: "0m",
    slaDeadline: "2026-06-04T23:40:00Z",
    over: false,
    slaPct: 100,
    products: "aspose.pdf",
    next: "Resolved — postmortem template is ready to complete.",
    pm: true,
    pmStatus: "ready",
    latestAction: "resolve",
    latestActionAt: "yesterday 23:38",
    latestActor: "su@local",
    actionCount: 4,
    escalations: [
      {
        at: "yesterday 23:20",
        by: "su@local",
        reason: "sla_deadline_breached — parser crash blocked the nightly publish.",
      },
    ],
  },
];

const sevP: Record<Severity, StatusVariant> = { crit: "crit", high: "warn", warning: "neutral" };

// API limitation: the events endpoint exposes no owner directory, so Assign autocomplete is
// driven from this in-file roster of known operators/teams.
const OWNERS = ["su@local", "product-owner", "oncall-data", "oncall-platform", "ingestion-team"];

// Postmortem status → pill variant + human label (pending_resolution / ready / complete).
const PM_STATUS: Record<string, { variant: StatusVariant; label: string }> = {
  ready: { variant: "ok", label: "ready" },
  complete: { variant: "ok", label: "complete" },
  pending_resolution: { variant: "warn", label: "pending resolution" },
  not_required: { variant: "neutral", label: "not required" },
};

// Per-incident outbound root-cause drill-outs (Logs & Traces / Snapshots /
// Ingestion Jobs). Each opens the sibling section so the operator can chase the cause.
const DRILLS: { key: SectionKey; icon: IconName; label: string }[] = [
  { key: "logs", icon: "list", label: "Logs & Traces" },
  { key: "snapshots", icon: "layers", label: "Snapshots" },
  { key: "ingestion", icon: "upload", label: "Ingestion Jobs" },
];

type AuditRow = [action: string, event: string, who: string, req: string, when: string];

const LOG: AuditRow[] = [
  ["severity-override", "evt-10472", "su@local", "—", "10:31"],
  ["acknowledge", "evt-10468", "su@local", "req_4a1f9b2", "09:14"],
  ["snooze", "evt-10455", "su@local", "—", "08:45"],
  ["escalate", "evt-10441", "product-owner", "req_71be0aa", "07:58"],
  ["escalate", "evt-10441", "su@local", "—", "08:02"],
  ["resolve", "evt-10402", "su@local", "req_2c77d10", "yesterday"],
];

function postmortem(i: Incident): string {
  return `# Incident ${i.id}
## Summary
publish_blocked for ${i.products} (apiref)
## Impact
MCP retrieval for ${i.products} apiref unavailable since ${i.created}.
## Detection
Publish-safety gate blocked the run; alert raised on SLA breach.
## Recovery
- [ ] Fix parser failures on the source repo
- [ ] Re-run Validate-Only, confirm chunk coverage ≥ 90%
- [ ] Publish snapshot and verify readiness
## Follow-ups
- [ ] Add a regression test for the frontmatter parser`;
}

// ───────────────────────────────────────── Live event → fixture-shape adapter ──
// Maps an API `CriticalEvent` onto the fixture `Incident` shape so the existing
// card render/copy stays byte-identical while the data goes live. Action handlers
// are routed to the hook's mutation separately (see `mutateAction` plumbing below).

const SEV_OF: Record<string, Severity> = { critical: "crit", high: "high", warning: "warning" };

function statusPill(status: string): StatusVariant {
  if (status === "open" || status === "escalated") return "crit";
  if (status === "acknowledged") return "info";
  if (status === "snoozed" || status === "muted") return status === "muted" ? "neutral" : "warn";
  if (status === "resolved") return "ok";
  return "neutral";
}

function humanMinutes(min: number): string {
  if (min <= 0) return "0m";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

// SLA budget consumed (0–100) from target vs remaining; drives the triage progress bar.
function slaPercent(sla: CriticalEvent["sla"]): number {
  if (sla.overdue) return 100;
  if (sla.target_minutes <= 0) return 0;
  const consumed = sla.target_minutes - Math.max(0, sla.remaining_minutes);
  return Math.max(0, Math.min(100, Math.round((consumed / sla.target_minutes) * 100)));
}

// Normalise the API's snake_case action verbs onto the audit-trail labels used in copy.
function actionLabel(a: string | null): string {
  if (!a) return "—";
  return a.replace("assign_owner", "assign").replace("severity_override", "severity-override").replace("_", "-");
}

function toIncident(e: CriticalEvent): Incident {
  const status = e.lifecycle.status;
  const sevC = SEV_OF[e.severity] ?? "warning";
  const escReason = e.lifecycle.escalation_reason;
  return {
    id: e.event_id,
    msg: e.message,
    type: e.event_type,
    sev: SEV_OF[e.lifecycle.effective_severity] ?? "warning",
    sevComputed: sevC,
    created: e.created_at,
    status,
    statusP: statusPill(status),
    owner: e.lifecycle.owner ?? "unassigned",
    sla: humanMinutes(Math.abs(e.sla.remaining_minutes)),
    slaDeadline: e.sla.deadline_at,
    over: e.sla.overdue,
    slaPct: slaPercent(e.sla),
    products: e.product_ids.join(", "),
    next: e.lifecycle.next_action_hint,
    pm: e.postmortem.required,
    pmStatus: e.postmortem.status,
    latestAction: actionLabel(e.lifecycle.latest_action),
    latestActionAt: e.lifecycle.latest_action_at ?? "—",
    latestActor: e.lifecycle.owner ?? (e.lifecycle.latest_action ? "system" : "—"),
    actionCount: e.lifecycle.action_count,
    escalations:
      e.lifecycle.escalation_recommended || escReason
        ? [
            {
              at: e.lifecycle.latest_action_at ?? e.created_at,
              by: e.lifecycle.owner ?? "auto-policy",
              reason: escReason ?? "escalation_recommended — SLA / ownership signal raised.",
            },
          ]
        : [],
  };
}

// Live action handler injected into IncidentCard. Online it must settle against the
// backend (success toast only in onSuccess; failures surface via the hook's onError
// toast); offline the cards apply the change locally so fixtures stay interactive.
type ActionVerb =
  | "acknowledge"
  | "mute"
  | "snooze"
  | "assign"
  | "severity-override"
  | "escalate"
  | "resolve";

type MutateAction = (
  eventId: string,
  action: ActionVerb,
  payload: Record<string, unknown>,
  /** Invoked only when the request settles successfully (drives success toasts). */
  onSuccess?: () => void,
) => void;

// Mute/Snooze duration validation (editable Minutes field, default 60,
// validated 1–43200 = 30 days max).
function validateDurationMinutes(v: string): string | null {
  const n = Number(v);
  if (!Number.isInteger(n) || n < 1 || n > 43_200) {
    return "Invalid duration. Allowed range: 1 to 43200 minutes (30 days max).";
  }
  return null;
}

// Severity-override targets ('critical | high | warning', default 'high').
const SEVERITY_OPTIONS = ["critical", "high", "warning"];

interface IncidentState {
  status: string;
  statusP: StatusVariant;
  next: string;
}

// ─────────────────────────────────────────── Inline SLA progress bar (tokens) ──
// Built from Mono tokens only (ok/warn/crit + surfaces); text label always present so
// colour is never the sole urgency indicator.

function SlaBar({ pct, over }: { pct: number; over: boolean }) {
  const tone: StatusVariant = over || pct >= 100 ? "crit" : pct >= 80 ? "warn" : "ok";
  const color =
    tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : "var(--ok)";
  return (
    <div
      className="sla-meter"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.min(100, pct)}
      aria-label={`SLA budget consumed ${Math.min(100, pct)}%${over ? " — overdue" : ""}`}
      title={over ? "SLA overdue" : `${Math.min(100, pct)}% of SLA budget consumed`}
      style={{
        height: 4,
        width: 96,
        borderRadius: "var(--radius-sm)",
        background: "var(--surface-3)",
        overflow: "hidden",
      }}
    >
      <span
        style={{
          display: "block",
          height: "100%",
          width: `${Math.min(100, pct)}%`,
          background: color,
        }}
      />
    </div>
  );
}

// ───────────────────────────────────────── Reason / value capture modal (kit) ──
// Reuses ConfirmModal's exact classes (`.modal-overlay`/`.modal`/`.modal-*`) with a
// <textarea>/<input> + focus-trap + Esc-to-close, so it matches the system. Enforces
// the minimum length before the mutation fires (safety & confirmation).

interface PromptConfig {
  title: string;
  icon: IconName;
  label: string;
  summary: ReactNode;
  body: string;
  defaultValue: string;
  confirmLabel: string;
  /** Multi-line reason (escalate/resolve) vs single-line value (owner). */
  multiline?: boolean;
  /** Render the kit <Select> with these options instead of a text input (severity). */
  options?: string[];
  /** Single-line input type; mute/snooze duration uses "number". */
  inputType?: "text" | "number";
  /** Datalist suggestions for the input (owner autocomplete). */
  suggestions?: string[];
  minLen?: number;
  maxLen?: number;
  /** Domain validation (e.g. duration 1–43200) — returns the error to show, or null. */
  validate?: (value: string) => string | null;
  /** Hint shown while the value is valid (defaults to the character count). */
  hint?: string;
  onSubmit: (value: string) => void;
}

function trapFocus(e: KeyboardEvent, container: HTMLElement | null) {
  if (!container || e.key !== "Tab") return;
  const focusable = container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function PromptModal({ config, onClose }: { config: PromptConfig; onClose: () => void }) {
  const [value, setValue] = useState(config.defaultValue);
  const modalRef = useRef<HTMLDivElement>(null);
  const fieldRef = useRef<HTMLTextAreaElement & HTMLInputElement>(null);
  const min = config.minLen ?? 1;
  const max = config.maxLen ?? 240;
  const trimmed = value.trim();
  const tooShort = trimmed.length < min;
  const tooLong = trimmed.length > max;
  const invalidMsg = !tooShort && !tooLong ? (config.validate?.(trimmed) ?? null) : null;
  const ok = !tooShort && !tooLong && !invalidMsg;
  const listId = `${config.title.replace(/\s+/g, "-").toLowerCase()}-suggest`;

  useEffect(() => {
    fieldRef.current?.focus();
    fieldRef.current?.select?.();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      else if (e.key === "Tab") trapFocus(e, modalRef.current);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function submit() {
    if (!ok) return;
    config.onSubmit(trimmed);
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="cp-title" ref={modalRef}>
        <div className="modal-head">
          <div className="mi" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
            <Icon name={config.icon} />
          </div>
          <div className="modal-title" id="cp-title">
            {config.title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div>{config.body}</div>
          <div className="sum">{config.summary}</div>
          <div className="modal-field">
            <label htmlFor="cp-field" id="cp-field-label">
              {config.label}
            </label>
            {config.options ? (
              // Kit Select (`.selectctl`) for closed value sets — severity override.
              <Select
                id="cp-field"
                options={config.options}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-labelledby="cp-field-label"
                aria-describedby="cp-field-hint"
                autoFocus
              />
            ) : config.multiline ? (
              <textarea
                id="cp-field"
                ref={fieldRef}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                aria-labelledby="cp-field-label"
                aria-describedby="cp-field-hint"
                rows={3}
                maxLength={max}
                spellCheck={false}
                style={{
                  width: "100%",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--surface)",
                  padding: "8px 12px",
                  fontFamily: "var(--font-mono)",
                  fontSize: 13,
                  color: "var(--fg)",
                  outline: "none",
                  resize: "vertical",
                }}
              />
            ) : (
              <>
                <input
                  id="cp-field"
                  ref={fieldRef}
                  type={config.inputType ?? "text"}
                  inputMode={config.inputType === "number" ? "numeric" : undefined}
                  list={config.suggestions ? listId : undefined}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  // Single-line inputs submit on Enter (within prompt dialogs, pressing
                  // Enter submits the form). Textareas keep Enter for newlines.
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      submit();
                    }
                  }}
                  aria-labelledby="cp-field-label"
                  aria-describedby="cp-field-hint"
                  maxLength={max}
                  autoComplete="off"
                  spellCheck={false}
                />
                {config.suggestions && (
                  <datalist id={listId}>
                    {config.suggestions.map((s) => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                )}
              </>
            )}
            <div className="confirm-hint" id="cp-field-hint">
              {tooShort
                ? `Required · at least ${min} characters.`
                : tooLong
                  ? `Too long · ${max} characters max.`
                  : (invalidMsg ?? config.hint ?? `${trimmed.length}/${max} characters.`)}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-amber" disabled={!ok} onClick={submit}>
            {config.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────── Incident card ──

function IncidentCard({
  inc,
  pmMarkdown,
  canMutate = true,
  actionsBusy = false,
  disabledReason,
  online = false,
  mutateAction,
  openPrompt,
  navigate,
}: {
  inc: Incident;
  /** Live postmortem markdown when present; falls back to the fixture scaffold. */
  pmMarkdown?: string | null;
  canMutate?: boolean;
  /** A lifecycle mutation is in flight → disable every action to prevent a double-fire. */
  actionsBusy?: boolean;
  disabledReason?: string | null;
  /** Session established → actions must settle against the backend before toasting. */
  online?: boolean;
  /** Direct (payload-carrying) mutation for all lifecycle actions. */
  mutateAction?: MutateAction;
  openPrompt: (config: PromptConfig) => void;
  navigate: (key: SectionKey) => void;
}) {
  const { toast } = useToast();
  const [st, setSt] = useState<IncidentState>({
    status: inc.status,
    statusP: inc.statusP,
    next: inc.next,
  });
  const [pmOpen, setPmOpen] = useState(false);
  const [escOpen, setEscOpen] = useState(false);

  const update = (status: string, statusP: StatusVariant, next: string) =>
    setSt({ status, statusP, next });
  // ONLINE: fire the mutation; the local state + success toast apply ONLY when the
  // request settles successfully (failures surface via the hook's onError toast).
  // OFFLINE: no backend — apply locally so the fixture queue stays fully interactive.
  const act = (
    action: ActionVerb,
    payload: Record<string, unknown>,
    successMsg: string,
    apply: () => void,
  ) => {
    if (online && mutateAction) {
      mutateAction(inc.id, action, payload, () => {
        apply();
        toast(successMsg);
      });
    } else {
      apply();
      toast(successMsg);
    }
  };
  // Lifecycle actions are gated by scope AND by an in-flight mutation (disabled when:
  // missing write:ingestion scope OR eventActionMutation.isPending). The hook resolves
  // `disabledReason` to the scope message or the "another action is in progress" message.
  const actionDisabled = !canMutate || actionsBusy;
  const hint = !canMutate
    ? (disabledReason ?? "Requires write:ingestion scope.")
    : actionsBusy
      ? (disabledReason ?? "Another critical-event action is in progress.")
      : undefined;
  const pmInfo = PM_STATUS[inc.pmStatus] ?? PM_STATUS.not_required;
  const overridden = inc.sev !== inc.sevComputed;

  return (
    <div className="inc" data-eid={inc.id} aria-label={`Event ${inc.id}`}>
      <div className="inc-main">
        <Pill variant={sevP[inc.sev]}>{inc.sev}</Pill>
        <div className="inc-body">
          <div className="inc-msg">{inc.msg}</div>
          <div className="inc-meta mono">
            {inc.id} · {inc.type} · {inc.products} · created {inc.created}
          </div>
          {overridden && (
            <div className="inc-meta mono" style={{ color: "var(--warn)" }}>
              severity overridden · computed {inc.sevComputed} → effective {inc.sev}
            </div>
          )}
          <div className="inc-next">
            <Icon name="info" className="ico" />
            <span>{st.next}</span>
          </div>
          {/* Latest action — surfaced so an operator does not duplicate in-flight work. */}
          <div className="inc-meta mono">
            latest <b style={{ color: "var(--fg)" }}>{inc.latestAction}</b> · {inc.latestActionAt} ·
            by {inc.latestActor} · {inc.actionCount} action{inc.actionCount === 1 ? "" : "s"}
          </div>
        </div>
        <div className="inc-side">
          <span className={cn("sla", inc.over && "over")}>
            {inc.over ? `SLA ${inc.sla} overdue` : `${inc.sla} to SLA`}
          </span>
          <SlaBar pct={inc.slaPct} over={inc.over} />
          {/* Absolute SLA deadline — the ISO deadline, not only the countdown. */}
          <span className="inc-owner">deadline {inc.slaDeadline}</span>
          <span>
            <Pill variant={st.statusP}>{st.status}</Pill>
          </span>
          <span className="inc-owner">{inc.owner}</span>
          {inc.pm && (
            <span title={`Postmortem ${pmInfo.label}`}>
              <Pill variant={pmInfo.variant}>pm: {pmInfo.label}</Pill>
            </span>
          )}
        </div>
      </div>

      <div className="inc-actions">
        <Button
          variant="btn-ghost"
          size="sm"
          icon="check"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            act("acknowledge", {}, `${inc.id} acknowledged`, () =>
              update("acknowledged", "info", "Investigate the root cause, then resolve with a summary."),
            )
          }
        >
          Acknowledge
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Mute notifications",
              icon: "bell",
              label: "Minutes (max 43200 = 30 days)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  duration in minutes · suppresses notifications while the team remediates
                </>
              ),
              body: "Notifications for this incident are suppressed for the chosen duration (1–43200 min). The incident is marked muted but the SLA timer keeps running.",
              defaultValue: "60",
              confirmLabel: "Mute",
              inputType: "number",
              validate: validateDurationMinutes,
              hint: "1–43200 minutes · 30 days max.",
              onSubmit: (raw) => {
                const minutes = Number(raw);
                act("mute", { duration_minutes: minutes }, `${inc.id} muted for ${minutes} min`, () =>
                  update("muted", "neutral", "Muted — revisit when the remediation lands."),
                );
              },
            })
          }
        >
          Mute
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          icon="clock"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Snooze incident",
              icon: "clock",
              label: "Minutes (max 43200 = 30 days)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  duration in minutes · SLA timer pauses until it returns
                </>
              ),
              body: "Defers the incident for the chosen duration (1–43200 min). The SLA timer pauses and the incident re-surfaces when the snooze elapses.",
              defaultValue: "60",
              confirmLabel: "Snooze",
              inputType: "number",
              validate: validateDurationMinutes,
              hint: "1–43200 minutes · 30 days max.",
              onSubmit: (raw) => {
                const minutes = Number(raw);
                act("snooze", { duration_minutes: minutes }, `${inc.id} snoozed for ${minutes} min`, () =>
                  update("snoozed", "warn", "Revisit after the snooze elapses."),
                );
              },
            })
          }
        >
          Snooze
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Assign owner",
              icon: "key",
              label: "Owner (operator or team · 1–120 chars)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  pick a known operator/team or type a new one · clears the escalation
                  recommendation when previously unassigned
                </>
              ),
              body: "Sets the incident owner. The owner is accountable for mitigation and appears in the audit trail.",
              defaultValue: inc.owner === "unassigned" ? "su@local" : inc.owner,
              confirmLabel: "Assign owner",
              suggestions: OWNERS,
              minLen: 1,
              maxLen: 120,
              onSubmit: (owner) =>
                act("assign", { owner }, `${inc.id} assigned to ${owner}`, () =>
                  update("acknowledged", "info", `Owner ${owner} assigned — investigate and resolve.`),
                ),
            })
          }
        >
          Assign
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Override severity",
              icon: "sliders",
              label: "Severity (critical | high | warning)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  computed <b>{inc.sevComputed}</b> · override recalculates SLA deadline and
                  escalation logic server-side
                </>
              ),
              body: "Manually overrides the auto-computed severity (CRITICAL / HIGH / WARNING). Use this when business impact differs from the computed value.",
              defaultValue: "high",
              confirmLabel: "Apply severity",
              options: SEVERITY_OPTIONS,
              validate: (v) => (SEVERITY_OPTIONS.includes(v) ? null : "Invalid severity value."),
              hint: "One of critical / high / warning.",
              onSubmit: (severity) =>
                act("severity-override", { severity }, `${inc.id} severity updated`, () =>
                  update(st.status, st.statusP, "Severity overridden — re-check the SLA target."),
                ),
            })
          }
        >
          Severity
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          icon="arrow"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Escalate incident",
              icon: "arrow",
              label: "Escalation reason (required · for the audit trail)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  notifies senior operators · the reason is recorded in the escalation chain
                </>
              ),
              body: "Sets status to escalated and increments escalation urgency. A reason (3–240 chars) is required for the audit trail.",
              defaultValue: inc.over ? "SLA deadline breached — needs senior attention." : "Requires senior or cross-team attention.",
              confirmLabel: "Escalate",
              multiline: true,
              minLen: 3,
              maxLen: 240,
              onSubmit: (reason) =>
                act("escalate", { reason }, `${inc.id} escalated`, () =>
                  update("escalated", "crit", "Escalated — senior operators notified; resolve when fixed."),
                ),
            })
          }
        >
          Escalate
        </Button>
        <div className="spacer" style={{ flex: 1 }} />
        {inc.escalations.length > 0 && (
          <Button
            variant="btn-ghost"
            size="sm"
            icon="history"
            aria-expanded={escOpen}
            onClick={() => setEscOpen((o) => !o)}
          >
            Escalation history
          </Button>
        )}
        {inc.pm && (
          <Button variant="btn-ghost" size="sm" aria-expanded={pmOpen} onClick={() => setPmOpen((o) => !o)}>
            Postmortem scaffold
          </Button>
        )}
        <Button
          variant="btn-primary"
          size="sm"
          icon="check"
          disabled={actionDisabled}
          title={hint}
          onClick={() =>
            openPrompt({
              title: "Resolve incident",
              icon: "check",
              label: "Resolution summary (required · for the audit trail)",
              summary: (
                <>
                  event <b>{inc.id}</b>
                  <br />
                  halts the SLA timer and archives the incident
                  {inc.pm ? " · postmortem status becomes ready" : ""}
                </>
              ),
              body: inc.pm
                ? "Sets status to resolved and stops the SLA timer. A resolution summary (3–240 chars) is required. Because a postmortem is required, its status becomes ready."
                : "Sets status to resolved and stops the SLA timer. A resolution summary (3–240 chars) is required.",
              defaultValue: "Incident resolved.",
              confirmLabel: "Resolve",
              multiline: true,
              minLen: 3,
              maxLen: 240,
              onSubmit: (reason) =>
                act(
                  "resolve",
                  { reason },
                  inc.pm ? `${inc.id} resolved · postmortem ready` : `${inc.id} resolved`,
                  () => update("resolved", "ok", "Resolved — postmortem template is ready to complete."),
                ),
            })
          }
        >
          Resolve
        </Button>
      </div>

      {/* Outbound root-cause drill-outs (Logs / Snapshots / Ingestion). */}
      <div className="inc-actions" style={{ marginTop: 6 }}>
        <span className="muted-note">Investigate root cause →</span>
        {DRILLS.map((d) => (
          <Button
            key={d.key}
            variant="btn-ghost"
            size="sm"
            icon={d.icon}
            title={`Open ${d.label} (search by ${inc.id})`}
            onClick={() => {
              toast(`Opening ${d.label} for ${inc.id}`);
              navigate(d.key);
            }}
          >
            {d.label}
          </Button>
        ))}
      </div>

      {escOpen && inc.escalations.length > 0 && (
        <div className="inc-pm">
          <div className="eh">Escalation history</div>
          <ol className="fix-steps">
            {inc.escalations.map((ev, i) => (
              <li key={i}>
                <span>
                  <span className="mono" style={{ color: "var(--fg-subtle)" }}>
                    {ev.at} · {ev.by}
                  </span>
                  <br />
                  {ev.reason}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {inc.pm && pmOpen && (
        <div className="inc-pm">
          <div className="eh">
            Postmortem scaffold · <Tag>{pmInfo.label}</Tag>
          </div>
          <pre className="rv-pre">{pmMarkdown ?? postmortem(inc)}</pre>
        </div>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────── Audit table ──
// Paginated with a "+N more" ShowMoreRow. Long live lists default to 10 visible rows
// lists; offline the audit fixture has 6 rows, so the default is set below that so the
// pagination control is reachable and demonstrably works with no backend.
const AUDIT_DEFAULT = 4;

function AuditTable({ rows = LOG }: { rows?: AuditRow[] }) {
  const head = rows.slice(0, AUDIT_DEFAULT);
  const rest = rows.slice(AUDIT_DEFAULT);
  const renderRow = ([action, event, who, req, when]: AuditRow, key: string) => (
    <tr className="data" key={key}>
      <td>
        <Tag>{action}</Tag>
      </td>
      <td>
        <span className="repo-id">{event}</span>
      </td>
      <td>
        <span className="mono" style={{ fontSize: 11.5, color: "var(--fg-muted)" }}>
          {who}
        </span>
      </td>
      <td>
        <span className="mono" style={{ fontSize: 11.5, color: "var(--fg-subtle)" }}>
          {req}
        </span>
      </td>
      <td className="num">{when}</td>
    </tr>
  );
  return (
    <TableCard>
      <Table>
        <thead>
          <tr>
            <th style={{ width: 160 }}>Action</th>
            <th style={{ width: 130 }}>Event</th>
            <th style={{ width: 140 }}>Actor</th>
            <th>Request</th>
            <th className="num" style={{ width: 110 }}>
              When
            </th>
          </tr>
        </thead>
        <tbody>
          {head.map((r, i) => renderRow(r, `${r[0]}-${r[1]}-${r[4]}-${i}`))}
          {rest.length > 0 && (
            <ShowMoreRow
              count={rest.length}
              colSpan={5}
              extra={rest.map((r, i) => renderRow(r, `more-${r[0]}-${r[1]}-${r[4]}-${i}`))}
            />
          )}
        </tbody>
      </Table>
    </TableCard>
  );
}

// ─────────────────────────────────────────────────────── Shared page header ──

function CriticalHead({
  onRefresh,
  lastFetched,
}: {
  onRefresh?: () => void;
  lastFetched?: string;
}) {
  const help = usePopover();
  return (
    <PageHead
      title="Critical Events"
      sub="Incident command — severity, SLA, ownership, and the acknowledge → escalate → resolve lifecycle."
      onHelp={help.toggle}
      actions={
        <>
          <ScopeChip label="scope" value="write:ingestion" dot />
          {/* "Last fetched" so the operator can judge freshness before trusting the queue. */}
          <span className="muted-note" title="Queue & actions auto-refresh every 60s while this section is open">
            Auto-refresh 60s{lastFetched ? ` · fetched ${lastFetched}` : ""}
          </span>
          <Button variant="btn-primary" size="sm" icon="refresh" onClick={onRefresh}>
            Refresh now
          </Button>
          {/* In-page Why/What/How popover (per-section help affordance, Esc-to-close). */}
          <div ref={help.wrapRef} style={{ position: "relative" }}>
            {help.open && (
              <div className="pop" role="dialog" aria-label="Critical Events help" style={{ right: 0 }}>
                <div className="pop-head">
                  <span className="pt">Critical Events</span>
                  <span className="ps">help</span>
                </div>
                <div className="pop-body">
                  <div className="pop-sub">Why</div>
                  <div className="pop-row">
                    <span className="nm">
                      Single queryable queue for system incidents so the next action is always clear.
                    </span>
                  </div>
                  <div className="pop-sub">What</div>
                  <div className="pop-row">
                    <span className="nm">
                      Severity & SLA-ranked incidents with acknowledge → assign → escalate → resolve.
                    </span>
                  </div>
                  <div className="pop-sub">How</div>
                  <div className="pop-row">
                    <span className="nm">
                      Triage the top SLA-overdue row, assign an owner, escalate with a reason, then
                      resolve with a summary to arm the postmortem.
                    </span>
                  </div>
                </div>
                <div className="pop-foot">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      help.close();
                      window.location.href = "/howto";
                    }}
                  >
                    Open full How-To
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      }
    />
  );
}

// ──────────────────────────────────────────────────────────────── Section ──

// Page size for the LIVE queue is 10 (fetch 50; "Show more" appends 10). Offline the
// incident fixture has 5 rows, so a smaller fixture default keeps Show more / Show less
// reachable and demonstrably working with no backend.
const QUEUE_PAGE = 10;
const QUEUE_DEFAULT = 3;
const STATUS_FILTER = ["All statuses", "open", "acknowledged", "muted", "snoozed", "escalated", "resolved"];

// Cross-section prefill: filter keys this section knows how to honour when another
// section hands off via navigate("critical", anchor, { filters }). Unknown keys are
// ignored gracefully. Both route into the free-text search box, whose predicate scans
// inc.products and inc.sev (the section has no discrete severity/product control).
// Ordered most-selective first so `product` wins when both are supplied.
const PREFILL_KEYS = ["product", "severity"] as const;

export function CriticalSection() {
  const { navigate, consumeIntent } = useShell();
  const data = useAdminData();
  // Mono section key is "critical"; the hook's refetch gate keys off the
  // SidebarSectionId "critical-events" — pass that so the 60s auto-refresh fires.
  const events = useCriticalEvents({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "critical-events",
    canMutateIngestion: data.can("write:ingestion"),
    showAlert: data.showAlert,
    // Every value-collecting action (mute/snooze duration, owner, severity, reasons)
    // is captured by this section's PromptModal and posted via `mutateAction`, so the
    // hook's showPrompt path is never exercised here — keep it inert.
    showPrompt: () => {},
  });

  // Single in-place value-capture modal (mute / snooze / assign / severity /
  // escalate / resolve).
  const [prompt, setPrompt] = useState<PromptConfig | null>(null);
  // Direct payload-carrying mutation for all lifecycle actions. The optional settle
  // callback lets cards apply state + toast success ONLY after the request succeeds;
  // failures surface via the hook's onError toast.
  const mutateAction: MutateAction = (eventId, action, payload, onSuccess) =>
    events.eventActionMutation.mutate({ eventId, action, payload }, { onSuccess });

  const canMutate = data.can("write:ingestion");
  // Live vs fixture: offline (no session → queries disabled) the fixtures ARE the
  // dataset and every control operates on them; online the queue renders LIVE data
  // only, so loading / error / live-empty are real, reachable states — fixtures
  // never mask an online failure or a genuinely healthy-empty system.
  const offline = !data.sessionIsSuccess;
  const live = events.criticalIncidents; // full fetched queue (≤50), no hook-side slice
  const allIncidents: Incident[] = offline ? INC : live.map(toIncident);
  const pmById = new Map(live.map((e) => [e.event_id, e.postmortem.template_markdown]));

  // ── Per-incident search + status filter. Filters the
  //    DISPLAY source so they visibly respond OFFLINE on fixtures (mirror Health). ──
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(STATUS_FILTER[0]);
  const q = search.trim().toLowerCase();
  const incidents = allIncidents.filter((inc) => {
    const matchesQ =
      !q ||
      inc.id.toLowerCase().includes(q) ||
      inc.msg.toLowerCase().includes(q) ||
      inc.type.toLowerCase().includes(q) ||
      inc.products.toLowerCase().includes(q) ||
      inc.owner.toLowerCase().includes(q) ||
      // Severity term match so a severity-scoped cross-section prefill (e.g. "crit")
      // genuinely narrows the queue through the same free-text filter.
      inc.sev.toLowerCase().includes(q);
    const matchesStatus = statusFilter === STATUS_FILTER[0] || inc.status === statusFilter;
    return matchesQ && matchesStatus;
  });

  // ── "Show more" / "Show less" pagination (10 visible initially, +10 per
  //    click over the 50-item fetch; offline the 3-row fixture default keeps the
  //    controls reachable). The override resets when the page size context flips. ──
  const pageSize = offline ? QUEUE_DEFAULT : QUEUE_PAGE;
  const [visibleOverride, setVisibleOverride] = useState<number | null>(null);

  // ── Cross-section prefill handoff. On mount, drain the one-shot SectionIntent for
  //    "critical" and apply its supported filters (severity/product) through THIS
  //    section's existing setters. `reset` clears the queue filters first; unknown
  //    filter keys are ignored. consumeIntent is one-shot, but a ref guard also blocks
  //    any re-run (e.g. StrictMode double-invoke) so a drained intent never re-applies.
  const intentApplied = useRef(false);
  useEffect(() => {
    if (intentApplied.current) return;
    intentApplied.current = true;
    const intent = consumeIntent("critical");
    if (!intent) return;
    if (intent.reset) {
      setSearch("");
      setStatusFilter(STATUS_FILTER[0]);
      setVisibleOverride(null);
    }
    const filters = intent.filters;
    if (filters) {
      // Route a supported filter value into the free-text search (its predicate scans
      // inc.products and inc.sev). Prefer the more selective `product`, else `severity`;
      // a single coherent term always matches real rows (a joined multi-term string
      // would not under the substring predicate). Unknown/blank keys are skipped.
      const term = PREFILL_KEYS.map((k) => filters[k]?.trim()).find((v) => !!v);
      if (term) {
        setSearch(term);
        setVisibleOverride(null);
      }
    }
    // Mount-only: consumeIntent is one-shot and the ref guard makes this idempotent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibleCount = visibleOverride ?? pageSize;
  const shownIncidents = incidents.slice(0, visibleCount);
  const remaining = incidents.length - shownIncidents.length;

  // Live audit trail → AuditRow tuples; fixtures only OFFLINE. Online the audit card
  // renders its own loading / error / empty states below — never fixture rows.
  const liveActions = events.criticalActionsQuery.data ?? [];
  const auditRows: AuditRow[] = offline
    ? LOG
    : liveActions.map((a) => [
        actionLabel(a.action),
        a.event_id,
        a.actor_key_id,
        a.request_id ?? "—",
        a.created_at,
      ]);
  const auditLoading = !offline && events.criticalActionsQuery.isPending && !auditRows.length;
  const auditErrored = events.criticalActionsQuery.isError && !auditRows.length;

  // KPI counts from the DISPLAY source (live online, fixtures offline).
  const openN = allIncidents.filter((i) => i.status === "open").length;
  const ackN = allIncidents.filter((i) => i.status === "acknowledged").length;
  const overdueN = allIncidents.filter((i) => i.over).length;
  // API limitation: events endpoint returns the active queue only, not a 24h-resolved
  // rollup — "Resolved · 24h" stays a fixture until a resolved-history count ships.
  const resolved24 = "3";

  // SLA-breach banner: open critical-severity incidents past their SLA, from the
  // DISPLAY source. Rendered only when such an incident exists — never with fixture
  // copy (or a "0 incidents" title) on a live system.
  const breached = allIncidents.filter(
    (i) => i.sev === "crit" && i.over && i.status !== "resolved",
  );
  const topBreached = breached[0];

  // Queue states: offline → fixtures (non-empty) keep the happy path interactive;
  // online the gates reflect the real query — loading skeleton, error + retry, and
  // the live-empty copy are all reachable because fixtures never substitute.
  const loading = !offline && events.criticalEventsQuery.isPending && !allIncidents.length;
  const errored = events.criticalEventsQuery.isError && !allIncidents.length;
  // Live-empty success OR a filter that excludes every row → empty queue copy.
  const emptyQueue =
    !loading && !errored && !shownIncidents.length;
  const filteredOut = emptyQueue && allIncidents.length > 0;

  return (
    <>
      <CriticalHead
        onRefresh={() => {
          // Header copy promises "Queue & actions" freshness — refresh both.
          void events.criticalEventsQuery.refetch();
          void events.criticalActionsQuery.refetch();
        }}
        lastFetched={events.criticalEventsQuery.isSuccess ? "just now" : undefined}
      />

      <KpiRow cols={4}>
        <Kpi
          label="Open"
          value={String(openN)}
          foot="needs action"
          accent
          pill={{ variant: "crit", text: "sev1" }}
        />
        <Kpi label="Acknowledged" value={String(ackN)} foot="in progress" />
        <Kpi label="SLA overdue" value={String(overdueN)} foot="escalate now" />
        <Kpi label="Resolved · 24h" value={resolved24} foot="postmortems ready" />
      </KpiRow>

      {/* Warn banner for the open sev1 — only when a breached critical
          incident actually exists in the display source; copy derives from that
          incident (fixture evt-10472 offline, the live worst-offender online). */}
      {topBreached && (
        <Banner
          variant="warn"
          icon="alert"
          title={`${breached.length} critical incident${breached.length === 1 ? "" : "s"} open · SLA breached`}
          text={
            <>
              <b>{topBreached.id}</b> {topBreached.type} for {topBreached.products} is{" "}
              {topBreached.owner === "unassigned" ? "unowned" : `owned by ${topBreached.owner}`} and
              past its SLA target. Acknowledge and escalate.
            </>
          }
        />
      )}

      <Card
        title="Incident lifecycle queue"
        sub="Severity & SLA-ranked. Acknowledge → assign → escalate → resolve; every action is audited."
        flush
        right={
          <span className="muted-note">
            Showing {shownIncidents.length} of {incidents.length}
            {incidents.length !== allIncidents.length ? ` (filtered from ${allIncidents.length})` : ""}
          </span>
        }
      >
        {/* Per-incident search + status filter — refine the DISPLAY source, works offline. */}
        <div className="toolbar" style={{ padding: "12px 16px 0", marginBottom: 0 }}>
          <Input
            width={260}
            value={search}
            placeholder="Search id, message, type, product, owner…"
            onChange={(e) => {
              setSearch(e.target.value);
              setVisibleOverride(null);
            }}
            aria-label="Search incidents"
          />
          <Select
            width={170}
            options={STATUS_FILTER}
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setVisibleOverride(null);
            }}
            aria-label="Filter by status"
          />
          {(q || statusFilter !== STATUS_FILTER[0]) && (
            <div className="toolbar-right">
              <Button
                variant="btn-ghost"
                size="sm"
                icon="x"
                onClick={() => {
                  setSearch("");
                  setStatusFilter(STATUS_FILTER[0]);
                  setVisibleOverride(null);
                }}
              >
                Clear filters
              </Button>
            </div>
          )}
        </div>

        {loading ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={3} />
          </div>
        ) : errored ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Failed to load critical events"
              cause="the admin API is unreachable"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => events.criticalEventsQuery.refetch()}
                >
                  Retry
                </Button>
              }
            />
          </div>
        ) : emptyQueue ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title={filteredOut ? "No incidents match these filters" : "No critical events recorded"}
              text={
                filteredOut
                  ? "Adjust or clear the search and status filters to widen the queue."
                  : "This section is active and will populate when ingestion or publish incidents are detected. An empty queue means the platform is healthy."
              }
              action={
                filteredOut ? (
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="x"
                    onClick={() => {
                      setSearch("");
                      setStatusFilter(STATUS_FILTER[0]);
                    }}
                  >
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <>
            <div className="inc-list">
              {shownIncidents.map((inc) => (
                <IncidentCard
                  key={inc.id}
                  inc={inc}
                  pmMarkdown={pmById.get(inc.id)}
                  canMutate={canMutate}
                  actionsBusy={events.eventActionMutation.isPending}
                  disabledReason={events.criticalEventActionDisabledReason}
                  online={!offline}
                  mutateAction={mutateAction}
                  openPrompt={setPrompt}
                  navigate={navigate}
                />
              ))}
            </div>
            {/* Show more / Show less pagination (+pageSize per click). */}
            {(remaining > 0 || visibleCount > pageSize) && (
              <div className="more-wrap" style={{ display: "flex", justifyContent: "center", gap: 8 }}>
                {remaining > 0 && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-label={`Show more incidents — ${remaining} remaining`}
                    onClick={() => setVisibleOverride(visibleCount + pageSize)}
                  >
                    Show more · {remaining} remaining
                  </button>
                )}
                {visibleCount > pageSize && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-label="Show fewer incidents"
                    onClick={() => setVisibleOverride(null)}
                  >
                    Show less
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      <Card
        title="Recent notification actions"
        sub="Who did what, when — accountability & postmortem reconstruction."
        flush
        right={
          auditRows.length > 0 ? (
            <span className="muted-note">
              Showing {Math.min(auditRows.length, AUDIT_DEFAULT)} of {auditRows.length}
            </span>
          ) : undefined
        }
      >
        {/* States for the audit subsection: skeleton (rows=2) while loading,
            failure alert with retry, "no actions yet" caption when live-empty. */}
        {auditLoading ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={2} />
          </div>
        ) : auditErrored ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Failed to load critical event actions"
              cause="the admin API is unreachable"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => events.criticalActionsQuery.refetch()}
                >
                  Retry
                </Button>
              }
            />
          </div>
        ) : auditRows.length === 0 ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No notification actions recorded yet."
              text="Actions will appear here once incidents are created and operators apply lifecycle actions."
            />
          </div>
        ) : (
          <AuditTable rows={auditRows} />
        )}
      </Card>

      {prompt && <PromptModal config={prompt} onClose={() => setPrompt(null)} />}
    </>
  );
}

// ───────────────────────────────────────────────── Module-level edge states ──
// The Section above renders the happy path. These cover the required
// states (loading / empty / error / permission / stale / read-only) and stay
// tree-shakeable without a second file, matching the Snapshots idiom.

export function CriticalLoading() {
  return (
    <>
      <CriticalHead />
      <Card title="Incident lifecycle queue" flush>
        <div style={{ padding: 16 }}>
          <Skeleton rows={3} />
        </div>
      </Card>
      <Card title="Recent notification actions" flush>
        <div style={{ padding: 16 }}>
          <Skeleton rows={2} />
        </div>
      </Card>
    </>
  );
}

export function CriticalEmpty() {
  return (
    <>
      <CriticalHead />
      <Card title="Incident lifecycle queue" flush>
        <div style={{ padding: 16 }}>
          <EmptyState
            title="No critical events recorded"
            text="This section is active and will populate when ingestion or publish incidents are detected. An empty queue means the platform is healthy."
          />
        </div>
      </Card>
    </>
  );
}

export function CriticalError() {
  const { navigate } = useShell();
  return (
    <>
      <CriticalHead />
      <ErrorState
        title="Failed to load critical events"
        text="The incident queue and notification actions could not be fetched. No automatic retry — refresh the page or re-open the section."
        cause="Qdrant connection timeout"
        actions={
          <>
            <Button variant="btn-ghost" size="sm" icon="refresh">
              Retry
            </Button>
            <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
              Open Logs & Traces
            </Button>
          </>
        }
      />
    </>
  );
}

export function CriticalDenied() {
  return (
    <>
      <CriticalHead />
      <PermissionDenied
        scope="write:ingestion"
        extra="Acknowledge, mute, snooze, assign, escalate, and resolve all require an ingestion-scoped key. Read-only viewers can still scan the queue."
      />
    </>
  );
}

export function CriticalStale() {
  return (
    <>
      <PageHead
        title="Critical Events"
        sub="Incident command — severity, SLA, ownership, and the acknowledge → escalate → resolve lifecycle."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            <ScopeChip label="scope" value="write:ingestion" dot />
            <StaleBadge>stale · 60s</StaleBadge>
            <Button variant="btn-primary" size="sm" icon="refresh">
              Refresh now
            </Button>
          </>
        }
      />
      <Banner
        variant="warn"
        icon="alert"
        title="1 critical incident open · SLA breached"
        text={
          <>
            <b>evt-10472</b> publish_blocked for aspose.cells.apiref is unowned and past its SLA target.
            Acknowledge and escalate.
          </>
        }
      />
      <Card title="Incident lifecycle queue" flush>
        <div className="inc-list">
          {INC.slice(0, 3).map((inc) => (
            <IncidentCard
              key={inc.id}
              inc={inc}
              openPrompt={() => {}}
              navigate={() => {}}
            />
          ))}
        </div>
      </Card>
    </>
  );
}

export function CriticalReadonly() {
  return (
    <>
      <ReadonlyBanner />
      <CriticalSection />
    </>
  );
}
