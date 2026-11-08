"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import { DEFAULT_PROGRAMMING_LANGUAGE_OPTIONS, ONBOARDING_WIZARD_STEPS } from "@/components/admin-console.types";
import {
  uniqueSorted,
  collectProgrammingLanguages,
  buildDisabledReason,
} from "@/components/admin-console.utils";
import type {
  IngestionJobOperation,
  RawMarkdownPreview,
  ReviewArtifactPreview,
  StagingManifestPreview,
} from "@/lib/admin-api";
import {
  fetchIngestionJobs,
  fetchProducts,
  fetchReviewArtifactPreview,
  fetchRawMarkdownPreview,
  fetchStagingManifestPreview,
  triggerIngestionRun,
  onboardSourceRepositoriesProduct,
} from "@/lib/admin-api";
import { useToast } from "@/hooks/useToast";

export type UseIngestionStateArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  selectedProductId: string;
  setSelectedProductId: (productId: string) => void;
  canMutateIngestion: boolean;
  canOnboardProducts: boolean;
  registryLanguageOptions: string[];
  showAlert: (message: string, title?: string) => void;
  showConfirm: (message: string, action: () => void) => void;
  openSection: (
    sectionId: SidebarSectionId,
    options?: { clearWorkspace?: boolean; focusMain?: boolean; scrollTo?: string },
  ) => void;
};

export function useIngestionState(args: UseIngestionStateArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    selectedProductId,
    setSelectedProductId,
    canMutateIngestion,
    canOnboardProducts,
    registryLanguageOptions,
    showAlert,
    showConfirm,
    openSection,
  } = args;

  const queryClient = useQueryClient();
  const { showToast } = useToast();

  // --- Repo selection ---
  const [repoId, setRepoId] = useState("aspose.ocr.docs");
  const [productUseFeedback, setProductUseFeedback] = useState<string | null>(null);

  // --- Batch state ---
  const [batchRepoIds, setBatchRepoIds] = useState<string[]>([]);
  const [batchIngestionFeedback, setBatchIngestionFeedback] = useState<string | null>(null);

  // --- Onboarding wizard state ---
  const [onboardingWizardStep, setOnboardingWizardStep] = useState(0);
  const [onboardProductId, setOnboardProductId] = useState("");
  const [onboardProductName, setOnboardProductName] = useState("");
  const [onboardProductFamily, setOnboardProductFamily] = useState("");
  const [onboardProductFamilyDir, setOnboardProductFamilyDir] = useState("");
  const [onboardDocsRepoUrl, setOnboardDocsRepoUrl] = useState("");
  const [onboardDocsDefaultBranch, setOnboardDocsDefaultBranch] = useState("main");
  const [onboardApirefRepoUrl, setOnboardApirefRepoUrl] = useState("");
  const [onboardApirefDefaultBranch, setOnboardApirefDefaultBranch] = useState("main");
  const [onboardKnownProgrammingLanguages, setOnboardKnownProgrammingLanguages] = useState<string[]>([]);
  const [onboardLanguagePickerValue, setOnboardLanguagePickerValue] = useState("");
  const [onboardCustomProgrammingLanguage, setOnboardCustomProgrammingLanguage] = useState("");
  const [onboardAutoLayoutDetection, setOnboardAutoLayoutDetection] = useState(true);
  const [onboardAutoValidateOnly, setOnboardAutoValidateOnly] = useState(true);
  const [onboardFeedback, setOnboardFeedback] = useState<string | null>(null);

  // --- Staging filters ---
  const [stagingProductFilter, setStagingProductFilter] = useState("");
  const [stagingLanguageFilter, setStagingLanguageFilter] = useState("");
  const [stagingVersionFilter, setStagingVersionFilter] = useState("");
  const [stagingLocaleFilter, setStagingLocaleFilter] = useState("");
  const [stagingSourceKindFilter, setStagingSourceKindFilter] = useState("");

  // --- Review workspace ---
  const [selectedIngestionOperationId, setSelectedIngestionOperationId] = useState("");
  const [selectedReviewRepoId, setSelectedReviewRepoId] = useState("");
  const [selectedReviewPageSourcePath, setSelectedReviewPageSourcePath] = useState("");
  const [selectedReviewChunkId, setSelectedReviewChunkId] = useState("");
  const [selectedReviewManifestPath, setSelectedReviewManifestPath] = useState("");

  const runSingleIngestionBlockRef = useRef<HTMLDivElement | null>(null);

  // --- Queries ---
  const jobsQuery = useQuery({
    queryKey: ["admin-ingestion-jobs", apiKey],
    queryFn: () => fetchIngestionJobs(apiKey, 20),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "ingestion-jobs" ? 60_000 : false,
  });

  const productsQuery = useQuery({
    queryKey: ["admin-products", apiKey],
    queryFn: () => fetchProducts(apiKey, 200),
    enabled: sessionIsSuccess,
    refetchInterval: 60_000,
  });

  // --- Mutations ---
  const triggerIngestionMutation = useMutation({
    mutationFn: (payload: { mode: "publish" | "validate_only"; repoId?: string }) =>
      triggerIngestionRun(apiKey, {
        mode: payload.mode,
        repo_id: payload.repoId?.trim() || repoId.trim() || undefined,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-ingestion-jobs", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-critical-events", apiKey] });
      showToast("Ingestion run triggered successfully.");
    },
  });

  const onboardProductMutation = useMutation({
    mutationFn: (payload: {
      product_id: string;
      product_name?: string;
      product_family: string;
      product_family_dir: string;
      programming_languages: string[];
      docs_git_url: string;
      docs_default_branch: string;
      apiref_git_url: string;
      apiref_default_branch: string;
      auto_run_layout_detection?: boolean;
      auto_run_validate_only?: boolean;
    }) => onboardSourceRepositoriesProduct(apiKey, payload),
    onSuccess: async (response) => {
      setOnboardFeedback(
        `Registered ${response.product_id}: ${response.created_repo_ids.join(", ")}`,
      );
      setSelectedProductId(response.product_id);
      if (response.created_repo_ids.length > 0) {
        setRepoId(response.created_repo_ids[0]);
        setBatchRepoIds(response.created_repo_ids);
      }
      await queryClient.invalidateQueries({ queryKey: ["admin-products", apiKey] });
      showToast("Product onboarded successfully.");
    },
  });

  const reviewArtifactPreviewMutation = useMutation({
    mutationFn: (artifactPath: string) =>
      fetchReviewArtifactPreview(apiKey, { artifact_path: artifactPath }),
  });

  const rawMarkdownPreviewMutation = useMutation({
    mutationFn: (sourcePath: string) =>
      fetchRawMarkdownPreview(apiKey, { source_path: sourcePath }),
  });

  const stagingManifestPreviewMutation = useMutation({
    mutationFn: (manifestPath: string) =>
      fetchStagingManifestPreview(apiKey, {
        manifest_path: manifestPath,
        max_documents: 6,
        max_chunk_objects: 6,
        max_chunk_records_per_object: 12,
      }),
  });

  const resetReviewArtifactPreview = reviewArtifactPreviewMutation.reset;
  const resetRawMarkdownPreview = rawMarkdownPreviewMutation.reset;
  const resetStagingManifestPreview = stagingManifestPreviewMutation.reset;

  // --- Effects ---

  useEffect(() => {
    const jobs = jobsQuery.data ?? [];
    if (jobs.length === 0) {
      if (selectedIngestionOperationId) {
        setSelectedIngestionOperationId("");
      }
      return;
    }
    if (
      !selectedIngestionOperationId ||
      !jobs.some((job) => job.operation_id === selectedIngestionOperationId)
    ) {
      setSelectedIngestionOperationId(jobs[0].operation_id);
    }
  }, [jobsQuery.data, selectedIngestionOperationId]);

  useEffect(() => {
    const products = productsQuery.data ?? [];
    if (products.length === 0) {
      return;
    }
    if (!products.some((row) => row.product_id === selectedProductId)) {
      setSelectedProductId(products[0].product_id);
      setRepoId(`${products[0].product_id}.docs`);
    }
  }, [productsQuery.data, selectedProductId]);

  useEffect(() => {
    const knownRepoIds = new Set(
      (productsQuery.data ?? []).flatMap((product) => product.repo_ids),
    );
    setBatchRepoIds((previous) =>
      previous.filter((repoValue) => knownRepoIds.has(repoValue)),
    );
  }, [productsQuery.data]);

  // --- Derived memos ---
  const selectedIngestionJob = useMemo<IngestionJobOperation | null>(
    () =>
      (jobsQuery.data ?? []).find(
        (job) => job.operation_id === selectedIngestionOperationId,
      ) ??
      (jobsQuery.data ?? [])[0] ??
      null,
    [jobsQuery.data, selectedIngestionOperationId],
  );

  const selectedIngestionResults = useMemo(
    () => selectedIngestionJob?.results ?? [],
    [selectedIngestionJob],
  );

  const filteredIngestionResults = useMemo(() => {
    const normalizedProduct = stagingProductFilter.trim().toLowerCase();
    const normalizedLanguage = stagingLanguageFilter.trim().toLowerCase();
    const normalizedVersion = stagingVersionFilter.trim().toLowerCase();
    const normalizedLocale = stagingLocaleFilter.trim().toLowerCase();
    const normalizedSourceKind = stagingSourceKindFilter.trim().toLowerCase();

    return selectedIngestionResults.filter((result) => {
      const sourceKindMatches =
        normalizedSourceKind.length === 0 ||
        result.source_kind.toLowerCase().includes(normalizedSourceKind);
      if (!sourceKindMatches) {
        return false;
      }
      const scopeCandidates =
        result.staging_scopes.length > 0
          ? result.staging_scopes
          : [
              {
                product_id: result.indexing_summary.product_id,
                programming_language: result.indexing_summary.programming_language,
                version: result.indexing_summary.version,
                doc_locale: "",
                source_kind: result.source_kind,
                manifest_path: "",
                documents_count: 0,
                chunk_records_count: 0,
              },
            ];
      return scopeCandidates.some((scope) => {
        const productMatches =
          normalizedProduct.length === 0 ||
          scope.product_id.toLowerCase().includes(normalizedProduct);
        const languageMatches =
          normalizedLanguage.length === 0 ||
          scope.programming_language.toLowerCase().includes(normalizedLanguage);
        const versionMatches =
          normalizedVersion.length === 0 ||
          scope.version.toLowerCase().includes(normalizedVersion);
        const localeMatches =
          normalizedLocale.length === 0 ||
          scope.doc_locale.toLowerCase().includes(normalizedLocale);
        return productMatches && languageMatches && versionMatches && localeMatches;
      });
    });
  }, [
    selectedIngestionResults,
    stagingProductFilter,
    stagingLanguageFilter,
    stagingVersionFilter,
    stagingLocaleFilter,
    stagingSourceKindFilter,
  ]);

  const selectedReviewResult = useMemo(
    () =>
      filteredIngestionResults.find((result) => result.repo_id === selectedReviewRepoId) ??
      filteredIngestionResults[0] ??
      null,
    [filteredIngestionResults, selectedReviewRepoId],
  );

  const selectedReviewPage = useMemo(
    () =>
      selectedReviewResult?.pages?.find((page) => page.source_path === selectedReviewPageSourcePath) ??
      selectedReviewResult?.pages?.[0] ??
      null,
    [selectedReviewPageSourcePath, selectedReviewResult],
  );

  const selectedReviewChunk = useMemo(
    () =>
      selectedReviewResult?.chunk_records?.find((chunk) => chunk.chunk_id === selectedReviewChunkId) ??
      selectedReviewResult?.chunk_records?.[0] ??
      null,
    [selectedReviewChunkId, selectedReviewResult],
  );

  const selectedReviewManifest = useMemo(() => {
    const manifestCandidates = uniqueSorted([
      ...(selectedReviewResult?.staging_repository_manifest_path
        ? [selectedReviewResult.staging_repository_manifest_path]
        : []),
      ...((selectedReviewResult?.staging_scopes ?? []).map((scope) => scope.manifest_path)),
    ].filter(Boolean));
    return (
      manifestCandidates.find((manifestPath) => manifestPath === selectedReviewManifestPath) ??
      manifestCandidates[0] ??
      ""
    );
  }, [selectedReviewManifestPath, selectedReviewResult]);

  const reviewArtifactPreview: ReviewArtifactPreview | null =
    reviewArtifactPreviewMutation.data ?? null;
  const rawMarkdownPreview: RawMarkdownPreview | null = rawMarkdownPreviewMutation.data ?? null;
  const stagingManifestPreview: StagingManifestPreview | null =
    stagingManifestPreviewMutation.data ?? null;

  // Review workspace sync effects
  useEffect(() => {
    const repoIds = filteredIngestionResults.map((result) => result.repo_id);
    if (repoIds.length === 0) {
      if (selectedReviewRepoId) {
        setSelectedReviewRepoId("");
      }
      return;
    }
    if (!selectedReviewRepoId || !repoIds.includes(selectedReviewRepoId)) {
      setSelectedReviewRepoId(repoIds[0]);
    }
  }, [filteredIngestionResults, selectedReviewRepoId]);

  useEffect(() => {
    const pageSourcePaths = selectedReviewResult?.pages?.map((page) => page.source_path) ?? [];
    if (pageSourcePaths.length === 0) {
      if (selectedReviewPageSourcePath) {
        setSelectedReviewPageSourcePath("");
      }
      resetRawMarkdownPreview();
      return;
    }
    if (
      !selectedReviewPageSourcePath ||
      !pageSourcePaths.includes(selectedReviewPageSourcePath)
    ) {
      setSelectedReviewPageSourcePath(pageSourcePaths[0]);
    }
  }, [
    resetRawMarkdownPreview,
    selectedReviewPageSourcePath,
    selectedReviewResult,
  ]);

  useEffect(() => {
    resetRawMarkdownPreview();
  }, [resetRawMarkdownPreview, selectedReviewPageSourcePath]);

  useEffect(() => {
    const chunkIds = selectedReviewResult?.chunk_records?.map((chunk) => chunk.chunk_id) ?? [];
    if (chunkIds.length === 0) {
      if (selectedReviewChunkId) {
        setSelectedReviewChunkId("");
      }
      return;
    }
    if (!selectedReviewChunkId || !chunkIds.includes(selectedReviewChunkId)) {
      setSelectedReviewChunkId(chunkIds[0]);
    }
  }, [selectedReviewChunkId, selectedReviewResult]);

  useEffect(() => {
    const manifestPaths = uniqueSorted([
      ...(selectedReviewResult?.staging_repository_manifest_path
        ? [selectedReviewResult.staging_repository_manifest_path]
        : []),
      ...((selectedReviewResult?.staging_scopes ?? []).map((scope) => scope.manifest_path)),
    ].filter(Boolean));
    if (manifestPaths.length === 0) {
      if (selectedReviewManifestPath) {
        setSelectedReviewManifestPath("");
      }
      resetStagingManifestPreview();
      return;
    }
    if (
      !selectedReviewManifestPath ||
      !manifestPaths.includes(selectedReviewManifestPath)
    ) {
      setSelectedReviewManifestPath(manifestPaths[0]);
    }
  }, [
    selectedReviewManifestPath,
    selectedReviewResult,
    resetStagingManifestPreview,
  ]);

  useEffect(() => {
    resetStagingManifestPreview();
  }, [resetStagingManifestPreview, selectedReviewManifestPath]);

  useEffect(() => {
    resetReviewArtifactPreview();
    resetRawMarkdownPreview();
    resetStagingManifestPreview();
  }, [
    resetReviewArtifactPreview,
    resetRawMarkdownPreview,
    selectedIngestionOperationId,
    selectedReviewRepoId,
    resetStagingManifestPreview,
  ]);

  // --- Derived option lists ---
  const knownRepoOptions = uniqueSorted((productsQuery.data ?? []).flatMap((product) => product.repo_ids));
  const repoOptions = repoId.trim()
    ? uniqueSorted([repoId, ...knownRepoOptions])
    : knownRepoOptions;
  const productOptions = uniqueSorted((productsQuery.data ?? []).map((product) => product.product_id));
  const productFamilyOptions = uniqueSorted(
    (productsQuery.data ?? []).map((product) => product.product_family),
  );
  const productFamilyDirOptions = uniqueSorted(
    (productsQuery.data ?? []).flatMap((product) => product.product_family_dirs ?? []),
  );
  const registeredProductsTotal = (productsQuery.data ?? []).length;

  const stagingProductOptions = uniqueSorted(
    selectedIngestionResults.flatMap((result) => result.staging_scopes.map((scope) => scope.product_id)),
  );
  const stagingLanguageOptions = uniqueSorted(
    selectedIngestionResults.flatMap((result) =>
      result.staging_scopes.map((scope) => scope.programming_language),
    ),
  );
  const stagingVersionOptions = uniqueSorted(
    selectedIngestionResults.flatMap((result) => result.staging_scopes.map((scope) => scope.version)),
  );
  const stagingLocaleOptions = uniqueSorted(
    selectedIngestionResults.flatMap((result) => result.staging_scopes.map((scope) => scope.doc_locale)),
  );
  const stagingSourceKindOptions = uniqueSorted(selectedIngestionResults.map((result) => result.source_kind));

  // --- Onboarding helpers ---
  const normalizedOnboardProductId = onboardProductId.trim().toLowerCase();
  const onboardProductIdParts = normalizedOnboardProductId
    .split(".")
    .map((part) => part.trim())
    .filter(Boolean);
  const suggestedOnboardProductFamily = onboardProductIdParts[0] ?? "";
  const suggestedOnboardProductFamilyDir =
    onboardProductIdParts.length > 0
      ? onboardProductIdParts
          .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
          .join(".")
      : "";

  const filteredProductFamilyDirOptions = uniqueSorted(
    productFamilyDirOptions.filter((dirValue) => {
      if (!onboardProductFamily.trim()) {
        return true;
      }
      const normalizedFamily = onboardProductFamily.trim().toLowerCase();
      const normalizedDir = dirValue.toLowerCase();
      return normalizedDir.startsWith(`${normalizedFamily}.`) || normalizedDir.includes(normalizedFamily);
    }),
  );

  const knownProductFamilyDirSelection = filteredProductFamilyDirOptions.includes(
    onboardProductFamilyDir.trim(),
  )
    ? onboardProductFamilyDir.trim()
    : "__custom__";

  const onboardingProgrammingLanguageOptions = uniqueSorted([
    ...DEFAULT_PROGRAMMING_LANGUAGE_OPTIONS,
    ...registryLanguageOptions,
    ...onboardKnownProgrammingLanguages,
  ]);
  const onboardingSelectedProgrammingLanguages = collectProgrammingLanguages([
    ...onboardKnownProgrammingLanguages,
    onboardCustomProgrammingLanguage,
  ]);

  const ingestionActionDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion ? "write:ingestion" : null,
    pending: triggerIngestionMutation.isPending,
    pendingMessage: "Ingestion operation is already running.",
  });
  const onboardingActionDisabledReason = buildDisabledReason({
    missingScope: !canOnboardProducts ? "superuser" : null,
    pending: onboardProductMutation.isPending,
    pendingMessage: "Product onboarding is in progress.",
    unmetCondition:
      !normalizedOnboardProductId
        ? "Set product_id first."
        : !(onboardProductFamily.trim() || suggestedOnboardProductFamily)
          ? "Set product_family first."
          : !(onboardProductFamilyDir.trim() || suggestedOnboardProductFamilyDir)
            ? "Set product_family_dir first."
            : !onboardDocsRepoUrl.trim()
              ? "Set docs git URL first."
              : !onboardApirefRepoUrl.trim()
                ? "Set apiref git URL first."
                : null,
  });
  const onboardingStepCompletion = [
    normalizedOnboardProductId.length > 0 &&
      (onboardProductFamily.trim().length > 0 || suggestedOnboardProductFamily.length > 0),
    onboardDocsRepoUrl.trim().length > 0 &&
      onboardApirefRepoUrl.trim().length > 0 &&
      (onboardProductFamilyDir.trim().length > 0 || suggestedOnboardProductFamilyDir.length > 0),
    onboardingSelectedProgrammingLanguages.length > 0,
    onboardingActionDisabledReason === null,
  ];
  const onboardingReviewSummary = [
    `product_id=${normalizedOnboardProductId || "not set"}`,
    `family=${(onboardProductFamily.trim() || suggestedOnboardProductFamily) || "not set"}`,
    `family_dir=${(onboardProductFamilyDir.trim() || suggestedOnboardProductFamilyDir) || "not set"}`,
    `languages=${
      onboardingSelectedProgrammingLanguages.length > 0
        ? onboardingSelectedProgrammingLanguages.join(", ")
        : "none"
    }`,
    `auto_layout_detection=${String(onboardAutoLayoutDetection || onboardAutoValidateOnly)}`,
    `auto_validate_only=${String(onboardAutoValidateOnly)}`,
  ];

  // --- Handler functions ---
  function applyOnboardingSuggestions() {
    if (!onboardProductFamily.trim() && suggestedOnboardProductFamily) {
      setOnboardProductFamily(suggestedOnboardProductFamily);
    }
    if (!onboardProductFamilyDir.trim() && suggestedOnboardProductFamilyDir) {
      setOnboardProductFamilyDir(suggestedOnboardProductFamilyDir);
    }
    if (!onboardProductName.trim() && suggestedOnboardProductFamilyDir) {
      setOnboardProductName(suggestedOnboardProductFamilyDir);
    }
  }

  function addProgrammingLanguageHint(languageId: string) {
    const normalizedLanguageId = languageId.trim().toLowerCase();
    if (!normalizedLanguageId) {
      return;
    }
    setOnboardKnownProgrammingLanguages((previous) =>
      uniqueSorted([...previous, normalizedLanguageId]),
    );
  }

  function removeProgrammingLanguageHint(languageId: string) {
    setOnboardKnownProgrammingLanguages((previous) =>
      previous.filter((item) => item !== languageId),
    );
  }

  function addCustomProgrammingLanguageHint() {
    addProgrammingLanguageHint(onboardCustomProgrammingLanguage);
    setOnboardCustomProgrammingLanguage("");
  }

  async function runOnboardProduct() {
    if (!canOnboardProducts) {
      return;
    }
    const productIdVal = onboardProductId.trim().toLowerCase();
    const productFamily = (
      onboardProductFamily.trim() || suggestedOnboardProductFamily
    ).toLowerCase();
    const productFamilyDir = onboardProductFamilyDir.trim() || suggestedOnboardProductFamilyDir;
    const docsGitUrl = onboardDocsRepoUrl.trim();
    const docsDefaultBranch = onboardDocsDefaultBranch.trim() || "main";
    const apirefGitUrl = onboardApirefRepoUrl.trim();
    const apirefDefaultBranch = onboardApirefDefaultBranch.trim() || "main";
    const programmingLanguages = collectProgrammingLanguages([
      ...onboardKnownProgrammingLanguages,
      onboardCustomProgrammingLanguage,
    ]);
    if (
      !productIdVal ||
      !productFamily ||
      !productFamilyDir ||
      !docsGitUrl ||
      !apirefGitUrl
    ) {
      showAlert("Fill required onboarding fields first.", "Validation Error");
      return;
    }
    showConfirm(
      `Register product ${productIdVal} with docs/apiref repositories in source registry?`,
      () => {
        setOnboardFeedback(null);
        void onboardProductMutation.mutateAsync({
          product_id: productIdVal,
          product_name: onboardProductName.trim() || undefined,
          product_family: productFamily,
          product_family_dir: productFamilyDir,
          programming_languages: programmingLanguages,
          docs_git_url: docsGitUrl,
          docs_default_branch: docsDefaultBranch,
          apiref_git_url: apirefGitUrl,
          apiref_default_branch: apirefDefaultBranch,
          auto_run_layout_detection: onboardAutoLayoutDetection || onboardAutoValidateOnly,
          auto_run_validate_only: onboardAutoValidateOnly,
        });
        setOnboardProductId("");
        setOnboardProductName("");
        setOnboardProductFamily("");
        setOnboardProductFamilyDir("");
        setOnboardDocsRepoUrl("");
        setOnboardApirefRepoUrl("");
        setOnboardKnownProgrammingLanguages([]);
        setOnboardLanguagePickerValue("");
        setOnboardCustomProgrammingLanguage("");
        setOnboardingWizardStep(0);
      },
    );
  }

  function nextOnboardingWizardStep() {
    setOnboardingWizardStep((previous) =>
      Math.min(previous + 1, ONBOARDING_WIZARD_STEPS.length - 1),
    );
  }

  function previousOnboardingWizardStep() {
    setOnboardingWizardStep((previous) => Math.max(previous - 1, 0));
  }

  function jumpToOnboardingWizardStep(stepIndex: number) {
    setOnboardingWizardStep(
      Math.max(0, Math.min(stepIndex, ONBOARDING_WIZARD_STEPS.length - 1)),
    );
  }

  async function loadSelectedReviewArtifact() {
    if (!selectedReviewResult?.review_artifact_path) {
      showAlert("No persisted review artifact is available for this repository result.");
      return;
    }
    await reviewArtifactPreviewMutation.mutateAsync(selectedReviewResult.review_artifact_path);
  }

  async function loadSelectedRawMarkdown() {
    if (!selectedReviewPage?.source_path) {
      showAlert("No parsed page is selected.");
      return;
    }
    await rawMarkdownPreviewMutation.mutateAsync(selectedReviewPage.source_path);
  }

  async function loadSelectedStagingManifest() {
    if (!selectedReviewManifest) {
      showAlert("No staging manifest is available for this repository result.");
      return;
    }
    await stagingManifestPreviewMutation.mutateAsync(selectedReviewManifest);
  }

  async function performBatchIngestion(repoIds: string[], mode: "publish" | "validate_only") {
    let successCount = 0;
    for (const item of repoIds) {
      try {
        await triggerIngestionMutation.mutateAsync({ mode, repoId: item });
        successCount += 1;
      } catch {
        // Keep best-effort batch mode and report summary to operator.
      }
    }
    setBatchIngestionFeedback(
      `Batch ${mode} completed: ${successCount}/${repoIds.length} accepted by backend.`,
    );
  }

  async function runSingleIngestion(mode: "publish" | "validate_only") {
    if (mode === "publish") {
      showConfirm(
        `Trigger publish ingestion for ${repoId.trim() || "all repositories"}?`,
        () => {
          setBatchIngestionFeedback(null);
          void triggerIngestionMutation.mutateAsync({ mode, repoId: repoId.trim() || undefined });
        },
      );
      return;
    }
    setBatchIngestionFeedback(null);
    await triggerIngestionMutation.mutateAsync({ mode, repoId: repoId.trim() || undefined });
  }

  async function runBatchIngestion(mode: "publish" | "validate_only") {
    const ids = batchRepoIds;
    if (ids.length === 0) {
      showAlert("Select at least one repository for batch ingestion.");
      return;
    }
    if (mode === "publish") {
      showConfirm(
        `Trigger publish ingestion for ${ids.length} repositories?`,
        () => void performBatchIngestion(ids, mode),
      );
      return;
    }
    await performBatchIngestion(ids, mode);
  }

  function scrollToRunSingleIngestionBlock() {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(() => {
      runSingleIngestionBlockRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  return {
    repoId,
    setRepoId,
    selectedProductId,
    setSelectedProductId,
    productUseFeedback,
    setProductUseFeedback,
    batchRepoIds,
    setBatchRepoIds,
    batchIngestionFeedback,
    setBatchIngestionFeedback,
    onboardingWizardStep,
    setOnboardingWizardStep,
    onboardProductId,
    setOnboardProductId,
    onboardProductName,
    setOnboardProductName,
    onboardProductFamily,
    setOnboardProductFamily,
    onboardProductFamilyDir,
    setOnboardProductFamilyDir,
    onboardDocsRepoUrl,
    setOnboardDocsRepoUrl,
    onboardDocsDefaultBranch,
    setOnboardDocsDefaultBranch,
    onboardApirefRepoUrl,
    setOnboardApirefRepoUrl,
    onboardApirefDefaultBranch,
    setOnboardApirefDefaultBranch,
    onboardKnownProgrammingLanguages,
    setOnboardKnownProgrammingLanguages,
    onboardLanguagePickerValue,
    setOnboardLanguagePickerValue,
    onboardCustomProgrammingLanguage,
    setOnboardCustomProgrammingLanguage,
    onboardAutoLayoutDetection,
    setOnboardAutoLayoutDetection,
    onboardAutoValidateOnly,
    setOnboardAutoValidateOnly,
    onboardFeedback,
    stagingProductFilter,
    setStagingProductFilter,
    stagingLanguageFilter,
    setStagingLanguageFilter,
    stagingVersionFilter,
    setStagingVersionFilter,
    stagingLocaleFilter,
    setStagingLocaleFilter,
    stagingSourceKindFilter,
    setStagingSourceKindFilter,
    selectedIngestionOperationId,
    setSelectedIngestionOperationId,
    selectedReviewRepoId,
    setSelectedReviewRepoId,
    selectedReviewPageSourcePath,
    setSelectedReviewPageSourcePath,
    selectedReviewChunkId,
    setSelectedReviewChunkId,
    selectedReviewManifestPath,
    setSelectedReviewManifestPath,
    runSingleIngestionBlockRef,
    jobsQuery,
    productsQuery,
    triggerIngestionMutation,
    onboardProductMutation,
    reviewArtifactPreviewMutation,
    rawMarkdownPreviewMutation,
    stagingManifestPreviewMutation,
    selectedIngestionJob,
    selectedIngestionResults,
    filteredIngestionResults,
    selectedReviewResult,
    selectedReviewPage,
    selectedReviewChunk,
    selectedReviewManifest,
    reviewArtifactPreview,
    rawMarkdownPreview,
    stagingManifestPreview,
    knownRepoOptions,
    repoOptions,
    productOptions,
    productFamilyOptions,
    productFamilyDirOptions,
    registeredProductsTotal,
    stagingProductOptions,
    stagingLanguageOptions,
    stagingVersionOptions,
    stagingLocaleOptions,
    stagingSourceKindOptions,
    normalizedOnboardProductId,
    suggestedOnboardProductFamily,
    suggestedOnboardProductFamilyDir,
    filteredProductFamilyDirOptions,
    knownProductFamilyDirSelection,
    onboardingProgrammingLanguageOptions,
    onboardingSelectedProgrammingLanguages,
    ingestionActionDisabledReason,
    onboardingActionDisabledReason,
    onboardingStepCompletion,
    onboardingReviewSummary,
    applyOnboardingSuggestions,
    addProgrammingLanguageHint,
    removeProgrammingLanguageHint,
    addCustomProgrammingLanguageHint,
    runOnboardProduct,
    nextOnboardingWizardStep,
    previousOnboardingWizardStep,
    jumpToOnboardingWizardStep,
    loadSelectedReviewArtifact,
    loadSelectedRawMarkdown,
    loadSelectedStagingManifest,
    runSingleIngestion,
    runBatchIngestion,
    scrollToRunSingleIngestionBlock,
  };
}
