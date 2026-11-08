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
  fetchPublicReleaseFreshness,
  type PublicReleaseFreshness,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Freshness & Release Visibility — section component for /integrations.
 *
 * Current release version and freshness status; latest snapshot timestamps;
 * release-note features. freshnessQuery → /v1/integrations/freshness. Two metric
 * cards (resolved_version, newest_available_version), per-source services table
 * (source_kind, mcp_ready pill, latest_version, snapshot_id, snapshot timestamp,
 * chunks), release-features accordion (kind pill, summary, symbol_fqn,
 * canonical_url link).
 *
 * Live wiring: the public fetchPublicReleaseFreshness (no auth) takes
 * product_id + optional programming_language / version. Product + language are
 * submitted-on-Apply server-side filters.
 *
 * Offline fallback:
 *   - live success            -> live PublicReleaseFreshness
 *   - live success but EMPTY   -> designed empty state (no services)
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file FRESHNESS_FIXTURE (fully reviewable)
 * State gates resolve on the DISPLAY set so fixtures always win offline.
 * -------------------------------------------------------------------------- */

function readyVariant(ready: boolean): StatusVariant {
  return ready ? "ok" : "warn";
}

function featureKindVariant(kind: string): StatusVariant {
  const k = kind.toLowerCase();
  if (k.includes("new") || k.includes("add") || k.includes("feature")) return "ok";
  if (k.includes("deprecat") || k.includes("remov") || k.includes("break")) return "crit";
  if (k.includes("chang") || k.includes("updat")) return "warn";
  return "info";
}

function relativeDays(iso: string | null): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const days = Math.max(0, Math.round((Date.now() - then) / 86_400_000));
  if (days === 0) return "today";
  return `${days}d ago`;
}

/* ---------------- offline fixture (verbatim-shaped response) ---------------- */

const FRESHNESS_FIXTURE: PublicReleaseFreshness = {
  product_id: "aspose.ocr",
  programming_language: "net",
  requested_version: null,
  resolved_version: "24.12",
  newest_available_version: "24.12",
  available_versions: ["24.12", "24.11", "24.9", "24.6"],
  latest_active_snapshot_at: "2026-05-16T08:00:00Z",
  services: [
    {
      source_kind: "docs",
      mcp_ready: true,
      latest_version: "24.12",
      latest_source_revision: "a1b2c3d",
      latest_snapshot_id: "snap_docs_2412",
      latest_snapshot_created_at: "2026-05-16T08:00:00Z",
      indexed_chunks_count: 188963,
    },
    {
      source_kind: "apiref",
      mcp_ready: false,
      latest_version: "24.11",
      latest_source_revision: "e4f5g6h",
      latest_snapshot_id: "snap_apiref_2411",
      latest_snapshot_created_at: "2026-04-21T08:00:00Z",
      indexed_chunks_count: 161802,
    },
  ],
  release_features: [
    {
      kind: "new",
      summary: "Added GPU-accelerated recognition for large multi-page PDFs.",
      symbol_fqn: "Aspose.OCR.RecognitionSettings.UseGpu",
      version: "24.12",
      source_kind: "docs",
      canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings/",
      section_anchor: "#use-gpu",
    },
    {
      kind: "changed",
      summary: "Default recognition language switched from auto-detect to Eng.",
      symbol_fqn: "Aspose.OCR.RecognitionSettings.Language",
      version: "24.12",
      source_kind: "docs",
      canonical_url: "https://docs.aspose.com/ocr/net/recognition-language/",
      section_anchor: "#default-language",
    },
    {
      kind: "deprecated",
      summary: "RecognizeImage(string) is deprecated in favor of Recognize(OcrInput).",
      symbol_fqn: "Aspose.OCR.AsposeOcr.RecognizeImage",
      version: "24.12",
      source_kind: "apiref",
      canonical_url:
        "https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage/",
      section_anchor: "#deprecated",
    },
  ],
  status_summary:
    "Resolved version 24.12 matches the newest available, but the API reference snapshot is one version behind and aging.",
  generated_at: "2026-06-10T09:00:00Z",
};

/* ---------------- visually-hidden label helper ----------------------------- */

const SR_ONLY: React.CSSProperties = {
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

/* -------------------------------------------------------------------------- */

interface FormState {
  product: string;
  language: string;
}

const DEFAULT_FORM: FormState = { product: "aspose.ocr", language: "net" };

export default function FreshnessVisibility() {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState<FormState>(DEFAULT_FORM);
  const [featuresOpen, setFeaturesOpen] = useState(true);

  const query = useQuery({
    queryKey: ["public-release-freshness", submitted.product, submitted.language],
    queryFn: () =>
      fetchPublicReleaseFreshness({
        product_id: submitted.product || "aspose.ocr",
        programming_language: submitted.language || undefined,
      }),
    staleTime: 60_000,
  });

  // Display source with fixture fallback — fixtures always win offline.
  const live = query.data;
  const board: PublicReleaseFreshness =
    live && live.services.length > 0 ? live : FRESHNESS_FIXTURE;
  const isFixture = !(live && live.services.length > 0);

  const loading = query.isLoading && !board.services.length;
  const errored = query.isError && !board.services.length;

  const versionBehind = useMemo(
    () =>
      board.resolved_version != null &&
      board.newest_available_version != null &&
      board.resolved_version !== board.newest_available_version,
    [board.resolved_version, board.newest_available_version],
  );

  const onApply = () => {
    setSubmitted({ product: form.product.trim(), language: form.language.trim() });
  };

  const onReset = () => {
    setForm(DEFAULT_FORM);
    setSubmitted(DEFAULT_FORM);
  };

  return (
    <section className="pub-card" id="freshness" aria-label="Freshness and release visibility">
      <div className="pub-card-head">
        <span className="pub-card-title">Freshness &amp; release visibility</span>
        <span className="right" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Pill variant={versionBehind ? "warn" : "ok"}>
            {versionBehind ? "version gap" : "up to date"}
          </Pill>
          <span className="muted-note">
            snapshot {relativeDays(board.latest_active_snapshot_at)}
          </span>
        </span>
      </div>

      {/* scope form (Product · Language) */}
      <form
        style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}
        onSubmit={(e) => {
          e.preventDefault();
          onApply();
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
            gap: 12,
          }}
        >
          <span className="field">
            <label className="flabel" htmlFor="freshness-product">
              Product ID
            </label>
            <input
              id="freshness-product"
              className="inputctl"
              value={form.product}
              onChange={(e) => setForm((f) => ({ ...f, product: e.target.value }))}
              placeholder="aspose.ocr"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="freshness-language">
              SDK Language
            </label>
            <input
              id="freshness-language"
              className="inputctl"
              value={form.language}
              onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
              placeholder="net"
              autoComplete="off"
            />
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <button type="submit" className="pub-cta" style={{ height: 34, fontSize: 13 }} disabled={loading}>
            Check freshness <Icon name="refresh" />
          </button>
          <button type="button" className="pub-cta ghost" style={{ height: 34, fontSize: 13 }} onClick={onReset}>
            Reset
          </button>
        </div>
      </form>

      {loading ? (
        <div style={{ padding: "16px 20px" }} className="muted-note">
          Loading release freshness…
        </div>
      ) : errored ? (
        <div style={{ padding: "16px 20px" }}>
          <Banner
            variant="warn"
            icon="alert"
            title="Could not load freshness"
            text={query.error ? (query.error as Error).message : undefined}
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => query.refetch()}>
                Retry
              </Button>
            }
          />
        </div>
      ) : (
        <>
          <div style={{ padding: "12px 20px 0" }}>
            <Banner
              variant={isFixture ? "info" : versionBehind ? "warn" : "ok"}
              icon="clock"
              guidance
              title={board.status_summary}
              text={
                isFixture
                  ? "Showing sample freshness data — live values appear when the public API is reachable."
                  : undefined
              }
            />
          </div>

          {/* two metric cards — resolved vs newest version */}
          <div
            className="metric-strip"
            style={{ gridTemplateColumns: "1fr 1fr", borderTop: "1px solid var(--border)" }}
            role="group"
            aria-label="Release versions"
          >
            <div className="m">
              <div className="mv">{board.resolved_version ?? "—"}</div>
              <div className="ml">Resolved version</div>
            </div>
            <div className="m">
              <div className="mv">{board.newest_available_version ?? "—"}</div>
              <div className="ml" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                Newest available
                {versionBehind ? <Pill variant="warn">behind</Pill> : null}
              </div>
            </div>
          </div>

          {board.available_versions.length > 0 ? (
            <div
              style={{
                padding: "12px 20px",
                borderTop: "1px solid var(--border)",
                display: "flex",
                gap: 6,
                flexWrap: "wrap",
                alignItems: "center",
              }}
            >
              <span className="muted-note" style={{ marginRight: 4 }}>
                Available versions
              </span>
              {board.available_versions.map((v) => (
                <Tag key={v}>{v}</Tag>
              ))}
            </div>
          ) : null}

          {/* per-source services table */}
          {board.services.length === 0 ? (
            <div style={{ padding: "8px 20px 20px" }}>
              <EmptyState
                title="No indexed services for this scope"
                text="This product/language has no active snapshot yet. Check the coverage navigator and triage center."
                action={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onReset}>
                    Reset scope
                  </Button>
                }
              />
            </div>
          ) : (
            <div style={{ overflowX: "auto", borderTop: "1px solid var(--border)" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th style={{ width: 110 }}>MCP ready</th>
                    <th style={{ width: 110 }}>Version</th>
                    <th style={{ width: 140 }}>Snapshot</th>
                    <th className="num" style={{ width: 120 }}>
                      Chunks
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {board.services.map((svc) => (
                    <tr className="data" key={svc.source_kind}>
                      <td>
                        <span className="svc-name" style={{ fontSize: 12.5 }}>
                          {svc.source_kind}
                        </span>
                        {svc.latest_source_revision ? (
                          <div className="muted-note mono">rev {svc.latest_source_revision}</div>
                        ) : null}
                      </td>
                      <td>
                        <Pill variant={readyVariant(svc.mcp_ready)}>
                          {svc.mcp_ready ? "ready" : "not ready"}
                        </Pill>
                      </td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {svc.latest_version ?? "—"}
                      </td>
                      <td>
                        <div className="mono" style={{ fontSize: 11 }}>
                          {svc.latest_snapshot_id ?? "—"}
                        </div>
                        <div className="muted-note">
                          {relativeDays(svc.latest_snapshot_created_at)}
                        </div>
                      </td>
                      <td className="num">{svc.indexed_chunks_count.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* release-features accordion */}
          {board.release_features.length > 0 ? (
            <div style={{ borderTop: "1px solid var(--border)", padding: "14px 20px" }}>
              <button
                type="button"
                className="pub-cta ghost"
                style={{ height: 30, fontSize: 12.5, padding: "0 12px" }}
                onClick={() => setFeaturesOpen((o) => !o)}
                aria-expanded={featuresOpen}
                aria-controls="freshness-features"
              >
                <Icon name={featuresOpen ? "chevron" : "chevronR"} />
                Release features ({board.release_features.length})
              </button>

              {featuresOpen ? (
                <div id="freshness-features" style={{ marginTop: 12, display: "grid", gap: 10 }}>
                  {board.release_features.map((feat, i) => (
                    <div
                      key={`${feat.symbol_fqn ?? feat.summary}-${i}`}
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius)",
                        padding: 12,
                        background: "var(--surface)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <Pill variant={featureKindVariant(feat.kind)}>{feat.kind}</Pill>
                        <Tag>v{feat.version}</Tag>
                        <Tag>{feat.source_kind}</Tag>
                      </div>
                      <div className="svc-desc" style={{ marginTop: 6 }}>
                        {feat.summary}
                      </div>
                      {feat.symbol_fqn ? (
                        <div className="muted-note mono" style={{ marginTop: 4 }}>
                          {feat.symbol_fqn}
                        </div>
                      ) : null}
                      <a
                        href={`${feat.canonical_url}${feat.section_anchor}`}
                        target="_blank"
                        rel="noreferrer"
                        className="mono"
                        style={{
                          marginTop: 6,
                          fontSize: 11.5,
                          color: "var(--accent-line)",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        View release note
                        <Icon name="arrow" />
                      </a>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}

      <span style={SR_ONLY} aria-hidden="true" />
    </section>
  );
}
