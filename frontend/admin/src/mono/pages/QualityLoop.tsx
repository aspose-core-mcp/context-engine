"use client";

import { type CSSProperties, useEffect, useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Button } from "../components/Button";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { Icon } from "../lib/icons";
import { Pill } from "../components/Pill";

/* ─────────────────────────────────────────────────────────────────────────────
   ADCS — Quality Loop Calibration Panel (read-only standalone page, route
   /quality-loop). Surfaces the AdaptiveAgent's self-tuning calibration state:
   current tunables + headroom, and the recent adaptation history.

   DATA WIRING ─────────────────────────────────────────────────────────────────
   No public calibration endpoint exists yet; the page renders an in-file fixture.
   Calibration state is served by the ADMIN-authed endpoint
   GET /v1/admin/quality-loop/calibration?limit=50 (service anchor:
   src/adcs/api/admin_quality_loop.py). That route requires require_admin_principal
   and is therefore NOT a public surface — there is no `fetchPublic*` calibration
   function in src/lib/admin-api.ts. This standalone public page also runs OUTSIDE
   the admin shell, so it has no useAdminData/apiKey context to authenticate that
   admin call.

   => The in-file FIXTURE is the offline dataset. It is modelled through the
      CalibrationDrift contract (the admin endpoint's response shape) and served
      via a TanStack useQuery whose queryFn resolves the fixture, so the data-flow,
      the loading → success transition, Refresh/refetch, and the empty/error
      states are all real and reachable. Once a public endpoint (+ a
      `fetchPublicQualityLoopCalibration` in admin-api.ts) exists, swapping the
      queryFn body for that call (and flipping FIXTURE_MODE off) wires live data
      with zero structural change.
   ───────────────────────────────────────────────────────────────────────────── */

/* ── Live contract (admin calibration response shape) ───────────────────────── */

type CalibrationState = {
  judge_low_threshold: number;
  diagnosis_min_low_ratio: number;
  proposal_high_confidence_floor: number;
  guard_auto_approve_blast_cap: number;
  cycle_count: number;
  cycles_since_last_rejection: number;
};

type CalibrationBounds = {
  judge_low_threshold_min: number;
  judge_low_threshold_max: number;
  diagnosis_min_low_ratio_min: number;
  diagnosis_min_low_ratio_max: number;
  proposal_high_confidence_floor_min: number;
  proposal_high_confidence_floor_max: number;
  guard_auto_approve_blast_cap_min: number;
  guard_auto_approve_blast_cap_max: number;
};

type AdaptationEventRecord = {
  event_id: string;
  cycle_id: string;
  emitted_at: string;
  /** Humanized form for the table (e.g. "2 min ago"); falls back to emitted_at. */
  emitted_label?: string;
  kind: "increase" | "decrease" | string;
  parameter_name: string;
  previous_value: number;
  new_value: number;
  delta: number;
  rationale: string;
};

type CalibrationDrift = {
  state: CalibrationState;
  bounds: CalibrationBounds;
  recent_adaptations: AdaptationEventRecord[];
  recent_adaptation_count: number;
};

/* ── Offline fixture ────────────────────────────────────────────────────────── */

const FIXTURE_MODE = true;

const FIXTURE: CalibrationDrift = {
  state: {
    judge_low_threshold: 0.723,
    diagnosis_min_low_ratio: 0.405,
    proposal_high_confidence_floor: 0.892,
    guard_auto_approve_blast_cap: 150,
    cycle_count: 1284,
    cycles_since_last_rejection: 847,
  },
  bounds: {
    judge_low_threshold_min: 0.5,
    judge_low_threshold_max: 0.85,
    diagnosis_min_low_ratio_min: 0.2,
    diagnosis_min_low_ratio_max: 0.7,
    proposal_high_confidence_floor_min: 0.7,
    proposal_high_confidence_floor_max: 0.95,
    guard_auto_approve_blast_cap_min: 25,
    guard_auto_approve_blast_cap_max: 500,
  },
  recent_adaptations: [
    {
      event_id: "adapt-1284",
      cycle_id: "cyc-1284",
      emitted_at: "2026-06-10T11:58:00Z",
      emitted_label: "2 min ago",
      kind: "decrease",
      parameter_name: "judge_low_threshold",
      previous_value: 0.741,
      new_value: 0.723,
      delta: -0.018,
      rationale: "Confidence boosting after a run of false positives in the judge phase.",
    },
    {
      event_id: "adapt-1281",
      cycle_id: "cyc-1281",
      emitted_at: "2026-06-10T11:00:00Z",
      emitted_label: "1 hour ago",
      kind: "increase",
      parameter_name: "diagnosis_min_low_ratio",
      previous_value: 0.38,
      new_value: 0.405,
      delta: 0.025,
      rationale: "Poor recall observed in diagnosis phase; widened low-confidence sampling.",
    },
    {
      event_id: "adapt-1275",
      cycle_id: "cyc-1275",
      emitted_at: "2026-06-10T09:00:00Z",
      emitted_label: "3 hours ago",
      kind: "increase",
      parameter_name: "proposal_high_confidence_floor",
      previous_value: 0.88,
      new_value: 0.892,
      delta: 0.012,
      rationale: "Tightened proposal floor after two low-quality auto-proposals slipped through.",
    },
    {
      event_id: "adapt-1240",
      cycle_id: "cyc-1240",
      emitted_at: "2026-06-09T12:00:00Z",
      emitted_label: "yesterday",
      kind: "decrease",
      parameter_name: "guard_auto_approve_blast_cap",
      previous_value: 180,
      new_value: 150,
      delta: -30,
      rationale: "Reduced blast cap following a near-miss on a large auto-approved batch.",
    },
  ],
  recent_adaptation_count: 4,
};

/**
 * queryFn for the calibration query. While FIXTURE_MODE is on (no public endpoint
 * exists) this resolves the in-file fixture, giving the page a real
 * loading → success cycle plus working Refresh/retry. When a public
 * `fetchPublicQualityLoopCalibration()` is added to admin-api.ts, replace this
 * body with `return fetchPublicQualityLoopCalibration({ limit: 50 });` and set
 * FIXTURE_MODE = false — the rest of the page is already bound to the contract.
 */
async function loadCalibrationDrift(): Promise<CalibrationDrift> {
  if (FIXTURE_MODE) {
    return FIXTURE;
  }
  // Unreachable while FIXTURE_MODE is true — documents the live call site only.
  throw new Error("No public quality-loop calibration endpoint is wired yet.");
}

/* ── Derived view model ─────────────────────────────────────────────────────── */

const THEME_KEY = "adcs_theme";

interface TunableView {
  key: string;
  label: string;
  value: number;
  min: number;
  max: number;
  desc: string;
  fmt: (n: number) => string;
}

/** Build the four tunable cards from the live/contract shape (in display order). */
function buildTunables(d: CalibrationDrift): TunableView[] {
  const f3 = (n: number) => n.toFixed(3);
  const int = (n: number) => Math.round(n).toString();
  return [
    {
      key: "judge_low_threshold",
      label: "Judge low threshold",
      value: d.state.judge_low_threshold,
      min: d.bounds.judge_low_threshold_min,
      max: d.bounds.judge_low_threshold_max,
      desc: "Quality gate for diagnosis output",
      fmt: f3,
    },
    {
      key: "diagnosis_min_low_ratio",
      label: "Diagnosis min-low ratio",
      value: d.state.diagnosis_min_low_ratio,
      min: d.bounds.diagnosis_min_low_ratio_min,
      max: d.bounds.diagnosis_min_low_ratio_max,
      desc: "Min ratio of low-confidence cases in diagnosis",
      fmt: f3,
    },
    {
      key: "proposal_high_confidence_floor",
      label: "Proposal high-confidence floor",
      value: d.state.proposal_high_confidence_floor,
      min: d.bounds.proposal_high_confidence_floor_min,
      max: d.bounds.proposal_high_confidence_floor_max,
      desc: "Confidence floor for proposal generation",
      fmt: f3,
    },
    {
      key: "guard_auto_approve_blast_cap",
      label: "Guard auto-approve blast cap",
      value: d.state.guard_auto_approve_blast_cap,
      min: d.bounds.guard_auto_approve_blast_cap_min,
      max: d.bounds.guard_auto_approve_blast_cap_max,
      desc: "Max batch size for auto-approved proposals",
      fmt: int,
    },
  ];
}

/** Headroom % within hard bounds + near-edge flag. */
function headroom(t: TunableView): { pct: number; near: boolean } {
  const span = t.max - t.min;
  const raw = span > 0 ? ((t.value - t.min) / span) * 100 : 0;
  const pct = Math.min(100, Math.max(0, raw));
  const near = pct > 88 || pct < 12;
  return { pct, near };
}

/** A tunable whose configured bounds are inverted (min ≥ max) is a Coordinator misconfig. */
function boundsInvalid(t: TunableView): boolean {
  return t.min >= t.max;
}

/** Compact integer grouping ("1 284") for KPI typography. */
function groupThousands(n: number): string {
  return n.toLocaleString("en-US").replace(/,/g, " ");
}

/** Visually-hidden style for live-region announcements (kit has no .sr-only class). */
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

function HeadroomBar({ tunable, invalid }: { tunable: TunableView; invalid: boolean }) {
  if (invalid) {
    // Inverted bounds — the headroom math is meaningless; surface the misconfig.
    return (
      <div className="ql-bounds mono" style={{ marginTop: 11 }}>
        <span>{tunable.fmt(tunable.min)}</span>
        <span className="near">invalid bounds</span>
        <span>{tunable.fmt(tunable.max)}</span>
      </div>
    );
  }
  const { pct, near } = headroom(tunable);
  const left = `${pct.toFixed(0)}%`;
  return (
    <>
      <div className="ql-bar">
        <span className={near ? "ql-fill near" : "ql-fill"} style={{ width: left }} />
        <span className="ql-knob" style={{ left }} />
      </div>
      <div className="ql-bounds mono">
        <span>{tunable.fmt(tunable.min)}</span>
        <span className={near ? "near" : undefined}>{near ? "low headroom" : "within range"}</span>
        <span>{tunable.fmt(tunable.max)}</span>
      </div>
    </>
  );
}

export default function QualityLoopPage() {
  // Hydration-safe theme: start at the light default, then sync from localStorage
  // on mount so server/client first render agree.
  const [dark, setDark] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(THEME_KEY) === "dark") setDark(true);
    } catch {
      /* localStorage unavailable — keep light default */
    }
  }, []);

  // Per-route document title (the app/ route only re-exports this component and
  // sets no metadata; set the a11y title without touching the route).
  useEffect(() => {
    const prev = document.title;
    document.title = "Quality Loop Calibration — ADCS Admin";
    return () => {
      document.title = prev;
    };
  }, []);

  function toggleTheme() {
    setDark((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore persistence failures */
      }
      return next;
    });
  }

  // Real TanStack query over the calibration contract (fixture-backed offline; see
  // the DATA WIRING header). Loading / error / empty below are genuine query states.
  const calibration = useQuery({
    queryKey: ["public", "quality-loop", "calibration", { limit: 50 }],
    queryFn: loadCalibrationDrift,
    staleTime: 30_000,
  });

  const data = calibration.data;
  const tunables = useMemo(() => (data ? buildTunables(data) : []), [data]);
  const invalidBoundsCount = useMemo(() => tunables.filter(boundsInvalid).length, [tunables]);

  const events = data?.recent_adaptations ?? [];
  const loading = calibration.isLoading;
  const errored = calibration.isError && !data;
  const refreshing = calibration.isFetching && !calibration.isLoading;

  // Distinguish auth/scope failures from service errors for the recovery copy
  // (401/403/503/network). Status comes from AdminApiError when a real endpoint
  // is wired.
  const errStatusRaw = (calibration.error as unknown as { status?: unknown } | null)?.status;
  const errStatus = typeof errStatusRaw === "number" ? errStatusRaw : null;
  const errMessage = calibration.error instanceof Error ? calibration.error.message : String(calibration.error ?? "");
  const errCause =
    errStatus === 401
      ? "your admin session has expired — sign in again from the status page"
      : errStatus === 403
        ? "your key lacks the admin scope required to read calibration state"
        : errStatus === 503
          ? "the backend could not read the calibration artefacts on disk"
          : "the calibration endpoint is unreachable";

  return (
    <div className={dark ? "adcs t-mono theme-dark" : "adcs t-mono"}>
      <div className="ql-wrap">
        <header className="ql-hero">
          <a className="ql-back" href="/#snapshots">
            <Icon name="arrow" />
            <span>Back to console</span>
          </a>
          <button
            type="button"
            className="icon-btn"
            onClick={toggleTheme}
            aria-pressed={dark}
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
          >
            <Icon name={dark ? "moon" : "sun"} />
          </button>
          <div className="ql-hero-main">
            <h1>Quality Loop Calibration</h1>
            <p>
              Read-only view of the AdaptiveAgent&apos;s self-tuning state. Inspect tunables and
              their headroom, scan recent adaptations, then decide whether to accept the drift or
              roll back via Snapshots.
            </p>
          </div>
        </header>

        <main>
          {/* Live-region: announce load / refresh / empty / error state changes for SR users.
              Visually hidden via inline a11y positioning (no .sr-only class in the kit). */}
          <p role="status" aria-live="polite" style={SR_ONLY}>
            {loading
              ? "Loading calibration state."
              : errored
                ? `Failed to load calibration drift: ${errMessage}`
                : `Calibration state loaded · ${events.length} recent adaptation event${events.length === 1 ? "" : "s"}.`}
          </p>

          {loading ? (
            /* ── Loading ─────────────────────────────────────────────────────── */
            <div className="tablecard" style={{ padding: 20 }}>
              <Skeleton rows={5} />
            </div>
          ) : errored ? (
            /* ── Error (role=alert via ErrorState) with retry ────────────────── */
            <ErrorState
              title="Failed to load calibration drift"
              text={errMessage}
              cause={errCause}
              actions={
                <Button size="sm" icon="refresh" onClick={() => void calibration.refetch()}>
                  Retry
                </Button>
              }
            />
          ) : (
            <>
              <div className="ql-kpis">
                <div className="ql-kpi">
                  <div className="k-label">Cycles run</div>
                  <div className="k-value">{groupThousands(data?.state.cycle_count ?? 0)}</div>
                  <div className="k-foot">since loop start</div>
                </div>
                <div className="ql-kpi">
                  <div className="k-label">Clean streak</div>
                  <div className="k-value">
                    {groupThousands(data?.state.cycles_since_last_rejection ?? 0)}
                  </div>
                  <div className="k-foot">cycles since last rollback</div>
                </div>
                <div className="ql-kpi">
                  <div className="k-label">Last adaptation</div>
                  <div className="k-value" style={{ fontSize: "18px" }}>
                    {events[0]?.emitted_label ?? events[0]?.emitted_at ?? "no events yet"}
                  </div>
                  <div className="k-foot">{events.length ? "loop is active" : "loop idle"}</div>
                </div>
                <div className="ql-kpi">
                  <div className="k-label">Bounds health</div>
                  <div className="k-value" style={{ fontSize: "18px" }}>
                    {invalidBoundsCount === 0 ? (
                      <Pill variant="ok">all valid</Pill>
                    ) : (
                      <Pill variant="crit">
                        {invalidBoundsCount} invalid
                      </Pill>
                    )}
                  </div>
                  <div className="k-foot">
                    {invalidBoundsCount === 0 ? "no misconfiguration" : "check Coordinator config"}
                  </div>
                </div>
              </div>

              <div className="ql-sec-label">
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                  Current calibration · tunable parameters
                  <Button
                    size="sm"
                    icon="refresh"
                    onClick={() => void calibration.refetch()}
                    disabled={refreshing}
                    aria-label="Refresh calibration state"
                  >
                    {refreshing ? "Refreshing" : "Refresh"}
                  </Button>
                </span>
              </div>
              <div className="ql-cards">
                {tunables.map((t) => {
                  const invalid = boundsInvalid(t);
                  return (
                    <div
                      className="ql-card"
                      key={t.key}
                      aria-label={t.label}
                      style={
                        invalid
                          ? { borderColor: "var(--crit)", background: "var(--crit-bg)" }
                          : undefined
                      }
                      title={invalid ? "Invalid bounds configuration — contact the backend team" : undefined}
                    >
                      <div className="ql-key mono">{t.key}</div>
                      <div className="ql-val">{t.fmt(t.value)}</div>
                      <div className="ql-desc">{t.desc}</div>
                      <HeadroomBar tunable={t} invalid={invalid} />
                    </div>
                  );
                })}
              </div>

              <div className="ql-sec-label">Recent adaptation events</div>
              {events.length === 0 ? (
                /* ── Empty (online success, no AdaptationEvent records) ────────── */
                <EmptyState
                  title="No adaptation events"
                  text={
                    (data?.state.cycle_count ?? 0) > 0
                      ? "The loop is running but has not emitted any mutations yet — it may be in an early exploration phase. Check the Coordinator logs if this persists."
                      : "No AdaptationEvent records found — either no cycles have run yet, or the AdaptiveAgent has emitted no mutations."
                  }
                  action={
                    <a className="btn btn-ghost btn-sm" href="/#snapshots">
                      <Icon name="arrow" className="ico" />
                      Go to Snapshots
                    </a>
                  }
                />
              ) : (
                <div className="tablecard">
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th className="num" scope="col" style={{ width: "90px" }}>
                          Emitted
                        </th>
                        <th scope="col" style={{ width: "90px" }}>
                          Cycle
                        </th>
                        <th scope="col" style={{ width: "96px" }}>
                          Kind
                        </th>
                        <th scope="col" style={{ width: "230px" }}>
                          Parameter
                        </th>
                        <th className="num" scope="col" style={{ width: "130px" }}>
                          Prev → New
                        </th>
                        <th className="num" scope="col" style={{ width: "80px" }}>
                          Delta
                        </th>
                        <th scope="col">Rationale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((e) => {
                        const isInt = Number.isInteger(e.previous_value) && Number.isInteger(e.new_value);
                        const fmtVal = (n: number) => (isInt ? Math.round(n).toString() : n.toFixed(3));
                        const deltaStr = `${e.delta > 0 ? "+" : e.delta < 0 ? "−" : ""}${
                          isInt ? Math.abs(Math.round(e.delta)).toString() : Math.abs(e.delta).toFixed(3)
                        }`;
                        const when = e.emitted_label ?? e.emitted_at;
                        return (
                          <tr className="data" key={e.event_id}>
                            <td className="num">
                              <span title={e.emitted_at}>{when}</span>
                            </td>
                            <td>
                              <span
                                className="mono"
                                style={{
                                  fontSize: "11px",
                                  color: "var(--fg-subtle)",
                                  display: "block",
                                  maxWidth: "90px",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                }}
                                title={e.cycle_id}
                              >
                                {e.cycle_id}
                              </span>
                            </td>
                            <td>
                              <Pill variant={e.kind === "increase" ? "info" : "neutral"}>
                                {e.kind}
                              </Pill>
                            </td>
                            <td>
                              <span className="mono" style={{ fontSize: "11.5px" }}>
                                {e.parameter_name}
                              </span>
                            </td>
                            <td className="num mono">
                              {fmtVal(e.previous_value)} → {fmtVal(e.new_value)}
                            </td>
                            <td className={e.delta > 0 ? "num mono pos" : "num mono neg"}>
                              {deltaStr}
                            </td>
                            <td>{e.rationale}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </main>

        <footer className="ql-foot">
          Calibration changes happen automatically via the Coordinator loop. To revert a degraded
          adaptation, <a href="/#snapshots">go to Snapshots →</a>
        </footer>
      </div>
    </div>
  );
}
