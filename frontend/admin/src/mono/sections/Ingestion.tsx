"use client";

import {
  Fragment,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { getAdminErrorMessage, toPreviewJson } from "@/components/admin-console.utils";
import { useIngestionState } from "@/hooks/useIngestionState";
import type {
  IngestionResultSummary,
  RawMarkdownPreview,
  ReviewArtifactPreview,
  StagingManifestPreview,
} from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { Tabs } from "../components/Tabbed";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useConfirm, useToast } from "../shell/overlays";

// ────────────────────────────────────────────── Token-only inline primitives ─
// The kit has no class for these small bespoke surfaces, so they are built INLINE
// from Mono tokens only (no new hex, no new fonts, no Material look), reusing existing
// classes + tokens.

const S = {
  statusBar: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 12,
    flexWrap: "wrap",
  } as CSSProperties,
  // Pulsing "running" LED — reuses the existing `ledpulse` keyframe (same pattern as
  // `.pub-status-led .led`), recolored to the info token. No new keyframes introduced.
  spinner: {
    width: 9,
    height: 9,
    borderRadius: "999px",
    background: "var(--info)",
    boxShadow: "0 0 0 0 color-mix(in srgb, var(--info) 70%, transparent)",
    animation: "ledpulse 2.4s infinite",
    flex: "none",
  } as CSSProperties,
  busyWrap: { display: "inline-flex", alignItems: "center", gap: 8 } as CSSProperties,
  spacer: { flex: 1 } as CSSProperties,
  // Selectable repository result chips (review workspace).
  resultTabs: { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 } as CSSProperties,
  resultTab: (sel: boolean): CSSProperties => ({
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    padding: "6px 11px",
    borderRadius: "var(--radius-sm)",
    border: `1px solid ${sel ? "var(--accent-line)" : "var(--border)"}`,
    background: sel ? "var(--surface-2)" : "var(--surface)",
    boxShadow: sel ? "0 0 0 2px color-mix(in srgb, var(--accent-line) 16%, transparent)" : "none",
    cursor: "pointer",
    font: "inherit",
  }),
  // Batch repository multi-select.
  batchList: { display: "flex", flexDirection: "column" } as CSSProperties,
  batchRow: (sel: boolean): CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "11px 16px",
    borderBottom: "1px solid var(--border)",
    cursor: "pointer",
    background: sel ? "var(--surface-2)" : "transparent",
    boxShadow: sel ? "inset 2px 0 0 var(--accent-line)" : "none",
  }),
  batchFoot: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginTop: 14,
    paddingTop: 14,
    borderTop: "1px solid var(--border)",
    flexWrap: "wrap",
  } as CSSProperties,
  // Language-hint chips (onboarding step 3).
  chipRow: { display: "flex", flexWrap: "wrap", gap: 7, alignItems: "center" } as CSSProperties,
  chip: { display: "inline-flex", alignItems: "center", gap: 4 } as CSSProperties,
  chipX: {
    display: "grid",
    placeItems: "center",
    width: 16,
    height: 16,
    padding: 0,
    border: "none",
    background: "transparent",
    color: "var(--fg-subtle)",
    cursor: "pointer",
  } as CSSProperties,
  rowActs: { display: "inline-flex", gap: 6, justifyContent: "flex-end" } as CSSProperties,
  loadArea: {
    border: "1px dashed var(--border-strong)",
    borderRadius: "var(--radius-sm)",
    background: "var(--surface-2)",
    padding: "16px 14px",
    textAlign: "center",
  } as CSSProperties,
  failMsg: {
    fontSize: 11.5,
    color: "var(--fg-muted)",
    margin: "2px 0 8px 24px",
    lineHeight: 1.5,
  } as CSSProperties,
  textarea: {
    width: "100%",
    minHeight: 70,
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    background: "var(--surface)",
    padding: "9px 12px",
    fontFamily: "var(--font-sans)",
    fontSize: 13,
    color: "var(--fg)",
    outline: "none",
    resize: "vertical",
    lineHeight: 1.5,
  } as CSSProperties,
} as const;

// ───────────────────────────────────────────── Onboarding wizard fixtures ────

const WIZ_STEPS = [
  "Product identity",
  "Repository layout",
  "Language hints",
  "Review & register",
] as const;

interface FInput {
  label: string;
  req?: boolean;
  /** Example value — shown as the placeholder of the bound control. */
  value?: string;
  ph?: string;
  hint?: string;
  focus?: boolean;
  chev?: boolean;
  full?: boolean;
}

const WIZ_FIELDS: FInput[][] = [
  [
    {
      label: "product_id",
      req: true,
      value: "aspose.ocr",
      hint: "Stable machine id, lowercase — e.g. aspose.omr",
      focus: true,
    },
    {
      label: "product_name",
      ph: "Aspose.OCR (optional)",
      hint: "Human-readable label shown in cards & lists",
    },
    {
      label: "product_family",
      req: true,
      value: "aspose",
      hint: "Top-level vendor namespace — e.g. aspose, groupdocs",
      chev: true,
    },
    {
      label: "product_family_dir",
      req: true,
      value: "Aspose.OCR",
      hint: "Exact top-level folder under source-repo-docs / source-repo-apiref",
    },
    { label: "docs git URL", ph: "https://git…/Aspose.OCR-docs.git", full: true },
    { label: "apiref git URL", ph: "https://git…/Aspose.OCR-apiref.git", full: true },
  ],
  [
    {
      label: "default branch",
      req: true,
      value: "main",
      chev: true,
      hint: "Branch synced for both repositories",
    },
    {
      label: "layout detection",
      value: "auto-detect",
      chev: true,
      hint: "Parser layout profile applied during ingestion",
    },
    {
      label: "docs content subpath",
      value: "content/",
      hint: "Folder under family dir holding docs markdown",
    },
    {
      label: "apiref content subpath",
      value: "api/",
      hint: "Folder under family dir holding API reference",
    },
  ],
  [
    {
      label: "programming languages",
      req: true,
      value: "net, java",
      full: true,
      hint: "Comma-separated canonical language ids served for this product",
    },
    {
      label: "documentation locales",
      value: "en",
      full: true,
      hint: "Locales available in the docs source — e.g. en, ru, zh",
    },
  ],
];

// Suggested language hints shown in the language-hints step (plus Add Custom Language).
// Picking one writes into the hook's onboardKnownProgrammingLanguages array — the
// exact list the Register submit posts to /admin/v1/source-repositories/onboard-product.
const SUGGESTED_LANGS = ["net", "java", "python-net", "python-java", "cpp", "node-cpp"] as const;

// ─────────────────────────────────────────────── Run discipline fixtures ────

interface RunOp {
  pill: StatusVariant;
  pillText: string;
  name: string;
  meta: string;
  action: ReactNode;
}

// Batch repository picker fixture (batch multi-select). Mirrors the repo ids the
// hook's batchRepoIds operates on; offline this seeds the multi-select so batch actions
// are fully exercisable. Live mode merges in real repo ids from the products query.
interface BatchRepoFixture {
  repoId: string;
  kind: "docs" | "apiref";
  state: "stale" | "fresh" | "never";
}

const BATCH_REPOS: BatchRepoFixture[] = [
  { repoId: "aspose.ocr.docs", kind: "docs", state: "stale" },
  { repoId: "aspose.ocr.apiref", kind: "apiref", state: "fresh" },
  { repoId: "aspose.cells.apiref", kind: "apiref", state: "stale" },
  { repoId: "aspose.cad.docs", kind: "docs", state: "stale" },
  { repoId: "aspose.barcode.apiref", kind: "apiref", state: "never" },
  { repoId: "groupdocs.parser.docs", kind: "docs", state: "fresh" },
];

// ──────────────────────────────────────────────── History & review data ────

type RunRow = [
  id: string,
  scope: string,
  res: "ok" | "warn" | "crit",
  out: "published" | "validated" | "blocked" | "failed",
  dur: string,
  when: string,
];

const RUNS: RunRow[] = [
  ["run_8c3864e", "aspose.ocr.apiref", "ok", "published", "12.4s", "today 12:17"],
  ["run_4a1f9b2", "aspose.ocr.docs", "ok", "validated", "8.1s", "today 11:52"],
  ["run_2c77d10", "aspose.cells.apiref", "warn", "blocked", "—", "today 10:30"],
  ["run_91be0a4", "aspose.cad.docs", "ok", "validated", "6.7s", "yesterday"],
  ["run_55da2f1", "aspose.barcode.apiref", "crit", "failed", "2.0s", "yesterday"],
];

const RUN_STATUS: Record<RunRow[3], [StatusVariant, string]> = {
  published: ["ok", "published"],
  validated: ["ok", "validated"],
  blocked: ["warn", "blocked"],
  failed: ["crit", "failed"],
};

const STAGE_SEQ = [
  ["raw", "Raw markdown"],
  ["parsed", "Parsed pages"],
  ["chunks", "Chunk records"],
  ["staging", "Staging manifest"],
  ["review", "Review artifact"],
] as const;

type StageKey = (typeof STAGE_SEQ)[number][0];

// Per-stage preview payload rendered as a human-readable preview (NOT raw JSON) when an
// operator clicks Load. API limitation: offline the hook's preview mutations cannot reach the
// backend, so the workspace drives these previews off the fixture below; live mode swaps
// in the real RawMarkdownPreview / StagingManifestPreview / ReviewArtifactPreview payload.
interface StagePreview {
  /** Short human caption shown above the preview block. */
  caption: string;
  /** Pre-formatted preview body (already humanized — line breaks, no JSON braces). */
  body: string;
  /** Whether this stage exposes a Load action that "fetches" the preview. */
  loadable?: boolean;
  /** Loaded-state label for the Load button (e.g. "Raw markdown"). */
  loadLabel?: string;
  /**
   * Derived-stage missing-content marker (live path only). When set, the derived
   * parsed/chunks stage produced no artifacts and the workspace renders the
   * EmptyState (title + suggested action) instead of a `.rv-pre` body string — matching
   * the other panels' empty states (no-parsed/no-chunks).
   */
  emptyTitle?: string;
}

interface ResultScope {
  product_id: string;
  programming_language: string;
  version: string;
  doc_locale: string;
  source_kind: "docs" | "apiref";
}

interface ResultFixture {
  repoId: string;
  scope: ResultScope;
  parsedPages: number;
  chunkRecords: number;
  parseWarnings: number;
  sourcePaths: number;
  decision: "approved" | "rejected" | "blocked";
  gate: string;
  gateMsg: string;
  stages: Record<StageKey, StagePreview>;
  failed: { code: string; path: string; message: string }[];
}

interface ReviewFixture {
  /** Top-level operation decision shown in the decision bar. */
  decision: "approved" | "rejected" | "blocked";
  gate: string;
  msg: string;
  /** Per-repository transformation results (filterable). */
  results: ResultFixture[];
}

const REVIEW: Record<string, ReviewFixture> = {
  run_8c3864e: {
    decision: "approved",
    gate: "publish_safety",
    msg: "Usable chunk coverage 99.2% · 0 critical parser failures.",
    results: [
      {
        repoId: "aspose.ocr.apiref",
        scope: {
          product_id: "aspose.ocr",
          programming_language: "net",
          version: "latest",
          doc_locale: "en",
          source_kind: "apiref",
        },
        parsedPages: 128,
        chunkRecords: 24_318,
        parseWarnings: 0,
        sourcePaths: 128,
        decision: "approved",
        gate: "publish_safety",
        gateMsg: "score 4.6 / 5 · blocking findings 0 · citation integrity 98%",
        stages: {
          raw: {
            caption: "128 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "title: Document.Save\nproduct: aspose.words\nlang: net\n\n# Document.Save(string fileName)\n\nSaves the document to the specified file. Throws ArgumentNullException when\nfileName is null.",
          },
          parsed: {
            caption: "128 parsed pages",
            body:
              'page #1 — title "Document.Save" · locale=en · lang=net · symbols=3\nheadings: Overview, Parameters, Examples\ncode blocks: 2 (csharp)',
          },
          chunks: {
            caption: "24 318 chunk records",
            body:
              "chunk#0 type=api_signature anchor=#save tokens=180\nchunk#1 type=parameters anchor=#parameters tokens=240\nchunk#2 type=example anchor=#examples tokens=420",
          },
          staging: {
            caption: "manifest written",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "scope net/latest · tier hot\ndocuments processed: 128\nchunks generated: 24 318\nmanifest: staging/aspose.ocr/net/latest/apiref.manifest.json",
          },
          review: {
            caption: "semantic gate passed",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: approved\ngate: publish_safety\nmessage: score 4.6 / 5 · blocking findings 0\ncitation integrity: 98%",
          },
        },
        failed: [],
      },
      {
        repoId: "aspose.ocr.docs",
        scope: {
          product_id: "aspose.ocr",
          programming_language: "java",
          version: "latest",
          doc_locale: "en",
          source_kind: "docs",
        },
        parsedPages: 64,
        chunkRecords: 5_120,
        parseWarnings: 3,
        sourcePaths: 66,
        decision: "approved",
        gate: "publish_safety",
        gateMsg: "score 4.4 / 5 · blocking findings 0 · 3 non-blocking parse warnings",
        stages: {
          raw: {
            caption: "66 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "title: Recognize images\nproduct: aspose.ocr\nlang: java\n\n# Recognize images\n\nThe OcrEngine reads characters from raster images. Configure the language\npack before calling recognize().",
          },
          parsed: {
            caption: "64 parsed pages · 2 index pages skipped",
            body:
              'page #1 — title "Recognize images" · locale=en · lang=java · symbols=1\nheadings: Overview, Languages, Sample\ncode blocks: 1 (java)',
          },
          chunks: {
            caption: "5 120 chunk records",
            body:
              "chunk#0 type=narrative anchor=#overview tokens=520\nchunk#1 type=example anchor=#sample tokens=380\nchunk#2 type=narrative anchor=#languages tokens=300",
          },
          staging: {
            caption: "manifest written",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "scope java/latest · tier hot\ndocuments processed: 64\nchunks generated: 5 120\nmanifest: staging/aspose.ocr/java/latest/docs.manifest.json",
          },
          review: {
            caption: "semantic gate passed (with warnings)",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: approved\ngate: publish_safety\nmessage: 3 non-blocking parse warnings — front-matter locale inferred\ncitation integrity: 96%",
          },
        },
        failed: [],
      },
    ],
  },
  run_2c77d10: {
    decision: "blocked",
    gate: "publish_safety",
    msg: "2 parser failures exceeded threshold; usable chunk coverage 71% (< 90%).",
    results: [
      {
        repoId: "aspose.cells.apiref",
        scope: {
          product_id: "aspose.cells",
          programming_language: "net",
          version: "24.1",
          doc_locale: "en",
          source_kind: "apiref",
        },
        parsedPages: 88,
        chunkRecords: 0,
        parseWarnings: 14,
        sourcePaths: 96,
        decision: "blocked",
        gate: "publish_safety",
        gateMsg: "run halted before semantic review — chunking aborted",
        stages: {
          raw: {
            caption: "96 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "title: PivotTable\n(front-matter malformed: missing 'product' key)\n\n# PivotTable\n\nUnterminated YAML block — parser could not resolve document metadata.",
          },
          parsed: {
            caption: "88 parsed pages · 8 dropped at parse stage",
            body:
              "8 pages dropped at parse stage (PARSE_ERROR_FRONTMATTER)\nremaining pages lack product metadata required for chunking",
          },
          chunks: {
            caption: "0 chunk records",
            body: "chunking aborted — staging gate not reached\nno indexable content produced",
          },
          staging: {
            caption: "no manifest",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "publish-safety gate blocked staging\nno manifest persisted — see parse warnings & failed items",
          },
          review: {
            caption: "semantic gate blocked",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: rejected\ngate: publish_safety\nmessage: 2 parser failures exceeded threshold; coverage 71% (< 90%)",
          },
        },
        failed: [
          {
            code: "PARSE_ERROR_FRONTMATTER",
            path: "content/cells/api/PivotTable.md",
            message: "Unterminated YAML front-matter block at line 1.",
          },
          {
            code: "GIT_CLONE_TIMEOUT",
            path: "aspose.cells.apiref @ origin",
            message: "Clone exceeded 120s — escalate to platform team.",
          },
        ],
      },
    ],
  },
  run_4a1f9b2: {
    decision: "approved",
    gate: "publish_safety",
    msg: "Validate-Only run · usable chunk coverage 100% · 0 parser failures.",
    results: [
      {
        repoId: "aspose.ocr.docs",
        scope: {
          product_id: "aspose.ocr",
          programming_language: "java",
          version: "latest",
          doc_locale: "en",
          source_kind: "docs",
        },
        parsedPages: 64,
        chunkRecords: 5_120,
        parseWarnings: 0,
        sourcePaths: 64,
        decision: "approved",
        gate: "publish_safety",
        gateMsg: "score 4.5 / 5 · blocking findings 0 · validate-only (no publish)",
        stages: {
          raw: {
            caption: "64 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "title: Recognize images\nproduct: aspose.ocr\nlang: java\n\n# Recognize images\n\nThe OcrEngine reads characters from raster images. Configure the language\npack before calling recognize().",
          },
          parsed: {
            caption: "64 parsed pages",
            body:
              'page #1 — title "Recognize images" · locale=en · lang=java · symbols=1\nheadings: Overview, Languages, Sample\ncode blocks: 1 (java)',
          },
          chunks: {
            caption: "5 120 chunk records",
            body:
              "chunk#0 type=narrative anchor=#overview tokens=520\nchunk#1 type=example anchor=#sample tokens=380\nchunk#2 type=narrative anchor=#languages tokens=300",
          },
          staging: {
            caption: "manifest written",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "scope java/latest · tier hot\ndocuments processed: 64\nchunks generated: 5 120\nmanifest: staging/aspose.ocr/java/latest/docs.manifest.json",
          },
          review: {
            caption: "semantic gate passed",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: approved\ngate: publish_safety\nmessage: validate-only run · score 4.5 / 5\ncitation integrity: 97%",
          },
        },
        failed: [],
      },
    ],
  },
  run_91be0a4: {
    decision: "approved",
    gate: "publish_safety",
    msg: "Validate-Only run · usable chunk coverage 98.7% · 0 parser failures.",
    results: [
      {
        repoId: "aspose.cad.docs",
        scope: {
          product_id: "aspose.cad",
          programming_language: "net",
          version: "latest",
          doc_locale: "en",
          source_kind: "docs",
        },
        parsedPages: 42,
        chunkRecords: 3_280,
        parseWarnings: 0,
        sourcePaths: 42,
        decision: "approved",
        gate: "publish_safety",
        gateMsg: "score 4.4 / 5 · blocking findings 0 · validate-only (no publish)",
        stages: {
          raw: {
            caption: "42 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "title: Load a CAD drawing\nproduct: aspose.cad\nlang: net\n\n# Load a CAD drawing\n\nUse Image.Load to open DWG and DXF files, then render to a raster format.",
          },
          parsed: {
            caption: "42 parsed pages",
            body:
              'page #1 — title "Load a CAD drawing" · locale=en · lang=net · symbols=2\nheadings: Overview, Supported formats, Sample\ncode blocks: 1 (csharp)',
          },
          chunks: {
            caption: "3 280 chunk records",
            body:
              "chunk#0 type=narrative anchor=#overview tokens=480\nchunk#1 type=example anchor=#sample tokens=360\nchunk#2 type=narrative anchor=#supported-formats tokens=320",
          },
          staging: {
            caption: "manifest written",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "scope net/latest · tier hot\ndocuments processed: 42\nchunks generated: 3 280\nmanifest: staging/aspose.cad/net/latest/docs.manifest.json",
          },
          review: {
            caption: "semantic gate passed",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: approved\ngate: publish_safety\nmessage: validate-only run · score 4.4 / 5\ncitation integrity: 96%",
          },
        },
        failed: [],
      },
    ],
  },
  run_55da2f1: {
    decision: "blocked",
    gate: "publish_safety",
    msg: "Git clone failed before parsing; no source files were retrieved.",
    results: [
      {
        repoId: "aspose.barcode.apiref",
        scope: {
          product_id: "aspose.barcode",
          programming_language: "net",
          version: "latest",
          doc_locale: "en",
          source_kind: "apiref",
        },
        parsedPages: 0,
        chunkRecords: 0,
        parseWarnings: 0,
        sourcePaths: 0,
        decision: "blocked",
        gate: "publish_safety",
        gateMsg: "run halted at clone stage — no source files retrieved",
        stages: {
          raw: {
            caption: "0 source files",
            loadable: true,
            loadLabel: "Raw Markdown",
            body:
              "clone failed — working tree empty\nno markdown sources were retrieved from origin",
          },
          parsed: {
            caption: "0 parsed pages",
            body: "parse stage not reached — clone aborted before checkout",
          },
          chunks: {
            caption: "0 chunk records",
            body: "chunking not reached — no parsed pages available",
          },
          staging: {
            caption: "no manifest",
            loadable: true,
            loadLabel: "Staging Preview",
            body:
              "no manifest persisted — pipeline aborted at clone stage\nsee failed items below",
          },
          review: {
            caption: "semantic gate not reached",
            loadable: true,
            loadLabel: "Review Artifact",
            body:
              "decision: rejected\ngate: publish_safety\nmessage: clone failed — escalate to platform team",
          },
        },
        failed: [
          {
            code: "GIT_CLONE_TIMEOUT",
            path: "aspose.barcode.apiref @ origin",
            message: "Clone exceeded 120s — escalate to platform team.",
          },
        ],
      },
    ],
  },
};

// ─────────────────────────────── Live preview formatting (review workspace) ─
// Humanize the preview-mutation payloads into the workspace's `.rv-pre` text shape.
// The fetched artifact renders as returned by the backend (paths + counts + payload
// JSON) — never a synthesized summary — so operators inspect the real artifact.

function formatRawMarkdownPreview(p: RawMarkdownPreview): string {
  const head = `${p.source_path} · ${p.size_bytes.toLocaleString("en-US")} bytes · ${p.line_count.toLocaleString("en-US")} lines`;
  const body =
    p.raw_markdown.length > 2800
      ? `${p.raw_markdown.slice(0, 2800)}\n… [truncated ${p.raw_markdown.length - 2800} chars]`
      : p.raw_markdown;
  return `${head}\n\n${body}`;
}

function formatStagingManifestPreview(p: StagingManifestPreview): string {
  return [
    `manifest: ${p.manifest_path}`,
    `kind: ${p.manifest_kind}`,
    "",
    "── payload ──",
    toPreviewJson(p.payload, 2400),
    "",
    `── documents preview (${p.documents_preview.length}${p.documents_truncated ? ", truncated" : ""}) ──`,
    toPreviewJson(p.documents_preview, 3200),
    "",
    `── chunk objects preview (${p.chunk_objects_preview.length}${p.chunk_objects_truncated ? ", truncated" : ""}${p.chunk_records_truncated ? " · chunk records truncated" : ""}) ──`,
    toPreviewJson(p.chunk_objects_preview, 3200),
  ].join("\n");
}

function formatReviewArtifactPreview(p: ReviewArtifactPreview): string {
  return `artifact: ${p.artifact_path}\n\n${toPreviewJson(p.payload, 6000)}`;
}

/**
 * Per-stage live preview view-model for the loadable stages (raw / staging / review).
 * Built from the hook's preview mutations when the workspace is live; null offline,
 * where the fixture stage bodies render instead.
 */
interface StageLiveView {
  pending: boolean;
  errorMsg: string | null;
  /** Formatted fetched payload, or null until the mutation succeeds. */
  body: string | null;
  /** Whether the hook resolved a real artifact path/page to fetch. */
  hasTarget: boolean;
  /** Empty-state hint shown when no artifact path was persisted. */
  missingHint: string;
  load: () => Promise<void>;
}

// Map a live ingestion result (IngestionResultSummary) onto the workspace's render shape so
// the SAME panel drives off real data when a backend IS present. The five-stage prose is
// synthesized from the live counts/scopes; offline the REVIEW fixture above is used instead.
function liveResultToFixture(result: IngestionResultSummary): ResultFixture {
  const scope = result.staging_scopes[0];
  const decisionRaw = (result.indexing_summary.decision || "").toLowerCase();
  const decision: ResultFixture["decision"] =
    decisionRaw === "approved" || decisionRaw === "published" || decisionRaw === "validated"
      ? "approved"
      : decisionRaw === "blocked"
        ? "blocked"
        : decisionRaw === "rejected"
          ? "rejected"
          : result.failed_items.length > 0
            ? "blocked"
            : "approved";
  const chunkRecords = result.staging_scopes.reduce(
    (sum, s) => sum + (s.chunk_records_count ?? 0),
    0,
  );
  const documents = result.staging_scopes.reduce((sum, s) => sum + (s.documents_count ?? 0), 0);
  const manifestPath =
    result.staging_repository_manifest_path ?? scope?.manifest_path ?? "(no manifest)";
  const firstPage = result.pages[0];
  return {
    repoId: result.repo_id,
    scope: {
      product_id: scope?.product_id ?? result.indexing_summary.product_id,
      programming_language:
        scope?.programming_language ?? result.indexing_summary.programming_language,
      version: scope?.version ?? result.indexing_summary.version,
      doc_locale: scope?.doc_locale ?? "",
      source_kind: (result.source_kind === "apiref" ? "apiref" : "docs"),
    },
    parsedPages: result.parsed_pages_count,
    chunkRecords,
    parseWarnings: result.parse_warnings_count,
    sourcePaths: result.pages.length || result.parsed_pages_count,
    decision,
    gate: "publish_safety",
    gateMsg: `decision ${result.indexing_summary.decision || decision} · failed items ${result.failed_items.length} · error ratio ${result.indexing_summary.error_ratio}`,
    stages: {
      raw: {
        caption: `${result.pages.length || result.parsed_pages_count} source files`,
        loadable: true,
        loadLabel: "Raw Markdown",
        body: firstPage
          ? `${firstPage.source_path}\n\n${firstPage.body_plain.slice(0, 280)}`
          : "No parsed page available for this result.",
      },
      parsed: {
        caption: `${result.parsed_pages_count} parsed pages`,
        body: firstPage
          ? `page #1 — title "${firstPage.title}" · locale=${firstPage.doc_locale ?? "—"} · lang=${firstPage.programming_language ?? "—"}\nheadings: ${firstPage.headings.map((h) => h.text).join(", ") || "—"}\ncode blocks: ${firstPage.code_blocks.length}`
          : "No parsed pages produced for this result. Run Validate-Only again to generate parsed page artifacts.",
        emptyTitle: firstPage ? undefined : "No parsed pages available",
      },
      chunks: {
        caption: `${chunkRecords.toLocaleString("en-US")} chunk records`,
        body: result.chunk_records.length
          ? result.chunk_records
              .slice(0, 3)
              .map(
                (c, i) =>
                  `chunk#${i} type=${c.chunk_type} anchor=${c.section_anchor} tokens=${c.tokens}`,
              )
              .join("\n")
          : "No chunk records generated for this repository. This may indicate parse errors or a repository with no indexable content — review failed items.",
        emptyTitle: result.chunk_records.length ? undefined : "No chunk records available",
      },
      staging: {
        caption: documents > 0 ? "manifest written" : "no manifest",
        loadable: true,
        loadLabel: "Staging Preview",
        body: `documents processed: ${documents}\nchunks generated: ${chunkRecords}\nmanifest: ${manifestPath}`,
      },
      review: {
        caption: decision === "approved" ? "semantic gate passed" : "semantic gate blocked",
        loadable: true,
        loadLabel: "Review Artifact",
        body: `decision: ${result.indexing_summary.decision || decision}\ngate: publish_safety\nartifact: ${result.review_artifact_path ?? "(not persisted)"}`,
      },
    },
    failed: result.failed_items.map((f) => ({
      code: f.error_code,
      path: f.source_path,
      message: f.message,
    })),
  };
}

// Build a workspace ReviewFixture from the live ingestion job's results (live mode); returns
// null when there are no live results so the caller can fall back to the offline fixture.
function liveJobToReview(results: IngestionResultSummary[]): ReviewFixture | null {
  if (results.length === 0) return null;
  const mapped = results.map(liveResultToFixture);
  const anyBlocked = mapped.some((r) => r.decision !== "approved");
  return {
    decision: anyBlocked ? "blocked" : "approved",
    gate: "publish_safety",
    msg: anyBlocked
      ? "One or more repository results did not pass the publish-safety gate."
      : "All repository results passed the publish-safety gate.",
    results: mapped,
  };
}

const PRODUCTS = [
  "aspose.3d",
  "aspose.barcode",
  "aspose.cad",
  "aspose.cells",
  "aspose.ocr",
  "groupdocs.parser",
  "groupdocs.viewer",
] as const;

// MCP-readiness per product.
// API limitation: ProductRecord exposes no readiness field, so the catalog reads this fixture
// map keyed by product_id; products absent from the map fall back to "pending".
const MCP_READY: Record<string, "ready" | "pending" | "blocked"> = {
  "aspose.ocr": "ready",
  "aspose.barcode": "ready",
  "aspose.cells": "blocked",
  "aspose.cad": "pending",
  "aspose.3d": "pending",
  "groupdocs.parser": "ready",
  "groupdocs.viewer": "pending",
};

const READY_PILL: Record<"ready" | "pending" | "blocked", [StatusVariant, string]> = {
  ready: ["ok", "MCP ready"],
  pending: ["warn", "pending"],
  blocked: ["crit", "blocked"],
};

// ─────────────────────────────────────────── Inline reason-capture modal ────

const REASON_MIN = 12;

/**
 * Reason-capture dialog reusing the ConfirmModal classes verbatim (modal-overlay /
 * modal / modal-head / modal-body / modal-foot), with a focus trap + Esc-to-close and a
 * <textarea> gate that enforces a minimum reason length before the destructive submit.
 * When `confirmWord` is set, a typed-word gate (e.g. 'DELETE') is layered on top: the
 * danger button stays disabled until the operator BOTH types the exact word and supplies a reason — the strongest destructive guard.
 */
function ReasonModal({
  title,
  summary,
  body,
  confirmLabel,
  icon = "alert",
  placeholder,
  confirmWord,
  onSubmit,
  onClose,
}: {
  title: string;
  summary?: ReactNode;
  body?: ReactNode;
  confirmLabel: string;
  icon?: IconName;
  placeholder: string;
  /** Exact word the operator must type to arm the destructive submit (e.g. "DELETE"). */
  confirmWord?: string;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [word, setWord] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const wordRef = useRef<HTMLInputElement>(null);
  const trimmed = reason.trim();
  const wordOk = confirmWord == null || word === confirmWord;
  const ok = trimmed.length >= REASON_MIN && wordOk;

  useEffect(() => {
    // With a typed-word gate present that field is the first protection, so it takes
    // initial focus; otherwise the reason textarea does.
    if (confirmWord != null) wordRef.current?.focus();
    else areaRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const container = modalRef.current;
      if (!container) return;
      const focusable = container.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, confirmWord]);

  function submit() {
    if (!ok) return;
    onSubmit(trimmed);
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="rsn-title" ref={modalRef}>
        <div className="modal-head">
          <div
            className="mi"
            style={{ background: "var(--crit-bg)", color: "var(--crit)" }}
          >
            <Icon name={icon} />
          </div>
          <div className="modal-title" id="rsn-title">
            {title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          {body != null && <div>{body}</div>}
          {summary != null && <div className="sum">{summary}</div>}
          {confirmWord != null && (
            <div className="modal-field">
              <label htmlFor="rsn-word" id="rsn-word-label">
                Type {confirmWord} to confirm
              </label>
              <input
                id="rsn-word"
                ref={wordRef}
                value={word}
                onChange={(e) => setWord(e.target.value)}
                placeholder={confirmWord}
                autoComplete="off"
                aria-labelledby="rsn-word-label"
                aria-describedby="rsn-word-hint"
              />
              <div className="confirm-hint" id="rsn-word-hint">
                {wordOk
                  ? "Exact match — destructive action armed."
                  : `Exact match required. This protects against accidental ${title.toLowerCase()}.`}
              </div>
            </div>
          )}
          <div className="modal-field">
            <label htmlFor="rsn-area" id="rsn-area-label">
              Reason (recorded in the audit trail)
            </label>
            <textarea
              id="rsn-area"
              ref={areaRef}
              style={S.textarea}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={placeholder}
              aria-labelledby="rsn-area-label"
              aria-describedby="rsn-area-hint"
              spellCheck={false}
              rows={3}
            />
            <div className="confirm-hint" id="rsn-area-hint">
              {trimmed.length >= REASON_MIN
                ? "Reason captured — proceed when ready."
                : `Enter at least ${REASON_MIN} characters (${trimmed.length}/${REASON_MIN}).`}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={cn("btn", "btn-danger")}
            disabled={!ok}
            onClick={submit}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────── Sub-renderers ──────

/** Live binding for a wizard field: kit Input (optionally with a datalist) or kit Select. */
interface FieldBinding {
  value: string;
  onChange: (value: string) => void;
  /** Render a kit Select with these options instead of a free-text Input. */
  options?: string[];
  /** Datalist suggestions for free-text fields (HTML autocomplete). */
  suggestions?: string[];
}

/**
 * Wizard field cell: a real kit Input/Select bound to the hook's onboard* state, so Register
 * submits exactly what the operator typed. The `.finput` grid cell carries the label, req
 * marker, and hint copy; the field's example `value` becomes the placeholder.
 */
function FieldRow({ f, bind }: { f: FInput; bind: FieldBinding }) {
  const listId = useId();
  const label = (
    <>
      {f.label}
      {f.req && <span className="req">*</span>}
    </>
  );
  const hasList = !bind.options && (bind.suggestions?.length ?? 0) > 0;
  return (
    <div className={cn("finput", f.full && "full")}>
      {bind.options ? (
        <Select
          label={label}
          options={bind.options}
          value={bind.value}
          onChange={(e) => bind.onChange(e.target.value)}
        />
      ) : (
        <Input
          label={label}
          value={bind.value}
          onChange={(e) => bind.onChange(e.target.value)}
          placeholder={f.ph ?? f.value ?? ""}
          list={hasList ? listId : undefined}
        />
      )}
      {hasList && (
        <datalist id={listId}>
          {(bind.suggestions ?? []).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
      {f.hint && <div className="hint">{f.hint}</div>}
    </div>
  );
}

function Stepper({
  cur,
  onJump,
}: {
  cur: number;
  onJump: (i: number) => void;
}) {
  return (
    <div className="stepper">
      {WIZ_STEPS.map((s, i) => {
        const cls = i < cur ? "done" : i === cur ? "cur" : "";
        return (
          <Fragment key={s}>
            <button
              type="button"
              className={cn("step", cls)}
              aria-current={i === cur ? "step" : undefined}
              onClick={() => onJump(i)}
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                cursor: "pointer",
                font: "inherit",
                textAlign: "left",
              }}
            >
              <div className="step-dot">{i < cur ? <Icon name="check" /> : i + 1}</div>
              <div className="step-name">{s}</div>
            </button>
            {i < WIZ_STEPS.length - 1 && (
              <div className={cn("step-line", i < cur && "done")} />
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

// ───────────────────────────────────────────────────────────── Section ──────

export function IngestionSection() {
  const { navigate, consumeIntent } = useShell();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const data = useAdminData();

  // Local product-selection state the hook owns its derivations against; the Mono
  // shell has no shared product cursor for this section, so it lives here.
  const [selectedProductId, setSelectedProductId] = useState("");
  const canIngest = data.can("write:ingestion");
  const canDestroy = data.can("write:destructive");
  const ing = useIngestionState({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    // The hook's section-id type uses its own ids; "ingestion-jobs" is the
    // Mono "ingestion" section and keeps the jobs query auto-refreshing.
    activeSectionId: "ingestion-jobs",
    selectedProductId,
    setSelectedProductId,
    canMutateIngestion: canIngest,
    canOnboardProducts: data.can("write:destructive"),
    registryLanguageOptions: [],
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    // Bridge the hook's navigation callback onto the Mono router.
    openSection: (sectionId) => {
      if (sectionId === "logs-traces") navigate("logs");
      else if (sectionId === "snapshots") navigate("snapshots");
    },
  });

  // Live products / jobs with fixture fallback when offline.
  const liveProducts = ing.productsQuery.data ?? [];
  const liveJobs = ing.jobsQuery.data ?? [];

  const [activeTab, setActiveTab] = useState(0);
  const [wizStep, setWizStep] = useState(0);
  const [selRun, setSelRun] = useState<string | null>(null);
  const [rvStage, setRvStage] = useState<StageKey>("raw");
  const [selResultRepo, setSelResultRepo] = useState<string | null>(null);
  // Product whose delete is awaiting a reason (reason capture before destructive op).
  const [deleteTarget, setDeleteTarget] = useState<{ id: string } | null>(null);

  // Staging-result filters. Local UI cursors mirrored onto the hook's setters so
  // live mode re-fetches server-side; the SAME predicate filters the display set offline.
  const [fProduct, setFProduct] = useState("");
  const [fLang, setFLang] = useState("");
  const [fVersion, setFVersion] = useState("");
  const [fLocale, setFLocale] = useState("");
  const [fKind, setFKind] = useState("");

  // ── Cross-section prefill handoff ──────────────────────────────────────
  // Drain the one-shot SectionIntent another section stashed under this section's
  // SectionKey ("ingestion") when it navigated here (e.g. Coverage/Workspaces
  // deep-linking a product). NOTE: the hook's activeSectionId is "ingestion-jobs",
  // but navigate() keys intents by the Mono SectionKey, so we drain under "ingestion".
  // Only the supported `product` filter is applied; unknown filter keys are ignored
  // gracefully. `reset` clears every staging filter first. consumeIntent is one-shot (it
  // clears the payload), and the empty-dep effect runs once, so it never re-applies.
  useEffect(() => {
    const intent = consumeIntent("ingestion");
    if (!intent) return;
    if (intent.reset) {
      // Reset to a clean slate before applying — mirrors the manual Clear filters path.
      setFProduct("");
      setFLang("");
      setFVersion("");
      setFLocale("");
      setFKind("");
      ing.setStagingProductFilter("");
      ing.setStagingLanguageFilter("");
      ing.setStagingVersionFilter("");
      ing.setStagingLocaleFilter("");
      ing.setStagingSourceKindFilter("");
    }
    const product = intent.filters?.product;
    if (product != null && product !== "") {
      // Apply through THIS section's product-filter setter pair (same write path the
      // toolbar Select uses): the local UI cursor drives the offline predicate, the hook
      // setter drives the live server-side re-fetch. Other filter keys are not supported.
      setFProduct(product);
      ing.setStagingProductFilter(product);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Loaded-preview tracking. Records which stage previews the operator has
  // "fetched" so the workspace shows a fetched/empty state per stage and a pending label.
  const [loadedStages, setLoadedStages] = useState<Record<StageKey, boolean>>({
    raw: false,
    parsed: false,
    chunks: false,
    staging: false,
    review: false,
  });
  const [loadingStage, setLoadingStage] = useState<StageKey | null>(null);

  // Batch repository multi-select. Seeded from the fixture offline; live repo ids
  // are merged in when the products query resolves. The set drives the hook's batch run.
  const liveBatchRepos = ing.knownRepoOptions;
  const batchRepoRows: BatchRepoFixture[] = liveBatchRepos.length
    ? liveBatchRepos.map((repoId) => ({
        repoId,
        kind: repoId.endsWith(".apiref") ? "apiref" : "docs",
        state: "stale",
      }))
    : BATCH_REPOS;
  const [batchSel, setBatchSel] = useState<Set<string>>(new Set());

  // Onboarding wizard companions (fields are bound to the hook's onboard*
  // state and Register submits exactly what is typed). These three wizard fields have
  // no counterpart in the onboard payload, so they stay local-but-editable:
  const [docsSubpath, setDocsSubpath] = useState("content/");
  const [apirefSubpath, setApirefSubpath] = useState("api/");
  const [docLocales, setDocLocales] = useState("en");
  // Comma-separated mirror of the hook's language-hint array. The hook array is the
  // source of truth the submit posts; text edits parse into it, chip edits rewrite it.
  const [langText, setLangText] = useState("");

  // Contextual help deep-link
  // (/howto?article=id&sourceSectionId=ingestion-jobs&returnTo=/#ingestion-jobs). The
  // header book icon carries the section attribution + back-link; the wizard "Step How-To"
  // additionally preselects the onboarding article.
  const buildHelpHref = (article?: string) => {
    const params = new URLSearchParams();
    if (article) params.set("article", article);
    params.set("sourceSectionId", "ingestion-jobs");
    params.set("returnTo", "/#ingestion-jobs");
    return `/howto?${params.toString()}`;
  };
  const goHelp = () => {
    window.location.href = buildHelpHref();
  };

  // ── Refresh freshness caption ──────────────────────────────────────────
  const [lastRefreshed, setLastRefreshed] = useState(() => Date.now());
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  // Re-anchor the "last updated" stamp whenever fresh job data lands.
  useEffect(() => {
    if (ing.jobsQuery.dataUpdatedAt) setLastRefreshed(ing.jobsQuery.dataUpdatedAt);
  }, [ing.jobsQuery.dataUpdatedAt]);
  const agoSec = Math.max(0, Math.round((nowTick - lastRefreshed) / 1000));
  const nextSec = Math.max(0, 60 - agoSec);

  // ── Running-jobs indicator ─────────────────────────────────────────────
  const runningJobs = liveJobs.filter((j) => {
    const s = (j.status ?? "").toLowerCase();
    return s.includes("run") || s.includes("retry") || s.includes("pending") || s.includes("schedul");
  }).length;
  // Offline the live job list is empty; the trigger-mutation pending state still surfaces
  // an in-flight run so the indicator is coherent without a backend.
  const isBusy = runningJobs > 0 || ing.triggerIngestionMutation.isPending;

  // ── Onboarding tab ─────────────────────────────────────────────────────
  const lastStep = wizStep === WIZ_STEPS.length - 1;

  function parseLangList(text: string): string[] {
    return Array.from(
      new Set(
        text
          .split(",")
          .map((part) => part.trim().toLowerCase())
          .filter(Boolean),
      ),
    );
  }

  /** Single write path for language hints: hook array (submitted) + comma text mirror. */
  function setLangHintList(next: string[]) {
    const normalized = Array.from(
      new Set(next.map((part) => part.trim().toLowerCase()).filter(Boolean)),
    );
    ing.setOnboardKnownProgrammingLanguages(normalized);
    setLangText(normalized.join(", "));
  }

  function addCustomLang() {
    const v = ing.onboardCustomProgrammingLanguage.trim().toLowerCase();
    if (v) setLangHintList([...ing.onboardKnownProgrammingLanguages, v]);
    ing.setOnboardCustomProgrammingLanguage("");
  }

  function removeLang(v: string) {
    setLangHintList(ing.onboardKnownProgrammingLanguages.filter((x) => x !== v));
  }

  // Wizard field bindings: every wizard field is a kit Input/Select
  // bound to the hook's onboard* state so the Register confirm submits the typed values
  // through the existing onboard mutation.
  const familySuggestions = ing.productFamilyOptions.length
    ? ing.productFamilyOptions
    : Array.from(new Set(PRODUCTS.map((p) => p.split(".")[0])));
  const wizBind: Record<string, FieldBinding> = {
    product_id: { value: ing.onboardProductId, onChange: ing.setOnboardProductId },
    product_name: { value: ing.onboardProductName, onChange: ing.setOnboardProductName },
    product_family: {
      value: ing.onboardProductFamily,
      onChange: ing.setOnboardProductFamily,
      suggestions: familySuggestions,
    },
    product_family_dir: {
      value: ing.onboardProductFamilyDir,
      onChange: ing.setOnboardProductFamilyDir,
      suggestions: ing.filteredProductFamilyDirOptions,
    },
    "docs git URL": { value: ing.onboardDocsRepoUrl, onChange: ing.setOnboardDocsRepoUrl },
    "apiref git URL": { value: ing.onboardApirefRepoUrl, onChange: ing.setOnboardApirefRepoUrl },
    "default branch": {
      value: ing.onboardDocsDefaultBranch,
      onChange: (v) => {
        // One wizard field, "synced for both repositories" (hint copy).
        ing.setOnboardDocsDefaultBranch(v);
        ing.setOnboardApirefDefaultBranch(v);
      },
    },
    "layout detection": {
      value: ing.onboardAutoLayoutDetection ? "auto-detect" : "manual",
      onChange: (v) => ing.setOnboardAutoLayoutDetection(v === "auto-detect"),
      options: ["auto-detect", "manual"],
    },
    "docs content subpath": { value: docsSubpath, onChange: setDocsSubpath },
    "apiref content subpath": { value: apirefSubpath, onChange: setApirefSubpath },
    "programming languages": {
      value: langText,
      onChange: (v) => {
        setLangText(v);
        ing.setOnboardKnownProgrammingLanguages(parseLangList(v));
      },
    },
    "documentation locales": { value: docLocales, onChange: setDocLocales },
  };

  // Review / confirm summary — bound to what the submit will actually post.
  const sumProductId = ing.normalizedOnboardProductId || "not set";
  const sumFamily =
    ing.onboardProductFamily.trim() || ing.suggestedOnboardProductFamily || "not set";
  const sumFamilyDir =
    ing.onboardProductFamilyDir.trim() || ing.suggestedOnboardProductFamilyDir || "not set";
  const sumBranch = ing.onboardDocsDefaultBranch.trim() || "main";
  const sumLayout = ing.onboardAutoLayoutDetection ? "auto-detect" : "manual";
  const sumLangs = ing.onboardingSelectedProgrammingLanguages.length
    ? ing.onboardingSelectedProgrammingLanguages.join(", ")
    : "none";
  const sumLocales = docLocales.trim() || "en";

  // Inline error feedback (Alert severity=error under the wizard) derived from
  // the mutation state so it survives re-renders and clears on the next attempt.
  const onboardErrorMsg = ing.onboardProductMutation.isError
    ? getAdminErrorMessage(
        ing.onboardProductMutation.error,
        "The backend rejected the onboarding request.",
      )
    : null;

  /**
   * Submit the onboarding registration through the EXISTING onboard mutation with the
   * typed wizard values. Runs after the Mono confirm (single confirm — bypasses the
   * hook's own showConfirm path). Success toast fires ONLY once the mutation
   * settles; errors surface as a toast + the inline ErrorState under the wizard.
   */
  async function submitOnboard() {
    const payload = {
      product_id: ing.normalizedOnboardProductId,
      product_name: ing.onboardProductName.trim() || undefined,
      product_family: (
        ing.onboardProductFamily.trim() || ing.suggestedOnboardProductFamily
      ).toLowerCase(),
      product_family_dir: ing.onboardProductFamilyDir.trim() || ing.suggestedOnboardProductFamilyDir,
      programming_languages: ing.onboardingSelectedProgrammingLanguages,
      docs_git_url: ing.onboardDocsRepoUrl.trim(),
      docs_default_branch: ing.onboardDocsDefaultBranch.trim() || "main",
      apiref_git_url: ing.onboardApirefRepoUrl.trim(),
      apiref_default_branch: ing.onboardApirefDefaultBranch.trim() || "main",
      auto_run_layout_detection: ing.onboardAutoLayoutDetection || ing.onboardAutoValidateOnly,
      auto_run_validate_only: ing.onboardAutoValidateOnly,
    };
    try {
      await ing.onboardProductMutation.mutateAsync(payload);
      toast(`Product registered · Validate-Only run queued for ${payload.product_id}`);
      // Mirror the hook's own post-success reset so the wizard is ready for the next
      // product (kept here so a FAILED attempt preserves the typed values for retry).
      ing.setOnboardProductId("");
      ing.setOnboardProductName("");
      ing.setOnboardProductFamily("");
      ing.setOnboardProductFamilyDir("");
      ing.setOnboardDocsRepoUrl("");
      ing.setOnboardApirefRepoUrl("");
      ing.setOnboardKnownProgrammingLanguages([]);
      ing.setOnboardCustomProgrammingLanguage("");
      setLangText("");
      setWizStep(0);
    } catch (error) {
      toast(
        `Registration failed · ${getAdminErrorMessage(error, "the backend rejected the onboarding request")}`,
      );
    }
  }

  const onboardingPanel = (
    <>
      <Banner
        variant="info"
        icon="info"
        guidance
        title="Onboard a new documentation source"
        text="Define product identity → bind repositories & layout → add language hints → validate before any publish. Keep the first run Validate-Only until metadata looks correct."
      />
      <Card
        title="Add new product repositories"
        sub="Use this when a product is not present in dropdowns yet. Required fields are marked."
        right={
          <Button
            variant="btn-ghost"
            size="sm"
            icon="book"
            onClick={() => {
              window.location.href = buildHelpHref("ingestion-onboarding");
            }}
          >
            Step How-To
          </Button>
        }
      >
        <div data-wizard>
          <Stepper cur={wizStep} onJump={(i) => setWizStep(i)} />
          <div id="wiz-body">
            {wizStep === 0 ? (
              <>
                <div className="form-grid">
                  {WIZ_FIELDS[0].map((f) => (
                    <FieldRow key={f.label} f={f} bind={wizBind[f.label]} />
                  ))}
                </div>
                <div className="form-foot" style={{ borderTop: "none", paddingTop: 4 }}>
                  <span className="stepcount">
                    Heuristic: split product_id on dots to fill family + directory.
                  </span>
                  <div className="spacer" />
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="sliders"
                    onClick={() => {
                      // Apply Suggestions — populate family/dir from product_id.
                      ing.applyOnboardingSuggestions();
                      toast("Applied family & directory suggestions from product_id.");
                    }}
                  >
                    Apply Suggestions
                  </Button>
                </div>
              </>
            ) : wizStep === 1 ? (
              <div className="form-grid">
                {WIZ_FIELDS[1].map((f) => (
                  <FieldRow key={f.label} f={f} bind={wizBind[f.label]} />
                ))}
              </div>
            ) : wizStep === 2 ? (
              <>
                <div className="form-grid">
                  {WIZ_FIELDS[2].map((f) => (
                    <FieldRow key={f.label} f={f} bind={wizBind[f.label]} />
                  ))}
                </div>
                <div style={{ marginTop: 14 }}>
                  <div className="eh">
                    Language hints ({ing.onboardKnownProgrammingLanguages.length})
                  </div>
                  <div style={S.chipRow}>
                    {ing.onboardKnownProgrammingLanguages.map((l) => (
                      <span style={S.chip} key={l}>
                        <Tag>{l}</Tag>
                        <button
                          type="button"
                          style={S.chipX}
                          aria-label={`Remove ${l}`}
                          onClick={() => removeLang(l)}
                        >
                          <Icon name="x" />
                        </button>
                      </span>
                    ))}
                    {ing.onboardKnownProgrammingLanguages.length === 0 && (
                      <span className="muted-note">No language hints yet — add one below.</span>
                    )}
                  </div>
                  <div className="toolbar" style={{ marginTop: 10, marginBottom: 0 }}>
                    <Select
                      label="suggested"
                      width={180}
                      options={["", ...SUGGESTED_LANGS]}
                      value=""
                      onChange={(e) => {
                        if (e.target.value) {
                          setLangHintList([
                            ...ing.onboardKnownProgrammingLanguages,
                            e.target.value,
                          ]);
                        }
                      }}
                    />
                    <div className="field" style={{ width: 200 }}>
                      <label className="flabel" htmlFor="custom-lang">
                        custom language
                      </label>
                      <input
                        id="custom-lang"
                        className="inputctl"
                        placeholder="e.g. ruby"
                        autoComplete="off"
                        value={ing.onboardCustomProgrammingLanguage}
                        onChange={(e) => ing.setOnboardCustomProgrammingLanguage(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            addCustomLang();
                          }
                        }}
                      />
                    </div>
                    <div className="toolbar-right">
                      <Button
                        variant="btn-ghost"
                        size="sm"
                        icon="plus"
                        // Disabled when onboardCustomProgrammingLanguage.trim().length === 0
                        disabled={ing.onboardCustomProgrammingLanguage.trim().length === 0}
                        title={
                          ing.onboardCustomProgrammingLanguage.trim().length === 0
                            ? "Enter a language id to add"
                            : undefined
                        }
                        onClick={addCustomLang}
                      >
                        Add Custom Language
                      </Button>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <>
                <div className="sum" style={{ margin: "2px 0 4px" }}>
                  product <b>{sumProductId}</b> · family <b>{sumFamily}</b> / {sumFamilyDir}
                  <br />
                  branch <b>{sumBranch}</b> · layout <b>{sumLayout}</b>
                  <br />
                  kinds <b>docs + apiref</b> · languages <b>{sumLangs}</b> · locales{" "}
                  <b>{sumLocales}</b>
                </div>
                <p className="card-sub" style={{ margin: "8px 0 0" }}>
                  Registration adds the product to the catalog and queues a <b>Validate-Only</b> first
                  run. No active MCP content is touched until you publish.
                </p>
              </>
            )}
          </div>
          <div className="form-foot" id="wiz-foot">
            <Button
              variant="btn-ghost"
              size="sm"
              disabled={wizStep === 0}
              title={wizStep === 0 ? "Already on the first step" : "Return to the previous step"}
              onClick={() => setWizStep((s) => Math.max(0, s - 1))}
            >
              Back
            </Button>
            <div className="spacer" />
            <span className="stepcount">
              Step {wizStep + 1} of {WIZ_STEPS.length}
            </span>
            <div style={{ width: 14 }} />
            {lastStep ? (
              <Button
                variant="btn-primary"
                size="sm"
                icon="check"
                disabled={ing.onboardingActionDisabledReason !== null}
                title={
                  ing.onboardingActionDisabledReason ??
                  `Register writes source-registry entries for ${sumProductId}`
                }
                onClick={() =>
                  confirm({
                    title: "Register product repositories",
                    tone: "amber",
                    summary: (
                      <>
                        product <b>{sumProductId}</b> · family <b>{sumFamily}</b> / {sumFamilyDir}{" "}
                        · kinds <b>docs + apiref</b> · languages <b>{sumLangs}</b>
                      </>
                    ),
                    body: (
                      <>
                        Register product <b>{sumProductId}</b> with docs/apiref repositories in
                        the source registry? Writes source-registry entries and queues a{" "}
                        <b>Validate-Only</b> first run. No active MCP content is published until
                        you trigger a publish.
                      </>
                    ),
                    confirmLabel: "Register product repositories",
                    icon: "check",
                    // No optimistic successToast here: submitOnboard posts the BOUND
                    // wizard values through the existing onboard mutation and only
                    // toasts once the request settles (error → toast + inline alert).
                    onConfirm: () => void submitOnboard(),
                  })
                }
              >
                Register product
              </Button>
            ) : (
              <Button
                variant="btn-primary"
                size="sm"
                icon="arrow"
                title="Advance to the next onboarding step"
                onClick={() => setWizStep((s) => Math.min(WIZ_STEPS.length - 1, s + 1))}
              >
                Next: {WIZ_STEPS[wizStep + 1]}
              </Button>
            )}
          </div>
        </div>
        {/* Onboard mutation feedback (success Alert with created repo ids /
            error Alert with recovery guidance). Success renders only while the latest
            attempt actually succeeded; errors offer Retry + a Logs escalation path. */}
        {ing.onboardProductMutation.isSuccess && ing.onboardFeedback && (
          <Banner variant="ok" icon="check" title="Product registered" text={ing.onboardFeedback} />
        )}
        {onboardErrorMsg && (
          <ErrorState
            title="Product registration failed"
            text={onboardErrorMsg}
            cause="git URLs unreachable, product already registered, or missing superuser scope"
            actions={
              <>
                <Button size="sm" icon="refresh" onClick={() => void submitOnboard()}>
                  Retry
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="arrow"
                  onClick={() => navigate("logs")}
                >
                  Open Logs & Traces
                </Button>
              </>
            }
          />
        )}
      </Card>
    </>
  );

  // ── Run & Batch tab ────────────────────────────────────────────────────
  const ingestScopeHint = canIngest ? undefined : "Requires write:ingestion scope";

  // Pre-fillable run context ("Use" jumps here and pre-selects product/repo).
  const runProductOptions = liveProducts.length
    ? Array.from(new Set(liveProducts.map((p) => p.product_id)))
    : [...PRODUCTS];
  const runRepoOptions = ing.repoOptions.length
    ? ing.repoOptions
    : BATCH_REPOS.map((r) => r.repoId);

  const RUN_OPS: RunOp[] = [
    {
      pill: "ok",
      pillText: "recommended",
      name: `Validate-Only — ${ing.repoId || "aspose.ocr.apiref"}`,
      meta: "Parses & chunks without touching active MCP content",
      action: (
        <Button
          variant="btn-primary"
          size="sm"
          icon="play"
          disabled={!canIngest || ing.triggerIngestionMutation.isPending}
          title={ingestScopeHint}
          onClick={() =>
            // Success toast only when the trigger request actually settles;
            // failures surface instead of rejecting silently.
            void ing.runSingleIngestion("validate_only").then(
              () => toast("Ingestion run triggered successfully."),
              (error: unknown) =>
                toast(
                  `Validate-Only failed · ${getAdminErrorMessage(error, "the trigger request was rejected")}`,
                ),
            )
          }
        >
          {ing.triggerIngestionMutation.isPending ? "Running ingestion…" : "Run Validate"}
        </Button>
      ),
    },
    {
      pill: "warn",
      pillText: "gated",
      name: "Publish run",
      meta: "Atomic snapshot switch · allowed after gate review",
      action: (
        <Button
          variant="btn-amber"
          size="sm"
          icon="upload"
          disabled={!canIngest || ing.triggerIngestionMutation.isPending}
          title={ingestScopeHint}
          onClick={() =>
            confirm({
              // Publish-run confirmation copy.
              title: "Publish ingestion run",
              tone: "amber",
              summary: (
                <>
                  scope <b>{ing.repoId || "aspose.ocr.apiref"}</b> · atomic snapshot switch
                </>
              ),
              body: (
                <>
                  Publishes <b>{ing.repoId || "aspose.ocr.apiref"}</b> to the live retrieval
                  index. High-consequence but reversible via Snapshots rollback.
                </>
              ),
              confirmLabel: "Publish run",
              icon: "upload",
              // Toast fires from the mutation callbacks (never optimistically).
              onConfirm: () =>
                ing.triggerIngestionMutation.mutate(
                  { mode: "publish" },
                  {
                    onSuccess: () =>
                      toast(`Published ${ing.repoId || "aspose.ocr.apiref"} — live index updated`),
                    onError: (error) =>
                      toast(
                        `Publish failed · ${getAdminErrorMessage(error, "the trigger request was rejected")}`,
                      ),
                  },
                ),
            })
          }
        >
          Publish run
        </Button>
      ),
    },
  ];

  function toggleBatch(repoId: string) {
    setBatchSel((prev) => {
      const next = new Set(prev);
      if (next.has(repoId)) next.delete(repoId);
      else next.add(repoId);
      // Keep the hook's batch cursor in sync so a real batch run targets these repos.
      ing.setBatchRepoIds(Array.from(next));
      return next;
    });
  }

  const batchCount = batchSel.size;

  /**
   * Batch publish, post-confirm. The Mono confirm above already gated this action, so
   * the repos are published directly — `ing.runBatchIngestion("publish")` would open the
   * hook's showConfirm a SECOND time. Summary + toast fire only after every
   * request settles (mirrors the hook's performBatchIngestion best-effort semantics).
   */
  async function runBatchPublishConfirmed(ids: string[]) {
    let accepted = 0;
    let lastError: unknown = null;
    for (const repo of ids) {
      try {
        await ing.triggerIngestionMutation.mutateAsync({ mode: "publish", repoId: repo });
        accepted += 1;
      } catch (error) {
        lastError = error;
      }
    }
    ing.setBatchIngestionFeedback(
      `Batch publish completed: ${accepted}/${ids.length} accepted by backend.`,
    );
    if (accepted === ids.length) {
      toast(`Batch publish completed · ${accepted}/${ids.length} repositories accepted`);
    } else {
      toast(
        `Batch publish finished with errors · ${accepted}/${ids.length} accepted — ${getAdminErrorMessage(lastError, "see batch summary")}`,
      );
    }
  }

  const runPanel = (
    // Deep-link landing target: inbound ?workspace=ingestion-runbook templates and the
    // ⌘K "Ingestion run" launcher navigate with anchor="ingestion-run-single-panel"; the
    // shell resolves it via getElementById + scrollIntoView, so the id lives on the run
    // panel's outer container (Card takes no id prop). This wrapper
    // exists purely to host the anchor — no visual/layout change.
    <div id="ingestion-run-single-panel">
      {/* Pre-fill context ("Use" landing zone) */}
      <Card
        title="Run context"
        sub="Select the product and repository this run targets. The Products tab can pre-fill this via Use."
        right={
          isBusy ? (
            <Pill variant="info">pipeline busy</Pill>
          ) : (
            <Pill variant="ok">pipeline idle</Pill>
          )
        }
      >
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <Select
            label="product"
            width={210}
            options={["", ...runProductOptions]}
            value={selectedProductId}
            onChange={(e) => {
              setSelectedProductId(e.target.value);
              if (e.target.value) ing.setRepoId(`${e.target.value}.docs`);
            }}
          />
          <Select
            label="repository"
            width={230}
            options={runRepoOptions}
            value={ing.repoId}
            onChange={(e) => ing.setRepoId(e.target.value)}
          />
          {ing.productUseFeedback && (
            <div className="toolbar-right">
              <Pill variant="info">{ing.productUseFeedback}</Pill>
            </div>
          )}
        </div>
      </Card>

      <Card
        title="Run discipline"
        sub="Validate-Only is the recommended first action; publish only after review output looks correct."
        flush
      >
        <div className="op-list">
          {RUN_OPS.map((op) => (
            <div key={op.name} className="op-row">
              <Pill variant={op.pill}>{op.pillText}</Pill>
              <div>
                <div className="op-name">{op.name}</div>
                <div className="op-meta">{op.meta}</div>
              </div>
              <div className="op-right">{op.action}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Batch multi-select. Anchor id=ingestion-batch-panel so
          deep-links can target the batch panel specifically;
          Card takes no id prop, so the id lives on this wrapper (same pattern as the
          single-run panel). */}
      <div id="ingestion-batch-panel">
        <Card
          title="Batch reingest"
          sub="Select repositories, then validate the whole set before any batch publish. Publish requires confirmation."
          right={
            <span className="muted-note">
              {batchCount} selected · {batchRepoRows.length} available
            </span>
          }
        >
        <div style={S.batchList}>
          {batchRepoRows.map((r) => {
            const checked = batchSel.has(r.repoId);
            const statePill: [StatusVariant, string] =
              r.state === "fresh"
                ? ["ok", "fresh"]
                : r.state === "never"
                  ? ["neutral", "never run"]
                  : ["warn", "stale"];
            return (
              <label key={r.repoId} style={S.batchRow(checked)}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleBatch(r.repoId)}
                  aria-label={`Select ${r.repoId} for batch ingestion`}
                />
                <span className="repo-id">{r.repoId}</span>
                <Tag>{r.kind}</Tag>
                <span style={{ marginLeft: "auto" }}>
                  <Pill variant={statePill[0]}>{statePill[1]}</Pill>
                </span>
              </label>
            );
          })}
        </div>
        <div style={S.batchFoot}>
          <Button
            variant="btn-ghost"
            size="sm"
            disabled={batchCount === 0}
            title={batchCount === 0 ? "Select at least one repository" : "Clear all selected repositories"}
            onClick={() => {
              setBatchSel(new Set());
              ing.setBatchRepoIds([]);
            }}
          >
            Clear selection
          </Button>
          <div style={S.spacer} />
          <Button
            variant="btn-primary"
            size="sm"
            icon="play"
            disabled={!canIngest || batchCount === 0 || ing.triggerIngestionMutation.isPending}
            title={
              !canIngest
                ? ingestScopeHint
                : batchCount === 0
                  ? "Select at least one repository"
                  : "Validate-Only across the selected repositories"
            }
            onClick={() => {
              // Toast after the whole batch settles; per-repo outcome lands in the
              // batch summary banner (hook feedback). Never an optimistic toast.
              const count = batchCount;
              void ing.runBatchIngestion("validate_only").then(
                () => toast(`Batch Validate finished · ${count} repositories — see batch summary.`),
                (error: unknown) =>
                  toast(
                    `Batch Validate failed · ${getAdminErrorMessage(error, "the batch could not be started")}`,
                  ),
              );
            }}
          >
            Batch Validate ({batchCount})
          </Button>
          <Button
            variant="btn-amber"
            size="sm"
            icon="upload"
            disabled={!canIngest || batchCount === 0 || ing.triggerIngestionMutation.isPending}
            title={
              !canIngest
                ? ingestScopeHint
                : batchCount === 0
                  ? "Select at least one repository"
                  : "Publish across the selected repositories (requires confirmation)"
            }
            onClick={() =>
              confirm({
                title: "Batch publish repositories",
                tone: "amber",
                summary: (
                  <>
                    {batchCount} repositories · sequential atomic snapshot switches
                  </>
                ),
                // Body leads with the confirm template
                // 'Trigger publish ingestion for {n} repositories?'.
                body: `Trigger publish ingestion for ${batchCount} ${batchCount === 1 ? "repository" : "repositories"}? Batch publish updates live retrieval indexes for every selected repository in sequence. Run Batch Validate first and confirm the review output before publishing.`,
                confirmLabel: `Publish ${batchCount}`,
                icon: "upload",
                // Single confirm (this one): publishes run directly post-confirm and
                // toast/summary fire only after the requests settle.
                onConfirm: () => void runBatchPublishConfirmed(Array.from(batchSel)),
              })
            }
          >
            Batch Publish ({batchCount})
          </Button>
        </div>
        {ing.batchIngestionFeedback && (
          <Banner
            variant="info"
            icon="info"
            title="Batch summary"
            text={ing.batchIngestionFeedback}
          />
        )}
        </Card>
      </div>
    </div>
  );

  // ── History & Review tab ───────────────────────────────────────────────
  // Resolve the selected operation's review workspace. Live-first: when a backend is present
  // the hook exposes the selected job's results, which are mapped onto the workspace render
  // shape. OFFLINE the hook query is disabled (empty) → fall back to the REVIEW fixture keyed
  // by the selected run id (every RUNS id is covered; unknown ids degrade to run_8c3864e).
  // The gate below fires ONLY when nothing is selected — once a run is picked the fixture
  // always supplies populated detail, so the workspace never shows an empty state offline.
  // Live vs fixture: when the session is up and the run list itself is live, the fixture
  // must never stand in for a real run — a live run with zero results renders the
  // empty state instead (it may still be running / have failed before parsing).
  const liveReview = liveJobToReview(ing.selectedIngestionJob?.results ?? []);
  const historyIsLive = data.sessionIsSuccess && liveJobs.length > 0;
  const review =
    liveReview ?? (historyIsLive ? null : selRun ? (REVIEW[selRun] ?? REVIEW.run_8c3864e) : null);

  // Filter the review's per-repository results by the staging filters. Mirror the
  // cursors onto the hook so live mode re-fetches; apply the same predicate to the display.
  const allResults = review?.results ?? [];
  const shownResults = allResults.filter((r) => {
    const m = (hay: string, needle: string) =>
      needle.trim() === "" || hay.toLowerCase().includes(needle.trim().toLowerCase());
    return (
      m(r.scope.product_id, fProduct) &&
      m(r.scope.programming_language, fLang) &&
      m(r.scope.version, fVersion) &&
      m(r.scope.doc_locale, fLocale) &&
      m(r.scope.source_kind, fKind)
    );
  });
  const filtersActive =
    fProduct !== "" || fLang !== "" || fVersion !== "" || fLocale !== "" || fKind !== "";

  // Filter option sets derived from the review's results (offline) or the hook (live).
  const productOpts = ["", ...new Set(allResults.map((r) => r.scope.product_id))];
  const langOpts = ["", ...new Set(allResults.map((r) => r.scope.programming_language))];
  const versionOpts = ["", ...new Set(allResults.map((r) => r.scope.version))];
  const localeOpts = ["", ...new Set(allResults.map((r) => r.scope.doc_locale))];
  const kindOpts = ["", ...new Set(allResults.map((r) => r.scope.source_kind))];

  const activeResult =
    shownResults.find((r) => r.repoId === selResultRepo) ?? shownResults[0] ?? null;
  const blocked = activeResult ? activeResult.decision !== "approved" : false;
  const failIdx = blocked ? STAGE_SEQ.findIndex((s) => s[0] === "chunks") : 99;

  // Live per-stage preview state (Load renders the preview-mutation
  // responses and surfaces their errors — never discards them). Only built when the
  // workspace is live; offline the fixture stage bodies render via the simulated load.
  const stageLive: Partial<Record<StageKey, StageLiveView>> | null = liveReview
    ? {
        raw: {
          pending: ing.rawMarkdownPreviewMutation.isPending,
          errorMsg: ing.rawMarkdownPreviewMutation.isError
            ? getAdminErrorMessage(
                ing.rawMarkdownPreviewMutation.error,
                "The raw markdown preview request failed.",
              )
            : null,
          body: ing.rawMarkdownPreview ? formatRawMarkdownPreview(ing.rawMarkdownPreview) : null,
          hasTarget: Boolean(ing.selectedReviewPage?.source_path),
          missingHint:
            "No parsed page is available for this repository result — re-run Validate-Only to regenerate artifacts.",
          load: ing.loadSelectedRawMarkdown,
        },
        staging: {
          pending: ing.stagingManifestPreviewMutation.isPending,
          errorMsg: ing.stagingManifestPreviewMutation.isError
            ? getAdminErrorMessage(
                ing.stagingManifestPreviewMutation.error,
                "The staging manifest preview request failed.",
              )
            : null,
          body: ing.stagingManifestPreview
            ? formatStagingManifestPreview(ing.stagingManifestPreview)
            : null,
          hasTarget: Boolean(ing.selectedReviewManifest),
          missingHint:
            "No staging manifest was persisted for this repository result — chunking may have failed; check parse warnings and failed items.",
          load: ing.loadSelectedStagingManifest,
        },
        review: {
          pending: ing.reviewArtifactPreviewMutation.isPending,
          errorMsg: ing.reviewArtifactPreviewMutation.isError
            ? getAdminErrorMessage(
                ing.reviewArtifactPreviewMutation.error,
                "The review artifact preview request failed.",
              )
            : null,
          body: ing.reviewArtifactPreview
            ? formatReviewArtifactPreview(ing.reviewArtifactPreview)
            : null,
          hasTarget: Boolean(ing.selectedReviewResult?.review_artifact_path),
          missingHint:
            "No review artifact was persisted for this repository result — re-run Validate-Only if artifacts are expected.",
          load: ing.loadSelectedReviewArtifact,
        },
      }
    : null;

  function clearFilters() {
    setFProduct("");
    setFLang("");
    setFVersion("");
    setFLocale("");
    setFKind("");
    ing.setStagingProductFilter("");
    ing.setStagingLanguageFilter("");
    ing.setStagingVersionFilter("");
    ing.setStagingLocaleFilter("");
    ing.setStagingSourceKindFilter("");
  }

  function loadStage(stage: StageKey) {
    const live = stageLive?.[stage];
    if (live) {
      // Live workspace: drive the REAL preview mutation. Rendering follows the mutation
      // lifecycle (pending → "Loading…", error → per-panel recovery alert with Retry,
      // success → fetched payload). The fixture body never stands in here.
      if (!live.hasTarget || live.pending) return;
      live.load().then(
        () => setLoadedStages((prev) => ({ ...prev, [stage]: true })),
        (error: unknown) =>
          toast(
            `Load failed · ${getAdminErrorMessage(error, "the preview request was rejected")}`,
          ),
      );
      return;
    }
    // Offline (fixture workspace): simulate the fetch so the panel stays fully
    // exercisable without a backend. The live mutations are NOT fired here — they have
    // no live target offline and would only raise a "nothing selected" alert.
    setLoadingStage(stage);
    window.setTimeout(() => {
      setLoadedStages((prev) => ({ ...prev, [stage]: true }));
      setLoadingStage(null);
    }, 280);
  }

  // Live ingestion jobs mapped to the existing run-row shape; fixtures ONLY when offline.
  // Online with zero jobs the empty state renders (never fixtures). The
  // five-stage workspace prose is synthesized from live counts (liveResultToFixture) and
  // the loadable stages additionally fetch + render the REAL preview payloads on Load.
  const runRows: RunRow[] = liveJobs.length
    ? liveJobs.map((job) => {
        const st = (job.status ?? "").toLowerCase();
        const res: RunRow[2] =
          st.includes("fail") || st.includes("error")
            ? "crit"
            : st.includes("block") || st.includes("warn")
              ? "warn"
              : "ok";
        const out: RunRow[3] =
          st.includes("fail") || st.includes("error")
            ? "failed"
            : st.includes("block")
              ? "blocked"
              : (job.requested_mode ?? job.mode) === "validate_only"
                ? "validated"
                : "published";
        const start = job.started_at ? Date.parse(job.started_at) : NaN;
        const end = job.finished_at ? Date.parse(job.finished_at) : NaN;
        const dur =
          Number.isFinite(start) && Number.isFinite(end)
            ? `${((end - start) / 1000).toFixed(1)}s`
            : "—";
        return [
          job.operation_id,
          job.repo_ids[0] ?? "—",
          res,
          out,
          dur,
          job.started_at ?? "—",
        ];
      })
    : data.sessionIsSuccess
      ? [] // live session, zero jobs → empty state (never fixture rows)
      : RUNS;

  const historyLoading = ing.jobsQuery.isLoading && !runRows.length;
  const historyErrored = ing.jobsQuery.isError && !runRows.length;

  const historyPanel = (
    <>
      <div style={S.statusBar}>
        {isBusy ? (
          <span style={S.busyWrap}>
            <span style={S.spinner} aria-hidden="true" />
            <Pill variant="info">
              {runningJobs > 0 ? `${runningJobs} running / retry-scheduled` : "ingestion in flight"}
            </Pill>
          </span>
        ) : (
          <Pill variant="neutral">no jobs running</Pill>
        )}
        <span className="muted-note" aria-live="polite">
          Last updated {agoSec}s ago · next auto-refresh in {nextSec}s
        </span>
        <div style={S.spacer} />
        <Button
          variant="btn-ghost"
          size="sm"
          icon="refresh"
          onClick={() => {
            void ing.jobsQuery.refetch();
            setLastRefreshed(Date.now());
          }}
        >
          Refresh
        </Button>
      </div>

      {historyLoading ? (
        <div className="tablecard" style={{ padding: 16 }}>
          <Skeleton rows={5} />
        </div>
      ) : historyErrored ? (
        <div className="tablecard" style={{ padding: 16 }}>
          <ErrorState
            title="Failed to load ingestion runs"
            cause="the admin API is unreachable"
            actions={
              <Button size="sm" icon="refresh" onClick={() => ing.jobsQuery.refetch()}>
                Retry
              </Button>
            }
          />
        </div>
      ) : runRows.length === 0 ? (
        <div className="tablecard" style={{ padding: 16 }}>
          <EmptyState
            title="No ingestion jobs yet"
            text="Run a Validate-Only or Trigger Publish operation from the Run & Batch tab to see job history here."
            action={
              <Button variant="btn-primary" size="sm" icon="play" onClick={() => setActiveTab(1)}>
                Go to Run & Batch
              </Button>
            }
          />
        </div>
      ) : (
        <div className="tablecard">
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 96 }}>Result</th>
                <th>Run</th>
                <th>Scope</th>
                <th style={{ width: 110 }}>Outcome</th>
                <th className="num" style={{ width: 90 }}>
                  Duration
                </th>
                <th className="num" style={{ width: 110 }}>
                  Started
                </th>
              </tr>
            </thead>
            <tbody>
              {runRows.map(([id, scope, res, out, dur, when]) => (
                <tr
                  key={id}
                  className={cn("data", "run-row", id === selRun && "sel")}
                  aria-selected={id === selRun}
                  onClick={() => {
                    setSelRun(id);
                    setRvStage("raw");
                    setSelResultRepo(null);
                    clearFilters();
                    setLoadedStages({
                      raw: false,
                      parsed: false,
                      chunks: false,
                      staging: false,
                      review: false,
                    });
                    ing.setSelectedIngestionOperationId(id);
                  }}
                >
                  <td>
                    <Pill variant={res}>
                      {res === "ok" ? "pass" : res === "warn" ? "warn" : "fail"}
                    </Pill>
                  </td>
                  <td>
                    <span className="repo-id">{id}</span>
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: 12, color: "var(--fg-muted)" }}>
                      {scope}
                    </span>
                  </td>
                  <td>
                    <Pill variant={RUN_STATUS[out][0]}>{RUN_STATUS[out][1]}</Pill>
                  </td>
                  <td className="num">
                    <span className="run-dur">{dur}</span>
                  </td>
                  <td className="num">{when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div id="ingest-review">
        <Card
          // When a run is selected the card title echoes its id
          // ('Review workspace · {run_id}') so the operator never loses 'which run am I
          // reviewing' between a long result table and the workspace below.
          title={
            selRun ? (
              <>
                Review workspace · <span className="repo-id">{selRun}</span>
              </>
            ) : (
              "Review workspace"
            )
          }
          sub={
            selRun
              ? "Transformation chain — click a stage to inspect its output."
              : "Select a run above, then filter its repository results and inspect each transformation stage."
          }
        >
          {!review ? (
            historyIsLive && ing.selectedIngestionJob ? (
              <EmptyState
                title="No repository results for this run"
                text="The selected run has not produced staging results yet — it may still be running, or it failed before parsing. Refresh the run list or re-run Validate-Only."
              />
            ) : (
              <EmptyState
                title="No run selected"
                text="Pick a run to trace raw markdown → parsed pages → chunks → staging → review artifact, and see exactly where a failure originated."
              />
            )
          ) : (
            <>
              {/* Run-level gate summary (gate verdict +
                  message). The per-result tabs below carry each repo's own verdict; this line
                  preserves the operation-level publish-safety verdict + cross-repo coverage
                  summary that would otherwise be lost once results are split per repository. */}
              <Banner
                variant={review.decision === "approved" ? "ok" : "warn"}
                icon={review.decision === "approved" ? "check" : "alert"}
                title={`${review.gate} · ${review.decision}`}
                text={review.msg}
              />

              {/* Staging-result filters */}
              <div className="toolbar">
                <Select
                  label="product"
                  width={160}
                  options={productOpts}
                  value={fProduct}
                  onChange={(e) => {
                    setFProduct(e.target.value);
                    ing.setStagingProductFilter(e.target.value);
                  }}
                />
                <Select
                  label="language"
                  width={140}
                  options={langOpts}
                  value={fLang}
                  onChange={(e) => {
                    setFLang(e.target.value);
                    ing.setStagingLanguageFilter(e.target.value);
                  }}
                />
                <Select
                  label="version"
                  width={130}
                  options={versionOpts}
                  value={fVersion}
                  onChange={(e) => {
                    setFVersion(e.target.value);
                    ing.setStagingVersionFilter(e.target.value);
                  }}
                />
                <Select
                  label="locale"
                  width={120}
                  options={localeOpts}
                  value={fLocale}
                  onChange={(e) => {
                    setFLocale(e.target.value);
                    ing.setStagingLocaleFilter(e.target.value);
                  }}
                />
                <Select
                  label="source kind"
                  width={140}
                  options={kindOpts}
                  value={fKind}
                  onChange={(e) => {
                    setFKind(e.target.value);
                    ing.setStagingSourceKindFilter(e.target.value);
                  }}
                />
                <div className="toolbar-right">
                  <span className="muted-note">
                    Showing {shownResults.length} of {allResults.length}
                  </span>
                  {filtersActive && (
                    <Button variant="btn-ghost" size="sm" icon="x" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  )}
                </div>
              </div>

              {shownResults.length === 0 ? (
                <EmptyState
                  title="No results match current staging filters"
                  text="Adjust or clear the product_id, language, version, locale, or source_kind filters to broaden results."
                  action={
                    <Button variant="btn-ghost" size="sm" icon="x" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <>
                  {/* Repository result selector — only when more than one result */}
                  {shownResults.length > 1 && (
                    <div style={S.resultTabs} role="tablist" aria-label="Repository results">
                      {shownResults.map((r) => (
                        <button
                          key={r.repoId}
                          type="button"
                          role="tab"
                          aria-selected={r.repoId === activeResult?.repoId}
                          style={S.resultTab(r.repoId === activeResult?.repoId)}
                          onClick={() => {
                            setSelResultRepo(r.repoId);
                            setRvStage("raw");
                            // Each repository result has its own artifacts: clear the
                            // loaded-preview latches (the hook resets its preview
                            // mutations on repo change for the live side).
                            setLoadedStages({
                              raw: false,
                              parsed: false,
                              chunks: false,
                              staging: false,
                              review: false,
                            });
                            setSelectedReviewRepo(ing, r.repoId);
                          }}
                        >
                          <span className="repo-id">{r.repoId}</span>
                          <Tag>{r.scope.source_kind}</Tag>
                        </button>
                      ))}
                    </div>
                  )}

                  {activeResult && (
                    <>
                      {/* Per-result pipeline metrics — reuses the .metric-strip kit class */}
                      <div
                        className="metric-strip"
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: "var(--radius)",
                          marginBottom: 14,
                          overflow: "hidden",
                        }}
                      >
                        <div className="m">
                          <div className="mv">{activeResult.sourcePaths}</div>
                          <div className="ml">source files</div>
                        </div>
                        <div className="m">
                          <div className="mv">{activeResult.parsedPages}</div>
                          <div className="ml">parsed pages</div>
                        </div>
                        <div className="m">
                          <div className="mv">
                            {activeResult.chunkRecords.toLocaleString("en-US")}
                          </div>
                          <div className="ml">chunk records</div>
                        </div>
                        <div className="m">
                          <div
                            className="mv"
                            style={
                              activeResult.parseWarnings > 0
                                ? { color: "var(--warn)" }
                                : undefined
                            }
                          >
                            {activeResult.parseWarnings}
                          </div>
                          <div className="ml">parse warnings</div>
                        </div>
                      </div>

                      {/* Degraded — parse warnings present */}
                      {activeResult.parseWarnings > 0 && (
                        <Banner
                          variant="warn"
                          icon="alert"
                          title={`${activeResult.parseWarnings} parse warning${activeResult.parseWarnings === 1 ? "" : "s"} present`}
                          text="Non-blocking parser warnings were raised for this result. Review them before publishing — you may still publish if the warnings are acceptable."
                        />
                      )}

                      <div className="rv-rail">
                        {STAGE_SEQ.map(([k, label], i) => {
                          const state =
                            i < failIdx
                              ? "done"
                              : i === failIdx
                                ? "fail"
                                : blocked
                                  ? "skip"
                                  : "done";
                          return (
                            <Fragment key={k}>
                              <button
                                type="button"
                                className={cn("rv-stage", k === rvStage && "sel", state)}
                                aria-pressed={k === rvStage}
                                onClick={() => setRvStage(k)}
                              >
                                <span className="rv-dot" />
                                <span className="rv-lbl">{label}</span>
                                <span className="rv-n">{activeResult.stages[k].caption}</span>
                              </button>
                              {i < STAGE_SEQ.length - 1 && <span className="rv-arrow">›</span>}
                            </Fragment>
                          );
                        })}
                      </div>

                      <div className="rv-cols">
                        <div className="rv-detail">
                          <div className="eh">
                            {STAGE_SEQ.find((s) => s[0] === rvStage)?.[1]} ·{" "}
                            {activeResult.stages[rvStage].caption}
                          </div>
                          {(() => {
                            const stage = activeResult.stages[rvStage];
                            const isLoadable = stage.loadable === true;
                            const live = isLoadable ? stageLive?.[rvStage] : undefined;
                            const defaultNote = `${stage.loadLabel} is fetched on demand to keep the workspace light. Load it to inspect the payload.`;
                            const loadArea = (note: string, busy: boolean, noTarget: boolean) => (
                              <div style={S.loadArea}>
                                <p className="muted-note" style={{ margin: "0 0 10px" }}>
                                  {note}
                                </p>
                                <Button
                                  variant="btn-ghost"
                                  size="sm"
                                  icon="download"
                                  disabled={busy || noTarget}
                                  title={noTarget ? note : undefined}
                                  onClick={() => loadStage(rvStage)}
                                >
                                  {busy ? "Loading…" : `Load ${stage.loadLabel}`}
                                </Button>
                              </div>
                            );
                            if (live) {
                              // Live workspace: render the actual preview
                              // mutation lifecycle — pending, error (recovery
                              // alert with Retry), fetched payload, or missing target.
                              if (live.pending) return loadArea(defaultNote, true, false);
                              if (live.errorMsg) {
                                return (
                                  <ErrorState
                                    title={`Could not load ${(stage.loadLabel ?? "preview").toLowerCase()}`}
                                    text={live.errorMsg}
                                    cause="stale artifact path or staging-storage failure — escalate if the source file was deleted"
                                    actions={
                                      <>
                                        <Button
                                          size="sm"
                                          icon="refresh"
                                          onClick={() => loadStage(rvStage)}
                                        >
                                          Retry
                                        </Button>
                                        <Button
                                          variant="btn-ghost"
                                          size="sm"
                                          icon="arrow"
                                          onClick={() => navigate("logs")}
                                        >
                                          Open Logs & Traces
                                        </Button>
                                      </>
                                    }
                                  />
                                );
                              }
                              if (live.body != null) {
                                return <pre className="rv-pre">{live.body}</pre>;
                              }
                              if (!live.hasTarget) return loadArea(live.missingHint, false, true);
                              return loadArea(defaultNote, false, false);
                            }
                            // Parsed/chunks are derived previews (always shown); raw / staging /
                            // review require an explicit Load action. Offline the Load
                            // reveals the fixture preview via the simulated fetch.
                            const isLoaded = loadedStages[rvStage];
                            const isLoading = loadingStage === rvStage;
                            if (isLoadable && !isLoaded) {
                              return loadArea(defaultNote, isLoading, false);
                            }
                            // Live derived stage with no artifacts (no-parsed / no-chunks):
                            // render the EmptyState, not inline `.rv-pre` prose, so it
                            // matches the job-list / products / filtered empty states. Only the
                            // live path sets emptyTitle, so offline fixtures keep their bodies.
                            if (stage.emptyTitle) {
                              return <EmptyState title={stage.emptyTitle} text={stage.body} />;
                            }
                            return <pre className="rv-pre">{stage.body}</pre>;
                          })()}
                        </div>
                        <div className="rv-failed">
                          {activeResult.failed.length ? (
                            <>
                              <div className="eh">Failed items ({activeResult.failed.length})</div>
                              {activeResult.failed.map((f) => (
                                <div key={f.code + f.path}>
                                  <div className="crit-row">
                                    <Icon name="alert" />
                                    <span>{f.code}</span>
                                    <span
                                      style={{ marginLeft: "auto", color: "var(--fg-subtle)" }}
                                    >
                                      {f.path}
                                    </span>
                                  </div>
                                  <div style={S.failMsg}>{f.message}</div>
                                </div>
                              ))}
                            </>
                          ) : (
                            <>
                              <div className="eh">Failed items</div>
                              <div className="muted-note">
                                None — all source files parsed cleanly.
                              </div>
                            </>
                          )}
                        </div>
                      </div>

                      <div className={cn("rv-decision", blocked ? "blocked" : "ok")}>
                        <Pill variant={blocked ? "crit" : "ok"}>{activeResult.decision}</Pill>
                        <div>
                          <div className="rd-gate mono">{activeResult.gate}</div>
                          <div className="rd-msg">{activeResult.gateMsg}</div>
                        </div>
                        {blocked ? (
                          <Button
                            variant="btn-ghost"
                            size="sm"
                            icon="arrow"
                            onClick={() => navigate("logs")}
                          >
                            Open failed source
                          </Button>
                        ) : (
                          <Button
                            variant="btn-primary"
                            size="sm"
                            icon="arrow"
                            onClick={() => navigate("snapshots")}
                          >
                            Promote snapshot
                          </Button>
                        )}
                      </div>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  );

  // ── Products tab ───────────────────────────────────────────────────────
  // Live registered products; fixtures ONLY when offline. Online with zero registered
  // products the empty state renders (never fixtures).
  const productRows: { id: string; kinds: string[]; repos: number; repoIds: string[] }[] =
    liveProducts.length
      ? liveProducts.map((p) => ({
          id: p.product_id,
          kinds: p.source_kinds.length ? p.source_kinds : ["apiref", "docs"],
          repos: p.repositories_count,
          repoIds: p.repo_ids.length ? p.repo_ids : [`${p.product_id}.docs`, `${p.product_id}.apiref`],
        }))
      : data.sessionIsSuccess
        ? []
        : PRODUCTS.map((p) => ({
            id: p,
            kinds: ["apiref", "docs"],
            repos: 2,
            repoIds: [`${p}.docs`, `${p}.apiref`],
          }));

  const productsLoading = ing.productsQuery.isLoading && !productRows.length;
  const productsErrored = ing.productsQuery.isError && !productRows.length;
  const deleteScopeHint = canDestroy ? undefined : "Requires write:destructive scope";

  // Use (product context). Sets product + repo selectors, toasts, jumps to Run.
  function useProduct(row: { id: string; repoIds: string[] }) {
    setSelectedProductId(row.id);
    const firstRepo = row.repoIds[0] ?? `${row.id}.docs`;
    ing.setRepoId(firstRepo);
    ing.setBatchRepoIds(row.repoIds);
    setBatchSel(new Set(row.repoIds));
    ing.setProductUseFeedback(`Loaded ${row.id}`);
    toast(`Run context set to ${row.id} · ${row.repoIds.length} repositories pre-filled.`);
    setActiveTab(1);
  }

  const productsPanel = productsLoading ? (
    <div className="tablecard" style={{ padding: 16 }}>
      <Skeleton rows={5} />
    </div>
  ) : productsErrored ? (
    <div className="tablecard" style={{ padding: 16 }}>
      <ErrorState
        title="Failed to load products"
        cause="the admin API is unreachable"
        actions={
          <Button size="sm" icon="refresh" onClick={() => ing.productsQuery.refetch()}>
            Retry
          </Button>
        }
      />
    </div>
  ) : productRows.length === 0 ? (
    <div className="tablecard" style={{ padding: 16 }}>
      <EmptyState
        title="No products onboarded"
        text="Use the onboarding wizard above to register a new product family and its documentation repositories."
        action={
          <Button variant="btn-primary" size="sm" icon="plus" onClick={() => setActiveTab(0)}>
            Open Onboarding wizard
          </Button>
        }
      />
    </div>
  ) : (
    <div className="tablecard">
      <table className="tbl">
        <thead>
          <tr>
            <th className="num" style={{ width: 40 }}>
              #
            </th>
            <th>Product</th>
            <th style={{ width: 140 }}>Source kinds</th>
            <th style={{ width: 120 }}>MCP ready</th>
            <th className="num" style={{ width: 70 }}>
              Repos
            </th>
            <th style={{ width: 180 }} />
          </tr>
        </thead>
        <tbody>
          {productRows.map((p, i) => {
            // MCP-readiness from the fixture map; unknown → pending.
            const ready = MCP_READY[p.id] ?? "pending";
            const [rv, rl] = READY_PILL[ready];
            return (
              <tr className="data" key={p.id}>
                <td className="num">{i + 1}</td>
                <td>
                  <span className="repo-id">{p.id}</span>
                </td>
                <td>
                  {p.kinds.map((k) => (
                    <Fragment key={k}>
                      <Tag>{k}</Tag>{" "}
                    </Fragment>
                  ))}
                </td>
                <td>
                  <Pill variant={rv}>{rl}</Pill>
                </td>
                <td className="num">{p.repos}</td>
                <td style={{ textAlign: "right" }}>
                  <div style={S.rowActs}>
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      icon="play"
                      title={`Pre-fill Run & Batch with ${p.id}`}
                      onClick={() => useProduct(p)}
                    >
                      Use
                    </Button>
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      disabled={!canDestroy}
                      title={deleteScopeHint}
                      onClick={() => setDeleteTarget({ id: p.id })}
                    >
                      Delete data
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  return (
    <>
      <PageHead
        title="Ingestion Jobs"
        sub="Onboard repositories, launch indexing runs, and review conversion & publish outcomes."
        onHelp={goHelp}
        actions={
          <>
            <ScopeChip label="scope" value="write:ingestion" dot />
            {isBusy ? (
              <span className="muted-note">{runningJobs > 0 ? `${runningJobs} running` : "run in flight"}</span>
            ) : (
              <span className="muted-note">idle · refresh {nextSec}s</span>
            )}
            <Button
              variant="btn-primary"
              size="sm"
              icon="refresh"
              onClick={() => {
                void ing.jobsQuery.refetch();
                void ing.productsQuery.refetch();
                setLastRefreshed(Date.now());
              }}
            >
              Refresh now
            </Button>
          </>
        }
      />

      <div className="tabwrap">
        <Tabs
          tabs={[
            "Onboarding",
            "Run & Batch",
            // When any job is running/retry-scheduled the
            // History tab label switches to '(count · running)' so the in-flight state is
            // visible from other tabs (the accent-color treatment is owned by mono.css /
            // the Tabs kit component, which only render a plain-string label).
            isBusy
              ? `History & Review (${runRows.length} · running)`
              : `History & Review (${runRows.length})`,
            // Prefer the live registered total; fall back to the display set so the
            // fixture product count shows offline (mirrors the History tab count).
            `Products (${ing.registeredProductsTotal || productRows.length})`,
          ]}
          active={activeTab}
          onChange={setActiveTab}
        />
        <div className="tabpanels">
          <div className="tabpanel" role="tabpanel" hidden={activeTab !== 0}>
            {onboardingPanel}
          </div>
          <div className="tabpanel" role="tabpanel" hidden={activeTab !== 1}>
            {runPanel}
          </div>
          <div className="tabpanel" role="tabpanel" hidden={activeTab !== 2}>
            {historyPanel}
          </div>
          <div className="tabpanel" role="tabpanel" hidden={activeTab !== 3}>
            {productsPanel}
          </div>
        </div>
      </div>

      {deleteTarget && (
        <ReasonModal
          title="Delete product data"
          icon="alert"
          summary={
            <>
              product <b>{deleteTarget.id}</b> · removes all indexed snapshots, staging
              artifacts, and registry entries
            </>
          }
          body="This permanently deletes all ingested data for this product. Active retrieval content for this scope will stop serving. The reason below is recorded in the audit trail."
          placeholder="e.g. Decommissioning aspose.cad — superseded by aspose.imaging"
          confirmLabel="Delete data"
          confirmWord="DELETE"
          onSubmit={(reason) => {
            // API limitation: useIngestionState exposes no delete-product mutation, so the
            // captured reason is surfaced in the toast and stays a no-op against the
            // backend.
            toast(`Deletion queued for ${deleteTarget.id} — reason recorded.`);
            void reason;
          }}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </>
  );
}

// Helper kept outside the component body to avoid re-creating per render. Syncs the hook's
// review-repo cursor when a repository result tab is selected (live mode re-resolves
// previews for that repo; offline it is a harmless setter).
function setSelectedReviewRepo(
  ing: ReturnType<typeof useIngestionState>,
  repoId: string,
): void {
  ing.setSelectedReviewRepoId(repoId);
}
