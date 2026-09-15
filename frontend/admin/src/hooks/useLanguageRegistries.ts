"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchRegistryLanguages,
  fetchRegistryLocales,
  fetchRegistryAliases,
  createRegistryLanguage,
  createRegistryLocale,
  createRegistryAlias,
  deleteRegistryLanguage,
  deleteRegistryLocale,
  deleteRegistryAlias,
} from "@/lib/admin-api";
import { uniqueSorted, buildDisabledReason } from "@/components/admin-console.utils";

export type UseLanguageRegistriesArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  selectedProductId: string;
  canWriteGlobalRegistry: boolean;
  canWriteSettings: boolean;
};

export function useLanguageRegistries(args: UseLanguageRegistriesArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    selectedProductId,
    canWriteGlobalRegistry,
    canWriteSettings,
  } = args;

  const queryClient = useQueryClient();

  const [newLangId, setNewLangId] = useState("");
  const [newLangName, setNewLangName] = useState("");
  const [newLocaleId, setNewLocaleId] = useState("");
  const [newLocaleName, setNewLocaleName] = useState("");
  const [aliasExternalId, setAliasExternalId] = useState("");
  const [aliasCanonicalId, setAliasCanonicalId] = useState("net");

  const registryLanguagesQuery = useQuery({
    queryKey: ["admin-registry-languages", apiKey],
    queryFn: () => fetchRegistryLanguages(apiKey),
    enabled: sessionIsSuccess,
  });

  const registryLocalesQuery = useQuery({
    queryKey: ["admin-registry-locales", apiKey],
    queryFn: () => fetchRegistryLocales(apiKey),
    enabled: sessionIsSuccess,
  });

  const registryAliasesQuery = useQuery({
    queryKey: ["admin-registry-aliases", apiKey, selectedProductId],
    queryFn: () => fetchRegistryAliases(apiKey, selectedProductId),
    enabled: sessionIsSuccess,
  });

  const upsertLanguageMutation = useMutation({
    mutationFn: () =>
      createRegistryLanguage(apiKey, {
        lang_id: newLangId,
        display_name: newLangName,
        enabled: true,
      }),
    onSuccess: async () => {
      setNewLangId("");
      setNewLangName("");
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-languages", apiKey] });
    },
  });

  const upsertLocaleMutation = useMutation({
    mutationFn: () =>
      createRegistryLocale(apiKey, {
        locale_id: newLocaleId,
        display_name: newLocaleName,
        enabled: true,
      }),
    onSuccess: async () => {
      setNewLocaleId("");
      setNewLocaleName("");
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-locales", apiKey] });
    },
  });

  const upsertAliasMutation = useMutation({
    mutationFn: () =>
      createRegistryAlias(apiKey, {
        product_id: selectedProductId,
        external_language_id: aliasExternalId,
        canonical_lang_id: aliasCanonicalId,
      }),
    onSuccess: async () => {
      setAliasExternalId("");
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-aliases", apiKey, selectedProductId] });
    },
  });

  const deleteLanguageMutation = useMutation({
    mutationFn: (langId: string) => deleteRegistryLanguage(apiKey, langId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-languages", apiKey] });
    },
  });

  const deleteLocaleMutation = useMutation({
    mutationFn: (localeId: string) => deleteRegistryLocale(apiKey, localeId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-locales", apiKey] });
    },
  });

  const deleteAliasMutation = useMutation({
    mutationFn: (externalLanguageId: string) =>
      deleteRegistryAlias(apiKey, selectedProductId, externalLanguageId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-registry-aliases", apiKey, selectedProductId] });
    },
  });

  const registryLanguageOptions = uniqueSorted((registryLanguagesQuery.data ?? []).map((item) => item.lang_id));
  const registryLocaleOptions = uniqueSorted((registryLocalesQuery.data ?? []).map((item) => item.locale_id));

  const registryWriteDisabledReason = buildDisabledReason({
    missingScope: !canWriteGlobalRegistry ? "superuser" : null,
    pending:
      upsertLanguageMutation.isPending ||
      upsertLocaleMutation.isPending,
    pendingMessage: "Registry update is in progress.",
  });

  const aliasWriteDisabledReason = buildDisabledReason({
    missingScope: !canWriteSettings ? "write:settings" : null,
    pending: upsertAliasMutation.isPending || deleteAliasMutation.isPending,
    pendingMessage: "Alias update is in progress.",
  });

  return {
    newLangId,
    setNewLangId,
    newLangName,
    setNewLangName,
    newLocaleId,
    setNewLocaleId,
    newLocaleName,
    setNewLocaleName,
    aliasExternalId,
    setAliasExternalId,
    aliasCanonicalId,
    setAliasCanonicalId,
    registryLanguagesQuery,
    registryLocalesQuery,
    registryAliasesQuery,
    upsertLanguageMutation,
    upsertLocaleMutation,
    upsertAliasMutation,
    deleteLanguageMutation,
    deleteLocaleMutation,
    deleteAliasMutation,
    registryLanguageOptions,
    registryLocaleOptions,
    registryWriteDisabledReason,
    aliasWriteDisabledReason,
  };
}
