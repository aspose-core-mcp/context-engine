"use client";

import { useEffect, useRef, useState } from "react";

import { useConfigHistory } from "@/hooks/useConfigHistory";
import type { ConfigHistoryEntry } from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Select } from "../components/Field";
import { IconButton } from "../components/IconButton";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ShowMoreRow } from "../components/Table";
import { EmptyState, ErrorState, PermissionDenied, Skeleton, StaleBadge } from "../components/states";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";
import { PopoverPanel, usePopover } from "../shell/Popover";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";

// ─────────────────────────────────────────────────────────── Fixtures ───────

/** One field-level entry in a before/after diff. */
interface DiffField {
  key: string;
  before: string | null;
  after: string | null;
  /** removed = present before, gone after · added = new after · changed = both differ. */
  status: "removed" | "added" | "changed";
}

interface ConfigChange {
  /** Live-timezone timestamp of the change (raw ISO for live rows, friendly for fixtures). */
  when: string;
  /** Config scope / area that changed. */
  area: string;
  /** One-line human summary of the change. */
  change: string;
  /** Actor (admin key / service account). */
  actor: string;
  /** The exact config key field that changed . */
  configKey: string;
  /** Action type: retrieval_settings / language_alias / rollback … */
  actionType: string;
  /** Operator-provided reason recorded with the change. */
  reason: string;
  /** Unique change record id. */
  changeId: string;
  /** HTTP request that triggered the change — traceable in Logs & Traces. */
  requestId: string | null;
  /** Pointer to the persisted change artifact (shown as an 'artifact:' chip when present). */
  artifactPath: string | null;
  /** If this entry is itself a rollback, the original change_id it reverted. */
  rollbackOf: string | null;
  /** Per-key before/after diff, shown inline. */
  diff: DiffField[];
  /** True only for live rows (drives the real rollback mutation). */
  live?: boolean;
}

// Build a fixture diff helper so each fixture row carries a real, labeled per-key diff.
function fx(
  rows: Array<{ key: string; before?: string; after?: string }>,
): DiffField[] {
  return rows.map((r) => {
    const before = r.before ?? null;
    const after = r.after ?? null;
    const status: DiffField["status"] =
      before == null ? "added" : after == null ? "removed" : "changed";
    return { key: r.key, before, after, status };
  });
}

// API limitation: the live ConfigHistoryEntry carries before/after blobs but no friendly
// summary/reason for older rows, and the offline session never reaches the backend,
// so these fixtures are the fully-usable offline dataset (mirrors Health.COMP_DATA).
const CFG_DATA: Record<string, ConfigChange[]> = {
  "aspose.ocr": [
    {
      when: "today 12:18",
      area: "retrieval_settings",
      change: "Results per query 6 → 8",
      actor: "key_su_01HZ",
      configKey: "results_per_query",
      actionType: "update",
      reason: "Coverage tuning: 6 results dropped relevant API symbols on multi-overload queries.",
      changeId: "chg_8f21ac",
      requestId: "req_8c3864e",
      artifactPath: "config/retrieval_settings/aspose.ocr/chg_8f21ac.json",
      rollbackOf: null,
      diff: fx([{ key: "results_per_query", before: "6", after: "8" }]),
    },
    {
      when: "yesterday 09:40",
      area: "abuse_guard",
      change: "Global limit 4000 → 5000 / min",
      actor: "key_su_01HZ",
      configKey: "global_per_min",
      actionType: "update",
      reason: "Raised ceiling ahead of the docs launch traffic spike.",
      changeId: "chg_7b03de",
      requestId: "req_5a1f02b",
      artifactPath: "config/abuse_guard/aspose.ocr/chg_7b03de.json",
      rollbackOf: null,
      diff: fx([
        { key: "global_per_min", before: "4000", after: "5000" },
        { key: "mode", before: "observe", after: "enforce" },
      ]),
    },
    {
      when: "2 days ago",
      area: "retrieval_settings",
      change: "Rollback of low_confidence_threshold change",
      actor: "key_su_01HZ",
      configKey: "low_confidence_threshold",
      actionType: "rollback",
      reason: "Incident mitigation: threshold 0.50 caused a zero-result spike; restored 0.65.",
      changeId: "chg_6c92fa",
      requestId: "req_4d77c19",
      artifactPath: "config/retrieval_settings/aspose.ocr/chg_6c92fa.json",
      rollbackOf: "chg_5a01bb",
      diff: fx([{ key: "low_confidence_threshold", before: "0.50", after: "0.65" }]),
    },
    {
      when: "2 days ago",
      area: "retrieval_settings",
      change: "Low-confidence threshold 0.65 → 0.50",
      actor: "key_op_42KP",
      configKey: "low_confidence_threshold",
      actionType: "update",
      reason: "Experiment: relax gate to surface more borderline matches.",
      changeId: "chg_5a01bb",
      requestId: "req_3b40e88",
      artifactPath: "config/retrieval_settings/aspose.ocr/chg_5a01bb.json",
      rollbackOf: null,
      diff: fx([{ key: "low_confidence_threshold", before: "0.65", after: "0.50" }]),
    },
    {
      when: "3 days ago",
      area: "language_alias",
      change: "Added locale ru",
      actor: "key_su_01HZ",
      configKey: "locales",
      actionType: "update",
      reason: "Onboarding Russian docs locale for OCR.",
      changeId: "chg_4e88aa",
      requestId: "req_2c11d70",
      artifactPath: "config/language_alias/aspose.ocr/chg_4e88aa.json",
      rollbackOf: null,
      diff: fx([
        { key: "locales", before: "[en]", after: "[en, ru]" },
        { key: "ru.aliases", after: "[russian, ru-RU]" },
      ]),
    },
    {
      when: "5 days ago",
      area: "abuse_guard",
      change: "Removed legacy per-key override",
      actor: "key_su_01HZ",
      configKey: "per_key_overrides",
      actionType: "update",
      reason: "Cleanup: stale override for a rotated key.",
      changeId: "chg_3a10cc",
      requestId: "req_1d09b41",
      artifactPath: null,
      rollbackOf: null,
      diff: fx([{ key: "per_key_overrides.legacy", before: "{ per_min: 9000 }" }]),
    },
  ],
  "aspose.cells": [
    {
      when: "today 10:32",
      area: "retrieval_settings",
      change: "Max context tokens 12288 → 16384",
      actor: "key_su_01HZ",
      configKey: "max_context_tokens",
      actionType: "update",
      reason: "Larger context window for multi-symbol spreadsheet queries.",
      changeId: "chg_9d44bf",
      requestId: "req_7f22a03",
      artifactPath: "config/retrieval_settings/aspose.cells/chg_9d44bf.json",
      rollbackOf: null,
      diff: fx([{ key: "max_context_tokens", before: "12288", after: "16384" }]),
    },
  ],
  "aspose.3d": [],
};

const PRODUCTS = ["aspose.ocr", "aspose.cells", "aspose.3d"];

// Human-readable expansions for raw config-scope identifiers: the caption shown under the
// metadata chips so operators can read what a scope governs.
const CONFIG_SCOPE_LABELS: Record<string, string> = {
  retrieval_settings: "Retrieval settings (weights, reranker, confidence thresholds)",
  abuse_guard: "Abuse guard (rate limits, per-key overrides, enforcement mode)",
  language_alias: "Language registry (locales and locale aliases)",
};

/** Friendly caption for a config scope, falling back to the raw identifier. */
function scopeDescription(scope: string): string | null {
  return CONFIG_SCOPE_LABELS[scope] ?? null;
}

/** Mutation scope required to roll a change back. */
const ROLLBACK_SCOPE = "write:settings";

/** A rollback reason is required, minimum 3 characters. */
const REASON_MIN = 3;

/** Default visible rows of the newest-first ledger before the kit ShowMoreRow pager. */
const DEFAULT_VISIBLE = 4;

// ───────────────────────────────────────────────── live-entry projection ────

// Convert a raw ISO timestamp to the operator's local timezone (localized timestamps
// reduce mental arithmetic during incident response).
// Fixtures already use friendly relative strings, so only live ISO strings are converted.
function toLocalTime(raw: string): string {
  const t = Date.parse(raw);
  if (Number.isNaN(t)) return raw;
  const d = new Date(t);
  const date = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return `${date} · ${time}`;
}

function fmtVal(v: unknown): string {
  if (v === undefined) return "—";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

// Compute a per-key add/remove/change diff from two config blobs (feeds the per-key
// diff table with explicit removed/added/changed rows + a textual Status column).
function diffBlobs(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): DiffField[] {
  const keys = Array.from(
    new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]),
  ).sort();
  const out: DiffField[] = [];
  for (const key of keys) {
    const inBefore = before != null && key in before;
    const inAfter = after != null && key in after;
    const bv = inBefore ? fmtVal(before[key]) : null;
    const av = inAfter ? fmtVal(after[key]) : null;
    if (inBefore && inAfter) {
      if (bv === av) continue; // unchanged keys are not surfaced as diff rows
      out.push({ key, before: bv, after: av, status: "changed" });
    } else if (inAfter) {
      out.push({ key, before: null, after: av, status: "added" });
    } else {
      out.push({ key, before: bv, after: null, status: "removed" });
    }
  }
  return out;
}

// Project a live ConfigHistoryEntry onto the section's ConfigChange row shape.
function entryToRow(e: ConfigHistoryEntry): ConfigChange {
  const verb = e.action_type === "rollback" ? "Rolled back" : "Updated";
  return {
    when: toLocalTime(e.created_at),
    area: e.config_scope,
    change: e.reason ?? `${verb} ${e.config_key}`,
    actor: e.actor_key_id,
    configKey: e.config_key,
    actionType: e.action_type,
    reason: e.reason ?? "(no reason recorded)",
    changeId: e.change_id,
    requestId: e.request_id,
    artifactPath: e.artifact_path || null,
    rollbackOf: e.rollback_of_change_id,
    diff: diffBlobs(e.before, e.after),
    live: true,
  };
}

// ────────────────────────────────────────────────────────── diff helpers ────

function diffPill(status: DiffField["status"]): { variant: StatusVariant; label: string } {
  if (status === "added") return { variant: "ok", label: "added" };
  if (status === "removed") return { variant: "crit", label: "removed" };
  return { variant: "warn", label: "changed" };
}

// The per-key diff table (red/green/yellow rows + a textual Status column for
// non-visual users). Color is never the sole signal — every row carries a Status pill.
function DiffTable({ diff }: { diff: DiffField[] }) {
  if (!diff.length) {
    return (
      <p style={{ fontSize: 12, color: "var(--fg-muted)", margin: 0 }}>
        No field-level changes recorded for this entry.
      </p>
    );
  }
  return (
    <div className="tablecard">
      <table className="tbl">
        <thead>
          <tr>
            <th scope="col" style={{ width: "26%" }}>
              Config key
            </th>
            <th scope="col">Before</th>
            <th scope="col">After</th>
            <th className="num" scope="col" style={{ width: 96 }}>
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {diff.map((d) => {
            const p = diffPill(d.status);
            return (
              <tr className="data" key={d.key}>
                <td>
                  <span className="mono" style={{ fontSize: "11.5px" }}>
                    {d.key}
                  </span>
                </td>
                <td>
                  <code className="kvline">{d.before ?? "—"}</code>
                </td>
                <td>
                  <code className="kvline">{d.after ?? "—"}</code>
                </td>
                <td className="num">
                  <Pill variant={p.variant}>{p.label}</Pill>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ────────────────────────────────────────────────────── Expandable row ──────

function CfgRow({
  row,
  rollbackByChangeId,
  onRollback,
  canRollback,
}: {
  row: ConfigChange;
  /** Map of change_id → the rollback entry that reverted it (chain visualization). */
  rollbackByChangeId: Map<string, ConfigChange>;
  onRollback: (row: ConfigChange) => void;
  canRollback: boolean;
}) {
  const [open, setOpen] = useState(false);
  const isRollback = row.actionType === "rollback";
  const revertedBy = rollbackByChangeId.get(row.changeId);
  // Stable id linking the clickable header row to its expanded detail row (the header's
  // aria-controls lets screen readers announce the revealed panel).
  const panelId = `cfg-exp-${row.changeId}`;
  const toggle = () => setOpen((o) => !o);
  return (
    <>
      <tr
        className={cn("data", "exp-toggle", open && "open")}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
        onKeyDown={(e) => {
          // Tab + Enter/Space expands/collapses (keyboard parity with mouse click).
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
      >
        <td className="num">{row.when}</td>
        <td>
          <Tag>{row.area}</Tag>
        </td>
        <td>
          <span className="cell-repo">
            <span className="exp">
              <Icon name={open ? "chevron" : "chevronR"} />
            </span>
            {isRollback && <Pill variant="info">rollback</Pill>}
            {revertedBy && <Pill variant="warn">reverted</Pill>}
            {row.change}
          </span>
        </td>
        <td>
          <span className="mono" style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}>
            {row.actor}
          </span>
        </td>
      </tr>
      <tr className="exp-row" id={panelId} hidden={!open}>
        <td colSpan={4}>
          <div className="exp-panel" style={{ gridTemplateColumns: "1fr", paddingLeft: 40 }}>
            {/* Metadata strip: change ID, config key, action type, request ID, artifact */}
            <div className="drill-kv" style={{ marginBottom: 4 }}>
              <span className="kvline">
                change_id=<b>{row.changeId}</b>
              </span>
              <span className="kvline">
                key=<b>{row.configKey}</b>
              </span>
              <span className="kvline">
                action=<b>{row.actionType}</b>
              </span>
              <span className="kvline">
                request_id=<b>{row.requestId ?? "—"}</b>
              </span>
              {row.artifactPath && (
                <span className="kvline" title={row.artifactPath}>
                  artifact=<b className="mono">{row.artifactPath}</b>
                </span>
              )}
            </div>

            {/* Human-readable expansion of the raw config scope. */}
            {scopeDescription(row.area) && (
              <div
                className="kvline"
                style={{ marginBottom: 4, color: "var(--fg-muted)" }}
              >
                {scopeDescription(row.area)}
              </div>
            )}

            {/* Rollback-chain references (rollback_of_change_id) */}
            {(row.rollbackOf || revertedBy) && (
              <div className="drill-kv" style={{ marginBottom: 4 }}>
                {row.rollbackOf && (
                  <span className="kvline">
                    <Pill variant="info">reverts</Pill> change <b>{row.rollbackOf}</b>
                  </span>
                )}
                {revertedBy && (
                  <span className="kvline">
                    <Pill variant="warn">reverted by</Pill> change <b>{revertedBy.changeId}</b> ·{" "}
                    {revertedBy.when}
                  </span>
                )}
              </div>
            )}

            {/* Operator-provided reason (audit context) */}
            <div className="exp-reason">
              <div className="eh">Operator reason</div>
              <div className="why">{row.reason}</div>
            </div>

            {/* Per-key before/after diff, inline (no modal deep-dives) */}
            <div>
              <div className="eh">Configuration diff</div>
              <DiffTable diff={row.diff} />
            </div>

            <div className="exp-actions">
              <Button
                variant="btn-danger"
                size="sm"
                icon="history"
                disabled={!canRollback}
                title={canRollback ? undefined : `Requires the ${ROLLBACK_SCOPE} scope`}
                onClick={(e) => {
                  e.stopPropagation();
                  onRollback(row);
                }}
              >
                Rollback this change
              </Button>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}

// ───────────────────────────────────────── Rollback reason-capture modal (kit) ──
// Reuses ConfirmModal's exact classes (`.modal-overlay` / `.modal` / `.modal-*`) with a
// <textarea> + focus-trap + Esc-to-close, so it matches the system. Owns the
// "Rollback in progress" (Applying rollback… · disabled dismissal) and "Rollback error"
// (in-dialog alert) states, which the generic confirm() overlay cannot express.

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

function RollbackModal({
  row,
  product,
  pending,
  error,
  onSubmit,
  onClose,
}: {
  row: ConfigChange;
  product: string;
  /** True while the rollback mutation is in flight. */
  pending: boolean;
  /** Error message when the rollback mutation failed. */
  error: string | null;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const trimmed = reason.trim();
  const reasonOk = trimmed.length >= REASON_MIN;

  // Accessibility: when the dialog closes, focus returns to the
  // triggering "Rollback this change" button. Capture it at mount, restore it on unmount.
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    return () => trigger?.focus?.();
  }, []);

  // Accessibility: focus moves to the reason field on open (immediate typing).
  useEffect(() => {
    reasonRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (pending) return; // cannot dismiss while the mutation is in flight
      if (e.key === "Escape") onClose();
      else if (e.key === "Tab") trapFocus(e, modalRef.current);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, pending]);

  function submit() {
    if (!reasonOk || pending) return;
    onSubmit(trimmed);
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        // Cannot dismiss the dialog while the rollback is applying.
        if (!pending && e.target === e.currentTarget) onClose();
      }}
    >
      {/* role=alertdialog announces the destructive nature. */}
      <div
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="cfg-rb-title"
        aria-describedby="cfg-rb-warn"
        ref={modalRef}
      >
        <div className="modal-head">
          <div className="mi">
            <Icon name="history" />
          </div>
          <div className="modal-title" id="cfg-rb-title">
            Roll back configuration change
          </div>
          <button
            type="button"
            className="x"
            aria-label="Close"
            onClick={onClose}
            disabled={pending}
          >
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div id="cfg-rb-warn">
            This reverts the <b>{row.area}</b> change <b>{row.change}</b> made by{" "}
            <b>{row.actor}</b> on <b>{row.when}</b>, and records a new rollback entry in the history
            ledger.
          </div>
          <div className="sum">
            Change <b>{row.changeId}</b> · <Tag>{product}</Tag> · key <b>{row.configKey}</b>
            <br />
            Restores the configuration state captured before this change.
          </div>

          <div className="modal-field" style={{ marginBottom: error ? 14 : 0 }}>
            <label htmlFor="cfg-rb-reason" id="cfg-rb-reason-label">
              Rollback reason
            </label>
            <textarea
              id="cfg-rb-reason"
              ref={reasonRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Incident mitigation: threshold too aggressive, restoring prior value"
              aria-labelledby="cfg-rb-reason-label"
              aria-describedby="cfg-rb-reason-hint"
              rows={3}
              disabled={pending}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 68,
                resize: "vertical",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                padding: "9px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: "var(--fg)",
                outline: "none",
                lineHeight: 1.5,
              }}
            />
            <div className="confirm-hint" id="cfg-rb-reason-hint">
              {reasonOk
                ? "A clear reason helps the team understand this action in audit history."
                : `Required · at least ${REASON_MIN} characters (${trimmed.length}/${REASON_MIN}).`}
            </div>
          </div>

          {/* Rollback error (mutation failed): alert adjacent to the dialog. */}
          {error && (
            <div className="recovery" role="alert" style={{ marginBottom: 0 }}>
              <div className="rec-ico">
                <Icon name="alert" />
              </div>
              <div className="rec-body">
                <div className="rec-title">Rollback failed</div>
                <div className="rec-text">{error}</div>
                <div className="rec-cause">
                  Likely cause: missing write:settings scope, the change was not found, or the audit
                  store is read-only.
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onClose}
            disabled={pending}
            title="Cancel the rollback and close the dialog without making changes."
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={!reasonOk || pending}
            onClick={submit}
            title="Confirm configuration rollback. Product settings will immediately revert to their previous state."
          >
            {pending ? (
              <>
                <Icon name="refresh" className="ico" />
                Applying rollback…
              </>
            ) : (
              "Confirm rollback"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────── How-To help popover (kit) ──
// Reuses the shell Popover classes (Esc + outside-click via usePopover) for contextual
// help with a return link to the full How-To.

function HelpPopover({ onOpenHowTo }: { onOpenHowTo: () => void }) {
  const pop = usePopover();
  return (
    <div className="pop-wrap" ref={pop.wrapRef} style={{ position: "relative" }}>
      <IconButton
        icon="info"
        aria-label="Help: Config History & Rollback"
        aria-haspopup="menu"
        aria-expanded={pop.open}
        onClick={pop.toggle}
      />
      {pop.open && (
        <PopoverPanel className="pop-help">
          <div className="pop-head">
            <span className="pt">Config History & Rollback</span>
            <span className="ps">runbook</span>
          </div>
          <div className="pop-body">
            <div style={{ padding: "6px 0" }}>
              <div className="pop-sub" style={{ margin: "0 0 3px" }}>
                Why this exists
              </div>
              <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5 }}>
                An immutable audit trail of product-level settings changes — and a one-click lever to
                revert a change that degraded quality.
              </div>
            </div>
            <div style={{ padding: "6px 0" }}>
              <div className="pop-sub" style={{ margin: "0 0 3px" }}>
                How to roll back
              </div>
              <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5 }}>
                Expand the suspect entry, review the per-key diff, then Rollback with a documented
                reason. The reversal is recorded as a new entry.
              </div>
            </div>
            <div style={{ padding: "6px 0" }}>
              <div className="pop-sub" style={{ margin: "0 0 3px" }}>
                Scope
              </div>
              <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5 }}>
                Product settings only. Runtime snapshot rollback lives in Snapshots.
              </div>
            </div>
          </div>
          <div className="pop-foot">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                pop.close();
                onOpenHowTo();
              }}
            >
              <Icon name="arrow" className="ico" />
              Open full How-To
            </button>
          </div>
        </PopoverPanel>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────── Section ──────

export function ConfigSection() {
  const { navigate } = useShell();
  const { toast } = useToast();
  const data = useAdminData();
  const [product, setProduct] = useState(PRODUCTS[0]);
  // The entry currently targeted by the reason-capture modal (null = closed).
  const [rollbackTarget, setRollbackTarget] = useState<ConfigChange | null>(null);
  const [rollbackError, setRollbackError] = useState<string | null>(null);

  // The hook owns the change-log query + rollback mutation; product state lives
  // here and drives `selectedProductId`. Scope gate comes from the session.
  const canRollback = data.can(ROLLBACK_SCOPE);
  const cfg = useConfigHistory({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "config-history-rollback",
    selectedProductId: product,
    canWriteSettings: canRollback,
    isSuperuser: data.session?.is_superuser ?? false,
  });

  // Offline → fixtures (section stays reviewable with no backend). Online → live results
  // only, so a live success with zero rows shows the empty state instead of being
  // masked by fixtures.
  const offline = !data.sessionIsSuccess;
  const liveEntries = cfg.configHistoryQuery.data ?? [];
  const rows: ConfigChange[] = offline
    ? (CFG_DATA[product] ?? [])
    : liveEntries.map(entryToRow);

  // Index reverted change_id → its rollback entry so each row can show the chain.
  const rollbackByChangeId = new Map<string, ConfigChange>();
  for (const r of rows) {
    if (r.rollbackOf) rollbackByChangeId.set(r.rollbackOf, r);
  }

  // State-gates fire on the DISPLAY set so a populated fixture is never hidden by a
  // skeleton/error offline (mirrors Health). A genuinely empty product still falls
  // through to the EmptyState. `stale` reflects an in-flight refetch after a rollback.
  const loading = cfg.configHistoryQuery.isLoading && !rows.length;
  const errored = cfg.configHistoryQuery.isError && !rows.length;
  const stale = cfg.configHistoryQuery.isFetching && !cfg.configHistoryQuery.isLoading;
  const pending = cfg.rollbackConfigMutation.isPending;

  const visible = rows.slice(0, DEFAULT_VISIBLE);
  const overflow = rows.slice(DEFAULT_VISIBLE);

  // Contextual help deep-link. This section maps to How-To article
  // "admin-config-history-rollback"; land directly on it and carry the return
  // context so the reader shows a working "Back to Config History & Rollback"
  // link (?article/?from/?source_label/?return_to are the params HowTo.tsx consumes).
  function openHowTo() {
    const params = new URLSearchParams({
      article: "admin-config-history-rollback",
      from: "config-history-rollback",
      source_label: "Config History & Rollback",
      return_to: "/#config-history-rollback",
    });
    window.location.href = `/howto?${params.toString()}`;
  }

  function requestRollback(row: ConfigChange) {
    if (!canRollback) return;
    setRollbackError(null);
    setRollbackTarget(row);
  }

  function submitRollback(reason: string) {
    const row = rollbackTarget;
    if (!row) return;
    setRollbackError(null);
    if (row.live) {
      // Live: POST the rollback through the hook with the operator-typed reason on
      // the wire — `{ change_id, reason }` — so the persisted audit record carries
      // the real reason the dialog collected. The hook
      // invalidates the history query + error-toasts on failure; the in-dialog
      // alert below is the error surface, and the success toast
      // fires only after the mutation settles.
      cfg.rollbackConfigMutation.mutate(
        { changeId: row.changeId, reason },
        {
          onSuccess: () => {
            setRollbackTarget(null);
            toast("Config rollback applied · previous configuration restored");
          },
          onError: (e: unknown) =>
            setRollbackError(e instanceof Error ? e.message : "The rollback request failed."),
        },
      );
    } else {
      // Offline fixtures have no backend; the operator reason is validated and echoed
      // back so the audited flow is fully exercisable without a server (a safe no-op).
      const snippet = reason.length > 48 ? `${reason.slice(0, 48)}…` : reason;
      setRollbackTarget(null);
      toast(`Config rollback applied · ${row.configKey} restored · reason: ${snippet}`);
    }
  }

  // Export the full change history for compliance review .
  // Builds a CSV from the DISPLAY set so it works fully offline (fixtures) and online.
  function exportHistory() {
    const header = [
      "change_id",
      "when",
      "product_id",
      "config_scope",
      "config_key",
      "action_type",
      "actor_key_id",
      "request_id",
      "rollback_of_change_id",
      "reason",
    ];
    const esc = (s: string) => `"${s.replace(/"/g, '""')}"`;
    const lines = rows.map((r) =>
      [
        r.changeId,
        r.when,
        product,
        r.area,
        r.configKey,
        r.actionType,
        r.actor,
        r.requestId ?? "",
        r.rollbackOf ?? "",
        r.reason,
      ]
        .map((v) => esc(String(v)))
        .join(","),
    );
    const csv = [header.join(","), ...lines].join("\n");
    if (typeof document !== "undefined") {
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `config-history-${product}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    }
    toast(`Exported ${rows.length} change${rows.length === 1 ? "" : "s"} · config-history-${product}.csv`);
  }

  return (
    <>
      <PageHead
        title="Config History & Rollback"
        sub="Track configuration changes over time and roll back to previous states."
        onHelp={openHowTo}
        actions={
          <>
            <HelpPopover onOpenHowTo={openHowTo} />
            <span className="muted-note">Auto-refresh 60s</span>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="download"
              disabled={!rows.length}
              onClick={exportHistory}
            >
              Export CSV
            </Button>
            <Button
              variant="btn-primary"
              size="sm"
              icon="refresh"
              disabled={cfg.configHistoryQuery.isFetching}
              onClick={() => cfg.configHistoryQuery.refetch()}
            >
              Refresh
            </Button>
          </>
        }
      />

      {!canRollback && (
        <PermissionDenied
          scope={ROLLBACK_SCOPE}
          extra="You can read the full change history, but rolling a change back stays disabled until an administrator grants the scope."
        />
      )}

      <Banner
        variant="info"
        icon="info"
        guidance
        title="Read the diff before you revert"
        text="Expand an entry to inspect the exact per-key before/after diff, the operator reason, and any rollback chain. Rollback restores product-level settings only — runtime snapshot rollback lives in Snapshots."
      />

      <Card
        title="Configuration change log"
        right={stale ? <StaleBadge>cache lag</StaleBadge> : undefined}
      >
        <div data-scopebody="config">
          <div className="toolbar">
            <Select
              label="Product"
              width={200}
              options={PRODUCTS}
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              aria-describedby="cfg-product-hint"
            />
            {/* Change-count chip + product-filter helper (product selector & controls row). */}
            {rows.length > 0 && (
              <Tag>
                {rows.length} change{rows.length === 1 ? "" : "s"}
              </Tag>
            )}
            <span id="cfg-product-hint" className="muted-note">
              Select a product to filter the configuration change log.
            </span>
            <div className="toolbar-right">
              <span className="muted-note">
                Scope: product-level settings · runtime snapshot rollback lives in Snapshots.
              </span>
            </div>
          </div>

          {loading ? (
            <Skeleton rows={4} />
          ) : errored ? (
            <ErrorState
              title="Config history is unavailable"
              text="The config history feed could not be loaded. Retry config history first; if it still fails, avoid rollback decisions until you can verify the change trail. Escalate if rollback or audit decisions are blocked because config history cannot be read."
              cause="the config audit store is unavailable or the current session cannot read rollback history"
              actions={
                <>
                  <Button
                    variant="btn-primary"
                    size="sm"
                    icon="refresh"
                    onClick={() => cfg.configHistoryQuery.refetch()}
                  >
                    Retry config history
                  </Button>
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="arrow"
                    onClick={() => navigate("logs")}
                  >
                    Open Logs & Traces
                  </Button>
                </>
              }
            />
          ) : rows.length === 0 ? (
            <EmptyState
              title="No configuration changes recorded"
              text="Changes appear here when settings are modified via the admin UI or API — retrieval weights, abuse-guard rules, or language aliases. Try changing a setting in Retrieval Settings or Language Registries for this product, then return here."
              action={
                <>
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="sliders"
                    onClick={() => navigate("retrieval")}
                  >
                    Retrieval Settings
                  </Button>
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="translate"
                    onClick={() => navigate("languages")}
                  >
                    Language Registries
                  </Button>
                </>
              }
            />
          ) : (
            <div className="tablecard">
              <table className="tbl">
                <thead>
                  <tr>
                    <th className="num" scope="col" style={{ width: 120 }}>
                      When
                    </th>
                    <th scope="col" style={{ width: 170 }}>
                      Area
                    </th>
                    <th scope="col">Change</th>
                    <th scope="col" style={{ width: 110 }}>
                      Actor
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row, i) => (
                    <CfgRow
                      key={row.changeId ?? `${row.when}-${i}`}
                      row={row}
                      rollbackByChangeId={rollbackByChangeId}
                      onRollback={requestRollback}
                      canRollback={canRollback}
                    />
                  ))}
                  {overflow.length > 0 && (
                    <ShowMoreRow
                      count={overflow.length}
                      colSpan={4}
                      extra={overflow.map((row, i) => (
                        <CfgRow
                          key={row.changeId ?? `more-${row.when}-${i}`}
                          row={row}
                          rollbackByChangeId={rollbackByChangeId}
                          onRollback={requestRollback}
                          canRollback={canRollback}
                        />
                      ))}
                    />
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      {rollbackTarget && (
        <RollbackModal
          row={rollbackTarget}
          product={product}
          pending={pending}
          error={rollbackError}
          onSubmit={submitRollback}
          onClose={() => {
            if (pending) return;
            setRollbackTarget(null);
            setRollbackError(null);
          }}
        />
      )}
    </>
  );
}
