"use client";

import { useMemo, useState, type CSSProperties } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { Tabs } from "@/mono/components/Tabbed";
import { Icon } from "@/mono/lib/icons";
import { cn } from "@/mono/lib/cn";
import {
  fetchPublicQueryReproPack,
  getPublicSymbolDoc,
  queryPublicDocs,
  resolvePublicProduct,
  submitPublicQueryFeedback,
  submitPublicQueryIssue,
  type PublicQueryDocsResponse,
  type PublicQueryReproPack,
  type PublicResolvedProduct,
  type PublicSymbolDocResponse,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Public Query Playground — Query / Symbol / Resolve tabs.
 *
 * Each lane is a real mutation against the public admin-api client
 * (no auth). Citations are hyperlinks; the Query lane surfaces feedback
 * (submitPublicQueryFeedback), report-issue (submitPublicQueryIssue) and a
 * repro pack (fetchPublicQueryReproPack), all tied to the live request_id.
 *
 * Offline / empty / error → designed states. The in-file fixtures are the
 * OFFLINE fallback so the lane is fully reviewable with no backend.
 * -------------------------------------------------------------------------- */

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

const PRODUCTS = ["aspose.ocr", "aspose.cells", "aspose.words", "aspose.3d"] as const;
const LANGUAGES = ["net", "java", "python", "cpp"] as const;

const FEEDBACK_RATINGS = ["useful", "partially_useful", "not_useful"] as const;
const ISSUE_TYPES = ["missing_content", "wrong_or_outdated", "no_results", "other"] as const;

/* ---------------- fixtures (offline dataset) ---------------- */

const FIXTURE_QUERY: PublicQueryDocsResponse = {
  query_id: "qy_fixture_playground",
  request_id: "req_fixture_ocr_recognize",
  mode: "task",
  query_locale_detected: "en",
  translation_fallback_applied: false,
  confidence: 0.86,
  confidence_level: "high",
  fallback_reason: null,
  version_resolution: {
    requested_version: null,
    preferred_version: "latest-stable",
    resolved_version: "24.12",
    available_versions: ["24.12", "24.11", "24.9"],
    prefers_latest_stable: true,
    strict_version_enforced: false,
    fallback_applied: false,
    fallback_reason: null,
  },
  clarification_questions: [],
  quality: {
    overall_score: 0.84,
    coverage_score: 0.88,
    freshness_score: 0.79,
    freshness_source: "active_snapshot",
    citation_density_score: 0.9,
    symbol_match_score: 0.81,
    intent: "task",
    intent_subtype: "how_to",
    completeness_status: "complete",
    completeness_missing_signals: [],
  },
  results: [
    {
      chunk_id: "chunk-ocr-recognize-quickstart",
      title: "Recognize text from an image — quickstart",
      excerpt:
        "Create an AsposeOcr engine, point it at an image or PDF page, and call RecognizeImage to return the extracted text with layout metadata.",
      canonical_url: "https://docs.aspose.com/ocr/net/recognize-text",
      section_anchor: "#quickstart",
      score: 0.91,
      source_revision: "rev-24.12-a17",
      executable_snippets: [
        {
          snippet_id: "snip-ocr-recognize-1",
          language: "csharp",
          code: 'var api = new AsposeOcr();\nstring text = api.RecognizeImage("scan.png");',
          parent_canonical_url: "https://docs.aspose.com/ocr/net/recognize-text",
          parent_section_anchor: "#quickstart",
          parent_symbol_fqn: "Aspose.OCR.AsposeOcr.RecognizeImage",
        },
      ],
    },
    {
      chunk_id: "chunk-ocr-recognize-settings",
      title: "RecognitionSettings.Language — constrain the OCR language",
      excerpt:
        "Set RecognitionSettings.Language before recognition to bias the engine toward a specific script and improve accuracy.",
      canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings",
      section_anchor: "#language",
      score: 0.83,
      source_revision: "rev-24.12-a17",
      executable_snippets: [],
    },
    {
      chunk_id: "chunk-ocr-recognize-pdf",
      title: "Recognize text from a PDF document",
      excerpt:
        "Iterate PDF pages and run RecognizeImage per page; results preserve page order and per-region confidence.",
      canonical_url: "https://docs.aspose.com/ocr/net/recognize-pdf",
      section_anchor: "#per-page",
      score: 0.78,
      source_revision: "rev-24.12-a17",
      executable_snippets: [],
    },
  ],
  warnings: [],
  api_guardrails: [
    "Signatures shown are from the resolved version 24.12 — do not assume members from other releases.",
  ],
  explainability: {
    reranker_backend: "cross-encoder",
    intent_subtype: "how_to",
    freshness_source: "active_snapshot",
    why_top_result: [
      "Exact match on RecognizeImage in the quickstart chunk.",
      "Citation density and version freshness both above threshold.",
    ],
    why_version: "Resolved to latest-stable 24.12 (no explicit version requested).",
    why_fallback: null,
  },
  debug: null,
};

const FIXTURE_SYMBOL: PublicSymbolDocResponse = {
  symbol_fqn: "Aspose.OCR.AsposeOcr.RecognizeImage",
  signature: "public string RecognizeImage(string imagePath)",
  summary:
    "Runs optical character recognition on the image at the given path and returns the recognized text.",
  parameters: [
    { name: "imagePath", type: "string", description: "Path to the source image or rendered PDF page." },
  ],
  returns: "The recognized text content as a single string.",
  examples: [
    {
      language: "csharp",
      code: 'var api = new AsposeOcr();\nstring text = api.RecognizeImage("scan.png");\nConsole.WriteLine(text);',
    },
  ],
  citations: [
    {
      canonical_url: "https://docs.aspose.com/ocr/net/recognize-text",
      section_anchor: "#recognizeimage",
    },
  ],
  deprecated: false,
  signature_variants: [
    {
      signature: "public string RecognizeImage(string imagePath)",
      source_kind: "apiref",
      chunk_type: "signature",
      is_deprecated: false,
      citation: {
        canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/asposeocr/recognizeimage",
        section_anchor: "#string",
      },
    },
  ],
  guardrails: [
    "Member resolved against version 24.12 — confirm availability before targeting a different release.",
  ],
};

const FIXTURE_RESOLVE: PublicResolvedProduct = {
  product_id: "aspose.ocr",
  language: "net",
  aliases: ["Aspose.OCR", "aspose-ocr", "ocr"],
  confidence: 0.97,
};

const FIXTURE_REPRO: PublicQueryReproPack = {
  request_id: "req_fixture_ocr_recognize",
  share_url: "http://localhost:3000/integrations?request_id=req_fixture_ocr_recognize",
  generated_at: "2026-06-10T09:00:00Z",
  assumptions: [
    "Replayed against the active latest-stable snapshot.",
    "include_examples=true, top_k=5.",
  ],
  handoff_notes: [
    "Outcome matched the original capture — no drift detected.",
    "Share this pack with the search team if relevance regresses.",
  ],
  scope: {
    request_id: "req_fixture_ocr_recognize",
    endpoint: "/v1/docs:query",
    tool: "query_docs",
    raw_query: "how to recognize text from an image in C#",
    product_id: "aspose.ocr",
    programming_language: "net",
    doc_locale: "en",
    captured_at: "2026-06-10T08:58:00Z",
  },
  original: {
    outcome: "answered",
    retrieval_mode: "task",
    result_count: 3,
    confidence: 0.86,
    latency_ms: 142,
    zero_result_reason: null,
    fallback_reason: null,
    warning_codes: [],
  },
  replay: {
    mode: "task",
    query_locale_detected: "en",
    translation_fallback_applied: false,
    confidence: 0.86,
    confidence_level: "high",
    fallback_reason: null,
    result_count: 3,
    warnings: [],
    version_resolution: FIXTURE_QUERY.version_resolution,
    quality: FIXTURE_QUERY.quality,
    clarification_questions: [],
    api_guardrails: FIXTURE_QUERY.api_guardrails,
    citations: [
      {
        title: "Recognize text from an image — quickstart",
        canonical_url: "https://docs.aspose.com/ocr/net/recognize-text",
        section_anchor: "#quickstart",
        score: 0.91,
        source_revision: "rev-24.12-a17",
        executable_snippets_count: 1,
      },
    ],
  },
  linked_signals: {
    total_feedback: 2,
    latest_feedback_rating: "useful",
    total_issue_reports: 0,
    issue_types: [],
    last_feedback_at: "2026-06-09T17:20:00Z",
    last_issue_at: null,
  },
};

/* ---------------- small helpers ---------------- */

function citationHref(url: string, anchor: string): string {
  if (!url) return anchor || "#";
  return anchor ? `${url}${anchor}` : url;
}

type LaneTab = 0 | 1 | 2;

export default function QueryPlayground() {
  const [tab, setTab] = useState<LaneTab>(0);

  // Shared scope (drives all three lanes).
  const [product, setProduct] = useState<string>(PRODUCTS[0]);
  const [language, setLanguage] = useState<string>(LANGUAGES[0]);

  // Query lane.
  const [queryText, setQueryText] = useState("");
  const queryMutation = useMutation({
    mutationFn: (query: string) =>
      queryPublicDocs({
        query,
        product_id: product || undefined,
        language: language || undefined,
        include_examples: true,
        top_k: 5,
      }),
  });

  // Symbol lane.
  const [symbolText, setSymbolText] = useState("Aspose.OCR.AsposeOcr.RecognizeImage");
  const symbolMutation = useMutation({
    mutationFn: (symbolFqn: string) =>
      getPublicSymbolDoc({
        product_id: product || "aspose.ocr",
        language: language || "net",
        symbol_fqn: symbolFqn,
      }),
  });

  // Resolve lane.
  const [resolveText, setResolveText] = useState("");
  const resolveMutation = useMutation({
    mutationFn: (hint: string) => resolvePublicProduct(hint),
  });

  // Feedback / issue tied to the live (or fixture) request_id.
  const [feedbackRating, setFeedbackRating] = useState<string>(FEEDBACK_RATINGS[0]);
  const feedbackMutation = useMutation({
    mutationFn: (payload: { request_id: string; rating: string }) =>
      submitPublicQueryFeedback({
        request_id: payload.request_id,
        rating: payload.rating,
        reason_codes: [payload.rating],
      }),
  });

  const [issueType, setIssueType] = useState<string>(ISSUE_TYPES[0]);
  const [issueNotes, setIssueNotes] = useState("");
  const issueMutation = useMutation({
    mutationFn: (payload: { request_id: string; issue_type: string; notes?: string }) =>
      submitPublicQueryIssue(payload),
  });

  // Repro pack — enabled once we have a request_id to fetch.
  const [reproRequestId, setReproRequestId] = useState("");
  const reproQuery = useQuery({
    queryKey: ["public-query-repro-pack", reproRequestId],
    queryFn: () => fetchPublicQueryReproPack({ request_id: reproRequestId }),
    enabled: reproRequestId.trim().length > 0,
  });

  // Display source with fixture fallback (offline → fixtures so the lane stays reviewable).
  const queryData = queryMutation.data ?? (queryMutation.isPending ? null : FIXTURE_QUERY);
  const queryIsFixture = !queryMutation.data && !queryMutation.isError;
  const symbolData = symbolMutation.data ?? (symbolMutation.isPending ? null : FIXTURE_SYMBOL);
  const symbolIsFixture = !symbolMutation.data && !symbolMutation.isError;
  const resolveData = resolveMutation.data ?? (resolveMutation.isPending ? null : FIXTURE_RESOLVE);
  const resolveIsFixture = !resolveMutation.data && !resolveMutation.isError;

  // The request_id that feedback / issue / repro act on.
  const activeRequestId = queryMutation.data?.request_id ?? (queryIsFixture ? FIXTURE_QUERY.request_id : "");

  const reproData: PublicQueryReproPack | null = reproQuery.data ?? (reproRequestId.trim() ? null : FIXTURE_REPRO);
  const reproIsFixture = !reproQuery.data && !reproRequestId.trim();

  const feedbackNote = useMemo(() => {
    if (feedbackMutation.isError) {
      return { variant: "warn" as const, text: (feedbackMutation.error as Error).message };
    }
    if (feedbackMutation.data) {
      return {
        variant: "ok" as const,
        text: `Feedback recorded (${feedbackMutation.data.rating}) for ${feedbackMutation.data.request_id}.`,
      };
    }
    return null;
  }, [feedbackMutation.isError, feedbackMutation.error, feedbackMutation.data]);

  const issueNote = useMemo(() => {
    if (issueMutation.isError) {
      return { variant: "warn" as const, text: (issueMutation.error as Error).message };
    }
    if (issueMutation.data) {
      return {
        variant: "ok" as const,
        text: `Issue ${issueMutation.data.issue_id} recorded — the content team will triage it.`,
      };
    }
    return null;
  }, [issueMutation.isError, issueMutation.error, issueMutation.data]);

  return (
    <section className="pub-card" style={{ padding: 22 }} aria-label="Public query playground">
      <div className="pub-card-title" style={{ marginBottom: 4 }}>
        Public query playground
      </div>
      <p className="pub-sub" style={{ marginTop: 0, marginBottom: 14, textAlign: "left" }}>
        Run live grounded retrieval, look up exact API symbols, or resolve a product hint — then capture a
        request_id, send feedback, report a documentation issue, or pull a reproducible evidence pack.
      </p>

      <Tabs
        tabs={["Query", "Symbol", "Resolve"]}
        active={tab}
        onChange={(i) => setTab(i as LaneTab)}
      />

      {/* ----------------------------------------------------------- Query */}
      {tab === 0 && (
        <div role="tabpanel" aria-label="Query lane">
          <form
            className="toolbar"
            style={{ margin: 0 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (queryText.trim()) queryMutation.mutate(queryText.trim());
            }}
          >
            <ScopePickers
              product={product}
              language={language}
              onProduct={setProduct}
              onLanguage={setLanguage}
            />
            <span className="input" style={{ flex: 1, minWidth: 240 }}>
              <label style={SR_ONLY} htmlFor="pg-query">
                Query
              </label>
              <input
                id="pg-query"
                className="inputctl"
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                placeholder="e.g. how to recognize text from a PDF in C#"
              />
            </span>
            <Button variant="btn-primary" type="submit" icon="play" disabled={queryMutation.isPending}>
              {queryMutation.isPending ? "Running…" : "Run query"}
            </Button>
          </form>

          <div style={{ marginTop: 14 }} aria-live="polite">
            {queryMutation.isPending ? (
              <div className="muted-note">Running grounded retrieval…</div>
            ) : queryMutation.isError ? (
              <Banner
                variant="warn"
                icon="alert"
                title="Query failed"
                text={(queryMutation.error as Error).message}
                actions={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => queryMutation.mutate(queryText.trim() || "how to recognize text from an image")}>
                    Retry
                  </Button>
                }
              />
            ) : queryData && queryData.results.length === 0 ? (
              <Banner
                variant="info"
                icon="search"
                title="No documents found"
                text="Try broadening the query or confirm coverage in the capability explorer. You can still report a zero-result issue below."
              />
            ) : queryData ? (
              <>
                <div className="svc-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
                  <Pill variant={queryData.confidence_level === "low" ? "warn" : "ok"}>
                    {queryData.confidence_level} confidence
                  </Pill>
                  <div>
                    <div className="svc-name">
                      {queryData.results.length} result{queryData.results.length === 1 ? "" : "s"} ·{" "}
                      <span className="mono">{queryData.mode}</span> mode
                    </div>
                    <div className="svc-desc">
                      request_id <span className="mono">{queryData.request_id}</span>
                      {" · "}resolved {queryData.version_resolution.resolved_version ?? "auto"}
                      {queryIsFixture ? " · sample (offline)" : ""}
                    </div>
                  </div>
                </div>

                {queryData.results.map((r) => (
                  <div className="svc-row" key={r.chunk_id} style={{ paddingLeft: 0, paddingRight: 0 }}>
                    <Pill variant="ok">cited</Pill>
                    <div style={{ minWidth: 0 }}>
                      <div className="svc-name">{r.title}</div>
                      <div className="svc-desc">{r.excerpt}</div>
                      <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                        <a
                          className="mono"
                          style={{ fontSize: 11.5, color: "var(--accent-line)" }}
                          href={citationHref(r.canonical_url, r.section_anchor)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {r.canonical_url}
                          {r.section_anchor}
                          <Icon name="arrow" />
                        </a>
                        <Tag>{r.source_revision}</Tag>
                        {r.executable_snippets.length > 0 && (
                          <span className="muted-note">
                            {r.executable_snippets.length} snippet
                            {r.executable_snippets.length === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="svc-up" style={{ width: "auto", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-subtle)" }}>
                      {r.score.toFixed(2)}
                    </div>
                  </div>
                ))}

                {/* feedback + report issue on the active request_id */}
                <FeedbackAndIssue
                  requestId={activeRequestId}
                  feedbackRating={feedbackRating}
                  onFeedbackRating={setFeedbackRating}
                  onSubmitFeedback={() =>
                    activeRequestId && feedbackMutation.mutate({ request_id: activeRequestId, rating: feedbackRating })
                  }
                  feedbackPending={feedbackMutation.isPending}
                  feedbackNote={feedbackNote}
                  issueType={issueType}
                  onIssueType={setIssueType}
                  issueNotes={issueNotes}
                  onIssueNotes={setIssueNotes}
                  onSubmitIssue={() =>
                    activeRequestId &&
                    issueMutation.mutate({
                      request_id: activeRequestId,
                      issue_type: issueType,
                      notes: issueNotes.trim() || undefined,
                    })
                  }
                  issuePending={issueMutation.isPending}
                  issueNote={issueNote}
                  onLoadReproPack={() => activeRequestId && setReproRequestId(activeRequestId)}
                />

                {/* repro pack */}
                <ReproPackPanel
                  data={reproData}
                  isFixture={reproIsFixture}
                  isPending={reproQuery.isFetching}
                  isError={reproQuery.isError}
                  errorText={reproQuery.error ? (reproQuery.error as Error).message : undefined}
                  hasRequest={Boolean(activeRequestId)}
                />
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------- Symbol */}
      {tab === 1 && (
        <div role="tabpanel" aria-label="Symbol lane">
          <form
            className="toolbar"
            style={{ margin: 0 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (symbolText.trim()) symbolMutation.mutate(symbolText.trim());
            }}
          >
            <ScopePickers
              product={product}
              language={language}
              onProduct={setProduct}
              onLanguage={setLanguage}
            />
            <span className="input" style={{ flex: 1, minWidth: 240 }}>
              <label style={SR_ONLY} htmlFor="pg-symbol">
                Symbol FQN
              </label>
              <input
                id="pg-symbol"
                className="inputctl"
                value={symbolText}
                onChange={(e) => setSymbolText(e.target.value)}
                placeholder="Aspose.OCR.AsposeOcr.RecognizeImage"
              />
            </span>
            <Button variant="btn-primary" type="submit" icon="search" disabled={symbolMutation.isPending}>
              {symbolMutation.isPending ? "Looking up…" : "Run symbol"}
            </Button>
          </form>

          <div style={{ marginTop: 14 }} aria-live="polite">
            {symbolMutation.isPending ? (
              <div className="muted-note">Looking up symbol…</div>
            ) : symbolMutation.isError ? (
              <Banner
                variant="warn"
                icon="alert"
                title="Symbol lookup failed"
                text={(symbolMutation.error as Error).message}
                actions={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => symbolMutation.mutate(symbolText.trim())}>
                    Retry
                  </Button>
                }
              />
            ) : symbolData ? (
              <div>
                <div className="svc-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
                  <Pill variant={symbolData.deprecated ? "warn" : "ok"}>
                    {symbolData.deprecated ? "deprecated" : "current"}
                  </Pill>
                  <div style={{ minWidth: 0 }}>
                    <div className="svc-name mono" style={{ fontSize: 12 }}>
                      {symbolData.symbol_fqn}
                    </div>
                    <div className="svc-desc">
                      {symbolData.summary}
                      {symbolIsFixture ? " · sample (offline)" : ""}
                    </div>
                  </div>
                </div>

                <CodeBlock code={symbolData.signature} />

                {symbolData.parameters.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="muted-note" style={{ marginBottom: 6 }}>
                      Parameters
                    </div>
                    {symbolData.parameters.map((p) => (
                      <div className="svc-row" key={p.name} style={{ paddingLeft: 0, paddingRight: 0 }}>
                        <Tag>{p.type}</Tag>
                        <div>
                          <div className="svc-name mono" style={{ fontSize: 12 }}>
                            {p.name}
                          </div>
                          <div className="svc-desc">{p.description}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                <div className="muted-note" style={{ marginTop: 10 }}>
                  Returns: {symbolData.returns}
                </div>

                {symbolData.examples.map((ex, i) => (
                  <CodeBlock key={i} code={ex.code} lang={ex.language} />
                ))}

                {symbolData.citations.length > 0 && (
                  <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {symbolData.citations.map((c, i) => (
                      <a
                        key={i}
                        className="mono"
                        style={{ fontSize: 11.5, color: "var(--accent-line)" }}
                        href={citationHref(c.canonical_url, c.section_anchor)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {c.canonical_url}
                        {c.section_anchor}
                        <Icon name="arrow" />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* --------------------------------------------------------- Resolve */}
      {tab === 2 && (
        <div role="tabpanel" aria-label="Resolve lane">
          <form
            className="toolbar"
            style={{ margin: 0 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (resolveText.trim()) resolveMutation.mutate(resolveText.trim());
            }}
          >
            <span className="input" style={{ flex: 1, minWidth: 240 }}>
              <label style={SR_ONLY} htmlFor="pg-resolve">
                Product hint
              </label>
              <input
                id="pg-resolve"
                className="inputctl"
                value={resolveText}
                onChange={(e) => setResolveText(e.target.value)}
                placeholder="e.g. Aspose OCR for .NET"
              />
            </span>
            <Button variant="btn-primary" type="submit" icon="check" disabled={resolveMutation.isPending}>
              {resolveMutation.isPending ? "Resolving…" : "Resolve product"}
            </Button>
          </form>

          <div style={{ marginTop: 14 }} aria-live="polite">
            {resolveMutation.isPending ? (
              <div className="muted-note">Resolving product hint…</div>
            ) : resolveMutation.isError ? (
              <Banner
                variant="warn"
                icon="alert"
                title="Resolve failed"
                text={(resolveMutation.error as Error).message}
                actions={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => resolveMutation.mutate(resolveText.trim())}>
                    Retry
                  </Button>
                }
              />
            ) : resolveData ? (
              <div className="svc-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
                <Pill variant={resolveData.confidence < 0.6 ? "warn" : "ok"}>
                  {Math.round(resolveData.confidence * 100)}% match
                </Pill>
                <div style={{ minWidth: 0 }}>
                  <div className="svc-name mono" style={{ fontSize: 12 }}>
                    {resolveData.product_id}
                    {resolveData.language ? ` · ${resolveData.language}` : ""}
                    {resolveIsFixture ? "  (sample, offline)" : ""}
                  </div>
                  <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {resolveData.aliases.length === 0 ? (
                      <span className="muted-note">No known aliases.</span>
                    ) : (
                      resolveData.aliases.map((a) => <Tag key={a}>{a}</Tag>)
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

/* ----------------------------------------------------------------------------
 * Sub-composites
 * -------------------------------------------------------------------------- */

function ScopePickers({
  product,
  language,
  onProduct,
  onLanguage,
}: {
  product: string;
  language: string;
  onProduct: (v: string) => void;
  onLanguage: (v: string) => void;
}) {
  return (
    <>
      <span className="select" style={{ minWidth: 140 }}>
        <label style={SR_ONLY} htmlFor="pg-product">
          Product
        </label>
        <select id="pg-product" className="selectctl" value={product} onChange={(e) => onProduct(e.target.value)}>
          {PRODUCTS.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </span>
      <span className="select" style={{ minWidth: 110 }}>
        <label style={SR_ONLY} htmlFor="pg-language">
          SDK language
        </label>
        <select id="pg-language" className="selectctl" value={language} onChange={(e) => onLanguage(e.target.value)}>
          {LANGUAGES.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </span>
    </>
  );
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  return (
    <div className="code-card" style={{ marginTop: 10 }}>
      {lang && (
        <div className="code-head">
          <span className="fname">{lang}</span>
        </div>
      )}
      <pre className="code-body" tabIndex={0}>
        {code}
      </pre>
    </div>
  );
}

type FeedbackNote = { variant: "ok" | "warn"; text: string } | null;

function FeedbackAndIssue({
  requestId,
  feedbackRating,
  onFeedbackRating,
  onSubmitFeedback,
  feedbackPending,
  feedbackNote,
  issueType,
  onIssueType,
  issueNotes,
  onIssueNotes,
  onSubmitIssue,
  issuePending,
  issueNote,
  onLoadReproPack,
}: {
  requestId: string;
  feedbackRating: string;
  onFeedbackRating: (v: string) => void;
  onSubmitFeedback: () => void;
  feedbackPending: boolean;
  feedbackNote: FeedbackNote;
  issueType: string;
  onIssueType: (v: string) => void;
  issueNotes: string;
  onIssueNotes: (v: string) => void;
  onSubmitIssue: () => void;
  issuePending: boolean;
  issueNote: FeedbackNote;
  onLoadReproPack: () => void;
}) {
  const disabled = !requestId;
  return (
    <div
      style={{
        marginTop: 14,
        paddingTop: 14,
        borderTop: "1px solid var(--border)",
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
        gap: 16,
      }}
    >
      {/* usefulness feedback */}
      <div>
        <div className="muted-note" style={{ marginBottom: 8 }}>
          Was this answer useful? <span className="mono">{requestId || "no request_id"}</span>
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <span className="select" style={{ minWidth: 150 }}>
            <label style={SR_ONLY} htmlFor="pg-rating">
              Rating
            </label>
            <select
              id="pg-rating"
              className="selectctl"
              value={feedbackRating}
              onChange={(e) => onFeedbackRating(e.target.value)}
            >
              {FEEDBACK_RATINGS.map((r) => (
                <option key={r} value={r}>
                  {r.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </span>
          <Button variant="btn-ghost" size="sm" icon="check" disabled={disabled || feedbackPending} onClick={onSubmitFeedback}>
            {feedbackPending ? "Sending…" : "Send feedback"}
          </Button>
        </div>
        {feedbackNote && (
          <div style={{ marginTop: 8 }}>
            <Banner variant={feedbackNote.variant} icon={feedbackNote.variant === "ok" ? "check" : "alert"} title={feedbackNote.text} />
          </div>
        )}
      </div>

      {/* report a documentation issue */}
      <div>
        <div className="muted-note" style={{ marginBottom: 8 }}>
          Report a documentation issue
        </div>
        <div className="toolbar" style={{ margin: 0 }}>
          <span className="select" style={{ minWidth: 160 }}>
            <label style={SR_ONLY} htmlFor="pg-issue-type">
              Issue type
            </label>
            <select id="pg-issue-type" className="selectctl" value={issueType} onChange={(e) => onIssueType(e.target.value)}>
              {ISSUE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </span>
          <span className="input" style={{ flex: 1, minWidth: 140 }}>
            <label style={SR_ONLY} htmlFor="pg-issue-notes">
              Notes
            </label>
            <input
              id="pg-issue-notes"
              className="inputctl"
              value={issueNotes}
              onChange={(e) => onIssueNotes(e.target.value)}
              placeholder="Optional notes"
            />
          </span>
          <Button variant="btn-ghost" size="sm" icon="alert" disabled={disabled || issuePending} onClick={onSubmitIssue}>
            {issuePending ? "Filing…" : "Report"}
          </Button>
        </div>
        {issueNote && (
          <div style={{ marginTop: 8 }}>
            <Banner variant={issueNote.variant} icon={issueNote.variant === "ok" ? "check" : "alert"} title={issueNote.text} />
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <Button variant="btn-ghost" size="sm" icon="history" disabled={disabled} onClick={onLoadReproPack}>
            Load repro pack
          </Button>
        </div>
      </div>
    </div>
  );
}

function ReproPackPanel({
  data,
  isFixture,
  isPending,
  isError,
  errorText,
  hasRequest,
}: {
  data: PublicQueryReproPack | null;
  isFixture: boolean;
  isPending: boolean;
  isError: boolean;
  errorText?: string;
  hasRequest: boolean;
}) {
  if (isPending) {
    return (
      <div style={{ marginTop: 14 }} className="muted-note">
        Building reproducible evidence pack…
      </div>
    );
  }
  if (isError) {
    return (
      <div style={{ marginTop: 14 }}>
        <Banner variant="warn" icon="alert" title="Could not load repro pack" text={errorText} />
      </div>
    );
  }
  if (!data) {
    if (!hasRequest) return null;
    return (
      <div style={{ marginTop: 14 }} className="muted-note">
        Run a query, then load the repro pack for its request_id.
      </div>
    );
  }
  return (
    <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
      <div className="svc-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <Pill variant={data.original.outcome === "answered" ? "ok" : "warn"}>{data.original.outcome}</Pill>
        <div style={{ minWidth: 0 }}>
          <div className="svc-name">
            Repro pack · <span className="mono">{data.request_id}</span>
            {isFixture ? "  (sample, offline)" : ""}
          </div>
          <div className="svc-desc">{data.scope.raw_query}</div>
          <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <a
              className="mono"
              style={{ fontSize: 11.5, color: "var(--accent-line)" }}
              href={data.share_url}
              target="_blank"
              rel="noreferrer"
            >
              Share link <Icon name="arrow" />
            </a>
            <Tag>{data.original.result_count} results</Tag>
            <Tag>{data.original.latency_ms}ms</Tag>
            <span className="muted-note">
              {data.linked_signals.total_feedback} feedback · {data.linked_signals.total_issue_reports} issues
            </span>
          </div>
        </div>
      </div>
      {data.handoff_notes.length > 0 && (
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {data.handoff_notes.map((n) => (
            <li key={n} className="svc-desc">
              {n}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
