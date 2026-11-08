import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import type { StatusVariant } from "../lib/types";

export interface PillProps {
  variant: StatusVariant;
  children: ReactNode;
}

/** Status pill — closed palette (ok/warn/crit/info/neutral). Dot is mandatory (color not sole indicator). */
export function Pill({ variant, children }: PillProps) {
  return (
    <span className={cn("pill", variant)}>
      <span className="dot" />
      {children}
    </span>
  );
}
