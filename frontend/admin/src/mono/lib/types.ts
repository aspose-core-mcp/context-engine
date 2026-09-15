/** Shared types for the "Mono" design-system kit. */

/** The closed status palette — exactly five variants (each renders dot + text). */
export type StatusVariant = "ok" | "warn" | "crit" | "info" | "neutral";

/** Console navigation zones (grouping only — never hue). */
export type ZoneId = "operations" | "observability" | "settings";

/** Button visual variants (primary is monochrome; danger=irreversible, amber=reversible-high-consequence). */
export type ButtonVariant = "btn-primary" | "btn-ghost" | "btn-danger" | "btn-amber";

/** The 17 console section keys (hash route + nav key). */
export type SectionKey =
  | "workspaces"
  | "health"
  | "indexes"
  | "coverage"
  | "catalog"
  | "ingestion"
  | "snapshots"
  | "critical"
  | "runtime"
  | "logs"
  | "analytics"
  | "campaigns"
  | "sql"
  | "retrieval"
  | "languages"
  | "apikeys"
  | "config"
  | "quality";

/** Names in the inline SVG icon set (see icons.tsx). */
export type IconName =
  | "grid"
  | "pulse"
  | "shield"
  | "layers"
  | "book"
  | "upload"
  | "camera"
  | "bell"
  | "list"
  | "bars"
  | "mega"
  | "sliders"
  | "translate"
  | "key"
  | "history"
  | "database"
  | "review"
  | "chevron"
  | "chevronR"
  | "lock"
  | "search"
  | "refresh"
  | "alert"
  | "check"
  | "sun"
  | "globe"
  | "moon"
  | "arrow"
  | "plus"
  | "download"
  | "info"
  | "play"
  | "clock"
  | "git"
  | "x";

export type Locale = "en" | "ru";
export type ThemeMode = "light" | "dark";
export type Density = "compact" | "comfortable";
