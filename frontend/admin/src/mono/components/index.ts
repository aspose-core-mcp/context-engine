// "Mono" component kit — barrel export.
export { Pill } from "./Pill";
export { Tag } from "./Tag";
export { Button } from "./Button";
export type { ButtonProps } from "./Button";
export { IconButton } from "./IconButton";
export { ScopeChip } from "./ScopeChip";
export { PageHead } from "./PageHead";
export { Kpi, KpiRow } from "./Kpi";
export type { KpiProps } from "./Kpi";
export { Banner } from "./Banner";
export type { BannerProps } from "./Banner";
export { Card } from "./Card";
export { FieldLabel, Select, Input, Segmented } from "./Field";
export { Tabbed, Tabs } from "./Tabbed";
export { TableCard, Table, ExpandableRow, TableGroup, ShowMoreRow } from "./Table";
export {
  EmptyState,
  Skeleton,
  ErrorState,
  StaleBadge,
  PermissionDenied,
  ReadonlyBanner,
} from "./states";

// Re-export the lib essentials the kit consumers need.
export { Icon } from "../lib/icons";
export { cn } from "../lib/cn";
export type {
  StatusVariant,
  ZoneId,
  ButtonVariant,
  SectionKey,
  IconName,
  Locale,
  ThemeMode,
  Density,
} from "../lib/types";
