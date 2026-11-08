"use client";

import { useEffect, useMemo, useState } from "react";

import type { CriticalEventAction } from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { IconButton } from "../components/IconButton";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { EmptyState, ErrorState, PermissionDenied, Skeleton, StaleBadge } from "../components/states";
import { Table, TableCard } from "../components/Table";
import { Tag } from "../components/Tag";
import { Icon } from "../lib/icons";
import type { IconName, StatusVariant } from "../lib/types";
import { usePopover, PopoverPanel } from "../shell/Popover";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";

// API limitation: no dedicated endpoint is wired here — there is no structured-log / critical-actions
// hook in this shell, so the log rows, the critical-event actions audit list, the drill-down summary
// feed, and the freshness clock all run from in-file fixtures and stay fully usable offline. Only the
// role chip and the CSV-export scope gate are bound live via useAdminData(); every other surface
// follows the Health fixture-fallback idiom (source = live.length ? live : FIXTURE).

// ─────────────────────────────────────────────────────────── Fixtures ──────

type Severity = "error" | "warn" | "info";

// `win` = the narrowest cumulative time bucket a row falls into ("15m" ⊂ "1h" ⊂ "24h").
// Carried on the fixture so the Window selector filters the offline dataset client-side
// (server-filters this column when a real log feed exists); never rendered.
type WindowBucket = "15m" | "1h" | "24h";

interface LogRow {
  time: string;
  sev: Severity;
  src: string;
  req: string;
  tr: string;
  msg: string;
  win: WindowBucket;
}

const LOGROWS: LogRow[] = [
  {
    time: "10:31:04",
    sev: "error",
    src: "api",
    req: "req_8c3864e",
    tr: "tr_91af2c",
    msg: "publish gate blocked — usable chunk coverage 71%",
    win: "15m",
  },
  {
    time: "10:30:58",
    sev: "warn",
    src: "ingestion",
    req: "req_4a1f9b2",
    tr: "tr_77de01",
    msg: "parse warning: malformed frontmatter in PivotTable.md",
    win: "15m",
  },
  {
    time: "10:30:41",
    sev: "info",
    src: "mcp",
    req: "req_2c77d10",
    tr: "tr_2c10bb",
    msg: "protocol negotiated v0.3 · session opened",
    win: "15m",
  },
  {
    time: "10:29:12",
    sev: "error",
    src: "retrieval",
    req: "req_91be0a4",
    tr: "tr_5a0e77",
    msg: "qdrant partial shard timeout (>5s) · stale-while-revalidate",
    win: "1h",
  },
  {
    time: "10:28:50",
    sev: "info",
    src: "admin",
    req: "req_55da2f1",
    tr: "tr_33be70",
    msg: "rollback executed → snap_71ad…c03 by su@local",
    win: "1h",
  },
  {
    time: "10:27:33",
    sev: "warn",
    src: "guard",
    req: "req_1bd4e88",
    tr: "tr_0f7a21",
    msg: "RATE_LIMIT decision (observe-only) · ip 203.0.113.7",
    win: "24h",
  },
];

const SEVP: Record<Severity, StatusVariant> = { error: "crit", warn: "warn", info: "info" };

const SEVERITY_OPTS = ["All", "error", "warn", "info"];
const SOURCE_OPTS = ["All", "api", "mcp", "ingestion", "retrieval", "guard", "admin"];
const WINDOW_OPTS = ["last 15m", "last 1h", "last 24h"];

// Each window label admits its bucket plus all narrower ones (cumulative recency).
const WINDOW_BUCKETS: Record<string, WindowBucket[]> = {
  "last 15m": ["15m"],
  "last 1h": ["15m", "1h"],
  "last 24h": ["15m", "1h", "24h"],
};

interface DrillLink {
  label: string;
  icon: IconName;
  /** Builds the deep-link from the currently-selected action's correlation ids. */
  href: (ctx: { req: string | null; tr: string | null }) => string;
  /** When true the link is request-scoped and must disable if request_id is null. */
  needsRequestId: boolean;
  /** Per-system explanation surfaced as the enabled-state tooltip. */
  tip: string;
}

// Grafana is a dashboard pivot (no per-request filter needed); Loki & Tempo are request/trace-scoped
// and substitute the SELECTED action's request_id / trace_id into the query template (per-row
// id substitution). All three carry a stable host so the buttons render a real, openable URL offline.
const DRILL_LINKS: DrillLink[] = [
  {
    label: "Open in Grafana",
    icon: "bars",
    href: () => "https://grafana.local/d/adcs-service-overview",
    needsRequestId: false,
    tip: "Open the Grafana dashboard in a new tab. Displays service performance metrics, error rates, and latency trends for correlating with incidents.",
  },
  {
    label: "Open in Loki",
    icon: "list",
    href: ({ req }) => `https://loki.local/explore?q={request_id="${req ?? ""}"}`,
    needsRequestId: true,
    tip: "Open Loki pre-filled with the request_id to view structured logs. Lets you trace the full request path across all services.",
  },
  {
    label: "Open in Tempo",
    icon: "git",
    href: ({ req, tr }) => `https://tempo.local/trace/${tr ?? req ?? ""}`,
    needsRequestId: true,
    tip: "Open Tempo pre-filled with the trace_id for distributed trace visualization. Shows the span waterfall and inter-component latencies.",
  },
];

// API limitation: critical-event actions audit list. Typed to the real backend contract
// (admin-api.ts `CriticalEventAction`: action_id / event_id / action / actor_key_id / request_id /
// payload / created_at) so a live `/admin/v1/events/critical/actions` feed drops in unchanged. Used
// wholesale offline. `created_at` is stored as a UTC ISO string and always rendered with a tz marker.
const CRITICAL_ACTIONS: CriticalEventAction[] = [
  {
    action_id: "act_0a91f3",
    event_id: "critical-event-sku-fallback",
    action: "escalate",
    actor_key_id: "key_oncall_a1",
    request_id: "req_8c3864e",
    payload: { to: "sev1", reason: "fallback ratio breached 30%" },
    created_at: "2026-06-05T10:31:12Z",
  },
  {
    action_id: "act_0a8f2c",
    event_id: "critical-event-sku-fallback",
    action: "acknowledge",
    actor_key_id: "key_oncall_a1",
    request_id: "req_8c3864e",
    payload: {},
    created_at: "2026-06-05T10:29:48Z",
  },
  {
    action_id: "act_0a7d10",
    event_id: "critical-event-qdrant-timeout",
    action: "assign_owner",
    actor_key_id: "key_sre_lead",
    request_id: "req_91be0a4",
    payload: { owner: "retrieval-oncall" },
    created_at: "2026-06-05T10:24:05Z",
  },
  {
    action_id: "act_0a6b88",
    event_id: "critical-event-qdrant-timeout",
    action: "severity_override",
    actor_key_id: "key_sre_lead",
    request_id: "req_91be0a4",
    payload: { from: "warning", to: "critical" },
    created_at: "2026-06-05T10:23:41Z",
  },
  {
    action_id: "act_0a5a2f",
    event_id: "critical-event-publish-gate",
    action: "mute",
    actor_key_id: "key_automation_publish",
    request_id: null,
    payload: { window_minutes: 30 },
    created_at: "2026-06-05T10:18:33Z",
  },
  {
    action_id: "act_0a49b1",
    event_id: "critical-event-rate-limit",
    action: "snooze",
    actor_key_id: "key_oncall_b2",
    request_id: "req_1bd4e88",
    payload: { until: "2026-06-05T12:00:00Z" },
    created_at: "2026-06-05T10:12:09Z",
  },
  {
    action_id: "act_0a38c4",
    event_id: "critical-event-rate-limit",
    action: "acknowledge",
    actor_key_id: "key_oncall_b2",
    request_id: "req_1bd4e88",
    payload: {},
    created_at: "2026-06-05T10:08:50Z",
  },
  {
    action_id: "act_0a27d7",
    event_id: "critical-event-parse-warning",
    action: "resolved",
    actor_key_id: "key_ingest_lead",
    request_id: "req_4a1f9b2",
    payload: { note: "frontmatter patched upstream" },
    created_at: "2026-06-05T10:01:17Z",
  },
  {
    action_id: "act_0a16ee",
    event_id: "critical-event-parse-warning",
    action: "assign_owner",
    actor_key_id: "key_ingest_lead",
    request_id: "req_4a1f9b2",
    payload: { owner: "ingestion-oncall" },
    created_at: "2026-06-05T09:57:42Z",
  },
  {
    action_id: "act_0a05a0",
    event_id: "critical-event-snapshot-rollback",
    action: "escalate",
    actor_key_id: "key_oncall_a1",
    request_id: "req_55da2f1",
    payload: { to: "sev2" },
    created_at: "2026-06-05T09:51:03Z",
  },
  {
    action_id: "act_09f4b3",
    event_id: "critical-event-snapshot-rollback",
    action: "acknowledge",
    actor_key_id: "key_oncall_a1",
    request_id: "req_55da2f1",
    payload: {},
    created_at: "2026-06-05T09:48:55Z",
  },
  {
    action_id: "act_09e3c6",
    event_id: "critical-event-opensearch-replica",
    action: "mute",
    actor_key_id: "key_automation_index",
    request_id: null,
    payload: { window_minutes: 60 },
    created_at: "2026-06-05T09:40:21Z",
  },
  {
    action_id: "act_09d2d9",
    event_id: "critical-event-opensearch-replica",
    action: "snooze",
    actor_key_id: "key_sre_lead",
    request_id: "req_77de019",
    payload: { until: "2026-06-05T11:30:00Z" },
    created_at: "2026-06-05T09:33:14Z",
  },
];

// Each action's primary label maps to a status pill from the closed palette (no new colors).
const ACTION_PILL: Record<string, StatusVariant> = {
  escalate: "crit",
  severity_override: "warn",
  mute: "warn",
  snooze: "info",
  assign_owner: "info",
  acknowledge: "neutral",
  resolved: "ok",
};

// Human label for the action verb (keeps the audit row scannable; backend verbs are snake_case).
const ACTION_LABEL: Record<string, string> = {
  escalate: "escalate",
  severity_override: "severity override",
  mute: "mute",
  snooze: "snooze",
  assign_owner: "assign owner",
  acknowledge: "acknowledge",
  resolved: "resolve",
};

function actionPill(action: string): StatusVariant {
  return ACTION_PILL[action] ?? "neutral";
}
function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action;
}

// Render a UTC ISO timestamp with an explicit timezone indicator (audit-critical — every
// timestamp carries a tz marker). Falls back to the raw value if it is not parseable.
function fmtUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`
  );
}

// The optional drill state lets us demonstrate the loading / error / stale states for
// the observability summary feed without fetching. Default is the live happy path.
type DrillState = "ready" | "loading" | "error" | "stale";

const ACTIONS_PAGE = 10; // Default view 10, expand +10.

export function LogsSection() {
  const { navigate } = useShell();
  const data = useAdminData();
  const helpPop = usePopover();

  // Toolbar filters (client-only; fixtures first).
  const [severity, setSeverity] = useState("All");
  const [source, setSource] = useState("All");
  const [idFilter, setIdFilter] = useState("");
  const [timeWindow, setTimeWindow] = useState(WINDOW_OPTS[0]);

  // Selected log row → drives per-row drill-down id substitution (Loki/Tempo carry THIS id).
  // Defaults to the first/most-recent fixture row so the buttons resolve a real id offline.
  const [selectedReq, setSelectedReq] = useState<string>(LOGROWS[0].req);

  // Critical-actions audit pagination (ephemeral; default 10, +10, Show less).
  const [actionsShown, setActionsShown] = useState(ACTIONS_PAGE);

  // Soft refresh clock — the actions list is cached and refetches every 60s; surface the age so the
  // operator knows the data may be up to 60s stale ("Last updated X seconds ago").
  const [ageSec, setAgeSec] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setAgeSec((s) => (s + 1) % 60), 1000);
    return () => clearInterval(id);
  }, []);
  // Header Refresh re-anchors the soft-refresh clock (there is no live feed to refetch).
  const refresh = () => setAgeSec(0);

  // Contextual How-To deep-link: carries the source section + back-link so
  // the knowledge center can render a "Back to Logs & Traces" link and preselect the section article.
  const buildHowToHref = (article = "admin-logs-traces") => {
    const params = new URLSearchParams();
    params.set("article", article);
    params.set("from", "logs-traces");
    params.set("source_label", "Logs & Traces");
    params.set("return_to", "/#logs-traces");
    return `/howto?${params.toString()}`;
  };

  // Permission gate for CSV export — read:logs under the six-scope model (keys without the
  // logs read scope cannot export). Permissive until a real session loads, so fixtures mode shows
  // the export enabled.
  const canExport = data.can("read:logs");
  // Observability-summary feed state — drives the loading / error / stale branches.
  // No live feed exists (API limitation); offline the summary is present, so the happy path renders.
  // Widened to DrillState so all four state branches stay type-reachable.
  const drill = "ready" as DrillState;

  const rows = useMemo(() => {
    const q = idFilter.trim().toLowerCase();
    const allowedWindows = WINDOW_BUCKETS[timeWindow] ?? WINDOW_BUCKETS["last 24h"];
    return LOGROWS.filter((r) => {
      if (severity !== "All" && r.sev !== severity) return false;
      if (source !== "All" && r.src !== source) return false;
      if (q && !r.req.toLowerCase().includes(q) && !r.tr.toLowerCase().includes(q)) return false;
      if (!allowedWindows.includes(r.win)) return false;
      return true;
    });
  }, [severity, source, idFilter, timeWindow]);

  // Keep the drill-down context valid: if the selected row scrolls out of the filtered set, fall back
  // to the first visible row so Loki/Tempo always target a row the operator can see.
  const selectedRow = rows.find((r) => r.req === selectedReq) ?? rows[0];
  const drillCtx = { req: selectedRow?.req ?? null, tr: selectedRow?.tr ?? null };

  // Critical-event actions audit list — fixture is the offline dataset (Health idiom: a live feed
  // would replace it via `live.length ? live : CRITICAL_ACTIONS`). There is no live feed,
  // so the source is the fixture; the empty state below still fires when the source is genuinely empty.
  const actionsSource: CriticalEventAction[] = CRITICAL_ACTIONS;
  const visibleActions = actionsSource.slice(0, actionsShown);
  const remainingActions = Math.max(0, actionsSource.length - actionsShown);

  return (
    <>
      <PageHead
        title="Logs & Traces"
        sub="Structured log explorer and distributed trace viewer for debugging production issues."
        actions={
          <>
            <ScopeChip
              label="role"
              value={data.session?.is_superuser ? "superuser" : "operator"}
              dot
            />
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              onClick={refresh}
              title="Re-fetch the latest log rows and critical-event actions"
            >
              Refresh
            </Button>
            <div className="pop-wrap" ref={helpPop.wrapRef} style={{ position: "relative" }}>
              <IconButton
                icon="book"
                aria-haspopup="dialog"
                aria-expanded={helpPop.open}
                title="How-To for this section"
                aria-label="Open How-To for Logs & Traces"
                onClick={helpPop.toggle}
              />
              {helpPop.open && (
                <HelpPopover
                  onOpenHowTo={() => {
                    helpPop.close();
                    window.location.href = buildHowToHref();
                  }}
                />
              )}
            </div>
          </>
        }
      />

      <Banner
        variant="info"
        icon="info"
        guidance
        title="Pivot from any request_id / trace_id straight into your observability stack"
        text="Select a log row, then use the deep-link buttons below — each carries that row's id for end-to-end tracing across Grafana, Loki, and Tempo. The audit list underneath records who acted on which critical event."
        actions={
          <Button variant="btn-ghost" size="sm" icon="alert" onClick={() => navigate("critical")}>
            Open Critical Events
          </Button>
        }
      />

      <Card
        title="Log explorer"
        sub="Request-oriented structured logs from critical-event actions and operator mutations. Select a row to set the drill-down target; filter by severity, source, id, or time window."
        flush
      >
        <div className="toolbar">
          <Select
            label="Severity"
            width={130}
            options={SEVERITY_OPTS}
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          />
          <Select
            label="Source"
            width={140}
            options={SOURCE_OPTS}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
          <Input
            label="request_id / trace_id"
            width={200}
            placeholder="filter by id…"
            value={idFilter}
            onChange={(e) => setIdFilter(e.target.value)}
          />
          <Select
            label="Window"
            width={140}
            options={WINDOW_OPTS}
            value={timeWindow}
            onChange={(e) => setTimeWindow(e.target.value)}
          />
          <div className="toolbar-right">
            <span className="muted-note">{rows.length} of 1 284 events</span>
          </div>
        </div>

        {rows.length === 0 ? (
          <EmptyState
            title="No events match these filters"
            text="No structured log events match the current severity, source, id, or time window. Widen the window or clear the id filter."
            action={
              <Button
                variant="btn-ghost"
                size="sm"
                icon="refresh"
                onClick={() => {
                  setSeverity("All");
                  setSource("All");
                  setIdFilter("");
                  setTimeWindow(WINDOW_OPTS[0]);
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <TableCard>
            <Table>
              <thead>
                <tr>
                  <th style={{ width: 44 }} aria-label="Drill-down target" />
                  <th className="num" style={{ width: 90 }}>
                    Time
                  </th>
                  <th style={{ width: 80 }}>Severity</th>
                  <th style={{ width: 96 }}>Source</th>
                  <th style={{ width: 120 }}>request_id</th>
                  <th style={{ width: 110 }}>trace_id</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const on = r.req === selectedRow?.req;
                  return (
                    <tr
                      className="data"
                      key={r.req}
                      data-selected={on || undefined}
                      style={on ? { background: "var(--surface-2)" } : undefined}
                    >
                      <td>
                        <input
                          type="radio"
                          name="log-drill-target"
                          checked={on}
                          onChange={() => setSelectedReq(r.req)}
                          aria-label={`Set ${r.req} as drill-down target`}
                        />
                      </td>
                      <td className="num">{r.time}</td>
                      <td>
                        <Pill variant={SEVP[r.sev]}>{r.sev}</Pill>
                      </td>
                      <td>
                        <Tag>{r.src}</Tag>
                      </td>
                      <td>
                        <span className="repo-id">{r.req}</span>
                      </td>
                      <td>
                        <span className="mono" style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                          {r.tr}
                        </span>
                      </td>
                      <td>{r.msg}</td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </TableCard>
        )}
      </Card>

      <Card
        title="External drill-down"
        sub="Deep links carry the selected request_id / trace_id for end-to-end tracing."
        flush
        right={
          drill === "stale" ? (
            <StaleBadge>cached · {ageSec}s</StaleBadge>
          ) : (
            <span className="muted-note" aria-live="polite">
              <Icon name="clock" className="ico" /> Updated {ageSec}s ago
            </span>
          )
        }
      >
        <div className="card-sub" style={{ marginBottom: 12 }}>
          Drilling down for{" "}
          {drillCtx.req ? (
            <span className="repo-id">{drillCtx.req}</span>
          ) : (
            <span className="mono" style={{ color: "var(--fg-subtle)" }}>
              no request selected
            </span>
          )}
          {drillCtx.tr ? (
            <>
              {" "}
              · trace <span className="repo-id">{drillCtx.tr}</span>
            </>
          ) : null}
          . Select a row in the log explorer above to change the target.
        </div>

        {drill === "loading" && <Skeleton rows={3} />}

        {drill === "error" && (
          <ErrorState
            title="Observability drill-down links are unavailable"
            text="The observability summary feed did not load, so the deep-link buttons are hidden. Check backend connectivity or wait for the service to recover."
            cause="observability/summary timeout"
            actions={
              <>
                <Button variant="btn-ghost" size="sm" icon="refresh" onClick={refresh}>
                  Refresh now
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="alert"
                  onClick={() => navigate("critical")}
                >
                  Open Critical Events
                </Button>
              </>
            }
          />
        )}

        {(drill === "ready" || drill === "stale") && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {DRILL_LINKS.map((l) => {
              const disabled = l.needsRequestId && !drillCtx.req;
              const title = disabled
                ? "request_id not yet available — select a log row with a request id"
                : l.tip;
              return disabled ? (
                <Button
                  key={l.label}
                  variant="btn-ghost"
                  icon={l.icon}
                  disabled
                  aria-disabled
                  title={title}
                >
                  {l.label}
                </Button>
              ) : (
                <a
                  key={l.label}
                  className="btn btn-ghost"
                  href={l.href(drillCtx)}
                  target="_blank"
                  rel="noreferrer"
                  title={title}
                >
                  <Icon name={l.icon} className="ico" />
                  {l.label}
                </a>
              );
            })}
            {canExport ? (
              <Button variant="btn-ghost" icon="download">
                Export logs (CSV)
              </Button>
            ) : (
              <Button variant="btn-ghost" icon="download" disabled title="Requires read:logs">
                Export logs (CSV)
              </Button>
            )}
          </div>
        )}

        {!canExport && (
          <PermissionDenied
            scope="read:logs"
            extra="CSV export of structured logs requires the logs read scope. Request it from an administrator."
          />
        )}
      </Card>

      <Card
        title="Critical event actions"
        sub="Chronological audit of operator mutations on critical events — who did what, when, to which event. Cross-reference the request_id to pivot into observability or back to Critical Events."
        flush
        right={
          <Button
            variant="btn-ghost"
            size="sm"
            icon="key"
            onClick={() => navigate("apikeys")}
            title="Verify an actor key's scopes in API Keys & Access"
          >
            Verify actor key
          </Button>
        }
      >
        {visibleActions.length === 0 ? (
          <EmptyState
            title="No critical event actions recorded yet"
            text="This section will populate when critical events are triggered and operator actions are recorded. Fresh deployments and quiet periods show no actions."
            action={
              <Button
                variant="btn-ghost"
                size="sm"
                icon="alert"
                onClick={() => navigate("critical")}
              >
                Open Critical Events
              </Button>
            }
          />
        ) : (
          <TableCard>
            <Table>
              <thead>
                <tr>
                  <th style={{ width: 150 }}>Action</th>
                  <th>Event</th>
                  <th style={{ width: 150 }}>Actor key</th>
                  <th style={{ width: 130 }}>request_id</th>
                  <th style={{ width: 180 }}>Recorded (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {visibleActions.map((a) => (
                  <tr className="data" key={a.action_id}>
                    <td>
                      <Pill variant={actionPill(a.action)}>{actionLabel(a.action)}</Pill>
                    </td>
                    <td>
                      <span className="repo-id">{a.event_id}</span>
                    </td>
                    <td>
                      <span className="mono" style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                        {a.actor_key_id}
                      </span>
                    </td>
                    <td>
                      {a.request_id ? (
                        <span className="repo-id">{a.request_id}</span>
                      ) : (
                        <span className="mono" style={{ fontSize: 11, color: "var(--fg-subtle)" }}>
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="mono" style={{ fontSize: 11, color: "var(--fg-muted)" }}>
                        {fmtUtc(a.created_at)}
                      </span>
                    </td>
                  </tr>
                ))}
                {(remainingActions > 0 || actionsShown > ACTIONS_PAGE) && (
                  <tr className="more-row">
                    <td colSpan={5}>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                        }}
                      >
                        <span className="muted-note">
                          Showing {visibleActions.length} of {actionsSource.length} actions
                        </span>
                        <div style={{ display: "flex", gap: 8 }}>
                          {actionsShown > ACTIONS_PAGE && (
                            <button
                              type="button"
                              className="more-wrap"
                              onClick={() => setActionsShown(ACTIONS_PAGE)}
                              aria-label="Show fewer critical event actions, collapse to the first 10"
                            >
                              Show less
                            </button>
                          )}
                          {remainingActions > 0 && (
                            <button
                              type="button"
                              className="more-wrap"
                              onClick={() =>
                                setActionsShown((n) =>
                                  Math.min(actionsSource.length, n + ACTIONS_PAGE),
                                )
                              }
                              aria-label={`Load ${Math.min(
                                ACTIONS_PAGE,
                                remainingActions,
                              )} more critical event actions, ${remainingActions} remaining`}
                            >
                              Show more ({remainingActions} remaining)
                            </button>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </Table>
          </TableCard>
        )}
      </Card>
    </>
  );
}

// Contextual Why / What / How help popover — reuses the shell `.pop` panel classes (role=dialog via
// aria, Esc + outside-click close handled by usePopover) with an optional "Open full How-To" link.
function HelpPopover({ onOpenHowTo }: { onOpenHowTo: () => void }) {
  return (
    <PopoverPanel className="logs-help-pop">
      <div className="pop-head" role="dialog" aria-label="Logs & Traces help">
        <Icon name="book" className="ico" />
        <span className="pt">Logs &amp; Traces</span>
      </div>
      <div className="pop-body" role="document">
        <div className="pop-sub">Why</div>
        <p className="card-sub" style={{ margin: "0 0 8px" }}>
          Provides accountability and request-level correlation for incident investigation.
        </p>
        <div className="pop-sub">What</div>
        <p className="card-sub" style={{ margin: "0 0 8px" }}>
          Shows action type, actor key, request_id, and timestamp for recent control-plane
          operations.
        </p>
        <div className="pop-sub">How</div>
        <p className="card-sub" style={{ margin: 0 }}>
          Filter by section first, then use request_id and timestamps to trace event lifecycle.
        </p>
      </div>
      <div className="pop-foot">
        <button type="button" className="more-wrap" onClick={onOpenHowTo}>
          Open full How-To →
        </button>
      </div>
    </PopoverPanel>
  );
}
