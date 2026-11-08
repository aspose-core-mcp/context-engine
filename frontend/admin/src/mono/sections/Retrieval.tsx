"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useRetrievalSettings } from "@/hooks/useRetrievalSettings";
import type { RetrievalSettings } from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { PageHead } from "../components/PageHead";
import { ScopeChip } from "../components/ScopeChip";
import { Select } from "../components/Field";
import {
  EmptyState,
  ErrorState,
  Skeleton,
  StaleBadge,
} from "../components/states";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { PopoverPanel, usePopover } from "../shell/Popover";
import { useConfirm, useToast } from "../shell/overlays";

// ── Fixtures (RSET_FIELDS / RSET_DATA) ─────────────────────────────────────────

interface RsetField {
  name: string;
  desc: string;
}

const RSET_FIELDS: RsetField[] = [
  { name: "Results per query", desc: "Document chunks returned per retrieval call (1–50)" },
  { name: "Max context tokens", desc: "Token budget for the combined retrieval context (512–65 536)" },
  { name: "Excerpt character limit", desc: "Max characters per excerpt in responses (120–5 000)" },
  { name: "Low confidence threshold", desc: "Score below which results trigger a confidence warning (0.0–1.0)" },
  { name: "Clarification policy", desc: "What to do when confidence is low" },
];

const PRODUCTS = [
  "aspose.ocr",
  "aspose.3d",
  "aspose.barcode",
  "aspose.cad",
  "aspose.cells",
  "aspose.words",
] as const;

type ProductId = (typeof PRODUCTS)[number];

// Sentinel "no product selected" option — drives the empty state + the
// disabled Load button. Offline the section defaults to a real product so the
// fixture rows always render (the empty state is only reachable on purpose).
const NO_PRODUCT = "— select a product —";

const RSET_DATA: Record<ProductId, string[]> = {
  "aspose.ocr": ["8", "8192", "1200", "0.35", "Ask when low confidence"],
  "aspose.3d": ["6", "6144", "1000", "0.40", "Ask when low confidence"],
  "aspose.barcode": ["10", "12288", "1400", "0.30", "Answer with caveat"],
  "aspose.cad": ["8", "8192", "1200", "0.35", "Ask when low confidence"],
  "aspose.cells": ["12", "16384", "1600", "0.25", "Answer with caveat"],
  "aspose.words": ["8", "8192", "1200", "0.45", "Refuse below threshold"],
};

// ── Clarification-policy catalog (3 enumerated options + descriptions) ──
// API limitation: the hook stores `clarification_policy` as a free string; the UI
// needs a constrained 3-option set, each with behaviour text. This catalog is
// the authoritative option-set; `policyOf` maps any fixture/live string onto one
// catalog entry so the read-only label, the edit <select>, and the per-policy
// description all stay in sync offline and online.
interface PolicyOption {
  id: string; // canonical value persisted to the backend
  label: string; // human label shown in the select + read-only view
  desc: string; // behaviour description announced on focus
  /** Safety-critical: silences all low-confidence results → soft confirm on save. */
  suppress?: boolean;
}

const POLICIES: PolicyOption[] = [
  {
    id: "ask_when_low_confidence",
    label: "Ask when low confidence",
    desc: "Proactively prompt the user to refine the query when confidence is low.",
  },
  {
    id: "always_return",
    label: "Answer with caveat",
    desc: "Always return best-effort results even when the match is uncertain.",
  },
  {
    id: "suppress_low_confidence",
    label: "Refuse below threshold",
    desc: "Return nothing when confidence falls below the threshold — no uncertain answers.",
    suppress: true,
  },
];

// Map any stored policy string (fixture display label OR live canonical id) onto
// a catalog entry, so the UI is coherent regardless of which form the data uses.
function policyOf(value: string): PolicyOption {
  return (
    POLICIES.find((p) => p.id === value || p.label === value) ?? POLICIES[0]
  );
}

// Numeric field ranges (valid-range inline help + invalid-range marking).
// Index aligns with RSET_FIELDS / RSET_DATA (policy at index 4 is non-numeric).
interface Range {
  min: number;
  max: number;
  step: number;
  /** Allow fractional values (the confidence threshold). */
  float?: boolean;
}

// Steps: large numeric knobs
// nudge by 100, the confidence threshold by 0.01 (the spinner-arrow increment;
// validateCell ignores step, so any in-range value still types/saves fine).
const RANGES: (Range | null)[] = [
  { min: 1, max: 50, step: 1 },
  { min: 512, max: 65536, step: 100 },
  { min: 120, max: 5000, step: 100 },
  { min: 0, max: 1, step: 0.01, float: true },
  null,
];

const SUPPRESS_POLICY = POLICIES.find((p) => p.suppress)!.id;

// All-options summary surfaced as the policy <select> tooltip (all policy options
// and their descriptions).
// Lets a sighted operator compare every option's consequence without selecting
// each one; the same text is associated to the control via aria-describedby.
const POLICY_TOOLTIP = POLICIES.map((p) => `${p.label}: ${p.desc}`).join("\n");

// Project the live RetrievalSettings record onto the 5-string row shape the
// read-only / edit rows render (same order as RSET_FIELDS / RSET_DATA values).
function settingsToRow(s: RetrievalSettings): string[] {
  return [
    String(s.top_k),
    String(s.max_context_tokens),
    String(s.excerpt_char_limit),
    String(s.low_confidence_threshold),
    s.clarification_policy,
  ];
}

// Seed an editable draft from a saved row: the policy cell (index 4) is stored in
// canonical id form so the <select> binds directly and the payload is correct.
function toDraft(row: string[]): string[] {
  return row.map((v, i) => (i === 4 ? policyOf(v).id : v));
}

// Validate one draft cell against its range / policy catalog. Returns an error
// message (string) when invalid, else null. Drives the inline red border + the
// "Invalid settings payload" alertdialog.
function validateCell(i: number, raw: string): string | null {
  if (i === 4) {
    return policyOfStrict(raw) ? null : "Select a clarification policy.";
  }
  const r = RANGES[i]!;
  const v = raw.trim();
  if (v === "") return "Required.";
  const n = Number(v);
  if (!Number.isFinite(n)) return "Must be a number.";
  if (!r.float && !Number.isInteger(n)) return "Must be a whole number.";
  if (n < r.min || n > r.max) return `Out of range (${fmtRange(r)}).`;
  return null;
}

// Strict policy lookup (no fallback) — an unknown/cleared value is invalid.
function policyOfStrict(value: string): PolicyOption | null {
  return POLICIES.find((p) => p.id === value || p.label === value) ?? null;
}

function fmtRange(r: Range): string {
  return r.float ? `${r.min.toFixed(1)}–${r.max.toFixed(1)}` : `${r.min}–${r.max}`;
}

// Compact relative-age string from an ISO timestamp ("Last updated 2
// hours ago"). Keeps the read-only stale indicator honest about data freshness.
function relAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "recently";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

// ── Section view modes (happy path + empty/loading/error states) ──
// "denied" is not a body-replacing mode — the read-only
// values stay visible when write:settings is absent (only Edit/Save disable).

type ViewMode = "loaded" | "empty" | "loading" | "error";

// ── Inline validation-error modal (alertdialog + focus management) ──────
// Reuses ConfirmModal's exact `.modal-overlay`/`.modal`/`.modal-*` classes so it
// matches the system 1:1. role="alertdialog", focus moves to OK on open and is
// trapped, Esc closes — exactly the kit overlay behaviour.
function ValidationModal({
  problems,
  onClose,
}: {
  problems: { field: string; message: string }[];
  onClose: () => void;
}) {
  const modalRef = useRef<HTMLDivElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Remember what had focus (the Save button that triggered validation) so we
    // can hand it back on close — focus returns to the
    // Save Settings button on dialog close. Capture BEFORE we autofocus OK.
    const trigger = document.activeElement as HTMLElement | null;
    okRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
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
    return () => {
      document.removeEventListener("keydown", onKey);
      // Restore focus to the trigger if it is still in the document and the modal
      // didn't already move focus elsewhere (keyboard users keep their place).
      if (trigger && trigger.isConnected && typeof trigger.focus === "function") {
        trigger.focus();
      }
    };
  }, [onClose]);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="rset-vt"
        aria-describedby="rset-vb"
        ref={modalRef}
      >
        <div className="modal-head">
          <div className="mi">
            <Icon name="alert" />
          </div>
          <div className="modal-title" id="rset-vt">
            Validation Error
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body" id="rset-vb">
          <div>
            Invalid settings payload. Correct the highlighted fields before saving — the backend
            rejects payloads outside the documented ranges, so these are fixed here first.
          </div>
          <div className="sum">
            {problems.map((p) => (
              <div key={p.field}>
                <b>{p.field}</b> — {p.message}
              </div>
            ))}
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" ref={okRef} className="btn btn-primary" onClick={onClose}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Contextual How-To help popover (header help link) ────
// Reuses the shell `.pop*` panel classes exactly as Logs/Indexes do; Esc +
// outside-click close handled by usePopover.
function HelpPopover({ onOpenHowTo }: { onOpenHowTo: () => void }) {
  return (
    <PopoverPanel className="rset-help-pop">
      <div className="pop-head">
        <span className="pt">Retrieval Settings</span>
      </div>
      <div className="pop-body" role="document">
        <div className="pop-sub">Why</div>
        <p className="card-sub" style={{ margin: "0 0 8px" }}>
          Tune the per-product trade-off between recall, precision, latency, and token spend when
          baseline retrieval quality drifts.
        </p>
        <div className="pop-sub">What</div>
        <p className="card-sub" style={{ margin: "0 0 8px" }}>
          Five knobs — results per query, context tokens, excerpt limit, confidence threshold, and
          the clarification policy — each within a fixed valid range.
        </p>
        <div className="pop-sub">How</div>
        <p className="card-sub" style={{ margin: 0 }}>
          Select a product, click Load, Edit one or two values, then Save. Every change is recorded
          in Config History &amp; Rollback, where you can revert without retyping.
        </p>
      </div>
      <div className="pop-foot">
        <button type="button" className="more-wrap" onClick={onOpenHowTo}>
          Open full How-To →
        </button>
      </div>
    </PopoverPanel>
  );
}

export function RetrievalSection() {
  const { navigate } = useShell();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const data = useAdminData();
  const helpPop = usePopover();

  const [product, setProduct] = useState<ProductId | "">("aspose.ocr");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(() => toDraft(RSET_DATA["aspose.ocr"]));
  // Fields the operator has touched in edit mode — only these surface a red
  // border, so an unedited valid row never flashes an error.
  const [touched, setTouched] = useState<boolean[]>(() => [false, false, false, false, false]);
  // Validation alertdialog payload ("Invalid settings payload").
  const [vErrors, setVErrors] = useState<{ field: string; message: string }[] | null>(null);

  const productSelected = product !== "";

  // The hook reads per-product settings + owns the save mutation; product state
  // lives here and drives `selectedProductId`. Scope gate comes from the session.
  const canWrite = data.can("write:settings");
  const retrieval = useRetrievalSettings({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    selectedProductId: productSelected ? product : "",
    canWriteSettings: canWrite,
  });

  // Display set the rows render from (live vs fixture). OFFLINE (no admin
  // session → queries disabled) every product renders its fixture row-set, fully
  // interactive. ONLINE the live record is the only source — loading / error /
  // empty render their states below the toolbar instead of silently
  // substituting fixtures.
  const online = data.sessionIsSuccess;
  const live = retrieval.currentSettings;
  const saved = useMemo(() => {
    if (product === "") return [];
    if (online) return live ? settingsToRow(live) : [];
    return RSET_DATA[product];
  }, [product, online, live]);
  // Compare against the canonical form so the policy cell (stored in the draft as
  // a canonical id, but in `saved` as a display label) does not read as dirty the
  // instant the editor opens.
  const dirty =
    editing &&
    draft.some((v, i) =>
      i === 4 ? policyOf(v).id !== policyOf(saved[i] ?? "").id : v !== saved[i],
    );
  const pending = retrieval.patchRetrievalSettingsMutation.isPending;

  // Per-field validity (inline field-level errors + range enforcement).
  const fieldErrors = useMemo(
    () => (editing ? draft.map((v, i) => validateCell(i, v)) : []),
    [editing, draft],
  );
  const hasErrors = fieldErrors.some(Boolean);

  // Effective view. Offline `saved` is the fixture row-set, so the section never
  // collapses into Skeleton/Error without a backend; online the real query state
  // drives the loading/error/empty bodies. EVERY mode renders below the
  // product toolbar — no state ever removes the selector + Load. The
  // permission-denied case keeps the read-only values visible — it is NOT a
  // body-replacing view mode.
  const liveLoading = online && retrieval.retrievalSettingsQuery.isLoading && !saved.length;
  const liveError = online && retrieval.retrievalSettingsQuery.isError && !saved.length;
  const effectiveView: ViewMode = !productSelected
    ? "empty"
    : liveLoading
      ? "loading"
      : liveError
        ? "error"
        : saved.length
          ? "loaded"
          : "empty";

  // Browser unsaved-changes guard (safety-critical: beforeunload warning).
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // Load settings for a product. Selecting a product in the toolbar calls this
  // directly (a scope switch reloads values per product); the Load
  // button re-invokes it as an explicit (re)fetch of the selected product. The
  // hook's query key tracks `product`, so a product change fetches that
  // product's record online; offline the fixture rows render instantly.
  function loadProduct(next: ProductId) {
    if (online && next === product) {
      // Same product: the query key doesn't change, so re-fetch explicitly.
      void retrieval.retrievalSettingsQuery.refetch();
    }
    setProduct(next);
    setEditing(false);
    setTouched([false, false, false, false, false]);
    retrieval.patchRetrievalSettingsMutation.reset();
    toast(`Loaded retrieval settings for ${next}`);
  }

  function beginEdit() {
    retrieval.patchRetrievalSettingsMutation.reset();
    setDraft(toDraft(saved));
    setTouched([false, false, false, false, false]);
    setEditing(true);
  }

  function cancelEdit() {
    retrieval.patchRetrievalSettingsMutation.reset();
    setDraft(toDraft(saved));
    setTouched([false, false, false, false, false]);
    setEditing(false);
  }

  // Map the 5 draft strings back onto the PATCH payload (same order as RSET_FIELDS).
  // Policy is normalized to its canonical id so the backend receives the enum.
  function draftPayload() {
    return {
      top_k: Number(draft[0]),
      max_context_tokens: Number(draft[1]),
      excerpt_char_limit: Number(draft[2]),
      low_confidence_threshold: Number(draft[3]),
      clarification_policy: policyOf(draft[4]).id,
    };
  }

  function commit() {
    // Persisting is what records a Config History entry.
    // The editor closes ONLY after the PATCH succeeds (the hook's onSuccess
    // toasts + invalidates). On failure it stays open with the draft intact —
    // the hook toasts the error and the inline alert below the rows shows the
    // message + recovery actions — so the operator can correct and retry.
    retrieval.patchRetrievalSettingsMutation.mutate(draftPayload(), {
      onSuccess: () => setEditing(false),
    });
  }

  function saveChanges() {
    // Validation gate first ("Invalid settings payload" alertdialog before
    // any submit; inline red borders mark the offending fields).
    const problems = draft
      .map((v, i) => ({ i, message: validateCell(i, v) }))
      .filter((p) => p.message)
      .map((p) => ({ field: RSET_FIELDS[p.i].name, message: p.message! }));
    if (problems.length) {
      setTouched([true, true, true, true, true]);
      setVErrors(problems);
      return;
    }

    const policyId = policyOf(draft[4]).id;
    const savedPolicyId = saved.length ? policyOf(saved[4]).id : "";
    if (policyId === SUPPRESS_POLICY && savedPolicyId !== SUPPRESS_POLICY) {
      confirm({
        title: "Switch clarification policy to suppress?",
        tone: "amber",
        icon: "alert",
        body: (
          <>
            <b>{product}</b> will stop returning results whose confidence falls below the threshold —
            queries the engine is unsure about get no answer instead of a caveated one.
          </>
        ),
        summary: <>clarification_policy → suppress_low_confidence · recorded in Config History</>,
        confirmLabel: "Save & suppress",
        // No `successToast` here: that would fire optimistically at confirm
        // time. The hook's onSuccess toasts once after the PATCH settles.
        onConfirm: () => {
          commit();
        },
      });
      return;
    }
    commit();
  }

  // Stale-data indicator — real relative age from the live timestamp; offline the
  // fixture keeps its friendly string ("Last updated 2h ago").
  const staleNode: ReactNode = live ? (
    <>
      updated {relAge(live.updated_at)} · {live.updated_by}
    </>
  ) : (
    <>updated 2h ago · su@local</>
  );

  // Contextual help deep-link. The section's How-To article is
  // "admin-retrieval-settings" — land directly on that How-To article (it exists
  // in HowTo.tsx) and carry the return context so the reader shows a working
  // "Back to Retrieval Settings" link (?article/?from/?source_label/?return_to
  // are the params HowTo.tsx actually consumes).
  function openHowTo() {
    const params = new URLSearchParams({
      article: "admin-retrieval-settings",
      from: "retrieval-settings",
      source_label: "Retrieval Settings",
      return_to: "/#retrieval-settings",
    });
    window.location.href = `/howto?${params.toString()}`;
  }

  // ── Header (help popover + stale-data indicator) ────────────────────────────
  const head = (
    <PageHead
      title="Retrieval Settings"
      sub="Configure retrieval lane weights, reranking, confidence thresholds, and version resolution."
      onHelp={openHowTo}
      actions={
        <>
          <ScopeChip label="scope" value="write:settings" dot />
          <div className="pop-wrap" ref={helpPop.wrapRef} style={{ position: "relative" }}>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="info"
              aria-haspopup="dialog"
              aria-expanded={helpPop.open}
              onClick={helpPop.toggle}
            >
              Help
            </Button>
            {helpPop.open && (
              <HelpPopover
                onOpenHowTo={() => {
                  helpPop.close();
                  openHowTo();
                }}
              />
            )}
          </div>
        </>
      }
    />
  );

  // ── Product toolbar (select + explicit Load + unsaved-changes / saved chip) ──
  // Rendered in EVERY view mode — the empty/loading/error bodies replace only
  // the rows below it, never the selector + Load. Picking a product loads it
  // immediately (scope switch); Load re-fetches the selected product
  // and stays disabled while none is selected.
  // Offline this is a no-op fetch over fixtures.
  const loadDisabled = !productSelected;
  const toolbar = (
    <div className="toolbar">
      <Select
        label="Product"
        width={200}
        options={[NO_PRODUCT, ...PRODUCTS]}
        value={productSelected ? product : NO_PRODUCT}
        disabled={pending}
        onChange={(e) => {
          const v = e.target.value;
          if (v === NO_PRODUCT) {
            // Clearing the selection shows the empty body below this
            // toolbar; the selector itself never disappears.
            setProduct("");
            setEditing(false);
            retrieval.patchRetrievalSettingsMutation.reset();
            return;
          }
          // Scope-switch loads that product's settings right away — any
          // in-progress edit is discarded.
          loadProduct(v as ProductId);
        }}
      />
      <Button
        variant="btn-ghost"
        size="sm"
        icon="download"
        disabled={loadDisabled || pending}
        title={
          loadDisabled
            ? "Select a product first"
            : "Fetch the current retrieval settings for the selected product"
        }
        onClick={() => {
          if (product !== "") loadProduct(product);
        }}
      >
        Load
      </Button>
      <div className="toolbar-right">
        {dirty && (
          <span className="muted-note" aria-hidden style={{ marginRight: 8 }}>
            unsaved edits not yet saved
          </span>
        )}
        <span
          className={cn("st-chip", dirty && "dirty")}
          role="status"
          aria-live="polite"
        >
          {dirty ? "Unsaved changes" : "Saved"}
        </span>
      </div>
    </div>
  );

  // ── Card header actions: Edit ↔ Cancel / Save ───────────────────────────────
  // Scope-gated by write:settings; the hook's disabled-reason drives the Save hint.
  // Permission denied: Edit/Save disable, but the read-only values remain.
  const saveDisabled = !canWrite || pending;
  const cardActions = editing ? (
    <>
      <Button variant="btn-ghost" size="sm" onClick={cancelEdit} disabled={pending}>
        Cancel
      </Button>
      <Button
        variant="btn-primary"
        size="sm"
        icon={pending ? "refresh" : "check"}
        onClick={saveChanges}
        disabled={saveDisabled}
        title={
          !canWrite
            ? "Requires write:settings scope"
            : (retrieval.retrievalUpdateDisabledReason ?? undefined)
        }
        aria-busy={pending}
      >
        {pending ? "Saving…" : "Save changes"}
      </Button>
    </>
  ) : (
    <Button
      variant="btn-ghost"
      size="sm"
      onClick={beginEdit}
      disabled={!canWrite}
      title={canWrite ? undefined : "Requires write:settings scope"}
    >
      Edit
    </Button>
  );

  // ── Read-only / edit rows for the 5 knobs ───────────────────────────────────
  // Numeric rows: constrained <input type=number> with min/max/step + inline
  // range help + red border on invalid. Policy row: constrained 3-option <select>
  // with the selected policy's behaviour text underneath.
  const rows = RSET_FIELDS.map((f, i) => {
    const isPolicy = i === 4;
    const err = editing ? fieldErrors[i] : null;
    const showErr = editing && touched[i] && !!err;
    const r = RANGES[i];
    const policy = isPolicy ? policyOf(editing ? draft[i] : saved[i] ?? POLICIES[0].id) : null;
    return (
      <div className="kv-row" key={f.name}>
        <div>
          <div className="kn">{f.name}</div>
          <div className="kd">{f.desc}</div>
          {/* The policy row shows the selected option's behaviour text so the
              operator sees its consequence (information + a11y). In edit
              mode it renders as an emphasized left-bordered info callout
              (padded, hover-tone background, 3px info left border,
              bold policy name + caption); read-only keeps the plain
              caption. aria-live announces the swap to screen-reader users, and
              the edit <select> points at this node via aria-describedby. */}
          {isPolicy && policy && (
            editing ? (
              <div
                id="rset-policy-desc"
                aria-live="polite"
                style={{
                  marginTop: 6,
                  padding: "8px 11px",
                  background: "var(--info-bg)",
                  borderLeft: "3px solid var(--info)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                <div className="kn" style={{ color: "var(--fg)" }}>
                  {policy.label}
                </div>
                <div className="kd" style={{ marginTop: 2, color: "var(--fg-muted)" }}>
                  {policy.desc}
                </div>
              </div>
            ) : (
              <div
                id="rset-policy-desc"
                className="kd"
                style={{ marginTop: 4, color: "var(--fg-muted)" }}
              >
                {policy.desc}
              </div>
            )
          )}
          {showErr && (
            <div
              className="kd"
              role="alert"
              style={{ marginTop: 4, color: "var(--crit)", fontWeight: 600 }}
            >
              {err}
            </div>
          )}
        </div>
        <div className="kvv">
          {editing ? (
            isPolicy ? (
              <select
                className="selectctl"
                style={{
                  width: 220,
                  ...(showErr
                    ? { borderColor: "var(--crit)", boxShadow: "0 0 0 3px var(--crit-bg)" }
                    : {}),
                }}
                value={policyOf(draft[i]).id}
                aria-label={f.name}
                aria-describedby="rset-policy-desc"
                aria-invalid={showErr || undefined}
                title={POLICY_TOOLTIP}
                disabled={pending}
                onChange={(e) => {
                  const v = e.target.value;
                  setDraft((prev) => prev.map((x, j) => (j === i ? v : x)));
                  setTouched((prev) => prev.map((x, j) => (j === i ? true : x)));
                }}
              >
                {POLICIES.map((p) => (
                  <option key={p.id} value={p.id} title={p.desc}>
                    {p.label}
                  </option>
                ))}
              </select>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                <input
                  className="inputctl rset-in"
                  type="number"
                  inputMode={r?.float ? "decimal" : "numeric"}
                  min={r?.min}
                  max={r?.max}
                  step={r?.step}
                  style={{
                    width: 150,
                    textAlign: "right",
                    ...(showErr
                      ? { borderColor: "var(--crit)", boxShadow: "0 0 0 3px var(--crit-bg)" }
                      : {}),
                  }}
                  value={draft[i]}
                  aria-label={f.name}
                  aria-invalid={showErr || undefined}
                  aria-describedby={`rset-hint-${i}`}
                  disabled={pending}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDraft((prev) => prev.map((x, j) => (j === i ? v : x)));
                    setTouched((prev) => prev.map((x, j) => (j === i ? true : x)));
                  }}
                />
                <span className="muted-note" id={`rset-hint-${i}`}>
                  valid {r ? fmtRange(r) : ""}
                </span>
              </div>
            )
          ) : isPolicy && policy ? (
            policy.label
          ) : (
            saved[i]
          )}
        </div>
      </div>
    );
  });

  // Save-failure message for the inline alert (error Alert showing
  // error.message, with fallback copy).
  const patchErr = retrieval.patchRetrievalSettingsMutation.error;
  const saveErrText =
    patchErr instanceof Error && patchErr.message
      ? patchErr.message
      : "Failed to update retrieval settings.";

  // ── Body switches between happy path and the documented states ──────
  // Every branch renders BELOW the always-visible product toolbar; the non-row
  // bodies get the standard padded wrapper inside the flush card.
  let body: ReactNode;
  if (effectiveView === "empty") {
    body = (
      <div style={{ padding: 16 }}>
        {productSelected ? (
          <EmptyState
            title="No settings loaded"
            text={`No retrieval settings were returned for ${product}. Click Load to retry the fetch.`}
            action={
              <Button
                variant="btn-primary"
                size="sm"
                icon="download"
                onClick={() => loadProduct(product)}
              >
                Load {product}
              </Button>
            }
          />
        ) : (
          <EmptyState
            title="No product selected"
            text="Select a product from the dropdown and click Load to fetch its retrieval settings."
          />
        )}
      </div>
    );
  } else if (effectiveView === "loading") {
    body = (
      <div style={{ padding: 16 }}>
        <Skeleton rows={5} />
      </div>
    );
  } else if (effectiveView === "error") {
    body = (
      <div style={{ padding: 16 }}>
        <ErrorState
          title="Couldn’t load retrieval settings"
          text="The admin service returned an error while fetching settings for this product."
          cause="admin API unreachable or product not found"
          actions={
            <>
              <Button
                variant="btn-primary"
                size="sm"
                icon="refresh"
                onClick={() => retrieval.retrievalSettingsQuery.refetch()}
              >
                Retry
              </Button>
              <Button variant="btn-ghost" size="sm" icon="pulse" onClick={() => navigate("health")}>
                Check Health
              </Button>
            </>
          }
        />
      </div>
    );
  } else {
    body = (
      <>
        <div className="kv-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
          {rows}
        </div>
        {/* Stale-data indicator sits BELOW the read-only list (a subtle
            timestamp indicator below the read-only view). Hidden in edit mode — the values being edited aren't stale. */}
        {!editing && (
          <div style={{ marginTop: 8 }}>
            <StaleBadge>{staleNode}</StaleBadge>
          </div>
        )}
        {/* Inline save-failure alert (conditional error Alert with the
            mutation's error.message + recovery guidance). The editor is still
            open at this point — commit() closes it on success only. */}
        {editing && retrieval.patchRetrievalSettingsMutation.isError && (
          <div style={{ marginTop: 12 }}>
            <ErrorState
              title="Could not save retrieval settings"
              text={saveErrText}
              cause="backend rejected the payload or the admin service is degraded"
              actions={
                <>
                  <Button
                    variant="btn-primary"
                    size="sm"
                    icon="refresh"
                    onClick={saveChanges}
                    disabled={pending}
                  >
                    Retry save
                  </Button>
                  <Button
                    variant="btn-ghost"
                    size="sm"
                    icon="pulse"
                    onClick={() => navigate("health")}
                  >
                    Check Health
                  </Button>
                </>
              }
            />
          </div>
        )}
        {hasErrors && editing && (
          <div className="muted-note" role="status" style={{ marginTop: 8, color: "var(--crit)" }}>
            <Icon name="alert" className="ico" /> Some fields are outside their valid range — fix the
            highlighted rows to save.
          </div>
        )}
        <div className="muted-note" data-guidance style={{ marginTop: 8 }}>
          Read-only by default. Click Edit to change values — saving records a Config History entry.
        </div>
      </>
    );
  }

  return (
    <>
      {head}

      <Card
        title="Settings"
        sub="Per-product retrieval configuration. Changes are recorded in Config History."
        flush
        right={effectiveView === "loaded" ? cardActions : undefined}
      >
        {effectiveView === "loaded" && !canWrite && (
          <Banner
            variant="warn"
            icon="lock"
            title="You do not have write:settings scope"
            text="Current values are visible, but Edit and Save are disabled. Contact your administrator to modify retrieval settings."
            guidance
          />
        )}
        {/* The product toolbar is part of EVERY view mode: switching products or
            clearing the selection swaps only the body below it, so the operator
            can always pick another product and Load it. */}
        {toolbar}
        {body}
      </Card>

      <Card
        title="After you change a setting"
        sub="Verify the change landed and watch for retrieval side-effects before walking away."
      >
        <div className="muted-note" style={{ lineHeight: 1.7 }}>
          Every saved change is written to{" "}
          <Button variant="btn-ghost" size="sm" icon="history" onClick={() => navigate("config")}>
            Config History &amp; Rollback
          </Button>{" "}
          — open it to confirm the new revision and, if needed, roll back to the previous values
          without retyping them. If saves start failing, the admin service may be degraded; check{" "}
          <Button variant="btn-ghost" size="sm" icon="pulse" onClick={() => navigate("health")}>
            Health
          </Button>
          .
        </div>
      </Card>

      {vErrors && <ValidationModal problems={vErrors} onClose={() => setVErrors(null)} />}
    </>
  );
}
