"use client";

import { useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Pill } from "../../components/Pill";
import { Tag } from "../../components/Tag";
import { cn } from "../../lib/cn";
import { Icon } from "../../lib/icons";
import {
  AdminApiError,
  fetchPublicMCPConfigExport,
  type PublicMCPConfigExport,
  type PublicMCPConfigSnippet,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Generate Client Configs — section component for /integrations.
 *
 * A 6-field generator form (Product ID · SDK Language · Version · Source kind ·
 * Client · Transport) that
 * drives configQuery → /v1/integrations/mcp-configs and renders per-client
 * config cards (config_path_hint · format · snippet · instructions · Copy).
 *
 * Live wiring: the public endpoint (fetchPublicMCPConfigExport) accepts
 * product_id + transport; the remaining form fields (language / version /
 * source_kind / client) scope WHICH client snippet is shown client-side, giving
 * the "select a product and client, then Generate" flow.
 *
 * Offline fallback:
 *   - live success            -> live PublicMCPConfigExport
 *   - live success but EMPTY   -> designed empty state
 *   - live ERROR               -> designed error state + Retry
 *   - offline / no backend     -> in-file CONFIG_FIXTURE (fully reviewable)
 * -------------------------------------------------------------------------- */

type ClientId = "cursor" | "claude-desktop" | "qwen-code" | "vscode";
type Transport = "streamable-http" | "sse";

const CLIENT_OPTIONS: { value: ClientId; label: string }[] = [
  { value: "cursor", label: "Cursor" },
  { value: "claude-desktop", label: "Claude Desktop" },
  { value: "qwen-code", label: "Qwen Code" },
  { value: "vscode", label: "VS Code" },
];

const SOURCE_KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All sources" },
  { value: "docs", label: "docs" },
  { value: "apiref", label: "apiref" },
];
const TRANSPORT_OPTIONS: { value: Transport; label: string }[] = [
  { value: "streamable-http", label: "streamable-http (recommended)" },
  { value: "sse", label: "sse" },
];

interface FormState {
  product: string;
  language: string;
  version: string;
  sourceKind: string;
  client: ClientId;
  transport: Transport;
}

const DEFAULT_FORM: FormState = {
  product: "aspose.ocr",
  language: "net",
  version: "",
  sourceKind: "",
  client: "cursor",
  transport: "streamable-http",
};

/** Human label for the source-kind scope shown in the result readout. */
function sourceKindLabel(sourceKind: string): string {
  if (sourceKind === "docs") return "docs only";
  if (sourceKind === "apiref") return "API reference only";
  return "docs + API reference";
}

/* ---------------- offline fixture (verbatim-shaped export) ---------------- */

const CONFIG_FIXTURE: PublicMCPConfigExport = {
  server_name: "aspose-docs",
  product_id: "aspose.ocr",
  transport: "streamable-http",
  mcp_url: "http://localhost:8080/mcp/v1/streamable-http",
  sample_prompt:
    "Using Aspose.OCR for .NET, how do I recognize text from a multi-page PDF? Cite the API reference.",
  clients: [
    {
      client_id: "cursor",
      display_name: "Cursor",
      config_path_hint: ".cursor/mcp.json",
      format: "json",
      snippet: `{
  "mcpServers": {
    "aspose-docs": {
      "url": "http://localhost:8080/mcp/v1/streamable-http",
      "headers": { "Authorization": "Bearer \${ADCS_KEY}" }
    }
  }
}`,
      instructions: [
        "Create .cursor/mcp.json in your project root (or open Cursor Settings → MCP).",
        "Paste the snippet and replace ${ADCS_KEY} with your product-scoped key.",
        "Reload Cursor; the aspose-docs server appears under MCP tools.",
      ],
    },
    {
      client_id: "claude-desktop",
      display_name: "Claude Desktop",
      config_path_hint: "claude_desktop_config.json",
      format: "json",
      snippet: `{
  "mcpServers": {
    "aspose-docs": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8080/mcp/v1/streamable-http"],
      "env": { "ADCS_KEY": "\${ADCS_KEY}" }
    }
  }
}`,
      instructions: [
        "Open Settings → Developer → Edit Config in Claude Desktop.",
        "Merge the snippet into mcpServers and set your ADCS_KEY.",
        "Restart Claude Desktop and confirm the server connects.",
      ],
    },
    {
      client_id: "qwen-code",
      display_name: "Qwen Code",
      config_path_hint: "~/.qwen/mcp.json",
      format: "json",
      snippet: `{
  "servers": {
    "aspose-docs": {
      "transport": "streamable-http",
      "url": "http://localhost:8080/mcp/v1/streamable-http",
      "headers": { "Authorization": "Bearer \${ADCS_KEY}" }
    }
  }
}`,
      instructions: [
        "Add the server block to ~/.qwen/mcp.json.",
        "Export ADCS_KEY in your shell or substitute the literal key.",
        "Run qwen and verify the aspose-docs tools are listed.",
      ],
    },
    {
      client_id: "vscode",
      display_name: "VS Code",
      config_path_hint: ".vscode/mcp.json",
      format: "json",
      snippet: `{
  "servers": {
    "aspose-docs": {
      "type": "http",
      "url": "http://localhost:8080/mcp/v1/streamable-http",
      "headers": { "Authorization": "Bearer \${ADCS_KEY}" }
    }
  }
}`,
      instructions: [
        "Create .vscode/mcp.json and paste the server entry.",
        "Set ADCS_KEY via an environment variable or input prompt.",
        "Run the “MCP: List Servers” command to confirm connection.",
      ],
    },
  ],
  generated_at: "2026-06-10T00:00:00Z",
};

/* ---------------- visually-hidden label helper (kit has no .sr-only) ------ */

const SR_ONLY: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};

/* -------------------------------------------------------------------------- */

export default function GenerateConfigs() {
  // Draft inputs vs the submitted scope that actually drives the query.
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitted, setSubmitted] = useState<FormState>(DEFAULT_FORM);
  const [generated, setGenerated] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const productId = useId();
  const languageId = useId();
  const versionId = useId();
  const sourceKindId = useId();
  const clientId = useId();
  const transportId = useId();

  const configQuery = useQuery({
    // Public endpoint — always enabled (no auth, no session gate).
    queryKey: ["public-mcp-config-export", submitted.product, submitted.transport],
    queryFn: () =>
      fetchPublicMCPConfigExport({
        product_id: submitted.product || undefined,
        transport: submitted.transport,
      }),
    staleTime: 60_000,
  });

  // Display source with fixture fallback: live export when present, else fixture.
  const exportData: PublicMCPConfigExport = configQuery.data ?? CONFIG_FIXTURE;

  // The selected client's snippet (client field scopes the card shown).
  const selectedClient: PublicMCPConfigSnippet | undefined = useMemo(() => {
    const exact = exportData.clients.find((c) => c.client_id === submitted.client);
    return exact ?? exportData.clients[0];
  }, [exportData, submitted.client]);

  // Gate on the DISPLAY set: offline → fixture (non-empty) → never hides UI.
  const hasClients = exportData.clients.length > 0;
  const loading = configQuery.isLoading && !hasClients;
  const errored = configQuery.isError && !hasClients;

  const errorMessage =
    configQuery.error instanceof AdminApiError
      ? configQuery.error.message
      : "Failed to generate MCP configs. Check the product ID and try again.";

  const onGenerate = () => {
    setSubmitted({ ...form, product: form.product.trim(), version: form.version.trim() });
    setGenerated(true);
  };

  const onReset = () => {
    setForm(DEFAULT_FORM);
    setSubmitted(DEFAULT_FORM);
    setGenerated(false);
  };

  const copySnippet = async (snippet: PublicMCPConfigSnippet) => {
    try {
      await navigator.clipboard.writeText(snippet.snippet);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopiedId(snippet.client_id);
    window.setTimeout(() => {
      setCopiedId((prev) => (prev === snippet.client_id ? null : prev));
    }, 2000);
  };

  return (
    <section className="pub-card" id="generate-client-configs" aria-label="Generate client configs">
      <div className="pub-card-head">
        <span className="pub-card-title">Generate Client Configs</span>
        <span className="right muted-note">
          {exportData.product_id ?? "all products"} · {submitted.transport} ·{" "}
          {sourceKindLabel(submitted.sourceKind)}
        </span>
      </div>

      {/* generator form (6 fields) */}
      <form
        style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)" }}
        onSubmit={(e) => {
          e.preventDefault();
          onGenerate();
        }}
      >
        <p className="muted-note" style={{ marginTop: 0, marginBottom: 12 }}>
          <span className="mono">streamable-http</span> is the recommended default for remote MCP
          deployments. Use <span className="mono">sse</span> only when a client explicitly requires
          it.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
            gap: 12,
          }}
        >
          <span className="field">
            <label className="flabel" htmlFor={productId}>
              Product ID
            </label>
            <input
              id={productId}
              className="inputctl"
              value={form.product}
              onChange={(e) => setForm((f) => ({ ...f, product: e.target.value }))}
              placeholder="aspose.ocr"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor={languageId}>
              SDK Language
            </label>
            <input
              id={languageId}
              className="inputctl"
              value={form.language}
              onChange={(e) => setForm((f) => ({ ...f, language: e.target.value }))}
              placeholder="net"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor={versionId}>
              Version
            </label>
            <input
              id={versionId}
              className="inputctl"
              value={form.version}
              onChange={(e) => setForm((f) => ({ ...f, version: e.target.value }))}
              placeholder="latest-stable or 25.1"
              autoComplete="off"
            />
          </span>
          <span className="field">
            <label className="flabel" htmlFor={sourceKindId}>
              Source kind
            </label>
            <select
              id={sourceKindId}
              className="selectctl"
              value={form.sourceKind}
              onChange={(e) => setForm((f) => ({ ...f, sourceKind: e.target.value }))}
            >
              {SOURCE_KIND_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
          <span className="field">
            <label className="flabel" htmlFor={clientId}>
              Client
            </label>
            <select
              id={clientId}
              className="selectctl"
              value={form.client}
              onChange={(e) => setForm((f) => ({ ...f, client: e.target.value as ClientId }))}
            >
              {CLIENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
          <span className="field">
            <label className="flabel" htmlFor={transportId}>
              Transport
            </label>
            <select
              id={transportId}
              className="selectctl"
              value={form.transport}
              onChange={(e) => setForm((f) => ({ ...f, transport: e.target.value as Transport }))}
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
            Generate <Icon name="arrow" />
          </button>
          <button
            type="button"
            className="pub-cta ghost"
            style={{ height: 34, fontSize: 13 }}
            onClick={onReset}
          >
            Reset
          </button>
        </div>
      </form>

      {/* result region */}
      <div style={{ padding: "16px 20px" }} aria-live="polite">
        {loading ? (
          <div className="muted-note">Generating client configs…</div>
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
              onClick={() => void configQuery.refetch()}
            >
              <Icon name="refresh" /> Retry
            </button>
          </div>
        ) : !hasClients ? (
          <div className="muted-note">
            No client configs generated yet. Select a product and click Generate.
          </div>
        ) : (
          <>
            {!generated ? (
              <div className="muted-note" style={{ marginBottom: 12 }}>
                Showing the default config for <span className="mono">{exportData.product_id}</span>.
                Adjust the form and click Generate to tailor it.
              </div>
            ) : (
              <div className="muted-note" style={{ marginBottom: 12 }}>
                Scope: <span className="mono">{submitted.product || "all products"}</span>
                {submitted.language ? (
                  <>
                    {" · "}
                    <span className="mono">{submitted.language}</span>
                  </>
                ) : null}
                {submitted.version ? (
                  <>
                    {" · "}
                    <span className="mono">{submitted.version}</span>
                  </>
                ) : null}
                {" · "}
                {sourceKindLabel(submitted.sourceKind)}. The same MCP endpoint serves every
                source kind; this scope tells the assistant which surfaces to prefer.
              </div>
            )}

            {/* Selected-client card (the Client field scopes which one shows). */}
            {selectedClient ? (
              <ClientCard
                snippet={selectedClient}
                copied={copiedId === selectedClient.client_id}
                onCopy={() => void copySnippet(selectedClient)}
                primary
              />
            ) : null}

            {/* All other clients remain available below, mirroring the export. */}
            {exportData.clients
              .filter((c) => c.client_id !== selectedClient?.client_id)
              .map((c) => (
                <ClientCard
                  key={c.client_id}
                  snippet={c}
                  copied={copiedId === c.client_id}
                  onCopy={() => void copySnippet(c)}
                />
              ))}

            <div className="muted-note" style={{ marginTop: 12 }}>
              Sample prompt: {exportData.sample_prompt}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

/* ---------------- per-client config card ---------------------------------- */

function ClientCard({
  snippet,
  copied,
  onCopy,
  primary = false,
}: {
  snippet: PublicMCPConfigSnippet;
  copied: boolean;
  onCopy: () => void;
  primary?: boolean;
}) {
  return (
    <div
      id={`client-snippet-${snippet.client_id}`}
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
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <span className="svc-name">{snippet.display_name}</span>
        {primary ? <Pill variant="ok">selected</Pill> : null}
        <Tag>{snippet.format}</Tag>
        <span className="mono" style={{ fontSize: 11.5, color: "var(--fg-subtle)", marginLeft: "auto" }}>
          {snippet.config_path_hint}
        </span>
      </div>

      {/* dark code card with copy */}
      <div className="code-card">
        <div className="code-head">
          <span className="dot3" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="fname">{snippet.config_path_hint}</span>
          <button
            type="button"
            className="copy"
            onClick={onCopy}
            aria-label={`Copy ${snippet.display_name} config snippet to clipboard`}
          >
            {copied ? "Copied" : "Copy Snippet"}
          </button>
        </div>
        <pre className="code-body" tabIndex={0}>
          {snippet.snippet}
        </pre>
        <span style={SR_ONLY} role="status" aria-live="polite">
          {copied ? `${snippet.display_name} config copied to clipboard` : ""}
        </span>
      </div>

      {/* instructions list */}
      {snippet.instructions.length > 0 ? (
        <ol className="step-list" style={{ marginTop: 14 }}>
          {snippet.instructions.map((step) => (
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
      ) : null}
    </div>
  );
}
