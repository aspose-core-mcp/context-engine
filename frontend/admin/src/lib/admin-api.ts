export type AdminSession = {
  key_id: string;
  effective_role: "viewer" | "operator" | "product-owner" | "superuser";
  is_superuser: boolean;
  scopes: string[];
  product_scopes: string[];
  source: string;
  /** Email of the key owner; available when the backend exposes it. */
  owner_email?: string;
};

export type DependencyHealth = {
  status: "ready" | "not_ready" | string;
  reason: string;
  required: boolean;
  summary: string;
  fix_plan: string[];
};

export type AdminSystemHealth = {
  status: "ok" | "degraded" | string;
  process: "ok" | string;
  dependencies: Record<string, DependencyHealth>;
  request_id: string | null;
  generated_at: string;
};

export type AdminContentServiceHealth = {
  repo_id: string;
  product_id: string;
  product_family: string;
  product_family_dir: string;
  source_kind: "docs" | "apiref" | string;
  git_url: string;
  default_branch: string;
  submodule_path: string;
  layout_type: string | null;
  layout_confidence: number | null;
  latest_operation_id: string | null;
  latest_operation_status: string | null;
  latest_operation_finished_at: string | null;
  parse_warnings_count: number;
  failed_items_count: number;
  active_snapshot_id: string | null;
  active_snapshot_created_at: string | null;
  active_scopes_count: number;
  supported_programming_languages: string[];
  supported_versions: string[];
  mcp_ready: boolean;
  onboarding_status: "active" | "ingested" | "pending_first_ingestion" | string;
  service_status: "healthy" | "warning" | "critical" | "unknown" | string;
  service_status_reason: string;
  indicator_color: "green" | "yellow" | "red" | "gray" | string;
  service_status_summary: string;
  fix_plan: string[];
};

export type AdminContentServicesOverview = {
  total_services: number;
  docs_services_total: number;
  apiref_services_total: number;
  docs_mcp_ready_total: number;
  apiref_mcp_ready_total: number;
  pending_first_ingestion_total: number;
  healthy_total: number;
  warning_total: number;
  critical_total: number;
  unknown_total: number;
  services: AdminContentServiceHealth[];
  request_id: string | null;
  generated_at: string;
};

export type PublicStatusResponse = {
  status: "ok" | "degraded" | string;
  process: "ok" | string;
  dependencies: Record<string, DependencyHealth>;
  total_services: number;
  docs_services_total: number;
  apiref_services_total: number;
  docs_mcp_ready_total: number;
  apiref_mcp_ready_total: number;
  pending_first_ingestion_total: number;
  healthy_total: number;
  warning_total: number;
  critical_total: number;
  unknown_total: number;
  filters: {
    product_id: string | null;
    repo_id: string | null;
  };
  services: AdminContentServiceHealth[];
  request_id: string | null;
  generated_at: string;
};

export type TopologyPolicyResponse = {
  profile: string;
  persistence_backend: string;
  retrieval_backend: string;
  config_path: string;
  qdrant: {
    shard_number: number;
    replication_factor: number;
    write_consistency_factor: number;
  };
  opensearch: {
    number_of_shards: number;
    number_of_replicas: number;
    refresh_interval: string;
  };
  compaction: {
    enabled: boolean;
    max_inactive_snapshots_per_scope: number;
    stale_snapshot_retention_days: number;
  };
  storage_tiering: {
    latest_stable_tier: string;
    archive_tier: string;
  };
  summary: string;
  generated_at: string;
};

export type PublicMCPConfigSnippet = {
  client_id: "cursor" | "claude-desktop" | "qwen-code" | "vscode" | string;
  display_name: string;
  config_path_hint: string;
  format: string;
  snippet: string;
  instructions: string[];
};

export type PublicMCPConfigExport = {
  server_name: string;
  product_id: string | null;
  transport: "streamable-http" | "sse" | string;
  mcp_url: string;
  sample_prompt: string;
  clients: PublicMCPConfigSnippet[];
  generated_at: string;
};

export type PublicMCPSelfTestCheck = {
  check_id: string;
  title: string;
  status: "pass" | "warn" | "fail" | string;
  summary: string;
  details: string[];
};

export type PublicMCPSelfTest = {
  product_id: string;
  programming_language: string | null;
  client_id: "cursor" | "claude-desktop" | "qwen-code" | "vscode" | string;
  transport: "streamable-http" | "sse" | string;
  status: "ready" | "partial" | "not_ready" | string;
  status_summary: string;
  docs_ready_count: number;
  apiref_ready_count: number;
  total_ready_services: number;
  total_registered_services: number;
  snippet_count: number;
  available_programming_languages: string[];
  available_versions: string[];
  checks: PublicMCPSelfTestCheck[];
  fix_plan: string[];
  config_export_url: string;
  status_page_url: string;
  mcp_url: string;
  sample_prompt: string;
  generated_at: string;
};

export type PublicResolvedProduct = {
  product_id: string;
  language: string | null;
  aliases: string[];
  confidence: number;
};

export type PublicQueryDocsResult = {
  chunk_id: string;
  title: string;
  excerpt: string;
  canonical_url: string;
  section_anchor: string;
  score: number;
  source_revision: string;
  executable_snippets: Array<{
    snippet_id: string;
    language: string;
    code: string;
    parent_canonical_url: string;
    parent_section_anchor: string;
    parent_symbol_fqn: string | null;
  }>;
};

export type PublicQueryDocsResponse = {
  query_id: string;
  request_id: string;
  mode: string;
  query_locale_detected: string;
  translation_fallback_applied: boolean;
  confidence: number;
  confidence_level: string;
  fallback_reason: string | null;
  version_resolution: {
    requested_version: string | null;
    preferred_version: string | null;
    resolved_version: string | null;
    available_versions: string[];
    prefers_latest_stable: boolean;
    strict_version_enforced: boolean;
    fallback_applied: boolean;
    fallback_reason: string | null;
  };
  clarification_questions: string[];
  quality: {
    overall_score: number;
    coverage_score: number;
    freshness_score: number;
    freshness_source: string;
    citation_density_score: number;
    symbol_match_score: number;
    intent: string;
    intent_subtype: string | null;
    completeness_status: string;
    completeness_missing_signals: string[];
  };
  results: PublicQueryDocsResult[];
  warnings: string[];
  api_guardrails: string[];
  explainability: {
    reranker_backend: string;
    intent_subtype: string | null;
    freshness_source: string;
    why_top_result: string[];
    why_version: string | null;
    why_fallback: string | null;
  };
  debug: Record<string, unknown> | null;
};

export type PublicQueryFeedbackResponse = {
  feedback_id: string;
  request_id: string;
  rating: string;
  reason_codes: string[];
  updated_existing: boolean;
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  created_at: string;
  updated_at: string;
};

export type PublicQueryIssueResponse = {
  issue_id: string;
  request_id: string;
  issue_type: string;
  updated_existing: boolean;
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  created_at: string;
  updated_at: string;
};

export type PublicQueryReproPack = {
  request_id: string;
  share_url: string;
  generated_at: string;
  assumptions: string[];
  handoff_notes: string[];
  scope: {
    request_id: string;
    endpoint: string;
    tool: string;
    raw_query: string;
    product_id: string | null;
    programming_language: string | null;
    doc_locale: string | null;
    captured_at: string;
  };
  original: {
    outcome: string;
    retrieval_mode: string | null;
    result_count: number;
    confidence: number;
    latency_ms: number;
    zero_result_reason: string | null;
    fallback_reason: string | null;
    warning_codes: string[];
  };
  replay: {
    mode: string;
    query_locale_detected: string;
    translation_fallback_applied: boolean;
    confidence: number;
    confidence_level: string;
    fallback_reason: string | null;
    result_count: number;
    warnings: string[];
    version_resolution: PublicQueryDocsResponse["version_resolution"];
    quality: PublicQueryDocsResponse["quality"];
    clarification_questions: string[];
    api_guardrails: string[];
    citations: Array<{
      title: string;
      canonical_url: string;
      section_anchor: string;
      score: number;
      source_revision: string;
      executable_snippets_count: number;
    }>;
  };
  linked_signals: {
    total_feedback: number;
    latest_feedback_rating: string | null;
    total_issue_reports: number;
    issue_types: string[];
    last_feedback_at: string | null;
    last_issue_at: string | null;
  };
};

export type PublicSymbolDocResponse = {
  symbol_fqn: string;
  signature: string;
  summary: string;
  parameters: Array<{ name: string; type: string; description: string }>;
  returns: string;
  examples: Array<{ language: string; code: string }>;
  citations: Array<{ canonical_url: string; section_anchor: string }>;
  deprecated: boolean;
  signature_variants: Array<{
    signature: string;
    source_kind: string;
    chunk_type: string;
    is_deprecated: boolean;
    citation: { canonical_url: string; section_anchor: string };
  }>;
  guardrails: string[];
};

export type PublicReleaseFreshness = {
  product_id: string;
  programming_language: string | null;
  requested_version: string | null;
  resolved_version: string | null;
  newest_available_version: string | null;
  available_versions: string[];
  latest_active_snapshot_at: string | null;
  services: Array<{
    source_kind: string;
    mcp_ready: boolean;
    latest_version: string | null;
    latest_source_revision: string | null;
    latest_snapshot_id: string | null;
    latest_snapshot_created_at: string | null;
    indexed_chunks_count: number;
  }>;
  release_features: Array<{
    kind: string;
    summary: string;
    symbol_fqn: string | null;
    version: string;
    source_kind: string;
    canonical_url: string;
    section_anchor: string;
  }>;
  status_summary: string;
  generated_at: string;
};

export type PublicReleaseAdoption = {
  product_id: string;
  programming_language: string | null;
  requested_version: string | null;
  resolved_version: string | null;
  newest_available_version: string | null;
  recommended_from_version: string | null;
  recommended_to_version: string | null;
  status: string;
  freshness_label: string;
  status_summary: string;
  latest_active_snapshot_at: string | null;
  migration_checklist: string[];
  upgrade_prompt: string;
  fix_plan: string[];
  compare_ranges: Array<{
    range_id: string;
    from_version: string;
    to_version: string;
    breaking_changes_total: number;
    status: string;
    summary: string;
  }>;
  latest_release: PublicLatestReleaseFeaturesResponse;
  breaking_changes: PublicBreakingChangesResponse;
  actions: Array<{ label: string; href: string }>;
  generated_at: string;
};

export type PublicUseCaseGallery = {
  filters: {
    product_id: string | null;
    programming_language: string | null;
    client_id: string | null;
    status: string | null;
  };
  status_summary: string;
  items: Array<{
    use_case_id: string;
    category: string;
    title: string;
    status: string;
    summary: string;
    starter_prompt: string;
    starter_query: string;
    recommended_journey_id: string | null;
    client_notes: Array<{ client_id: string; note: string }>;
    evidence: Array<{
      evidence_type: string;
      title: string;
      canonical_url: string;
      section_anchor: string;
      snippet_id: string | null;
    }>;
    actions: Array<{ label: string; href: string }>;
  }>;
  generated_at: string;
};

export type PublicBreakingChangesResponse = {
  items: Array<{
    type: string;
    symbol_fqn: string | null;
    from_version: string | null;
    to_version: string | null;
    description: string;
    migration_hint: string;
    citation: {
      canonical_url: string;
      section_anchor: string;
    };
  }>;
  page: number;
  page_size: number;
  total: number;
};

export type PublicLatestReleaseFeaturesResponse = {
  product_id: string;
  language: string;
  resolved_version: string;
  items: Array<{
    kind: string;
    summary: string;
    symbol_fqn: string | null;
    version: string;
    source_kind: string;
    citation: {
      canonical_url: string;
      section_anchor: string;
    };
  }>;
  guardrails: string[];
};

export type PublicContentTriage = {
  filters: {
    product_id: string | null;
    repo_id: string | null;
    severity: string | null;
    source_kind: string | null;
  };
  stale_after_days: number;
  total_items: number;
  critical_total: number;
  warning_total: number;
  info_total: number;
  status_summary: string;
  items: Array<{
    gap_id: string;
    severity: string;
    signal_type: string;
    product_id: string;
    repo_id: string;
    source_kind: string;
    mcp_ready: boolean;
    indexed_chunks_count: number;
    executable_snippets_count: number;
    active_snapshot_created_at: string | null;
    stale_days: number | null;
    summary: string;
    service_status: string;
    service_status_reason: string;
    fix_plan: string[];
  }>;
  generated_at: string;
};

export type PublicStarterPacks = {
  product_id: string | null;
  programming_language: string | null;
  transport: string;
  packs: Array<{
    pack_id: string;
    client_id: string;
    display_name: string;
    title: string;
    description: string;
    config_path_hint: string;
    config_format: string;
    config_snippet: string;
    starter_prompt: string;
    first_queries: string[];
    starter_checklist: string[];
    bundle_markdown: string;
    download_filename: string;
  }>;
  generated_at: string;
};

export type PublicCoverageGapTracker = {
  filters: {
    product_id: string | null;
    programming_language: string | null;
    source_kind: string | null;
    version: string | null;
  };
  products_total: number;
  surfaces_total: number;
  ready_surfaces_total: number;
  partial_surfaces_total: number;
  registered_only_surfaces_total: number;
  high_priority_surfaces_total: number;
  medium_priority_surfaces_total: number;
  low_priority_surfaces_total: number;
  status_summary: string;
  products: Array<{
    product_id: string;
    product_name: string;
    product_family: string;
    product_family_dirs: string[];
    repo_ids: string[];
    registered_source_kinds: string[];
    expected_programming_languages: string[];
    ready_surfaces_total: number;
    partial_surfaces_total: number;
    registered_only_surfaces_total: number;
    high_priority_surfaces_total: number;
    medium_priority_surfaces_total: number;
    low_priority_surfaces_total: number;
    surfaces: Array<{
      surface_id: string;
      product_id: string;
      product_name: string;
      product_family: string;
      programming_language: string;
      status: string;
      onboarding_priority: string;
      registered_source_kinds: string[];
      ready_source_kinds: string[];
      latest_stable_visible: boolean;
      executable_snippets_count: number;
      expected_versions: string[];
      gap_badges: string[];
      summary: string;
      source_kinds: Array<{
        source_kind: string;
        registered: boolean;
        ready: boolean;
        repo_ids: string[];
        active_snapshot_ids: string[];
        active_versions: string[];
        latest_stable_visible: boolean;
        supported_versions: string[];
        service_statuses: string[];
        service_reasons: string[];
      }>;
    }>;
  }>;
  generated_at: string;
};

export type PublicCoverageNavigator = {
  filters: {
    product_id: string | null;
    programming_language: string | null;
    source_kind: string | null;
    version: string | null;
  };
  products_total: number;
  surfaces_total: number;
  ready_total: number;
  partial_total: number;
  registered_only_total: number;
  available_products: string[];
  available_programming_languages: string[];
  available_source_kinds: string[];
  available_versions: string[];
  status_summary: string;
  surfaces: Array<{
    surface_id: string;
    product_id: string;
    product_name: string;
    product_family: string;
    programming_language: string;
    overall_status: string;
    onboarding_priority: string;
    latest_visible_versions: string[];
    executable_snippets_count: number;
    gap_badges: string[];
    summary: string;
    remediation: string[];
    cells: Array<{
      source_kind: string;
      status: string;
      active_versions: string[];
      service_reason: string | null;
    }>;
    actions: Array<{ label: string; href: string }>;
  }>;
  generated_at: string;
};

export type PublicTrustSignalsBoard = {
  product_id: string;
  programming_language: string | null;
  requested_version: string | null;
  resolved_version: string | null;
  trust_posture: string;
  strong_total: number;
  watch_total: number;
  weak_total: number;
  status_summary: string;
  explainability: string[];
  scorecards: Array<{
    signal_id: string;
    title: string;
    status: string;
    score: number;
    summary: string;
    evidence: string[];
    actions: Array<{ label: string; href: string }>;
  }>;
  generated_at: string;
};

export type PublicScopeCompareBoard = {
  preferred_side: string;
  status_summary: string;
  explainability: string[];
  left_scope: {
    product_id: string;
    programming_language: string | null;
    requested_version: string | null;
    resolved_version: string | null;
    trust_posture: string;
    average_signal_score: number;
    executable_snippets_count: number;
    summary: string;
  };
  right_scope: {
    product_id: string;
    programming_language: string | null;
    requested_version: string | null;
    resolved_version: string | null;
    trust_posture: string;
    average_signal_score: number;
    executable_snippets_count: number;
    summary: string;
  };
  metrics: Array<{
    metric_id: string;
    title: string;
    preferred_side: string;
    summary: string;
    left_score: number;
    right_score: number;
    left_status: string;
    right_status: string;
    left_evidence: string[];
    right_evidence: string[];
    left_href: string;
    right_href: string;
  }>;
  generated_at: string;
};

export type PublicCapabilityExplorer = {
  filters: {
    product_id: string | null;
    programming_language: string | null;
    source_kind: string | null;
    version: string | null;
  };
  products_total: number;
  capabilities_total: number;
  ready_total: number;
  partial_total: number;
  gap_total: number;
  available_programming_languages: string[];
  available_source_kinds: string[];
  status_summary: string;
  items: Array<{
    capability_id: string;
    product_id: string;
    product_name: string;
    product_family: string;
    programming_language: string;
    status: string;
    onboarding_priority: string;
    latest_stable_visible: boolean;
    freshness_label: string | null;
    resolved_version: string | null;
    newest_available_version: string | null;
    executable_snippets_count: number;
    registered_source_kinds: string[];
    ready_source_kinds: string[];
    gap_badges: string[];
    summary: string;
    snippet_titles: string[];
    actions: Array<{
      label: string;
      href: string;
    }>;
  }>;
  generated_at: string;
};

export type PublicTroubleshooting = {
  filters: {
    product_id: string | null;
    programming_language: string | null;
    client_id: string | null;
    transport: string | null;
    request_id: string | null;
  };
  status_summary: string;
  self_test_status: string;
  critical_gap_total: number;
  warning_gap_total: number;
  request_diagnostics: {
    request_id: string | null;
    outcome: string | null;
    result_count: number | null;
    confidence: number | null;
    zero_result_reason: string | null;
    fallback_reason: string | null;
    feedback_total: number;
    issue_total: number;
  };
  paths: Array<{
    path_id: string;
    title: string;
    severity: string;
    summary: string;
    match_reason: string;
    evidence: string[];
    fix_plan: string[];
    copy_block_label: string | null;
    copy_block_text: string | null;
    actions: Array<{
      label: string;
      href: string;
    }>;
  }>;
  generated_at: string;
};

export type PublicSnippetItem = {
  snippet_id: string;
  product_id: string;
  programming_language: string;
  version: string;
  source_kind: string;
  doc_type: string;
  title: string;
  canonical_url: string;
  section_anchor: string;
  symbol_fqn: string | null;
  snippet_language: string;
  code: string;
  source_revision: string;
  repo_id: string;
};

export type PublicSnippetExplorer = {
  product_id: string | null;
  programming_language: string | null;
  version: string | null;
  source_kind: string | null;
  total_snippets: number;
  items: PublicSnippetItem[];
  generated_at: string;
};

export type HowToLocalizedText = {
  en: string;
  ru: string;
};

export type HowToLocalizedLines = {
  en: string[];
  ru: string[];
};

export type HowToOverrideCallout = {
  id: string;
  level: "info" | "warning" | "success";
  title: HowToLocalizedText;
  body: HowToLocalizedLines;
};

export type HowToOverrideCommand = {
  id: string;
  label: HowToLocalizedText;
  description: HowToLocalizedText;
  command: string;
};

export type HowToOverrideExample = {
  id: string;
  title: HowToLocalizedText;
  bullets: HowToLocalizedLines;
};

export type HowToOverrideScreenshot = {
  id: string;
  src: string;
  alt: HowToLocalizedText;
  caption: HowToLocalizedText;
};

export type HowToOverridePayload = {
  entry_label: HowToLocalizedText;
  title: HowToLocalizedText;
  summary: HowToLocalizedText;
  purpose: HowToLocalizedLines;
  workflow: HowToLocalizedLines;
  callouts: HowToOverrideCallout[];
  commands: HowToOverrideCommand[];
  examples: HowToOverrideExample[];
  screenshots: HowToOverrideScreenshot[];
};

export type HowToOverrideEnvelope = {
  article_id: string;
  draft: HowToOverridePayload | null;
  draft_updated_at: string | null;
  draft_updated_by: string | null;
  published: HowToOverridePayload | null;
  published_updated_at: string | null;
  published_updated_by: string | null;
};

export type HowToOverrideListResponse = {
  records: HowToOverrideEnvelope[];
  generated_at: string;
};

export type PublishedHowToArticle = {
  article_id: string;
  published: HowToOverridePayload;
  published_updated_at: string | null;
  published_updated_by: string | null;
};

export type PublishedHowToListResponse = {
  articles: PublishedHowToArticle[];
  generated_at: string;
};

export type HowToAssetUploadResponse = {
  asset_name: string;
  asset_url: string;
  size_bytes: number;
};

export type AdminObservabilitySummary = {
  mcp_negotiation_total: number;
  mcp_negotiation_fallback_total: number;
  mcp_negotiation_fail_ratio: number;
  mcp_sessions_by_revision: Record<string, number>;
  mcp_fallback_by_reason: Record<string, number>;
  mcp_fallback_breakdown: Array<{
    requested_revision: string;
    negotiated_revision: string;
    fallback_reason: string;
    count: number;
  }>;
  abuse_guard_decisions_by_mode: Record<string, Record<string, number>>;
  abuse_guard_decisions_breakdown: Array<{
    mode: string;
    decision: string;
    count: number;
  }>;
  abuse_guard_settings: {
    mode: "observe-only" | "enforce" | string;
    allowlist_size: number;
    requests_per_ip_per_minute: number;
    requests_per_fingerprint_per_minute: number;
    requests_global_per_minute: number;
    debug_header_enabled: boolean;
    updated_by: string;
    updated_at: string;
  };
  trace_policy: {
    enabled: boolean;
    service_name: string;
    sample_ratio: number;
    error_sample_ratio: number;
    slow_request_threshold_ms: number;
    backend: string;
    otlp_endpoint: string | null;
  };
  drilldown_links: {
    grafana_dashboard_url: string | null;
    loki_logs_url_template: string | null;
    tempo_trace_url_template: string | null;
    traces_enabled: boolean;
  };
  alert_rules: Array<{
    rule_id: string;
    severity: string;
    description: string;
    window_minutes: number;
    threshold: string;
  }>;
  latest_deploy_smoke: {
    status: string;
    target_base_url: string | null;
    started_at: string | null;
    finished_at: string | null;
    checks: Array<{
      check_id: string;
      status: string;
      detail: string;
    }>;
  };
  canary_policy: {
    enabled: boolean;
    initial_traffic_pct: number;
    full_traffic_pct: number;
    analysis_window_minutes: number;
    max_error_rate_pct: number;
    max_latency_p95_ms: number;
    auto_rollback: boolean;
    latest_decision: string | null;
    latest_reason: string | null;
  };
  request_id: string | null;
  generated_at: string;
};

export type AbuseGuardSettings = {
  mode: "observe-only" | "enforce" | string;
  allowlist: string[];
  requests_per_ip_per_minute: number;
  requests_per_fingerprint_per_minute: number;
  requests_global_per_minute: number;
  debug_header_enabled: boolean;
  updated_by: string;
  updated_at: string;
};

export type IngestionResultSummary = {
  repo_id: string;
  source_kind: string;
  parsed_pages_count: number;
  parse_warnings_count: number;
  review_artifact_path: string | null;
  staging_repository_manifest_path: string | null;
  staging_replay_used: boolean;
  staging_scopes: Array<{
    product_id: string;
    programming_language: string;
    version: string;
    doc_locale: string;
    source_kind: string;
    manifest_path: string;
    documents_count: number;
    chunk_records_count: number;
  }>;
  pages: Array<{
    repo_id: string;
    source_path: string;
    source_kind: string;
    product_id: string | null;
    product_family: string | null;
    programming_language: string | null;
    doc_locale: string | null;
    title: string;
    metadata: Record<string, unknown>;
    body_plain: string;
    headings: Array<{
      level: number;
      text: string;
      line_hint: number;
    }>;
    code_blocks: Array<{
      language: string | null;
      code: string;
      line_start: number;
      line_end: number;
    }>;
    parse_warnings: Array<{
      code: string;
      message: string;
      line_hint: number | null;
      severity: string;
    }>;
    is_index_page: boolean;
  }>;
  chunk_records: Array<{
    chunk_id: string;
    repo_id: string;
    product_id: string;
    product_family: string;
    programming_language: string;
    version: string;
    source_kind: string;
    doc_locale: string;
    doc_type: string;
    symbol_fqn: string | null;
    title: string;
    section_path: string[];
    canonical_url: string;
    source_path: string;
    source_revision: string;
    is_deprecated: boolean;
    has_code_example: boolean;
    chunk_type: string;
    section_anchor: string;
    text: string;
    tokens: number;
    checksum: string;
    executable_snippets: Array<{
      snippet_id: string;
      language: string;
      code: string;
      parent_canonical_url: string;
      parent_section_anchor: string;
      parent_symbol_fqn: string | null;
    }>;
  }>;
  failed_items: Array<{
    source_path: string;
    error_code: string;
    message: string;
  }>;
  indexing_summary: {
    snapshot_id: string;
    product_id: string;
    programming_language: string;
    version: string;
    source_kind: string;
    decision: string;
    mode: string;
    error_ratio: number;
    failed_items_count: number;
  };
};

export type IngestionJobOperation = {
  operation_id: string;
  status: string;
  mode?: string;
  requested_mode?: string;
  dry_run?: boolean;
  force_full_reindex?: boolean;
  repo_ids: string[];
  started_at: string | null;
  finished_at: string | null;
  results: IngestionResultSummary[];
};

export type ReviewArtifactPreview = {
  artifact_path: string;
  payload: Record<string, unknown>;
};

export type RawMarkdownPreview = {
  source_path: string;
  size_bytes: number;
  line_count: number;
  raw_markdown: string;
};

export type StagingDocumentPreview = {
  source_path: string;
  document_path: string;
  document_checksum: string;
  payload: Record<string, unknown>;
};

export type StagingChunkPreview = {
  source_path: string;
  chunk_path: string;
  chunk_records_count: number;
  payload: Record<string, unknown>;
};

export type StagingManifestPreview = {
  manifest_path: string;
  manifest_kind: string;
  payload: Record<string, unknown>;
  documents_preview: StagingDocumentPreview[];
  chunk_objects_preview: StagingChunkPreview[];
  documents_truncated: boolean;
  chunk_objects_truncated: boolean;
  chunk_records_truncated: boolean;
};

export type SnapshotRecord = {
  snapshot_id: string;
  product_id: string;
  programming_language: string;
  version: string;
  source_kind: string;
  source_revision: string;
  status: "active" | "inactive" | "partial" | string;
  indexed_chunks_count: number;
  created_at: string;
};

export type SnapshotCompareResult = {
  base_snapshot: SnapshotRecord;
  target_snapshot: SnapshotRecord;
  same_scope: boolean;
  same_source_kind: boolean;
  indexed_chunks_delta: number;
  created_at_delta_seconds: number;
};

export type SnapshotRollbackCheck = {
  code: string;
  status: "pass" | "fail" | "warn" | string;
  message: string;
  details: Record<string, unknown>;
};

export type SnapshotRollbackConfirmation = {
  snapshot_id: string;
  confirm_token: string;
  expires_at: string;
  ttl_seconds: number;
};

export type SnapshotRollbackExecutionResult = {
  audit_id: string;
  operation_id: string;
  status: "completed" | string;
  can_execute: boolean;
  target_snapshot: SnapshotRecord;
  active_snapshot_before: SnapshotRecord;
  active_snapshot_after: SnapshotRecord;
  preflight_diagnostics: SnapshotRollbackCheck[];
  consistency_checks: SnapshotRollbackCheck[];
  history_preserved: boolean;
};

export type SnapshotRollbackAuditRecord = {
  audit_id: string;
  operation_id: string;
  result_status: string;
  actor_key_id: string;
  request_id: string | null;
  reason: string;
  product_id: string;
  programming_language: string;
  version: string;
  target_snapshot_id: string;
  active_snapshot_before_id: string | null;
  active_snapshot_after_id: string | null;
  diagnostics: Record<string, unknown>;
  created_at: string;
};

export type SnapshotCleanupProtectedRecord = {
  snapshot: SnapshotRecord;
  reason: string;
};

export type SnapshotCleanupPreviewResult = {
  operation_id: string;
  status: string;
  compaction_enabled: boolean;
  matched_snapshots_count: number;
  delete_candidates_count: number;
  protected_snapshots_count: number;
  max_inactive_snapshots_per_scope: number;
  stale_snapshot_retention_days: number;
  product_id: string;
  programming_language: string | null;
  version: string | null;
  source_kind: string | null;
  delete_candidates: SnapshotRecord[];
  protected_snapshots: SnapshotCleanupProtectedRecord[];
  risk_summary: string[];
  generated_at: string;
};

export type SnapshotCleanupExecutionResult = SnapshotCleanupPreviewResult & {
  audit_id: string;
  deleted_snapshots_count: number;
  deleted_snapshots: SnapshotRecord[];
  reason: string;
};

export type SnapshotCleanupAuditRecord = {
  audit_id: string;
  operation_id: string;
  result_status: string;
  actor_key_id: string;
  request_id: string | null;
  reason: string;
  product_id: string;
  programming_language: string | null;
  version: string | null;
  source_kind: string | null;
  dry_run: boolean;
  deleted_snapshot_ids: string[];
  protected_snapshot_ids: string[];
  diagnostics: Record<string, unknown>;
  created_at: string;
};

export type ProductRecord = {
  product_id: string;
  product_family: string;
  product_family_dirs?: string[];
  source_kinds: string[];
  repo_ids: string[];
  repositories_count: number;
};

export type SourceRepositoriesOnboardProductRequest = {
  product_id: string;
  product_name?: string;
  product_family: string;
  product_family_dir: string;
  programming_languages?: string[];
  docs_git_url: string;
  docs_default_branch?: string;
  apiref_git_url: string;
  apiref_default_branch?: string;
  auto_run_layout_detection?: boolean;
  auto_run_validate_only?: boolean;
};

export type SourceRepositoriesOnboardedRepo = {
  repo_id: string;
  source_kind: string;
  git_url: string;
  default_branch: string;
  submodule_path: string;
  local_path_created: boolean;
};

export type SourceRepositoriesOnboardProductResponse = {
  product_id: string;
  product_family: string;
  product_family_dir: string;
  created_repo_ids: string[];
  repositories: SourceRepositoriesOnboardedRepo[];
  programming_languages: string[];
  registry_path: string;
  next_steps: string[];
  bootstrap: {
    status: string;
    layout_detection_requested: boolean;
    validate_only_requested: boolean;
    layout_detection_operation: {
      operation_id: string;
      status: string;
      repo_ids: string[];
      layout_backend: string;
      logs: Array<{ stream: string; line: string }>;
      results: Array<{
        repo_id: string;
        layout_type: string;
        confidence: number;
        confidence_threshold: number;
        confidence_policy_status: string;
        manual_override_applied: boolean;
        dimensions: Array<Record<string, unknown>>;
        sample_markdown_paths: string[];
        detector_version: string;
      }>;
      started_at: string | null;
      finished_at: string | null;
    } | null;
    validate_only_operation: {
      operation_id: string;
      job_id: string;
      status: string;
      repo_ids: string[];
      mode: string;
      requested_mode: string;
      conversion_backend: string;
      prompt_registry_version: string;
      prompt_experiment_id: string;
      dry_run: boolean;
      force_full_reindex: boolean;
      request_id: string | null;
      idempotency_key: string | null;
      idempotency_scope: string | null;
      idempotency_reused: boolean;
      idempotency_expires_at: string | null;
      attempt_count: number;
      max_attempts: number;
      next_retry_at: string | null;
      last_error_kind: string | null;
      cancel_requested_at: string | null;
      cancelled_at: string | null;
      resumable: boolean;
      logs: Array<{ stream: string; line: string }>;
      results: IngestionResultSummary[];
      started_at: string | null;
      finished_at: string | null;
    } | null;
    warnings: string[];
  };
};

export type AdminKeyRecord = {
  key_id: string;
  key_prefix: string;
  owner_email?: string;
  is_superuser: boolean;
  enabled: boolean;
  product_scopes: string[];
  scopes: string[];
  source: string;
  effective_role: "viewer" | "operator" | "product-owner" | "superuser" | string;
  created_at: string;
  updated_at: string;
};

export type AdminKeyCreateResponse = {
  key: AdminKeyRecord;
  api_key: string;
};

export type AdminKeyAuditRecord = {
  audit_id: string;
  action: string;
  target_key_id: string;
  actor_key_id: string;
  request_id: string | null;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
};

export type CriticalEvent = {
  event_id: string;
  severity: "critical" | "high" | "warning" | string;
  event_type: "partial_publish" | "publish_blocked" | "ingestion_critical_fail" | string;
  message: string;
  details: Record<string, unknown>;
  created_at: string;
  product_ids: string[];
  sla: {
    target_minutes: number;
    deadline_at: string;
    remaining_minutes: number;
    overdue: boolean;
  };
  lifecycle: {
    status: "open" | "acknowledged" | "muted" | "snoozed" | "escalated" | "resolved" | string;
    effective_severity: "critical" | "high" | "warning" | string;
    owner: string | null;
    latest_action:
      | "acknowledge"
      | "mute"
      | "snooze"
      | "assign_owner"
      | "severity_override"
      | "escalate"
      | "resolved"
      | null
      | string;
    latest_action_at: string | null;
    action_count: number;
    muted_until: string | null;
    snoozed_until: string | null;
    escalation_recommended: boolean;
    escalation_reason: string | null;
    next_action_hint: string;
  };
  postmortem: {
    required: boolean;
    status: "ready" | "pending_resolution" | "not_required" | string;
    template_markdown: string | null;
  };
};

export type CriticalEventAction = {
  action_id: string;
  event_id: string;
  action:
    | "acknowledge"
    | "mute"
    | "snooze"
    | "assign_owner"
    | "severity_override"
    | "escalate"
    | "resolved"
    | string;
  actor_key_id: string;
  request_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type RegistryLanguage = {
  lang_id: string;
  display_name: string;
  enabled: boolean;
  created_at: string;
};

export type RegistryLocale = {
  locale_id: string;
  display_name: string;
  enabled: boolean;
  created_at: string;
};

export type RegistryAlias = {
  product_id: string;
  external_language_id: string;
  canonical_lang_id: string;
  created_at: string;
};

export type RetrievalSettings = {
  product_id: string;
  top_k: number;
  max_context_tokens: number;
  excerpt_char_limit: number;
  low_confidence_threshold: number;
  clarification_policy: string;
  updated_by: string;
  updated_at: string;
};

export type AnalyticsSlice = {
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
  refresh_lag_minutes: number;
};

export type ZeroResultCluster = {
  cluster_id: string;
  zero_result_reason: string;
  fallback_reason: string;
  retrieval_mode: string;
  primary_warning_code: string;
  total_requests: number;
  share_of_filtered_requests: number;
  affected_products: string[];
  affected_programming_languages: string[];
  affected_doc_locales: string[];
  sample_queries: string[];
  recommendation_title: string;
  recommendation_detail: string;
};

export type ZeroResultOverview = {
  filtered_requests_total: number;
  without_useful_result_requests: number;
  without_useful_result_share: number;
  no_result_requests: number;
  low_confidence_requests: number;
  by_zero_result_reason: Record<string, number>;
  by_fallback_reason: Record<string, number>;
  by_warning_code: Record<string, number>;
  by_retrieval_mode: Record<string, number>;
  top_affected_products: Record<string, number>;
  top_affected_programming_languages: Record<string, number>;
  clusters: ZeroResultCluster[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type CapacityForecastProduct = {
  product_id: string;
  recent_requests: number;
  previous_window_requests: number;
  projected_requests_next_24h: number;
  growth_ratio: number;
  zero_result_pressure_share: number;
  low_confidence_share: number;
  warning_density: number;
  coverage_saturation_score: number;
  saturation_risk: "low" | "medium" | "high" | string;
  recommended_action: string;
};

export type CapacityForecast = {
  filtered_requests_total: number;
  observed_window_hours: number;
  projected_requests_next_24h: number;
  previous_window_requests: number;
  growth_ratio: number;
  zero_result_pressure_share: number;
  low_confidence_share: number;
  warning_density: number;
  coverage_saturation_score: number;
  saturation_risk: "low" | "medium" | "high" | string;
  recommended_action: string;
  hottest_products: CapacityForecastProduct[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type UsefulnessSignal = {
  feedback_id: string;
  request_id: string;
  rating: string;
  reason_codes: string[];
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  endpoint: string;
  tool: string;
  raw_query: string;
  outcome: string;
  retrieval_mode: string | null;
  result_count: number;
  zero_result_reason: string | null;
  fallback_reason: string | null;
  warning_codes: string[];
  created_at: string;
  updated_at: string;
};

export type UsefulnessSummary = {
  total_feedback: number;
  useful_feedback: number;
  partially_useful_feedback: number;
  not_useful_feedback: number;
  useful_share: number;
  negative_share: number;
  by_rating: Record<string, number>;
  by_reason_code: Record<string, number>;
  by_product_id: Record<string, number>;
  by_programming_language: Record<string, number>;
  by_doc_locale: Record<string, number>;
  recent_negative_signals: UsefulnessSignal[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type IssueReviewSignal = {
  issue_id: string;
  request_id: string;
  issue_type: string;
  severity: "critical" | "warning" | "info" | string;
  severity_reason: string;
  recommendation_title: string;
  recommendation_detail: string;
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  endpoint: string;
  tool: string;
  raw_query: string;
  outcome: string;
  retrieval_mode: string | null;
  result_count: number;
  zero_result_reason: string | null;
  fallback_reason: string | null;
  warning_codes: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type IssueReviewSummary = {
  total_reports: number;
  by_issue_type: Record<string, number>;
  by_severity: Record<string, number>;
  by_product_id: Record<string, number>;
  by_programming_language: Record<string, number>;
  by_doc_locale: Record<string, number>;
  recommendation_mix: Record<string, number>;
  recent_reports: IssueReviewSignal[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type RequestEvidenceReplayInput = {
  query: string;
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  version: string | null;
  top_k: number;
  strict_version: boolean;
  include_examples: boolean;
  doc_types: string[];
  assumptions: string[];
};

export type RequestEvidenceOriginal = {
  request_id: string;
  endpoint: string;
  tool: string;
  raw_query: string;
  product_id: string | null;
  programming_language: string | null;
  doc_locale: string | null;
  confidence: number;
  outcome: string;
  retrieval_mode: string | null;
  result_count: number;
  zero_result_reason: string | null;
  fallback_reason: string | null;
  warning_codes: string[];
  created_at: string;
};

export type RequestEvidenceReplay = {
  executed_at: string;
  request: RequestEvidenceReplayInput;
  outcome: string;
  result_count: number;
  zero_result_reason: string | null;
  fallback_reason: string | null;
  response: PublicQueryDocsResponse;
};

export type RequestEvidenceDiff = {
  drift_status: string;
  summary: string;
  outcome_changed: boolean;
  original_outcome: string;
  current_outcome: string;
  result_count_delta: number;
  confidence_delta: number;
  warning_codes_added: string[];
  warning_codes_removed: string[];
  fallback_changed: boolean;
  original_fallback_reason: string | null;
  current_fallback_reason: string | null;
  zero_result_reason_changed: boolean;
  original_zero_result_reason: string | null;
  current_zero_result_reason: string | null;
  suspected_fault_domain: string;
  suspected_fault_reason: string;
  operator_hint: string;
  unavailable_original_fields: string[];
};

export type RequestEvidenceResponse = {
  request_id: string;
  original: RequestEvidenceOriginal;
  replay: RequestEvidenceReplay;
  diff: RequestEvidenceDiff;
  related_issue_reports: IssueReviewSignal[];
  related_usefulness_feedback: UsefulnessSignal[];
  copy_context: Record<string, unknown>;
  generated_at: string;
};

export type IssueHotspotCluster = {
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
};

export type IssueHotspotOverview = {
  filtered_reports_total: number;
  hotspots_total: number;
  by_priority: Record<string, number>;
  by_product_id: Record<string, number>;
  by_issue_type: Record<string, number>;
  by_severity: Record<string, number>;
  clusters: IssueHotspotCluster[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type PublicFunnelStage = {
  stage_id: string;
  title: string;
  sessions: number;
  share_of_filtered_sessions: number;
  conversion_from_previous: number | null;
};

export type PublicFunnelDropoff = {
  dropoff_id: string;
  stage_id: string;
  reason: string;
  sessions: number;
  share_of_filtered_sessions: number;
  recommendation_title: string;
  recommendation_detail: string;
};

export type PublicFunnelScope = {
  scope_id: string;
  product_id: string | null;
  programming_language: string | null;
  client_id: string | null;
  sessions: number;
  resolve_sessions: number;
  self_test_sessions: number;
  query_sessions: number;
  feedback_sessions: number;
  issue_sessions: number;
  zero_result_sessions: number;
  latest_activity_at: string;
};

export type PublicFunnelOverview = {
  filtered_sessions_total: number;
  by_product_id: Record<string, number>;
  by_programming_language: Record<string, number>;
  by_client_id: Record<string, number>;
  stages: PublicFunnelStage[];
  top_dropoffs: PublicFunnelDropoff[];
  scopes: PublicFunnelScope[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type FreshnessWatchlistScope = {
  scope_id: string;
  product_id: string;
  programming_language: string | null;
  source_kind: string;
  repo_id: string;
  risk_score: number;
  risk_level: string;
  primary_reason: string;
  recommended_action: string;
  stale_days: number | null;
  latest_active_snapshot_at: string | null;
  latest_active_version: string | null;
  newest_visible_version: string | null;
  release_visibility_gap: boolean;
  release_feature_signals: number;
  query_sessions_30d: number;
  no_result_sessions_30d: number;
  low_confidence_sessions_30d: number;
  issue_reports_30d: number;
  critical_issue_reports_30d: number;
  negative_feedback_30d: number;
  indexed_chunks_count: number;
  executable_snippets_count: number;
  parse_warnings_count: number;
  failed_items_count: number;
  service_status: string;
  service_status_reason: string;
  fix_plan: string[];
};

export type FreshnessWatchlistOverview = {
  filtered_scopes_total: number;
  high_risk_total: number;
  medium_risk_total: number;
  low_risk_total: number;
  by_product_id: Record<string, number>;
  by_programming_language: Record<string, number>;
  by_source_kind: Record<string, number>;
  status_summary: string;
  items: FreshnessWatchlistScope[];
  refreshed_at: string;
  refresh_lag_minutes: number;
};

export type AnalyticsSqlResult = {
  columns: string[];
  rows: Array<Array<unknown>>;
  row_count: number;
  truncated: boolean;
};

export type AnalyticsSqlExport = {
  filename: string;
  row_count: number;
  csv_payload: string;
};

export type ConfigHistoryEntry = {
  change_id: string;
  product_id: string;
  config_scope: string;
  config_key: string;
  action_type: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  actor_key_id: string;
  request_id: string | null;
  reason: string | null;
  rollback_of_change_id: string | null;
  created_at: string;
  artifact_path: string;
};

export type ConfigRollbackResult = {
  rolled_back_change_id: string;
  rollback_change_id: string;
  status: string;
};

export type QualityReviewApprovalMode = "human_approve_all" | "auto_approve";

export type QualityReviewPolicy = {
  product_id: string;
  sample_size: number;
  sampling_strategy: string;
  score_scale: string;
  threshold_score: number;
  approval_mode: QualityReviewApprovalMode;
  updated_by: string;
  updated_at: string;
};

export type QualityReviewRunSummary = {
  sampled_count: number;
  evaluated_count: number;
  overall_score: number;
  threshold_score: number;
  pass_gates: boolean;
};

export type QualityReviewScoreMatrixRow = {
  stratum: string;
  sampled_count: number;
  evaluated_count: number;
  avg_score: number | null;
  blocking_count: number;
};

export type QualityReviewBlockingFinding = {
  item_id: string;
  source_path: string;
  stratum: string;
  blocking_error_type:
    | "hallucinated_api_member"
    | "invalid_signature_or_parameters_or_returns"
    | "citation_or_source_path_loss";
  score: number;
  review_notes: string | null;
};

export type QualityReviewReviewerVote = {
  vote_id: string;
  run_id: string;
  reviewer_slot: "reviewer_1" | "reviewer_2" | "product_owner_tie_break" | string;
  actor_key_id: string | null;
  decision: "approve" | "reject" | string;
  notes: string | null;
  created_at: string;
};

export type QualityReviewApprovalTrail = {
  approval_id: string;
  run_id: string;
  actor_type: "agent" | "admin_key" | string;
  actor_key_id: string | null;
  action: "submit" | "approve_all" | "auto_approve" | "reject" | string;
  reason: string | null;
  request_id: string | null;
  created_at: string;
};

export type QualityReviewItem = {
  item_id: string;
  source_path: string;
  stratum: string;
  score: number;
  blocking_error_type:
    | "hallucinated_api_member"
    | "invalid_signature_or_parameters_or_returns"
    | "citation_or_source_path_loss"
    | null;
  review_notes: string | null;
  created_at: string;
};

export type QualityReviewRunOrigin = {
  source: string;
  request_id: string | null;
  issue_id: string | null;
  issue_type: string | null;
  severity: string | null;
  raw_query: string | null;
  suspected_fault_domain: string | null;
  suspected_fault_reason: string | null;
  recommendation_title: string | null;
  recommendation_detail: string | null;
};

export type QualityReviewGuidedFixStep = {
  step_id: string;
  title: string;
  detail: string;
  target_section: string;
  action_kind: string;
};

export type QualityReviewGuidedFixPlan = {
  summary: string;
  priority: string;
  owner_hint: string;
  next_step: string;
  actions: QualityReviewGuidedFixStep[];
};

export type QualityReviewRun = {
  run_id: string;
  product_id: string;
  version: string | null;
  source_revision: string;
  trigger_type: "major_change" | "manual" | string;
  status: "running" | "awaiting_approval" | "approved" | "rejected" | "blocked" | string;
  fail_fast_triggered: boolean;
  blocking_error_count: number;
  artifact_path: string;
  created_by: "agent" | "admin_key" | string;
  created_by_key_id: string | null;
  created_at: string;
  finished_at: string | null;
  policy: QualityReviewPolicy;
  summary: QualityReviewRunSummary;
  score_matrix: QualityReviewScoreMatrixRow[];
  blocking_findings: QualityReviewBlockingFinding[];
  reviewer_votes: QualityReviewReviewerVote[];
  approval_trail: QualityReviewApprovalTrail[];
  items: QualityReviewItem[];
  origin: QualityReviewRunOrigin | null;
  guided_fix_plan: QualityReviewGuidedFixPlan | null;
};

export type GuidedContentFixDraft = {
  request_id: string;
  issue_id: string | null;
  issue_type: string | null;
  severity: string | null;
  product_id: string;
  programming_language: string | null;
  doc_locale: string | null;
  source_revision: string;
  recommendation_title: string;
  recommendation_detail: string;
  quality_review_run: QualityReviewRun;
  fix_plan: QualityReviewGuidedFixPlan;
  generated_at: string;
};

export type QualityReviewPolicyPreset = {
  preset_id: string;
  display_name: string;
  description: string;
  sample_size: number;
  threshold_score: number;
  approval_mode: QualityReviewApprovalMode;
};

export type QualityReviewBatchActionItem = {
  run_id: string;
  status: "applied" | "failed";
  message: string | null;
  run: QualityReviewRun | null;
};

export type QualityReviewBatchActionResponse = {
  action: "approve_all" | "reject";
  requested_count: number;
  processed_count: number;
  applied_count: number;
  failed_count: number;
  results: QualityReviewBatchActionItem[];
};

export type QualityReviewRunDiff = {
  baseline_run_id: string;
  candidate_run_id: string;
  product_id: string;
  status_before: string;
  status_after: string;
  status_changed: boolean;
  overall_score_delta: number;
  threshold_delta: number;
  blocking_error_delta: number;
  pass_gates_before: boolean;
  pass_gates_after: boolean;
  approval_mode_before: QualityReviewApprovalMode;
  approval_mode_after: QualityReviewApprovalMode;
  approval_mode_changed: boolean;
  fail_fast_before: boolean;
  fail_fast_after: boolean;
  fail_fast_changed: boolean;
  source_revision_before: string;
  source_revision_after: string;
  source_revision_changed: boolean;
  blocking_findings_added: string[];
  blocking_findings_resolved: string[];
};

export type IndexStatusQdrantCollection = {
  total_points: number;
  products: Record<string, number>;
  error: string | null;
};

export type IndexStatusOpenSearchAlias = {
  total_docs: number;
  error: string | null;
};

export type IndexStatusSummary = {
  total_qdrant_points: number;
  total_opensearch_docs: number;
  products_with_docs: number;
  products_with_apiref: number;
};

export type IndexStatusResponse = {
  qdrant: Record<string, IndexStatusQdrantCollection>;
  opensearch: Record<string, IndexStatusOpenSearchAlias>;
  summary: IndexStatusSummary;
};

export class AdminApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const runtimeDefaultApiBase =
  typeof window === "undefined"
    ? "http://localhost:8080"
    : `${window.location.protocol}//${window.location.hostname}:8080`;
const API_BASE =
  process.env.NEXT_PUBLIC_ADCS_ADMIN_API_BASE?.replace(/\/$/, "") ?? runtimeDefaultApiBase;

export function getAdminApiBaseUrl(): string {
  return API_BASE;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Record<string, unknown> | undefined;
};

async function request<T>(path: string, apiKey = "", options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  // UI can use cookie-only auth mode and keeps this sentinel in component state.
  // Never forward it as x-api-key, otherwise browser may perform unnecessary preflight
  // requests and backend auth receives a meaningless key value.
  const normalizedApiKey = apiKey.trim();
  if (normalizedApiKey.length > 0 && normalizedApiKey !== "__cookie_session__") {
    headers["x-api-key"] = apiKey;
  }
  const requestInit: RequestInit = {
    method: options.method ?? "GET",
    headers,
    cache: "no-store",
    credentials: "include",
  };
  if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    requestInit.body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${path}`, requestInit);

  const rawBody = await response.text();
  const body = rawBody ? JSON.parse(rawBody) : {};
  if (!response.ok) {
    const message = body?.detail?.error?.message ?? `Request failed with status ${response.status}`;
    throw new AdminApiError(message, response.status);
  }

  return body as T;
}

export function fetchAdminSession(apiKey = ""): Promise<AdminSession> {
  return request<AdminSession>("/admin/v1/system/session", apiKey);
}

export function loginAdminSession(
  apiKey: string,
  rememberDevice = true,
): Promise<AdminSession> {
  return request<AdminSession>("/admin/v1/system/session/login", "", {
    method: "POST",
    body: { api_key: apiKey, remember_device: rememberDevice },
  });
}

export function logoutAdminSession(apiKey = ""): Promise<{ status: string }> {
  return request<{ status: string }>("/admin/v1/system/session/logout", apiKey, {
    method: "POST",
  });
}

export function fetchAdminSystemHealth(apiKey: string): Promise<AdminSystemHealth> {
  return request<AdminSystemHealth>("/admin/v1/system/health", apiKey);
}

export function fetchAdminIndexStatus(apiKey: string): Promise<IndexStatusResponse> {
  return request<IndexStatusResponse>("/admin/v1/index-status", apiKey);
}

export type ProductCoverageRow = {
  product_id: string;
  product_name: string;
  family: string;
  docs_chunks: number;
  apiref_symbols: number;
  docs_repo: string | null;
  apiref_repo: string | null;
  gaps: string[];
};

export type ProductCoverageSummary = {
  total_products: number;
  products_with_docs: number;
  products_with_apiref: number;
  products_fully_covered: number;
  total_docs_chunks: number;
  total_apiref_symbols: number;
};

export type ProductCoverageResponse = {
  rows: ProductCoverageRow[];
  summary: ProductCoverageSummary;
  generated_at: string;
  postgres_error: string | null;
};

export function fetchProductCoverage(apiKey: string): Promise<ProductCoverageResponse> {
  return request<ProductCoverageResponse>("/admin/v1/product-coverage", apiKey);
}

export function fetchAdminContentServicesOverview(
  apiKey: string,
): Promise<AdminContentServicesOverview> {
  return request<AdminContentServicesOverview>("/admin/v1/system/content-services", apiKey);
}

export function fetchAdminTopologyPolicy(apiKey: string): Promise<TopologyPolicyResponse> {
  return request<TopologyPolicyResponse>("/admin/v1/system/topology", apiKey);
}

export function fetchPublicStatus(filters: {
  product_id?: string;
  repo_id?: string;
} = {}): Promise<PublicStatusResponse> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.repo_id) {
    params.set("repo_id", filters.repo_id);
  }
  const query = params.toString();
  const path = query ? `/v1/status?${query}` : "/v1/status";
  return request<PublicStatusResponse>(path);
}

export function fetchPublicTopologyPolicy(): Promise<TopologyPolicyResponse> {
  return request<TopologyPolicyResponse>("/v1/topology");
}

// ----------------------------------------------------------------------------
// Status page
// ----------------------------------------------------------------------------

export interface StatusComponentRuntime {
  id: string;
  name: string;
  description: string;
  depends_on: string[];
  state: "operational" | "degraded" | "partial_outage" | "major_outage" | "unknown";
  note: string;
}

export interface StatusIncidentUpdate {
  timestamp: string;
  state:
    | "investigating"
    | "identified"
    | "monitoring"
    | "resolved"
    | "scheduled"
    | "in_progress";
  message: string;
}

export interface StatusIncident {
  id: string;
  title: string;
  severity: "sev1" | "sev2" | "sev3" | "sev4";
  affected_components: string[];
  started_at: string;
  resolved_at: string | null;
  public_message: string;
  updates: StatusIncidentUpdate[];
}

export interface StatusMaintenanceWindow {
  id: string;
  title: string;
  affected_components: string[];
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string | null;
  actual_end: string | null;
  public_message: string;
}

export interface StatusAnnouncement {
  id: string;
  title: string;
  severity: "info" | "warning" | "critical";
  posted_at: string;
  expires_at: string | null;
  body: string;
}

export interface PublicStatusPageResponse {
  overall_state: "operational" | "degraded" | "partial_outage" | "major_outage";
  overall_message: string;
  components: StatusComponentRuntime[];
  active_incidents: StatusIncident[];
  recent_incidents: StatusIncident[];
  upcoming_maintenance: StatusMaintenanceWindow[];
  active_maintenance: StatusMaintenanceWindow[];
  announcements: StatusAnnouncement[];
  generated_at: string;
  config_version: string;
}

export function fetchPublicStatusPage(): Promise<PublicStatusPageResponse> {
  return request<PublicStatusPageResponse>("/v1/status/page");
}

export function fetchPublicMCPConfigExport(filters: {
  product_id?: string;
  transport?: "streamable-http" | "sse";
} = {}): Promise<PublicMCPConfigExport> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.transport) {
    params.set("transport", filters.transport);
  }
  const query = params.toString();
  const path = query ? `/v1/integrations/mcp-configs?${query}` : "/v1/integrations/mcp-configs";
  return request<PublicMCPConfigExport>(path);
}

export function fetchPublicMCPSelfTest(filters: {
  product_id: string;
  programming_language?: string;
  client_id?: "cursor" | "claude-desktop" | "qwen-code" | "vscode";
  transport?: "streamable-http" | "sse";
}): Promise<PublicMCPSelfTest> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.client_id) {
    params.set("client_id", filters.client_id);
  }
  if (filters.transport) {
    params.set("transport", filters.transport);
  }
  return request<PublicMCPSelfTest>(`/v1/integrations/self-test?${params.toString()}`);
}

export function resolvePublicProduct(query: string): Promise<PublicResolvedProduct> {
  return request<PublicResolvedProduct>("/v1/products:resolve", "", {
    method: "POST",
    body: { query },
  });
}

export function queryPublicDocs(payload: {
  query: string;
  product_id?: string;
  language?: string;
  version?: string;
  query_locale?: string;
  top_k?: number;
  strict_version?: boolean;
  doc_types?: string[];
  include_examples?: boolean;
  debug?: boolean;
}): Promise<PublicQueryDocsResponse> {
  return request<PublicQueryDocsResponse>("/v1/docs:query", "", {
    method: "POST",
    body: payload,
  });
}

export function submitPublicQueryFeedback(payload: {
  request_id: string;
  rating: string;
  reason_codes?: string[];
}): Promise<PublicQueryFeedbackResponse> {
  return request<PublicQueryFeedbackResponse>("/v1/docs:feedback", "", {
    method: "POST",
    body: payload,
  });
}

export function submitPublicQueryIssue(payload: {
  request_id: string;
  issue_type: string;
  notes?: string;
}): Promise<PublicQueryIssueResponse> {
  return request<PublicQueryIssueResponse>("/v1/docs:issues", "", {
    method: "POST",
    body: payload,
  });
}

export function fetchPublicQueryReproPack(filters: {
  request_id: string;
}): Promise<PublicQueryReproPack> {
  const params = new URLSearchParams();
  params.set("request_id", filters.request_id);
  return request<PublicQueryReproPack>(`/v1/docs:repro-pack?${params.toString()}`);
}

export function getPublicSymbolDoc(payload: {
  product_id: string;
  language: string;
  version?: string;
  symbol_fqn: string;
}): Promise<PublicSymbolDocResponse> {
  return request<PublicSymbolDocResponse>("/v1/symbols:get", "", {
    method: "POST",
    body: payload,
  });
}

export function fetchPublicReleaseFreshness(filters: {
  product_id: string;
  programming_language?: string;
  version?: string;
  top_k?: number;
}): Promise<PublicReleaseFreshness> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.version) {
    params.set("version", filters.version);
  }
  if (typeof filters.top_k === "number") {
    params.set("top_k", String(filters.top_k));
  }
  return request<PublicReleaseFreshness>(`/v1/integrations/freshness?${params.toString()}`);
}

export function fetchPublicReleaseAdoption(filters: {
  product_id: string;
  programming_language: string;
  version?: string;
}): Promise<PublicReleaseAdoption> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  params.set("programming_language", filters.programming_language);
  if (filters.version) {
    params.set("version", filters.version);
  }
  return request<PublicReleaseAdoption>(`/v1/integrations/release-adoption?${params.toString()}`);
}

export function fetchPublicUseCaseGallery(filters: {
  product_id: string;
  programming_language?: string;
  client_id?: string;
  status?: string;
}): Promise<PublicUseCaseGallery> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.client_id) {
    params.set("client_id", filters.client_id);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  return request<PublicUseCaseGallery>(`/v1/integrations/use-cases?${params.toString()}`);
}

export function fetchPublicBreakingChanges(payload: {
  product_id: string;
  language: string;
  from_version: string;
  to_version: string;
  page?: number;
  page_size?: number;
}): Promise<PublicBreakingChangesResponse> {
  return request<PublicBreakingChangesResponse>("/v1/changes:list", "", {
    method: "POST",
    body: payload,
  });
}

export function fetchPublicLatestReleaseFeatures(payload: {
  product_id: string;
  language: string;
  version?: string;
  top_k?: number;
}): Promise<PublicLatestReleaseFeaturesResponse> {
  return request<PublicLatestReleaseFeaturesResponse>("/v1/releases:latest", "", {
    method: "POST",
    body: payload,
  });
}

export function fetchPublicContentTriage(filters?: {
  product_id?: string;
  repo_id?: string;
  severity?: string;
  source_kind?: string;
  stale_after_days?: number;
  limit?: number;
}): Promise<PublicContentTriage> {
  const params = new URLSearchParams();
  if (filters?.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters?.repo_id) {
    params.set("repo_id", filters.repo_id);
  }
  if (filters?.severity) {
    params.set("severity", filters.severity);
  }
  if (filters?.source_kind) {
    params.set("source_kind", filters.source_kind);
  }
  if (typeof filters?.stale_after_days === "number") {
    params.set("stale_after_days", String(filters.stale_after_days));
  }
  if (typeof filters?.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request<PublicContentTriage>(
    query ? `/v1/integrations/triage?${query}` : "/v1/integrations/triage",
  );
}

export function fetchPublicStarterPacks(filters?: {
  product_id?: string;
  programming_language?: string;
  transport?: string;
}): Promise<PublicStarterPacks> {
  const params = new URLSearchParams();
  if (filters?.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters?.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters?.transport) {
    params.set("transport", filters.transport);
  }
  const query = params.toString();
  return request<PublicStarterPacks>(
    query ? `/v1/integrations/starter-packs?${query}` : "/v1/integrations/starter-packs",
  );
}

export function fetchPublicCoverageGapTracker(filters?: {
  product_id?: string;
  programming_language?: string;
  source_kind?: string;
  version?: string;
}): Promise<PublicCoverageGapTracker> {
  const params = new URLSearchParams();
  if (filters?.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters?.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters?.source_kind) {
    params.set("source_kind", filters.source_kind);
  }
  if (filters?.version) {
    params.set("version", filters.version);
  }
  const query = params.toString();
  return request<PublicCoverageGapTracker>(
    query ? `/v1/integrations/coverage-gaps?${query}` : "/v1/integrations/coverage-gaps",
  );
}

export function fetchPublicCoverageNavigator(filters?: {
  product_id?: string;
  programming_language?: string;
  source_kind?: string;
  version?: string;
}): Promise<PublicCoverageNavigator> {
  const params = new URLSearchParams();
  if (filters?.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters?.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters?.source_kind) {
    params.set("source_kind", filters.source_kind);
  }
  if (filters?.version) {
    params.set("version", filters.version);
  }
  const query = params.toString();
  return request<PublicCoverageNavigator>(
    query
      ? `/v1/integrations/coverage-navigator?${query}`
      : "/v1/integrations/coverage-navigator",
  );
}

export function fetchPublicTrustSignalsBoard(filters: {
  product_id: string;
  programming_language?: string;
  version?: string;
}): Promise<PublicTrustSignalsBoard> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.version) {
    params.set("version", filters.version);
  }
  return request<PublicTrustSignalsBoard>(
    `/v1/integrations/trust-signals?${params.toString()}`,
  );
}

export function fetchPublicScopeCompareBoard(filters: {
  left_product_id: string;
  left_programming_language?: string;
  left_version?: string;
  left_source_kind?: string;
  right_product_id: string;
  right_programming_language?: string;
  right_version?: string;
  right_source_kind?: string;
}): Promise<PublicScopeCompareBoard> {
  const params = new URLSearchParams();
  params.set("left_product_id", filters.left_product_id);
  params.set("right_product_id", filters.right_product_id);
  if (filters.left_programming_language) {
    params.set("left_programming_language", filters.left_programming_language);
  }
  if (filters.left_version) {
    params.set("left_version", filters.left_version);
  }
  if (filters.left_source_kind) {
    params.set("left_source_kind", filters.left_source_kind);
  }
  if (filters.right_programming_language) {
    params.set("right_programming_language", filters.right_programming_language);
  }
  if (filters.right_version) {
    params.set("right_version", filters.right_version);
  }
  if (filters.right_source_kind) {
    params.set("right_source_kind", filters.right_source_kind);
  }
  return request<PublicScopeCompareBoard>(
    `/v1/integrations/compare-board?${params.toString()}`,
  );
}

export function fetchPublicCapabilityExplorer(filters?: {
  product_id?: string;
  programming_language?: string;
  source_kind?: string;
  version?: string;
}): Promise<PublicCapabilityExplorer> {
  const params = new URLSearchParams();
  if (filters?.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters?.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters?.source_kind) {
    params.set("source_kind", filters.source_kind);
  }
  if (filters?.version) {
    params.set("version", filters.version);
  }
  const query = params.toString();
  return request<PublicCapabilityExplorer>(
    query ? `/v1/integrations/capabilities?${query}` : "/v1/integrations/capabilities",
  );
}

export function fetchPublicTroubleshooting(filters: {
  product_id: string;
  programming_language?: string;
  client_id?: "cursor" | "claude-desktop" | "qwen-code" | "vscode";
  transport?: "streamable-http" | "sse";
  request_id?: string;
}): Promise<PublicTroubleshooting> {
  const params = new URLSearchParams();
  params.set("product_id", filters.product_id);
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.client_id) {
    params.set("client_id", filters.client_id);
  }
  if (filters.transport) {
    params.set("transport", filters.transport);
  }
  if (filters.request_id) {
    params.set("request_id", filters.request_id);
  }
  return request<PublicTroubleshooting>(`/v1/integrations/troubleshooting?${params.toString()}`);
}

export function fetchPublicSnippetExplorer(filters: {
  product_id?: string;
  programming_language?: string;
  version?: string;
  source_kind?: string;
  limit?: number;
} = {}): Promise<PublicSnippetExplorer> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.version) {
    params.set("version", filters.version);
  }
  if (filters.source_kind) {
    params.set("source_kind", filters.source_kind);
  }
  if (typeof filters.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  const path = query ? `/v1/snippets?${query}` : "/v1/snippets";
  return request<PublicSnippetExplorer>(path);
}

export function fetchPublicHowToArticles(): Promise<PublishedHowToListResponse> {
  return request<PublishedHowToListResponse>("/v1/howto/articles");
}

export function fetchAdminObservabilitySummary(apiKey: string): Promise<AdminObservabilitySummary> {
  return request<AdminObservabilitySummary>("/admin/v1/observability/summary", apiKey);
}

export function fetchAbuseGuardSettings(apiKey: string): Promise<AbuseGuardSettings> {
  return request<AbuseGuardSettings>("/admin/v1/settings/public-api/abuse-guard", apiKey);
}

export function fetchAdminHowToArticles(
  apiKey: string,
): Promise<HowToOverrideListResponse> {
  return request<HowToOverrideListResponse>("/admin/v1/howto/articles", apiKey);
}

export function fetchAdminHowToArticle(
  apiKey: string,
  articleId: string,
): Promise<HowToOverrideEnvelope> {
  return request<HowToOverrideEnvelope>(
    `/admin/v1/howto/articles/${encodeURIComponent(articleId)}`,
    apiKey,
  );
}

export function saveAdminHowToDraft(
  apiKey: string,
  articleId: string,
  payload: HowToOverridePayload,
): Promise<HowToOverrideEnvelope> {
  return request<HowToOverrideEnvelope>(
    `/admin/v1/howto/articles/${encodeURIComponent(articleId)}/draft`,
    apiKey,
    {
      method: "PUT",
      body: payload as unknown as Record<string, unknown>,
    },
  );
}

export function publishAdminHowToDraft(
  apiKey: string,
  articleId: string,
): Promise<HowToOverrideEnvelope> {
  return request<HowToOverrideEnvelope>(
    `/admin/v1/howto/articles/${encodeURIComponent(articleId)}:publish`,
    apiKey,
    { method: "POST" },
  );
}

export function resetAdminHowToDraft(
  apiKey: string,
  articleId: string,
): Promise<HowToOverrideEnvelope> {
  return request<HowToOverrideEnvelope>(
    `/admin/v1/howto/articles/${encodeURIComponent(articleId)}:reset-draft`,
    apiKey,
    { method: "POST" },
  );
}

export function clearAdminHowToPublished(
  apiKey: string,
  articleId: string,
): Promise<HowToOverrideEnvelope> {
  return request<HowToOverrideEnvelope>(
    `/admin/v1/howto/articles/${encodeURIComponent(articleId)}:clear-published`,
    apiKey,
    { method: "POST" },
  );
}

export function uploadAdminHowToAsset(
  apiKey: string,
  payload: { filename: string; content_base64: string },
): Promise<HowToAssetUploadResponse> {
  return request<HowToAssetUploadResponse>("/admin/v1/howto/assets:upload", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function patchAbuseGuardSettings(
  apiKey: string,
  payload: {
    mode?: "observe-only" | "enforce";
    allowlist?: string[];
    requests_per_ip_per_minute?: number;
    requests_per_fingerprint_per_minute?: number;
    requests_global_per_minute?: number;
    debug_header_enabled?: boolean;
  },
): Promise<AbuseGuardSettings> {
  return request<AbuseGuardSettings>("/admin/v1/settings/public-api/abuse-guard", apiKey, {
    method: "PATCH",
    body: payload,
  });
}

export function fetchIngestionJobs(
  apiKey: string,
  limit = 20,
): Promise<IngestionJobOperation[]> {
  return request<IngestionJobOperation[]>(`/admin/v1/ingestion/jobs?limit=${limit}`, apiKey);
}

export function fetchReviewArtifactPreview(
  apiKey: string,
  payload: { artifact_path: string },
): Promise<ReviewArtifactPreview> {
  return request<ReviewArtifactPreview>("/admin/v1/source-repositories/review-artifact:preview", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchRawMarkdownPreview(
  apiKey: string,
  payload: { source_path: string },
): Promise<RawMarkdownPreview> {
  return request<RawMarkdownPreview>("/admin/v1/source-repositories/raw-markdown:preview", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchStagingManifestPreview(
  apiKey: string,
  payload: {
    manifest_path: string;
    max_documents?: number;
    max_chunk_objects?: number;
    max_chunk_records_per_object?: number;
  },
): Promise<StagingManifestPreview> {
  return request<StagingManifestPreview>("/admin/v1/source-repositories/staging-manifest:preview", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function triggerIngestionRun(
  apiKey: string,
  payload: {
    mode: "publish" | "validate_only";
    repo_id?: string;
    partial_publish_threshold_pct?: number;
  },
): Promise<IngestionJobOperation> {
  return request<IngestionJobOperation>("/admin/v1/ingestion/trigger", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchSnapshots(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    version?: string;
    limit?: number;
  } = {},
): Promise<SnapshotRecord[]> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.programming_language) {
    params.set("programming_language", filters.programming_language);
  }
  if (filters.version) {
    params.set("version", filters.version);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  const path = query ? `/admin/v1/snapshots?${query}` : "/admin/v1/snapshots";
  return request<SnapshotRecord[]>(path, apiKey);
}

export function fetchActiveSnapshot(
  apiKey: string,
  filters: {
    product_id: string;
    programming_language: string;
    version: string;
  },
): Promise<SnapshotRecord> {
  const params = new URLSearchParams({
    product_id: filters.product_id,
    programming_language: filters.programming_language,
    version: filters.version,
  });
  return request<SnapshotRecord>(`/admin/v1/snapshots/active?${params.toString()}`, apiKey);
}

export function promoteSnapshot(apiKey: string, snapshotId: string): Promise<SnapshotRecord> {
  return request<SnapshotRecord>(`/admin/v1/snapshots/${encodeURIComponent(snapshotId)}:promote`, apiKey, {
    method: "POST",
  });
}

export function compareSnapshots(
  apiKey: string,
  payload: {
    base_snapshot_id: string;
    target_snapshot_id: string;
  },
): Promise<SnapshotCompareResult> {
  const params = new URLSearchParams({
    base_snapshot_id: payload.base_snapshot_id,
    target_snapshot_id: payload.target_snapshot_id,
  });
  return request<SnapshotCompareResult>(`/admin/v1/snapshots:compare?${params.toString()}`, apiKey);
}

export function issueSnapshotRollbackConfirmation(
  apiKey: string,
  snapshotId: string,
  payload: { reason: string },
): Promise<SnapshotRollbackConfirmation> {
  return request<SnapshotRollbackConfirmation>(
    `/admin/v1/snapshots/${encodeURIComponent(snapshotId)}:rollback-confirmation`,
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function rollbackSnapshot(
  apiKey: string,
  snapshotId: string,
  payload: { reason: string; confirm_token: string },
): Promise<SnapshotRollbackExecutionResult> {
  return request<SnapshotRollbackExecutionResult>(
    `/admin/v1/snapshots/${encodeURIComponent(snapshotId)}:rollback`,
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function fetchSnapshotRollbackAudit(
  apiKey: string,
  filters: { limit?: number; product_id?: string } = {},
): Promise<SnapshotRollbackAuditRecord[]> {
  const params = new URLSearchParams();
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/snapshots:rollback-audit?${query}`
    : "/admin/v1/snapshots:rollback-audit";
  return request<SnapshotRollbackAuditRecord[]>(path, apiKey);
}

export function previewSnapshotCleanup(
  apiKey: string,
  payload: {
    product_id: string;
    programming_language?: string;
    version?: string;
    source_kind?: string;
  },
): Promise<SnapshotCleanupPreviewResult> {
  return request<SnapshotCleanupPreviewResult>("/admin/v1/snapshots:cleanup-preview", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function executeSnapshotCleanup(
  apiKey: string,
  payload: {
    product_id: string;
    programming_language?: string;
    version?: string;
    source_kind?: string;
    reason: string;
  },
): Promise<SnapshotCleanupExecutionResult> {
  return request<SnapshotCleanupExecutionResult>("/admin/v1/snapshots:cleanup", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchSnapshotCleanupHistory(
  apiKey: string,
  filters: { limit?: number; product_id?: string } = {},
): Promise<SnapshotCleanupAuditRecord[]> {
  const params = new URLSearchParams();
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/snapshots:cleanup-history?${query}`
    : "/admin/v1/snapshots:cleanup-history";
  return request<SnapshotCleanupAuditRecord[]>(path, apiKey);
}

export function fetchProducts(apiKey: string, limit = 200): Promise<ProductRecord[]> {
  return request<ProductRecord[]>(`/admin/v1/products?limit=${limit}`, apiKey);
}

export function onboardSourceRepositoriesProduct(
  apiKey: string,
  payload: SourceRepositoriesOnboardProductRequest,
): Promise<SourceRepositoriesOnboardProductResponse> {
  return request<SourceRepositoriesOnboardProductResponse>(
    "/admin/v1/source-repositories/onboard-product",
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function fetchAdminKeys(apiKey: string): Promise<AdminKeyRecord[]> {
  return request<AdminKeyRecord[]>("/admin/v1/keys", apiKey);
}

export function createAdminKey(
  apiKey: string,
  payload: {
    is_superuser: boolean;
    enabled: boolean;
    product_scopes: string[];
    scopes: string[];
    reason?: string;
    owner_email?: string;
  },
): Promise<AdminKeyCreateResponse> {
  return request<AdminKeyCreateResponse>("/admin/v1/keys", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function disableAdminKey(
  apiKey: string,
  keyId: string,
  reason?: string,
): Promise<AdminKeyRecord> {
  return request<AdminKeyRecord>(`/admin/v1/keys/${encodeURIComponent(keyId)}:disable`, apiKey, {
    method: "POST",
    body: reason ? { reason } : {},
  });
}

export function enableAdminKey(
  apiKey: string,
  keyId: string,
  reason?: string,
): Promise<AdminKeyRecord> {
  return request<AdminKeyRecord>(`/admin/v1/keys/${encodeURIComponent(keyId)}:enable`, apiKey, {
    method: "POST",
    body: reason ? { reason } : {},
  });
}

export function updateAdminKeyScopes(
  apiKey: string,
  keyId: string,
  payload: { product_scopes: string[]; scopes: string[]; reason?: string },
): Promise<AdminKeyRecord> {
  return request<AdminKeyRecord>(`/admin/v1/keys/${encodeURIComponent(keyId)}/scopes`, apiKey, {
    method: "PATCH",
    body: payload,
  });
}

export function fetchAdminKeyAudit(
  apiKey: string,
  limit = 100,
): Promise<AdminKeyAuditRecord[]> {
  return request<AdminKeyAuditRecord[]>(`/admin/v1/keys/audit?limit=${limit}`, apiKey);
}

export function rotateAdminKey(
  apiKey: string,
  keyId: string,
): Promise<AdminKeyCreateResponse> {
  return request<AdminKeyCreateResponse>(
    `/admin/v1/keys/${encodeURIComponent(keyId)}:rotate`,
    apiKey,
    { method: "POST", body: {} },
  );
}

export function exportAdminKeys(apiKey: string): Promise<AdminKeyRecord[]> {
  return request<AdminKeyRecord[]>("/admin/v1/keys:export", apiKey);
}

export function importAdminKeys(
  apiKey: string,
  keys: AdminKeyRecord[],
): Promise<{ imported: number }> {
  return request<{ imported: number }>("/admin/v1/keys:import", apiKey, {
    method: "POST",
    body: { keys },
  });
}

export function fetchCriticalEvents(apiKey: string, limit = 50): Promise<CriticalEvent[]> {
  return request<CriticalEvent[]>(`/admin/v1/events/critical?limit=${limit}`, apiKey);
}

export function fetchCriticalEventActions(
  apiKey: string,
  limit = 50,
): Promise<CriticalEventAction[]> {
  return request<CriticalEventAction[]>(`/admin/v1/events/critical/actions?limit=${limit}`, apiKey);
}

export function postCriticalEventAction(
  apiKey: string,
  eventId: string,
  action:
    | "acknowledge"
    | "mute"
    | "snooze"
    | "assign"
    | "severity-override"
    | "escalate"
    | "resolve",
  payload: Record<string, unknown>,
): Promise<CriticalEventAction> {
  return request<CriticalEventAction>(`/admin/v1/events/critical/${eventId}:${action}`, apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchRegistryLanguages(apiKey: string): Promise<RegistryLanguage[]> {
  return request<RegistryLanguage[]>("/admin/v1/registries/languages", apiKey);
}

export function createRegistryLanguage(
  apiKey: string,
  payload: { lang_id: string; display_name: string; enabled: boolean },
): Promise<RegistryLanguage> {
  return request<RegistryLanguage>("/admin/v1/registries/languages", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function deleteRegistryLanguage(
  apiKey: string,
  langId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/admin/v1/registries/languages?lang_id=${encodeURIComponent(langId)}`,
    apiKey,
    { method: "DELETE" },
  );
}

export function fetchRegistryLocales(apiKey: string): Promise<RegistryLocale[]> {
  return request<RegistryLocale[]>("/admin/v1/registries/locales", apiKey);
}

export function createRegistryLocale(
  apiKey: string,
  payload: { locale_id: string; display_name: string; enabled: boolean },
): Promise<RegistryLocale> {
  return request<RegistryLocale>("/admin/v1/registries/locales", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function deleteRegistryLocale(
  apiKey: string,
  localeId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/admin/v1/registries/locales?locale_id=${encodeURIComponent(localeId)}`,
    apiKey,
    { method: "DELETE" },
  );
}

export function fetchRegistryAliases(
  apiKey: string,
  productId?: string,
): Promise<RegistryAlias[]> {
  const query = productId ? `?product_id=${encodeURIComponent(productId)}` : "";
  return request<RegistryAlias[]>(`/admin/v1/registries/languages/aliases${query}`, apiKey);
}

export function createRegistryAlias(
  apiKey: string,
  payload: {
    product_id: string;
    external_language_id: string;
    canonical_lang_id: string;
  },
): Promise<RegistryAlias> {
  return request<RegistryAlias>("/admin/v1/registries/languages/aliases", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function deleteRegistryAlias(
  apiKey: string,
  productId: string,
  externalLanguageId: string,
): Promise<{ deleted: boolean }> {
  const query = new URLSearchParams({
    product_id: productId,
    external_language_id: externalLanguageId,
  });
  return request<{ deleted: boolean }>(
    `/admin/v1/registries/languages/aliases?${query.toString()}`,
    apiKey,
    { method: "DELETE" },
  );
}

export function fetchRetrievalSettings(
  apiKey: string,
  productId: string,
): Promise<RetrievalSettings> {
  return request<RetrievalSettings>(
    `/admin/v1/settings/retrieval/${encodeURIComponent(productId)}`,
    apiKey,
  );
}

export function patchRetrievalSettings(
  apiKey: string,
  productId: string,
  payload: {
    top_k: number;
    max_context_tokens: number;
    excerpt_char_limit: number;
    low_confidence_threshold: number;
    clarification_policy: string;
  },
): Promise<RetrievalSettings> {
  return request<RetrievalSettings>(
    `/admin/v1/settings/retrieval/${encodeURIComponent(productId)}`,
    apiKey,
    {
      method: "PATCH",
      body: payload,
    },
  );
}

export function fetchAnalyticsSlices(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    hashed_ip?: string;
    fingerprint?: string;
    outcome?: string;
    retrieval_mode?: string;
    zero_result_reason?: string;
    fallback_reason?: string;
    warning_code?: string;
  } = {},
): Promise<AnalyticsSlice> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  const path = query ? `/admin/v1/analytics/slices?${query}` : "/admin/v1/analytics/slices";
  return request<AnalyticsSlice>(path, apiKey);
}

export function fetchZeroResultOverview(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    hashed_ip?: string;
    fingerprint?: string;
    outcome?: string;
    retrieval_mode?: string;
    zero_result_reason?: string;
    fallback_reason?: string;
    warning_code?: string;
  } = {},
): Promise<ZeroResultOverview> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/zero-results?${query}`
    : "/admin/v1/analytics/zero-results";
  return request<ZeroResultOverview>(path, apiKey);
}

export function fetchCapacityForecast(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    hashed_ip?: string;
    fingerprint?: string;
    outcome?: string;
    retrieval_mode?: string;
    zero_result_reason?: string;
    fallback_reason?: string;
    warning_code?: string;
  } = {},
): Promise<CapacityForecast> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/capacity-forecast?${query}`
    : "/admin/v1/analytics/capacity-forecast";
  return request<CapacityForecast>(path, apiKey);
}

export function fetchUsefulnessSummary(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    rating?: string;
    reason_code?: string;
  } = {},
): Promise<UsefulnessSummary> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/usefulness?${query}`
    : "/admin/v1/analytics/usefulness";
  return request<UsefulnessSummary>(path, apiKey);
}

export function fetchUsefulnessSignals(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    rating?: string;
    reason_code?: string;
    request_id?: string;
    negative_only?: boolean;
    limit?: number;
  } = {},
): Promise<UsefulnessSignal[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/usefulness-signals?${query}`
    : "/admin/v1/analytics/usefulness-signals";
  return request<UsefulnessSignal[]>(path, apiKey);
}

export function fetchIssueReviewSummary(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    issue_type?: string;
    severity?: string;
    request_id?: string;
  } = {},
): Promise<IssueReviewSummary> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query ? `/admin/v1/analytics/issues?${query}` : "/admin/v1/analytics/issues";
  return request<IssueReviewSummary>(path, apiKey);
}

export function fetchIssueReviewSignals(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    issue_type?: string;
    severity?: string;
    request_id?: string;
    limit?: number;
  } = {},
): Promise<IssueReviewSignal[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/issue-signals?${query}`
    : "/admin/v1/analytics/issue-signals";
  return request<IssueReviewSignal[]>(path, apiKey);
}

export function fetchRequestEvidence(
  apiKey: string,
  filters: {
    request_id: string;
  },
): Promise<RequestEvidenceResponse> {
  const params = new URLSearchParams();
  params.set("request_id", filters.request_id);
  return request<RequestEvidenceResponse>(
    `/admin/v1/analytics/request-evidence?${params.toString()}`,
    apiKey,
  );
}

export function createGuidedContentFixDraft(
  apiKey: string,
  payload: {
    request_id: string;
    issue_id?: string;
  },
): Promise<GuidedContentFixDraft> {
  return request<GuidedContentFixDraft>("/admin/v1/analytics/request-evidence:create-fix-draft", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchIssueHotspots(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    endpoint?: string;
    tool?: string;
    issue_type?: string;
    severity?: string;
    request_id?: string;
    limit?: number;
  } = {},
): Promise<IssueHotspotOverview> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/issue-hotspots?${query}`
    : "/admin/v1/analytics/issue-hotspots";
  return request<IssueHotspotOverview>(path, apiKey);
}

export function fetchPublicAdoptionFunnel(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    doc_locale?: string;
    client_id?: string;
    limit?: number;
  } = {},
): Promise<PublicFunnelOverview> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/public-funnel?${query}`
    : "/admin/v1/analytics/public-funnel";
  return request<PublicFunnelOverview>(path, apiKey);
}

export function fetchFreshnessWatchlist(
  apiKey: string,
  filters: {
    product_id?: string;
    programming_language?: string;
    source_kind?: string;
    issue_window_days?: number;
    stale_after_days?: number;
    limit?: number;
  } = {},
): Promise<FreshnessWatchlistOverview> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  const path = query
    ? `/admin/v1/analytics/freshness-watchlist?${query}`
    : "/admin/v1/analytics/freshness-watchlist";
  return request<FreshnessWatchlistOverview>(path, apiKey);
}

export function queryAnalyticsSql(
  apiKey: string,
  payload: { sql: string; max_rows: number },
): Promise<AnalyticsSqlResult> {
  return request<AnalyticsSqlResult>("/admin/v1/analytics/sql:query", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function exportAnalyticsSql(
  apiKey: string,
  payload: { sql: string; max_rows: number },
): Promise<AnalyticsSqlExport> {
  return request<AnalyticsSqlExport>("/admin/v1/analytics/sql:export", apiKey, {
    method: "POST",
    body: payload,
  });
}

// ---------------------------------------------------------------------------
// SQL Explorer schema
// ---------------------------------------------------------------------------

export type AnalyticsSqlSchemaColumn = {
  name: string;
  data_type: string;
  description?: string | null;
};

export type AnalyticsSqlSchemaTable = {
  name: string;
  description: string;
  columns: AnalyticsSqlSchemaColumn[];
  sample_query: string;
};

export type AnalyticsSqlSchemaResponse = {
  tables: AnalyticsSqlSchemaTable[];
  blocked_tables: string[];
  blocked_column_patterns: string[];
  notes: string[];
};

export function fetchAnalyticsSqlSchema(apiKey: string): Promise<AnalyticsSqlSchemaResponse> {
  return request<AnalyticsSqlSchemaResponse>("/admin/v1/analytics/sql:schema", apiKey);
}

export function fetchConfigHistory(
  apiKey: string,
  filters: {
    product_id?: string;
    config_scope?: string;
    limit?: number;
  } = {},
): Promise<ConfigHistoryEntry[]> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.config_scope) {
    params.set("config_scope", filters.config_scope);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  const path = query ? `/admin/v1/config/history?${query}` : "/admin/v1/config/history";
  return request<ConfigHistoryEntry[]>(path, apiKey);
}

export function rollbackConfigChange(
  apiKey: string,
  payload: { change_id: string; reason?: string },
): Promise<ConfigRollbackResult> {
  return request<ConfigRollbackResult>("/admin/v1/config/rollback", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function fetchQualityReviewRuns(
  apiKey: string,
  filters: {
    product_id?: string;
    limit?: number;
  } = {},
): Promise<QualityReviewRun[]> {
  const params = new URLSearchParams();
  if (filters.product_id) {
    params.set("product_id", filters.product_id);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  const path = query ? `/admin/v1/quality-reviews/runs?${query}` : "/admin/v1/quality-reviews/runs";
  return request<QualityReviewRun[]>(path, apiKey);
}

export function createQualityReviewRun(
  apiKey: string,
  payload: {
    product_id: string;
    version?: string;
    source_revision: string;
    trigger_type?: "major_change" | "manual";
    items: Array<{
      source_path: string;
      stratum: string;
      simulated_score?: number;
      simulated_blocking_error_type?:
        | "hallucinated_api_member"
        | "invalid_signature_or_parameters_or_returns"
        | "citation_or_source_path_loss";
      review_notes?: string;
    }>;
  },
): Promise<QualityReviewRun> {
  return request<QualityReviewRun>("/admin/v1/quality-reviews/runs", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function approveAllQualityReviewRun(apiKey: string, runId: string): Promise<QualityReviewRun> {
  return request<QualityReviewRun>(
    `/admin/v1/quality-reviews/runs/${encodeURIComponent(runId)}:approve-all`,
    apiKey,
    {
      method: "POST",
    },
  );
}

export function rejectQualityReviewRun(
  apiKey: string,
  runId: string,
  payload: { reason: string },
): Promise<QualityReviewRun> {
  return request<QualityReviewRun>(
    `/admin/v1/quality-reviews/runs/${encodeURIComponent(runId)}:reject`,
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function patchQualityReviewPolicy(
  apiKey: string,
  payload: {
    product_id: string;
    sample_size?: number;
    threshold_score?: number;
    approval_mode?: QualityReviewApprovalMode;
  },
): Promise<QualityReviewPolicy> {
  return request<QualityReviewPolicy>("/admin/v1/quality-reviews/policy", apiKey, {
    method: "PATCH",
    body: payload,
  });
}

export function fetchQualityReviewPolicyPresets(
  apiKey: string,
): Promise<QualityReviewPolicyPreset[]> {
  return request<QualityReviewPolicyPreset[]>("/admin/v1/quality-reviews/policy-presets", apiKey);
}

export function applyQualityReviewPolicyPreset(
  apiKey: string,
  payload: { product_id: string; preset_id: string },
): Promise<QualityReviewPolicy> {
  return request<QualityReviewPolicy>("/admin/v1/quality-reviews/policy:apply-preset", apiKey, {
    method: "POST",
    body: payload,
  });
}

export function batchApproveAllQualityReviewRuns(
  apiKey: string,
  payload: { run_ids: string[] },
): Promise<QualityReviewBatchActionResponse> {
  return request<QualityReviewBatchActionResponse>(
    "/admin/v1/quality-reviews/runs:batch-approve-all",
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function batchRejectQualityReviewRuns(
  apiKey: string,
  payload: { run_ids: string[]; reason: string },
): Promise<QualityReviewBatchActionResponse> {
  return request<QualityReviewBatchActionResponse>(
    "/admin/v1/quality-reviews/runs:batch-reject",
    apiKey,
    {
      method: "POST",
      body: payload,
    },
  );
}

export function diffQualityReviewRuns(
  apiKey: string,
  payload: { baseline_run_id: string; candidate_run_id: string },
): Promise<QualityReviewRunDiff> {
  const params = new URLSearchParams();
  params.set("baseline_run_id", payload.baseline_run_id);
  params.set("candidate_run_id", payload.candidate_run_id);
  return request<QualityReviewRunDiff>(
    `/admin/v1/quality-reviews/runs:diff?${params.toString()}`,
    apiKey,
  );
}
