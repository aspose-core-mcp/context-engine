"use client";

import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSqlExplorer, validateSelectOnlySql } from "@/hooks/useSqlExplorer";
import type { SqlSavedView } from "@/components/admin-console.types";
import { SQL_QUALITY_PRESETS } from "@/components/admin-console.types";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { Tabbed } from "../components/Tabbed";
import { Tag } from "../components/Tag";
import { Table, TableCard, ShowMoreRow } from "../components/Table";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";
import { PopoverPanel, usePopover } from "../shell/Popover";

/* ---------- fixtures (SQL_PRESETS) ---------- */

interface PresetResult {
  cols: string[];
  rows: string[][];
  /** Total matched rows; `> rows.length` means the result was truncated at the cap. */
  total: number;
}

interface Preset {
  key: string;
  label: string;
  /**
   * The EXACT SQL the preset puts into the editor — which is also exactly what a
   * Run executes and what Save persists (single `sql.sqlText` source of truth).
   * Runnable presets reuse the hook's `SQL_QUALITY_PRESETS` strings verbatim so
   * the displayed statement can never diverge from the executed one.
   */
  sql: string;
  /** Present for runnable presets; absent for the blocked-table demo. */
  result?: PresetResult;
  blocked?: boolean;
}

/**
 * Maps a fixture preset `key` to the hook's `SQL_QUALITY_PRESETS` id; the preset's
 * editor SQL is sourced from that table so loading a preset via `applySqlPreset`
 * yields exactly the string shown here. The "blocked" demo has no live counterpart
 * (it is rejected by the SELECT-only pre-check before execution).
 */
const PRESET_ID_BY_KEY: Record<string, string> = {
  noresults: "preset-no-results",
  fallback: "preset-fallback-reasons",
  warnings: "preset-warning-codes",
};

function presetSqlFor(key: string): string {
  const id = PRESET_ID_BY_KEY[key];
  return SQL_QUALITY_PRESETS.find((p) => p.id === id)?.sql ?? "";
}

// Offline demo data: the canned `result` rows below have columns that correspond exactly to the preset SQL that is displayed
// and executed (display ↔ execute ↔ canned result always match). Live runs ignore
// them; offline they make Run fully reviewable.
const PRESETS: Preset[] = [
  {
    key: "noresults",
    label: "No-results",
    sql: presetSqlFor("noresults"),
    result: {
      cols: ["product_id", "programming_language", "requests"],
      rows: [
        ["aspose.3d", "python", "142"],
        ["aspose.barcode", "java", "88"],
        ["aspose.cad", "csharp", "61"],
        ["aspose.ocr", "cpp", "37"],
      ],
      total: 4,
    },
  },
  {
    key: "fallback",
    label: "Fallback reasons",
    sql: presetSqlFor("fallback"),
    result: {
      cols: ["fallback_reason", "requests"],
      rows: [
        ["version_mismatch", "128"],
        ["negotiation_timeout", "41"],
        ["protocol_error", "22"],
        ["network_issue", "12"],
      ],
      total: 4,
    },
  },
  {
    key: "warnings",
    label: "Warning codes",
    sql: presetSqlFor("warnings"),
    result: { cols: ["warning_codes", "requests"], rows: [], total: 0 },
  },
  {
    key: "blocked",
    label: "Blocked table (demo)",
    sql: "SELECT * FROM api_keys;",
    blocked: true,
  },
];

/** Canned result for an offline run of arbitrary SQL (no preset fixture to show). */
const EMPTY_FIXTURE_RESULT: PresetResult = { cols: [], rows: [], total: 0 };

/** Loose SQL equality — ignores leading/trailing whitespace and a trailing `;`. */
function sameSql(a: string, b: string): boolean {
  const norm = (s: string) => s.trim().replace(/;+\s*$/, "");
  return norm(a) === norm(b);
}

/** Column metadata for a schema table (name + type + human description). */
interface SchemaColumn {
  name: string;
  type: string;
  desc: string;
}

interface SchemaRow {
  table: string;
  desc: string;
  access: "readable" | "blocked";
  /** Per-column catalog — surfaced inline so operators avoid invalid references. */
  columns: SchemaColumn[];
  /** A ready-to-run sample SELECT loaded into the editor via "Use sample". */
  sample: string;
}

// API limitation: offline the sqlSchemaQuery is disabled (no API key), so the rich
// per-column catalog, sample queries, and access flags come from this fixture.
// When the live schema is present its tables/columns/sample_query/blocked lists win.
const SCHEMA: SchemaRow[] = [
  {
    table: "analytics_queries",
    desc: "request log · endpoint, outcome, latency",
    access: "readable",
    columns: [
      { name: "request_id", type: "uuid", desc: "primary key · joins feedback & issues" },
      { name: "product_id", type: "text", desc: "canonical product, e.g. aspose.ocr" },
      { name: "programming_language", type: "text", desc: "SDK binding language" },
      { name: "doc_locale", type: "text", desc: "documentation locale" },
      { name: "outcome", type: "text", desc: "answered / zero_result / fallback" },
      { name: "latency_ms", type: "int", desc: "end-to-end retrieval latency" },
      { name: "confidence", type: "float", desc: "ranked confidence score 0..1" },
      { name: "created_at", type: "timestamptz", desc: "request time (UTC)" },
    ],
    sample:
      "SELECT product_id, COUNT(*) AS requests\nFROM analytics_queries\nGROUP BY product_id\nORDER BY requests DESC\nLIMIT 100",
  },
  {
    table: "usefulness_feedback",
    desc: "thumbs / reason codes per request",
    access: "readable",
    columns: [
      { name: "request_id", type: "uuid", desc: "foreign key → analytics_queries" },
      { name: "user_rating", type: "int", desc: "1..5 usefulness rating" },
      { name: "reason_code", type: "text", desc: "negative-feedback reason" },
      { name: "created_at", type: "timestamptz", desc: "feedback time (UTC)" },
    ],
    sample:
      "SELECT reason_code, COUNT(*) AS n\nFROM usefulness_feedback\nWHERE user_rating <= 2\nGROUP BY reason_code\nORDER BY n DESC\nLIMIT 100",
  },
  {
    table: "issue_intake_reports",
    desc: "operator-filed issue reports",
    access: "readable",
    columns: [
      { name: "request_id", type: "uuid", desc: "foreign key → analytics_queries" },
      { name: "type", type: "text", desc: "issue category" },
      { name: "product_id", type: "text", desc: "affected product" },
      { name: "notes", type: "text", desc: "free-form operator notes" },
    ],
    sample:
      "SELECT type, COUNT(*) AS n\nFROM issue_intake_reports\nGROUP BY type\nORDER BY n DESC\nLIMIT 100",
  },
  {
    table: "analytics_warnings",
    desc: "per-session warning codes",
    access: "readable",
    columns: [
      { name: "request_id", type: "uuid", desc: "foreign key → analytics_queries" },
      { name: "warning_code", type: "text", desc: "emitted warning code" },
      { name: "created_at", type: "timestamptz", desc: "warning time (UTC)" },
    ],
    sample:
      "SELECT warning_code, COUNT(*) AS hits\nFROM analytics_warnings\nGROUP BY warning_code\nORDER BY hits DESC\nLIMIT 100",
  },
];

// API limitation (offline): the live schema payload carries `blocked_tables` +
// `blocked_column_patterns`; offline these fixtures stand in so the security
// catalog is fully reviewable. Live lists win when sqlSchemaQuery resolves.
const BLOCKED_TABLES_FIXTURE: string[] = [
  "admin_api_keys",
  "admin_sessions",
  "pg_authid",
  "pg_shadow",
  "pg_user",
  "pg_roles",
];

const BLOCKED_COLUMNS_FIXTURE: string[] = [
  "token_hash",
  "api_key",
  "password",
  "secret",
  "private_key",
  "credentials",
  "session_token",
];

/**
 * Saved-query fixtures — used wholesale OFFLINE so the Saved-queries tab renders a
 * fully-reviewable, interactive list when no operator has saved anything in this
 * browser yet. When `sql.savedSqlViews` (localStorage) is non-empty, the live list
 * wins and these are not shown.
 */
const SAVED_FIXTURE: SqlSavedView[] = [
  {
    view_id: "fx-zero-results",
    name: "Zero-result clusters by product",
    sql: "SELECT product_id, COUNT(*) AS zero_results FROM analytics_queries WHERE outcome = 'zero_result' GROUP BY product_id ORDER BY zero_results DESC",
    created_at: "2026-05-18T09:12:00.000Z",
    updated_at: "2026-05-29T14:03:00.000Z",
    author_email: "sre@example.com",
    description: "Daily triage — products with the most empty retrievals.",
    comment: "Run with a WHERE created_at filter for incident windows.",
  },
  {
    view_id: "fx-latency-lang",
    name: "p95 latency by SDK language",
    sql: "SELECT programming_language, ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95_ms FROM analytics_queries GROUP BY programming_language ORDER BY p95_ms DESC",
    created_at: "2026-05-21T11:40:00.000Z",
    updated_at: "2026-05-21T11:40:00.000Z",
    author_email: "ingestion@example.com",
    description: "Latency SLA check per language binding.",
  },
  {
    view_id: "fx-feedback-reasons",
    name: "Low-usefulness reason codes",
    sql: "SELECT f.reason_code, COUNT(*) AS n FROM usefulness_feedback f JOIN analytics_queries q ON q.request_id = f.request_id WHERE f.user_rating <= 2 GROUP BY f.reason_code ORDER BY n DESC",
    created_at: "2026-05-25T16:22:00.000Z",
    updated_at: "2026-06-01T08:15:00.000Z",
    author_email: "analyst@example.com",
    description: "Dominant negative-feedback reasons for the last window.",
    comment: "Correlate with issue_intake_reports for content-gap RCAs.",
  },
];

/** Saved-query rows visible before the "show more" expander (keeps the list scannable). */
const SAVED_PAGE_SIZE = 8;

/** Min length for the Edit-dialog discard confirmation to treat fields as dirty. */
const EDIT_DIRTY_NONE = "";

/** Short, locale-stable date for saved-query timestamps (avoids hydration drift). */
function fmtSavedDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().slice(0, 10);
}

/** Client-side `analytics-export-YYYYMMDD-HHMMSS.csv` name (matches the backend). */
function exportFilename(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}-${p(
    d.getUTCHours(),
  )}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}`;
  return `analytics-export-${stamp}.csv`;
}

/**
 * SQL tokenizer for the highlight layer — wraps keywords and single-quoted string
 * literals in `.kw` spans. Multi-word
 * keywords are listed before their single-word prefixes so `GROUP BY` highlights
 * as one token. Matching is case-insensitive; the original casing is preserved.
 */
const SQL_TOKEN_RE =
  /('(?:[^']|'')*')|\b(group\s+by|order\s+by|left\s+join|right\s+join|inner\s+join|outer\s+join|within\s+group|percentile_cont|select|from|where|join|on|and|or|not|as|in|is|null|like|between|case|when|then|else|end|union|all|distinct|having|limit|offset|asc|desc|count|sum|avg|min|max|round|coalesce|interval|now|with)\b/gi;

/** Tokenize SQL text into highlight nodes; newlines render via `white-space: pre-wrap`. */
function renderTokenizedSql(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  SQL_TOKEN_RE.lastIndex = 0;
  for (let m = SQL_TOKEN_RE.exec(text); m != null; m = SQL_TOKEN_RE.exec(text)) {
    if (m.index > last) {
      nodes.push(<Fragment key={key++}>{text.slice(last, m.index)}</Fragment>);
    }
    nodes.push(
      <span className="kw" key={key++}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  }
  return nodes;
}

/**
 * Editable SQL editor — keeps the `.sql-editor` look (tokenized `.kw`
 * highlighting) while being a real input: a transparent absolutely-positioned
 * `<textarea>` (caret in `var(--fg)`, identical inherited font metrics + padding)
 * sits over the in-flow highlight layer, both rendering the SAME `value` string.
 * The highlight layer defines the auto-growing height; a trailing zero-width
 * space keeps a final empty line measurable so caret and box never desync.
 */
function SqlEditor({
  value,
  onChange,
  describedBy,
}: {
  value: string;
  onChange: (next: string) => void;
  describedBy?: string;
}) {
  const layerWrap = {
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
    wordBreak: "normal",
  } as const;
  return (
    <div className="sql-editor" id="sql-editor" style={{ position: "relative" }}>
      <div aria-hidden="true" style={{ ...layerWrap, pointerEvents: "none" }}>
        {renderTokenizedSql(value)}
        {"\u200b"}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="SQL query editor"
        aria-describedby={describedBy}
        spellCheck={false}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        wrap="soft"
        style={{
          ...layerWrap,
          position: "absolute",
          inset: 0,
          boxSizing: "border-box",
          // Same metrics as the highlight layer → glyph-perfect overlay.
          padding: "inherit",
          margin: 0,
          border: 0,
          outline: "none",
          resize: "none",
          overflow: "hidden",
          background: "transparent",
          color: "transparent",
          caretColor: "var(--fg)",
          font: "inherit",
          letterSpacing: "inherit",
          textAlign: "left",
        }}
      />
    </div>
  );
}

/* ---------- save-view popover (inline, reuses .pop classes) ---------- */

/**
 * Save-query popover — a popover overlay with three fields:
 * Name (required), Short description (optional), Comment (optional, multiline).
 * Reuses the kit's `.pop` / `.pop-head` / `.pop-body` / `.pop-foot` classes exactly
 * (as PopoverPanel does) so it matches the design system. Esc / outside-click close
 * is provided by `usePopover`. Save is disabled until Name is non-whitespace.
 */
function SaveViewPopover({
  open,
  name,
  description,
  comment,
  defaultSql,
  scopeOk,
  onName,
  onDescription,
  onComment,
  onCancel,
  onSave,
}: {
  open: boolean;
  name: string;
  description: string;
  comment: string;
  /** Preview of the SQL that will be persisted (read-only). */
  defaultSql: string;
  /** read:analytics gate — disables Save with inline messaging when false. */
  scopeOk: boolean;
  onName: (v: string) => void;
  onDescription: (v: string) => void;
  onComment: (v: string) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const nameOk = name.trim().length > 0;
  if (!open) return null;
  return (
    <PopoverPanel>
      <div className="pop-head">
        <span className="pt">Save current query</span>
        <span className="ps">this browser</span>
      </div>
      <div className="pop-body">
        <div className="field" style={{ marginBottom: 10 }}>
          <label className="flabel" htmlFor="sql-save-name">
            Name <span style={{ color: "var(--crit)" }}>*</span>
          </label>
          <input
            id="sql-save-name"
            className="inputctl"
            aria-label="saved sql view"
            placeholder="e.g. Zero-result clusters by product"
            value={name}
            onChange={(e) => onName(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            // Focus management: autoFocus on Name (popover mounts on open).
            autoFocus
          />
        </div>
        <div className="field" style={{ marginBottom: 10 }}>
          <label className="flabel" htmlFor="sql-save-desc">
            Short description
          </label>
          <input
            id="sql-save-desc"
            className="inputctl"
            aria-label="saved sql view description"
            placeholder="What does this query diagnose?"
            value={description}
            onChange={(e) => onDescription(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="field" style={{ marginBottom: 10 }}>
          <label className="flabel" htmlFor="sql-save-comment">
            Comment
          </label>
          <textarea
            id="sql-save-comment"
            className="st-ta"
            aria-label="saved sql view comment"
            placeholder="Context for the next operator (optional)…"
            rows={2}
            value={comment}
            onChange={(e) => onComment(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div className="muted-note" style={{ marginBottom: 2 }}>
          Saves the current editor SQL:
        </div>
        <div className="sum" style={{ margin: 0, maxHeight: 64, overflow: "auto" }}>
          {defaultSql || "—"}
        </div>
        {!scopeOk && (
          <div className="confirm-hint" style={{ marginTop: 8 }}>
            Requires the <b>read:analytics</b> scope to save.
          </div>
        )}
      </div>
      <div className="pop-foot" style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!nameOk || !scopeOk}
          title={
            !scopeOk
              ? "Requires read:analytics scope"
              : !nameOk
                ? "Name is required"
                : undefined
          }
          style={{ marginLeft: "auto" }}
          onClick={onSave}
        >
          Save query
        </button>
      </div>
    </PopoverPanel>
  );
}

/* ---------- edit-view dialog (inline, reuses ConfirmModal classes) ---------- */

/**
 * Edit-saved-query dialog — a dialog with four editable
 * fields: Name, Short description, Comment (multiline), SQL (multiline, monospace).
 * Reuses the kit's modal-overlay / modal / modal-field classes 1:1 (mirrors
 * ConfirmModal + Snapshots' ReasonModal), traps focus, and closes on Esc /
 * overlay-click. Cancel with unsaved edits warns before discard.
 */
function EditViewModal({
  view,
  onClose,
  onSave,
}: {
  view: SqlSavedView;
  onClose: () => void;
  onSave: (patch: {
    name: string;
    description?: string;
    comment?: string;
    sql: string;
  }) => void;
}) {
  const [name, setName] = useState(view.name);
  const [description, setDescription] = useState(view.description ?? "");
  const [comment, setComment] = useState(view.comment ?? "");
  const [sql, setSql] = useState(view.sql);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const nameOk = name.trim().length > 0;
  const sqlOk = sql.trim().length > 0;
  const dirty =
    name !== view.name ||
    description !== (view.description ?? EDIT_DIRTY_NONE) ||
    comment !== (view.comment ?? EDIT_DIRTY_NONE) ||
    sql !== view.sql;

  // Cancel: warn first if there are unsaved edits, else close immediately.
  function requestClose() {
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    onClose();
  }

  useEffect(() => {
    nameRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        requestClose();
        return;
      }
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
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
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  function doSave() {
    if (!nameOk || !sqlOk) return;
    onSave({
      name: name.trim(),
      description: description.trim() || undefined,
      comment: comment.trim() || undefined,
      sql: sql.trim(),
    });
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) requestClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sql-edit-title"
        ref={modalRef}
      >
        <div className="modal-head">
          <div className="mi" style={{ background: "var(--surface-3)", color: "var(--fg)" }}>
            <Icon name="sliders" />
          </div>
          <div className="modal-title" id="sql-edit-title">
            Edit saved query
          </div>
          <button type="button" className="x" aria-label="Close" onClick={requestClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          {confirmDiscard ? (
            <>
              <p>You have unsaved changes. Discard them and close the editor?</p>
              <div className="sum">
                Edits to <b>{view.name}</b> will be lost. Saved queries are easy to recreate, but
                this cannot be undone.
              </div>
            </>
          ) : (
            <>
              <div className="modal-field" style={{ marginBottom: 14 }}>
                <label htmlFor="sql-edit-name" id="sql-edit-name-label">
                  Name
                </label>
                <input
                  id="sql-edit-name"
                  ref={nameRef}
                  aria-label="saved sql view"
                  aria-labelledby="sql-edit-name-label"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
                {!nameOk && <div className="confirm-hint">Name is required.</div>}
              </div>
              <div className="modal-field" style={{ marginBottom: 14 }}>
                <label htmlFor="sql-edit-desc" id="sql-edit-desc-label">
                  Short description
                </label>
                <input
                  id="sql-edit-desc"
                  aria-labelledby="sql-edit-desc-label"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="modal-field" style={{ marginBottom: 14 }}>
                <label htmlFor="sql-edit-comment" id="sql-edit-comment-label">
                  Comment
                </label>
                <textarea
                  id="sql-edit-comment"
                  className="st-ta"
                  aria-labelledby="sql-edit-comment-label"
                  rows={2}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  spellCheck={false}
                />
              </div>
              <div className="modal-field">
                <label htmlFor="sql-edit-sql" id="sql-edit-sql-label">
                  SQL
                </label>
                <textarea
                  id="sql-edit-sql"
                  className="st-ta"
                  aria-labelledby="sql-edit-sql-label"
                  // SQL field minRows=6 (the multiline monospace editor).
                  rows={6}
                  value={sql}
                  onChange={(e) => setSql(e.target.value)}
                  spellCheck={false}
                />
                {!sqlOk && <div className="confirm-hint">SQL cannot be empty.</div>}
              </div>
            </>
          )}
        </div>
        <div className="modal-foot">
          {confirmDiscard ? (
            <>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setConfirmDiscard(false)}
              >
                Keep editing
              </button>
              <button type="button" className="btn btn-danger" onClick={onClose}>
                Discard changes
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-ghost" onClick={requestClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!nameOk || !sqlOk}
                onClick={doSave}
              >
                Save
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- result panel ---------- */

/**
 * Normalized result the panel renders. Built from the live `sqlQueryMutation`
 * result when a real query ran, else from a fixture preset's `result`.
 * `durationMs` is the live `sqlLastQueryDurationMs` when available, else null.
 */
interface RenderResult {
  cols: string[];
  rows: ReactNode[][];
  total: number;
  durationMs: number | null;
  /** True when the backend reported the result was capped at the 10k row limit. */
  truncated: boolean;
}

function ResultPanel({
  result,
  blocked,
  error,
}: {
  result: RenderResult | null;
  blocked: boolean;
  /** Live mutation error message, shown in place of the result table. */
  error?: string | null;
}) {
  if (blocked) {
    return (
      <ErrorState
        title="Query rejected"
        text="Access to credential/sensitive tables is blocked by policy."
        cause={<Tag>forbidden_table: api_keys</Tag>}
      />
    );
  }

  if (error) {
    // Surface statement-timeout guidance distinctly (query timeout state).
    const timedOut = /timeout/i.test(error);
    return (
      <ErrorState
        title={timedOut ? "Query timed out" : "Query failed"}
        text={
          timedOut
            ? "The statement exceeded the 30-second sandbox timeout. Add WHERE filters or a tighter date window to reduce the scanned row count."
            : "The query could not be executed against the metadata database."
        }
        cause={<Tag>{error}</Tag>}
      />
    );
  }

  if (!result) return null;

  const durLabel = result.durationMs != null ? `${result.durationMs} ms` : "487 ms";

  if (result.rows.length === 0) {
    // A `0 rows · <ms>` muted-note above the kit's EmptyState block — not an
    // inline table cell. The recovery hint suggests modifying WHERE and re-running.
    return (
      <>
        <div className="muted-note" style={{ marginBottom: 8 }} aria-live="polite">
          0 rows · {result.durationMs != null ? `${result.durationMs} ms` : "12 ms"}
        </div>
        <EmptyState
          title="Query returned no rows"
          text="The query executed successfully but matched no records in the current window. Widen the WHERE clause or date window and run again."
        />
      </>
    );
  }

  const truncated = result.truncated || result.total > result.rows.length;
  return (
    <>
      <div className="muted-note" style={{ marginBottom: 8 }} aria-live="polite">
        Results: {result.total} row{result.total !== 1 ? "s" : ""} · last query: {durLabel}
        {truncated ? " " : ""}
        {truncated && <Tag>truncated</Tag>}
      </div>
      <TableCard>
        <Table>
          <thead>
            <tr>
              {result.cols.map((c, i) => (
                <th key={c} className={i > 0 ? "num" : undefined}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, ri) => (
              <tr className="data" key={ri}>
                {r.map((v, ci) => (
                  <td key={ci} className={ci > 0 ? "num mono" : undefined}>
                    {ci === 0 ? <span className="repo-id">{v}</span> : v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </TableCard>
      {truncated && (
        <div className="muted-note" style={{ marginTop: 8 }}>
          <Icon name="info" className="ico" /> Result truncated at the 10 000-row cap. Add a WHERE
          clause or LIMIT to narrow the set.
        </div>
      )}
    </>
  );
}

/* ---------- section ---------- */

export function SqlSection() {
  const { navigate } = useShell();
  const { toast } = useToast();
  const data = useAdminData();

  // useSqlExplorer is mutation-driven: queries run on demand via sqlQueryMutation,
  // and sqlSchemaQuery auto-loads the schema when an API key is present. The hook
  // owns sqlText (the live query string), the saved-views list, and CSV export.
  const sql = useSqlExplorer({
    apiKey: data.apiKey,
    showAlert: data.showAlert,
    currentUserEmail: data.session?.owner_email,
  });

  // Read-only diagnostic console — gated on analytics read scope.
  const canRun = data.can("read:analytics");
  // ONLINE = real session established → run/export hit the backend and the panel
  // reflects the live mutation (data / empty / error). OFFLINE →
  // mutations never fire; Run renders the canned fixture result instead.
  const online = data.sessionIsSuccess;

  // null = no run yet (no result panel). "blocked" = the SELECT-only pre-check
  // rejected the statement before execution (the blocked-table demo). "fixture" =
  // an OFFLINE run; `result` is the canned rows to render (preset demo data, or
  // the 0-row result for arbitrary SQL with no canned counterpart).
  const [ran, setRan] = useState<
    null | { kind: "blocked" } | { kind: "fixture"; result: PresetResult }
  >(null);
  // Bumping this remounts <Tabbed> with initial={0}, which jumps the user back to the
  // Editor tab after a saved-query play/copy (the kit's Tabbed owns its own active
  // index; remounting is the in-file way to drive it without editing the component).
  const [editorJump, setEditorJump] = useState(0);

  // Saved-queries tab filters (client-side over the display source → work offline).
  const [savedSearch, setSavedSearch] = useState("");
  const [savedScope, setSavedScope] = useState<"all" | "mine">("all");
  // The saved query currently open in the Edit dialog (null = closed).
  const [editing, setEditing] = useState<SqlSavedView | null>(null);

  // Save-query popover (Save opens a 3-field popover overlay).
  const savePop = usePopover();

  // Live SELECT-only validation of the editor body:
  // drives the ✓ / blocked helper line and disables Run/Export on invalid SQL.
  const validation = validateSelectOnlySql(sql.sqlText);
  // Preset whose SQL is exactly what the editor currently shows (drives the
  // pressed state of the preset buttons and the offline canned-result lookup).
  const activePresetKey = PRESETS.find((p) => sameSql(p.sql, sql.sqlText))?.key ?? null;

  // Execute the editor SQL (or `statement` when it was just loaded this tick —
  // avoids running a stale `sqlText`). ONLINE → live mutation with settled-only
  // feedback; OFFLINE → canned preset result / 0-row result.
  function executeStatement(statement: string) {
    if (!validateSelectOnlySql(statement).ok) {
      // Rejected before execution (the blocked-table demo path).
      setRan({ kind: "blocked" });
      return;
    }
    if (online) {
      setRan(null);
      sql.runSqlQueryWithTiming(statement).then(
        () => undefined,
        (err: unknown) =>
          toast(`Query failed — ${err instanceof Error ? err.message : "execution error"}`),
      );
      return;
    }
    const preset = PRESETS.find((p) => p.result && sameSql(p.sql, statement));
    setRan({ kind: "fixture", result: preset?.result ?? EMPTY_FIXTURE_RESULT });
  }

  function loadPreset(p: Preset) {
    // Single source of truth: the preset writes the EXACT statement it stands for
    // into sql.sqlText — what is displayed is what Run executes and Save persists.
    if (p.blocked) {
      sql.setSqlText(p.sql);
    } else {
      sql.applySqlPreset(PRESET_ID_BY_KEY[p.key] ?? "");
    }
    sql.sqlQueryMutation.reset();
    // The blocked demo shows its rejection panel immediately — the statement
    // never reaches the backend.
    setRan(p.blocked ? { kind: "blocked" } : null);
  }

  // Load arbitrary SQL into the editor (single sqlText state) and jump to Editor.
  function loadSqlIntoEditor(rawSql: string) {
    sql.setSqlText(rawSql);
    sql.sqlQueryMutation.reset();
    setRan(null);
    setEditorJump((n) => n + 1);
  }

  // Play icon — loads query SQL into the editor, switches tab to Editor, and
  // immediately runs the query. Passes the SQL explicitly so the run can never
  // execute a stale editor body.
  function playSavedView(view: SqlSavedView) {
    loadSqlIntoEditor(view.sql);
    executeStatement(view.sql);
  }

  // Copy-into-editor — loads query SQL into the editor and switches tab to
  // Editor (does NOT run automatically).
  function loadSavedViewNoRun(view: SqlSavedView) {
    loadSqlIntoEditor(view.sql);
  }

  // Copy-to-clipboard — a copy affordance distinct from load+run.
  async function copySavedViewSql(view: SqlSavedView) {
    try {
      await navigator.clipboard?.writeText(view.sql);
      toast("Query SQL copied to clipboard");
    } catch {
      // Clipboard unavailable (e.g. offline / insecure context) → still load it in,
      // so the operator can copy manually. Never leaves the action inert.
      loadSavedViewNoRun(view);
      toast("Loaded into editor — copy from there");
    }
  }

  function deleteSavedView(view: SqlSavedView) {
    sql.deleteSqlView(view.view_id);
    toast("Saved query deleted");
  }

  // Edit dialog Save → updateSqlView bumps updated_at, preserves author/created_at.
  function saveEdit(
    viewId: string,
    patch: { name: string; description?: string; comment?: string; sql: string },
  ) {
    sql.updateSqlView(viewId, patch);
    toast("Saved query updated");
  }

  // Save-query popover Save → persists Name/Description/Comment + current SQL.
  // `sql.sqlText` IS the editor body (typing, presets, saved views and schema
  // samples all write the same state), so saveSqlView() persists exactly what is
  // on screen — never a divergent execute/save string.
  function commitSaveView() {
    sql.saveSqlView();
    // The hook clears name/description/comment only on a successful save; if the name
    // were blank it shows a validation alert and leaves the popover open. We close on
    // the happy path (name present, which the Save button already gates on).
    if (sql.sqlViewName.trim()) {
      savePop.close();
      toast("Query saved to this browser");
    }
  }

  // Run executes EXACTLY what the editor shows — the one sqlText state.
  function run() {
    executeStatement(sql.sqlText);
  }

  function exportCsv() {
    if (!online) {
      // Offline demo: no backend to hit — surface the timestamped filename
      // pattern so the operator sees what would download.
      toast(`Exporting ${exportFilename()}`);
      return;
    }
    sql.runSqlExportWithTiming().then(
      (res) => toast(`Exported ${res.filename}`),
      (err: unknown) =>
        toast(`Export failed — ${err instanceof Error ? err.message : "export error"}`),
    );
  }

  // Live validation line (empty → neutral guidance; invalid → blocked line in
  // crit color; valid → ✓ pre-check). Recomputed on every keystroke from sqlText.
  const validLine =
    sql.sqlText.trim().length === 0 ? (
      <>
        <Icon name="info" className="ico" /> Enter a SELECT query. Read-only, 30s timeout, 10,000
        row limit.
      </>
    ) : !validation.ok ? (
      <span style={{ color: "var(--crit)" }}>
        <Icon name="alert" className="ico" /> Blocked: {validation.error} SELECT is rejected before
        execution.
      </span>
    ) : (
      <>
        <Icon name="check" className="ico" /> Query is valid (frontend pre-check).
      </>
    );

  // Result panel state. Blocked rejection panel shows while the offending statement
  // is still in the editor; fixing the SQL clears it.
  const resultBlocked = ran?.kind === "blocked" && !validation.ok;
  // ONLINE the panel is mutation-driven only (live rows / empty /
  // error — never fixtures). OFFLINE it renders the canned fixture run, if any.
  const live = online ? sql.sqlQueryMutation.data : undefined;
  const resultError =
    !resultBlocked && online && sql.sqlQueryMutation.isError
      ? sql.sqlQueryMutation.error instanceof Error
        ? sql.sqlQueryMutation.error.message
        : "Query execution failed"
      : null;
  const fixtureResult = !online && ran?.kind === "fixture" ? ran.result : null;
  const renderResult: RenderResult | null = resultBlocked
    ? null
    : live != null
      ? {
          cols: live.columns,
          rows: live.rows.map((r) => r.map((v) => (v == null ? "" : String(v)))),
          total: live.row_count,
          durationMs: sql.sqlLastQueryDurationMs,
          truncated: live.truncated,
        }
      : fixtureResult
        ? {
            cols: fixtureResult.cols,
            rows: fixtureResult.rows,
            total: fixtureResult.total,
            durationMs: null,
            truncated: fixtureResult.total > fixtureResult.rows.length,
          }
        : null;

  // Export processing-time readout ("export: 102 ms"). Live duration wins;
  // offline a representative value keeps the readout informative.
  const exportDurLabel =
    sql.sqlLastExportDurationMs != null ? `${sql.sqlLastExportDurationMs} ms` : "102 ms";
  const exporting = sql.sqlExportMutation.isPending;

  /* ----- Tab 1: Editor ----- */
  const editorPanel = (
    <>
      <div className="preset-row">
        <span className="pl">Quick presets:</span>
        {PRESETS.map((p) => {
          const active = activePresetKey === p.key;
          return (
            <Button
              key={p.key}
              // The selected preset swaps
              // btn-ghost → btn-primary so the active query is visible, not just
              // exposed via aria-pressed.
              variant={active ? "btn-primary" : "btn-ghost"}
              size="sm"
              aria-pressed={active}
              onClick={() => loadPreset(p)}
            >
              {p.label}
            </Button>
          );
        })}
      </div>

      <SqlEditor value={sql.sqlText} onChange={sql.setSqlText} describedBy="sql-valid" />

      <div className="muted-note" id="sql-valid" style={{ margin: "8px 0 12px" }}>
        {validLine}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Button
          variant="btn-primary"
          size="sm"
          icon="play"
          disabled={!validation.ok || !canRun || sql.sqlQueryMutation.isPending}
          title={
            !canRun
              ? "Requires read:analytics scope"
              : !validation.ok
                ? validation.error
                : undefined
          }
          onClick={run}
        >
          {sql.sqlQueryMutation.isPending ? "Running…" : "Run SELECT"}
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          icon="download"
          disabled={!validation.ok || !canRun || exporting}
          title={
            !canRun
              ? "Requires read:analytics scope"
              : !validation.ok
                ? validation.error
                : undefined
          }
          onClick={exportCsv}
        >
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
        {/* Save popover anchor — relative wrapper so the .pop panel anchors here. */}
        <div ref={savePop.wrapRef} style={{ position: "relative" }}>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="plus"
            aria-haspopup="dialog"
            aria-expanded={savePop.open}
            title={!canRun ? "Requires read:analytics scope" : undefined}
            onClick={savePop.toggle}
          >
            Save query
          </Button>
          <SaveViewPopover
            open={savePop.open}
            name={sql.sqlViewName}
            description={sql.sqlViewDescription}
            comment={sql.sqlViewComment}
            defaultSql={sql.sqlText}
            scopeOk={canRun}
            onName={sql.setSqlViewName}
            onDescription={sql.setSqlViewDescription}
            onComment={sql.setSqlViewComment}
            onCancel={savePop.close}
            onSave={commitSaveView}
          />
        </div>
        <span className="muted-note" style={{ marginLeft: "auto" }}>
          Last export: {exportDurLabel} · file analytics-export-…csv
        </span>
      </div>

      <div style={{ marginTop: 16 }}>
        <ResultPanel result={renderResult} blocked={resultBlocked} error={resultError} />
      </div>
    </>
  );

  /* ----- Tab 2: Saved queries ----- */
  // Display source: the operator's real saved views win when present. OFFLINE the
  // fixtures render so the tab stays fully reviewable + interactive; ONLINE with an
  // empty store the empty state renders instead (never fixture stand-ins).
  const savedSource: SqlSavedView[] = sql.savedSqlViews.length
    ? sql.savedSqlViews
    : online
      ? []
      : SAVED_FIXTURE;
  // Client-side filters over the DISPLAY source → search + author scope work offline.
  const ownerEmail = data.session?.owner_email ?? null;
  const savedQuery = savedSearch.trim().toLowerCase();
  const savedShown = savedSource.filter((v) => {
    const mine = !!ownerEmail && v.author_email === ownerEmail;
    if (savedScope === "mine" && !mine) return false;
    if (!savedQuery) return true;
    return (
      v.name.toLowerCase().includes(savedQuery) ||
      (v.description ?? "").toLowerCase().includes(savedQuery) ||
      (v.author_email ?? "").toLowerCase().includes(savedQuery) ||
      v.sql.toLowerCase().includes(savedQuery)
    );
  });

  // Row-action cluster — Play (load+run), Copy-to-editor, Copy-SQL, Edit, Delete.
  function savedRowActions(v: SqlSavedView): ReactNode {
    return (
      <div className="op-right" style={{ marginLeft: 0 }}>
        <button
          type="button"
          className="icon-btn"
          title="Load & run in editor"
          aria-label={`Run saved query ${v.name}`}
          disabled={!canRun}
          onClick={() => playSavedView(v)}
        >
          <Icon name="play" className="ico" />
        </button>
        <button
          type="button"
          className="icon-btn"
          title="Load into editor (no run)"
          aria-label={`Load saved query ${v.name} into editor`}
          onClick={() => loadSavedViewNoRun(v)}
        >
          <Icon name="arrow" className="ico" />
        </button>
        <button
          type="button"
          className="icon-btn"
          title="Copy SQL to clipboard"
          aria-label={`Copy SQL of saved query ${v.name}`}
          onClick={() => void copySavedViewSql(v)}
        >
          <Icon name="layers" className="ico" />
        </button>
        <button
          type="button"
          className="icon-btn"
          title="Edit saved query"
          aria-label={`Edit saved query ${v.name}`}
          onClick={() => setEditing(v)}
        >
          <Icon name="sliders" className="ico" />
        </button>
        <button
          type="button"
          className="icon-btn"
          title="Delete saved query"
          aria-label={`Delete saved query ${v.name}`}
          onClick={() => deleteSavedView(v)}
        >
          <Icon name="x" className="ico" />
        </button>
      </div>
    );
  }

  // Present saved-query metadata as scannable
  // columns (Name · Description · Author · Created · Updated · actions), and — when
  // a comment is present — a full-width second row beneath it carrying the complete
  // comment (monospace, italic, pre-wrap, 💬 prefix) so long context is never
  // truncated. `.exp-row` gives it the hover-tone (surface-2) backdrop.
  function savedRow(v: SqlSavedView): ReactNode {
    return (
      <Fragment key={v.view_id}>
        <tr className="data">
          <td>
            <div className="op-name">{v.name}</div>
          </td>
          <td>
            <span className="card-sub" style={{ margin: 0 }}>
              {v.description ?? "—"}
            </span>
          </td>
          <td>
            <Tag>{v.author_email ?? "unknown"}</Tag>
          </td>
          <td className="mono">{fmtSavedDate(v.created_at)}</td>
          <td className="mono">{fmtSavedDate(v.updated_at ?? v.created_at)}</td>
          <td>{savedRowActions(v)}</td>
        </tr>
        {v.comment && (
          <tr className="exp-row">
            <td colSpan={6}>
              <div
                className="sum mono"
                style={{
                  margin: "0 16px",
                  fontStyle: "italic",
                  whiteSpace: "pre-wrap",
                  background: "transparent",
                  border: 0,
                }}
              >
                💬 {v.comment}
              </div>
            </td>
          </tr>
        )}
      </Fragment>
    );
  }

  const savedHead = savedShown.slice(0, SAVED_PAGE_SIZE);
  const savedRest = savedShown.slice(SAVED_PAGE_SIZE);

  const savedPanel = (
    <>
      <div className="preset-row">
        <span className="pl">Saved queries:</span>
        <div className="seg" role="group" aria-label="Filter saved queries by author">
          <button
            type="button"
            className={cn(savedScope === "all" && "on")}
            aria-pressed={savedScope === "all"}
            onClick={() => setSavedScope("all")}
          >
            All
          </button>
          <button
            type="button"
            className={cn(savedScope === "mine" && "on")}
            aria-pressed={savedScope === "mine"}
            onClick={() => setSavedScope("mine")}
          >
            Mine
          </button>
        </div>
        <input
          className="inputctl"
          style={{ maxWidth: 260 }}
          type="search"
          placeholder="Filter by name, author, or SQL…"
          aria-label="Filter saved queries"
          value={savedSearch}
          onChange={(e) => setSavedSearch(e.target.value)}
        />
      </div>

      {savedShown.length === 0 ? (
        <EmptyState
          title="No saved queries yet"
          text="Open the Editor tab, enter SQL, and click Save. Saved queries persist in this browser and keep their SELECT-only guardrails."
          action={
            <Button
              variant="btn-ghost"
              size="sm"
              icon="arrow"
              onClick={() => {
                setSavedSearch("");
                setSavedScope("all");
                setEditorJump((n) => n + 1);
              }}
            >
              Back to editor
            </Button>
          }
        />
      ) : (
        <TableCard>
          <Table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th style={{ width: 150 }}>Author</th>
                <th style={{ width: 96 }}>Created</th>
                <th style={{ width: 96 }}>Updated</th>
                <th style={{ width: 170 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {savedHead.map((v) => savedRow(v))}
              {savedRest.length > 0 && (
                <ShowMoreRow
                  colSpan={6}
                  count={savedRest.length}
                  extra={savedRest.map((v) => savedRow(v))}
                />
              )}
            </tbody>
          </Table>
        </TableCard>
      )}
    </>
  );

  /* ----- Tab 3: Database schema ----- */
  // Live schema from sqlSchemaQuery (the section's primary auto-running query);
  // access derived from the blocked_tables list. Fixtures used wholesale offline.
  const liveSchema = sql.sqlSchemaQuery.data;
  const schemaRows: SchemaRow[] = liveSchema
    ? liveSchema.tables.map((t) => ({
        table: t.name,
        desc: t.description,
        access: liveSchema.blocked_tables.includes(t.name) ? "blocked" : "readable",
        columns: t.columns.map((c) => ({
          name: c.name,
          type: c.data_type,
          desc: c.description ?? "—",
        })),
        sample: t.sample_query,
      }))
    : SCHEMA;
  // Blocked catalogs: the live schema's lists win whenever the schema resolved
  // (even when empty — never substitute fixtures for live data); fixtures offline.
  const blockedTables = liveSchema ? liveSchema.blocked_tables : BLOCKED_TABLES_FIXTURE;
  const blockedColumns = liveSchema
    ? liveSchema.blocked_column_patterns
    : BLOCKED_COLUMNS_FIXTURE;

  const schemaLoading = sql.sqlSchemaQuery.isLoading && !liveSchema;
  const schemaErrored = sql.sqlSchemaQuery.isError && !liveSchema;
  const schemaFetching = sql.sqlSchemaQuery.isFetching;

  // Track which schema table's column catalog is expanded (local UI state).
  const [openSchema, setOpenSchema] = useState<string | null>(null);

  // Use sample → load the table's sample query into the editor and jump to Editor.
  function useSample(s: SchemaRow) {
    loadSqlIntoEditor(s.sample);
    toast(`Loaded sample for ${s.table}`);
  }

  const schemaToolbar = (
    <div className="preset-row" style={{ justifyContent: "space-between" }}>
      <span className="pl">
        <Icon name="clock" className="ico" /> Schema cache refreshes every 10 minutes — use Refresh
        for an up-to-the-second catalog.
      </span>
      <Button
        variant="btn-ghost"
        size="sm"
        icon="refresh"
        disabled={schemaFetching}
        onClick={() => {
          void sql.sqlSchemaQuery.refetch();
          toast("Refreshing schema…");
        }}
      >
        {schemaFetching ? "Refreshing…" : "Refresh schema"}
      </Button>
    </div>
  );

  const schemaBody = schemaLoading ? (
    <>
      <Banner variant="info" icon="info" title="Loading schema…" text="Fetching the analytics table catalog from the admin API." />
      <Skeleton rows={5} />
    </>
  ) : schemaErrored ? (
    <ErrorState
      title="Failed to load database schema"
      text="The AnalyticsService is unreachable. You can still load and run saved queries from this browser; the Analytics dashboard remains available as a fallback."
      cause="the admin API is unreachable"
      actions={
        <Button size="sm" icon="refresh" onClick={() => sql.sqlSchemaQuery.refetch()}>
          Retry
        </Button>
      }
    />
  ) : (
    <>
      <TableCard className="schema-tbl">
        <Table>
          <thead>
            <tr>
              <th>Table</th>
              <th>Description</th>
              <th style={{ width: 110 }}>Access</th>
              <th style={{ width: 220 }}>Sample</th>
            </tr>
          </thead>
          <tbody>
            {schemaRows.map((s) => {
              const open = openSchema === s.table;
              return (
                <Fragment key={s.table}>
                  <tr className="data">
                    <td>
                      <button
                        type="button"
                        className="more-link"
                        aria-expanded={open}
                        aria-controls={`schema-cols-${s.table}`}
                        onClick={() => setOpenSchema(open ? null : s.table)}
                        style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                      >
                        <Icon name={open ? "chevron" : "chevronR"} className="chev" />
                        <span className="repo-id">{s.table}</span>
                      </button>
                    </td>
                    <td>
                      <span className="card-sub" style={{ margin: 0 }}>
                        {s.desc}
                      </span>
                    </td>
                    <td>
                      {s.access === "readable" ? (
                        <Pill variant="ok">readable</Pill>
                      ) : (
                        <Pill variant="crit">blocked</Pill>
                      )}
                    </td>
                    <td>
                      <Button
                        variant="btn-ghost"
                        size="sm"
                        icon="arrow"
                        disabled={s.access === "blocked"}
                        title={
                          s.access === "blocked"
                            ? "Blocked table — no sample available"
                            : "Load sample query into the editor"
                        }
                        onClick={() => useSample(s)}
                      >
                        Use sample
                      </Button>
                    </td>
                  </tr>
                  {open && (
                    <tr className="exp-row">
                      <td colSpan={4} id={`schema-cols-${s.table}`}>
                        <div className="exp-panel" style={{ gridTemplateColumns: "1fr" }}>
                          <div>
                            <div className="eh">Columns</div>
                            <div className="kv-list">
                              {s.columns.map((c) => (
                                <div className="kvline" key={c.name} style={{ marginBottom: 4 }}>
                                  <b>{c.name}</b> <Tag>{c.type}</Tag> — {c.desc}
                                </div>
                              ))}
                            </div>
                            <div className="eh" style={{ marginTop: 12 }}>
                              Sample query
                            </div>
                            <div className="sum" style={{ margin: "0 0 0 0", whiteSpace: "pre" }}>
                              {s.sample}
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
      </TableCard>

      {/* Dedicated red-chip sections for forbidden tables + column patterns. */}
      <Card
        title="Blocked tables"
        sub="These tables hold credentials and are rejected before execution — querying them returns a policy error."
        flush
      >
        <div
          className="badge-row"
          style={{ padding: "12px 16px", margin: 0 }}
          role="list"
          aria-label="Forbidden tables"
        >
          {blockedTables.map((t) => (
            <span key={t} role="listitem" aria-label={`forbidden table ${t}`}>
              <Pill variant="crit">{t}</Pill>
            </span>
          ))}
        </div>
      </Card>

      <Card
        title="Blocked column patterns"
        sub="Any query referencing these column names is rejected — even against readable tables."
        flush
      >
        <div
          className="badge-row"
          style={{ padding: "12px 16px", margin: 0 }}
          role="list"
          aria-label="Forbidden column patterns"
        >
          {blockedColumns.map((c) => (
            <span key={c} role="listitem" aria-label={`forbidden column pattern ${c}`}>
              <Pill variant="crit">{c}</Pill>
            </span>
          ))}
        </div>
      </Card>
    </>
  );

  const schemaPanel = (
    <>
      {schemaToolbar}
      {schemaBody}
    </>
  );

  return (
    <>
      <PageHead
        title="SQL Explorer"
        sub="Run read-only SQL queries against the metadata database."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("analytics")}>
            Open Analytics
          </Button>
        }
      />

      <Banner
        variant="info"
        icon="info"
        guidance
        title="Read-only diagnostic console"
        text="Queries are single-statement SELECTs, sandboxed and capped. Sensitive credential tables are rejected before execution."
      />

      <div className="badge-row">
        <Tag>SELECT only</Tag>
        <Tag>timeout 30s</Tag>
        <Tag>row limit 10k</Tag>
        <Tag>max export 100MB</Tag>
        <Pill variant="crit">sensitive tables blocked</Pill>
      </div>

      <Card title="Query">
        {/* `key={editorJump}` remounts Tabbed at the Editor tab when a saved-query
            play/copy (or "Back to editor") fires — the kit's Tabbed owns its active
            index, so remounting is the in-file way to jump tabs programmatically. */}
        <Tabbed
          key={editorJump}
          tabs={["Editor", `Saved queries (${savedSource.length})`, "Database schema"]}
          panels={[editorPanel, savedPanel, schemaPanel]}
        />
      </Card>

      {editing && (
        <EditViewModal
          view={editing}
          onClose={() => setEditing(null)}
          onSave={(patch) => saveEdit(editing.view_id, patch)}
        />
      )}
    </>
  );
}
