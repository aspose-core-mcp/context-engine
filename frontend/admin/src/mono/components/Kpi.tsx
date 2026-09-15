import type { CSSProperties, ReactNode } from "react";

import { cn } from "../lib/cn";
import type { StatusVariant } from "../lib/types";
import { Pill } from "./Pill";

export interface KpiProps {
  label: ReactNode;
  value: ReactNode;
  foot?: ReactNode;
  /** Adds the 3px accent left bar. */
  accent?: boolean;
  /** Optional status pill, top-right. */
  pill?: { variant: StatusVariant; text: ReactNode };
}

export function Kpi({ label, value, foot, accent, pill }: KpiProps) {
  return (
    <div className={cn("kpi", accent && "accent")}>
      {pill && (
        <span className="k-pill">
          <Pill variant={pill.variant}>{pill.text}</Pill>
        </span>
      )}
      <div className="k-label">{label}</div>
      <div className="k-value">{value}</div>
      {foot != null && <div className="k-foot">{foot}</div>}
    </div>
  );
}

export interface KpiRowProps {
  children: ReactNode;
  /** Fixed column count; defaults to the CSS grid (auto). */
  cols?: number;
}

export function KpiRow({ children, cols }: KpiRowProps) {
  const style: CSSProperties | undefined = cols
    ? { gridTemplateColumns: `repeat(${cols},1fr)` }
    : undefined;
  return (
    <div className="kpi-row" style={style}>
      {children}
    </div>
  );
}
