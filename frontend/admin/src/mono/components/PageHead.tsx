import type { ReactNode } from "react";

import { IconButton } from "./IconButton";

export interface PageHeadProps {
  title: ReactNode;
  sub?: ReactNode;
  /** Right-aligned actions (scope chips, buttons). */
  actions?: ReactNode;
  /** Mandatory help (book) icon — every section header has one. */
  onHelp?: () => void;
}

export function PageHead({ title, sub, actions, onHelp }: PageHeadProps) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub != null && <p className="page-sub">{sub}</p>}
      </div>
      <div className="page-head-actions">
        {actions}
        {onHelp && (
          <IconButton
            icon="book"
            onClick={onHelp}
            title="How-To for this section"
            aria-label="Open How-To for this section"
          />
        )}
      </div>
    </div>
  );
}
