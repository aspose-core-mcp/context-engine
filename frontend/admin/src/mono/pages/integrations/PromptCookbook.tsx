"use client";

import { useMemo, useState } from "react";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { EmptyState } from "@/mono/components/states";
import { Pill } from "@/mono/components/Pill";
import { Tag } from "@/mono/components/Tag";
import { Icon } from "@/mono/lib/icons";

/* ----------------------------------------------------------------------------
 * Prompt Cookbook — section component for /integrations.
 *
 * Curated reusable prompts (quickstart · release · migration · troubleshooting ·
 * symbol · support). Goal filter; recipe cards with title, goal pill, summary,
 * checklist accordion, prompt code block, Apply + Copy.
 *
 * API limitation: there is NO public fetchPublic* function for prompt recipes in
 * src/lib/admin-api.ts (no fetchPublicPromptCookbook / recipes endpoint exists —
 * unlike snippets / freshness / use-cases which have dedicated fetchers), so this
 * section is driven entirely by the in-file RECIPE_FIXTURES below. When a public
 * recipes endpoint is added to admin-api.ts, wire a useQuery over it with
 * `live.length ? live : RECIPE_FIXTURES` exactly as the other integration
 * sections do; the fixtures then become the offline dataset and no other change
 * is needed.
 *
 * Mono styling: `.pub-card` + `.code-card` + Mono <Pill>/<Tag> + tokens.
 * No new colors/fonts, no raw-JSON-in-UI.
 * -------------------------------------------------------------------------- */

type RecipeGoal =
  | "quickstart"
  | "release"
  | "migration"
  | "troubleshooting"
  | "symbol"
  | "support";

interface Recipe {
  recipe_id: string;
  title: string;
  goal: RecipeGoal;
  summary: string;
  checklist: string[];
  prompt: string;
}

const GOAL_OPTS: { value: "all" | RecipeGoal; label: string }[] = [
  { value: "all", label: "All goals" },
  { value: "quickstart", label: "Quickstart" },
  { value: "release", label: "Latest release" },
  { value: "migration", label: "Migration" },
  { value: "troubleshooting", label: "Troubleshooting" },
  { value: "symbol", label: "Symbol lookup" },
  { value: "support", label: "Support handoff" },
];

function goalVariant(goal: RecipeGoal) {
  if (goal === "quickstart" || goal === "symbol") return "ok" as const;
  if (goal === "migration" || goal === "troubleshooting") return "warn" as const;
  return "info" as const;
}

/* ---------------- in-file fixtures (no public endpoint) -------------------- */

const RECIPE_FIXTURES: Recipe[] = [
  {
    recipe_id: "quickstart-recognize",
    title: "Quickstart: recognize text with Aspose.OCR",
    goal: "quickstart",
    summary:
      "Ask the assistant to write a first working recognition snippet grounded in current API signatures.",
    checklist: [
      "Name the product_id (aspose.ocr) and SDK language explicitly.",
      "Request a citation so the answer is anchored to canonical docs.",
      "Ask for the latest-stable version unless you need a pinned release.",
    ],
    prompt:
      "Using Aspose.OCR for .NET (latest-stable), write a minimal program that recognizes text from a single PNG image and prints the result. Use only current API signatures and cite the API reference for each call.",
  },
  {
    recipe_id: "release-latest-features",
    title: "What changed in the latest release",
    goal: "release",
    summary:
      "Summarize new features and behavior changes for a product so you can plan an upgrade.",
    checklist: [
      "Specify the product and language.",
      "Ask for new features AND behavior changes, not just additions.",
      "Request canonical_url citations for each item.",
    ],
    prompt:
      "List the new features and notable behavior changes in the latest release of Aspose.OCR for .NET. Group them as 'new', 'changed', and 'deprecated', and cite the release notes URL for each entry.",
  },
  {
    recipe_id: "migration-breaking-changes",
    title: "Plan a safe version migration",
    goal: "migration",
    summary:
      "Build an upgrade plan that highlights breaking changes and the exact call-site edits required.",
    checklist: [
      "Provide both the from-version and to-version.",
      "Ask for breaking changes with migration hints.",
      "Request a step-by-step checklist you can paste into a ticket.",
    ],
    prompt:
      "I am upgrading Aspose.OCR for .NET from 24.6 to 25.1. List every breaking change with its migration hint and a code-level before/after, then produce an ordered migration checklist. Cite the breaking-changes reference for each item.",
  },
  {
    recipe_id: "troubleshooting-zero-results",
    title: "Diagnose a zero-result query",
    goal: "troubleshooting",
    summary:
      "Turn a customer 'I got nothing back' complaint into a reproducible diagnosis with a request_id.",
    checklist: [
      "Include the failing query verbatim and the request_id if you have one.",
      "Ask whether the gap is coverage (no index data) or retrieval (poor ranking).",
      "Request the next action: file a triage issue or escalate to search relevance.",
    ],
    prompt:
      "A query for 'table recognition' against Aspose.OCR (.NET) returns no results (request_id req_abc123). Determine whether this is a coverage gap or a retrieval-quality issue, explain the evidence, and recommend the next action with a link to the relevant section.",
  },
  {
    recipe_id: "symbol-exact-signature",
    title: "Look up an exact API symbol",
    goal: "symbol",
    summary:
      "Get the authoritative signature, parameters, and a usage example for one API member.",
    checklist: [
      "Give the fully-qualified symbol name.",
      "Ask for parameters, return type, and one runnable example.",
      "Request the citation so you can verify against the reference.",
    ],
    prompt:
      "Show the exact signature, parameter list, return type, and a runnable example for Aspose.OCR.AsposeOcr.Recognize in the .NET SDK (latest-stable). Cite the API reference page.",
  },
  {
    recipe_id: "support-handoff",
    title: "Hand a content gap to the docs team",
    goal: "support",
    summary:
      "Produce a concise, reproducible bug report a documentation owner can act on cold.",
    checklist: [
      "Include product, language, version, and the request_id.",
      "State the expected vs actual content.",
      "Suggest the specific page or symbol that needs updating.",
    ],
    prompt:
      "Draft a documentation issue report: Aspose.OCR (.NET, 24.12) is missing a how-to for recognizing text from TIFF images (request_id req_def456). Describe the expected content, the gap, and the canonical page that should host it.",
  },
];

/* ---------------- visually-hidden label helper ----------------------------- */

const SR_ONLY: React.CSSProperties = {
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

/* -------------------------------------------------------------------------- */

export default function PromptCookbook() {
  const [goal, setGoal] = useState<"all" | RecipeGoal>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);

  const shown = useMemo(
    () => RECIPE_FIXTURES.filter((r) => goal === "all" || r.goal === goal),
    [goal],
  );

  const copyPrompt = async (recipe: Recipe) => {
    try {
      await navigator.clipboard.writeText(recipe.prompt);
    } catch {
      /* clipboard may be blocked — still surface the confirmation */
    }
    setCopiedId(recipe.recipe_id);
    window.setTimeout(() => {
      setCopiedId((prev) => (prev === recipe.recipe_id ? null : prev));
    }, 2000);
  };

  const applyRecipe = (recipe: Recipe) => {
    // Apply = surface the prompt for the operator to lift into the playground.
    // (No server mutation; this is the "Apply [recipe]" affordance.)
    setAppliedId(recipe.recipe_id);
    setOpenId(recipe.recipe_id);
    window.setTimeout(() => {
      setAppliedId((prev) => (prev === recipe.recipe_id ? null : prev));
    }, 2500);
  };

  return (
    <section className="pub-card" id="prompt-cookbook" aria-label="Prompt cookbook">
      <div className="pub-card-head">
        <span className="pub-card-title">Prompt cookbook</span>
        <span className="right" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label htmlFor="cookbook-goal" style={SR_ONLY}>
            Cookbook goal
          </label>
          <select
            id="cookbook-goal"
            className="selectctl"
            style={{ height: 28, minWidth: 160 }}
            value={goal}
            onChange={(e) => setGoal(e.target.value as "all" | RecipeGoal)}
            aria-label="Cookbook goal"
          >
            {GOAL_OPTS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </span>
      </div>

      <div style={{ padding: "12px 20px 0" }}>
        <Banner
          variant="info"
          icon="book"
          guidance
          title="Curated, copy-ready prompts for grounded MCP answers."
          text={`${shown.length} recipe${shown.length === 1 ? "" : "s"}${goal !== "all" ? ` · ${goal}` : ""}. Copy a prompt, or Apply to expand its checklist for the playground.`}
        />
      </div>

      <div style={{ padding: "8px 20px 16px" }} aria-live="polite">
        {shown.length === 0 ? (
          <EmptyState
            title="No recipes match the selected goal"
            text="Try a different goal or browse all recipes."
            action={
              <Button variant="btn-ghost" size="sm" icon="refresh" onClick={() => setGoal("all")}>
                Show all recipes
              </Button>
            }
          />
        ) : (
          shown.map((recipe) => {
            const open = openId === recipe.recipe_id;
            const copied = copiedId === recipe.recipe_id;
            const applied = appliedId === recipe.recipe_id;
            return (
              <div
                key={recipe.recipe_id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  padding: 16,
                  marginTop: 12,
                  background: "var(--surface)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    marginBottom: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span className="svc-name">{recipe.title}</span>
                  <Pill variant={goalVariant(recipe.goal)}>{recipe.goal}</Pill>
                  {applied ? (
                    <span className="muted-note" style={{ marginLeft: "auto", color: "var(--accent-line)" }}>
                      Applied — checklist expanded
                    </span>
                  ) : null}
                </div>
                <div className="svc-desc" style={{ marginBottom: 10 }}>
                  {recipe.summary}
                </div>

                {/* checklist accordion */}
                <button
                  type="button"
                  className="pub-cta ghost"
                  style={{ height: 28, fontSize: 12, padding: "0 12px" }}
                  onClick={() => setOpenId(open ? null : recipe.recipe_id)}
                  aria-expanded={open}
                  aria-controls={`checklist-${recipe.recipe_id}`}
                >
                  <Icon name={open ? "chevron" : "chevronR"} />
                  {open ? "Hide checklist" : "Show checklist"}
                </button>

                {open ? (
                  <ul
                    id={`checklist-${recipe.recipe_id}`}
                    className="muted-note"
                    style={{ margin: "10px 0 0", paddingLeft: 16, lineHeight: 1.7 }}
                  >
                    {recipe.checklist.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ul>
                ) : null}

                {/* prompt code card */}
                <div className="code-card" style={{ marginTop: 12 }}>
                  <div className="code-head">
                    <span className="dot3" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                    <span className="fname">{recipe.recipe_id}.prompt</span>
                    <button
                      type="button"
                      className="copy"
                      onClick={() => void copyPrompt(recipe)}
                      aria-label={`Copy the ${recipe.title} prompt to clipboard`}
                    >
                      {copied ? "Copied" : "Copy prompt"}
                    </button>
                  </div>
                  <pre className="code-body" tabIndex={0} style={{ whiteSpace: "pre-wrap" }}>
                    {recipe.prompt}
                  </pre>
                  <span style={SR_ONLY} role="status" aria-live="polite">
                    {copied ? `${recipe.title} prompt copied to clipboard` : ""}
                  </span>
                </div>

                <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                  <button
                    type="button"
                    className="pub-cta"
                    style={{ height: 30, fontSize: 12.5 }}
                    onClick={() => applyRecipe(recipe)}
                  >
                    Apply recipe <Icon name="arrow" />
                  </button>
                  <button
                    type="button"
                    className="pub-cta ghost"
                    style={{ height: 30, fontSize: 12.5 }}
                    onClick={() => void copyPrompt(recipe)}
                  >
                    {copied ? "Copied" : "Copy prompt"}
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
