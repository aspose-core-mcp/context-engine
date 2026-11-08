import type { IconName, SectionKey, ZoneId } from "./types";

export interface NavItem {
  key: SectionKey;
  icon: IconName;
  /** English default label (localized at render via i18n). */
  label: string;
  /** Scope-gated: render a lock and stay visible (never hidden). */
  locked?: boolean;
  /** Optional count badge, e.g. "19". */
  badge?: string;
}

export interface NavZone {
  id: ZoneId;
  /** English default zone label (localized at render). */
  label: string;
  items: NavItem[];
}

/** Navigation model — 3 zones, 18 sections. */
export const NAV: NavZone[] = [
  {
    id: "operations",
    label: "Operations",
    items: [
      { key: "workspaces", icon: "grid", label: "Workspaces" },
      { key: "health", icon: "pulse", label: "Health" },
      { key: "indexes", icon: "layers", label: "Indexes & Topology" },
      { key: "coverage", icon: "book", label: "Content Coverage" },
      { key: "catalog", icon: "database", label: "Catalog Matrix" },
      { key: "ingestion", icon: "upload", label: "Ingestion Jobs", locked: true },
      { key: "snapshots", icon: "camera", label: "Snapshots", locked: true },
      { key: "critical", icon: "bell", label: "Critical Events", locked: true },
    ],
  },
  {
    id: "observability",
    label: "Observability",
    items: [
      { key: "runtime", icon: "shield", label: "Runtime Guard & MCP" },
      { key: "logs", icon: "list", label: "Logs & Traces" },
      { key: "analytics", icon: "bars", label: "Analytics" },
      { key: "campaigns", icon: "mega", label: "Coverage Campaigns", badge: "19" },
      { key: "sql", icon: "database", label: "SQL Explorer" },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    items: [
      { key: "retrieval", icon: "sliders", label: "Retrieval Settings" },
      { key: "languages", icon: "translate", label: "Language Registries" },
      { key: "apikeys", icon: "key", label: "API Keys & Access" },
      { key: "config", icon: "history", label: "Config History & Rollback" },
      { key: "quality", icon: "review", label: "Quality Reviews" },
    ],
  },
];

export const ALL_SECTIONS: NavItem[] = NAV.flatMap((z) => z.items);

export const SECTION_BY_KEY = Object.fromEntries(
  ALL_SECTIONS.map((i) => [i.key, i]),
) as Record<SectionKey, NavItem>;

export const ZONE_OF = Object.fromEntries(
  NAV.flatMap((z) => z.items.map((i) => [i.key, z])),
) as Record<SectionKey, NavZone>;

export const SECTION_KEYS: SectionKey[] = ALL_SECTIONS.map((i) => i.key);

/** First load defaults to the Health monitoring dashboard. */
export const DEFAULT_SECTION: SectionKey = "health";

/** A global ⌘K workspace launcher: a named task that deep-links into a section. */
export interface WorkspaceLauncher {
  /** Stable launcher id (also used as a search alias). */
  id: string;
  /** Human-readable task title rendered after the "Launch:" prefix. */
  title: string;
  /** Target console section. */
  section: SectionKey;
  /** Optional element id to deep-link + focus within the section. */
  anchor?: string;
}

/**
 * Curated workspace templates surfaced in the global ⌘K palette. Each entry
 * launches a common operator task by navigating to a section and (optionally)
 * deep-linking to the relevant panel anchor.
 */
export const WORKSPACE_LAUNCHERS: WorkspaceLauncher[] = [
  { id: "issue-triage", title: "Issue triage", section: "critical" },
  {
    id: "ingestion-run",
    title: "Ingestion run",
    section: "ingestion",
    anchor: "ingestion-run-single-panel",
  },
  {
    id: "coverage-review",
    title: "Coverage review",
    section: "coverage",
    anchor: "coverage-triage-panel",
  },
  {
    id: "quality-review",
    title: "Quality review",
    section: "quality",
    anchor: "quality-runs-panel",
  },
];

export function isSectionKey(value: string): value is SectionKey {
  return Object.prototype.hasOwnProperty.call(SECTION_BY_KEY, value);
}
