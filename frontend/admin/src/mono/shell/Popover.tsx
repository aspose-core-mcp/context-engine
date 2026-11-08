"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";

/**
 * Single-anchor popover state: open/close with Escape + outside-click on the
 * wrapper (so clicking the trigger toggles without immediately re-closing).
 */
export function usePopover() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return {
    open,
    wrapRef,
    toggle: () => setOpen((o) => !o),
    close: () => setOpen(false),
  };
}

/** The anchored dropdown panel (`.pop`). Render inside a `position:relative` wrapper. */
export function PopoverPanel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("pop", className)} role="menu">
      {children}
    </div>
  );
}
