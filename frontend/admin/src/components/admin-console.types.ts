import type { AdminSession } from "@/lib/admin-api";
import type { HowToArticleId } from "@/content/howto";

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

export type SidebarSectionId =
  | "workspaces"
  | "health"
  | "runtime-guard"
  | "indexes-topology"
  | "content-coverage"
  | "ingestion-jobs"
  | "snapshots"
  | "critical-events"
  | "logs-traces"
  | "analytics"
  | "coverage-campaigns"
  | "retrieval-settings"
  | "language-registries"
  | "api-keys-access"
  | "config-history-rollback"
  | "sql-explorer-read-only"
  | "quality-reviews";

export type SidebarSectionZone = "operations" | "observability" | "settings";

export type SidebarSection = {
  id: SidebarSectionId;
  label: string;
  requiredScope?: string;
  /** Material icon name for sidebar visual anchor */
  icon: string;
  /** Section zone for accent color differentiation */
  zone: SidebarSectionZone;
};

// ---------------------------------------------------------------------------
// Workspace templates
// ---------------------------------------------------------------------------

export type AdminWorkspaceTemplateId =
  | "operational-triage"
  | "ingestion-runbook"
  | "quality-review"
  | "rollback-preparation";

export type AdminWorkspaceTemplate = {
  id: AdminWorkspaceTemplateId;
  title: string;
  description: string;
  sectionId: SidebarSectionId;
  anchorId: string;
  requiredScope?: string;
  recommendedRoles: AdminSession["effective_role"][];
  summaryLines: string[];
  quickActions: string[];
};

// ---------------------------------------------------------------------------
// Command palette
// ---------------------------------------------------------------------------

export type CommandPaletteGroup = "Sections" | "How-To" | "Actions";

export type CommandPaletteCommand = {
  id: string;
  group: CommandPaletteGroup;
  title: string;
  description: string;
  aliases: string[];
  execute: () => void;
};

// ---------------------------------------------------------------------------
// Analytics
// ---------------------------------------------------------------------------

export type AnalyticsSavedView = {
  view_id: string;
  name: string;
  product_id: string;
  programming_language: string;
  doc_locale: string;
  client_id: string;
  source_kind: string;
  outcome: string;
  retrieval_mode: string;
  zero_result_reason: string;
  fallback_reason: string;
  warning_code: string;
  // Scope dimensions (optional + additive for backward-compatible restore of older views).
  hashed_ip?: string;
  fingerprint?: string;
  created_at: string;
};

export type AnalyticsSliceExport = {
  total_requests: number;
  by_product_id: Record<string, number>;
  by_programming_language: Record<string, number>;
  by_doc_locale: Record<string, number>;
  by_endpoint: Record<string, number>;
  by_tool: Record<string, number>;
  by_outcome: Record<string, number>;
  by_retrieval_mode: Record<string, number>;
  by_zero_result_reason: Record<string, number>;
  by_fallback_reason: Record<string, number>;
  by_warning_code: Record<string, number>;
  refreshed_at: string;
};

export type IssueHotspotsExport = {
  filtered_reports_total: number;
  hotspots_total: number;
  clusters: Array<{
    hotspot_id: string;
    priority: string;
    product_id: string | null;
    programming_language: string | null;
    doc_locale: string | null;
    issue_type: string;
    severity: string;
    zero_result_reason: string | null;
    fallback_reason: string | null;
    primary_warning_code: string;
    total_reports: number;
    unique_request_ids: number;
    recent_reports_24h: number;
    previous_reports_24h: number;
    trend_status: string;
    trend_delta: number;
    share_of_filtered_reports: number;
    sample_queries: string[];
    sample_request_ids: string[];
    recommendation_title: string;
    recommendation_detail: string;
  }>;
};

// ---------------------------------------------------------------------------
// SQL Explorer
// ---------------------------------------------------------------------------

export type SqlSavedView = {
  view_id: string;
  name: string;
  sql: string;
  created_at: string;
  /** Last update timestamp; defaults to created_at on initial save. */
  updated_at?: string;
  /** Email of the author who created the saved query. */
  author_email?: string;
  /** Short human description of what the query does. */
  description?: string;
  /** Free-form comment / notes about the query. */
  comment?: string;
};

// ---------------------------------------------------------------------------
// Remediation campaigns
// ---------------------------------------------------------------------------

export type RemediationCampaignFaultDomain = "coverage" | "freshness" | "retrieval";

export type RemediationCampaignPriority = "highest" | "high" | "medium" | "low";

export type RemediationCampaignTarget = {
  sectionId: SidebarSectionId;
  anchorId: string;
  label: string;
  requiredScope: string | null;
};

export type RemediationCampaign = {
  campaign_id: string;
  title: string;
  summary: string;
  product_id: string | null;
  programming_language: string | null;
  source_kind: string | null;
  repo_ids: string[];
  fault_domain: RemediationCampaignFaultDomain;
  priority_score: number;
  priority: RemediationCampaignPriority;
  blast_radius: number;
  blast_radius_summary: string;
  evidence: string[];
  next_steps: string[];
  signal_counts: Record<string, number>;
  focus_target: RemediationCampaignTarget;
  workflow_target: RemediationCampaignTarget;
  severity_hint: string | null;
  zero_result_reason: string | null;
  fallback_reason: string | null;
};

// ---------------------------------------------------------------------------
// Workflow checklists
// ---------------------------------------------------------------------------

export type WorkflowChecklistStep = {
  id: string;
  title: string;
  description: string;
  anchorId: string;
  howToArticleId?: HowToArticleId;
};

export type WorkflowChecklistCardData = {
  id: string;
  title: string;
  description: string;
  statusLabel: string;
  statusTone: "default" | "warning" | "success";
  howToArticleId: HowToArticleId;
  steps: WorkflowChecklistStep[];
};

// ---------------------------------------------------------------------------
// Recovery guidance
// ---------------------------------------------------------------------------

export type RecoveryGuidanceAction = {
  label: string;
  onClick: () => void;
  variant?: "text" | "outlined" | "contained";
};

export type RecoveryGuidanceAlertProps = {
  severity: "error" | "warning" | "info" | "success";
  title: string;
  summary: string;
  likelyCause: string;
  nextStep: string;
  escalationHint?: string;
  howToArticleId?: HowToArticleId;
  sourceSectionId: SidebarSectionId;
  sourceLabel: string;
  returnTo: string;
  actions?: RecoveryGuidanceAction[];
};

// ---------------------------------------------------------------------------
// Help popover
// ---------------------------------------------------------------------------

export type HelpPopoverButtonProps = {
  title: string;
  why: string;
  what: string;
  how: string;
  howToArticleId?: HowToArticleId;
  size?: "small" | "medium";
};

// ---------------------------------------------------------------------------
// Guarded action button
// ---------------------------------------------------------------------------

export type GuardedActionButtonProps = {
  disabledReason?: string | null;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SIDEBAR_SECTIONS: readonly SidebarSection[] = [
  { id: "workspaces", label: "Workspaces", icon: "Dashboard", zone: "operations" },
  { id: "health", label: "Health", icon: "MonitorHeart", zone: "operations" },
  { id: "runtime-guard", label: "Runtime Guard & MCP", icon: "Security", zone: "observability" },
  { id: "indexes-topology", label: "Indexes & Topology", icon: "Storage", zone: "operations" },
  { id: "content-coverage", label: "Content Coverage", icon: "LibraryBooks", zone: "operations" },
  { id: "ingestion-jobs", label: "Ingestion Jobs", requiredScope: "write:ingestion", icon: "CloudUpload", zone: "operations" },
  { id: "snapshots", label: "Snapshots", requiredScope: "write:ingestion", icon: "CameraAlt", zone: "operations" },
  { id: "critical-events", label: "Critical Events", requiredScope: "write:ingestion", icon: "NotificationsActive", zone: "operations" },
  { id: "logs-traces", label: "Logs & Traces", icon: "Receipt", zone: "observability" },
  { id: "analytics", label: "Analytics", icon: "BarChart", zone: "observability" },
  { id: "coverage-campaigns", label: "Coverage Campaigns", icon: "Campaign", zone: "observability" },
  { id: "retrieval-settings", label: "Retrieval Settings", requiredScope: "write:settings", icon: "Tune", zone: "settings" },
  { id: "language-registries", label: "Language Registries", requiredScope: "write:settings", icon: "Translate", zone: "settings" },
  { id: "api-keys-access", label: "API Keys & Access", requiredScope: "write:settings", icon: "VpnKey", zone: "settings" },
  { id: "config-history-rollback", label: "Config History & Rollback", requiredScope: "write:settings", icon: "History", zone: "settings" },
  { id: "sql-explorer-read-only", label: "SQL Explorer (Read-Only)", icon: "Storage", zone: "observability" },
  { id: "quality-reviews", label: "Quality Reviews", requiredScope: "write:settings", icon: "FactCheck", zone: "settings" },
] as const;

export const SIDEBAR_SECTION_ID_SET: ReadonlySet<SidebarSectionId> = new Set(
  SIDEBAR_SECTIONS.map((item) => item.id),
);

export const OPERATION_SCOPE_HINTS = [
  { label: "Trigger Source Sync", requiredScope: "write:ingestion" },
  { label: "Validate-Only Ingestion", requiredScope: "write:ingestion" },
  { label: "Delete Product Version Data", requiredScope: "write:destructive" },
] as const;

export const DEFAULT_PROGRAMMING_LANGUAGE_OPTIONS = [
  "net",
  "java",
  "cpp",
  "python",
  "javascript",
  "typescript",
  "nodejs",
  "go",
  "php",
  "ruby",
  "swift",
  "kotlin",
] as const;

export const COOKIE_SESSION_SENTINEL = "__cookie_session__";
export const SECTION_STORAGE_KEY = "adcs-admin-active-section";
export const SIDEBAR_COLLAPSED_STORAGE_KEY = "adcs-admin-sidebar-collapsed";
export const ADMIN_DENSITY_STORAGE_KEY = "adcs-admin-density";
export const ADMIN_GUIDANCE_LAYER_STORAGE_KEY = "adcs-admin-guidance-layer";
export const ANALYTICS_VIEWS_STORAGE_KEY = "adcs-admin-analytics-views";
export const SQL_VIEWS_STORAGE_KEY = "adcs-admin-sql-views";
export const WORKSPACE_TEMPLATE_QUERY_PARAM = "workspace";

export const COMMAND_PALETTE_GROUP_ORDER: Record<CommandPaletteGroup, number> = {
  Sections: 0,
  Actions: 1,
  "How-To": 2,
};

export const SQL_QUALITY_PRESETS = [
  {
    id: "preset-no-results",
    label: "No-Results",
    sql: `
SELECT
  COALESCE(product_id, 'unknown') AS product_id,
  COALESCE(programming_language, 'unknown') AS programming_language,
  COUNT(*) AS requests
FROM analytics_queries
WHERE outcome = 'no_results'
GROUP BY product_id, programming_language
ORDER BY requests DESC
LIMIT 200
    `.trim(),
  },
  {
    id: "preset-fallback-reasons",
    label: "Fallback Reasons",
    sql: `
SELECT
  COALESCE(fallback_reason, 'none') AS fallback_reason,
  COUNT(*) AS requests
FROM analytics_queries
GROUP BY fallback_reason
ORDER BY requests DESC
LIMIT 200
    `.trim(),
  },
  {
    id: "preset-warning-codes",
    label: "Warning Codes",
    sql: `
SELECT
  COALESCE(warning_codes, 'none') AS warning_codes,
  COUNT(*) AS requests
FROM analytics_queries
GROUP BY warning_codes
ORDER BY requests DESC
LIMIT 200
    `.trim(),
  },
] as const;

export const ONBOARDING_WIZARD_STEPS = [
  "Product Identity",
  "Repository Layout",
  "Language Hints",
  "Review & Register",
] as const;
