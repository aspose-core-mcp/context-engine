"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill } from "../../components/Pill";
import { cn } from "../../lib/cn";
import { Icon } from "../../lib/icons";
import type { StatusVariant } from "../../lib/types";
import {
  AdminApiError,
  fetchPublicMCPSelfTest,
  type PublicMCPSelfTest,
  type PublicMCPSelfTestCheck,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * MCP Connection Self-Test — section component for /integrations.
 *
 * selfTestQuery → /v1/integrations/self-test, four metric cards (Self-test
 * status · Ready services · Snippet coverage · Target client), a colored status
 * banner, and a checks list with status badges + nested detail lines, plus a
 * fix-plan.
 *
 * Live wiring: fetchPublicMCPSelfTest({ product_id, programming_language?,
 * client_id?, transport? }). Public endpoint — always enabled.
 *
 * Offline fallback:
 *   - live success            -> live PublicMCPSelfTest
 *   - live success but EMPTY   -> impossible here (object always has status); a
 *                                 zero-check payload renders the checks empty note
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file SELF_TEST_FIXTURE (fully reviewable)
 * -------------------------------------------------------------------------- */

type ClientId = "cursor" | "claude-desktop" | "qwen-code" | "vscode";
type Transport = "streamable-http" | "sse";

const CLIENT_OPTIONS: { value: ClientId; label: string }[] = [
  { value: "cursor", label: "Cursor" },
  { value: "claude-desktop", label: "Claude Desktop" },
  { value: "qwen-code", label: "Qwen Code" },
  { value: "vscode", label: "VS Code" },
];

const TRANSPORT_OPTIONS: { value: Transport; label: string }[] = [
  { value: "streamable-http", label: "streamable-http" },
  { value: "sse", label: "sse" },
];

/* ---------------- offline fixture (verbatim-shaped self-test) ------------- */

const SELF_TEST_FIXTURE: PublicMCPSelfTest = {
  product_id: "aspose.ocr",
  programming_language: "net",
  client_id: "cursor",
  transport: "streamable-http",
  status: "partial",
  status_summary:
    "Product is registered and docs + API reference are MCP-ready, but the active snapshot is aging — refresh before announcing GA.",
  docs_ready_count: 2,
  apiref_ready_count: 2,
  total_ready_services: 4,
  total_registered_services: 4,
  snippet_count: 1240,
  available_programming_languages: ["net", "java", "python"],
  available_versions: ["latest-stable", "25.1", "24.12"],
  checks: [
    {
      check_id: "product-registered",
      title: "Product registered in source registry",
      status: "pass",
      summary: "aspose.ocr resolves to a canonical product with docs + apiref repositories.",
      details: ["repo_ids: aspose.ocr.docs, aspose.ocr.apiref", "product_family: aspose"],
    },
    {
      check_id: "content-ready",
      title: "Public docs & API reference are MCP-ready",
      status: "pass",
      summary: "Both source kinds have an active snapshot serving the latest stable version.",
      details: ["docs ready_count=2", "apiref ready_count=2"],
    },
    {
      check_id: "snippet-coverage",
      title: "Executable snippets exist for the selected SDK language",
      status: "pass",
      summary: "1 240 executable snippets indexed for net (threshold 500).",
      details: ["language=net", "snippet_count=1240 / threshold=500"],
    },
    {
      check_id: "snapshot-fresh",
      title: "Active snapshot is fresh",
      status: "warn",
      summary: "The newest active snapshot is 25 days old; target freshness is 30 days.",
      details: ["snapshot_age_days=25", "stale_after_days=30"],
    },
  ],
  fix_plan: [
    "Trigger a re-ingestion for aspose.ocr to refresh the aging snapshot.",
    "Re-run this self-test after publish completes to confirm status=ready.",
    "Verify citations on the target client before handing the config to developers.",
  ],
  config_export_url: "/integrations#generate-client-configs",
  status_page_url: "/status?product_id=aspose.ocr",
  mcp_url: "http://localhost:8080/mcp/v1/streamable-http",
  sample_prompt: "Using Aspose.OCR for .NET, recognize text from a PDF and cite the API reference.",
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- status → Mono pill variant -------------------------------*/

function overallVariant(status: string): StatusVariant {
  if (status === "ready") return "ok";
  if (status === "partial") return "warn";
  if (status === "not_ready") return "crit";
  return "neutral";
}

function checkVariant(status: string): StatusVariant {
  if (status === "pass") return "ok";
  if (status === "warn") return "warn";
  if (status === "fail") return "crit";
  return "neutral";
}

function bannerColors(variant: StatusVariant): { bg: string; fg: string } {
  switch (variant) {
    case "ok":
      return { bg: "var(--ok-bg)", fg: "var(--ok)" };
    case "warn":
      return { bg: "var(--warn-bg)", fg: "var(--warn)" };
    case "crit":
      return { bg: "var(--crit-bg)", fg: "var(--crit)" };
    default:
      return { bg: "var(--info-bg)", fg: "var(--info)" };
  }
}

/* -------------------------------------------------------------------------- */

export default function SelfTest() {
  const [productInput, setProductInput] = useState("aspose.ocr");
  const [submittedProduct, setSubmittedProduct] = useState("aspose.ocr");
  const [language, setLanguage] = useState("net");
  const [client, setClient] = useState<ClientId>("cursor");
  const [transport, setTransport] = useState<Transport>("streamable-http");

  const productFieldId = useId();
  const languageFieldId = useId();
  const clientFieldId = useId();
  const transportFieldId = useId();

  const selfTestQuery = useQuery({
    // Public endpoint — always enabled (no auth, no session gate).
    queryKey: ["public-mcp-self-test", submittedProduct, language, client, transport],
    queryFn: () =>
      fetchPublicMCPSelfTest({
        product_id: submittedProduct,
        programming_language: language || undefined,
        client_id: client,
        transport,
      }),
    enabled: submittedProduct.length > 0,
    staleTime: 30_000,
  });

  // Display source with fixture fallback.
  const data: PublicMCPSelfTest = selfTestQuery.data ?? SELF_TEST_FIXTURE;

  // Gate on the display set: with the fixture present, never hide the UI.
  const usingFixture = selfTestQuery.data == null;
  const loading = selfTestQuery.isLoading && !selfTestQuery.data;
  const errored = selfTestQuery.isError && !selfTestQuery.data;

  const errorMessage =
    selfTestQuery.error instanceof AdminApiError
      ? selfTestQuery.error.message
      : "Failed to run the MCP self-test. Confirm the product ID and try again.";

  const variant = overallVariant(data.status);
  const banner = bannerColors(variant);

  const onRun = () => setSubmittedProduct(productInput.trim());

  const metrics: { label: string; value: string; helper: string }[] = [
    {
      label: "Self-test status",
      value: data.status.replaceAll("_", " "),
      helper: data.status_summary,
    },
    {
      label: "Ready services",
      value: `${data.total_ready_services}/${data.total_registered_services}`,
      helper: `docs ${data.docs_ready_count} · apiref ${data.apiref_ready_count}`,
    },
    {
      label: "Snippet coverage",
      value: String(data.snippet_count),
      helper: `language ${data.programming_language ?? "auto"}`,
    },
    {
      label: "Target client",
      value: data.client_id,
      helper: data.transport,
    },
  ];

  return (
    <section className="pub-card" id="self-test" aria-label="MCP connection self-test">
      <div className="pub-card-head">
        <span className="pub-card-title">MCP connection self-test</span>
        <span className="right muted-note">
          {data.product_id} · GA readiness
        </span>
      </div>

      {/* scope form */}
      <form
        style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 12,
          }}
        >
          <span className="field">
            <label className="flabel" htmlFor={productFieldId}>
              Product ID
            </label>
            <input
              id={productFieldId}
              className="inputctl"
              value={productInput}
              onChange={(e) => setProductInput(e.target.value)}
              placeholder="aspose.ocr"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor={languageFieldId}>
              SDK Language
            </label>
            <input
              id={languageFieldId}
              className="inputctl"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder="net"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor={clientFieldId}>
              Client
            </label>
            <select
              id={clientFieldId}
              className="selectctl"
              value={client}
              onChange={(e) => setClient(e.target.value as ClientId)}
            >
              {CLIENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
          <span className="field">
            <label className="flabel" htmlFor={transportFieldId}>
              Transport
            </label>
            <select
              id={transportFieldId}
              className="selectctl"
              value={transport}
              onChange={(e) => setTransport(e.target.value as Transport)}
            >
              {TRANSPORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <button
            type="submit"
            className="pub-cta"
            style={{ height: 34, fontSize: 13 }}
            disabled={loading}
          >
            <Icon name="play" /> Run self-test
          </button>
          {usingFixture && !loading && !errored ? (
            <span className="muted-note" style={{ alignSelf: "center" }}>
              Showing a sample diagnostic — connect a backend for live results.
            </span>
          ) : null}
        </div>
      </form>

      <div style={{ padding: "16px 20px" }} aria-live="polite">
        {loading ? (
          <div className="muted-note">Running self-test…</div>
        ) : errored ? (
          <div
            className="pub-status-led"
            style={{ background: "var(--crit-bg)", color: "var(--crit)", borderColor: "var(--crit)" }}
            role="alert"
          >
            <span className="led" style={{ background: "var(--crit)", animation: "none" }} />
            {errorMessage}
            <button
              type="button"
              className="pub-cta ghost"
              style={{ height: 28, fontSize: 12, marginLeft: 10 }}
              onClick={() => void selfTestQuery.refetch()}
            >
              <Icon name="refresh" /> Retry
            </button>
          </div>
        ) : (
          <>
            {/* 4 metric cards */}
            <div
              className="metric-strip"
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                marginBottom: 14,
              }}
            >
              {metrics.map((m) => (
                <div className="m" key={m.label}>
                  <div className="mv" style={{ fontSize: 19 }}>
                    {m.value}
                  </div>
                  <div className="ml">{m.label}</div>
                  <div className="muted-note" style={{ marginTop: 6 }}>
                    {m.helper}
                  </div>
                </div>
              ))}
            </div>

            {/* colored status banner */}
            <div
              className="pub-status-led"
              style={{
                background: banner.bg,
                color: banner.fg,
                borderColor: banner.fg,
                marginBottom: 14,
              }}
              role="status"
            >
              <span className="led" style={{ background: banner.fg, animation: "none" }} />
              {data.status_summary}
            </div>

            {/* checks list */}
            {data.checks.length === 0 ? (
              <div className="muted-note">No diagnostic checks were returned for this scope.</div>
            ) : (
              data.checks.map((check) => <CheckRow key={check.check_id} check={check} />)
            )}

            {/* recommended next steps */}
            {data.fix_plan.length > 0 ? (
              <div
                style={{
                  marginTop: 14,
                  paddingTop: 14,
                  borderTop: "1px solid var(--border)",
                }}
              >
                <div className="svc-name" style={{ marginBottom: 8 }}>
                  Recommended next steps
                </div>
                <ol className="step-list">
                  {data.fix_plan.map((step) => (
                    <li className="step-card" key={step}>
                      <div className="sn" aria-hidden="true" />
                      <div>
                        <div className="st-body" style={{ marginTop: 4 }}>
                          {step}
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className="muted-note" style={{ marginTop: 12 }}>
                  Available SDK languages: {data.available_programming_languages.join(", ") || "none"}
                  {" · "}
                  Available versions: {data.available_versions.join(", ") || "none"}
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                  <a
                    className="pub-cta ghost"
                    style={{ height: 32, fontSize: 12 }}
                    href={`#client-snippet-${data.client_id}`}
                  >
                    Jump to client snippet
                  </a>
                  <a
                    className="pub-cta ghost"
                    style={{ height: 32, fontSize: 12 }}
                    href={data.status_page_url}
                  >
                    Open filtered status
                  </a>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

/* ---------------- a single check row -------------------------------------- */

function CheckRow({ check }: { check: PublicMCPSelfTestCheck }) {
  const variant = checkVariant(check.status);
  return (
    <div className="svc-row" style={{ alignItems: "flex-start" }}>
      <Pill variant={variant}>{check.status}</Pill>
      <div style={{ flex: 1 }}>
        <div className="svc-name">{check.title}</div>
        <div className="svc-desc">{check.summary}</div>
        {check.details.length > 0 ? (
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {check.details.map((detail) => (
              <li
                key={detail}
                className={cn("mono")}
                style={{ fontSize: 11, color: "var(--fg-subtle)", lineHeight: 1.7 }}
              >
                {detail}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
