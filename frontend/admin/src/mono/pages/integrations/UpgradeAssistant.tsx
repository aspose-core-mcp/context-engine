"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  AdminApiError,
  fetchPublicBreakingChanges,
  fetchPublicLatestReleaseFeatures,
  fetchPublicReleaseAdoption,
  fetchPublicReleaseFreshness,
} from "@/lib/admin-api";
import type {
  PublicBreakingChangesResponse,
  PublicLatestReleaseFeaturesResponse,
} from "@/lib/admin-api";

import { Pill } from "../../components/Pill";
import { Tag } from "../../components/Tag";
import { cn } from "../../lib/cn";
import type { StatusVariant } from "../../lib/types";

/* ----------------------------------------------------------------------------
 * Release Upgrade Assistant — standalone public Mono section.
 *
 * Builds a public-safe upgrade brief for one SDK language + version jump by
 * combining latest release features (`/v1/releases:latest`) and breaking-change
 * evidence (`/v1/changes:list`) — both PUBLIC endpoints, no auth.
 *
 * Data flow: a single useQuery whose queryFn runs BOTH fetchPublic* calls in
 * parallel (Promise.all). Enabled once the operator submits product + language +
 * from + to versions (Build upgrade plan).
 *   - live success            → render the combined plan
 *   - live error / no backend  → designed error notice (Retry) + in-file fixture
 *                                so the plan is fully reviewable offline.
 *   - not yet submitted        → designed "idle" prompt to build a plan; the
 *                                fixture plan is shown so the layout is reviewable.
 *
 * Styling: only mono.css `.pub` scope + kit Pill/Tag + tokens.
 * -------------------------------------------------------------------------- */

const THEME_KEY = "adcs_theme";

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

const DEFAULT_PRODUCT = "aspose.ocr";
const DEFAULT_LANGUAGE = "net";
const DEFAULT_FROM = "24.12";
const DEFAULT_TO = "25.1";

interface UpgradePlanScope {
  product_id: string;
  language: string;
  from_version: string;
  to_version: string;
}

interface UpgradePlan {
  scope: UpgradePlanScope;
  latestRelease: PublicLatestReleaseFeaturesResponse;
  breakingChanges: PublicBreakingChangesResponse;
}

/* ---------------- offline fixture (shape-complete) ---------------- */

const FIXTURE_LATEST: PublicLatestReleaseFeaturesResponse = {
  product_id: DEFAULT_PRODUCT,
  language: DEFAULT_LANGUAGE,
  resolved_version: DEFAULT_TO,
  items: [
    {
      kind: "feature",
      summary: "Added structured table-recognition output with cell bounding boxes.",
      symbol_fqn: "Aspose.OCR.OcrEngine.RecognizeTable",
      version: DEFAULT_TO,
      source_kind: "apiref",
      citation: {
        canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/ocrengine/recognizetable/",
        section_anchor: "#recognizetable",
      },
    },
    {
      kind: "improvement",
      summary: "Improved multi-language detection accuracy for mixed-script documents.",
      symbol_fqn: "Aspose.OCR.RecognitionSettings.Language",
      version: DEFAULT_TO,
      source_kind: "docs",
      citation: {
        canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings/",
        section_anchor: "#language",
      },
    },
  ],
  guardrails: [],
};

const FIXTURE_BREAKING: PublicBreakingChangesResponse = {
  items: [
    {
      type: "signature_change",
      symbol_fqn: "Aspose.OCR.RecognitionSettings.Language",
      from_version: DEFAULT_FROM,
      to_version: DEFAULT_TO,
      description: "Language is now an enum flag set instead of a single string value.",
      migration_hint: "Replace the string assignment with the Languages flag enum.",
      citation: {
        canonical_url: "https://docs.aspose.com/ocr/net/recognition-settings/",
        section_anchor: "#language",
      },
    },
    {
      type: "removed_member",
      symbol_fqn: "Aspose.OCR.OcrEngine.RecognizeFast",
      from_version: DEFAULT_FROM,
      to_version: DEFAULT_TO,
      description: "RecognizeFast was removed in favor of the speed-mode setting.",
      migration_hint: "Use Recognize with RecognitionSettings.DetectAreasMode = Fast.",
      citation: {
        canonical_url: "https://reference.aspose.com/ocr/net/aspose.ocr/ocrengine/",
        section_anchor: "#recognize",
      },
    },
  ],
  page: 1,
  page_size: 50,
  total: 2,
};

const FIXTURE_PLAN: UpgradePlan = {
  scope: {
    product_id: DEFAULT_PRODUCT,
    language: DEFAULT_LANGUAGE,
    from_version: DEFAULT_FROM,
    to_version: DEFAULT_TO,
  },
  latestRelease: FIXTURE_LATEST,
  breakingChanges: FIXTURE_BREAKING,
};

/** Build the guided migration checklist + prompt from a plan. */
function deriveChecklist(plan: UpgradePlan): string[] {
  return [
    `Review ${plan.breakingChanges.total} breaking change(s) before updating production code.`,
    `Validate the ${plan.latestRelease.items.length} latest release feature(s) against your integration.`,
    `Pin retrieval to the resolved target version ${plan.latestRelease.resolved_version}.`,
    "Re-run the product self-test before promoting the upgrade.",
  ];
}

function derivePrompt(plan: UpgradePlan): string {
  return [
    `Upgrade ${plan.scope.product_id} (${plan.scope.language}) from ${plan.scope.from_version} to ${plan.scope.to_version}.`,
    "List breaking changes, latest release features, exact symbols that changed, and end with a migration checklist plus a minimal safe-upgrade code sketch.",
  ].join(" ");
}

function statusVariant(blocking: number): StatusVariant {
  return blocking > 0 ? "warn" : "ok";
}

/* ----------------------------------------------------------------------------
 * Section
 * -------------------------------------------------------------------------- */

export default function UpgradeAssistant() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(THEME_KEY) === "dark") setDark(true);
    } catch {
      /* keep default */
    }
  }, []);

  const [productInput, setProductInput] = useState(DEFAULT_PRODUCT);
  const [languageInput, setLanguageInput] = useState(DEFAULT_LANGUAGE);
  const [fromInput, setFromInput] = useState(DEFAULT_FROM);
  const [toInput, setToInput] = useState(DEFAULT_TO);

  // The "submitted" scope gates the query (null = not built yet).
  const [scope, setScope] = useState<UpgradePlanScope | null>(null);

  const planQuery = useQuery({
    queryKey: [
      "public-upgrade-assistant",
      scope?.product_id,
      scope?.language,
      scope?.from_version,
      scope?.to_version,
    ],
    queryFn: async (): Promise<UpgradePlan> => {
      // scope is guaranteed non-null while enabled
      const active = scope as UpgradePlanScope;
      const [latestRelease, breakingChanges] = await Promise.all([
        fetchPublicLatestReleaseFeatures({
          product_id: active.product_id,
          language: active.language,
          version: active.to_version,
        }),
        fetchPublicBreakingChanges({
          product_id: active.product_id,
          language: active.language,
          from_version: active.from_version,
          to_version: active.to_version,
        }),
      ]);
      return { scope: active, latestRelease, breakingChanges };
    },
    enabled: scope !== null, // built on demand from the form
  });

  const buildPlan = useCallback(() => {
    const next: UpgradePlanScope = {
      product_id: productInput.trim() || DEFAULT_PRODUCT,
      language: languageInput.trim() || DEFAULT_LANGUAGE,
      from_version: fromInput.trim() || DEFAULT_FROM,
      to_version: toInput.trim() || DEFAULT_TO,
    };
    setScope(next);
  }, [productInput, languageInput, fromInput, toInput]);

  // --- prefill shortcuts (button-triggered, not always-on queries) -----------
  // Seed the from/to fields from public release endpoints without building a plan,
  // so the operator still reviews the range before clicking Build upgrade plan.
  const [prefillNote, setPrefillNote] = useState<string | null>(null);

  const freshnessPrefill = useMutation({
    mutationFn: () =>
      fetchPublicReleaseFreshness({
        product_id: productInput.trim() || DEFAULT_PRODUCT,
        programming_language: languageInput.trim() || DEFAULT_LANGUAGE,
      }),
    onSuccess: (data) => {
      const newest = data.newest_available_version;
      const versions = data.available_versions ?? [];
      // `from` = the next-newest distinct visible version when available.
      const prior = versions.find((v) => v !== newest) ?? data.resolved_version ?? null;
      if (newest) setToInput(newest);
      if (prior) setFromInput(prior);
      setPrefillNote(
        newest
          ? `Loaded freshness defaults → newest visible ${newest}${prior ? ` (from ${prior})` : ""}.`
          : "Freshness endpoint returned no newest visible version.",
      );
    },
    onError: (err) => {
      setPrefillNote(
        err instanceof AdminApiError ? err.message : "Could not load freshness defaults.",
      );
    },
  });

  const recommendedRangePrefill = useMutation({
    mutationFn: () =>
      fetchPublicReleaseAdoption({
        product_id: productInput.trim() || DEFAULT_PRODUCT,
        programming_language: languageInput.trim() || DEFAULT_LANGUAGE,
      }),
    onSuccess: (data) => {
      const from = data.recommended_from_version;
      const to = data.recommended_to_version;
      if (from) setFromInput(from);
      if (to) setToInput(to);
      setPrefillNote(
        from && to
          ? `Loaded recommended range ${from} → ${to}.`
          : "Adoption endpoint returned no recommended range.",
      );
    },
    onError: (err) => {
      setPrefillNote(
        err instanceof AdminApiError ? err.message : "Could not load the recommended range.",
      );
    },
  });

  const prefillBusy = freshnessPrefill.isPending || recommendedRangePrefill.isPending;

  const live = planQuery.data ?? null;
  const usingFixture = live === null;
  const plan = live ?? FIXTURE_PLAN;
  const idle = scope === null; // never built a live plan in this session
  const errored = planQuery.isError;
  const errorMessage =
    planQuery.error instanceof AdminApiError
      ? planQuery.error.message
      : "Could not reach the release endpoints.";

  const checklist = useMemo(() => deriveChecklist(plan), [plan]);
  const prompt = useMemo(() => derivePrompt(plan), [plan]);
  const blocking = plan.breakingChanges.total;

  // Copy upgrade prompt → clipboard.
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(prompt);
    } catch {
      /* clipboard blocked */
    }
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 2000);
  }, [prompt]);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const productId = useId();
  const languageId = useId();
  const fromId = useId();
  const toId = useId();

  return (
    <div className={cn("pub", "t-mono", dark && "theme-dark")} suppressHydrationWarning>
      <main className="pub-wrap">
        <section className="pub-hero" style={{ paddingBottom: 24 }}>
          <span
            className="pub-status-led"
            style={{
              background: "var(--accent-weak)",
              color: "var(--accent-line)",
              borderColor: "color-mix(in srgb,var(--accent-line) 30%,var(--border))",
            }}
          >
            <span className="led" style={{ background: "var(--accent-line)", animation: "none" }} />
            Release upgrade assistant
          </span>
          <h1 className="pub-h1">Build a safe upgrade brief</h1>
          <p className="pub-sub">
            Combine latest release features and breaking-change evidence for one version jump. Move
            from one visible version to another without manually stitching release notes, migration
            hints and citations.
          </p>
        </section>

        {/* version inputs */}
        <section className="pub-card" style={{ padding: 20 }} aria-label="Upgrade scope">
          <form
            className="toolbar"
            style={{ margin: 0 }}
            onSubmit={(e) => {
              e.preventDefault();
              buildPlan();
            }}
          >
            <span className="input" style={{ minWidth: 160 }}>
              <label style={SR_ONLY} htmlFor={productId}>
                Product ID
              </label>
              <input
                id={productId}
                className="inputctl"
                value={productInput}
                onChange={(e) => setProductInput(e.target.value)}
                placeholder="aspose.ocr"
              />
            </span>
            <span className="input" style={{ minWidth: 110 }}>
              <label style={SR_ONLY} htmlFor={languageId}>
                SDK language
              </label>
              <input
                id={languageId}
                className="inputctl"
                value={languageInput}
                onChange={(e) => setLanguageInput(e.target.value)}
                placeholder="net"
              />
            </span>
            <span className="input" style={{ minWidth: 120 }}>
              <label style={SR_ONLY} htmlFor={fromId}>
                From version
              </label>
              <input
                id={fromId}
                className="inputctl"
                value={fromInput}
                onChange={(e) => setFromInput(e.target.value)}
                placeholder="24.12"
              />
            </span>
            <span className="input" style={{ minWidth: 120 }}>
              <label style={SR_ONLY} htmlFor={toId}>
                To version
              </label>
              <input
                id={toId}
                className="inputctl"
                value={toInput}
                onChange={(e) => setToInput(e.target.value)}
                placeholder="25.1"
              />
            </span>
            <button
              type="button"
              className="pub-cta ghost"
              style={{ height: 34, fontSize: 13 }}
              onClick={() => freshnessPrefill.mutate()}
              disabled={prefillBusy}
              title="Seed the to-version from the newest visible release"
            >
              {freshnessPrefill.isPending ? "Loading…" : "Use freshness defaults"}
            </button>
            <button
              type="button"
              className="pub-cta ghost"
              style={{ height: 34, fontSize: 13 }}
              onClick={() => recommendedRangePrefill.mutate()}
              disabled={prefillBusy}
              title="Seed from/to versions from the recommended adoption range"
            >
              {recommendedRangePrefill.isPending ? "Loading…" : "Load recommended range"}
            </button>
            <button type="submit" className="pub-cta" style={{ height: 34, fontSize: 13 }}>
              {planQuery.isFetching ? "Building…" : "Build upgrade plan"}
            </button>
          </form>
          {prefillNote ? (
            <div className="muted-note" style={{ marginTop: 10 }} role="status" aria-live="polite">
              {prefillNote}
            </div>
          ) : null}
          <div className="muted-note" style={{ marginTop: 10 }}>
            Uses only public endpoints: <span className="mono">/v1/releases:latest</span>,{" "}
            <span className="mono">/v1/changes:list</span>,{" "}
            <span className="mono">/v1/releases/freshness</span> and{" "}
            <span className="mono">/v1/integrations/release-adoption</span>.
          </div>
        </section>

        {/* idle hint (no plan built yet) — fixture preview still renders below */}
        {idle ? (
          <section className="pub-card" style={{ padding: 16 }}>
            <div className="svc-row" style={{ padding: 0, borderBottom: "none" }}>
              <Pill variant="info">preview</Pill>
              <div>
                <div className="svc-name">Sample upgrade plan shown below</div>
                <div className="svc-desc">
                  Enter a from/to version and select Build upgrade plan to run a live brief.
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {/* offline / error notice */}
        {!idle && usingFixture && errored ? (
          <section className="pub-card" style={{ padding: 16 }} role="alert">
            <div className="svc-row" style={{ padding: 0, borderBottom: "none" }}>
              <Pill variant="warn">offline</Pill>
              <div>
                <div className="svc-name">Showing sample upgrade plan</div>
                <div className="svc-desc">{errorMessage} Reconnect to load live evidence.</div>
              </div>
              <button
                type="button"
                className="pub-cta ghost"
                style={{ height: 32, fontSize: 12, marginLeft: "auto" }}
                onClick={() => void planQuery.refetch()}
              >
                Retry
              </button>
            </div>
          </section>
        ) : null}

        {/* upgrade path summary */}
        <section className="pub-card" style={{ marginTop: 4 }} aria-label="Upgrade path">
          <div className="pub-card-head">
            <span className="pub-card-title">Upgrade path</span>
            <span className="right" style={{ marginLeft: "auto" }}>
              <Pill variant={statusVariant(blocking)}>
                {blocking > 0 ? `${blocking} breaking` : "additive-only"}
              </Pill>
            </span>
          </div>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)" }}>
            <span className="svc-desc" style={{ marginTop: 0 }}>
              {plan.scope.product_id} / {plan.scope.language}:{" "}
              <span className="mono">
                {plan.scope.from_version} → {plan.scope.to_version}
              </span>{" "}
              · {plan.breakingChanges.total} breaking change(s),{" "}
              {plan.latestRelease.items.length} latest feature(s), resolved target ={" "}
              {plan.latestRelease.resolved_version}.
            </span>
          </div>
          <div className="metric-strip">
            <div className="m">
              <div className="mv">{plan.breakingChanges.total}</div>
              <div className="ml">Breaking changes</div>
            </div>
            <div className="m">
              <div className="mv" style={{ fontSize: 18 }}>
                {plan.latestRelease.resolved_version}
              </div>
              <div className="ml">Resolved target</div>
            </div>
            <div className="m">
              <div className="mv">{plan.latestRelease.items.length}</div>
              <div className="ml">Release features</div>
            </div>
            <div className="m">
              <div className="mv" style={{ fontSize: 18 }}>
                <span className="mono">
                  {plan.scope.from_version}→{plan.scope.to_version}
                </span>
              </div>
              <div className="ml">Version jump</div>
            </div>
          </div>
        </section>

        {/* migration checklist + comprehensive prompt */}
        <section className="pub-card" style={{ padding: 22 }} aria-label="Migration checklist">
          <div className="pub-card-title" style={{ marginBottom: 14 }}>
            Migration checklist
          </div>
          <ol className="step-list">
            {checklist.map((step) => (
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

          <div className="pub-card-title" style={{ margin: "22px 0 10px", fontSize: 13.5 }}>
            Comprehensive upgrade prompt
          </div>
          <div className="code-card">
            <div className="code-head">
              <span className="dot3" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="fname">upgrade-prompt.txt</span>
              <button
                type="button"
                className="copy"
                onClick={copyPrompt}
                aria-label="Copy upgrade prompt to clipboard"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="code-body" tabIndex={0}>
              {prompt}
            </pre>
          </div>
          <span style={SR_ONLY} role="status" aria-live="polite">
            {copied ? "Upgrade prompt copied to clipboard" : ""}
          </span>
        </section>

        {/* breaking changes table */}
        <section className="pub-card" aria-label="Breaking changes">
          <div className="pub-card-head">
            <span className="pub-card-title">Breaking changes</span>
            <span className="right muted-note">
              {plan.scope.from_version} → {plan.scope.to_version}
            </span>
          </div>
          {plan.breakingChanges.items.length === 0 ? (
            <div style={{ padding: "16px 20px" }}>
              <span className="muted-note">
                No breaking changes for this version jump — additive-only.
              </span>
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: 150 }}>Type</th>
                    <th>Symbol</th>
                    <th>Description &amp; migration hint</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.breakingChanges.items.map((item, i) => (
                    <tr className="data" key={`${item.type}-${item.symbol_fqn}-${i}`}>
                      <td>
                        <Pill variant="warn">{item.type}</Pill>
                      </td>
                      <td>
                        {item.symbol_fqn ? (
                          <span className="repo-id">{item.symbol_fqn}</span>
                        ) : (
                          <span className="muted-note">—</span>
                        )}
                      </td>
                      <td>
                        <div className="svc-name" style={{ fontSize: 12.5, fontWeight: 500 }}>
                          {item.description}
                        </div>
                        <div className="svc-desc" style={{ marginTop: 3 }}>
                          Migration hint: {item.migration_hint}
                        </div>
                        <a
                          className="muted-note"
                          href={`${item.citation.canonical_url}${item.citation.section_anchor}`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ textDecoration: "underline" }}
                        >
                          View citation
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* latest features list */}
        <section className="pub-card" aria-label="Latest release features">
          <div className="pub-card-head">
            <span className="pub-card-title">Latest release features</span>
            <span className="right muted-note">resolved {plan.latestRelease.resolved_version}</span>
          </div>
          {plan.latestRelease.items.length === 0 ? (
            <div style={{ padding: "16px 20px" }}>
              <span className="muted-note">No release-note features indexed for this scope.</span>
            </div>
          ) : (
            plan.latestRelease.items.map((item, i) => (
              <div className="svc-row" key={`${item.summary}-${i}`}>
                <Tag>{item.kind}</Tag>
                <div>
                  <div className="svc-name" style={{ fontSize: 13 }}>
                    {item.summary}
                  </div>
                  <div className="svc-desc">
                    {item.symbol_fqn ? <span className="mono">{item.symbol_fqn}</span> : item.source_kind}{" "}
                    ·{" "}
                    <a
                      href={`${item.citation.canonical_url}${item.citation.section_anchor}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ textDecoration: "underline", color: "var(--fg-muted)" }}
                    >
                      citation
                    </a>
                  </div>
                </div>
                <div
                  className="svc-up"
                  style={{ width: "auto", fontFamily: "var(--font-mono)", fontSize: 11 }}
                >
                  {item.version}
                </div>
              </div>
            ))
          )}
        </section>
      </main>
    </div>
  );
}
