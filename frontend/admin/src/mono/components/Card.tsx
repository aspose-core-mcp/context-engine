import type { ReactNode } from "react";

import { cn } from "../lib/cn";

export interface CardProps {
  title?: ReactNode;
  sub?: ReactNode;
  /** Right-aligned header content (filters, buttons). */
  right?: ReactNode;
  /** Remove body padding for full-bleed tables/lists. */
  flush?: boolean;
  children: ReactNode;
}

/** Standard content container: `.card` › `.card-head` › `.card-body[.flush]`. */
export function Card({ title, sub, right, flush, children }: CardProps) {
  const hasHead = title != null || sub != null || right != null;
  return (
    <section className="card">
      {hasHead && (
        <div className="card-head">
          <div>
            {title != null && <div className="card-title">{title}</div>}
            {sub != null && <div className="card-sub">{sub}</div>}
          </div>
          {right != null && <div className="card-right">{right}</div>}
        </div>
      )}
      <div className={cn("card-body", flush && "flush")}>{children}</div>
    </section>
  );
}
