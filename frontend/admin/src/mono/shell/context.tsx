"use client";

import { createContext, useContext } from "react";

import type { SectionKey } from "../lib/types";

/** Aggregate system status shown in the topbar chip + status popover. */
export type SystemStatus = "operational" | "degraded" | "partial" | "major";

const SYSTEM_STATUSES: readonly SystemStatus[] = ["operational", "degraded", "partial", "major"];

/** Narrow an arbitrary persisted string to a {@link SystemStatus}. */
export function isSystemStatus(value: string): value is SystemStatus {
  return (SYSTEM_STATUSES as readonly string[]).includes(value);
}

/**
 * Cross-section prefill payload handed off through {@link ShellContextValue.navigate}.
 * The source section stashes it under the target {@link SectionKey}; the target
 * drains it once on mount via {@link ShellContextValue.consumeIntent} (one-shot).
 */
export interface SectionIntent {
  /** Filter values to pre-apply in the target section (e.g. `{ product: "ocr" }`). */
  filters?: Record<string, string>;
  /** When `true`, the target section should clear its current state before applying. */
  reset?: boolean;
}

export interface ShellContextValue {
  /** Active console section. */
  section: SectionKey;
  /**
   * Navigate to a section (updates hash + active nav + breadcrumb).
   * Optional `anchor` deep-links to an element id within the target section,
   * scrolling it into view and moving focus after the section mounts.
   * Optional `intent` stashes a one-shot prefill payload for the target section,
   * drained on mount via {@link consumeIntent}.
   */
  navigate: (key: SectionKey, anchor?: string, intent?: SectionIntent) => void;
  /**
   * Drain the pending prefill {@link SectionIntent} for `key`, returning it (or
   * `null` if none) and clearing it so it applies exactly once.
   */
  consumeIntent: (key: SectionKey) => SectionIntent | null;
  /** Open the ⌘K command palette. */
  openPalette: () => void;
  /** Aggregate status (drives the chip + components recolor). */
  status: SystemStatus;
  setStatus: (status: SystemStatus) => void;
}

export const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const v = useContext(ShellContext);
  if (!v) throw new Error("useShell must be used within the Shell");
  return v;
}
