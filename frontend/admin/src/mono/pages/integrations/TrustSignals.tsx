"use client";

import { useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { Pill } from "@/mono/components";
import { cn } from "@/mono/lib/cn";
import { Icon } from "@/mono/lib/icons";
import type { StatusVariant } from "@/mono/lib/types";
import {
  fetchPublicScopeCompareBoard,
  fetchPublicTrustSignalsBoard,
  type PublicScopeCompareBoard,
  type PublicTrustSignalsBoard,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Trust Signals Board — standalone Mono public section (/integrations).
 *
 * Public endpoints (no auth) drive two queries that always run:
 *   • fetchPublicTrustSignalsBoard  → trust posture + 3 scorecards (score,
 *     status, evidence bullets, action links).
 *   • fetchPublicScopeCompareBoard  → posture cards for two scopes + the
 *     per-metric preferred-side comparison.
 *
 * Fixtures are the OFFLINE fallback: live success
 * → live data; live success but EMPTY → designed empty state; live error →
 * designed error state with retry; offline/disabled → in-file fixtures so the
 * section is fully reviewable with no backend. Every display surface resolves
 * `live ?? FIXTURE` and gates loading/error on the DISPLAY set, never the raw
 * live set — so fixtures always win offline and no skeleton/empty/error hides
 * the interactive UI.
 *
 * Visual design is the `.pub` scope (mirrors Status.tsx / Integrations.tsx):
 * `.pub-card`, `.metric-strip`, `.svc-row`, Mono `<Pill>`, tokens only. No new
 * colors/fonts.
 * -------------------------------------------------------------------------- */

const TRUST_SCOPE = { product_id: "aspose.ocr", programming_language: "net" } as const;
const COMPARE_SCOPE = {
  left_product_id: "aspose.ocr",
  left_programming_language: "net",
  right_product_id: "aspose.cells",
  right_programming_language: "net",
} as const;

/* ---------------- status → Mono variant ------------------------------------ */

function postureVariant(status: string): StatusVariant {
  const s = status.toLowerCase();
  if (s === "strong" || s === "high" || s === "ready" || s === "trusted") return "ok";
  if (s === "watch" || s === "guarded" || s === "aging" || s === "monitor") return "warn";
  if (s === "weak" || s === "investigate" || s === "blocked" || s === "not-ready") return "crit";
  return "info";
}

/** Posture chip label is the raw posture token, humanized lightly. */
function postureLabel(status: string): string {
  return status.replace(/[_-]+/g, " ");
}

/* ---------------- fixtures (offline dataset) -------------------------------- */

const TRUST_FIXTURE: PublicTrustSignalsBoard = {
  product_id: "aspose.ocr",
  programming_language: "net",
  requested_version: null,
  resolved_version: "latest-stable",
  trust_posture: "watch",
  strong_total: 1,
  watch_total: 2,
  weak_total: 0,
  status_summary:
    "Trust posture is WATCH — readiness is strong, but freshness is aging and one feedback issue is open.",
  explainability: [
    "Readiness evidence supports public MCP use for aspose.ocr (net).",
    "Freshness is the limiting signal: the active snapshot is older than the 14-day comfort window.",
    "Resolve the open feedback issue to lift the posture from WATCH to STRONG.",
  ],
  scorecards: [
    {
      signal_id: "readiness",
      title: "Readiness",
      status: "strong",
      score: 0.96,
      summary: "Docs and API reference are both indexed and serving the latest stable version.",
      evidence: [
        "Docs repository indexed · 188,963 chunks",
        "API reference indexed · 161,802 chunks",
        "Self-test: all readiness checks passing",
      ],
      actions: [
        { label: "Open self-test", href: "#self-test" },
        { label: "Coverage navigator", href: "#coverage-navigator" },
      ],
    },
    {
      signal_id: "freshness",
      title: "Freshness",
      status: "watch",
      score: 0.71,
      summary: "Active snapshot is 25 days old (target ≤ 14d). No newer release detected yet.",
      evidence: [
        "Latest active snapshot · 25d ago",
        "Resolved version matches newest available",
        "No stale-source-kind gaps",
      ],
      actions: [
        { label: "Freshness & releases", href: "#freshness" },
        { label: "Triage center", href: "#triage" },
      ],
    },
    {
      signal_id: "feedback",
      title: "Feedback",
      status: "watch",
      score: 0.74,
      summary: "One open community issue references an outdated table-recognition example.",
      evidence: ["2 open community issues", "1 linked to a stale snippet", "No critical reports"],
      actions: [{ label: "Report an issue", href: "/status#report" }],
    },
  ],
  generated_at: "2026-06-10T09:00:00Z",
};

const COMPARE_FIXTURE: PublicScopeCompareBoard = {
  preferred_side: "left",
  status_summary:
    "aspose.ocr (net) leads aspose.cells (net) on average signal score and executable-snippet coverage.",
  explainability: [
    "aspose.ocr has a higher average signal score across readiness, freshness and feedback.",
    "aspose.cells trails on developer feedback — more open issues reference outdated examples.",
  ],
  left_scope: {
    product_id: "aspose.ocr",
    programming_language: "net",
    requested_version: null,
    resolved_version: "latest-stable",
    trust_posture: "watch",
    average_signal_score: 0.8,
    executable_snippets_count: 1240,
    summary: "Strong readiness; freshness and feedback are the watch items.",
  },
  right_scope: {
    product_id: "aspose.cells",
    programming_language: "net",
    requested_version: null,
    resolved_version: "latest-stable",
    trust_posture: "watch",
    average_signal_score: 0.78,
    executable_snippets_count: 980,
    summary: "Readiness is solid; developer feedback is weaker than aspose.ocr.",
  },
  metrics: [
    {
      metric_id: "readiness",
      title: "Readiness",
      preferred_side: "tie",
      summary: "Both scopes index docs and API reference for the latest stable version.",
      left_score: 0.96,
      right_score: 0.95,
      left_status: "strong",
      right_status: "strong",
      left_evidence: ["Docs + apiref indexed", "Self-test passing"],
      right_evidence: ["Docs + apiref indexed", "Self-test passing"],
      left_href: "#coverage-navigator",
      right_href: "#coverage-navigator",
    },
    {
      metric_id: "freshness",
      title: "Freshness",
      preferred_side: "right",
      summary: "aspose.cells has a slightly newer active snapshot.",
      left_score: 0.71,
      right_score: 0.79,
      left_status: "watch",
      right_status: "watch",
      left_evidence: ["Snapshot 25d"],
      right_evidence: ["Snapshot 18d"],
      left_href: "#freshness",
      right_href: "#freshness",
    },
    {
      metric_id: "feedback",
      title: "Feedback",
      preferred_side: "left",
      summary: "aspose.ocr has fewer open community issues and more positive usefulness ratings.",
      left_score: 0.74,
      right_score: 0.6,
      left_status: "watch",
      right_status: "watch",
      left_evidence: ["2 open issues", "1 stale snippet"],
      right_evidence: ["4 open issues", "sparse ratings"],
      left_href: "#feedback-reporting",
      right_href: "#feedback-reporting",
    },
  ],
  generated_at: "2026-06-10T09:00:00Z",
};

/* ---------------- helpers --------------------------------------------------- */

function errMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "Could not load trust signals from the public API.";
}

function scoreText(score: number): string {
  // Backend may emit 0..1 fractions or 0..100 scores — render both readably.
  if (score <= 1) return `${Math.round(score * 100)}`;
  return `${Math.round(score)}`;
}

/* ---------------- section --------------------------------------------------- */

export default function TrustSignals() {
  const trustQuery = useQuery({
    queryKey: ["public-trust-signals", TRUST_SCOPE.product_id, TRUST_SCOPE.programming_language],
    queryFn: () => fetchPublicTrustSignalsBoard({ ...TRUST_SCOPE }),
    staleTime: 60_000,
  });

  const compareQuery = useQuery({
    queryKey: [
      "public-scope-compare",
      COMPARE_SCOPE.left_product_id,
      COMPARE_SCOPE.right_product_id,
    ],
    queryFn: () => fetchPublicScopeCompareBoard({ ...COMPARE_SCOPE }),
    staleTime: 60_000,
  });

  // Display source with fixture fallback — fixtures always win offline.
  const board: PublicTrustSignalsBoard =
    trustQuery.data && trustQuery.data.scorecards.length > 0 ? trustQuery.data : TRUST_FIXTURE;
  const compare: PublicScopeCompareBoard =
    compareQuery.data && compareQuery.data.metrics.length > 0
      ? compareQuery.data
      : COMPARE_FIXTURE;

  // Live-only error: surface a retry affordance, but only when there is no
  // display data at all (offline → board is the fixture → never errors out).
  const boardErrored = trustQuery.isError && !(trustQuery.data?.scorecards.length ?? 0);

  // Scorecard focus is local UI state; clicking a card filters the evidence
  // rail to that signal (offline this operates on the fixture scorecards).
  const [focus, setFocus] = useState<string | null>(null);
  const focused = useMemo(
    () => board.scorecards.find((s) => s.signal_id === focus) ?? null,
    [board.scorecards, focus],
  );

  return (
    <>
      {/* trust posture + scorecards */}
      <section className="pub-card" style={{ marginTop: 18 }} aria-label="Trust signals board">
        <div className="pub-card-head">
          <span className="pub-card-title">Trust signals board</span>
          <span className="right" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Pill variant={postureVariant(board.trust_posture)}>
              {postureLabel(board.trust_posture)}
            </Pill>
            <span className="muted-note">
              {board.product_id}
              {board.programming_language ? ` · ${board.programming_language}` : ""}
            </span>
          </span>
        </div>

        {boardErrored ? (
          <div style={{ padding: "16px 20px" }}>
            <div
              className="pub-status-led"
              style={{ background: "var(--crit-bg)", color: "var(--crit)" }}
            >
              <span className="led" style={{ background: "var(--crit)", animation: "none" }} />
              {errMessage(trustQuery.error)}
            </div>
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="pub-cta ghost"
                style={{ height: 32, fontSize: 12 }}
                onClick={() => void trustQuery.refetch()}
              >
                <Icon name="refresh" /> Retry
              </button>
            </div>
          </div>
        ) : board.scorecards.length === 0 ? (
          <div style={{ padding: "18px 20px" }}>
            <span className="muted-note">
              No trust signals are available for this scope yet. Run the self-test and re-check
              coverage to populate the board.
            </span>
          </div>
        ) : (
          <>
            {/* posture strip — one cell per signal score */}
            <div
              className="metric-strip"
              style={{
                gridTemplateColumns: `repeat(${Math.max(board.scorecards.length, 1)}, 1fr)`,
                borderTop: "1px solid var(--border)",
              }}
              role="group"
              aria-label="Signal scores"
            >
              {board.scorecards.map((s) => {
                const active = focus === s.signal_id;
                return (
                  <button
                    key={s.signal_id}
                    type="button"
                    className="m"
                    onClick={() => setFocus(active ? null : s.signal_id)}
                    aria-pressed={active}
                    style={{
                      textAlign: "left",
                      background: active ? "var(--bg-subtle)" : "transparent",
                      border: 0,
                      borderRight: "1px solid var(--border)",
                      cursor: "pointer",
                      font: "inherit",
                    }}
                  >
                    <div className="mv">
                      {scoreText(s.score)}
                      <span style={{ fontSize: 13, color: "var(--fg-subtle)" }}> / 100</span>
                    </div>
                    <div
                      className="ml"
                      style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5 }}
                    >
                      <Pill variant={postureVariant(s.status)}>{s.title}</Pill>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* per-signal scorecards: summary + evidence bullets + action links */}
            {board.scorecards
              .filter((s) => focus === null || s.signal_id === focus)
              .map((s) => (
                <div className="svc-row" key={s.signal_id} style={{ alignItems: "flex-start" }}>
                  <Pill variant={postureVariant(s.status)}>{s.status}</Pill>
                  <div style={{ flex: 1 }}>
                    <div className="svc-name">
                      {s.title}
                      <span
                        className="mono"
                        style={{ marginLeft: 8, fontSize: 11, color: "var(--fg-subtle)" }}
                      >
                        {s.signal_id} · score {scoreText(s.score)}/100
                      </span>
                    </div>
                    <div className="svc-desc">{s.summary}</div>
                    {s.evidence.length > 0 && (
                      <ul
                        className="muted-note"
                        style={{ margin: "8px 0 0", paddingLeft: 16, lineHeight: 1.6 }}
                      >
                        {s.evidence.map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    )}
                    {s.actions.length > 0 && (
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 8,
                          marginTop: 10,
                        }}
                      >
                        {s.actions.map((a) => (
                          <a
                            key={`${a.label}-${a.href}`}
                            className="pub-cta ghost"
                            href={a.href}
                            style={{ height: 28, fontSize: 12, padding: "0 12px" }}
                          >
                            {a.label} <Icon name="arrow" />
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}

            {/* explainability + posture summary footer */}
            <div style={{ padding: "14px 20px", borderTop: "1px solid var(--border)" }}>
              <div className="muted-note" style={{ marginBottom: focused ? 0 : 6 }}>
                {focused
                  ? `Showing the ${focused.title} signal — clear focus to see all signals.`
                  : board.status_summary}
              </div>
              {!focused &&
                board.explainability.map((line, i) => (
                  <div
                    key={i}
                    className="muted-note"
                    style={{ display: "flex", gap: 8, marginTop: 4 }}
                  >
                    <span aria-hidden="true" style={{ color: "var(--fg-subtle)" }}>
                      •
                    </span>
                    <span>{line}</span>
                  </div>
                ))}
            </div>
          </>
        )}
      </section>

      {/* scope comparison — posture cards + per-metric preferred side */}
      <section className="pub-card" style={{ marginTop: 18 }} aria-label="Scope comparison">
        <div className="pub-card-head">
          <span className="pub-card-title">Scope comparison</span>
          <span className="right muted-note">
            {compare.left_scope.product_id} vs {compare.right_scope.product_id}
          </span>
        </div>

        {/* two posture cards */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            borderTop: "1px solid var(--border)",
          }}
        >
          {[
            { side: "left" as const, scope: compare.left_scope },
            { side: "right" as const, scope: compare.right_scope },
          ].map(({ side, scope }) => {
            const preferred = compare.preferred_side === side;
            return (
              <div
                key={side}
                style={{
                  padding: "16px 20px",
                  borderRight: side === "left" ? "1px solid var(--border)" : undefined,
                  background: preferred ? "var(--bg-subtle)" : "transparent",
                }}
              >
                <div
                  style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
                >
                  <span className="svc-name">{scope.product_id}</span>
                  {scope.programming_language && (
                    <span className="mono" style={{ fontSize: 11, color: "var(--fg-muted)" }}>
                      {scope.programming_language}
                    </span>
                  )}
                  <Pill variant={postureVariant(scope.trust_posture)}>
                    {postureLabel(scope.trust_posture)}
                  </Pill>
                  {preferred && (
                    <span className="muted-note" style={{ marginLeft: "auto" }}>
                      preferred
                    </span>
                  )}
                </div>
                <div className="svc-desc" style={{ marginBottom: 8 }}>
                  {scope.summary}
                </div>
                <div style={{ display: "flex", gap: 18 }}>
                  <div>
                    <div className="mv" style={{ fontSize: 20 }}>
                      {scoreText(scope.average_signal_score)}
                      <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}> / 100</span>
                    </div>
                    <div className="ml">Avg signal score</div>
                  </div>
                  <div>
                    <div className="mv" style={{ fontSize: 20 }}>
                      {scope.executable_snippets_count.toLocaleString()}
                    </div>
                    <div className="ml">Executable snippets</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* per-metric comparison table */}
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Metric</th>
                <th style={{ width: 130 }}>{compare.left_scope.product_id}</th>
                <th style={{ width: 130 }}>{compare.right_scope.product_id}</th>
                <th style={{ width: 110 }}>Preferred</th>
              </tr>
            </thead>
            <tbody>
              {compare.metrics.map((m) => (
                <tr className="data" key={m.metric_id}>
                  <td>
                    <div className="svc-name" style={{ fontSize: 12.5 }}>
                      {m.title}
                    </div>
                    <div className="muted-note">{m.summary}</div>
                  </td>
                  <td>
                    <a
                      href={m.left_href}
                      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                    >
                      <Pill variant={postureVariant(m.left_status)}>
                        {scoreText(m.left_score)}
                      </Pill>
                    </a>
                  </td>
                  <td>
                    <a
                      href={m.right_href}
                      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                    >
                      <Pill variant={postureVariant(m.right_status)}>
                        {scoreText(m.right_score)}
                      </Pill>
                    </a>
                  </td>
                  <td>
                    {m.preferred_side === "tie" ? (
                      <span className="muted-note">tie</span>
                    ) : (
                      <span className="mono" style={{ fontSize: 11.5 }}>
                        {m.preferred_side === "left"
                          ? compare.left_scope.product_id
                          : compare.right_scope.product_id}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
          <span className="muted-note">{compare.status_summary}</span>
        </div>
      </section>
    </>
  );
}
