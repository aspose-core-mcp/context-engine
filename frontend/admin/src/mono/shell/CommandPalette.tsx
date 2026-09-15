"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import { NAV } from "../lib/nav";
import type { IconName, SectionKey } from "../lib/types";

export interface PaletteCommand {
  id: string;
  group: "Workspace" | "Action" | "How-To";
  label: string;
  icon: IconName;
  aliases?: string[];
  run: () => void;
}

interface Entry {
  id: string;
  group: "Section" | "Workspace" | "Action" | "How-To";
  label: string;
  icon: IconName;
  aliases: string[];
  run: () => void;
}

/**
 * Section search aliases, covering all 17 sections. The empty-state hint advertises several of these
 * shorthands (e.g. 'zr'), so the set must stay complete.
 */
const ALIASES: Partial<Record<SectionKey, string[]>> = {
  workspaces: ["ws"],
  health: ["hp"],
  indexes: ["idx", "topology"],
  coverage: ["cov"],
  ingestion: ["gi", "ingest"],
  snapshots: ["snap", "rollback"],
  critical: ["incident", "sev"],
  runtime: ["guard", "mcp"],
  logs: ["trace", "loki"],
  analytics: ["zr", "metrics"],
  campaigns: ["camp"],
  sql: ["sql", "query"],
  retrieval: ["tune", "topk"],
  languages: ["lang", "alias"],
  apikeys: ["keys", "token"],
  config: ["cfg"],
  quality: ["qa", "review"],
};

function loadFreq(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem("adcs_pal_freq") ?? "{}") as Record<string, number>;
  } catch {
    return {};
  }
}
function bumpFreq(id: string) {
  try {
    const f = loadFreq();
    f[id] = (f[id] ?? 0) + 1;
    localStorage.setItem("adcs_pal_freq", JSON.stringify(f));
  } catch {
    /* ignore */
  }
}

/** alias-exact > alias-prefix > title-prefix > word-prefix > substring; 0 = no match. */
function score(query: string, e: Entry): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const label = e.label.toLowerCase();
  const aliases = e.aliases.map((a) => a.toLowerCase());
  if (aliases.includes(q)) return 100;
  if (aliases.some((a) => a.startsWith(q))) return 80;
  if (label.startsWith(q)) return 70;
  if (label.split(/\s+/).some((w) => w.startsWith(q))) return 55;
  if (label.includes(q)) return 40;
  if (aliases.some((a) => a.includes(q))) return 30;
  return 0;
}

/** Wrap Tab/Shift+Tab focus within `container`. */
function trapFocus(e: KeyboardEvent, container: HTMLElement | null) {
  if (!container) return;
  const focusable = container.querySelectorAll<HTMLElement>(
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

export function CommandPalette({
  open,
  onClose,
  onNavigate,
  commands = [],
}: {
  open: boolean;
  onClose: () => void;
  onNavigate: (key: SectionKey) => void;
  commands?: PaletteCommand[];
}) {
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const entries = useMemo<Entry[]>(() => {
    const sections: Entry[] = NAV.flatMap((z) =>
      z.items.map((it) => ({
        id: `section:${it.key}`,
        group: "Section" as const,
        label: it.label,
        icon: it.icon,
        // Shorthand first so the rendered .pi-alias chip (aliases[0]) surfaces the
        // primary quick-jump alias; the section key and zone label remain
        // searchable tokens.
        aliases: [...(ALIASES[it.key] ?? []), it.key, z.label],
        run: () => onNavigate(it.key),
      })),
    );
    const cmds: Entry[] = commands.map((c) => ({
      id: c.id,
      group: c.group,
      label: c.label,
      icon: c.icon,
      aliases: c.aliases ?? [],
      run: c.run,
    }));
    return [...sections, ...cmds];
  }, [onNavigate, commands]);

  const groups = useMemo(() => {
    const freq = loadFreq();
    if (!query.trim()) {
      // Empty query: ≤4 Recent, then the grouped rest,
      // with the whole initial list capped at 18 rows.
      const recent = [...entries]
        .filter((e) => freq[e.id])
        .sort((a, b) => freq[b.id] - freq[a.id])
        .slice(0, 4);
      const recentIds = new Set(recent.map((e) => e.id));
      const rest = (["Section", "Workspace", "Action", "How-To"] as const).flatMap((g) =>
        entries.filter((e) => e.group === g && !recentIds.has(e.id)),
      );
      const limited = [...recent, ...rest].slice(0, 18);
      const limitedIds = new Set(limited.map((e) => e.id));
      const out: { label: string; items: Entry[] }[] = [];
      const shownRecent = recent.filter((e) => limitedIds.has(e.id));
      if (shownRecent.length) out.push({ label: "Recent", items: shownRecent });
      for (const g of ["Section", "Workspace", "Action", "How-To"] as const) {
        const items = limited.filter((e) => e.group === g && !recentIds.has(e.id));
        if (items.length) out.push({ label: g === "Section" ? "Sections" : g, items });
      }
      return out;
    }
    const ranked = entries
      // Recency boost only applies to a positive base match, so frequently-used
      // commands never leak into unrelated queries.
      .map((e) => {
        const base = score(query, e);
        return { e, s: base > 0 ? base + (freq[e.id] ?? 0) * 0.5 : 0 };
      })
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 18)
      .map((x) => x.e);
    const byGroup: { label: string; items: Entry[] }[] = [];
    for (const g of ["Section", "Workspace", "Action", "How-To"] as const) {
      const items = ranked.filter((e) => e.group === g);
      if (items.length) byGroup.push({ label: g === "Section" ? "Sections" : g, items });
    }
    return byGroup;
  }, [query, entries]);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(0);
      const id = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
  }, [open]);

  useEffect(() => setSel(0), [query]);

  function choose(e: Entry) {
    bumpFreq(e.id);
    onClose();
    e.run();
  }

  // Document-level key handling so Escape always closes (even after Tab moves
  // focus) and a Tab focus trap on .cmdk-panel keeps the dialog modal.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Tab") {
        trapFocus(e, panelRef.current);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSel((s) => Math.min(s + 1, flat.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSel((s) => Math.max(s - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = flat[sel];
        if (item) choose(item);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // `choose` is stable enough for this handler; re-bind when the visible list
    // or selection changes so Enter/arrows act on current state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, flat, sel, onClose]);

  if (!open) return null;

  let runningIndex = -1;

  return (
    <div
      className="cmdk-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="cmdk-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        ref={panelRef}
      >
        <div className="cmdk-search">
          <Icon name="search" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sections…"
            aria-label="Search sections and actions"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="cmdk-results" role="listbox">
          {flat.length === 0 && (
            <div className="cmdk-empty">
              No matches for “{query}”. Try: health, gi, rollback, sql, zr
            </div>
          )}
          {groups.map((g) => (
            <Fragment key={g.label}>
              <div className="cmdk-grp">
                <div className="cmdk-grp-label">{g.label}</div>
              </div>
              {g.items.map((it) => {
                runningIndex += 1;
                const idx = runningIndex;
                const alias = it.aliases[0];
                return (
                  <button
                    type="button"
                    key={it.id}
                    role="option"
                    aria-selected={idx === sel}
                    className={cn("cmdk-item", idx === sel && "sel")}
                    onMouseMove={() => setSel(idx)}
                    onClick={() => choose(it)}
                  >
                    <Icon name={it.icon} />
                    <span>{it.label}</span>
                    {alias && <span className="pi-alias">{alias}</span>}
                  </button>
                );
              })}
            </Fragment>
          ))}
        </div>
        <div className="cmdk-foot">
          <span>
            <span className="kbd">↑</span>
            <span className="kbd">↓</span> navigate
          </span>
          <span>
            <span className="kbd">↵</span> open
          </span>
          <span>
            <span className="kbd">Esc</span> close
          </span>
        </div>
      </div>
    </div>
  );
}
