"use client";

import { useEffect, useState, type ReactNode } from "react";

import { getAdminErrorMessage } from "@/components/admin-console.utils";
import { useHealthQueries } from "@/hooks/useHealthQueries";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { IconButton } from "../components/IconButton";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { ShowMoreRow, Table, TableCard } from "../components/Table";
import { Tag } from "../components/Tag";
import { EmptyState, ErrorState, Skeleton, StaleBadge } from "../components/states";
import { Icon } from "../lib/icons";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";
import { PopoverPanel, usePopover } from "../shell/Popover";

// ─────────────────────────────────────────────────────────── fixtures ───────

// Cap the per-product table on first paint; the rest collapse behind a "+N more" row.
// Production carries 70+ indexed repos, so the list must not render unbounded.
const VISIBLE_QDRANT_ROWS = 8;

interface QdrantRow {
  product: string;
  collection: string;
  points: string;
}

const QDRANT_PROD: QdrantRow[] = [
  { product: "aspose.cells.apiref", collection: "docs_dense_v1", points: "52 412" },
  { product: "aspose.barcode.apiref", collection: "docs_dense_v1", points: "31 905" },
  { product: "aspose.cad.apiref", collection: "docs_dense_v1", points: "18 060" },
  { product: "aspose.ocr.apiref", collection: "apiref_dense_v1", points: "24 318" },
  { product: "aspose.3d.apiref", collection: "apiref_dense_v1", points: "8 142" },
  { product: "aspose.words.apiref", collection: "apiref_dense_v1", points: "0" },
];

interface OsRow {
  alias: string;
  index: string;
  documents: string;
}

const OS_ALIAS: OsRow[] = [
  { alias: "docs-latest", index: "docs_lex_v1", documents: "61 204" },
  { alias: "apiref-latest", index: "apiref_lex_v1", documents: "48 530" },
  { alias: "docs-archive", index: "docs_lex_v1", documents: "12 880" },
  { alias: "apiref-archive", index: "apiref_lex_v1", documents: "9 442" },
];

// API limitation: the index-status opensearch payload carries no per-alias index name.
// Resolve a real index name for live alias rows from this naming convention so the
// table confirms data landed on the alias for live rows too (not "—").
const OS_INDEX_BY_ALIAS: Record<string, string> = {
  "docs-latest": "docs_lex_v1",
  "apiref-latest": "apiref_lex_v1",
  "docs-archive": "docs_lex_v1",
  "apiref-archive": "apiref_lex_v1",
};
function osIndexForAlias(alias: string): string {
  const known = OS_INDEX_BY_ALIAS[alias];
  if (known) return known;
  // Derive `<kind>_lex_v1` from the alias prefix (e.g. "docs-foo" → "docs_lex_v1").
  const prefix = alias.split("-")[0];
  return prefix ? `${prefix}_lex_v1` : "—";
}

// API limitation: IndexStatusResponse has no generated_at field, so freshness can't be
// read from the live payload. ONLINE the label anchors to the query's dataUpdatedAt
// (last successful fetch — resets after every 60s auto-refresh / manual refetch);
// OFFLINE it anchors to this fixture instant so the timestamp still renders and ticks.
const INDEX_STATUS_META = { generatedAt: Date.now() - 24_000 };

function agoLabel(fromMs: number, nowMs: number): string {
  const secs = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  if (secs < 90) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

// Match the fixtures' space-grouped thousands so live + offline numbers render identically.
function grp(n: number): string {
  return n.toLocaleString("en-US").replace(/,/g, " ");
}

// Per-product Qdrant table row — shared by the head slice and the "+N more" overflow.
function renderQdrantRow(r: QdrantRow): ReactNode {
  return (
    <tr className="data" key={`${r.collection}:${r.product}`}>
      <td>
        <span className="cell-repo">
          <span className="repo-id">{r.product}</span>
        </span>
      </td>
      <td>
        <Tag>{r.collection}</Tag>
      </td>
      <td className="num">
        {r.points === "0" ? <span style={{ color: "var(--crit)" }}>0</span> : r.points}
      </td>
    </tr>
  );
}

// ── Inline copy-metric control ("Copy metric value") ──
// Copies the raw metric text to clipboard for documentation / cross-reference.
function CopyMetric({
  value,
  copy,
  label,
}: {
  value: ReactNode;
  copy: string;
  label: string;
}) {
  const { toast } = useToast();
  return (
    <span className="copy-metric" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {value}
      <IconButton
        icon="download"
        aria-label={`Copy ${label} (${copy})`}
        title={`Copy ${label}`}
        onClick={() => {
          void navigator.clipboard?.writeText(copy).catch(() => {});
          toast(`Copied ${label}: ${copy}`);
        }}
      />
    </span>
  );
}

// ── Inline per-card How-To help popover (per-subsection help) ──
// Reuses the shell Popover classes; Esc/outside-click close handled by usePopover.
interface HelpItem {
  q: string;
  a: ReactNode;
}
function HelpPopover({
  title,
  items,
}: {
  title: string;
  items: HelpItem[];
}) {
  const pop = usePopover();
  return (
    <div className="pop-wrap" ref={pop.wrapRef} style={{ position: "relative" }}>
      <IconButton
        icon="info"
        aria-label={`Help: ${title}`}
        aria-haspopup="menu"
        aria-expanded={pop.open}
        onClick={pop.toggle}
      />
      {pop.open && (
        <PopoverPanel className="pop-help">
          <div className="pop-head">
            <span className="pt">{title}</span>
            <span className="ps">runbook</span>
          </div>
          <div className="pop-body">
            {items.map((it) => (
              <div key={it.q} style={{ padding: "6px 0" }}>
                <div className="pop-sub" style={{ margin: "0 0 3px" }}>
                  {it.q}
                </div>
                <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5 }}>{it.a}</div>
              </div>
            ))}
          </div>
          <div className="pop-foot">
            <a
              href="/howto"
              className="btn btn-ghost btn-sm"
              style={{ textDecoration: "none" }}
            >
              <Icon name="arrow" className="ico" />
              Open full How-To
            </a>
          </div>
        </PopoverPanel>
      )}
    </div>
  );
}

export function IndexesSection() {
  const { navigate } = useShell();
  const { toast } = useToast();
  const data = useAdminData();
  // Reuses the Health hook's topologyPolicyQuery + indexStatusQuery (read-only).
  // The mandatory canConfigureAbuseGuard arg is unused here; satisfied via write:settings.
  const health = useHealthQueries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "indexes-topology",
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    canConfigureAbuseGuard: data.can("write:settings"),
  });

  // Advertised "Auto-refresh 60s" (page head + freshness line): useHealthQueries only
  // interval-refetches indexStatusQuery while the HEALTH section is active
  // (refetchInterval gated on activeSectionId === "health"), so while this section is
  // mounted the live counts would never background-refresh. Drive the interval here.
  // Paused OFFLINE — refetch() force-fetches even disabled queries, which would poll a
  // backend that is not there. (topologyPolicyQuery already self-refetches every 60s.)
  const online = data.sessionIsSuccess;
  const refetchIndexStatus = health.indexStatusQuery.refetch;
  useEffect(() => {
    if (!online) return undefined;
    const id = window.setInterval(() => {
      // Mirror TanStack's refetchIntervalInBackground default: skip hidden tabs.
      if (document.hidden) return;
      void refetchIndexStatus();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [online, refetchIndexStatus]);

  // 1s tick so the "Live counts generated Xs ago" label counts up in real time
  // instead of only updating on incidental re-renders.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const topology = health.topologyPolicyQuery.data;
  const indexStatus = health.indexStatusQuery.data;

  // ── Topology card: live policy, else fixture banner/KPIs ──
  const topoLoading = health.topologyPolicyQuery.isLoading && !topology;
  const topoErrored =
    (health.topologyPolicyQuery.isError && !topology) || (!!topology && !health.topologyPolicyReady);
  const topoProfile = topology?.profile ?? "dev";
  const topoPersistence = topology?.persistence_backend ?? "memory";
  const topoRetrieval = topology?.retrieval_backend ?? "memory";
  const qShards = topology?.qdrant.shard_number ?? 1;
  const qReplicas = topology?.qdrant.replication_factor ?? 1;
  const qWriteConsistency = topology?.qdrant.write_consistency_factor;
  const osShards = topology?.opensearch.number_of_shards ?? 1;
  const osReplicas = topology?.opensearch.number_of_replicas ?? 0;
  const osRefresh = topology?.opensearch.refresh_interval ?? "1s";
  const compactionOn = topology?.compaction.enabled ?? false;
  const keepInactive = topology?.compaction.max_inactive_snapshots_per_scope ?? 3;
  const staleDays = topology?.compaction.stale_snapshot_retention_days ?? 30;
  const hotTier = topology?.storage_tiering.latest_stable_tier ?? "hot";
  const warmTier = topology?.storage_tiering.archive_tier ?? "warm";
  const topoConfigPath = topology?.config_path ?? "index-topology-policy.json";
  // Surface a summary of the live endpoint error, falling
  // back to the static description when there is no error object (e.g. policy resolved
  // but incomplete → topologyPolicyReady false).
  const topoErrorText = health.topologyPolicyQuery.isError
    ? getAdminErrorMessage(
        health.topologyPolicyQuery.error,
        "The index-topology-policy.json endpoint did not return a valid resolved policy.",
      )
    : "The index-topology-policy.json endpoint did not return a valid resolved policy.";
  const topoBannerTitle = `profile=${topoProfile} · persistence=${topoPersistence} · retrieval=${topoRetrieval}`;
  const topoBannerText = topology?.summary
    ? topology.summary
    : `Resolved at startup from ${topoConfigPath} · qdrant ${qShards} shard / ${qReplicas} replica · opensearch ${osShards} shard / ${osReplicas} replica · compaction ${compactionOn ? "on" : "off"}`;

  // ── Live index status: summary KPIs + breakdown rows ──
  const statusLoading = health.indexStatusQuery.isLoading && !indexStatus;
  // Error gate mirrors Health: only when the live fetch failed AND no payload is held.
  // Offline (query disabled) this is false, so fixtures/last-good KPIs always render.
  const statusErrored = health.indexStatusQuery.isError && !indexStatus;
  const qdrantTotalNum = indexStatus ? indexStatus.summary.total_qdrant_points : 134_937;
  const osTotalNum = indexStatus ? indexStatus.summary.total_opensearch_docs : 132_056;
  const qdrantTotal = grp(qdrantTotalNum);
  const osTotal = grp(osTotalNum);
  const qdrantCollectionCount = indexStatus ? Object.keys(indexStatus.qdrant).length : 2;

  // Live Qdrant↔OpenSearch parity delta — points/docs should be in rough parity;
  // a wide gap flags a pipeline issue. Computed from the totals (not static copy).
  const parityDelta = Math.abs(qdrantTotalNum - osTotalNum);
  const parityLabel = `Δ ${grp(parityDelta)} ${qdrantTotalNum >= osTotalNum ? "more vectors than docs" : "more docs than vectors"}`;

  // Freshness label: with a live payload, anchored to the query's last successful
  // fetch (dataUpdatedAt) so it resets after each background/manual refresh; offline,
  // anchored to the fixture instant. nowMs makes it tick every second either way.
  const generatedAtMs =
    indexStatus && health.indexStatusQuery.dataUpdatedAt
      ? health.indexStatusQuery.dataUpdatedAt
      : INDEX_STATUS_META.generatedAt;
  const generatedLabel = agoLabel(generatedAtMs, nowMs);

  // Per-alias OpenSearch counts power both the breakdown table and the summary foot.
  // Display source with fixture fallback — the alias table is never hidden offline.
  const osAliasRows: OsRow[] = indexStatus
    ? Object.entries(indexStatus.opensearch).map(([alias, item]) => ({
        alias,
        // Index name resolved from a naming-convention fixture (see osIndexForAlias).
        index: osIndexForAlias(alias),
        documents: grp(item.total_docs),
      }))
    : OS_ALIAS;
  const osFoot = indexStatus
    ? Object.entries(indexStatus.opensearch)
        .map(([alias, item]) => `${alias} ${grp(item.total_docs)}`)
        .join(" · ") || "no aliases"
    : "docs_lex 74 084 · apiref_lex 57 972";

  // Per-collection failures for BOTH backends (Qdrant AND OpenSearch errors).
  const qdrantErrors = indexStatus
    ? Object.entries(indexStatus.qdrant).filter(([, c]) => c.error)
    : [];
  const osErrors = indexStatus
    ? Object.entries(indexStatus.opensearch).filter(([, a]) => a.error)
    : [];
  const hasLiveCollectionError = qdrantErrors.length > 0 || osErrors.length > 0;

  // Per-product Qdrant breakdown: flatten products across dense collections, by volume.
  const liveQdrantRows: QdrantRow[] = indexStatus
    ? Object.entries(indexStatus.qdrant)
        .flatMap(([collection, c]) =>
          Object.entries(c.products).map(([product, points]) => ({
            product,
            collection,
            points: grp(points),
          })),
        )
        .sort((a, b) => Number(b.points.replace(/ /g, "")) - Number(a.points.replace(/ /g, "")))
    : [];
  // Live vs fixture: fixtures stand in only OFFLINE (no live payload held — queries
  // are disabled without a session). A live payload whose registry holds zero products
  // is a REAL empty registry ("Empty (no products)") and must render the
  // EmptyState below — never the fixture table with fake counts.
  const qdrantRows = indexStatus ? liveQdrantRows : QDRANT_PROD;
  // Gate the empty-state on the DISPLAY set: offline it is the (non-empty) fixture
  // table, so the interactive UI is never hidden; online-empty it is [] → EmptyState.
  const qdrantEmpty = !qdrantRows.length;

  // Live staleness: a held payload past its staleTime awaiting background refresh
  // ("Stale data" state). False offline (disabled queries are not stale).
  const isStale = !!indexStatus && health.indexStatusQuery.isStale;

  return (
    <>
      <PageHead
        title="Indexes & Topology"
        sub="Resolved Qdrant/OpenSearch topology policy and real-time index point & document counts."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            {isStale ? (
              <StaleBadge>stale · cache</StaleBadge>
            ) : (
              <span className="muted-note">Auto-refresh 60s</span>
            )}
            <Button
              variant="btn-ghost"
              size="sm"
              icon="arrow"
              onClick={() => navigate("snapshots")}
            >
              View snapshots
            </Button>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              onClick={() => {
                toast("Refreshing topology & index status…");
                health.topologyPolicyQuery.refetch();
                health.indexStatusQuery.refetch();
              }}
            >
              Refresh all
            </Button>
          </>
        }
      />

      {/* ── Index topology policy ─────────────────────────────────────────── */}
      <Card
        title="Index topology policy"
        sub="Resolved shard, replica, retention and storage-tiering policy for the current runtime profile."
        right={
          <HelpPopover
            title="Topology policy verification"
            items={[
              {
                q: "Why",
                a: "Confirm the runtime is running the intended environment configuration after a shard, replica, or refresh-interval change.",
              },
              {
                q: "What",
                a: "Profile, Qdrant shards/replicas, OpenSearch shards/refresh, retention thresholds and storage tiers are resolved once at startup and shown read-only.",
              },
              {
                q: "How",
                a: "After a config push or restart, use Retry topology to re-resolve, then verify each card matches the expected values; mismatch = policy drift.",
              },
            ]}
          />
        }
      >
        {topoLoading ? (
          <Skeleton rows={4} />
        ) : topoErrored ? (
          <ErrorState
            title="Topology policy is unavailable"
            text={topoErrorText}
            cause="malformed JSON or a missing policy file at startup."
            actions={
              <>
                <Button
                  variant="btn-primary"
                  size="sm"
                  icon="refresh"
                  onClick={() => health.topologyPolicyQuery.refetch()}
                >
                  Retry topology
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="arrow"
                  onClick={() => navigate("logs")}
                >
                  Open Logs &amp; Traces
                </Button>
              </>
            }
          />
        ) : (
          <>
            <Banner variant="info" icon="info" title={topoBannerTitle} text={topoBannerText} />
            <KpiRow cols={4}>
              <Kpi
                label="Profile"
                value={<CopyMetric value={topoProfile} copy={topoProfile} label="profile" />}
                foot={`${topoPersistence} persistence`}
              />
              <Kpi
                label="Qdrant"
                value={
                  <CopyMetric
                    value={
                      <>
                        {qShards}
                        <small>
                          {" "}
                          sh / {qReplicas} rp
                        </small>
                      </>
                    }
                    copy={`${qShards} shards / ${qReplicas} replicas`}
                    label="Qdrant shards/replicas"
                  />
                }
                foot={
                  qWriteConsistency != null
                    ? `write consistency = ${qWriteConsistency}`
                    : "write consistency = all"
                }
              />
              <Kpi
                label="OpenSearch"
                value={
                  <CopyMetric
                    value={
                      <>
                        {osShards}
                        <small>
                          {" "}
                          sh / {osReplicas} rp
                        </small>
                      </>
                    }
                    copy={`${osShards} shards / ${osReplicas} replicas`}
                    label="OpenSearch shards/replicas"
                  />
                }
                foot={`refresh interval ${osRefresh}`}
              />
              <Kpi
                label="Retention"
                value={
                  <CopyMetric
                    value={compactionOn ? "on" : "off"}
                    copy={`compaction ${compactionOn ? "on" : "off"} · keep ${keepInactive} inactive · stale ${staleDays}d`}
                    label="retention policy"
                  />
                }
                foot={`keep ${keepInactive} inactive · stale ${staleDays}d`}
              />
            </KpiRow>
            <div className="muted-note" style={{ marginTop: 4 }}>
              Storage tiering: latest stable = {hotTier} · archive = {warmTier} · config ={" "}
              {topoConfigPath} · resolved{" "}
              {topology?.generated_at ? new Date(topology.generated_at).toLocaleString() : "at startup"}
            </div>
          </>
        )}
      </Card>

      {/* ── Live index status ─────────────────────────────────────────────── */}
      <Card
        title="Live index status"
        sub="Real-time point and document counts from Qdrant and OpenSearch."
        right={
          <HelpPopover
            title="Post-ingestion validation"
            items={[
              {
                q: "Why",
                a: "Confirm an ingestion run actually landed — zero points = complete ingestion failure; a wide vector↔doc gap signals a pipeline issue.",
              },
              {
                q: "What",
                a: "Total Qdrant points and OpenSearch docs with a live parity delta, plus per-collection error surfacing for both backends.",
              },
              {
                q: "How",
                a: "Compare totals against the ingestion manifest; if a fetch times out use Retry; for backend errors open Logs & Traces and check the Health section.",
              },
            ]}
          />
        }
      >
        {statusLoading ? (
          <Skeleton rows={3} />
        ) : statusErrored ? (
          <ErrorState
            title="Index status unavailable"
            text="Live point and document counts could not be fetched from Qdrant and OpenSearch."
            cause="a backend query timed out (>5s) or a retrieval service is unreachable."
            actions={
              <Button
                variant="btn-primary"
                size="sm"
                icon="refresh"
                onClick={() => health.indexStatusQuery.refetch()}
              >
                Retry
              </Button>
            }
          />
        ) : (
          <>
            <KpiRow cols={2}>
              <Kpi
                label="Qdrant total points"
                value={
                  <CopyMetric value={qdrantTotal} copy={qdrantTotal} label="Qdrant total points" />
                }
                foot={`across ${qdrantCollectionCount} dense collections`}
                accent
              />
              <Kpi
                label="OpenSearch total docs"
                value={
                  <CopyMetric value={osTotal} copy={osTotal} label="OpenSearch total docs" />
                }
                foot={osFoot}
              />
            </KpiRow>
            <div className="muted-note" style={{ marginTop: 6 }}>
              {/* API limitation: index-status payload has no generated_at; freshness is anchored to
                  the INDEX_STATUS_META fixture instant. Parity Δ IS computed from live totals. */}
              <Icon name="clock" className="ico" /> Live counts generated {generatedLabel} ·
              auto-refresh 60s · points/docs should be in rough parity ({parityLabel})
            </div>
            {/* Per-collection Qdrant failures ("Qdrant unreachable or error: <reason>") */}
            {qdrantErrors.map(([collection, c]) => (
              <div className="crit-row" key={`q:${collection}`}>
                <Icon name="alert" />
                <span>
                  {collection} — Qdrant unreachable or error: {c.error} · serving
                  stale-while-revalidate
                </span>
                <span style={{ marginLeft: "auto" }}>
                  <Button variant="btn-ghost" size="sm" onClick={() => navigate("logs")}>
                    Open Logs
                  </Button>
                </span>
              </div>
            ))}
            {/* Per-alias OpenSearch failures. */}
            {osErrors.map(([alias, a]) => (
              <div className="crit-row" key={`os:${alias}`}>
                <Icon name="alert" />
                <span>
                  {alias} — OpenSearch unreachable or error: {a.error} · serving
                  stale-while-revalidate
                </span>
                <span style={{ marginLeft: "auto" }}>
                  <Button variant="btn-ghost" size="sm" onClick={() => navigate("logs")}>
                    Open Logs
                  </Button>
                </span>
              </div>
            ))}
            {/* Offline / no-live-payload fixture degraded sample so the failure surface is
                visible without a backend; suppressed once any live error renders. */}
            {!indexStatus && !hasLiveCollectionError && (
              <div className="crit-row">
                <Icon name="alert" />
                <span>
                  docs_dense_v1 — Qdrant unreachable or error: partial shard timeout (&gt;5s) ·
                  serving stale-while-revalidate
                </span>
                <span style={{ marginLeft: "auto" }}>
                  <Button variant="btn-ghost" size="sm" onClick={() => navigate("logs")}>
                    Open Logs
                  </Button>
                </span>
              </div>
            )}
          </>
        )}
      </Card>

      {/* ── Per-product Qdrant breakdown ──────────────────────────────────── */}
      <Card
        title="Per-product Qdrant breakdown"
        sub="Vector points per product across dense collections — sorted by volume. Zero points = ingestion targeted the wrong collection or never ran."
        flush
        right={
          <HelpPopover
            title="Capacity planning & triage"
            items={[
              {
                q: "Why",
                a: "Identify which products are missing data, and review total indexed volume to estimate scale-out and retention needs.",
              },
              {
                q: "What",
                a: "Per-product vector counts across docs_dense_v1 and apiref_dense_v1, sorted highest-volume first; zero counts are flagged.",
              },
              {
                q: "How",
                a: "A zero or missing product means ingestion targeted the wrong collection or never ran — re-run from Ingestion Jobs, or register it in Language Registries.",
              },
            ]}
          />
        }
      >
        {qdrantEmpty ? (
          <EmptyState
            title="No products configured"
            text="No products are registered in the source registry, so there are no per-product breakdowns to show. Register a product in Language Registries to populate this table."
            action={
              <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("languages")}>
                Open Language Registries
              </Button>
            }
          />
        ) : (
          <TableCard>
            <Table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th style={{ width: 170 }}>Collection</th>
                  <th className="num" style={{ width: 110 }}>
                    Points
                  </th>
                </tr>
              </thead>
              <tbody>
                {qdrantRows.slice(0, VISIBLE_QDRANT_ROWS).map(renderQdrantRow)}
                {qdrantRows.length > VISIBLE_QDRANT_ROWS && (
                  <ShowMoreRow
                    count={qdrantRows.length - VISIBLE_QDRANT_ROWS}
                    colSpan={3}
                    extra={qdrantRows.slice(VISIBLE_QDRANT_ROWS).map(renderQdrantRow)}
                  />
                )}
              </tbody>
            </Table>
          </TableCard>
        )}
      </Card>

      {/* ── Per-alias OpenSearch breakdown ────────────────────────────────── */}
      <Card
        title="Per-alias OpenSearch breakdown"
        sub="Document counts per alias — confirms data landed on the alias search queries read from."
        flush
        right={
          <HelpPopover
            title="Lexical alias validation"
            items={[
              {
                q: "Why",
                a: "Confirm BM25 search reads a populated index — retrieval queries hit the alias, so a zero-doc alias means lexical results silently vanish even when Qdrant is healthy.",
              },
              {
                q: "What",
                a: "Document counts per OpenSearch alias (docs-latest, apiref-latest and their archives) with the concrete index each alias resolves to.",
              },
              {
                q: "How",
                a: "Compare each alias count against the matching Qdrant collection; a populated collection with a near-empty alias means the lexical write lane lagged — re-run from Ingestion Jobs and check Logs & Traces.",
              },
            ]}
          />
        }
      >
        <TableCard>
          <Table>
            <thead>
              <tr>
                <th>Alias</th>
                <th style={{ width: 170 }}>Index</th>
                <th className="num" style={{ width: 110 }}>
                  Documents
                </th>
              </tr>
            </thead>
            <tbody>
              {osAliasRows.map((r) => (
                <tr className="data" key={r.alias}>
                  <td>
                    <span className="cell-repo">
                      <span className="repo-id">{r.alias}</span>
                    </span>
                  </td>
                  <td>
                    <Tag>{r.index}</Tag>
                  </td>
                  <td className="num">{r.documents}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
      </Card>
    </>
  );
}
