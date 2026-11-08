"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import {
  fetchAdminSystemHealth,
  fetchAdminContentServicesOverview,
  fetchAdminTopologyPolicy,
  fetchAdminObservabilitySummary,
  fetchAdminIndexStatus,
  fetchAbuseGuardSettings,
  fetchPublicContentTriage,
  patchAbuseGuardSettings,
} from "@/lib/admin-api";
import type {
  AdminContentServicesOverview,
  AdminObservabilitySummary,
  IndexStatusResponse,
} from "@/lib/admin-api";
import { uniqueSorted, parseCsvList } from "@/components/admin-console.utils";

export type UseHealthQueriesArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  showAlert: (message: string, title?: string) => void;
  showConfirm: (message: string, action: () => void) => void;
  canConfigureAbuseGuard: boolean;
};

export function useHealthQueries(args: UseHealthQueriesArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    showAlert,
    showConfirm,
    canConfigureAbuseGuard,
  } = args;

  const queryClient = useQueryClient();

  const isHealthActive = activeSectionId === "health";
  const isAnalyticsActive = activeSectionId === "analytics";

  // --- Abuse guard local form state ---
  const [abuseGuardMode, setAbuseGuardMode] = useState<"observe-only" | "enforce">("observe-only");
  const [abuseGuardAllowlistInput, setAbuseGuardAllowlistInput] = useState("");
  const [abuseGuardIpLimitInput, setAbuseGuardIpLimitInput] = useState("120");
  const [abuseGuardFingerprintLimitInput, setAbuseGuardFingerprintLimitInput] = useState("180");
  const [abuseGuardGlobalLimitInput, setAbuseGuardGlobalLimitInput] = useState("5000");
  const [abuseGuardDebugHeaderEnabled, setAbuseGuardDebugHeaderEnabled] = useState(true);

  // --- Content service filters ---
  const [contentServiceProductFilter, setContentServiceProductFilter] = useState("");
  const [contentServiceRepoFilter, setContentServiceRepoFilter] = useState("");
  const [contentTriageSeverityFilter, setContentTriageSeverityFilter] = useState("");

  // --- Dependency selection ---
  const [selectedDependencyName, setSelectedDependencyName] = useState<string>("");

  const healthQuery = useQuery({
    queryKey: ["admin-health", apiKey],
    queryFn: () => fetchAdminSystemHealth(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: isHealthActive ? 60_000 : false,
  });

  const contentServicesQuery = useQuery({
    queryKey: ["admin-content-services", apiKey],
    queryFn: () => fetchAdminContentServicesOverview(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: isHealthActive ? 60_000 : false,
  });

  const contentTriageQuery = useQuery({
    queryKey: [
      "public-content-triage-admin",
      contentServiceProductFilter,
      contentServiceRepoFilter,
      contentTriageSeverityFilter,
    ],
    queryFn: () =>
      fetchPublicContentTriage({
        product_id: contentServiceProductFilter || undefined,
        repo_id: contentServiceRepoFilter.trim() || undefined,
        severity: contentTriageSeverityFilter || undefined,
        stale_after_days: 30,
        limit: 12,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isHealthActive || isAnalyticsActive ? 60_000 : false,
  });

  const topologyPolicyQuery = useQuery({
    queryKey: ["admin-topology-policy", apiKey],
    queryFn: () => fetchAdminTopologyPolicy(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: 60_000,
  });

  const observabilityQuery = useQuery({
    queryKey: ["admin-observability", apiKey],
    queryFn: () => fetchAdminObservabilitySummary(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: 60_000,
  });

  const indexStatusQuery = useQuery({
    queryKey: ["admin-index-status", apiKey],
    queryFn: () => fetchAdminIndexStatus(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: isHealthActive ? 60_000 : false,
  });

  const topologyPolicyReady =
    !!topologyPolicyQuery.data?.qdrant &&
    !!topologyPolicyQuery.data?.opensearch &&
    !!topologyPolicyQuery.data?.compaction &&
    !!topologyPolicyQuery.data?.storage_tiering;

  const abuseGuardSettingsQuery = useQuery({
    queryKey: ["admin-abuse-guard-settings", apiKey],
    queryFn: () => fetchAbuseGuardSettings(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: isHealthActive ? 60_000 : false,
  });

  const patchAbuseGuardSettingsMutation = useMutation({
    mutationFn: (payload: {
      mode: "observe-only" | "enforce";
      allowlist: string[];
      requests_per_ip_per_minute: number;
      requests_per_fingerprint_per_minute: number;
      requests_global_per_minute: number;
      debug_header_enabled: boolean;
    }) => patchAbuseGuardSettings(apiKey, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-abuse-guard-settings", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-observability", apiKey] });
    },
  });

  // Sync abuse guard settings from query
  useEffect(() => {
    const settings = abuseGuardSettingsQuery.data;
    if (!settings) {
      return;
    }
    setAbuseGuardMode(settings.mode === "enforce" ? "enforce" : "observe-only");
    setAbuseGuardAllowlistInput(settings.allowlist.join(","));
    setAbuseGuardIpLimitInput(String(settings.requests_per_ip_per_minute));
    setAbuseGuardFingerprintLimitInput(String(settings.requests_per_fingerprint_per_minute));
    setAbuseGuardGlobalLimitInput(String(settings.requests_global_per_minute));
    setAbuseGuardDebugHeaderEnabled(settings.debug_header_enabled);
  }, [abuseGuardSettingsQuery.data]);

  // Sync dependency name selection
  useEffect(() => {
    const dependencyNames = Object.keys(healthQuery.data?.dependencies ?? {});
    if (dependencyNames.length === 0) {
      if (selectedDependencyName) {
        setSelectedDependencyName("");
      }
      return;
    }
    if (!selectedDependencyName || !dependencyNames.includes(selectedDependencyName)) {
      setSelectedDependencyName(dependencyNames[0]);
    }
  }, [healthQuery.data, selectedDependencyName]);

  function applyAbuseGuardSettings() {
    if (!canConfigureAbuseGuard) {
      return;
    }
    const requestsPerIp = Number.parseInt(abuseGuardIpLimitInput, 10);
    const requestsPerFingerprint = Number.parseInt(abuseGuardFingerprintLimitInput, 10);
    const requestsGlobal = Number.parseInt(abuseGuardGlobalLimitInput, 10);
    if (
      Number.isNaN(requestsPerIp) ||
      Number.isNaN(requestsPerFingerprint) ||
      Number.isNaN(requestsGlobal) ||
      requestsPerIp < 1 ||
      requestsPerFingerprint < 1 ||
      requestsGlobal < 1
    ) {
      showAlert("Abuse guard thresholds must be positive integers.", "Validation Error");
      return;
    }
    if (abuseGuardMode === "enforce") {
      showConfirm(
        "Enable ENFORCE mode for public API abuse guard now?",
        () => {
          patchAbuseGuardSettingsMutation.mutate({
            mode: abuseGuardMode,
            allowlist: parseCsvList(abuseGuardAllowlistInput),
            requests_per_ip_per_minute: requestsPerIp,
            requests_per_fingerprint_per_minute: requestsPerFingerprint,
            requests_global_per_minute: requestsGlobal,
            debug_header_enabled: abuseGuardDebugHeaderEnabled,
          });
        },
      );
      return;
    }
    patchAbuseGuardSettingsMutation.mutate({
      mode: abuseGuardMode,
      allowlist: parseCsvList(abuseGuardAllowlistInput),
      requests_per_ip_per_minute: requestsPerIp,
      requests_per_fingerprint_per_minute: requestsPerFingerprint,
      requests_global_per_minute: requestsGlobal,
      debug_header_enabled: abuseGuardDebugHeaderEnabled,
    });
  }

  // --- Derived values ---
  const observability: AdminObservabilitySummary | null = observabilityQuery.data ?? null;
  const contentServicesOverview: AdminContentServicesOverview | null =
    contentServicesQuery.data ?? null;
  const contentServicesRows = contentServicesOverview?.services ?? [];
  const contentServiceProductOptions = uniqueSorted(
    contentServicesRows.map((service) => service.product_id),
  );
  const normalizedContentServiceRepoFilter = contentServiceRepoFilter.trim().toLowerCase();
  const filteredContentServicesRows = contentServicesRows.filter((service) => {
    const productMatches = !contentServiceProductFilter || service.product_id === contentServiceProductFilter;
    const repoMatches =
      !normalizedContentServiceRepoFilter ||
      service.repo_id.toLowerCase().includes(normalizedContentServiceRepoFilter);
    return productMatches && repoMatches;
  });
  const filteredDocsServices = filteredContentServicesRows.filter(
    (service) => service.source_kind === "docs",
  );
  const filteredApirefServices = filteredContentServicesRows.filter(
    (service) => service.source_kind === "apiref",
  );
  const filteredDocsReadyCount = filteredDocsServices.filter((service) => service.mcp_ready).length;
  const filteredApirefReadyCount = filteredApirefServices.filter((service) => service.mcp_ready).length;
  const filteredHealthyCount = filteredContentServicesRows.filter(
    (service) => service.service_status === "healthy",
  ).length;
  const filteredWarningCount = filteredContentServicesRows.filter(
    (service) => service.service_status === "warning",
  ).length;
  const filteredCriticalCount = filteredContentServicesRows.filter(
    (service) => service.service_status === "critical",
  ).length;
  const filteredUnknownCount = filteredContentServicesRows.filter(
    (service) => service.service_status === "unknown",
  ).length;
  const filteredPendingCount = filteredContentServicesRows.filter(
    (service) => service.onboarding_status === "pending_first_ingestion",
  ).length;
  const filteredNotReadyRows = filteredContentServicesRows.filter((service) => !service.mcp_ready);
  const filteredNotReadyActivelyBroken = filteredNotReadyRows.filter(
    (service) => service.onboarding_status !== "pending_first_ingestion",
  );
  const filteredNotReadyReasonRows = Object.entries(
    filteredNotReadyRows.reduce<Record<string, number>>((acc, service) => {
      const reason = service.service_status_reason || "unknown_reason";
      acc[reason] = (acc[reason] ?? 0) + 1;
      return acc;
    }, {}),
  ).sort((left, right) => right[1] - left[1]);
  const topNotReadyService = filteredNotReadyRows[0] ?? null;
  const readyServicesTotal = filteredContentServicesRows.filter((service) => service.mcp_ready).length;
  const docsCoverageLabel = `${filteredDocsReadyCount}/${filteredDocsServices.length}`;
  const apirefCoverageLabel = `${filteredApirefReadyCount}/${filteredApirefServices.length}`;

  const dependencyRows = Object.entries(healthQuery.data?.dependencies ?? {});
  const degradedDependencyRows = dependencyRows.filter(([, item]) => item.status !== "ready");
  const leadingDegradedDependency = degradedDependencyRows[0] ?? null;
  const dependencyNameOptions = uniqueSorted(dependencyRows.map(([name]) => name));
  const selectedDependency = selectedDependencyName
    ? (healthQuery.data?.dependencies ?? {})[selectedDependencyName]
    : null;

  return {
    healthQuery,
    contentServicesQuery,
    contentTriageQuery,
    topologyPolicyQuery,
    observabilityQuery,
    indexStatusQuery,
    topologyPolicyReady,
    abuseGuardSettingsQuery,
    patchAbuseGuardSettingsMutation,
    abuseGuardMode,
    setAbuseGuardMode,
    abuseGuardAllowlistInput,
    setAbuseGuardAllowlistInput,
    abuseGuardIpLimitInput,
    setAbuseGuardIpLimitInput,
    abuseGuardFingerprintLimitInput,
    setAbuseGuardFingerprintLimitInput,
    abuseGuardGlobalLimitInput,
    setAbuseGuardGlobalLimitInput,
    abuseGuardDebugHeaderEnabled,
    setAbuseGuardDebugHeaderEnabled,
    applyAbuseGuardSettings,
    contentServiceProductFilter,
    setContentServiceProductFilter,
    contentServiceRepoFilter,
    setContentServiceRepoFilter,
    contentTriageSeverityFilter,
    setContentTriageSeverityFilter,
    selectedDependencyName,
    setSelectedDependencyName,
    observability,
    contentServicesOverview,
    contentServicesRows,
    contentServiceProductOptions,
    filteredContentServicesRows,
    filteredDocsReadyCount,
    filteredApirefReadyCount,
    filteredHealthyCount,
    filteredWarningCount,
    filteredCriticalCount,
    filteredUnknownCount,
    filteredPendingCount,
    filteredNotReadyActivelyBroken,
    filteredNotReadyReasonRows,
    topNotReadyService,
    readyServicesTotal,
    docsCoverageLabel,
    apirefCoverageLabel,
    dependencyRows,
    degradedDependencyRows,
    leadingDegradedDependency,
    dependencyNameOptions,
    selectedDependency,
  };
}
