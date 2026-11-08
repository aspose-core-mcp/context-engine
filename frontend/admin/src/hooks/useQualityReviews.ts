"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import type { QualityReviewApprovalMode, QualityReviewPolicy } from "@/lib/admin-api";
import {
  fetchQualityReviewRuns,
  fetchQualityReviewPolicyPresets,
  diffQualityReviewRuns,
  createQualityReviewRun,
  patchQualityReviewPolicy,
  applyQualityReviewPolicyPreset,
  approveAllQualityReviewRun,
  rejectQualityReviewRun,
  batchApproveAllQualityReviewRuns,
  batchRejectQualityReviewRuns,
} from "@/lib/admin-api";
import { uniqueSorted } from "@/components/admin-console.utils";

/** Mutating action ids surfaced through `onMutationError`. */
export type QualityReviewMutationAction =
  | "patch_policy"
  | "apply_preset"
  | "create_run"
  | "approve_run"
  | "reject_run"
  | "batch_approve"
  | "batch_reject";

export type UseQualityReviewsArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  selectedProductId: string;
  snapshotVersionOptions: string[];
  /**
   * Optional error tap invoked from every quality-review mutation's `onError`
   * so callers can surface a toast / alert.
   * Additive and optional — existing callers keep their behavior.
   */
  onMutationError?: (action: QualityReviewMutationAction, error: unknown) => void;
};

export function useQualityReviews(args: UseQualityReviewsArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    selectedProductId,
    snapshotVersionOptions,
    onMutationError,
  } = args;

  const queryClient = useQueryClient();

  const [qualityRunVersion, setQualityRunVersion] = useState("latest");
  const [qualitySourceRevision, setQualitySourceRevision] = useState("dev-local");
  const [qualityPolicySampleSize, setQualityPolicySampleSize] = useState("60");
  const [qualityPolicyThreshold, setQualityPolicyThreshold] = useState("4.3");
  const [qualityPolicyApprovalMode, setQualityPolicyApprovalMode] =
    useState<QualityReviewApprovalMode>("human_approve_all");
  const [qualityPolicyPresetId, setQualityPolicyPresetId] = useState("balanced_default");
  const [selectedQualityRunId, setSelectedQualityRunId] = useState("");
  const [selectedQualityRunIds, setSelectedQualityRunIds] = useState<string[]>([]);
  const [qualityDiffBaselineRunId, setQualityDiffBaselineRunId] = useState("");
  const [qualityDiffCandidateRunId, setQualityDiffCandidateRunId] = useState("");

  const qualityReviewRunsQuery = useQuery({
    queryKey: ["admin-quality-review-runs", apiKey, selectedProductId],
    queryFn: () =>
      fetchQualityReviewRuns(apiKey, {
        product_id: selectedProductId || undefined,
        limit: 20,
      }),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "quality-reviews" ? 60_000 : false,
  });

  const qualityPolicyPresetsQuery = useQuery({
    queryKey: ["admin-quality-review-policy-presets", apiKey],
    queryFn: () => fetchQualityReviewPolicyPresets(apiKey),
    enabled: sessionIsSuccess,
  });

  const qualityRunDiffQuery = useQuery({
    queryKey: [
      "admin-quality-review-diff",
      apiKey,
      qualityDiffBaselineRunId,
      qualityDiffCandidateRunId,
    ],
    queryFn: () =>
      diffQualityReviewRuns(apiKey, {
        baseline_run_id: qualityDiffBaselineRunId,
        candidate_run_id: qualityDiffCandidateRunId,
      }),
    enabled:
      sessionIsSuccess &&
      qualityDiffBaselineRunId.trim().length > 0 &&
      qualityDiffCandidateRunId.trim().length > 0 &&
      qualityDiffBaselineRunId !== qualityDiffCandidateRunId,
  });

  const patchQualityPolicyMutation = useMutation({
    mutationFn: (payload: {
      sample_size: number;
      threshold_score: number;
      approval_mode: QualityReviewApprovalMode;
    }) =>
      patchQualityReviewPolicy(apiKey, {
        product_id: selectedProductId,
        sample_size: payload.sample_size,
        threshold_score: payload.threshold_score,
        approval_mode: payload.approval_mode,
      }),
    onSuccess: async (data: QualityReviewPolicy) => {
      setQualityPolicySampleSize(String(data.sample_size));
      setQualityPolicyThreshold(String(data.threshold_score));
      setQualityPolicyApprovalMode(data.approval_mode);
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => onMutationError?.("patch_policy", error),
  });

  const applyQualityPolicyPresetMutation = useMutation({
    mutationFn: () =>
      applyQualityReviewPolicyPreset(apiKey, {
        product_id: selectedProductId,
        preset_id: qualityPolicyPresetId,
      }),
    onSuccess: async (data: QualityReviewPolicy) => {
      // Update form fields with values returned by the applied preset
      setQualityPolicySampleSize(String(data.sample_size));
      setQualityPolicyThreshold(String(data.threshold_score));
      setQualityPolicyApprovalMode(data.approval_mode);
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => onMutationError?.("apply_preset", error),
  });

  const createQualityReviewRunMutation = useMutation({
    mutationFn: () =>
      createQualityReviewRun(apiKey, {
        product_id: selectedProductId,
        version: qualityRunVersion || undefined,
        source_revision: qualitySourceRevision,
        trigger_type: "major_change",
        items: [
          {
            source_path: `apiref/${selectedProductId}/symbol-rich.md`,
            stratum: "apiref_symbol_rich",
          },
          {
            source_path: `docs/${selectedProductId}/shortcode-guides.md`,
            stratum: "docs_shortcode",
          },
          {
            source_path: `docs/${selectedProductId}/html-embed.md`,
            stratum: "docs_html_embed",
          },
          {
            source_path: `docs/${selectedProductId}/general-overview.md`,
            stratum: "docs_general",
          },
        ],
      }),
    onSuccess: async (run) => {
      setSelectedQualityRunId(run.run_id);
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => onMutationError?.("create_run", error),
  });

  const approveQualityRunMutation = useMutation({
    mutationFn: (runId: string) => approveAllQualityReviewRun(apiKey, runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => onMutationError?.("approve_run", error),
  });

  const rejectQualityRunMutation = useMutation({
    mutationFn: ({ runId, reason }: { runId: string; reason: string }) =>
      rejectQualityReviewRun(apiKey, runId, { reason }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
    },
    onError: (error: unknown) => onMutationError?.("reject_run", error),
  });

  const batchApproveQualityRunsMutation = useMutation({
    mutationFn: (runIds: string[]) =>
      batchApproveAllQualityReviewRuns(apiKey, {
        run_ids: runIds,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
      setSelectedQualityRunIds([]);
    },
    onError: (error: unknown) => onMutationError?.("batch_approve", error),
  });

  const batchRejectQualityRunsMutation = useMutation({
    mutationFn: ({ runIds, reason }: { runIds: string[]; reason: string }) =>
      batchRejectQualityReviewRuns(apiKey, {
        run_ids: runIds,
        reason,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-quality-review-runs", apiKey, selectedProductId] });
      setSelectedQualityRunIds([]);
    },
    onError: (error: unknown) => onMutationError?.("batch_reject", error),
  });

  // --- Effects ---
  useEffect(() => {
    const runs = qualityReviewRunsQuery.data ?? [];
    if (runs.length === 0) {
      if (selectedQualityRunId) {
        setSelectedQualityRunId("");
      }
      if (selectedQualityRunIds.length > 0) {
        setSelectedQualityRunIds([]);
      }
      if (qualityDiffBaselineRunId) {
        setQualityDiffBaselineRunId("");
      }
      if (qualityDiffCandidateRunId) {
        setQualityDiffCandidateRunId("");
      }
      return;
    }
    if (!selectedQualityRunId || !runs.some((run) => run.run_id === selectedQualityRunId)) {
      setSelectedQualityRunId(runs[0].run_id);
    }
    setSelectedQualityRunIds((prev) =>
      prev.filter((runId) => runs.some((run) => run.run_id === runId)),
    );
    if (!qualityDiffBaselineRunId || !runs.some((run) => run.run_id === qualityDiffBaselineRunId)) {
      setQualityDiffBaselineRunId(runs[0].run_id);
    }
    if (
      !qualityDiffCandidateRunId ||
      !runs.some((run) => run.run_id === qualityDiffCandidateRunId) ||
      qualityDiffCandidateRunId === qualityDiffBaselineRunId
    ) {
      setQualityDiffCandidateRunId((runs[1] ?? runs[0]).run_id);
    }
  }, [
    qualityReviewRunsQuery.data,
    selectedQualityRunId,
    selectedQualityRunIds.length,
    qualityDiffBaselineRunId,
    qualityDiffCandidateRunId,
  ]);

  useEffect(() => {
    const latestRun = qualityReviewRunsQuery.data?.[0];
    if (!latestRun) {
      return;
    }
    setQualityPolicySampleSize(String(latestRun.policy.sample_size));
    setQualityPolicyThreshold(String(latestRun.policy.threshold_score));
    setQualityPolicyApprovalMode(latestRun.policy.approval_mode);
  }, [qualityReviewRunsQuery.data]);

  // --- Derived ---
  const selectedQualityRun = useMemo(
    () =>
      (qualityReviewRunsQuery.data ?? []).find((run) => run.run_id === selectedQualityRunId) ??
      (qualityReviewRunsQuery.data ?? [])[0] ??
      null,
    [qualityReviewRunsQuery.data, selectedQualityRunId],
  );

  const toggleQualityRunSelection = (runId: string): void => {
    setSelectedQualityRunIds((previous) => {
      if (previous.includes(runId)) {
        return previous.filter((item) => item !== runId);
      }
      return [...previous, runId];
    });
  };

  const qualityRunIdOptions = uniqueSorted((qualityReviewRunsQuery.data ?? []).map((run) => run.run_id));
  const qualityPolicyPresetOptions = uniqueSorted(
    (qualityPolicyPresetsQuery.data ?? []).map((preset) => preset.preset_id),
  );
  const qualityVersionOptions = uniqueSorted(["latest", qualityRunVersion, ...snapshotVersionOptions]);

  return {
    qualityRunVersion,
    setQualityRunVersion,
    qualitySourceRevision,
    setQualitySourceRevision,
    qualityPolicySampleSize,
    setQualityPolicySampleSize,
    qualityPolicyThreshold,
    setQualityPolicyThreshold,
    qualityPolicyApprovalMode,
    setQualityPolicyApprovalMode,
    qualityPolicyPresetId,
    setQualityPolicyPresetId,
    selectedQualityRunId,
    setSelectedQualityRunId,
    selectedQualityRunIds,
    setSelectedQualityRunIds,
    qualityDiffBaselineRunId,
    setQualityDiffBaselineRunId,
    qualityDiffCandidateRunId,
    setQualityDiffCandidateRunId,
    qualityReviewRunsQuery,
    qualityPolicyPresetsQuery,
    qualityRunDiffQuery,
    patchQualityPolicyMutation,
    applyQualityPolicyPresetMutation,
    createQualityReviewRunMutation,
    approveQualityRunMutation,
    rejectQualityRunMutation,
    batchApproveQualityRunsMutation,
    batchRejectQualityRunsMutation,
    selectedQualityRun,
    toggleQualityRunSelection,
    qualityRunIdOptions,
    qualityPolicyPresetOptions,
    qualityVersionOptions,
  };
}
