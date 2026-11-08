"use client";

import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill, Tag } from "@/mono/components";
import type { StatusVariant } from "@/mono/components";
import {
  AdminApiError,
  fetchPublicCoverageGapTracker,
  type PublicCoverageGapTracker,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Product Coverage Gap Tracker
 *
 * Separates what is merely registered from what is actually MCP-ready. Per
 * product → per language surface → per source-kind breakdown (docs/apiref),
 * gap badges, expected versions, service reasons, fix priorities.
 * Live data via fetchPublicCoverageGapTracker (public — query always enabled);
 * fixtures are the offline fallback (reviewable with no backend). Live success
 * EMPTY -> designed empty state; live ERROR with no data -> error + retry.
 * -------------------------------------------------------------------------- */

type GapProduct = PublicCoverageGapTracker["products"][number];
type GapSurface = GapProduct["surfaces"][number];

/* ---------------- fixtures (offline dataset) ---------------- */

const FIXTURE_PRODUCTS: GapProduct[] = [
  {
    product_id: "aspose.ocr",
    product_name: "Aspose.OCR",
    product_family: "ocr",
    product_family_dirs: ["aspose.ocr"],
    repo_ids: ["aspose.ocr.docs", "aspose.ocr.apiref"],
    registered_source_kinds: ["docs", "apiref"],
    expected_programming_languages: ["net", "java", "python"],
    ready_surfaces_total: 1,
    partial_surfaces_total: 1,
    registered_only_surfaces_total: 0,
    high_priority_surfaces_total: 1,
    medium_priority_surfaces_total: 1,
    low_priority_surfaces_total: 0,
    surfaces: [
      {
        surface_id: "aspose.ocr::net",
        product_id: "aspose.ocr",
        product_name: "Aspose.OCR",
        product_family: "ocr",
        programming_language: "net",
        status: "ready",
        onboarding_priority: "high",
        registered_source_kinds: ["docs", "apiref"],
        ready_source_kinds: ["docs", "apiref"],
        latest_stable_visible: true,
        executable_snippets_count: 1240,
        expected_versions: ["25.1", "24.12"],
        gap_badges: [],
        summary: "Docs and API reference both live for the latest stable .NET surface.",
        source_kinds: [
          {
            source_kind: "docs",
            registered: true,
            ready: true,
            repo_ids: ["aspose.ocr.docs"],
            active_snapshot_ids: ["snap_docs_2025"],
            active_versions: ["25.1"],
            latest_stable_visible: true,
            supported_versions: ["25.1", "24.12"],
            service_statuses: ["ok"],
            service_reasons: [],
          },
          {
            source_kind: "apiref",
            registered: true,
            ready: true,
            repo_ids: ["aspose.ocr.apiref"],
            active_snapshot_ids: ["snap_api_2025"],
            active_versions: ["25.1"],
            latest_stable_visible: true,
            supported_versions: ["25.1", "24.12"],
            service_statuses: ["ok"],
            service_reasons: [],
          },
        ],
      },
      {
        surface_id: "aspose.ocr::java",
        product_id: "aspose.ocr",
        product_name: "Aspose.OCR",
        product_family: "ocr",
        programming_language: "java",
        status: "partial",
        onboarding_priority: "medium",
        registered_source_kinds: ["docs", "apiref"],
        ready_source_kinds: ["docs"],
        latest_stable_visible: false,
        executable_snippets_count: 312,
        expected_versions: ["24.12"],
        gap_badges: ["apiref_lagging"],
        summary: "Docs live; API reference snapshot is one release behind latest stable.",
        source_kinds: [
          {
            source_kind: "docs",
            registered: true,
            ready: true,
            repo_ids: ["aspose.ocr.docs"],
            active_snapshot_ids: ["snap_docs_2024"],
            active_versions: ["24.12"],
            latest_stable_visible: true,
            supported_versions: ["24.12"],
            service_statuses: ["ok"],
            service_reasons: [],
          },
          {
            source_kind: "apiref",
            registered: true,
            ready: false,
            repo_ids: ["aspose.ocr.apiref"],
            active_snapshot_ids: [],
            active_versions: [],
            latest_stable_visible: false,
            supported_versions: ["24.11"],
            service_statuses: ["degraded"],
            service_reasons: ["snapshot_behind_latest"],
          },
        ],
      },
    ],
  },
  {
    product_id: "aspose.cells",
    product_name: "Aspose.Cells",
    product_family: "cells",
    product_family_dirs: ["aspose.cells"],
    repo_ids: ["aspose.cells.docs"],
    registered_source_kinds: ["docs"],
    expected_programming_languages: ["net", "python"],
    ready_surfaces_total: 0,
    partial_surfaces_total: 0,
    registered_only_surfaces_total: 1,
    high_priority_surfaces_total: 0,
    medium_priority_surfaces_total: 0,
    low_priority_surfaces_total: 1,
    surfaces: [
      {
        surface_id: "aspose.cells::python",
        product_id: "aspose.cells",
        product_name: "Aspose.Cells",
        product_family: "cells",
        programming_language: "python",
        status: "registered_only",
        onboarding_priority: "low",
        registered_source_kinds: ["docs"],
        ready_source_kinds: [],
        latest_stable_visible: false,
        executable_snippets_count: 0,
        expected_versions: [],
        gap_badges: ["no_index_data", "apiref_not_registered"],
        summary: "Registered but no snapshot indexed yet; apiref source not registered.",
        source_kinds: [
          {
            source_kind: "docs",
            registered: true,
            ready: false,
            repo_ids: ["aspose.cells.docs"],
            active_snapshot_ids: [],
            active_versions: [],
            latest_stable_visible: false,
            supported_versions: [],
            service_statuses: ["not_ready"],
            service_reasons: ["no_active_snapshot"],
          },
          {
            source_kind: "apiref",
            registered: false,
            ready: false,
            repo_ids: [],
            active_snapshot_ids: [],
            active_versions: [],
            latest_stable_visible: false,
            supported_versions: [],
            service_statuses: ["not_registered"],
            service_reasons: ["not_registered"],
          },
        ],
      },
    ],
  },
];

const FIXTURE: PublicCoverageGapTracker = {
  filters: { product_id: null, programming_language: null, source_kind: null, version: null },
  products_total: FIXTURE_PRODUCTS.length,
  surfaces_total: 3,
  ready_surfaces_total: 1,
  partial_surfaces_total: 1,
  registered_only_surfaces_total: 1,
  high_priority_surfaces_total: 1,
  medium_priority_surfaces_total: 1,
  low_priority_surfaces_total: 1,
  status_summary: "1 ready · 1 partial · 1 registered-only surface across 2 products.",
  products: FIXTURE_PRODUCTS,
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- status → closed-palette mapping ---------------- */

const STATUS_VARIANT: Record<string, StatusVariant> = {
  ready: "ok",
  partial: "warn",
  registered_only: "neutral",
};
const statusVariant = (s: string): StatusVariant => STATUS_VARIANT[s] ?? "neutral";

const PRIORITY_VARIANT: Record<string, StatusVariant> = {
  high: "crit",
  medium: "warn",
  low: "ok",
};
const priorityVariant = (p: string): StatusVariant => PRIORITY_VARIANT[p] ?? "neutral";

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

export default function GapTracker() {
  // Filters: Product ID, Language, Version, Source Kind. Each drives the live
  // query (committed via the queryKey) AND is applied client-side so the controls
  // visibly respond offline (fixtures).
  const [productFilter, setProductFilter] = useState("");
  const [languageFilter, setLanguageFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [sourceKindFilter, setSourceKindFilter] = useState("");

  const trimmedProduct = productFilter.trim();

  const query = useQuery({
    queryKey: [
      "public-coverage-gap-tracker",
      trimmedProduct,
      languageFilter,
      versionFilter,
      sourceKindFilter,
    ],
    queryFn: () =>
      fetchPublicCoverageGapTracker({
        product_id: trimmedProduct || undefined,
        programming_language: languageFilter || undefined,
        version: versionFilter || undefined,
        source_kind: sourceKindFilter || undefined,
      }),
    staleTime: 60_000,
  });

  const data: PublicCoverageGapTracker = query.data ?? FIXTURE;
  const source: GapProduct[] = query.isSuccess ? query.data.products : data.products;

  // Language / version options derived from the display source (fixtures offline,
  // live response when present); source kinds are the fixed registered set.
  const languageOptions = useMemo(() => {
    const set = new Set<string>();
    for (const p of source) for (const s of p.surfaces) set.add(s.programming_language);
    return Array.from(set).sort();
  }, [source]);
  const versionOptions = useMemo(() => {
    const set = new Set<string>();
    for (const p of source)
      for (const s of p.surfaces) for (const v of s.expected_versions) set.add(v);
    return Array.from(set).sort().reverse();
  }, [source]);

  const trimmed = trimmedProduct.toLowerCase();
  const shown = useMemo(() => {
    const matchSurface = (s: GapSurface): boolean => {
      if (languageFilter && s.programming_language !== languageFilter) return false;
      if (versionFilter && !s.expected_versions.includes(versionFilter)) return false;
      if (sourceKindFilter && !s.registered_source_kinds.includes(sourceKindFilter)) return false;
      return true;
    };
    return source
      .filter(
        (p) =>
          !trimmed ||
          p.product_id.toLowerCase().includes(trimmed) ||
          p.product_name.toLowerCase().includes(trimmed),
      )
      .map((p) => ({ ...p, surfaces: p.surfaces.filter(matchSurface) }))
      .filter((p) => p.surfaces.length > 0);
  }, [source, trimmed, languageFilter, versionFilter, sourceKindFilter]);

  const errored = query.isError && source.length === 0;

  return (
    <section className="pub-card" id="coverage-gap-tracker" aria-label="Product coverage gap tracker">
      <div className="pub-card-head">
        <span className="pub-card-title">Product coverage gap tracker</span>
        <span className="right muted-note">registered vs. MCP-ready</span>
      </div>

      <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
        <p className="muted-note" style={{ margin: "0 0 12px" }}>
          Separates what is merely registered from what is actually MCP-ready: which surfaces have
          docs and API reference live, which are partial, and which onboarding gaps to prioritize.
        </p>
        <div className="toolbar" style={{ margin: 0 }}>
          <span className="input" style={{ minWidth: 220 }}>
            <label style={SR_ONLY} htmlFor="gap-product-filter">
              Product ID
            </label>
            <input
              id="gap-product-filter"
              className="inputctl"
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
              placeholder="Filter by product id / name…"
            />
          </span>
          <span className="select" style={{ minWidth: 150 }}>
            <label style={SR_ONLY} htmlFor="gap-language-filter">
              Language
            </label>
            <select
              id="gap-language-filter"
              className="selectctl"
              value={languageFilter}
              onChange={(e) => setLanguageFilter(e.target.value)}
            >
              <option value="">all languages</option>
              {languageOptions.map((lang) => (
                <option key={lang} value={lang}>
                  {lang}
                </option>
              ))}
            </select>
          </span>
          <span className="select" style={{ minWidth: 150 }}>
            <label style={SR_ONLY} htmlFor="gap-version-filter">
              Version
            </label>
            <select
              id="gap-version-filter"
              className="selectctl"
              value={versionFilter}
              onChange={(e) => setVersionFilter(e.target.value)}
            >
              <option value="">all versions</option>
              {versionOptions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </span>
          <span className="select" style={{ minWidth: 150 }}>
            <label style={SR_ONLY} htmlFor="gap-source-kind-filter">
              Source Kind
            </label>
            <select
              id="gap-source-kind-filter"
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
            products {shown.length}
          </span>
        </div>
      </div>

      {errored ? (
        <ErrorRow
          message={
            query.error instanceof AdminApiError
              ? query.error.message
              : "Failed to load the coverage gap tracker."
          }
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          <div className="svc-row" style={{ flexWrap: "wrap" }}>
            <span className="muted-note" style={{ flex: 1, minWidth: 220 }}>
              {data.status_summary}
            </span>
            <span style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Pill variant="ok">ready {data.ready_surfaces_total}</Pill>
              <Pill variant="warn">partial {data.partial_surfaces_total}</Pill>
              <Pill variant="neutral">registered-only {data.registered_only_surfaces_total}</Pill>
              <Pill variant="crit">high priority {data.high_priority_surfaces_total}</Pill>
              <RefreshControl
                generatedAt={data.generated_at}
                isFetching={query.isFetching}
                onRefresh={() => void query.refetch()}
              />
            </span>
          </div>

          {shown.length === 0 ? (
            <div style={{ padding: "20px" }}>
              <div className="muted-note">No surfaces match the current filters.</div>
              <div className="muted-note" style={{ marginTop: 4 }}>
                Clear the product, language, version or source-kind filter and try again.
              </div>
            </div>
          ) : (
            shown.map((product) => <ProductBlock key={product.product_id} product={product} />)
          )}
        </>
      )}
    </section>
  );
}

/* ---------------- per-product block ---------------- */

function ProductBlock({ product }: { product: GapProduct }) {
  return (
    <div className="svc-row" style={{ alignItems: "stretch", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="svc-name">{product.product_name}</div>
          <div className="svc-desc">
            <span className="repo-id">{product.product_id}</span> · repos{" "}
            {product.repo_ids.join(", ") || "none"}
          </div>
        </div>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Tag>ready {product.ready_surfaces_total}</Tag>
          <Tag>partial {product.partial_surfaces_total}</Tag>
          <Pill variant="crit">high {product.high_priority_surfaces_total}</Pill>
        </span>
      </div>

      <div style={CAPTION}>
        Expected languages: {product.expected_programming_languages.join(", ") || "none"}.
        Registered source kinds: {product.registered_source_kinds.join(", ") || "none"}.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {product.surfaces.map((surface) => (
          <SurfaceBlock key={surface.surface_id} surface={surface} />
        ))}
      </div>
    </div>
  );
}

/* ---------------- per-surface block ---------------- */

function SurfaceBlock({ surface }: { surface: GapSurface }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "11px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 9,
      }}
    >
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="svc-name" style={{ fontSize: 13 }}>
            {surface.programming_language}
          </div>
          <div className="svc-desc">{surface.summary}</div>
        </div>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Pill variant={statusVariant(surface.status)}>{surface.status}</Pill>
          <Pill variant={priorityVariant(surface.onboarding_priority)}>
            priority {surface.onboarding_priority}
          </Pill>
          <Tag>snippets {surface.executable_snippets_count}</Tag>
        </span>
      </div>

      {(surface.gap_badges.length > 0 || surface.expected_versions.length > 0) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {surface.gap_badges.map((b) => (
            <Pill key={`${surface.surface_id}-${b}`} variant="crit">
              {b}
            </Pill>
          ))}
          {surface.expected_versions.map((v) => (
            <Tag key={`${surface.surface_id}-v-${v}`}>v{v}</Tag>
          ))}
        </div>
      )}

      {/* per source-kind breakdown */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {surface.source_kinds.map((sk) => (
          <div
            key={`${surface.surface_id}-${sk.source_kind}`}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "8px 12px",
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <span style={{ display: "flex", gap: 7, flexWrap: "wrap", alignItems: "center" }}>
              <Tag>{sk.source_kind}</Tag>
              <Pill variant={sk.registered ? "neutral" : "warn"}>
                {sk.registered ? "registered" : "missing"}
              </Pill>
              <Pill variant={sk.ready ? "ok" : "warn"}>{sk.ready ? "ready" : "not ready"}</Pill>
            </span>
            <span style={{ ...CAPTION, marginLeft: "auto", textAlign: "right" }}>
              repos={sk.repo_ids.join(", ") || "none"} · versions=
              {sk.active_versions.join(", ") || sk.supported_versions.join(", ") || "none"} · reasons=
              {sk.service_reasons.join(", ") || "none"}
            </span>
          </div>
        ))}
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
        <div className="svc-name">Coverage gap tracker unavailable</div>
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
