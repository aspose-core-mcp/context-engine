"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { cn } from "../lib/cn";
import { translate } from "../lib/i18n";
import type { Density, Locale, ThemeMode } from "../lib/types";

interface PrefsState {
  theme: ThemeMode;
  density: Density;
  guidance: boolean;
  locale: Locale;
}

interface PrefsContextValue extends PrefsState {
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setDensity: (density: Density) => void;
  setGuidance: (on: boolean) => void;
  setLocale: (locale: Locale) => void;
  /** Localized lookup bound to the current locale. */
  t: (key: string, fallback: string) => string;
  /** Root class list to apply on the `.adcs` shell element. */
  rootClassName: string;
}

const DEFAULTS: PrefsState = {
  theme: "light",
  density: "comfortable",
  guidance: true,
  locale: "en",
};

const LS = {
  theme: "adcs_theme",
  density: "adcs_density",
  guidance: "adcs_guidance",
  locale: "adcs_locale",
} as const;

const PrefsCtx = createContext<PrefsContextValue | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  // Start from defaults for SSR/hydration parity; sync from localStorage post-mount.
  const [state, setState] = useState<PrefsState>(DEFAULTS);

  useEffect(() => {
    try {
      const theme = localStorage.getItem(LS.theme);
      const density = localStorage.getItem(LS.density);
      const guidance = localStorage.getItem(LS.guidance);
      const locale = localStorage.getItem(LS.locale);
      setState({
        theme: theme === "dark" ? "dark" : "light",
        density: density === "compact" ? "compact" : "comfortable",
        guidance: guidance == null ? DEFAULTS.guidance : guidance !== "off",
        locale: locale === "ru" ? "ru" : "en",
      });
    } catch {
      /* localStorage unavailable — keep defaults */
    }
  }, []);

  // Keep <html lang> in sync with the active locale so screen readers use the
  // right pronunciation in RU.
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = state.locale;
    }
  }, [state.locale]);

  const persist = useCallback((key: string, value: string) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* ignore */
    }
  }, []);

  const setTheme = useCallback(
    (theme: ThemeMode) => {
      setState((s) => ({ ...s, theme }));
      persist(LS.theme, theme);
    },
    [persist],
  );
  const toggleTheme = useCallback(() => {
    setState((s) => {
      const theme: ThemeMode = s.theme === "dark" ? "light" : "dark";
      persist(LS.theme, theme);
      return { ...s, theme };
    });
  }, [persist]);
  const setDensity = useCallback(
    (density: Density) => {
      setState((s) => ({ ...s, density }));
      persist(LS.density, density);
    },
    [persist],
  );
  const setGuidance = useCallback(
    (on: boolean) => {
      setState((s) => ({ ...s, guidance: on }));
      persist(LS.guidance, on ? "on" : "off");
    },
    [persist],
  );
  const setLocale = useCallback(
    (locale: Locale) => {
      setState((s) => ({ ...s, locale }));
      persist(LS.locale, locale);
    },
    [persist],
  );

  const t = useCallback(
    (key: string, fallback: string) => translate(state.locale, key, fallback),
    [state.locale],
  );

  const rootClassName = cn(
    "adcs",
    "t-mono",
    state.theme === "dark" && "theme-dark",
    state.density === "compact" && "density-compact",
    !state.guidance && "guidance-off",
  );

  const value = useMemo<PrefsContextValue>(
    () => ({
      ...state,
      setTheme,
      toggleTheme,
      setDensity,
      setGuidance,
      setLocale,
      t,
      rootClassName,
    }),
    [state, setTheme, toggleTheme, setDensity, setGuidance, setLocale, t, rootClassName],
  );

  return <PrefsCtx.Provider value={value}>{children}</PrefsCtx.Provider>;
}

export function usePrefs(): PrefsContextValue {
  const v = useContext(PrefsCtx);
  if (!v) throw new Error("usePrefs must be used within PrefsProvider");
  return v;
}

export function useT() {
  return usePrefs().t;
}
