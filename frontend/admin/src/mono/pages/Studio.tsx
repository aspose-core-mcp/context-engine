"use client";

/**
 * ADCS support page — How-To Studio (route `/howto/studio`).
 *
 * The editorial surface where operators author, translate, and publish bilingual
 * How-To articles. Built on the Mono component kit + tokens with REAL
 * persistence: Save / Publish / Reset / Clear-Published / Upload Asset call the
 * live `/admin/v1/howto/*` admin mutations through TanStack `useMutation`. Feedback
 * is honest and settled — the success toast and refreshed metadata only appear
 * after the mutation resolves; failures surface the AdminApiError. No optimistic
 * UI, no fake "Published".
 *
 * Session + scope come from the admin console shell context (`useAdminData`), not a
 * page-local cookie fetch: offline (no reachable backend) falls back to the content
 * baseline with every control enabled; online without `write:settings` disables
 * every mutation and shows the PermissionDenied recovery block.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type ReactNode,
} from "react";

import {
  HOW_TO_ARTICLES,
  HOW_TO_ARTICLE_BY_ID,
  HOW_TO_TOPICS,
  applyHowToOverride,
  articleHasLocaleGaps,
  buildHowToHref,
  buildHowToOverridePayload,
  listHowToArticlesByTopic,
  type HowToArticle,
  type HowToArticleId,
  type HowToLocale,
} from "@/content/howto";
import {
  AdminApiError,
  clearAdminHowToPublished,
  fetchAdminHowToArticle,
  getAdminApiBaseUrl,
  publishAdminHowToDraft,
  resetAdminHowToDraft,
  saveAdminHowToDraft,
  uploadAdminHowToAsset,
  type HowToOverrideCallout,
  type HowToOverrideCommand,
  type HowToOverrideExample,
  type HowToOverridePayload,
  type HowToOverrideScreenshot,
} from "@/lib/admin-api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "../components/Button";
import { PermissionDenied, Skeleton } from "../components/states";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName } from "../lib/types";
import { AdminDataProvider, useAdminData } from "../shell/data";
import { OverlayProvider, useToast } from "../shell/overlays";

/* --------------------------------------------------------------- constants -- */

const WRITE_SCOPE = "write:settings";
const THEME_KEY = "adcs_theme";

/** Visually-hidden style (the Mono kit has no `.sr-only` utility). */
const SR_ONLY: CSSProperties = {
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

/* ----------------------------------------------------------------- helpers -- */

function toMultiline(value: string[]): string {
  return value.join("\n");
}

/**
 * Parse a textarea value into trimmed, non-empty lines for the persisted payload.
 * The textarea itself keeps its RAW string in component state (see `useRawLines`)
 * so pressing Enter at the end of the text is never swallowed — only the derived
 * array drops blank lines.
 */
function fromMultiline(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function replaceAt<T>(items: readonly T[], index: number, value: T): T[] {
  return items.map((item, i) => (i === index ? value : item));
}

function removeAt<T>(items: readonly T[], index: number): T[] {
  return items.filter((_, i) => i !== index);
}

function emptyText() {
  return { en: "", ru: "" };
}

function emptyLines() {
  return { en: [] as string[], ru: [] as string[] };
}

function errMessage(error: unknown, fallback: string): string {
  if (error instanceof AdminApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const t = Date.parse(value);
  if (Number.isNaN(t)) return value;
  return new Date(t).toLocaleString();
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file."));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      const [, payload = ""] = result.split(",", 2);
      resolve(payload);
    };
    reader.readAsDataURL(file);
  });
}

function loc(value: { en: string; ru: string }, l: HowToLocale): string {
  // Match the Mono How-To Center reader (HowTo.tsx `L`): fall back to EN only
  // when the localized value is null/undefined.
  // An empty RU string renders blank so a translator sees the gap (surfaced by the
  // "RU gaps → EN fallback" indicator) instead of silently masking it with English.
  const v = value[l];
  return (v != null ? v : value.en) || "";
}

function locLines(value: { en: string[]; ru: string[] }, l: HowToLocale): string[] {
  const v = value[l];
  return (v != null && v.length ? v : value.en) || [];
}

/* ============================================================== component == */

/**
 * The `/howto/studio` route renders its OWN root (outside the console Shell), so the
 * Shell-local providers are not in the tree. We mount them here — `OverlayProvider`
 * (toasts + confirm modals) and `AdminDataProvider` (cookie/API-key session + scope
 * bridge) — inside the themed `.adcs .t-mono` root so overlays inherit Mono tokens.
 * The app-wide `QueryClientProvider` (src/components/providers.tsx) already backs the
 * `useQuery`/`useMutation` calls below.
 */
export default function StudioPage() {
  // Self-contained light/dark toggle (matches HowTo.tsx; persisted to `adcs_theme`).
  // Theme lives on the OUTER root so toasts/modals render inside the themed wrapper.
  const [dark, setDark] = useState(false);
  useEffect(() => {
    try {
      setDark(window.localStorage.getItem(THEME_KEY) === "dark");
    } catch {
      /* storage unavailable — keep default light */
    }
  }, []);
  const toggleTheme = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore persistence failure */
      }
      return next;
    });
  }, []);

  return (
    <div className={cn("adcs", "t-mono", dark && "theme-dark")}>
      <OverlayProvider>
        <AdminDataProvider>
          <StudioInner dark={dark} onToggleTheme={toggleTheme} />
        </AdminDataProvider>
      </OverlayProvider>
    </div>
  );
}

function StudioInner({
  dark,
  onToggleTheme,
}: {
  dark: boolean;
  onToggleTheme: () => void;
}) {
  const data = useAdminData();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<HowToArticleId>(HOW_TO_ARTICLES[0].id);
  const [previewLocale, setPreviewLocale] = useState<HowToLocale>("en");
  const [draft, setDraft] = useState<HowToOverridePayload | null>(null);
  const [zoom, setZoom] = useState<HowToOverrideScreenshot | null>(null);

  const apiKey = data.apiKey;
  const sessionReady = data.sessionIsSuccess;
  const canEdit = data.can(WRITE_SCOPE);

  // Live record (draft/published envelope). Only runs once a real session is up;
  // offline we keep the content baseline so the editor stays fully reviewable.
  const articleQuery = useQuery({
    queryKey: ["studio-howto-article", selectedId],
    queryFn: () => fetchAdminHowToArticle(apiKey, selectedId),
    enabled: sessionReady,
    retry: false,
  });

  const baseArticle: HowToArticle = useMemo(
    () => HOW_TO_ARTICLE_BY_ID.get(selectedId)!,
    [selectedId],
  );

  // The persisted source of truth for dirty-detection: live draft → live published →
  // repository baseline (offline, or a never-touched article).
  const persisted = useMemo<HowToOverridePayload>(
    () =>
      (articleQuery.data?.draft ??
        articleQuery.data?.published ??
        buildHowToOverridePayload(baseArticle)) as HowToOverridePayload,
    [articleQuery.data?.draft, articleQuery.data?.published, baseArticle],
  );

  // Re-seed the editable draft whenever the persisted record changes (article switch,
  // or a settled mutation invalidates + refetches the envelope).
  useEffect(() => {
    setDraft(persisted);
  }, [persisted]);

  const previewArticle = useMemo(
    () => applyHowToOverride(baseArticle, draft),
    [baseArticle, draft],
  );

  const isDirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(persisted),
    [draft, persisted],
  );

  const draftMeta = articleQuery.data;

  function updateDraft(mutator: (current: HowToOverridePayload) => HowToOverridePayload) {
    setDraft((current) => (current ? mutator(current) : current));
  }

  async function refreshArticle() {
    await queryClient.invalidateQueries({
      queryKey: ["studio-howto-article", selectedId],
    });
    await queryClient.invalidateQueries({ queryKey: ["public-howto-articles"] });
  }

  /* ----------------------------------------------------------- mutations -- */
  // No optimistic UI: every onSuccess waits for the envelope to settle, then toasts
  // and refetches so the metadata chips + dirty flag reflect the real server state.

  const saveMutation = useMutation({
    mutationFn: (payload: HowToOverridePayload) =>
      saveAdminHowToDraft(apiKey, selectedId, payload),
    onSuccess: async () => {
      await refreshArticle();
      toast("Draft saved · stored as the private working copy");
    },
    onError: (error: unknown) =>
      toast(errMessage(error, "Saving the draft failed.")),
  });

  const publishMutation = useMutation({
    mutationFn: () => publishAdminHowToDraft(apiKey, selectedId),
    onSuccess: async () => {
      await refreshArticle();
      toast("Draft published · live for users");
    },
    onError: (error: unknown) =>
      toast(errMessage(error, "Publishing the draft failed.")),
  });

  const resetMutation = useMutation({
    mutationFn: () => resetAdminHowToDraft(apiKey, selectedId),
    onSuccess: async () => {
      await refreshArticle();
      toast("Draft reset · preview now follows the published or repository baseline");
    },
    onError: (error: unknown) =>
      toast(errMessage(error, "Resetting the draft failed.")),
  });

  const clearMutation = useMutation({
    mutationFn: () => clearAdminHowToPublished(apiKey, selectedId),
    onSuccess: async () => {
      await refreshArticle();
      toast("Published override cleared · users fall back to the repository baseline");
    },
    onError: (error: unknown) =>
      toast(errMessage(error, "Clearing the published override failed.")),
  });

  const uploadMutation = useMutation({
    mutationFn: (payload: { filename: string; content_base64: string }) =>
      uploadAdminHowToAsset(apiKey, payload),
  });

  const anyPending =
    saveMutation.isPending ||
    publishMutation.isPending ||
    resetMutation.isPending ||
    clearMutation.isPending;

  async function handleScreenshotUpload(index: number, file: File): Promise<void> {
    try {
      const contentBase64 = await fileToBase64(file);
      const response = await uploadMutation.mutateAsync({
        filename: file.name,
        content_base64: contentBase64,
      });
      const absoluteUrl = response.asset_url.startsWith("http")
        ? response.asset_url
        : `${getAdminApiBaseUrl()}${response.asset_url}`;
      updateDraft((current) => ({
        ...current,
        screenshots: replaceAt(current.screenshots, index, {
          ...current.screenshots[index],
          src: absoluteUrl,
        }),
      }));
      toast(`Uploaded screenshot asset ${response.asset_name}`);
    } catch (error: unknown) {
      // Honest failure: the URL field is left untouched so the operator can retry.
      toast(errMessage(error, "Uploading the screenshot asset failed."));
    }
  }

  const liveHref = buildHowToHref(selectedId, previewLocale);

  /* ------------------------------------------------------------- gating -- */

  if (data.sessionIsLoading) {
    return (
      <div className="st-shell">
        <div style={{ padding: 24 }}>
          <Skeleton rows={5} />
        </div>
      </div>
    );
  }

  const mutationError =
    (saveMutation.error as Error | null) ??
    (publishMutation.error as Error | null) ??
    (resetMutation.error as Error | null) ??
    (clearMutation.error as Error | null) ??
    (uploadMutation.error as Error | null);
  const articleError =
    articleQuery.error instanceof AdminApiError ? articleQuery.error : null;

  /* ============================================================ render === */
  return (
    <>
      <a className="skip-link" href="#st-editor">
        Skip to editor
      </a>

      <div className="st-shell">
        {/* ----------------------------------------------------- top / header */}
        <header className="st-top">
          <a className="ql-back" href="/howto">
            <Icon name="arrow" />
            <span>How-To Center</span>
          </a>

          <label style={SR_ONLY} htmlFor="st-pick">
            Article to edit
          </label>
          <select
            id="st-pick"
            className="selectctl st-pick"
            aria-label="Article to edit"
            value={selectedId}
            disabled={anyPending}
            onChange={(e) => {
              setZoom(null);
              setSelectedId(e.target.value as HowToArticleId);
            }}
            style={{ maxWidth: 320 }}
          >
            {HOW_TO_TOPICS.map((topic) => (
              <optgroup key={topic} label={topic}>
                {listHowToArticlesByTopic(topic).map((article) => (
                  <option key={article.id} value={article.id}>
                    {article.title.en}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>

          <div className="st-meta">
            <span
              className={cn("st-chip", isDirty && "dirty")}
              role="status"
              aria-live="polite"
            >
              {isDirty ? "Unsaved changes" : "Saved state"}
            </span>
            <span className="muted-note">
              draft {formatTimestamp(draftMeta?.draft_updated_at)}
              {draftMeta?.draft_updated_by ? ` · ${draftMeta.draft_updated_by}` : ""} · published{" "}
              {formatTimestamp(draftMeta?.published_updated_at)}
              {draftMeta?.published_updated_by ? ` · ${draftMeta.published_updated_by}` : ""}
            </span>
          </div>

          <div className="st-actions">
            <button
              type="button"
              className="icon-btn"
              aria-pressed={dark}
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              title="Toggle theme"
              onClick={onToggleTheme}
            >
              <Icon name={dark ? "sun" : "moon"} />
            </button>
            <a
              className="btn btn-ghost btn-sm"
              href={liveHref}
              target="_blank"
              rel="noreferrer"
              style={{ textDecoration: "none" }}
            >
              <Icon name="arrow" className="ico" />
              Open live
            </a>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="history"
              disabled={!canEdit || resetMutation.isPending || !draft}
              title={canEdit ? "Reset the draft to the published / repository baseline" : `Requires the ${WRITE_SCOPE} scope`}
              onClick={() =>
                data.showConfirm(
                  "Reset this draft to the published or repository baseline? Unsaved edits are discarded.",
                  () => resetMutation.mutate(),
                )
              }
            >
              {resetMutation.isPending ? "Resetting…" : "Reset draft"}
            </Button>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="check"
              disabled={!canEdit || !draft || saveMutation.isPending}
              title={canEdit ? undefined : `Requires the ${WRITE_SCOPE} scope`}
              onClick={() => draft && saveMutation.mutate(draft)}
            >
              {saveMutation.isPending ? "Saving…" : "Save draft"}
            </Button>
            <Button
              variant="btn-amber"
              size="sm"
              icon="upload"
              disabled={!canEdit || publishMutation.isPending}
              title={canEdit ? "Publish the current draft — visible to users immediately" : `Requires the ${WRITE_SCOPE} scope`}
              onClick={() =>
                data.showConfirm(
                  "Publish the current draft? It becomes live for users immediately.",
                  () => publishMutation.mutate(),
                )
              }
            >
              {publishMutation.isPending ? "Publishing…" : "Publish"}
            </Button>
            <Button
              variant="btn-danger"
              size="sm"
              icon="x"
              disabled={!canEdit || clearMutation.isPending}
              title={canEdit ? "Remove the published override — users fall back to the repository baseline" : `Requires the ${WRITE_SCOPE} scope`}
              onClick={() =>
                data.showConfirm(
                  "Clear the published override? Users fall back to the repository baseline. This cannot be undone.",
                  () => clearMutation.mutate(),
                )
              }
            >
              {clearMutation.isPending ? "Clearing…" : "Clear published"}
            </Button>
          </div>
        </header>

        {/* --------------------------------------------------- alert banners */}
        {(!canEdit || articleError || mutationError) && (
          <div style={{ padding: "12px 20px 0" }}>
            {!canEdit && (
              <PermissionDenied
                scope={WRITE_SCOPE}
                extra="This page stays visible for review, but Save, Publish, Reset, Clear Published, and Upload Asset remain disabled until an administrator grants the scope."
              />
            )}
            {articleError && (
              <div className="recovery" role="alert" style={{ marginTop: canEdit ? 0 : 10 }}>
                <div className="rec-ico">
                  <Icon name="alert" />
                </div>
                <div className="rec-body">
                  <div className="rec-title">Article record unavailable</div>
                  <div className="rec-text">{articleError.message}</div>
                  <div className="rec-cause">
                    Likely cause: the admin session expired, the key lacks read access, or the
                    overrides store returned a 5xx. The editor below falls back to the repository
                    baseline.
                  </div>
                </div>
              </div>
            )}
            {mutationError && (
              <div className="recovery" role="alert" style={{ marginTop: 10 }}>
                <div className="rec-ico">
                  <Icon name="alert" />
                </div>
                <div className="rec-body">
                  <div className="rec-title">Last action failed</div>
                  <div className="rec-text">{mutationError.message}</div>
                  <div className="rec-cause">
                    Likely cause: missing {WRITE_SCOPE} scope, an expired session, or the overrides
                    store is read-only. Fix the issue and retry.
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ------------------------------------------------------ editor cols */}
        <main className="st-cols">
          {/* ----- left: bilingual editor ----- */}
          <section className="st-editor" id="st-editor" aria-label="Article editor">
            {draft ? (
              <>
                <div className="st-pv-top" style={{ marginBottom: 6 }}>
                  <h2 className="st-sec" style={{ margin: 0 }}>
                    Content
                  </h2>
                  <Tag>{baseArticle.topic}</Tag>
                </div>

                <LocalizedTextField
                  label="Entry label"
                  hint="Short label used in article lists and related links."
                  testId="entry-label"
                  value={draft.entry_label}
                  onChange={(value) =>
                    updateDraft((current) => ({ ...current, entry_label: value }))
                  }
                />
                <LocalizedTextField
                  label="Article title"
                  hint="Primary H1 used by the article page and the preview pane."
                  testId="article-title"
                  value={draft.title}
                  onChange={(value) => updateDraft((current) => ({ ...current, title: value }))}
                />
                <LocalizedTextField
                  label="Summary"
                  hint="Lead paragraph shown in the knowledge center header and article intro."
                  testId="summary"
                  multiline
                  rows={3}
                  value={draft.summary}
                  onChange={(value) => updateDraft((current) => ({ ...current, summary: value }))}
                />

                <LocalizedLinesField
                  label="Purpose · one bullet per line"
                  hint="Explain why this page exists and when to use it."
                  value={draft.purpose}
                  onChange={(value) => updateDraft((current) => ({ ...current, purpose: value }))}
                />
                <LocalizedLinesField
                  label="Workflow steps · one per line"
                  hint="Each line renders as a numbered operational step in the reader."
                  value={draft.workflow}
                  onChange={(value) => updateDraft((current) => ({ ...current, workflow: value }))}
                />

                {/* ---- callouts ---- */}
                <CollectionHead
                  title="Callouts"
                  hint="Operator guidance blocks — warnings, safe defaults, or recommended sequencing."
                  addLabel="Add callout"
                  onAdd={() =>
                    updateDraft((current) => ({
                      ...current,
                      callouts: [
                        ...current.callouts,
                        {
                          id: `callout-${current.callouts.length + 1}`,
                          level: "info",
                          title: emptyText(),
                          body: emptyLines(),
                        },
                      ],
                    }))
                  }
                />
                {draft.callouts.length === 0 ? (
                  <p className="muted-note" style={{ margin: "0 0 12px" }}>
                    No callouts yet.
                  </p>
                ) : (
                  draft.callouts.map((item, index) => (
                    <CalloutEditor
                      key={`${item.id}-${index}`}
                      item={item}
                      onChange={(next) =>
                        updateDraft((current) => ({
                          ...current,
                          callouts: replaceAt(current.callouts, index, next),
                        }))
                      }
                      onRemove={() =>
                        updateDraft((current) => ({
                          ...current,
                          callouts: removeAt(current.callouts, index),
                        }))
                      }
                    />
                  ))
                )}

                {/* ---- commands ---- */}
                <CollectionHead
                  title="Commands"
                  hint="Copy-ready commands shown under the article as operational shortcuts."
                  addLabel="Add command"
                  onAdd={() =>
                    updateDraft((current) => ({
                      ...current,
                      commands: [
                        ...current.commands,
                        {
                          id: `command-${current.commands.length + 1}`,
                          label: emptyText(),
                          description: emptyText(),
                          command: "",
                        },
                      ],
                    }))
                  }
                />
                {draft.commands.length === 0 ? (
                  <p className="muted-note" style={{ margin: "0 0 12px" }}>
                    No commands yet.
                  </p>
                ) : (
                  draft.commands.map((item, index) => (
                    <CommandEditor
                      key={`${item.id}-${index}`}
                      item={item}
                      onChange={(next) =>
                        updateDraft((current) => ({
                          ...current,
                          commands: replaceAt(current.commands, index, next),
                        }))
                      }
                      onRemove={() =>
                        updateDraft((current) => ({
                          ...current,
                          commands: removeAt(current.commands, index),
                        }))
                      }
                    />
                  ))
                )}

                {/* ---- examples ---- */}
                <CollectionHead
                  title="Examples"
                  hint="Practical scenarios shown as compact operational examples."
                  addLabel="Add example"
                  onAdd={() =>
                    updateDraft((current) => ({
                      ...current,
                      examples: [
                        ...current.examples,
                        {
                          id: `example-${current.examples.length + 1}`,
                          title: emptyText(),
                          bullets: emptyLines(),
                        },
                      ],
                    }))
                  }
                />
                {draft.examples.length === 0 ? (
                  <p className="muted-note" style={{ margin: "0 0 12px" }}>
                    No examples yet.
                  </p>
                ) : (
                  draft.examples.map((item, index) => (
                    <ExampleEditor
                      key={`${item.id}-${index}`}
                      item={item}
                      onChange={(next) =>
                        updateDraft((current) => ({
                          ...current,
                          examples: replaceAt(current.examples, index, next),
                        }))
                      }
                      onRemove={() =>
                        updateDraft((current) => ({
                          ...current,
                          examples: removeAt(current.examples, index),
                        }))
                      }
                    />
                  ))
                )}

                {/* ---- screenshots ---- */}
                <CollectionHead
                  title="Screenshots"
                  hint="Keep captions bilingual. Uploading an asset fills the screenshot URL automatically."
                  addLabel="Add screenshot"
                  onAdd={() =>
                    updateDraft((current) => ({
                      ...current,
                      screenshots: [
                        ...current.screenshots,
                        {
                          id: `screenshot-${current.screenshots.length + 1}`,
                          src: "",
                          alt: emptyText(),
                          caption: emptyText(),
                        },
                      ],
                    }))
                  }
                />
                {draft.screenshots.length === 0 ? (
                  <p className="muted-note" style={{ margin: "0 0 12px" }}>
                    No screenshots yet.
                  </p>
                ) : (
                  draft.screenshots.map((item, index) => (
                    <ScreenshotEditor
                      key={`${item.id}-${index}`}
                      item={item}
                      canEdit={canEdit}
                      uploadPending={uploadMutation.isPending}
                      onChange={(next) =>
                        updateDraft((current) => ({
                          ...current,
                          screenshots: replaceAt(current.screenshots, index, next),
                        }))
                      }
                      onRemove={() =>
                        updateDraft((current) => ({
                          ...current,
                          screenshots: removeAt(current.screenshots, index),
                        }))
                      }
                      onUpload={(file) => handleScreenshotUpload(index, file)}
                    />
                  ))
                )}
              </>
            ) : (
              <div style={{ paddingTop: 8 }}>
                <Skeleton rows={6} />
              </div>
            )}
          </section>

          {/* ----- right: live preview ----- */}
          <aside className="st-previewpane" aria-label="Live preview">
            <div className="st-pv-top">
              <span className="st-sec" style={{ margin: 0 }}>
                Preview
              </span>
              <div className="seg" role="group" aria-label="Preview language">
                <button
                  type="button"
                  className={previewLocale === "en" ? "on" : undefined}
                  aria-pressed={previewLocale === "en"}
                  onClick={() => setPreviewLocale("en")}
                >
                  EN
                </button>
                <button
                  type="button"
                  className={previewLocale === "ru" ? "on" : undefined}
                  aria-pressed={previewLocale === "ru"}
                  onClick={() => setPreviewLocale("ru")}
                >
                  RU
                </button>
              </div>
            </div>
            <div className="st-pv-body" id="st-preview">
              <ArticlePreview
                article={previewArticle}
                locale={previewLocale}
                onZoom={setZoom}
              />
            </div>
          </aside>
        </main>

        {/* --------------------------------------------------------- footer */}
        <footer
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            padding: "10px 20px",
            borderTop: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          <span className="muted-note">
            ADCS How-To Studio · drafts are private until published
          </span>
          <a
            className="btn btn-ghost btn-sm"
            href="/howto"
            style={{ textDecoration: "none" }}
          >
            How-To Center
          </a>
        </footer>
      </div>

      {/* ------------------------------------------------ screenshot zoom dialog */}
      {zoom && (
        <ScreenshotZoom screenshot={zoom} locale={previewLocale} onClose={() => setZoom(null)} />
      )}
    </>
  );
}

/* ------------------------------------------------------ editor sub-parts ----- */

/** Bilingual EN/RU input pair (single-line or multiline), Mono `.st-bi` grid. */
function LocalizedTextField({
  label,
  hint,
  value,
  onChange,
  multiline = false,
  rows = 2,
  testId,
}: {
  label: string;
  hint?: string;
  value: { en: string; ru: string };
  onChange: (value: { en: string; ru: string }) => void;
  multiline?: boolean;
  rows?: number;
  testId?: string;
}) {
  return (
    <div className="st-field">
      <label className="flabel">{label}</label>
      <div className="st-bi">
        {multiline ? (
          <textarea
            className="inputctl st-ta"
            rows={rows}
            placeholder="EN"
            aria-label={`${label} (English)`}
            data-testid={testId ? `${testId}-en` : undefined}
            value={value.en}
            onChange={(e) => onChange({ ...value, en: e.target.value })}
          />
        ) : (
          <input
            className="inputctl st-in"
            placeholder="EN"
            aria-label={`${label} (English)`}
            data-testid={testId ? `${testId}-en` : undefined}
            value={value.en}
            onChange={(e) => onChange({ ...value, en: e.target.value })}
          />
        )}
        {multiline ? (
          <textarea
            className="inputctl st-ta"
            rows={rows}
            placeholder="RU"
            aria-label={`${label} (Russian)`}
            data-testid={testId ? `${testId}-ru` : undefined}
            value={value.ru}
            onChange={(e) => onChange({ ...value, ru: e.target.value })}
          />
        ) : (
          <input
            className="inputctl st-in"
            placeholder="RU"
            aria-label={`${label} (Russian)`}
            data-testid={testId ? `${testId}-ru` : undefined}
            value={value.ru}
            onChange={(e) => onChange({ ...value, ru: e.target.value })}
          />
        )}
      </div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

/**
 * Bilingual one-item-per-line editor. CRITICAL: the textarea binds to a RAW string
 * kept in local state, so Enter at the end of the text is preserved (a trailing
 * newline survives). The trimmed array is derived only on change for the persisted
 * payload — never round-tripped back into the textarea value.
 */
function LocalizedLinesField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: { en: string[]; ru: string[] };
  onChange: (value: { en: string[]; ru: string[] }) => void;
}) {
  const [rawEn, setRawEn] = useRawLines(value.en);
  const [rawRu, setRawRu] = useRawLines(value.ru);

  return (
    <div className="st-field">
      <label className="flabel">{label}</label>
      <div className="st-bi">
        <textarea
          className="inputctl st-ta"
          rows={5}
          placeholder="EN · one per line"
          aria-label={`${label} (English)`}
          value={rawEn}
          onChange={(e) => {
            setRawEn(e.target.value);
            onChange({ ...value, en: fromMultiline(e.target.value) });
          }}
        />
        <textarea
          className="inputctl st-ta"
          rows={5}
          placeholder="RU · one per line"
          aria-label={`${label} (Russian)`}
          value={rawRu}
          onChange={(e) => {
            setRawRu(e.target.value);
            onChange({ ...value, ru: fromMultiline(e.target.value) });
          }}
        />
      </div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

/**
 * Keeps a raw textarea string in sync with an external string[] without clobbering
 * the user's in-progress newline. The raw value is re-synced from the canonical
 * array ONLY when the canonical array no longer matches what the raw text parses to
 * (i.e. an external change such as an article switch / reset), so typing Enter at
 * the end is never reverted.
 */
function useRawLines(lines: string[]): [string, (value: string) => void] {
  const [raw, setRaw] = useState(() => toMultiline(lines));
  const lastLines = useRef(lines);

  useEffect(() => {
    if (lastLines.current === lines) return;
    lastLines.current = lines;
    if (JSON.stringify(fromMultiline(raw)) !== JSON.stringify(lines)) {
      setRaw(toMultiline(lines));
    }
  }, [lines, raw]);

  return [raw, setRaw];
}

function CollectionHead({
  title,
  hint,
  addLabel,
  onAdd,
}: {
  title: string;
  hint: string;
  addLabel: string;
  onAdd: () => void;
}) {
  return (
    <div className="st-pv-top" style={{ marginTop: 18, marginBottom: 4 }}>
      <div>
        <h2 className="st-sec" style={{ margin: 0 }}>
          {title}
        </h2>
        <div className="hint" style={{ marginTop: 2 }}>
          {hint}
        </div>
      </div>
      <Button variant="btn-ghost" size="sm" icon="plus" onClick={onAdd}>
        {addLabel}
      </Button>
    </div>
  );
}

/** Card chrome shared by every collection-item editor (outlined Mono surface). */
function ItemCard({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        background: "var(--surface)",
        padding: 12,
        marginBottom: 10,
      }}
    >
      {children}
    </div>
  );
}

function PlainField({
  label,
  value,
  onChange,
  multiline = false,
  rows = 3,
  mono = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  rows?: number;
  mono?: boolean;
}) {
  const style: CSSProperties | undefined = mono
    ? { fontFamily: "var(--font-mono)" }
    : undefined;
  return (
    <div className="st-field" style={{ marginBottom: 8 }}>
      <label className="flabel">{label}</label>
      {multiline ? (
        <textarea
          className="inputctl st-ta"
          rows={rows}
          aria-label={label}
          style={style}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className="inputctl st-in"
          aria-label={label}
          style={style}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

const CALLOUT_LEVELS: { id: HowToOverrideCallout["level"]; label: string }[] = [
  { id: "info", label: "info" },
  { id: "warning", label: "warning" },
  { id: "success", label: "success" },
];

function CalloutEditor({
  item,
  onChange,
  onRemove,
}: {
  item: HowToOverrideCallout;
  onChange: (value: HowToOverrideCallout) => void;
  onRemove: () => void;
}) {
  return (
    <ItemCard>
      <div className="st-field" style={{ marginBottom: 8 }}>
        <label className="flabel">Callout ID · severity</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            className="inputctl st-in"
            aria-label="Callout ID"
            style={{ flex: "1 1 160px" }}
            value={item.id}
            onChange={(e) => onChange({ ...item, id: e.target.value })}
          />
          <span className="seg" role="group" aria-label="Callout severity">
            {CALLOUT_LEVELS.map((level) => (
              <button
                key={level.id}
                type="button"
                className={item.level === level.id ? "on" : undefined}
                aria-pressed={item.level === level.id}
                onClick={() => onChange({ ...item, level: level.id })}
              >
                {level.label}
              </button>
            ))}
          </span>
        </div>
      </div>
      <LocalizedTextField
        label="Callout title"
        value={item.title}
        onChange={(value) => onChange({ ...item, title: value })}
      />
      <LocalizedLinesField
        label="Callout body · one bullet per line"
        value={item.body}
        onChange={(value) => onChange({ ...item, body: value })}
      />
      <Button variant="btn-danger" size="sm" icon="x" onClick={onRemove}>
        Remove callout
      </Button>
    </ItemCard>
  );
}

function CommandEditor({
  item,
  onChange,
  onRemove,
}: {
  item: HowToOverrideCommand;
  onChange: (value: HowToOverrideCommand) => void;
  onRemove: () => void;
}) {
  return (
    <ItemCard>
      <PlainField
        label="Command ID"
        value={item.id}
        onChange={(value) => onChange({ ...item, id: value })}
      />
      <LocalizedTextField
        label="Command label"
        value={item.label}
        onChange={(value) => onChange({ ...item, label: value })}
      />
      <LocalizedTextField
        label="Command description"
        multiline
        rows={2}
        value={item.description}
        onChange={(value) => onChange({ ...item, description: value })}
      />
      <PlainField
        label="Command · shell / CLI"
        multiline
        rows={3}
        mono
        value={item.command}
        onChange={(value) => onChange({ ...item, command: value })}
      />
      <Button variant="btn-danger" size="sm" icon="x" onClick={onRemove}>
        Remove command
      </Button>
    </ItemCard>
  );
}

function ExampleEditor({
  item,
  onChange,
  onRemove,
}: {
  item: HowToOverrideExample;
  onChange: (value: HowToOverrideExample) => void;
  onRemove: () => void;
}) {
  return (
    <ItemCard>
      <PlainField
        label="Example ID"
        value={item.id}
        onChange={(value) => onChange({ ...item, id: value })}
      />
      <LocalizedTextField
        label="Example title"
        value={item.title}
        onChange={(value) => onChange({ ...item, title: value })}
      />
      <LocalizedLinesField
        label="Example bullets · one per line"
        value={item.bullets}
        onChange={(value) => onChange({ ...item, bullets: value })}
      />
      <Button variant="btn-danger" size="sm" icon="x" onClick={onRemove}>
        Remove example
      </Button>
    </ItemCard>
  );
}

function ScreenshotEditor({
  item,
  canEdit,
  uploadPending,
  onChange,
  onRemove,
  onUpload,
}: {
  item: HowToOverrideScreenshot;
  canEdit: boolean;
  uploadPending: boolean;
  onChange: (value: HowToOverrideScreenshot) => void;
  onRemove: () => void;
  onUpload: (file: File) => Promise<void>;
}) {
  async function handleFileInput(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) return;
    await onUpload(file);
    event.target.value = "";
  }

  return (
    <ItemCard>
      <PlainField
        label="Screenshot ID"
        value={item.id}
        onChange={(value) => onChange({ ...item, id: value })}
      />
      <PlainField
        label="Screenshot URL"
        value={item.src}
        onChange={(value) => onChange({ ...item, src: value })}
        mono
      />
      {item.src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.src}
          alt={item.alt.en || "Screenshot preview"}
          style={{
            maxWidth: "100%",
            maxHeight: 160,
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            marginBottom: 8,
            display: "block",
          }}
        />
      ) : null}
      <LocalizedTextField
        label="Alt text"
        value={item.alt}
        onChange={(value) => onChange({ ...item, alt: value })}
      />
      <LocalizedTextField
        label="Caption"
        multiline
        rows={2}
        value={item.caption}
        onChange={(value) => onChange({ ...item, caption: value })}
      />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <label
          className={cn("btn", "btn-ghost", "btn-sm")}
          style={{
            cursor: canEdit && !uploadPending ? "pointer" : "not-allowed",
            opacity: canEdit && !uploadPending ? 1 : 0.55,
          }}
        >
          <Icon name="upload" className="ico" />
          {uploadPending ? "Uploading…" : "Upload asset"}
          <input
            type="file"
            accept="image/*"
            hidden
            disabled={!canEdit || uploadPending}
            data-testid={`screenshot-upload-${item.id}`}
            onChange={(event) => void handleFileInput(event)}
          />
        </label>
        <Button variant="btn-danger" size="sm" icon="x" onClick={onRemove}>
          Remove screenshot
        </Button>
      </div>
    </ItemCard>
  );
}

/* -------------------------------------------------------- preview render ----- */

/**
 * Read-side article rendering on the Mono `.ht-article` markup (identical kit to
 * HowTo.tsx ArticleView), driven by the override-applied preview article. Commands
 * get a working Copy button; screenshots open the zoom dialog.
 */
function ArticlePreview({
  article,
  locale,
  onZoom,
}: {
  article: HowToArticle;
  locale: HowToLocale;
  onZoom: (screenshot: HowToOverrideScreenshot) => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const copyCommand = useCallback((id: string, cmd: string) => {
    const announce = () => {
      setCopied(id);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(null), 1500);
    };
    try {
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(cmd).then(announce, announce);
        return;
      }
    } catch {
      /* fall through to legacy path */
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = cmd;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* ignore */
      }
      ta.remove();
    } catch {
      /* ignore */
    }
    announce();
  }, []);

  const title = loc(article.title, locale);
  const summary = loc(article.summary, locale);
  const purpose = locLines(article.purpose, locale);
  const workflow = locLines(article.workflow, locale);
  const callouts = article.callouts ?? [];
  const commands = article.commands ?? [];
  const localeGaps = articleHasLocaleGaps(article, locale);

  return (
    <article className="ht-article" aria-labelledby="st-pv-title">
      <div className="ht-meta">
        <Tag>{article.topic}</Tag>
        {article.keywords.slice(0, 3).map((k) => (
          <Tag key={k}>{k}</Tag>
        ))}
        {localeGaps && <Tag>RU gaps → EN fallback</Tag>}
      </div>
      <h1 id="st-pv-title">
        {title || <span style={{ color: "var(--fg-subtle)" }}>Untitled</span>}
      </h1>
      {summary ? <p className="ht-summary">{summary}</p> : null}

      {callouts.map((c) => {
        // Mirror the live reader (HowTo.tsx `calloutVariant`): only `warn` and `info`
        // are styled in mono.css, and the reader collapses `success` → info-styled box
        // with the info icon. Keeping the same mapping here makes the Studio preview
        // match exactly what published users see (no unstyled `ok` class / check glyph).
        const variant = c.level === "warning" ? "warn" : "info";
        const iconName: IconName = c.level === "warning" ? "alert" : "info";
        const body = locLines(c.body, locale);
        return (
          <div className={cn("ht-callout", variant)} key={c.id} role="note">
            <Icon name={iconName} />
            <div>
              <div className="hc-t">{loc(c.title, locale)}</div>
              {body.map((line, i) => (
                <div className="hc-b" key={i}>
                  {line}
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {purpose.length > 0 && (
        <>
          <div className="ht-h">{locale === "ru" ? "Зачем это" : "Why this exists"}</div>
          <ul className="ht-purpose">
            {purpose.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </>
      )}

      {workflow.length > 0 && (
        <>
          <div className="ht-h">{locale === "ru" ? "Шаги" : "Workflow steps"}</div>
          <ol className="ht-steps">
            {workflow.map((s, i) => (
              <li key={i}>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </>
      )}

      {commands.length > 0 && (
        <>
          <div className="ht-h">{locale === "ru" ? "Команды" : "Commands"}</div>
          {commands.map((command) => {
            const isCopied = copied === command.id;
            const label = loc(command.label, locale);
            const description = loc(command.description, locale);
            return (
              <div className="ht-cmd" key={command.id}>
                <div className="hcmd-h">
                  <span>{label || command.id}</span>
                  <button
                    type="button"
                    className="hcmd-copy"
                    aria-label={isCopied ? `${label} copied to clipboard` : `Copy command: ${label}`}
                    onClick={() => copyCommand(command.id, command.command)}
                  >
                    {isCopied
                      ? locale === "ru"
                        ? "Скопировано"
                        : "Copied"
                      : locale === "ru"
                        ? "Копировать"
                        : "Copy"}
                  </button>
                </div>
                {description ? (
                  <div
                    className="muted-note"
                    style={{ padding: "6px 11px 0" }}
                  >
                    {description}
                  </div>
                ) : null}
                <pre>{command.command}</pre>
              </div>
            );
          })}
        </>
      )}

      {article.examples.length > 0 && (
        <>
          <div className="ht-h">{locale === "ru" ? "Примеры" : "Examples"}</div>
          {article.examples.map((example) => {
            const bullets = locLines(example.bullets, locale);
            return (
              <div className="ht-example" key={example.id}>
                <div className="he-t">{loc(example.title, locale)}</div>
                {bullets.map((b, i) => (
                  <div className="he-b" key={i}>
                    {b}
                  </div>
                ))}
              </div>
            );
          })}
        </>
      )}

      {article.screenshots.length > 0 && (
        <div className="ht-screens">
          <div className="ht-h">{locale === "ru" ? "Скриншоты" : "Screenshots"}</div>
          {article.screenshots.map((shot) => (
            <div className="ht-shot" key={shot.id}>
              {shot.src ? (
                <button
                  type="button"
                  onClick={() => onZoom(shot)}
                  aria-label={`Open ${loc(shot.caption, locale) || loc(shot.alt, locale) || "screenshot"} at full size`}
                  style={{
                    display: "block",
                    width: "100%",
                    padding: 0,
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--surface)",
                    cursor: "zoom-in",
                    overflow: "hidden",
                  }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={shot.src}
                    alt={loc(shot.alt, locale) || "Screenshot"}
                    style={{ width: "100%", display: "block" }}
                  />
                </button>
              ) : (
                <div className="ht-shot-ph">
                  <Icon name="grid" />
                  <span>{locale === "ru" ? "Скриншот экрана" : "Screen capture"}</span>
                </div>
              )}
              {loc(shot.caption, locale) ? (
                <div className="muted-note" style={{ marginTop: 4 }}>
                  {loc(shot.caption, locale)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

/** Full-size screenshot zoom on the Mono `.modal-overlay` chrome (Esc / backdrop to close). */
function ScreenshotZoom({
  screenshot,
  locale,
  onClose,
}: {
  screenshot: HowToOverrideScreenshot;
  locale: HowToLocale;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const caption = loc(screenshot.caption, locale) || loc(screenshot.alt, locale) || "Screenshot";

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={caption}
        style={{ maxWidth: "min(1100px, 92vw)", width: "auto" }}
      >
        <div className="modal-head">
          <div className="modal-title">{caption}</div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body" style={{ display: "flex", justifyContent: "center" }}>
          {screenshot.src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={screenshot.src}
              alt={loc(screenshot.alt, locale) || caption}
              style={{ maxWidth: "100%", maxHeight: "76vh", borderRadius: "var(--radius-sm)" }}
            />
          ) : (
            <p className="muted-note">No image URL set for this screenshot.</p>
          )}
        </div>
      </div>
    </div>
  );
}
