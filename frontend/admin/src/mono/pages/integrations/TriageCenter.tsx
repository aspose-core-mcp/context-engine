"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill, Tag } from "@/mono/components";
import type { StatusVariant } from "@/mono/components";
import {
  AdminApiError,
  fetchPublicContentTriage,
  type PublicContentTriage,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Stale and No-Index Triage Center. Finds repos that are not MCP-ready, have
 * stale active snapshots, expose no indexed content, or lack executable snippet
 * coverage. Items are grouped by severity; each carries a copyable fix plan.
 *
 * Live data via fetchPublicContentTriage (public — query always enabled);
 * fixtures are the offline fallback (reviewable with no backend). Live success
 * EMPTY -> "no gaps" success state; live ERROR with no data -> error + retry.
 * Repo/severity filters re-fetch live AND apply to the display source offline.
 * "Copy fix plan" writes to the clipboard and reports success/failure honestly.
 * -------------------------------------------------------------------------- */

type TriageItem = PublicContentTriage["items"][number];

/* ---------------- fixtures (offline dataset) ---------------- */

const FIXTURE_ITEMS: TriageItem[] = [
  {
    gap_id: "gap-aspose.3d.apiref-no-index",
    severity: "critical",
    signal_type: "no_index_data",
    product_id: "aspose.3d",
    repo_id: "aspose.3d.apiref",
    source_kind: "apiref",
    mcp_ready: false,
    indexed_chunks_count: 0,
    executable_snippets_count: 0,
    active_snapshot_created_at: null,
    stale_days: null,
    summary: "No active snapshot — API reference is not indexed and not MCP-usable.",
    service_status: "not_ready",
    service_status_reason: "no_active_snapshot",
    fix_plan: [
      "Schedule a first ingestion run for aspose.3d.apiref.",
      "Verify the source repository layout is detected (apiref).",
      "Publish the snapshot and re-run the self-test.",
    ],
  },
  {
    gap_id: "gap-aspose.ocr.apiref-stale",
    severity: "warning",
    signal_type: "stale_snapshot",
    product_id: "aspose.ocr",
    repo_id: "aspose.ocr.apiref",
    source_kind: "apiref",
    mcp_ready: true,
    indexed_chunks_count: 8421,
    executable_snippets_count: 540,
    active_snapshot_created_at: "2026-05-16T00:00:00Z",
    stale_days: 25,
    summary: "Active snapshot is aging (25d, target 30d); a refresh is recommended soon.",
    service_status: "degraded",
    service_status_reason: "snapshot_aging",
    fix_plan: [
      "Re-run ingestion to pick up the latest release content.",
      "Confirm the new snapshot resolves the latest stable version.",
    ],
  },
  {
    gap_id: "gap-aspose.cells.docs-no-snippets",
    severity: "info",
    signal_type: "missing_snippets",
    product_id: "aspose.cells",
    repo_id: "aspose.cells.docs",
    source_kind: "docs",
    mcp_ready: true,
    indexed_chunks_count: 3120,
    executable_snippets_count: 0,
    active_snapshot_created_at: "2026-06-08T00:00:00Z",
    stale_days: 2,
    summary: "Docs are indexed but carry no executable snippets for code generation.",
    service_status: "ok",
    service_status_reason: "no_executable_snippets",
    fix_plan: [
      "Improve source content to include runnable code examples.",
      "Re-ingest so the chunker emits executable snippet chunks.",
    ],
  },
];

const FIXTURE: PublicContentTriage = {
  filters: { product_id: null, repo_id: null, severity: null, source_kind: null },
  stale_after_days: 30,
  total_items: FIXTURE_ITEMS.length,
  critical_total: 1,
  warning_total: 1,
  info_total: 1,
  status_summary: "1 critical · 1 warning · 1 info gap across 3 repositories.",
  items: FIXTURE_ITEMS,
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- severity → closed-palette mapping ---------------- */

const SEVERITY_VARIANT: Record<string, StatusVariant> = {
  critical: "crit",
  warning: "warn",
  info: "info",
};
const severityVariant = (s: string): StatusVariant => SEVERITY_VARIANT[s] ?? "neutral";

const SERVICE_VARIANT: Record<string, StatusVariant> = {
  ok: "ok",
  degraded: "warn",
  not_ready: "crit",
  not_registered: "neutral",
};
const serviceVariant = (s: string): StatusVariant => SERVICE_VARIANT[s] ?? "neutral";

const SEVERITY_ORDER = ["critical", "warning", "info"] as const;

const SR_ONLY: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};
const CAPTION: CSSProperties = { color: "var(--fg-subtle)", fontSize: 11.5 };

/** Compact "updated Ns ago" from an ISO timestamp (closed-palette, no new css). */
function relativeAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/** Stale-while-revalidate cue + manual refresh (kit `.pub-cta ghost` + tokens). */
function RefreshControl({
  generatedAt,
  isFetching,
  onRefresh,
}: {
  generatedAt: string | null | undefined;
  isFetching: boolean;
  onRefresh: () => void;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className="muted-note" role="status" aria-live="polite">
        {isFetching ? "refreshing…" : `updated ${relativeAge(generatedAt)}`}
      </span>
      <button
        type="button"
        className="pub-cta ghost"
        style={{ height: 28, padding: "0 12px", fontSize: 12 }}
        onClick={onRefresh}
        disabled={isFetching}
      >
        Refresh
      </button>
    </span>
  );
}

/* ---------------- component ---------------- */

export default function TriageCenter() {
  // Filters: Product ID, Repo ID, Severity, Source Kind. Each drives the live
  // query (committed via the queryKey) AND is applied client-side so the controls
  // respond offline.
  const [productFilter, setProductFilter] = useState("");
  const [repoFilter, setRepoFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [sourceKindFilter, setSourceKindFilter] = useState("");

  // Drive the live query off the committed filters; also apply them client-side
  // to the display source so the controls visibly respond offline (fixtures).
  const query = useQuery({
    queryKey: [
      "public-content-triage",
      productFilter,
      repoFilter,
      severityFilter,
      sourceKindFilter,
    ],
    queryFn: () =>
      fetchPublicContentTriage({
        product_id: productFilter || undefined,
        repo_id: repoFilter.trim() || undefined,
        severity: severityFilter || undefined,
        source_kind: sourceKindFilter || undefined,
      }),
    staleTime: 60_000,
  });

  const data: PublicContentTriage = query.data ?? FIXTURE;
  const liveItems: TriageItem[] = query.isSuccess ? query.data.items : data.items;

  // Product options derived from the display source (fixtures offline, live when
  // present); source kinds are the fixed registered set (docs / apiref).
  const productOptions = useMemo(
    () => Array.from(new Set(liveItems.map((i) => i.product_id))).sort(),
    [liveItems],
  );

  const trimmedRepo = repoFilter.trim().toLowerCase();
  const shown = useMemo(
    () =>
      liveItems.filter((item) => {
        if (productFilter && item.product_id !== productFilter) return false;
        if (trimmedRepo && !item.repo_id.toLowerCase().includes(trimmedRepo)) return false;
        if (severityFilter && item.severity !== severityFilter) return false;
        if (sourceKindFilter && item.source_kind !== sourceKindFilter) return false;
        return true;
      }),
    [liveItems, productFilter, trimmedRepo, severityFilter, sourceKindFilter],
  );

  const grouped = useMemo(
    () =>
      SEVERITY_ORDER.map((sev) => ({
        severity: sev,
        items: shown.filter((i) => i.severity === sev),
      })).filter((g) => g.items.length > 0),
    [shown],
  );

  const errored = query.isError && liveItems.length === 0;

  return (
    <section className="pub-card" id="content-triage" aria-label="Stale and no-index triage center">
      <div className="pub-card-head">
        <span className="pub-card-title">Stale and no-index triage center</span>
        <span className="right muted-note">stale threshold {data.stale_after_days}d</span>
      </div>

      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
        <p className="muted-note" style={{ margin: "0 0 12px" }}>
          Repositories that are not MCP-ready, have stale active snapshots, expose no indexed
          content, or still lack executable snippet coverage — the fastest surface for deciding where
          to run ingestion next.
        </p>
        <div className="toolbar" style={{ margin: 0 }}>
          <span className="select" style={{ minWidth: 160 }}>
            <label style={SR_ONLY} htmlFor="triage-product-filter">
              Product ID
            </label>
            <select
              id="triage-product-filter"
              className="selectctl"
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
            >
              <option value="">all products</option>
              {productOptions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </span>
          <span className="input" style={{ minWidth: 200 }}>
            <label style={SR_ONLY} htmlFor="triage-repo-filter">
              Repo id filter
            </label>
            <input
              id="triage-repo-filter"
              className="inputctl"
              value={repoFilter}
              onChange={(e) => setRepoFilter(e.target.value)}
              placeholder="aspose.ocr.apiref"
            />
          </span>
          <span className="select" style={{ minWidth: 160 }}>
            <label style={SR_ONLY} htmlFor="triage-severity-filter">
              Severity
            </label>
            <select
              id="triage-severity-filter"
              className="selectctl"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
            >
              <option value="">all severities</option>
              <option value="critical">critical</option>
              <option value="warning">warning</option>
              <option value="info">info</option>
            </select>
          </span>
          <span className="select" style={{ minWidth: 150 }}>
            <label style={SR_ONLY} htmlFor="triage-source-kind-filter">
              Source Kind
            </label>
            <select
              id="triage-source-kind-filter"
              className="selectctl"
              value={sourceKindFilter}
              onChange={(e) => setSourceKindFilter(e.target.value)}
            >
              <option value="">all source kinds</option>
              <option value="docs">docs</option>
              <option value="apiref">apiref</option>
            </select>
          </span>
          <span className="muted-note" style={{ marginLeft: "auto" }}>
            gaps {shown.length}
          </span>
        </div>
      </div>

      {errored ? (
        <ErrorRow
          message={
            query.error instanceof AdminApiError
              ? query.error.message
              : "Failed to load triage gaps."
          }
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          {/* severity totals */}
          <div className="metric-strip" style={{ borderBottom: "1px solid var(--border)" }}>
            <div className="m">
              <div className="mv">{data.critical_total}</div>
              <div className="ml">Critical</div>
            </div>
            <div className="m">
              <div className="mv">{data.warning_total}</div>
              <div className="ml">Warning</div>
            </div>
            <div className="m">
              <div className="mv">{data.info_total}</div>
              <div className="ml">Info</div>
            </div>
            <div className="m">
              <div className="mv">{data.total_items}</div>
              <div className="ml">Total gaps</div>
            </div>
          </div>

          <div className="svc-row" style={{ flexWrap: "wrap" }}>
            <Pill variant={data.critical_total > 0 ? "crit" : "info"}>
              {data.critical_total > 0 ? "action needed" : "clear"}
            </Pill>
            <span className="muted-note" style={{ flex: 1, minWidth: 200 }}>
              {data.status_summary}
            </span>
            <RefreshControl
              generatedAt={data.generated_at}
              isFetching={query.isFetching}
              onRefresh={() => void query.refetch()}
            />
          </div>

          {/* severity-grouped gap cards */}
          {grouped.length === 0 ? (
            <div className="svc-row" style={{ gap: 12 }}>
              <Pill variant="ok">clear</Pill>
              <span className="muted-note" style={{ flex: 1 }}>
                No triage gaps are visible for the current filters.
              </span>
            </div>
          ) : (
            grouped.map((group) => (
              <div key={group.severity}>
                <div
                  style={{
                    padding: "10px 20px",
                    borderBottom: "1px solid var(--border)",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <Pill variant={severityVariant(group.severity)}>{group.severity}</Pill>
                  <span className="muted-note">{group.items.length} gap(s)</span>
                </div>
                {group.items.map((item) => (
                  <TriageRow key={item.gap_id} item={item} />
                ))}
              </div>
            ))
          )}
        </>
      )}
    </section>
  );
}

/* ---------------- per-gap row (with Copy fix plan) ---------------- */

function TriageRow({ item }: { item: TriageItem }) {
  const [copied, setCopied] = useState<"idle" | "ok" | "err">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copyFixPlan = useCallback(async () => {
    const text = [`Fix plan — ${item.repo_id} (${item.severity})`, ...item.fix_plan.map((s, i) => `${i + 1}. ${s}`)].join(
      "\n",
    );
    let ok = true;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      ok = false;
    }
    setCopied(ok ? "ok" : "err");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied("idle"), 2000);
  }, [item]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return (
    <div className="svc-row" style={{ alignItems: "stretch", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <Pill variant={severityVariant(item.severity)}>{item.severity}</Pill>
          <Tag>{item.signal_type}</Tag>
          <Tag>{item.source_kind}</Tag>
          <span className="repo-id" style={{ fontSize: 12.5, fontWeight: 600 }}>
            {item.repo_id}
          </span>
        </span>
        <span style={{ ...CAPTION, marginLeft: "auto", textAlign: "right" }}>
          product={item.product_id} · chunks={item.indexed_chunks_count} · snippets=
          {item.executable_snippets_count}
        </span>
      </div>

      <div className="svc-desc" style={{ margin: 0 }}>
        {item.summary}
      </div>

      <div style={CAPTION}>
        service={item.service_status}/{item.service_status_reason} · mcp_ready=
        {String(item.mcp_ready)} · stale_days={item.stale_days ?? "n/a"}
      </div>

      <ol className="muted-note" style={{ margin: 0, paddingLeft: 18 }}>
        {item.fix_plan.map((step) => (
          <li key={`${item.gap_id}-${step}`} style={{ marginTop: 2 }}>
            {step}
          </li>
        ))}
      </ol>

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          type="button"
          className="pub-cta ghost"
          style={{ height: 30, padding: "0 14px", fontSize: 12.5 }}
          onClick={() => void copyFixPlan()}
        >
          Copy fix plan
        </button>
        <span role="status" aria-live="polite" className="muted-note">
          {copied === "ok"
            ? "Fix plan copied to clipboard."
            : copied === "err"
              ? "Clipboard write was blocked."
              : ""}
        </span>
      </div>
    </div>
  );
}

/* ---------------- shared error row (retry) ---------------- */

function ErrorRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="svc-row" style={{ gap: 12, flexWrap: "wrap" }}>
      <Pill variant="crit">error</Pill>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div className="svc-name">Triage center unavailable</div>
        <div className="svc-desc">{message}</div>
      </div>
      <button
        type="button"
        className="pub-cta ghost"
        style={{ height: 30, padding: "0 14px", fontSize: 12.5 }}
        onClick={onRetry}
      >
        Retry
      </button>
    </div>
  );
}
