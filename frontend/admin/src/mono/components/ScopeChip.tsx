import type { ReactNode } from "react";

export interface ScopeChipProps {
  label: ReactNode;
  value: ReactNode;
  /** Optional leading accent dot. */
  dot?: boolean;
}

/** Context chip in page headers: "role superuser", "scope aspose.ocr". */
export function ScopeChip({ label, value, dot }: ScopeChipProps) {
  return (
    <span className="scope-chip">
      {dot && <span className="dot" />}
      {label} <b>{value}</b>
    </span>
  );
}
