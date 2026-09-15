"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type CSSProperties,
  type PropsWithChildren,
} from "react";

// ---------------------------------------------------------------------------
// Data-layer toast used by the data hooks (`showToast`). Renders a token-driven
// "Mono" toast; the console shell has its own toast in src/mono/shell/overlays.tsx.
// ---------------------------------------------------------------------------

export type ToastSeverity = "success" | "info" | "warning" | "error";

type ToastEntry = {
  id: number;
  message: string;
  severity: ToastSeverity;
};

type ToastContextValue = {
  showToast: (message: string, severity?: ToastSeverity) => void;
};

const ToastContext = createContext<ToastContextValue>({
  showToast: () => {
    /* noop default */
  },
});

let nextToastId = 0;

const SEVERITY_TOKEN: Record<ToastSeverity, string> = {
  success: "ok",
  info: "info",
  warning: "warn",
  error: "crit",
};

export function ToastProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);

  const showToast = useCallback((message: string, severity: ToastSeverity = "success") => {
    const id = ++nextToastId;
    setToasts((prev) => [...prev, { id, message, severity }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toasts.length > 0 && (
        <div
          style={{
            position: "fixed",
            bottom: 16,
            right: 16,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            zIndex: 1000,
          }}
        >
          {toasts.map((t) => {
            const style: CSSProperties = {
              background: "var(--surface)",
              color: "var(--fg)",
              border: "1px solid var(--border)",
              borderLeft: `3px solid var(--${SEVERITY_TOKEN[t.severity]})`,
              borderRadius: "var(--radius)",
              boxShadow: "var(--shadow-md)",
              padding: "10px 14px",
              fontFamily: "var(--font-sans)",
              fontSize: "12.5px",
              fontWeight: 500,
              maxWidth: 360,
            };
            return (
              <div key={t.id} role="status" aria-live="polite" style={style}>
                {t.message}
              </div>
            );
          })}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}
