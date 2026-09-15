"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useHealthQueries } from "@/hooks/useHealthQueries";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Segmented } from "../components/Field";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { ErrorState, Skeleton, StaleBadge } from "../components/states";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, SectionKey } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";
import { PopoverPanel, usePopover } from "../shell/Popover";

// API limitation: no dedicated endpoint — workspace templates have no backing API,
// so the list stays a fixture; only the per-template launch gating is wired live
// via useAdminData().can(scope), falling back to GRANTED_SCOPES when offline.

interface Workspace {
  /** Stable template id — used as the `?workspace=` deep-link value + palette key. */
  id: string;
  icon: IconName;
  title: string;
  desc: string;
  /** [section label, required scope]. Empty scope ("") = no scope required. */
  meta: [section: string, scope: string];
  /** Target section key Launch / "Open section only" navigate to. */
  nav: SectionKey;
  /** Downstream section + safe defaults the operator lands on. */
  opened: string;
  /** Roles best suited to this template ("Recommended roles"). */
  roles: string[];
  /** Quick-action workflow keywords / tags. Also fuels palette search. */
  tags: string[];
  /** Bulleted pre-select details the template applies (summary line items). */
  summary: string[];
  /** Target panel anchor the launch jumps focus to inside the section. */
  anchor: string;
  /**
   * Cross-section prefill handed to the TARGET section via navigate()'s `intent`
   * so Launch applies downstream defaults. These mirror the human-readable
   * `summary`/`meta` scope as machine-applicable filter keys the destination drains
   * once through its own filter setters; unknown keys are ignored there. Optional so
   * older fixtures / navigate(key[, anchor]) call sites stay backward-compatible.
   */
  prefill?: Record<string, string>;
}

const WORKSPACES: Workspace[] = [
  {
    id: "operational-triage",
    icon: "grid",
    title: "Operational triage",
    desc: "Open the analytics issue inbox with critical-first filters: external pain, zero-result pressure, and linked request evidence in one jump.",
    meta: ["Analytics", ""],
    nav: "analytics",
    opened: "Analytics",
    roles: ["operator", "product-owner", "superuser"],
    tags: ["Review issue severity", "Open request evidence", "Escalate via critical events if needed"],
    summary: [
      "Product scope: aspose.ocr",
      "Severity default: critical",
      "Sort: zero-result pressure first",
    ],
    anchor: "analytics-issue-inbox-panel",
    prefill: { product: "aspose.ocr", severity: "critical", sort: "zero-result" },
  },
  {
    id: "ingestion-runbook",
    icon: "upload",
    title: "Ingestion runbook",
    desc: "Preload the single-run ingestion surface with the safest repo and product defaults so publish work starts in the controlled path.",
    meta: ["Ingestion", "write:ingestion"],
    nav: "ingestion",
    opened: "Ingestion",
    roles: ["operator", "superuser"],
    tags: ["Run single repo", "Validate before publish", "Check parse warnings"],
    summary: [
      "Product scope: aspose.ocr",
      "Source repo: safest default repository",
      "Validate-only mode enabled",
    ],
    anchor: "ingestion-run-single-panel",
    prefill: { product: "aspose.ocr", repo: "safest-default", mode: "validate-only" },
  },
  {
    id: "quality-review-desk",
    icon: "review",
    title: "Quality review desk",
    desc: "Open semantic review with a product-scoped run queue and policy presets so release gating starts from the safest posture.",
    meta: ["Quality", "write:settings"],
    nav: "quality",
    opened: "Quality Reviews",
    roles: ["product-owner", "superuser"],
    tags: ["Review run queue", "Apply balanced preset", "Reject with reason"],
    summary: [
      "Product scope: aspose.ocr",
      "Policy preset: balanced (threshold 4.3)",
      "Queue filter: needs review",
    ],
    anchor: "quality-runs-panel",
    prefill: { product: "aspose.ocr", preset: "balanced", queue: "needs-review" },
  },
  {
    id: "rollback-preparation",
    icon: "camera",
    title: "Rollback preparation",
    desc: "Jump into snapshot controls with explicit rollback discipline before any active content is changed.",
    meta: ["Snapshots", "write:ingestion"],
    nav: "snapshots",
    opened: "Snapshots",
    roles: ["operator", "superuser"],
    tags: ["Compare snapshots", "Prepare rollback", "Confirm audit_id"],
    summary: [
      "Product scope: aspose.ocr",
      "Active-snapshot resolver pre-filled",
      "Rollback confirmation required",
    ],
    anchor: "snapshots-active-panel",
    prefill: { product: "aspose.ocr", snapshot: "active", confirm: "required" },
  },
];

/** Scopes granted to the current admin key — fixture fallback for template gating when offline. */
const GRANTED_SCOPES: ReadonlySet<string> = new Set([
  "read:analytics",
  "read:logs",
  "read:events",
  "write:settings",
  "write:ingestion",
  "write:destructive",
]);

// OFFLINE FALLBACK: degraded-defaults is derived LIVE from Health-query dependency
// liveness (a required backing service not ready — see `degraded` below). Offline the
// health query is session-gated → disabled → no dependency rows, so we fall back to this
// fixture flag. Default off keeps the offline happy path clean; flip to `true` to preview
// the "defaults not fully initialized" banner with no backend.
const DEGRADED_DEFAULTS = false;

/** Availability filter — client-side over the display source so it responds offline on fixtures. */
const AVAIL_FILTERS = ["All", "Read-safe", "Scope-gated"] as const;
type AvailFilter = (typeof AVAIL_FILTERS)[number];

function matchesAvail(ws: Workspace, filter: AvailFilter): boolean {
  if (filter === "All") return true;
  const readSafe = ws.meta[1] === "";
  return filter === "Read-safe" ? readSafe : !readSafe;
}

/**
 * Resolve an inbound prefill {@link SectionIntent} to THIS section's only filter —
 * the availability segmented control. Used by the consume-on-mount handoff: another
 * section can hand Workspaces a one-shot intent (e.g. `{ avail: "Scope-gated" }`) and
 * we apply it through `setAvail`. Recognizes the canonical `avail` key plus a couple of
 * forgiving aliases/values; ANY unknown key or unmatched value returns `null` so the
 * intent is ignored gracefully (unknown filter keys are ignored, never thrown on).
 */
function availFromIntentFilters(filters: Record<string, string> | undefined): AvailFilter | null {
  if (!filters) return null;
  const raw = filters.avail ?? filters.access ?? filters.availability;
  if (typeof raw !== "string") return null;
  const v = raw.trim().toLowerCase();
  // Exact match against the canonical option labels (case-insensitive).
  const exact = AVAIL_FILTERS.find((opt) => opt.toLowerCase() === v);
  if (exact) return exact;
  // Forgiving synonyms for the two non-"All" options.
  if (v === "read-safe" || v === "readsafe" || v === "read" || v === "safe") return "Read-safe";
  if (v === "scope-gated" || v === "scopegated" || v === "scoped" || v === "gated") {
    return "Scope-gated";
  }
  if (v === "all" || v === "any") return "All";
  return null;
}

/** Read the current `?workspace=` deep-link value (browser only). */
function readWorkspaceParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("workspace");
}

/**
 * Persist (or clear) the `?workspace=` query param WITHOUT touching the hash route
 * (Shell routes off `location.hash`). Launch encodes state in the URL so it
 * survives reloads and is copyable/shareable; "Open section only" strips it.
 */
function writeWorkspaceParam(id: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("workspace", id);
  else url.searchParams.delete("workspace");
  window.history.replaceState(window.history.state, "", url.toString());
}

// ─────────────────────────────────────── in-section command palette ─────────
// Complements the global CommandPalette. The shell
// (shell/Shell.tsx) owns the window-level ⌘/Ctrl+K binding, and its global palette
// already surfaces "Launch: <template>" commands via WORKSPACE_LAUNCHERS — so this
// template palette registers NO keydown listener of its own (a second ⌘K binding
// would stack two .cmdk-overlay layers). It opens from the section's buttons only,
// reusing the kit `.cmdk-*` classes + Esc/arrow/Enter behaviour for template search.

function paletteScore(query: string, ws: Workspace): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const title = ws.title.toLowerCase();
  if (title.startsWith(q)) return 100;
  if (ws.id.includes(q)) return 85;
  if (title.split(/\s+/).some((w) => w.startsWith(q))) return 70;
  if (ws.tags.some((t) => t.toLowerCase().includes(q))) return 55;
  if (title.includes(q)) return 40;
  if (ws.opened.toLowerCase().includes(q)) return 30;
  return -1;
}

function WorkspacePalette({
  open,
  onClose,
  templates,
  onLaunch,
}: {
  open: boolean;
  onClose: () => void;
  templates: Workspace[];
  onLaunch: (ws: Workspace) => void;
}) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const ranked = useMemo(() => {
    if (!query.trim()) return templates;
    return templates
      .map((ws) => ({ ws, s: paletteScore(query, ws) }))
      .filter((x) => x.s >= 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.ws);
  }, [query, templates]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSel(0);
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => setSel(0), [query]);

  if (!open) return null;

  function choose(ws: Workspace) {
    onClose();
    onLaunch(ws);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, ranked.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = ranked[sel];
      if (item) choose(item);
    }
  }

  return (
    <div
      className="cmdk-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="cmdk-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Launch workspace template"
        onKeyDown={onKeyDown}
      >
        <div className="cmdk-search">
          <Icon name="search" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search workspace templates… (e.g. rollback, ingestion)"
            aria-label="Search workspace templates"
            autoComplete="off"
            spellCheck={false}
          />
          <span className="kbd">Esc</span>
        </div>
        <div className="cmdk-results" role="listbox">
          {ranked.length === 0 && <div className="cmdk-empty">No templates match “{query}”.</div>}
          <div className="cmdk-grp">
            <div className="cmdk-grp-label">Workspaces</div>
            {ranked.map((ws, idx) => (
              <button
                type="button"
                key={ws.id}
                role="option"
                aria-selected={idx === sel}
                className={cn("cmdk-item", idx === sel && "sel")}
                onMouseMove={() => setSel(idx)}
                onClick={() => choose(ws)}
              >
                <Icon name={ws.icon} />
                <span className="ci-label">{ws.title}</span>
                <span className="pi-alias">{ws.opened}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="cmdk-foot">
          <span>
            <span className="kbd">↑</span>
            <span className="kbd">↓</span> navigate
          </span>
          <span>
            <span className="kbd">↵</span> launch
          </span>
          <span>
            <span className="kbd">Esc</span> close
          </span>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────── per-card How-To popover ────────────

/** Contextual How-To for a template's TARGET section ("Section How-To" action). */
function HowToButton({ ws, onOpenFull }: { ws: Workspace; onOpenFull: () => void }) {
  const pop = usePopover();
  return (
    <div ref={pop.wrapRef} style={{ position: "relative" }}>
      <Button
        variant="btn-ghost"
        size="sm"
        icon="book"
        aria-haspopup="dialog"
        aria-expanded={pop.open}
        aria-label={`How-To for ${ws.opened}`}
        onClick={pop.toggle}
      >
        How-To
      </Button>
      {pop.open && (
        <PopoverPanel>
          <div className="pop-head">
            <span className="pt">{ws.opened} runbook</span>
            <span className="ps">help</span>
          </div>
          <div className="pop-body">
            <div className="pop-sub">Why</div>
            <p className="muted-note" style={{ margin: "0 0 8px" }}>
              {ws.desc}
            </p>
            <div className="pop-sub">Applies</div>
            <div className="pop-scopes">
              {ws.summary.map((s) => (
                <Tag key={s}>{s}</Tag>
              ))}
            </div>
          </div>
          <div className="pop-foot" style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              type="button"
              className="more-link"
              onClick={() => {
                pop.close();
                onOpenFull();
              }}
            >
              Open full How-To →
            </button>
            <span style={{ marginLeft: "auto" }}>Closes to Workspaces</span>
          </div>
        </PopoverPanel>
      )}
    </div>
  );
}

// ─────────────────────────────────────── reason-capture modal ───────────────

const MIN_REASON = 12;

/**
 * "Open section only" clears the active workspace and lands the operator on stale
 * filters — a deliberate context reset. This inline modal reuses
 * ConfirmModal's classes to capture WHY (audit trail) before the reset fires.
 */
function ResetReasonModal({
  ws,
  onCancel,
  onConfirm,
}: {
  ws: Workspace;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const ok = reason.trim().length >= MIN_REASON;

  useEffect(() => {
    taRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
      else if (e.key === "Tab") {
        const c = modalRef.current;
        if (!c) return;
        const f = c.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="ws-reset-title" ref={modalRef}>
        <div className="modal-head">
          <div className="mi" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
            <Icon name="alert" />
          </div>
          <div className="modal-title" id="ws-reset-title">
            Open {ws.opened} without a workspace
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onCancel}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <p>
            This clears the active workspace from the URL and lands you on {ws.opened} with whatever
            stale filters the last session left behind. Record why you are resetting context.
          </p>
          <div className="modal-field">
            <label htmlFor="ws-reset-reason" id="ws-reset-reason-label">
              Reason for opening without defaults
            </label>
            <textarea
              id="ws-reset-reason"
              ref={taRef}
              className="st-ta"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-labelledby="ws-reset-reason-label"
              aria-describedby="ws-reset-reason-hint"
              spellCheck={false}
            />
            <div className="confirm-hint" id="ws-reset-reason-hint">
              {ok
                ? "Reason recorded for the audit trail."
                : `Enter at least ${MIN_REASON} characters (${reason.trim().length}/${MIN_REASON}).`}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-amber"
            disabled={!ok}
            onClick={() => ok && onConfirm(reason.trim())}
          >
            Open section only
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────── section ───────────

export function WorkspacesSection() {
  const { navigate, consumeIntent } = useShell();
  const { toast } = useToast();
  const data = useAdminData();
  // LIVE dependency liveness — backs the "defaults not fully initialized" banner.
  // Session-gated like every other section, so offline the queries stay disabled.
  const health = useHealthQueries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "workspaces",
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    canConfigureAbuseGuard: data.can("write:settings"),
  });
  const [launched, setLaunched] = useState<string | null>(null);
  const [avail, setAvail] = useState<AvailFilter>("All");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [resetFor, setResetFor] = useState<Workspace | null>(null);
  /** Deep-link scope-mismatch info banner (partial results / deep-link scope mismatch). */
  const [mismatch, setMismatch] = useState<{ id: string; scope: string } | null>(null);
  /** Guards the inbound prefill handoff so it drains + applies exactly once (one-shot). */
  const intentDrained = useRef(false);

  // Display source: no backing endpoint exists, so the templates are always the
  // fixture set — it IS the offline dataset. The availability filter applies to
  // this source client-side so the segmented control visibly responds with no backend.
  const source = WORKSPACES;
  const shown = source.filter((ws) => matchesAvail(ws, avail));

  // Scope check shared by launch + deep-link resolution. Live vs fixture: when a
  // live session payload exists, its hasScope() decision (via data.can) is
  // authoritative — a live deny disables Launch / strips deep links. The
  // GRANTED_SCOPES fixture applies ONLY offline (no session payload), keeping the
  // fixture grid fully interactive with no backend.
  const allows = (scope: string) =>
    scope === "" || (data.session ? data.can(scope) : GRANTED_SCOPES.has(scope));

  // Live-session signals → section states. `sessionIsSuccess` true but no session payload =
  // the key was accepted then revoked mid-session (session expired / API key revoked).
  const sessionExpired = data.sessionIsSuccess && !data.session;
  // While the session resolves, the product/repo defaults that back the templates are
  // still loading (loading state). Gate on the DISPLAY set so fixtures never hide.
  const loadingDefaults = data.sessionIsLoading && !shown.length;
  // LIVE degraded-defaults signal: the Health query (Qdrant / PostgreSQL / OpenSearch
  // liveness) is the real owner. A REQUIRED dependency that is not "ready" means the
  // backing service that populates product/repo defaults is down → drive the
  // "defaults not fully initialized" banner from that. `degradedDependencyRows` already
  // filters to `status !== "ready"`; narrow to required deps so optional services don't
  // trip the banner. OFFLINE: the health query is session-gated (disabled with
  // no backend) → `dependencyRows` is empty → no live rows, so fall back to the fixture
  // flag (default off) and the section still renders cleanly.
  const requiredDependencyNotReady = health.degradedDependencyRows.some(
    ([, item]) => item.required,
  );
  const degraded = health.dependencyRows.length ? requiredDependencyNotReady : DEGRADED_DEFAULTS;

  const roleLabel = data.session?.is_superuser
    ? "superuser"
    : (data.session?.effective_role ?? "superuser");
  const defaultScope = data.session?.product_scopes?.[0] ?? "aspose.ocr";

  function applyDeepLink(ws: Workspace, persist: boolean) {
    setLaunched(ws.id);
    setMismatch(null);
    if (persist) writeWorkspaceParam(ws.id);
    // Cross-section prefill handoff so Launch applies downstream defaults:
    // hand the target section its scope defaults so it lands pre-filtered instead of on
    // stale state. The shell stashes the intent BEFORE switching and the target drains it
    // once via consumeIntent; `reset: true` asks it to clear prior state first. Anchor is
    // routed through navigate() too (it owns the deferred scroll/focus) — keeping the
    // deep-link + anchor behavior.
    const intent = ws.prefill ? { filters: ws.prefill, reset: true } : undefined;
    navigate(ws.nav, ws.anchor, intent);
    // Belt-and-braces focus fallback: navigate() already defers scroll/focus, but a
    // template launched into a section with NO consumer of this intent (or a panel that
    // lands a frame late offline) still gets its anchor focused here. Idempotent with
    // navigate()'s own focus, and keeps fixtures working with no backend.
    if (typeof window !== "undefined") {
      window.setTimeout(() => {
        const el = document.getElementById(ws.anchor);
        if (el) {
          el.scrollIntoView({ block: "start" });
          if (el instanceof HTMLElement) {
            el.setAttribute("tabindex", "-1");
            el.focus({ preventScroll: true });
          }
        }
      }, 0);
    }
  }

  function launch(ws: Workspace) {
    // Chokepoint guard: the card button is already disabled on a scope deny, but the
    // command palette lists every template — a live deny must not launch from there
    // either. Surface the same scope-mismatch banner instead of silently navigating.
    const scope = ws.meta[1];
    if (!allows(scope)) {
      setMismatch({ id: ws.id, scope });
      return;
    }
    applyDeepLink(ws, true);
    toast(`Workspace ready: ${ws.title}. Opened ${ws.opened} with safe defaults.`, () => {
      setLaunched(null);
      writeWorkspaceParam(null);
    });
  }

  function openSectionOnly(ws: Workspace, reason: string) {
    setResetFor(null);
    setLaunched(null);
    writeWorkspaceParam(null);
    navigate(ws.nav);
    toast(`Opened ${ws.opened} without a workspace · reason logged: “${reason.slice(0, 40)}”.`);
  }

  // On mount / when the session resolves: restore the active workspace from the URL,
  // or strip a scope-mismatched deep link and surface the info alert (deep-link
  // resilience). Offline `allows()` is permissive, so shared links resolve on fixtures.
  useEffect(() => {
    const param = readWorkspaceParam();
    if (!param) return;
    const ws = WORKSPACES.find((w) => w.id === param);
    if (!ws) {
      writeWorkspaceParam(null);
      return;
    }
    const scope = ws.meta[1];
    if (!allows(scope)) {
      // The effect re-runs once the live session resolves; a permissive pass while
      // the session was still loading may already have activated the workspace —
      // a live deny strips the param AND the active state, then explains why.
      writeWorkspaceParam(null);
      setLaunched(null);
      setMismatch({ id: ws.id, scope });
      return;
    }
    setLaunched(ws.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.sessionIsSuccess, data.session]);

  // Inbound cross-section prefill handoff: if another section navigated HERE with an
  // intent (navigate("workspaces", anchor?, { filters, reset })), drain it once and apply
  // recognized filters through this section's own setter (availability). consumeIntent is
  // already one-shot at the shell, but the ref also guards StrictMode's double mount so the
  // prefill can never apply twice. Unknown filter keys are ignored gracefully; `reset` falls
  // back to the "All" default before applying so the operator lands on a clean, predictable
  // filter. No backend needed — purely client state, so fixtures stay fully interactive.
  useEffect(() => {
    if (intentDrained.current) return;
    intentDrained.current = true;
    const intent = consumeIntent("workspaces");
    if (!intent) return;
    const next = availFromIntentFilters(intent.filters);
    if (next) setAvail(next);
    else if (intent.reset) setAvail("All");
  }, [consumeIntent]);

  // NOTE: no window-level ⌘/Ctrl+K listener here. The shell (shell/Shell.tsx) owns
  // that hotkey for the GLOBAL CommandPalette — which already exposes workspace
  // launch commands — and a second listener would stack two .cmdk-overlay layers on
  // one keypress. The in-section template palette opens via its buttons only
  // ("Launch via ⌘K" in the page head + "Command palette" on the card).

  function openHelp() {
    window.location.href = "/howto";
  }

  // Session revoked mid-session → replace the whole section with a recovery alert
  // (do NOT silently render disabled cards).
  if (sessionExpired) {
    return (
      <>
        <PageHead
          title="Workspaces"
          sub="Operational launchpad — preloaded scenarios open the right section with safe defaults so you don’t rebuild context by hand."
          onHelp={openHelp}
          actions={<StaleBadge>session ended</StaleBadge>}
        />
        <Card title="Session no longer valid">
          <ErrorState
            title="Your session is invalid"
            text="The admin key for this session was revoked or expired. Workspace templates are hidden until you re-authenticate."
            cause="API key revoked or session expired mid-session"
            actions={
              <Button
                variant="btn-primary"
                size="sm"
                icon="refresh"
                onClick={() => window.location.reload()}
              >
                Reload to re-authenticate
              </Button>
            }
          />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="Workspaces"
        sub="Operational launchpad — preloaded scenarios open the right section with safe defaults so you don’t rebuild context by hand."
        onHelp={openHelp}
        actions={
          <>
            <ScopeChip label="role" value={roleLabel} dot />
            <ScopeChip label="default scope" value={defaultScope} />
            <Button
              variant="btn-ghost"
              size="sm"
              icon="search"
              onClick={() => setPaletteOpen(true)}
            >
              Launch via ⌘K
            </Button>
          </>
        }
      />

      {degraded && (
        <Banner
          variant="warn"
          icon="alert"
          title="Workspace defaults not fully initialized"
          text="A backing service (Qdrant / PostgreSQL / OpenSearch) is unavailable, so product and repo defaults could not be populated. Templates still launch, but you may need to select a product or repository manually."
          actions={
            <Button variant="btn-ghost" size="sm" icon="pulse" onClick={() => navigate("health")}>
              Open Health
            </Button>
          }
        />
      )}

      {mismatch && (
        <Banner
          variant="info"
          icon="info"
          title={`Workspace unavailable: requires ${mismatch.scope}`}
          text={`The shared deep link (?workspace=${mismatch.id}) was not applied because your key lacks the required scope. You stayed on the current section without the workspace context — a safe fallback. Request ${mismatch.scope} from an administrator to use this template.`}
        />
      )}

      <KpiRow cols={4}>
        <Kpi label="Uptime" value="online" foot="service status = ok" />
        <Kpi
          label="Readiness"
          value={
            <>
              4<small>/4</small>
            </>
          }
          foot="dependencies ready"
        />
        <Kpi
          label="Open incidents"
          value="1"
          foot="critical events"
          accent
          pill={{ variant: "crit", text: "sev1" }}
        />
        <Kpi label="Coverage gaps" value="2" foot="critical triage" />
      </KpiRow>

      <Card
        title="Workspace templates"
        sub={`Showing ${shown.length} of ${source.length} quick-launch workspaces · safe defaults for the current role and product scope. Launch jumps to the section with context applied and pins it in the URL.`}
        right={
          <Button variant="btn-ghost" size="sm" icon="search" onClick={() => setPaletteOpen(true)}>
            Command palette
          </Button>
        }
      >
        <div className="toolbar">
          <Segmented
            options={[...AVAIL_FILTERS]}
            active={AVAIL_FILTERS.indexOf(avail)}
            onChange={(i) => setAvail(AVAIL_FILTERS[i])}
            ariaLabel="Filter workspaces by required access"
          />
          {launched && (
            <span className="muted-note toolbar-right">
              Active workspace pinned to <Tag>?workspace={launched}</Tag>
            </span>
          )}
        </div>

        {loadingDefaults ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={4} />
            <div className="muted-note" style={{ marginTop: 10, textAlign: "center" }}>
              Loading workspace defaults…
            </div>
          </div>
        ) : !shown.length ? (
          <div className="empty">
            <div className="empty-orb" />
            <div className="empty-title">No workspaces available</div>
            <div className="empty-text">
              No workspace templates match your current role and product scope. Contact an
              administrator to request access to operational workspaces.
            </div>
          </div>
        ) : (
          <div className="ws-grid">
            {shown.map((ws) => {
              const [section, scope] = ws.meta;
              const allowed = allows(scope);
              const active = launched === ws.id;
              return (
                <div
                  className="ws-card"
                  key={ws.id}
                  aria-current={active ? "true" : undefined}
                  aria-label={`${ws.title}. ${ws.desc}`}
                  style={
                    active ? { boxShadow: "inset 2px 0 0 var(--accent-line), var(--shadow-sm)" } : undefined
                  }
                >
                  <div className="ws-top">
                    <div className="ws-ico">
                      <Icon name={ws.icon} />
                    </div>
                    <div className="ws-title">{ws.title}</div>
                    {active && <Pill variant="ok">active</Pill>}
                  </div>
                  <div className="ws-desc">{ws.desc}</div>

                  <div className="ws-prefill">
                    <Icon name="check" className="ico" />
                    <span>Preloads: {section} scope · safe defaults</span>
                  </div>
                  {/* Summary line items — parallel
                      scope facts, not ordered steps, so render as stacked muted
                      lines rather than the numbered fix-steps affordance. */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, margin: "10px 0 0" }}>
                    {ws.summary.map((s) => (
                      <div className="muted-note" key={s}>
                        {s}
                      </div>
                    ))}
                  </div>

                  {/* Recommended roles */}
                  <div className="muted-note" style={{ margin: "11px 0 0" }}>
                    Recommended roles: {ws.roles.join(", ")}
                  </div>

                  {/* Quick-action keyword tags */}
                  <div className="ws-meta">
                    <Pill variant="neutral">{section}</Pill>
                    {scope ? <Tag>{scope}</Tag> : <Pill variant="ok">read-safe</Pill>}
                    {ws.tags.map((t) => (
                      <Tag key={t}>{t}</Tag>
                    ))}
                  </div>

                  {!allowed && (
                    <div className="muted-note" style={{ margin: "8px 0 0" }}>
                      Requires scope: <Tag>{scope}</Tag> — this workspace stays visible so operators
                      know which role or delegated key is required.
                    </div>
                  )}

                  <div className="ws-foot">
                    <Button
                      variant="btn-primary"
                      size="sm"
                      icon="arrow"
                      disabled={!allowed}
                      title={allowed ? undefined : `Unavailable — requires ${scope}`}
                      aria-label={`Launch ${ws.title}`}
                      aria-disabled={!allowed}
                      onClick={() => launch(ws)}
                    >
                      Launch
                    </Button>
                    <HowToButton ws={ws} onOpenFull={openHelp} />
                    <button
                      type="button"
                      className="more-link"
                      title={`Copy deep link to ${ws.title}`}
                      onClick={() => {
                        const url = new URL(window.location.href);
                        url.searchParams.set("workspace", ws.id);
                        const link = url.toString();
                        if (navigator.clipboard?.writeText) {
                          void navigator.clipboard.writeText(link);
                        }
                        toast(`Deep link copied · ?workspace=${ws.id}`);
                      }}
                    >
                      Copy link
                    </button>
                    <button
                      type="button"
                      className="more-link"
                      style={{ marginLeft: "auto" }}
                      onClick={() => setResetFor(ws)}
                    >
                      Open section only →
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <WorkspacePalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        templates={shown}
        onLaunch={launch}
      />

      {resetFor && (
        <ResetReasonModal
          ws={resetFor}
          onCancel={() => setResetFor(null)}
          onConfirm={(reason) => openSectionOnly(resetFor, reason)}
        />
      )}
    </>
  );
}
