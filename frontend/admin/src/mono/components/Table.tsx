"use client";

import { useState, type ReactNode } from "react";

import { cn } from "../lib/cn";

/** Table wrapper card (`.tablecard`) — gives the bordered, rounded, sticky-header frame. */
export function TableCard({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("tablecard", className)}>{children}</div>;
}

/** The table element (`.tbl`) — compose `<thead>`/`<tbody>` with `.num` on numeric columns. */
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <table className={cn("tbl", className)}>{children}</table>;
}

export interface ExpandableRowProps {
  /** Cells of the summary row (the `<td>`s, typically ending in a chevron). */
  summary: ReactNode;
  /** Content of the expandable detail panel (`.exp-panel`). */
  detail: ReactNode;
  /** Column count for the detail row's spanning cell. */
  colSpan: number;
  defaultOpen?: boolean;
  className?: string;
}

/** A clickable summary row + a collapsible detail row (`.exp-toggle` / `.exp-row`). */
export function ExpandableRow({
  summary,
  detail,
  colSpan,
  defaultOpen = false,
  className,
}: ExpandableRowProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <tr
        className={cn("data", "exp-toggle", open && "open", className)}        onClick={() => setOpen((o) => !o)}
      >
        {summary}
      </tr>
      <tr className="exp-row" hidden={!open}>
        <td colSpan={colSpan}>
          <div className="exp-panel">{detail}</div>
        </td>
      </tr>
    </>
  );
}

export interface TableGroupProps {
  /** Group header content (chevron + product name + dir + meta). */
  header: ReactNode;
  /** The group's data rows (`<tr>`s) — hidden when collapsed. */
  children: ReactNode;
  colSpan: number;
  defaultOpen?: boolean;
}

/** Collapsible product-cluster group (`.grp-row` header + its rows). */
export function TableGroup({ header, children, colSpan, defaultOpen = true }: TableGroupProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <tr
        className={cn("grp-row", !open && "collapsed")}        onClick={() => setOpen((o) => !o)}
      >
        <td colSpan={colSpan}>
          <div className="grp-head">{header}</div>
        </td>
      </tr>
      {open && children}
    </>
  );
}

export interface ShowMoreRowProps {
  /** The hidden `<tr>`s revealed on click. */
  extra: ReactNode;
  count: number;
  colSpan: number;
}

/** "+N more" pagination row that reveals the extra rows in place. */
export function ShowMoreRow({ extra, count, colSpan }: ShowMoreRowProps) {
  const [shown, setShown] = useState(false);
  if (shown) return <>{extra}</>;
  return (
    <tr className="more-row">
      <td colSpan={colSpan}>
        <button type="button" className="more-wrap" onClick={() => setShown(true)}>
          +{count} more
        </button>
      </td>
    </tr>
  );
}
