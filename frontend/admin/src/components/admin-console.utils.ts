import type {
  AdminContentServiceHealth,
  AdminSystemHealth,
  CriticalEvent,
  AdminApiError as AdminApiErrorType,
} from "@/lib/admin-api";
import { AdminApiError } from "@/lib/admin-api";
import { hasScope } from "@/lib/scopes";
import type { AdminSession } from "@/lib/admin-api";
import type {
  AnalyticsSliceExport,
  IssueHotspotsExport,
  RemediationCampaignFaultDomain,
  RemediationCampaignPriority,
  SidebarSectionId,
  AdminWorkspaceTemplateId,
} from "./admin-console.types";
import { SIDEBAR_SECTION_ID_SET, WORKSPACE_TEMPLATE_QUERY_PARAM } from "./admin-console.types";

// ---------------------------------------------------------------------------
// Section / navigation helpers
// ---------------------------------------------------------------------------

export function isSidebarSectionId(value: string): value is SidebarSectionId {
  return SIDEBAR_SECTION_ID_SET.has(value as SidebarSectionId);
}

export function readSectionFromHash(hash: string): SidebarSectionId | null {
  const normalized = hash.trim().replace(/^#/, "");
  if (!normalized) {
    return null;
  }
  return isSidebarSectionId(normalized) ? normalized : null;
}

export function getSectionDomId(sectionId: SidebarSectionId): string {
  return `section-${sectionId}`;
}

// ---------------------------------------------------------------------------
// Health helpers
// ---------------------------------------------------------------------------

export function getReadinessSummary(health: AdminSystemHealth | undefined): string {
  if (!health) {
    return "unknown";
  }
  const total = Object.keys(health.dependencies).length;
  const ready = Object.values(health.dependencies).filter((item) => item.status === "ready").length;
  return `${ready}/${total} ready`;
}

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

export function canRunOperation(session: AdminSession, requiredScope: string): boolean {
  return hasScope(session, requiredScope);
}

// ---------------------------------------------------------------------------
// Workspace template helpers
// ---------------------------------------------------------------------------

export function isWorkspaceTemplateId(value: string | null): value is AdminWorkspaceTemplateId {
  return (
    value === "operational-triage" ||
    value === "ingestion-runbook" ||
    value === "quality-review" ||
    value === "rollback-preparation"
  );
}

export function readWorkspaceTemplateFromSearch(search: string): AdminWorkspaceTemplateId | null {
  const value = new URLSearchParams(search).get(WORKSPACE_TEMPLATE_QUERY_PARAM);
  return isWorkspaceTemplateId(value) ? value : null;
}

export function getWorkspaceTemplateRequiredScope(
  templateId: AdminWorkspaceTemplateId,
): string | null {
  if (templateId === "quality-review") {
    return "write:settings";
  }
  if (templateId === "ingestion-runbook" || templateId === "rollback-preparation") {
    return "write:ingestion";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

export function buildDisabledReason(args: {
  missingScope?: string | null;
  pending?: boolean;
  pendingMessage?: string;
  unmetCondition?: string | null;
}): string | null {
  if (args.missingScope) {
    return `Requires scope: ${args.missingScope}`;
  }
  if (args.pending) {
    return args.pendingMessage ?? "Operation is currently in progress.";
  }
  if (args.unmetCondition) {
    return args.unmetCondition;
  }
  return null;
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

export function getAdminErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof AdminApiError && error.message.trim().length > 0) {
    return error.message;
  }
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return fallback;
}

export function formatMinutesWindow(value: number): string {
  const absoluteMinutes = Math.abs(value);
  const hours = Math.floor(absoluteMinutes / 60);
  const minutes = absoluteMinutes % 60;
  const compactValue = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  return value < 0 ? `${compactValue} overdue` : `${compactValue} left`;
}

export function uniqueSorted(values: Iterable<string>): string[] {
  return Array.from(new Set(Array.from(values).map((item) => item.trim()).filter(Boolean))).sort();
}

export function parseCsvList(value: string): string[] {
  const seen = new Set<string>();
  const rows: string[] = [];
  for (const item of value.split(",")) {
    const normalized = item.trim();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    rows.push(normalized);
  }
  return rows;
}

export function normalizeMultiSelectValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return uniqueSorted(value.map((item) => String(item)));
  }
  if (typeof value === "string") {
    return parseCsvList(value);
  }
  return [];
}

export function collectProgrammingLanguages(knownValues: string[]): string[] {
  return uniqueSorted(knownValues.map((item) => item.toLowerCase()));
}

export function toPreviewJson(value: unknown, maxChars = 14_000): string {
  const encoded = JSON.stringify(value, null, 2);
  if (encoded.length <= maxChars) {
    return encoded;
  }
  return `${encoded.slice(0, maxChars)}\n... [truncated ${encoded.length - maxChars} chars]`;
}

export function sortedCounterEntries(
  counter: Record<string, number>,
  limit = 8,
): Array<[string, number]> {
  return Object.entries(counter)
    .sort((left, right) => {
      const byCount = right[1] - left[1];
      if (byCount !== 0) {
        return byCount;
      }
      return left[0].localeCompare(right[0]);
    })
    .slice(0, limit);
}

// ---------------------------------------------------------------------------
// Chip color helpers
// ---------------------------------------------------------------------------

export function eventBadgeColor(severity: CriticalEvent["severity"]): "error" | "warning" | "success" {
  if (severity === "critical") {
    return "error";
  }
  if (severity === "high") {
    return "warning";
  }
  return "success";
}

export function eventLifecycleChipColor(
  status: CriticalEvent["lifecycle"]["status"],
): "default" | "primary" | "success" | "warning" | "error" {
  if (status === "resolved") {
    return "success";
  }
  if (status === "escalated") {
    return "error";
  }
  if (status === "muted" || status === "snoozed") {
    return "warning";
  }
  if (status === "acknowledged") {
    return "primary";
  }
  return "default";
}

export function observabilityChipColor(
  value: string,
): "default" | "primary" | "success" | "warning" | "error" {
  const normalized = value.trim().toLowerCase();
  if (["pass", "healthy", "enabled", "promote", "success"].includes(normalized)) {
    return "success";
  }
  if (["warning", "warn", "hold", "missing_dependency"].includes(normalized)) {
    return "warning";
  }
  if (["fail", "failed", "rollback", "critical", "disabled"].includes(normalized)) {
    return "error";
  }
  if (["unknown", "skipped"].includes(normalized)) {
    return "default";
  }
  return "primary";
}

export function reviewStatusChipColor(status: string): "default" | "primary" | "success" | "warning" | "error" {
  if (status === "approved") {
    return "success";
  }
  if (status === "awaiting_approval") {
    return "warning";
  }
  if (status === "blocked" || status === "rejected") {
    return "error";
  }
  if (status === "running") {
    return "primary";
  }
  return "default";
}

export function contentServiceStatusChipColor(
  status: AdminContentServiceHealth["service_status"],
): "default" | "success" | "warning" | "error" {
  if (status === "healthy") {
    return "success";
  }
  if (status === "warning") {
    return "warning";
  }
  if (status === "critical") {
    return "error";
  }
  return "default";
}

export function freshnessRiskChipColor(riskLevel: string): "default" | "success" | "warning" | "error" {
  if (riskLevel === "high") {
    return "error";
  }
  if (riskLevel === "medium") {
    return "warning";
  }
  if (riskLevel === "low") {
    return "success";
  }
  return "default";
}

export function contentServiceIndicatorColor(indicatorColor: string): string {
  if (indicatorColor === "green") {
    return "#2e7d32";
  }
  if (indicatorColor === "yellow") {
    return "#ed6c02";
  }
  if (indicatorColor === "red") {
    return "#d32f2f";
  }
  return "#757575";
}

export function remediationCampaignPriorityColor(
  priority: RemediationCampaignPriority,
): "default" | "success" | "warning" | "error" {
  if (priority === "highest") {
    return "error";
  }
  if (priority === "high") {
    return "warning";
  }
  if (priority === "medium") {
    return "success";
  }
  return "default";
}

export function remediationCampaignDomainColor(
  domain: RemediationCampaignFaultDomain,
): "info" | "warning" | "success" {
  if (domain === "coverage") {
    return "warning";
  }
  if (domain === "freshness") {
    return "info";
  }
  return "success";
}

export function scoreToRemediationCampaignPriority(score: number): RemediationCampaignPriority {
  if (score >= 100) {
    return "highest";
  }
  if (score >= 75) {
    return "high";
  }
  if (score >= 50) {
    return "medium";
  }
  return "low";
}

// ---------------------------------------------------------------------------
// Content service action hint
// ---------------------------------------------------------------------------

export function getContentServiceActionHint(service: AdminContentServiceHealth): {
  summary: string;
  details: string;
} {
  const fixPlan = service.fix_plan ?? [];
  if (service.service_status_summary || fixPlan.length > 0) {
    return {
      summary: service.service_status_summary || "Inspect service diagnostics",
      details: fixPlan[0] ?? "Review repository diagnostics and retry the required action.",
    };
  }
  if (service.mcp_ready) {
    return {
      summary: "Ready",
      details: "Service has an active snapshot and is currently MCP-ready.",
    };
  }
  if (!service.active_snapshot_id) {
    if (service.onboarding_status === "pending_first_ingestion") {
      return {
        summary: "Awaiting first ingestion",
        details:
          "This product is registered but has never been ingested. Run ingestion to make it MCP-ready.",
      };
    }
    return {
      summary: "Run Trigger Publish",
      details:
        "No active snapshot exists yet. Open Ingestion Jobs and run Trigger Publish for this repository.",
    };
  }
  if (service.service_status_reason === "no_recent_runtime_signal") {
    return {
      summary: "Check runtime signal",
      details:
        "Snapshot exists, but no recent MCP runtime signal was detected. Run a query and verify backend health/metrics.",
    };
  }
  if (service.latest_operation_status === "failed") {
    return {
      summary: "Review last ingestion",
      details:
        "Last ingestion failed. Open Ingestion Jobs, inspect failed items, then rerun validate/publish.",
    };
  }
  return {
    summary: "Inspect service diagnostics",
    details:
      "Review latest ingestion status, warnings, and active snapshot details to recover MCP readiness.",
  };
}

// ---------------------------------------------------------------------------
// Drilldown template
// ---------------------------------------------------------------------------

export function materializeDrilldownTemplate(
  template: string | null,
  replacements: Record<string, string>,
): string | null {
  if (!template) {
    return null;
  }
  let value = template;
  for (const [key, replacement] of Object.entries(replacements)) {
    value = value.replaceAll(`{${key}}`, encodeURIComponent(replacement));
  }
  return value;
}

// ---------------------------------------------------------------------------
// CSV export helpers
// ---------------------------------------------------------------------------

export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(url);
}

export function escapeCsvValue(value: string): string {
  if (value.includes(",") || value.includes("\"") || value.includes("\n")) {
    return `"${value.replaceAll("\"", "\"\"")}"`;
  }
  return value;
}

export function buildAnalyticsSlicesCsv(args: {
  slice: AnalyticsSliceExport;
  filters: Record<string, string>;
}): string {
  const rows: string[] = [];
  rows.push("section,key,value");
  rows.push(`summary,total_requests,${args.slice.total_requests}`);
  rows.push(`summary,refreshed_at,${escapeCsvValue(args.slice.refreshed_at)}`);
  for (const [key, value] of Object.entries(args.filters)) {
    rows.push(`filter,${escapeCsvValue(key)},${escapeCsvValue(value || "*")}`);
  }

  const counters: Array<[string, Record<string, number>]> = [
    ["by_product_id", args.slice.by_product_id],
    ["by_programming_language", args.slice.by_programming_language],
    ["by_doc_locale", args.slice.by_doc_locale],
    ["by_endpoint", args.slice.by_endpoint],
    ["by_tool", args.slice.by_tool],
    ["by_outcome", args.slice.by_outcome],
    ["by_retrieval_mode", args.slice.by_retrieval_mode],
    ["by_zero_result_reason", args.slice.by_zero_result_reason],
    ["by_fallback_reason", args.slice.by_fallback_reason],
    ["by_warning_code", args.slice.by_warning_code],
  ];
  for (const [section, counter] of counters) {
    for (const [key, count] of sortedCounterEntries(counter, Number.MAX_SAFE_INTEGER)) {
      rows.push(`${section},${escapeCsvValue(key)},${count}`);
    }
    if (Object.keys(counter).length === 0) {
      rows.push(`${section},none,0`);
    }
  }

  return `${rows.join("\n")}\n`;
}

export function buildIssueHotspotsCsv(args: {
  overview: IssueHotspotsExport;
  filters: Record<string, string>;
}): string {
  const rows: string[] = [];
  rows.push("section,key,value");
  rows.push(`summary,filtered_reports_total,${args.overview.filtered_reports_total}`);
  rows.push(`summary,hotspots_total,${args.overview.hotspots_total}`);
  for (const [key, value] of Object.entries(args.filters)) {
    rows.push(`filter,${escapeCsvValue(key)},${escapeCsvValue(value || "*")}`);
  }
  rows.push("");
  rows.push(
    [
      "hotspot_id",
      "priority",
      "product_id",
      "programming_language",
      "doc_locale",
      "issue_type",
      "severity",
      "zero_result_reason",
      "fallback_reason",
      "primary_warning_code",
      "total_reports",
      "unique_request_ids",
      "recent_reports_24h",
      "previous_reports_24h",
      "trend_status",
      "trend_delta",
      "share_of_filtered_reports",
      "sample_queries",
      "sample_request_ids",
      "recommendation_title",
      "recommendation_detail",
    ].join(","),
  );
  for (const cluster of args.overview.clusters) {
    rows.push(
      [
        cluster.hotspot_id,
        cluster.priority,
        cluster.product_id ?? "unknown",
        cluster.programming_language ?? "unknown",
        cluster.doc_locale ?? "unknown",
        cluster.issue_type,
        cluster.severity,
        cluster.zero_result_reason ?? "none",
        cluster.fallback_reason ?? "none",
        cluster.primary_warning_code,
        String(cluster.total_reports),
        String(cluster.unique_request_ids),
        String(cluster.recent_reports_24h),
        String(cluster.previous_reports_24h),
        cluster.trend_status,
        String(cluster.trend_delta),
        String(cluster.share_of_filtered_reports),
        cluster.sample_queries.join(" | "),
        cluster.sample_request_ids.join(" | "),
        cluster.recommendation_title,
        cluster.recommendation_detail,
      ]
        .map(escapeCsvValue)
        .join(","),
    );
  }
  return `${rows.join("\n")}\n`;
}
