"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill } from "../../components/Pill";
import { Tag } from "../../components/Tag";
import { Icon } from "../../lib/icons";
import type { StatusVariant } from "../../lib/types";
import {
  AdminApiError,
  fetchPublicTroubleshooting,
  type PublicTroubleshooting,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * MCP Troubleshooting Desk — section component for /integrations.
 *
 * troubleshootingQuery → /v1/integrations/troubleshooting, optional request_id
 * input, a status banner + summary chips, and a set of symptom→diagnosis
 * recovery-path cards (severity chip · title · summary · match_reason · evidence
 * chips · fix_plan list · Copy fix plan · action links).
 *
 * Live wiring: fetchPublicTroubleshooting({ product_id, programming_language?,
 * client_id?, transport?, request_id? }). Public endpoint — always enabled.
 *
 * Offline fallback:
 *   - live success            -> live PublicTroubleshooting
 *   - live success but EMPTY   -> designed "no recovery paths" empty state
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file TROUBLESHOOTING_FIXTURE (reviewable)
 * -------------------------------------------------------------------------- */

type ClientId = "cursor" | "claude-desktop" | "qwen-code" | "vscode";
type Transport = "streamable-http" | "sse";

const CLIENT_OPTIONS: { value: ClientId; label: string }[] = [
  { value: "cursor", label: "Cursor" },
  { value: "claude-desktop", label: "Claude Desktop" },
  { value: "qwen-code", label: "Qwen Code" },
  { value: "vscode", label: "VS Code" },
];

/* ---------------- offline fixture (verbatim-shaped payload) --------------- */

const TROUBLESHOOTING_FIXTURE: PublicTroubleshooting = {
  filters: {
    product_id: "aspose.ocr",
    programming_language: "net",
    client_id: "cursor",
    transport: "streamable-http",
    request_id: null,
  },
  status_summary:
    "MCP is connected and the self-test is partial. The most likely cause of weak answers is an aging snapshot — refresh content, then re-run the failing query.",
  self_test_status: "partial",
  critical_gap_total: 0,
  warning_gap_total: 1,
  request_diagnostics: {
    request_id: null,
    outcome: null,
    result_count: null,
    confidence: null,
    zero_result_reason: null,
    fallback_reason: null,
    feedback_total: 0,
    issue_total: 0,
  },
  paths: [
    {
      path_id: "connection",
      title: "Connection & handshake",
      severity: "info",
      summary:
        "Verify the client actually reaches the MCP endpoint and negotiates a supported revision.",
      match_reason: "self_test_status=partial — registration succeeded, so the transport is reachable.",
      evidence: ["mcp_url reachable", "revision negotiated", "transport=streamable-http"],
      fix_plan: [
        "Confirm the Authorization header carries a valid product-scoped key.",
        "Restart the client so it re-runs the MCP initialize handshake.",
        "Re-run the public self-test to confirm status flips to ready.",
      ],
      copy_block_label: "Copy connection fix plan",
      copy_block_text:
        "Connection fix plan:\n1. Confirm Authorization header has a valid key.\n2. Restart the client to re-initialize MCP.\n3. Re-run the self-test and confirm status=ready.",
      actions: [
        { label: "Open self-test", href: "#self-test" },
        { label: "Open client config", href: "#generate-client-configs" },
      ],
    },
    {
      path_id: "content-gap",
      title: "Content gap or stale snapshot",
      severity: "warning",
      summary:
        "Answers are weak or empty because the active snapshot is aging or a source kind is missing.",
      match_reason: "warning_gap_total=1 — the active snapshot is older than the freshness target.",
      evidence: ["snapshot_age_days=25", "stale_after_days=30", "apiref ready"],
      fix_plan: [
        "Trigger a re-ingestion for aspose.ocr to refresh the snapshot.",
        "Confirm both docs and apiref show an active snapshot after publish.",
        "Re-run the query that produced weak answers.",
      ],
      copy_block_label: "Copy content-gap fix plan",
      copy_block_text:
        "Content-gap fix plan:\n1. Re-ingest aspose.ocr to refresh the snapshot.\n2. Confirm docs + apiref are MCP-ready.\n3. Re-run the failing query.",
      actions: [{ label: "Open content triage", href: "#triage" }],
    },
    {
      path_id: "request-quality",
      title: "Request quality (zero-result / low confidence)",
      severity: "info",
      summary:
        "Content exists but retrieval returned nothing useful — paste the public request_id to diagnose the exact query.",
      match_reason: "No request_id provided — enter one to load per-request diagnostics.",
      evidence: ["needs request_id"],
      fix_plan: [
        "Copy the request_id from the playground or your query logs.",
        "Paste it above and re-run troubleshooting.",
        "If content is ready but results are empty, escalate to the search relevance team.",
      ],
      copy_block_label: "Copy request-quality fix plan",
      copy_block_text:
        "Request-quality fix plan:\n1. Get the request_id from the playground.\n2. Paste it into the troubleshooting desk.\n3. Escalate to search relevance if content is ready but empty.",
      actions: [{ label: "Open query playground", href: "#query-playground" }],
    },
  ],
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- mappers --------------------------------------------------*/

function selfTestVariant(status: string): StatusVariant {
  if (status === "ready") return "ok";
  if (status === "partial") return "warn";
  if (status === "not_ready") return "crit";
  return "neutral";
}

function severityVariant(severity: string): StatusVariant {
  if (severity === "error") return "crit";
  if (severity === "warning") return "warn";
  return "info";
}

/* -------------------------------------------------------------------------- */

export default function TroubleshootingDesk() {
  const [productInput, setProductInput] = useState("aspose.ocr");
  const [submittedProduct, setSubmittedProduct] = useState("aspose.ocr");
  const [language, setLanguage] = useState("net");
  const [client, setClient] = useState<ClientId>("cursor");
  const [requestInput, setRequestInput] = useState("");
  const [submittedRequest, setSubmittedRequest] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const productFieldId = useId();
  const languageFieldId = useId();
  const clientFieldId = useId();
  const requestFieldId = useId();

  const troubleshootingQuery = useQuery({
    // Public endpoint — always enabled (no auth, no session gate).
    queryKey: [
      "public-troubleshooting",
      submittedProduct,
      language,
      client,
      submittedRequest,
    ],
    queryFn: () =>
      fetchPublicTroubleshooting({
        product_id: submittedProduct,
        programming_language: language || undefined,
        client_id: client,
        request_id: submittedRequest || undefined,
      }),
    enabled: submittedProduct.length > 0,
    staleTime: 30_000,
  });

  // Display source with fixture fallback.
  const data: PublicTroubleshooting = troubleshootingQuery.data ?? TROUBLESHOOTING_FIXTURE;
  const usingFixture = troubleshootingQuery.data == null;

  // Gate on the display set: with the fixture present, never hide the UI.
  const loading = troubleshootingQuery.isLoading && !troubleshootingQuery.data;
  const errored = troubleshootingQuery.isError && !troubleshootingQuery.data;

  const errorMessage =
    troubleshootingQuery.error instanceof AdminApiError
      ? troubleshootingQuery.error.message
      : "Failed to build troubleshooting guidance. Confirm the product ID and try again.";

  const stVariant = selfTestVariant(data.self_test_status);
  const stColor =
    stVariant === "ok"
      ? "var(--ok)"
      : stVariant === "warn"
        ? "var(--warn)"
        : stVariant === "crit"
          ? "var(--crit)"
          : "var(--info)";
  const stBg =
    stVariant === "ok"
      ? "var(--ok-bg)"
      : stVariant === "warn"
        ? "var(--warn-bg)"
        : stVariant === "crit"
          ? "var(--crit-bg)"
          : "var(--info-bg)";

  const activeRequestId = (data.request_diagnostics.request_id ?? submittedRequest) || "none";

  const onRun = () => {
    setSubmittedProduct(productInput.trim());
    setSubmittedRequest(requestInput.trim());
  };

  const copyPlan = async (pathId: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopiedId(pathId);
    window.setTimeout(() => {
      setCopiedId((prev) => (prev === pathId ? null : prev));
    }, 2000);
  };

  return (
    <section className="pub-card" id="troubleshooting" aria-label="MCP troubleshooting desk">
      <div className="pub-card-head">
        <span className="pub-card-title">MCP troubleshooting desk</span>
        <span className="right muted-note">request scope · {activeRequestId}</span>
      </div>

      {/* scope + request form */}
      <form
        style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
      >
        <p className="muted-note" style={{ marginTop: 0, marginBottom: 12 }}>
          Use this desk when MCP is connected but answers are weak, empty, stale, or inconsistent. It
          combines self-test status, content-gap signals, and an optional public{" "}
          <span className="mono">request_id</span> into explainable recovery paths.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
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
            <label className="flabel" htmlFor={requestFieldId}>
              request_id (optional)
            </label>
            <input
              id={requestFieldId}
              className="inputctl"
              value={requestInput}
              onChange={(e) => setRequestInput(e.target.value)}
              placeholder="req-query-1"
              autoComplete="off"
            />
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <button
            type="submit"
            className="pub-cta"
            style={{ height: 34, fontSize: 13 }}
            disabled={loading}
          >
            <Icon name="search" /> Diagnose
          </button>
          {usingFixture && !loading && !errored ? (
            <span className="muted-note" style={{ alignSelf: "center" }}>
              Showing sample recovery paths — connect a backend for live diagnostics.
            </span>
          ) : null}
        </div>
      </form>

      <div style={{ padding: "16px 20px" }} aria-live="polite">
        {loading ? (
          <div className="muted-note">Building troubleshooting paths…</div>
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
              onClick={() => void troubleshootingQuery.refetch()}
            >
              <Icon name="refresh" /> Retry
            </button>
          </div>
        ) : (
          <>
            {/* status banner */}
            <div
              className="pub-status-led"
              style={{ background: stBg, color: stColor, borderColor: stColor, marginBottom: 12 }}
              role="status"
            >
              <span className="led" style={{ background: stColor, animation: "none" }} />
              {data.status_summary}
            </div>

            {/* summary chips */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              <Pill variant={stVariant}>self-test {data.self_test_status}</Pill>
              <Pill variant={data.critical_gap_total > 0 ? "crit" : "neutral"}>
                critical gaps {data.critical_gap_total}
              </Pill>
              <Pill variant={data.warning_gap_total > 0 ? "warn" : "neutral"}>
                warning gaps {data.warning_gap_total}
              </Pill>
              <Tag>request {data.request_diagnostics.request_id ?? "none"}</Tag>
            </div>

            {/* recovery-path cards */}
            {data.paths.length === 0 ? (
              <div className="muted-note">
                No recovery paths matched for{" "}
                <span className="mono">request_id={activeRequestId}</span>. Ensure the request_id is
                from a recent public query, or diagnose by product instead.
              </div>
            ) : (
              data.paths.map((path) => (
                <div
                  key={path.path_id}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 16,
                    marginBottom: 12,
                    background: "var(--surface)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      flexWrap: "wrap",
                      marginBottom: 6,
                    }}
                  >
                    <span className="svc-name">{path.title}</span>
                    <span style={{ marginLeft: "auto" }}>
                      <Pill variant={severityVariant(path.severity)}>{path.severity}</Pill>
                    </span>
                  </div>
                  <div className="svc-desc" style={{ marginBottom: 6 }}>
                    {path.summary}
                  </div>
                  <div className="muted-note" style={{ marginBottom: 8 }}>
                    {path.match_reason}
                  </div>

                  {path.evidence.length > 0 ? (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                      {path.evidence.map((item) => (
                        <Tag key={`${path.path_id}-${item}`}>{item}</Tag>
                      ))}
                    </div>
                  ) : null}

                  {path.fix_plan.length > 0 ? (
                    <ol className="step-list" style={{ marginBottom: 12 }}>
                      {path.fix_plan.map((step) => (
                        <li className="step-card" key={`${path.path_id}-${step}`}>
                          <div className="sn" aria-hidden="true" />
                          <div>
                            <div className="st-body" style={{ marginTop: 4 }}>
                              {step}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : null}

                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    {path.copy_block_text ? (
                      <button
                        type="button"
                        className="pub-cta"
                        style={{ height: 30, fontSize: 12 }}
                        onClick={() => void copyPlan(path.path_id, path.copy_block_text ?? "")}
                      >
                        {copiedId === path.path_id
                          ? "Copied plan"
                          : path.copy_block_label ?? "Copy fix plan"}
                      </button>
                    ) : null}
                    {path.actions.map((action) => (
                      <a
                        key={`${path.path_id}-${action.label}`}
                        className="pub-cta ghost"
                        style={{ height: 30, fontSize: 12 }}
                        href={action.href}
                      >
                        {action.label}
                      </a>
                    ))}
                  </div>
                </div>
              ))
            )}
          </>
        )}
      </div>
    </section>
  );
}
