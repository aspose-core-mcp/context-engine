"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchProductCoverage, type ProductCoverageRow } from "@/lib/admin-api";

import { Button } from "../components/Button";
import { Input, Segmented, Select } from "../components/Field";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { Tag } from "../components/Tag";
import type { StatusVariant } from "../lib/types";
import { useAdminData } from "../shell/data";

const TABLE_COLS = 7;

// gap key (from the backend) → human label + status colour.
const GAP_META: Record<string, { label: string; variant: StatusVariant }> = {
  docs_missing: { label: "no docs indexed", variant: "crit" },
  apiref_missing: { label: "no apiref indexed", variant: "crit" },
  docs_thin: { label: "thin docs", variant: "warn" },
  no_docs_source: { label: "no docs repo", variant: "neutral" },
  no_apiref_source: { label: "no apiref repo", variant: "neutral" },
};

const FAMILY_OPTIONS = ["All families", "aspose", "groupdocs"];

function num(n: number): string {
  return n.toLocaleString("en-US");
}

function RepoCell({ repo }: { repo: string | null }) {
  if (!repo) return <span className="muted-note">—</span>;
  return (
    <a className="repo-id" href={`https://github.com/${repo}`} target="_blank" rel="noreferrer">
      {repo}
    </a>
  );
}

export function CatalogSection() {
  const data = useAdminData();
  const query = useQuery({
    queryKey: ["admin-product-coverage", data.apiKey],
    queryFn: () => fetchProductCoverage(data.apiKey),
    enabled: data.sessionIsSuccess,
    refetchInterval: 120_000,
  });

  const [family, setFamily] = useState(FAMILY_OPTIONS[0]);
  const [search, setSearch] = useState("");
  const [gapsTab, setGapsTab] = useState(0); // 0 = all, 1 = gaps only

  const rows = useMemo(() => query.data?.rows ?? [], [query.data]);
  const summary = query.data?.summary;

  const q = search.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (family !== FAMILY_OPTIONS[0] && r.family !== family) return false;
        if (gapsTab === 1 && r.gaps.length === 0) return false;
        if (
          q &&
          !r.product_id.toLowerCase().includes(q) &&
          !r.product_name.toLowerCase().includes(q)
        )
          return false;
        return true;
      }),
    [rows, family, gapsTab, q],
  );

  const head = (
    <PageHead
      title="Catalog Matrix"
      sub="Every registered Aspose/GroupDocs product with its live docs chunk count (Qdrant), apiref symbol count (Postgres), backing GitHub repos, and coverage gaps."
      actions={
        <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => query.refetch()}>
          Refresh
        </Button>
      }
    />
  );

  if (query.isError) {
    return (
      <>
        {head}
        <ErrorState
          title="Catalog coverage is unavailable"
          text="The per-product coverage feed could not be loaded, so no data is shown."
          cause="Qdrant timeout, Postgres unreachable, or an expired admin key."
          actions={
            <Button variant="btn-primary" size="sm" icon="refresh" onClick={() => query.refetch()}>
              Retry
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      {head}

      <p className="muted-note" style={{ margin: "0 0 12px" }}>
        Docs counts are live points in the <span className="mono">docs_dense_v1</span> Qdrant
        collection; apiref counts are rows in the Postgres <span className="mono">symbols</span>{" "}
        store. A product is <b>fully covered</b> when both lanes are non-empty.
      </p>

      {query.data?.postgres_error && (
        <p className="muted-note" style={{ margin: "0 0 12px" }}>
          <Pill variant="warn">apiref unavailable</Pill> {query.data.postgres_error}
        </p>
      )}

      <KpiRow cols={6}>
        <Kpi
          label="Products"
          value={summary ? String(summary.total_products) : "—"}
          foot="registered"
        />
        <Kpi
          label="With docs"
          value={
            summary ? (
              <>
                {summary.products_with_docs}
                <small>/{summary.total_products}</small>
              </>
            ) : (
              "—"
            )
          }
          foot="docs indexed"
        />
        <Kpi
          label="With apiref"
          value={
            summary ? (
              <>
                {summary.products_with_apiref}
                <small>/{summary.total_products}</small>
              </>
            ) : (
              "—"
            )
          }
          foot="symbols indexed"
        />
        <Kpi
          label="Fully covered"
          value={
            summary ? (
              <>
                {summary.products_fully_covered}
                <small>/{summary.total_products}</small>
              </>
            ) : (
              "—"
            )
          }
          foot="both lanes"
        />
        <Kpi
          label="Doc chunks"
          value={summary ? num(summary.total_docs_chunks) : "—"}
          foot="docs_dense_v1"
        />
        <Kpi
          label="Apiref symbols"
          value={summary ? num(summary.total_apiref_symbols) : "—"}
          foot="symbols store"
        />
      </KpiRow>

      <div className="toolbar">
        <Select
          width={160}
          options={FAMILY_OPTIONS}
          value={family}
          aria-label="Filter by family"
          onChange={(e) => setFamily(e.target.value)}
        />
        <Input
          width={200}
          placeholder="Filter by product…"
          value={search}
          aria-label="Filter by product"
          onChange={(e) => setSearch(e.target.value)}
        />
        <Segmented
          options={["All products", "Gaps only"]}
          active={gapsTab}
          onChange={setGapsTab}
          ariaLabel="Filter by coverage gaps"
        />
        <div className="toolbar-right">
          <span className="muted-note">
            Showing {filtered.length} of {rows.length} products
          </span>
        </div>
      </div>

      <div className="tablecard">
        <table className="tbl">
          <thead>
            <tr>
              <th>Product</th>
              <th style={{ width: 84 }}>Family</th>
              <th className="num" style={{ width: 96 }}>
                Docs
              </th>
              <th className="num" style={{ width: 104 }}>
                ApiRef
              </th>
              <th>Docs repo</th>
              <th>ApiRef repo</th>
              <th style={{ width: 200 }}>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {query.isLoading ? (
              <tr>
                <td colSpan={TABLE_COLS}>
                  <div style={{ padding: 16 }}>
                    <Skeleton rows={8} />
                  </div>
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={TABLE_COLS}>
                  <EmptyState
                    title="No products match the current filters"
                    text="Clear the family / gaps filter or adjust the product search."
                    action={
                      <Button
                        variant="btn-ghost"
                        size="sm"
                        onClick={() => {
                          setFamily(FAMILY_OPTIONS[0]);
                          setSearch("");
                          setGapsTab(0);
                        }}
                      >
                        Clear filters
                      </Button>
                    }
                  />
                </td>
              </tr>
            ) : (
              filtered.map((r) => <CatalogRow key={r.product_id} row={r} />)
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function CatalogRow({ row }: { row: ProductCoverageRow }) {
  return (
    <tr className="data">
      <td>
        <span className="repo-id">{row.product_id}</span>
      </td>
      <td>
        <Tag>{row.family}</Tag>
      </td>
      <td className="num">
        {row.docs_chunks > 0 ? num(row.docs_chunks) : <span className="muted-note">0</span>}
      </td>
      <td className="num">
        {row.apiref_symbols > 0 ? num(row.apiref_symbols) : <span className="muted-note">0</span>}
      </td>
      <td>
        <RepoCell repo={row.docs_repo} />
      </td>
      <td>
        <RepoCell repo={row.apiref_repo} />
      </td>
      <td>
        {row.gaps.length === 0 ? (
          <Pill variant="ok">complete</Pill>
        ) : (
          <span className="signals" style={{ flexWrap: "wrap", gap: 6 }}>
            {row.gaps.map((g) => {
              const meta = GAP_META[g] ?? { label: g, variant: "neutral" as StatusVariant };
              return (
                <Pill key={g} variant={meta.variant}>
                  {meta.label}
                </Pill>
              );
            })}
          </span>
        )}
      </td>
    </tr>
  );
}
