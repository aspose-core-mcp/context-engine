"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { ErrorState, Skeleton } from "@/mono/components/states";
import { cn } from "@/mono/lib/cn";
import { Icon } from "@/mono/lib/icons";
import type { StatusVariant } from "@/mono/lib/types";
import { fetchPublicUseCaseGallery, type PublicUseCaseGallery } from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Guided Integration Journeys
 *
 * Step-by-step integration journeys for the MCP adoption lifecycle. Driven by
 * the public Use-Case Gallery (fetchPublicUseCaseGallery → /v1/integrations/
 * use-cases), which carries `recommended_journey_id`, `starter_prompt`,
 * `starter_query`, `evidence`, `actions` and `status` per scenario. Each gallery
 * item is projected into a journey card with a step-by-step plan.
 *
 * Live success      -> journeys derived from gallery items.
 * Live success EMPTY -> in-file JOURNEY_FIXTURES (designed offline dataset).
 * Live ERROR         -> in-file JOURNEY_FIXTURES + a non-blocking error banner with retry.
 * Offline/disabled   -> in-file JOURNEY_FIXTURES so the section is fully reviewable.
 * -------------------------------------------------------------------------- */

const GALLERY_PRODUCT = "aspose.ocr";
const GALLERY_LANGUAGE = "net";

interface JourneyStep {
  title: string;
  detail: string;
  section_label: string;
  section_href: string;
}

type JourneyStatus = "ready" | "watch" | "blocked" | "prep";

interface Journey {
  journey_id: string;
  title: string;
  tagline: string;
  status: JourneyStatus;
  summary: string;
  evidence: string[];
  starter_prompt: string;
  starter_query: string;
  share_url: string;
  steps: JourneyStep[];
}

/** Status → Mono pill variant (closed palette). */
const STATUS_VARIANT: Record<JourneyStatus, StatusVariant> = {
  ready: "ok",
  watch: "warn",
  blocked: "crit",
  prep: "info",
};

const STATUS_LABEL: Record<JourneyStatus, string> = {
  ready: "ready",
  watch: "watch",
  blocked: "blocked",
  prep: "prep",
};

/** Fixtures — the four canonical MCP-adoption journeys (offline dataset). */
const JOURNEY_FIXTURES: Journey[] = [
  {
    journey_id: "first-cited-answer",
    title: "First cited answer",
    tagline:
      "Connect a client, validate readiness, and get a grounded quickstart before asking for code.",
    status: "ready",
    summary: "This scope is ready for a clean MCP-first quickstart.",
    evidence: ["self-test=ready", "ready_services=2/2", "starter_queries=3", "freshness=fresh"],
    starter_prompt:
      "Using the Aspose.OCR MCP server, recognize text from an image in C# and cite the exact API signature you use.",
    starter_query: "how to recognize text from an image in C#",
    share_url: "/integrations?journey_id=first-cited-answer",
    steps: [
      {
        title: "Run the MCP connection self-test",
        detail:
          "Confirm the selected product, SDK language, and transport are actually MCP-ready before opening the IDE.",
        section_label: "Open self-test",
        section_href: "#self-test",
      },
      {
        title: "Copy the client starter pack",
        detail:
          "Use the generated client-specific config and first queries instead of writing MCP JSON manually.",
        section_label: "Open starter packs",
        section_href: "#starter-packs",
      },
      {
        title: "Apply the strict quickstart recipe",
        detail:
          "Seed the public playground with a cited quickstart prompt so the model validates symbols before codegen.",
        section_label: "Open prompt cookbook",
        section_href: "#prompt-cookbook",
      },
      {
        title: "Verify the answer in the public playground",
        detail:
          "Run the MCP-grounded query and only then move the prompt into Cursor, Qwen, Claude, or VS Code.",
        section_label: "Open playground",
        section_href: "#public-playground",
      },
    ],
  },
  {
    journey_id: "release-safe-rollout",
    title: "Release-safe rollout",
    tagline: "Ground new code in the newest visible release evidence before upgrading.",
    status: "watch",
    summary: "Inspect freshness and release cues before generating production code.",
    evidence: ["latest=25.1", "freshness=monitor", "release_features=4"],
    starter_prompt:
      "List the breaking changes between Aspose.OCR 24.12 and 25.1, then write upgrade-safe C# that cites the new signatures.",
    starter_query: "breaking changes between Aspose.OCR 24.12 and 25.1",
    share_url: "/integrations?journey_id=release-safe-rollout",
    steps: [
      {
        title: "Check whether the target surface is already MCP-ready",
        detail:
          "Use the public coverage tracker first so release work does not start on a missing or partial surface.",
        section_label: "Open coverage tracker",
        section_href: "#coverage-gap-tracker",
      },
      {
        title: "Apply the release-safe codegen recipe",
        detail:
          "Force the playground prompt to cite latest features, exact signatures, and explicit fallback warnings.",
        section_label: "Open prompt cookbook",
        section_href: "#prompt-cookbook",
      },
      {
        title: "Validate the answer against the upgrade assistant",
        detail:
          "Compare the quickstart against the upgrade path before you ship changes into a real repository.",
        section_label: "Open upgrade assistant",
        section_href: "#upgrade-assistant",
      },
    ],
  },
  {
    journey_id: "zero-result-recovery",
    title: "Zero-result recovery",
    tagline:
      "Turn weak or empty answers into a clear diagnosis before changing code, prompts, or content.",
    status: "prep",
    summary:
      "Use the troubleshooting recipe to separate content gaps, freshness drift, and low-confidence retrieval.",
    evidence: ["triage_critical=0", "triage_warning=1", "query_warnings=0", "quality=0.82"],
    starter_prompt:
      "My Aspose.OCR query for table recognition returned no results. Diagnose whether this is a content gap, a freshness gap, or low-confidence retrieval before suggesting code.",
    starter_query: "recognize a table layout from a scanned PDF",
    share_url: "/integrations?journey_id=zero-result-recovery",
    steps: [
      {
        title: "Inspect content triage and freshness cues",
        detail:
          "Check whether the scope is missing content, lagging on freshness, or only partially indexed.",
        section_label: "Open content triage",
        section_href: "#content-triage",
      },
      {
        title: "Apply the zero-result troubleshooting recipe",
        detail:
          "Use a diagnosis-first prompt instead of asking for code again with the same weak grounding.",
        section_label: "Open prompt cookbook",
        section_href: "#prompt-cookbook",
      },
      {
        title: "Capture a repro pack for the failing request",
        detail: "Share the exact public request context if you need Product Owner or support help.",
        section_label: "Open playground",
        section_href: "#public-playground",
      },
    ],
  },
  {
    journey_id: "support-handoff",
    title: "Support-ready handoff",
    tagline:
      "Package the current public MCP investigation into a compact, evidence-backed handoff.",
    status: "prep",
    summary:
      "Run at least one public query first so the handoff contains a concrete request_id and citations.",
    evidence: ["request_id=none", "repro_pack=not-loaded", "feedback=none", "issue_type=missing"],
    starter_prompt:
      "Summarize this Aspose.OCR investigation for a support handoff: include the request_id, the citations, the root cause, and the next operator step.",
    starter_query: "summarize OCR recognition accuracy options",
    share_url: "/integrations?journey_id=support-handoff",
    steps: [
      {
        title: "Run the public query that should be handed off",
        detail:
          "Make sure the final handoff references a real request, not only a hypothetical scenario.",
        section_label: "Open playground",
        section_href: "#public-playground",
      },
      {
        title: "Apply the support handoff recipe",
        detail:
          "Generate a compact summary with citations, root cause framing, and the next operator step.",
        section_label: "Open prompt cookbook",
        section_href: "#prompt-cookbook",
      },
      {
        title: "Export the current workspace or repro context",
        detail:
          "Preserve the MCP scope and starter prompts so another engineer can reproduce the same public view.",
        section_label: "Open workspace packs",
        section_href: "#workspace-presets",
      },
      {
        title: "Escalate with a clean issue if content is actually missing",
        detail: "Only after the public evidence is coherent should you file the docs/content issue.",
        section_label: "Open content triage",
        section_href: "#content-triage",
      },
    ],
  },
];

/** Map gallery item.status text → journey status (closed set). */
function galleryStatus(raw: string): JourneyStatus {
  const value = raw.toLowerCase();
  if (value.includes("ready") || value.includes("active") || value.includes("ga")) return "ready";
  if (value.includes("block") || value.includes("missing") || value.includes("critical"))
    return "blocked";
  if (value.includes("watch") || value.includes("partial") || value.includes("warn"))
    return "watch";
  return "prep";
}

/** Project the live Use-Case Gallery into journey cards (one per use case). */
function journeysFromGallery(data: PublicUseCaseGallery): Journey[] {
  return data.items.map((item) => {
    const status = galleryStatus(item.status);
    return {
      journey_id: item.recommended_journey_id ?? item.use_case_id,
      title: item.title,
      tagline: item.summary,
      status,
      summary: item.summary,
      evidence: [
        `category=${item.category}`,
        `status=${item.status}`,
        `evidence=${item.evidence.length}`,
      ],
      starter_prompt: item.starter_prompt,
      starter_query: item.starter_query,
      share_url: `/integrations?use_case_id=${encodeURIComponent(item.use_case_id)}`,
      steps: item.evidence.length
        ? item.evidence.map((ev) => ({
            title: ev.title,
            detail: `${ev.evidence_type} · ${ev.section_anchor || "section"}`,
            section_label: "Open citation",
            section_href: ev.canonical_url || "#",
          }))
        : item.actions.map((action) => ({
            title: action.label,
            detail: "Continue the journey in the linked section.",
            section_label: action.label,
            section_href: action.href,
          })),
    };
  });
}

export default function GuidedJourneys() {
  const galleryQuery = useQuery({
    queryKey: ["public-use-case-gallery", GALLERY_PRODUCT, GALLERY_LANGUAGE],
    queryFn: () =>
      fetchPublicUseCaseGallery({
        product_id: GALLERY_PRODUCT,
        programming_language: GALLERY_LANGUAGE,
      }),
  });

  // Display source: live gallery (if any items) else fixtures — fixtures always win offline.
  const liveJourneys = galleryQuery.data ? journeysFromGallery(galleryQuery.data) : [];
  const journeys = liveJourneys.length ? liveJourneys : JOURNEY_FIXTURES;

  const [activeId, setActiveId] = useState<string>(journeys[0]?.journey_id ?? "");
  // Keep the active selection valid when the source flips between live/fixtures.
  useEffect(() => {
    if (!journeys.some((j) => j.journey_id === activeId) && journeys[0]) {
      setActiveId(journeys[0].journey_id);
    }
  }, [journeys, activeId]);

  const active = useMemo(
    () => journeys.find((j) => j.journey_id === activeId) ?? journeys[0] ?? null,
    [journeys, activeId],
  );

  // Copy-to-clipboard with an aria-live confirmation keyed by intent.
  const [copied, setCopied] = useState<"prompt" | "share" | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copy = useCallback(async (text: string, intent: "prompt" | "share") => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopied(intent);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(null), 2000);
  }, []);
  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  // Gate on the DISPLAY set: fixtures (non-empty) guarantee the UI never collapses.
  const loading = galleryQuery.isLoading && !journeys.length;
  const errored = galleryQuery.isError && !journeys.length;
  const liveError = galleryQuery.isError && journeys.length > 0;

  return (
    <div className="pub t-mono">
      <section className="pub-card" aria-label="Guided integration journeys">
        <div className="pub-card-head">
          <span className="pub-card-title">Guided integration journeys</span>
          <span className="right muted-note">step-by-step MCP adoption</span>
        </div>

        <div style={{ padding: "16px 20px" }}>
          {liveError && (
            <Banner
              variant="warn"
              icon="alert"
              title="Showing reference journeys"
              text="Live use-case data is unavailable right now, so the canonical journeys are shown instead."
              actions={
                <Button size="sm" icon="refresh" onClick={() => galleryQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          )}

          {loading ? (
            <Skeleton rows={4} />
          ) : errored ? (
            <ErrorState
              title="Could not load guided journeys"
              text="The public use-case service did not respond."
              cause="use-case gallery endpoint unreachable"
              actions={
                <Button icon="refresh" onClick={() => galleryQuery.refetch()}>
                  Retry
                </Button>
              }
            />
          ) : active == null ? null : (
            <>
              {/* Journey selector — local UI state, switches the rendered plan. */}
              <div className="tabs" role="tablist" aria-label="Integration journeys">
                {journeys.map((j) => (
                  <button
                    key={j.journey_id}
                    type="button"
                    role="tab"
                    aria-selected={j.journey_id === active.journey_id}
                    className={cn("tab", j.journey_id === active.journey_id && "on")}
                    onClick={() => setActiveId(j.journey_id)}
                  >
                    {j.title}
                  </button>
                ))}
              </div>

              <Banner
                variant={active.status === "ready" ? "ok" : active.status === "blocked" ? "warn" : "info"}
                icon={active.status === "ready" ? "check" : "info"}
                title={active.title}
                text={active.summary}
              />

              <div className="intro-grid" style={{ marginTop: 14 }}>
                {/* Left: tagline + evidence + actions */}
                <div className="pub-card" style={{ margin: 0, padding: 18 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                    <Pill variant={STATUS_VARIANT[active.status]}>{STATUS_LABEL[active.status]}</Pill>
                    <Tag>{active.journey_id}</Tag>
                  </div>
                  <div className="st-body" style={{ marginBottom: 12 }}>
                    {active.tagline}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
                    {active.evidence.map((ev) => (
                      <Tag key={ev}>{ev}</Tag>
                    ))}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    <Button
                      variant="btn-primary"
                      icon="play"
                      onClick={() => copy(active.starter_prompt, "prompt")}
                    >
                      {copied === "prompt" ? "Prompt copied" : "Apply journey prompt"}
                    </Button>
                    <Button icon="arrow" onClick={() => copy(active.share_url, "share")}>
                      {copied === "share" ? "Link copied" : "Copy share link"}
                    </Button>
                  </div>
                  <div className="muted-note" style={{ marginTop: 10 }}>
                    Starter query: <span className="mono">{active.starter_query}</span>
                  </div>
                  <span style={SR_ONLY} role="status" aria-live="polite">
                    {copied === "prompt"
                      ? "Journey prompt copied to clipboard"
                      : copied === "share"
                        ? "Share link copied to clipboard"
                        : ""}
                  </span>
                </div>

                {/* Right: step-by-step plan */}
                <div className="pub-card" style={{ margin: 0, padding: 18 }}>
                  <div className="pub-card-title" style={{ fontSize: 14, marginBottom: 14 }}>
                    Step-by-step plan
                  </div>
                  <ol className="step-list">
                    {active.steps.map((step, i) => (
                      <li className="step-card" key={`${step.title}-${i}`}>
                        <div className="sn" aria-hidden="true" />
                        <div>
                          <div className="st-title">{step.title}</div>
                          <div className="st-body">{step.detail}</div>
                          <a
                            href={step.section_href}
                            className="muted-note"
                            style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 6 }}
                          >
                            {step.section_label}
                            <Icon name="arrow" />
                          </a>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/** Visually-hidden style for screen-reader-only live regions (kit has no .sr-only). */
const SR_ONLY = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
} as const;
