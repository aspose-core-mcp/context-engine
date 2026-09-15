"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { AdminApiError, fetchPublicReleaseAdoption } from "@/lib/admin-api";
import type { PublicReleaseAdoption } from "@/lib/admin-api";

import { Pill } from "../../components/Pill";
import { Tag } from "../../components/Tag";
import { Icon } from "../../lib/icons";
import type { StatusVariant } from "../../lib/types";

/* ----------------------------------------------------------------------------
 * Release Adoption Desk — standalone public Mono section.
 *
 * Data: useQuery → fetchPublicReleaseAdoption (PUBLIC, no auth, enabled always).
 *   - live success            → render the live adoption guidance
 *   - live success but empty   → designed empty state (no recommended range / no
 *                                breaking changes / no features)
 *   - live error / no backend  → designed error notice (Retry) AND the in-file
 *                                fixture so the section stays fully reviewable
 *                                offline (in-file fixtures are the offline fallback).
 *
 * Styling: only mono.css `.pub` scope classes + kit Pill/Tag + tokens.
 * No new colors/fonts.
 * -------------------------------------------------------------------------- */

/** Visually-hidden style (kit has no .sr-only class). */
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

const DEFAULT_PRODUCT = "aspose.ocr";
const DEFAULT_LANGUAGE = "net";

/** status → closed Mono pill palette. */
function statusVariant(status: string): StatusVariant {
  const s = status.toLowerCase();
  if (s === "ready" || s === "ok" || s === "strong") return "ok";
  if (s === "watch" || s === "warn" || s === "aging" || s === "partial") return "warn";
  if (s === "blocked" || s === "crit" || s === "weak" || s === "not_ready" || s === "not-ready")
    return "crit";
  return "neutral";
}

/* ----------------------------------------------------------------------------
 * Offline fixture — shape-complete PublicReleaseAdoption (reviewable with no backend)
 * -------------------------------------------------------------------------- */

const ADOPTION_FIXTURE: PublicReleaseAdoption = {
  product_id: DEFAULT_PRODUCT,
  programming_language: DEFAULT_LANGUAGE,
  requested_version: null,
  resolved_version: "25.1",
  newest_available_version: "25.1",
  recommended_from_version: "24.12",
  recommended_to_version: "25.1",
  status: "watch",
  freshness_label: "aging",
  status_summary:
    "Recommended upgrade 24.12 → 25.1 carries 3 breaking change(s); review them before promoting the upgrade prompt.",
  latest_active_snapshot_at: "2026-05-16T09:12:00Z",
  migration_checklist: [
    "Pin retrieval to version 25.1 and re-run the product self-test before announcing.",
    "Validate the 3 breaking change(s) against your generated code paths.",
    "Update client config samples to the resolved target version.",
    "Re-run the query playground and confirm no new regressions before promotion.",
  ],
  upgrade_prompt:
    "Upgrade aspose.ocr (net) from 24.12 to 25.1. First list the latest release features and the breaking changes, then produce a migration checklist with cited APIs and exact symbol validation steps.",
  fix_plan: [
    "Active snapshot is 25 days old (target 30d) — schedule a refresh.",
    "No blocking breaking changes detected; safe to plan the upgrade.",
  ],
  compare_ranges: [
    {
      range_id: "r-2412-251",
      from_version: "24.12",
      to_version: "25.1",
      breaking_changes_total: 3,
      status: "watch",
      summary: "Recommended migration range. Signature changes in RecognitionSettings.",
    },
    {
      range_id: "r-2411-2412",
      from_version: "24.11",
      to_version: "24.12",
      breaking_changes_total: 0,
      status: "ready",
      summary: "Additive-only release. Safe to adopt without code changes.",
    },
  ],
  latest_release: {
    product_id: DEFAULT_PRODUCT,
    language: DEFAULT_LANGUAGE,
    resolved_version: "25.1",
    items: [
      {
        kind: "feature",
        summary: "Added structured table-recognition output with cell bounding boxes.",
        symbol_fqn: "Aspose.OCR.OcrEngine.RecognizeTable",
        version: "25.1",
        source_kind: "apiref",
        citation: {
          canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/ocrengine/recognizetable/",
          section_anchor: "#recognizetable",
        },
      },
      {
        kind: "improvement",
        summary: "Improved multi-language detection accuracy for mixed-script documents.",
        symbol_fqn: "Aspose.OCR.RecognitionSettings.Language",
        version: "25.1",
        source_kind: "docs",
        citation: {
          canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings/",
          section_anchor: "#language",
        },
      },
    ],
    guardrails: [],
  },
  breaking_changes: {
    items: [
      {
        type: "signature_change",
        symbol_fqn: "Aspose.OCR.RecognitionSettings.Language",
        from_version: "24.12",
        to_version: "25.1",
        description: "Language is now an enum flag set instead of a single string value.",
        migration_hint: "Replace the string assignment with the Languages flag enum.",
        citation: {
          canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings/",
          section_anchor: "#language",
        },
      },
      {
        type: "removed_member",
        symbol_fqn: "Aspose.OCR.OcrEngine.RecognizeFast",
        from_version: "24.12",
        to_version: "25.1",
        description: "RecognizeFast was removed in favor of the speed-mode setting.",
        migration_hint: "Use Recognize with RecognitionSettings.DetectAreasMode = Fast.",
        citation: {
          canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/ocrengine/",
          section_anchor: "#recognize",
        },
      },
      {
        type: "default_changed",
        symbol_fqn: "Aspose.OCR.RecognitionSettings.DetectAreas",
        from_version: "24.12",
        to_version: "25.1",
        description: "DetectAreas now defaults to true.",
        migration_hint: "Set DetectAreas = false explicitly to preserve 24.12 behavior.",
        citation: {
          canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/recognitionsettings/",
          section_anchor: "#detectareas",
        },
      },
    ],
    page: 1,
    page_size: 50,
    total: 3,
  },
  actions: [
    { label: "Open freshness panel", href: "#freshness" },
    { label: "Open upgrade assistant", href: "#upgrade-assistant" },
  ],
  generated_at: "2026-06-10T00:00:00Z",
};

/* ----------------------------------------------------------------------------
 * Section
 * -------------------------------------------------------------------------- */

export default function ReleaseAdoption() {
  // Filters drive the live query AND (offline) the displayed scope echo.
  const [productInput, setProductInput] = useState(DEFAULT_PRODUCT);
  const [languageInput, setLanguageInput] = useState(DEFAULT_LANGUAGE);
  const [versionInput, setVersionInput] = useState("");
  const [submitted, setSubmitted] = useState({
    product_id: DEFAULT_PRODUCT,
    programming_language: DEFAULT_LANGUAGE,
    version: "",
  });

  const adoptionQuery = useQuery({
    queryKey: [
      "public-release-adoption",
      submitted.product_id,
      submitted.programming_language,
      submitted.version,
    ],
    queryFn: () =>
      fetchPublicReleaseAdoption({
        product_id: submitted.product_id,
        programming_language: submitted.programming_language,
        version: submitted.version.trim() ? submitted.version.trim() : undefined,
      }),
    enabled: true, // public endpoint — no auth/session gate
  });

  // Display source: live data when present, fixture otherwise (offline reviewable).
  const live = adoptionQuery.data ?? null;
  const usingFixture = live === null;
  const data = live ?? ADOPTION_FIXTURE;

  // A live response that resolved no range AND surfaced nothing is "empty".
  const isLiveEmpty =
    live !== null &&
    !live.recommended_from_version &&
    !live.recommended_to_version &&
    live.breaking_changes.total === 0 &&
    live.latest_release.items.length === 0;

  const errored = adoptionQuery.isError;
  const errorMessage =
    adoptionQuery.error instanceof AdminApiError
      ? adoptionQuery.error.message
      : "Could not reach the release-adoption service.";

  const runRefresh = useCallback(() => {
    setSubmitted({
      product_id: productInput.trim() || DEFAULT_PRODUCT,
      programming_language: languageInput.trim() || DEFAULT_LANGUAGE,
      version: versionInput.trim(),
    });
  }, [productInput, languageInput, versionInput]);

  // Copy-to-clipboard for the upgrade prompt (announces via aria-live).
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(data.upgrade_prompt);
    } catch {
      /* clipboard blocked — still confirm */
    }
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  }, [data.upgrade_prompt]);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const recommendedRange = useMemo(() => {
    if (data.recommended_from_version && data.recommended_to_version) {
      return `${data.recommended_from_version} → ${data.recommended_to_version}`;
    }
    return "not-ready";
  }, [data.recommended_from_version, data.recommended_to_version]);

  const productId = useId();
  const languageId = useId();
  const versionId = useId();

  return (
    <>
      {/* scope toolbar — owns the section anchor (peers self-anchor likewise) */}
      <section
        className="pub-card"
        id="release-adoption"
        style={{ padding: 20 }}
        aria-label="Release adoption scope"
      >
          <form
            className="toolbar"
            style={{ margin: 0 }}
            onSubmit={(e) => {
              e.preventDefault();
              runRefresh();
            }}
          >
            <span className="input" style={{ minWidth: 170 }}>
              <label style={SR_ONLY} htmlFor={productId}>
                Product ID
              </label>
              <input
                id={productId}
                className="inputctl"
                value={productInput}
                onChange={(e) => setProductInput(e.target.value)}
                placeholder="aspose.ocr"
              />
            </span>
            <span className="input" style={{ minWidth: 120 }}>
              <label style={SR_ONLY} htmlFor={languageId}>
                SDK language
              </label>
              <input
                id={languageId}
                className="inputctl"
                value={languageInput}
                onChange={(e) => setLanguageInput(e.target.value)}
                placeholder="net"
              />
            </span>
            <span className="input" style={{ minWidth: 150 }}>
              <label style={SR_ONLY} htmlFor={versionId}>
                Version (optional)
              </label>
              <input
                id={versionId}
                className="inputctl"
                value={versionInput}
                onChange={(e) => setVersionInput(e.target.value)}
                placeholder="latest-stable or 25.1"
              />
            </span>
            <button type="submit" className="pub-cta" style={{ height: 34, fontSize: 13 }}>
              {adoptionQuery.isFetching ? "Loading…" : "Load adoption guidance"}
            </button>
          </form>
          <div className="muted-note" style={{ marginTop: 10 }}>
            Scope: {data.product_id} / {data.programming_language ?? "auto"} · uses only the public{" "}
            <span className="mono">/v1/integrations/release-adoption</span> endpoint.
          </div>
        </section>

        {/* offline / error notice — honest, non-blocking (fixtures still render) */}
        {usingFixture && errored ? (
          <section className="pub-card" style={{ padding: 16 }} role="alert">
            <div className="svc-row" style={{ padding: 0, borderBottom: "none" }}>
              <Pill variant="warn">offline</Pill>
              <div>
                <div className="svc-name">Showing sample adoption guidance</div>
                <div className="svc-desc">{errorMessage} Reconnect to load live data.</div>
              </div>
              <button
                type="button"
                className="pub-cta ghost"
                style={{ height: 32, fontSize: 12, marginLeft: "auto" }}
                onClick={() => void adoptionQuery.refetch()}
              >
                <Icon name="refresh" />
                Retry
              </button>
            </div>
          </section>
        ) : null}

        {/* status summary + KPI strip */}
        <section className="pub-card" style={{ marginTop: 4 }} aria-label="Adoption summary">
          <div className="pub-card-head">
            <span className="pub-card-title">Adoption summary</span>
            <span className="right" style={{ marginLeft: "auto" }}>
              <Pill variant={statusVariant(data.status)}>{data.status}</Pill>
            </span>
          </div>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
            <span className="svc-desc" style={{ marginTop: 0 }}>
              {data.status_summary}
            </span>
          </div>
          <div className="metric-strip">
            <div className="m">
              <div className="mv" style={{ fontSize: 18 }}>
                {recommendedRange}
              </div>
              <div className="ml">Recommended range</div>
            </div>
            <div className="m">
              <div className="mv">{data.breaking_changes.total}</div>
              <div className="ml">Breaking changes</div>
            </div>
            <div className="m">
              <div className="mv">{data.latest_release.items.length}</div>
              <div className="ml">Latest features · {data.latest_release.resolved_version}</div>
            </div>
            <div className="m">
              <div className="mv" style={{ fontSize: 18 }}>
                <Pill variant={statusVariant(data.freshness_label)}>{data.freshness_label}</Pill>
              </div>
              <div className="ml">
                Freshness · {data.latest_active_snapshot_at?.slice(0, 10) ?? "no snapshot"}
              </div>
            </div>
          </div>
        </section>

        {isLiveEmpty ? (
          /* designed empty state — live responded with no actionable guidance */
          <section className="pub-card" style={{ padding: 28, textAlign: "center" }}>
            <div className="pub-card-title" style={{ marginBottom: 8 }}>
              No upgrade range to recommend
            </div>
            <div className="muted-note" style={{ maxWidth: 460, margin: "0 auto" }}>
              This scope has a single visible release (or no comparable range yet). Add a target
              version above, or check the freshness panel once a newer snapshot is indexed.
            </div>
          </section>
        ) : (
          <>
            {/* recommended migration path */}
            <section className="pub-card" style={{ padding: 22 }} aria-label="Recommended migration path">
              <div className="pub-card-title" style={{ marginBottom: 14 }}>
                Recommended migration path
              </div>
              <ol className="step-list">
                {data.migration_checklist.map((step) => (
                  <li className="step-card" key={step}>
                    <div className="sn" aria-hidden="true" />
                    <div>
                      <div className="st-body" style={{ marginTop: 4 }}>
                        {step}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              <div
                style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 18 }}
              >
                <button
                  type="button"
                  className="pub-cta"
                  style={{ height: 34, fontSize: 13 }}
                  onClick={copyPrompt}
                >
                  {copied ? "Copied upgrade prompt" : "Copy upgrade prompt"}
                </button>
                {data.actions.map((action) => (
                  <a
                    key={action.label}
                    className="pub-cta ghost"
                    style={{ height: 34, fontSize: 13 }}
                    href={action.href}
                  >
                    {action.label}
                  </a>
                ))}
              </div>
              <span style={SR_ONLY} role="status" aria-live="polite">
                {copied ? "Upgrade prompt copied to clipboard" : ""}
              </span>
            </section>

            {/* breaking changes table */}
            <section className="pub-card" aria-label="Breaking changes">
              <div className="pub-card-head">
                <span className="pub-card-title">Breaking changes</span>
                <span className="right muted-note">
                  {data.recommended_from_version ?? "?"} → {data.recommended_to_version ?? "?"}
                </span>
              </div>
              {data.breaking_changes.items.length === 0 ? (
                <div style={{ padding: "16px 20px" }}>
                  <span className="muted-note">
                    No breaking changes in the recommended range — additive-only.
                  </span>
                </div>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th style={{ width: 150 }}>Type</th>
                        <th>Symbol</th>
                        <th>Description &amp; migration hint</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.breaking_changes.items.map((item, i) => (
                        <tr className="data" key={`${item.type}-${item.symbol_fqn}-${i}`}>
                          <td>
                            <Pill variant="warn">{item.type}</Pill>
                          </td>
                          <td>
                            {item.symbol_fqn ? (
                              <span className="repo-id">{item.symbol_fqn}</span>
                            ) : (
                              <span className="muted-note">—</span>
                            )}
                          </td>
                          <td>
                            <div className="svc-name" style={{ fontSize: 12.5, fontWeight: 500 }}>
                              {item.description}
                            </div>
                            <div className="svc-desc" style={{ marginTop: 3 }}>
                              Migration hint: {item.migration_hint}
                            </div>
                            <a
                              className="muted-note"
                              href={`${item.citation.canonical_url}${item.citation.section_anchor}`}
                              target="_blank"
                              rel="noreferrer"
                              style={{ textDecoration: "underline" }}
                            >
                              View citation
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* latest release features */}
            <section className="pub-card" aria-label="Latest release features">
              <div className="pub-card-head">
                <span className="pub-card-title">Latest release features</span>
                <span className="right muted-note">
                  resolved {data.latest_release.resolved_version}
                </span>
              </div>
              {data.latest_release.items.length === 0 ? (
                <div style={{ padding: "16px 20px" }}>
                  <span className="muted-note">No release-note features indexed for this scope.</span>
                </div>
              ) : (
                data.latest_release.items.map((item, i) => (
                  <div className="svc-row" key={`${item.summary}-${i}`}>
                    <Tag>{item.kind}</Tag>
                    <div>
                      <div className="svc-name" style={{ fontSize: 13 }}>
                        {item.summary}
                      </div>
                      <div className="svc-desc">
                        {item.symbol_fqn ? (
                          <span className="mono">{item.symbol_fqn}</span>
                        ) : (
                          item.source_kind
                        )}{" "}
                        ·{" "}
                        <a
                          href={`${item.citation.canonical_url}${item.citation.section_anchor}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ textDecoration: "underline", color: "var(--fg-muted)" }}
                        >
                          citation
                        </a>
                      </div>
                    </div>
                    <div
                      className="svc-up"
                      style={{ width: "auto", fontFamily: "var(--font-mono)", fontSize: 11 }}
                    >
                      {item.version}
                    </div>
                  </div>
                ))
              )}
            </section>

            {/* compare visible ranges */}
            {data.compare_ranges.length > 0 ? (
              <section className="pub-card" aria-label="Compare visible ranges">
                <div className="pub-card-head">
                  <span className="pub-card-title">Compare visible ranges</span>
                  <span className="right muted-note">{data.compare_ranges.length} range(s)</span>
                </div>
                {data.compare_ranges.map((range) => (
                  <div className="svc-row" key={range.range_id}>
                    <Pill variant={statusVariant(range.status)}>{range.status}</Pill>
                    <div>
                      <div className="svc-name" style={{ fontSize: 13 }}>
                        <span className="mono">
                          {range.from_version} → {range.to_version}
                        </span>
                      </div>
                      <div className="svc-desc">{range.summary}</div>
                    </div>
                    <div style={{ marginLeft: "auto" }}>
                      <Tag>breaking {range.breaking_changes_total}</Tag>
                    </div>
                  </div>
                ))}
              </section>
            ) : null}
          </>
        )}
    </>
  );
}
