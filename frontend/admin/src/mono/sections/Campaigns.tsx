"use client";

import { useEffect, useState, type ReactNode } from "react";

import type {
  RemediationCampaign,
  RemediationCampaignPriority,
  RemediationCampaignTarget,
} from "@/components/admin-console.types";
import { useAnalyticsState } from "@/hooks/useAnalyticsState";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Segmented } from "../components/Field";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { EmptyState, ErrorState, ReadonlyBanner, Skeleton, StaleBadge } from "../components/states";
import { Tag } from "../components/Tag";
import { Icon } from "../lib/icons";
import type { SectionKey, StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";

// ───────────────────────────────────────────────────────────────── Fixtures ──

type FaultDomain = "coverage" | "freshness" | "zero-result" | "retrieval" | "repeated-issue";

interface Campaign {
  title: string;
  scope: string;
  priorityVariant: StatusVariant;
  score: string;
  type: FaultDomain;
  signals: string;
  // ── Detail fields (carried per-row so the detail
  // panel renders fully offline). Live rows fill these from RemediationCampaign;
  // fixture rows carry realistic, grounded values.
  severityHint: string | null;
  blastRadiusSummary: string;
  repos: string[];
  evidence: string[];
  // Live handle (present ONLY for live rows). Drives the row's nav actions
  // through the hook's focus/workflow cascade. Null offline → fixtures fall back
  // to a local navigate via the fault-domain focus key (no-op cascade, still
  // switches section), so every action stays clickable offline.
  live: RemediationCampaign | null;
}

const CAMP: Campaign[] = [
  {
    title: "Coverage recovery for aspose.3d / apiref",
    scope: "aspose.3d / all / apiref",
    priorityVariant: "crit",
    score: "highest · 132",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "1,200 request/report signals in the current filtered scope",
    repos: ["aspose.3d.apiref:main", "aspose.3d.examples:main"],
    evidence: [
      "coverage_gap in aspose.3d.apiref:main",
      "mcp_unready:readiness_probe_failing",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Coverage recovery for aspose.barcode / docs",
    scope: "aspose.barcode / all / docs",
    priorityVariant: "crit",
    score: "highest · 132",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "980 request/report signals in the current filtered scope",
    repos: ["aspose.barcode.docs:main"],
    evidence: [
      "coverage_gap in aspose.barcode.docs:main",
      "service_status=down:no_active_snapshot",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Coverage recovery for aspose.cad / apiref",
    scope: "aspose.cad / all / apiref",
    priorityVariant: "crit",
    score: "highest · 132",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "760 request/report signals in the current filtered scope",
    repos: ["aspose.cad.apiref:main"],
    evidence: [
      "coverage_gap in aspose.cad.apiref:main",
      "mcp_unready:readiness_probe_failing",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Coverage recovery for aspose.cells / apiref",
    scope: "aspose.cells / all / apiref",
    priorityVariant: "crit",
    score: "highest · 128",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "640 request/report signals in the current filtered scope",
    repos: ["aspose.cells.apiref:main"],
    evidence: [
      "coverage_gap in aspose.cells.apiref:main",
      "critical:parse_errors",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Coverage recovery for aspose.ocr / docs",
    scope: "aspose.ocr / all / docs",
    priorityVariant: "crit",
    score: "highest · 124",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "1,040 request/report signals in the current filtered scope",
    repos: ["aspose.ocr.docs:main"],
    evidence: [
      "coverage_gap in aspose.ocr.docs:main",
      "service_status=degraded:stale_snapshot",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Coverage recovery for aspose.words / apiref",
    scope: "aspose.words / all / apiref",
    priorityVariant: "crit",
    score: "highest · 120",
    type: "coverage",
    signals: "2 signals",
    severityHint: "critical",
    blastRadiusSummary: "590 request/report signals in the current filtered scope",
    repos: ["aspose.words.apiref:main"],
    evidence: [
      "coverage_gap in aspose.words.apiref:main",
      "mcp_unready:readiness_probe_failing",
      "chunks=0, snippets=0",
    ],
    live: null,
  },
  {
    title: "Freshness recovery for aspose.3d / apiref",
    scope: "aspose.3d / all / apiref",
    priorityVariant: "warn",
    score: "medium · 86",
    type: "freshness",
    signals: "1 signal",
    severityHint: "warning",
    blastRadiusSummary: "62 grouped signals in the current filtered scope",
    repos: ["aspose.3d.apiref:main"],
    evidence: [
      "stale_snapshot in aspose.3d.apiref:main",
      "snapshot=23.12 -> visible=24.5",
      "queries=41, issues=3, negative=2",
    ],
    live: null,
  },
  {
    title: "Freshness recovery for aspose.barcode / docs",
    scope: "aspose.barcode / all / docs",
    priorityVariant: "warn",
    score: "medium · 78",
    type: "freshness",
    signals: "1 signal",
    severityHint: "warning",
    blastRadiusSummary: "48 grouped signals in the current filtered scope",
    repos: ["aspose.barcode.docs:main"],
    evidence: [
      "stale_snapshot in aspose.barcode.docs:main",
      "snapshot=23.10 -> visible=24.4",
      "queries=27, issues=1, negative=0",
    ],
    live: null,
  },
  {
    title: "Freshness recovery for aspose.cad / docs",
    scope: "aspose.cad / all / docs",
    priorityVariant: "warn",
    score: "medium · 74",
    type: "freshness",
    signals: "1 signal",
    severityHint: "warning",
    blastRadiusSummary: "39 grouped signals in the current filtered scope",
    repos: ["aspose.cad.docs:main"],
    evidence: [
      "stale_snapshot in aspose.cad.docs:main",
      "snapshot=23.11 -> visible=24.5",
      "queries=22, issues=2, negative=1",
    ],
    live: null,
  },
  {
    title: "Zero-result recovery for aspose.cells / net",
    scope: "aspose.cells / net / all",
    priorityVariant: "warn",
    score: "medium · 72",
    type: "zero-result",
    signals: "1 signal",
    severityHint: "warning",
    blastRadiusSummary: "144 request/report signals in the current filtered scope",
    repos: [],
    evidence: [
      "zero=scope_mismatch, fallback=language_fallback, mode=symbol",
      "warning=no_symbol_match, requests=144",
      '"pivot grouping" → zero_result',
    ],
    live: null,
  },
  {
    title: "Retrieval quality recovery for aspose.ocr / net",
    scope: "aspose.ocr / net / all",
    priorityVariant: "neutral",
    score: "low · 37",
    type: "retrieval",
    signals: "1 signal",
    severityHint: "warning",
    blastRadiusSummary: "21 grouped signals in the current filtered scope",
    repos: [],
    evidence: [
      "low_confidence below 0.35 threshold",
      "citation_loss:missing_source_anchors",
      "quality run rev_4a1f9b2",
    ],
    live: null,
  },
  {
    title: "Repeated-issue recovery for groupdocs.parser",
    scope: "groupdocs.parser / all / docs",
    priorityVariant: "neutral",
    score: "low · 31",
    type: "repeated-issue",
    signals: "1 signal",
    severityHint: null,
    blastRadiusSummary: "18 grouped signals in the current filtered scope",
    repos: ["groupdocs.parser.docs:main"],
    evidence: [
      "repeated_issue / warning / low",
      "reports=4, delta=+2",
      '"mail merge" → wrong_api',
    ],
    live: null,
  },
];

// Map a live RemediationCampaign (hook) onto the section's row shape. The hook
// only emits coverage | freshness | retrieval fault domains — all present as
// CAMP_DETAIL keys — so the generic fault-domain explanation and the offline
// fallback targets still resolve per row. The live campaign itself is kept so
// the expanded panel renders the campaign's OWN summary / signal_counts /
// next_steps and the row's nav actions honor its focus/workflow targets.
function priorityToVariant(priority: RemediationCampaignPriority): StatusVariant {
  if (priority === "highest") return "crit";
  if (priority === "high" || priority === "medium") return "warn";
  return "neutral";
}

function liveCampaignToRow(campaign: RemediationCampaign): Campaign {
  const scope = [
    campaign.product_id ?? "unknown",
    campaign.programming_language ?? "all",
    campaign.source_kind ?? "all",
  ].join(" / ");
  // Signal count = number of DISTINCT diagnostic signals triggering the campaign, i.e.
  // the count of signal_counts KEYS, not the sum of their occurrences. A single
  // key occurring 47× is "1 signal", not "47 signals".
  const distinctSignals = Object.keys(campaign.signal_counts).length;
  return {
    title: campaign.title,
    scope,
    priorityVariant: priorityToVariant(campaign.priority),
    score: `${campaign.priority} · ${campaign.priority_score}`,
    type: campaign.fault_domain,
    signals: `${distinctSignals} ${distinctSignals === 1 ? "signal" : "signals"}`,
    severityHint: campaign.severity_hint,
    blastRadiusSummary: campaign.blast_radius_summary,
    repos: campaign.repo_ids,
    evidence: campaign.evidence,
    live: campaign,
  };
}

interface CampaignDetail {
  cause: string;
  signals: [code: string, detail: string][];
  steps: string[];
  // Fallback focus/workflow targets used OFFLINE (when `live` is null). Live rows
  // override these with the campaign's own focus_target / workflow_target.
  focus: SectionKey;
  focusLabel: string;
  workflow: SectionKey;
  workflowLabel: string;
  workflowScope: string;
}

const CAMP_DETAIL: Record<FaultDomain, CampaignDetail> = {
  coverage: {
    cause: "No active healthy content service is serving this scope, so retrieval returns nothing.",
    signals: [
      ["coverage_gap", "2 repos with 0 indexed chunks"],
      ["mcp_unready", "readiness probe failing"],
    ],
    steps: [
      "Onboard the repository if it has never been ingested",
      "Run Validate-Only, confirm chunk output",
      "Publish an active snapshot",
    ],
    focus: "health",
    focusLabel: "Open coverage triage",
    workflow: "ingestion",
    workflowLabel: "Open ingestion workflow",
    workflowScope: "write:ingestion",
  },
  freshness: {
    cause: "The active published snapshot has aged past the freshness target for this scope.",
    signals: [
      ["stale_snapshot", "active snapshot age 45d (> 30d)"],
      ["drift_risk", "rising query volume"],
    ],
    steps: [
      "Reingest the source repository",
      "Publish a fresh snapshot",
      "Verify freshness cue returns to green",
    ],
    focus: "analytics",
    focusLabel: "Open freshness watchlist",
    workflow: "ingestion",
    workflowLabel: "Open ingestion workflow",
    workflowScope: "write:ingestion",
  },
  "zero-result": {
    cause: "A cluster of public queries returns no results due to scope/version mismatch.",
    signals: [
      ["zero_result", "11% of resolved queries"],
      ["scope_mismatch", "language resolves to fallback"],
    ],
    steps: [
      "Add a product alias so the language resolves",
      "Pin latest-stable version",
      "Re-run the failing query",
    ],
    focus: "analytics",
    focusLabel: "Open zero-result cockpit",
    workflow: "ingestion",
    workflowLabel: "Open ingestion workflow",
    workflowScope: "write:ingestion",
  },
  retrieval: {
    cause: "Retrieved content is present but low-confidence, hurting answer quality.",
    signals: [
      ["low_confidence", "below 0.35 threshold"],
      ["citation_loss", "missing source anchors"],
    ],
    steps: [
      "Re-parse with citation extraction",
      "Run a semantic quality review",
      "Tune the low-confidence threshold",
    ],
    focus: "analytics",
    focusLabel: "Open issue hotspots",
    workflow: "quality",
    workflowLabel: "Open quality review desk",
    workflowScope: "write:settings",
  },
  "repeated-issue": {
    cause: "The same complaint recurs for this scope, indicating an unresolved content defect.",
    signals: [
      ["repeated_issue", "4 reports in 24h"],
      ["wrong_api", "citation points at renamed member"],
    ],
    steps: [
      "Flag the document for a content fix",
      "Re-ingest after the source is corrected",
      "Confirm the issue stops recurring",
    ],
    focus: "analytics",
    focusLabel: "Open issue inbox",
    workflow: "ingestion",
    workflowLabel: "Open ingestion workflow",
    workflowScope: "write:ingestion",
  },
};

const INITIAL_VISIBLE = 6;

// Freshness badge anchor. OFFLINE the aggregation is anchored to this fixture
// instant (~24s in the past) so the header badge starts at
// "aggregated 24s ago" and then ticks up; ONLINE it anchors to the newest of the
// three contributing queries' dataUpdatedAt (last successful fetch), so it resets
// after every manual / 60s background refresh instead of asserting a fixed age.
const AGGREGATION_META = { generatedAt: Date.now() - 24_000 };

// "Xs ago" / "Xm ago" / "Xh ago" — mirrors the Indexes section's freshness label.
function agoLabel(fromMs: number, nowMs: number): string {
  const secs = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  if (secs < 90) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

// Outbound cross-section deep-links, keyed by fault domain — the OFFLINE
// fallback when a row has no live campaign (live rows use the campaign's OWN
// focus_target / workflow_target, see liveTargetToOutbound). Each row action
// navigates to the related section AND scrolls its named panel into view via
// navigate(key, anchor). `focus` = the SOURCE investigation panel (where the
// signal is observed); `workflow` = the REMEDIATION panel (where the operator
// acts). Anchors match the target sections' DOM ids — each label must point at
// the panel it names:
//   coverage       → coverage  #coverage-triage-panel
//   freshness      → analytics #analytics-freshness-watchlist-panel
//   zero-result    → analytics #analytics-zero-result-cockpit-panel
//   retrieval      → analytics #analytics-issue-hotspots-panel
//   repeated-issue → analytics #analytics-issue-inbox-panel
//   workflows      → ingestion #ingestion-run-single-panel · quality #quality-runs-panel
// navigate() no-ops the scroll if an id is absent, so every action stays
// clickable offline.
interface OutboundTarget {
  section: SectionKey;
  anchor: string;
}

// Placeholder scope tokens that liveCampaignToRow / the fixtures emit when a
// dimension is unscoped ("all") or unknown. They are not real filter values, so
// the prefill cascade drops them rather than handing a meaningless token to the
// target section's filter setters.
const SCOPE_PLACEHOLDERS = new Set(["all", "unknown", "*", ""]);

function scopeToken(value: string | null | undefined): string | null {
  const token = (value ?? "").trim();
  if (!token || SCOPE_PLACEHOLDERS.has(token.toLowerCase())) {
    return null;
  }
  return token;
}

// Build the cross-section prefill filters for a campaign's scope. Live rows read
// the campaign's structured product/language/source_kind; offline fixture rows
// parse the "product / language / source_kind" scope string. Only real (non
// placeholder) dimensions are included, so a target section never receives an
// "all"/"unknown" filter that would over-narrow its list.
function campaignScopeFilters(campaign: Campaign): Record<string, string> {
  const [product, language, sourceKind] = campaign.live
    ? [campaign.live.product_id, campaign.live.programming_language, campaign.live.source_kind]
    : campaign.scope.split("/").map((part) => part.trim());
  const filters: Record<string, string> = {};
  const productToken = scopeToken(product);
  const languageToken = scopeToken(language);
  const sourceKindToken = scopeToken(sourceKind);
  if (productToken) filters.product = productToken;
  if (languageToken) filters.language = languageToken;
  if (sourceKindToken) filters.source_kind = sourceKindToken;
  return filters;
}

// Resolve a campaign's product / sdk / kind triple for the expanded "Scope &
// blast radius" chip cluster (chips `product: X`, `sdk: Y`, `kind: Z`). Live rows
// read the campaign's structured dimensions (null → "unknown"/"all" defaults); offline fixture rows
// parse the "product / language / source_kind" scope string. This is presentation
// only and never drops a dimension, so it complements (does not replace) the row
// meta-line and the Affected-repositories list.
function campaignScopeChips(campaign: Campaign): { product: string; sdk: string; kind: string } {
  if (campaign.live) {
    return {
      product: campaign.live.product_id ?? "unknown",
      sdk: campaign.live.programming_language ?? "all",
      kind: campaign.live.source_kind ?? "all",
    };
  }
  const [product, language, sourceKind] = campaign.scope.split("/").map((part) => part.trim());
  return {
    product: product || "unknown",
    sdk: language || "all",
    kind: sourceKind || "all",
  };
}

const OUTBOUND: Record<FaultDomain, { focus: OutboundTarget; workflow: OutboundTarget }> = {
  // Coverage gap → triage the missing content, then run a single-repo ingest.
  coverage: {
    focus: { section: "coverage", anchor: "coverage-triage-panel" },
    workflow: { section: "ingestion", anchor: "ingestion-run-single-panel" },
  },
  // Stale snapshot → freshness watchlist, then reingest to refresh.
  freshness: {
    focus: { section: "analytics", anchor: "analytics-freshness-watchlist-panel" },
    workflow: { section: "ingestion", anchor: "ingestion-run-single-panel" },
  },
  // Zero-result cluster → analytics zero-result cockpit, then ingest the fix.
  "zero-result": {
    focus: { section: "analytics", anchor: "analytics-zero-result-cockpit-panel" },
    workflow: { section: "ingestion", anchor: "ingestion-run-single-panel" },
  },
  // Low-confidence retrieval → analytics issue hotspots, then a quality review run.
  retrieval: {
    focus: { section: "analytics", anchor: "analytics-issue-hotspots-panel" },
    workflow: { section: "quality", anchor: "quality-runs-panel" },
  },
  // Recurring complaint → analytics issue inbox, then reingest the corrected source.
  "repeated-issue": {
    focus: { section: "analytics", anchor: "analytics-issue-inbox-panel" },
    workflow: { section: "ingestion", anchor: "ingestion-run-single-panel" },
  },
};

// The hook's campaign targets carry the hook's own sidebar section/anchor
// ids. Map them onto this console's Mono section keys + panel ids so a live
// campaign's own focus_target / workflow_target drives navigation instead of
// being discarded for the per-domain fallback. Unknown sections fall back to
// the OUTBOUND entry; unmapped anchors pass through unchanged (the Mono
// Analytics panels share their ids with the hook's anchors).
const TARGET_SECTION_KEY: Partial<Record<RemediationCampaignTarget["sectionId"], SectionKey>> = {
  workspaces: "workspaces",
  health: "health",
  analytics: "analytics",
  "content-coverage": "coverage",
  "ingestion-jobs": "ingestion",
  "quality-reviews": "quality",
  "coverage-campaigns": "campaigns",
};

// Hook anchor ids whose Mono panel ids differ.
const TARGET_ANCHOR_REMAP: Record<string, string> = {
  "quality-reviews-runs-panel": "quality-runs-panel",
};

function liveTargetToOutbound(target: RemediationCampaignTarget): OutboundTarget | null {
  // The coverage-gap triage panel lives in the Mono COVERAGE section, not Health.
  if (target.anchorId === "health-coverage-gap-triage-panel") {
    return { section: "coverage", anchor: "coverage-triage-panel" };
  }
  const section = TARGET_SECTION_KEY[target.sectionId];
  if (!section) {
    return null;
  }
  return { section, anchor: TARGET_ANCHOR_REMAP[target.anchorId] ?? target.anchorId };
}

// Per-signal-key description for LIVE signal_counts rows (Signal
// Breakdown table, Description column). Keys follow the hook's generators:
//   content:<signal_type> · freshness:<risk_level> ·
//   zero:<zero_reason>:<fallback_reason> · issue:<issue_type>:<severity>
// Unknown shapes fall back to a generic occurrence description (the Signal cell
// always shows the bare key).
function describeSignal(key: string): string {
  const [group, ...rest] = key.split(":");
  if (group === "content" && rest.length > 0) {
    return `Content triage signal "${rest.join(":")}" observed on this scope's repositories.`;
  }
  if (group === "freshness" && rest.length > 0) {
    return `Freshness risk "${rest.join(":")}" from the analytics stale-snapshot watchlist.`;
  }
  if (group === "zero" && rest.length >= 2) {
    return `Zero-result cluster — reason "${rest[0]}", fallback "${rest.slice(1).join(":")}".`;
  }
  if (group === "issue" && rest.length >= 2) {
    return `Reported issue hotspot — type "${rest[0]}", severity "${rest.slice(1).join(":")}".`;
  }
  return "Diagnostic signal occurrences grouped into this campaign.";
}

// Severity hint → pill variant (text label always shown alongside, never colour
// alone, for accessibility).
function severityVariant(hint: string | null): StatusVariant {
  if (!hint) return "neutral";
  const value = hint.toLowerCase();
  if (value === "critical") return "crit";
  if (value === "warning") return "warn";
  return "info";
}

// ───────────────────────────────────────────────────────────── Campaign row ──

function CampaignRow({
  campaign,
  index,
  hidden,
  open,
  onToggle,
  can,
  readOnly,
  onFocusCampaign,
  onWorkflow,
}: {
  campaign: Campaign;
  index: number;
  hidden: boolean;
  open: boolean;
  onToggle: () => void;
  can: (scope: string) => boolean;
  readOnly: boolean;
  onFocusCampaign: (campaign: Campaign) => void;
  onWorkflow: (campaign: Campaign) => void;
}) {
  const d = CAMP_DETAIL[campaign.type];
  // The Evidence pack and Recommended next steps lists cap
  // their display at the first 4 items (evidence.slice(0,4) / next_steps.slice(0,4))
  // — no "see more". Live next_steps are already capped at 4 upstream by the hook,
  // but live evidence is not, so the slice guards a backend returning >4 lines and
  // keeps the offline fixtures bound to the same limit.
  const steps = (campaign.live ? campaign.live.next_steps : d.steps).slice(0, 4);
  const evidence = campaign.evidence.slice(0, 4);
  const scope = campaignScopeChips(campaign);
  // Live rows carry their own targets/labels; offline rows use the fault-domain
  // fallback so the actions resolve fully without a backend.
  const focusLabel = campaign.live?.focus_target.label ?? d.focusLabel;
  const workflowLabel = campaign.live?.workflow_target.label ?? d.workflowLabel;
  const workflowScope = campaign.live?.workflow_target.requiredScope ?? d.workflowScope;
  const workflowIsIngestion = workflowLabel.toLowerCase().includes("ingestion");
  // Scope-gate the workflow hand-off: disabled (with a hint) when the active key
  // lacks the write scope, or when the backend is read-only (navigation would
  // land on a mutation panel the operator cannot use). Stays enabled offline.
  const missingScope = workflowScope != null && !can(workflowScope);
  const workflowBlocked = missingScope || readOnly;
  const workflowTitle = missingScope
    ? `Requires scope: ${workflowScope}`
    : readOnly
      ? "Backend is read-only — remediation workflows are temporarily disabled"
      : undefined;

  const panelId = `campaign-detail-${index}`;
  const headerId = `campaign-header-${index}`;

  return (
    <>
      <button
        type="button"
        id={headerId}
        className="snap-row camp-row"
        aria-expanded={open}
        aria-controls={panelId}
        hidden={hidden}
        onClick={onToggle}
      >
        <div>
          <div className="snap-id" style={{ fontFamily: "var(--font-display)" }}>
            {campaign.title}
          </div>
          <div className="snap-meta mono">{campaign.scope}</div>
        </div>
        <div className="snap-right">
          <Pill variant={campaign.priorityVariant}>{campaign.score}</Pill>
          {campaign.severityHint && (
            <Pill variant={severityVariant(campaign.severityHint)}>{campaign.severityHint}</Pill>
          )}
          <Tag>{campaign.type}</Tag>
          <span className="muted-note">{campaign.signals}</span>
          <span className="camp-chev" style={{ transform: open ? "rotate(90deg)" : "none" }}>
            <Icon name="chevronR" className="chev" />
          </span>
        </div>
      </button>
      <div className="camp-detail" id={panelId} role="region" aria-labelledby={headerId} hidden={hidden || !open}>
        <div className="exp-panel" style={{ gridTemplateColumns: "1.2fr 1fr" }}>
          <div>
            <div className="eh">Root cause</div>
            {/* Live rows show the campaign's OWN summary first, then the generic
                fault-domain explanation; offline fixture rows keep the per-domain
                prose. */}
            <div className="why" style={{ marginBottom: campaign.live ? 4 : 10 }}>
              {campaign.live ? campaign.live.summary : d.cause}
            </div>
            {campaign.live && (
              <div className="why" style={{ marginBottom: 10 }}>
                {d.cause}
              </div>
            )}

            <div className="eh">Signal breakdown</div>
            {campaign.live ? (
              // Live: one row per signal_counts key — Signal / Count /
              // Description (Signal Breakdown table). The campaign's
              // ACTUAL signal keys and occurrence counts, never canned prose.
              <table className="tbl" style={{ marginBottom: 10 }}>
                <thead>
                  <tr>
                    <th scope="col">Signal</th>
                    <th scope="col">Count</th>
                    <th scope="col">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(campaign.live.signal_counts).map(([key, count]) => (
                    <tr className="data" key={key}>
                      <td>
                        <Tag>{key}</Tag>
                      </td>
                      <td>
                        <Pill variant={count > 0 ? "neutral" : "ok"}>{count}</Pill>
                      </td>
                      <td>{describeSignal(key)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="tbl" style={{ marginBottom: 10 }}>
                <thead>
                  <tr>
                    <th scope="col">Signal</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {d.signals.map(([code, detail]) => (
                    <tr className="data" key={code}>
                      <td>
                        <Tag>{code}</Tag>
                      </td>
                      <td>{detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="eh">Affected repositories</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
              {campaign.repos.length > 0 ? (
                campaign.repos.map((repo) => <Tag key={repo}>{repo}</Tag>)
              ) : (
                <span className="muted-note">No repositories — scope is query-derived, not repo-bound.</span>
              )}
            </div>

            <div className="eh">Evidence pack</div>
            <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
              {evidence.length > 0 ? (
                evidence.map((line) => (
                  <li key={line} className="kvline" style={{ lineHeight: 1.5 }}>
                    {line}
                  </li>
                ))
              ) : (
                <li className="muted-note">No supporting evidence captured for this campaign.</li>
              )}
            </ul>
          </div>
          <div>
            {/* Scope & blast radius: a labelled chip cluster naming the
                campaign's product / sdk / kind dimensions, above the blast-radius
                figure. Presentation only — the same dimensions still appear in the
                row meta-line and repos under "Affected repositories". */}
            <div className="eh">Scope &amp; blast radius</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              <Tag>product: {scope.product}</Tag>
              <Tag>sdk: {scope.sdk}</Tag>
              <Tag>kind: {scope.kind}</Tag>
            </div>
            <div className="kvline" style={{ marginBottom: campaign.live ? 4 : 10 }}>
              Blast radius: {campaign.blastRadiusSummary}
            </div>
            {/* Live-only diagnostic captions:
                conditional zero-result / fallback reasons. Offline fixtures carry
                the equivalents inside their evidence strings, so these render only
                for live rows that actually populate the fields. */}
            {campaign.live?.zero_result_reason && (
              <div className="muted-note" style={{ marginBottom: 4 }}>
                Zero-result reason: {campaign.live.zero_result_reason}
              </div>
            )}
            {campaign.live?.fallback_reason && (
              <div className="muted-note" style={{ marginBottom: 10 }}>
                Fallback reason: {campaign.live.fallback_reason}
              </div>
            )}
            {campaign.live &&
              !campaign.live.zero_result_reason &&
              !campaign.live.fallback_reason && <div style={{ marginBottom: 6 }} />}

            <div className="eh">Next steps</div>
            {/* Live rows list the campaign's OWN generated next_steps (already
                capped at 4 by the hook); offline rows keep the fixture steps. */}
            {steps.length > 0 ? (
              <ol className="fix-steps">
                {steps.map((s) => (
                  <li key={s}>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="muted-note">
                No generated next steps for this campaign — use the focus link below to investigate.
              </div>
            )}
            <div className="exp-actions">
              {/* (1) Focus campaign — jump to the analytics/health SOURCE panel
                  with the campaign scope pre-applied (live cascade via the hook). */}
              <Button
                variant="btn-primary"
                size="sm"
                icon="search"
                onClick={() => onFocusCampaign(campaign)}
                title="Open the source analytics/health panel with this campaign's scope pre-applied"
              >
                Focus campaign
              </Button>
              {/* (2) Fault-domain remediation workflow — ingestion (coverage /
                  freshness) or quality review desk (retrieval). Scope-gated. */}
              <Button
                variant="btn-ghost"
                size="sm"
                icon={workflowIsIngestion ? "upload" : "review"}
                disabled={workflowBlocked}
                title={workflowTitle}
                onClick={() => onWorkflow(campaign)}
              >
                {workflowLabel}
              </Button>
            </div>
            {/* (3) Jump to [focus target] — text deep-link to the named panel for
                deeper inspection without the full focus flow. */}
            <button
              type="button"
              className="more-link"
              style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 6 }}
              title={`Jump to ${focusLabel.toLowerCase()} and scroll it into view for deeper inspection`}
              onClick={() => onFocusCampaign(campaign)}
            >
              <Icon name="arrow" className="chev" />
              {focusLabel}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ───────────────────────────────────────────────────────────── Section body ──

const FAULT_DOMAIN_LABEL: Record<FaultDomain, string> = {
  coverage: "coverage",
  freshness: "freshness",
  "zero-result": "zero-result",
  retrieval: "retrieval",
  "repeated-issue": "repeated-issue",
};

// Stable display order for the fault-domain segmented filter.
const FAULT_DOMAIN_ORDER: FaultDomain[] = [
  "coverage",
  "freshness",
  "zero-result",
  "retrieval",
  "repeated-issue",
];

export function CampaignsSection() {
  const { navigate, consumeIntent, status } = useShell();
  const data = useAdminData();
  const [shownAll, setShownAll] = useState(false);
  // Display-side filters. These narrow the rendered campaign list CLIENT-SIDE in
  // BOTH modes so they respond offline (fixtures) and online (live) alike; the
  // product search ALSO drives the hook filter so live mode re-fetches scoped.
  const [domainFilter, setDomainFilter] = useState<FaultDomain | "all">("all");
  const [scopeQuery, setScopeQuery] = useState("");
  // Controlled expansion map so per-row toggles plus Expand-all / Collapse-all
  // all drive the same state (and work offline against the fixtures).
  const [openMap, setOpenMap] = useState<Record<string, boolean>>({});
  // 1s tick so the header freshness badge ("aggregated Xs ago") counts up in real
  // time rather than only updating on incidental re-renders (matches Indexes).
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  // Remediation campaigns from the analytics hook. We consume the campaign
  // aggregation + priority counters, the product filter setter (the scope search
  // drives it so live mode re-fetches scoped), and the focus/workflow cascade
  // callbacks (wired into the row actions). Its registry/triage inputs are
  // empty — see the API limitation note below.
  const noop = () => {};
  const h = useAnalyticsState({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "coverage-campaigns",
    // API limitation: this Mono section has no registry/content-services/triage hooks,
    // so these aggregation inputs are empty — live campaigns are built from the
    // hook's own freshness-watchlist, zero-result and issue-hotspot queries only.
    registryLanguageOptions: [],
    registryLocaleOptions: [],
    contentServicesRows: [],
    contentTriageData: null,
    showAlert: data.showAlert,
    // Cross-section navigation cascade: the hook's focus/workflow callbacks call
    // these to pre-apply the campaign scope downstream + scroll the target panel
    // into view. The Mono shell owns section switching (useShell.navigate); the
    // hook-side filter/scroll cascade is a no-op here because target-section
    // filter state + DOM anchors live in those sections, not this one. The Mono
    // row actions additionally call navigate(...) so the section switch happens.
    openSection: noop,
    jumpToElement: noop,
    setSelectedProductId: noop,
    setQualityRunVersion: noop,
    setQualitySourceRevision: noop,
    setSelectedQualityRunId: noop,
    setSelectedQualityRunIds: noop,
  });

  // Campaigns aggregate three contributing queries; treat them collectively for
  // loading/error so the online states stay reachable.
  // Labeled so the partial-failure notice can name WHICH contributing source
  // failed (the "Error (partial failure)" notice explains which data
  // source failed). Order is purely for the readable failed-source list.
  const campSources = [
    { label: "freshness watchlist", query: h.freshnessWatchlistQuery },
    { label: "zero-result overview", query: h.zeroResultOverviewQuery },
    { label: "issue hotspots", query: h.issueHotspotsQuery },
  ];
  const campQueries = campSources.map((s) => s.query);
  const liveCampaigns = h.remediationCampaigns;
  // Live vs fixture: OFFLINE (no admin session → queries disabled) the fixtures
  // are the full interactive dataset. ONLINE the display source is live data
  // ONLY, so an empty or failed backend renders the empty/error states
  // below instead of silently substituting the 12 demo campaigns.
  const online = data.sessionIsSuccess;
  const source: Campaign[] = online ? liveCampaigns.map(liveCampaignToRow) : CAMP;
  const refetchCampaigns = () => {
    void h.freshnessWatchlistQuery.refetch();
    void h.zeroResultOverviewQuery.refetch();
    void h.issueHotspotsQuery.refetch();
  };

  // Freshness badge label: ONLINE anchor to the newest successful fetch across the
  // three contributing queries (resets after every manual / 60s refresh); OFFLINE
  // anchor to the fixture instant so it starts at "24s ago" and
  // ticks.
  const lastAggregatedMs = online
    ? Math.max(0, ...campQueries.map((qr) => qr.dataUpdatedAt))
    : AGGREGATION_META.generatedAt;
  const aggregatedLabel =
    online && lastAggregatedMs === 0
      ? "awaiting first aggregation"
      : `aggregated ${agoLabel(lastAggregatedMs, nowMs)}`;

  // Read-only awareness ("Degraded — read-only backend"): when the shell
  // reports a degraded/major status the backend is treated as read-only —
  // campaigns still render (reads allowed) but the remediation-workflow buttons
  // disable with a tooltip. Offline the shell status defaults to "operational",
  // so workflow buttons stay enabled (an operator can flip the topbar status
  // chip to see the read-only state).
  const readOnly = status === "degraded" || status === "major";

  // Bridge a row's nav actions onto the hook's cascade AND the Mono shell's
  // cross-section deep-link. LIVE rows navigate to the campaign's OWN
  // focus_target / workflow_target (section + anchor remapped to Mono ids via
  // liveTargetToOutbound) so the deep-link always matches the action's label;
  // offline rows use the per-fault-domain OUTBOUND fallback. Live rows ALSO fire
  // the hook cascade first (scope pre-apply downstream). In either mode
  // navigate(section, anchor) switches the section and scrolls the named panel
  // into view (a no-op scroll if the id is not present yet).
  function focusCampaign(campaign: Campaign) {
    if (campaign.live) {
      h.focusRemediationCampaign(campaign.live);
    }
    const target =
      (campaign.live ? liveTargetToOutbound(campaign.live.focus_target) : null) ??
      OUTBOUND[campaign.type].focus;
    // Hand the campaign's scope to the target section as a one-shot prefill so the
    // Focus cascade actually narrows the destination (not just a section switch
    // + scroll). `reset` clears the target's current filters first.
    navigate(target.section, target.anchor, {
      filters: campaignScopeFilters(campaign),
      reset: true,
    });
  }
  function openWorkflow(campaign: Campaign) {
    if (campaign.live) {
      h.openRemediationCampaignWorkflow(campaign.live);
    }
    const target =
      (campaign.live ? liveTargetToOutbound(campaign.live.workflow_target) : null) ??
      OUTBOUND[campaign.type].workflow;
    // Same scope hand-off for the remediation-workflow target (ingestion / quality).
    navigate(target.section, target.anchor, {
      filters: campaignScopeFilters(campaign),
      reset: true,
    });
  }

  // Segmented domain options derived from the domains present in the SOURCE, so
  // the control is coherent both offline (5 fixture domains) and online (the 3
  // live fault domains) without ever offering an empty bucket.
  const presentDomains = FAULT_DOMAIN_ORDER.filter((d) => source.some((c) => c.type === d));
  const domainTabs = ["all", ...presentDomains];
  const domainTabLabels = ["all", ...presentDomains.map((d) => FAULT_DOMAIN_LABEL[d])];
  const activeDomainTab = domainFilter === "all" ? 0 : Math.max(0, domainTabs.indexOf(domainFilter));

  // Apply the SAME predicate to the display source in both modes. For live rows
  // (already server-scoped by product) the scope predicate is idempotent; the
  // domain predicate is a pure client-side display filter (the hook has no
  // fault-domain filter param — it derives the domain from signals).
  const q = scopeQuery.trim().toLowerCase();
  const shown = source.filter((c) => {
    if (domainFilter !== "all" && c.type !== domainFilter) return false;
    if (q && !(`${c.title} ${c.scope}`.toLowerCase().includes(q))) return false;
    return true;
  });
  const filtered = domainFilter !== "all" || q.length > 0;

  // State gates: offline (`online` false) they are ALL false, so the fixtures
  // render untouched; online they reflect the real queries.
  const anyCampLoading = campQueries.some((qr) => qr.isLoading);
  const anyCampError = campQueries.some((qr) => qr.isError);
  // Human-readable list of the failed contributing sources, for the partial-failure
  // notice (names which data source failed). e.g. "freshness watchlist" or
  // "zero-result overview and issue hotspots".
  const failedSourceNames = campSources.filter((s) => s.query.isError).map((s) => s.label);
  const failedSourcesText =
    failedSourceNames.length <= 1
      ? failedSourceNames[0] ?? ""
      : `${failedSourceNames.slice(0, -1).join(", ")} and ${
          failedSourceNames[failedSourceNames.length - 1]
        }`;
  // Initial online aggregation with nothing rendered yet → skeletons.
  const loading = online && anyCampLoading && !source.length;
  // Every contributing source failed (nothing aggregated) → error state.
  const errored = online && anyCampError && !source.length;
  // Partial failure: a source failed but others produced campaigns →
  // "Error (partial failure)" notice over the surviving list.
  const partialError = online && anyCampError && source.length > 0;
  // Live success with zero campaigns → the success-empty state;
  // fixtures never substitute online (offline this stays false).
  const liveEmpty =
    online && campQueries.every((qr) => qr.isSuccess) && liveCampaigns.length === 0;
  // The partial-failure notice is dismissible;
  // re-arm it once the failing source recovers.
  const [partialDismissed, setPartialDismissed] = useState(false);
  useEffect(() => {
    if (!anyCampError) {
      setPartialDismissed(false);
    }
  }, [anyCampError]);

  // Inbound cross-section prefill: drain any one-shot SectionIntent stashed for
  // this section (e.g. a sibling section handing off a campaign scope) and apply
  // it through THIS section's existing filter setters. consumeIntent is one-shot
  // and the empty dep array keeps this mount-only, so the prefill never re-applies
  // on re-render. Unknown filter keys (anything but product/language/source_kind)
  // are ignored gracefully; the scope search is the section's product/scope lever,
  // so product (falling back to source_kind) seeds it and drives the hook filter.
  useEffect(() => {
    const intent = consumeIntent("campaigns");
    if (!intent?.filters) return;
    const f = intent.filters;
    // reset:true clears the section's current filters before applying incoming ones.
    if (intent.reset) {
      setDomainFilter("all");
      setScopeQuery("");
      setShownAll(false);
      h.setAnalyticsProductFilter("");
    }
    // product/source_kind -> the product/scope search (matches title + scope text,
    // and drives the hook filter so live mode re-fetches scoped). language alone
    // is accepted but only narrows when it appears in the scope string.
    const scope = f.product ?? f.source_kind ?? f.language;
    if (scope != null && scope !== "" && scope.toLowerCase() !== "all") {
      setScopeQuery(scope);
      setShownAll(false);
      h.setAnalyticsProductFilter(scope.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setOpenAll = (value: boolean) => {
    setShownAll(true);
    setOpenMap(Object.fromEntries(shown.map((c, i) => [`${c.title}-${i}`, value])));
  };

  const visibleCount = filtered || shownAll ? shown.length : Math.min(INITIAL_VISIBLE, shown.length);
  const hiddenCount = filtered ? 0 : shown.length - visibleCount;

  function renderBody(): ReactNode {
    if (loading) {
      return <Skeleton rows={6} />;
    }
    if (errored) {
      return (
        <ErrorState
          title="Campaigns unavailable"
          text="The campaign aggregation sources failed to load, so no campaigns can be shown. The list will refresh automatically in 60s."
          cause="analytics_aggregation_timeout"
          actions={
            <>
              <Button variant="btn-primary" size="sm" icon="refresh" onClick={refetchCampaigns}>
                Retry now
              </Button>
              <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
                Open Logs
              </Button>
            </>
          }
        />
      );
    }
    if (liveEmpty) {
      return (
        <EmptyState
          title="No remediation campaigns"
          text="No campaigns were created for the current analytics filters. Clear filters or widen the scope to see global campaigns — or this scope simply has no outstanding remediation work."
          action={
            <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => navigate("analytics")}>
              Review analytics filters
            </Button>
          }
        />
      );
    }
    // Filtered-empty: the source has campaigns but the local filters exclude them
    // all. Offer an in-place reset (mirror Coverage) instead of hiding everything.
    if (!shown.length) {
      return (
        <EmptyState
          title="No campaigns match the current filters"
          text="No remediation campaigns match the selected fault domain or scope search. Reset the filters to see the full list."
          action={
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              onClick={() => {
                setDomainFilter("all");
                setScopeQuery("");
                h.setAnalyticsProductFilter("");
              }}
            >
              Clear filters
            </Button>
          }
        />
      );
    }

    // Happy path: filtered display list (live, or fixtures when offline).
    return (
      <>
        {shown.map((c, i) => {
          const key = `${c.title}-${i}`;
          return (
            <CampaignRow
              key={key}
              campaign={c}
              index={i}
              hidden={!filtered && i >= INITIAL_VISIBLE && !shownAll}
              open={openMap[key] ?? false}
              onToggle={() => setOpenMap((m) => ({ ...m, [key]: !m[key] }))}
              can={data.can}
              readOnly={readOnly}
              onFocusCampaign={focusCampaign}
              onWorkflow={openWorkflow}
            />
          );
        })}
        {!shownAll && hiddenCount > 0 && (
          <div className="more-wrap">
            <button
              type="button"
              className="more-link"
              aria-label={`Show ${hiddenCount} more campaigns`}
              onClick={() => setShownAll(true)}
            >
              Show {hiddenCount} more campaigns →
            </button>
          </div>
        )}
      </>
    );
  }

  const showSummary = !loading && !errored;
  const total = shown.length;
  // Accurate filter suffix: only the fault-domain segmented control narrows by
  // "signal type". When just the free-text scope search is active, say so instead
  // of mislabelling it a signal-type filter. Unfiltered keeps the default copy
  // "grouped by signal type".
  const domainActive = domainFilter !== "all";
  const filterSuffix = domainActive
    ? q.length > 0
      ? "filtered by signal type and scope"
      : "filtered by signal type"
    : q.length > 0
      ? "filtered by scope"
      : "grouped by signal type";
  const cardSub = !loading && !errored && !liveEmpty
    ? filtered
      ? `Showing ${total} of ${source.length} · ${filterSuffix}`
      : shownAll
        ? `Showing ${total} of ${total} · grouped by signal type`
        : `Showing ${Math.min(INITIAL_VISIBLE, total)} of ${total} · grouped by signal type`
    : "Grouped by signal type";

  // Priority counters: live online (zeros included — the strip keeps
  // rendering with 0 values when empty); fixture demo values offline only.
  const counters = online
    ? h.remediationCampaignPriorityCounters
    : { highest: 6, high: 0, medium: 12, low: 1 };

  // Conditional summary-banner severity (error if
  // highest>0, warning if high>0, info otherwise) so the standing banner escalates
  // its colour to the worst priority present instead of being a fixed 'warn'. The
  // Mono Banner palette has no dedicated 'error' tier, so error/warning
  // both map to the kit's `warn` (the highest available urgency), with the `info`
  // tier reserved for the no-urgent-work case; the icon escalates to `alert` for
  // either urgent tier and stays `info` otherwise.
  const summaryUrgent = counters.highest > 0 || counters.high > 0;
  const summaryVariant: "warn" | "info" = summaryUrgent ? "warn" : "info";
  const summaryIcon: "alert" | "info" = summaryUrgent ? "alert" : "info";

  return (
    <>
      <PageHead
        title="Coverage Campaigns"
        sub="Coverage, freshness, zero-result and repeated-issue signals grouped into explainable remediation campaigns instead of isolated counters."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            {showSummary && <StaleBadge>{aggregatedLabel}</StaleBadge>}
            <Button variant="btn-primary" size="sm" icon="refresh" onClick={refetchCampaigns}>
              Refresh now
            </Button>
          </>
        }
      />

      {/* Degraded / read-only backend: campaigns still render;
          remediation-workflow buttons disable with a tooltip (handled per-row). */}
      {readOnly && showSummary && <ReadonlyBanner />}

      {showSummary && (
        <KpiRow cols={4}>
          <Kpi
            label="Highest priority"
            value={String(counters.highest)}
            foot="act now"
            accent
            pill={{ variant: "crit", text: "highest" }}
          />
          <Kpi label="High priority" value={String(counters.high)} foot="prepare this cycle" />
          <Kpi label="Medium priority" value={String(counters.medium)} foot="plan after urgent" />
          <Kpi label="Low priority" value={String(counters.low)} foot="track only" />
        </KpiRow>
      )}

      {/* "Error (partial failure)" state: a contributing source failed
          but surviving campaigns still render — dismissible notice + retry. */}
      {showSummary && partialError && !partialDismissed && (
        <Banner
          variant="warn"
          icon="alert"
          title={
            failedSourceNames.length > 1
              ? `Campaigns incomplete — ${failedSourceNames.length} backend sources failed`
              : "Campaigns incomplete — one backend source failed"
          }
          text={`The ${failedSourcesText} source${
            failedSourceNames.length > 1 ? "s" : ""
          } failed, so its campaigns are omitted; other sources still rendered. The list will refresh automatically in 60s.`}
          actions={
            <>
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={refetchCampaigns}>
                Retry now
              </Button>
              <Button variant="btn-ghost" size="sm" onClick={() => setPartialDismissed(true)}>
                Dismiss
              </Button>
            </>
          }
        />
      )}

      {/* Standing guidance explainer. Suppressed while the partial-failure notice
          above is showing, so the operator sees one coherent message — the
          "Error (partial failure)" state is a single dismissible
          notification. It returns once that notice is dismissed or the failing
          source recovers; the campaign count is still carried by the KPI row and
          the card sub-header meanwhile. */}
      {showSummary && !liveEmpty && !(partialError && !partialDismissed) && (
        <Banner
          variant={summaryVariant}
          icon={summaryIcon}
          guidance
          title={`${source.length} remediation campaigns planned`}
          text="Priority is stable by score, then blast radius, then campaign id. Expand a campaign for root cause, evidence, and next steps."
        />
      )}

      {showSummary && !liveEmpty && (
        <div className="toolbar">
          <Segmented
            options={domainTabLabels}
            active={activeDomainTab}
            ariaLabel="Filter campaigns by fault domain"
            onChange={(i) => {
              setDomainFilter(i === 0 ? "all" : (domainTabs[i] as FaultDomain));
              setShownAll(false);
            }}
          />
          <Input
            width={210}
            placeholder="Filter by product or scope…"
            value={scopeQuery}
            aria-label="Filter campaigns by product or scope"
            onChange={(e) => {
              const next = e.target.value;
              setScopeQuery(next);
              setShownAll(false);
              // Drive the hook filter too so live mode re-fetches scoped; offline
              // this is a harmless no-op (queries are disabled) and the client-side
              // predicate above still narrows the fixtures.
              h.setAnalyticsProductFilter(next.trim());
            }}
          />
          <div className="toolbar-right">
            <Button
              variant="btn-ghost"
              size="sm"
              title="Expand all campaign cards to show full details: signal breakdown, evidence, root cause, and recommended next steps."
              onClick={() => setOpenAll(true)}
            >
              Expand all
            </Button>
            <Button
              variant="btn-ghost"
              size="sm"
              title="Collapse all campaign cards to compact headers for a quick priority overview."
              onClick={() => setOpenMap({})}
            >
              Collapse all
            </Button>
          </div>
        </div>
      )}

      <Card title="Remediation campaigns" sub={cardSub} flush>
        {renderBody()}
      </Card>
    </>
  );
}
