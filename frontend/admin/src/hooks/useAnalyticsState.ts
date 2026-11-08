"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId, AnalyticsSavedView } from "@/components/admin-console.types";
import { ANALYTICS_VIEWS_STORAGE_KEY } from "@/components/admin-console.types";
import {
  uniqueSorted,
  downloadCsv,
  buildAnalyticsSlicesCsv,
  buildIssueHotspotsCsv,
} from "@/components/admin-console.utils";
import type {
  RemediationCampaign,
  RemediationCampaignFaultDomain,
  RemediationCampaignPriority,
  RemediationCampaignTarget,
} from "@/components/admin-console.types";
import type { GuidedContentFixDraft } from "@/lib/admin-api";
import {
  fetchAnalyticsSlices,
  fetchZeroResultOverview,
  fetchCapacityForecast,
  fetchPublicAdoptionFunnel,
  fetchFreshnessWatchlist,
  fetchUsefulnessSummary,
  fetchUsefulnessSignals,
  fetchIssueReviewSummary,
  fetchIssueReviewSignals,
  fetchRequestEvidence,
  fetchIssueHotspots,
  createGuidedContentFixDraft,
} from "@/lib/admin-api";
import { scoreToRemediationCampaignPriority } from "@/components/admin-console.utils";

export type UseAnalyticsStateArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  registryLanguageOptions: string[];
  registryLocaleOptions: string[];
  contentServicesRows: { product_id: string; source_kind: string }[];
  contentTriageData: { items?: Array<{
    signal_type: string;
    product_id: string;
    source_kind: string;
    repo_id: string;
    severity: string;
    stale_days?: number | null;
    indexed_chunks_count: number;
    executable_snippets_count: number;
    mcp_ready: boolean;
    service_status: string;
    service_status_reason: string;
    fix_plan: string[];
    summary: string;
  }> } | null;
  showAlert: (message: string, title?: string) => void;
  openSection: (
    sectionId: SidebarSectionId,
    options?: { clearWorkspace?: boolean; focusMain?: boolean; scrollTo?: string },
  ) => void;
  jumpToElement: (elementId: string) => void;
  setSelectedProductId: (productId: string) => void;
  setQualityRunVersion: (version: string) => void;
  setQualitySourceRevision: (revision: string) => void;
  setSelectedQualityRunId: (runId: string) => void;
  setSelectedQualityRunIds: (runIds: string[]) => void;
};

export function useAnalyticsState(args: UseAnalyticsStateArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    registryLanguageOptions,
    registryLocaleOptions,
    contentServicesRows,
    contentTriageData,
    showAlert,
    openSection,
    jumpToElement,
    setSelectedProductId,
    setQualityRunVersion,
    setQualitySourceRevision,
    setSelectedQualityRunId,
    setSelectedQualityRunIds,
  } = args;

  const queryClient = useQueryClient();
  const isAnalyticsActive = activeSectionId === "analytics";

  // --- Filter state ---
  const [analyticsProductFilter, setAnalyticsProductFilter] = useState("");
  const [analyticsLanguageFilter, setAnalyticsLanguageFilter] = useState("");
  const [analyticsLocaleFilter, setAnalyticsLocaleFilter] = useState("");
  const [analyticsClientFilter, setAnalyticsClientFilter] = useState("");
  const [analyticsSourceKindFilter, setAnalyticsSourceKindFilter] = useState("");
  const [analyticsOutcomeFilter, setAnalyticsOutcomeFilter] = useState("");
  const [analyticsRetrievalModeFilter, setAnalyticsRetrievalModeFilter] = useState("");
  const [analyticsZeroResultReasonFilter, setAnalyticsZeroResultReasonFilter] = useState("");
  const [analyticsFallbackReasonFilter, setAnalyticsFallbackReasonFilter] = useState("");
  const [analyticsWarningCodeFilter, setAnalyticsWarningCodeFilter] = useState("");
  const [analyticsIssueTypeFilter, setAnalyticsIssueTypeFilter] = useState("");
  const [analyticsIssueSeverityFilter, setAnalyticsIssueSeverityFilter] = useState("");
  const [analyticsIpHashFilter, setAnalyticsIpHashFilter] = useState("");
  const [analyticsFingerprintFilter, setAnalyticsFingerprintFilter] = useState("");

  // --- Issue evidence ---
  const [selectedIssueEvidenceRequestId, setSelectedIssueEvidenceRequestId] = useState("");
  const [copiedIssueEvidenceRequestId, setCopiedIssueEvidenceRequestId] = useState<string | null>(null);
  const [latestGuidedFixDraft, setLatestGuidedFixDraft] = useState<GuidedContentFixDraft | null>(null);

  // --- Saved views ---
  const [analyticsViewName, setAnalyticsViewName] = useState("");
  const [savedAnalyticsViews, setSavedAnalyticsViews] = useState<AnalyticsSavedView[]>([]);

  // Load saved views from localStorage
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(ANALYTICS_VIEWS_STORAGE_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw) as AnalyticsSavedView[];
      if (Array.isArray(parsed)) {
        setSavedAnalyticsViews(parsed);
      }
    } catch {
      setSavedAnalyticsViews([]);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      ANALYTICS_VIEWS_STORAGE_KEY,
      JSON.stringify(savedAnalyticsViews),
    );
  }, [savedAnalyticsViews]);

  // --- Queries ---
  const analyticsSliceQuery = useQuery({
    queryKey: [
      "admin-analytics-slices",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsOutcomeFilter,
      analyticsRetrievalModeFilter,
      analyticsZeroResultReasonFilter,
      analyticsFallbackReasonFilter,
      analyticsWarningCodeFilter,
      analyticsIpHashFilter,
      analyticsFingerprintFilter,
    ],
    queryFn: () =>
      fetchAnalyticsSlices(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        outcome: analyticsOutcomeFilter || undefined,
        retrieval_mode: analyticsRetrievalModeFilter || undefined,
        zero_result_reason: analyticsZeroResultReasonFilter || undefined,
        fallback_reason: analyticsFallbackReasonFilter || undefined,
        warning_code: analyticsWarningCodeFilter || undefined,
        hashed_ip: analyticsIpHashFilter || undefined,
        fingerprint: analyticsFingerprintFilter || undefined,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const zeroResultOverviewQuery = useQuery({
    queryKey: [
      "admin-analytics-zero-results",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsOutcomeFilter,
      analyticsRetrievalModeFilter,
      analyticsZeroResultReasonFilter,
      analyticsFallbackReasonFilter,
      analyticsWarningCodeFilter,
      analyticsIpHashFilter,
      analyticsFingerprintFilter,
    ],
    queryFn: () =>
      fetchZeroResultOverview(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        outcome: analyticsOutcomeFilter || undefined,
        retrieval_mode: analyticsRetrievalModeFilter || undefined,
        zero_result_reason: analyticsZeroResultReasonFilter || undefined,
        fallback_reason: analyticsFallbackReasonFilter || undefined,
        warning_code: analyticsWarningCodeFilter || undefined,
        hashed_ip: analyticsIpHashFilter || undefined,
        fingerprint: analyticsFingerprintFilter || undefined,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const capacityForecastQuery = useQuery({
    queryKey: [
      "admin-analytics-capacity-forecast",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsOutcomeFilter,
      analyticsRetrievalModeFilter,
      analyticsZeroResultReasonFilter,
      analyticsFallbackReasonFilter,
      analyticsWarningCodeFilter,
      analyticsIpHashFilter,
      analyticsFingerprintFilter,
    ],
    queryFn: () =>
      fetchCapacityForecast(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        outcome: analyticsOutcomeFilter || undefined,
        retrieval_mode: analyticsRetrievalModeFilter || undefined,
        zero_result_reason: analyticsZeroResultReasonFilter || undefined,
        fallback_reason: analyticsFallbackReasonFilter || undefined,
        warning_code: analyticsWarningCodeFilter || undefined,
        hashed_ip: analyticsIpHashFilter || undefined,
        fingerprint: analyticsFingerprintFilter || undefined,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const publicAdoptionFunnelQuery = useQuery({
    queryKey: [
      "admin-analytics-public-funnel",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsClientFilter,
    ],
    queryFn: () =>
      fetchPublicAdoptionFunnel(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        client_id: analyticsClientFilter || undefined,
        limit: 12,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const freshnessWatchlistQuery = useQuery({
    queryKey: [
      "admin-analytics-freshness-watchlist",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsSourceKindFilter,
    ],
    queryFn: () =>
      fetchFreshnessWatchlist(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        source_kind: analyticsSourceKindFilter || undefined,
        stale_after_days: 30,
        issue_window_days: 30,
        limit: 12,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const usefulnessSummaryQuery = useQuery({
    queryKey: [
      "admin-analytics-usefulness",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
    ],
    queryFn: () =>
      fetchUsefulnessSummary(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        tool: "query_docs",
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const usefulnessSignalsQuery = useQuery({
    queryKey: [
      "admin-analytics-usefulness-signals",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
    ],
    queryFn: () =>
      fetchUsefulnessSignals(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        tool: "query_docs",
        negative_only: true,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const issueReviewSummaryQuery = useQuery({
    queryKey: [
      "admin-analytics-issues",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsIssueTypeFilter,
      analyticsIssueSeverityFilter,
    ],
    queryFn: () =>
      fetchIssueReviewSummary(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        tool: "query_docs",
        issue_type: analyticsIssueTypeFilter || undefined,
        severity: analyticsIssueSeverityFilter || undefined,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const issueReviewSignalsQuery = useQuery({
    queryKey: [
      "admin-analytics-issue-signals",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsIssueTypeFilter,
      analyticsIssueSeverityFilter,
    ],
    queryFn: () =>
      fetchIssueReviewSignals(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        tool: "query_docs",
        issue_type: analyticsIssueTypeFilter || undefined,
        severity: analyticsIssueSeverityFilter || undefined,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const requestEvidenceQuery = useQuery({
    queryKey: ["admin-analytics-request-evidence", apiKey, selectedIssueEvidenceRequestId],
    queryFn: () =>
      fetchRequestEvidence(apiKey, {
        request_id: selectedIssueEvidenceRequestId,
      }),
    enabled: sessionIsSuccess && selectedIssueEvidenceRequestId.trim().length > 0,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const issueHotspotsQuery = useQuery({
    queryKey: [
      "admin-analytics-issue-hotspots",
      apiKey,
      analyticsProductFilter,
      analyticsLanguageFilter,
      analyticsLocaleFilter,
      analyticsIssueTypeFilter,
      analyticsIssueSeverityFilter,
    ],
    queryFn: () =>
      fetchIssueHotspots(apiKey, {
        product_id: analyticsProductFilter || undefined,
        programming_language: analyticsLanguageFilter || undefined,
        doc_locale: analyticsLocaleFilter || undefined,
        tool: "query_docs",
        issue_type: analyticsIssueTypeFilter || undefined,
        severity: analyticsIssueSeverityFilter || undefined,
        limit: 12,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isAnalyticsActive ? 60_000 : false,
  });

  const createGuidedContentFixDraftMutation = useMutation({
    mutationFn: ({ requestId, issueId }: { requestId: string; issueId?: string }) =>
      createGuidedContentFixDraft(apiKey, {
        request_id: requestId,
        issue_id: issueId,
      }),
    onSuccess: async (draft) => {
      setLatestGuidedFixDraft(draft);
      setSelectedProductId(draft.product_id);
      setQualityRunVersion(draft.quality_review_run.version ?? "latest");
      setQualitySourceRevision(draft.source_revision);
      setSelectedQualityRunId(draft.quality_review_run.run_id);
      setSelectedQualityRunIds([draft.quality_review_run.run_id]);
      openSection("quality-reviews");
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, draft.product_id] });
    },
  });

  // --- Option lists ---
  const analyticsLanguageOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_programming_language ?? {}),
    ...registryLanguageOptions,
  ]);
  const analyticsLocaleOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_doc_locale ?? {}),
    ...registryLocaleOptions,
  ]);
  const analyticsClientOptions = uniqueSorted([
    "cursor",
    "claude-desktop",
    "qwen-code",
    "vscode",
    ...Object.keys(publicAdoptionFunnelQuery.data?.by_client_id ?? {}),
  ]);
  const analyticsSourceKindOptions = uniqueSorted([
    ...Object.keys(freshnessWatchlistQuery.data?.by_source_kind ?? {}),
    ...contentServicesRows.map((service) => service.source_kind),
  ]);
  const analyticsOutcomeOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_outcome ?? {}),
  ]);
  const analyticsRetrievalModeOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_retrieval_mode ?? {}),
  ]);
  const analyticsZeroResultReasonOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_zero_result_reason ?? {}),
  ]);
  const analyticsFallbackReasonOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_fallback_reason ?? {}),
  ]);
  const analyticsWarningCodeOptions = uniqueSorted([
    ...Object.keys(analyticsSliceQuery.data?.by_warning_code ?? {}),
  ]);
  const analyticsIssueTypeOptions = uniqueSorted([
    "missing_docs",
    "wrong_docs",
    "outdated_docs",
    "bad_example",
    "other",
    ...Object.keys(issueReviewSummaryQuery.data?.by_issue_type ?? {}),
  ]);
  const analyticsIssueSeverityOptions = uniqueSorted([
    "critical",
    "warning",
    "info",
    ...Object.keys(issueReviewSummaryQuery.data?.by_severity ?? {}),
  ]);

  // --- Remediation campaigns ---
  const remediationCampaigns = useMemo(() => {
    type CampaignAccumulator = Omit<
      RemediationCampaign,
      "priority" | "blast_radius_summary" | "evidence" | "next_steps" | "signal_counts"
    > & {
      evidence: Set<string>;
      next_steps: Set<string>;
      signal_counts: Map<string, number>;
    };

    const campaigns = new Map<string, CampaignAccumulator>();

    function ensureCampaign(cArgs: {
      campaignId: string;
      title: string;
      summary: string;
      productId: string | null;
      programmingLanguage: string | null;
      sourceKind: string | null;
      repoIds: string[];
      faultDomain: RemediationCampaignFaultDomain;
      priorityScore: number;
      blastRadius: number;
      focusTarget: RemediationCampaignTarget;
      workflowTarget: RemediationCampaignTarget;
      severityHint?: string | null;
      zeroResultReason?: string | null;
      fallbackReason?: string | null;
      evidence: string[];
      nextSteps: string[];
      signalKey: string;
    }) {
      const existing = campaigns.get(cArgs.campaignId);
      if (!existing) {
        campaigns.set(cArgs.campaignId, {
          campaign_id: cArgs.campaignId,
          title: cArgs.title,
          summary: cArgs.summary,
          product_id: cArgs.productId,
          programming_language: cArgs.programmingLanguage,
          source_kind: cArgs.sourceKind,
          repo_ids: uniqueSorted(cArgs.repoIds),
          fault_domain: cArgs.faultDomain,
          priority_score: cArgs.priorityScore,
          blast_radius: cArgs.blastRadius,
          evidence: new Set(cArgs.evidence.filter(Boolean)),
          next_steps: new Set(cArgs.nextSteps.filter(Boolean).slice(0, 5)),
          signal_counts: new Map([[cArgs.signalKey, 1]]),
          focus_target: cArgs.focusTarget,
          workflow_target: cArgs.workflowTarget,
          severity_hint: cArgs.severityHint ?? null,
          zero_result_reason: cArgs.zeroResultReason ?? null,
          fallback_reason: cArgs.fallbackReason ?? null,
        });
        return;
      }
      existing.priority_score += cArgs.priorityScore;
      existing.blast_radius += cArgs.blastRadius;
      existing.repo_ids = uniqueSorted([...existing.repo_ids, ...cArgs.repoIds]);
      for (const evidence of cArgs.evidence) {
        if (evidence) {
          existing.evidence.add(evidence);
        }
      }
      for (const step of cArgs.nextSteps.slice(0, 5)) {
        if (step) {
          existing.next_steps.add(step);
        }
      }
      existing.signal_counts.set(cArgs.signalKey, (existing.signal_counts.get(cArgs.signalKey) ?? 0) + 1);
      if (!existing.severity_hint && cArgs.severityHint) {
        existing.severity_hint = cArgs.severityHint;
      }
      if (!existing.zero_result_reason && cArgs.zeroResultReason) {
        existing.zero_result_reason = cArgs.zeroResultReason;
      }
      if (!existing.fallback_reason && cArgs.fallbackReason) {
        existing.fallback_reason = cArgs.fallbackReason;
      }
    }

    for (const item of contentTriageData?.items ?? []) {
      const faultDomain: RemediationCampaignFaultDomain =
        item.signal_type === "stale_snapshot" ? "freshness" : "coverage";
      const productId = item.product_id || null;
      const sourceKind = item.source_kind || null;
      const campaignId = [faultDomain, productId ?? "unknown", sourceKind ?? "unknown", item.repo_id].join("::");
      const severityScore =
        item.severity === "critical" ? 52 : item.severity === "warning" ? 34 : 18;
      const stalePenalty = Math.min(18, item.stale_days ?? 0);
      const missingIndexPenalty = item.indexed_chunks_count <= 0 ? 22 : 0;
      const nextSteps =
        item.fix_plan.length > 0
          ? item.fix_plan
          : ["Open Ingestion Jobs, validate the source scope, then publish a healthy snapshot."];
      ensureCampaign({
        campaignId,
        title:
          faultDomain === "freshness"
            ? `Freshness recovery for ${productId ?? "unknown"} / ${sourceKind ?? "unknown"}`
            : `Coverage recovery for ${productId ?? "unknown"} / ${sourceKind ?? "unknown"}`,
        summary: item.summary,
        productId,
        programmingLanguage: analyticsLanguageFilter || null,
        sourceKind,
        repoIds: [item.repo_id],
        faultDomain,
        priorityScore: severityScore + stalePenalty + missingIndexPenalty + (item.mcp_ready ? 0 : 10),
        blastRadius: Math.max(1, (item.indexed_chunks_count <= 0 ? 5 : 1) + (item.executable_snippets_count <= 0 ? 3 : 0)),
        focusTarget:
          faultDomain === "freshness"
            ? {
                sectionId: "analytics",
                anchorId: "analytics-freshness-watchlist-panel",
                label: "Open freshness watchlist",
                requiredScope: null,
              }
            : {
                sectionId: "health",
                anchorId: "health-coverage-gap-triage-panel",
                label: "Open coverage triage",
                requiredScope: null,
              },
        workflowTarget: {
          sectionId: "ingestion-jobs",
          anchorId: "ingestion-run-single-panel",
          label: "Open ingestion workflow",
          requiredScope: "write:ingestion",
        },
        severityHint: item.severity,
        evidence: [
          `${item.signal_type} in ${item.repo_id}`,
          `${item.service_status}:${item.service_status_reason}`,
          `chunks=${item.indexed_chunks_count}, snippets=${item.executable_snippets_count}`,
        ],
        nextSteps,
        signalKey: `content:${item.signal_type}`,
      });
    }

    for (const item of freshnessWatchlistQuery.data?.items ?? []) {
      const productId = item.product_id || null;
      const programmingLanguage = item.programming_language || null;
      const sourceKind = item.source_kind || null;
      const campaignId = ["freshness", productId ?? "unknown", programmingLanguage ?? "all", sourceKind ?? "unknown"].join("::");
      const nextSteps =
        item.fix_plan.length > 0
          ? item.fix_plan
          : ["Inspect snapshot age, then republish a validated latest-stable snapshot."];
      ensureCampaign({
        campaignId,
        title: `Freshness recovery for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"} / ${sourceKind ?? "unknown"}`,
        summary: item.primary_reason,
        productId,
        programmingLanguage,
        sourceKind,
        repoIds: [item.repo_id],
        faultDomain: "freshness",
        priorityScore:
          item.risk_score +
          (item.release_visibility_gap ? 12 : 0) +
          item.critical_issue_reports_30d * 5 +
          item.no_result_sessions_30d * 2,
        blastRadius:
          item.query_sessions_30d +
          item.issue_reports_30d * 3 +
          item.negative_feedback_30d * 2 +
          item.no_result_sessions_30d,
        focusTarget: {
          sectionId: "analytics",
          anchorId: "analytics-freshness-watchlist-panel",
          label: "Open freshness watchlist",
          requiredScope: null,
        },
        workflowTarget: {
          sectionId: "ingestion-jobs",
          anchorId: "ingestion-run-single-panel",
          label: "Open ingestion workflow",
          requiredScope: "write:ingestion",
        },
        severityHint: item.risk_level === "high" ? "critical" : "warning",
        evidence: [
          `${item.repo_id} risk=${item.risk_level} (${item.risk_score})`,
          `snapshot=${item.latest_active_version ?? "none"} -> visible=${item.newest_visible_version ?? "unknown"}`,
          `queries=${item.query_sessions_30d}, issues=${item.issue_reports_30d}, negative=${item.negative_feedback_30d}`,
        ],
        nextSteps: [item.recommended_action, ...nextSteps],
        signalKey: `freshness:${item.risk_level}`,
      });
    }

    for (const cluster of zeroResultOverviewQuery.data?.clusters ?? []) {
      const faultDomain: RemediationCampaignFaultDomain =
        cluster.zero_result_reason === "no_index_data" || cluster.primary_warning_code === "no_index_data"
          ? "coverage"
          : "retrieval";
      const products = cluster.affected_products.length > 0 ? cluster.affected_products : ["unknown"];
      for (const productIdValue of products) {
        const productId = productIdValue || null;
        const programmingLanguage =
          cluster.affected_programming_languages.length === 1
            ? cluster.affected_programming_languages[0] || null
            : analyticsLanguageFilter || null;
        const sourceKind = analyticsSourceKindFilter || null;
        const campaignId = [faultDomain, productId ?? "unknown", programmingLanguage ?? "all", cluster.cluster_id].join("::");
        ensureCampaign({
          campaignId,
          title:
            faultDomain === "coverage"
              ? `Coverage recovery for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"}`
              : `Retrieval quality recovery for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"}`,
          summary: cluster.recommendation_detail,
          productId,
          programmingLanguage,
          sourceKind,
          repoIds: [],
          faultDomain,
          priorityScore:
            36 +
            Math.round(cluster.total_requests * Math.max(cluster.share_of_filtered_requests, 0.01)) +
            (cluster.total_requests >= 150 ? 12 : 0),
          blastRadius: cluster.total_requests,
          focusTarget: {
            sectionId: "analytics",
            anchorId: "analytics-zero-result-cockpit-panel",
            label: "Open zero-result cockpit",
            requiredScope: null,
          },
          workflowTarget:
            faultDomain === "coverage"
              ? {
                  sectionId: "ingestion-jobs",
                  anchorId: "ingestion-run-single-panel",
                  label: "Open ingestion workflow",
                  requiredScope: "write:ingestion",
                }
              : {
                  sectionId: "quality-reviews",
                  anchorId: "quality-reviews-runs-panel",
                  label: "Open quality review desk",
                  requiredScope: "write:settings",
                },
          severityHint: cluster.total_requests >= 150 ? "critical" : "warning",
          zeroResultReason: cluster.zero_result_reason,
          fallbackReason: cluster.fallback_reason,
          evidence: [
            `zero=${cluster.zero_result_reason}, fallback=${cluster.fallback_reason}, mode=${cluster.retrieval_mode}`,
            `warning=${cluster.primary_warning_code}, requests=${cluster.total_requests}`,
            cluster.sample_queries[0] ?? "No sample query captured.",
          ],
          nextSteps: [cluster.recommendation_title, cluster.recommendation_detail],
          signalKey: `zero:${cluster.zero_result_reason}:${cluster.fallback_reason}`,
        });
      }
    }

    for (const cluster of issueHotspotsQuery.data?.clusters ?? []) {
      const faultDomain: RemediationCampaignFaultDomain =
        cluster.issue_type === "outdated_docs"
          ? "freshness"
          : cluster.issue_type === "missing_docs" ||
              cluster.zero_result_reason === "no_index_data" ||
              cluster.primary_warning_code === "no_index_data"
            ? "coverage"
            : "retrieval";
      const productId = cluster.product_id || null;
      const programmingLanguage = cluster.programming_language || null;
      const campaignId = [faultDomain, productId ?? "unknown", programmingLanguage ?? "all", cluster.issue_type].join("::");
      const priorityWeight =
        cluster.priority === "highest" ? 52 : cluster.priority === "high" ? 38 : 24;
      ensureCampaign({
        campaignId,
        title:
          faultDomain === "freshness"
            ? `Freshness complaint campaign for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"}`
            : faultDomain === "coverage"
              ? `Coverage complaint campaign for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"}`
              : `Retrieval complaint campaign for ${productId ?? "unknown"} / ${programmingLanguage ?? "all"}`,
        summary: cluster.recommendation_detail,
        productId,
        programmingLanguage,
        sourceKind: analyticsSourceKindFilter || null,
        repoIds: [],
        faultDomain,
        priorityScore:
          priorityWeight +
          cluster.total_reports * 3 +
          Math.max(0, cluster.trend_delta * 2) +
          (cluster.severity === "critical" ? 12 : 0),
        blastRadius: cluster.total_reports * 3 + cluster.unique_request_ids,
        focusTarget: {
          sectionId: "analytics",
          anchorId:
            faultDomain === "retrieval"
              ? "analytics-issue-hotspots-panel"
              : faultDomain === "freshness"
                ? "analytics-freshness-watchlist-panel"
                : "analytics-issue-inbox-panel",
          label:
            faultDomain === "retrieval"
              ? "Open issue hotspots"
              : faultDomain === "freshness"
                ? "Open freshness watchlist"
                : "Open issue inbox",
          requiredScope: null,
        },
        workflowTarget:
          faultDomain === "retrieval"
            ? {
                sectionId: "quality-reviews",
                anchorId: "quality-reviews-runs-panel",
                label: "Open quality review desk",
                requiredScope: "write:settings",
              }
            : {
                sectionId: "ingestion-jobs",
                anchorId: "ingestion-run-single-panel",
                label: "Open ingestion workflow",
                requiredScope: "write:ingestion",
              },
        severityHint: cluster.severity,
        zeroResultReason: cluster.zero_result_reason,
        fallbackReason: cluster.fallback_reason,
        evidence: [
          `${cluster.issue_type} / ${cluster.severity} / ${cluster.priority}`,
          `reports=${cluster.total_reports}, delta=${cluster.trend_delta >= 0 ? "+" : ""}${cluster.trend_delta}`,
          cluster.sample_queries[0] ?? "No sample query captured.",
        ],
        nextSteps: [cluster.recommendation_title, cluster.recommendation_detail],
        signalKey: `issue:${cluster.issue_type}:${cluster.severity}`,
      });
    }

    return Array.from(campaigns.values())
      .map((campaign) => ({
        campaign_id: campaign.campaign_id,
        title: campaign.title,
        summary: campaign.summary,
        product_id: campaign.product_id,
        programming_language: campaign.programming_language,
        source_kind: campaign.source_kind,
        repo_ids: campaign.repo_ids,
        fault_domain: campaign.fault_domain,
        priority_score: campaign.priority_score,
        priority: scoreToRemediationCampaignPriority(campaign.priority_score),
        blast_radius: campaign.blast_radius,
        blast_radius_summary:
          campaign.blast_radius >= 100
            ? `${campaign.blast_radius} request/report signals in the current filtered scope`
            : `${campaign.blast_radius} grouped signals in the current filtered scope`,
        evidence: Array.from(campaign.evidence).slice(0, 4),
        next_steps: Array.from(campaign.next_steps).slice(0, 4),
        signal_counts: Object.fromEntries(campaign.signal_counts),
        focus_target: campaign.focus_target,
        workflow_target: campaign.workflow_target,
        severity_hint: campaign.severity_hint,
        zero_result_reason: campaign.zero_result_reason,
        fallback_reason: campaign.fallback_reason,
      }))
      .sort((left, right) => {
        const scoreDelta = right.priority_score - left.priority_score;
        if (scoreDelta !== 0) {
          return scoreDelta;
        }
        const blastDelta = right.blast_radius - left.blast_radius;
        if (blastDelta !== 0) {
          return blastDelta;
        }
        return left.campaign_id.localeCompare(right.campaign_id);
      });
  }, [contentTriageData, freshnessWatchlistQuery.data, zeroResultOverviewQuery.data, issueHotspotsQuery.data, analyticsLanguageFilter, analyticsSourceKindFilter]);

  const remediationCampaignPriorityCounters = remediationCampaigns.reduce(
    (accumulator, campaign) => {
      accumulator[campaign.priority] += 1;
      return accumulator;
    },
    { highest: 0, high: 0, medium: 0, low: 0 } as Record<RemediationCampaignPriority, number>,
  );

  // --- Handlers ---
  function saveAnalyticsView() {
    const name = analyticsViewName.trim();
    if (!name) {
      showAlert("Set view name.", "Validation Error");
      return;
    }
    const view: AnalyticsSavedView = {
      view_id: `${Date.now()}`,
      name,
      product_id: analyticsProductFilter,
      programming_language: analyticsLanguageFilter,
      doc_locale: analyticsLocaleFilter,
      client_id: analyticsClientFilter,
      source_kind: analyticsSourceKindFilter,
      outcome: analyticsOutcomeFilter,
      retrieval_mode: analyticsRetrievalModeFilter,
      zero_result_reason: analyticsZeroResultReasonFilter,
      fallback_reason: analyticsFallbackReasonFilter,
      warning_code: analyticsWarningCodeFilter,
      hashed_ip: analyticsIpHashFilter,
      fingerprint: analyticsFingerprintFilter,
      created_at: new Date().toISOString(),
    };
    setSavedAnalyticsViews((previous) => [view, ...previous].slice(0, 30));
    setAnalyticsViewName("");
  }

  function applyAnalyticsView(view: AnalyticsSavedView) {
    setAnalyticsProductFilter(view.product_id);
    setAnalyticsLanguageFilter(view.programming_language);
    setAnalyticsLocaleFilter(view.doc_locale);
    setAnalyticsClientFilter(view.client_id ?? "");
    setAnalyticsSourceKindFilter(view.source_kind ?? "");
    setAnalyticsOutcomeFilter(view.outcome ?? "");
    setAnalyticsRetrievalModeFilter(view.retrieval_mode ?? "");
    setAnalyticsZeroResultReasonFilter(view.zero_result_reason ?? "");
    setAnalyticsFallbackReasonFilter(view.fallback_reason ?? "");
    setAnalyticsWarningCodeFilter(view.warning_code ?? "");
    setAnalyticsIpHashFilter(view.hashed_ip ?? "");
    setAnalyticsFingerprintFilter(view.fingerprint ?? "");
  }

  function deleteAnalyticsView(viewId: string) {
    setSavedAnalyticsViews((previous) => previous.filter((item) => item.view_id !== viewId));
  }

  function clearAnalyticsFilters() {
    setAnalyticsProductFilter("");
    setAnalyticsLanguageFilter("");
    setAnalyticsLocaleFilter("");
    setAnalyticsClientFilter("");
    setAnalyticsSourceKindFilter("");
    setAnalyticsOutcomeFilter("");
    setAnalyticsRetrievalModeFilter("");
    setAnalyticsZeroResultReasonFilter("");
    setAnalyticsFallbackReasonFilter("");
    setAnalyticsWarningCodeFilter("");
    setAnalyticsIssueTypeFilter("");
    setAnalyticsIssueSeverityFilter("");
    setAnalyticsIpHashFilter("");
    setAnalyticsFingerprintFilter("");
  }

  async function copyIssueEvidenceContext(): Promise<void> {
    if (!requestEvidenceQuery.data) {
      return;
    }
    const payload = JSON.stringify(requestEvidenceQuery.data.copy_context, null, 2);
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(payload);
      setCopiedIssueEvidenceRequestId(requestEvidenceQuery.data.request_id);
      window.setTimeout(() => {
        setCopiedIssueEvidenceRequestId((current) =>
          current === requestEvidenceQuery.data?.request_id ? null : current,
        );
      }, 1500);
      return;
    }
    showAlert(payload, "Copy request evidence context");
  }

  function exportAnalyticsSlicesCsv() {
    if (!analyticsSliceQuery.data) {
      showAlert("No analytics slice data to export.");
      return;
    }
    const filters = {
      product_id: analyticsProductFilter,
      programming_language: analyticsLanguageFilter,
      doc_locale: analyticsLocaleFilter,
      outcome: analyticsOutcomeFilter,
      retrieval_mode: analyticsRetrievalModeFilter,
      zero_result_reason: analyticsZeroResultReasonFilter,
      fallback_reason: analyticsFallbackReasonFilter,
      warning_code: analyticsWarningCodeFilter,
    };
    const timestamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
    downloadCsv(
      `analytics-slices-${timestamp}.csv`,
      buildAnalyticsSlicesCsv({
        slice: analyticsSliceQuery.data,
        filters,
      }),
    );
  }

  function exportIssueHotspotsCsv() {
    if (!issueHotspotsQuery.data) {
      showAlert("No hotspot data to export.");
      return;
    }
    const timestamp = new Date().toISOString().replaceAll(":", "-").replaceAll(".", "-");
    downloadCsv(
      `issue-hotspots-${timestamp}.csv`,
      buildIssueHotspotsCsv({
        overview: issueHotspotsQuery.data,
        filters: {
          product_id: analyticsProductFilter,
          programming_language: analyticsLanguageFilter,
          doc_locale: analyticsLocaleFilter,
          issue_type: analyticsIssueTypeFilter,
          severity: analyticsIssueSeverityFilter,
        },
      }),
    );
  }

  function focusRemediationCampaign(campaign: RemediationCampaign) {
    setAnalyticsProductFilter(campaign.product_id ?? "");
    setAnalyticsLanguageFilter(campaign.programming_language ?? "");
    setAnalyticsSourceKindFilter(campaign.source_kind ?? "");
    setAnalyticsIssueSeverityFilter(campaign.severity_hint ?? "");
    setAnalyticsZeroResultReasonFilter(campaign.zero_result_reason ?? "");
    setAnalyticsFallbackReasonFilter(campaign.fallback_reason ?? "");
    openSection(campaign.focus_target.sectionId);
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        jumpToElement(campaign.focus_target.anchorId);
      });
    }
  }

  function openRemediationCampaignWorkflow(campaign: RemediationCampaign) {
    setSelectedProductId(campaign.product_id ?? "");
    openSection(campaign.workflow_target.sectionId);
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        jumpToElement(campaign.workflow_target.anchorId);
      });
    }
  }

  return {
    analyticsProductFilter,
    setAnalyticsProductFilter,
    analyticsLanguageFilter,
    setAnalyticsLanguageFilter,
    analyticsLocaleFilter,
    setAnalyticsLocaleFilter,
    analyticsClientFilter,
    setAnalyticsClientFilter,
    analyticsSourceKindFilter,
    setAnalyticsSourceKindFilter,
    analyticsOutcomeFilter,
    setAnalyticsOutcomeFilter,
    analyticsRetrievalModeFilter,
    setAnalyticsRetrievalModeFilter,
    analyticsZeroResultReasonFilter,
    setAnalyticsZeroResultReasonFilter,
    analyticsFallbackReasonFilter,
    setAnalyticsFallbackReasonFilter,
    analyticsWarningCodeFilter,
    setAnalyticsWarningCodeFilter,
    analyticsIssueTypeFilter,
    setAnalyticsIssueTypeFilter,
    analyticsIssueSeverityFilter,
    setAnalyticsIssueSeverityFilter,
    analyticsIpHashFilter,
    setAnalyticsIpHashFilter,
    analyticsFingerprintFilter,
    setAnalyticsFingerprintFilter,
    selectedIssueEvidenceRequestId,
    setSelectedIssueEvidenceRequestId,
    copiedIssueEvidenceRequestId,
    latestGuidedFixDraft,
    setLatestGuidedFixDraft,
    analyticsViewName,
    setAnalyticsViewName,
    savedAnalyticsViews,
    analyticsSliceQuery,
    zeroResultOverviewQuery,
    capacityForecastQuery,
    publicAdoptionFunnelQuery,
    freshnessWatchlistQuery,
    usefulnessSummaryQuery,
    usefulnessSignalsQuery,
    issueReviewSummaryQuery,
    issueReviewSignalsQuery,
    requestEvidenceQuery,
    issueHotspotsQuery,
    createGuidedContentFixDraftMutation,
    analyticsLanguageOptions,
    analyticsLocaleOptions,
    analyticsClientOptions,
    analyticsSourceKindOptions,
    analyticsOutcomeOptions,
    analyticsRetrievalModeOptions,
    analyticsZeroResultReasonOptions,
    analyticsFallbackReasonOptions,
    analyticsWarningCodeOptions,
    analyticsIssueTypeOptions,
    analyticsIssueSeverityOptions,
    remediationCampaigns,
    remediationCampaignPriorityCounters,
    saveAnalyticsView,
    applyAnalyticsView,
    deleteAnalyticsView,
    clearAnalyticsFilters,
    copyIssueEvidenceContext,
    exportAnalyticsSlicesCsv,
    exportIssueHotspotsCsv,
    focusRemediationCampaign,
    openRemediationCampaignWorkflow,
  };
}
