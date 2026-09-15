"use client";

import { useEffect, useState, type ReactNode } from "react";

import { materializeDrilldownTemplate } from "@/components/admin-console.utils";
import { useHealthQueries } from "@/hooks/useHealthQueries";

import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { IconButton } from "../components/IconButton";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import {
  EmptyState,
  ReadonlyBanner,
  Skeleton,
  StaleBadge,
} from "../components/states";
import { Tag } from "../components/Tag";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";
import { useConfirm } from "../shell/overlays";
import { PopoverPanel, usePopover } from "../shell/Popover";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";

/* ---------- fixtures ---------- */

interface SessionRow {
  rev: string;
  count: string;
  variant: StatusVariant;
}
const SESSIONS: SessionRow[] = [
  { rev: "v0.3", count: "29 540", variant: "info" },
  { rev: "v0.2", count: "13 110", variant: "neutral" },
  { rev: "v0.1", count: "2 365", variant: "warn" },
];

const REASONS: [reason: string, count: string][] = [
  ["version_mismatch", "128"],
  ["negotiation_timeout", "41"],
  ["protocol_error", "22"],
  ["network_issue", "12"],
];

interface DecisionRow {
  decision: string;
  count: string;
  variant: StatusVariant;
}
// Decisions are reported per guard mode by the live summary
// (`abuse_guard_decisions_by_mode`); the breakdown shows BOTH modes' groups at
// once (grouped by observe-only and enforce modes), independent of the
// unapplied Guard-mode select. The fixtures mirror that shape for offline parity.
const DECISIONS_BY_MODE: Record<"observe-only" | "enforce", DecisionRow[]> = {
  "observe-only": [
    { decision: "ALLOW", count: "44 980", variant: "ok" },
    { decision: "RATE_LIMIT", count: "198", variant: "warn" },
    { decision: "FINGERPRINT_ATTACK", count: "34", variant: "crit" },
    { decision: "BLOCK", count: "6", variant: "crit" },
  ],
  enforce: [
    { decision: "ALLOW", count: "44 742", variant: "ok" },
    { decision: "RATE_LIMIT", count: "402", variant: "warn" },
    { decision: "FINGERPRINT_ATTACK", count: "58", variant: "crit" },
    { decision: "BLOCK", count: "16", variant: "crit" },
  ],
};

interface AlertRow {
  variant: StatusVariant;
  pillText: string;
  name: string;
  desc: string;
  meta: string;
}
const ALERTS: AlertRow[] = [
  {
    variant: "crit",
    pillText: "critical",
    name: "api-latency-p95-breach",
    desc: "API p95 latency above SLO for query_docs window.",
    meta: "window 10m · p95 > 1200ms",
  },
  {
    variant: "crit",
    pillText: "critical",
    name: "api-5xx-spike",
    desc: "HTTP 5xx ratio exceeded production error budget.",
    meta: "window 10m · 5xx > 1%",
  },
  {
    variant: "info",
    pillText: "info",
    name: "ingestion-publish-failure",
    desc: "One or more publish runs failed or remained blocked.",
    meta: "window 15m · failed > 0",
  },
  {
    variant: "info",
    pillText: "info",
    name: "zero-result-spike",
    desc: "Zero-result ratio exceeded expected operating band.",
    meta: "window 15m · zero_ratio > 20%",
  },
  {
    variant: "warn",
    pillText: "warn",
    name: "stale-index-freshness",
    desc: "Latest published snapshot freshness lag above target.",
    meta: "window 30m · lag > 30m",
  },
];

const SMOKE_CHECKS = ["/healthz", "/readyz", "/v1/status"];

// API limitation (offline only): the read-only abuse-guard settings summary + audit
// metadata come from `obs.abuse_guard_settings` live; offline that summary is
// absent, so this fixture supplies the current limits / allowlist size / last-
// modified provenance the "Rate-Limit Thresholds" + "Auditing config
// changes" rows require. It mirrors the hook's default form state (120/180/5000).
interface GuardSettingsSummary {
  ipPerMin: number;
  fingerprintPerMin: number;
  globalPerMin: number;
  allowlistSize: number;
  debugHeaderEnabled: boolean;
  updatedBy: string;
  updatedAt: string;
}
const GUARD_SETTINGS_FALLBACK: GuardSettingsSummary = {
  ipPerMin: 120,
  fingerprintPerMin: 180,
  globalPerMin: 5000,
  allowlistSize: 4,
  debugHeaderEnabled: true,
  updatedBy: "su@local",
  updatedAt: "2026-06-05T09:12:00Z",
};

/* bar-width helpers */
function sessionWidth(count: string): number {
  return Math.round(Number(count.replace(/\s/g, "")) / 295);
}
function decisionWidth(count: string): number {
  return Math.max(Math.round(Number(count.replace(/\s/g, "")) / 450), 2);
}

/* Live-data formatting: integers → the spaced-thousands strings the width helpers + bars expect. */
function fmtCount(n: number): string {
  return n.toLocaleString("en-US").replace(/,/g, " ");
}
/* Map a live abuse-guard decision name to a bar/pill variant. */
function decisionVariant(decision: string): StatusVariant {
  const d = decision.toUpperCase();
  if (d === "ALLOW") return "ok";
  if (d === "RATE_LIMIT") return "warn";
  if (d === "BLOCK" || d === "FINGERPRINT_ATTACK") return "crit";
  return "neutral";
}
/* Map a live smoke/canary/status string to a pill variant (ok / warn / crit). */
function statusVariant(status: string): StatusVariant {
  const s = status.toLowerCase();
  if (s === "pass" || s === "ok" || s === "promoted" || s === "passed" || s === "healthy") return "ok";
  if (s === "warn" || s === "warning" || s === "degraded") return "warn";
  if (s === "fail" || s === "failed" || s === "error" || s === "rolled_back" || s === "critical")
    return "crit";
  return "neutral";
}
/* Map an alert-rule severity to a pill variant + label. */
function severityVariant(severity: string): StatusVariant {
  const s = severity.toLowerCase();
  if (s === "critical" || s === "crit") return "crit";
  if (s === "warning" || s === "warn") return "warn";
  return "info";
}

/* Best-effort relative "N ago" rendering for an ISO timestamp (audit freshness).
   Returns "—" for an unparseable value so the audit row never shows raw garbage. */
function timeAgo(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}
/* Stale once the observability summary is older than its 60s refetch budget. */
function isStale(iso: string): boolean {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  return Date.now() - t > 120_000;
}

/* ---------- inline help popover (Why / What / How) ---------- */
/* Reuses the system `.pop*` classes exactly as PopoverPanel does; usePopover
   gives Escape-to-close + outside-click WITHOUT trapping focus (the help affordance
   is non-modal). */
function HelpPopover() {
  const pop = usePopover();
  return (
    <div ref={pop.wrapRef} style={{ position: "relative" }}>
      <IconButton
        icon="book"
        onClick={pop.toggle}
        aria-haspopup="dialog"
        aria-expanded={pop.open}
        title="How-To for this section"
        aria-label="Open How-To for this section"
      />
      {pop.open && (
        <PopoverPanel
          className="help-pop"
          // The panel is a non-modal help dialog; mark it as such for AT but do
          // NOT trap focus (usePopover only wires Esc + outside-click).
        >
          <div className="pop-head" role="dialog" aria-label="Runtime Guard & MCP help">
            <Icon name="book" className="ico" />
            <span className="pt">Runtime Guard &amp; MCP</span>
            <button type="button" className="ps" onClick={pop.close} aria-label="Close help">
              Esc
            </button>
          </div>
          <div className="pop-body" style={{ maxWidth: 320 }}>
            <div className="pop-sub">Why</div>
            <div className="muted-note" style={{ lineHeight: 1.55 }}>
              MCP clients negotiate a protocol revision; a fallback means a client downgraded to an
              older revision, which can degrade answer quality. The abuse guard caps request volume
              per IP, per fingerprint, and platform-wide to protect live traffic.
            </div>
            <div className="pop-sub" style={{ marginTop: 10 }}>
              What
            </div>
            <div className="muted-note" style={{ lineHeight: 1.55 }}>
              This screen surfaces negotiation health (fallback ratio, session mix, fallback
              reasons) and lets a superuser tune rate-limit thresholds and switch between
              observe-only and enforce modes for the public API.
            </div>
            <div className="pop-sub" style={{ marginTop: 10 }}>
              How
            </div>
            <ol className="fix-steps" style={{ marginTop: 4 }}>
              <li>
                <span>Scan the fallback ratio (green &lt; 0.5%) and the decisions breakdown.</span>
              </li>
              <li>
                <span>Adjust IP / fingerprint / global limits and the allowlist as needed.</span>
              </li>
              <li>
                <span>Apply in observe-only first, then switch to enforce once confident.</span>
              </li>
            </ol>
          </div>
          {/* How-To Knowledge Center link — every console help (book) icon links here,
              matching sibling Mono sections' "Open full How-To" affordance. */}
          <div className="pop-foot">
            <a href="/howto" className="btn btn-ghost btn-sm" style={{ textDecoration: "none" }}>
              <Icon name="arrow" className="ico" />
              Open full How-To
            </a>
          </div>
        </PopoverPanel>
      )}
    </div>
  );
}

/* ---------- inline role=alert notice (mutation success / error) ---------- */
/* The system's role=alert primitive is `.recovery`. Crit (error) uses it as-is;
   the success tone overrides border/bg with the --ok token the same way
   `.recovery.warn` overrides with --warn — token-only, no new colors. */
function InlineNotice({
  tone,
  title,
  text,
  actions,
}: {
  tone: "ok" | "crit";
  title: string;
  text: ReactNode;
  actions?: ReactNode;
}) {
  const okStyle =
    tone === "ok"
      ? {
          borderColor: "color-mix(in srgb, var(--ok) 28%, var(--border))",
          background: "var(--ok-bg)",
        }
      : undefined;
  const icoStyle =
    tone === "ok"
      ? {
          background: "color-mix(in srgb, var(--ok) 14%, transparent)",
          color: "var(--ok)",
        }
      : undefined;
  return (
    <div className="recovery" role="alert" style={{ ...okStyle, marginTop: 12 }}>
      <div className="rec-ico" style={icoStyle}>
        <Icon name={tone === "ok" ? "check" : "alert"} />
      </div>
      <div className="rec-body">
        <div className="rec-title">{title}</div>
        <div className="rec-text">{text}</div>
        {actions && <div className="rec-actions">{actions}</div>}
      </div>
    </div>
  );
}

/* ---------- section ---------- */

export function RuntimeSection() {
  const { navigate } = useShell();
  const { confirm } = useConfirm();
  const data = useAdminData();
  const health = useHealthQueries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    // The hook's `SidebarSectionId` arg uses the hook's own section ids; this Mono section's
    // equivalent is "runtime-guard". observabilityQuery runs on its fixed 60s interval
    // (unconditional in the hook); abuseGuardSettingsQuery's interval is gated on the
    // "health" id, so here it does NOT auto-refetch — it re-syncs on invalidation after our
    // own mutations (read-only telemetry around it stays live via observabilityQuery).
    activeSectionId: "runtime-guard",
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    canConfigureAbuseGuard: data.can("write:settings"),
  });

  // Observability summary drives MCP telemetry, decisions, alerts, tracing, deploy safety.
  const obs = health.observability;

  // Abuse-guard form state is owned by the hook; drive the section's controls from it.
  const guardMode = health.abuseGuardMode;
  const setGuardMode = health.setAbuseGuardMode;
  const enforce = guardMode === "enforce";
  // The mode currently APPLIED on the server (settings query is the synced truth;
  // observability is the read-only fallback; offline the fixture default is
  // observe-only). The enforce confirm fires only on a CHANGE to enforce from this
  // baseline — not when re-applying thresholds while already in enforce.
  const appliedMode =
    health.abuseGuardSettingsQuery.data?.mode ?? obs?.abuse_guard_settings.mode ?? "observe-only";
  const switchingToEnforce = enforce && appliedMode !== "enforce";

  // Superuser-gated mutations (abuse guard is restricted to superuser keys
  // only — broader write:settings scope is NOT sufficient). Permissive until a real
  // session loads so fixtures-mode renders the enabled form (matches data.can()'s
  // load-time semantics); once a session exists, only is_superuser unlocks the form.
  const canEdit = data.session ? data.session.is_superuser : true;

  // Local mutation-feedback latch: an INLINE success/error alert renders
  // below Apply (not only the confirm dialog's toast). We set this when we fire a
  // mutation and read the mutation's isSuccess/isError to render the right notice.
  const [applied, setApplied] = useState(false);
  const mutation = health.patchAbuseGuardSettingsMutation;
  const mutationError =
    mutation.error instanceof Error ? mutation.error.message : "The backend rejected the change.";

  // The success notice displays for 3–5 seconds: auto-dismiss the inline
  // ok-tone alert ~4s after a successful apply by dropping the latch (the error notice
  // is intentionally NOT auto-dismissed — it stays for retry).
  const mutationSucceeded = mutation.isSuccess;
  useEffect(() => {
    if (!applied || !mutationSucceeded) return;
    const t = setTimeout(() => setApplied(false), 4000);
    return () => clearTimeout(t);
  }, [applied, mutationSucceeded]);

  // --- Live → fixture fallback for the MCP session breakdown ---
  const liveSessions: SessionRow[] = Object.entries(obs?.mcp_sessions_by_revision ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([rev, n], i) => ({
      rev,
      count: fmtCount(n),
      variant: (["info", "neutral", "warn"] as StatusVariant[])[i] ?? "neutral",
    }));
  const sessions: SessionRow[] = liveSessions.length ? liveSessions : SESSIONS;

  const liveReasons: [string, string][] = Object.entries(obs?.mcp_fallback_by_reason ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([reason, n]) => [reason, fmtCount(n)]);
  const reasons: [string, string][] = liveReasons.length ? liveReasons : REASONS;

  // --- Live → fixture fallback for the abuse-guard decisions breakdown ---
  // Both modes' groups are shown at once (grouped by observe-only and
  // enforce modes) so reviewing observe-only false-positive rates is never lost by
  // pre-selecting enforce in the (unapplied) Guard-mode control. Each present mode
  // becomes a labelled group of rows, ordered observe-only then enforce.
  function toDecisionRows(byDecision: Record<string, number>): DecisionRow[] {
    return Object.entries(byDecision)
      .sort((a, b) => b[1] - a[1])
      .map(([decision, n]) => ({
        decision: decision.toUpperCase(),
        count: fmtCount(n),
        variant: decisionVariant(decision),
      }));
  }
  const MODE_ORDER: ("observe-only" | "enforce")[] = ["observe-only", "enforce"];
  const liveDecisionGroups: { mode: string; rows: DecisionRow[] }[] = obs
    ? Object.entries(obs.abuse_guard_decisions_by_mode ?? {})
        .map(([mode, byDecision]) => ({ mode, rows: toDecisionRows(byDecision) }))
        .filter((g) => g.rows.length)
        .sort((a, b) => {
          const ai = MODE_ORDER.indexOf(a.mode as "observe-only" | "enforce");
          const bi = MODE_ORDER.indexOf(b.mode as "observe-only" | "enforce");
          return (ai < 0 ? MODE_ORDER.length : ai) - (bi < 0 ? MODE_ORDER.length : bi);
        })
    : MODE_ORDER.map((mode) => ({ mode, rows: DECISIONS_BY_MODE[mode] }));

  // --- Live → fixture fallback for the alert pack ---
  const liveAlerts: AlertRow[] = (obs?.alert_rules ?? []).map((rule) => {
    const v = severityVariant(rule.severity);
    return {
      variant: v,
      pillText: v === "crit" ? "critical" : v,
      name: rule.rule_id,
      desc: rule.description,
      meta: `window ${rule.window_minutes}m · ${rule.threshold}`,
    };
  });
  const alerts: AlertRow[] = liveAlerts.length ? liveAlerts : ALERTS;

  // --- Live → fixture fallback for deploy-safety smoke checks ---
  // ONLINE with an empty live checks array → the single fallback row
  // ("not-run" / "unknown" + "No deploy smoke report is available yet."), never
  // the fabricated fixture pass rows. Fixtures render OFFLINE only (no `obs`).
  const liveSmoke = obs?.latest_deploy_smoke?.checks ?? [];
  const smokeChecks: { id: string; status: string; meta: string }[] = obs
    ? liveSmoke.length
      ? // Carry the live check.detail into the row meta (Detail column, e.g.
        // "Database connectivity verified in 250ms") instead of echoing the status,
        // which already shows in the row pill. Fall back to status only if detail is empty.
        liveSmoke.map((c) => ({
          id: c.check_id,
          status: c.status,
          meta: c.detail || `status=${c.status}`,
        }))
      : [{ id: "not-run", status: "unknown", meta: "No deploy smoke report is available yet." }]
    : SMOKE_CHECKS.map((p) => ({ id: p, status: "pass", meta: "status=200" }));

  // --- Live → fixture fallback for the read-only settings summary + audit meta ---
  // ("Rate-Limit Thresholds" read-only view + "Auditing configuration changes").
  const settingsSummary: GuardSettingsSummary = obs?.abuse_guard_settings
    ? {
        ipPerMin: obs.abuse_guard_settings.requests_per_ip_per_minute,
        fingerprintPerMin: obs.abuse_guard_settings.requests_per_fingerprint_per_minute,
        globalPerMin: obs.abuse_guard_settings.requests_global_per_minute,
        allowlistSize: obs.abuse_guard_settings.allowlist_size,
        debugHeaderEnabled: obs.abuse_guard_settings.debug_header_enabled,
        updatedBy: obs.abuse_guard_settings.updated_by,
        updatedAt: obs.abuse_guard_settings.updated_at,
      }
    : GUARD_SETTINGS_FALLBACK;

  // --- Drilldown deep-links: materialize {request_id}/{trace_id} placeholders ---
  // The summary exposes one sample correlation id (`request_id`), which is
  // substituted for both placeholders. Without a sample id (or a
  // template) the deep link cannot be materialized → button disabled + tooltip.
  const sampleRequestId = obs?.request_id ?? null;
  const lokiUrl =
    obs && sampleRequestId
      ? materializeDrilldownTemplate(obs.drilldown_links.loki_logs_url_template, {
          request_id: sampleRequestId,
          trace_id: sampleRequestId,
        })
      : null;
  const tempoUrl =
    obs && sampleRequestId
      ? materializeDrilldownTemplate(obs.drilldown_links.tempo_trace_url_template, {
          request_id: sampleRequestId,
          trace_id: sampleRequestId,
        })
      : null;

  // State gates (live vs fixture): OFFLINE the queries are disabled —
  // `isLoading`/`isError` stay false — so the fixtures render fully interactive.
  // ONLINE the loading / error states are reachable: initial fetch → skeletons
  // (3 + 2 rows), failure with no data → ObservabilityError with
  // retry ("all chips hidden until retry succeeds"), success → live data only.
  const obsLoading = health.observabilityQuery.isLoading;
  const obsError = health.observabilityQuery.isError && !obs;
  // While the live summary is loading or failed, observability-driven chips and
  // cards are withheld instead of impersonating fixture telemetry.
  const obsUnavailable = obsLoading || obsError;
  // Guard-card skeleton: observability load (2 rows) or the settings fetch.
  const guardLoading = obsLoading || health.abuseGuardSettingsQuery.isLoading;
  // A settings error hides the form until a retry succeeds;
  // offline the query is disabled (never erroring) so the form always renders.
  const settingsError =
    health.abuseGuardSettingsQuery.isError && !health.abuseGuardSettingsQuery.data;
  // Per-card empty placeholders: the three "…recorded yet / configured"
  // online empty states fire only when the LIVE summary is present but the sub-array
  // is genuinely empty. Offline (no `obs`) the fixtures populate every set, so the
  // placeholder never hides a fixture. This makes the
  // empty copy reachable for a real empty live sub-array without breaking offline.
  const noFallbackReasons = !!obs && !liveReasons.length;
  const noDecisions = !!obs && !liveDecisionGroups.length;
  const noAlerts = !!obs && !liveAlerts.length;

  // KPI values: live MCP negotiation telemetry; fixture copy renders OFFLINE only.
  // While the live summary is loading/unavailable the numbers are withheld ("—")
  // instead of presenting fixture telemetry as real.
  const negotiations = obs
    ? fmtCount(obs.mcp_negotiation_total)
    : obsUnavailable
      ? "—"
      : "45 218";
  const fallbacks = obs
    ? fmtCount(obs.mcp_negotiation_fallback_total)
    : obsUnavailable
      ? "—"
      : "203";
  const failRatioPct = obs
    ? (obs.mcp_negotiation_fail_ratio * 100).toFixed(2)
    : obsUnavailable
      ? null
      : "0.45";
  // Threshold recolor: green under 0.5%, orange at or above. The KPI keeps
  // its accent left-bar below target and gains a warn status pill once the live ratio
  // reaches 0.5%, so the cue is conveyed by more than the static foot text.
  const failRatioWarn =
    failRatioPct !== null && Number.parseFloat(failRatioPct) >= 0.5;
  // Freshness: live `generated_at` drives the stale badge + relative readout;
  // offline we show the fixture summary's modified time so the affordance still renders.
  const generatedAt = obs?.generated_at ?? GUARD_SETTINGS_FALLBACK.updatedAt;
  const staleData = obs ? isStale(obs.generated_at) : false;

  // Build the abuse-guard PATCH payload from the hook's form inputs.
  function buildPayload(mode: "observe-only" | "enforce") {
    return {
      mode,
      allowlist: health.abuseGuardAllowlistInput
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      requests_per_ip_per_minute: Number.parseInt(health.abuseGuardIpLimitInput, 10),
      requests_per_fingerprint_per_minute: Number.parseInt(
        health.abuseGuardFingerprintLimitInput,
        10,
      ),
      requests_global_per_minute: Number.parseInt(health.abuseGuardGlobalLimitInput, 10),
      debug_header_enabled: health.abuseGuardDebugHeaderEnabled,
    };
  }

  // Validation failure (numeric thresholds): positive-integer guard BEFORE
  // any mutate. Mirrors the hook's applyAbuseGuardSettings() validation, which a
  // direct mutate() call would otherwise bypass.
  function thresholdsValid(): boolean {
    const ip = Number.parseInt(health.abuseGuardIpLimitInput, 10);
    const fp = Number.parseInt(health.abuseGuardFingerprintLimitInput, 10);
    const gl = Number.parseInt(health.abuseGuardGlobalLimitInput, 10);
    return (
      Number.isInteger(ip) &&
      Number.isInteger(fp) &&
      Number.isInteger(gl) &&
      ip >= 1 &&
      fp >= 1 &&
      gl >= 1
    );
  }

  // Fire the PATCH for the current form mode and arm the inline-feedback latch.
  function commitSettings() {
    setApplied(true);
    mutation.mutate(buildPayload(guardMode));
  }

  function applySettings() {
    // Mutations are superuser-gated; the Apply button is disabled too — defense in depth.
    if (!canEdit) return;
    // Reset the inline-feedback latch so a previous success/error alert clears
    // when a new attempt starts.
    setApplied(false);
    if (!thresholdsValid()) {
      // Validation failure: a BLOCKING alert dialog titled "Validation Error"
      // (the Mono showAlert bridge maps to a transient toast and drops the title, so we
      // surface it directly through the focus-trapped confirm modal — acknowledge only).
      confirm({
        title: "Validation Error",
        summary: "Abuse guard thresholds must be positive integers.",
        tone: "amber",
        confirmLabel: "OK",
        icon: "alert",
        onConfirm: () => {},
      });
      return;
    }
    // Confirm is required ONLY when changing the live mode to enforce; observe-only
    // applies and re-applying thresholds while already in enforce commit straight through.
    if (switchingToEnforce) {
      confirm({
        title: "Enable ENFORCE mode for public API abuse guard now?",
        summary: (
          <>
            Enforce actively rejects requests exceeding the configured limits for <b>all clients</b>{" "}
            instantly. Thresholds and allowlist below apply on confirm.
          </>
        ),
        tone: "amber",
        confirmLabel: "Enable enforce",
        icon: "shield",
        onConfirm: commitSettings,
      });
      return;
    }
    commitSettings();
  }

  return (
    <>
      <PageHead
        title="Runtime Guard & MCP"
        sub="MCP protocol-negotiation telemetry and abuse-guard runtime policy for live traffic."
        actions={
          <>
            <ScopeChip label="scope" value={data.session?.is_superuser ? "superuser" : "operator"} dot />
            {staleData && <StaleBadge>stale</StaleBadge>}
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              disabled={health.observabilityQuery.isFetching}
              onClick={() => health.observabilityQuery.refetch()}
            >
              Refresh now
            </Button>
            <HelpPopover />
          </>
        }
      />

      <KpiRow cols={3}>
        <Kpi
          label="MCP fallback ratio"
          value={
            failRatioPct === null ? (
              "—"
            ) : (
              <>
                {failRatioPct}
                <small>%</small>
              </>
            )
          }
          foot={failRatioWarn ? "≥ 0.5% — above target" : "< 0.5% target"}
          accent={!failRatioWarn}
          pill={failRatioWarn ? { variant: "warn", text: "elevated" } : undefined}
        />
        <Kpi label="Negotiations" value={negotiations} foot="current window" />
        <Kpi label="Fallbacks" value={fallbacks} foot="protocol downgrades" />
      </KpiRow>

      <Card
        title="MCP session breakdown"
        sub="Active sessions per negotiated protocol revision · skew toward old revisions after an upgrade signals outdated clients."
      >
        {obsLoading ? (
          <Skeleton rows={3} />
        ) : obsError ? (
          <ObservabilityError navigate={navigate} onRefresh={() => health.observabilityQuery.refetch()} />
        ) : (
          <div className="chart-grid">
            <div>
              {sessions.map((s) => (
                <div className="bar-row" key={s.rev}>
                  <span className="bar-lbl">{s.rev}</span>
                  <span className="bar-track">
                    <span
                      className={`bar-fill ${s.variant}`}
                      style={{ width: `${sessionWidth(s.count)}%` }}
                    />
                  </span>
                  <span className="bar-val mono">{s.count}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="eh">Fallback reasons</div>
              {noFallbackReasons ? (
                <div className="muted-note">No fallback reasons recorded yet.</div>
              ) : (
                reasons.map(([reason, count]) => (
                  <div className="kvline" style={{ marginBottom: 4 }} key={reason}>
                    <Tag>{reason}</Tag> <b>{count}</b>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Abuse guard"
        sub="Observe-only logs decisions; enforce actively blocks requests exceeding limits."
        right={
          enforce ? (
            <Pill variant="warn">enforcing</Pill>
          ) : (
            <Pill variant="ok">observe-only</Pill>
          )
        }
      >
        {guardLoading ? (
          <Skeleton rows={2} />
        ) : (
          <>
            {/* Observability-driven chips are withheld while the live summary is
                failed (all chips stay hidden until retry succeeds; the recovery
                alert with the retry actions renders in the session card above). */}
            {!obsError && (
              <>
                {/* Read-only current-configuration summary — scannable at a glance,
                    independent of the editable form ("Rate-Limit Thresholds":
                    current limits + allowlist SIZE). */}
                <div className="metric-strip" style={{ marginBottom: 14 }}>
                  <div className="m">
                    <div className="mv mono">{settingsSummary.ipPerMin}</div>
                    <div className="ml">IP / min</div>
                  </div>
                  <div className="m">
                    <div className="mv mono">{settingsSummary.fingerprintPerMin}</div>
                    <div className="ml">Fingerprint / min</div>
                  </div>
                  <div className="m">
                    <div className="mv mono">{fmtCount(settingsSummary.globalPerMin)}</div>
                    <div className="ml">Global / min</div>
                  </div>
                  <div className="m">
                    <div className="mv mono">{settingsSummary.allowlistSize}</div>
                    <div className="ml">Allowlist size</div>
                  </div>
                </div>

                {/* Audit provenance + Config History deep-link ("Auditing
                    configuration changes"): last-modified by / when, with rollback path. */}
                <div
                  className="toolbar"
                  style={{ marginBottom: 12, alignItems: "center" }}
                >
                  <span className="kvline">
                    last change by <b>{settingsSummary.updatedBy}</b>
                  </span>
                  <span className="kvline">
                    {settingsSummary.updatedAt} · <b>{timeAgo(settingsSummary.updatedAt)}</b>
                  </span>
                  <span className="kvline">
                    debug header <b>{settingsSummary.debugHeaderEnabled ? "enabled" : "disabled"}</b>
                  </span>
                  <div className="toolbar-right">
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      icon="history"
                      onClick={() => navigate("config")}
                    >
                      View in Config History
                    </Button>
                  </div>
                </div>
              </>
            )}

            {settingsError ? (
              // Error — abuse-guard settings unavailable: only the form is
              // hidden until a retry succeeds; telemetry around it stays visible.
              <SettingsError
                navigate={navigate}
                onRetry={() => health.abuseGuardSettingsQuery.refetch()}
              />
            ) : (
              <>
                {/* Permission denied (non-superuser): the form stays
                    rendered and readable — inputs + Apply are disabled (grayed,
                    matching .btn[disabled]) with an explaining caption. No red
                    alert banner. */}
                <div className="toolbar">
                  <Select
                    label="Guard mode"
                    width={180}
                    options={["observe-only", "enforce"]}
                    value={guardMode}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) =>
                      setGuardMode(e.target.value === "enforce" ? "enforce" : "observe-only")
                    }
                  />
                  <Select
                    label="Debug header"
                    width={160}
                    options={["enabled", "disabled"]}
                    value={health.abuseGuardDebugHeaderEnabled ? "enabled" : "disabled"}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) =>
                      health.setAbuseGuardDebugHeaderEnabled(e.target.value === "enabled")
                    }
                  />
                  <Input
                    label="Allowlist tokens (CSV)"
                    width={260}
                    placeholder="fingerprint / host / hashed IP"
                    value={health.abuseGuardAllowlistInput}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) => health.setAbuseGuardAllowlistInput(e.target.value)}
                  />
                </div>
                <div className="muted-note" style={{ margin: "2px 0 8px" }}>
                  {enforce
                    ? "Enforcing: requests exceeding limits are actively blocked with HTTP 429 and logged."
                    : "Observe-only: limit breaches are logged with reason codes but requests are still served."}
                </div>
                <div className="toolbar" style={{ marginTop: 4 }}>
                  <Input
                    label="IP / min"
                    width={150}
                    value={health.abuseGuardIpLimitInput}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) => health.setAbuseGuardIpLimitInput(e.target.value)}
                    inputMode="numeric"
                  />
                  <Input
                    label="Fingerprint / min"
                    width={160}
                    value={health.abuseGuardFingerprintLimitInput}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) => health.setAbuseGuardFingerprintLimitInput(e.target.value)}
                    inputMode="numeric"
                  />
                  <Input
                    label="Global / min"
                    width={170}
                    value={health.abuseGuardGlobalLimitInput}
                    disabled={!canEdit}
                    style={canEdit ? undefined : { opacity: 0.5 }}
                    onChange={(e) => health.setAbuseGuardGlobalLimitInput(e.target.value)}
                    inputMode="numeric"
                  />
                  <div className="toolbar-right">
                    {!canEdit && (
                      <span className="muted-note">
                        Only superuser key can update abuse guard policy.
                      </span>
                    )}
                    <Button
                      variant="btn-primary"
                      size="sm"
                      icon="check"
                      onClick={applySettings}
                      disabled={
                        !canEdit || mutation.isPending || health.abuseGuardSettingsQuery.isLoading
                      }
                    >
                      {mutation.isPending ? "Applying…" : "Apply settings"}
                    </Button>
                  </div>
                </div>

                {/* Inline mutation feedback ("Mutation success" / "Error —
                    mutation failed"). role=alert; Apply stays enabled for retry. */}
                {applied && mutation.isSuccess && (
                  <InlineNotice
                    tone="ok"
                    title="Abuse guard settings updated."
                    text="Observability queries re-fetch to reflect the new thresholds and mode."
                  />
                )}
                {applied && mutation.isError && (
                  <InlineNotice
                    tone="crit"
                    title="Could not update abuse guard settings"
                    text={mutationError}
                    actions={
                      <Button
                        variant="btn-ghost"
                        size="sm"
                        icon="refresh"
                        onClick={applySettings}
                      >
                        Retry
                      </Button>
                    }
                  />
                )}
              </>
            )}

            {/* Decisions breakdown is read-only telemetry — visible to every
                authenticated role (only the mutation controls above are
                superuser-gated). Withheld while the live summary is failed. */}
            {!obsError && (
              <>
                <div className="eh" style={{ marginTop: 14 }}>
                  Decisions breakdown · current window
                </div>
                {noDecisions ? (
                  <div className="muted-note" style={{ marginTop: 8 }}>
                    No decisions recorded yet.
                  </div>
                ) : (
                  // Both guard modes shown at once (grouped by observe-only
                  // and enforce modes) — the 2-col grid pads to a second cell when a
                  // single mode is present so the chart keeps its layout.
                  <div className="chart-grid" style={{ marginTop: 8 }}>
                    {liveDecisionGroups.map((group) => (
                      <div key={group.mode}>
                        <div className="eh">{group.mode}</div>
                        {group.rows.map((d) => (
                          <div className="bar-row" key={`${group.mode}-${d.decision}`}>
                            <span className="bar-lbl">{d.decision}</span>
                            <span className="bar-track">
                              <span
                                className={`bar-fill ${d.variant}`}
                                style={{ width: `${decisionWidth(d.count)}%` }}
                              />
                            </span>
                            <span className="bar-val mono">{d.count}</span>
                          </div>
                        ))}
                      </div>
                    ))}
                    {liveDecisionGroups.length < 2 && <div />}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </Card>

      {/* Observability-driven reference cards: withheld while the live summary is
          loading/failed (the error state hides all chips until retry succeeds;
          the recovery alert + retry actions live in the session card above).
          Offline the queries are disabled, so the fixture cards always render. */}
      {!obsUnavailable && (
      <Card
        title="Alert pack"
        sub="Runtime alerts evaluated against live traffic windows."
        flush
      >
        {noAlerts ? (
          <EmptyState
            title="No alert rules configured"
            text="Configure alerting rules to evaluate live traffic windows against severity thresholds."
          />
        ) : (
          alerts.map((a) => (
            <div className="alert-row" key={a.name}>
              <Pill variant={a.variant}>{a.pillText}</Pill>
              <div>
                <div className="a-name">{a.name}</div>
                <div className="a-desc">{a.desc}</div>
              </div>
              <div className="a-meta">{a.meta}</div>
            </div>
          ))
        )}
      </Card>
      )}

      {!obsUnavailable && (
      <Card
        title="Tracing & drilldown"
        sub="Distributed tracing config and external observability deep-links carry request_id / trace_id."
        right={<span className="kvline">generated <b>{timeAgo(generatedAt)}</b></span>}
      >
        <div className="toolbar" style={{ margin: "0 0 12px" }}>
          <span className="kvline">
            tracing=<b>{obs ? (obs.trace_policy.enabled ? "enabled" : "disabled") : "enabled"}</b>
          </span>
          <span className="kvline">
            backend=<b>{obs?.trace_policy.backend ?? "Tempo"}</b>
          </span>
          <span className="kvline">
            sample=<b>{obs ? `${Math.round(obs.trace_policy.sample_ratio * 100)}%` : "10%"}</b>
          </span>
          <span className="kvline">
            slow threshold=
            <b>{obs ? `${obs.trace_policy.slow_request_threshold_ms}ms` : "500ms"}</b>
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="bars"
            disabled={!!obs && !obs.drilldown_links.grafana_dashboard_url}
            title={
              !!obs && !obs.drilldown_links.grafana_dashboard_url
                ? "No Grafana dashboard URL configured"
                : undefined
            }
            onClick={() => {
              const url = obs?.drilldown_links.grafana_dashboard_url;
              if (url) window.open(url, "_blank", "noopener");
            }}
          >
            Open Grafana
          </Button>
          {/* Loki/Tempo open the MATERIALIZED template ({request_id}/{trace_id}
              substituted with the live sample id) — never the raw template.
              Missing template or sample id → disabled with an explaining tooltip. */}
          <Button
            variant="btn-ghost"
            size="sm"
            icon="list"
            disabled={!!obs && !lokiUrl}
            title={
              !obs
                ? undefined
                : !obs.drilldown_links.loki_logs_url_template
                  ? "No Loki URL template configured"
                  : !sampleRequestId
                    ? "No sample request_id recorded yet to deep-link"
                    : undefined
            }
            onClick={() => {
              if (lokiUrl) window.open(lokiUrl, "_blank", "noopener");
            }}
          >
            Open Loki
          </Button>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="git"
            disabled={!!obs && !tempoUrl}
            title={
              !obs
                ? undefined
                : !obs.drilldown_links.tempo_trace_url_template
                  ? "No Tempo URL template configured"
                  : !sampleRequestId
                    ? "No sample request_id recorded yet to deep-link"
                    : undefined
            }
            onClick={() => {
              if (tempoUrl) window.open(tempoUrl, "_blank", "noopener");
            }}
          >
            Open Tempo
          </Button>
          <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
            Open Logs & Traces
          </Button>
        </div>
      </Card>
      )}

      {!obsUnavailable && (
      <Card
        title="Deploy safety"
        sub="Canary policy decision + smoke-test results for the latest control-plane deployment."
        flush
      >
        <div className="alert-row">
          {/* Live `latest_decision: null` = the "not evaluated" state
              (neutral pill), never the fixture "promoted" copy; the fixture row
              renders OFFLINE only. */}
          <Pill variant={obs ? statusVariant(obs.canary_policy.latest_decision ?? "") : "ok"}>
            {obs ? (obs.canary_policy.latest_decision ?? "not evaluated") : "promoted"}
          </Pill>
          <div>
            <div className="a-name">Canary policy</div>
            <div className="a-desc">
              {obs
                ? (obs.canary_policy.latest_reason ??
                  "No canary decision has been recorded for the latest deploy yet.")
                : "Latest deploy promoted · no rollback"}
            </div>
          </div>
          <div className="a-meta">
            {obs ? (obs.canary_policy.auto_rollback ? "auto-rollback on" : "auto-rollback off") : "build 8c3864e"}
          </div>
        </div>
        {smokeChecks.map((c) => (
          <div className="alert-row" key={c.id}>
            <Pill variant={statusVariant(c.status)}>{c.status}</Pill>
            <div className="a-name">{c.id}</div>
            <div className="a-meta">{c.meta}</div>
          </div>
        ))}
      </Card>
      )}
    </>
  );
}

/* ---------- documented error states (recovery alerts with deep-links) ---------- */

function ObservabilityError({
  navigate,
  onRefresh,
}: {
  navigate: (k: "logs") => void;
  onRefresh: () => void;
}) {
  return (
    <div className="recovery" role="alert">
      <div className="rec-ico">
        <Icon name="alert" />
      </div>
      <div className="rec-body">
        <div className="rec-title">Observability summary is unavailable</div>
        <div className="rec-text">
          MCP negotiation telemetry could not be loaded. Chips stay hidden until a retry succeeds.
        </div>
        <div className="rec-cause">Likely cause: observability endpoint unreachable or timed out.</div>
        <div className="rec-actions">
          <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onRefresh}>
            Refresh now
          </Button>
          <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
            Open Logs & Traces
          </Button>
        </div>
      </div>
    </div>
  );
}

function SettingsError({
  navigate,
  onRetry,
}: {
  navigate: (k: "logs") => void;
  onRetry: () => void;
}) {
  return (
    <div className="recovery" role="alert">
      <div className="rec-ico">
        <Icon name="alert" />
      </div>
      <div className="rec-body">
        <div className="rec-title">Abuse guard settings are unavailable</div>
        <div className="rec-text">
          The form is hidden to prevent submitting inconsistent changes against stale data.
        </div>
        <div className="rec-cause">Likely cause: settings query failed for the current key.</div>
        <div className="rec-actions">
          <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onRetry}>
            Retry settings load
          </Button>
          <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
            Open Logs & Traces
          </Button>
        </div>
      </div>
    </div>
  );
}

/* Kept for the read-only posture (non-superuser audit view). */
export function RuntimeReadonlyNotice() {
  return <ReadonlyBanner />;
}
