"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchRetrievalSettings,
  patchRetrievalSettings,
} from "@/lib/admin-api";
import { buildDisabledReason } from "@/components/admin-console.utils";
import { useToast } from "@/hooks/useToast";

export type UseRetrievalSettingsArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  selectedProductId: string;
  canWriteSettings: boolean;
};

export function useRetrievalSettings(args: UseRetrievalSettingsArgs) {
  const { apiKey, sessionIsSuccess, selectedProductId, canWriteSettings } = args;

  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const retrievalSettingsQuery = useQuery({
    queryKey: ["admin-retrieval-settings", apiKey, selectedProductId],
    queryFn: () => fetchRetrievalSettings(apiKey, selectedProductId),
    // Per-product load: never fire a fetch without a concrete product id (the
    // "no product selected" sentinel passes "" — there is nothing to load yet).
    enabled: sessionIsSuccess && selectedProductId !== "",
  });

  const patchRetrievalSettingsMutation = useMutation({
    mutationFn: (payload: {
      top_k: number;
      max_context_tokens: number;
      excerpt_char_limit: number;
      low_confidence_threshold: number;
      clarification_policy: string;
    }) => patchRetrievalSettings(apiKey, selectedProductId, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-retrieval-settings", apiKey, selectedProductId] });
      // Success feedback fires ONLY here, after the PATCH settled — never
      // optimistically at confirm/click time.
      showToast(
        selectedProductId
          ? `Retrieval settings updated for ${selectedProductId}.`
          : "Retrieval settings updated.",
      );
    },
    onError: (error: unknown) => {
      // Failed PATCH must be visible (403 / 422 range error / 5xx / offline):
      // error toast here; the section additionally renders an inline error alert.
      showToast(
        error instanceof Error && error.message
          ? error.message
          : "Failed to update retrieval settings.",
        "error",
      );
    },
  });

  const currentSettings = retrievalSettingsQuery.data;

  const retrievalUpdateDisabledReason = buildDisabledReason({
    missingScope: !canWriteSettings ? "write:settings" : null,
    pending: patchRetrievalSettingsMutation.isPending,
    pendingMessage: "Settings update is in progress.",
    unmetCondition: retrievalSettingsQuery.data ? null : "Load current settings first.",
  });

  return {
    retrievalSettingsQuery,
    patchRetrievalSettingsMutation,
    currentSettings,
    retrievalUpdateDisabledReason,
  };
}
