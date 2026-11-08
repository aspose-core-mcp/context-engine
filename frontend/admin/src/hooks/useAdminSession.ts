"use client";

import { FormEvent, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchAdminSession,
  loginAdminSession,
  logoutAdminSession,
} from "@/lib/admin-api";
import { COOKIE_SESSION_SENTINEL } from "@/components/admin-console.types";
import { getAdminErrorMessage } from "@/components/admin-console.utils";

export function useAdminSession() {
  const queryClient = useQueryClient();

  // Local serving has no login UI (the mono console relies on a pre-existing
  // session cookie). When the app is built with NEXT_PUBLIC_ADCS_ADMIN_API_KEY
  // set (local dev only), seed the session with that key so every request
  // authenticates via x-api-key — no cookie/login needed, and it survives api
  // restarts. Unset (prod default) → cookie-session mode, unchanged.
  const seededKey = process.env.NEXT_PUBLIC_ADCS_ADMIN_API_KEY?.trim();
  const [apiKey, setApiKey] = useState(seededKey || COOKIE_SESSION_SENTINEL);
  const [loginPending, setLoginPending] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [rememberDevice, setRememberDevice] = useState(true);
  const loginApiKeyFieldRef = useRef<HTMLInputElement | null>(null);

  const sessionQuery = useQuery({
    queryKey: ["admin-session", apiKey],
    queryFn: () => fetchAdminSession(apiKey === COOKIE_SESSION_SENTINEL ? "" : apiKey),
    enabled: apiKey.length > 0,
  });

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const rawApiKey = formData.get("admin_api_key");
    const normalizedKey = typeof rawApiKey === "string" ? rawApiKey.trim() : "";
    if (!normalizedKey) {
      return;
    }
    setLoginPending(true);
    setLoginError(null);
    try {
      await loginAdminSession(normalizedKey, rememberDevice);
      if (loginApiKeyFieldRef.current) {
        loginApiKeyFieldRef.current.value = "";
      }
      setApiKey(COOKIE_SESSION_SENTINEL);
      await queryClient.invalidateQueries({ queryKey: ["admin-session"] });
    } catch (error: unknown) {
      const message = getAdminErrorMessage(error, "Failed to sign in.");
      setLoginError(message);
      setApiKey("");
    } finally {
      setLoginPending(false);
    }
  }

  async function handleLogout() {
    try {
      await logoutAdminSession(apiKey === COOKIE_SESSION_SENTINEL ? "" : apiKey);
    } catch {
      // best-effort logout
    }
    setApiKey("");
    setLoginError(null);
    if (loginApiKeyFieldRef.current) {
      loginApiKeyFieldRef.current.value = "";
    }
    queryClient.clear();
  }

  const shouldShowLoginForm =
    !apiKey || (sessionQuery.isError && apiKey === COOKIE_SESSION_SENTINEL);

  return {
    apiKey,
    setApiKey,
    loginPending,
    loginError,
    rememberDevice,
    setRememberDevice,
    loginApiKeyFieldRef,
    sessionQuery,
    shouldShowLoginForm,
    handleLogin,
    handleLogout,
  };
}
