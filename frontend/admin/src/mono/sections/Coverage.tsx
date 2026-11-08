"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useHealthQueries } from "@/hooks/useHealthQueries";
import type { AdminContentServiceHealth, PublicContentTriage } from "@/lib/admin-api";

import { Banner, type BannerProps } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Kpi, KpiRow } from "../components/Kpi";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { Input, Segmented, Select } from "../components/Field";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";

// ───────────────────────────────────────────────────────────────── Fixtures ──

type CovReason = "no_recent_runtime_signal" | "no_index_data";

interface CovRepo {
  id: string;
  kind: "apiref" | "docs";
  reason: CovReason;
  /** [chunks, snippets, stale-label] */
  sig: [number, number, string];
  last: string;
  open?: boolean;
  /** Live overlay (present when bound to the content-services overview). */
  live?: CovRepoLive;
}

/** Live per-repo overlay sourced from AdminContentServiceHealth; absent in offline fixtures. */
interface CovRepoLive {
  status: StatusVariant;
  statusLabel: string;
  ready: boolean;
  /**
   * Previously ingested but no longer MCP-ready (onboarding_status != pending_first_ingestion).
   * Distinguishes the "not-ready" (degraded) state from "pending" (never ingested).
   */
  notReady: boolean;
  /** latest_operation_status (e.g. "success"/"failed"); "none" when no run has finished. */
  lastStatus: string;
  reasonLabel: string;
  reasonText: string;
  fixSteps: string[];
  langs: string;
  versions: string;
  layout: string;
  fresh: string;
  gitUrl: string;
  /** Per-repo diagnostics. */
  scopesCount: number;
  snapshotId: string;
  snapshotCreated: string;
  defaultBranch: string;
  submodulePath: string;
  parseWarnings: number;
  failedItems: number;
}

interface CovGroup {
  product: string;
  dir: string;
  repos: CovRepo[];
}

const COV_GROUPS: CovGroup[] = [
  {
    product: "aspose.3d",
    dir: "Aspose.3D",
    repos: [
      {
        id: "aspose.3d.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
        open: true,
      },
    ],
  },
  {
    product: "aspose.barcode",
    dir: "Aspose.BarCode",
    repos: [
      {
        id: "aspose.barcode.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
      {
        id: "aspose.barcode.docs",
        kind: "docs",
        reason: "no_index_data",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
  {
    product: "aspose.cad",
    dir: "Aspose.CAD",
    repos: [
      {
        id: "aspose.cad.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
      {
        id: "aspose.cad.docs",
        kind: "docs",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
  {
    product: "aspose.cells",
    dir: "Aspose.Cells",
    repos: [
      {
        id: "aspose.cells.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
      {
        id: "aspose.cells.docs",
        kind: "docs",
        reason: "no_index_data",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
  {
    product: "aspose.ocr",
    dir: "Aspose.OCR",
    repos: [
      {
        id: "aspose.ocr.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
      {
        id: "aspose.ocr.docs",
        kind: "docs",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
  {
    product: "aspose.words",
    dir: "Aspose.Words",
    repos: [
      {
        id: "aspose.words.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
  {
    product: "groupdocs.parser",
    dir: "GroupDocs.Parser",
    repos: [
      {
        id: "groupdocs.parser.apiref",
        kind: "apiref",
        reason: "no_recent_runtime_signal",
        sig: [0, 0, "n/a"],
        last: "never",
      },
      {
        id: "groupdocs.parser.docs",
        kind: "docs",
        reason: "no_index_data",
        sig: [0, 0, "n/a"],
        last: "never",
      },
    ],
  },
];

const COV_REASON: Record<CovReason, string> = {
  no_recent_runtime_signal:
    "No recent runtime signal exists, so the service cannot prove MCP readiness yet.",
  no_index_data:
    "No normalized chunk records were found, so retrieval cannot return content from this repository.",
};

const COV_FIX: Record<CovReason, string[]> = {
  no_recent_runtime_signal: [
    "Run layout detection, then a Validate-Only ingestion if this repo was onboarded recently.",
    "Publish an active snapshot for this source kind if none exists yet.",
    "Run a public query or smoke test to confirm live runtime traffic.",
  ],
  no_index_data: [
    "Run Validate-Only and inspect the review workspace for chunk output.",
    "Confirm the parser produced normalized chunks before publishing.",
  ],
};

const COV_KLANG: Record<CovRepo["kind"], string> = {
  apiref: "net, java, python",
  docs: "net, java",
};

function covMeta(r: CovRepo) {
  const never = r.last === "never";
  const fresh = never ? "not-ready · no active snapshot" : "active snapshot age 45d";
  // API limitation (offline only): the live overlay carries real scopes/snapshot/branch/parse counts;
  // these fixture values keep the diagnostics panel fully populated with no backend.
  return {
    fresh,
    langs: COV_KLANG[r.kind] ?? "net",
    versions: "latest-stable",
    layout: r.reason === "no_index_data" ? "standard · 0.42" : "auto-detect · n/a",
    scopesCount: r.kind === "apiref" ? 3 : 2,
    snapshotId: never ? "none" : `snap_${r.id.split(".").slice(-2).join("_")}_45d`,
    snapshotCreated: never ? "—" : "45d ago",
    defaultBranch: "main",
    submodulePath: `source-repo-${r.id}/`,
    parseWarnings: r.reason === "no_index_data" ? 4 : 0,
    failedItems: r.reason === "no_index_data" ? 2 : 0,
  };
}

// Days after which an active snapshot is considered stale (presented as a labeled field).
const STALE_THRESHOLD_DAYS = 30;

// ── Service Health Mix (healthy / warning / critical / unknown breakdown) ──
type HealthMixKey = "healthy" | "warning" | "critical" | "unknown";

interface HealthMixDatum {
  key: HealthMixKey;
  label: string;
  variant: StatusVariant;
}

const HEALTH_MIX_DEFS: HealthMixDatum[] = [
  { key: "healthy", label: "healthy", variant: "ok" },
  { key: "warning", label: "warning", variant: "warn" },
  { key: "critical", label: "critical", variant: "crit" },
  { key: "unknown", label: "unknown", variant: "neutral" },
];

// API limitation (offline only): live counts come from the overview; this fixture mirrors the
// offline banner ("1 degraded · 76 awaiting first ingestion") so the mix tile is coherent.
const HEALTH_MIX_FIXTURE: Record<HealthMixKey, number> = {
  healthy: 0,
  warning: 1,
  critical: 0,
  unknown: 76,
};

const COV_PRODUCTS = [
  "All products",
  "aspose.3d",
  "aspose.barcode",
  "aspose.cad",
  "aspose.cells",
  "aspose.ocr",
  "aspose.words",
  "groupdocs.parser",
];

type Sev = "crit" | "warn" | "info";

const SEV_WORD: Record<Sev, string> = { crit: "critical", warn: "warning", info: "info" };

// Maps the table severity segmented index onto a service-row Sev (0 = no severity filter).
const SEV_FILTER_BY_TAB: (Sev | null)[] = [null, "crit", "warn", "info"];

interface TriageItem {
  /** Stable React key — live feed `gap_id` (unique per gap); fixtures fall back to repo+signal. */
  id: string;
  sigt: string;
  repo: string;
  sev: Sev;
  detail: string;
  fix: string;
}

const TRIAGE: TriageItem[] = [
  {
    id: "aspose.3d.apiref:missing_chunks",
    sigt: "missing_chunks",
    repo: "aspose.3d.apiref",
    sev: "crit",
    detail: "0 indexed chunks · never ingested",
    fix: "Onboard & publish — no snapshot exists.",
  },
  {
    id: "aspose.barcode.docs:missing_chunks",
    sigt: "missing_chunks",
    repo: "aspose.barcode.docs",
    sev: "crit",
    detail: "0 indexed chunks · no_index_data",
    fix: "Run Validate-Only, confirm chunk output.",
  },
  {
    id: "aspose.ocr.apiref:stale_snapshot",
    sigt: "stale_snapshot",
    repo: "aspose.ocr.apiref",
    sev: "warn",
    detail: "active snapshot age 45d (> 30d target)",
    fix: "Reingest to refresh the active snapshot.",
  },
  {
    id: "aspose.cells.docs:missing_snippets",
    sigt: "missing_snippets",
    repo: "aspose.cells.docs",
    sev: "warn",
    detail: "0 executable snippets in 1 240 chunks",
    fix: "Re-parse with code-block extraction.",
  },
  {
    id: "aspose.cad.docs:stale_snapshot",
    sigt: "stale_snapshot",
    repo: "aspose.cad.docs",
    sev: "info",
    detail: "active snapshot age 12d",
    fix: "Monitor; below stale threshold.",
  },
];

// The triage list renders at most 5 items.
const TRIAGE_MAX_ITEMS = 5;

const SEVP: Record<Sev, "crit" | "warn" | "info"> = { crit: "crit", warn: "warn", info: "info" };

const TOTAL_SERVICES = 77;
const VISIBLE_GROUPS = 3;
const TABLE_COLS = 7;

const ALL_PRODUCTS = "All products";

// ─────────────────────────────────────────────── Live → render-shape mappers ──

function svcStatusVariant(status: string): StatusVariant {
  if (status === "healthy" || status === "ready" || status === "ok") return "ok";
  if (status === "warning" || status === "degraded") return "warn";
  if (status === "critical" || status === "down" || status === "error") return "crit";
  return "neutral";
}

function svcKind(sourceKind: string): CovRepo["kind"] {
  return sourceKind === "docs" ? "docs" : "apiref";
}

/** Map one live content-service row onto the section's CovRepo render shape. */
function toCovRepo(service: AdminContentServiceHealth): CovRepo {
  const kind = svcKind(service.source_kind);
  const ready = service.mcp_ready;
  const last = service.latest_operation_finished_at
    ? service.latest_operation_finished_at.slice(0, 10)
    : "never";
  return {
    id: service.repo_id,
    kind,
    // Keep a valid fixture-union value for offline fallback paths; live text comes from `live`.
    reason: kind === "docs" ? "no_index_data" : "no_recent_runtime_signal",
    // API limitation: AdminContentServiceHealth carries no per-repo chunk/snippet/stale counts, so the
    // Signals column cannot be populated from the overview feed. Real counts surface per-gap in
    // the triage feed (indexed_chunks_count / executable_snippets_count / stale_days), not here.
    sig: [0, 0, "n/a"],
    last,
    live: {
      status: svcStatusVariant(service.service_status),
      statusLabel: service.service_status,
      ready,
      // not-ready (degraded) vs pending (never ingested): a previously-ingested service
      // that lost readiness is "not-ready"; one awaiting its first run is "pending".
      notReady: !ready && service.onboarding_status !== "pending_first_ingestion",
      lastStatus: service.latest_operation_status || "none",
      reasonLabel: service.service_status_reason || "unknown_reason",
      reasonText: service.service_status_summary || COV_REASON.no_recent_runtime_signal,
      fixSteps: service.fix_plan,
      langs: service.supported_programming_languages.join(", ") || COV_KLANG[kind],
      versions: service.supported_versions.join(", ") || "latest-stable",
      layout:
        service.layout_type != null
          ? `${service.layout_type}${
              service.layout_confidence != null ? ` · ${service.layout_confidence}` : ""
            }`
          : "auto-detect · n/a",
      fresh: service.active_snapshot_created_at
        ? `active snapshot since ${service.active_snapshot_created_at.slice(0, 10)}`
        : "not-ready · no active snapshot",
      gitUrl: service.git_url,
      scopesCount: service.active_scopes_count,
      snapshotId: service.active_snapshot_id ?? "none",
      snapshotCreated: service.active_snapshot_created_at
        ? service.active_snapshot_created_at.slice(0, 10)
        : "—",
      defaultBranch: service.default_branch || "main",
      submodulePath: service.submodule_path || "—",
      parseWarnings: service.parse_warnings_count,
      failedItems: service.failed_items_count,
    },
  };
}

/** Group live rows by product into the section's CovGroup shape (dir = product family dir). */
function toCovGroups(services: AdminContentServiceHealth[]): CovGroup[] {
  const byProduct = new Map<string, CovGroup>();
  for (const service of services) {
    let group = byProduct.get(service.product_id);
    if (!group) {
      group = {
        product: service.product_id,
        dir: service.product_family_dir || service.product_family || service.product_id,
        repos: [],
      };
      byProduct.set(service.product_id, group);
    }
    group.repos.push(toCovRepo(service));
  }
  return [...byProduct.values()];
}

/**
 * Severity of a service ROW — the key of the toolbar severity segmented, i.e. exactly what
 * its labels promise. Every offline sample row counts as a "warning"
 * severity gap (labels read Critical 0 / Warning 12 / Info 0; Critical/Info empty the
 * table). Live rows derive from the service status; healthy MCP-ready rows carry no
 * coverage gap and appear only under "All gaps".
 */
function svcSeverity(repo: CovRepo): Sev | null {
  const live = repo.live;
  if (!live) return "warn"; // offline fixtures: all sample rows are warning severity
  if (live.status === "crit") return "crit";
  if (live.status === "warn") return "warn";
  if (live.status === "info") return "info";
  if (live.status === "ok" && live.ready) return null; // healthy & ready — no gap
  return "warn"; // unknown / awaiting-first-ingestion rows are warning-class gaps
}

/** Map the live triage feed onto the section's TriageItem render shape. */
function toTriageItems(items: PublicContentTriage["items"]): TriageItem[] {
  return items.map((it) => ({
    // gap_id is unique per gap, so a single repo emitting multiple gaps (e.g.
    // missing_chunks + stale_snapshot) never collides React keys.
    id: it.gap_id || `${it.repo_id}:${it.signal_type}`,
    sigt: it.signal_type,
    repo: it.repo_id,
    sev: it.severity === "critical" ? "crit" : it.severity === "warning" ? "warn" : "info",
    detail: it.summary,
    fix: it.fix_plan[0] ?? "Review remediation plan in the services table.",
  }));
}

// Clickable wrapper that keeps the `.kpi` visual but smooth-scrolls to the table.
function TileButton({
  onClick,
  ariaLabel,
  children,
}: {
  onClick: () => void;
  ariaLabel: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      style={{
        background: "none",
        border: 0,
        padding: 0,
        margin: 0,
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        display: "block",
        width: "100%",
      }}
    >
      {children}
    </button>
  );
}

// Service Health Mix tile — the four status counts as the closed-palette pills.
function HealthMixTile({ mix }: { mix: Record<HealthMixKey, number> }) {
  const total = HEALTH_MIX_DEFS.reduce((n, d) => n + mix[d.key], 0);
  return (
    <Kpi
      label="Service health mix"
      value={String(total)}
      foot={
        <span className="signals" style={{ flexWrap: "wrap", gap: 6 }}>
          {HEALTH_MIX_DEFS.map((d) => (
            <Pill key={d.key} variant={d.variant}>
              {d.label} {mix[d.key]}
            </Pill>
          ))}
        </span>
      }
    />
  );
}

// ───────────────────────────────────────────────────────────── Component ────

export function CoverageSection() {
  const { navigate, consumeIntent } = useShell();
  const data = useAdminData();
  const { toast } = useToast();
  const tableRef = useRef<HTMLDivElement>(null);
  const cov = useHealthQueries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "content-coverage",
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    canConfigureAbuseGuard: data.can("write:settings"),
  });

  // Scope gates. Running/validating ingestion is a write op.
  const canRunIngestion = data.can("write:ingestion");

  // Live content-services overview is the section's primary feed; fixtures wholesale when offline.
  const overview = cov.contentServicesOverview;
  const liveRows = cov.filteredContentServicesRows;
  const hasLiveRows = liveRows.length > 0;

  const [sevTab, setSevTab] = useState(0); // table severity segmented (visual)
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      COV_GROUPS.flatMap((g) => g.repos).filter((r) => r.open).map((r) => [r.id, true]),
    ),
  );
  // Collapsed product groups — clicking a group header hides its child rows,
  // rotates the chevron -90°, and detail rows stay closed when the group is re-expanded.
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const toggleGroup = (group: CovGroup) => {
    const collapsing = !collapsedGroups[group.product];
    setCollapsedGroups((c) => ({ ...c, [group.product]: collapsing }));
    if (collapsing) {
      setOpen((o) => {
        const next = { ...o };
        for (const r of group.repos) next[r.id] = false;
        return next;
      });
    }
  };

  // Filters live on the hook so changing them recomputes its derived rows + triage query.
  const product = cov.contentServiceProductFilter || ALL_PRODUCTS;
  const repoFilter = cov.contentServiceRepoFilter;
  const setProduct = (value: string) =>
    cov.setContentServiceProductFilter(value === ALL_PRODUCTS ? "" : value);
  const setRepoFilter = cov.setContentServiceRepoFilter;
  const productOptions = cov.contentServiceProductOptions.length
    ? [ALL_PRODUCTS, ...cov.contentServiceProductOptions]
    : COV_PRODUCTS;

  // Triage severity tab drives the hook's triage filter (API severity terms ↔ section Sev).
  const triageSev: Sev | "all" =
    cov.contentTriageSeverityFilter === "critical"
      ? "crit"
      : cov.contentTriageSeverityFilter === "warning"
        ? "warn"
        : cov.contentTriageSeverityFilter === "info"
          ? "info"
          : "all";
  const setTriageSev = (sev: Sev | "all") =>
    cov.setContentTriageSeverityFilter(
      sev === "crit" ? "critical" : sev === "warn" ? "warning" : sev === "info" ? "info" : "",
    );

  // Cross-section prefill handoff: drain the one-shot SectionIntent stashed by a source
  // section via navigate("coverage", anchor, { filters, reset }). Runs once on mount;
  // consumeIntent is one-shot (auto-clears), so the empty dep array guards re-apply.
  // ("coverage" is this section's Mono SectionKey — the hook's "content-coverage" id is
  // remapped to it for navigation; see Campaigns.tsx TARGET_SECTION_KEY.)
  useEffect(() => {
    const intent = consumeIntent("coverage");
    if (!intent?.filters) return;
    const f = intent.filters;
    // reset:true clears existing filters before applying the incoming ones.
    if (intent.reset) {
      setProduct(ALL_PRODUCTS);
      setRepoFilter("");
      setSevTab(0);
      setTriageSev("all");
      setShowAll(false);
    }
    // product -> product filter setter ("All products"/""/"all" clear it; else pass through).
    if (f.product != null) {
      const p = f.product;
      setProduct(p === "" || p.toLowerCase() === "all" ? ALL_PRODUCTS : p);
      setShowAll(false);
    }
    // severity -> triage severity segmented (accept short "crit/warn/info" or long forms).
    if (f.severity != null) {
      const s = f.severity.toLowerCase();
      const sev: Sev | "all" | null =
        s === "crit" || s === "critical"
          ? "crit"
          : s === "warn" || s === "warning"
            ? "warn"
            : s === "info"
              ? "info"
              : s === "all" || s === ""
                ? "all"
                : null; // unknown severity value — ignore gracefully
      if (sev) setTriageSev(sev);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const q = repoFilter.trim().toLowerCase();

  // Table severity segmented → active Sev filter for the services table.
  const tableSev = SEV_FILTER_BY_TAB[sevTab] ?? null;

  const liveTriageData = cov.contentTriageQuery.data;

  // ONLINE (session established): live rows only — an empty live result stays empty so the
  // empty state renders (never substitute fixtures). OFFLINE: fixtures, filtered
  // client-side. The hook already filters live rows by product/repo-id.
  const baseGroups = useMemo(
    () =>
      hasLiveRows || data.sessionIsSuccess
        ? toCovGroups(liveRows)
        : COV_GROUPS.map((g) => {
            const repos = g.repos.filter((r) => !q || r.id.toLowerCase().includes(q));
            return { ...g, repos };
          }).filter((g) => {
            if (product !== ALL_PRODUCTS && g.product !== product) return false;
            return g.repos.length > 0;
          }),
    [hasLiveRows, data.sessionIsSuccess, liveRows, product, q],
  );

  // Service-severity counts for the current scope keep the segmented labels' promise true:
  // the offline fixtures yield "Critical 0 / Warning 12 / Info 0".
  const sevCounts = useMemo(() => {
    const counts: Record<Sev, number> = { crit: 0, warn: 0, info: 0 };
    for (const g of baseGroups)
      for (const r of g.repos) {
        const sev = svcSeverity(r);
        if (sev) counts[sev] += 1;
      }
    return counts;
  }, [baseGroups]);
  const sevOptions = [
    "All gaps",
    `Critical ${sevCounts.crit}`,
    `Warning ${sevCounts.warn}`,
    `Info ${sevCounts.info}`,
  ];

  // Severity segmented filters BOTH modes client-side on each row's own service severity.
  const groups = useMemo(() => {
    if (!tableSev) return baseGroups;
    return baseGroups
      .map((g) => ({ ...g, repos: g.repos.filter((r) => svcSeverity(r) === tableSev) }))
      .filter((g) => g.repos.length > 0);
  }, [baseGroups, tableSev]);

  const filtered = product !== ALL_PRODUCTS || q.length > 0 || tableSev !== null;
  const shownGroups = showAll || filtered ? groups : groups.slice(0, VISIBLE_GROUPS);
  const hiddenCount = filtered ? 0 : groups.length - shownGroups.length;
  const shownRepoCount = shownGroups.reduce((n, g) => n + g.repos.length, 0);
  const totalServices = overview?.total_services ?? TOTAL_SERVICES;
  // A severity selection with no matching rows swaps the caption for a
  // dedicated "No <severity> gaps in the current scope" message.
  // The filtered caption names the selected product (e.g. "· aspose.ocr");
  // it falls back to a generic "· filtered" for repo-id / severity-only scopes.
  const filterScopeLabel = product !== ALL_PRODUCTS ? product : "filtered";
  const totalShownLabel =
    tableSev && shownRepoCount === 0
      ? `No ${SEV_WORD[tableSev]} gaps in the current scope`
      : filtered
        ? `Showing ${shownRepoCount} of ${totalServices} services · ${filterScopeLabel}`
        : `Showing ${shownRepoCount} of ${totalServices} services · grouped by product`;

  // Triage feed: live items mapped to render shape, fixtures as fallback. The section caps the
  // rendered list at 5 items, so a large live feed never produces an unbounded list.
  const triageItems = (
    liveTriageData
      ? toTriageItems(liveTriageData.items)
      : TRIAGE.filter((t) => triageSev === "all" || t.sev === triageSev)
  ).slice(0, TRIAGE_MAX_ITEMS);
  const triageDown = cov.contentTriageQuery.isError && !liveTriageData;
  // Stale-snapshot threshold — live value from the triage feed, fixture constant offline.
  const staleThresholdDays = liveTriageData?.stale_after_days ?? STALE_THRESHOLD_DAYS;
  // Severity-tab counts — live totals from the triage feed when present (so they track the
  // live-filtered results), else the fixture counts the offline TRIAGE sample carries.
  const triageTabCounts: Record<Sev, number> = liveTriageData
    ? {
        crit: liveTriageData.critical_total,
        warn: liveTriageData.warning_total,
        info: liveTriageData.info_total,
      }
    : { crit: 2, warn: 2, info: 1 };
  const triageTabs: { label: string; sev: Sev | "all" }[] = [
    { label: "All", sev: "all" },
    { label: `Critical ${triageTabCounts.crit}`, sev: "crit" },
    { label: `Warning ${triageTabCounts.warn}`, sev: "warn" },
    { label: `Info ${triageTabCounts.info}`, sev: "info" },
  ];
  // Status summary alert: a live one-line gap summary above the triage items. It
  // escalates when critical_total>0; the Banner kit has no crit variant
  // (palette ok/warn/info), so warn is the strongest expressible escalation here.
  const triageSummary = liveTriageData?.status_summary;
  const triageSummaryVariant: BannerProps["variant"] =
    liveTriageData && liveTriageData.critical_total > 0 ? "warn" : "info";

  // Primary-query states (only block the table when there is nothing to show).
  const servicesLoading = cov.contentServicesQuery.isLoading && !hasLiveRows;
  const servicesError = cov.contentServicesQuery.isError && !hasLiveRows;

  // KPI / banner numbers — live overview totals, fixture copy when offline.
  const kReady = overview ? cov.readyServicesTotal : 0;
  const kTotal = overview?.total_services ?? 77;
  const kDocsReady = overview?.docs_mcp_ready_total ?? 0;
  const kDocsTotal = overview?.docs_services_total ?? 38;
  const kApirefReady = overview?.apiref_mcp_ready_total ?? 0;
  const kApirefTotal = overview?.apiref_services_total ?? 39;
  const kDegraded = overview ? cov.filteredWarningCount : 1;
  const kAwaiting = overview?.pending_first_ingestion_total ?? 76;
  const bannerTitle = overview
    ? `${kTotal} services indexed · ${kDegraded} degraded · ${kAwaiting} awaiting first ingestion`
    : "77 services indexed · 1 degraded · 76 awaiting first ingestion";

  // Service Health Mix — live overview counts when present, fixture mix offline.
  const healthMix: Record<HealthMixKey, number> = overview
    ? {
        healthy: cov.filteredHealthyCount,
        warning: cov.filteredWarningCount,
        critical: cov.filteredCriticalCount,
        unknown: cov.filteredUnknownCount,
      }
    : HEALTH_MIX_FIXTURE;
  const degradedTotal = healthMix.warning + healthMix.critical;
  const topAffectedRepo =
    cov.topNotReadyService?.repo_id ?? shownGroups[0]?.repos[0]?.id ?? "aspose.ocr.apiref";
  // This alert escalates when any critical service exists. The Mono Banner kit's palette
  // is ok/warn/info only (no crit), so warn is the strongest expressible variant.
  const coverageBannerVariant: BannerProps["variant"] = "warn";
  // Next step — pull the most-affected service's first fix-plan step when live;
  // fixture copy ("re-publish the active snapshot") otherwise.
  const recommendedNextStep =
    cov.topNotReadyService?.fix_plan?.[0] ?? "re-publish the active snapshot or validate the parser";

  // Smooth-scroll any summary tile to the services table (tiles are clickable).
  const scrollToTable = () =>
    tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  // CSV export of the currently-displayed services (data export for reporting).
  const exportRows = shownGroups.flatMap((g) =>
    g.repos.map((r) => {
      const m = covMeta(r);
      const l = r.live;
      return {
        repo_id: r.id,
        product: g.product,
        source_kind: r.kind,
        status: l?.statusLabel ?? "unknown",
        mcp_ready: l?.ready ? "ready" : "pending",
        active_snapshot_id: l?.snapshotId ?? m.snapshotId,
        active_scopes: String(l?.scopesCount ?? m.scopesCount),
        parse_warnings: String(l?.parseWarnings ?? m.parseWarnings),
        failed_items: String(l?.failedItems ?? m.failedItems),
        default_branch: l?.defaultBranch ?? m.defaultBranch,
        last_ingest: r.last,
      };
    }),
  );
  const exportCsv = () => {
    const cols = Object.keys(
      exportRows[0] ?? {
        repo_id: "",
        product: "",
        source_kind: "",
        status: "",
        mcp_ready: "",
        active_snapshot_id: "",
        active_scopes: "",
        parse_warnings: "",
        failed_items: "",
        default_branch: "",
        last_ingest: "",
      },
    );
    const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
    const lines = [
      cols.join(","),
      ...exportRows.map((row) => cols.map((c) => esc(String((row as Record<string, string>)[c]))).join(",")),
    ];
    const csv = lines.join("\n");
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(csv).catch(() => undefined);
    }
    if (typeof document !== "undefined") {
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "content-coverage-services.csv";
      a.click();
      URL.revokeObjectURL(url);
    }
    toast(`Copied ${exportRows.length} services to clipboard + CSV`);
  };

  const head = (
    <PageHead
      title="Content Coverage"
      sub="Registered documentation & API-reference services, their MCP readiness, and coverage-gap triage."
      onHelp={() => {
        window.location.href = "/howto";
      }}
      actions={
        <>
          <ScopeChip label="role" value={data.session?.is_superuser ? "superuser" : "operator"} dot />
          <ScopeChip label="scope" value="aspose.ocr" />
          <Button
            variant="btn-ghost"
            size="sm"
            icon="refresh"
            onClick={() => {
              cov.contentServicesQuery.refetch();
              cov.contentTriageQuery.refetch();
            }}
          >
            Refresh
          </Button>
        </>
      }
    />
  );

  // ── Error state (coverage feed unavailable — tiles/table/triage hidden) ──
  if (servicesError) {
    return (
      <>
        {head}
        <ErrorState
          title="MCP coverage feed is unavailable"
          text={
            <>
              The content services overview could not be loaded, so no cached data is shown.{" "}
              <b>Next step:</b> retry the coverage feed; if it still fails, inspect Logs &amp; Traces
              for the request id. <b>Escalation:</b> if retries keep failing, page the on-call
              platform engineer — the backend overview build is likely down.
            </>
          }
          cause="Qdrant timeout, snapshot registry read error, or an expired admin key."
          actions={
            <>
              <Button
                variant="btn-primary"
                size="sm"
                icon="refresh"
                onClick={() => cov.contentServicesQuery.refetch()}
              >
                Retry coverage
              </Button>
              <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
                Open Logs &amp; Traces
              </Button>
            </>
          }
        />
      </>
    );
  }

  // ── Happy path (+ loading via skeleton-less progressive states) ──
  return (
    <>
      {head}

      {/* Explanation caption — the ready/total convention + status-color semantics. */}
      <p className="muted-note" style={{ margin: "0 0 12px" }}>
        Coverage counters are shown as MCP-ready/total. A service is considered MCP-ready when it
        has an active snapshot for its source kind (<span className="mono">docs</span> or{" "}
        <span className="mono">apiref</span>). Status colors in the table reflect ingestion activity
        and snapshot signals.
      </p>

      <Banner
        variant={coverageBannerVariant}
        icon="alert"
        title={bannerTitle}
        text={
          <>
            {degradedTotal > 0 ? (
              <>
                <b>{degradedTotal}</b> service{degradedTotal === 1 ? "" : "s"} degraded · most
                affected <span className="mono">{topAffectedRepo}</span>. Recommended next step:{" "}
                <b>{recommendedNextStep}</b>.{" "}
              </>
            ) : null}
            Most gaps share one cause: <b>no recent runtime signal</b>. Onboard or run Validate-Only
            to make these scopes MCP-ready — no per-row action needed.
          </>
        }
        actions={
          <>
            <Button variant="btn-ghost" size="sm">
              Recovery How-To
            </Button>
            <Button variant="btn-ghost" size="sm" icon="bell" onClick={() => navigate("critical")}>
              Open Critical Events
            </Button>
            <Button
              variant="btn-primary"
              size="sm"
              icon="arrow"
              onClick={() => navigate("ingestion")}
            >
              Open Ingestion Jobs
            </Button>
          </>
        }
      />

      {kAwaiting > 0 && (
        <Banner
          variant="info"
          icon="info"
          title={`${kAwaiting} service${kAwaiting === 1 ? "" : "s"} are awaiting first ingestion`}
          text="These products are registered in the catalog but have never been ingested. Run ingestion to make them MCP-ready."
          actions={
            <Button
              variant="btn-ghost"
              size="sm"
              icon="arrow"
              onClick={() => navigate("ingestion")}
            >
              Open Ingestion Jobs
            </Button>
          }
        />
      )}

      <KpiRow cols={5}>
        <TileButton onClick={scrollToTable} ariaLabel="MCP-ready services — scroll to services table">
          <Kpi
            label="MCP-Ready"
            value={
              <>
                {kReady}
                <small>/{kTotal}</small>
              </>
            }
            foot={`${kAwaiting} pending first ingestion`}
          />
        </TileButton>
        <TileButton
          onClick={scrollToTable}
          ariaLabel="Documentation services ready — scroll to services table"
        >
          <Kpi
            label="Docs services"
            value={
              <>
                {kDocsReady}
                <small>/{kDocsTotal}</small>
              </>
            }
            foot="ready / total"
          />
        </TileButton>
        <TileButton
          onClick={scrollToTable}
          ariaLabel="API reference services ready — scroll to services table"
        >
          <Kpi
            label="API reference"
            value={
              <>
                {kApirefReady}
                <small>/{kApirefTotal}</small>
              </>
            }
            foot="ready / total"
          />
        </TileButton>
        <TileButton
          onClick={scrollToTable}
          ariaLabel="Service health mix — scroll to services table"
        >
          <HealthMixTile mix={healthMix} />
        </TileButton>
        <TileButton
          onClick={scrollToTable}
          ariaLabel="Services awaiting first ingestion — scroll to services table"
        >
          <Kpi label="Awaiting" value={String(kAwaiting)} foot="never ingested" />
        </TileButton>
      </KpiRow>

      <div className="toolbar">
        <Select
          width={180}
          options={productOptions}
          value={product}
          aria-label="Filter by product"
          onChange={(e) => {
            setProduct(e.target.value);
            setShowAll(false);
          }}
        />
        <Input
          width={190}
          placeholder="Filter by repo id…"
          value={repoFilter}
          aria-label="Filter by repository id"
          onChange={(e) => setRepoFilter(e.target.value)}
        />
        <Segmented
          options={sevOptions}
          active={sevTab}
          onChange={setSevTab}
          ariaLabel="Filter table by severity"
        />
        <div className="toolbar-right">
          <span className="muted-note" id="cov-count">
            {totalShownLabel}
          </span>
          {/* The control stays in the toolbar and announces its disabled state to AT
              when no filter is active (rather than disappearing until needed). */}
          <Button
            variant="btn-ghost"
            size="sm"
            icon="x"
            disabled={!filtered}
            onClick={() => {
              setProduct(ALL_PRODUCTS);
              setRepoFilter("");
              setSevTab(0);
              setShowAll(false);
            }}
          >
            Clear filters
          </Button>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="download"
            onClick={exportCsv}
            disabled={exportRows.length === 0}
            title="Copy the displayed services to the clipboard and download a CSV for reporting"
          >
            Export CSV
          </Button>
        </div>
      </div>

      <div className="tablecard" ref={tableRef}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 96 }}>Status</th>
              <th>Repository</th>
              <th style={{ width: 74 }}>Kind</th>
              <th style={{ width: 104 }}>MCP ready</th>
              <th style={{ width: 170 }}>Reason</th>
              <th style={{ width: 210 }}>Signals</th>
              <th className="num" style={{ width: 92 }}>
                Last ingest
              </th>
            </tr>
          </thead>
          <tbody>
            {servicesLoading ? (
              <tr>
                <td colSpan={TABLE_COLS}>
                  <div style={{ padding: 16 }}>
                    <Skeleton rows={5} />
                  </div>
                </td>
              </tr>
            ) : shownRepoCount === 0 ? (
              <tr>
                <td colSpan={TABLE_COLS}>
                  <EmptyState
                    title={
                      tableSev
                        ? `No ${SEV_WORD[tableSev]} gaps in the current scope`
                        : "No MCP content services match current filters"
                    }
                    text={
                      tableSev
                        ? "Services in scope sit at other severities. Clear the severity filter to see every registered service."
                        : "Clear the product filter or adjust the repo-id search to see registered services."
                    }
                    action={
                      <Button
                        variant="btn-ghost"
                        size="sm"
                        onClick={() => {
                          setProduct(ALL_PRODUCTS);
                          setRepoFilter("");
                          setSevTab(0);
                        }}
                      >
                        Clear filters
                      </Button>
                    }
                  />
                </td>
              </tr>
            ) : (
              shownGroups.map((g) => (
                <CoverageGroup
                  key={g.product}
                  group={g}
                  open={open}
                  collapsed={!!collapsedGroups[g.product]}
                  onCollapseToggle={() => toggleGroup(g)}
                  onToggle={(id) => setOpen((o) => ({ ...o, [id]: !o[id] }))}
                  onNavigate={navigate}
                  canRunIngestion={canRunIngestion}
                />
              ))
            )}
            {hiddenCount > 0 && (
              <tr className="more-row">
                <td colSpan={TABLE_COLS}>
                  <button
                    type="button"
                    className="more-link"
                    onClick={() => setShowAll(true)}
                  >
                    Show {hiddenCount} more {hiddenCount > 1 ? "products" : "product"} →
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div id="coverage-triage-panel">
      <Card
        title="Coverage gap triage"
        sub="Prioritised remediation items across products. Filter by severity; stale threshold below."
        flush
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="scope-chip">
              stale threshold <b>{staleThresholdDays}d</b>
            </span>
            <div className="seg" role="group" aria-label="Filter triage by severity">
              {triageTabs.map((t) => (
                <button
                  key={t.sev}
                  type="button"
                  className={triageSev === t.sev ? "on" : undefined}
                  aria-pressed={triageSev === t.sev}
                  onClick={() => setTriageSev(t.sev)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        }
      >
        {triageDown ? (
          <div style={{ padding: 16 }}>
            <Banner
              variant="warn"
              icon="alert"
              title="The triage feed is unavailable right now"
              text="The services table above stays fully functional — use the Fix Plan in each row's detail to remediate not-ready services."
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => cov.contentTriageQuery.refetch()}
                >
                  Retry triage
                </Button>
              }
            />
          </div>
        ) : triageItems.length === 0 ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title={
                triageSev === "all"
                  ? "No triage gaps for the current health filters"
                  : "No triage gaps detected"
              }
              text={
                triageSev === "all"
                  ? "Every registered service is within coverage targets — no missing chunks, stale snapshots, or missing snippets."
                  : `No ${triageSev === "crit" ? "critical" : triageSev === "warn" ? "warning" : "info"} gaps in scope. Clear the severity filter to see other levels.`
              }
              action={
                triageSev !== "all" ? (
                  <Button variant="btn-ghost" size="sm" onClick={() => setTriageSev("all")}>
                    Show all gaps
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <>
            {triageSummary && (
              <div style={{ padding: 16, paddingBottom: 0 }}>
                <Banner
                  variant={triageSummaryVariant}
                  icon={triageSummaryVariant === "warn" ? "alert" : "info"}
                  title={triageSummary}
                />
              </div>
            )}
            {triageItems.map((t) => (
            <div key={t.id} className="op-row triage-item" data-sev={t.sev}>
              <Pill variant={SEVP[t.sev]}>{t.sigt.replace(/_/g, " ")}</Pill>
              <div>
                <div className="op-name mono">{t.repo}</div>
                <div className="op-meta">{t.detail}</div>
              </div>
              <div className="op-right">
                <span className="muted-note">{t.fix}</span>
                <Button variant="btn-ghost" size="sm" onClick={() => navigate("ingestion")}>
                  Fix
                </Button>
              </div>
            </div>
            ))}
          </>
        )}
      </Card>
      </div>
    </>
  );
}

// ───────────────────────────────────────────── Section-specific composites ──

function CoverageGroup({
  group,
  open,
  collapsed,
  onCollapseToggle,
  onToggle,
  onNavigate,
  canRunIngestion,
}: {
  group: CovGroup;
  open: Record<string, boolean>;
  collapsed: boolean;
  onCollapseToggle: () => void;
  onToggle: (id: string) => void;
  onNavigate: (key: "ingestion") => void;
  canRunIngestion: boolean;
}) {
  const count = group.repos.length;
  // Live MCP-ready count when rows carry an overlay; 0 in offline fixtures (none are ready).
  const readyCount = group.repos.filter((r) => r.live?.ready).length;
  return (
    <>
      <tr className={cn("grp-row", collapsed && "collapsed")}>
        <td colSpan={TABLE_COLS}>
          {/* The whole group header toggles collapse — as a real button. */}
          <button
            type="button"
            className="grp-head"
            aria-expanded={!collapsed}
            onClick={onCollapseToggle}
            style={{
              background: "none",
              border: 0,
              padding: 0,
              margin: 0,
              width: "100%",
              textAlign: "left",
              font: "inherit",
              color: "inherit",
              cursor: "pointer",
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: "inline-flex",
                transform: collapsed ? "rotate(-90deg)" : "none",
              }}
            >
              <Icon name="chevron" className="chev" />
            </span>
            <span className="name">{group.product}</span>
            <span className="dir">{group.dir}</span>
            <span className="meta">
              · <b>{count}</b> {count > 1 ? "repositories" : "repository"} · <b>{readyCount}</b>{" "}
              MCP-ready
            </span>
          </button>
        </td>
      </tr>
      {!collapsed &&
        group.repos.map((r) => (
          <CoverageRow
            key={r.id}
            repo={r}
            open={!!open[r.id]}
            onToggle={() => onToggle(r.id)}
            onNavigate={onNavigate}
            canRunIngestion={canRunIngestion}
          />
        ))}
    </>
  );
}

function CoverageRow({
  repo,
  open,
  onToggle,
  onNavigate,
  canRunIngestion,
}: {
  repo: CovRepo;
  open: boolean;
  onToggle: () => void;
  onNavigate: (key: "ingestion") => void;
  canRunIngestion: boolean;
}) {
  const live = repo.live;
  const m = covMeta(repo);
  const gitTail = repo.id.split(".").slice(0, 2).join(".");
  const signals: ReactNode = (
    <span className="signals">
      <span className="sig">
        chunks <b>{repo.sig[0]}</b>
      </span>
      <span className="sig">
        snip <b>{repo.sig[1]}</b>
      </span>
      <span className="sig">stale {repo.sig[2]}</span>
    </span>
  );

  // Live status/ready/reason/fix/diagnostics when present; fixture copy otherwise.
  const statusVariant = live?.status ?? "neutral";
  const statusLabel = live?.statusLabel ?? "unknown";
  const reasonLabel = live?.reasonLabel ?? repo.reason;
  const reasonText = live?.reasonText ?? COV_REASON[repo.reason];
  const fixSteps = live?.fixSteps?.length ? live.fixSteps : COV_FIX[repo.reason];
  const ingestScopeHint = canRunIngestion ? undefined : "requires write:ingestion scope";

  return (
    <>
      <tr
        className={cn("data", "exp-toggle", open && "open")}
        onClick={onToggle}
      >
        <td>
          <Pill variant={statusVariant}>{statusLabel}</Pill>
        </td>
        <td>
          <span className="cell-repo">
            <span className="exp">
              <Icon name={open ? "chevron" : "chevronR"} />
            </span>
            <span className="repo-id">{repo.id}</span>
          </span>
        </td>
        <td>
          <Tag>{repo.kind}</Tag>
        </td>
        <td>
          {live?.ready ? (
            <Pill variant="ok">ready</Pill>
          ) : live?.notReady ? (
            <Pill variant="warn">not-ready</Pill>
          ) : (
            <Pill variant="warn">pending</Pill>
          )}
        </td>
        <td>
          <Tag>{reasonLabel}</Tag>
        </td>
        <td>{signals}</td>
        <td className="num">{repo.last}</td>
      </tr>
      <tr className="exp-row" hidden={!open}>
        <td colSpan={TABLE_COLS}>
          <div className="exp-panel" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
            <div>
              <div className="eh">Why it&apos;s not ready</div>
              <div className="exp-reason">
                <Tag>{reasonLabel}</Tag>
                <div className="why">{reasonText}</div>
              </div>
            </div>
            <div>
              <div className="eh">Recommended fix plan</div>
              <ol className="fix-steps">
                {fixSteps.map((s, i) => (
                  <li key={i}>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
              <div className="exp-actions">
                <Button
                  variant="btn-primary"
                  size="sm"
                  icon="arrow"
                  onClick={() => onNavigate("ingestion")}
                >
                  Go to Ingestion
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  disabled={!canRunIngestion}
                  title={ingestScopeHint}
                >
                  Validate-Only
                </Button>
              </div>
            </div>
            <div>
              <div className="eh">Diagnostics</div>
              <div className="kvline">
                freshness=<b>{live?.fresh ?? m.fresh}</b>
              </div>
              <div className="kvline">
                last_ingest=<b>{live?.lastStatus ?? (repo.last === "never" ? "none" : "success")}</b>{" "}
                · <b>{repo.last}</b>
              </div>
              <div className="kvline">
                active_snapshot=<b>{live?.snapshotId ?? m.snapshotId}</b> ·{" "}
                <b>{live?.snapshotCreated ?? m.snapshotCreated}</b>
              </div>
              <div className="kvline">
                active_scopes=<b>{live?.scopesCount ?? m.scopesCount}</b>
              </div>
              <div className="kvline">
                parse_warnings=<b>{live?.parseWarnings ?? m.parseWarnings}</b> · failed_items=
                <b>{live?.failedItems ?? m.failedItems}</b>
              </div>
              <div className="kvline">
                branch=<b>{live?.defaultBranch ?? m.defaultBranch}</b> · submodule=
                <b>{live?.submodulePath ?? m.submodulePath}</b>
              </div>
              <div className="kvline">
                sdk_langs=<b>{live?.langs ?? m.langs}</b>
              </div>
              <div className="kvline">
                versions=<b>{live?.versions ?? m.versions}</b>
              </div>
              <div className="kvline">
                layout=<b>{live?.layout ?? m.layout}</b>
              </div>
              <div className="kvline">
                git=<b>{live?.gitUrl ?? `git…/${gitTail}-${repo.kind}.git`}</b>
              </div>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}
