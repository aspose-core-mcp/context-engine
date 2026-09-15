"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import { useLocale } from "@/hooks/useLocale";
import type {
  SnapshotCleanupAuditRecord,
  SnapshotCleanupExecutionResult,
  SnapshotCleanupPreviewResult,
  SnapshotCompareResult,
  SnapshotRollbackAuditRecord,
  SnapshotRollbackExecutionResult,
} from "@/lib/admin-api";
import {
  fetchSnapshots,
  fetchActiveSnapshot,
  fetchSnapshotRollbackAudit,
  fetchSnapshotCleanupHistory,
  compareSnapshots,
  promoteSnapshot,
  issueSnapshotRollbackConfirmation,
  rollbackSnapshot,
  previewSnapshotCleanup,
  executeSnapshotCleanup,
} from "@/lib/admin-api";
import {
  uniqueSorted,
  buildDisabledReason,
  getAdminErrorMessage,
} from "@/components/admin-console.utils";
import { useToast } from "@/hooks/useToast";

export type UseSnapshotStateArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  selectedProductId: string;
  canMutateIngestion: boolean;
  canRunDestructive: boolean;
  showAlert: (message: string, title?: string) => void;
  showConfirm: (message: string, action: () => void) => void;
};

export function useSnapshotState(args: UseSnapshotStateArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    selectedProductId,
    canMutateIngestion,
    canRunDestructive,
    showAlert,
    showConfirm,
  } = args;

  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { locale } = useLocale();
  const isSnapshotsActive = activeSectionId === "snapshots";

  const [snapshotLanguageFilter, setSnapshotLanguageFilter] = useState("");
  const [snapshotVersionFilter, setSnapshotVersionFilter] = useState("");
  const [snapshotCompareBaseId, setSnapshotCompareBaseId] = useState("");
  const [snapshotCompareTargetId, setSnapshotCompareTargetId] = useState("");
  const [snapshotRollbackTargetId, setSnapshotRollbackTargetId] = useState("");
  const [snapshotRollbackReason, setSnapshotRollbackReason] = useState("");
  const [snapshotRollbackConfirmText, setSnapshotRollbackConfirmText] = useState("");
  const [snapshotCleanupSourceKind, setSnapshotCleanupSourceKind] = useState("");
  const [snapshotCleanupReason, setSnapshotCleanupReason] = useState("");
  const [selectedSnapshotIds, setSelectedSnapshotIds] = useState<string[]>([]);

  const snapshotsQuery = useQuery({
    queryKey: [
      "admin-snapshots",
      apiKey,
      selectedProductId,
      snapshotLanguageFilter,
      snapshotVersionFilter,
    ],
    queryFn: () =>
      fetchSnapshots(apiKey, {
        product_id: selectedProductId || undefined,
        programming_language: snapshotLanguageFilter || undefined,
        version: snapshotVersionFilter || undefined,
        limit: 50,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isSnapshotsActive ? 60_000 : false,
  });

  const snapshotRollbackAuditQuery = useQuery({
    queryKey: ["admin-snapshot-rollback-audit", apiKey, selectedProductId],
    queryFn: () =>
      fetchSnapshotRollbackAudit(apiKey, {
        product_id: selectedProductId || undefined,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isSnapshotsActive ? 60_000 : false,
  });

  const snapshotCleanupHistoryQuery = useQuery({
    queryKey: ["admin-snapshot-cleanup-history", apiKey, selectedProductId],
    queryFn: () =>
      fetchSnapshotCleanupHistory(apiKey, {
        product_id: selectedProductId || undefined,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: isSnapshotsActive ? 60_000 : false,
  });

  const activeSnapshotQuery = useQuery({
    queryKey: [
      "admin-active-snapshot",
      apiKey,
      selectedProductId,
      snapshotLanguageFilter,
      snapshotVersionFilter,
    ],
    queryFn: () =>
      fetchActiveSnapshot(apiKey, {
        product_id: selectedProductId,
        programming_language: snapshotLanguageFilter,
        version: snapshotVersionFilter,
      }),
    enabled:
      sessionIsSuccess &&
      selectedProductId.trim().length > 0 &&
      snapshotLanguageFilter.trim().length > 0 &&
      snapshotVersionFilter.trim().length > 0,
    refetchInterval: isSnapshotsActive ? 60_000 : false,
    retry: false,
  });

  // --- Mutations ---
  // Every mutation surfaces failures via an error toast (each
  // promote/compare/rollback/cleanup failure must be operator-visible);
  // success toasts fire only in onSuccess, after settle.
  const promoteSnapshotMutation = useMutation({
    mutationFn: (snapshotId: string) => promoteSnapshot(apiKey, snapshotId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-snapshots", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-active-snapshot", apiKey] });
      showToast("Snapshot promoted successfully.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to promote snapshot."), "error");
    },
  });

  const compareSnapshotsMutation = useMutation({
    mutationFn: (payload: { baseSnapshotId: string; targetSnapshotId: string }) =>
      compareSnapshots(apiKey, {
        base_snapshot_id: payload.baseSnapshotId,
        target_snapshot_id: payload.targetSnapshotId,
      }),
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to compare snapshots."), "error");
    },
  });

  const rollbackSnapshotMutation = useMutation({
    mutationFn: async (payload: { snapshotId: string; reason: string }) => {
      const confirmation = await issueSnapshotRollbackConfirmation(apiKey, payload.snapshotId, {
        reason: payload.reason,
      });
      return rollbackSnapshot(apiKey, payload.snapshotId, {
        reason: payload.reason,
        confirm_token: confirmation.confirm_token,
      });
    },
    onSuccess: async () => {
      setSnapshotRollbackConfirmText("");
      await queryClient.invalidateQueries({ queryKey: ["admin-snapshots", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-active-snapshot", apiKey] });
      await queryClient.invalidateQueries({
        queryKey: ["admin-snapshot-rollback-audit", apiKey, selectedProductId],
      });
      await queryClient.invalidateQueries({ queryKey: ["admin-critical-events", apiKey] });
      showToast("Snapshot rollback completed.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to roll back snapshot."), "error");
    },
  });

  const previewSnapshotCleanupMutation = useMutation({
    mutationFn: (payload: {
      product_id: string;
      programming_language?: string;
      version?: string;
      source_kind?: string;
    }) => previewSnapshotCleanup(apiKey, payload),
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to preview snapshot cleanup."), "error");
    },
  });

  const executeSnapshotCleanupMutation = useMutation({
    mutationFn: (payload: {
      product_id: string;
      programming_language?: string;
      version?: string;
      source_kind?: string;
      reason: string;
    }) => executeSnapshotCleanup(apiKey, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-snapshots", apiKey] });
      await queryClient.invalidateQueries({
        queryKey: ["admin-snapshot-cleanup-history", apiKey, selectedProductId],
      });
      await queryClient.invalidateQueries({ queryKey: ["admin-active-snapshot", apiKey] });
      setSnapshotCleanupReason("");
      showToast("Snapshot cleanup completed.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to execute snapshot cleanup."), "error");
    },
  });

  // --- Derived ---
  const snapshotRows = useMemo(
    () => (snapshotsQuery.data ?? []).slice(0, 20),
    [snapshotsQuery.data],
  );
  const snapshotRollbackAuditRows = useMemo<SnapshotRollbackAuditRecord[]>(
    () => (snapshotRollbackAuditQuery.data ?? []).slice(0, 10),
    [snapshotRollbackAuditQuery.data],
  );
  const snapshotCleanupHistoryRows = useMemo<SnapshotCleanupAuditRecord[]>(
    () => (snapshotCleanupHistoryQuery.data ?? []).slice(0, 10),
    [snapshotCleanupHistoryQuery.data],
  );

  const snapshotCompareResult: SnapshotCompareResult | null = compareSnapshotsMutation.data ?? null;
  const snapshotRollbackResult: SnapshotRollbackExecutionResult | null =
    rollbackSnapshotMutation.data ?? null;
  const snapshotCleanupPreviewResult: SnapshotCleanupPreviewResult | null =
    previewSnapshotCleanupMutation.data ?? null;
  const snapshotCleanupExecutionResult: SnapshotCleanupExecutionResult | null =
    executeSnapshotCleanupMutation.data ?? null;

  const selectedRollbackTargetSnapshot =
    snapshotRows.find((row) => row.snapshot_id === snapshotRollbackTargetId) ?? null;
  const snapshotSourceKindOptions = uniqueSorted(snapshotRows.map((item) => item.source_kind));
  const snapshotLanguageOptions = uniqueSorted(snapshotRows.map((item) => item.programming_language));
  const snapshotVersionOptions = uniqueSorted(snapshotRows.map((item) => item.version));
  const rollbackRequiresConfirmation = snapshotRollbackConfirmText.trim() === "ROLLBACK";

  const canSubmitRollback =
    canMutateIngestion &&
    !rollbackSnapshotMutation.isPending &&
    snapshotRollbackTargetId.trim().length > 0 &&
    snapshotRollbackReason.trim().length > 0 &&
    rollbackRequiresConfirmation;

  const canPreviewSnapshotCleanup =
    canMutateIngestion &&
    canRunDestructive &&
    !previewSnapshotCleanupMutation.isPending &&
    selectedProductId.trim().length > 0;

  const canExecuteSnapshotCleanup =
    canMutateIngestion &&
    canRunDestructive &&
    !executeSnapshotCleanupMutation.isPending &&
    snapshotCleanupReason.trim().length > 0 &&
    (snapshotCleanupPreviewResult?.delete_candidates_count ?? 0) > 0;

  // --- Disabled reason strings ---
  const batchPromoteDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion ? "write:ingestion" : null,
    pending: promoteSnapshotMutation.isPending,
    pendingMessage: "Snapshot promotion is in progress.",
    unmetCondition:
      selectedSnapshotIds.length === 0 ? "Select at least one snapshot before batch promote." : null,
  });
  const rollbackActionDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion ? "write:ingestion" : null,
    pending: rollbackSnapshotMutation.isPending,
    pendingMessage: "Rollback operation is in progress.",
    unmetCondition:
      selectedRollbackTargetSnapshot?.status === "active"
        ? "Selected target is already active."
        : !snapshotRollbackTargetId.trim()
          ? "Set `target_snapshot_id` first."
          : !snapshotRollbackReason.trim()
            ? "Set rollback `reason` first."
            : !rollbackRequiresConfirmation
              ? "Type `ROLLBACK` to confirm."
              : null,
  });
  const snapshotCleanupPreviewDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion
      ? "write:ingestion"
      : !canRunDestructive
        ? "write:destructive"
        : null,
    pending: previewSnapshotCleanupMutation.isPending,
    pendingMessage: "Cleanup preview is running.",
    unmetCondition: !selectedProductId.trim() ? "Select `product_id` first." : null,
  });
  const snapshotCleanupExecuteDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion
      ? "write:ingestion"
      : !canRunDestructive
        ? "write:destructive"
        : null,
    pending: executeSnapshotCleanupMutation.isPending,
    pendingMessage: "Cleanup execution is in progress.",
    unmetCondition:
      !snapshotCleanupPreviewResult
        ? "Run cleanup preview first."
        : (snapshotCleanupPreviewResult.delete_candidates_count ?? 0) === 0
          ? "Preview found no deletable inactive snapshots."
          : !snapshotCleanupReason.trim()
            ? "Set cleanup `reason` first."
            : null,
  });

  // --- Sync effects ---
  useEffect(() => {
    const snapshots = snapshotsQuery.data ?? [];
    if (snapshots.length === 0) {
      if (snapshotCompareBaseId) {
        setSnapshotCompareBaseId("");
      }
      if (snapshotCompareTargetId) {
        setSnapshotCompareTargetId("");
      }
      if (snapshotRollbackTargetId) {
        setSnapshotRollbackTargetId("");
      }
      return;
    }
    if (!snapshotCompareBaseId || !snapshots.some((row) => row.snapshot_id === snapshotCompareBaseId)) {
      setSnapshotCompareBaseId(snapshots[0].snapshot_id);
    }
    if (!snapshotCompareTargetId || !snapshots.some((row) => row.snapshot_id === snapshotCompareTargetId)) {
      setSnapshotCompareTargetId((snapshots[1] ?? snapshots[0]).snapshot_id);
    }
    if (
      !snapshotRollbackTargetId ||
      !snapshots.some((row) => row.snapshot_id === snapshotRollbackTargetId)
    ) {
      const rollbackCandidate =
        snapshots.find((row) => row.status !== "active") ?? snapshots[0];
      setSnapshotRollbackTargetId(rollbackCandidate.snapshot_id);
    }
    setSelectedSnapshotIds((previous) =>
      previous.filter((snapshotId) =>
        snapshots.some((row) => row.snapshot_id === snapshotId),
      ),
    );
  }, [
    snapshotsQuery.data,
    snapshotCompareBaseId,
    snapshotCompareTargetId,
    snapshotRollbackTargetId,
  ]);

  // --- Handlers ---
  function toggleSnapshotSelection(snapshotId: string) {
    setSelectedSnapshotIds((previous) => {
      if (previous.includes(snapshotId)) {
        return previous.filter((item) => item !== snapshotId);
      }
      return [...previous, snapshotId];
    });
  }

  function runSnapshotRollback() {
    const targetSnapshotId = snapshotRollbackTargetId.trim();
    const rollbackReason = snapshotRollbackReason.trim();
    if (!targetSnapshotId || !rollbackReason) {
      return;
    }
    // Resolve the actual scope from the target snapshot record rather than the
    // filter panel: filter values may be empty when the user hasn't narrowed
    // down the language/version, which would produce misleading messages
    // like "for aspose.llm// to snap-000..." with empty scope segments.
    const targetSnapshot = (snapshotsQuery.data ?? []).find(
      (row) => row.snapshot_id === targetSnapshotId,
    );
    const scopeLabel = targetSnapshot
      ? `${targetSnapshot.product_id}/${targetSnapshot.programming_language}/${targetSnapshot.version}`
      : `${selectedProductId}/${snapshotLanguageFilter || "?"}/${snapshotVersionFilter || "?"}`;
    const message =
      locale === "ru"
        ? `Откатить активный снапшот для ${scopeLabel} к ${targetSnapshotId}?`
        : `Rollback active snapshot for ${scopeLabel} to ${targetSnapshotId}?`;
    showConfirm(message, () => {
      rollbackSnapshotMutation.mutate({
        snapshotId: targetSnapshotId,
        reason: rollbackReason,
      });
    });
  }

  function runSnapshotCleanupPreview() {
    if (!selectedProductId.trim()) {
      return;
    }
    previewSnapshotCleanupMutation.mutate({
      product_id: selectedProductId.trim(),
      programming_language: snapshotLanguageFilter.trim() || undefined,
      version: snapshotVersionFilter.trim() || undefined,
      source_kind: snapshotCleanupSourceKind.trim() || undefined,
    });
  }

  function runSnapshotCleanupExecute() {
    const cleanupReason = snapshotCleanupReason.trim();
    if (!selectedProductId.trim() || !cleanupReason) {
      return;
    }
    const candidatesCount = snapshotCleanupPreviewResult?.delete_candidates_count ?? 0;
    const message =
      locale === "ru"
        ? `Удалить ${candidatesCount} неактивных снапшот(а/ов) для ${selectedProductId}?`
        : `Delete ${candidatesCount} inactive snapshot(s) for ${selectedProductId}?`;
    showConfirm(message, () => {
      executeSnapshotCleanupMutation.mutate({
        product_id: selectedProductId.trim(),
        programming_language: snapshotLanguageFilter.trim() || undefined,
        version: snapshotVersionFilter.trim() || undefined,
        source_kind: snapshotCleanupSourceKind.trim() || undefined,
        reason: cleanupReason,
      });
    });
  }

  // Confirmation-free batch promote: runs the sequential loop directly so callers
  // that already obtained an explicit confirmation (e.g. the Mono section's single
  // ConfirmModal) do not stack a second dialog. Resolves only after every
  // promotion settles; on the first failure the loop halts (the mutation's
  // onError toast has already surfaced it) and the selection is preserved so the
  // operator can retry. Never rejects.
  async function runBatchSnapshotPromoteNow(): Promise<{
    ok: boolean;
    promoted: number;
    total: number;
  }> {
    const snapshotIds = [...selectedSnapshotIds];
    let promoted = 0;
    for (const snapshotId of snapshotIds) {
      try {
        await promoteSnapshotMutation.mutateAsync(snapshotId);
        promoted += 1;
      } catch {
        return { ok: false, promoted, total: snapshotIds.length };
      }
    }
    setSelectedSnapshotIds([]);
    return { ok: true, promoted, total: snapshotIds.length };
  }

  async function runBatchSnapshotPromote() {
    if (selectedSnapshotIds.length === 0) {
      showAlert("Select at least one snapshot.");
      return;
    }
    showConfirm(
      `Promote ${selectedSnapshotIds.length} snapshot(s) sequentially (last successful becomes active)?`,
      () => {
        void runBatchSnapshotPromoteNow();
      },
    );
  }

  return {
    snapshotLanguageFilter,
    setSnapshotLanguageFilter,
    snapshotVersionFilter,
    setSnapshotVersionFilter,
    snapshotCompareBaseId,
    setSnapshotCompareBaseId,
    snapshotCompareTargetId,
    setSnapshotCompareTargetId,
    snapshotRollbackTargetId,
    setSnapshotRollbackTargetId,
    snapshotRollbackReason,
    setSnapshotRollbackReason,
    snapshotRollbackConfirmText,
    setSnapshotRollbackConfirmText,
    snapshotCleanupSourceKind,
    setSnapshotCleanupSourceKind,
    snapshotCleanupReason,
    setSnapshotCleanupReason,
    selectedSnapshotIds,
    setSelectedSnapshotIds,
    snapshotsQuery,
    snapshotRollbackAuditQuery,
    snapshotCleanupHistoryQuery,
    activeSnapshotQuery,
    promoteSnapshotMutation,
    compareSnapshotsMutation,
    rollbackSnapshotMutation,
    previewSnapshotCleanupMutation,
    executeSnapshotCleanupMutation,
    snapshotRows,
    snapshotRollbackAuditRows,
    snapshotCleanupHistoryRows,
    snapshotCompareResult,
    snapshotRollbackResult,
    snapshotCleanupPreviewResult,
    snapshotCleanupExecutionResult,
    selectedRollbackTargetSnapshot,
    snapshotSourceKindOptions,
    snapshotLanguageOptions,
    snapshotVersionOptions,
    rollbackRequiresConfirmation,
    canSubmitRollback,
    canPreviewSnapshotCleanup,
    canExecuteSnapshotCleanup,
    batchPromoteDisabledReason,
    rollbackActionDisabledReason,
    snapshotCleanupPreviewDisabledReason,
    snapshotCleanupExecuteDisabledReason,
    toggleSnapshotSelection,
    runSnapshotRollback,
    runSnapshotCleanupPreview,
    runSnapshotCleanupExecute,
    runBatchSnapshotPromote,
    runBatchSnapshotPromoteNow,
  };
}
