"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { EmptyState } from "@/mono/components/states";
import { Icon } from "@/mono/lib/icons";

/* ----------------------------------------------------------------------------
 * Workspace Presets and Deck Management
 *
 * Save / load / delete reusable public-playground scopes (product, language,
 * version, source kind, client, transport, query or symbol). Persistence is the
 * browser only — there is NO server API for presets — keyed to
 *   adcs.publicWorkspacePresets.v1   (max 12 presets, oldest dropped).
 *
 * Because the data source is localStorage (not a fetchPublic* endpoint), the
 * "offline fallback" here is the SEED below: on first visit, or when storage is
 * empty/unavailable (private mode, quota), the section hydrates from PRESET_SEED
 * so it is fully reviewable and every control (save / load / delete / export /
 * import) visibly responds. Once the user saves, their own presets persist and
 * win on the next visit.
 *
 * Export/Import move a portable JSON pack so a session can be reproduced on
 * another machine. Import validates the pack shape and reports honestly.
 * -------------------------------------------------------------------------- */

const WORKSPACE_PRESETS_STORAGE_KEY = "adcs.publicWorkspacePresets.v1";
const SESSION_DECK_STORAGE_KEY = "adcs.publicSessionDeck.v1";
const MAX_WORKSPACE_PRESETS = 12;
const MAX_SESSION_DECK = 12;
const WORKSPACE_PACK_VERSION = "adcs.public-workspace-pack.v1";

type WorkspaceMode = "search" | "symbol";
type WorkspaceClientId = "cursor" | "claude-desktop" | "qwen-code" | "vscode";
type WorkspaceTransport = "streamable-http" | "sse";

interface WorkspacePreset {
  preset_id: string;
  name: string;
  product_id: string;
  programming_language: string;
  version: string;
  source_kind: string;
  client_id: WorkspaceClientId;
  transport: WorkspaceTransport;
  mode: WorkspaceMode;
  query: string;
  symbol_fqn: string;
  created_at: string;
  last_used_at: string;
}

interface WorkspacePresetPack {
  pack_version: typeof WORKSPACE_PACK_VERSION;
  exported_at: string;
  exported_from: "adcs-public-integrations";
  preset_count: number;
  presets: WorkspacePreset[];
}

const CLIENT_OPTIONS: { value: WorkspaceClientId; label: string }[] = [
  { value: "cursor", label: "Cursor" },
  { value: "claude-desktop", label: "Claude Desktop" },
  { value: "qwen-code", label: "Qwen Code" },
  { value: "vscode", label: "VS Code" },
];

const SOURCE_OPTIONS = ["", "docs", "apiref"] as const;

/** Designed offline dataset: seeds the section so it is reviewable with no prior saves. */
const PRESET_SEED: WorkspacePreset[] = [
  {
    preset_id: "seed-ocr-quickstart",
    name: "OCR · C# quickstart",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "latest-stable",
    source_kind: "docs",
    client_id: "cursor",
    transport: "streamable-http",
    mode: "search",
    query: "how to recognize text from an image in C#",
    symbol_fqn: "",
    created_at: "2026-06-01T09:12:00.000Z",
    last_used_at: "2026-06-08T14:30:00.000Z",
  },
  {
    preset_id: "seed-ocr-symbol",
    name: "OCR · Recognize symbol",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "",
    source_kind: "apiref",
    client_id: "claude-desktop",
    transport: "streamable-http",
    mode: "symbol",
    query: "",
    symbol_fqn: "Aspose.OCR.OcrEngine.Recognize",
    created_at: "2026-06-03T11:00:00.000Z",
    last_used_at: "2026-06-03T11:00:00.000Z",
  },
];

/** Designed offline dataset for the ordered session deck (walkthrough running order). */
const SESSION_DECK_SEED: WorkspacePreset[] = [
  {
    preset_id: "deck-ocr-resolve",
    name: "1 · Resolve the product",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "latest-stable",
    source_kind: "",
    client_id: "cursor",
    transport: "streamable-http",
    mode: "search",
    query: "resolve aspose.ocr for .NET",
    symbol_fqn: "",
    created_at: "2026-06-05T08:00:00.000Z",
    last_used_at: "2026-06-09T16:10:00.000Z",
  },
  {
    preset_id: "deck-ocr-recognize",
    name: "2 · Recognize symbol walkthrough",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "",
    source_kind: "apiref",
    client_id: "cursor",
    transport: "streamable-http",
    mode: "symbol",
    query: "",
    symbol_fqn: "Aspose.OCR.OcrEngine.Recognize",
    created_at: "2026-06-05T08:05:00.000Z",
    last_used_at: "2026-06-09T16:12:00.000Z",
  },
];

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

/* ---------------- storage helpers ---------------- */

function readPresetStore(storageKey: string, cap: number): WorkspacePreset[] | null {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter(isWorkspacePreset).slice(0, cap);
  } catch {
    return null;
  }
}

/** Returns true on success, false if storage is unavailable / quota-exceeded. */
function writePresetStore(storageKey: string, presets: WorkspacePreset[]): boolean {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(presets));
    return true;
  } catch {
    return false;
  }
}

function isWorkspaceClientId(value: unknown): value is WorkspaceClientId {
  return (
    value === "cursor" || value === "claude-desktop" || value === "qwen-code" || value === "vscode"
  );
}

function isWorkspaceTransport(value: unknown): value is WorkspaceTransport {
  return value === "streamable-http" || value === "sse";
}

function isWorkspacePreset(value: unknown): value is WorkspacePreset {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.preset_id === "string" &&
    typeof v.name === "string" &&
    typeof v.product_id === "string" &&
    typeof v.programming_language === "string" &&
    typeof v.version === "string" &&
    typeof v.source_kind === "string" &&
    isWorkspaceClientId(v.client_id) &&
    isWorkspaceTransport(v.transport) &&
    (v.mode === "search" || v.mode === "symbol") &&
    typeof v.query === "string" &&
    typeof v.symbol_fqn === "string" &&
    typeof v.created_at === "string" &&
    typeof v.last_used_at === "string"
  );
}

function normalizePack(raw: unknown): WorkspacePreset[] | null {
  if (!raw || typeof raw !== "object") return null;
  const candidate = raw as Record<string, unknown>;
  // Accept either a bare array or a wrapped pack envelope.
  const list = Array.isArray(candidate) ? candidate : candidate.presets;
  if (!Array.isArray(list)) return null;
  const presets = list.filter(isWorkspacePreset);
  return presets.length ? presets : null;
}

function formatStamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function downloadJson(filename: string, contents: string) {
  try {
    const blob = new Blob([contents], { type: "application/json;charset=utf-8" });
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

interface FlashMessage {
  variant: "ok" | "warn" | "info";
  title: string;
  text?: string;
}

export default function WorkspacePresets() {
  // Hydration-safe: start empty (SSR), then load from storage / seed after mount.
  const [presets, setPresets] = useState<WorkspacePreset[]>([]);
  const [deck, setDeck] = useState<WorkspacePreset[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [flash, setFlash] = useState<FlashMessage | null>(null);

  useEffect(() => {
    const storedPresets = readPresetStore(WORKSPACE_PRESETS_STORAGE_KEY, MAX_WORKSPACE_PRESETS);
    setPresets(storedPresets ?? PRESET_SEED);
    const storedDeck = readPresetStore(SESSION_DECK_STORAGE_KEY, MAX_SESSION_DECK);
    setDeck(storedDeck ?? SESSION_DECK_SEED);
    setHydrated(true);
  }, []);

  // Persist after hydration whenever the set changes (skip the initial seed write
  // so we never clobber a user's real storage on first mount).
  const didHydrateRef = useRef(false);
  useEffect(() => {
    if (!hydrated) return;
    if (!didHydrateRef.current) {
      didHydrateRef.current = true;
      return;
    }
    const ok =
      writePresetStore(WORKSPACE_PRESETS_STORAGE_KEY, presets) &&
      writePresetStore(SESSION_DECK_STORAGE_KEY, deck);
    if (!ok) {
      setFlash({
        variant: "warn",
        title: "Saved in memory only",
        text: "Browser storage is unavailable (private mode or quota). Presets persist for this session but will not survive a reload.",
      });
    }
  }, [presets, deck, hydrated]);

  // --- current workspace form (the scope a Save snapshots) ---
  const [name, setName] = useState("");
  const [productId, setProductId] = useState("aspose.ocr");
  const [language, setLanguage] = useState("net");
  const [version, setVersion] = useState("");
  const [sourceKind, setSourceKind] = useState("");
  const [clientId, setClientId] = useState<WorkspaceClientId>("cursor");
  const [transport, setTransport] = useState<WorkspaceTransport>("streamable-http");
  const [mode, setMode] = useState<WorkspaceMode>("search");
  const [query, setQuery] = useState("");
  const [symbolFqn, setSymbolFqn] = useState("");

  const nameId = useId();
  const productFieldId = useId();
  const languageFieldId = useId();
  const versionFieldId = useId();
  const sourceFieldId = useId();
  const clientFieldId = useId();
  const transportFieldId = useId();
  const modeFieldId = useId();
  const detailFieldId = useId();
  const importFieldId = useId();

  const atCapacity = presets.length >= MAX_WORKSPACE_PRESETS;

  const saveCurrent = useCallback(() => {
    const normalizedName = name.trim();
    if (!normalizedName) {
      setFlash({ variant: "warn", title: "Workspace name is required before saving." });
      return;
    }
    const now = new Date().toISOString();
    const preset: WorkspacePreset = {
      preset_id: `preset-${now}-${Math.random().toString(36).slice(2, 7)}`,
      name: normalizedName,
      product_id: productId.trim() || "aspose.ocr",
      programming_language: language.trim() || "net",
      version: version.trim(),
      source_kind: sourceKind,
      client_id: clientId,
      transport,
      mode,
      query: mode === "search" ? query.trim() : "",
      symbol_fqn: mode === "symbol" ? symbolFqn.trim() : "",
      created_at: now,
      last_used_at: now,
    };
    setPresets((current) => {
      // Replace a same-named preset, else prepend; cap to MAX (drop oldest tail).
      const withoutDup = current.filter((p) => p.name !== normalizedName);
      return [preset, ...withoutDup].slice(0, MAX_WORKSPACE_PRESETS);
    });
    setName("");
    setFlash({ variant: "ok", title: `Saved workspace “${normalizedName}”.` });
  }, [name, productId, language, version, sourceKind, clientId, transport, mode, query, symbolFqn]);

  const loadPreset = useCallback((preset: WorkspacePreset) => {
    setName(preset.name);
    setProductId(preset.product_id);
    setLanguage(preset.programming_language);
    setVersion(preset.version);
    setSourceKind(preset.source_kind);
    setClientId(preset.client_id);
    setTransport(preset.transport);
    setMode(preset.mode);
    setQuery(preset.query);
    setSymbolFqn(preset.symbol_fqn);
    const now = new Date().toISOString();
    setPresets((current) =>
      current.map((p) => (p.preset_id === preset.preset_id ? { ...p, last_used_at: now } : p)),
    );
    setFlash({ variant: "info", title: `Loaded “${preset.name}” into the workspace form.` });
  }, []);

  const deletePreset = useCallback((preset: WorkspacePreset) => {
    setPresets((current) => current.filter((p) => p.preset_id !== preset.preset_id));
    setFlash({ variant: "info", title: `Deleted “${preset.name}”.` });
  }, []);

  const exportPack = useCallback(() => {
    if (!presets.length) {
      setFlash({ variant: "warn", title: "No presets to export yet." });
      return;
    }
    const pack: WorkspacePresetPack = {
      pack_version: WORKSPACE_PACK_VERSION,
      exported_at: new Date().toISOString(),
      exported_from: "adcs-public-integrations",
      preset_count: presets.length,
      presets,
    };
    downloadJson("adcs-workspace-presets.json", JSON.stringify(pack, null, 2));
    setFlash({ variant: "ok", title: `Exported ${presets.length} preset(s).` });
  }, [presets]);

  /* ---------------- session deck (ordered walkthrough) ---------------- */

  const addCurrentToDeck = useCallback(() => {
    const normalizedName = name.trim() || `Step ${deck.length + 1}`;
    const now = new Date().toISOString();
    const card: WorkspacePreset = {
      preset_id: `deck-${now}-${Math.random().toString(36).slice(2, 7)}`,
      name: normalizedName,
      product_id: productId.trim() || "aspose.ocr",
      programming_language: language.trim() || "net",
      version: version.trim(),
      source_kind: sourceKind,
      client_id: clientId,
      transport,
      mode,
      query: mode === "search" ? query.trim() : "",
      symbol_fqn: mode === "symbol" ? symbolFqn.trim() : "",
      created_at: now,
      last_used_at: now,
    };
    // Deck is ORDERED: append to the running order, cap by dropping the oldest head.
    setDeck((current) => [...current, card].slice(-MAX_SESSION_DECK));
    setFlash({ variant: "ok", title: `Added “${normalizedName}” to the session deck.` });
  }, [name, productId, language, version, sourceKind, clientId, transport, mode, query, symbolFqn, deck.length]);

  const removeFromDeck = useCallback((card: WorkspacePreset) => {
    setDeck((current) => current.filter((p) => p.preset_id !== card.preset_id));
    setFlash({ variant: "info", title: `Removed “${card.name}” from the session deck.` });
  }, []);

  const clearDeck = useCallback(() => {
    if (!deck.length) {
      setFlash({ variant: "warn", title: "The session deck is already empty." });
      return;
    }
    setDeck([]);
    setFlash({ variant: "info", title: "Cleared the session deck." });
  }, [deck.length]);

  const exportDeck = useCallback(() => {
    if (!deck.length) {
      setFlash({ variant: "warn", title: "No session-deck cards to export yet." });
      return;
    }
    const pack: WorkspacePresetPack = {
      pack_version: WORKSPACE_PACK_VERSION,
      exported_at: new Date().toISOString(),
      exported_from: "adcs-public-integrations",
      preset_count: deck.length,
      presets: deck,
    };
    downloadJson("adcs-session-deck.json", JSON.stringify(pack, null, 2));
    setFlash({ variant: "ok", title: `Exported ${deck.length} session-deck card(s).` });
  }, [deck]);

  const [importText, setImportText] = useState("");
  const importFileRef = useRef<HTMLInputElement | null>(null);

  const importFromFile = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      setImportText(text);
      let parsed: unknown;
      try {
        parsed = JSON.parse(text.trim());
      } catch {
        setFlash({ variant: "warn", title: "Import failed", text: "The selected file is not valid JSON." });
        return;
      }
      const incoming = normalizePack(parsed);
      if (!incoming) {
        setFlash({
          variant: "warn",
          title: "Import failed",
          text: "No valid workspace presets were found in the file.",
        });
        return;
      }
      setPresets((current) => {
        const byId = new Map(current.map((p) => [p.preset_id, p]));
        for (const p of incoming) byId.set(p.preset_id, p);
        return Array.from(byId.values()).slice(0, MAX_WORKSPACE_PRESETS);
      });
      setImportText("");
      setFlash({ variant: "ok", title: `Imported ${incoming.length} preset(s) from ${file.name}.` });
    };
    reader.onerror = () => {
      setFlash({ variant: "warn", title: "Import failed", text: "Could not read the selected file." });
    };
    reader.readAsText(file);
  }, []);

  const importPack = useCallback(() => {
    const trimmed = importText.trim();
    if (!trimmed) {
      setFlash({ variant: "warn", title: "Paste a workspace pack JSON to import." });
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      setFlash({ variant: "warn", title: "Import failed", text: "The pasted text is not valid JSON." });
      return;
    }
    const incoming = normalizePack(parsed);
    if (!incoming) {
      setFlash({
        variant: "warn",
        title: "Import failed",
        text: "No valid workspace presets were found in the pack.",
      });
      return;
    }
    setPresets((current) => {
      const byId = new Map(current.map((p) => [p.preset_id, p]));
      for (const p of incoming) byId.set(p.preset_id, p);
      return Array.from(byId.values()).slice(0, MAX_WORKSPACE_PRESETS);
    });
    setImportText("");
    setFlash({ variant: "ok", title: `Imported ${incoming.length} preset(s).` });
  }, [importText]);

  const sortedPresets = useMemo(
    () => [...presets].sort((a, b) => b.last_used_at.localeCompare(a.last_used_at)),
    [presets],
  );

  return (
    <div className="pub t-mono">
      <section className="pub-card" aria-label="Workspace presets and deck management">
        <div className="pub-card-head">
          <span className="pub-card-title">Workspace presets &amp; deck</span>
          <span className="right muted-note">
            {hydrated ? `${presets.length}/${MAX_WORKSPACE_PRESETS} saved · local to this browser` : "local to this browser"}
          </span>
        </div>

        <div style={{ padding: "16px 20px" }}>
          {flash && (
            <div style={{ marginBottom: 14 }} role="status" aria-live="polite">
              <Banner
                variant={flash.variant}
                icon={flash.variant === "ok" ? "check" : flash.variant === "warn" ? "alert" : "info"}
                title={flash.title}
                text={flash.text}
              />
            </div>
          )}

          {/* current workspace form */}
          <div className="pub-card" style={{ margin: 0 }}>
            <div className="pub-card-head">
              <span className="pub-card-title" style={{ fontSize: 14 }}>
                Current workspace
              </span>
            </div>
            <div style={{ padding: "14px 18px" }}>
              <div className="toolbar" style={{ margin: 0, flexWrap: "wrap" }}>
                <span className="input" style={{ minWidth: 200, flex: 1 }}>
                  <label style={SR_ONLY} htmlFor={nameId}>
                    Workspace name
                  </label>
                  <input
                    id={nameId}
                    className="inputctl"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Workspace name (e.g. OCR · C# quickstart)"
                    aria-label="Workspace name"
                  />
                </span>
                <Button
                  variant="btn-primary"
                  icon="plus"
                  onClick={saveCurrent}
                  disabled={!name.trim()}
                  title={atCapacity ? "At capacity — saving drops the oldest preset" : undefined}
                >
                  Save workspace
                </Button>
                <Button
                  icon="layers"
                  onClick={addCurrentToDeck}
                  title="Append the current scope to the ordered session deck"
                >
                  Add to deck
                </Button>
              </div>

              <div className="toolbar" style={{ marginTop: 12, marginBottom: 0, flexWrap: "wrap" }}>
                <span className="input" style={{ minWidth: 130 }}>
                  <label style={SR_ONLY} htmlFor={productFieldId}>
                    Product ID
                  </label>
                  <input
                    id={productFieldId}
                    className="inputctl"
                    value={productId}
                    onChange={(e) => setProductId(e.target.value)}
                    placeholder="aspose.ocr"
                    aria-label="Product ID"
                  />
                </span>
                <span className="input" style={{ minWidth: 90 }}>
                  <label style={SR_ONLY} htmlFor={languageFieldId}>
                    SDK language
                  </label>
                  <input
                    id={languageFieldId}
                    className="inputctl"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    placeholder="net"
                    aria-label="SDK language"
                  />
                </span>
                <span className="input" style={{ minWidth: 110 }}>
                  <label style={SR_ONLY} htmlFor={versionFieldId}>
                    Version
                  </label>
                  <input
                    id={versionFieldId}
                    className="inputctl"
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    placeholder="latest-stable"
                    aria-label="Version"
                  />
                </span>
                <span className="select" style={{ minWidth: 110 }}>
                  <label style={SR_ONLY} htmlFor={sourceFieldId}>
                    Source kind
                  </label>
                  <select
                    id={sourceFieldId}
                    className="selectctl"
                    value={sourceKind}
                    onChange={(e) => setSourceKind(e.target.value)}
                    aria-label="Source kind"
                  >
                    {SOURCE_OPTIONS.map((s) => (
                      <option key={s || "all"} value={s}>
                        {s || "all sources"}
                      </option>
                    ))}
                  </select>
                </span>
                <span className="select" style={{ minWidth: 130 }}>
                  <label style={SR_ONLY} htmlFor={clientFieldId}>
                    Client
                  </label>
                  <select
                    id={clientFieldId}
                    className="selectctl"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value as WorkspaceClientId)}
                    aria-label="Client"
                  >
                    {CLIENT_OPTIONS.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </span>
                <span className="select" style={{ minWidth: 140 }}>
                  <label style={SR_ONLY} htmlFor={transportFieldId}>
                    Transport
                  </label>
                  <select
                    id={transportFieldId}
                    className="selectctl"
                    value={transport}
                    onChange={(e) => setTransport(e.target.value as WorkspaceTransport)}
                    aria-label="Transport"
                  >
                    <option value="streamable-http">streamable-http</option>
                    <option value="sse">sse</option>
                  </select>
                </span>
                <span className="select" style={{ minWidth: 100 }}>
                  <label style={SR_ONLY} htmlFor={modeFieldId}>
                    Mode
                  </label>
                  <select
                    id={modeFieldId}
                    className="selectctl"
                    value={mode}
                    onChange={(e) => setMode(e.target.value as WorkspaceMode)}
                    aria-label="Mode"
                  >
                    <option value="search">query</option>
                    <option value="symbol">symbol</option>
                  </select>
                </span>
                <span className="input" style={{ flex: 1, minWidth: 220 }}>
                  <label style={SR_ONLY} htmlFor={detailFieldId}>
                    {mode === "search" ? "Query" : "Symbol FQN"}
                  </label>
                  {mode === "search" ? (
                    <input
                      id={detailFieldId}
                      className="inputctl"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="query text"
                      aria-label="Query"
                    />
                  ) : (
                    <input
                      id={detailFieldId}
                      className="inputctl"
                      value={symbolFqn}
                      onChange={(e) => setSymbolFqn(e.target.value)}
                      placeholder="Aspose.OCR.OcrEngine.Recognize"
                      aria-label="Symbol FQN"
                    />
                  )}
                </span>
              </div>
            </div>
          </div>

          {/* saved presets */}
          <div style={{ marginTop: 16 }}>
            {!hydrated ? null : sortedPresets.length === 0 ? (
              <EmptyState
                title="No saved presets"
                text="Snapshot the current workspace scope above to reuse it across sessions. Presets are stored in this browser only."
              />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {sortedPresets.map((preset) => (
                  <div className="svc-row" key={preset.preset_id} style={{ flexWrap: "wrap" }}>
                    <Pill variant={preset.mode === "symbol" ? "info" : "ok"}>{preset.mode}</Pill>
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <div className="svc-name">{preset.name}</div>
                      <div className="svc-desc" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                        <Tag>{preset.product_id}</Tag>
                        <Tag>{preset.programming_language}</Tag>
                        {preset.version ? <Tag>{preset.version}</Tag> : null}
                        <Tag>{preset.client_id}</Tag>
                      </div>
                      <div className="muted-note" style={{ marginTop: 4 }}>
                        {(preset.mode === "search" ? preset.query : preset.symbol_fqn) || "—"}
                      </div>
                    </div>
                    <div
                      className="mono"
                      style={{ fontSize: 11, color: "var(--fg-subtle)", minWidth: 150 }}
                    >
                      saved {formatStamp(preset.created_at)}
                      <br />
                      used {formatStamp(preset.last_used_at)}
                    </div>
                    <div style={{ display: "inline-flex", gap: 8 }}>
                      <Button size="sm" icon="play" onClick={() => loadPreset(preset)}>
                        Load
                      </Button>
                      <Button
                        size="sm"
                        variant="btn-danger"
                        icon="x"
                        onClick={() => deletePreset(preset)}
                        aria-label={`Delete preset ${preset.name}`}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* export / import deck */}
          <div className="pub-card" style={{ margin: "16px 0 0" }}>
            <div className="pub-card-head">
              <span className="pub-card-title" style={{ fontSize: 14 }}>
                Export / import deck
              </span>
              <span className="right">
                <Button size="sm" icon="download" onClick={exportPack} disabled={!presets.length}>
                  Export pack
                </Button>
              </span>
            </div>
            <div style={{ padding: "14px 18px" }}>
              <label className="muted-note" htmlFor={importFieldId} style={{ display: "block", marginBottom: 6 }}>
                Upload an exported pack file, or paste its JSON, to merge it into this browser
              </label>
              <textarea
                id={importFieldId}
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder='{"pack_version":"adcs.public-workspace-pack.v1", ...}'
                aria-label="Workspace pack JSON"
                rows={3}
                spellCheck={false}
                style={{
                  display: "block",
                  width: "100%",
                  marginBottom: 10,
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--surface)",
                  padding: "8px 10px",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--fg)",
                  outline: "none",
                  resize: "vertical",
                }}
              />
              <input
                ref={importFileRef}
                type="file"
                accept="application/json,.json"
                style={SR_ONLY}
                aria-label="Choose a workspace pack file"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) importFromFile(file);
                  e.target.value = "";
                }}
              />
              <div style={{ display: "inline-flex", gap: 8 }}>
                <Button icon="upload" onClick={() => importFileRef.current?.click()}>
                  Choose file…
                </Button>
                <Button variant="btn-primary" icon="check" onClick={importPack} disabled={!importText.trim()}>
                  Import pack
                </Button>
              </div>
              <div className="muted-note" style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name="info" />
                Presets live under <span className="mono">{WORKSPACE_PRESETS_STORAGE_KEY}</span> — export before clearing browser data.
              </div>
            </div>
          </div>

          {/* session deck — ordered walkthrough (similar workflow, separate store) */}
          <div className="pub-card" style={{ margin: "16px 0 0" }} aria-label="Session deck">
            <div className="pub-card-head">
              <span className="pub-card-title" style={{ fontSize: 14 }}>
                Session deck
              </span>
              <span className="right" style={{ display: "inline-flex", gap: 8 }}>
                <Button size="sm" icon="download" onClick={exportDeck} disabled={!deck.length}>
                  Export deck
                </Button>
                <Button size="sm" variant="btn-danger" icon="x" onClick={clearDeck} disabled={!deck.length}>
                  Clear deck
                </Button>
              </span>
            </div>
            <div style={{ padding: "14px 18px" }}>
              <div className="muted-note" style={{ marginBottom: 12, display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon name="info" />
                Build an ordered walkthrough — use <span className="mono">Add to deck</span> above to append the current scope in running order.
              </div>
              {!hydrated ? null : deck.length === 0 ? (
                <EmptyState
                  title="Session deck is empty"
                  text="Append the current workspace scope to assemble an ordered onboarding walkthrough. The deck is stored in this browser only."
                />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {deck.map((card, index) => (
                    <div className="svc-row" key={card.preset_id} style={{ flexWrap: "wrap" }}>
                      <span
                        className="mono"
                        aria-hidden="true"
                        style={{ fontSize: 12, color: "var(--fg-subtle)", minWidth: 22 }}
                      >
                        {index + 1}
                      </span>
                      <Pill variant={card.mode === "symbol" ? "info" : "ok"}>{card.mode}</Pill>
                      <div style={{ flex: 1, minWidth: 220 }}>
                        <div className="svc-name">{card.name}</div>
                        <div className="svc-desc" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                          <Tag>{card.product_id}</Tag>
                          <Tag>{card.programming_language}</Tag>
                          {card.version ? <Tag>{card.version}</Tag> : null}
                          <Tag>{card.client_id}</Tag>
                        </div>
                        <div className="muted-note" style={{ marginTop: 4 }}>
                          {(card.mode === "search" ? card.query : card.symbol_fqn) || "—"}
                        </div>
                      </div>
                      <div style={{ display: "inline-flex", gap: 8 }}>
                        <Button size="sm" icon="play" onClick={() => loadPreset(card)}>
                          Load
                        </Button>
                        <Button
                          size="sm"
                          variant="btn-danger"
                          icon="x"
                          onClick={() => removeFromDeck(card)}
                          aria-label={`Remove ${card.name} from the session deck`}
                        >
                          Remove
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
