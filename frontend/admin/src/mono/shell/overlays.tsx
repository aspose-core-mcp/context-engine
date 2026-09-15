"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName } from "../lib/types";

// ─────────────────────────────────────────────────────────── Toast ──────────

interface ToastState {
  id: number;
  message: string;
  undo?: () => void;
}

interface ToastApi {
  /** Show a success toast; with `undo`, shows an Undo button and extends to 5.2s. */
  toast: (message: string, undo?: () => void) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const v = useContext(ToastCtx);
  if (!v) throw new Error("useToast must be used within OverlayProvider");
  return v;
}

// ───────────────────────────────────────────────────────── Confirm ──────────

export interface ConfirmConfig {
  title: string;
  body?: ReactNode;
  /** Mono summary block (`.sum`). */
  summary?: ReactNode;
  /** Typed-word gate (e.g. "ROLLBACK") — confirm enabled only on exact match. */
  word?: string;
  /** `danger` (red, irreversible) | `amber` (reversible, high-consequence). */
  tone?: "danger" | "amber";
  confirmLabel?: string;
  icon?: IconName;
  /** Optional success toast shown after confirm. */
  successToast?: string;
  onConfirm: () => void;
}

interface ConfirmApi {
  confirm: (config: ConfirmConfig) => void;
}

const ConfirmCtx = createContext<ConfirmApi | null>(null);

export function useConfirm(): ConfirmApi {
  const v = useContext(ConfirmCtx);
  if (!v) throw new Error("useConfirm must be used within OverlayProvider");
  return v;
}

function trapFocus(e: KeyboardEvent, container: HTMLElement | null) {
  if (!container || e.key !== "Tab") return;
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

function ConfirmModal({
  config,
  onClose,
  onToast,
}: {
  config: ConfirmConfig;
  onClose: () => void;
  onToast: (message: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // Trim before comparing so a trailing space doesn't fail the gate.
  const gateOk = !config.word || typed.trim() === config.word;
  const tone = config.tone ?? "danger";

  useEffect(() => {
    const target = config.word ? inputRef.current : confirmRef.current;
    target?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      else if (e.key === "Tab") trapFocus(e, modalRef.current);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [config, onClose]);

  function doConfirm() {
    if (!gateOk) return;
    config.onConfirm();
    if (config.successToast) onToast(config.successToast);
    onClose();
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cf-title"
        ref={modalRef}
      >
        <div className="modal-head">
          <div
            className="mi"
            style={tone === "amber" ? { background: "var(--warn-bg)", color: "var(--warn)" } : undefined}
          >
            <Icon name={config.icon ?? "alert"} />
          </div>
          <div className="modal-title" id="cf-title">
            {config.title}
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          {config.body != null && <div>{config.body}</div>}
          {config.summary != null && <div className="sum">{config.summary}</div>}
          {config.word && (
            <div className="modal-field">
              <label htmlFor="cf-word" id="cf-word-label">
                Type {config.word} to confirm
              </label>
              <input
                id="cf-word"
                ref={inputRef}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={config.word}
                aria-labelledby="cf-word-label"
                aria-describedby="cf-word-hint"
                autoComplete="off"
                spellCheck={false}
              />
              <div className="confirm-hint" id="cf-word-hint">
                Exact match required. This protects against accidental{" "}
                {config.title.toLowerCase()}.
              </div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            ref={confirmRef}
            className={cn("btn", tone === "amber" ? "btn-amber" : "btn-danger")}
            disabled={!gateOk}
            onClick={doConfirm}
          >
            {config.confirmLabel ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────── Provider ──────────

let toastSeq = 0;

export function OverlayProvider({ children }: { children: ReactNode }) {
  const [activeToast, setActiveToast] = useState<ToastState | null>(null);
  const [confirmConfig, setConfirmConfig] = useState<ConfirmConfig | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const toast = useCallback((message: string, undo?: () => void) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const id = ++toastSeq;
    setActiveToast({ id, message, undo });
    timerRef.current = setTimeout(
      () => setActiveToast((t) => (t && t.id === id ? null : t)),
      undo ? 5200 : 3200,
    );
  }, []);

  const confirm = useCallback((config: ConfirmConfig) => setConfirmConfig(config), []);

  return (
    <ToastCtx.Provider value={{ toast }}>
      <ConfirmCtx.Provider value={{ confirm }}>
        {children}
        {confirmConfig && (
          <ConfirmModal
            config={confirmConfig}
            onClose={() => setConfirmConfig(null)}
            onToast={toast}
          />
        )}
        {activeToast && (
          <div className="modal-toast" role="status" aria-live="polite">
            <Icon name="check" />
            <span>{activeToast.message}</span>
            {activeToast.undo && (
              <button
                type="button"
                className="toast-undo"
                onClick={() => {
                  activeToast.undo?.();
                  setActiveToast(null);
                }}
              >
                Undo
              </button>
            )}
          </div>
        )}
      </ConfirmCtx.Provider>
    </ToastCtx.Provider>
  );
}
