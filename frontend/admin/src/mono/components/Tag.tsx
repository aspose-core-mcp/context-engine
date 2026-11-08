import type { ReactNode } from "react";

/** Mono identifier chip — repo ids, codes, versions, enum `reason=…` values. Never raw JSON dumps. */
export function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}
