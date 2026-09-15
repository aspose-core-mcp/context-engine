import type { ComponentType } from "react";

import type { SectionKey } from "../lib/types";
import { AnalyticsSection } from "./Analytics";
import { ApiKeysSection } from "./ApiKeys";
import { CampaignsSection } from "./Campaigns";
import { CatalogSection } from "./Catalog";
import { ConfigSection } from "./Config";
import { CoverageSection } from "./Coverage";
import { CriticalSection } from "./Critical";
import { HealthSection } from "./Health";
import { IndexesSection } from "./Indexes";
import { IngestionSection } from "./Ingestion";
import { LanguagesSection } from "./Languages";
import { LogsSection } from "./Logs";
import { QualitySection } from "./Quality";
import { RetrievalSection } from "./Retrieval";
import { RuntimeSection } from "./Runtime";
import { SnapshotsSection } from "./Snapshots";
import { SqlSection } from "./Sql";
import { WorkspacesSection } from "./Workspaces";

/** Section key → React component (all 17 console sections). */
const REGISTRY: Record<SectionKey, ComponentType> = {
  workspaces: WorkspacesSection,
  health: HealthSection,
  indexes: IndexesSection,
  coverage: CoverageSection,
  catalog: CatalogSection,
  ingestion: IngestionSection,
  snapshots: SnapshotsSection,
  critical: CriticalSection,
  runtime: RuntimeSection,
  logs: LogsSection,
  analytics: AnalyticsSection,
  campaigns: CampaignsSection,
  sql: SqlSection,
  retrieval: RetrievalSection,
  languages: LanguagesSection,
  apikeys: ApiKeysSection,
  config: ConfigSection,
  quality: QualitySection,
};

export function renderSection(key: SectionKey) {
  const Section = REGISTRY[key];
  return <Section key={key} />;
}
