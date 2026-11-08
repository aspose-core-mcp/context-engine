"use client";

import {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

// ---------------------------------------------------------------------------
// Locale types — reuse HowToLocale shape
// ---------------------------------------------------------------------------

export type AppLocale = "en" | "ru";

export type L10nText = Record<AppLocale, string>;
export type L10nLines = Record<AppLocale, string[]>;

/** Shorthand for creating localized text pairs. */
export function l(en: string, ru: string): L10nText {
  return { en, ru };
}

/** Shorthand for creating localized line arrays. */
export function ll(en: string[], ru: string[]): L10nLines {
  return { en, ru };
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

type LocaleContextValue = {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
  /** Resolve a localized text object to a string for the current locale. */
  t: (text: L10nText) => string;
  /** Resolve a localized lines object to string[] for the current locale. */
  tl: (lines: L10nLines) => string[];
  /** Resolve a plain string OR an L10nText (backward compat for gradual migration). */
  ts: (text: string | L10nText) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const LOCALE_STORAGE_KEY = "adcs-admin-locale";

function getInitialLocale(): AppLocale {
  if (typeof window === "undefined") return "en";
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (stored === "ru") return "ru";
  return "en";
}

export function LocaleProvider({ children }: PropsWithChildren) {
  const [locale, setLocaleRaw] = useState<AppLocale>(getInitialLocale);

  const setLocale = useCallback((next: AppLocale) => {
    setLocaleRaw(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    }
  }, []);

  const t = useCallback((text: L10nText) => text[locale], [locale]);
  const tl = useCallback((lines: L10nLines) => lines[locale], [locale]);
  const ts = useCallback(
    (text: string | L10nText) => (typeof text === "string" ? text : text[locale]),
    [locale],
  );

  const value = useMemo<LocaleContextValue>(
    () => ({ locale, setLocale, t, tl, ts }),
    [locale, setLocale, t, tl, ts],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) {
    throw new Error("useLocale must be used within a LocaleProvider");
  }
  return ctx;
}
