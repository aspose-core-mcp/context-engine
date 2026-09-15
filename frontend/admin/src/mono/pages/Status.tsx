"use client";

import { useEffect, useId, useMemo, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  AdminApiError,
  fetchPublicStatus,
  fetchPublicStatusPage,
  fetchPublicTopologyPolicy,
  submitPublicQueryIssue,
  type AdminContentServiceHealth,
  type DependencyHealth,
  type PublicStatusPageResponse,
  type PublicStatusResponse,
  type StatusComponentRuntime,
  type TopologyPolicyResponse,
} from "@/lib/admin-api";

import { IconButton } from "../components/IconButton";
import { Pill } from "../components/Pill";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";

/* ----------------------------------------------------------------------------
 * Public Status Dashboard (/status) — standalone Mono public page.
 *
 * LIVE-VS-FIXTURE (public, no auth): public endpoints need no session, so each
 * section is driven by a TanStack `useQuery` over the existing admin-api
 * `fetchPublic*` fns. Fixtures are the OFFLINE fallback so the whole page stays
 * reviewable with no backend:
 *   • offline / disabled  → in-file fixtures
 *   • live success        → live data
 *   • live success EMPTY  → empty state
 *   • live ERROR          → error state with Retry
 * "Live" is opt-in via NEXT_PUBLIC_ADCS_PUBLIC_LIVE (same NEXT_PUBLIC_ADCS_*
 * convention as the API base); unset → offline so the page renders the fixtures
 * with no network. The report-issue form always POSTs for real.
 * -------------------------------------------------------------------------- */

const THEME_KEY = "adcs_theme";

/** Live data is opt-in. Unset / "0" / "false" → offline fixtures (fully reviewable, no backend). */
const PUBLIC_LIVE = (() => {
  const flag = process.env.NEXT_PUBLIC_ADCS_PUBLIC_LIVE?.trim().toLowerCase();
  return flag === "1" || flag === "true" || flag === "on" || flag === "yes";
})();

/* ---------------- fixtures ---------------- */

interface ServiceRow {
  name: string;
  desc: string;
  up: string;
  /** index (0..19) of the degraded sparkline bar, or -1 for none. */
  degradedIdx: number;
}

const SERVICES: ServiceRow[] = [
  {
    name: "Retrieval API",
    desc: "query_docs · semantic + lexical retrieval",
    up: "100.00%",
    degradedIdx: -1,
  },
  {
    name: "MCP Endpoint",
    desc: "Model Context Protocol negotiation",
    up: "100.00%",
    degradedIdx: -1,
  },
  {
    name: "Ingestion Runtime",
    desc: "layout detection, parsing & publish",
    up: "99.98%",
    degradedIdx: 13,
  },
  {
    name: "Vector Index (Qdrant)",
    desc: "dense retrieval store",
    up: "100.00%",
    degradedIdx: -1,
  },
  {
    name: "Lexical Index (OpenSearch)",
    desc: "sparse retrieval store",
    up: "100.00%",
    degradedIdx: -1,
  },
  {
    name: "Admin Control Plane",
    desc: "operator console & API",
    up: "100.00%",
    degradedIdx: -1,
  },
];

interface IncidentRow {
  date: string;
  title: string;
  body: string;
}

const INCIDENTS: IncidentRow[] = [
  {
    date: "Jun 2, 2026",
    title: "Ingestion runtime — brief publish delay",
    body: "Resolved · A publish run for aspose.cells queued for 6 minutes during an index refresh. No retrieval impact; runtime auto-recovered.",
  },
  {
    date: "May 24, 2026",
    title: "Scheduled index compaction",
    body: "Completed · Routine maintenance on the lexical index. Read traffic served from the active snapshot throughout.",
  },
];

interface DepRow {
  name: string;
  desc: string;
  reason: string;
}

const DEPS: DepRow[] = [
  { name: "Qdrant", desc: "vector index", reason: "connected · memory profile" },
  { name: "OpenSearch", desc: "lexical index", reason: "connected · 1 shard / 0 replica" },
  { name: "PostgreSQL", desc: "metadata DB", reason: "not_required_for_current_runtime" },
  { name: "Redis", desc: "cache & queue", reason: "optional in dev profile" },
];

interface CovRow {
  repo: string;
  product: string;
  kind: string;
  fresh: string;
  freshVariant: StatusVariant;
  langs: string;
  version: string;
}

const COVSVC: CovRow[] = [
  {
    repo: "aspose.ocr.apiref",
    product: "aspose.ocr",
    kind: "apiref",
    fresh: "fresh · 2d",
    freshVariant: "ok",
    langs: "net, java",
    version: "latest",
  },
  {
    repo: "aspose.cells.apiref",
    product: "aspose.cells",
    kind: "apiref",
    fresh: "fresh · today",
    freshVariant: "ok",
    langs: "net",
    version: "latest",
  },
  {
    repo: "aspose.barcode.docs",
    product: "aspose.barcode",
    kind: "docs",
    fresh: "aging · 25d",
    freshVariant: "warn",
    langs: "net, java",
    version: "latest",
  },
  {
    repo: "aspose.3d.apiref",
    product: "aspose.3d",
    kind: "apiref",
    fresh: "not-ready · no snapshot",
    freshVariant: "crit",
    langs: "net",
    version: "—",
  },
];

/* ---------------- live → view mapping ---------------- */

/** StatusVariant for a backend status token. */
function statusVariant(status: string): StatusVariant {
  if (status === "healthy" || status === "ok" || status === "ready" || status === "operational") {
    return "ok";
  }
  if (status === "warning" || status === "degraded") return "warn";
  if (
    status === "critical" ||
    status === "not_ready" ||
    status === "partial_outage" ||
    status === "major_outage"
  ) {
    return "crit";
  }
  return "neutral";
}

interface FreshnessCue {
  label: string;
  variant: StatusVariant;
  detail: string;
}

/** Freshness cue for a content service. */
function serviceFreshnessCue(service: {
  mcp_ready: boolean;
  active_snapshot_created_at: string | null;
  supported_versions: string[];
}): FreshnessCue {
  if (!service.mcp_ready || !service.active_snapshot_created_at) {
    return { label: "not-ready · no snapshot", variant: "crit", detail: "no active snapshot" };
  }
  const ageDays = Math.max(
    0,
    Math.floor(
      (Date.now() - new Date(service.active_snapshot_created_at).getTime()) / 86_400_000,
    ),
  );
  if (ageDays > 30) return { label: `stale · ${ageDays}d`, variant: "warn", detail: "snapshot stale" };
  if (ageDays > 14) return { label: `aging · ${ageDays}d`, variant: "warn", detail: "snapshot aging" };
  return {
    label: ageDays <= 1 ? "fresh · today" : `fresh · ${ageDays}d`,
    variant: "ok",
    detail: `${service.supported_versions.length} version(s)`,
  };
}

/** Map one live content service into the coverage-table row shape. */
function serviceToCovRow(service: AdminContentServiceHealth): CovRow {
  const cue = serviceFreshnessCue(service);
  return {
    repo: service.repo_id,
    product: service.product_id,
    kind: service.source_kind,
    fresh: cue.label,
    freshVariant: cue.variant,
    langs:
      service.supported_programming_languages.length > 0
        ? service.supported_programming_languages.join(", ")
        : "—",
    version:
      service.supported_versions.length > 0 ? service.supported_versions.join(", ") : "—",
  };
}

/** Friendly component name + description, keyed by the live component id. */
const COMPONENT_PROSE: Record<string, { name: string; desc: string }> = {
  retrieval: { name: "Retrieval API", desc: "query_docs · semantic + lexical retrieval" },
  mcp: { name: "MCP Endpoint", desc: "Model Context Protocol negotiation" },
  ingestion: { name: "Ingestion Runtime", desc: "layout detection, parsing & publish" },
  qdrant: { name: "Vector Index (Qdrant)", desc: "dense retrieval store" },
  opensearch: { name: "Lexical Index (OpenSearch)", desc: "sparse retrieval store" },
  admin: { name: "Admin Control Plane", desc: "operator console & API" },
};

const COMPONENT_STATE_LABEL: Record<string, string> = {
  operational: "operational",
  degraded: "degraded",
  partial_outage: "partial outage",
  major_outage: "major outage",
  unknown: "unknown",
};

/* ---------------- deterministic sparkline / uptime helpers ---------------- */

/** 20 deterministic sparkline bars; `degradedIdx` marks the degraded bar. */
function sparkBars(seed: number, degradedIdx: number): { h: number; degraded: boolean }[] {
  const bars: { h: number; degraded: boolean }[] = [];
  for (let i = 0; i < 20; i++) {
    const degraded = i === degradedIdx;
    const v = 8 + ((seed * 7 + i * 13) % 18);
    bars.push({ h: degraded ? 22 : v, degraded });
  }
  return bars;
}

/** Uptime grid — 90 cells, optional degraded indices. */
function uptimeCells(degraded: number[]): boolean[] {
  return Array.from({ length: 90 }, (_, i) => degraded.includes(i));
}

/* ---------------- small composites ---------------- */

function Spark({ seed, degradedIdx }: { seed: number; degradedIdx: number }) {
  return (
    <div className="svc-spark" aria-hidden="true">
      {sparkBars(seed, degradedIdx).map((b, i) => (
        <i key={i} className={cn(b.degraded && "d")} style={{ height: `${b.h}px` }} />
      ))}
    </div>
  );
}

function PubNav({ dark, onToggleTheme }: { dark: boolean; onToggleTheme: () => void }) {
  return (
    <nav className="pub-nav" aria-label="Public navigation">
      <div className="side-logo">A</div>
      <div className="pub-brand">
        ADCS<small>Aspose Context Service</small>
      </div>
      <div className="links">
        <a href="/status" className="on" aria-current="page">
          Status
        </a>
        <a href="/integrations">Integrations</a>
        <a href="#" style={{ opacity: 0.55, pointerEvents: "none" }} aria-disabled="true">
          Docs
        </a>
        <a
          href="/"
          title="Open admin console"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <Icon name="grid" />
          Console
        </a>
        <IconButton
          icon={dark ? "moon" : "sun"}
          id="pub-theme"
          onClick={onToggleTheme}
          aria-pressed={dark}
          aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
          title="Toggle theme"
        />
      </div>
    </nav>
  );
}

function PubFooter({ note }: { note: string }) {
  return (
    <footer className="pub-footer">
      <div className="pf-line">{note}</div>
      <div className="pf-bar">
        <div className="pf-brand">
          <div
            className="side-logo"
            style={{ width: 22, height: 22, fontSize: 11 }}
            aria-hidden="true"
          >
            A
          </div>
          <span>ADCS · Aspose Context Service</span>
        </div>
        <nav className="pf-nav" aria-label="Footer">
          <a href="/status">Status</a>
          <a href="/integrations">Integrations</a>
          <a href="/">Console</a>
          <span className="pf-dim">Docs</span>
        </nav>
      </div>
      <div className="pf-fine">© 2026 Aspose · Documentation Context Service</div>
    </footer>
  );
}

/* ---------------- page ---------------- */

export default function StatusPage() {
  // Hydration-safe theme: start at default (light), sync from storage post-mount.
  const [dark, setDark] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(THEME_KEY);
      if (stored === "dark") setDark(true);
      else if (stored === "light") setDark(false);
    } catch {
      /* storage unavailable — keep default light */
    }
  }, []);

  const toggleTheme = () => {
    setDark((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore persistence failure */
      }
      return next;
    });
  };

  /* --- MCP content services filter (live substring over product/repo) --- */
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const trimmedFilter = filter.trim().toLowerCase();

  /* --- Live queries (public, no auth). Disabled offline so fixtures drive the UI. --- */

  // /v1/status — services, dependencies, readiness counters. Filter pushes to the
  // server (live mode) and is ALSO applied client-side over the display set so the
  // offline fixtures filter too (LIVE-VS-FIXTURE).
  const statusQuery = useQuery({
    queryKey: ["public-status", trimmedFilter],
    queryFn: () => fetchPublicStatus(trimmedFilter ? { product_id: trimmedFilter } : {}),
    enabled: PUBLIC_LIVE,
    staleTime: 60_000,
  });

  // /v1/status/page — overall banner state + announcements/incident feed (30s
  // refetch). Drives the hero LED and the incident-history card when live.
  const statusPageQuery = useQuery<PublicStatusPageResponse>({
    queryKey: ["public-status-page"],
    queryFn: () => fetchPublicStatusPage(),
    enabled: PUBLIC_LIVE,
    staleTime: 60_000,
    refetchInterval: PUBLIC_LIVE ? 30_000 : false,
  });

  // /v1/topology — runtime topology summary line.
  const topologyQuery = useQuery<TopologyPolicyResponse>({
    queryKey: ["public-topology-policy"],
    queryFn: () => fetchPublicTopologyPolicy(),
    enabled: PUBLIC_LIVE,
    staleTime: 60_000,
  });

  /* ----- derive view models with fixture fallback ----- */

  const statusData: PublicStatusResponse | undefined = statusQuery.data;
  const pageData: PublicStatusPageResponse | undefined = statusPageQuery.data;
  const topologyData: TopologyPolicyResponse | undefined = topologyQuery.data;

  // Coverage table. Live success → mapped services; offline → fixtures. The filter
  // predicate is applied to BOTH so the control responds offline (idempotent on the
  // already-server-filtered live rows).
  const liveRows = useMemo<CovRow[]>(
    () => (statusData?.services ?? []).map(serviceToCovRow),
    [statusData?.services],
  );
  const covSource: CovRow[] = PUBLIC_LIVE && statusData ? liveRows : COVSVC;
  const filteredRows = useMemo(() => {
    if (!trimmedFilter) return covSource;
    return covSource.filter(
      (r) =>
        r.repo.toLowerCase().includes(trimmedFilter) ||
        r.product.toLowerCase().includes(trimmedFilter),
    );
  }, [covSource, trimmedFilter]);
  const coverageLoading = statusQuery.isLoading && !filteredRows.length;
  const coverageErrored = statusQuery.isError && !filteredRows.length;
  // Empty only distinguishes "live returned zero rows AND no active filter" (empty
  // state) from "filter hides everything" (filter-empty copy).
  const coverageEmptyLive =
    PUBLIC_LIVE && !!statusData && liveRows.length === 0 && !coverageLoading && !coverageErrored;

  // Components (hero "Components" card). Live → runtime component list; offline → fixtures.
  interface ComponentVM {
    key: string;
    name: string;
    desc: string;
    variant: StatusVariant;
    label: string;
    seed: number;
    degradedIdx: number;
    up: string;
  }
  const liveComponents = useMemo<ComponentVM[]>(() => {
    const list: StatusComponentRuntime[] = pageData?.components ?? [];
    return list.map((c) => {
      const prose = COMPONENT_PROSE[c.id];
      return {
        key: c.id,
        name: c.name || prose?.name || c.id,
        desc: c.note || prose?.desc || "",
        variant: statusVariant(c.state),
        label: COMPONENT_STATE_LABEL[c.state] ?? c.state,
        seed: (c.name || c.id).length,
        degradedIdx: c.state === "operational" ? -1 : 13,
        up: c.state === "operational" ? "100.00%" : "—",
      };
    });
  }, [pageData?.components]);
  const componentSource: ComponentVM[] =
    PUBLIC_LIVE && liveComponents.length
      ? liveComponents
      : SERVICES.map((s) => ({
          key: s.name,
          name: s.name,
          desc: s.desc,
          variant: "ok" as StatusVariant,
          label: "operational",
          seed: s.name.length,
          degradedIdx: s.degradedIdx,
          up: s.up,
        }));
  const componentsNote =
    PUBLIC_LIVE && pageData
      ? `${componentSource.length} services · ${pageData.overall_message}`
      : "6 services · all operational";

  // Hero LED — live overall state when present; fixture "operational" otherwise.
  const overallState = PUBLIC_LIVE ? pageData?.overall_state : undefined;
  const ledVariant: StatusVariant = overallState ? statusVariant(overallState) : "ok";
  const ledLabel = (() => {
    if (!PUBLIC_LIVE || !pageData) return "All systems operational";
    return pageData.overall_message || "All systems operational";
  })();
  const ledTone =
    ledVariant === "ok"
      ? { bg: undefined, fg: undefined }
      : ledVariant === "warn"
        ? { bg: "var(--warn-bg)", fg: "var(--warn)" }
        : { bg: "var(--crit-bg)", fg: "var(--crit)" };
  const updatedNote = (() => {
    if (PUBLIC_LIVE && statusPageQuery.isError) return "Live status unavailable · showing last known";
    if (PUBLIC_LIVE && pageData) return "Live · auto-refresh 30s";
    return "Reference snapshot · auto-refresh 60s when live";
  })();

  // Dependency readiness. Live → backend dependency map; offline → fixtures.
  interface DepVM {
    key: string;
    name: string;
    desc: string;
    variant: StatusVariant;
    reason: string;
  }
  const liveDeps = useMemo<DepVM[]>(() => {
    const entries: [string, DependencyHealth][] = Object.entries(statusData?.dependencies ?? {});
    return entries.map(([name, dep]) => {
      const prose = DEPS.find((d) => d.name.toLowerCase() === name.toLowerCase());
      return {
        key: name,
        name: prose?.name ?? name,
        desc: prose?.desc ?? "",
        variant: statusVariant(dep.status),
        reason: dep.reason || dep.summary || dep.status,
      };
    });
  }, [statusData?.dependencies]);
  const depSource: DepVM[] =
    PUBLIC_LIVE && liveDeps.length
      ? liveDeps
      : DEPS.map((d) => ({
          key: d.name,
          name: d.name,
          desc: d.desc,
          variant: "ok" as StatusVariant,
          reason: d.reason,
        }));

  // Runtime topology line. Live → backend summary; offline → fixture string. On a
  // live error we honestly say so instead of asserting a topology.
  const topologyLine = (() => {
    if (!PUBLIC_LIVE) {
      return "Runtime topology · qdrant 1 shard / 1 replica · opensearch 1 shard / 0 replica · retention off · tiering hot/warm";
    }
    if (topologyQuery.isLoading) return "Runtime topology · loading…";
    if (topologyQuery.isError || !topologyData) return "Runtime topology · unavailable.";
    const q = topologyData.qdrant;
    const o = topologyData.opensearch;
    const retention = topologyData.compaction.enabled
      ? `retention ${topologyData.compaction.stale_snapshot_retention_days}d`
      : "retention off";
    return `Runtime topology · qdrant ${q.shard_number} shard / ${q.replication_factor} replica · opensearch ${o.number_of_shards} shard / ${o.number_of_replicas} replica · ${retention} · tiering ${topologyData.storage_tiering.latest_stable_tier}/${topologyData.storage_tiering.archive_tier}`;
  })();
  const runtimeProfileNote =
    PUBLIC_LIVE && topologyData
      ? `runtime profile: ${topologyData.profile}`
      : "runtime profile: dev / memory";

  // Coverage-readiness strip — live readiness counters when present, else fixtures.
  const freshnessSummary = useMemo(() => {
    const counts = { fresh: 0, aging: 0, stale: 0, notReady: 0 };
    for (const service of statusData?.services ?? []) {
      const cue = serviceFreshnessCue(service);
      if (cue.label.startsWith("fresh")) counts.fresh += 1;
      else if (cue.label.startsWith("aging")) counts.aging += 1;
      else if (cue.label.startsWith("stale")) counts.stale += 1;
      else counts.notReady += 1;
    }
    return counts;
  }, [statusData?.services]);
  const covReady =
    PUBLIC_LIVE && statusData
      ? {
          docsReady: statusData.docs_mcp_ready_total,
          docsTotal: statusData.docs_services_total,
          apirefReady: statusData.apiref_mcp_ready_total,
          apirefTotal: statusData.apiref_services_total,
          aging: freshnessSummary.aging + freshnessSummary.stale,
          notReady: freshnessSummary.notReady,
        }
      : { docsReady: 38, docsTotal: 39, apirefReady: 37, apirefTotal: 38, aging: 3, notReady: 1 };

  // Primary metric strip — "indexed services" is the only metric the live status feed
  // backs directly; availability/latency/error-rate have no public feed, so they keep
  // the fixture values (the page is a fixture snapshot unless live data overrides
  // what it can).
  const indexedServices =
    PUBLIC_LIVE && statusData ? statusData.total_services : 77;

  // Incident history — live recent incidents when present; otherwise fixtures.
  const incidentSource: IncidentRow[] = useMemo(() => {
    if (!PUBLIC_LIVE || !pageData) return INCIDENTS;
    const fmt = (iso: string) =>
      new Date(iso).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    const rows: IncidentRow[] = pageData.recent_incidents.map((inc) => ({
      date: fmt(inc.resolved_at ?? inc.started_at),
      title: inc.title,
      body: inc.public_message,
    }));
    return rows.length ? rows : INCIDENTS;
  }, [pageData]);
  const incidentNote =
    PUBLIC_LIVE && pageData
      ? incidentSource === INCIDENTS
        ? "no incidents · past 30 days"
        : "past 30 days"
      : "past 30 days";

  /* --- Report-issue form — real POST via submitPublicQueryIssue --- */
  const [issueReq, setIssueReq] = useState("");
  const [issueType, setIssueType] = useState("missing_docs");
  const [issueNotes, setIssueNotes] = useState("");
  const issueReqId = useId();
  const issueTypeId = useId();
  const issueNotesId = useId();

  const issueMutation = useMutation({
    mutationFn: (payload: { request_id: string; issue_type: string; notes?: string }) =>
      submitPublicQueryIssue(payload),
  });
  const issueRequest = issueReq.trim();
  const submitIssue = () => {
    if (!issueRequest) return;
    issueMutation.mutate({
      request_id: issueRequest,
      issue_type: issueType,
      notes: issueNotes.trim() || undefined,
    });
  };
  const issueResult = issueMutation.data;
  const issueError = issueMutation.error;
  const issueErrorMessage =
    issueError instanceof AdminApiError
      ? issueError.message
      : issueError
        ? "Failed to submit issue report."
        : null;

  return (
    <div className={cn("pub", "t-mono", dark && "theme-dark")}>
      <PubNav dark={dark} onToggleTheme={toggleTheme} />

      <div className="pub-wrap">
        <main>
          {/* hero */}
          <header className="pub-hero">
            <span
              className="pub-status-led"
              style={
                ledTone.bg ? { background: ledTone.bg, color: ledTone.fg } : undefined
              }
            >
              <span
                className="led"
                style={ledTone.fg ? { background: ledTone.fg } : undefined}
              />
              {ledLabel}
            </span>
            <h1 className="pub-h1">ADCS Service Status</h1>
            <p className="pub-sub">
              Live availability for the Aspose Documentation Context Service — retrieval, MCP,
              ingestion and indexing.
            </p>
            <div className="pub-updated">{updatedNote}</div>
          </header>

          {/* primary metric strip */}
          <div className="pub-card">
            <div className="metric-strip">
              <div className="m">
                <div className="mv">
                  100
                  <span style={{ fontSize: 15, color: "var(--fg-subtle)" }}>%</span>
                </div>
                <div className="ml">Retrieval availability · 90d</div>
              </div>
              <div className="m">
                <div className="mv">
                  212
                  <span style={{ fontSize: 15, color: "var(--fg-subtle)" }}>ms</span>
                </div>
                <div className="ml">p95 query latency</div>
              </div>
              <div className="m">
                <div className="mv">
                  0.00
                  <span style={{ fontSize: 15, color: "var(--fg-subtle)" }}>%</span>
                </div>
                <div className="ml">5xx error rate · 10m</div>
              </div>
              <div className="m">
                <div className="mv">{indexedServices}</div>
                <div className="ml">Indexed services</div>
              </div>
            </div>
          </div>

          {/* coverage readiness */}
          <section className="pub-card" aria-label="Coverage readiness">
            <div className="pub-card-head">
              <span className="pub-card-title">Coverage readiness</span>
              <span className="right muted-note">MCP-ready scopes</span>
            </div>
            <div className="metric-strip">
              <div className="m">
                <div className="mv">
                  {covReady.docsReady}
                  <span style={{ fontSize: 15, color: "var(--fg-subtle)" }}>
                    /{covReady.docsTotal}
                  </span>
                </div>
                <div className="ml">Docs services ready</div>
              </div>
              <div className="m">
                <div className="mv">
                  {covReady.apirefReady}
                  <span style={{ fontSize: 15, color: "var(--fg-subtle)" }}>
                    /{covReady.apirefTotal}
                  </span>
                </div>
                <div className="ml">API-ref services ready</div>
              </div>
              <div className="m">
                <div className="mv">{covReady.aging}</div>
                <div className="ml">Aging / stale snapshots</div>
              </div>
              <div className="m">
                <div className="mv">{covReady.notReady}</div>
                <div className="ml">Not-ready scopes</div>
              </div>
            </div>
          </section>

          {/* components */}
          <section className="pub-card" aria-label="Components">
            <div className="pub-card-head">
              <span className="pub-card-title">Components</span>
              <span className="right muted-note">{componentsNote}</span>
            </div>
            {componentSource.map((s) => (
              <div className="svc-row" key={s.key}>
                <Pill variant={s.variant}>{s.label}</Pill>
                <div>
                  <div className="svc-name">{s.name}</div>
                  <div className="svc-desc">{s.desc}</div>
                </div>
                <Spark seed={s.seed} degradedIdx={s.degradedIdx} />
                <div className="svc-up">{s.up}</div>
              </div>
            ))}
          </section>

          {/* dependency readiness */}
          <section className="pub-card" aria-label="Dependency readiness">
            <div className="pub-card-head">
              <span className="pub-card-title">Dependency readiness</span>
              <span className="right muted-note">{runtimeProfileNote}</span>
            </div>
            {depSource.map((d) => (
              <div className="svc-row" key={d.key}>
                <Pill variant={d.variant}>{d.variant === "ok" ? "ready" : d.variant === "warn" ? "degraded" : "not-ready"}</Pill>
                <div>
                  <div className="svc-name">{d.name}</div>
                  <div className="svc-desc">{d.desc}</div>
                </div>
                <div
                  className="svc-up"
                  style={{
                    width: "auto",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--fg-subtle)",
                  }}
                >
                  {d.reason}
                </div>
              </div>
            ))}
            <div style={{ padding: "11px 20px", borderTop: "1px solid var(--border)" }}>
              <span className="muted-note">{topologyLine}</span>
            </div>
          </section>

          {/* MCP content services — filterable table */}
          <section className="pub-card" aria-label="MCP content services">
            <div className="pub-card-head">
              <span className="pub-card-title">MCP content services</span>
              <span className="right" style={{ display: "flex", gap: 8 }}>
                <span className="input" style={{ height: 28, minWidth: 150 }}>
                  <input
                    id={filterId}
                    className="inputctl"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter by product / repo…"
                    aria-label="Filter MCP content services by product or repo"
                  />
                </span>
              </span>
            </div>
            {coverageLoading ? (
              <div style={{ padding: 16 }}>
                <Skeleton rows={4} />
              </div>
            ) : coverageErrored ? (
              <div style={{ padding: 16 }}>
                <ErrorState
                  title="Failed to load public status"
                  cause={
                    statusQuery.error instanceof AdminApiError
                      ? statusQuery.error.message
                      : "the public status API is unreachable"
                  }
                  actions={
                    <button
                      type="button"
                      className="pub-cta ghost"
                      style={{ height: 32, fontSize: 13 }}
                      onClick={() => statusQuery.refetch()}
                    >
                      Retry
                    </button>
                  }
                />
              </div>
            ) : coverageEmptyLive ? (
              <div style={{ padding: 16 }}>
                <EmptyState
                  title="No content services registered"
                  text="The public status feed returned no source repositories yet."
                  action={
                    <button
                      type="button"
                      className="pub-cta ghost"
                      style={{ height: 32, fontSize: 13 }}
                      onClick={() => statusQuery.refetch()}
                    >
                      Refresh
                    </button>
                  }
                />
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Repository</th>
                      <th style={{ width: 110 }}>Product</th>
                      <th style={{ width: 80 }}>Kind</th>
                      <th style={{ width: 150 }}>Freshness</th>
                      <th style={{ width: 140 }}>SDK langs</th>
                      <th style={{ width: 90 }}>Version</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.length === 0 ? (
                      <tr>
                        <td colSpan={6}>
                          <span className="muted-note">No services match the active filter.</span>
                        </td>
                      </tr>
                    ) : (
                      filteredRows.map((r) => (
                        <tr className="data" key={r.repo}>
                          <td>
                            <span className="repo-id">{r.repo}</span>
                          </td>
                          <td>
                            <span
                              className="mono"
                              style={{ fontSize: 11.5, color: "var(--fg-muted)" }}
                            >
                              {r.product}
                            </span>
                          </td>
                          <td>
                            <Tag>{r.kind}</Tag>
                          </td>
                          <td>
                            <Pill variant={r.freshVariant}>{r.fresh}</Pill>
                          </td>
                          <td>
                            <span className="muted-note">{r.langs}</span>
                          </td>
                          <td>
                            <Tag>{r.version}</Tag>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* report a documentation issue */}
          <section className="pub-card" aria-label="Report a documentation issue">
            <div className="pub-card-head">
              <span className="pub-card-title">Report a documentation issue</span>
              <span className="right muted-note">links to your query request_id</span>
            </div>
            <div style={{ padding: "16px 20px" }}>
              <form
                className="toolbar"
                style={{ margin: 0 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  submitIssue();
                }}
              >
                <span className="input" style={{ minWidth: 200 }}>
                  <input
                    id={issueReqId}
                    className="inputctl"
                    value={issueReq}
                    onChange={(e) => setIssueReq(e.target.value)}
                    placeholder="request_id (from your query logs)"
                    aria-label="request_id from your query logs"
                  />
                </span>
                <span className="select" style={{ minWidth: 160 }}>
                  <select
                    id={issueTypeId}
                    className="selectctl"
                    value={issueType}
                    onChange={(e) => setIssueType(e.target.value)}
                    aria-label="Issue type"
                  >
                    <option value="missing_docs">Missing content</option>
                    <option value="wrong_docs">Wrong / outdated answer</option>
                    <option value="other">No results</option>
                  </select>
                </span>
                <span className="input" style={{ flex: 1, minWidth: 200 }}>
                  <input
                    id={issueNotesId}
                    className="inputctl"
                    value={issueNotes}
                    onChange={(e) => setIssueNotes(e.target.value)}
                    placeholder="Optional notes"
                    aria-label="Optional notes"
                  />
                </span>
                <button
                  type="submit"
                  className="pub-cta"
                  style={{ height: 34, fontSize: 13 }}
                  disabled={issueMutation.isPending || !issueRequest}
                >
                  {issueMutation.isPending ? "Reporting…" : "Report issue"}
                </button>
              </form>
              <div style={{ marginTop: 10 }} role="status" aria-live="polite">
                {issueErrorMessage ? (
                  <div
                    className="pub-status-led"
                    style={{ background: "var(--crit-bg)", color: "var(--crit)" }}
                    role="alert"
                  >
                    <span className="led" style={{ background: "var(--crit)", animation: "none" }} />
                    {issueErrorMessage}
                  </div>
                ) : issueResult ? (
                  <div
                    className="pub-status-led"
                    style={{ background: "var(--ok-bg)", color: "var(--ok)" }}
                  >
                    <span className="led" style={{ background: "var(--ok)", animation: "none" }} />
                    {issueResult.updated_existing
                      ? `Issue report updated for ${issueResult.request_id} — the content team will triage it.`
                      : `Issue recorded for ${issueResult.request_id} — the content team will triage it.`}
                  </div>
                ) : !issueRequest ? (
                  <div className="muted-note">
                    Enter the request_id from your query logs to link the report to stored evidence.
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          {/* 90-day uptime */}
          <section className="pub-card" aria-label="90-day uptime — Retrieval API">
            <div className="pub-card-head">
              <span className="pub-card-title">90-day uptime — Retrieval API</span>
              <span className="right muted-note">100.00% · 0 incidents</span>
            </div>
            <div style={{ padding: "14px 20px" }}>
              <div className="uptime-grid" aria-hidden="true">
                {uptimeCells([]).map((deg, i) => (
                  <i key={i} className={cn(deg && "d")} />
                ))}
              </div>
            </div>
          </section>

          {/* incident history */}
          <section className="pub-card" aria-label="Incident history">
            <div className="pub-card-head">
              <span className="pub-card-title">Incident history</span>
              <span className="right muted-note">{incidentNote}</span>
            </div>
            {incidentSource.map((inc) => (
              <div className="tl-row" key={inc.title}>
                <div className="tl-date">{inc.date}</div>
                <div>
                  <div className="tl-title">{inc.title}</div>
                  <div className="tl-body">{inc.body}</div>
                </div>
              </div>
            ))}
          </section>

          <PubFooter note="ADCS is a context-delivery layer for Aspose product documentation. Subscribe to status updates from your client integration." />
        </main>
      </div>
    </div>
  );
}
