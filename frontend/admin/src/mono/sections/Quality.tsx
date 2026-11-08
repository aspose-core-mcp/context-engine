"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { useQualityReviews, type QualityReviewMutationAction } from "@/hooks/useQualityReviews";
import type {
  QualityReviewApprovalMode,
  QualityReviewApprovalTrail,
  QualityReviewBatchActionResponse,
  QualityReviewBlockingFinding,
  QualityReviewGuidedFixPlan,
  QualityReviewReviewerVote,
  QualityReviewRun,
  QualityReviewRunOrigin,
} from "@/lib/admin-api";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Segmented, Select } from "../components/Field";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { ShowMoreRow } from "../components/Table";
import { Tabs } from "../components/Tabbed";
import { Tag } from "../components/Tag";
import {
  EmptyState,
  ErrorState,
  PermissionDenied,
  Skeleton,
  StaleBadge,
} from "../components/states";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";
import { useConfirm, useToast } from "../shell/overlays";

// ─────────────────────────────────────────────────────────── Fixtures ───────

const PRODUCTS = ["aspose.ocr", "aspose.cells", "aspose.words", "aspose.barcode"];
const VERSIONS = ["latest", "v24.1", "v24.2"];

/**
 * Strictness presets. Names match the preset set (balanced / strict /
 * throughput). Each tuple matches the five policy fields below, in order.
 */
type PresetKey = "Balanced" | "Strict" | "Throughput";
const PRESETS: PresetKey[] = ["Balanced", "Strict", "Throughput"];
const QPOLICY: Record<PresetKey, [string, string, string, string, string]> = {
  Balanced: ["0.80", "0.70", "0.90", "60", "Block on fail"],
  Strict: ["0.90", "0.85", "0.95", "80", "Block on fail"],
  Throughput: ["0.65", "0.55", "0.78", "40", "Warn on fail"],
};
/** Per-preset one-line trade-off shown under the segmented control. */
const PRESET_NOTE: Record<PresetKey, string> = {
  Balanced: "Default quality/velocity balance — blocks runs below threshold.",
  Strict: "Tightest gate and largest sample — fewest escapes, slower throughput.",
  Throughput: "Looser gate for high release volume — warns instead of blocking.",
};
const QFIELDS: [name: string, desc: string][] = [
  ["Accuracy threshold", "Minimum factual-accuracy score to pass a document"],
  ["Completeness threshold", "Required coverage of the source material"],
  ["Citation quality", "Minimum share of claims with valid citations"],
  ["Sample size", "Documents sampled per run"],
  ["Gate policy", "Block publish when a run fails"],
];

/** A semantic review run's status bucket — drives the row status pill. */
type RunStatusKey = "passed" | "review" | "failed" | "running";

/** A semantic review run row. */
type RunRow = [
  id: string,
  product: string,
  version: string,
  res: StatusVariant,
  score: string,
  status: RunStatusKey,
  when: string,
  blocking: number,
  threshold: string,
];

const RUNS: RunRow[] = [
  ["rev_8c3864e", "aspose.ocr", "latest", "ok", "0.91", "passed", "today 12:20", 0, "0.86"],
  ["rev_4a1f9b2", "aspose.ocr", "latest", "warn", "0.74", "review", "today 11:05", 2, "0.86"],
  ["rev_9b02e5a", "aspose.words", "v24.2", "neutral", "—", "running", "today 11:58", 0, "0.86"],
  ["rev_2c77d10", "aspose.cells", "v24.1", "crit", "0.58", "failed", "yesterday", 5, "0.86"],
  ["rev_7d51c93", "aspose.barcode", "v24.1", "ok", "0.88", "passed", "yesterday", 0, "0.86"],
  ["rev_3e90a64", "aspose.ocr", "v24.2", "warn", "0.79", "review", "2 days ago", 1, "0.86"],
  ["rev_1f22b08", "aspose.cells", "latest", "ok", "0.92", "passed", "2 days ago", 0, "0.86"],
];

/** Run-status → [pill variant, pill label]. */
const RUN_STATUS: Record<RunStatusKey, [StatusVariant, string]> = {
  passed: ["ok", "approved"],
  review: ["warn", "awaiting approval"],
  failed: ["crit", "blocked"],
  running: ["info", "in progress"],
};

interface Finding {
  type: string;
  sev: "critical" | "warning";
  path: string;
  evidence: string;
}

interface RunDetail {
  score: string;
  thr: string;
  sampled: number;
  evaluated: number;
  findings: Finding[];
  votes: string;
  trail: [action: string, who: string, when: string, why: string][];
  /** Optional guided-fix handoff (present when run was triggered from an analytics issue). */
  guided: GuidedFix | null;
}

/**
 * API limitation (offline only): the live `QualityReviewRun` carries `origin` +
 * `guided_fix_plan`, but the fixture runs are not analytics-triggered, so this
 * fixture supplies a representative guided-fix handoff for the offline review
 * detail. Online, `originToGuided` maps the real run fields instead.
 */
interface GuidedFix {
  origin: string;
  issueId: string;
  requestId: string;
  severity: string;
  summary: string;
  owner: string;
  priority: string;
  nextStep: string;
  steps: [title: string, detail: string, target: string][];
}

const GUIDED_FIX: GuidedFix = {
  origin: "analytics_issue_investigation",
  issueId: "iss_5f2a91",
  requestId: "req_8c3864e",
  severity: "warning",
  summary: "Citation anchors dropped on 2 OCR recognize chunks after the last ingestion.",
  owner: "ingestion-engineer",
  priority: "high",
  nextStep: "Re-parse the affected source revision, then re-run the review to confirm 0 blocking.",
  steps: [
    [
      "Re-parse source documents",
      "Open the ingestion job for this source revision and re-run normalization.",
      "ingestion",
    ],
    [
      "Verify citation anchors",
      "Confirm section anchors are emitted for every chunk in the staging preview.",
      "ingestion",
    ],
    [
      "Re-run semantic review",
      "Trigger a fresh run on the corrected revision and approve when blocking = 0.",
      "quality-reviews",
    ],
  ],
};

const QDETAIL: Record<string, RunDetail> = {
  rev_8c3864e: {
    score: "0.91",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 60,
    findings: [],
    votes: "3 approve · 0 reject",
    trail: [["approved", "su@local", "today 12:21", "score above threshold, 0 blocking"]],
    guided: null,
  },
  rev_4a1f9b2: {
    score: "0.74",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 58,
    findings: [
      {
        type: "citation_loss",
        sev: "warning",
        path: "content/ocr/recognize.md",
        evidence: "source anchor missing on 2 chunks",
      },
    ],
    votes: "1 approve · 1 reject",
    trail: [["ran", "system", "today 11:05", "sampled 60 docs"]],
    guided: GUIDED_FIX,
  },
  rev_9b02e5a: {
    score: "—",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 22,
    findings: [],
    votes: "0 approve · 0 reject",
    trail: [["ran", "system", "today 11:58", "semantic analysis in progress"]],
    guided: null,
  },
  rev_2c77d10: {
    score: "0.58",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 60,
    findings: [
      {
        type: "hallucinated_api_member",
        sev: "critical",
        path: "api/cells/PivotTable.md",
        evidence: "member Cells.PivotTable.AutoGroup does not exist",
      },
      {
        type: "invalid_signature",
        sev: "critical",
        path: "api/cells/Range.md",
        evidence: "parameter order differs from source",
      },
    ],
    votes: "0 approve · 2 reject",
    trail: [
      ["ran", "system", "yesterday", "sampled 60 docs"],
      ["blocked", "system", "yesterday", "2 blocking findings"],
    ],
    guided: null,
  },
  rev_7d51c93: {
    score: "0.88",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 60,
    findings: [],
    votes: "2 approve · 0 reject",
    trail: [["approved", "su@local", "yesterday", "score above threshold, 0 blocking"]],
    guided: null,
  },
  rev_3e90a64: {
    score: "0.79",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 59,
    findings: [
      {
        type: "citation_loss",
        sev: "warning",
        path: "content/ocr/settings.md",
        evidence: "broken canonical URL on 1 chunk",
      },
    ],
    votes: "1 approve · 0 reject",
    trail: [["ran", "system", "2 days ago", "sampled 60 docs"]],
    guided: null,
  },
  rev_1f22b08: {
    score: "0.92",
    thr: "4.3 (0.86)",
    sampled: 60,
    evaluated: 60,
    findings: [],
    votes: "3 approve · 0 reject",
    trail: [["approved", "su@local", "2 days ago", "score above threshold, 0 blocking"]],
    guided: null,
  },
};

/**
 * Run Diff panel fallbacks (offline only): the diff compares a base run vs a candidate
 * run side-by-side. When a selected base/candidate id has no matching `QDETAIL` row, these
 * named details stand in so each side always resolves to populated score + blocking data —
 * keeping the offline diff (deltas, improvement verdict) consistent with the run diff
 * delta: score change, blocking findings added/removed. Base = a clean passing
 * run; candidate = a regressed run, so the offline default reads as a real regression.
 * Online, the live diff response and per-run records supply these instead.
 */
const DIFF_FALLBACK_BASE: RunDetail = QDETAIL.rev_8c3864e;
const DIFF_FALLBACK_CANDIDATE: RunDetail = QDETAIL.rev_2c77d10;

const RUN_IDS = RUNS.map((r) => r[0]);

/**
 * approval_mode select options. Raw enum
 * values — the kit Select renders value === label.
 */
const APPROVAL_MODES: QualityReviewApprovalMode[] = ["human_approve_all", "auto_approve"];

/** Mutation scope required to launch runs, change policy, or approve/reject. */
const WRITE_SCOPE = "write:settings";

/** Default number of run rows shown before the "Load more" control. */
const RUN_PAGE = 5;

/** Minimum length of a rejection reason (safety-critical: decision must be documented). */
const REASON_MIN = 8;

// ───────────────────────────────────── Live → fixture-shape adapters ─────────
// Map the hook's QualityReviewRun records onto the render shapes the fixtures
// use, so the existing markup binds live data unchanged and still renders the
// fixtures when offline.

/** Run status → the fixture's status bucket (includes a live running state). */
function runStatusBucket(run: QualityReviewRun): RunStatusKey {
  if (run.status === "running" || run.status === "in_progress") return "running";
  if (run.status === "approved") return "passed";
  if (run.status === "rejected" || run.status === "blocked") return "failed";
  return "review";
}

/** Run status → result pill variant. */
function runResultVariant(run: QualityReviewRun): StatusVariant {
  if (run.status === "running" || run.status === "in_progress") return "neutral";
  if (run.summary.pass_gates && run.blocking_error_count === 0) return "ok";
  if (run.blocking_error_count > 0 || run.status === "rejected" || run.status === "blocked")
    return "crit";
  return "warn";
}

function fmtScore(value: number): string {
  return value.toFixed(2);
}

function fmtWhen(run: QualityReviewRun): string {
  const iso = run.finished_at ?? run.created_at;
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isRunning(status: RunStatusKey): boolean {
  return status === "running";
}

function runToRow(run: QualityReviewRun): RunRow {
  const running = run.status === "running" || run.status === "in_progress";
  return [
    run.run_id,
    run.product_id,
    run.version ?? "latest",
    runResultVariant(run),
    running ? "—" : fmtScore(run.summary.overall_score),
    runStatusBucket(run),
    fmtWhen(run),
    run.blocking_error_count,
    fmtScore(run.summary.threshold_score),
  ];
}

/** Blocking-error-type → the fixture's short finding label. */
function findingType(kind: QualityReviewBlockingFinding["blocking_error_type"]): string {
  if (kind === "hallucinated_api_member") return "hallucinated_api_member";
  if (kind === "invalid_signature_or_parameters_or_returns") return "invalid_signature";
  return "citation_loss";
}

function findingToFixture(f: QualityReviewBlockingFinding): Finding {
  // hallucinated members + bad signatures are publish-blocking (critical); citation loss is a warning.
  const critical = f.blocking_error_type !== "citation_or_source_path_loss";
  return {
    type: findingType(f.blocking_error_type),
    sev: critical ? "critical" : "warning",
    path: f.source_path,
    evidence: f.review_notes ?? `score ${f.score.toFixed(2)} on ${f.stratum}`,
  };
}

function votesLine(votes: QualityReviewReviewerVote[]): string {
  const approve = votes.filter((v) => v.decision === "approve").length;
  const reject = votes.filter((v) => v.decision === "reject").length;
  return `${approve} approve · ${reject} reject`;
}

function trailRows(trail: QualityReviewApprovalTrail[]): RunDetail["trail"] {
  return trail.map((t) => [
    t.action,
    t.actor_key_id ?? t.actor_type,
    new Date(t.created_at).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    t.reason ?? "—",
  ]);
}

/** Live origin + guided-fix-plan → the fixture's GuidedFix render shape (or null). */
function originToGuided(
  origin: QualityReviewRunOrigin | null,
  plan: QualityReviewGuidedFixPlan | null,
): GuidedFix | null {
  if (!plan || !origin) return null;
  return {
    origin: origin.source,
    issueId: origin.issue_id ?? "—",
    requestId: origin.request_id ?? "—",
    severity: origin.severity ?? "—",
    summary: plan.summary,
    owner: plan.owner_hint,
    priority: plan.priority,
    nextStep: plan.next_step,
    steps: plan.actions.map((a) => [a.title, a.detail, a.target_section]),
  };
}

function runToDetail(run: QualityReviewRun): RunDetail {
  return {
    score: run.status === "running" ? "—" : fmtScore(run.summary.overall_score),
    thr: fmtScore(run.summary.threshold_score),
    sampled: run.summary.sampled_count,
    evaluated: run.summary.evaluated_count,
    findings: run.blocking_findings.map(findingToFixture),
    votes: votesLine(run.reviewer_votes),
    trail: trailRows(run.approval_trail),
    guided: originToGuided(run.origin, run.guided_fix_plan),
  };
}

// ─────────────────────────────────────────────── Mutation error surfacing ───
// Every mutation failure surfaces — toast for all, plus a dedicated
// alert (alert dialog for create/preset validation errors,
// inline error alert for policy / batch / approve / reject, warning alert for
// the run diff). Success toasts fire ONLY from onSuccess, never optimistically.

function errMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}

/** Hook-level onError → toast prefix per mutating action. */
const MUTATION_ERROR_COPY: Record<QualityReviewMutationAction, string> = {
  patch_policy: "Couldn't save policy",
  apply_preset: "Couldn't apply preset",
  create_run: "Couldn't start semantic review",
  approve_run: "Couldn't approve run",
  reject_run: "Couldn't reject run",
  batch_approve: "Batch approve failed",
  batch_reject: "Batch reject failed",
};

/** Per-run failure reasons from a batch approve/reject response. */
function batchFailureLines(res: QualityReviewBatchActionResponse): string[] {
  const failed = res.results.filter((r) => r.status === "failed");
  if (!failed.length) return ["No per-run failure details were returned."];
  return failed.map((r) => `${r.run_id} — ${r.message ?? "failed"}`);
}

/** Inline batch-action failure notice (per-run reasons), rendered above the batch bar. */
interface BatchIssue {
  title: string;
  lines: string[];
  hint: string;
}

// ─────────────────────────────────────── Running-state pulse indicator ──────

/** Pulsing dot (reuses the `ledpulse` keyframes) shown next to in-flight runs. */
function RunningPulse() {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: 999,
        background: "var(--info)",
        boxShadow: "0 0 0 0 color-mix(in srgb, var(--info) 70%, transparent)",
        animation: "ledpulse 2.4s infinite",
        flex: "none",
      }}
    />
  );
}

// ───────────────────────────────────────── Reason-capture modal (inline) ────
// Reuses ConfirmModal's overlay/modal classes so it matches the design system
// exactly, but swaps the typed-word gate for a free-text <textarea> with a
// minimum-length requirement (safety-critical: the rejection decision must be
// documented before the mutation fires). Traps focus + closes on Escape.

interface ReasonRequest {
  title: string;
  summary: ReactNode;
  confirmLabel: string;
  onSubmit: (reason: string) => void;
}

function ReasonModal({ request, onClose }: { request: ReasonRequest; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fieldId = useId();
  const trimmed = reason.trim();
  const ok = trimmed.length >= REASON_MIN;

  useEffect(() => {
    areaRef.current?.focus();
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

  function submit() {
    if (!ok) return;
    request.onSubmit(trimmed);
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="qr-reason-title" ref={modalRef}>
        <div className="modal-head">
          <div className="mi">
            <Icon name="x" />
          </div>
          <div className="modal-title" id="qr-reason-title">
            {request.title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div className="sum">{request.summary}</div>
          <div className="modal-field">
            <label htmlFor={fieldId}>Rejection reason (recorded in approval trail)</label>
            <textarea
              id={fieldId}
              ref={areaRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-required="true"
              aria-describedby={`${fieldId}-hint`}
              spellCheck
              rows={3}
              placeholder="Document why this run is being rejected…"
              style={{
                width: "100%",
                minHeight: 76,
                resize: "vertical",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                padding: "9px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: "var(--fg)",
                outline: "none",
              }}
            />
            <div className="confirm-hint" id={`${fieldId}-hint`}>
              {ok
                ? "Reason will be stored on the approval trail for audit compliance."
                : `Enter at least ${REASON_MIN} characters (${trimmed.length}/${REASON_MIN}).`}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" disabled={!ok} onClick={submit}>
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Alert dialog (error modal) ───
// Mono alert-dialog modal: shown on
// create-run / preset validation failures. Reuses ConfirmModal's overlay/modal
// classes; initial focus on OK, Escape closes, focus stays trapped.

interface AlertRequest {
  title: string;
  message: string;
  hint?: string;
}

function AlertModal({ request, onClose }: { request: AlertRequest; onClose: () => void }) {
  const modalRef = useRef<HTMLDivElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
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
    return () => document.removeEventListener("keydown", onKey);
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
        aria-labelledby="qr-alert-title"
        aria-describedby="qr-alert-message"
        ref={modalRef}
      >
        <div className="modal-head">
          <div className="mi">
            <Icon name="alert" />
          </div>
          <div className="modal-title" id="qr-alert-title">
            {request.title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div className="sum" id="qr-alert-message">
            {request.message}
          </div>
          {request.hint && <p>{request.hint}</p>}
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

// ─────────────────────────────────────────── Run-diff warning alert ─────────
// qualityRunDiffQuery.isError → Alert severity=WARNING with
// the message — never a silent fall back to client-computed deltas. Reuses the
// `.recovery.warn` role=alert primitive (same structure as the kit ErrorState).

function DiffWarningAlert({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="recovery warn" role="alert">
      <div className="rec-ico">
        <Icon name="alert" />
      </div>
      <div className="rec-body">
        <div className="rec-title">Could not compute run diff</div>
        <div className="rec-text">{message}</div>
        <div className="rec-cause">
          Likely cause: baseline or candidate run id missing, or the runs belong to different
          products
        </div>
        <div className="rec-actions">
          <Button variant="btn-ghost" size="sm" icon="refresh" onClick={onRetry}>
            Retry diff
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────── Blocking-findings list ─────

function FindingList({ findings }: { findings: Finding[] }) {
  if (!findings.length) {
    return <div className="muted-note">No blocking findings — content is publish-safe.</div>;
  }
  return (
    <>
      {findings.map((f) => (
        <div
          className="crit-row"
          key={`${f.type}-${f.path}`}
          style={
            f.sev === "warning"
              ? {
                  borderColor: "color-mix(in srgb, var(--warn) 26%, var(--border))",
                  background: "var(--warn-bg)",
                }
              : undefined
          }
        >
          <Icon name="alert" />
          <span>
            <b>{f.type}</b> · {f.path}
            <br />
            <span style={{ color: "var(--fg-subtle)" }}>{f.evidence}</span>
          </span>
          <span style={{ marginLeft: "auto" }}>
            <Pill variant={f.sev === "critical" ? "crit" : "warn"}>{f.sev}</Pill>
          </span>
        </div>
      ))}
    </>
  );
}

// ─────────────────────────────────────────── Guided-fix handoff panel ───────

function GuidedFixPanel({ guided, onOpenOrigin }: { guided: GuidedFix; onOpenOrigin: () => void }) {
  return (
    <div className="qr-guided">
      <div className="eh" style={{ marginTop: 13 }}>
        Guided fix plan
      </div>
      <div className="crit-row" style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}>
        <Icon name="review" />
        <span>
          {guided.summary}
          <br />
          <span style={{ color: "var(--fg-subtle)" }}>
            owner {guided.owner} · next: {guided.nextStep}
          </span>
        </span>
        <span style={{ marginLeft: "auto" }}>
          <Pill variant={guided.priority === "critical" ? "crit" : "warn"}>{guided.priority}</Pill>
        </span>
      </div>
      <div className="kvline" style={{ marginTop: 6 }}>
        origin=<b>{guided.origin}</b> · issue=<b>{guided.issueId}</b> · request=<b>{guided.requestId}</b> ·
        severity=<b>{guided.severity}</b>
      </div>
      <ol className="fix-steps" style={{ marginTop: 8 }}>
        {guided.steps.map(([title, detail, target], i) => (
          <li key={i}>
            <span>
              <b>{title}</b> — {detail} <Tag>{target}</Tag>
            </span>
          </li>
        ))}
      </ol>
      <div className="qr-acts">
        <Button variant="btn-ghost" size="sm" icon="arrow" onClick={onOpenOrigin}>
          Open analytics issue
        </Button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────── Section ──────

export function QualitySection() {
  const { navigate, consumeIntent } = useShell();
  const { confirm } = useConfirm();
  const { toast } = useToast();
  const data = useAdminData();

  // Controlled tab index so in-panel CTAs can
  // switch tabs programmatically — e.g. the empty Review Runs state jumps to
  // Run & Queue (tab 0). 0 = Run & Queue (the default landing tab).
  const [activeTab, setActiveTab] = useState(0);

  // Reason-capture modal request (single + batch reject share this surface).
  const [reasonRequest, setReasonRequest] = useState<ReasonRequest | null>(null);
  // Alert-dialog request: create-run / preset validation errors.
  const [alertRequest, setAlertRequest] = useState<AlertRequest | null>(null);
  // Inline batch failure notice (per-run reasons from the batch response or a hard error).
  const [batchIssue, setBatchIssue] = useState<BatchIssue | null>(null);

  // ONLINE = session established; mutations hit the backend and surface their
  // real outcome. OFFLINE = fixtures everywhere; mutating actions stay clickable
  // and no-op with an optimistic toast (deliberate, mirrors Config).
  const online = data.sessionIsSuccess;

  // ── Tab 1: Run & Queue ─────────────────────────────────────────────────
  // Product is section-local (Mono shell has no global product selector); the
  // hook owns version + source-revision state and uses both as inputs.
  const [product, setProduct] = useState(PRODUCTS[0]);

  // ── Cross-section prefill handoff ──────────────────────────────────────
  // Drain the one-shot SectionIntent another section stashed under "quality" when it
  // navigated here (e.g. Analytics/Coverage deep-linking a product into a review run).
  // Only the supported `product` filter is applied — to the run product input via this
  // section's own setProduct (the same write path the toolbar Select uses); unknown
  // filter keys are ignored gracefully. An incoming value is resolved against the known
  // PRODUCTS list (exact id or short slug like "ocr" → "aspose.ocr"); an unrecognized
  // product is a no-op so the input never holds an out-of-range value. `reset` clears the
  // run product back to its default first. consumeIntent is one-shot (it clears the
  // payload) and the empty-dep effect runs once, so the handoff never re-applies.
  useEffect(() => {
    const intent = consumeIntent("quality");
    if (!intent) return;
    if (intent.reset) {
      // Reset to a clean slate before applying — the run product is the only state
      // this handoff touches, so restore it to the default first.
      setProduct(PRODUCTS[0]);
    }
    const want = intent.filters?.product;
    if (want != null && want !== "") {
      const resolved =
        PRODUCTS.find((p) => p === want) ??
        PRODUCTS.find((p) => p === `aspose.${want}` || p.split(".").pop() === want);
      if (resolved) setProduct(resolved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const q = useQualityReviews({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "quality-reviews",
    selectedProductId: product,
    snapshotVersionOptions: VERSIONS,
    // Every mutation failure surfaces. Toast here (all seven
    // mutations); the alert dialog / inline alerts are wired at
    // each mutate call below. Mutations only fire online, so this never reports
    // the doomed offline request.
    onMutationError: (action, error) =>
      toast(`${MUTATION_ERROR_COPY[action]} — ${errMessage(error)}`),
  });

  const goHelp = () => {
    window.location.href = "/howto";
  };

  // Live runs; fixtures only stand in while OFFLINE (session not established →
  // the query is disabled). ONLINE, the live result is authoritative: success
  // with no rows → EmptyState; error → ErrorState with retry —
  // fixtures are never silently substituted for a live outcome.
  const liveRuns = q.qualityReviewRunsQuery.data ?? [];
  const hasLiveRuns = liveRuns.length > 0;
  const runRows: RunRow[] = hasLiveRuns ? liveRuns.map(runToRow) : online ? [] : RUNS;
  const runningCount = runRows.filter((r) => isRunning(r[5])).length;

  // write:settings gates every mutating control.
  const canWrite = data.can(WRITE_SCOPE);
  // Runs list state — offline the disabled query is never loading/errored, so the
  // populated fixture set always renders; online the real query state drives the
  // skeleton / error panels (stale rows win over the error).
  const runsLoading = online && q.qualityReviewRunsQuery.isLoading;
  const runsErrored = online && q.qualityReviewRunsQuery.isError && !hasLiveRuns;
  // API limitation: no semantic_review_service liveness signal on these endpoints — the
  // "service down" badge/banner stays fixture-driven (off) until an ops health field exists.
  const serviceDegraded = false;

  // Hook-owned version + source revision (drives Tab 1 inputs and the run mutation).
  const version = q.qualityRunVersion;
  const setVersion = q.setQualityRunVersion;
  const revision = q.qualitySourceRevision;
  const setRevision = q.setQualitySourceRevision;
  const versionOptions = q.qualityVersionOptions.length ? q.qualityVersionOptions : VERSIONS;

  const runQueuePanel = (
    <>
      <Banner
        variant="info"
        icon="info"
        guidance
        title="Start a new quality review"
        text="Choose product, version, and source revision, then run. The system samples documents from the latest ingestion and scores accuracy, completeness, and citation quality."
      />
      <Card
        title="Run execution & review queue"
        sub="Only documents of the selected version are sampled."
      >
        <div className="toolbar">
          <Select
            label="product_id"
            width={190}
            options={PRODUCTS}
            value={product}
            onChange={(e) => setProduct(e.target.value)}
          />
          <Select
            label="version"
            width={160}
            options={versionOptions}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
          <Input
            label="source_revision"
            width={200}
            placeholder="dev-local (SHA or tag)"
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
          />
          <div className="toolbar-right">
            <Button
              variant="btn-primary"
              size="sm"
              icon="play"
              disabled={!canWrite || serviceDegraded || q.createQualityReviewRunMutation.isPending}
              title={canWrite ? undefined : `requires ${WRITE_SCOPE}`}
              onClick={() => {
                if (!online) {
                  // Offline no-op: keep the fixture interaction responsive.
                  toast(`Semantic review queued · ${product} ${version}`);
                  return;
                }
                q.createQualityReviewRunMutation.mutate(undefined, {
                  onSuccess: (run) =>
                    toast(`Semantic review queued · ${run.product_id} ${run.version ?? version}`),
                  // Create-run failure → alert dialog with the error message.
                  onError: (e) =>
                    setAlertRequest({
                      title: "Validation error",
                      message: errMessage(e),
                      hint: "Verify product_id and version are correct, then run the review again.",
                    }),
                });
              }}
            >
              Run semantic review
            </Button>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="refresh"
              onClick={() => q.qualityReviewRunsQuery.refetch()}
            >
              Refresh runs
            </Button>
          </div>
        </div>
        {runningCount > 0 && (
          <div
            className="kvline"
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}
          >
            <RunningPulse />
            {runningCount} run{runningCount === 1 ? "" : "s"} in progress · status auto-refreshes every
            60s
          </div>
        )}
      </Card>
    </>
  );

  // ── Tab 2: Policy & Presets ────────────────────────────────────────────
  const [preset, setPreset] = useState<number>(0); // Balanced
  const presetKey = PRESETS[preset];
  // Live policy presets (e.g. "balanced_default"); when present, the Segmented index
  // selects one and drives the hook's preset id. Falls back to fixture presets offline.
  const livePresetIds = q.qualityPolicyPresetOptions;
  const livePresetId = livePresetIds[preset] ?? livePresetIds[0];
  // Presets-query state surfacing: online, reflect the live
  // policy-presets fetch. Offline the query is disabled, so the fixture-labelled
  // segmented control stands in with no banners (presetsState === "ready").
  const presetsState: "ready" | "loading" | "error" | "empty" = !online
    ? "ready"
    : q.qualityPolicyPresetsQuery.isLoading
      ? "loading"
      : q.qualityPolicyPresetsQuery.isError
        ? "error"
        : livePresetIds.length === 0
          ? "empty"
          : "ready";

  // Live policy values overlay the fixture preset row values where the endpoint models them.
  // API limitation: the policy endpoint exposes only sample_size / threshold_score / approval_mode —
  // there are no separate accuracy / completeness / citation-quality thresholds, so those three
  // rows stay fixture-driven.
  const liveSample = hasLiveRuns ? q.qualityPolicySampleSize : null;
  const liveGate =
    q.qualityPolicyApprovalMode === "auto_approve" ? "Auto-approve on pass" : "Block on fail";
  const policyVals: [string, string, string, string, string] = [
    QPOLICY[presetKey][0],
    QPOLICY[presetKey][1],
    QPOLICY[presetKey][2],
    liveSample ?? QPOLICY[presetKey][3],
    hasLiveRuns ? liveGate : QPOLICY[presetKey][4],
  ];

  // Policy mutations: success toasts fire ONLY in onSuccess. Offline the buttons
  // stay clickable and no-op with a toast (no request fires, so no
  // misleading network error surfaces for the fixture interaction).
  function savePolicy() {
    if (!online) {
      toast(`Policy saved · ${presetKey} preset`);
      return;
    }
    q.patchQualityPolicyMutation.mutate(
      {
        sample_size: Number(q.qualityPolicySampleSize),
        threshold_score: Number(q.qualityPolicyThreshold),
        approval_mode: q.qualityPolicyApprovalMode,
      },
      { onSuccess: () => toast(`Policy saved · ${presetKey} preset`) },
    );
  }

  function applyPreset() {
    if (livePresetId) q.setQualityPolicyPresetId(livePresetId);
    if (!online) {
      toast(`Applied ${presetKey} preset · future runs`);
      return;
    }
    q.applyQualityPolicyPresetMutation.mutate(undefined, {
      onSuccess: () => toast(`Applied ${presetKey} preset · future runs`),
      // Preset failure → alert dialog with the error message.
      onError: (e) =>
        setAlertRequest({
          title: "Validation error",
          message: errMessage(e),
          hint: "Verify the selected preset exists for this product, then apply it again.",
        }),
    });
  }

  const policyPanel = (
    <Card
      title="Policy & presets"
      sub="Strictness presets applied before a publish gate. Stored per product."
      right={
        <Segmented
          options={PRESETS}
          active={preset}
          onChange={(i) => {
            setPreset(i);
            const id = livePresetIds[i];
            if (id) q.setQualityPolicyPresetId(id);
          }}
          ariaLabel="Policy strictness preset"
        />
      }
    >
      <div className="muted-note" style={{ marginBottom: 10 }}>
        {PRESET_NOTE[presetKey]}
      </div>
      {presetsState === "loading" && (
        <div className="muted-note" style={{ marginBottom: 10 }}>
          Loading policy presets…
        </div>
      )}
      {presetsState === "empty" && (
        <div className="muted-note" style={{ marginBottom: 10 }}>
          No policy presets returned for this product — showing the built-in strictness presets.
        </div>
      )}
      {presetsState === "error" && (
        <div style={{ marginBottom: 12 }}>
          <ErrorState
            title="Could not load policy presets"
            text={errMessage(q.qualityPolicyPresetsQuery.error)}
            cause="policy-preset endpoint returned an error — the built-in presets are shown instead"
            actions={
              <Button
                variant="btn-ghost"
                size="sm"
                icon="refresh"
                onClick={() => q.qualityPolicyPresetsQuery.refetch()}
              >
                Retry
              </Button>
            }
          />
        </div>
      )}
      {/* Stack 1: manual parameters — sample_size /
          threshold_score numeric inputs + an approval_mode select, bound to the
          hook's policy state so a PO can fine-tune the gate independent of a
          preset. "Update Policy" PATCHes these exact three fields (the same
          mutation savePolicy() drives). */}
      <div className="eh">Manual parameters</div>
      <div className="toolbar" style={{ marginTop: 4, marginBottom: 0 }}>
        <Input
          label="sample_size"
          width={140}
          type="number"
          min={1}
          max={500}
          inputMode="numeric"
          placeholder="60"
          value={q.qualityPolicySampleSize}
          onChange={(e) => q.setQualityPolicySampleSize(e.target.value)}
        />
        <Input
          label="threshold_score"
          width={150}
          type="number"
          min={0}
          max={5}
          step={0.1}
          inputMode="decimal"
          placeholder="4.3"
          value={q.qualityPolicyThreshold}
          onChange={(e) => q.setQualityPolicyThreshold(e.target.value)}
        />
        <Select
          label="approval_mode"
          width={200}
          options={APPROVAL_MODES}
          value={q.qualityPolicyApprovalMode}
          onChange={(e) =>
            q.setQualityPolicyApprovalMode(e.target.value as QualityReviewApprovalMode)
          }
        />
        <div className="toolbar-right">
          <Button
            variant="btn-primary"
            size="sm"
            icon="check"
            disabled={!canWrite || serviceDegraded || q.patchQualityPolicyMutation.isPending}
            title={canWrite ? undefined : `requires ${WRITE_SCOPE}`}
            onClick={savePolicy}
          >
            {q.patchQualityPolicyMutation.isPending ? "Saving…" : "Update Policy"}
          </Button>
        </div>
      </div>
      <div className="muted-note" style={{ marginTop: 8, marginBottom: 14 }}>
        sample_size 1..500 · threshold_score 0..5 · applied to future runs for {product}.
      </div>
      {/* Stack 2: preset selection. The kv-list shows the
          effective preset-derived values; the Segmented control (in the card
          header) picks a preset and "Apply preset" promotes it server-side. */}
      <div className="eh">Preset definition</div>
      <div className="kv-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", marginTop: 4 }}>
        {QFIELDS.map(([name, desc], i) => (
          <div className="kv-row" key={name}>
            <div>
              <div className="kn">{name}</div>
              <div className="kd">{desc}</div>
            </div>
            <div className="kvv">{policyVals[i]}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
        <Button
          variant="btn-ghost"
          size="sm"
          icon="sliders"
          disabled={!canWrite || q.applyQualityPolicyPresetMutation.isPending}
          title={canWrite ? undefined : `requires ${WRITE_SCOPE}`}
          onClick={applyPreset}
        >
          {q.applyQualityPolicyPresetMutation.isPending ? "Applying…" : `Apply ${presetKey} preset`}
        </Button>
      </div>
      {/* Patch-policy failure → inline error alert with the
          message + the recovery hint (sample_size 1..500, threshold_score 0..5). */}
      {q.patchQualityPolicyMutation.isError && (
        <div style={{ marginTop: 12 }}>
          <ErrorState
            title="Could not save policy"
            text={errMessage(q.patchQualityPolicyMutation.error)}
            cause="invalid values — sample_size must be 1..500 and threshold_score 0..5"
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={savePolicy}>
                Retry
              </Button>
            }
          />
        </div>
      )}
    </Card>
  );

  // ── Tab 3: Review Runs ─────────────────────────────────────────────────
  // Selection is hook-owned (keeps detail/diff selectors consistent + reset on refetch).
  // Offline the hook clears its id (no live rows), so fall back to the first DISPLAY
  // row id — the drill-down is then populated by default, mirroring Health's seeded
  // selection, and row clicks still flow through the hook setter to re-render it.
  const selRun = q.selectedQualityRunId || (hasLiveRuns ? null : (runRows[0]?.[0] ?? null));
  const setSelRun = (id: string | null) => {
    q.setSelectedQualityRunId(id ?? "");
    // The detail panel's approve/reject error alerts belong to the previous run.
    q.approveQualityRunMutation.reset();
    q.rejectQualityRunMutation.reset();
  };
  // Run detail resolved from the DISPLAY source: live detail mapped to the fixture
  // shape when present, else the fixture detail for the selected (or first) run.
  const detail: RunDetail | null = hasLiveRuns
    ? q.selectedQualityRun
      ? runToDetail(q.selectedQualityRun)
      : null
    : selRun
      ? (QDETAIL[selRun] ?? QDETAIL[RUN_IDS[0]])
      : null;
  const blocked = detail ? detail.findings.length > 0 : false;
  const blockingCount = detail ? detail.findings.length : 0;
  // Id of the run actually rendered in the detail panel (live coalesces to runs[0],
  // so prefer the real selected-run id; offline uses the seeded display row).
  const shownRunId = hasLiveRuns ? (q.selectedQualityRun?.run_id ?? null) : selRun;
  const selRunning = !!selRun && runRows.some((r) => r[0] === selRun && isRunning(r[5]));
  // Selected run vanished from the live list (rejected/removed by another operator).
  const detailStale = hasLiveRuns && selRun != null && q.selectedQualityRun == null;
  // Approve/reject failures render an inline error alert in the
  // Run details panel (cleared via mutation.reset() when another run is opened).
  const approveError = q.approveQualityRunMutation.isError
    ? errMessage(q.approveQualityRunMutation.error)
    : null;
  const rejectError = q.rejectQualityRunMutation.isError
    ? errMessage(q.rejectQualityRunMutation.error)
    : null;

  // ── Batch selection (hook-owned id array; works offline on local state) ──
  const batchIds = q.selectedQualityRunIds;
  const batchCount = batchIds.length;
  const toggleBatch = (id: string) => q.toggleQualityRunSelection(id);
  const clearBatch = () => q.setSelectedQualityRunIds([]);

  function rejectRun(id: string) {
    setReasonRequest({
      title: "Reject review run",
      confirmLabel: "Reject run",
      summary: (
        <>
          Blocks publication of <b>{id}</b>. Rejection is permanent — there is no undo, only a new
          review run. The reason below is recorded in the approval trail.
        </>
      ),
      onSubmit: (reason) => {
        if (!online) {
          // Offline no-op: fixture interaction stays responsive.
          toast(`Run ${id} rejected · reason recorded`);
          return;
        }
        q.rejectQualityRunMutation.mutate(
          { runId: id, reason },
          // Success toast fires only once the mutation settles; failures surface
          // via the hook's error toast + the inline alert in Run details.
          { onSuccess: () => toast(`Run ${id} rejected · reason recorded`) },
        );
      },
    });
  }

  function batchReject() {
    if (!batchCount) return;
    setReasonRequest({
      title: `Reject ${batchCount} review run${batchCount === 1 ? "" : "s"}`,
      confirmLabel: `Reject ${batchCount} run${batchCount === 1 ? "" : "s"}`,
      summary: (
        <>
          Blocks publication of <b>{batchCount}</b> selected run{batchCount === 1 ? "" : "s"}. The
          reason below is recorded on each run&apos;s approval trail. Rejection is permanent.
        </>
      ),
      onSubmit: (reason) => {
        if (!online) {
          clearBatch();
          toast(`${batchCount} run${batchCount === 1 ? "" : "s"} rejected · reason recorded`);
          return;
        }
        setBatchIssue(null);
        // Selection is cleared by the hook's own onSuccess; never optimistically.
        q.batchRejectQualityRunsMutation.mutate(
          { runIds: batchIds, reason },
          {
            onSuccess: (res) => {
              if (res.failed_count > 0) {
                setBatchIssue({
                  title: `Batch reject: ${res.applied_count} applied · ${res.failed_count} failed`,
                  lines: batchFailureLines(res),
                  hint: "runs already decided, missing, or in another product — retry or select different runs",
                });
              }
              toast(
                res.failed_count > 0
                  ? `Batch reject: ${res.applied_count} applied · ${res.failed_count} failed`
                  : `${res.applied_count} run${res.applied_count === 1 ? "" : "s"} rejected · reason recorded`,
              );
            },
            onError: (e) =>
              setBatchIssue({
                title: "Batch reject failed",
                lines: [errMessage(e)],
                hint: "service unavailable or the request was rejected — retry once it recovers",
              }),
          },
        );
      },
    });
  }

  function batchApprove() {
    if (!batchCount) return;
    const withBlocking = batchIds.filter((id) => (QDETAIL[id]?.findings.length ?? 0) > 0 || liveRuns.find((r) => r.run_id === id)?.blocking_error_count);
    confirm({
      title: `Approve ${batchCount} review run${batchCount === 1 ? "" : "s"}`,
      tone: withBlocking.length ? "amber" : undefined,
      icon: "upload",
      summary: (
        <>
          Publishes <b>{batchCount}</b> selected run{batchCount === 1 ? "" : "s"} to production
          retrieval and records an approval entry for each.
          {withBlocking.length
            ? ` ${withBlocking.length} of them still have blocking findings — proceed anyway?`
            : ""}
        </>
      ),
      confirmLabel: withBlocking.length ? "Approve anyway" : `Approve ${batchCount}`,
      onConfirm: () => {
        if (!online) {
          clearBatch();
          toast(`${batchCount} run${batchCount === 1 ? "" : "s"} approved · published`);
          return;
        }
        setBatchIssue(null);
        // Selection is cleared by the hook's own onSuccess; never optimistically.
        q.batchApproveQualityRunsMutation.mutate(batchIds, {
          onSuccess: (res) => {
            if (res.failed_count > 0) {
              setBatchIssue({
                title: `Batch approve: ${res.applied_count} applied · ${res.failed_count} failed`,
                lines: batchFailureLines(res),
                hint: "runs already decided, missing, or in another product — retry or select different runs",
              });
            }
            toast(
              res.failed_count > 0
                ? `Batch approve: ${res.applied_count} applied · ${res.failed_count} failed`
                : `${res.applied_count} run${res.applied_count === 1 ? "" : "s"} approved · published`,
            );
          },
          onError: (e) =>
            setBatchIssue({
              title: "Batch approve failed",
              lines: [errMessage(e)],
              hint: "service unavailable or the request was rejected — retry once it recovers",
            }),
        });
      },
    });
  }

  function approveRun(id: string, count: number) {
    const anyway = count > 0;
    confirm({
      title: anyway ? "Approve run despite blocking findings" : "Approve & publish run",
      tone: "amber",
      icon: "upload",
      summary: (
        <>
          Publishes the reviewed content for <b>{id}</b> to production retrieval and records an
          approval entry in the trail.
          {anyway
            ? ` This run has ${count} blocking finding${count === 1 ? "" : "s"}. Proceed anyway?`
            : ""}
        </>
      ),
      confirmLabel: anyway ? `Approve anyway (${count})` : "Approve & publish",
      onConfirm: () => {
        if (!online) {
          toast(`Run ${id} approved · published`);
          return;
        }
        // Success toast fires only once the mutation settles; failures surface
        // via the hook's error toast + the inline alert in Run details.
        q.approveQualityRunMutation.mutate(id, {
          onSuccess: () => toast(`Run ${id} approved · published`),
        });
      },
    });
  }

  const batchBar = (
    <div className="toolbar" style={{ marginBottom: 12, alignItems: "center" }}>
      <span className="kvline">
        {batchCount > 0 ? (
          <>
            <b>{batchCount}</b> selected
          </>
        ) : (
          "Select runs to approve or reject in bulk"
        )}
      </span>
      <div className="toolbar-right">
        <Button
          variant="btn-primary"
          size="sm"
          icon="upload"
          disabled={!canWrite || serviceDegraded || batchCount === 0 || q.batchApproveQualityRunsMutation.isPending}
          title={canWrite ? undefined : `requires ${WRITE_SCOPE}`}
          onClick={batchApprove}
        >
          Batch approve{batchCount ? ` (${batchCount})` : ""}
        </Button>
        <Button
          variant="btn-danger"
          size="sm"
          icon="x"
          disabled={!canWrite || serviceDegraded || batchCount === 0 || q.batchRejectQualityRunsMutation.isPending}
          title={canWrite ? undefined : `requires ${WRITE_SCOPE}`}
          onClick={batchReject}
        >
          Batch reject{batchCount ? ` (${batchCount})` : ""}
        </Button>
        <Button
          variant="btn-ghost"
          size="sm"
          disabled={batchCount === 0}
          onClick={clearBatch}
        >
          Clear selection
        </Button>
      </div>
    </div>
  );

  function runRowEl([id, p, v, res, sc, st, when, bl, thr]: RunRow) {
    return (
      <tr
        key={id}
        className={cn("data", "qrun", id === selRun && "sel")}
        aria-selected={id === selRun}
        onClick={() => setSelRun(id)}
      >
        <td onClick={(e) => e.stopPropagation()} style={{ width: 38 }}>
          <input
            type="checkbox"
            checked={batchIds.includes(id)}
            onChange={() => toggleBatch(id)}
            aria-label={`Select run ${id} for batch action`}
            style={{ accentColor: "var(--accent-line)" }}
          />
        </td>
        <td>
          {isRunning(st) ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <RunningPulse />
              <Pill variant="info">running</Pill>
            </span>
          ) : (
            <Pill variant={res}>{res === "ok" ? "pass" : res === "warn" ? "warn" : res === "crit" ? "fail" : "—"}</Pill>
          )}
        </td>
        <td>
          <span className="repo-id">{id}</span>
        </td>
        <td>
          <span className="mono" style={{ fontSize: 12, color: "var(--fg-muted)" }}>
            {p}
          </span>
        </td>
        <td>
          <Tag>{v}</Tag>
        </td>
        <td className="num">{sc}</td>
        <td className="num">{thr}</td>
        <td className="num">
          {bl > 0 ? <span style={{ color: "var(--crit)", fontWeight: 600 }}>{bl}</span> : "0"}
        </td>
        <td>
          <Pill variant={RUN_STATUS[st][0]}>{RUN_STATUS[st][1]}</Pill>
        </td>
        <td className="num">{when}</td>
      </tr>
    );
  }

  const COLS = 10;
  const headRow = runRows.slice(0, RUN_PAGE);
  const tailRow = runRows.slice(RUN_PAGE);

  const runsTable = (
    <div id="quality-runs-panel" className="tablecard">
      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 38 }} aria-label="Select" />
            <th style={{ width: 84 }}>Result</th>
            <th>Review run</th>
            <th style={{ width: 118 }}>Product</th>
            <th style={{ width: 84 }}>Version</th>
            <th className="num" style={{ width: 70 }}>
              Score
            </th>
            <th className="num" style={{ width: 84 }}>
              Threshold
            </th>
            <th className="num" style={{ width: 84 }}>
              Blocking
            </th>
            <th style={{ width: 140 }}>Status</th>
            <th className="num" style={{ width: 96 }}>
              When
            </th>
          </tr>
        </thead>
        <tbody>
          {headRow.map(runRowEl)}
          {tailRow.length > 0 && (
            <ShowMoreRow extra={tailRow.map(runRowEl)} count={tailRow.length} colSpan={COLS} />
          )}
        </tbody>
      </table>
    </div>
  );

  const runDetailCard = (
    <div id="qr-detail">
      <Card
        title={
          shownRunId && detail && !detailStale ? (
            <>
              Run details · <span className="repo-id">{shownRunId}</span>
            </>
          ) : (
            "Run details"
          )
        }
        sub="Select a review run above to inspect blocking findings, reviewer votes, and the approval trail."
      >
        {!detail ? (
          <EmptyState
            title="No run selected"
            text="Pick a review run to see why it passed or was blocked, then approve or reject with an audit trail."
          />
        ) : detailStale ? (
          <ErrorState
            title="Run no longer available"
            text="This run has been removed or rejected server-side while open. Select another run before approving or rejecting."
            cause="run deleted or status changed by another operator"
            actions={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => setSelRun(null)}>
                Clear selection
              </Button>
            }
          />
        ) : (
          <div className="qr-grid">
            <div>
              <div className="eh">
                Scoring
                {selRunning && (
                  <span style={{ marginLeft: 8, display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <RunningPulse />
                    <span style={{ color: "var(--info)" }}>analysis in progress</span>
                  </span>
                )}
              </div>
              <div className="kvline">
                quality score=<b>{detail.score}</b> · threshold=<b>{detail.thr}</b>
              </div>
              <div className="kvline">
                sampled=<b>{detail.sampled}</b> · evaluated=<b>{detail.evaluated}</b>
              </div>
              <div className="kvline">
                reviewer votes=<b>{detail.votes}</b>
              </div>
              <div className="eh" style={{ marginTop: 13 }}>
                Approval trail
              </div>
              {detail.trail.map(([action, who, when, why], i) => (
                <div className="kvline" key={i}>
                  {action} · <b>{who}</b> · {when} — {why}
                </div>
              ))}
              {detail.guided && (
                <GuidedFixPanel guided={detail.guided} onOpenOrigin={() => navigate("analytics")} />
              )}
            </div>
            <div>
              <div className="eh">Blocking findings ({detail.findings.length})</div>
              <FindingList findings={detail.findings} />
              <div className="qr-acts">
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="git"
                  onClick={() => navigate("ingestion")}
                >
                  View ingestion job
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="layers"
                  disabled={!selRun}
                  title="Set this run as the diff candidate in Run Diff"
                  onClick={() => {
                    if (!selRun) return;
                    q.setQualityDiffCandidateRunId(selRun);
                    toast(`Set ${selRun} as diff candidate`);
                  }}
                >
                  Use as candidate
                </Button>
                <Button
                  variant="btn-ghost"
                  size="sm"
                  disabled={
                    !canWrite || serviceDegraded || selRunning || q.rejectQualityRunMutation.isPending
                  }
                  title={
                    canWrite
                      ? selRunning
                        ? "Run is still computing"
                        : undefined
                      : `requires ${WRITE_SCOPE}`
                  }
                  onClick={() => selRun && rejectRun(selRun)}
                >
                  Reject
                </Button>
                <Button
                  variant="btn-primary"
                  size="sm"
                  disabled={
                    !canWrite ||
                    serviceDegraded ||
                    selRunning ||
                    q.approveQualityRunMutation.isPending
                  }
                  title={
                    canWrite
                      ? selRunning
                        ? "Run is still computing"
                        : undefined
                      : `requires ${WRITE_SCOPE}`
                  }
                  onClick={() => selRun && approveRun(selRun, blockingCount)}
                >
                  {blocked ? `Approve anyway (${blockingCount})` : "Approve & publish"}
                </Button>
              </div>
              {approveError && (
                <div style={{ marginTop: 12 }}>
                  <ErrorState
                    title="Approve failed"
                    text={approveError}
                    cause="run not in awaiting_approval state — check the approval trail"
                  />
                </div>
              )}
              {rejectError && (
                <div style={{ marginTop: 12 }}>
                  <ErrorState
                    title="Reject failed"
                    text={rejectError}
                    cause="run already rejected, or the service rejected the request"
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );

  let runsPanel: ReactNode;
  if (runsLoading) {
    runsPanel = (
      <Card title="Review runs" sub="Loading the latest semantic review runs…">
        <Skeleton rows={4} />
      </Card>
    );
  } else if (runsErrored) {
    runsPanel = (
      <ErrorState
        title="Could not load quality review runs"
        text="The run list did not load. Check Logs & Traces for backend errors, then retry."
        cause="semantic review service or gateway returned a 5xx"
        actions={
          <>
            <Button
              variant="btn-primary"
              size="sm"
              icon="refresh"
              onClick={() => q.qualityReviewRunsQuery.refetch()}
            >
              Retry
            </Button>
            <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("logs")}>
              Open Logs & Traces
            </Button>
          </>
        }
      />
    );
  } else if (runRows.length === 0) {
    runsPanel = (
      <EmptyState
        title="No quality review runs"
        text="Start a semantic review run to generate a review package for release gating."
        action={
          <Button variant="btn-primary" size="sm" icon="play" onClick={() => setActiveTab(0)}>
            Go to Run &amp; Queue
          </Button>
        }
      />
    );
  } else {
    runsPanel = (
      <>
        {/* Batch approve/reject failures → inline error alert
            with per-run failure reasons (also covers partial 200 responses). */}
        {batchIssue && (
          <div style={{ marginBottom: 12 }}>
            <ErrorState
              title={batchIssue.title}
              text={batchIssue.lines.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
              cause={batchIssue.hint}
              actions={
                <Button variant="btn-ghost" size="sm" onClick={() => setBatchIssue(null)}>
                  Dismiss
                </Button>
              }
            />
          </div>
        )}
        {batchBar}
        {runsTable}
        {runDetailCard}
      </>
    );
  }

  // ── Tab 4: Run Diff ────────────────────────────────────────────────────
  // Hook owns base/candidate ids and auto-runs the diff query when both differ;
  // local `diffOn` keeps the "pick base & candidate" empty-state until requested.
  // Fixture run ids stand in only while OFFLINE — online the live list is
  // authoritative (empty live list → empty selectors, empty state).
  const [diffOn, setDiffOn] = useState(false);
  const runIdOptions = q.qualityRunIdOptions.length ? q.qualityRunIdOptions : online ? [] : RUN_IDS;
  const base = q.qualityDiffBaselineRunId || runIdOptions[0] || "";
  const candidate = q.qualityDiffCandidateRunId || runIdOptions[runIdOptions.length - 1] || "";

  // Per-side score/blocking: live runs when present, else fixture details (keyed by the
  // current base/candidate selection). DIFF_FALLBACK names the offline detail used when a
  // selected id has no fixture row, so each side always resolves to a populated detail.
  const liveBase = liveRuns.find((r) => r.run_id === base);
  const liveCand = liveRuns.find((r) => r.run_id === candidate);
  const baseDetail = QDETAIL[base] ?? DIFF_FALLBACK_BASE;
  const candDetail = QDETAIL[candidate] ?? DIFF_FALLBACK_CANDIDATE;
  const b = liveBase
    ? { score: fmtScore(liveBase.summary.overall_score), findings: liveBase.blocking_findings }
    : { score: baseDetail.score, findings: baseDetail.findings };
  const c = liveCand
    ? { score: fmtScore(liveCand.summary.overall_score), findings: liveCand.blocking_findings }
    : { score: candDetail.score, findings: candDetail.findings };

  // Deltas: from the live diff response when available, else computed from the two sides.
  const liveDiff = q.qualityRunDiffQuery.data;
  const dScore = (liveDiff ? liveDiff.overall_score_delta : Number(c.score) - Number(b.score)).toFixed(2);
  const dFind = liveDiff ? liveDiff.blocking_error_delta : c.findings.length - b.findings.length;
  const scoreUp = Number(dScore) >= 0;
  const improvement = scoreUp && dFind <= 0;

  // Live diff failure → the WARNING alert with retry;
  // never silently fall back to client-computed deltas. Offline the query is
  // disabled (isError stays false), so the fixture diff keeps rendering.
  const diffErrored = online && q.qualityRunDiffQuery.isError;

  // Gate the populated diff on whether content is RESOLVABLE in EITHER source — never on the
  // local button alone. It renders when the live diff query returned data, OR the operator
  // pressed Compute on a valid pair, OR (offline) both sides resolve to a fixture detail for
  // two distinct runs. So once base & candidate are chosen, the fixture diff renders offline;
  // the "pick base & candidate" prompt only stands in before a real two-run selection exists.
  const diffPairOk = base !== "" && candidate !== "" && base !== candidate;
  const fixtureDiffReady = !online && diffPairOk;
  const diffReady = liveDiff != null || (diffOn && diffPairOk) || fixtureDiffReady;

  const diffPanel = (
    <Card
      title="Run diff"
      sub="Compare two review runs to see which documents regressed or improved."
    >
      <div className="toolbar">
        <Select
          label="Base"
          width={200}
          options={runIdOptions}
          value={base}
          onChange={(e) => {
            q.setQualityDiffBaselineRunId(e.target.value);
            setDiffOn(false);
          }}
        />
        <Select
          label="Candidate"
          width={200}
          options={runIdOptions}
          value={candidate}
          onChange={(e) => {
            q.setQualityDiffCandidateRunId(e.target.value);
            setDiffOn(false);
          }}
        />
        <div className="toolbar-right">
          <Button variant="btn-primary" size="sm" onClick={() => setDiffOn(true)}>
            Compute diff
          </Button>
        </div>
      </div>
      <div id="qr-diff">
        {diffErrored ? (
          <DiffWarningAlert
            message={errMessage(q.qualityRunDiffQuery.error)}
            onRetry={() => q.qualityRunDiffQuery.refetch()}
          />
        ) : !diffReady ? (
          <EmptyState
            title="Pick base & candidate"
            text="Choose two runs and compute the diff to inspect score and blocking-finding deltas. Tip: open a run and use ‘Use as candidate’ to seed this view."
          />
        ) : (
          <>
            <div className="qr-grid">
              <div>
                <div className="eh">Base · {base}</div>
                <div className="kvline">
                  score=<b>{b.score}</b> · blocking=<b>{b.findings.length}</b>
                </div>
              </div>
              <div>
                <div className="eh">Candidate · {candidate}</div>
                <div className="kvline">
                  score=<b>{c.score}</b> · blocking=<b>{c.findings.length}</b>
                </div>
              </div>
            </div>
            <div className="qr-delta">
              <Pill variant={scoreUp ? "ok" : "crit"}>
                {(scoreUp ? "+" : "") + dScore} score
              </Pill>
              <Pill variant={dFind > 0 ? "crit" : "ok"}>
                {(dFind > 0 ? "+" : "") + dFind} blocking
              </Pill>
              <span className="muted-note">
                {improvement
                  ? "Candidate is an improvement — safe to promote."
                  : "Candidate regressed — do not promote."}
              </span>
            </div>
          </>
        )}
      </div>
    </Card>
  );

  return (
    <>
      <PageHead
        title="Quality Reviews"
        sub="Semantic quality review before publish — launch runs, tune policy strictness, approve/reject, and compare runs side by side."
        onHelp={goHelp}
        actions={
          <>
            <ScopeChip label="scope" value="write:settings" dot />
            {runningCount > 0 && (
              <span className="muted-note" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <RunningPulse />
                {runningCount} running
              </span>
            )}
            {serviceDegraded && <StaleBadge>service down</StaleBadge>}
          </>
        }
      />

      {serviceDegraded && (
        <Banner
          variant="warn"
          icon="alert"
          title="Quality review service unavailable"
          text="Existing approval data is shown, but new runs and decisions cannot be recorded until the service recovers. All mutating actions are disabled."
        />
      )}

      {!canWrite && (
        <PermissionDenied
          scope={WRITE_SCOPE}
          extra="You can read runs, scores, and approval trails, but launching runs, editing policy, and approving or rejecting are disabled until an administrator grants the scope."
        />
      )}

      <div className="tabwrap">
        <Tabs
          tabs={["Run & Queue", "Policy & Presets", "Review Runs", "Run Diff"]}
          active={activeTab}
          onChange={setActiveTab}
        />
        <div className="tabpanels">
          {[runQueuePanel, policyPanel, runsPanel, diffPanel].map((panel, i) => (
            <div key={i} className="tabpanel" role="tabpanel" hidden={i !== activeTab}>
              {panel}
            </div>
          ))}
        </div>
      </div>

      {reasonRequest && (
        <ReasonModal request={reasonRequest} onClose={() => setReasonRequest(null)} />
      )}
      {alertRequest && <AlertModal request={alertRequest} onClose={() => setAlertRequest(null)} />}
    </>
  );
}
