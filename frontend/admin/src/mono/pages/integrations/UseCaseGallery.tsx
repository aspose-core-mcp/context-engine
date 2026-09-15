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
  fetchPublicUseCaseGallery,
  type PublicUseCaseGallery,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Use-Case Gallery — section component for /integrations.
 *
 * Curated use-case scenarios showcasing MCP capabilities; apply to the playground
 * to start from a pattern. useCaseGalleryQuery → /v1/integrations/use-cases. Filters (product,
 * language, client, status); use-case cards with category pill, title, status
 * pill, summary, starter_prompt, starter_query, recommended_journey_id badge,
 * evidence links, Apply + Focus journey.
 *
 * Live wiring: the public fetchPublicUseCaseGallery (no auth) takes
 * product_id + optional programming_language / client_id / status. Product,
 * language and client are submitted-on-Apply server-side filters; status also
 * filters the display source client-side so the same predicate works offline.
 *
 * Offline fallback:
 *   - live success            -> live PublicUseCaseGallery
 *   - live success but EMPTY   -> designed empty state
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file GALLERY_FIXTURE (fully reviewable)
 * State gates resolve on the DISPLAY set so fixtures always win offline.
 * -------------------------------------------------------------------------- */

const STATUS_OPTS = ["all", "ready", "partial", "preview"] as const;
type StatusFilter = (typeof STATUS_OPTS)[number];

function statusVariant(status: string): StatusVariant {
  const s = status.toLowerCase();
  if (s === "ready" || s === "ga" || s === "stable") return "ok";
  if (s === "partial" || s === "preview" || s === "beta") return "warn";
  if (s === "blocked" || s === "unavailable") return "crit";
  return "neutral";
}

/* ---------------- offline fixture (verbatim-shaped response) ---------------- */

const GALLERY_FIXTURE: PublicUseCaseGallery = {
  filters: { product_id: null, programming_language: null, client_id: null, status: null },
  status_summary: "3 curated use-cases for aspose.ocr (net) — sample data shown offline.",
  items: [
    {
      use_case_id: "ocr-invoice-extraction",
      category: "Document automation",
      title: "Extract structured fields from scanned invoices",
      status: "ready",
      summary:
        "Recognize an invoice image, then map the recognized text into structured fields with a follow-up prompt.",
      starter_prompt:
        "Using Aspose.OCR for .NET, recognize text from an invoice image and extract the invoice number, date, and total as JSON. Cite the API reference for each OCR call.",
      starter_query: "extract invoice fields with Aspose.OCR .NET",
      recommended_journey_id: "journey-quickstart",
      client_notes: [
        { client_id: "cursor", note: "Works well with inline code actions for the mapping step." },
        { client_id: "claude-desktop", note: "Use the file picker to attach a sample invoice." },
      ],
      evidence: [
        {
          evidence_type: "snippet",
          title: "Recognize text from an image",
          canonical_url: "https://docs.aspose.com/ocr/net/recognize-image/",
          section_anchor: "#recognize-image",
          snippet_id: "ocr-net-recognize-image",
        },
      ],
      actions: [{ label: "Focus journey", href: "#journey-quickstart" }],
    },
    {
      use_case_id: "ocr-multilang-pdf",
      category: "Multi-language",
      title: "Recognize a mixed-language scanned PDF",
      status: "partial",
      summary:
        "Recognize a multi-page PDF that mixes English and German text, constraining the recognition language per page.",
      starter_prompt:
        "Using Aspose.OCR for .NET, recognize a multi-page PDF where pages alternate between English and German, setting the recognition language per page. Cite each setting.",
      starter_query: "recognize mixed-language PDF Aspose.OCR",
      recommended_journey_id: "journey-coverage",
      client_notes: [
        { client_id: "qwen-code", note: "Confirm the apiref snapshot is current before relying on language enums." },
      ],
      evidence: [
        {
          evidence_type: "snippet",
          title: "Constrain recognition language",
          canonical_url: "https://docs.aspose.com/ocr/net/recognition-language/",
          section_anchor: "#recognition-language",
          snippet_id: "ocr-net-language-constraint",
        },
      ],
      actions: [{ label: "Focus journey", href: "#journey-coverage" }],
    },
    {
      use_case_id: "ocr-handwriting-preview",
      category: "Handwriting",
      title: "Preview handwriting recognition accuracy",
      status: "preview",
      summary:
        "Evaluate handwriting recognition on a sample set and report confidence before committing to the workflow.",
      starter_prompt:
        "Using Aspose.OCR for .NET, recognize handwritten notes from an image and report the per-line confidence. Note any API members marked preview.",
      starter_query: "handwriting recognition confidence Aspose.OCR",
      recommended_journey_id: null,
      client_notes: [],
      evidence: [
        {
          evidence_type: "doc",
          title: "Recognition results and confidence",
          canonical_url: "https://docs.aspose.com/ocr/net/recognition-results/",
          section_anchor: "#confidence",
          snippet_id: null,
        },
      ],
      actions: [],
    },
  ],
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
  client: string;
}

const DEFAULT_FORM: FormState = { product: "aspose.ocr", language: "net", client: "" };

export default function UseCaseGallery() {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState<FormState>(DEFAULT_FORM);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: [
      "public-use-case-gallery",
      submitted.product,
      submitted.language,
      submitted.client,
      statusFilter,
    ],
    queryFn: () =>
      fetchPublicUseCaseGallery({
        product_id: submitted.product || "aspose.ocr",
        programming_language: submitted.language || undefined,
        client_id: submitted.client || undefined,
        status: statusFilter === "all" ? undefined : statusFilter,
      }),
    staleTime: 60_000,
  });

  // Display source with fixture fallback — fixtures always win offline.
  const live = query.data;
  const board: PublicUseCaseGallery = live && live.items.length > 0 ? live : GALLERY_FIXTURE;
  const isFixture = !(live && live.items.length > 0);

  // Status filter applies to the display source so it works offline on fixtures.
  const shown = useMemo(
    () =>
      board.items.filter((it) => statusFilter === "all" || it.status === statusFilter),
    [board.items, statusFilter],
  );

  const loading = query.isLoading && !board.items.length;
  const errored = query.isError && !board.items.length;

  const onApply = () => {
    setSubmitted({
      product: form.product.trim(),
      language: form.language.trim(),
      client: form.client.trim(),
    });
  };

  const onReset = () => {
    setForm(DEFAULT_FORM);
    setSubmitted(DEFAULT_FORM);
    setStatusFilter("all");
  };

  const copyPrompt = async (id: string, prompt: string) => {
    try {
      await navigator.clipboard.writeText(prompt);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopiedId(id);
    window.setTimeout(() => {
      setCopiedId((prev) => (prev === id ? null : prev));
    }, 2000);
  };

  return (
    <section className="pub-card" id="use-case-gallery" aria-label="Use-case gallery">
      <div className="pub-card-head">
        <span className="pub-card-title">Use-case gallery</span>
        <span className="right" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label htmlFor="usecase-status" style={SR_ONLY}>
            Use-case status
          </label>
          <select
            id="usecase-status"
            className="selectctl"
            style={{ height: 28, minWidth: 130 }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            aria-label="Use-case status"
          >
            {STATUS_OPTS.map((o) => (
              <option key={o} value={o}>
                {o === "all" ? "All status" : o}
              </option>
            ))}
          </select>
        </span>
      </div>

      {/* scope form (Product · Language · Client) */}
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
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 12,
          }}
        >
          <span className="field">
            <label className="flabel" htmlFor="usecase-product">
              Product ID
            </label>
            <input
              id="usecase-product"
              className="inputctl"
              value={form.product}
              onChange={(e) => setForm((f) => ({ ...f, product: e.target.value }))}
              placeholder="aspose.ocr"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="usecase-language">
              SDK Language
            </label>
            <input
              id="usecase-language"
              className="inputctl"
              value={form.language}
              onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
              placeholder="net"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="usecase-client">
              Client
            </label>
            <input
              id="usecase-client"
              className="inputctl"
              value={form.client}
              onChange={(e) => setForm((f) => ({ ...f, client: e.target.value }))}
              placeholder="cursor (optional)"
              autoComplete="off"
            />
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <button type="submit" className="pub-cta" style={{ height: 34, fontSize: 13 }} disabled={loading}>
            Apply filters <Icon name="search" />
          </button>
          <button type="button" className="pub-cta ghost" style={{ height: 34, fontSize: 13 }} onClick={onReset}>
            Reset
          </button>
        </div>
      </form>

      <div style={{ padding: "12px 20px 0" }}>
        <Banner
          variant={isFixture ? "info" : "ok"}
          icon="layers"
          guidance
          title={board.status_summary}
          text={
            isFixture
              ? "Showing sample use-cases — live values appear when the public API is reachable."
              : `${shown.length} shown${statusFilter !== "all" ? ` · ${statusFilter} only` : ""}.`
          }
        />
      </div>

      <div style={{ padding: "8px 20px 16px" }} aria-live="polite">
        {loading ? (
          <div className="muted-note" style={{ padding: "8px 0" }}>
            Loading use-cases…
          </div>
        ) : errored ? (
          <Banner
            variant="warn"
            icon="alert"
            title="Could not load use-cases"
            text={query.error ? (query.error as Error).message : undefined}
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => query.refetch()}>
                Retry
              </Button>
            }
          />
        ) : shown.length === 0 ? (
          <EmptyState
            title="No use-cases match the current filters"
            text="Try broadening the criteria (product, language, client, or status)."
            action={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onReset}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {shown.map((item) => {
              const copied = copiedId === item.use_case_id;
              return (
                <div
                  key={item.use_case_id}
                  id={`use-case-${item.use_case_id}`}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 16,
                    background: "var(--surface)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 6,
                      flexWrap: "wrap",
                    }}
                  >
                    <Tag>{item.category}</Tag>
                    <span className="svc-name">{item.title}</span>
                    <Pill variant={statusVariant(item.status)}>{item.status}</Pill>
                    {item.recommended_journey_id ? (
                      <span className="muted-note" style={{ marginLeft: "auto" }}>
                        journey: <span className="mono">{item.recommended_journey_id}</span>
                      </span>
                    ) : null}
                  </div>

                  <div className="svc-desc" style={{ marginBottom: 10 }}>
                    {item.summary}
                  </div>

                  {/* starter prompt */}
                  <div className="code-card">
                    <div className="code-head">
                      <span className="dot3" aria-hidden="true">
                        <i />
                        <i />
                        <i />
                      </span>
                      <span className="fname">starter prompt</span>
                      <button
                        type="button"
                        className="copy"
                        onClick={() => void copyPrompt(item.use_case_id, item.starter_prompt)}
                        aria-label={`Copy the ${item.title} starter prompt to clipboard`}
                      >
                        {copied ? "Copied" : "Copy prompt"}
                      </button>
                    </div>
                    <pre className="code-body" tabIndex={0} style={{ whiteSpace: "pre-wrap" }}>
                      {item.starter_prompt}
                    </pre>
                    <span style={SR_ONLY} role="status" aria-live="polite">
                      {copied ? `${item.title} starter prompt copied to clipboard` : ""}
                    </span>
                  </div>

                  {/* starter query */}
                  <div className="muted-note" style={{ marginTop: 8 }}>
                    Starter query: <span className="mono">{item.starter_query}</span>
                  </div>

                  {/* evidence links */}
                  {item.evidence.length > 0 ? (
                    <div style={{ marginTop: 10 }}>
                      <div className="muted-note" style={{ marginBottom: 4 }}>
                        Evidence
                      </div>
                      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                        {item.evidence.map((ev, i) => (
                          <a
                            key={`${ev.title}-${i}`}
                            href={`${ev.canonical_url}${ev.section_anchor}`}
                            target="_blank"
                            rel="noreferrer"
                            className="mono"
                            style={{
                              fontSize: 11.5,
                              color: "var(--accent-line)",
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                            }}
                          >
                            <Tag>{ev.evidence_type}</Tag>
                            {ev.title}
                            <Icon name="arrow" />
                          </a>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {/* client notes */}
                  {item.client_notes.length > 0 ? (
                    <ul
                      className="muted-note"
                      style={{ margin: "10px 0 0", paddingLeft: 16, lineHeight: 1.6 }}
                    >
                      {item.client_notes.map((n, i) => (
                        <li key={i}>
                          <span className="mono">{n.client_id}</span>: {n.note}
                        </li>
                      ))}
                    </ul>
                  ) : null}

                  {/* actions: Apply (copy prompt) + section links */}
                  <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="pub-cta"
                      style={{ height: 30, fontSize: 12.5 }}
                      onClick={() => void copyPrompt(item.use_case_id, item.starter_prompt)}
                    >
                      {copied ? "Copied" : "Apply use case"} <Icon name="arrow" />
                    </button>
                    {item.actions.map((a) => (
                      <a
                        key={`${a.label}-${a.href}`}
                        href={a.href}
                        className="pub-cta ghost"
                        style={{ height: 30, fontSize: 12.5, padding: "0 12px" }}
                      >
                        {a.label}
                      </a>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
