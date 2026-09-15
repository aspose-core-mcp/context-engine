"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { EmptyState } from "@/mono/components/states";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { Icon } from "@/mono/lib/icons";
import type { StatusVariant } from "@/mono/lib/types";
import {
  fetchPublicCapabilityExplorer,
  type PublicCapabilityExplorer,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Capability Explorer — compact readiness table per product surface.
 *
 * Driven by the public fetchPublicCapabilityExplorer (no auth). Status and
 * source filters re-fetch server-side AND filter the display source client-side,
 * so the section stays interactive OFFLINE on the in-file fixtures (the offline
 * fallback).
 * -------------------------------------------------------------------------- */

const STATUS_OPTS = ["all", "ready", "partial", "registered_only"] as const;
const SOURCE_OPTS = ["all", "docs", "apiref"] as const;

type StatusFilter = (typeof STATUS_OPTS)[number];
type SourceFilter = (typeof SOURCE_OPTS)[number];

function statusVariant(status: string): StatusVariant {
  if (status === "ready") return "ok";
  if (status === "partial") return "warn";
  if (status === "registered_only" || status === "gap") return "crit";
  return "neutral";
}

/* ---------------- fixtures (offline dataset) ---------------- */

const FIXTURE: PublicCapabilityExplorer = {
  filters: { product_id: null, programming_language: null, source_kind: null, version: null },
  products_total: 3,
  capabilities_total: 5,
  ready_total: 2,
  partial_total: 2,
  gap_total: 1,
  available_programming_languages: ["net", "java", "python", "cpp"],
  available_source_kinds: ["docs", "apiref"],
  status_summary: "2 ready · 2 partial · 1 gap across 3 products (sample data shown offline).",
  items: [
    {
      capability_id: "aspose.ocr::net",
      product_id: "aspose.ocr",
      product_name: "Aspose.OCR",
      product_family: "aspose",
      programming_language: "net",
      status: "ready",
      onboarding_priority: "high",
      latest_stable_visible: true,
      freshness_label: "fresh",
      resolved_version: "24.12",
      newest_available_version: "24.12",
      executable_snippets_count: 48,
      registered_source_kinds: ["docs", "apiref"],
      ready_source_kinds: ["docs", "apiref"],
      gap_badges: [],
      summary: "Docs and API reference both indexed at latest-stable with executable snippets.",
      snippet_titles: [
        "Recognize text from an image",
        "Constrain recognition language",
        "Recognize text from a PDF",
      ],
      actions: [{ label: "Open coverage", href: "#coverage" }],
    },
    {
      capability_id: "aspose.ocr::python",
      product_id: "aspose.ocr",
      product_name: "Aspose.OCR",
      product_family: "aspose",
      programming_language: "python",
      status: "partial",
      onboarding_priority: "high",
      latest_stable_visible: true,
      freshness_label: "aging",
      resolved_version: "24.11",
      newest_available_version: "24.12",
      executable_snippets_count: 12,
      registered_source_kinds: ["docs", "apiref"],
      ready_source_kinds: ["docs"],
      gap_badges: ["apiref_not_ready", "snapshot_aging"],
      summary: "Docs ready; API reference snapshot is aging and one version behind.",
      snippet_titles: ["Recognize text (Python)", "Set recognition settings"],
      actions: [{ label: "Open triage", href: "#triage" }],
    },
    {
      capability_id: "aspose.cells::net",
      product_id: "aspose.cells",
      product_name: "Aspose.Cells",
      product_family: "aspose",
      programming_language: "net",
      status: "ready",
      onboarding_priority: "medium",
      latest_stable_visible: true,
      freshness_label: "fresh",
      resolved_version: "24.12",
      newest_available_version: "24.12",
      executable_snippets_count: 63,
      registered_source_kinds: ["docs", "apiref"],
      ready_source_kinds: ["docs", "apiref"],
      gap_badges: [],
      summary: "Full coverage across docs and API reference.",
      snippet_titles: ["Open and save a workbook", "Read a cell value", "Apply a formula"],
      actions: [{ label: "Open coverage", href: "#coverage" }],
    },
    {
      capability_id: "aspose.cells::java",
      product_id: "aspose.cells",
      product_name: "Aspose.Cells",
      product_family: "aspose",
      programming_language: "java",
      status: "partial",
      onboarding_priority: "medium",
      latest_stable_visible: false,
      freshness_label: "aging",
      resolved_version: "24.9",
      newest_available_version: "24.12",
      executable_snippets_count: 21,
      registered_source_kinds: ["docs", "apiref"],
      ready_source_kinds: ["apiref"],
      gap_badges: ["docs_not_ready", "latest_stable_hidden"],
      summary: "API reference ready; docs not yet republished at latest-stable.",
      snippet_titles: ["Create a workbook (Java)", "Write to a cell"],
      actions: [{ label: "Open triage", href: "#triage" }],
    },
    {
      capability_id: "aspose.3d::net",
      product_id: "aspose.3d",
      product_name: "Aspose.3D",
      product_family: "aspose",
      programming_language: "net",
      status: "registered_only",
      onboarding_priority: "low",
      latest_stable_visible: false,
      freshness_label: null,
      resolved_version: null,
      newest_available_version: null,
      executable_snippets_count: 0,
      registered_source_kinds: ["docs", "apiref"],
      ready_source_kinds: [],
      gap_badges: ["no_index_data", "no_snapshot"],
      summary: "Repositories registered but never ingested — no snapshot, no snippets.",
      snippet_titles: [],
      actions: [{ label: "Open triage", href: "#triage" }],
    },
  ],
  generated_at: "2026-06-10T09:00:00Z",
};

export default function CapabilityExplorer() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  const query = useQuery({
    queryKey: ["public-capability-explorer", sourceFilter],
    // Source is a server-side filter; status is applied client-side over the
    // display source so the same predicate works on fixtures offline.
    queryFn: () =>
      fetchPublicCapabilityExplorer(sourceFilter === "all" ? {} : { source_kind: sourceFilter }),
  });

  // Display source with fixture fallback (offline / empty → fixtures).
  const live = query.data;
  const board: PublicCapabilityExplorer = live && live.items.length > 0 ? live : FIXTURE;
  const isFixture = !(live && live.items.length > 0);

  const shown = useMemo(() => {
    return board.items.filter((it) => {
      if (statusFilter !== "all" && it.status !== statusFilter) return false;
      if (sourceFilter !== "all" && !it.registered_source_kinds.includes(sourceFilter)) return false;
      return true;
    });
  }, [board.items, statusFilter, sourceFilter]);

  const loading = query.isLoading && !board.items.length;
  const errored = query.isError && !board.items.length;

  return (
    <section className="pub-card" aria-label="Capability explorer">
      <div className="pub-card-head">
        <span className="pub-card-title">Capability explorer</span>
        <span className="right" style={{ display: "flex", gap: 8 }}>
          <span className="select" style={{ height: 28, minWidth: 150 }}>
            <label className="sr-only" htmlFor="cap-status" style={{ display: "none" }}>
              Capability status
            </label>
            <select
              id="cap-status"
              className="selectctl"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              aria-label="Capability status"
            >
              {STATUS_OPTS.map((o) => (
                <option key={o} value={o}>
                  {o === "all" ? "All status" : o.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </span>
          <span className="select" style={{ height: 28, minWidth: 130 }}>
            <select
              id="cap-source"
              className="selectctl"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
              aria-label="Capability source focus"
            >
              {SOURCE_OPTS.map((o) => (
                <option key={o} value={o}>
                  {o === "all" ? "All sources" : o}
                </option>
              ))}
            </select>
          </span>
        </span>
      </div>

      <div style={{ padding: "12px 20px 0" }}>
        <Banner
          variant={isFixture ? "info" : board.gap_total > 0 ? "warn" : "ok"}
          icon="layers"
          guidance
          title={board.status_summary}
          text={
            isFixture
              ? "Showing sample capability data — live values appear when the public API is reachable."
              : `${board.ready_total} ready · ${board.partial_total} partial · ${board.gap_total} gap across ${board.products_total} products.`
          }
        />
      </div>

      {loading ? (
        <div style={{ padding: "16px 20px" }} className="muted-note">
          Loading capability surfaces…
        </div>
      ) : errored ? (
        <div style={{ padding: "16px 20px" }}>
          <Banner
            variant="warn"
            icon="alert"
            title="Could not load capabilities"
            text={query.error ? (query.error as Error).message : undefined}
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => query.refetch()}>
                Retry
              </Button>
            }
          />
        </div>
      ) : shown.length === 0 ? (
        <div style={{ padding: "8px 20px 20px" }}>
          <EmptyState
            title="No capabilities match the filters"
            text="Try broadening the status or source filter to see registered product surfaces."
            action={
              <Button
                variant="btn-ghost"
                size="sm"
                icon="refresh"
                onClick={() => {
                  setStatusFilter("all");
                  setSourceFilter("all");
                }}
              >
                Clear filters
              </Button>
            }
          />
        </div>
      ) : (
        <div>
          {shown.map((it) => (
            <div className="svc-row" key={it.capability_id} style={{ alignItems: "flex-start" }}>
              <Pill variant={statusVariant(it.status)}>{it.status.replace(/_/g, " ")}</Pill>
              <div style={{ minWidth: 0 }}>
                <div className="svc-name">
                  <span className="mono">{it.product_id}</span> · {it.programming_language}
                  <span className="muted-note" style={{ marginLeft: 8, fontWeight: 400 }}>
                    {it.onboarding_priority} priority
                  </span>
                </div>
                <div className="svc-desc">{it.summary}</div>

                {it.snippet_titles.length > 0 && (
                  <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {it.snippet_titles.map((t) => (
                      <Tag key={t}>{t}</Tag>
                    ))}
                  </div>
                )}

                {it.gap_badges.length > 0 && (
                  <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {it.gap_badges.map((g) => (
                      <span className="stale-badge" key={g} title="Coverage gap">
                        <Icon name="alert" className="ico" />
                        {g.replace(/_/g, " ")}
                      </span>
                    ))}
                  </div>
                )}

                {it.actions.length > 0 && (
                  <div style={{ marginTop: 8, display: "flex", gap: 12, flexWrap: "wrap" }}>
                    {it.actions.map((a) => (
                      <a
                        key={a.label}
                        href={a.href}
                        className="mono"
                        style={{ fontSize: 11.5, color: "var(--accent-line)", display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        {a.label}
                        <Icon name="arrow" />
                      </a>
                    ))}
                  </div>
                )}
              </div>
              <div
                className="svc-up"
                style={{ width: "auto", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-subtle)", textAlign: "right" }}
              >
                {it.executable_snippets_count} snippets
                <br />
                {it.resolved_version ?? "—"}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
