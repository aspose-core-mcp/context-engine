"use client";

import { Fragment, useState, type ReactNode } from "react";

import { getAdminErrorMessage } from "@/components/admin-console.utils";
import { useLanguageRegistries } from "@/hooks/useLanguageRegistries";
import { AdminApiError } from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { IconButton } from "../components/IconButton";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import {
  EmptyState,
  ErrorState,
  PermissionDenied,
  ReadonlyBanner,
  Skeleton,
} from "../components/states";
import { ShowMoreRow, Table, TableCard } from "../components/Table";
import { Tag } from "../components/Tag";
import { Icon } from "../lib/icons";
import { PopoverPanel, usePopover } from "../shell/Popover";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useConfirm, useToast } from "../shell/overlays";

type LanguageRegistries = ReturnType<typeof useLanguageRegistries>;

// ───────────────────────────────────────────────────────────────── Fixtures ──

interface ProductRow {
  id: string;
  family: string;
  familyDir: string;
  kinds: string[];
  repos: number;
  // API limitation: useLanguageRegistries exposes no product list, so the example
  // repository ids are fixture-only.
  repoIds: string[];
}

// Product registry rows (offline dataset), in display order.
const PRODUCTS: ProductRow[] = [
  { id: "aspose.3d", family: "aspose", familyDir: "Aspose.3D", kinds: ["apiref"], repos: 1, repoIds: ["aspose.3d.apiref"] },
  { id: "aspose.barcode", family: "aspose", familyDir: "Aspose.BarCode", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.barcode.apiref", "aspose.barcode.docs"] },
  { id: "aspose.cad", family: "aspose", familyDir: "Aspose.CAD", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.cad.apiref", "aspose.cad.docs"] },
  { id: "aspose.cells", family: "aspose", familyDir: "Aspose.Cells", kinds: ["apiref"], repos: 1, repoIds: ["aspose.cells.apiref"] },
  { id: "aspose.ocr", family: "aspose", familyDir: "Aspose.OCR", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.ocr.apiref", "aspose.ocr.docs"] },
  { id: "groupdocs.parser", family: "groupdocs", familyDir: "GroupDocs.Parser", kinds: ["apiref", "docs"], repos: 2, repoIds: ["groupdocs.parser.apiref", "groupdocs.parser.docs"] },
  { id: "groupdocs.viewer", family: "groupdocs", familyDir: "GroupDocs.Viewer", kinds: ["apiref", "docs"], repos: 2, repoIds: ["groupdocs.viewer.apiref", "groupdocs.viewer.docs"] },
  { id: "aspose.words", family: "aspose", familyDir: "Aspose.Words", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.words.apiref", "aspose.words.docs"] },
  { id: "aspose.pdf", family: "aspose", familyDir: "Aspose.PDF", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.pdf.apiref", "aspose.pdf.docs"] },
  { id: "aspose.slides", family: "aspose", familyDir: "Aspose.Slides", kinds: ["apiref"], repos: 1, repoIds: ["aspose.slides.apiref"] },
  { id: "aspose.email", family: "aspose", familyDir: "Aspose.Email", kinds: ["apiref", "docs"], repos: 2, repoIds: ["aspose.email.apiref", "aspose.email.docs"] },
  { id: "groupdocs.viewer.net", family: "groupdocs", familyDir: "GroupDocs.Conversion", kinds: ["apiref"], repos: 1, repoIds: ["groupdocs.conversion.net.apiref"] },
];

const VISIBLE_PRODUCTS = 7;

// Dictionary entry: id + human-readable display name + enabled flag (display name
// and enabled/disabled status are shown per entry).
interface DictEntry {
  id: string;
  name: string;
  enabled: boolean;
}

// Offline fallback for the canonical language dictionary. Live entries
// (RegistryLanguage with display_name + enabled) override these wholesale.
const INITIAL_LANG_ENTRIES: DictEntry[] = [
  { id: "net", name: ".NET", enabled: true },
  { id: "java", name: "Java", enabled: true },
  { id: "python", name: "Python", enabled: true },
  { id: "cpp", name: "C++", enabled: true },
  { id: "php", name: "PHP", enabled: true },
  { id: "nodejs", name: "Node.js", enabled: false },
];

// Offline fallback for the documentation-locale dictionary.
const INITIAL_LOCALE_ENTRIES: DictEntry[] = [
  { id: "en", name: "English", enabled: true },
  { id: "ru", name: "Русский", enabled: true },
  { id: "zh", name: "中文", enabled: true },
  { id: "de", name: "Deutsch", enabled: true },
  { id: "es", name: "Español", enabled: false },
];

interface AliasRow {
  product: string;
  external: string;
  canonical: string; // "—" = unmapped
}

const INITIAL_ALIASES: AliasRow[] = [
  { product: "aspose.ocr", external: "c#", canonical: "net" },
  { product: "aspose.ocr", external: "csharp", canonical: "net" },
  { product: "aspose.ocr", external: "py", canonical: "python" },
  { product: "aspose.cells", external: "c++", canonical: "cpp" },
  { product: "aspose.words", external: "golang", canonical: "—" },
];

const ALIAS_PRODUCTS = ["aspose.ocr", "aspose.cells", "aspose.words"];
const CANONICAL_OPTIONS = ["net", "java", "python", "cpp"];

// ──────────────────────────────────────── Per-subsection How-To help popover ──
// Reuses the shell Popover classes (.pop / .pop-head / .pop-body / .pop-sub /
// .pop-foot); Esc + outside-click close handled by usePopover. Provides the
// "?" help affordance per subsection.
interface HelpItem {
  q: string;
  a: ReactNode;
}
function HelpPopover({ title, items }: { title: string; items: HelpItem[] }) {
  const pop = usePopover();
  return (
    <div ref={pop.wrapRef} style={{ position: "relative" }}>
      <IconButton
        icon="info"
        aria-label={`Help: ${title}`}
        aria-haspopup="menu"
        aria-expanded={pop.open}
        onClick={pop.toggle}
      />
      {pop.open && (
        <PopoverPanel>
          <div className="pop-head">
            <span className="pt">{title}</span>
            <span className="ps">runbook</span>
          </div>
          <div className="pop-body" role="document">
            {items.map((it) => (
              <div key={it.q} style={{ padding: "6px 0" }}>
                <div className="pop-sub" style={{ margin: "0 0 3px" }}>
                  {it.q}
                </div>
                <div style={{ fontSize: 12, color: "var(--fg-muted)", lineHeight: 1.5 }}>{it.a}</div>
              </div>
            ))}
          </div>
          <div className="pop-foot">
            <a href="/howto" className="btn btn-ghost btn-sm" style={{ textDecoration: "none" }}>
              <Icon name="arrow" className="ico" />
              Open full How-To
            </a>
          </div>
        </PopoverPanel>
      )}
    </div>
  );
}

// Read-only-database mutation failure detection ("Readonly database" state: if
// Postgres is read-only, mutation.isError is set). Postgres surfaces this as a
// "read-only transaction" message and the gateway forwards it (optionally as 503),
// so match the wire text (error message contains 'read-only' or 'readonly') plus
// the 503 Service Unavailable status.
function isReadonlyDbError(error: unknown): boolean {
  if (error instanceof AdminApiError && error.status === 503) return true;
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  return (
    message.includes("read-only") || message.includes("readonly") || message.includes("read only")
  );
}

// ────────────────────────────────────────────── Inline mutation error alert ──
// The in-section Alert for failed registry mutations ("Language deletion
// conflict"). Renders from the
// mutation's isError state, so it appears only after the request settles and
// auto-clears when the next attempt starts. A 409 CONFLICT swaps in the
// conflict copy (same markup as the LanguagesConflict harness below); a
// read-only-database failure swaps in the dedicated "Readonly database"
// copy (takes precedence — it is the more specific, actionable condition).
function MutationErrorAlert({
  error,
  title,
  fallback,
  conflictTitle,
  conflictCause,
}: {
  error: unknown;
  title: ReactNode;
  fallback: string;
  conflictTitle?: ReactNode;
  conflictCause?: ReactNode;
}) {
  const readonly = isReadonlyDbError(error);
  const conflict = !readonly && error instanceof AdminApiError && error.status === 409;
  if (readonly) {
    return (
      <div style={{ margin: "10px 0 4px" }}>
        <ErrorState
          title="Database is in read-only mode"
          text="Configuration changes are temporarily unavailable. Contact support if this persists."
          cause="the metadata database is in read-only mode — mutations are rejected"
        />
      </div>
    );
  }
  return (
    <div style={{ margin: "10px 0 4px" }}>
      <ErrorState
        title={conflict && conflictTitle ? conflictTitle : title}
        text={getAdminErrorMessage(error, fallback)}
        cause={conflict ? conflictCause : undefined}
      />
    </div>
  );
}

// ───────────────────────────────────────────────────── Product registry card ──

// API limitation: useLanguageRegistries exposes no product list — the registry table
// is fixture-only.
function ProductRegistry() {
  const head = PRODUCTS.slice(0, VISIBLE_PRODUCTS);
  const rest = PRODUCTS.slice(VISIBLE_PRODUCTS);

  const renderRow = (p: ProductRow, i: number) => (
    <tr className="data" key={p.id}>
      <td className="num">{i + 1}</td>
      <td>
        <span className="repo-id">{p.id}</span>
      </td>
      <td>
        <Tag>{p.family}</Tag>
      </td>
      <td className="mono" style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}>
        {p.familyDir}
      </td>
      <td>
        {p.kinds.map((k) => (
          <Tag key={k}>{k}</Tag>
        ))}
      </td>
      <td>
        <div className="tile-pillrow">
          {p.repoIds.map((r) => (
            <span className="repo-id" key={r} style={{ fontSize: "11px", color: "var(--fg-muted)" }}>
              {r}
            </span>
          ))}
        </div>
      </td>
      <td className="num">{p.repos}</td>
    </tr>
  );

  return (
    <Card
      title="Product registry"
      sub={`42 products across aspose & groupdocs families · showing ${VISIBLE_PRODUCTS}`}
      flush
      right={
        <HelpPopover
          title="Registered products"
          items={[
            {
              q: "Why",
              a: "Confirm a product exists and see its scope (family, source kinds, example repos) before creating or editing its language aliases.",
            },
            {
              q: "What",
              a: "Each row is a product known to ingestion — product id, family, family dir, source kinds, example repository ids and repo count.",
            },
            {
              q: "How",
              a: "This list is shared with Ingestion Jobs; if a product is missing, register its repositories there first, then return to map aliases.",
            },
          ]}
        />
      }
    >
      <TableCard>
        <Table>
          <thead>
            <tr>
              <th className="num" style={{ width: 40 }}>
                #
              </th>
              <th>Product ID</th>
              <th style={{ width: 110 }}>Family</th>
              <th style={{ width: 150 }}>Family dir</th>
              <th style={{ width: 130 }}>Source kinds</th>
              <th>Example repos</th>
              <th className="num" style={{ width: 64 }}>
                Repos
              </th>
            </tr>
          </thead>
          <tbody>
            {head.map(renderRow)}
            <ShowMoreRow
              count={rest.length}
              colSpan={7}
              extra={rest.map((p, i) => renderRow(p, VISIBLE_PRODUCTS + i))}
            />
          </tbody>
        </Table>
      </TableCard>
    </Card>
  );
}

// ─────────────────────────────────────────────── Canonical dictionaries card ──

function CanonicalDictionaries({
  reg,
  canWrite,
  online,
}: {
  reg: LanguageRegistries;
  canWrite: boolean;
  online: boolean;
}) {
  const { confirm } = useConfirm();
  const { toast } = useToast();

  // Live dictionary entries (RegistryLanguage/RegistryLocale carry display_name +
  // enabled, which the hook's *Options string[] drop). Map them to DictEntry so
  // each chip can show its display name and enabled/disabled status.
  const liveLangEntries: DictEntry[] = (reg.registryLanguagesQuery.data ?? []).map((l) => ({
    id: l.lang_id,
    name: l.display_name,
    enabled: l.enabled,
  }));
  const liveLocaleEntries: DictEntry[] = (reg.registryLocalesQuery.data ?? []).map((l) => ({
    id: l.locale_id,
    name: l.display_name,
    enabled: l.enabled,
  }));
  // Live vs fixture: with a live session the dictionaries render live entries ONLY —
  // a legitimately empty live registry shows the implicit-empty list
  // ("0 registered", no chips), never fixtures. Fixtures are the OFFLINE dataset
  // (session absent → queries disabled).
  const langEntries = online ? liveLangEntries : INITIAL_LANG_ENTRIES;
  const localeEntries = online ? liveLocaleEntries : INITIAL_LOCALE_ENTRIES;
  const langs = langEntries.map((e) => e.id);
  const locales = localeEntries.map((e) => e.id);

  // Add inputs drive the hook's own state — the upsert mutations read from it.
  const langId = reg.newLangId;
  const langName = reg.newLangName;
  const localeId = reg.newLocaleId;
  const localeName = reg.newLocaleName;

  const writeHint = reg.registryWriteDisabledReason ?? undefined;

  // Missing-authorization state: for an online under-scoped key, show a proactive
  // warning Banner IN PLACE OF the add-forms rather than leaving editable inputs
  // behind a hover-only hint. Offline (no session → canWrite permissive) keeps the
  // forms enabled on fixtures.
  const showSuperuserWarning = online && !canWrite;

  // Real-time duplicate detection for the id fields (validates against existing
  // language IDs and shows a helper note on a duplicate). A trimmed, non-empty id already present
  // in the registry blocks submission and surfaces an inline helper note.
  const langDuplicate = langId.trim() !== "" && langs.includes(langId.trim());
  const localeDuplicate = localeId.trim() !== "" && locales.includes(localeId.trim());

  // Pending-mutation gating ("Mutation in progress" state, buttons disabled
  // while mutation.isPending): disable the Add buttons
  // while the upsert is in flight so rapid clicks can't double-submit.
  const langPending = reg.upsertLanguageMutation.isPending;
  const localePending = reg.upsertLocaleMutation.isPending;

  function addLang() {
    const id = langId.trim();
    if (!id || langs.includes(id)) return;
    if (!online) {
      // Offline demo no-op (no backend to settle against): mirror the hook's
      // onSuccess side effects so the flow stays exercisable.
      reg.setNewLangId("");
      reg.setNewLangName("");
      toast(`Added language ${id}`);
      return;
    }
    reg.upsertLanguageMutation.mutate(undefined, {
      onSuccess: () => toast(`Added language ${id}`),
    });
  }

  function addLocale() {
    const id = localeId.trim();
    if (!id || locales.includes(id)) return;
    if (!online) {
      reg.setNewLocaleId("");
      reg.setNewLocaleName("");
      toast(`Added locale ${id}`);
      return;
    }
    reg.upsertLocaleMutation.mutate(undefined, {
      onSuccess: () => toast(`Added locale ${id}`),
    });
  }

  function removeLang(id: string) {
    confirm({
      title: "Delete programming language",
      tone: "danger",
      word: "DELETE",
      icon: "alert",
      summary: (
        <>
          removing canonical language <b>{id}</b>
          <br />
          from the global registry
        </>
      ),
      body: "Deletion fails if any product alias still resolves to this language — delete those aliases first. After removal, indexing and retrieval can no longer reference this id.",
      confirmLabel: "Delete language",
      // Success toast fires ONLY after the DELETE settles successfully — a 409
      // (language still referenced by aliases) or any other failure surfaces the
      // inline conflict alert below instead. Offline is a demo no-op.
      onConfirm: () => {
        if (!online) {
          toast(`Language ${id} deleted`);
          return;
        }
        reg.deleteLanguageMutation.mutate(id, {
          onSuccess: () => toast(`Language ${id} deleted`),
        });
      },
    });
  }

  function removeLocale(id: string) {
    confirm({
      title: "Delete documentation locale",
      tone: "danger",
      word: "DELETE",
      icon: "alert",
      summary: (
        <>
          removing locale <b>{id}</b>
          <br />
          from the global registry
        </>
      ),
      body: "Verify no active product or ingestion depends on this locale before removing it. Documentation in this locale will no longer be associated after deletion.",
      confirmLabel: "Delete locale",
      onConfirm: () => {
        if (!online) {
          toast(`Locale ${id} deleted`);
          return;
        }
        reg.deleteLocaleMutation.mutate(id, {
          onSuccess: () => toast(`Locale ${id} deleted`),
        });
      },
    });
  }

  // One dictionary chip: id (primary) + display name + enabled/disabled status
  // pill + removable affordance (display name + enabled/disabled status alongside
  // each ID).
  function dictChips(
    entries: DictEntry[],
    kind: "language" | "locale",
    onRemove: (id: string) => void,
    pending: boolean,
    pendingHint: string,
    deletingId: string | undefined,
  ) {
    // Surface the in-flight DELETE message for authorized users too, not just the
    // missing-scope hint ("Mutation in progress" state).
    const removeHint = !canWrite ? writeHint : pending ? pendingHint : undefined;
    return (
      <div className="tile-pillrow" style={{ margin: "8px 0 12px", gap: 8 }}>
        {entries.map((e) => {
          // Per-row in-flight progress ("Mutation in progress" state): the
          // delete mutation's variable is the entry id, so only the chip actually
          // being removed swaps its × affordance to the spinning refresh icon.
          const rowDeleting = pending && deletingId === e.id;
          return (
            <span
              key={e.id}
              className="tag"
              style={{ gap: 7, alignItems: "center" }}
              title={`${e.name} · ${e.enabled ? "enabled" : "disabled"}`}
            >
              <span className="mono" style={{ fontWeight: 600 }}>
                {e.id}
              </span>
              <span style={{ color: "var(--fg-subtle)", fontSize: "11px" }}>{e.name}</span>
              <Pill variant={e.enabled ? "ok" : "neutral"}>
                {e.enabled ? "enabled" : "disabled"}
              </Pill>
              <button
                type="button"
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  display: "inline-flex",
                  color: "var(--fg-subtle)",
                  cursor: canWrite && !pending ? "pointer" : "not-allowed",
                }}
                aria-label={`Remove ${kind} ${e.id} (${e.name})`}
                disabled={!canWrite || pending}
                title={removeHint}
                aria-busy={rowDeleting}
                onClick={() => onRemove(e.id)}
              >
                <Icon name={rowDeleting ? "refresh" : "x"} className="ico" />
              </button>
            </span>
          );
        })}
      </div>
    );
  }

  return (
    <Card
      title="Canonical dictionaries"
      sub="Programming languages and documentation locales used across normalization."
      right={
        <HelpPopover
          title="Canonical dictionaries"
          items={[
            {
              q: "Why",
              a: "These are the authoritative language ids and documentation locales every product and the public query API must reference; a mismatch breaks language-filtered search.",
            },
            {
              q: "What",
              a: "Each entry shows its canonical id, human-readable display name and enabled/disabled status. Ids are immutable; add a new one before products can alias to it.",
            },
            {
              q: "How",
              a: "Use lowercase canonical ids (e.g. python, c++, zh-hant). Deletion is superuser-only and is blocked while any alias still resolves to the language — clear those aliases first.",
            },
          ]}
        />
      }
    >
      {showSuperuserWarning && (
        <div style={{ marginBottom: 12 }}>
          <Banner
            variant="warn"
            icon="alert"
            title="Global language registry is superuser-only. Your key cannot modify this dictionary."
            text="You can audit the registered languages and locales below, but adding or removing canonical entries needs a superuser key."
          />
        </div>
      )}
      <div>
        <div className="flabel">
          Programming languages{" "}
          <span style={{ color: "var(--fg-subtle)" }}>· {langs.length} registered</span>
        </div>
        {dictChips(
          langEntries,
          "language",
          removeLang,
          reg.deleteLanguageMutation.isPending,
          "Registry update is in progress.",
          reg.deleteLanguageMutation.variables,
        )}
        {/* 409-conflict alert ("Language
            deletion conflict"): renders live whenever the delete mutation errors,
            below the registered-languages list. */}
        {reg.deleteLanguageMutation.isError && (
          <MutationErrorAlert
            error={reg.deleteLanguageMutation.error}
            title="Couldn't delete language"
            fallback="Failed to delete language."
            conflictTitle="Cannot delete language: it is still referenced"
            conflictCause="language_in_use — alias references must be cleared before deletion"
          />
        )}
        {!showSuperuserWarning && (
          <>
            <div className="toolbar" style={{ margin: 0 }}>
              <Input
                label="lang_id"
                width={160}
                placeholder="e.g. csharp"
                value={langId}
                onChange={(e) => reg.setNewLangId(e.target.value)}
                aria-invalid={langDuplicate || undefined}
              />
              <Input
                label="display_name"
                width={180}
                placeholder="C#"
                value={langName}
                onChange={(e) => reg.setNewLangName(e.target.value)}
              />
              <Button
                variant="btn-ghost"
                size="sm"
                icon={langPending ? "refresh" : "plus"}
                disabled={langId.trim() === "" || langDuplicate || !canWrite || langPending}
                title={writeHint}
                aria-busy={langPending}
                onClick={addLang}
              >
                {langPending ? "Adding…" : "Add language"}
              </Button>
            </div>
            {/* Real-time duplicate validation (helper note on a duplicate id): a no-op submit is otherwise
                silent, so flag the collision before the user clicks Add. */}
            {langDuplicate && (
              <div className="muted-note" style={{ marginTop: 6 }} role="note">
                <Icon name="alert" className="ico" /> ID &lsquo;{langId.trim()}&rsquo; already exists in
                the registry.
              </div>
            )}
          </>
        )}
        {reg.upsertLanguageMutation.isError && (
          <MutationErrorAlert
            error={reg.upsertLanguageMutation.error}
            title="Couldn't register language"
            fallback="Failed to register language."
          />
        )}
      </div>

      <div
        style={{
          marginTop: 18,
          paddingTop: 16,
          borderTop: "1px solid var(--border)",
        }}
      >
        <div className="flabel">
          Documentation locales{" "}
          <span style={{ color: "var(--fg-subtle)" }}>· {locales.length} registered</span>
        </div>
        {dictChips(
          localeEntries,
          "locale",
          removeLocale,
          reg.deleteLocaleMutation.isPending,
          "Registry update is in progress.",
          reg.deleteLocaleMutation.variables,
        )}
        {/* Locale-delete failures surface below the registered-locales list
            (alert below the accordion). */}
        {reg.deleteLocaleMutation.isError && (
          <MutationErrorAlert
            error={reg.deleteLocaleMutation.error}
            title="Couldn't delete locale"
            fallback="Failed to delete locale."
            conflictTitle="Cannot delete locale: it is still in use"
            conflictCause="locale references must be cleared before deletion"
          />
        )}
        {!showSuperuserWarning && (
          <>
            <div className="toolbar" style={{ margin: 0 }}>
              <Input
                label="locale_id"
                width={160}
                placeholder="e.g. ru"
                value={localeId}
                onChange={(e) => reg.setNewLocaleId(e.target.value)}
                aria-invalid={localeDuplicate || undefined}
              />
              <Input
                label="display_name"
                width={180}
                placeholder="Русский"
                value={localeName}
                onChange={(e) => reg.setNewLocaleName(e.target.value)}
              />
              <Button
                variant="btn-ghost"
                size="sm"
                icon={localePending ? "refresh" : "plus"}
                disabled={localeId.trim() === "" || localeDuplicate || !canWrite || localePending}
                title={writeHint}
                aria-busy={localePending}
                onClick={addLocale}
              >
                {localePending ? "Adding…" : "Add locale"}
              </Button>
            </div>
            {localeDuplicate && (
              <div className="muted-note" style={{ marginTop: 6 }} role="note">
                <Icon name="alert" className="ico" /> ID &lsquo;{localeId.trim()}&rsquo; already exists in
                the registry.
              </div>
            )}
          </>
        )}
        {reg.upsertLocaleMutation.isError && (
          <MutationErrorAlert
            error={reg.upsertLocaleMutation.error}
            title="Couldn't register locale"
            fallback="Failed to register locale."
          />
        )}
      </div>
    </Card>
  );
}

// ──────────────────────────────────────────────── Per-product alias mapping ──

function AliasMapping({
  reg,
  product,
  setProduct,
  canWrite,
  online,
}: {
  reg: LanguageRegistries;
  product: string;
  setProduct: (value: string) => void;
  canWrite: boolean;
  online: boolean;
}) {
  const { confirm } = useConfirm();
  const { toast } = useToast();

  // Hook owns the upsert payload fields; bind inputs to them.
  const external = reg.aliasExternalId;
  const canonical = reg.aliasCanonicalId;

  // Canonical options from the live language registry; fixtures only OFFLINE. A
  // live-but-empty registry leaves zero options, so the alias-form
  // validation ("Must select an existing canonical language…") kicks in instead
  // of offering phantom fixture ids.
  const canonicalOptions = online ? reg.registryLanguageOptions : CANONICAL_OPTIONS;

  // Live aliases for the selected product mapped to the row shape.
  const liveAliases: AliasRow[] = (reg.registryAliasesQuery.data ?? []).map((a) => ({
    product: a.product_id,
    external: a.external_language_id,
    canonical: a.canonical_lang_id || "—",
  }));
  // Live vs fixture: with a live session the table renders live rows ONLY — a
  // backend that successfully returns zero aliases gets the
  // "No aliases for this product" EmptyState, never
  // fixture rows. Fixtures are the OFFLINE dataset (session absent → query disabled).
  const source = online ? liveAliases : INITIAL_ALIASES;
  // The product Select drives the hook query key (server-filters online); apply the SAME
  // predicate to the display source so the selector filters fixtures client-side offline.
  const aliases = source.filter((a) => a.product === product);

  const writeHint = reg.aliasWriteDisabledReason ?? undefined;

  // State gates fire only online (offline the query is disabled → never
  // loading/error/success, so fixtures are never hidden). Online: loading →
  // skeleton; error → ErrorState with retry; success+empty →
  // EmptyState; success+data → live rows.
  const loading = online && reg.registryAliasesQuery.isLoading;
  const errored = online && reg.registryAliasesQuery.isError;
  const empty = online && reg.registryAliasesQuery.isSuccess && !aliases.length;

  // Per-switch loading affordance ("Loading aliases for selected
  // product"): a background refetch keeps the previous product's rows visible,
  // so isLoading is false while isFetching is true. Surface a caption then so
  // stale rows aren't mistaken for the newly-selected product. Offline the
  // query is disabled → isFetching is false → this never fires (fixtures show).
  const switching = reg.registryAliasesQuery.isFetching && !loading && !errored;

  // Alias-delete failure placement: the
  // error belongs next to the row it targets. The delete mutation's variable
  // is the row's external id; on failure that row stays in the table, so render
  // the alert as a sub-row directly beneath it. Only fall back to an above-table
  // alert if the targeted row is no longer present (so the error is never lost).
  const deleteAliasFailedId =
    reg.deleteAliasMutation.isError &&
    typeof reg.deleteAliasMutation.variables === "string"
      ? reg.deleteAliasMutation.variables
      : undefined;
  const deleteAliasErrorRowVisible =
    deleteAliasFailedId !== undefined && aliases.some((a) => a.external === deleteAliasFailedId);

  // Alias form validation: the selected
  // canonical must be an existing canonical language from the global registry.
  const canonicalValid = canonicalOptions.includes(canonical);
  const externalFilled = external.trim() !== "";
  // Pending-mutation gating ("Mutation in progress" state): block the Upsert
  // and per-row Remove while either alias mutation is in flight so rapid clicks
  // can't double-submit. aliasWriteDisabledReason already carries this message.
  const aliasPending = reg.upsertAliasMutation.isPending || reg.deleteAliasMutation.isPending;
  const upsertHint = !canWrite
    ? writeHint
    : aliasPending
      ? writeHint
      : !canonicalValid
        ? "Must select an existing canonical language from the global registry."
        : !externalFilled
          ? "Enter the product's external language identifier to alias."
          : undefined;
  const upsertDisabled = !canWrite || aliasPending || !canonicalValid || !externalFilled;
  // Surface the in-flight message to authorized users on the per-row Remove too.
  const removeHint = !canWrite ? writeHint : aliasPending ? writeHint : undefined;

  function upsert() {
    if (upsertDisabled) return;
    if (!online) {
      // Offline demo no-op: mirror the hook's onSuccess side effects.
      reg.setAliasExternalId("");
      toast("Alias mapping saved");
      return;
    }
    reg.upsertAliasMutation.mutate(undefined, {
      onSuccess: () => toast("Alias mapping saved"),
    });
  }

  function remove(a: AliasRow) {
    confirm({
      title: "Delete alias",
      tone: "danger",
      word: "DELETE",
      icon: "alert",
      summary: (
        <>
          product <b>{a.product}</b>
          <br />
          external alias <b>{a.external}</b>
          {a.canonical !== "—" && (
            <>
              {" "}
              → <b>{a.canonical}</b>
            </>
          )}
        </>
      ),
      body: "After deletion the external identifier no longer resolves to a canonical language during indexing. Code labelled with it stays unindexed until a new alias is created.",
      confirmLabel: "Delete alias",
      // Toast fires only once the DELETE settles successfully; failures surface
      // the inline alert above the table. Offline is a demo no-op.
      onConfirm: () => {
        if (!online) {
          toast("Alias removed");
          return;
        }
        reg.deleteAliasMutation.mutate(a.external, {
          onSuccess: () => toast("Alias removed"),
        });
      },
    });
  }

  return (
    <Card
      title="Per-product alias mapping"
      sub="Map external language strings (from client queries) to canonical ids. Upsert or delete per product."
      right={
        <HelpPopover
          title="Per-product language aliases"
          items={[
            {
              q: "Why",
              a: "A repository may name a language differently from the canonical id (e.g. python3_dev, cpp, csharp). An alias reconciles that so source code is indexed under the right language.",
            },
            {
              q: "What",
              a: "Each row maps {product}: {external_id} → {canonical_id}. Upsert overwrites an existing external-id mapping for the product; an unmapped alias falls back to the product default.",
            },
            {
              q: "How",
              a: "Pick the product, enter the external identifier, choose the canonical language, then Upsert. Editing aliases needs a write:settings key scoped to the product.",
            },
          ]}
        />
      }
    >
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <Select
          label="product_id"
          width={170}
          options={ALIAS_PRODUCTS}
          value={product}
          onChange={(e) => setProduct(e.target.value)}
        />
        <Input
          label="external alias"
          width={150}
          placeholder="e.g. c#"
          value={external}
          onChange={(e) => reg.setAliasExternalId(e.target.value)}
        />
        <Select
          label="canonical"
          width={150}
          options={canonicalOptions}
          value={canonical}
          onChange={(e) => reg.setAliasCanonicalId(e.target.value)}
        />
        <Button
          variant="btn-ghost"
          size="sm"
          icon={reg.upsertAliasMutation.isPending ? "refresh" : "plus"}
          disabled={upsertDisabled}
          title={upsertHint}
          aria-busy={reg.upsertAliasMutation.isPending}
          onClick={upsert}
        >
          {reg.upsertAliasMutation.isPending ? "Saving…" : "Upsert mapping"}
        </Button>
      </div>

      {/* Upsert failures (e.g. 400 unknown canonical_lang_id) surface inline below
          the form; the toast above fires only on settled success. */}
      {reg.upsertAliasMutation.isError && (
        <MutationErrorAlert
          error={reg.upsertAliasMutation.error}
          title="Couldn't save alias mapping"
          fallback="Failed to create or update alias."
        />
      )}

      {!canonicalValid && (
        <div className="muted-note" style={{ marginBottom: 10 }} role="note">
          <Icon name="alert" className="ico" /> Must select an existing canonical language from the
          global registry.
        </div>
      )}

      {switching && (
        <div className="muted-note" style={{ marginBottom: 10 }} role="status" aria-live="polite">
          <Icon name="refresh" className="ico" /> Loading aliases for {product}…
        </div>
      )}

      {/* Alias-delete failures surface next to the row they target (rendered as a
          sub-row inside the table below). This above-table alert is a fallback for
          the rare case where the targeted row is no longer present, so the error is
          never lost. The "Alias removed" toast never fires unless the DELETE
          actually succeeded. */}
      {reg.deleteAliasMutation.isError && !deleteAliasErrorRowVisible && (
        <MutationErrorAlert
          error={reg.deleteAliasMutation.error}
          title="Couldn't remove alias"
          fallback="Failed to delete alias."
        />
      )}

      <TableCard>
        {loading ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={4} />
          </div>
        ) : errored ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Couldn't load aliases"
              cause="the registry service is unreachable"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => reg.registryAliasesQuery.refetch()}
                >
                  Retry
                </Button>
              }
            />
          </div>
        ) : empty ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No aliases for this product"
              text="No external-language aliases are mapped yet. Add one above to override the product default during indexing."
            />
          </div>
        ) : (
          <Table>
            <thead>
              <tr>
                <th style={{ width: 160 }}>Product</th>
                <th style={{ width: 140 }}>External alias</th>
                <th>Resolves to</th>
                <th className="num" style={{ width: 90 }}>
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {aliases.map((a) => {
                // Per-row in-flight progress ("Mutation in progress" state):
                // the delete mutation's variable is the external id, so only the
                // row actually being removed swaps to the refresh icon + "Removing…".
                const rowDeleting =
                  reg.deleteAliasMutation.isPending &&
                  reg.deleteAliasMutation.variables === a.external;
                // Row-adjacent delete failure (next to the row it
                // targets): the failed delete's error renders
                // as a sub-row immediately beneath the row it targeted.
                const rowDeleteError =
                  deleteAliasErrorRowVisible && deleteAliasFailedId === a.external;
                return (
                  <Fragment key={`${a.product}:${a.external}`}>
                    <tr className="data">
                      <td>
                        <span
                          className="mono"
                          style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}
                        >
                          {a.product}
                        </span>
                      </td>
                      <td>
                        <span className="repo-id">{a.external}</span>
                      </td>
                      <td>
                        {a.canonical === "—" ? (
                          <span className="muted-note">unmapped</span>
                        ) : (
                          <>
                            <Icon name="arrow" className="ico" /> <Tag>{a.canonical}</Tag>
                          </>
                        )}
                      </td>
                      <td className="num">
                        <Button
                          variant="btn-ghost"
                          size="sm"
                          icon={rowDeleting ? "refresh" : undefined}
                          disabled={!canWrite || aliasPending}
                          title={removeHint}
                          aria-busy={rowDeleting}
                          aria-label={
                            a.canonical === "—"
                              ? `Remove ${a.product} language alias ${a.external}`
                              : `Remove ${a.product} language alias ${a.external} → ${a.canonical}`
                          }
                          onClick={() => remove(a)}
                        >
                          {rowDeleting ? "Removing…" : "Remove"}
                        </Button>
                      </td>
                    </tr>
                    {rowDeleteError && (
                      <tr className="data">
                        <td colSpan={4} style={{ paddingTop: 0 }}>
                          <MutationErrorAlert
                            error={reg.deleteAliasMutation.error}
                            title="Couldn't remove alias"
                            fallback="Failed to delete alias."
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </Table>
        )}
      </TableCard>
      <div className="muted-note" style={{ marginTop: 8 }}>
        <Icon name="info" className="ico" /> Unmapped aliases fall back to the product default and
        emit a language_fallback warning at query time.
      </div>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────── Section ──

export function LanguagesSection() {
  const data = useAdminData();
  // selectedProductId is a hook input arg, so the section owns it and feeds it up.
  const [product, setProduct] = useState(ALIAS_PRODUCTS[0]);
  // Global dictionary writes are SUPERUSER-ONLY — not write:destructive,
  // which a product key could also hold. Permissive offline (no session) so
  // fixtures mode renders enabled controls; gated on is_superuser once a
  // session loads, matching the hook's "superuser" disabled-reason vocabulary.
  const canWriteGlobalRegistry = data.session ? data.session.is_superuser : true;
  const canWriteSettings = data.can("write:settings");
  const reg = useLanguageRegistries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    selectedProductId: product,
    canWriteGlobalRegistry,
    canWriteSettings,
  });

  // Live vs fixture: the card gates fire only with a live session — offline the
  // queries are disabled (never loading/error) and the dictionaries render the
  // fixture dataset. Online, the skeleton/error states cover BOTH
  // dictionary queries; a live-but-empty registry renders the
  // implicit-empty dictionaries, never fixtures.
  const online = data.sessionIsSuccess;
  const dictLoading =
    online && (reg.registryLanguagesQuery.isLoading || reg.registryLocalesQuery.isLoading);
  const dictErrored =
    online && (reg.registryLanguagesQuery.isError || reg.registryLocalesQuery.isError);

  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <ScopeChip
            label="role"
            value={data.session?.is_superuser ? "superuser" : "operator"}
            dot
          />
        }
      />

      <ProductRegistry />
      {/* Stable How-To deep-link anchor; navigate("languages", anchor)
          scrolls here. */}
      <div id="language-registries-dictionaries-panel">
        {dictLoading ? (
          <Card title="Canonical dictionaries" sub="Loading languages and locales…">
            <Skeleton rows={4} />
          </Card>
        ) : dictErrored ? (
          <Card title="Canonical dictionaries" sub="Programming languages and documentation locales.">
            <ErrorState
              title="Couldn't load language registries"
              cause="registry service returned 5xx / network error"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => {
                    void reg.registryLanguagesQuery.refetch();
                    void reg.registryLocalesQuery.refetch();
                  }}
                >
                  Retry
                </Button>
              }
            />
          </Card>
        ) : (
          <CanonicalDictionaries reg={reg} canWrite={canWriteGlobalRegistry} online={online} />
        )}
      </div>
      <div id="language-registries-aliases-panel">
        <AliasMapping
          reg={reg}
          product={product}
          setProduct={setProduct}
          canWrite={canWriteSettings}
          online={online}
        />
      </div>
    </>
  );
}

// ───────────────────────────────────────────────── Module-level edge states ──
// The Section above renders the happy path. These cover the required
// states (loading / empty / error / permission / read-only). They are exported
// so the shell's state harness can mount them without a second file.

export function LanguagesLoading() {
  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <Card title="Canonical dictionaries" sub="Loading languages and locales…">
        <Skeleton rows={4} />
      </Card>
    </>
  );
}

export function LanguagesEmptyProducts() {
  const { navigate } = useShell();
  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <Card title="Product registry" sub="0 products · no repositories configured" flush>
        <div style={{ padding: 16 }}>
          <EmptyState
            title="No registered products found"
            text="Ensure products are registered in the ingestion system before managing aliases. The table is not broken — no products exist yet."
            action={
              <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("ingestion")}>
                Open Ingestion Jobs
              </Button>
            }
          />
        </div>
      </Card>
    </>
  );
}

export function LanguagesError() {
  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <ErrorState
        title="Couldn't load language registries"
        text="Fetching languages, locales, or aliases failed. Refresh to retry — if it persists, contact support."
        cause="registry service returned 5xx / network error"
        actions={
          <Button variant="btn-ghost" size="sm" icon="refresh">
            Retry
          </Button>
        }
      />
    </>
  );
}

export function LanguagesConflict() {
  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <ErrorState
        title="Cannot delete language: it is still referenced"
        text={
          <>
            Language <b>cpp</b> is referenced by aliases in <Tag>aspose.cells</Tag>. Delete those
            aliases first, then retry the language removal.
          </>
        }
        cause="language_in_use — alias references must be cleared before deletion"
      />
    </>
  );
}

export function LanguagesDenied() {
  return (
    <>
      <PageHead
        title="Language Registries"
        sub="Manage programming-language aliases, canonical dictionaries, and normalization rules."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <PermissionDenied
        scope="write:settings"
        extra="The global language registry is superuser-only and alias edits need a write:settings key. Read-only viewers can still audit the tables."
      />
    </>
  );
}

export function LanguagesReadonly() {
  return (
    <>
      <ReadonlyBanner />
      <LanguagesSection />
    </>
  );
}
