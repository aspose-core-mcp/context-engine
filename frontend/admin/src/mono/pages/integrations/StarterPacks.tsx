"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { EmptyState, ErrorState, Skeleton } from "@/mono/components/states";
import { Icon } from "@/mono/lib/icons";
import { fetchPublicStarterPacks, type PublicStarterPacks } from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Client Onboarding Starter Packs
 *
 * Copy-ready onboarding bundles (config + starter prompt + first queries +
 * checklist) per MCP client. Driven by fetchPublicStarterPacks
 * (→ /v1/integrations/starter-packs).
 *
 * Live success       -> live packs.
 * Live success EMPTY -> designed empty state.
 * Live ERROR         -> designed error state with retry.
 * Offline/disabled   -> in-file STARTER_PACKS_FIXTURE so the section is reviewable.
 * -------------------------------------------------------------------------- */

const STARTER_PRODUCT = "aspose.ocr";
const STARTER_LANGUAGE = "net";

type StarterPack = PublicStarterPacks["packs"][number];

const STARTER_PACKS_FIXTURE: StarterPack[] = [
  {
    pack_id: "aspose.ocr-cursor",
    client_id: "cursor",
    display_name: "Cursor",
    title: "Aspose.OCR · Cursor starter pack",
    description:
      "Drop-in Cursor MCP config plus the first grounded queries to validate recognition workflows in C#.",
    config_path_hint: ".cursor/mcp.json",
    config_format: "json",
    config_snippet: `{
  "mcpServers": {
    "aspose-docs": {
      "url": "http://localhost:8080/mcp/v1/streamable-http",
      "headers": { "Authorization": "Bearer \${ADCS_KEY}" }
    }
  }
}`,
    starter_prompt:
      "Using the Aspose.OCR MCP server, recognize text from an image in C# and cite the exact API signature.",
    first_queries: [
      "how to recognize text from an image in C#",
      "set recognition language for Aspose.OCR",
      "extract text from a multi-page PDF",
    ],
    starter_checklist: [
      "Add the config to .cursor/mcp.json and restart Cursor",
      "Confirm the aspose-docs server shows as connected",
      "Run the first query and check the cited canonical_url",
    ],
    bundle_markdown:
      "# Aspose.OCR · Cursor starter pack\n\nConfig path: .cursor/mcp.json\n\nFirst query: how to recognize text from an image in C#\n",
    download_filename: "aspose-ocr-cursor-starter.md",
  },
  {
    pack_id: "aspose.ocr-claude-desktop",
    client_id: "claude-desktop",
    display_name: "Claude Desktop",
    title: "Aspose.OCR · Claude Desktop starter pack",
    description:
      "Claude Desktop config and a quickstart prompt so the assistant grounds every answer in versioned docs.",
    config_path_hint: "claude_desktop_config.json",
    config_format: "json",
    config_snippet: `{
  "mcpServers": {
    "aspose-docs": {
      "url": "http://localhost:8080/mcp/v1/streamable-http",
      "headers": { "Authorization": "Bearer \${ADCS_KEY}" }
    }
  }
}`,
    starter_prompt:
      "Connect to the Aspose.OCR docs and show me the recommended recognition settings for scanned invoices.",
    first_queries: [
      "recommended recognition settings for scanned documents",
      "how to detect text regions before recognition",
    ],
    starter_checklist: [
      "Paste the config into claude_desktop_config.json",
      "Restart Claude Desktop and approve the MCP server",
      "Ask the starter prompt and verify the citations",
    ],
    bundle_markdown:
      "# Aspose.OCR · Claude Desktop starter pack\n\nConfig path: claude_desktop_config.json\n",
    download_filename: "aspose-ocr-claude-desktop-starter.md",
  },
];

/** Trigger a browser download of a text artifact (markdown bundle). */
function downloadText(filename: string, contents: string) {
  try {
    const blob = new Blob([contents], { type: "text/markdown;charset=utf-8" });
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

export default function StarterPacks() {
  const packsQuery = useQuery({
    queryKey: ["public-starter-packs", STARTER_PRODUCT, STARTER_LANGUAGE],
    queryFn: () =>
      fetchPublicStarterPacks({
        product_id: STARTER_PRODUCT,
        programming_language: STARTER_LANGUAGE,
        transport: "streamable-http",
      }),
  });

  // Display source: live packs (if any) else fixtures.
  const livePacks = packsQuery.data?.packs ?? [];
  const packs = livePacks.length ? livePacks : STARTER_PACKS_FIXTURE;

  // Per-pack copy confirmation, keyed by `${pack_id}:${intent}`.
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copy = useCallback(async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked — still surface confirmation */
    }
    setCopiedKey(key);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopiedKey(null), 2000);
  }, []);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  // Live-present-but-empty -> designed empty state (distinct from offline fixtures).
  const liveEmpty = packsQuery.isSuccess && livePacks.length === 0;
  const loading = packsQuery.isLoading && !packs.length;
  const errored = packsQuery.isError && !livePacks.length && !STARTER_PACKS_FIXTURE.length;
  const liveError = packsQuery.isError && livePacks.length === 0;

  return (
    <div className="pub t-mono">
      <section className="pub-card" aria-label="Client onboarding starter packs">
        <div className="pub-card-head">
          <span className="pub-card-title">Client onboarding starter packs</span>
          <span className="right muted-note">config · prompt · first queries · checklist</span>
        </div>

        <div style={{ padding: "16px 20px" }}>
          {liveError && (
            <Banner
              variant="warn"
              icon="alert"
              title="Showing reference starter packs"
              text="Live starter-pack data is unavailable, so the canonical Cursor and Claude Desktop packs are shown instead."
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
              title="Could not load starter packs"
              text="The public starter-pack service did not respond."
              cause="starter-packs endpoint unreachable"
              actions={
                <Button icon="refresh" onClick={() => packsQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          ) : liveEmpty ? (
            <EmptyState
              title="No starter packs yet"
              text="No client onboarding packs are published for this product and language. Try a different scope or check coverage."
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {packs.map((pack) => {
                const cfgKey = `${pack.pack_id}:config`;
                const promptKey = `${pack.pack_id}:prompt`;
                return (
                  <div className="pub-card" style={{ margin: 0 }} key={pack.pack_id}>
                    <div className="pub-card-head">
                      <span className="pub-card-title" style={{ fontSize: 14 }}>
                        {pack.title}
                      </span>
                      <span className="right" style={{ display: "inline-flex", gap: 8 }}>
                        <Pill variant="ok">{pack.display_name}</Pill>
                        <Tag>{pack.client_id}</Tag>
                      </span>
                    </div>
                    <div style={{ padding: "14px 18px" }}>
                      <div className="st-body" style={{ marginBottom: 12 }}>
                        {pack.description}
                      </div>

                      {/* Dark config snippet card */}
                      <div className="code-card">
                        <div className="code-head">
                          <span className="dot3" aria-hidden="true">
                            <i />
                            <i />
                            <i />
                          </span>
                          <span className="fname">{pack.config_path_hint}</span>
                          <button
                            type="button"
                            className="copy"
                            onClick={() => copy(pack.config_snippet, cfgKey)}
                            aria-label={`Copy ${pack.config_path_hint} to clipboard`}
                          >
                            {copiedKey === cfgKey ? "Copied" : "Copy"}
                          </button>
                        </div>
                        <pre className="code-body" tabIndex={0}>
                          {pack.config_snippet}
                        </pre>
                      </div>

                      {/* Starter prompt */}
                      <div className="muted-note" style={{ marginTop: 14, marginBottom: 4 }}>
                        Starter prompt
                      </div>
                      <div
                        className="mono"
                        style={{
                          fontSize: 12.5,
                          color: "var(--fg-muted)",
                          lineHeight: 1.55,
                        }}
                      >
                        {pack.starter_prompt}
                      </div>

                      {/* First queries */}
                      {pack.first_queries.length > 0 && (
                        <>
                          <div className="muted-note" style={{ marginTop: 14, marginBottom: 6 }}>
                            First queries
                          </div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            {pack.first_queries.map((q) => (
                              <Tag key={q}>{q}</Tag>
                            ))}
                          </div>
                        </>
                      )}

                      {/* Checklist */}
                      {pack.starter_checklist.length > 0 && (
                        <>
                          <div className="muted-note" style={{ marginTop: 14, marginBottom: 6 }}>
                            Setup checklist
                          </div>
                          <ul style={{ margin: 0, paddingLeft: 18 }} className="st-body">
                            {pack.starter_checklist.map((step) => (
                              <li key={step} style={{ marginBottom: 4 }}>
                                {step}
                              </li>
                            ))}
                          </ul>
                        </>
                      )}

                      {/* Actions */}
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 16 }}>
                        <Button icon="download" onClick={() => copy(pack.config_snippet, cfgKey)}>
                          {copiedKey === cfgKey ? "Config copied" : "Copy config"}
                        </Button>
                        <Button icon="play" onClick={() => copy(pack.starter_prompt, promptKey)}>
                          {copiedKey === promptKey ? "Prompt copied" : "Copy prompt"}
                        </Button>
                        <Button
                          variant="btn-primary"
                          icon="download"
                          onClick={() => downloadText(pack.download_filename, pack.bundle_markdown)}
                        >
                          Download starter pack
                        </Button>
                      </div>
                      <span style={SR_ONLY} role="status" aria-live="polite">
                        {copiedKey === cfgKey
                          ? "Config copied to clipboard"
                          : copiedKey === promptKey
                            ? "Starter prompt copied to clipboard"
                            : ""}
                      </span>
                    </div>
                  </div>
                );
              })}
              <div className="muted-note" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name="info" />
                Packs are scoped to {STARTER_PRODUCT} · {STARTER_LANGUAGE} over streamable-http.
              </div>
            </div>
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
