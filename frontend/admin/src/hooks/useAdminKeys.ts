"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import type { AdminKeyCreateResponse, AdminKeyRecord } from "@/lib/admin-api";
import { useToast } from "@/hooks/useToast";
import {
  fetchAdminKeys,
  fetchAdminKeyAudit,
  createAdminKey,
  disableAdminKey,
  enableAdminKey,
  updateAdminKeyScopes,
  rotateAdminKey,
  exportAdminKeys,
  importAdminKeys,
} from "@/lib/admin-api";
import {
  parseCsvList,
  buildDisabledReason,
  getAdminErrorMessage,
} from "@/components/admin-console.utils";

export type UseAdminKeysArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  canManageKeys: boolean;
  showAlert: (message: string, title?: string) => void;
  showPrompt: (title: string, label: string, defaultValue: string, action: (value: string) => void) => void;
};

export function useAdminKeys(args: UseAdminKeysArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    canManageKeys,
    showAlert,
    showPrompt,
  } = args;

  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const [newKeyIsSuperuser, setNewKeyIsSuperuser] = useState(false);
  const [newKeyProductScopes, setNewKeyProductScopes] = useState("aspose.ocr");
  const [newKeyScopes, setNewKeyScopes] = useState("read:analytics,read:events");
  const [newKeyReason, setNewKeyReason] = useState("");
  const [newKeyOwnerEmail, setNewKeyOwnerEmail] = useState("");
  const [issuedKeyPreview, setIssuedKeyPreview] = useState<string | null>(null);
  const [rotatedKeyPreview, setRotatedKeyPreview] = useState<string | null>(null);

  const adminKeysQuery = useQuery({
    queryKey: ["admin-keys", apiKey],
    queryFn: () => fetchAdminKeys(apiKey),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "api-keys-access" ? 60_000 : false,
  });

  const adminKeyAuditQuery = useQuery({
    queryKey: ["admin-keys-audit", apiKey],
    queryFn: () => fetchAdminKeyAudit(apiKey, 50),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "api-keys-access" ? 60_000 : false,
  });

  const createAdminKeyMutation = useMutation({
    mutationFn: () =>
      createAdminKey(apiKey, {
        is_superuser: newKeyIsSuperuser,
        enabled: true,
        product_scopes: parseCsvList(newKeyProductScopes),
        scopes: parseCsvList(newKeyScopes),
        reason: newKeyReason.trim() || undefined,
        owner_email: newKeyOwnerEmail.trim() || undefined,
      }),
    onSuccess: async (response: AdminKeyCreateResponse) => {
      setIssuedKeyPreview(response.api_key);
      setNewKeyReason("");
      await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
      showToast("API key created successfully.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to create admin key."), "error");
    },
  });

  const disableAdminKeyMutation = useMutation({
    mutationFn: (keyId: string) => disableAdminKey(apiKey, keyId, "Disabled from admin console"),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
      showToast("API key disabled.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to update key settings."), "error");
    },
  });

  const enableAdminKeyMutation = useMutation({
    mutationFn: (keyId: string) => enableAdminKey(apiKey, keyId, "Enabled from admin console"),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
      showToast("API key enabled.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to update key settings."), "error");
    },
  });

  const updateAdminKeyScopesMutation = useMutation({
    // `reason` is optional so existing callers stay source-compatible; when the UI
    // captures an operator-provided audit reason it is sent verbatim, otherwise a
    // generic default reason is sent.
    mutationFn: (input: { keyId: string; productScopes: string[]; scopes: string[]; reason?: string }) =>
      updateAdminKeyScopes(apiKey, input.keyId, {
        product_scopes: input.productScopes,
        scopes: input.scopes,
        reason: input.reason?.trim() || "Scope update from admin console",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
      showToast("Key scopes updated.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to update key settings."), "error");
    },
  });

  const rotateAdminKeyMutation = useMutation({
    mutationFn: (keyId: string) => rotateAdminKey(apiKey, keyId),
    onSuccess: async (response: AdminKeyCreateResponse) => {
      setRotatedKeyPreview(response.api_key);
      await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
      showToast("Key rotated. Old key disabled, new key active.");
    },
    onError: (error: unknown) => {
      showToast(getAdminErrorMessage(error, "Failed to update key settings."), "error");
    },
  });

  async function runExportKeys() {
    try {
      const keys = await exportAdminKeys(apiKey);
      const blob = new Blob([JSON.stringify(keys, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `adcs-keys-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Keys exported.");
    } catch {
      showAlert("Failed to export keys.", "Export Error");
    }
  }

  async function runImportKeys() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const keys = JSON.parse(text) as AdminKeyRecord[];
        const result = await importAdminKeys(apiKey, keys);
        await queryClient.invalidateQueries({ queryKey: ["admin-keys", apiKey] });
        await queryClient.invalidateQueries({ queryKey: ["admin-keys-audit", apiKey] });
        showToast(`Imported ${result.imported} key(s).`);
      } catch {
        showAlert("Failed to import keys. Check file format.", "Import Error");
      }
    };
    input.click();
  }

  /**
   * Clears the one-time issued/rotated secret previews. The reveal card's Dismiss
   * action is the operator's way to clear the raw secret from screen after vaulting
   * it (security-sensitive surface).
   */
  function dismissKeyPreviews() {
    setIssuedKeyPreview(null);
    setRotatedKeyPreview(null);
  }

  const emailMissing = !newKeyOwnerEmail.trim();
  const emailInvalid = !emailMissing && !newKeyOwnerEmail.includes("@");

  const keyCreateDisabledReason = buildDisabledReason({
    missingScope: !canManageKeys ? "write:settings" : null,
    pending: createAdminKeyMutation.isPending,
    pendingMessage: "Key creation is in progress.",
    unmetCondition: emailMissing
      ? "Owner email is required."
      : emailInvalid
        ? "Owner email must contain @."
        : null,
  });

  function runKeyScopeUpdate(key: AdminKeyRecord) {
    showPrompt("Product Scopes", "Product scopes (comma-separated)", key.product_scopes.join(","), (productScopesRaw) => {
      showPrompt("Scopes", "Scopes (comma-separated)", key.scopes.join(","), (scopesRaw) => {
        const productScopes = parseCsvList(productScopesRaw);
        const scopes = parseCsvList(scopesRaw);
        if (!key.is_superuser && productScopes.length === 0) {
          showAlert("Non-superuser key must include at least one product scope.", "Validation Error");
          return;
        }
        updateAdminKeyScopesMutation.mutate({
          keyId: key.key_id,
          productScopes,
          scopes,
        });
      });
    });
  }

  return {
    newKeyIsSuperuser,
    setNewKeyIsSuperuser,
    newKeyProductScopes,
    setNewKeyProductScopes,
    newKeyScopes,
    setNewKeyScopes,
    newKeyReason,
    setNewKeyReason,
    newKeyOwnerEmail,
    setNewKeyOwnerEmail,
    issuedKeyPreview,
    rotatedKeyPreview,
    dismissKeyPreviews,
    adminKeysQuery,
    adminKeyAuditQuery,
    createAdminKeyMutation,
    disableAdminKeyMutation,
    enableAdminKeyMutation,
    updateAdminKeyScopesMutation,
    rotateAdminKeyMutation,
    keyCreateDisabledReason,
    runKeyScopeUpdate,
    runExportKeys,
    runImportKeys,
  };
}
