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
  fetchPublicSnippetExplorer,
  type PublicSnippetExplorer,
  type PublicSnippetItem,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Snippet Explorer — section component for /integrations.
 *
 * Browse executable code snippets indexed for a product/language/version; verify
 * MCP-readiness and citations. Filters (Product ID · SDK Language · Version · Source kind) drive
 * snippetQuery → /v1/snippets and render snippet cards (snippet_id, doc_type
 * pill, title link, version, source_kind pill, code block, Copy). Status summary,
 * loading spinner, error alert, empty state.
 *
 * Live wiring: the public fetchPublicSnippetExplorer (no auth) accepts
 * product_id / programming_language / version / source_kind. Product, language
 * and version are submitted-on-Apply server-side filters; source_kind also
 * filters the display source client-side so the same predicate works on the
 * fixture offline.
 *
 * Offline fallback:
 *   - live success            -> live PublicSnippetExplorer
 *   - live success but EMPTY   -> designed empty state
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file SNIPPET_FIXTURE (fully reviewable)
 * State gates resolve on the DISPLAY set, never the raw live set, so fixtures
 * always win offline and no skeleton/empty/error hides the interactive UI.
 * -------------------------------------------------------------------------- */

const SOURCE_OPTS = ["all", "docs", "apiref"] as const;
type SourceFilter = (typeof SOURCE_OPTS)[number];

function sourceVariant(sourceKind: string): StatusVariant {
  if (sourceKind === "apiref") return "info";
  if (sourceKind === "docs") return "ok";
  return "neutral";
}

/* ---------------- visually-hidden label helper (kit has no .sr-only) -------- */

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

/* ---------------- offline fixture (verbatim-shaped response) ---------------- */

const SNIPPET_FIXTURE: PublicSnippetExplorer = {
  product_id: "aspose.ocr",
  programming_language: "net",
  version: "latest-stable",
  source_kind: null,
  total_snippets: 4,
  items: [
    {
      snippet_id: "ocr-net-recognize-image",
      product_id: "aspose.ocr",
      programming_language: "net",
      version: "24.12",
      source_kind: "docs",
      doc_type: "howto",
      title: "Recognize text from an image",
      canonical_url: "https://docs.aspose.com/ocr/net/recognize-image/",
      section_anchor: "#recognize-image",
      symbol_fqn: null,
      snippet_language: "csharp",
      code: `using Aspose.OCR;

var api = new AsposeOcr();
OcrInput input = new OcrInput(InputType.SingleImage);
input.Add("page.png");

List<RecognitionResult> results = api.Recognize(input);
Console.WriteLine(results[0].RecognitionText);`,
      source_revision: "a1b2c3d",
      repo_id: "aspose.ocr.docs",
    },
    {
      snippet_id: "ocr-net-recognize-pdf",
      product_id: "aspose.ocr",
      programming_language: "net",
      version: "24.12",
      source_kind: "docs",
      doc_type: "howto",
      title: "Recognize text from a multi-page PDF",
      canonical_url: "https://docs.aspose.com/ocr/net/recognize-pdf/",
      section_anchor: "#recognize-pdf",
      symbol_fqn: null,
      snippet_language: "csharp",
      code: `using Aspose.OCR;

var api = new AsposeOcr();
OcrInput input = new OcrInput(InputType.PDF);
input.Add("scanned.pdf");

RecognitionSettings settings = new RecognitionSettings
{
    RecognizeSingleLine = false
};
List<RecognitionResult> results = api.Recognize(input, settings);
foreach (var page in results)
{
    Console.WriteLine(page.RecognitionText);
}`,
      source_revision: "a1b2c3d",
      repo_id: "aspose.ocr.docs",
    },
    {
      snippet_id: "ocr-net-recognize-signature",
      product_id: "aspose.ocr",
      programming_language: "net",
      version: "24.12",
      source_kind: "apiref",
      doc_type: "api_member",
      title: "AsposeOcr.Recognize(OcrInput, RecognitionSettings)",
      canonical_url:
        "https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognize/",
      section_anchor: "#recognize",
      symbol_fqn: "Aspose.OCR.AsposeOcr.Recognize",
      snippet_language: "csharp",
      code: `public List<RecognitionResult> Recognize(
    OcrInput input,
    RecognitionSettings settings = null)`,
      source_revision: "e4f5g6h",
      repo_id: "aspose.ocr.apiref",
    },
    {
      snippet_id: "ocr-net-language-constraint",
      product_id: "aspose.ocr",
      programming_language: "net",
      version: "24.12",
      source_kind: "docs",
      doc_type: "howto",
      title: "Constrain recognition language",
      canonical_url: "https://docs.aspose.com/ocr/net/recognition-language/",
      section_anchor: "#recognition-language",
      symbol_fqn: null,
      snippet_language: "csharp",
      code: `var settings = new RecognitionSettings
{
    Language = Language.Eng
};
List<RecognitionResult> results = api.Recognize(input, settings);`,
      source_revision: "a1b2c3d",
      repo_id: "aspose.ocr.docs",
    },
  ],
  generated_at: "2026-06-10T09:00:00Z",
};

/* -------------------------------------------------------------------------- */

interface FormState {
  product: string;
  language: string;
  version: string;
  sourceKind: SourceFilter;
}

const DEFAULT_FORM: FormState = {
  product: "aspose.ocr",
  language: "net",
  version: "",
  sourceKind: "all",
};

export default function SnippetExplorer() {
  // Draft inputs vs the submitted scope that actually drives the query.
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState<FormState>(DEFAULT_FORM);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Source kind is the 4th filter field: it applies on Apply alongside the
  // others (server param when live, display predicate on the fixture offline).
  const sourceFilter = submitted.sourceKind;

  const query = useQuery({
    // Public endpoint — always enabled (no auth, no session gate).
    queryKey: [
      "public-snippet-explorer",
      submitted.product,
      submitted.language,
      submitted.version,
      submitted.sourceKind,
    ],
    queryFn: () =>
      fetchPublicSnippetExplorer({
        product_id: submitted.product || undefined,
        programming_language: submitted.language || undefined,
        version: submitted.version || undefined,
        source_kind: submitted.sourceKind === "all" ? undefined : submitted.sourceKind,
      }),
    staleTime: 60_000,
  });

  // Display source with fixture fallback — fixtures always win offline.
  const live = query.data;
  const board: PublicSnippetExplorer = live && live.items.length > 0 ? live : SNIPPET_FIXTURE;
  const isFixture = !(live && live.items.length > 0);

  // Source filter applies to the display source so it works offline on fixtures.
  const shown = useMemo(
    () =>
      board.items.filter(
        (it) => sourceFilter === "all" || it.source_kind === sourceFilter,
      ),
    [board.items, sourceFilter],
  );

  const loading = query.isLoading && !board.items.length;
  const errored = query.isError && !board.items.length;

  const onApply = () => {
    setSubmitted({
      product: form.product.trim(),
      language: form.language.trim(),
      version: form.version.trim(),
      sourceKind: form.sourceKind,
    });
  };

  const onReset = () => {
    setForm(DEFAULT_FORM);
    setSubmitted(DEFAULT_FORM);
  };

  const copyCode = async (item: PublicSnippetItem) => {
    try {
      await navigator.clipboard.writeText(item.code);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopiedId(item.snippet_id);
    window.setTimeout(() => {
      setCopiedId((prev) => (prev === item.snippet_id ? null : prev));
    }, 2000);
  };

  return (
    <section className="pub-card" id="snippet-explorer" aria-label="Snippet explorer">
      <div className="pub-card-head">
        <span className="pub-card-title">Snippet explorer</span>
        <span className="right muted-note">{board.total_snippets} indexed</span>
      </div>

      {/* filter form (Product · Language · Version · Source kind) */}
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
            <label className="flabel" htmlFor="snippet-product">
              Product ID
            </label>
            <input
              id="snippet-product"
              className="inputctl"
              value={form.product}
              onChange={(e) => setForm((f) => ({ ...f, product: e.target.value }))}
              placeholder="aspose.ocr"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="snippet-language">
              SDK Language
            </label>
            <input
              id="snippet-language"
              className="inputctl"
              value={form.language}
              onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
              placeholder="net"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="snippet-version">
              Version
            </label>
            <input
              id="snippet-version"
              className="inputctl"
              value={form.version}
              onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))}
              placeholder="latest-stable or 25.1"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor="snippet-source">
              Source kind
            </label>
            <select
              id="snippet-source"
              className="selectctl"
              value={form.sourceKind}
              onChange={(e) => setForm((f) => ({ ...f, sourceKind: e.target.value as SourceFilter }))}
              aria-label="Snippet source kind"
            >
              {SOURCE_OPTS.map((o) => (
                <option key={o} value={o}>
                  {o === "all" ? "All sources" : o}
                </option>
              ))}
            </select>
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

      {/* status summary */}
      <div style={{ padding: "12px 20px 0" }}>
        <Banner
          variant={isFixture ? "info" : "ok"}
          icon="book"
          guidance
          title={
            isFixture
              ? "Showing sample snippets — live results appear when the public API is reachable."
              : `${board.total_snippets} executable snippets indexed for ${board.product_id ?? "this scope"}.`
          }
          text={`${shown.length} shown${sourceFilter !== "all" ? ` · ${sourceFilter} only` : ""} · scope ${submitted.product || "all"} · ${submitted.language || "all languages"}`}
        />
      </div>

      {/* result region */}
      <div style={{ padding: "8px 20px 16px" }} aria-live="polite">
        {loading ? (
          <div className="muted-note" style={{ padding: "8px 0" }}>
            Loading snippets…
          </div>
        ) : errored ? (
          <Banner
            variant="warn"
            icon="alert"
            title="Could not load snippets"
            text={query.error ? (query.error as Error).message : undefined}
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => query.refetch()}>
                Retry
              </Button>
            }
          />
        ) : shown.length === 0 ? (
          <EmptyState
            title="No snippets match the current filters"
            text="Ensure the product and language are MCP-ready via the coverage navigator. Try removing the version or source-kind filter."
            action={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onReset}>
                Reset filters
              </Button>
            }
          />
        ) : (
          shown.map((item) => (
            <SnippetCard
              key={item.snippet_id}
              item={item}
              copied={copiedId === item.snippet_id}
              onCopy={() => void copyCode(item)}
            />
          ))
        )}
      </div>
    </section>
  );
}

/* ---------------- per-snippet card (dark code-card + Copy) ----------------- */

function SnippetCard({
  item,
  copied,
  onCopy,
}: {
  item: PublicSnippetItem;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div
      id={`snippet-${item.snippet_id}`}
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: 16,
        marginTop: 12,
        background: "var(--surface)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <Pill variant={sourceVariant(item.source_kind)}>{item.source_kind}</Pill>
        <a
          href={item.canonical_url}
          target="_blank"
          rel="noreferrer"
          className="svc-name"
          style={{ color: "var(--fg)", textDecoration: "none" }}
        >
          {item.title}
        </a>
        <Tag>{item.doc_type.replace(/_/g, " ")}</Tag>
        <span className="mono" style={{ fontSize: 11, color: "var(--fg-subtle)", marginLeft: "auto" }}>
          v{item.version} · {item.programming_language}
        </span>
      </div>

      {item.symbol_fqn ? (
        <div className="muted-note" style={{ marginBottom: 8 }}>
          Symbol: <span className="mono">{item.symbol_fqn}</span>
        </div>
      ) : null}

      {/* dark code card with copy */}
      <div className="code-card">
        <div className="code-head">
          <span className="dot3" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="fname">
            {item.snippet_id}.{item.snippet_language}
          </span>
          <button
            type="button"
            className="copy"
            onClick={onCopy}
            aria-label={`Copy ${item.title} snippet to clipboard`}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="code-body" tabIndex={0}>
          {item.code}
        </pre>
        <span style={SR_ONLY} role="status" aria-live="polite">
          {copied ? `${item.title} snippet copied to clipboard` : ""}
        </span>
      </div>

      <div className="muted-note" style={{ marginTop: 10, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <a
          href={`${item.canonical_url}${item.section_anchor}`}
          target="_blank"
          rel="noreferrer"
          className="mono"
          style={{ color: "var(--accent-line)", display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          View citation
          <Icon name="arrow" />
        </a>
        <span className="mono">rev {item.source_revision}</span>
        <span className="mono">{item.repo_id}</span>
      </div>
    </div>
  );
}
