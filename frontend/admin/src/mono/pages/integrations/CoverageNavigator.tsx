"use client";

import { useId, useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill, Tag } from "@/mono/components";
import type { StatusVariant } from "@/mono/components";
import {
  AdminApiError,
  fetchPublicCoverageNavigator,
  type PublicCoverageNavigator,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Coverage Navigator
 *
 * Compact answer to one question: which product/SDK surfaces are truly
 * MCP-usable right now, which source kind lags, and where to click to recover.
 * Live data via fetchPublicCoverageNavigator (public — query always enabled).
 * Fixtures are the OFFLINE fallback: live present -> live; live success EMPTY
 * -> designed empty state; live ERROR with no data -> error state + retry;
 * offline/loading -> fixtures so the section is fully reviewable with no backend.
 * -------------------------------------------------------------------------- */

type Surface = PublicCoverageNavigator["surfaces"][number];

/* ---------------- fixtures (offline dataset) ---------------- */

const FIXTURE_SURFACES: Surface[] = [
  {
    surface_id: "aspose.ocr::net",
    product_id: "aspose.ocr",
    product_name: "Aspose.OCR",
    product_family: "ocr",
    programming_language: "net",
    overall_status: "ready",
    onboarding_priority: "high",
    latest_visible_versions: ["25.1", "24.12"],
    executable_snippets_count: 1240,
    gap_badges: [],
    summary: "Docs and API reference are both live for the latest stable .NET surface.",
    remediation: ["No action required — surface is MCP-ready."],
    cells: [
      { source_kind: "docs", status: "ready", active_versions: ["25.1"], service_reason: null },
      { source_kind: "apiref", status: "ready", active_versions: ["25.1"], service_reason: null },
    ],
    actions: [
      { label: "Open coverage gap tracker", href: "#coverage-gap-tracker" },
      { label: "Open self-test", href: "#self-test" },
    ],
  },
  {
    surface_id: "aspose.ocr::java",
    product_id: "aspose.ocr",
    product_name: "Aspose.OCR",
    product_family: "ocr",
    programming_language: "java",
    overall_status: "partial",
    onboarding_priority: "medium",
    latest_visible_versions: ["24.12"],
    executable_snippets_count: 312,
    gap_badges: ["apiref_lagging"],
    summary: "Docs are live; API reference is one release behind the latest stable.",
    remediation: [
      "Re-run apiref ingestion for the aspose.ocr.apiref repo.",
      "Verify the active snapshot resolves the latest stable version.",
    ],
    cells: [
      { source_kind: "docs", status: "ready", active_versions: ["24.12"], service_reason: null },
      {
        source_kind: "apiref",
        status: "gap",
        active_versions: [],
        service_reason: "snapshot_behind_latest",
      },
    ],
    actions: [{ label: "Open content triage", href: "#content-triage" }],
  },
  {
    surface_id: "aspose.cells::python",
    product_id: "aspose.cells",
    product_name: "Aspose.Cells",
    product_family: "cells",
    programming_language: "python",
    overall_status: "registered_only",
    onboarding_priority: "low",
    latest_visible_versions: [],
    executable_snippets_count: 0,
    gap_badges: ["no_index_data", "no_snippets"],
    summary: "Repo is registered but no snapshot is indexed yet — not MCP-usable.",
    remediation: [
      "Schedule a first ingestion run for the Python surface.",
      "Confirm the source repository exposes Python examples.",
    ],
    cells: [
      {
        source_kind: "docs",
        status: "gap",
        active_versions: [],
        service_reason: "no_active_snapshot",
      },
      {
        source_kind: "apiref",
        status: "gap",
        active_versions: [],
        service_reason: "not_registered",
      },
    ],
    actions: [{ label: "Open content triage", href: "#content-triage" }],
  },
];

const FIXTURE: PublicCoverageNavigator = {
  filters: { product_id: null, programming_language: null, source_kind: null, version: null },
  products_total: 2,
  surfaces_total: FIXTURE_SURFACES.length,
  ready_total: 1,
  partial_total: 1,
  registered_only_total: 1,
  available_products: ["aspose.ocr", "aspose.cells"],
  available_programming_languages: ["net", "java", "python"],
  available_source_kinds: ["docs", "apiref"],
  available_versions: ["25.1", "24.12"],
  status_summary: "1 ready · 1 partial · 1 registered-only surface across 2 products.",
  surfaces: FIXTURE_SURFACES,
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- status → closed-palette mapping ---------------- */

const STATUS_VARIANT: Record<string, StatusVariant> = {
  ready: "ok",
  partial: "warn",
  registered_only: "neutral",
  gap: "crit",
};
const statusVariant = (s: string): StatusVariant => STATUS_VARIANT[s] ?? "neutral";

const PRIORITY_VARIANT: Record<string, StatusVariant> = {
  high: "crit",
  medium: "warn",
  low: "ok",
};
const priorityVariant = (p: string): StatusVariant => PRIORITY_VARIANT[p] ?? "neutral";

type StatusFilter = "all" | "ready" | "partial" | "registered_only";
type SourceFilter = "all" | "docs" | "apiref";

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

export default function CoverageNavigator() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sourceFocus, setSourceFocus] = useState<SourceFilter>("all");
  const statusId = useId();
  const sourceId = useId();

  // `source` maps to the server `source_kind` param (committed via the queryKey)
  // so the focus drives the live query; `status` has no server param and stays
  // client-side. Offline, both apply to the fixture below so controls respond.
  const query = useQuery({
    queryKey: ["public-coverage-navigator", sourceFocus],
    queryFn: () =>
      fetchPublicCoverageNavigator({
        source_kind: sourceFocus === "all" ? undefined : sourceFocus,
      }),
    staleTime: 60_000,
  });

  // Live present -> live; otherwise the offline fixture so the UI is reviewable.
  const data: PublicCoverageNavigator = query.data ?? FIXTURE;
  // Distinguish "live reachable but empty" (real empty state) from "offline"
  // (use fixtures). When the query genuinely succeeded we trust its surfaces.
  const source: Surface[] = query.isSuccess ? query.data.surfaces : data.surfaces;

  const shown = useMemo(
    () =>
      source.filter((item) => {
        if (statusFilter !== "all" && item.overall_status !== statusFilter) return false;
        if (sourceFocus !== "all" && !item.cells.some((c) => c.source_kind === sourceFocus)) {
          return false;
        }
        return true;
      }),
    [source, statusFilter, sourceFocus],
  );

  // Hard error only blocks when there is genuinely nothing to show.
  const errored = query.isError && source.length === 0;

  return (
    <section className="pub-card" id="coverage-navigator" aria-label="Coverage navigator">
      <div className="pub-card-head">
        <span className="pub-card-title">Coverage navigator</span>
        <span className="right muted-note">product × SDK readiness</span>
      </div>

      {/* filter toolbar */}
      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
        <p className="muted-note" style={{ margin: "0 0 12px" }}>
          Which product/SDK surfaces are truly MCP-usable right now, which source kind is missing or
          lagging, and where to click next to recover the gap.
        </p>
        <form className="toolbar" style={{ margin: 0 }} onSubmit={(e) => e.preventDefault()}>
          <span className="select" style={{ minWidth: 170 }}>
            <label style={SR_ONLY} htmlFor={statusId}>
              Navigator status
            </label>
            <select
              id={statusId}
              className="selectctl"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            >
              <option value="all">all statuses</option>
              <option value="ready">ready</option>
              <option value="partial">partial</option>
              <option value="registered_only">registered_only</option>
            </select>
          </span>
          <span className="select" style={{ minWidth: 170 }}>
            <label style={SR_ONLY} htmlFor={sourceId}>
              Source focus
            </label>
            <select
              id={sourceId}
              className="selectctl"
              value={sourceFocus}
              onChange={(e) => setSourceFocus(e.target.value as SourceFilter)}
            >
              <option value="all">all source kinds</option>
              <option value="docs">docs</option>
              <option value="apiref">apiref</option>
            </select>
          </span>
          <span className="muted-note" style={{ marginLeft: "auto" }}>
            filtered rows {shown.length}
          </span>
        </form>
      </div>

      {errored ? (
        <ErrorRow
          message={
            query.error instanceof AdminApiError
              ? query.error.message
              : "Failed to load the coverage navigator."
          }
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          {/* status summary + totals */}
          <div className="svc-row" style={{ flexWrap: "wrap" }}>
            <span className="muted-note" style={{ flex: 1, minWidth: 220 }}>
              {data.status_summary}
            </span>
            <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Pill variant="ok">ready {data.ready_total}</Pill>
              <Pill variant="warn">partial {data.partial_total}</Pill>
              <Pill variant="neutral">registered-only {data.registered_only_total}</Pill>
              <Tag>versions {data.available_versions.length}</Tag>
              <RefreshControl
                generatedAt={data.generated_at}
                isFetching={query.isFetching}
                onRefresh={() => void query.refetch()}
              />
            </span>
          </div>

          {/* navigator rows */}
          {shown.length === 0 ? (
            <div style={{ padding: "20px" }}>
              <div className="muted-note">
                No coverage navigator rows match the current status/source filters.
              </div>
              <div className="muted-note" style={{ marginTop: 4 }}>
                Adjust the filters above or select a different product/language.
              </div>
            </div>
          ) : (
            shown.map((item) => <NavigatorRow key={item.surface_id} item={item} />)
          )}
        </>
      )}
    </section>
  );
}

/* ---------------- per-surface row ---------------- */

function NavigatorRow({ item }: { item: Surface }) {
  return (
    <div className="svc-row" style={{ alignItems: "stretch", flexDirection: "column", gap: 12 }}>
      {/* heading + status / priority / snippets */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="svc-name">
            <span className="repo-id">{item.product_id}</span> · {item.programming_language}
          </div>
          <div className="svc-desc">{item.summary}</div>
        </div>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Pill variant={statusVariant(item.overall_status)}>{item.overall_status}</Pill>
          <Pill variant={priorityVariant(item.onboarding_priority)}>
            priority {item.onboarding_priority}
          </Pill>
          <Tag>snippets {item.executable_snippets_count}</Tag>
        </span>
      </div>

      {/* per-source-kind cells */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {item.cells.map((cell) => (
          <div
            key={`${item.surface_id}-${cell.source_kind}`}
            style={{
              flex: "1 1 200px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "9px 12px",
            }}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 11.5, fontWeight: 600 }}>
                {cell.source_kind}
              </span>
              <Pill variant={statusVariant(cell.status)}>{cell.status}</Pill>
            </div>
            <div style={{ ...CAPTION, marginTop: 5 }}>
              versions={cell.active_versions.join(", ") || "none"} · reason=
              {cell.service_reason ?? "none"}
            </div>
          </div>
        ))}
      </div>

      {/* version + gap badges */}
      {(item.latest_visible_versions.length > 0 || item.gap_badges.length > 0) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {item.latest_visible_versions.map((v) => (
            <Tag key={`${item.surface_id}-v-${v}`}>v{v}</Tag>
          ))}
          {item.gap_badges.map((b) => (
            <Pill key={`${item.surface_id}-${b}`} variant="crit">
              {b}
            </Pill>
          ))}
        </div>
      )}

      {/* remediation steps */}
      {item.remediation.length > 0 && (
        <ol className="muted-note" style={{ margin: 0, paddingLeft: 18 }}>
          {item.remediation.map((step) => (
            <li key={`${item.surface_id}-${step}`} style={{ marginTop: 2 }}>
              {step}
            </li>
          ))}
        </ol>
      )}

      {/* action links */}
      {item.actions.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {item.actions.map((action) => (
            <a
              key={`${item.surface_id}-${action.label}`}
              className="pub-cta ghost"
              href={action.href}
              style={{ height: 30, padding: "0 14px", fontSize: 12.5 }}
            >
              {action.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- shared error row (retry) ---------------- */

function ErrorRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="svc-row" style={{ gap: 12, flexWrap: "wrap" }}>
      <Pill variant="crit">error</Pill>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div className="svc-name">Coverage navigator unavailable</div>
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
