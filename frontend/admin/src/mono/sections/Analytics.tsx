"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useAnalyticsState } from "@/hooks/useAnalyticsState";
import type { AnalyticsSavedView } from "@/components/admin-console.types";
import type {
  PublicQueryDocsResponse,
  PublicQueryDocsResult,
  RequestEvidenceResponse,
} from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { Input, Select } from "../components/Field";
import { Segmented } from "../components/Field";
import { EmptyState, ErrorState, Skeleton, StaleBadge } from "../components/states";
import { ShowMoreRow, Table, TableCard } from "../components/Table";
import { Tabbed } from "../components/Tabbed";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";
import { usePopover, PopoverPanel } from "../shell/Popover";

// Min reason length for the destructive saved-view delete (audit-grade capture).
const REASON_MIN = 8;

// ─────────────────────────────────────────────────────────── Fixtures ──────────

interface FunnelStage {
  label: string;
  value: string;
  conv: string;
  width: number;
}

const FUNNEL: FunnelStage[] = [
  { label: "Resolve product", value: "0", conv: "entry stage", width: 0 },
  { label: "Run self-test", value: "1", conv: "100% of sessions", width: 100 },
  { label: "Execute query", value: "0", conv: "0% conversion", width: 0 },
  { label: "Submit feedback", value: "0", conv: "0% conversion", width: 0 },
  { label: "Report issue", value: "0", conv: "0% conversion", width: 0 },
];

type Risk = "high" | "medium" | "low";

interface DriftRow {
  product: string;
  lang: string;
  kind: string;
  risk: Risk;
  score: number;
}

const DRIFT: DriftRow[] = [
  { product: "aspose.3d", lang: "net", kind: "apiref", risk: "high", score: 132 },
  { product: "aspose.barcode", lang: "net", kind: "apiref", risk: "high", score: 132 },
  { product: "aspose.barcode", lang: "java", kind: "docs", risk: "high", score: 128 },
  { product: "aspose.cad", lang: "net", kind: "apiref", risk: "high", score: 124 },
  { product: "aspose.cells", lang: "net", kind: "apiref", risk: "high", score: 120 },
  { product: "aspose.cells", lang: "python", kind: "docs", risk: "medium", score: 86 },
  { product: "aspose.ocr", lang: "net", kind: "docs", risk: "high", score: 118 },
  { product: "aspose.ocr", lang: "java", kind: "apiref", risk: "medium", score: 74 },
  { product: "aspose.words", lang: "net", kind: "docs", risk: "high", score: 116 },
  { product: "aspose.words", lang: "python", kind: "apiref", risk: "medium", score: 72 },
  { product: "groupdocs.parser", lang: "net", kind: "docs", risk: "low", score: 37 },
  { product: "groupdocs.viewer", lang: "java", kind: "apiref", risk: "low", score: 34 },
  { product: "aspose.pdf", lang: "net", kind: "apiref", risk: "high", score: 122 },
  { product: "aspose.slides", lang: "cpp", kind: "docs", risk: "medium", score: 68 },
];

const RISK_PILL: Record<Risk, StatusVariant> = { high: "crit", medium: "warn", low: "neutral" };
const RISK_RANK: Record<Risk, number> = { high: 0, medium: 1, low: 2 };

// distribution + cockpit + issues + hotspots data
interface BarDatum {
  label: string;
  value: string;
  pct: number;
  variant: StatusVariant;
}

const A_DIST_OUTCOME: BarDatum[] = [
  { label: "answered", value: "0", pct: 0, variant: "ok" },
  { label: "low confidence", value: "0", pct: 0, variant: "warn" },
  { label: "zero result", value: "0", pct: 0, variant: "crit" },
];
const A_DIST_MODE: BarDatum[] = [
  { label: "hybrid", value: "1", pct: 100, variant: "info" },
  { label: "vector only", value: "0", pct: 0, variant: "neutral" },
  { label: "lexical only", value: "0", pct: 0, variant: "neutral" },
];
const A_ZRR: BarDatum[] = [
  { label: "no_index_data", value: "—", pct: 0, variant: "neutral" },
  { label: "scope_mismatch", value: "—", pct: 0, variant: "neutral" },
  { label: "stale_snapshot", value: "—", pct: 0, variant: "neutral" },
  { label: "language_fallback", value: "—", pct: 0, variant: "neutral" },
  { label: "version_fallback", value: "—", pct: 0, variant: "neutral" },
];
const A_USEFULNESS: BarDatum[] = [
  { label: "useful", value: "0", pct: 0, variant: "ok" },
  { label: "partially useful", value: "0", pct: 0, variant: "warn" },
  { label: "not useful", value: "0", pct: 0, variant: "crit" },
];
const A_USE_REASONS: BarDatum[] = [
  { label: "missing_examples", value: "—", pct: 0, variant: "neutral" },
  { label: "wrong_api", value: "—", pct: 0, variant: "neutral" },
  { label: "incomplete_docs", value: "—", pct: 0, variant: "neutral" },
  { label: "outdated", value: "—", pct: 0, variant: "neutral" },
];
// API limitation: the Mono toolbar drives the slice query through product/language/kind only, so the
// fallback-reason / warning-code / endpoint / tool count maps stay empty offline. These fixtures
// give the four extra distribution charts a populated offline dataset (7 charts total).
const A_DIST_FALLBACK: BarDatum[] = [
  { label: "language_fallback", value: "0", pct: 0, variant: "warn" },
  { label: "version_fallback", value: "0", pct: 0, variant: "warn" },
  { label: "none", value: "1", pct: 100, variant: "neutral" },
];
const A_DIST_WARNING: BarDatum[] = [
  { label: "stale_snapshot", value: "0", pct: 0, variant: "warn" },
  { label: "low_confidence", value: "0", pct: 0, variant: "warn" },
  { label: "no_index_data", value: "0", pct: 0, variant: "crit" },
];
const A_DIST_ENDPOINT: BarDatum[] = [
  { label: "query_docs", value: "1", pct: 100, variant: "info" },
  { label: "get_symbol_doc", value: "0", pct: 0, variant: "neutral" },
  { label: "list_breaking_changes", value: "0", pct: 0, variant: "neutral" },
  { label: "resolve_product", value: "0", pct: 0, variant: "neutral" },
];
const A_DIST_TOOL: BarDatum[] = [
  { label: "query_docs", value: "1", pct: 100, variant: "info" },
  { label: "get_symbol_doc", value: "0", pct: 0, variant: "neutral" },
  { label: "list_latest_release_features", value: "0", pct: 0, variant: "neutral" },
];

interface Cluster {
  reason: string;
  impact: string;
  scopes: string;
  q: string;
  fix: string;
  // Secondary-filter facets (offline only) — `reason` above already serves the zero-result
  // reason filter; these let the remaining "More filters" controls refine the cockpit.
  locale?: string;
  client?: string;
  outcome?: string;
  mode?: string;
  fallback?: string;
  warn?: string;
  issueType?: string;
  severity?: string;
  // Scope-identity facets behind the two free-text "More filters" Inputs (Hashed IP / Fingerprint).
  ip?: string;
  fingerprint?: string;
}

const A_COCKPIT: Cluster[] = [
  {
    reason: "no_index_data",
    impact: "62%",
    scopes: "aspose.3d · aspose.barcode · aspose.cad",
    q: '"how to read a 3d mesh in c#"',
    fix: "Run Validate-Only then publish — these scopes have never been indexed.",
    locale: "en",
    client: "cursor",
    outcome: "zero_result",
    mode: "hybrid",
    fallback: "none",
    warn: "no_index_data",
    issueType: "missing_docs",
    severity: "critical",
    ip: "ip_7f3a9c21",
    fingerprint: "fp_a1b2c3",
  },
  {
    reason: "stale_snapshot",
    impact: "21%",
    scopes: "aspose.ocr / net",
    q: '"recognize text from pdf latest api"',
    fix: "Reingest; active snapshot is older than the freshness target.",
    locale: "de",
    client: "claude-desktop",
    outcome: "low_confidence",
    mode: "vector",
    fallback: "version_fallback",
    warn: "stale_snapshot",
    issueType: "outdated_docs",
    severity: "warning",
    ip: "ip_2e8b41d0",
    fingerprint: "fp_d4e5f6",
  },
  {
    reason: "scope_mismatch",
    impact: "11%",
    scopes: "aspose.words / python",
    q: '"mail merge python example"',
    fix: "Add a product alias so python resolves to the indexed language.",
    locale: "fr",
    client: "qwen-code",
    outcome: "zero_result",
    mode: "lexical",
    fallback: "language_fallback",
    warn: "low_confidence",
    issueType: "wrong_docs",
    severity: "info",
    ip: "ip_9c0f5a77",
    fingerprint: "fp_77ab90",
  },
  {
    reason: "language_fallback",
    impact: "6%",
    scopes: "aspose.cells / cpp",
    q: '"cell formula c++"',
    fix: "No cpp snapshot — served from net with a fallback warning.",
    locale: "ja",
    client: "vscode",
    outcome: "answered",
    mode: "hybrid",
    fallback: "language_fallback",
    warn: "low_confidence",
    issueType: "bad_example",
    severity: "info",
    ip: "ip_4d2c6e10",
    fingerprint: "fp_22cd44",
  },
];

interface Issue {
  id: string;
  scope: string;
  type: string;
  sev: "crit" | "warn" | "info";
  q: string;
  outcome: string;
  results: number;
  warn: string;
  rec: string;
  // Secondary-filter facets (offline only). `outcome` + `warn` above already match the
  // Outcome / Warning-code option sets, so the matcher reads them directly; `issueType` and
  // `severity` use the dedicated option-set vocabulary (ISSUE_TYPES / SEVERITIES) which the
  // display `type`/`sev` fields do not, and locale/client/mode/reason/fallback are added so
  // every secondary Select refines the inbox offline.
  locale?: string;
  client?: string;
  mode?: string;
  reason?: string;
  fallback?: string;
  issueType?: string;
  severity?: string;
  // Scope-identity facets behind the two free-text "More filters" Inputs (Hashed IP / Fingerprint).
  ip?: string;
  fingerprint?: string;
}

const A_ISSUES: Issue[] = [
  {
    id: "req_8c3864e",
    scope: "aspose.3d / net / apiref",
    type: "no_result",
    sev: "crit",
    q: "load .obj mesh and export to glb",
    outcome: "zero_result",
    results: 0,
    warn: "no_index_data",
    rec: "Onboard & publish aspose.3d.apiref — no snapshot exists.",
    locale: "en",
    client: "cursor",
    mode: "hybrid",
    reason: "no_index_data",
    fallback: "none",
    issueType: "missing_docs",
    severity: "critical",
    ip: "ip_7f3a9c21",
    fingerprint: "fp_a1b2c3",
  },
  {
    id: "req_4a1f9b2",
    scope: "aspose.ocr / net / docs",
    type: "low_confidence",
    sev: "warn",
    q: "recognize handwriting accuracy settings",
    outcome: "low_confidence",
    results: 3,
    warn: "stale_snapshot",
    rec: "Reingest aspose.ocr.docs; snapshot is past the freshness target.",
    locale: "de",
    client: "claude-desktop",
    mode: "vector",
    reason: "stale_snapshot",
    fallback: "version_fallback",
    issueType: "outdated_docs",
    severity: "warning",
    ip: "ip_2e8b41d0",
    fingerprint: "fp_d4e5f6",
  },
  {
    id: "req_2c77d10",
    scope: "aspose.words / python / docs",
    type: "wrong_api",
    sev: "warn",
    q: "insert table of contents",
    outcome: "answered",
    results: 6,
    warn: "—",
    rec: "Citation points at a renamed member — flag for content fix.",
    locale: "fr",
    client: "qwen-code",
    mode: "lexical",
    reason: "scope_mismatch",
    fallback: "none",
    issueType: "wrong_docs",
    severity: "warning",
    ip: "ip_9c0f5a77",
    fingerprint: "fp_77ab90",
  },
  {
    id: "req_91be0a4",
    scope: "aspose.cells / net / apiref",
    type: "no_result",
    sev: "info",
    q: "pivot table grouping by month",
    outcome: "zero_result",
    results: 0,
    warn: "scope_mismatch",
    rec: "Version resolved to legacy; pin latest-stable.",
    locale: "es",
    client: "vscode",
    mode: "hybrid",
    reason: "scope_mismatch",
    fallback: "version_fallback",
    issueType: "other",
    severity: "info",
    ip: "ip_4d2c6e10",
    fingerprint: "fp_22cd44",
  },
];

interface Hotspot {
  scope: string;
  pri: StatusVariant;
  priLabel: string;
  sig: string;
  trend: string;
  delta: string;
  reports: number;
  q: string;
  rec: string;
  // Secondary-filter facets (offline only). `severity` + `issueType` use the SEVERITIES /
  // ISSUE_TYPES option vocabulary (the display `pri`/`sig` fields encode different labels),
  // and the rest let every secondary Select refine the hotspot list offline.
  locale?: string;
  client?: string;
  outcome?: string;
  mode?: string;
  reason?: string;
  fallback?: string;
  warn?: string;
  issueType?: string;
  severity?: string;
  // Scope-identity facets behind the two free-text "More filters" Inputs (Hashed IP / Fingerprint).
  ip?: string;
  fingerprint?: string;
}

const A_HOTSPOTS: Hotspot[] = [
  {
    scope: "aspose.3d / net / apiref",
    pri: "crit",
    priLabel: "highest",
    sig: "no_index_data · zero-result 62%",
    trend: "rising",
    delta: "+18 / 24h",
    reports: 9,
    q: '"export glb", "read fbx"',
    rec: "Top of backlog — onboard & publish.",
    locale: "en",
    client: "cursor",
    outcome: "zero_result",
    mode: "hybrid",
    reason: "no_index_data",
    fallback: "none",
    warn: "no_index_data",
    issueType: "missing_docs",
    severity: "critical",
    ip: "ip_7f3a9c21",
    fingerprint: "fp_a1b2c3",
  },
  {
    scope: "aspose.ocr / net / docs",
    pri: "warn",
    priLabel: "medium",
    sig: "stale_snapshot · low-confidence 21%",
    trend: "flat",
    delta: "+1 / 24h",
    reports: 4,
    q: '"handwriting", "pdf ocr"',
    rec: "Schedule reingest this cycle.",
    locale: "de",
    client: "claude-desktop",
    outcome: "low_confidence",
    mode: "vector",
    reason: "stale_snapshot",
    fallback: "version_fallback",
    warn: "stale_snapshot",
    issueType: "outdated_docs",
    severity: "warning",
    ip: "ip_2e8b41d0",
    fingerprint: "fp_d4e5f6",
  },
  {
    scope: "aspose.words / python / docs",
    pri: "info",
    priLabel: "low",
    sig: "wrong_api · citation 3%",
    trend: "falling",
    delta: "−2 / 24h",
    reports: 2,
    q: '"toc", "mail merge"',
    rec: "Content fix; monitor.",
    locale: "fr",
    client: "qwen-code",
    outcome: "answered",
    mode: "lexical",
    reason: "scope_mismatch",
    fallback: "none",
    warn: "low_confidence",
    issueType: "wrong_docs",
    severity: "info",
    ip: "ip_9c0f5a77",
    fingerprint: "fp_77ab90",
  },
];

// API limitation: capacityForecastQuery only feeds the saturation KPI offline (queries disabled). This
// fixture drives the Capacity-forecast panel's hottest-products table fully offline (per-product
// projected 24h demand + quality pressure + saturation risk + recommended action).
interface CapRow {
  product: string;
  projected: number;
  growth: string;
  zeroPct: number;
  lowConfPct: number;
  risk: Risk;
  rec: string;
}

const A_CAPACITY: CapRow[] = [
  {
    product: "aspose.3d",
    projected: 1480,
    growth: "+22%",
    zeroPct: 62,
    lowConfPct: 9,
    risk: "high",
    rec: "Onboard & publish before the demand spike — every query zero-results today.",
  },
  {
    product: "aspose.ocr",
    projected: 980,
    growth: "+11%",
    zeroPct: 8,
    lowConfPct: 21,
    risk: "medium",
    rec: "Reingest to clear the stale snapshot before traffic grows further.",
  },
  {
    product: "aspose.words",
    projected: 760,
    growth: "+4%",
    zeroPct: 3,
    lowConfPct: 6,
    risk: "low",
    rec: "Healthy — keep on the normal refresh cadence.",
  },
  {
    product: "aspose.cells",
    projected: 540,
    growth: "−2%",
    zeroPct: 11,
    lowConfPct: 7,
    risk: "medium",
    rec: "Pin latest-stable so legacy versions stop draining capacity.",
  },
];

// API limitation: saved views persist in the hook's localStorage list, which is empty on a first/offline
// visit. This fixture shows the saved-views surface (Apply / Delete) populated so the feature is
// usable offline (named filter sets, max 30, Apply + Delete actions).
const A_SAVED_VIEWS: AnalyticsSavedView[] = [
  {
    view_id: "fixture-3d-coverage",
    name: "3D coverage gaps",
    product_id: "aspose.3d",
    programming_language: "net",
    doc_locale: "",
    client_id: "cursor",
    source_kind: "apiref",
    outcome: "zero_result",
    retrieval_mode: "",
    zero_result_reason: "no_index_data",
    fallback_reason: "",
    warning_code: "",
    hashed_ip: "ip_7f3a9c21",
    fingerprint: "fp_a1b2c3",
    created_at: "2026-06-04T09:12:00.000Z",
  },
  {
    view_id: "fixture-ocr-freshness",
    name: "OCR freshness watch",
    product_id: "aspose.ocr",
    programming_language: "",
    doc_locale: "",
    client_id: "",
    source_kind: "docs",
    outcome: "low_confidence",
    retrieval_mode: "hybrid",
    zero_result_reason: "",
    fallback_reason: "",
    warning_code: "stale_snapshot",
    created_at: "2026-06-03T16:40:00.000Z",
  },
];

// API limitation: the Request replay inspector's detail resolves from `requestEvidenceQuery`, a per-id
// query that is DISABLED offline (needs a backend session + a selected request id). With no
// backend the inspector would have no `evidence` and collapse the "Current replay" column onto
// the original (empty result list, confidence Δ=0, no fault domain). This fixture gives EACH inbox
// issue a realistic replayed-evidence record — original vs current outcome, a current result list,
// confidence delta, suspected fault domain, and operator hint — so a selection populates the panel
// offline.

/** Minimal current-replay result the inspector lists (title / canonical_url); the factory pads the
 *  remaining PublicQueryDocsResult fields with valid neutral defaults the panel never reads. */
interface ReplayResultSeed {
  title: string;
  canonical_url: string;
}

/** Realistic per-issue replay-evidence seed; the factory expands it into a full, type-valid
 *  RequestEvidenceResponse identical in shape to the live query payload. */
interface ReplayEvidenceSeed {
  original: { outcome: string; result_count: number; warning_codes: string[] };
  replay: { outcome: string; result_count: number; results: ReplayResultSeed[] };
  diff: {
    summary: string;
    confidence_delta: number;
    suspected_fault_domain: string;
    operator_hint: string;
  };
}

function makeReplayResult(seed: ReplayResultSeed, index: number): PublicQueryDocsResult {
  return {
    chunk_id: `fixture-chunk-${index + 1}`,
    title: seed.title,
    excerpt: "",
    canonical_url: seed.canonical_url,
    section_anchor: "",
    score: 0,
    source_revision: "fixture",
    executable_snippets: [],
  };
}

/** Expand a seed into a complete RequestEvidenceResponse. Fields the inspector renders carry the
 *  seed's realistic values; the verbose required-but-unread members get valid neutral defaults so
 *  the offline fixture is the exact shape live would return. */
function makeReplayEvidence(id: string, seed: ReplayEvidenceSeed): RequestEvidenceResponse {
  const emptyQuery: PublicQueryDocsResponse = {
    query_id: `fixture-query-${id}`,
    request_id: id,
    mode: "hybrid",
    query_locale_detected: "en",
    translation_fallback_applied: false,
    confidence: 0,
    confidence_level: "low",
    fallback_reason: null,
    version_resolution: {
      requested_version: null,
      preferred_version: null,
      resolved_version: null,
      available_versions: [],
      prefers_latest_stable: true,
      strict_version_enforced: false,
      fallback_applied: false,
      fallback_reason: null,
    },
    clarification_questions: [],
    quality: {
      overall_score: 0,
      coverage_score: 0,
      freshness_score: 0,
      freshness_source: "fixture",
      citation_density_score: 0,
      symbol_match_score: 0,
      intent: "task",
      intent_subtype: null,
      completeness_status: "unknown",
      completeness_missing_signals: [],
    },
    results: seed.replay.results.map(makeReplayResult),
    warnings: [],
    api_guardrails: [],
    explainability: {
      reranker_backend: "fixture",
      intent_subtype: null,
      freshness_source: "fixture",
      why_top_result: [],
      why_version: null,
      why_fallback: null,
    },
    debug: null,
  };
  return {
    request_id: id,
    original: {
      request_id: id,
      endpoint: "/v1/docs:query",
      tool: "query_docs",
      raw_query: "",
      product_id: null,
      programming_language: null,
      doc_locale: null,
      confidence: 0,
      outcome: seed.original.outcome,
      retrieval_mode: "hybrid",
      result_count: seed.original.result_count,
      zero_result_reason: null,
      fallback_reason: null,
      warning_codes: seed.original.warning_codes,
      created_at: "2026-06-04T08:00:00.000Z",
    },
    replay: {
      executed_at: "2026-06-05T09:00:00.000Z",
      request: {
        query: "",
        product_id: null,
        programming_language: null,
        doc_locale: null,
        version: null,
        top_k: 8,
        strict_version: false,
        include_examples: true,
        doc_types: [],
        assumptions: [],
      },
      outcome: seed.replay.outcome,
      result_count: seed.replay.result_count,
      zero_result_reason: null,
      fallback_reason: null,
      response: emptyQuery,
    },
    diff: {
      drift_status: seed.diff.suspected_fault_domain === "none" ? "stable" : "drifted",
      summary: seed.diff.summary,
      outcome_changed: seed.original.outcome !== seed.replay.outcome,
      original_outcome: seed.original.outcome,
      current_outcome: seed.replay.outcome,
      result_count_delta: seed.replay.result_count - seed.original.result_count,
      confidence_delta: seed.diff.confidence_delta,
      warning_codes_added: [],
      warning_codes_removed: [],
      fallback_changed: false,
      original_fallback_reason: null,
      current_fallback_reason: null,
      zero_result_reason_changed: false,
      original_zero_result_reason: null,
      current_zero_result_reason: null,
      suspected_fault_domain: seed.diff.suspected_fault_domain,
      suspected_fault_reason: seed.diff.summary,
      operator_hint: seed.diff.operator_hint,
      unavailable_original_fields: [],
    },
    related_issue_reports: [],
    related_usefulness_feedback: [],
    copy_context: { request_id: id, source: "fixture" },
    generated_at: "2026-06-05T09:00:00.000Z",
  };
}

// Keyed by the A_ISSUES inbox ids so a selection resolves its detail offline (live query wins when
// present). Each record tells a coherent drift story matching that issue's failure signal.
const A_REPLAY_EVIDENCE: Record<string, RequestEvidenceResponse> = {
  req_8c3864e: makeReplayEvidence("req_8c3864e", {
    original: { outcome: "zero_result", result_count: 0, warning_codes: ["no_index_data"] },
    replay: { outcome: "zero_result", result_count: 0, results: [] },
    diff: {
      summary: "Coverage drift — aspose.3d.apiref still has no active snapshot, so the replay returns nothing.",
      confidence_delta: 0,
      suspected_fault_domain: "coverage",
      operator_hint: "Onboard & publish aspose.3d.apiref, then replay to confirm the scope now answers.",
    },
  }),
  req_4a1f9b2: makeReplayEvidence("req_4a1f9b2", {
    original: { outcome: "low_confidence", result_count: 3, warning_codes: ["stale_snapshot"] },
    replay: {
      outcome: "answered",
      result_count: 4,
      results: [
        {
          title: "Recognize handwriting — accuracy settings",
          canonical_url: "https://docs.aspose.com/ocr/net/recognize-handwriting/",
        },
        {
          title: "OcrEngine.RecognitionSettings",
          canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/recognitionsettings/",
        },
        {
          title: "Tune recognition for noisy scans",
          canonical_url: "https://docs.aspose.com/ocr/net/improve-accuracy/",
        },
      ],
    },
    diff: {
      summary: "Freshness recovered — a newer snapshot now answers what was low-confidence at capture.",
      confidence_delta: 0.27,
      suspected_fault_domain: "freshness",
      operator_hint: "Issue likely resolved by the latest reingest — verify the citation and close the report.",
    },
  }),
  req_2c77d10: makeReplayEvidence("req_2c77d10", {
    original: { outcome: "answered", result_count: 6, warning_codes: [] },
    replay: {
      outcome: "answered",
      result_count: 6,
      results: [
        {
          title: "Insert a table of contents",
          canonical_url: "https://docs.aspose.com/words/python-net/insert-table-of-contents/",
        },
        {
          title: "DocumentBuilder.insert_table_of_contents",
          canonical_url: "https://reference.aspose.com/words/python-net/aspose.words/documentbuilder/",
        },
      ],
    },
    diff: {
      summary: "Retrieval drift — the top citation points at a renamed member; ranking is otherwise stable.",
      confidence_delta: -0.04,
      suspected_fault_domain: "retrieval",
      operator_hint: "Flag the renamed member for a content fix; retrieval scope and freshness are healthy.",
    },
  }),
  req_91be0a4: makeReplayEvidence("req_91be0a4", {
    original: { outcome: "zero_result", result_count: 0, warning_codes: ["scope_mismatch"] },
    replay: {
      outcome: "answered",
      result_count: 5,
      results: [
        {
          title: "Group pivot table rows by month",
          canonical_url: "https://docs.aspose.com/cells/net/pivot-tables-grouping/",
        },
        {
          title: "PivotField.group_by",
          canonical_url: "https://reference.aspose.com/cells/net/aspose.cells.pivot/pivotfield/",
        },
      ],
    },
    diff: {
      summary: "Resolved — pinning latest-stable cleared the legacy version mismatch and the replay now answers.",
      confidence_delta: 0.41,
      suspected_fault_domain: "none",
      operator_hint: "Version pin fixed the miss — confirm and close; no ingestion change needed.",
    },
  }),
};

const PRODUCTS = [
  "All products",
  "aspose.3d",
  "aspose.barcode",
  "aspose.cad",
  "aspose.cells",
  "aspose.ocr",
  "aspose.words",
  "aspose.pdf",
  "aspose.slides",
  "groupdocs.parser",
  "groupdocs.viewer",
];
const LANGS = ["All languages", "net", "java", "python", "cpp"];
const RISKS = ["All risk", "High", "Medium", "Low"];
const KINDS = ["All kinds", "apiref", "docs"];
// Secondary-filter option sets (outcome, mode, zero-result reason, fallback reason, warning
// code, issue type, severity, locale, client behind a Collapse). "All …" maps to the hook's "".
const LOCALES = ["All locales", "en", "de", "fr", "es", "ja", "zh"];
const CLIENTS = ["All clients", "cursor", "claude-desktop", "qwen-code", "vscode"];
const OUTCOMES = ["All outcomes", "answered", "low_confidence", "zero_result"];
const MODES = ["All modes", "hybrid", "vector", "lexical"];
const ZRR_OPTS = [
  "All zero-result reasons",
  "no_index_data",
  "scope_mismatch",
  "stale_snapshot",
  "language_fallback",
  "version_fallback",
];
const FALLBACK_OPTS = ["All fallbacks", "language_fallback", "version_fallback", "none"];
const WARNING_OPTS = ["All warnings", "stale_snapshot", "low_confidence", "no_index_data"];
const ISSUE_TYPES = [
  "All issue types",
  "missing_docs",
  "wrong_docs",
  "outdated_docs",
  "bad_example",
  "other",
];
const SEVERITIES = ["All severities", "critical", "warning", "info"];

// ─────────────────────────────────────────────────────── Small composites ──────────

function severityVariant(sev: "crit" | "warn" | "info"): StatusVariant {
  return sev;
}

/** Bar/pie chart block. `mode` toggles the visual; the pie is a CSS conic gradient over tokens. */
function ChartBlock({
  title,
  rows,
  sub,
  mode = "bar",
}: {
  title: string;
  rows: BarDatum[];
  sub?: string;
  mode?: "bar" | "pie";
}) {
  if (mode === "pie") {
    return <PieBlock title={title} rows={rows} sub={sub} />;
  }
  return (
    <div className="chart">
      <div className="chart-h">
        <span className="chart-title">{title}</span>
        {sub && <span className="chart-sub">{sub}</span>}
      </div>
      {rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <span className="bar-lbl">{r.label}</span>
          <span className="bar-track">
            <span className={cn("bar-fill", r.variant)} style={{ width: `${Math.max(r.pct, 2)}%` }} />
          </span>
          <span className="bar-val mono">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

const PIE_TOKEN: Record<StatusVariant, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  crit: "var(--crit)",
  info: "var(--info)",
  neutral: "var(--border-strong)",
};

/** Pie variant of a distribution: conic-gradient ring built only from Mono status tokens. */
function PieBlock({ title, rows, sub }: { title: string; rows: BarDatum[]; sub?: string }) {
  const total = rows.reduce((sum, r) => sum + (Number(r.value) || 0), 0) || 1;
  let acc = 0;
  const stops = rows
    .map((r) => {
      const frac = (Number(r.value) || 0) / total;
      const start = acc * 360;
      acc += frac;
      const end = acc * 360;
      return `${PIE_TOKEN[r.variant]} ${start.toFixed(1)}deg ${end.toFixed(1)}deg`;
    })
    .join(", ");
  return (
    <div className="chart">
      <div className="chart-h">
        <span className="chart-title">{title}</span>
        {sub && <span className="chart-sub">{sub}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 4 }}>
        <span
          aria-hidden
          style={{
            width: 84,
            height: 84,
            flex: "none",
            borderRadius: "999px",
            background: `conic-gradient(${stops})`,
            border: "1px solid var(--border)",
          }}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {rows.map((r) => (
            <span
              key={r.label}
              style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11.5, color: "var(--fg-muted)" }}
            >
              <span
                aria-hidden
                style={{ width: 9, height: 9, borderRadius: 3, background: PIE_TOKEN[r.variant], flex: "none" }}
              />
              <span style={{ flex: 1 }}>{r.label}</span>
              <span className="mono" style={{ color: "var(--fg)" }}>
                {r.value}
              </span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Live → fixture-shape mappers ──────────
// Helpers translate the hook's response payloads into the existing fixture shapes so the
// section renders identically whether data is live or offline (fixtures fallback).

const ALL_PRODUCT = "All products";
const ALL_LANG = "All languages";

/** "" (hook = no filter) ↔ "All products" (Select fixture label), else the raw id. */
function filterToLabel(value: string, allLabel: string): string {
  return value ? value : allLabel;
}
function labelToFilter(label: string, allLabel: string): string {
  return label === allLabel ? "" : label;
}

/** Build percentage bar rows from a `Record<string,number>` count map, mapped to fixture labels. */
function barsFromCounts(
  template: BarDatum[],
  counts: Record<string, number> | undefined,
): BarDatum[] {
  if (!counts || Object.keys(counts).length === 0) return template;
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0) || 1;
  return template.map((row) => {
    const n = counts[row.label] ?? 0;
    return { ...row, value: String(n), pct: Math.round((n / total) * 100) };
  });
}

function riskFromLevel(level: string): Risk {
  if (level === "high" || level === "critical") return "high";
  if (level === "medium" || level === "warning") return "medium";
  return "low";
}

function riskPill(risk: Risk): StatusVariant {
  return RISK_PILL[risk];
}

/**
 * Client-side scope matcher so the toolbar filters refine the display source OFFLINE
 * (live mode already filters server-side; this predicate is idempotent on live rows).
 * Cockpit/issue/hotspot fixtures encode scope as free text ("aspose.3d / net / apiref"
 * or "aspose.ocr · aspose.cells"); a token is "All …" when no filter is set. Falsy
 * (empty) and "All …" selections match everything so an unrelated dimension never hides
 * a row that has no such token.
 */
function scopeMatches(
  scopeText: string,
  product: string,
  lang: string,
  kind: string,
): boolean {
  const hay = scopeText.toLowerCase();
  const wants = (token: string, allLabel: string): boolean => {
    if (!token || token === allLabel) return true;
    return hay.includes(token.toLowerCase());
  };
  return (
    wants(product, ALL_PRODUCT) && wants(lang, ALL_LANG) && wants(kind, "All kinds")
  );
}

/**
 * Per-row secondary-filter facets the offline fixtures carry so the nine "More filters"
 * Selects (locale, client, outcome, mode, zero-result reason, fallback reason, warning
 * code, issue type, severity) visibly refine the cockpit / issue inbox / hotspot rows with
 * NO backend. Live rows never carry these (the server already applied the filters) → the
 * matcher treats an absent facet as a match, keeping the predicate idempotent on live data.
 */
interface SecFacets {
  locale?: string;
  client?: string;
  outcome?: string;
  mode?: string;
  reason?: string;
  fallback?: string;
  warn?: string;
  issueType?: string;
  severity?: string;
  ipHash?: string;
  fingerprint?: string;
}

/** Active label values of the nine secondary filters ("All …" = unset → match-all). */
interface SecFilters {
  locale: string;
  client: string;
  outcome: string;
  mode: string;
  zrr: string;
  fallback: string;
  warning: string;
  issueType: string;
  severity: string;
  // Free-text scope identifiers (Input controls); narrow offline via substring match.
  ipHash: string;
  fingerprint: string;
}

/**
 * Match-all-default secondary predicate (mirrors `scopeMatches`' `wants` idiom): a filter
 * at its "All …" default never hides a row, and a dimension a row does not encode never
 * hides it either. So with every Select at default the full fixture set shows, and moving
 * ANY one Select narrows the visible offline rows on whichever surfaces carry that facet.
 */
function secondaryMatches(f: SecFacets, sel: SecFilters): boolean {
  const wants = (facet: string | undefined, token: string, allLabel: string): boolean => {
    if (!token || token === allLabel) return true; // filter unset → match everything
    if (facet == null) return true; // row (e.g. live) does not encode this dimension
    return facet.toLowerCase() === token.toLowerCase();
  };
  // Free-text identifiers (hashed IP / fingerprint) come from kit Inputs: empty = unset →
  // match-all, and a non-empty value narrows by case-insensitive substring so typing a prefix
  // visibly trims the offline fixtures. Live rows omit the facet → idempotent (match).
  const wantsText = (facet: string | undefined, token: string): boolean => {
    const needle = token.trim();
    if (!needle) return true; // filter unset → match everything
    if (facet == null) return true; // row (e.g. live) does not encode this dimension
    return facet.toLowerCase().includes(needle.toLowerCase());
  };
  return (
    wants(f.locale, sel.locale, "All locales") &&
    wants(f.client, sel.client, "All clients") &&
    wants(f.outcome, sel.outcome, "All outcomes") &&
    wants(f.mode, sel.mode, "All modes") &&
    wants(f.reason, sel.zrr, "All zero-result reasons") &&
    wants(f.fallback, sel.fallback, "All fallbacks") &&
    wants(f.warn, sel.warning, "All warnings") &&
    wants(f.issueType, sel.issueType, "All issue types") &&
    wants(f.severity, sel.severity, "All severities") &&
    wantsText(f.ipHash, sel.ipHash) &&
    wantsText(f.fingerprint, sel.fingerprint)
  );
}

// ─────────────────────────────────────────────────────────── Section ──────────

export function AnalyticsSection() {
  const { navigate, consumeIntent } = useShell();
  const { toast } = useToast();
  const data = useAdminData();

  // Reuse the existing analytics data layer. Inputs the Mono shell doesn't surface are passed
  // inert: registry/content option-augmenters stay empty (API limitation), and the cross-section
  // navigation/quality-draft callbacks are no-ops — the Mono section routes those flows through
  // its own useShell().navigate. Without a backend the queries stay empty → fixtures render.
  const h = useAnalyticsState({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "analytics",
    // API limitation: registry language/locale + content-service/triage option lists are not wired into
    // the Mono shell; they only augment filter dropdowns this section doesn't expose.
    registryLanguageOptions: [],
    registryLocaleOptions: [],
    contentServicesRows: [],
    contentTriageData: null,
    showAlert: data.showAlert,
    openSection: () => {},
    jumpToElement: () => {},
    setSelectedProductId: () => {},
    setQualityRunVersion: () => {},
    setQualitySourceRevision: () => {},
    setSelectedQualityRunId: () => {},
    setSelectedQualityRunIds: () => {},
  });

  // Filter + sort state — product/language are owned by the hook (drive the live queries);
  // risk/kind remain local refinements over the (live-or-fixture) drift rows.
  const product = filterToLabel(h.analyticsProductFilter, ALL_PRODUCT);
  const setProduct = (label: string) =>
    h.setAnalyticsProductFilter(labelToFilter(label, ALL_PRODUCT));
  const lang = filterToLabel(h.analyticsLanguageFilter, ALL_LANG);
  const setLang = (label: string) => h.setAnalyticsLanguageFilter(labelToFilter(label, ALL_LANG));
  const [risk, setRisk] = useState("All risk");
  const kind = filterToLabel(h.analyticsSourceKindFilter, "All kinds");
  const setKind = (label: string) =>
    h.setAnalyticsSourceKindFilter(labelToFilter(label, "All kinds"));
  const [sortByProduct, setSortByProduct] = useState(false);

  // Cross-section prefill handoff: a source section can navigate here with a one-shot SectionIntent
  // (navigate("analytics", anchor?, { filters, reset })). On mount we drain it once via
  // consumeIntent and apply the filter keys this section owns — product → product filter, language →
  // language filter, severity → issue-severity filter — through the hook setters so live mode
  // re-fetches and the offline fixtures re-scope identically. `reset: true` clears every filter
  // first (matching the toolbar "Clear"). consumeIntent is already one-shot, but the empty-dep
  // effect + ref guard keep it from re-applying under React StrictMode's double-invoke in dev.
  // Unknown filter keys are ignored; absent/empty intent is a no-op.
  const intentApplied = useRef(false);
  useEffect(() => {
    if (intentApplied.current) return;
    intentApplied.current = true;
    const intent = consumeIntent("analytics");
    if (!intent) return;
    if (intent.reset) {
      h.clearAnalyticsFilters();
      setRisk("All risk");
    }
    const filters = intent.filters;
    if (!filters) return;
    if (filters.product != null) h.setAnalyticsProductFilter(filters.product);
    if (filters.language != null) h.setAnalyticsLanguageFilter(filters.language);
    if (filters.severity != null) h.setAnalyticsIssueSeverityFilter(filters.severity);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Secondary filters (locale, client, outcome, mode, zero-result reason, fallback reason,
  // warning code, issue type, severity) behind a Collapse. Each maps to a hook setter so live mode
  // re-fetches; the display sources also apply the same predicates so they respond offline.
  const [secOpen, setSecOpen] = useState(false);
  const locale = filterToLabel(h.analyticsLocaleFilter, "All locales");
  const client = filterToLabel(h.analyticsClientFilter, "All clients");
  const outcome = filterToLabel(h.analyticsOutcomeFilter, "All outcomes");
  const mode = filterToLabel(h.analyticsRetrievalModeFilter, "All modes");
  const zrrFilter = filterToLabel(h.analyticsZeroResultReasonFilter, "All zero-result reasons");
  const fallbackFilter = filterToLabel(h.analyticsFallbackReasonFilter, "All fallbacks");
  const warningFilter = filterToLabel(h.analyticsWarningCodeFilter, "All warnings");
  const issueType = filterToLabel(h.analyticsIssueTypeFilter, "All issue types");
  const severity = filterToLabel(h.analyticsIssueSeverityFilter, "All severities");
  // Free-text scope identifiers (kit Inputs): the hook value is the raw string ("" = unset), so no
  // "All …" label mapping — bind the value straight through and let `secondaryMatches` substring-match.
  const ipHash = h.analyticsIpHashFilter;
  const fingerprint = h.analyticsFingerprintFilter;
  // Bundle the secondary-filter labels so the cockpit / issue / hotspot display sources can apply
  // `secondaryMatches(...)` and respond offline (mirrors the primary scopeMatches wiring).
  const secFilters: SecFilters = {
    locale,
    client,
    outcome,
    mode,
    zrr: zrrFilter,
    fallback: fallbackFilter,
    warning: warningFilter,
    issueType,
    severity,
    ipHash,
    fingerprint,
  };
  // Count of active secondary filters → shown on the toggle so the operator knows scope is narrowed.
  const secActiveCount = [
    h.analyticsLocaleFilter,
    h.analyticsClientFilter,
    h.analyticsOutcomeFilter,
    h.analyticsRetrievalModeFilter,
    h.analyticsZeroResultReasonFilter,
    h.analyticsFallbackReasonFilter,
    h.analyticsWarningCodeFilter,
    h.analyticsIssueTypeFilter,
    h.analyticsIssueSeverityFilter,
    h.analyticsIpHashFilter,
    h.analyticsFingerprintFilter,
  ].filter(Boolean).length;
  // Auto-focus the first secondary filter when the Collapse opens (accessibility).
  // The kit Select doesn't forward refs, so focus by id after the row mounts.
  useEffect(() => {
    if (secOpen) {
      window.requestAnimationFrame(() =>
        document.getElementById("analytics-sec-first")?.focus(),
      );
    }
  }, [secOpen]);

  // Distribution chart mode toggle (charts toggle between bar and pie).
  const [chartMode, setChartMode] = useState<"bar" | "pie">("bar");

  // Issue inbox selection → request replay inspector below.
  const [selectedIssue, setSelectedIssue] = useState<string | null>(null);
  // Offline copy feedback: the hook's copiedIssueEvidenceRequestId only toggles on the live
  // clipboard path (it reads requestEvidenceQuery.data). When the inspector is rendering from the
  // A_REPLAY_EVIDENCE fixture (query disabled), this id drives the "Copied debug context" toggle.
  const [offlineCopiedId, setOfflineCopiedId] = useState<string | null>(null);
  // Drive the live request-evidence query from the selected issue (offline: query stays disabled →
  // the inspector falls back to the fixture verdict).
  useEffect(() => {
    h.setSelectedIssueEvidenceRequestId(selectedIssue ?? "");
  }, [selectedIssue]);

  // Save-view popover + saved-views delete reason modal state.
  const savePop = usePopover();
  const [viewToDelete, setViewToDelete] = useState<AnalyticsSavedView | null>(null);
  // The hook's saveAnalyticsView() reads its own analyticsViewName state, so commit the name first
  // then save on the NEXT render (when the hook closure sees the new name). `pendingSave` arms that.
  const [pendingSave, setPendingSave] = useState(false);
  useEffect(() => {
    if (pendingSave && h.analyticsViewName.trim().length > 0) {
      h.saveAnalyticsView();
      setPendingSave(false);
    }
  }, [pendingSave, h.analyticsViewName]);

  // write:settings gates "Create fix draft" (scope-gated; disabled state preserved when denied).
  const canWriteSettings = data.can("write:settings");

  // Primary query drives section-level loading / error / stale chrome. Fixtures fall back when empty.
  const sliceData = h.analyticsSliceQuery.data;
  const isStale = (sliceData?.refresh_lag_minutes ?? 0) > 60;
  // Opacity treatment for stale (Postgres read-only) panels (0.6 on affected panels).
  const staleStyle = isStale ? { opacity: 0.6 } : undefined;

  // ── Live → fixture-shape bindings (each falls back to its fixture when the query is empty) ──
  const zero = h.zeroResultOverviewQuery.data;
  const usefulness = h.usefulnessSummaryQuery.data;
  const capacity = h.capacityForecastQuery.data;

  const funnelStages: FunnelStage[] = h.publicAdoptionFunnelQuery.data?.stages.length
    ? h.publicAdoptionFunnelQuery.data.stages.map((s) => ({
        label: s.title,
        value: String(s.sessions),
        conv:
          s.conversion_from_previous == null
            ? "entry stage"
            : `${Math.round(s.conversion_from_previous * 100)}% conversion`,
        width: Math.round(s.share_of_filtered_sessions * 100),
      }))
    : FUNNEL;

  const distOutcome = barsFromCounts(A_DIST_OUTCOME, sliceData?.by_outcome);
  const distMode = barsFromCounts(A_DIST_MODE, sliceData?.by_retrieval_mode);
  const zrr = barsFromCounts(A_ZRR, zero?.by_zero_result_reason);
  const distFallback = barsFromCounts(A_DIST_FALLBACK, sliceData?.by_fallback_reason);
  const distWarning = barsFromCounts(A_DIST_WARNING, sliceData?.by_warning_code);
  const distEndpoint = barsFromCounts(A_DIST_ENDPOINT, sliceData?.by_endpoint);
  const distTool = barsFromCounts(A_DIST_TOOL, sliceData?.by_tool);
  const usefulnessBars = barsFromCounts(A_USEFULNESS, usefulness?.by_rating);
  const useReasons = barsFromCounts(A_USE_REASONS, usefulness?.by_reason_code);

  // Top KPIs.
  const totalRequests = sliceData ? String(sliceData.total_requests) : "1";
  const totalRequestsNum = sliceData?.total_requests ?? 1;
  const withoutUsefulPct = zero ? Math.round(zero.without_useful_result_share * 100) : 0;
  const zeroResultPct =
    zero && zero.filtered_requests_total > 0
      ? Math.round((zero.no_result_requests / zero.filtered_requests_total) * 100)
      : 0;
  const negativePct = usefulness ? Math.round(usefulness.negative_share * 100) : 0;
  const saturationRisk = capacity?.saturation_risk ?? "low";
  // Distinct endpoints / warnings KPIs — live count maps offline fall back to the fixture
  // distribution shapes so the chips read coherently with no backend.
  const distinctEndpoints = sliceData
    ? Object.keys(sliceData.by_endpoint).length
    : A_DIST_ENDPOINT.filter((r) => Number(r.value) > 0).length;
  const distinctWarnings = sliceData
    ? Object.keys(sliceData.by_warning_code).length
    : A_DIST_WARNING.filter((r) => Number(r.value) > 0).length;
  // Projected requests + growth% KPI — live forecast or the capacity fixture lead row.
  const projected = capacity ? capacity.projected_requests_next_24h : A_CAPACITY[0].projected;
  const growthPct = capacity
    ? Math.round((capacity.growth_ratio - 1) * 100)
    : 22;
  const growthLabel = `${growthPct >= 0 ? "+" : ""}${growthPct}%`;

  // Zero-result cockpit clusters → fixture shape.
  const cockpitSource: Cluster[] = zero?.clusters.length
    ? zero.clusters.map((c) => ({
        reason: c.zero_result_reason,
        impact: `${Math.round(c.share_of_filtered_requests * 100)}%`,
        scopes: c.affected_products.join(" · ") || "—",
        q: c.sample_queries[0] ? `"${c.sample_queries[0]}"` : "—",
        fix: c.recommendation_detail,
      }))
    : A_COCKPIT;
  // Refine on the display source so the toolbar filters work offline (kind not encoded here).
  // Primary scope + the nine secondary facets the cockpit fixtures carry (zero-result reason via
  // `reason`, plus locale/client/outcome/mode/fallback/warning/issue-type/severity).
  const cockpitClusters = cockpitSource.filter(
    (c) =>
      scopeMatches(c.scopes, product, lang, "All kinds") &&
      secondaryMatches(
        {
          locale: c.locale,
          client: c.client,
          outcome: c.outcome,
          mode: c.mode,
          reason: c.reason,
          fallback: c.fallback,
          warn: c.warn,
          issueType: c.issueType,
          severity: c.severity,
          ipHash: c.ip,
          fingerprint: c.fingerprint,
        },
        secFilters,
      ),
  );

  // Capacity hottest-products rows → fixture shape (projected demand + quality pressure).
  const capacitySource: CapRow[] = capacity?.hottest_products.length
    ? capacity.hottest_products.map((p) => ({
        product: p.product_id,
        projected: p.projected_requests_next_24h,
        growth: `${p.growth_ratio >= 1 ? "+" : ""}${Math.round((p.growth_ratio - 1) * 100)}%`,
        zeroPct: Math.round(p.zero_result_pressure_share * 100),
        lowConfPct: Math.round(p.low_confidence_share * 100),
        risk: riskFromLevel(p.saturation_risk),
        rec: p.recommended_action,
      }))
    : A_CAPACITY;
  const capacityRows = capacitySource.filter(
    (c) => product === ALL_PRODUCT || c.product === product,
  );

  // Issue inbox rows → fixture shape.
  const issueSource: Issue[] = h.issueReviewSummaryQuery.data?.recent_reports.length
    ? h.issueReviewSummaryQuery.data.recent_reports.map((r) => ({
        id: r.request_id,
        scope: [r.product_id, r.programming_language, r.tool]
          .filter(Boolean)
          .join(" / "),
        type: r.issue_type,
        sev: r.severity === "critical" ? "crit" : r.severity === "warning" ? "warn" : "info",
        q: r.raw_query,
        outcome: r.outcome,
        results: r.result_count,
        warn: r.warning_codes[0] ?? "—",
        rec: r.recommendation_detail,
      }))
    : A_ISSUES;
  // Refine on the display source so product/language/kind + the nine secondary filters work
  // offline. The inbox reads outcome/warning straight off the existing `outcome`/`warn` fields
  // (their values already match the option sets) and the issue-type/severity/locale/client/mode/
  // reason/fallback facets added to the fixture.
  const issueRows = issueSource.filter(
    (it) =>
      scopeMatches(it.scope, product, lang, kind) &&
      secondaryMatches(
        {
          locale: it.locale,
          client: it.client,
          outcome: it.outcome,
          mode: it.mode,
          reason: it.reason,
          fallback: it.fallback,
          warn: it.warn,
          issueType: it.issueType,
          severity: it.severity,
          ipHash: it.ip,
          fingerprint: it.fingerprint,
        },
        secFilters,
      ),
  );

  // Hotspot clusters → fixture shape.
  const hotspotSource: Hotspot[] = h.issueHotspotsQuery.data?.clusters.length
    ? h.issueHotspotsQuery.data.clusters.map((c) => ({
        scope: [c.product_id, c.programming_language, c.issue_type].filter(Boolean).join(" / "),
        pri: c.priority === "highest" || c.priority === "high" ? "crit" : c.severity === "warning" ? "warn" : "info",
        priLabel: c.priority,
        sig: `${c.zero_result_reason ?? c.primary_warning_code} · ${c.issue_type}`,
        trend: c.trend_status,
        delta: `${c.trend_delta >= 0 ? "+" : ""}${c.trend_delta} / 24h`,
        reports: c.total_reports,
        q: c.sample_queries[0] ? `"${c.sample_queries[0]}"` : "—",
        rec: c.recommendation_detail,
      }))
    : A_HOTSPOTS;
  // Refine on the display source so product/language + the nine secondary filters work offline
  // (kind not encoded here). Hotspots carry severity + issue-type (distinct from the display
  // `pri`/`sig` labels) plus locale/client/outcome/mode/reason/fallback/warning facets.
  const hotspotRows = hotspotSource.filter(
    (hs) =>
      scopeMatches(hs.scope, product, lang, "All kinds") &&
      secondaryMatches(
        {
          locale: hs.locale,
          client: hs.client,
          outcome: hs.outcome,
          mode: hs.mode,
          reason: hs.reason,
          fallback: hs.fallback,
          warn: hs.warn,
          issueType: hs.issueType,
          severity: hs.severity,
          ipHash: hs.ip,
          fingerprint: hs.fingerprint,
        },
        secFilters,
      ),
  );
  // Unfiltered totals for the partial-results "Showing X of Y" summaries.
  const issueTotal = issueSource.length;
  const hotspotTotal = hotspotSource.length;

  // Saved views: live localStorage list ↔ fixture so the surface is populated offline.
  const savedViews: AnalyticsSavedView[] = h.savedAnalyticsViews.length
    ? h.savedAnalyticsViews
    : A_SAVED_VIEWS;

  // Remediation campaign count for the guidance banner (hook-derived; fixture copy is "19").
  const campaignCount = h.remediationCampaigns.length;

  // Live freshness watchlist → DRIFT fixture shape; fed through the existing client-side filter memo
  // so risk/kind refinement, counts, sort, and show-more behave identically.
  const driftSource: DriftRow[] = h.freshnessWatchlistQuery.data?.items.length
    ? h.freshnessWatchlistQuery.data.items.map((it) => ({
        product: it.product_id,
        lang: it.programming_language ?? "—",
        kind: it.source_kind,
        risk: riskFromLevel(it.risk_level),
        score: Math.round(it.risk_score),
      }))
    : DRIFT;

  function resetFilters() {
    // Clear primary + every secondary filter ("Clear": all filter state → empty), and
    // return the watchlist sort to its "By risk" default (the first segment).
    h.clearAnalyticsFilters();
    setRisk("All risk");
    setSortByProduct(false);
  }

  // Refresh refetches EVERY slice query, not just the primary one (all 10 queries), so a live
  // failed panel is retried from any Refresh CTA —
  // header, the section error state, and each per-panel error action — rather than only by the 60s poll.
  function refetchAllSlices() {
    void h.analyticsSliceQuery.refetch();
    void h.zeroResultOverviewQuery.refetch();
    void h.capacityForecastQuery.refetch();
    void h.publicAdoptionFunnelQuery.refetch();
    void h.freshnessWatchlistQuery.refetch();
    void h.issueReviewSummaryQuery.refetch();
    void h.issueReviewSignalsQuery.refetch();
    void h.usefulnessSummaryQuery.refetch();
    void h.usefulnessSignalsQuery.refetch();
    void h.issueHotspotsQuery.refetch();
  }

  const drift = useMemo(() => {
    const rows = driftSource.filter(
      (d) =>
        (product === "All products" || d.product === product) &&
        (lang === "All languages" || d.lang === lang) &&
        (risk === "All risk" || d.risk === (risk.toLowerCase() as Risk)) &&
        (kind === "All kinds" || d.kind === kind),
    );
    rows.sort((a, b) =>
      sortByProduct
        ? a.product.localeCompare(b.product) || RISK_RANK[a.risk] - RISK_RANK[b.risk]
        : RISK_RANK[a.risk] - RISK_RANK[b.risk] || b.score - a.score,
    );
    const counts: Record<Risk, number> = { high: 0, medium: 0, low: 0 };
    rows.forEach((r) => (counts[r.risk] += 1));
    return { rows, counts, total: rows.length };
  }, [driftSource, product, lang, risk, kind, sortByProduct]);

  const DRIFT_LIMIT = 6;
  const visibleDrift = drift.rows.slice(0, DRIFT_LIMIT);
  const extraDrift = drift.rows.slice(DRIFT_LIMIT);

  // Section-level loading/error chrome gates on the DISPLAY set, not the live slice alone:
  // every tab has a fixture fallback, so offline `hasDisplayData` stays true and the tabbed
  // UI is never hidden behind a skeleton/error. Online the gate still fires while the primary
  // query is in-flight / failed AND no display content exists yet.
  const hasDisplayData =
    funnelStages.length > 0 ||
    cockpitClusters.length > 0 ||
    issueRows.length > 0 ||
    hotspotRows.length > 0 ||
    drift.total > 0;
  const slicesLoading = h.analyticsSliceQuery.isLoading && !hasDisplayData;
  const slicesError = h.analyticsSliceQuery.isError && !hasDisplayData;

  // Per-panel error isolation (each panel shows its own error independently; "Vector search
  // is offline" hint for the Qdrant-backed watchlist + cockpit). Gates on the panel's OWN query AND
  // an empty display set, so a fixture is never hidden offline (mirrors Health).
  const watchlistErr = h.freshnessWatchlistQuery.isError && drift.total === 0;
  const cockpitErr = h.zeroResultOverviewQuery.isError && cockpitClusters.length === 0;
  const capacityErr = h.capacityForecastQuery.isError && capacityRows.length === 0;
  const usefulnessErr = h.usefulnessSummaryQuery.isError && !usefulness;
  const inboxErr = h.issueReviewSummaryQuery.isError && issueRows.length === 0;
  const hotspotsErr = h.issueHotspotsQuery.isError && hotspotRows.length === 0;
  const funnelErr = h.publicAdoptionFunnelQuery.isError && !h.publicAdoptionFunnelQuery.data;

  function panelError(title: string, vectorBacked: boolean) {
    return (
      <ErrorState
        title={title}
        text="This panel's query failed; the others on this screen are unaffected and stay live."
        cause={
          vectorBacked
            ? "Vector search is offline — Qdrant is unreachable for this panel."
            : "a query timeout, storage backend error, or a filter scope that is too narrow."
        }
        actions={
          <>
            <Button variant="btn-primary" size="sm" icon="refresh" onClick={refetchAllSlices}>
              Refresh
            </Button>
            <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
              Clear filters
            </Button>
            <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
              Open Logs &amp; Traces
            </Button>
          </>
        }
      />
    );
  }

  // ── Tab: Overview ─────────────────────────────────────────────────────────
  const overview = (
    <>
      <Card
        title="Public adoption funnel"
        sub="Resolve → self-test → query → feedback → issue. Admin actions excluded."
      >
        <div id="analytics-public-funnel-panel" style={staleStyle}>
          {funnelErr ? (
            panelError("Adoption funnel is unavailable", false)
          ) : (
            <div className="funnel">
              {funnelStages.map((f) => (
                <div className="fstage" key={f.label}>
                  <div className="fs-label">{f.label}</div>
                  <div className="fs-val">{f.value}</div>
                  <div className="fs-conv">{f.conv}</div>
                  <div className="fbar">
                    <i style={{ width: `${f.width}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Distribution"
        sub="Traffic shape across outcomes, modes, and failure reasons. Toggle bar / pie to compare spread."
        right={
          <Segmented
            options={["Bar", "Pie"]}
            active={chartMode === "pie" ? 1 : 0}
            onChange={(i) => setChartMode(i === 1 ? "pie" : "bar")}
            ariaLabel="Distribution chart mode"
          />
        }
      >
        <div className="chart-grid" style={staleStyle}>
          <ChartBlock title="Request outcomes" rows={distOutcome} sub="24h window" mode={chartMode} />
          <ChartBlock title="Retrieval modes" rows={distMode} mode={chartMode} />
          <ChartBlock title="Zero-result reasons" rows={zrr} mode={chartMode} />
          <ChartBlock title="Fallback reasons" rows={distFallback} mode={chartMode} />
          <ChartBlock title="Warning codes" rows={distWarning} mode={chartMode} />
          <ChartBlock title="Endpoints" rows={distEndpoint} mode={chartMode} />
          <ChartBlock title="Tools" rows={distTool} mode={chartMode} />
        </div>
      </Card>

      <Card
        title="Usefulness feedback"
        sub="Quality gaps where content returned but did not help — invisible to zero-result metrics."
      >
        <div id="analytics-usefulness-feedback-panel" style={staleStyle}>
          {usefulnessErr ? (
            panelError("Usefulness feedback is unavailable", false)
          ) : (
            <div className="chart-grid">
              <div>
                <ChartBlock title="Ratings" rows={usefulnessBars} mode={chartMode} />
              </div>
              <div>
                <ChartBlock title="Reason codes" rows={useReasons} mode={chartMode} />
              </div>
            </div>
          )}
        </div>
      </Card>
    </>
  );

  // ── Tab: Freshness watchlist ──────────────────────────────────────────────
  // The panel id sits on the outer container (not the kit Card, which takes no id prop) so an
  // inbound deep-link (navigate("analytics", "analytics-freshness-watchlist-panel"), fired by the
  // hook's campaign focusTarget) scrolls/focuses the whole panel including its header.
  const watchlist = (
    <div id="analytics-freshness-watchlist-panel">
    <Card
      title="Freshness drift watchlist"
      sub="Explainable stale-risk ranking. Filters above scope this list live; the shared action is collapsed into each row."
      right={
        <Segmented
          options={["By risk", "By product"]}
          active={sortByProduct ? 1 : 0}
          onChange={(i) => setSortByProduct(i === 1)}
          ariaLabel="Sort drift watchlist"
        />
      }
    >
      <div style={staleStyle}>
        {watchlistErr ? (
          panelError("Freshness watchlist is unavailable", true)
        ) : (
          <>
            <KpiRow cols={4}>
              <Kpi
                label="High risk"
                value={drift.counts.high}
                foot="act before adoption grows"
                accent
                pill={{ variant: "crit", text: "high" }}
              />
              <Kpi label="Medium risk" value={drift.counts.medium} foot="monitor & validate" />
              <Kpi label="Low risk" value={drift.counts.low} foot="normal monitoring" />
              <Kpi label="Filtered scopes" value={drift.total} foot="rows in view" />
            </KpiRow>

            {drift.total === 0 ? (
              <EmptyState
                title="No scopes match these filters"
                text="Loosen the product, language, risk, or kind filter to see drift candidates."
                action={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <TableCard>
                <Table>
                  <thead>
                    <tr>
                      <th>Scope</th>
                      <th style={{ width: 120 }}>Risk</th>
                      <th style={{ width: 150 }}>Lang / kind</th>
                      <th className="num" style={{ width: 90 }}>
                        Issues
                      </th>
                      <th>Primary reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleDrift.map((d) => (
                      <DriftScope key={`${d.product}.${d.kind}`} d={d} onNav={() => navigate("campaigns")} />
                    ))}
                    {extraDrift.length > 0 && (
                      <ShowMoreRow
                        key={`more-${product}-${lang}-${risk}-${kind}-${sortByProduct}`}
                        count={extraDrift.length}
                        colSpan={5}
                        extra={extraDrift.map((d) => (
                          <DriftScope
                            key={`${d.product}.${d.kind}`}
                            d={d}
                            onNav={() => navigate("campaigns")}
                          />
                        ))}
                      />
                    )}
                  </tbody>
                </Table>
              </TableCard>
            )}
          </>
        )}
      </div>
    </Card>
    </div>
  );

  // ── Tab: Capacity forecast ────────────────────────────────────────────────
  const capacityPanel = (
    <Card
      title="Capacity forecast"
      sub="Projected 24h demand and quality pressure per product. Coordinate refreshes and tuning ahead of demand spikes."
      flush
    >
      <div id="analytics-capacity-forecast-panel" style={staleStyle}>
        {capacityErr ? (
          <div style={{ padding: 16 }}>{panelError("Capacity forecast is unavailable", false)}</div>
        ) : (
          <>
            <div style={{ padding: "14px 16px 4px" }}>
              <KpiRow cols={4}>
                <Kpi
                  label="Projected requests (24h)"
                  value={projected.toLocaleString()}
                  foot={`${growthLabel} vs previous window`}
                  accent
                />
                <Kpi
                  label="Zero-result pressure"
                  value={
                    <>
                      {capacity ? Math.round(capacity.zero_result_pressure_share * 100) : capacityRows[0]?.zeroPct ?? 0}
                      <small>%</small>
                    </>
                  }
                  foot="weighing remediation"
                />
                <Kpi
                  label="Low-confidence pressure"
                  value={
                    <>
                      {capacity ? Math.round(capacity.low_confidence_share * 100) : capacityRows[0]?.lowConfPct ?? 0}
                      <small>%</small>
                    </>
                  }
                  foot="content quality"
                />
                <Kpi
                  label="Saturation risk"
                  value={saturationRisk}
                  foot="demand vs capacity"
                  pill={{ variant: riskPill(riskFromLevel(String(saturationRisk))), text: String(saturationRisk) }}
                />
              </KpiRow>
            </div>
            {capacityRows.length === 0 ? (
              <div style={{ padding: 16 }}>
                <EmptyState
                  title="No hottest products for the current filter set"
                  text="The forecast above still reflects the full window. Clear the product filter to list the per-product demand and pressure rows."
                  action={
                    <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                      Clear filters
                    </Button>
                  }
                />
              </div>
            ) : (
              <TableCard>
                <Table>
                  <thead>
                    <tr>
                      <th>Hottest products</th>
                      <th className="num" style={{ width: 130 }}>
                        Projected 24h
                      </th>
                      <th style={{ width: 90 }}>Growth</th>
                      <th className="num" style={{ width: 90 }}>
                        Zero %
                      </th>
                      <th className="num" style={{ width: 110 }}>
                        Low-conf %
                      </th>
                      <th style={{ width: 110 }}>Risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {capacityRows.map((c) => (
                      <CapacityRow key={c.product} c={c} onNav={() => navigate("campaigns")} />
                    ))}
                  </tbody>
                </Table>
              </TableCard>
            )}
          </>
        )}
      </div>
    </Card>
  );

  // ── Tab: Zero-result cockpit ──────────────────────────────────────────────
  const cockpit = (
    <Card
      title="Zero-result cockpit"
      sub="No-result & low-confidence clusters grouped by root cause. Act on highest-impact first."
      flush
    >
      <div id="analytics-zero-result-cockpit-panel" style={staleStyle}>
        {cockpitErr ? (
          <div style={{ padding: 16 }}>{panelError("Zero-result cockpit is unavailable", true)}</div>
        ) : cockpitClusters.length === 0 ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No zero-result or low-confidence clusters for the current filter set"
              text="Refresh the cockpit first. If it still stays empty, clear filters or move to SQL Explorer for manual diagnostics."
              action={
                <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                  Clear filters
                </Button>
              }
            />
          </div>
        ) : (
          cockpitClusters.map((c) => (
            <div className="cluster" key={c.reason}>
              <div className="cl-head">
                <Tag>{c.reason}</Tag>
                <span className="cl-impact">{c.impact} of misses</span>
                <span className="cl-scopes mono">{c.scopes}</span>
              </div>
              <div className="cl-q">sample: {c.q}</div>
              <div className="cl-fix">
                <Icon name="arrow" className="ico" /> {c.fix}
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );

  // ── Tab: Issue inbox + replay inspector ───────────────────────────────────
  // Resolve the selected request from the unfiltered source so the inspector keeps
  // working even if the toolbar filters scope it out of the visible inbox rows.
  const active = selectedIssue ? issueSource.find((x) => x.id === selectedIssue) : undefined;
  const inbox = (
    <>
      <Card
        title="Issue inbox"
        sub="Deduplicated public complaints linked to request evidence. Select a row to replay against the current index."
        flush
        right={
          <span className="muted-note">
            Showing {issueRows.length} of {issueTotal} issues
          </span>
        }
      >
        <div id="analytics-issue-inbox-panel" style={staleStyle}>
          {inboxErr ? (
            <div style={{ padding: 16 }}>{panelError("Issue inbox is unavailable", false)}</div>
          ) : issueRows.length === 0 ? (
            <div style={{ padding: 16 }}>
              <EmptyState
                title="No issue reports for the current filter set"
                text="Refresh the issue review feed and clear restrictive filters before assuming there are no open content reports."
                action={
                  <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                    Clear filters
                  </Button>
                }
              />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th style={{ width: 120 }}>Type</th>
                  <th style={{ width: 120 }}>Request</th>
                  <th style={{ width: 190 }}>Scope</th>
                  <th>Query</th>
                  <th className="num" style={{ width: 70 }}>
                    Results
                  </th>
                  <th style={{ width: 150 }}>Warning</th>
                </tr>
              </thead>
              <tbody>
                {issueRows.map((it) => (
                  <tr
                    key={it.id}
                    className={cn("data", "issue-row", it.id === selectedIssue && "sel")}
                    aria-selected={it.id === selectedIssue}
                    onClick={() => setSelectedIssue(it.id)}
                  >
                    <td>
                      <Pill variant={severityVariant(it.sev)}>{it.type.replace("_", " ")}</Pill>
                    </td>
                    <td>
                      <span className="repo-id">{it.id}</span>
                    </td>
                    <td>
                      <span className="mono" style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}>
                        {it.scope}
                      </span>
                    </td>
                    <td>{it.q}</td>
                    <td className="num mono">{it.results}</td>
                    <td>{it.warn === "—" ? <span className="muted-note">—</span> : <Tag>{it.warn}</Tag>}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </Card>

      <Card
        title="Request replay inspector"
        // The inspector card shows the title only once a row is selected;
        // the prompt sub remains only in the unselected/empty state.
        sub={active ? undefined : "Select an issue above to compare original evidence with current results."}
      >
        <div id="analytics-request-evidence-panel" style={staleStyle}>
          {active ? (
            <ReplayInspector
              it={active}
              // Live per-id evidence when the query has data; offline (query disabled) fall back to
              // the replay-evidence fixture keyed by the selected issue so the panel populates its
              // current-replay detail instead of collapsing onto the original.
              evidence={h.requestEvidenceQuery.data ?? A_REPLAY_EVIDENCE[active.id]}
              // "Copied debug context" toggle from either the live hook id or the offline fixture id.
              copiedId={h.copiedIssueEvidenceRequestId ?? offlineCopiedId}
              canWriteSettings={canWriteSettings}
              onReplay={() => h.requestEvidenceQuery.refetch()}
              onCopy={() => copyDebugContext(h.requestEvidenceQuery.data ?? A_REPLAY_EVIDENCE[active.id])}
              onCreateDraft={createFixDraft}
            />
          ) : (
            <EmptyState
              title="No request selected"
              text="Pick an issue row to replay it against the current index and detect coverage / freshness / retrieval drift."
            />
          )}
        </div>
      </Card>
    </>
  );

  // ── Tab: Hotspots ─────────────────────────────────────────────────────────
  const hotspots = (
    <Card
      title="Issue hotspots"
      sub="Repeated complaints clustered by scope and failure signal, ranked by priority and trend."
      right={
        <>
          <span className="muted-note">
            Showing {hotspotRows.length} of {hotspotTotal} hotspots
          </span>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="download"
            onClick={() =>
              h.issueHotspotsQuery.data ? h.exportIssueHotspotsCsv() : toast("Exported 3 hotspots to CSV")
            }
          >
            Export hotspots
          </Button>
        </>
      }
      flush
    >
      <div id="analytics-issue-hotspots-panel" style={staleStyle}>
        {hotspotsErr ? (
          <div style={{ padding: 16 }}>{panelError("Issue hotspots are unavailable", false)}</div>
        ) : hotspotRows.length === 0 ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No repeated issue hotspots for the current filter set"
              text="Refresh hotspot clustering first, then relax issue filters before assuming the queue has no repeated patterns."
              action={
                <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                  Clear filters
                </Button>
              }
            />
          </div>
        ) : (
          hotspotRows.map((hs) => (
            <div className="snap-row" key={hs.scope}>
              <div>
                <div className="snap-id" style={{ fontFamily: "var(--font-display)" }}>
                  {hs.scope}
                </div>
                <div className="snap-meta mono">
                  {hs.sig} · {hs.reports} reports · samples {hs.q}
                </div>
              </div>
              <div className="snap-right">
                <Pill variant={hs.pri}>{hs.priLabel}</Pill>
                <Tag>
                  {hs.trend} {hs.delta}
                </Tag>
                <span className="muted-note">{hs.rec}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );

  // ── Tab: Saved views ──────────────────────────────────────────────────────
  const savedViewsPanel = (
    <Card
      title="Saved views"
      sub="Named filter sets stored locally (max 30). Apply reloads every filter; Delete removes the view (filters and data are untouched)."
      flush
    >
      {savedViews.length === 0 ? (
        <EmptyState
          title="No saved views yet"
          text="Set the filters above, then use Save view in the header to store this scope as a named view for later."
        />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              <th style={{ width: 160 }}>Created</th>
              <th style={{ width: 170 }} />
            </tr>
          </thead>
          <tbody>
            {savedViews.map((v) => (
              <tr key={v.view_id} className="data">
                <td>
                  <span style={{ fontWeight: 600 }}>{v.name}</span>
                </td>
                <td>
                  <span className="mono" style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}>
                    {viewScopeLabel(v)}
                  </span>
                </td>
                <td>
                  <span className="mono" style={{ fontSize: "11.5px", color: "var(--fg-subtle)" }}>
                    {formatDate(v.created_at)}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      icon="arrow"
                      onClick={() => {
                        h.applyAnalyticsView(v);
                        setRisk("All risk");
                        setSortByProduct(false);
                        toast(`Applied view "${v.name}"`);
                      }}
                    >
                      Apply
                    </Button>
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      icon="x"
                      onClick={() => setViewToDelete(v)}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );

  // Create-fix-draft: scope-gated; on a real request id fire the hook mutation, else no-op the
  // mutation. Either way hand off to Quality, deep-linking the run queue panel where the guided
  // draft lands (navigate("quality", "quality-runs-panel")) so the operator continues the flow.
  function createFixDraft() {
    if (!canWriteSettings) return;
    if (active && active.id) {
      h.createGuidedContentFixDraftMutation.mutate({ requestId: active.id });
    }
    navigate("quality", "quality-runs-panel");
  }

  // Copy debug context: live path delegates to the hook (reads requestEvidenceQuery.data, sets the
  // 1.5s "Copied" toggle, alert fallback when clipboard is unavailable). Offline the inspector renders
  // from the A_REPLAY_EVIDENCE fixture, which the hook never sees — so copy that fixture's copy_context
  // here, toast like every other offline action, and drive the local "Copied debug context" toggle
  // (clipboard write + 1.5s feedback + alert fallback).
  function copyDebugContext(evidence: RequestEvidenceResponse | undefined) {
    if (h.requestEvidenceQuery.data) {
      void h.copyIssueEvidenceContext();
      return;
    }
    if (!evidence) return;
    const payload = JSON.stringify(evidence.copy_context, null, 2);
    const requestId = evidence.request_id;
    const markCopied = () => {
      setOfflineCopiedId(requestId);
      toast("Copied debug context");
      window.setTimeout(
        () => setOfflineCopiedId((current) => (current === requestId ? null : current)),
        1500,
      );
    };
    if (navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(payload).then(markCopied);
      return;
    }
    data.showAlert(payload, "Copy request evidence context");
  }

  // Save-view popover submit: commit the name into the hook, then arm the pendingSave effect so the
  // hook's saveAnalyticsView() runs once it sees the new name (persists locally, works offline).
  function submitSaveView(name: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    h.setAnalyticsViewName(trimmed);
    setPendingSave(true);
    savePop.close();
    toast(`Saved view "${trimmed}"`);
  }

  return (
    <>
      <PageHead
        title="Analytics"
        sub="Usage metrics, retrieval-quality signals, and capacity forecasting."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            {isStale && <StaleBadge>stale · cached</StaleBadge>}
            <div ref={savePop.wrapRef} style={{ position: "relative" }}>
              <Button
                variant="btn-ghost"
                size="sm"
                icon="plus"
                aria-haspopup="dialog"
                aria-expanded={savePop.open}
                onClick={savePop.toggle}
              >
                Save view
              </Button>
              {savePop.open && (
                <SaveViewPopover
                  count={savedViews.length}
                  onCancel={savePop.close}
                  onSave={submitSaveView}
                />
              )}
            </div>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="download"
              onClick={() =>
                sliceData ? h.exportAnalyticsSlicesCsv() : toast("Exported analytics slices to CSV")
              }
            >
              Export CSV
            </Button>
            <Button
              variant="btn-primary"
              size="sm"
              icon="refresh"
              onClick={refetchAllSlices}
            >
              Refresh
            </Button>
          </>
        }
      />

      <div className="toolbar">
        <Select width={160} options={PRODUCTS} value={product} onChange={(e) => setProduct(e.target.value)} aria-label="Filter by product" />
        <Select width={150} options={LANGS} value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Filter by language" />
        <Select width={140} options={RISKS} value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Filter by risk" />
        <Select width={140} options={KINDS} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind" />
        <div className="toolbar-right">
          <Button
            variant="btn-ghost"
            size="sm"
            icon="sliders"
            aria-expanded={secOpen}
            aria-controls="analytics-secondary-filters"
            onClick={() => setSecOpen((o) => !o)}
          >
            {secOpen ? "Hide filters" : "More filters"}
            {secActiveCount > 0 && <Tag>{secActiveCount}</Tag>}
          </Button>
          <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
            Reset
          </Button>
        </div>
      </div>

      {secOpen && (
        <div className="toolbar" id="analytics-secondary-filters" role="group" aria-label="Secondary filters">
          <Select label="Locale" width={150} options={LOCALES} value={locale} id="analytics-sec-first" onChange={(e) => h.setAnalyticsLocaleFilter(labelToFilter(e.target.value, "All locales"))} />
          <Select label="Client" width={160} options={CLIENTS} value={client} onChange={(e) => h.setAnalyticsClientFilter(labelToFilter(e.target.value, "All clients"))} />
          <Select label="Outcome" width={160} options={OUTCOMES} value={outcome} onChange={(e) => h.setAnalyticsOutcomeFilter(labelToFilter(e.target.value, "All outcomes"))} />
          <Select label="Mode" width={140} options={MODES} value={mode} onChange={(e) => h.setAnalyticsRetrievalModeFilter(labelToFilter(e.target.value, "All modes"))} />
          <Select label="Zero-result reason" width={190} options={ZRR_OPTS} value={zrrFilter} onChange={(e) => h.setAnalyticsZeroResultReasonFilter(labelToFilter(e.target.value, "All zero-result reasons"))} />
          <Select label="Fallback reason" width={170} options={FALLBACK_OPTS} value={fallbackFilter} onChange={(e) => h.setAnalyticsFallbackReasonFilter(labelToFilter(e.target.value, "All fallbacks"))} />
          <Select label="Warning code" width={170} options={WARNING_OPTS} value={warningFilter} onChange={(e) => h.setAnalyticsWarningCodeFilter(labelToFilter(e.target.value, "All warnings"))} />
          <Select label="Issue type" width={170} options={ISSUE_TYPES} value={issueType} onChange={(e) => h.setAnalyticsIssueTypeFilter(labelToFilter(e.target.value, "All issue types"))} />
          <Select label="Severity" width={150} options={SEVERITIES} value={severity} onChange={(e) => h.setAnalyticsIssueSeverityFilter(labelToFilter(e.target.value, "All severities"))} />
          <Input label="Hashed IP" width={170} placeholder="ip_…" value={ipHash} onChange={(e) => h.setAnalyticsIpHashFilter(e.target.value)} />
          <Input label="Fingerprint" width={170} placeholder="fp_…" value={fingerprint} onChange={(e) => h.setAnalyticsFingerprintFilter(e.target.value)} />
        </div>
      )}

      <KpiRow cols={5}>
        <Kpi label="Total requests" value={totalRequests} foot="current window" pill={{ variant: requestsVariant(totalRequestsNum), text: "24h" }} />
        <Kpi
          label="Without useful result"
          value={
            <>
              {withoutUsefulPct}
              <small>%</small>
            </>
          }
          foot="zero + low-confidence"
          accent
          pill={{ variant: shareVariant(withoutUsefulPct, 15, 5), text: shareWord(withoutUsefulPct, 15, 5) }}
        />
        <Kpi
          label="Zero-result"
          value={
            <>
              {zeroResultPct}
              <small>%</small>
            </>
          }
          foot="of resolved queries"
        />
        <Kpi
          label="Negative feedback"
          value={
            <>
              {negativePct}
              <small>%</small>
            </>
          }
          foot="of ratings"
          pill={{ variant: shareVariant(negativePct, 10, 5), text: shareWord(negativePct, 10, 5) }}
        />
        <Kpi label="Saturation risk" value={saturationRisk} foot="demand vs capacity" />
      </KpiRow>

      <KpiRow cols={4}>
        <Kpi label="Distinct endpoints" value={distinctEndpoints} foot="unique APIs queried" />
        <Kpi label="Distinct warnings" value={distinctWarnings} foot="retrieval-health codes" pill={distinctWarnings > 0 ? { variant: "warn", text: "investigate" } : undefined} />
        <Kpi
          label="Projected requests (24h)"
          value={projected.toLocaleString()}
          foot={`${growthLabel} vs previous window`}
        />
        <Kpi
          label="High-risk freshness"
          value={drift.counts.high}
          foot="scopes past stale target"
          pill={drift.counts.high > 0 ? { variant: "crit", text: "act now" } : { variant: "ok", text: "clear" }}
        />
      </KpiRow>

      <Banner
        variant="info"
        icon="info"
        guidance
        title={`${campaignCount > 0 ? campaignCount : 19} remediation campaigns planned`}
        text={
          <>
            These freshness and coverage signals are grouped into explainable campaigns.{" "}
            <button type="button" className="blink" onClick={() => navigate("campaigns")}>
              Open Coverage Campaigns →
            </button>
          </>
        }
      />

      {isStale && (
        <Banner
          variant="warn"
          icon="alert"
          title="Data is stale (Postgres may be in read-only mode)"
          text="Analytics queries returned cached results. Click Refresh to retry once the primary recovers."
        />
      )}

      {slicesLoading ? (
        <Skeleton rows={5} />
      ) : slicesError ? (
        <ErrorState
          title="Analytics slices are unavailable"
          text="One or more analytics queries failed. Recent traffic, distributions, and watchlist data could not be loaded."
          cause="storage backend down, a query timeout, or a filter scope that is too narrow."
          actions={
            <>
              <Button
                variant="btn-primary"
                size="sm"
                icon="refresh"
                onClick={refetchAllSlices}
              >
                Refresh
              </Button>
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={resetFilters}>
                Clear filters
              </Button>
              <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
                Open Logs &amp; Traces
              </Button>
            </>
          }
        />
      ) : (
        <Tabbed
          tabs={[
            "Overview",
            "Freshness watchlist",
            "Capacity forecast",
            "Zero-result cockpit",
            "Issue inbox",
            "Hotspots",
            "Saved views",
          ]}
          panels={[overview, watchlist, capacityPanel, cockpit, inbox, hotspots, savedViewsPanel]}
          initial={0}
        />
      )}

      {/* Footer timestamp: caption echoing the slice's refreshed_at so operators can spot
          stale data before acting. Rendered only when
          live data is present — offline the fixtures carry no real refresh time. The Refresh CTA's
          success feedback (a new 'Refreshed at: HH:MM' timestamp) lands here. */}
      {sliceData && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
          <span className="muted-note" aria-live="polite">
            Refreshed at: {formatDate(sliceData.refreshed_at)}
          </span>
        </div>
      )}

      {viewToDelete && (
        <DeleteViewModal
          view={viewToDelete}
          onClose={() => setViewToDelete(null)}
          onConfirm={(reason) => {
            // Reason captured for the audit trail; deletion only touches local storage (data
            // and filters are unaffected). Offline this still removes the row from the live list.
            h.deleteAnalyticsView(viewToDelete.view_id);
            toast(`Deleted view "${viewToDelete.name}" · ${reason.length} char reason logged`);
          }}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────── KPI threshold helpers ──────────
// Color-code primary metrics by threshold (red/yellow/green) using the pill variants.

function requestsVariant(n: number): StatusVariant {
  if (n > 1000) return "ok";
  if (n >= 100) return "warn";
  return "neutral";
}
function shareVariant(pct: number, red: number, yellow: number): StatusVariant {
  if (pct > red) return "crit";
  if (pct >= yellow) return "warn";
  return "ok";
}
function shareWord(pct: number, red: number, yellow: number): string {
  if (pct > red) return "high";
  if (pct >= yellow) return "watch";
  return "healthy";
}

function viewScopeLabel(v: AnalyticsSavedView): string {
  const parts = [
    v.product_id,
    v.programming_language,
    v.doc_locale,
    v.source_kind,
    v.outcome,
    v.warning_code,
    v.hashed_ip,
    v.fingerprint,
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "full dataset";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ───────────────────────────────────────────────── Watchlist drill-down row ──────────

function DriftScope({ d, onNav }: { d: DriftRow; onNav: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className={cn("data", "exp-toggle", open && "open")}
        onClick={() => setOpen((o) => !o)}
      >
        <td>
          <span className="cell-repo">
            <span className="exp">
              <Icon name={open ? "chevron" : "chevronR"} />
            </span>
            <span className="repo-id">
              {d.product}.{d.kind}
            </span>
          </span>
        </td>
        <td>
          <Pill variant={RISK_PILL[d.risk]}>
            {d.risk} · {d.score}
          </Pill>
        </td>
        <td>
          <Tag>{d.lang}</Tag> <Tag>{d.kind}</Tag>
        </td>
        <td className="num mono">issues 0</td>
        <td>
          <span className="card-sub" style={{ margin: 0 }}>
            No active healthy content service serving this scope.
          </span>
        </td>
      </tr>
      <tr className="exp-row" hidden={!open}>
        <td colSpan={5}>
          <div className="exp-panel">
            <div>
              <div className="eh">Primary reason</div>
              <div className="exp-reason">
                <div className="why">
                  No active healthy content service is serving this scope, so retrieval cannot prove
                  freshness or quality.
                </div>
              </div>
            </div>
            <div>
              <div className="eh">Recommended action</div>
              <ol className="fix-steps">
                <li>
                  <span>Reingest or republish the scope before public traffic grows further.</span>
                </li>
                <li>
                  <span>Run layout detection and Validate-Only if this repository was onboarded recently.</span>
                </li>
              </ol>
              <div className="exp-actions">
                <Button variant="btn-primary" size="sm" icon="arrow" onClick={onNav}>
                  Open in Campaigns
                </Button>
              </div>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}

// ─────────────────────────────────────────────────── Capacity hottest-product row ──────────

function CapacityRow({ c, onNav }: { c: CapRow; onNav: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className={cn("data", "exp-toggle", open && "open")}
        onClick={() => setOpen((o) => !o)}
      >
        <td>
          <span className="cell-repo">
            <span className="exp">
              <Icon name={open ? "chevron" : "chevronR"} />
            </span>
            <span className="repo-id">{c.product}</span>
          </span>
        </td>
        <td className="num mono">{c.projected.toLocaleString()}</td>
        <td>
          <Tag>{c.growth}</Tag>
        </td>
        <td className="num mono">{c.zeroPct}%</td>
        <td className="num mono">{c.lowConfPct}%</td>
        <td>
          <Pill variant={RISK_PILL[c.risk]}>{c.risk}</Pill>
        </td>
      </tr>
      <tr className="exp-row" hidden={!open}>
        <td colSpan={6}>
          <div className="exp-panel">
            <div>
              <div className="eh">Quality pressure</div>
              <div className="kvline">
                projected=<b>{c.projected.toLocaleString()}</b> · growth=<b>{c.growth}</b>
              </div>
              <div className="kvline">
                zero-result=<b>{c.zeroPct}%</b> · low-confidence=<b>{c.lowConfPct}%</b>
              </div>
              <div className="kvline">
                saturation=<b>{c.risk}</b>
              </div>
            </div>
            <div>
              <div className="eh">Recommended action</div>
              <ol className="fix-steps">
                <li>
                  <span>{c.rec}</span>
                </li>
              </ol>
              <div className="exp-actions">
                <Button variant="btn-primary" size="sm" icon="arrow" onClick={onNav}>
                  Open in Campaigns
                </Button>
              </div>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
}

// ─────────────────────────────────────────────────── Request replay inspector ──────────

function driftVerdict(it: Issue): string {
  if (it.outcome === "answered") return "No drift — current index still answers this request.";
  if (it.warn === "no_index_data") return "Coverage drift — scope still has no active snapshot.";
  if (it.warn === "stale_snapshot")
    return "Freshness drift — snapshot aged past target since this request.";
  return "Retrieval drift — ranking/scope changed since this request.";
}

function ReplayInspector({
  it,
  evidence,
  copiedId,
  canWriteSettings,
  onReplay,
  onCopy,
  onCreateDraft,
}: {
  it: Issue;
  evidence: RequestEvidenceResponse | undefined;
  copiedId: string | null;
  canWriteSettings: boolean;
  onReplay: () => void;
  onCopy: () => void;
  onCreateDraft: () => void;
}) {
  // Live evidence (when present) supplies the current result LIST, real confidence delta, and
  // assumptions; offline the inspector falls back to the fixture issue row's verdict.
  const diff = evidence?.diff;
  const replay = evidence?.replay;
  const results = replay?.response.results ?? [];
  const confDelta = diff ? diff.confidence_delta : 0;
  const copied = copiedId === it.id;
  return (
    <div className="replay">
      <div className="replay-head">
        <div className="rp-title">
          Request replay · <span className="repo-id">{it.id}</span>
        </div>
        <div className="rp-actions">
          <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onReplay}>
            Replay again
          </Button>
          <Button variant="btn-ghost" size="sm" icon="download" onClick={onCopy}>
            {copied ? "Copied debug context" : "Copy debug context"}
          </Button>
          <Button
            variant="btn-primary"
            size="sm"
            icon="arrow"
            disabled={!canWriteSettings}
            title={canWriteSettings ? undefined : "Requires the write:settings scope"}
            onClick={onCreateDraft}
          >
            Create fix draft
          </Button>
        </div>
      </div>
      <div className="replay-grid">
        <div>
          <div className="eh">Original evidence</div>
          <div className="kvline">
            scope=<b>{it.scope}</b>
          </div>
          <div className="kvline">
            outcome=<b>{evidence?.original.outcome ?? it.outcome}</b> · results=
            <b>{evidence?.original.result_count ?? it.results}</b>
          </div>
          <div className="kvline">
            warning=<b>{evidence?.original.warning_codes[0] ?? it.warn}</b>
          </div>
          <div className="rp-q">{it.q}</div>
        </div>
        <div>
          <div className="eh">Current replay</div>
          <div className="kvline">
            outcome=<b>{replay?.outcome ?? it.outcome}</b> · results=
            <b>{replay?.result_count ?? it.results}</b>
          </div>
          <div className="kvline">
            confidence Δ=<b>{confDelta > 0 ? "+" : ""}{confDelta.toFixed(2)}</b>
            {diff && (
              <>
                {" "}
                · fault=<b>{diff.suspected_fault_domain}</b>
              </>
            )}
          </div>
          {results.length > 0 ? (
            <ol className="fix-steps" style={{ marginTop: 9 }}>
              {results.slice(0, 3).map((r, i) => (
                <li key={i}>
                  <span className="mono" style={{ fontSize: "11.5px" }}>
                    {r.title || r.canonical_url || `result ${i + 1}`}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <div className="rp-drift">{diff ? diff.summary : driftVerdict(it)}</div>
          )}
        </div>
      </div>
      <div className="replay-hint">
        <Icon name="info" className="ico" /> {diff ? diff.operator_hint : it.rec}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Save-view popover (kit classes) ──────────
// Reuses the kit's PopoverPanel (.pop) + pop-head/body/foot classes so the save-view dialog
// matches the system exactly. Name is required → Save disabled until non-empty.

function SaveViewPopover({
  count,
  onCancel,
  onSave,
}: {
  count: number;
  onCancel: () => void;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState("");
  useEffect(() => {
    window.requestAnimationFrame(() => document.getElementById("save-view-name")?.focus());
  }, []);
  const atLimit = count >= 30;
  const ok = name.trim().length > 0 && !atLimit;
  return (
    <PopoverPanel>
      <div className="pop-head">
        <span className="pt">Save current view</span>
        <span className="ps">{count}/30</span>
      </div>
      <div className="pop-body">
        <Input
          label="View name"
          id="save-view-name"
          value={name}
          placeholder="e.g. 3D coverage gaps"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && ok) onSave(name);
          }}
        />
        <div className="muted-note" style={{ marginTop: 8 }}>
          {atLimit
            ? "View limit reached (30). Delete a view before saving a new one."
            : "Stores the full filter set locally — product, language, locale, client, kind, and every secondary refinement."}
        </div>
      </div>
      <div className="modal-foot" style={{ background: "transparent" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={!ok} onClick={() => onSave(name)}>
          Save view
        </button>
      </div>
    </PopoverPanel>
  );
}

// ─────────────────────────────────── Delete-view reason modal (ConfirmModal classes) ──────────
// Reuses ConfirmModal's overlay/modal/field/foot classes 1:1 and captures a reason (min length
// enforced) before the destructive delete, mirroring the kit's confirm flow. Traps focus + Esc.

function DeleteViewModal({
  view,
  onClose,
  onConfirm,
}: {
  view: AnalyticsSavedView;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const icon: IconName = "alert";
  const reasonOk = reason.trim().length >= REASON_MIN;

  useEffect(() => {
    reasonRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function doConfirm() {
    if (!reasonOk) return;
    onConfirm(reason.trim());
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="del-view-title" ref={modalRef}>
        <div className="modal-head">
          <div className="mi">
            <Icon name={icon} />
          </div>
          <div className="modal-title" id="del-view-title">
            Delete saved view “{view.name}”?
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div className="sum">
            view <b>{view.name}</b>
            <br />
            scope <b>{viewScopeLabel(view)}</b>
          </div>
          <div className="modal-field">
            <label htmlFor="del-view-reason" id="del-view-reason-label">
              Reason for deletion
            </label>
            <textarea
              id="del-view-reason"
              ref={reasonRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this view no longer needed? (searchable for future audits)"
              aria-labelledby="del-view-reason-label"
              aria-describedby="del-view-reason-hint"
              rows={3}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 68,
                resize: "vertical",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                padding: "9px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: "var(--fg)",
                outline: "none",
                lineHeight: 1.5,
              }}
            />
            <div className="confirm-hint" id="del-view-reason-hint">
              {reasonOk
                ? "Recorded in the audit trail. Filters and analytics data are unaffected."
                : `Enter at least ${REASON_MIN} characters (${reason.trim().length}/${REASON_MIN}).`}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={cn("btn", "btn-danger")} disabled={!reasonOk} onClick={doConfirm}>
            Delete view
          </button>
        </div>
      </div>
    </div>
  );
}
