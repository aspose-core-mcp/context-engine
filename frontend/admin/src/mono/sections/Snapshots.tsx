"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getAdminErrorMessage } from "@/components/admin-console.utils";
import { useSnapshotState } from "@/hooks/useSnapshotState";
import type {
  SnapshotCleanupAuditRecord,
  SnapshotRecord,
  SnapshotRollbackAuditRecord,
} from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Select } from "../components/Field";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { EmptyState, ErrorState, PermissionDenied, ReadonlyBanner, Skeleton } from "../components/states";
import { Table, TableCard, ShowMoreRow } from "../components/Table";
import { Tabbed } from "../components/Tabbed";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useConfirm, useToast } from "../shell/overlays";

type SnapshotHook = ReturnType<typeof useSnapshotState>;

// Minimum characters for an auditable, searchable reason (rollback / cleanup).
const REASON_MIN = 8;
// Default visible rows in an audit trail before "+N more" (keeps dense lists short).
const AUDIT_VISIBLE = 4;

// ───────────────────────────────────────────────────────────────── Fixtures ──

interface Snap {
  id: string;
  active: boolean;
  rev: string;
  created: string;
  points: string;
  // Live `source_kind` is a free string; fixtures use apiref/docs.
  kind: string;
}

// Map a live SnapshotRecord onto the section's render-ready Snap shape so the
// existing markup renders backend data unchanged.
function toSnap(r: SnapshotRecord): Snap {
  return {
    id: r.snapshot_id,
    active: r.status === "active",
    rev: r.source_revision,
    created: r.created_at,
    points: r.indexed_chunks_count.toLocaleString("en-US").replace(/,/g, " "),
    kind: r.source_kind,
  };
}

const SNAP_DATA: Record<string, Snap[]> = {
  "aspose.ocr": [
    { id: "snap_2f9c…a17", active: true, rev: "dev-local @ 8c3864e", created: "today 12:17", points: "24 318", kind: "apiref" },
    { id: "snap_71ad…c03", active: false, rev: "dev-local @ 4a1f9b2", created: "yesterday 09:41", points: "24 290", kind: "apiref" },
    { id: "snap_03be…9f2", active: false, rev: "dev-local @ 2c77d10", created: "3 days ago", points: "23 884", kind: "docs" },
  ],
  "aspose.3d": [
    { id: "snap_4d10…b71", active: true, rev: "dev-local @ a91c20f", created: "2 days ago", points: "8 142", kind: "apiref" },
  ],
  "aspose.barcode": [
    { id: "snap_77fe…2a0", active: true, rev: "dev-local @ 1bd4e88", created: "today 08:02", points: "31 905", kind: "apiref" },
    { id: "snap_19cc…d4e", active: false, rev: "dev-local @ 0f7a213", created: "4 days ago", points: "31 720", kind: "docs" },
  ],
  "aspose.cad": [
    { id: "snap_5b22…f90", active: true, rev: "dev-local @ 7e0c9a1", created: "yesterday 14:50", points: "18 060", kind: "apiref" },
    { id: "snap_a3d1…118", active: false, rev: "dev-local @ 5c2b740", created: "5 days ago", points: "17 998", kind: "docs" },
  ],
  "aspose.cells": [
    { id: "snap_c0fa…7e2", active: true, rev: "dev-local @ d41aa09", created: "today 10:31", points: "52 412", kind: "apiref" },
    { id: "snap_8e7b…a55", active: false, rev: "dev-local @ b90f312", created: "2 days ago", points: "52 180", kind: "apiref" },
    { id: "snap_2210…c9d", active: false, rev: "dev-local @ 6a1c882", created: "6 days ago", points: "51 044", kind: "docs" },
    { id: "snap_f93a…001", active: false, rev: "dev-local @ 33be770", created: "9 days ago", points: "50 870", kind: "docs" },
  ],
};

const PRODUCTS = ["aspose.ocr", "aspose.3d", "aspose.barcode", "aspose.cad", "aspose.cells"];
const LANGS = ["net", "java", "python", "cpp"];
const VERSIONS = ["latest", "v24.1", "v23.12"];
// Explicit "all/any" head entry for the language/version selects: maps to the hook's empty-string filter so the unfiltered
// default is visible and reachable again after picking a concrete value.
const SCOPE_ANY = "all/any";
// Combined source-kind entry for cleanup: maps to the
// hook's empty-string state → `source_kind=undefined` → both docs + apiref.
const BOTH_SOURCE_KINDS = "docs & apiref";

const numPts = (p: string) => Number.parseInt(p.replace(/\s+/g, ""), 10);

// Compare Δ-time: render a signed, human-readable duration in the largest sensible
// unit (seconds → minutes → hours → days), for the "Δ time: {human-readable
// delta}" chip. Used only on the live path where a real second-delta is available.
function humanizeDelta(seconds: number): string {
  const sign = seconds < 0 ? "−" : "+";
  const abs = Math.abs(seconds);
  if (abs < 60) return `${sign}${Math.round(abs)}s`;
  if (abs < 3600) return `${sign}${Math.round(abs / 60)}m`;
  if (abs < 86_400) return `${sign}${Math.round(abs / 3600)}h`;
  return `${sign}${Math.round(abs / 86_400)}d`;
}

// Fixtures carry no language/version field, so offline a deterministic bucket is
// derived from the snapshot id (a stable hash) → the language/version filters can
// VISIBLY partition the fixture set client-side. Live rows are already filtered
// server-side by the hook's queryKey, so the same predicate is idempotent on them.
function hashIndex(id: string, len: number): number {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % len;
}
const fixtureLang = (s: Snap) => LANGS[hashIndex(s.id, LANGS.length)];
const fixtureVersion = (s: Snap) => VERSIONS[hashIndex(s.id + "v", VERSIONS.length)];

// API limitation: the snapshots list endpoint carries no cleanup-policy window; the
// values live only inside a cleanup-preview result. Offline (and before a preview
// runs) this fixture provides the retention window to surface so
// the policy caption is never an empty "?".
const CLEANUP_POLICY_FIXTURE = { maxInactive: 3, staleDays: 30 };

// API limitation: risk_summary is only present on a live cleanup-preview result; this
// fixture lets the preview's risk bullets render fully offline.
const CLEANUP_RISK_FIXTURE = [
  "Active snapshots are protected and will never be deleted.",
  "Candidates exceed the retention window of 3 inactive snapshots per scope.",
  "All candidates are older than the 30-day stale threshold.",
];

// API limitation: rollback/cleanup audit endpoints are query-gated and empty offline.
// These fixtures drive the audit trails so the accountability surfaces render
// fully with no backend; live rows replace them when present.
const ROLLBACK_AUDIT_FIXTURE: SnapshotRollbackAuditRecord[] = [
  {
    audit_id: "aud_rb_5f21c9",
    operation_id: "op_rb_a17c4e",
    result_status: "completed",
    actor_key_id: "key_sre_2f9c",
    request_id: "req_8c3864e",
    reason: "Bad apiref publish broke get_symbol_doc — reverting to last-known-good.",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "latest",
    target_snapshot_id: "snap_71ad…c03",
    active_snapshot_before_id: "snap_2f9c…a17",
    active_snapshot_after_id: "snap_71ad…c03",
    diagnostics: {},
    created_at: "today 12:31",
  },
  {
    audit_id: "aud_rb_4a02d8",
    operation_id: "op_rb_91af2c",
    result_status: "completed",
    actor_key_id: "key_ops_8e7b",
    request_id: "req_4a1f9b2",
    reason: "Stale chunk counts after partial index — rolling back one revision.",
    product_id: "aspose.cells",
    programming_language: "java",
    version: "v24.1",
    target_snapshot_id: "snap_8e7b…a55",
    active_snapshot_before_id: "snap_c0fa…7e2",
    active_snapshot_after_id: "snap_8e7b…a55",
    diagnostics: {},
    created_at: "yesterday 14:50",
  },
  {
    audit_id: "aud_rb_2c77d1",
    operation_id: "op_rb_2c77d1",
    result_status: "failed",
    actor_key_id: "key_ops_8e7b",
    request_id: null,
    reason: "Attempted rollback to a docs snapshot; preflight blocked scope mismatch.",
    product_id: "aspose.barcode",
    programming_language: "python",
    version: "latest",
    target_snapshot_id: "snap_19cc…d4e",
    active_snapshot_before_id: "snap_77fe…2a0",
    active_snapshot_after_id: "snap_77fe…2a0",
    diagnostics: {},
    created_at: "2 days ago",
  },
  {
    audit_id: "aud_rb_7e0c9a",
    operation_id: "op_rb_7e0c9a",
    result_status: "completed",
    actor_key_id: "key_sre_2f9c",
    request_id: "req_7e0c9a1",
    reason: "Routine rollback drill — verifying confirm-token flow end to end.",
    product_id: "aspose.cad",
    programming_language: "cpp",
    version: "v23.12",
    target_snapshot_id: "snap_a3d1…118",
    active_snapshot_before_id: "snap_5b22…f90",
    active_snapshot_after_id: "snap_a3d1…118",
    diagnostics: {},
    created_at: "5 days ago",
  },
  {
    audit_id: "aud_rb_0f7a21",
    operation_id: "op_rb_0f7a21",
    result_status: "completed",
    actor_key_id: "key_po_03be",
    request_id: "req_0f7a213",
    reason: "Reverted experimental embedding swap after relevance regression.",
    product_id: "aspose.ocr",
    programming_language: "net",
    version: "latest",
    target_snapshot_id: "snap_03be…9f2",
    active_snapshot_before_id: "snap_71ad…c03",
    active_snapshot_after_id: "snap_03be…9f2",
    diagnostics: {},
    created_at: "6 days ago",
  },
];

const CLEANUP_HISTORY_FIXTURE: SnapshotCleanupAuditRecord[] = [
  {
    audit_id: "aud_cl_9f21c0",
    operation_id: "op_cl_2210c9",
    result_status: "completed",
    actor_key_id: "key_ops_8e7b",
    request_id: "req_2210c9d",
    reason: "Quarterly retention sweep — trimming inactive docs snapshots.",
    product_id: "aspose.cells",
    programming_language: null,
    version: null,
    source_kind: "docs",
    dry_run: false,
    deleted_snapshot_ids: ["snap_2210…c9d", "snap_f93a…001"],
    protected_snapshot_ids: ["snap_c0fa…7e2"],
    diagnostics: {},
    created_at: "today 10:42",
  },
  {
    audit_id: "aud_cl_4a1f9b",
    operation_id: "op_cl_03be9f",
    result_status: "completed",
    actor_key_id: "key_po_03be",
    request_id: "req_4a1f9b2",
    reason: "Reclaiming index storage after re-ingest superseded old revisions.",
    product_id: "aspose.ocr",
    programming_language: null,
    version: null,
    source_kind: "docs",
    dry_run: false,
    deleted_snapshot_ids: ["snap_03be…9f2"],
    protected_snapshot_ids: ["snap_2f9c…a17"],
    diagnostics: {},
    created_at: "3 days ago",
  },
  {
    audit_id: "aud_cl_1bd4e8",
    operation_id: "op_cl_19ccd4",
    result_status: "completed",
    actor_key_id: "key_sre_2f9c",
    request_id: "req_1bd4e88",
    reason: "Removing stale barcode docs snapshot beyond retention window.",
    product_id: "aspose.barcode",
    programming_language: null,
    version: null,
    source_kind: "docs",
    dry_run: false,
    deleted_snapshot_ids: ["snap_19cc…d4e"],
    protected_snapshot_ids: ["snap_77fe…2a0"],
    diagnostics: {},
    created_at: "4 days ago",
  },
  {
    audit_id: "aud_cl_5c2b74",
    operation_id: "op_cl_5c2b74",
    result_status: "completed",
    actor_key_id: "key_ops_8e7b",
    request_id: "req_5c2b740",
    reason: "CAD inactive docs cleanup after migration validation.",
    product_id: "aspose.cad",
    programming_language: null,
    version: null,
    source_kind: "docs",
    dry_run: false,
    deleted_snapshot_ids: ["snap_a3d1…118"],
    protected_snapshot_ids: ["snap_5b22…f90"],
    diagnostics: {},
    created_at: "5 days ago",
  },
  {
    audit_id: "aud_cl_6a1c88",
    operation_id: "op_cl_6a1c88",
    result_status: "completed",
    actor_key_id: "key_po_03be",
    request_id: null,
    reason: "Bounded inventory sweep across mixed source kinds.",
    product_id: "aspose.cells",
    programming_language: null,
    version: null,
    source_kind: null,
    dry_run: false,
    deleted_snapshot_ids: ["snap_2210…c9d"],
    protected_snapshot_ids: ["snap_c0fa…7e2", "snap_8e7b…a55"],
    diagnostics: {},
    created_at: "8 days ago",
  },
];

function auditPill(status: string): StatusVariant {
  if (status === "completed" || status === "ok") return "ok";
  if (status === "failed" || status === "error") return "crit";
  if (status === "partial" || status === "warn") return "warn";
  return "neutral";
}

// ───────────────────────────────────────────── Reason-capture modal (inline) ──
// Reuses ConfirmModal's exact overlay/modal/field/foot classes so it matches the
// design system 1:1. Captures a free-text reason (min length enforced) and an
// optional typed-word token before a destructive mutation fires. Traps focus and
// closes on Esc / overlay-click, mirroring the kit's ConfirmModal.

interface ReasonModalConfig {
  title: string;
  body?: React.ReactNode;
  summary?: React.ReactNode;
  /** Typed-word gate (e.g. "ROLLBACK" / "DELETE"). */
  word?: string;
  tone?: "danger" | "amber";
  icon?: IconName;
  reasonLabel: string;
  reasonPlaceholder?: string;
  initialReason?: string;
  confirmLabel: string;
  onConfirm: (reason: string) => void;
}

function ReasonModal({ config, onClose }: { config: ReasonModalConfig; onClose: () => void }) {
  const [reason, setReason] = useState(config.initialReason ?? "");
  const [typed, setTyped] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const tone = config.tone ?? "danger";
  const reasonOk = reason.trim().length >= REASON_MIN;
  const wordOk = !config.word || typed === config.word;
  const gateOk = reasonOk && wordOk;

  useEffect(() => {
    reasonRef.current?.focus();
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
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function doConfirm() {
    if (!gateOk) return;
    config.onConfirm(reason.trim());
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
            style={tone === "amber" ? { background: "var(--warn-bg)", color: "var(--warn)" } : undefined}
          >
            <Icon name={config.icon ?? "alert"} />
          </div>
          <div className="modal-title" id="rsn-title">
            {config.title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          {config.body != null && <div>{config.body}</div>}
          {config.summary != null && <div className="sum">{config.summary}</div>}
          <div className="modal-field" style={{ marginBottom: 14 }}>
            <label htmlFor="rsn-reason" id="rsn-reason-label">
              {config.reasonLabel}
            </label>
            <textarea
              id="rsn-reason"
              ref={reasonRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={config.reasonPlaceholder}
              aria-labelledby="rsn-reason-label"
              aria-describedby="rsn-reason-hint"
              rows={3}
              spellCheck={false}
              style={{
                width: "100%",
                minHeight: 68,
                resize: "vertical",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                padding: "9px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: "var(--fg)",
                outline: "none",
                lineHeight: 1.5,
              }}
            />
            <div className="confirm-hint" id="rsn-reason-hint">
              {reasonOk
                ? "Recorded in the audit trail and searchable for future audits."
                : `Enter at least ${REASON_MIN} characters (${reason.trim().length}/${REASON_MIN}).`}
            </div>
          </div>
          {config.word && (
            <div className="modal-field">
              <label htmlFor="rsn-word" id="rsn-word-label">
                Type {config.word} to confirm
              </label>
              <input
                id="rsn-word"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                aria-labelledby="rsn-word-label"
                aria-describedby="rsn-word-hint"
                autoComplete="off"
                spellCheck={false}
              />
              <div className="confirm-hint" id="rsn-word-hint">
                Exact match required. This protects against accidental {config.title.toLowerCase()}.
              </div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={cn("btn", tone === "amber" ? "btn-amber" : "btn-danger")}
            disabled={!gateOk}
            onClick={doConfirm}
          >
            {config.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────── Active & Compare panel ──

function ActiveComparePanel({
  hook,
  data,
  product,
  setProduct,
}: {
  hook: SnapshotHook;
  data: ReturnType<typeof useAdminData>;
  product: string;
  setProduct: (next: string) => void;
}) {
  const { navigate } = useShell();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const lang = hook.snapshotLanguageFilter;
  const [picked, setPicked] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  const canPromote = data.can("write:ingestion");

  // Live snapshots for the selected product → fixtures fallback when offline/empty.
  const liveSnaps = hook.snapshotRows;
  const liveMode = liveSnaps.length > 0;
  const source: Snap[] = liveSnaps.length ? liveSnaps.map(toSnap) : (SNAP_DATA[product] ?? []);

  // Language options from live rows; fall back to the fixture list when offline.
  // Both selects always lead with the "all/any" entry (= empty filter) so the
  // default unfiltered view is a real option and stays reachable after filtering.
  const langOptions = [
    SCOPE_ANY,
    ...(hook.snapshotLanguageOptions.length ? hook.snapshotLanguageOptions : LANGS),
  ];
  const versionOptions = [
    SCOPE_ANY,
    ...(hook.snapshotVersionOptions.length ? hook.snapshotVersionOptions : VERSIONS),
  ];
  const version = hook.snapshotVersionFilter;

  // Filter the DISPLAY source so the language/version selects respond offline.
  // Empty filter = "all"; live rows are pre-filtered server-side (predicate idempotent).
  const snaps: Snap[] = useMemo(
    () =>
      source.filter((s) => {
        if (lang && fixtureLang(s) !== lang) return false;
        if (version && fixtureVersion(s) !== version) return false;
        return true;
      }),
    [source, lang, version],
  );
  const activeCount = snaps.filter((s) => s.active).length;
  const hasActive = activeCount > 0;

  // Gate on the DISPLAY set so a fixture is never hidden offline (mirror Health).
  const loading = hook.snapshotsQuery.isLoading && !snaps.length;
  const errored = hook.snapshotsQuery.isError && !snaps.length;

  // "Fill both filters to resolve active snapshot" / active-snapshot recovery.
  // The active-snapshot query only runs once product + language + version are all
  // set (mirrors the hook's `enabled` guard). Surface that exact precondition and
  // the failure recovery here instead of the generic fixture-driven warn banner.
  const filtersComplete = lang.trim().length > 0 && version.trim().length > 0;
  const activeErrored = filtersComplete && hook.activeSnapshotQuery.isError;

  // Batch promotion. Selection here drives BOTH the 2-item compare picker and
  // the hook's multi-select (`selectedSnapshotIds`) used by Batch Set Active. Live
  // mode promotes sequentially via the hook; offline it is a no-op toast.
  const selectedIds = hook.selectedSnapshotIds;
  const selectedCount = selectedIds.length;

  function setActive(s: Snap) {
    confirm({
      title: "Set snapshot active",
      tone: "amber",
      icon: "upload",
      summary: (
        <>
          promote <b>{s.id}</b>
          <br />
          scope <b>{product} / {lang || "—"}</b> · {s.points} points ·{" "}
          <span className="mono">{s.kind}</span>
          <br />
          revision <b>{s.rev}</b>
        </>
      ),
      body: "This promotes the snapshot to active for its scope and serves it to live retrieval. Reversible via Rollback.",
      confirmLabel: "Set active",
      onConfirm: () => {
        if (liveSnaps.length) {
          hook.promoteSnapshotMutation.mutate(s.id);
        } else {
          toast(`Snapshot ${s.id} is now active`);
        }
      },
    });
  }

  function batchPromote() {
    if (selectedCount === 0) return;
    confirm({
      title: "Batch set active",
      tone: "amber",
      icon: "upload",
      summary: (
        <>
          promoting <b>{selectedCount}</b> snapshot{selectedCount !== 1 ? "s" : ""} sequentially
          <br />
          scope <b>{product} / {lang || "—"}</b>
          <br />
          last successful promotion becomes <b>active</b>
        </>
      ),
      body: "Selected snapshots are promoted one after another; the last to succeed becomes the active snapshot served to users. If one fails, the loop halts and selection is preserved for retry.",
      confirmLabel: `Promote ${selectedCount}`,
      onConfirm: () => {
        if (liveSnaps.length) {
          // Single confirmation (this modal) only: run the sequential loop
          // directly — no second hook-side confirm. The completion toast fires
          // only after every promotion settles; a failure surfaces via the
          // mutation's error toast + the inline alert below the list, with the
          // selection preserved for retry.
          void hook.runBatchSnapshotPromoteNow().then((result) => {
            if (result.ok) toast(`Batch promote complete · ${result.total} processed`);
          });
        } else {
          hook.setSelectedSnapshotIds([]);
          toast(`Batch promote complete · ${selectedCount} processed`);
        }
      },
    });
  }

  // Selection toggles the hook's multi-select AND keeps the (max-2) compare pair.
  function toggle(id: string) {
    setCompareOpen(false);
    hook.toggleSnapshotSelection(id);
    setPicked((cur) =>
      cur.includes(id) ? cur.filter((x) => x !== id) : cur.length >= 2 ? [cur[1], id] : [...cur, id],
    );
  }
  function clearSelection() {
    hook.setSelectedSnapshotIds([]);
    setPicked([]);
    setCompareOpen(false);
  }
  function reset(nextProduct: string) {
    setProduct(nextProduct);
    // Product switch returns the scope filters to the "all/any" default so the
    // new product never starts on a stale (possibly nonexistent) scope.
    hook.setSnapshotLanguageFilter("");
    hook.setSnapshotVersionFilter("");
    clearSelection();
  }

  const pair = useMemo(
    () => picked.map((id) => snaps.find((s) => s.id === id)).filter((s): s is Snap => Boolean(s)),
    [picked, snaps],
  );

  // Full 9-field comparison + summary chips. `compareSnapshotsMutation` supplies
  // live data; fall back to a fixture-derived comparison so the side-by-side
  // and the same-scope / same-kind / Δ-chunks / Δ-time chips render offline.
  const liveCompare = hook.snapshotCompareResult;
  function runCompare() {
    if (pair.length !== 2) return;
    setCompareOpen(true);
    if (liveSnaps.length) {
      hook.compareSnapshotsMutation.mutate({
        baseSnapshotId: pair[0].id,
        targetSnapshotId: pair[1].id,
      });
    }
  }

  const cmp = useMemo(() => {
    if (pair.length !== 2) return null;
    const [a, b] = pair;
    // Use the live compare result only when it matches the current pair.
    const live =
      liveCompare &&
      liveCompare.base_snapshot.snapshot_id === a.id &&
      liveCompare.target_snapshot.snapshot_id === b.id
        ? liveCompare
        : null;
    // Live rows never fall back to fixture-derived math: while the compare API
    // call is pending or failed, the panel renders its own state instead of
    // silently showing locally computed values.
    if (liveMode && !live) return null;
    const aLang = fixtureLang(a);
    const aVer = fixtureVersion(a);
    const bLang = fixtureLang(b);
    const bVer = fixtureVersion(b);
    return {
      // Scope is surfaced as three enumerated rows (product_id / programming_language
      // / version) to match the 9-field side-by-side table; live values come
      // from the compare result's full SnapshotRecords, offline from the fixtures.
      baseProduct: live ? live.base_snapshot.product_id : product,
      targetProduct: live ? live.target_snapshot.product_id : product,
      baseLang: live ? live.base_snapshot.programming_language : aLang,
      targetLang: live ? live.target_snapshot.programming_language : bLang,
      baseVersion: live ? live.base_snapshot.version : aVer,
      targetVersion: live ? live.target_snapshot.version : bVer,
      baseStatus: a.active ? "active" : "inactive",
      targetStatus: b.active ? "active" : "inactive",
      sameScope: live ? live.same_scope : aLang === bLang && aVer === bVer,
      sameKind: live ? live.same_source_kind : a.kind === b.kind,
      deltaChunks: live ? live.indexed_chunks_delta : numPts(b.points) - numPts(a.points),
      // "Δ time: {human-readable delta} (seconds/minutes/hours)". Live deltas
      // are humanized to the largest sensible unit; the offline fixtures carry only
      // relative-date strings with no parseable timestamp, so they show created→created.
      deltaTimeLabel: live ? humanizeDelta(live.created_at_delta_seconds) : `${a.created} → ${b.created}`,
    };
  }, [pair, liveCompare, product, liveMode]);

  // 9-field side-by-side: snapshot_id, product_id, programming_language, version,
  // source_kind, source_revision, status, indexed_chunks_count, created_at. Each row
  // carries its base/target values; per-row diff drives the warning highlight.
  const compareRows: [string, string, string][] = cmp
    ? [
        ["snapshot_id", pair[0].id, pair[1].id],
        ["product_id", cmp.baseProduct, cmp.targetProduct],
        ["programming_language", cmp.baseLang, cmp.targetLang],
        ["version", cmp.baseVersion, cmp.targetVersion],
        ["source_kind", pair[0].kind, pair[1].kind],
        ["source_revision", pair[0].rev, pair[1].rev],
        ["status", cmp.baseStatus, cmp.targetStatus],
        ["indexed_chunks_count", pair[0].points, pair[1].points],
        ["created_at", pair[0].created, pair[1].created],
      ]
    : [];

  return (
    // Deep-link target for the Workspaces "Rollback preparation" launcher
    // (Workspaces.tsx anchor "snapshots-active-panel"); the shell's navigate()
    // scrolls/focuses this id. Matches the sibling-section anchor pattern.
    <div id="snapshots-active-panel">
      <div className="toolbar">
        <Select
          label="product_id"
          width={180}
          options={PRODUCTS}
          value={product}
          onChange={(e) => reset(e.target.value)}
        />
        <Select
          label="programming_language"
          width={170}
          options={langOptions}
          value={lang || SCOPE_ANY}
          onChange={(e) =>
            hook.setSnapshotLanguageFilter(e.target.value === SCOPE_ANY ? "" : e.target.value)
          }
        />
        <Select
          label="version"
          width={160}
          options={versionOptions}
          value={hook.snapshotVersionFilter || SCOPE_ANY}
          onChange={(e) =>
            hook.setSnapshotVersionFilter(e.target.value === SCOPE_ANY ? "" : e.target.value)
          }
        />
        <div className="toolbar-right">
          <Button
            variant="btn-ghost"
            size="sm"
            icon="layers"
            disabled={picked.length !== 2 || hook.compareSnapshotsMutation.isPending}
            title={
              picked.length !== 2
                ? "Select exactly two snapshots to compare"
                : hook.compareSnapshotsMutation.isPending
                  ? "Comparison is running"
                  : undefined
            }
            onClick={runCompare}
          >
            Compare selected
          </Button>
        </div>
      </div>

      {/* Active-snapshot resolution states (fill-both-filters / recovery). */}
      {!filtersComplete ? (
        <Banner
          variant="info"
          icon="info"
          title="Fill both filters to resolve active snapshot"
          text="Select a programming_language and version to resolve the exact active snapshot for this scope. The list below shows all published snapshots for the product."
        />
      ) : activeErrored ? (
        <div style={{ marginBottom: 14 }}>
          <ErrorState
            title="No active snapshot for this exact scope"
            text={`The active-snapshot lookup for ${product} / ${lang} / ${version} returned no result.`}
            cause="this scope was likely never published, or its active snapshot was cleaned up"
            actions={
              <>
                <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("ingestion")}>
                  Open Ingestion Jobs
                </Button>
                <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => hook.activeSnapshotQuery.refetch()}>
                  Retry lookup
                </Button>
              </>
            }
          />
        </div>
      ) : !hasActive ? (
        <Banner
          variant="warn"
          icon="alert"
          title="No active snapshot for this scope"
          text={`${product} / ${lang} has published snapshots but none is currently active. Promote one below, or publish new content from Ingestion Jobs.`}
        />
      ) : null}

      <Card
        title="Published snapshots"
        sub={`${snaps.length} snapshot${snaps.length !== 1 ? "s" : ""} for ${product}${lang ? ` / ${lang}` : ""} · ${activeCount} active`}
        flush
        right={
          <div className="toolbar-right" style={{ margin: 0 }}>
            {/* Batch Set Active + Clear Selection. Scope-gated; stay enabled offline. */}
            <span className="muted-note">{selectedCount} selected</span>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="x"
              disabled={selectedCount === 0}
              onClick={clearSelection}
            >
              Clear selection
            </Button>
            <Button
              variant="btn-primary"
              size="sm"
              icon="upload"
              disabled={!canPromote || selectedCount === 0 || hook.promoteSnapshotMutation.isPending}
              title={
                !canPromote
                  ? "Requires write:ingestion scope"
                  : hook.promoteSnapshotMutation.isPending
                    ? "Snapshot promotion is in progress"
                    : undefined
              }
              onClick={batchPromote}
            >
              Batch set active ({selectedCount})
            </Button>
          </div>
        }
      >
        {loading ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={4} />
          </div>
        ) : errored ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Failed to load snapshots"
              cause="the admin API is unreachable"
              actions={
                <Button size="sm" icon="refresh" onClick={() => hook.snapshotsQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : snaps.length ? (
          <div id="snap-list">
            {snaps.map((s) => (
              <div key={s.id} className="snap-row">
                <input
                  type="checkbox"
                  className="snap-cb"
                  checked={selectedIds.includes(s.id)}
                  onChange={() => toggle(s.id)}
                  aria-label={`Select snapshot ${s.id} (${s.active ? "active" : "inactive"})`}
                  style={{ accentColor: "var(--accent-line)" }}
                />
                <div>
                  <div className="snap-id">
                    {s.id} {s.active && <Pill variant="ok">active</Pill>}
                  </div>
                  <div className="snap-meta">
                    {s.rev} · {s.created} · <Tag>{s.kind}</Tag>
                  </div>
                </div>
                <div className="snap-right">
                  <div className="snap-stat">
                    <div className="v">{s.points}</div>
                    <div className="l">points</div>
                  </div>
                  {!s.active && (
                    <Button
                      variant="btn-ghost"
                      size="sm"
                      disabled={!canPromote || hook.promoteSnapshotMutation.isPending}
                      title={
                        canPromote
                          ? hook.promoteSnapshotMutation.isPending
                            ? "Snapshot promotion is in progress"
                            : undefined
                          : "Requires write:ingestion scope"
                      }
                      onClick={() => setActive(s)}
                    >
                      Set active
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No published snapshots"
              text="No published snapshots yet. Publish a snapshot first via Ingestion Jobs, then return to Snapshots to promote it to active."
              action={
                <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("ingestion")}>
                  Open Ingestion Jobs
                </Button>
              }
            />
          </div>
        )}
        {/* Inline promote error (single + batch): an error alert renders
            below the snapshot list for every failed promotion. */}
        {hook.promoteSnapshotMutation.isError && (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Snapshot promotion failed"
              text={getAdminErrorMessage(
                hook.promoteSnapshotMutation.error,
                "The promote request was rejected by the admin API.",
              )}
              cause="the snapshot registry may be unavailable, or the snapshot is invalid for this scope"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="x"
                  onClick={() => hook.promoteSnapshotMutation.reset()}
                >
                  Dismiss
                </Button>
              }
            />
          </div>
        )}
      </Card>

      <div id="snap-compare">
        {/* Live compare reflects the real mutation: pending → skeleton, error →
            error state with retry (fixture math never masks a failure). */}
        {compareOpen && pair.length === 2 && liveMode && hook.compareSnapshotsMutation.isPending && (
          <Card
            title="Snapshot comparison"
            sub="Field-by-field delta between the two selected revisions."
          >
            <Skeleton rows={3} />
          </Card>
        )}
        {compareOpen && pair.length === 2 && liveMode && hook.compareSnapshotsMutation.isError && (
          <Card
            title="Snapshot comparison"
            sub="Field-by-field delta between the two selected revisions."
          >
            <ErrorState
              title="Snapshot comparison failed"
              text={getAdminErrorMessage(
                hook.compareSnapshotsMutation.error,
                "The compare request failed.",
              )}
              cause="the admin API rejected the request or the compare endpoint is unreachable"
              actions={
                <Button variant="btn-ghost" size="sm" icon="refresh" onClick={runCompare}>
                  Retry compare
                </Button>
              }
            />
          </Card>
        )}
        {compareOpen && cmp && pair.length === 2 && (
          <Card
            title="Snapshot comparison"
            sub="Field-by-field delta between the two selected revisions."
          >
            {/* Summary chips — same scope? same source kind? Δ chunks? Δ time? */}
            <div className="qr-delta" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
              <Pill variant={cmp.sameScope ? "ok" : "warn"}>
                {cmp.sameScope ? "same scope" : "scope changed"}
              </Pill>
              <Pill variant={cmp.sameKind ? "ok" : "warn"}>
                {cmp.sameKind ? "same source_kind" : "source_kind changed"}
              </Pill>
              <Pill variant={cmp.deltaChunks === 0 ? "neutral" : cmp.deltaChunks > 0 ? "ok" : "warn"}>
                Δ chunks: {cmp.deltaChunks > 0 ? "+" : ""}
                {cmp.deltaChunks.toLocaleString("en-US")}
              </Pill>
              <Pill variant="info">Δ time: {cmp.deltaTimeLabel}</Pill>
              {/* Promote-safety verdict: interprets the
                  Δ-chunks sign for the operator (positive/zero = safe). */}
              <span className="muted-note">
                {cmp.deltaChunks >= 0
                  ? "Newer snapshot adds content — safe to promote."
                  : "Newer snapshot has fewer points — verify coverage before promoting."}
              </span>
            </div>
            {/* 9-field side-by-side table (differing fields highlighted). */}
            <div style={{ marginTop: 14, overflowX: "auto" }}>
              <TableCard>
                <Table>
                  <thead>
                    <tr>
                      <th>field</th>
                      <th>baseline</th>
                      <th>target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compareRows.map(([field, a, b]) => {
                      // Differing fields highlighted (color warning.main,
                      // fontWeight 600) — applied to both value cells when they differ.
                      const differs = a !== b;
                      const diffStyle = differs
                        ? { color: "var(--warn)", fontWeight: 600 }
                        : undefined;
                      return (
                        <tr className="data" key={field}>
                          <td>
                            <Tag>{field}</Tag>
                          </td>
                          <td className="mono" style={diffStyle}>
                            {a}
                          </td>
                          <td className="mono" style={diffStyle}>
                            {b}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              </TableCard>
            </div>
          </Card>
        )}
      </div>

      {/* Rollback Audit Trail + Cleanup Execution History on the overview. */}
      <AuditTrails hook={hook} />
    </div>
  );
}

// ──────────────────────────────────────────────────────────── Audit trails ──

function AuditTrails({ hook }: { hook: SnapshotHook }) {
  // Live audit rows → fixtures fallback so the trails render fully offline.
  const liveRollback = hook.snapshotRollbackAuditRows;
  const liveCleanup = hook.snapshotCleanupHistoryRows;
  const rollbackRows: SnapshotRollbackAuditRecord[] = liveRollback.length
    ? liveRollback
    : ROLLBACK_AUDIT_FIXTURE;
  const cleanupRows: SnapshotCleanupAuditRecord[] = liveCleanup.length
    ? liveCleanup
    : CLEANUP_HISTORY_FIXTURE;

  return (
    <>
      {/* If no operations are recorded, no audit box is rendered at all. With
          the fixture fallback the display set is non-empty offline (so it always
          renders); a genuinely empty live set with fixtures present still shows
          fixtures, since fixtures take precedence. */}
      {rollbackRows.length > 0 && (
        <Card
          title="Rollback audit trail"
          sub="Recent controlled rollbacks — who reverted which scope, and the result."
          flush
        >
          <TableCard>
            <Table>
              <thead>
                <tr>
                  <th>result</th>
                  <th>target_snapshot_id</th>
                  <th>scope</th>
                  <th>actor_key_id</th>
                  <th>audit_id</th>
                  <th>when</th>
                </tr>
              </thead>
              <tbody>
                {rollbackRows.slice(0, AUDIT_VISIBLE).map((r) => (
                  <RollbackAuditRow key={r.audit_id} row={r} />
                ))}
                {rollbackRows.length > AUDIT_VISIBLE && (
                  <ShowMoreRow
                    colSpan={6}
                    count={rollbackRows.length - AUDIT_VISIBLE}
                    extra={rollbackRows.slice(AUDIT_VISIBLE).map((r) => (
                      <RollbackAuditRow key={r.audit_id} row={r} />
                    ))}
                  />
                )}
              </tbody>
            </Table>
          </TableCard>
        </Card>
      )}

      {cleanupRows.length > 0 && (
        <Card
          title="Cleanup execution history"
          sub="Recent cleanup operations — storage reclaimed and the audit reference for follow-up."
          flush
        >
          <TableCard>
            <Table>
              <thead>
                <tr>
                  <th>status</th>
                  <th>deleted</th>
                  <th>scope</th>
                  <th>actor_key_id</th>
                  <th>audit_id</th>
                  <th>when</th>
                </tr>
              </thead>
              <tbody>
                {cleanupRows.slice(0, AUDIT_VISIBLE).map((r) => (
                  <CleanupAuditRow key={r.audit_id} row={r} />
                ))}
                {cleanupRows.length > AUDIT_VISIBLE && (
                  <ShowMoreRow
                    colSpan={6}
                    count={cleanupRows.length - AUDIT_VISIBLE}
                    extra={cleanupRows.slice(AUDIT_VISIBLE).map((r) => (
                      <CleanupAuditRow key={r.audit_id} row={r} />
                    ))}
                  />
                )}
              </tbody>
            </Table>
          </TableCard>
        </Card>
      )}
    </>
  );
}

function RollbackAuditRow({ row }: { row: SnapshotRollbackAuditRecord }) {
  return (
    <tr className="data">
      <td>
        <Pill variant={auditPill(row.result_status)}>{row.result_status}</Pill>
      </td>
      <td className="mono">{row.target_snapshot_id}</td>
      <td className="mono">
        {row.product_id} / {row.programming_language} / {row.version}
      </td>
      <td>
        <Tag>{row.actor_key_id}</Tag>
      </td>
      <td className="mono">{row.audit_id}</td>
      <td className="mono">{row.created_at}</td>
    </tr>
  );
}

function CleanupAuditRow({ row }: { row: SnapshotCleanupAuditRecord }) {
  const scope = row.product_id + (row.source_kind ? ` / ${row.source_kind}` : "");
  return (
    <tr className="data">
      <td>
        <Pill variant={auditPill(row.result_status)}>{row.result_status}</Pill>
      </td>
      <td className="num">{row.deleted_snapshot_ids.length}</td>
      <td className="mono">{scope}</td>
      <td>
        <Tag>{row.actor_key_id}</Tag>
      </td>
      <td className="mono">{row.audit_id}</td>
      <td className="mono">{row.created_at}</td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────── Rollback panel ──

function RollbackPanel({
  hook,
  data,
  product,
}: {
  hook: SnapshotHook;
  data: ReturnType<typeof useAdminData>;
  product: string;
}) {
  const { toast } = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const canRollback = data.can("write:ingestion");

  // Live inactive snapshots → fixtures fallback (following the selected product) when offline/empty.
  const liveInactive = hook.snapshotRows.filter((s) => s.status !== "active");
  const fixtureInactive = (SNAP_DATA[product] ?? []).filter((s) => !s.active);
  const inactiveOptions = liveInactive.length
    ? liveInactive.map((s) => s.snapshot_id)
    : fixtureInactive.map((s) => s.id);
  // The hook's sync effect clears its rollback target to "" while offline (empty
  // query data), so a local target is held to make the selector VISIBLY respond;
  // the hook setter is still called so live mode re-resolves the target server-side.
  const [localTarget, setLocalTarget] = useState("");
  // Honor the local pick only while it remains a valid option (it may go stale when
  // the product changes offline); otherwise fall back to the first inactive option.
  const localValid = inactiveOptions.includes(localTarget) ? localTarget : "";
  const target =
    hook.snapshotRollbackTargetId || localValid || inactiveOptions[0] || "";
  const reason = hook.snapshotRollbackReason;
  // Resolve the chosen snapshot from the fixture fallback so the scope line tracks
  // the selection offline (hook.selectedRollbackTargetSnapshot is null with no live rows).
  const fixtureTarget = fixtureInactive.find((s) => s.id === target);
  // The confirm summary names the snapshot being replaced.
  // Resolve the currently-active snapshot for the scope (live rows → fixtures) and
  // the target's point count so the dialog states both "from (active)" and "to".
  const liveActive = hook.snapshotRows.find((s) => s.status === "active");
  const fixtureActive = (SNAP_DATA[product] ?? []).find((s) => s.active);
  const fromSnapshotId = liveActive?.snapshot_id ?? fixtureActive?.id ?? "";
  const liveTarget = hook.snapshotRows.find((s) => s.snapshot_id === target);
  const targetPoints =
    (liveTarget ? toSnap(liveTarget).points : undefined) ?? fixtureTarget?.points ?? "";
  const scopeLabel = hook.selectedRollbackTargetSnapshot
    ? `${hook.selectedRollbackTargetSnapshot.product_id} / ${hook.selectedRollbackTargetSnapshot.programming_language} / ${hook.selectedRollbackTargetSnapshot.version}`
    : fixtureTarget
      ? `${product} / ${fixtureLang(fixtureTarget)} / ${fixtureVersion(fixtureTarget)}`
      : `${product} / ${hook.snapshotLanguageFilter || "—"} / ${hook.snapshotVersionFilter || "—"}`;

  // "Selected target already active" guard. Live: the hook's
  // selectedRollbackTargetSnapshot reports status. Offline: derive from fixtures.
  const targetIsActive =
    hook.selectedRollbackTargetSnapshot?.status === "active" ||
    (SNAP_DATA[product] ?? []).some((s) => s.id === target && s.active);
  const noTarget = !target;
  const rollbackPending = hook.rollbackSnapshotMutation.isPending;
  const rollbackDisabled = !canRollback || targetIsActive || noTarget || rollbackPending;
  const disabledReason = !canRollback
    ? "Requires write:ingestion scope"
    : rollbackPending
      ? "Rollback operation is in progress"
      : noTarget
        ? "Select an inactive target snapshot"
        : targetIsActive
          ? "Selected target already active. Choose an older snapshot."
          : undefined;

  // Operation result / audit_id after rollback.
  const result = hook.snapshotRollbackResult;

  return (
    <div className="danger-card">
      <div className="danger-head">
        <Icon name="alert" />
        <span className="dt">Runtime snapshot rollback</span>
        <span className="card-sub" style={{ margin: 0 }}>
          Switches the active runtime snapshot for the selected scope.
        </span>
      </div>
      <div className="danger-body">
        <p className="card-sub" style={{ margin: "0 0 14px" }}>
          Rollback re-points live retrieval traffic to a previous snapshot. Choose the target, then confirm with a
          reason and the typed token in the dialog.
        </p>

        {/* Surface the "target already active" warning before the action. */}
        {targetIsActive && (
          <div style={{ marginBottom: 14 }}>
            <Banner
              variant="warn"
              icon="alert"
              title="Selected target already active"
              text="The chosen snapshot is the one currently served. Choose an older snapshot to roll back to."
            />
          </div>
        )}

        <div className="confirm-row">
          <Select
            label="Roll back to"
            options={inactiveOptions}
            value={target}
            onChange={(e) => {
              setLocalTarget(e.target.value);
              hook.setSnapshotRollbackTargetId(e.target.value);
            }}
          />
          <Input
            label="Reason"
            placeholder="Captured in the dialog · searchable in the audit trail"
            value={reason}
            onChange={(e) => hook.setSnapshotRollbackReason(e.target.value)}
          />
          <div />
          <Button
            variant="btn-danger"
            size="sm"
            icon="alert"
            disabled={rollbackDisabled}
            title={disabledReason}
            onClick={() => setModalOpen(true)}
          >
            Rollback active…
          </Button>
        </div>

        {/* Post-op result block — audit_id / operation_id / before→after. */}
        {result && (
          <div className="drill" style={{ marginTop: 16 }}>
            <div className="drill-kv">
              <span className="kvline">
                result=<b>{result.status}</b>
              </span>
              <span className="kvline">
                audit_id=<b>{result.audit_id}</b>
              </span>
              <span className="kvline">
                operation_id=<b>{result.operation_id}</b>
              </span>
            </div>
            <div className="qr-delta">
              <Tag>{result.active_snapshot_before.snapshot_id}</Tag>
              <Icon name="arrow" className="ico" />
              <Tag>{result.active_snapshot_after.snapshot_id}</Tag>
              <Pill variant="ok">history preserved</Pill>
            </div>
          </div>
        )}

        {/* Inline rollback error: an error alert renders in this panel
            whenever the rollback mutation fails (e.g. preflight rejection). */}
        {hook.rollbackSnapshotMutation.isError && (
          <div style={{ marginTop: 16 }}>
            <ErrorState
              title="Rollback failed"
              text={getAdminErrorMessage(
                hook.rollbackSnapshotMutation.error,
                "The rollback request was rejected.",
              )}
              cause="preflight checks failed or the rollback API is unreachable"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  disabled={rollbackDisabled}
                  title={disabledReason}
                  onClick={() => setModalOpen(true)}
                >
                  Retry rollback…
                </Button>
              }
            />
          </div>
        )}
      </div>

      {modalOpen && (
        <ReasonModal
          config={{
            title: "Rollback active snapshot",
            tone: "danger",
            icon: "alert",
            word: "ROLLBACK",
            reasonLabel: "Rollback reason",
            reasonPlaceholder: "Why is this rollback needed? (searchable for future audits)",
            initialReason: reason,
            confirmLabel: "Rollback active",
            summary: (
              <>
                scope <b>{scopeLabel}</b>
                <br />
                {fromSnapshotId && (
                  <>
                    from <b>{fromSnapshotId}</b> <span className="mono" style={{ color: "var(--ok)" }}>(active)</span>
                    <br />
                  </>
                )}
                to <b>{target}</b>
                {targetPoints && <> · {targetPoints} points</>}
              </>
            ),
            body: "Live retrieval traffic will be re-pointed to the target snapshot. This is reversible by rolling back again, but it changes which content is served immediately.",
            onConfirm: (capturedReason) => {
              hook.setSnapshotRollbackReason(capturedReason);
              if (hook.snapshotRows.length && target) {
                hook.rollbackSnapshotMutation.mutate({ snapshotId: target, reason: capturedReason });
              } else {
                toast(`Rollback complete · ${target} is now active`);
              }
            },
          }}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────── Cleanup panel ──

function CleanupPanel({
  hook,
  data,
  product,
}: {
  hook: SnapshotHook;
  data: ReturnType<typeof useAdminData>;
  product: string;
}) {
  const { toast } = useToast();
  const [previewed, setPreviewed] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  // Cleanup is dual-scoped: the hook's own contract (canPreview/ExecuteSnapshotCleanup)
  // and the API require write:ingestion AND write:destructive. Gate on both so the
  // UI affordance matches what the server will accept.
  const canCleanup = data.can("write:ingestion") && data.can("write:destructive");
  const note = hook.snapshotCleanupReason;

  // Source-kind options from live rows when available; fixtures otherwise. The
  // combined "docs & apiref" entry is ALWAYS first and maps to
  // the hook's empty-string state, so the displayed value and the preview/execute
  // payload (`source_kind=undefined` → both kinds) can never diverge.
  const sourceKindOptions = [
    BOTH_SOURCE_KINDS,
    ...(hook.snapshotSourceKindOptions.length ? hook.snapshotSourceKindOptions : ["docs", "apiref"]),
  ];
  const sourceKind = hook.snapshotCleanupSourceKind || BOTH_SOURCE_KINDS;

  // ONLINE (session ok): the preview surface mirrors the real mutation — result,
  // pending skeleton, or error with retry; fixtures never stand in for a live
  // failure or an empty live result. OFFLINE: the local `previewed` flag drives
  // the fixture preview and the source_kind select filters candidates client-side.
  const online = data.sessionIsSuccess;
  const livePreview = hook.snapshotCleanupPreviewResult;
  const liveCandidates: Snap[] = livePreview ? livePreview.delete_candidates.map(toSnap) : [];
  const fixtureScope = SNAP_DATA[product] ?? SNAP_DATA["aspose.ocr"];
  const fixtureCandidates = fixtureScope.filter(
    (s) => !s.active && (sourceKind === BOTH_SOURCE_KINDS || s.kind === sourceKind),
  );
  const candidates: Snap[] = livePreview ? liveCandidates : online ? [] : fixtureCandidates;
  const protectedCount = livePreview
    ? livePreview.protected_snapshots_count
    : fixtureScope.length - fixtureScope.filter((s) => !s.active).length;
  const scopeLabel = livePreview
    ? `${livePreview.product_id}${livePreview.programming_language ? ` / ${livePreview.programming_language}` : ""}`
    : `${product} / ${sourceKind}`;
  const showPreview = online ? Boolean(livePreview) : previewed;
  const previewPending = online && hook.previewSnapshotCleanupMutation.isPending;
  const previewErrored = online && hook.previewSnapshotCleanupMutation.isError;

  // Live cleanup-policy window (max inactive / stale days) with "?" fallback.
  const policyMax = livePreview
    ? (livePreview.max_inactive_snapshots_per_scope ?? "?")
    : CLEANUP_POLICY_FIXTURE.maxInactive;
  const policyStale = livePreview
    ? (livePreview.stale_snapshot_retention_days ?? "?")
    : CLEANUP_POLICY_FIXTURE.staleDays;

  // risk_summary bullets from the live preview; fixture bullets offline.
  const riskSummary = livePreview
    ? livePreview.risk_summary.length
      ? livePreview.risk_summary
      : []
    : CLEANUP_RISK_FIXTURE;

  // Cleanup execution result — audit_id / deleted count after Execute.
  const execResult = hook.snapshotCleanupExecutionResult;

  // Top 6 candidates only; the rest are summarized by the count.
  const topCandidates = candidates.slice(0, 6);

  return (
    <Card
      title="Snapshot cleanup"
      sub="Removes inactive snapshots beyond retention. Active snapshots are always protected. Preview before executing."
      right={
        <span className="kvline">
          retention: keep <b>{policyMax}</b> · stale <b>{policyStale}d</b>
        </span>
      }
    >
      <div className="confirm-row">
        <Select
          label="source_kind"
          options={sourceKindOptions}
          value={sourceKind}
          onChange={(e) =>
            hook.setSnapshotCleanupSourceKind(
              e.target.value === BOTH_SOURCE_KINDS ? "" : e.target.value,
            )
          }
        />
        <Input
          label="Cleanup note"
          placeholder="Reason for deletion (required to execute)"
          value={note}
          onChange={(e) => hook.setSnapshotCleanupReason(e.target.value)}
        />
        <div />
        <div style={{ display: "flex", gap: 8 }}>
          <Button
            variant="btn-ghost"
            size="sm"
            icon="search"
            disabled={!canCleanup || previewPending}
            title={
              !canCleanup
                ? "Requires write:ingestion and write:destructive scopes"
                : previewPending
                  ? "Cleanup preview is running"
                  : undefined
            }
            onClick={() => {
              setPreviewed(true);
              // Online: run the real preview mutation (its pending/error/result
              // states drive the zone below). Offline: fixtures only — never
              // fire a doomed request just to satisfy the no-op path.
              if (online) {
                hook.runSnapshotCleanupPreview();
              }
            }}
          >
            Preview cleanup
          </Button>
          <Button
            variant="btn-danger"
            size="sm"
            icon="alert"
            disabled={
              !canCleanup ||
              !showPreview ||
              candidates.length === 0 ||
              hook.executeSnapshotCleanupMutation.isPending
            }
            title={
              !canCleanup
                ? "Requires write:ingestion and write:destructive scopes"
                : !showPreview
                  ? "Run cleanup preview first"
                  : candidates.length === 0
                    ? "Preview found no deletable inactive snapshots."
                    : hook.executeSnapshotCleanupMutation.isPending
                      ? "Cleanup execution is in progress"
                      : undefined
            }
            onClick={() => setModalOpen(true)}
          >
            Execute
          </Button>
        </div>
      </div>

      <div id="cleanup-preview" style={{ marginTop: 14 }}>
        {previewPending ? (
          <Skeleton rows={3} />
        ) : previewErrored ? (
          /* Inline preview error: an error alert renders below the
             Preview button; fixtures never mask a live preview failure. */
          <ErrorState
            title="Cleanup preview failed"
            text={getAdminErrorMessage(
              hook.previewSnapshotCleanupMutation.error,
              "The cleanup-preview request failed.",
            )}
            cause="the snapshot registry or index services may be unavailable"
            actions={
              <Button
                variant="btn-ghost"
                size="sm"
                icon="refresh"
                onClick={() => hook.runSnapshotCleanupPreview()}
              >
                Retry preview
              </Button>
            }
          />
        ) : !showPreview ? (
          <p className="muted-note">No preview yet — run "Preview cleanup" to list deletion candidates.</p>
        ) : candidates.length === 0 ? (
          <EmptyState
            title="No deletable snapshots"
            text="Preview found no inactive snapshots beyond retention for this scope. Execute is disabled."
          />
        ) : (
          <>
            <div className="drill-kv" style={{ marginBottom: 12 }}>
              <span className="kvline">
                delete_candidates=<b>{candidates.length}</b>
              </span>
              <span className="kvline">
                protected=<b>{protectedCount}</b>
              </span>
              <span className="kvline">
                scope=<b>{scopeLabel}</b>
              </span>
            </div>

            {/* Risk summary bullets. */}
            {riskSummary.length > 0 && (
              <ol className="fix-steps" style={{ marginBottom: 14 }}>
                {riskSummary.map((bullet, i) => (
                  <li key={i}>
                    <span>{bullet}</span>
                  </li>
                ))}
              </ol>
            )}

            <div className="muted-note" style={{ marginBottom: 8 }}>
              Top {topCandidates.length} candidate{topCandidates.length !== 1 ? "s" : ""}
              {candidates.length > topCandidates.length ? ` of ${candidates.length}` : ""}
            </div>
            <div id="snap-list">
              {topCandidates.map((s) => (
                <div key={s.id} className="snap-row">
                  <div>
                    <div className="snap-id">{s.id}</div>
                    <div className="snap-meta">
                      {s.rev} · {s.created} · <Tag>{s.kind}</Tag>
                    </div>
                  </div>
                  <div className="snap-right">
                    <div className="snap-stat">
                      <div className="v">{s.points}</div>
                      <div className="l">points</div>
                    </div>
                    <Pill variant="neutral">candidate</Pill>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Cleanup execution result — audit_id / deleted count. */}
        {execResult && (
          <div className="drill" style={{ marginTop: 16 }}>
            <div className="drill-kv">
              <span className="kvline">
                status=<b>{execResult.status}</b>
              </span>
              <span className="kvline">
                audit_id=<b>{execResult.audit_id}</b>
              </span>
              <span className="kvline">
                deleted=<b>{execResult.deleted_snapshots_count}</b>
              </span>
            </div>
            <p style={{ margin: 0 }}>
              Cleanup recorded. Reference <span className="mono">{execResult.audit_id}</span> in SQL Explorer or
              Critical Events for follow-up.
            </p>
          </div>
        )}

        {/* Inline execute error: an error alert renders below Execute
            whenever the cleanup mutation fails. */}
        {hook.executeSnapshotCleanupMutation.isError && (
          <div style={{ marginTop: 16 }}>
            <ErrorState
              title="Cleanup execution failed"
              text={getAdminErrorMessage(
                hook.executeSnapshotCleanupMutation.error,
                "The cleanup request was rejected.",
              )}
              cause="the deletion may be partially applied — verify in Cleanup execution history before retrying"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => setModalOpen(true)}
                >
                  Retry execute…
                </Button>
              }
            />
          </div>
        )}
      </div>

      {modalOpen && (
        <ReasonModal
          config={{
            title: "Execute snapshot cleanup",
            tone: "danger",
            icon: "alert",
            word: "DELETE",
            reasonLabel: "Cleanup reason",
            reasonPlaceholder: "Why delete these snapshots now? (recorded with the audit entry)",
            initialReason: note,
            confirmLabel: `Delete ${candidates.length}`,
            summary: (
              <>
                deleting <b>{candidates.length}</b> inactive snapshot{candidates.length !== 1 ? "s" : ""}
                <br />
                protected <b>{protectedCount}</b> active · scope <b>{scopeLabel}</b>
              </>
            ),
            body: "This permanently deletes the inactive snapshots in the preview and reclaims their index storage. Active snapshots are never deleted. This cannot be undone.",
            onConfirm: (capturedReason) => {
              hook.setSnapshotCleanupReason(capturedReason);
              if (livePreview) {
                hook.executeSnapshotCleanupMutation.mutate({
                  product_id: livePreview.product_id || product,
                  programming_language: hook.snapshotLanguageFilter.trim() || undefined,
                  version: hook.snapshotVersionFilter.trim() || undefined,
                  source_kind: hook.snapshotCleanupSourceKind.trim() || undefined,
                  reason: capturedReason,
                });
              } else {
                toast(`Cleanup executed · ${candidates.length} snapshots deleted`);
              }
            },
          }}
          onClose={() => setModalOpen(false)}
        />
      )}
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────── Section ──

export function SnapshotsSection() {
  const data = useAdminData();
  // The hook owns language/version filters + compare/rollback/cleanup state, but
  // NOT product — the section owns it and feeds the hook's `selectedProductId`.
  const [product, setProduct] = useState(PRODUCTS[0]);
  const hook = useSnapshotState({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "snapshots",
    selectedProductId: product,
    canMutateIngestion: data.can("write:ingestion"),
    canRunDestructive: data.can("write:destructive"),
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
  });

  return (
    <>
      <PageHead
        title="Snapshots"
        sub="Manage active published retrieval snapshots, compare revisions, and execute controlled rollback."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            <ScopeChip label="scope" value="write:ingestion" dot />
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              onClick={() => hook.snapshotsQuery.refetch()}
            >
              Refresh
            </Button>
          </>
        }
      />

      <Tabbed
        tabs={["Active & Compare", "Rollback", "Cleanup"]}
        panels={[
          <ActiveComparePanel key="ac" hook={hook} data={data} product={product} setProduct={setProduct} />,
          <RollbackPanel key="rb" hook={hook} data={data} product={product} />,
          <CleanupPanel key="cl" hook={hook} data={data} product={product} />,
        ]}
        initial={0}
      />
    </>
  );
}

// ───────────────────────────────────────────────── Module-level edge states ──
// Rendered when the section is mounted in a degraded/restricted context. These
// cover the required states (loading / permission / read-only); the
// Section above renders the happy path. Exported helpers keep them tree-shake-
// able and available to the shell's state harness without a second file.

export function SnapshotsLoading() {
  return (
    <>
      <PageHead
        title="Snapshots"
        sub="Manage active published retrieval snapshots, compare revisions, and execute controlled rollback."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <Card title="Published snapshots" flush>
        <div style={{ padding: 16 }}>
          <Skeleton rows={4} />
        </div>
      </Card>
    </>
  );
}

export function SnapshotsDenied() {
  return (
    <>
      <PageHead
        title="Snapshots"
        sub="Manage active published retrieval snapshots, compare revisions, and execute controlled rollback."
        onHelp={() => {
          window.location.href = "/howto";
        }}
      />
      <PermissionDenied
        scope="write:ingestion"
        extra="Snapshot promotion and rollback require an ingestion-scoped key. Read-only viewers can still inspect the list."
      />
    </>
  );
}

export function SnapshotsReadonly() {
  return (
    <>
      <ReadonlyBanner />
      <SnapshotsSection />
    </>
  );
}
