"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import {
  fetchConfigHistory,
  rollbackConfigChange,
} from "@/lib/admin-api";
import { buildDisabledReason } from "@/components/admin-console.utils";
import { useToast } from "@/hooks/useToast";

export type UseConfigHistoryArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  selectedProductId: string;
  canWriteSettings: boolean;
  isSuperuser: boolean;
};

/**
 * Variables accepted by the rollback mutation. The object form carries the
 * operator-typed reason onto the wire (`POST /admin/v1/config/rollback` with
 * `{ change_id, reason }`), so the persisted audit record holds the real
 * reason the dialog collected. The bare `string` form (just the change_id) is
 * kept for backward compatibility and falls back to a generic default reason.
 */
export type RollbackConfigVars =
  | string
  | { changeId: string; reason: string };

export function useConfigHistory(args: UseConfigHistoryArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    selectedProductId,
    canWriteSettings,
    isSuperuser,
  } = args;

  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const configHistoryQuery = useQuery({
    queryKey: ["admin-config-history", apiKey, selectedProductId],
    queryFn: () =>
      fetchConfigHistory(apiKey, {
        product_id: selectedProductId || undefined,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "config-history-rollback" ? 60_000 : false,
  });

  const rollbackConfigMutation = useMutation({
    mutationFn: (vars: RollbackConfigVars) => {
      // Normalize both call shapes; the operator-typed reason (object form) is
      // sent on the wire so it lands in the persisted audit record.
      const { changeId, reason } =
        typeof vars === "string"
          ? { changeId: vars, reason: "Manual rollback from admin UI" }
          : vars;
      return rollbackConfigChange(apiKey, { change_id: changeId, reason });
    },
    onSuccess: async () => {
      // Refresh the change log + any settings views the rollback may have reverted.
      // No success toast here: the Mono shell section owns the single success
      // message, so emitting one here would double it.
      await queryClient.invalidateQueries({ queryKey: ["admin-config-history", apiKey, selectedProductId] });
      await queryClient.invalidateQueries({ queryKey: ["admin-retrieval-settings", apiKey, selectedProductId] });
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-aliases", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => {
      // A failed rollback must be visible (403 missing scope / 404 change_id /
      // 5xx / offline): error toast here; the section additionally renders the
      // in-dialog alert via its per-mutate onError.
      showToast(
        error instanceof Error && error.message
          ? error.message
          : "Config rollback failed.",
        "error",
      );
    },
  });

  const configRollbackDisabledReason = buildDisabledReason({
    missingScope: !canWriteSettings && !isSuperuser ? "write:settings" : null,
    pending: rollbackConfigMutation.isPending,
    pendingMessage: "Config rollback is in progress.",
  });

  return {
    configHistoryQuery,
    rollbackConfigMutation,
    configRollbackDisabledReason,
  };
}
