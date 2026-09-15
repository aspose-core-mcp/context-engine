"use client";

import { createContext, useCallback, useContext, type ReactNode } from "react";

import { useAdminSession } from "@/hooks/useAdminSession";
import type { AdminSession } from "@/lib/admin-api";
import { hasScope } from "@/lib/scopes";

import { useConfirm, useToast } from "./overlays";

/**
 * Shell-level admin data context. Runs the cookie/API-key session and bridges
 * the data hooks' callback args (`showAlert` / `showConfirm`) onto the
 * Mono toast/confirm, plus a scope check. Sections call their `use*` hook with
 * these values; without a reachable backend the session simply isn't successful,
 * the hook queries stay empty, and sections fall back to fixtures.
 */
export interface AdminDataValue {
  apiKey: string;
  session: AdminSession | undefined;
  sessionIsSuccess: boolean;
  sessionIsLoading: boolean;
  /** Data-hook `showAlert(message, title?)` → Mono toast. */
  showAlert: (message: string, title?: string) => void;
  /** Data-hook `showConfirm(message, action)` → Mono confirm modal. */
  showConfirm: (message: string, action: () => void) => void;
  /** Scope check; permissive until a real session loads, so fixtures-mode shows controls enabled. */
  can: (scope: string) => boolean;
}

const AdminDataCtx = createContext<AdminDataValue | null>(null);

export function AdminDataProvider({ children }: { children: ReactNode }) {
  const session = useAdminSession();
  const { toast } = useToast();
  const { confirm } = useConfirm();

  const sessionData = session.sessionQuery.data as AdminSession | undefined;

  const showAlert = useCallback((message: string) => toast(message), [toast]);
  const showConfirm = useCallback(
    (message: string, action: () => void) =>
      confirm({ title: message, tone: "amber", onConfirm: action }),
    [confirm],
  );
  const can = useCallback(
    (scope: string) => (sessionData ? hasScope(sessionData, scope) : true),
    [sessionData],
  );

  const value: AdminDataValue = {
    apiKey: session.apiKey,
    session: sessionData,
    sessionIsSuccess: session.sessionQuery.isSuccess,
    sessionIsLoading: session.sessionQuery.isLoading,
    showAlert,
    showConfirm,
    can,
  };

  return <AdminDataCtx.Provider value={value}>{children}</AdminDataCtx.Provider>;
}

export function useAdminData(): AdminDataValue {
  const v = useContext(AdminDataCtx);
  if (!v) throw new Error("useAdminData must be used within AdminDataProvider");
  return v;
}
