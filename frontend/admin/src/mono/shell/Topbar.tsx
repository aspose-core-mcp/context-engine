"use client";

import { useEffect, useState, type FormEvent, type RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getAdminErrorMessage } from "@/components/admin-console.utils";
import { loginAdminSession, logoutAdminSession } from "@/lib/admin-api";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import { SECTION_BY_KEY, ZONE_OF } from "../lib/nav";
import type { StatusVariant } from "../lib/types";
import { Pill } from "../components/Pill";
import { useShell, type SystemStatus } from "./context";
import { useAdminData } from "./data";
import { useToast } from "./overlays";
import { PopoverPanel, usePopover } from "./Popover";
import { usePrefs } from "./prefs";

const STATUS_VARIANT: Record<SystemStatus, StatusVariant> = {
  operational: "ok",
  degraded: "warn",
  // Partial maps to the crit palette.
  partial: "crit",
  major: "crit",
};

const STATUS_LABEL: Record<SystemStatus, string> = {
  operational: "Operational",
  degraded: "Degraded",
  partial: "Partial outage",
  major: "Major outage",
};

/** Per-state incident/maintenance summary line for the popover foot. */
const STATUS_FOOT: Record<SystemStatus, string> = {
  operational: "No active incidents · no maintenance windows",
  degraded: "1 degraded dependency · investigating",
  partial: "Retrieval API impaired · incident sev2 open",
  major: "Multiple services down · incident sev1 open",
};

const STATUS_STEPS: SystemStatus[] = ["operational", "degraded", "partial", "major"];

/** Aggregate-state switcher labels (OK / Degraded / Partial / Major). */
const STATUS_STEP_LABEL: Record<SystemStatus, string> = {
  operational: "OK",
  degraded: "Degraded",
  partial: "Partial",
  major: "Major",
};

/**
 * Dependency components for the status popover, in display order. The
 * per-state recolor maps a single state to the affected components: degraded →
 * Qdrant only; partial → first two; major → first four; all others stay ready.
 * Index positions are load-bearing.
 */
const COMPONENTS: string[] = [
  "Control Plane",
  "Retrieval API",
  "MCP Endpoint",
  "Ingestion Runtime",
  "Qdrant",
  "OpenSearch",
  "PostgreSQL",
  "Redis",
];

/**
 * Resolve a component's pill for the current aggregate state by index:
 * degraded recolors only Qdrant (index 4); partial the first two; major the
 * first four; the rest stay ready.
 */
function componentPill(index: number, status: SystemStatus): { variant: StatusVariant; label: string } {
  if (status === "degraded" && index === 4) return { variant: "warn", label: "degraded" };
  if (status === "partial" && index < 2) return { variant: "crit", label: "impaired" };
  if (status === "major" && index < 4) return { variant: "crit", label: "down" };
  return { variant: "ok", label: "ready" };
}

/** Offline-preview scope fixture for the user popover — shown until a real session loads. */
const SCOPES = [
  "read:analytics",
  "read:logs",
  "read:events",
  "write:settings",
  "write:ingestion",
  "write:destructive",
];

/** Title-cased role label for the role popover head (`.pt`), e.g. "product-owner" → "Product Owner". */
function roleTitle(role: string): string {
  return role
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

/** Avatar initials for the user chip, derived from the session role. */
function roleAbbr(role: string): string {
  switch (role) {
    case "superuser":
      return "SU";
    case "operator":
      return "OP";
    case "product-owner":
      return "PO";
    case "viewer":
      return "VW";
    default:
      return role.slice(0, 2).toUpperCase() || "SU";
  }
}

/**
 * Keep an open `.pop` panel inside the viewport. CSS right-aligns the panel
 * under its trigger (top = trigger bottom + 8px); this applies a `left ≥ 8px`
 * clamp as a translateX shift, re-evaluated on resize and panel-content changes.
 */
function useViewportClamp(open: boolean, wrapRef: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (!open) return;
    const panel = wrapRef.current?.querySelector<HTMLElement>(".pop");
    if (!panel) return;
    const clamp = () => {
      panel.style.transform = "";
      const r = panel.getBoundingClientRect();
      let shift = 0;
      const maxRight = window.innerWidth - 8;
      if (r.right > maxRight) shift -= r.right - maxRight;
      if (r.left + shift < 8) shift += 8 - (r.left + shift);
      if (shift !== 0) panel.style.transform = `translateX(${shift}px)`;
    };
    clamp();
    const ro = new ResizeObserver(clamp);
    ro.observe(panel);
    window.addEventListener("resize", clamp);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", clamp);
    };
  }, [open, wrapRef]);
}

export function Topbar({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const { section, status, setStatus, openPalette } = useShell();
  const {
    t,
    theme,
    toggleTheme,
    density,
    setDensity,
    guidance,
    setGuidance,
    locale,
    setLocale,
  } = usePrefs();
  const data = useAdminData();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const statusPop = usePopover();
  const userPop = usePopover();
  useViewportClamp(statusPop.open, statusPop.wrapRef);
  useViewportClamp(userPop.open, userPop.wrapRef);

  const [loginKey, setLoginKey] = useState("");
  const [authPending, setAuthPending] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  const session = data.session;

  async function submitLogin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const key = loginKey.trim();
    if (!key || authPending) return;
    setAuthPending(true);
    setLoginError(null);
    try {
      await loginAdminSession(key, true);
      setLoginKey("");
      // Refetch the shared cookie-session query so the whole console flips live.
      await queryClient.invalidateQueries({ queryKey: ["admin-session"] });
      toast("Signed in");
    } catch (error: unknown) {
      const message = getAdminErrorMessage(error, "Failed to sign in.");
      setLoginError(message);
      toast(message);
    } finally {
      setAuthPending(false);
    }
  }

  async function handleLogout() {
    if (authPending) return;
    setAuthPending(true);
    try {
      await logoutAdminSession();
    } catch {
      // Best-effort logout (mirrors useAdminSession.handleLogout): clear local
      // session state even when the network call fails.
    }
    queryClient.clear();
    setAuthPending(false);
    toast("Signed out");
  }

  const zone = ZONE_OF[section];
  const title = t(`nav.${section}`, SECTION_BY_KEY[section].label);
  const statusVariant = STATUS_VARIANT[status];
  // The chip text tracks the current state in every locale. The RU seed only
  // translates the Operational label; the other states fall through to their
  // English label (there are no RU strings for Degraded/Partial/Major).
  const statusChipLabel =
    status === "operational" ? t("tb.operational", STATUS_LABEL[status]) : STATUS_LABEL[status];

  return (
    <header className="topbar">
      <button
        className="icon-btn drawer-btn"
        aria-label="Open navigation"
        onClick={onOpenDrawer}
      >
        <Icon name="list" />
      </button>

      <nav className="crumbs" aria-label="Breadcrumb">
        <span className="crumb-zone">{t(`zone.${zone.label}`, zone.label)}</span>
        <span className="sep">/</span>
        <span className="cur">{title}</span>
      </nav>

      <div className="pop-wrap" ref={statusPop.wrapRef}>
        <button
          className={cn("status-chip", statusVariant)}
          aria-label={`System status: ${STATUS_LABEL[status]}`}
          aria-haspopup="menu"
          aria-expanded={statusPop.open}
          onClick={statusPop.toggle}
        >
          <span className="dot" />
          <span className="sc-label">{statusChipLabel}</span>
        </button>
        {statusPop.open && (
          <PopoverPanel>
            <div className="pop-head">
              <span className={cn("status-chip", statusVariant)} style={{ pointerEvents: "none" }}>
                <span className="dot" />
                {STATUS_LABEL[status]}
              </span>
              <span className="ps">auto-refresh 30s</span>
            </div>
            <div className="pop-body">
              {COMPONENTS.map((name, i) => {
                const { variant, label } = componentPill(i, status);
                return (
                  <div className="comp-chip" key={name}>
                    <span className="cn">{name}</span>
                    <span className="cs">
                      <Pill variant={variant}>{label}</Pill>
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="pop-foot">
              {STATUS_FOOT[status]}
              <div className="seg" role="group" aria-label="Status state" style={{ marginTop: 9 }}>
                {STATUS_STEPS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={s === status ? "on" : undefined}
                    onClick={() => setStatus(s)}
                  >
                    {STATUS_STEP_LABEL[s]}
                  </button>
                ))}
              </div>
            </div>
          </PopoverPanel>
        )}
      </div>

      <div className="topbar-spacer" />

      <button className="cmdk" aria-label="Open command palette" onClick={openPalette}>
        <Icon name="search" />
        <span className="cmdk-ph">{t("tb.search", "Search…")}</span>
        <span className="kbd">⌘K</span>
      </button>

      <div className="toggle-group" data-toggle="density" title="Information density">
        <button
          className={cn("toggle", density === "compact" && "on")}
          aria-pressed={density === "compact"}
          onClick={() => setDensity("compact")}
        >
          {t("tb.compact", "Compact")}
        </button>
        <button
          className={cn("toggle", density === "comfortable" && "on")}
          aria-pressed={density === "comfortable"}
          onClick={() => setDensity("comfortable")}
        >
          {t("tb.comfortable", "Comfortable")}
        </button>
      </div>

      <div className="toggle-group" data-toggle="guidance" title="Contextual guidance">
        <button
          className={cn("toggle", guidance && "on")}
          aria-pressed={guidance}
          onClick={() => setGuidance(true)}
        >
          {t("tb.guidance", "Guidance")}
        </button>
        <button
          className={cn("toggle", !guidance && "on")}
          aria-pressed={!guidance}
          onClick={() => setGuidance(false)}
        >
          {t("tb.off", "Off")}
        </button>
      </div>

      <button
        className="locale-btn"
        aria-label="Toggle language"
        onClick={() => {
          const prev = locale;
          const next = prev === "en" ? "ru" : "en";
          setLocale(next);
          // Bilingual confirmation with Undo restoring the prior locale.
          toast(
            next === "ru"
              ? "Язык: Русский — локализация расширяется поэтапно"
              : "Language set to English",
            () => setLocale(prev),
          );
        }}
      >
        <span className="dot" />
        <span>{locale.toUpperCase()}</span>
      </button>

      <button
        className="icon-btn"
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        onClick={toggleTheme}
      >
        <Icon name={theme === "dark" ? "moon" : "sun"} />
      </button>

      <div className="pop-wrap" ref={userPop.wrapRef}>
        <button
          className="user-chip"
          aria-label="Role and access"
          aria-haspopup="menu"
          aria-expanded={userPop.open}
          onClick={userPop.toggle}
        >
          <span className="uc-avatar">{session ? roleAbbr(session.effective_role) : "SU"}</span>
        </button>
        {userPop.open && (
          <PopoverPanel>
            <div className="pop-head">
              <span className="user-chip" style={{ pointerEvents: "none" }}>
                <span className="uc-avatar">{session ? roleAbbr(session.effective_role) : "SU"}</span>
              </span>
              <span className="pt">{session ? roleTitle(session.effective_role) : "Superuser"}</span>
              <span className="ps">
                {session
                  ? session.product_scopes.length
                    ? `${session.product_scopes.length} product scope${
                        session.product_scopes.length === 1 ? "" : "s"
                      }`
                    : "all products"
                  : data.sessionIsLoading
                    ? "checking session…"
                    : "all products"}
              </span>
            </div>
            <div className="pop-body">
              {!session && !data.sessionIsLoading && (
                <>
                  <div className="pop-row">
                    <span className="nm">Role</span>
                    <span className="vv">
                      <Pill variant="info">superuser</Pill>
                    </span>
                  </div>
                  <div className="pop-row">
                    <span className="nm">Default scope</span>
                    <span className="vv">
                      <span className="tag">aspose.ocr</span>
                    </span>
                  </div>
                </>
              )}
              {session && (
                <>
                  <div className="pop-row">
                    <span className="nm">Key</span>
                    <span className="vv">
                      <span className="tag">{session.key_id}</span>
                    </span>
                  </div>
                  <div className="pop-row">
                    <span className="nm">Source</span>
                    <span className="vv">
                      <span className="tag">{session.source}</span>
                    </span>
                  </div>
                  {session.owner_email && (
                    <div className="pop-row">
                      <span className="nm">Owner</span>
                      <span className="vv">
                        <span className="tag">{session.owner_email}</span>
                      </span>
                    </div>
                  )}
                  {session.product_scopes.length > 0 && (
                    <>
                      <div className="pop-sub">Product scopes</div>
                      <div className="pop-scopes">
                        {session.product_scopes.map((p) => (
                          <span className="tag" key={p}>
                            {p}
                          </span>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
              <div className="pop-sub">Granted scopes</div>
              {session && session.scopes.length === 0 ? (
                <div className="muted-note">
                  No explicit scopes — access follows the {session.effective_role} role.
                </div>
              ) : (
                <div className="pop-scopes">
                  {(session ? session.scopes : SCOPES).map((s) => (
                    <span className="tag" key={s}>
                      {s}
                    </span>
                  ))}
                </div>
              )}
              {!session && !data.sessionIsLoading && (
                <>
                  <div className="pop-sub">Sign in</div>
                  <form
                    onSubmit={submitLogin}
                    aria-label="Sign in with an admin API key"
                    style={{ display: "flex", gap: 8, marginTop: 2 }}
                  >
                    <input
                      className="inputctl"
                      type="password"
                      value={loginKey}
                      onChange={(e) => setLoginKey(e.target.value)}
                      placeholder="Admin API key"
                      aria-label="Admin API key"
                      autoComplete="off"
                      spellCheck={false}
                      style={{ flex: 1, minWidth: 0 }}
                    />
                    <button
                      type="submit"
                      className="btn btn-primary"
                      disabled={authPending}
                      style={{ flex: "none" }}
                    >
                      {authPending ? "Signing in…" : "Sign in"}
                    </button>
                  </form>
                  {loginError && (
                    <div className="crit-row" role="alert" style={{ marginTop: 8, marginBottom: 0 }}>
                      <Icon name="alert" className="ico" />
                      <span>{loginError}</span>
                    </div>
                  )}
                </>
              )}
            </div>
            <div className="pop-foot">
              {!session || session.is_superuser
                ? "Superuser bypasses scope gating · all sections accessible"
                : "Scope-gated sections follow the granted scopes"}
              {session && (
                <div style={{ marginTop: 9 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={handleLogout}
                    disabled={authPending}
                  >
                    {authPending ? "Signing out…" : "Sign out"}
                  </button>
                </div>
              )}
            </div>
          </PopoverPanel>
        )}
      </div>

      <a
        className="icon-btn"
        href="/status"
        title="Public status & integrations"
        style={{ textDecoration: "none" }}
      >
        <Icon name="globe" />
      </a>
    </header>
  );
}
