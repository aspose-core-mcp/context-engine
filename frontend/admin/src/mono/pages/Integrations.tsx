"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName } from "../lib/types";

/* Section components — each is a self-contained `pub` section that owns its own
 * form state, TanStack `useQuery` over the public admin-api `fetchPublic*` fns,
 * and an in-file offline fixture fallback (see each file's header). They take
 * no props. */
import GenerateConfigs from "./integrations/GenerateConfigs";
import SelfTest from "./integrations/SelfTest";
import GuidedJourneys from "./integrations/GuidedJourneys";
import StarterPacks from "./integrations/StarterPacks";
import BundleBuilder from "./integrations/BundleBuilder";
import CoverageNavigator from "./integrations/CoverageNavigator";
import GapTracker from "./integrations/GapTracker";
import CapabilityExplorer from "./integrations/CapabilityExplorer";
import TrustSignals from "./integrations/TrustSignals";
import ReleaseAdoption from "./integrations/ReleaseAdoption";
import UpgradeAssistant from "./integrations/UpgradeAssistant";
import TroubleshootingDesk from "./integrations/TroubleshootingDesk";
import TriageCenter from "./integrations/TriageCenter";
import QueryPlayground from "./integrations/QueryPlayground";
import FeedbackReporting from "./integrations/FeedbackReporting";
import WorkspacePresets from "./integrations/WorkspacePresets";
import SnippetExplorer from "./integrations/SnippetExplorer";
import PromptCookbook from "./integrations/PromptCookbook";
import FreshnessVisibility from "./integrations/FreshnessVisibility";
import UseCaseGallery from "./integrations/UseCaseGallery";

/* ----------------------------------------------------------------------------
 * MCP Integration Portal (/integrations) — assembled Mono public page.
 *
 * This file is the SHELL + ASSEMBLY only. It renders the public shell (sticky
 * nav · hero · footer · hydration-safe theme toggle) and the section components
 * in grouped lifecycle order (registration → readiness → onboarding → coverage →
 * trust/evidence → releases → diagnose → try-it → workspace). An in-page section
 * nav (sticky, reusing `.pub` scope classes + tokens) links to each anchor.
 *
 * Each section is fully self-contained (no props) and reviewable offline via its
 * own fixtures, so this page imports them and lays them out — it does not own any
 * section data wiring itself.
 * -------------------------------------------------------------------------- */

const THEME_KEY = "adcs_theme";

/** Sticky offset so the section nav + top nav don't cover an anchored heading. */
const ANCHOR_SCROLL_OFFSET = 132;

interface SectionDef {
  id: string;
  label: string;
  /** Short kicker shown above the section heading. */
  kicker: string;
  /** One-line orientation copy for the section heading block. */
  blurb: string;
  Component: () => ReactNode;
}

interface GroupDef {
  id: string;
  title: string;
  icon: IconName;
  /** What this stage of the MCP-adoption lifecycle answers. */
  summary: string;
  sections: SectionDef[];
}

/* Grouped order — follows the MCP-adoption lifecycle
 * (registration → readiness verification → onboarding handoff → coverage →
 * trust posture → safety gates → upgrade planning → issue triage → try-it →
 * workspace). Anchor ids match each section's intended in-page target. */
const GROUPS: GroupDef[] = [
  {
    id: "grp-connect",
    title: "Connect & verify",
    icon: "key",
    summary: "Generate a ready-to-paste MCP config, then prove the product is MCP-ready.",
    sections: [
      {
        id: "generate-client-configs",
        label: "Generate configs",
        kicker: "Onboard",
        blurb: "Ready-to-paste MCP configs for Cursor, Claude Desktop, Qwen Code and VS Code.",
        Component: GenerateConfigs,
      },
      {
        id: "self-test",
        label: "Self-test",
        kicker: "Verify",
        blurb: "Run the GA-readiness diagnostic for a product / language / client scope.",
        Component: SelfTest,
      },
    ],
  },
  {
    id: "grp-onboard",
    title: "Guided onboarding",
    icon: "list",
    summary: "Hand a working setup to a developer — journeys, starter packs and multi-client bundles.",
    sections: [
      {
        id: "guided-journeys",
        label: "Guided journeys",
        kicker: "Workflow",
        blurb: "Step-by-step adoption workflows with evidence and a copyable share link.",
        Component: GuidedJourneys,
      },
      {
        id: "starter-packs",
        label: "Starter packs",
        kicker: "Handoff",
        blurb: "Copy-ready bundles: config + prompt + first queries + checklist, per client.",
        Component: StarterPacks,
      },
      {
        id: "bundle-builder",
        label: "Bundle builder",
        kicker: "Handoff",
        blurb: "Assemble a multi-client onboarding bundle from the clients you select.",
        Component: BundleBuilder,
      },
    ],
  },
  {
    id: "grp-coverage",
    title: "Coverage & capabilities",
    icon: "layers",
    summary: "See what is indexed — product × language readiness, deep gaps and surface capabilities.",
    sections: [
      {
        id: "coverage-navigator",
        label: "Coverage navigator",
        kicker: "Coverage",
        blurb: "Product × language readiness matrix with priority, versions and gap badges.",
        Component: CoverageNavigator,
      },
      {
        id: "coverage-gap-tracker",
        label: "Gap tracker",
        kicker: "Coverage",
        blurb: "Deep dive into readiness per product / language / version and source kind.",
        Component: GapTracker,
      },
      {
        id: "capability-explorer",
        label: "Capability explorer",
        kicker: "Coverage",
        blurb: "Compact surface table with readiness, snippet evidence and quick links.",
        Component: CapabilityExplorer,
      },
    ],
  },
  {
    id: "grp-trust",
    title: "Trust & evidence",
    icon: "shield",
    summary: "Decide “ready to announce?” from trust signals and a side-by-side scope comparison.",
    sections: [
      {
        id: "trust-signals",
        label: "Trust signals",
        kicker: "Posture",
        blurb: "Readiness, freshness and feedback rolled into one trust posture.",
        Component: TrustSignals,
      },
    ],
  },
  {
    id: "grp-release",
    title: "Releases & upgrades",
    icon: "history",
    summary:
      "See current release freshness, plan a safe upgrade, and browse the use-cases each release unlocks.",
    sections: [
      {
        id: "freshness-visibility",
        label: "Freshness & visibility",
        kicker: "Freshness",
        blurb:
          "Resolved vs newest version, per-source snapshot freshness and the latest release-note features.",
        Component: FreshnessVisibility,
      },
      {
        id: "release-adoption",
        label: "Release adoption",
        kicker: "Plan",
        blurb: "Recommended release range, migration checklist and release-note features.",
        Component: ReleaseAdoption,
      },
      {
        id: "upgrade-assistant",
        label: "Upgrade assistant",
        kicker: "Plan",
        blurb: "Build a comprehensive upgrade plan and an actionable migration prompt.",
        Component: UpgradeAssistant,
      },
      {
        id: "use-case-gallery",
        label: "Use-case gallery",
        kicker: "Explore",
        blurb: "Curated MCP use-case scenarios with starter prompts, queries and evidence to apply.",
        Component: UseCaseGallery,
      },
    ],
  },
  {
    id: "grp-diagnose",
    title: "Diagnose & triage",
    icon: "alert",
    summary: "Recover failing integrations — request-id troubleshooting and stale / no-index triage.",
    sections: [
      {
        id: "troubleshooting",
        label: "Troubleshooting desk",
        kicker: "Diagnose",
        blurb: "Recovery paths for a request_id: connection, content-gap and request-quality.",
        Component: TroubleshootingDesk,
      },
      {
        id: "content-triage",
        label: "Triage center",
        kicker: "Diagnose",
        blurb: "Indexing and freshness gaps grouped by severity, with copyable fix plans.",
        Component: TriageCenter,
      },
    ],
  },
  {
    id: "grp-tryit",
    title: "Explore, try it & report",
    icon: "play",
    summary:
      "Browse indexed snippets, grab a prompt recipe, run a grounded query, then report usefulness or content issues.",
    sections: [
      {
        id: "snippet-explorer",
        label: "Snippet explorer",
        kicker: "Explore",
        blurb:
          "Browse executable code snippets indexed per product / language / version with citations.",
        Component: SnippetExplorer,
      },
      {
        id: "prompt-cookbook",
        label: "Prompt cookbook",
        kicker: "Explore",
        blurb:
          "Curated reusable prompts — quickstart, release, migration, troubleshooting, symbol and support.",
        Component: PromptCookbook,
      },
      {
        id: "query-playground",
        label: "Query playground",
        kicker: "Try it",
        blurb: "Run grounded queries, resolve products and look up symbols against the public index.",
        Component: QueryPlayground,
      },
      {
        id: "feedback-reporting",
        label: "Feedback & issues",
        kicker: "Report",
        blurb: "Tie usefulness feedback and content-issue reports to a request_id.",
        Component: FeedbackReporting,
      },
    ],
  },
  {
    id: "grp-workspace",
    title: "Workspace",
    icon: "sliders",
    summary: "Save, export and import your portal presets and session deck for reuse across sessions.",
    sections: [
      {
        id: "workspace-presets",
        label: "Workspace presets",
        kicker: "Reuse",
        blurb: "Save, export and import playground presets and the session deck (local-only).",
        Component: WorkspacePresets,
      },
    ],
  },
];

/* Flat nav list derived from the grouped order (one link per section). */
const NAV_SECTIONS: { id: string; label: string }[] = GROUPS.flatMap((g) =>
  g.sections.map((s) => ({ id: s.id, label: s.label })),
);

/* ----------------------------------------------------------------------------
 * Page
 * -------------------------------------------------------------------------- */

export default function IntegrationsPage() {
  // Hydration-safe theme: start at the SSR default (light), then sync from
  // localStorage after mount so server and first client render agree.
  const [dark, setDark] = useState(false);
  const [themeReady, setThemeReady] = useState(false);

  useEffect(() => {
    try {
      setDark(window.localStorage.getItem(THEME_KEY) === "dark");
    } catch {
      /* localStorage may be unavailable (private mode) — keep default */
    }
    setThemeReady(true);
  }, []);

  const toggleTheme = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore persistence failures */
      }
      return next;
    });
  }, []);

  return (
    <div className={cn("pub", "t-mono", dark && "theme-dark")} suppressHydrationWarning>
      {/* ---------------------------------------------------------------- nav */}
      <header>
        <nav className="pub-nav" aria-label="Primary">
          <div className="side-logo" aria-hidden="true">
            A
          </div>
          <div className="pub-brand">
            ADCS<small>Aspose Context Service</small>
          </div>
          <div className="links">
            <a href="/status">Status</a>
            <a href="/integrations" className="on" aria-current="page">
              Integrations
            </a>
            <a href="#" aria-disabled="true" style={{ opacity: 0.55, pointerEvents: "none" }}>
              Docs
            </a>
            <a
              href="/"
              title="Open admin console"
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <Icon name="grid" />
              Console
            </a>
            <button
              type="button"
              className="icon-btn"
              data-act="theme"
              onClick={toggleTheme}
              aria-pressed={dark}
              aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              title={dark ? "Switch to light theme" : "Switch to dark theme"}
            >
              {themeReady && dark ? <Icon name="moon" /> : <Icon name="sun" />}
            </button>
          </div>
        </nav>
      </header>

      {/* --------------------------------------------------------------- main */}
      <main className="pub-wrap">
        {/* hero */}
        <section className="pub-hero">
          <span
            className="pub-status-led"
            style={{
              background: "var(--accent-weak)",
              color: "var(--accent-line)",
              borderColor: "color-mix(in srgb,var(--accent-line) 30%,var(--border))",
            }}
          >
            <span className="led" style={{ background: "var(--accent-line)", animation: "none" }} />
            Model Context Protocol
          </span>
          <h1 className="pub-h1">
            Connect your AI assistant
            <br />
            to Aspose documentation
          </h1>
          <p className="pub-sub">
            The integration command center: generate ready-to-paste MCP configs, verify GA readiness,
            inspect coverage and trust signals, plan upgrades, and diagnose live issues — all grounded
            in versioned Aspose docs and API reference.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 22 }}>
            <a className="pub-cta" href="#generate-client-configs">
              Get an MCP config <Icon name="arrow" />
            </a>
            <a className="pub-cta ghost" href="/status">
              View status
            </a>
          </div>
        </section>

        {/* in-page section nav (sticky, grouped) */}
        <SectionNav />

        {/* grouped sections */}
        {GROUPS.map((group) => (
          <section
            key={group.id}
            id={group.id}
            aria-label={group.title}
            style={{ scrollMarginTop: ANCHOR_SCROLL_OFFSET, marginTop: 34 }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                paddingBottom: 14,
                marginBottom: 4,
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 34,
                  height: 34,
                  flex: "0 0 auto",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--accent-weak)",
                  color: "var(--accent-line)",
                }}
              >
                <Icon name={group.icon} />
              </span>
              <div>
                <h2
                  className="pub-card-title"
                  style={{ margin: 0, fontSize: 19, letterSpacing: "-0.01em" }}
                >
                  {group.title}
                </h2>
                <div className="muted-note" style={{ marginTop: 2 }}>
                  {group.summary}
                </div>
              </div>
            </div>

            {group.sections.map(({ id, label, kicker, blurb, Component }) => (
              <div
                key={id}
                id={id}
                style={{ scrollMarginTop: ANCHOR_SCROLL_OFFSET, marginTop: 18 }}
              >
                <div style={{ marginBottom: 10 }}>
                  <div
                    className="mono"
                    style={{
                      fontSize: 11,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      color: "var(--fg-subtle)",
                    }}
                  >
                    {kicker}
                  </div>
                  <h3
                    className="pub-card-title"
                    style={{ margin: "2px 0 0", fontSize: 16 }}
                  >
                    {label}
                  </h3>
                  <div className="muted-note" style={{ marginTop: 2 }}>
                    {blurb}
                  </div>
                </div>
                <Component />
              </div>
            ))}
          </section>
        ))}
      </main>

      {/* ------------------------------------------------------------- footer */}
      <PubFooter note="Need a different transport? ADCS also exposes an OpenAPI-described HTTP endpoint for custom integrations." />
    </div>
  );
}

/* ----------------------------------------------------------------------------
 * Page-specific composites (markup the kit does not wrap — `.pub` scope only)
 * -------------------------------------------------------------------------- */

/** Sticky in-page section nav: horizontal, scrollable, grouped-order links. */
function SectionNav() {
  return (
    <nav
      className="pub-card"
      aria-label="Integration sections"
      style={{
        position: "sticky",
        top: 60, // below the 60px sticky primary nav
        zIndex: 4,
        marginTop: 8,
        padding: "10px 14px",
        display: "flex",
        alignItems: "center",
        gap: 8,
        overflowX: "auto",
        background: "color-mix(in srgb,var(--surface) 92%,transparent)",
        backdropFilter: "saturate(1.1) blur(6px)",
      }}
    >
      <span
        className="mono"
        style={{
          flex: "0 0 auto",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--fg-subtle)",
          paddingRight: 4,
        }}
      >
        Jump to
      </span>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {NAV_SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            style={{
              flex: "0 0 auto",
              whiteSpace: "nowrap",
              fontSize: 12.5,
              fontWeight: 500,
              color: "var(--fg-muted)",
              padding: "6px 11px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--surface)",
              textDecoration: "none",
            }}
          >
            {s.label}
          </a>
        ))}
      </div>
    </nav>
  );
}

/** Unified public footer. */
function PubFooter({ note }: { note: ReactNode }) {
  return (
    <footer className="pub-footer">
      <div className="pf-line">{note}</div>
      <div className="pf-bar">
        <div className="pf-brand">
          <div
            className="side-logo"
            style={{ width: 22, height: 22, fontSize: 11 }}
            aria-hidden="true"
          >
            A
          </div>
          <span>ADCS · Aspose Context Service</span>
        </div>
        <nav className="pf-nav" aria-label="Footer">
          <a href="/status">Status</a>
          <a href="/integrations">Integrations</a>
          <a href="/">Console</a>
          <span className="pf-dim">Docs</span>
        </nav>
      </div>
      <div className="pf-fine">© 2026 Aspose · Documentation Context Service</div>
    </footer>
  );
}
