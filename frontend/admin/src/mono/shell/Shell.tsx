"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { DEFAULT_SECTION, isSectionKey, WORKSPACE_LAUNCHERS } from "../lib/nav";
import type { IconName, SectionKey } from "../lib/types";
import { renderSection } from "../sections/registry";
import { CommandPalette, type PaletteCommand } from "./CommandPalette";
import {
  isSystemStatus,
  ShellContext,
  type SectionIntent,
  type ShellContextValue,
  type SystemStatus,
} from "./context";
import { AdminDataProvider } from "./data";
import { OverlayProvider, useToast } from "./overlays";
import { PrefsProvider, usePrefs } from "./prefs";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** ⌘K deep-action jumps — navigate + toast the action name. */
const ACTION_JUMPS: { id: string; section: SectionKey; icon: IconName; label: string; aliases: string[] }[] = [
  { id: "act:validate", section: "ingestion", icon: "play", label: "Run Validate-Only ingestion", aliases: ["validate"] },
  { id: "act:rollback", section: "snapshots", icon: "camera", label: "Jump: Snapshot rollback", aliases: ["rollback"] },
  { id: "act:onboard", section: "ingestion", icon: "upload", label: "Onboard a new product", aliases: ["onboard"] },
  { id: "act:newkey", section: "apikeys", icon: "key", label: "Create API key", aliases: ["newkey"] },
  { id: "act:zr", section: "analytics", icon: "bars", label: "Open zero-result cockpit", aliases: ["zr"] },
  { id: "act:qa", section: "quality", icon: "review", label: "Run semantic quality review", aliases: ["qa"] },
  { id: "act:cfg", section: "config", icon: "history", label: "Rollback a config change", aliases: ["cfg"] },
  { id: "act:sql", section: "sql", icon: "database", label: "New SQL query", aliases: ["sql"] },
];

/** ⌘K How-To command set. */
const HOWTO_JUMPS: { id: string; section: SectionKey; label: string }[] = [
  { id: "howto:coverage", section: "coverage", label: "How-To: Diagnose coverage gaps" },
  { id: "howto:rollback", section: "snapshots", label: "How-To: Publish & rollback safely" },
  { id: "howto:onboard", section: "ingestion", label: "How-To: Onboard a documentation source" },
];

function ShellInner() {
  const prefs = usePrefs();
  const { toast } = useToast();
  const [section, setSection] = useState<SectionKey>(DEFAULT_SECTION);
  // Start from the operational default for SSR/hydration parity; the demo state
  // is hydrated from localStorage (`adcs_sysstate`) post-mount.
  const [status, setStatusState] = useState<SystemStatus>("operational");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Persist the simulated system state so it survives reload.
  useEffect(() => {
    try {
      const saved = localStorage.getItem("adcs_sysstate");
      if (saved && isSystemStatus(saved)) setStatusState(saved);
    } catch {
      /* localStorage unavailable — keep the operational default */
    }
  }, []);

  const setStatus = useCallback((next: SystemStatus) => {
    setStatusState(next);
    try {
      localStorage.setItem("adcs_sysstate", next);
    } catch {
      /* ignore */
    }
  }, []);

  /** The `.content` scroll container — section switches reset it to the top. */
  const mainRef = useRef<HTMLElement | null>(null);
  /** Marks a hash write made by navigate(), so the hashchange listener skips its own scroll reset. */
  const selfNavRef = useRef(false);
  /** One-shot cross-section prefill payloads, keyed by target section, drained by consumeIntent. */
  const intentRef = useRef<Partial<Record<SectionKey, SectionIntent>>>({});

  // Hash-persisted section routing; first load defaults to Health.
  useEffect(() => {
    function apply() {
      const h = window.location.hash.replace(/^#/, "");
      if (!isSectionKey(h)) return;
      setSection(h);
      // navigate() handles its own scroll behavior (top reset or anchor focus);
      // reset here only for external hash changes (back/forward, manual edits).
      if (selfNavRef.current) {
        selfNavRef.current = false;
        return;
      }
      requestAnimationFrame(() => {
        if (mainRef.current) mainRef.current.scrollTop = 0;
      });
    }
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  const navigate = useCallback((key: SectionKey, anchor?: string, intent?: SectionIntent) => {
    // Stash the prefill BEFORE switching, so the target section can drain it on mount.
    if (intent) intentRef.current[key] = intent;
    setSection(key);
    setDrawerOpen(false);
    if (window.location.hash !== `#${key}`) {
      selfNavRef.current = true;
      window.location.hash = key;
    }
    // Deep-link: the target section mounts on the next render, so defer the
    // scroll/focus to the next paint, with a short timeout fallback in case
    // the node lands a frame later (lazy panels, data-driven content).
    const focusAnchor = () => {
      if (!anchor) return true;
      const el = document.getElementById(anchor);
      if (!el) return false;
      el.scrollIntoView({ block: "start", behavior: "smooth" });
      el.tabIndex = -1;
      el.focus({ preventScroll: true });
      return true;
    };
    requestAnimationFrame(() => {
      if (anchor) {
        if (!focusAnchor()) window.setTimeout(focusAnchor, 120);
        return;
      }
      // Every section switch lands at the top.
      if (mainRef.current) mainRef.current.scrollTop = 0;
    });
  }, []);

  const consumeIntent = useCallback((key: SectionKey): SectionIntent | null => {
    const intent = intentRef.current[key];
    if (!intent) return null;
    // One-shot: drop it so the prefill applies exactly once per navigate.
    delete intentRef.current[key];
    return intent;
  }, []);

  const openPalette = useCallback(() => setPaletteOpen(true), []);

  // ⌘/Ctrl+K toggles the palette from anywhere.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const ctx = useMemo<ShellContextValue>(
    () => ({ section, navigate, consumeIntent, openPalette, status, setStatus }),
    [section, navigate, consumeIntent, openPalette, status],
  );

  const paletteCommands = useMemo<PaletteCommand[]>(
    () => [
      // Actions: deep-action jumps into a section + confirmation toast with the
      // action name.
      ...ACTION_JUMPS.map((a) => ({
        id: a.id,
        group: "Action" as const,
        label: a.label,
        icon: a.icon,
        aliases: a.aliases,
        run: () => {
          navigate(a.section);
          toast(a.label);
        },
      })),
      {
        id: "act:theme",
        group: "Action",
        label: prefs.theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        icon: prefs.theme === "dark" ? "sun" : "moon",
        aliases: ["theme", "dark", "light"],
        run: prefs.toggleTheme,
      },
      {
        id: "act:density",
        group: "Action",
        label: prefs.density === "compact" ? "Comfortable density" : "Compact density",
        icon: "sliders",
        aliases: ["density", "compact", "comfortable"],
        run: () => prefs.setDensity(prefs.density === "compact" ? "comfortable" : "compact"),
      },
      {
        id: "act:public",
        group: "Action",
        label: "Public status & integrations",
        icon: "globe",
        aliases: ["public", "status", "integrations"],
        run: () => {
          window.location.href = "/status";
        },
      },
      // Global ⌘K workspace launch: one command per curated template. Searching
      // the palette surfaces + launches workspace templates, deep-linking to
      // the relevant section/panel anchor.
      ...WORKSPACE_LAUNCHERS.map((l) => ({
        id: `ws:${l.id}`,
        group: "Workspace" as const,
        label: `Launch: ${l.title}`,
        icon: "play" as const,
        aliases: [l.id, "workspace", "launch"],
        run: () => {
          navigate(l.section, l.anchor);
          // Non-Section commands confirm with a toast.
          toast(`Launch: ${l.title}`);
        },
      })),
      // How-To set: jump to the related console section.
      ...HOWTO_JUMPS.map((h) => ({
        id: h.id,
        group: "How-To" as const,
        label: h.label,
        icon: "book" as const,
        aliases: [],
        run: () => {
          navigate(h.section);
          toast(h.label);
        },
      })),
    ],
    [prefs, navigate, toast],
  );

  return (
    <ShellContext.Provider value={ctx}>
      <AdminDataProvider>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <div className={cn("adcs-app", drawerOpen && "drawer-open")}>
          <Sidebar onNavigated={() => setDrawerOpen(false)} />
          <Topbar onOpenDrawer={() => setDrawerOpen(true)} />
          <main className="content" id="main-content" role="main" tabIndex={-1} ref={mainRef}>
            {renderSection(section)}
          </main>
          {drawerOpen && (
            <button
              type="button"
              className="drawer-scrim"
              aria-label="Close navigation"
              onClick={() => setDrawerOpen(false)}
            />
          )}
        </div>
        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          onNavigate={navigate}
          commands={paletteCommands}
        />
      </AdminDataProvider>
    </ShellContext.Provider>
  );
}

/** Themed `.adcs` root — wraps the overlays too, so toasts/modals inherit the Mono tokens. */
function ShellRoot({ children }: { children: ReactNode }) {
  const prefs = usePrefs();
  return <div className={prefs.rootClassName}>{children}</div>;
}

/** Root of the admin console. Mount at `app/page.tsx`. */
export function MonoConsole() {
  return (
    <PrefsProvider>
      <ShellRoot>
        <OverlayProvider>
          <ShellInner />
        </OverlayProvider>
      </ShellRoot>
    </PrefsProvider>
  );
}
