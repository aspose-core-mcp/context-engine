"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Pill } from "@/mono/components/Pill";
import { Segmented } from "@/mono/components/Field";
import { Tag } from "@/mono/components/Tag";
import { ErrorState, Skeleton } from "@/mono/components/states";
import { cn } from "@/mono/lib/cn";
import { Icon } from "@/mono/lib/icons";
import { fetchPublicStarterPacks, type PublicStarterPacks } from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Multi-Client Onboarding Bundle Builder
 *
 * Assemble a single onboarding bundle (markdown or JSON) from selected client
 * starter packs. Reads the same source as the Starter Packs section
 * (fetchPublicStarterPacks → /v1/integrations/starter-packs) and composes the
 * chosen packs client-side; selection + format are local UI state.
 *
 * Live success       -> compose from live packs.
 * Live success EMPTY -> fall back to fixtures so the builder stays operable.
 * Live ERROR         -> fixtures + non-blocking banner with retry.
 * Offline/disabled   -> in-file BUNDLE_PACKS_FIXTURE so the section is reviewable.
 * -------------------------------------------------------------------------- */

const BUNDLE_PRODUCT = "aspose.ocr";
const BUNDLE_LANGUAGE = "net";
const BUNDLE_VERSION = "adcs.public-onboarding-bundle.v1";

type StarterPack = PublicStarterPacks["packs"][number];

const BUNDLE_PACKS_FIXTURE: StarterPack[] = [
  {
    pack_id: "aspose.ocr-cursor",
    client_id: "cursor",
    display_name: "Cursor",
    title: "Aspose.OCR · Cursor starter pack",
    description: "Drop-in Cursor MCP config plus the first grounded recognition queries in C#.",
    config_path_hint: ".cursor/mcp.json",
    config_format: "json",
    config_snippet: `{
  "mcpServers": {
    "aspose-docs": { "url": "http://localhost:8080/mcp/v1/streamable-http" }
  }
}`,
    starter_prompt:
      "Using the Aspose.OCR MCP server, recognize text from an image in C# and cite the signature.",
    first_queries: ["how to recognize text from an image in C#", "set recognition language"],
    starter_checklist: ["Add to .cursor/mcp.json and restart", "Run the first query, check citation"],
    bundle_markdown: "## Cursor\nConfig: .cursor/mcp.json\n",
    download_filename: "aspose-ocr-cursor-starter.md",
  },
  {
    pack_id: "aspose.ocr-claude-desktop",
    client_id: "claude-desktop",
    display_name: "Claude Desktop",
    title: "Aspose.OCR · Claude Desktop starter pack",
    description: "Claude Desktop config and a quickstart prompt grounded in versioned docs.",
    config_path_hint: "claude_desktop_config.json",
    config_format: "json",
    config_snippet: `{
  "mcpServers": {
    "aspose-docs": { "url": "http://localhost:8080/mcp/v1/streamable-http" }
  }
}`,
    starter_prompt: "Show the recommended Aspose.OCR recognition settings for scanned invoices.",
    first_queries: ["recommended recognition settings for scanned documents"],
    starter_checklist: ["Paste into claude_desktop_config.json", "Restart and approve the server"],
    bundle_markdown: "## Claude Desktop\nConfig: claude_desktop_config.json\n",
    download_filename: "aspose-ocr-claude-desktop-starter.md",
  },
  {
    pack_id: "aspose.ocr-vscode",
    client_id: "vscode",
    display_name: "VS Code",
    title: "Aspose.OCR · VS Code starter pack",
    description: "VS Code / Continue MCP config with a grounded first query for table layouts.",
    config_path_hint: ".vscode/mcp.json",
    config_format: "json",
    config_snippet: `{
  "servers": {
    "aspose-docs": { "url": "http://localhost:8080/mcp/v1/streamable-http" }
  }
}`,
    starter_prompt: "Recognize a table layout from a scanned PDF using Aspose.OCR and cite the docs.",
    first_queries: ["recognize a table layout from a scanned PDF"],
    starter_checklist: ["Add to .vscode/mcp.json", "Reload the window"],
    bundle_markdown: "## VS Code\nConfig: .vscode/mcp.json\n",
    download_filename: "aspose-ocr-vscode-starter.md",
  },
];

const FORMATS = ["markdown", "json"] as const;
type BundleFormat = (typeof FORMATS)[number];

/** Compose a markdown bundle from the selected packs. */
function composeMarkdown(packs: StarterPack[]): string {
  const head = `# ADCS multi-client onboarding bundle\n\n- product: ${BUNDLE_PRODUCT}\n- language: ${BUNDLE_LANGUAGE}\n- clients: ${packs.map((p) => p.client_id).join(", ")}\n`;
  const body = packs
    .map((p) => {
      const queries = p.first_queries.map((q) => `- ${q}`).join("\n");
      const checklist = p.starter_checklist.map((c) => `- [ ] ${c}`).join("\n");
      return [
        `## ${p.display_name} (${p.client_id})`,
        "",
        p.description,
        "",
        `Config — \`${p.config_path_hint}\` (${p.config_format})`,
        "",
        "```" + p.config_format,
        p.config_snippet,
        "```",
        "",
        `Starter prompt: ${p.starter_prompt}`,
        "",
        "First queries:",
        queries || "- (none)",
        "",
        "Checklist:",
        checklist || "- (none)",
      ].join("\n");
    })
    .join("\n\n---\n\n");
  return `${head}\n${body}\n`;
}

/** Compose a JSON bundle from the selected packs. */
function composeJson(packs: StarterPack[]): string {
  const bundle = {
    bundle_version: BUNDLE_VERSION,
    product_id: BUNDLE_PRODUCT,
    programming_language: BUNDLE_LANGUAGE,
    exported_at: new Date().toISOString(),
    client_count: packs.length,
    clients: packs.map((p) => ({
      pack_id: p.pack_id,
      client_id: p.client_id,
      display_name: p.display_name,
      config_path_hint: p.config_path_hint,
      config_format: p.config_format,
      config_snippet: p.config_snippet,
      starter_prompt: p.starter_prompt,
      first_queries: p.first_queries,
      starter_checklist: p.starter_checklist,
    })),
  };
  return JSON.stringify(bundle, null, 2);
}

function downloadText(filename: string, contents: string, mime: string) {
  try {
    const blob = new Blob([contents], { type: mime });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  } catch {
    /* download may be blocked — no-op */
  }
}

export default function BundleBuilder() {
  const packsQuery = useQuery({
    queryKey: ["public-starter-packs-bundle", BUNDLE_PRODUCT, BUNDLE_LANGUAGE],
    queryFn: () =>
      fetchPublicStarterPacks({
        product_id: BUNDLE_PRODUCT,
        programming_language: BUNDLE_LANGUAGE,
        transport: "streamable-http",
      }),
  });

  const livePacks = packsQuery.data?.packs ?? [];
  const packs = livePacks.length ? livePacks : BUNDLE_PACKS_FIXTURE;

  // Selection — default to all clients selected; reconcile when source changes.
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(packs.map((p) => p.client_id)),
  );
  const allClientIds = useMemo(() => packs.map((p) => p.client_id), [packs]);
  useEffect(() => {
    // Drop any selections that no longer exist in the current source.
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => allClientIds.includes(id)));
      return next.size ? next : new Set(allClientIds);
    });
  }, [allClientIds]);

  const toggle = useCallback((clientId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(clientId)) next.delete(clientId);
      else next.add(clientId);
      return next;
    });
  }, []);

  const [formatIdx, setFormatIdx] = useState(0);
  const format: BundleFormat = FORMATS[formatIdx];

  const selectedPacks = useMemo(
    () => packs.filter((p) => selected.has(p.client_id)),
    [packs, selected],
  );

  const bundleText = useMemo(() => {
    if (!selectedPacks.length) return "";
    return format === "markdown" ? composeMarkdown(selectedPacks) : composeJson(selectedPacks);
  }, [selectedPacks, format]);

  const downloadName = `adcs-onboarding-bundle.${format === "markdown" ? "md" : "json"}`;

  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked */
    }
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  }, []);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const loading = packsQuery.isLoading && !packs.length;
  const errored = packsQuery.isError && !packs.length;
  const liveError = packsQuery.isError && livePacks.length === 0;
  const noneSelected = selectedPacks.length === 0;

  return (
    <div className="pub t-mono">
      <section className="pub-card" aria-label="Multi-client onboarding bundle builder">
        <div className="pub-card-head">
          <span className="pub-card-title">Multi-client onboarding bundle builder</span>
          <span className="right muted-note">compose selected packs</span>
        </div>

        <div style={{ padding: "16px 20px" }}>
          {liveError && (
            <Banner
              variant="warn"
              icon="alert"
              title="Building from reference packs"
              text="Live starter-pack data is unavailable, so the builder uses the canonical packs."
              actions={
                <Button size="sm" icon="refresh" onClick={() => packsQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          )}

          {loading ? (
            <Skeleton rows={4} />
          ) : errored ? (
            <ErrorState
              title="Could not load packs for the bundle"
              text="The public starter-pack service did not respond."
              cause="starter-packs endpoint unreachable"
              actions={
                <Button icon="refresh" onClick={() => packsQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          ) : (
            <>
              {/* Client selector — multi-select toggle grid */}
              <div className="muted-note" style={{ marginBottom: 8 }}>
                Select clients to include
              </div>
              <div className="client-grid">
                {packs.map((pack) => {
                  const on = selected.has(pack.client_id);
                  return (
                    <button
                      key={pack.pack_id}
                      type="button"
                      className={cn("client-card", on && "on")}
                      aria-pressed={on}
                      onClick={() => toggle(pack.client_id)}
                      style={{
                        textAlign: "left",
                        cursor: "pointer",
                        outline: on ? "2px solid var(--fg)" : undefined,
                        outlineOffset: -1,
                      }}
                    >
                      <div className="cc-ico" aria-hidden="true">
                        <Icon name={on ? "check" : "plus"} />
                      </div>
                      <div className="cc-name">{pack.display_name}</div>
                      <div className="cc-status">
                        <Pill variant={on ? "ok" : "neutral"}>{on ? "included" : "excluded"}</Pill>{" "}
                        {pack.client_id}
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Format selector */}
              <div
                className="toolbar"
                style={{ margin: "16px 0 0", display: "flex", alignItems: "center", gap: 12 }}
              >
                <span className="muted-note">Bundle format</span>
                <Segmented
                  options={["markdown", "json"]}
                  active={formatIdx}
                  onChange={setFormatIdx}
                  ariaLabel="Bundle format"
                />
                <span className="right muted-note" style={{ marginLeft: "auto" }}>
                  {selectedPacks.length} of {packs.length} clients
                </span>
              </div>

              {/* Bundle preview */}
              {noneSelected ? (
                <Banner
                  variant="info"
                  icon="info"
                  title="No clients selected"
                  text="Select at least one client above to compose a bundle."
                />
              ) : (
                <div className="code-card" style={{ marginTop: 14 }}>
                  <div className="code-head">
                    <span className="dot3" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                    <span className="fname">{downloadName}</span>
                    <button
                      type="button"
                      className="copy"
                      onClick={() => copy(bundleText)}
                      aria-label={`Copy ${downloadName} to clipboard`}
                    >
                      {copied ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <pre
                    className="code-body"
                    tabIndex={0}
                    style={{ maxHeight: 340, overflow: "auto", whiteSpace: "pre-wrap" }}
                  >
                    {bundleText}
                  </pre>
                </div>
              )}

              {/* Selected client tags + actions */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14 }}>
                {selectedPacks.map((p) => (
                  <Tag key={p.pack_id}>{p.client_id}</Tag>
                ))}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
                <Button icon="download" disabled={noneSelected} onClick={() => copy(bundleText)}>
                  {copied ? "Bundle copied" : "Copy bundle"}
                </Button>
                <Button
                  variant="btn-primary"
                  icon="download"
                  disabled={noneSelected}
                  onClick={() =>
                    downloadText(
                      downloadName,
                      bundleText,
                      format === "markdown"
                        ? "text/markdown;charset=utf-8"
                        : "application/json;charset=utf-8",
                    )
                  }
                >
                  Download bundle
                </Button>
              </div>
              <span style={SR_ONLY} role="status" aria-live="polite">
                {copied ? "Onboarding bundle copied to clipboard" : ""}
              </span>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/** Visually-hidden style for screen-reader-only live regions. */
const SR_ONLY = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
} as const;
