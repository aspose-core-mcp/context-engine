"use client";

import { useState, type ReactNode } from "react";

import { useCriticalEvents } from "@/hooks/useCriticalEvents";
import { useHealthQueries } from "@/hooks/useHealthQueries";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Kpi, KpiRow } from "../components/Kpi";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { EmptyState, ErrorState, Skeleton } from "../components/states";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { StatusVariant } from "../lib/types";
import { useShell } from "../shell/context";
import { useAdminData } from "../shell/data";

interface CompDatum {
  key: string;
  label: string;
  status: string;
  required: boolean;
  reason: string;
  text: ReactNode;
  steps: string[];
}

// Fixture prose (human label / explanation / fix steps) — live status/required/reason
// from the API are merged over these by dependency name; used wholesale when offline.
const COMP_DATA: CompDatum[] = [
  {
    key: "postgres",
    label: "Metadata DB (PostgreSQL)",
    status: "ready",
    required: false,
    reason: "not_required_for_current_runtime",
    text: (
      <>
        <b>postgres</b> is not required for the current runtime topology, so readiness does not
        depend on it.
      </>
    ),
    steps: [
      "No action required for the current runtime profile.",
      "If you expect this dependency to be used, switch the runtime adapters and re-run readiness.",
    ],
  },
  {
    key: "redis",
    label: "Cache & queue (Redis)",
    status: "ready",
    required: false,
    reason: "not_required_for_current_runtime",
    text: (
      <>
        <b>redis</b> is optional in dev profile; queueing falls back to the in-process scheduler.
      </>
    ),
    steps: [
      "Safe to ignore in the dev runtime profile.",
      "Provision Redis before enabling distributed ingestion workers.",
    ],
  },
  {
    key: "qdrant",
    label: "Vector index (Qdrant)",
    status: "ready",
    required: true,
    reason: "connected · memory profile",
    text: (
      <>
        <b>qdrant</b> is the active dense-retrieval store and is required. It is currently serving
        from the in-memory profile.
      </>
    ),
    steps: [
      "No action needed — vector search is live.",
      "Switch to a persistent profile before production traffic.",
    ],
  },
  {
    key: "opensearch",
    label: "Lexical index (OpenSearch)",
    status: "ready",
    required: true,
    reason: "connected · 1 shard",
    text: (
      <>
        <b>opensearch</b> backs lexical retrieval and is required. Single-shard dev configuration is
        active.
      </>
    ),
    steps: [
      "No action needed — lexical search is live.",
      "Add replicas before production to survive node loss.",
    ],
  },
];

const OPS: [name: string, scope: string][] = [
  ["Trigger Source Sync", "write:ingestion"],
  ["Validate-Only Ingestion", "write:ingestion"],
  ["Delete Product Version Data", "write:destructive"],
];

function depPill(status: string): StatusVariant {
  if (status === "ready" || status === "ok" || status === "healthy") return "ok";
  if (status === "degraded" || status === "warning") return "warn";
  if (status === "critical" || status === "down" || status === "error") return "crit";
  return "neutral";
}

export function HealthSection() {
  const { navigate } = useShell();
  const data = useAdminData();
  const health = useHealthQueries({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "health",
    showAlert: data.showAlert,
    showConfirm: data.showConfirm,
    canConfigureAbuseGuard: data.can("write:settings"),
  });
  // Read-only incident feed for the headline banner (the incident segment comes from
  // criticalEvents.criticalIncidents). The hook's 60s auto-refresh gate keys off the
  // SidebarSectionId "critical-events" — pass that so the banner honors this page's
  // "Auto-refresh 60s" promise while mounted.
  // Lifecycle actions live in the Critical section, so the hook's prompt path is inert.
  const events = useCriticalEvents({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    activeSectionId: "critical-events",
    canMutateIngestion: data.can("write:ingestion"),
    showAlert: data.showAlert,
    showPrompt: () => {},
  });

  // Live vs fixture: offline (no session → queries disabled) the fixtures ARE the dataset
  // and the page renders fully populated. Online, banner / KPIs / component
  // list bind live state only — loading / error / empty are real states and
  // fixtures never mask them.
  const offline = !data.sessionIsSuccess;

  // Live dependency status merged with fixture prose; fixtures wholesale when offline.
  const liveDeps = health.dependencyRows;
  const liveComponents: CompDatum[] = liveDeps.map(([name, item]) => {
    const fx = COMP_DATA.find((c) => c.key === name);
    return {
      key: name,
      label: fx?.label ?? name,
      status: item.status ?? "unknown",
      required: item.required ?? fx?.required ?? false,
      reason: item.reason ?? fx?.reason ?? "—",
      text: fx?.text ?? <>Live status for <b>{name}</b>.</>,
      steps: fx?.steps ?? [],
    };
  });
  const components: CompDatum[] = offline ? COMP_DATA : liveComponents;

  const [sel, setSel] = useState(COMP_DATA[0].key);
  const active = components.find((c) => c.key === sel) ?? components[0];

  const loading = !offline && health.healthQuery.isLoading && !components.length;
  const errored = !offline && health.healthQuery.isError && !components.length;
  const empty = !offline && !loading && !errored && components.length === 0;

  // ── Headline banner — live incident/runtime state (never announce "no active
  //    critical incidents" as a compile-time constant). Service + control-plane segments
  //    come from healthQuery (status / process), the queue segment from criticalIncidents.
  //    API limitation: the fixture's "ingestion runtime completed" segment would source from
  //    ingestion.jobsQuery[0]; this section does not consume
  //    useIngestionState, so the live text omits the ingestion segment.
  const healthData = health.healthQuery.data;
  const healthErr = health.healthQuery.isError;
  const incidentsErr = events.criticalEventsQuery.isError;
  const incidentsReady = events.criticalEventsQuery.isSuccess;
  // Muted/snoozed incidents are deliberately silenced and resolved ones are closed —
  // neither should trip the dashboard headline.
  const activeIncidents = events.criticalIncidents.filter(
    (e) =>
      e.lifecycle.status === "open" ||
      e.lifecycle.status === "acknowledged" ||
      e.lifecycle.status === "escalated",
  );
  const runtimeOk = !healthErr && healthData?.status === "ok" && healthData?.process === "ok";
  const banner = (() => {
    if (offline) {
      return {
        variant: "ok" as const,
        icon: "check" as const,
        title: "No active critical incidents",
        text: "Service online · control plane ok · ingestion runtime completed · incident queue clean.",
      };
    }
    const svcSeg = healthErr
      ? "Service unreachable"
      : healthData
        ? healthData.status === "ok"
          ? "Service online"
          : `Service ${healthData.status}`
        : "Service status pending";
    const cpSeg = healthErr
      ? "control plane unreachable"
      : healthData
        ? healthData.process === "ok"
          ? "control plane ok"
          : "control plane degraded"
        : "control plane pending";
    const incSeg = incidentsErr
      ? "incident queue unavailable"
      : incidentsReady
        ? activeIncidents.length
          ? `${activeIncidents.length} active incident${activeIncidents.length === 1 ? "" : "s"} in queue`
          : "incident queue clean"
        : "incident queue pending";
    const text = `${svcSeg} · ${cpSeg} · ${incSeg}.`;
    if (activeIncidents.length) {
      return {
        variant: "warn" as const,
        icon: "alert" as const,
        title: `${activeIncidents.length} active critical incident${activeIncidents.length === 1 ? "" : "s"}`,
        text,
      };
    }
    if (healthErr || incidentsErr || (healthData && !runtimeOk)) {
      return {
        variant: "warn" as const,
        icon: "alert" as const,
        title: healthErr
          ? "Control plane unreachable"
          : incidentsErr
            ? "Incident queue unavailable"
            : "Service degraded",
        text,
      };
    }
    if (healthData && incidentsReady) {
      return {
        variant: "ok" as const,
        icon: "check" as const,
        title: "No active critical incidents",
        text,
      };
    }
    // Queries still settling — never assert a clean queue before we actually know.
    return {
      variant: "info" as const,
      icon: "info" as const,
      title: "Checking incident & runtime state",
      text,
    };
  })();

  // ── KPI strip — live bindings where this section's hooks expose a source; the
  //    n/a treatment (healthQuery error → KPIs show 'n/a')
  //    replaces fixture numbers whenever we are online without live health data.
  const kpiNA = !offline && !healthData;
  const uptimeValue = offline
    ? "online"
    : healthData
      ? healthData.status === "ok"
        ? "online"
        : healthData.status
      : "n/a";
  const uptimeFoot = `service status = ${offline ? "ok" : (healthData?.status ?? "n/a")}`;
  const okCount = components.filter((c) => depPill(c.status) === "ok").length;
  const requiredDown = components.some((c) => c.required && depPill(c.status) !== "ok");
  // Readiness color rules — green=Ready, yellow=Degraded, red=Not Ready.
  // Live-only: the offline fixture strip stays bare (no pill).
  const readinessPill =
    offline || !components.length
      ? undefined
      : requiredDown
        ? { variant: "crit" as const, text: "not ready" }
        : okCount < components.length
          ? { variant: "warn" as const, text: "degraded" }
          : { variant: "ok" as const, text: "ready" };

  return (
    <>
      <PageHead
        title="Health"
        sub="System health & component liveness — runtime readiness, dependencies, and active incidents."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            <ScopeChip label="role" value={data.session?.is_superuser ? "superuser" : "operator"} dot />
            <span className="muted-note">Auto-refresh 60s</span>
            <Button
              variant="btn-primary"
              size="sm"
              icon="refresh"
              onClick={() => {
                // The banner reflects both runtime and incident state — refresh both feeds.
                void health.healthQuery.refetch();
                void events.criticalEventsQuery.refetch();
              }}
            >
              Refresh now
            </Button>
          </>
        }
      />

      {/* Live incident/runtime banner; cards click-open their sections, so the
          actions slot carries the drill-in (works offline too — pure navigation). */}
      <Banner
        variant={banner.variant}
        icon={banner.icon}
        title={banner.title}
        text={banner.text}
        actions={
          <Button variant="btn-ghost" size="sm" icon="arrow" onClick={() => navigate("critical")}>
            View incidents
          </Button>
        }
      />

      <KpiRow cols={4}>
        <Kpi label="Uptime" value={uptimeValue} foot={uptimeFoot} />
        <Kpi
          label="Readiness"
          value={
            kpiNA ? (
              "n/a"
            ) : (
              <>
                {okCount}
                <small>/{components.length}</small>
              </>
            )
          }
          foot={
            <>
              <span className="dotset">
                {components.map((c) => (
                  <span className="d" key={c.key} />
                ))}
              </span>{" "}
              dependencies ready
            </>
          }
          pill={readinessPill}
        />
        {/* API limitation: the intended live source is the analytics outcome counters
            (error_rate_5xx = errors/total from analyticsSliceQuery, red >5% / yellow >2%);
            useHealthQueries exposes no request-outcome metrics, so online this tile renders
            the n/a treatment instead of a fake fixture number. */}
        <Kpi
          label="5xx error rate"
          value={
            offline ? (
              <>
                0.00<small>%</small>
              </>
            ) : (
              "n/a"
            )
          }
          foot="rolling 10m window"
          accent
        />
        {/* API limitation: no p95 latency feed exists in this section's hooks (observability only
            exposes canary thresholds, not measured latency) — n/a online, never a fake
            number; the "within SLO" claim renders only with the offline fixture value. */}
        <Kpi
          label="p95 latency"
          value={
            offline ? (
              <>
                212<small>ms</small>
              </>
            ) : (
              "n/a"
            )
          }
          foot={offline ? "query_docs · within SLO" : "query_docs"}
        />
      </KpiRow>

      <Card
        title="Component status"
        sub="Dependency-by-dependency status with drill-down diagnostics. Select a component to inspect."
        flush
        right={
          // The link uses a TRAILING arrow; the kit Button only has a leading-icon slot, so place
          // the `.ico` arrow after the label by hand to match the deep-link affordance.
          <Button variant="btn-ghost" size="sm" onClick={() => navigate("indexes")}>
            View topology <Icon name="arrow" className="ico" />
          </Button>
        }
      >
        {loading ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={4} />
          </div>
        ) : errored ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Failed to load component health"
              cause="the admin API is unreachable"
              actions={
                <Button size="sm" icon="refresh" onClick={() => health.healthQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          </div>
        ) : empty ? (
          // Online success with an empty dependency map — empty state, never a
          // fixture substitution.
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No dependencies reported"
              text="The health endpoint returned no dependency data. Refresh to re-check readiness."
              action={
                <Button size="sm" icon="refresh" onClick={() => health.healthQuery.refetch()}>
                  Refresh
                </Button>
              }
            />
          </div>
        ) : (
          <>
            <div className="comp-list">
              {components.map((c) => (
                <button
                  key={c.key}
                  type="button"
                  className={cn("comp-row", c.key === sel && "sel")}
                  aria-pressed={c.key === sel}
                  onClick={() => setSel(c.key)}
                >
                  <Pill variant={depPill(c.status)}>
                    {depPill(c.status) === "ok" ? "ready" : c.status}
                  </Pill>
                  <span className="comp-name">{c.key}</span>
                  <span className="card-sub" style={{ margin: 0 }}>
                    {c.label}
                  </span>
                  <span className="comp-reason">{c.required ? "required" : "optional"}</span>
                  <Icon name="chevronR" className="chev" />
                </button>
              ))}
            </div>
            <div className="drill" id="comp-drill">
              <div className="drill-kv">
                <span className="kvline">
                  status=<b>{active.status}</b>
                </span>
                <span className="kvline">
                  reason=<b>{active.reason}</b>
                </span>
                <span className="kvline">
                  required=<b>{String(active.required)}</b>
                </span>
              </div>
              <p>{active.text}</p>
              {active.steps.length > 0 && (
                <ol className="fix-steps">
                  {active.steps.map((s, i) => (
                    <li key={i}>
                      <span>{s}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </>
        )}
      </Card>

      <Card
        title="Operation scope preview"
        sub="Scope-gated actions under the current admin key. Disallowed actions stay disabled with a scope hint."
        flush
      >
        <div className="op-list">
          {OPS.map(([name, scope]) => {
            const ok = data.can(scope);
            return (
              <div key={name} className={cn("op-row", !ok && "denied")}>
                {ok ? <Pill variant="ok">allowed</Pill> : <Pill variant="neutral">no scope</Pill>}
                <div>
                  <div className="op-name">{name}</div>
                  <div className="op-meta">
                    requires <Tag>{scope}</Tag>
                  </div>
                </div>
                <div className="op-right">
                  <Button variant="btn-ghost" size="sm" icon="play" disabled={!ok}>
                    Run
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </>
  );
}
