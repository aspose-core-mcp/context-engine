import type { ReactNode } from "react";

import { Icon } from "../lib/icons";
import { Banner } from "./Banner";

/** Centered empty state with orb + copy + optional action. */
export function EmptyState({
  title,
  text,
  action,
}: {
  title: ReactNode;
  text: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-orb" />
      <div className="empty-title">{title}</div>
      <div className="empty-text">{text}</div>
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

const SK_WIDTHS = [58, 72, 46, 64, 52];

/** Shimmer skeleton (role=status). */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-live="polite" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div className="sk-row" key={i}>
          <span className="sk-bar" style={{ width: `${SK_WIDTHS[i % SK_WIDTHS.length]}%` }} />
        </div>
      ))}
    </div>
  );
}

/** Recovery alert (role=alert) with a likely-cause line + recovery buttons. */
export function ErrorState({
  title = "Something went wrong",
  text,
  cause,
  actions,
}: {
  title?: ReactNode;
  text?: ReactNode;
  cause?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="recovery" role="alert">
      <div className="rec-ico">
        <Icon name="alert" />
      </div>
      <div className="rec-body">
        <div className="rec-title">{title}</div>
        {text != null && <div className="rec-text">{text}</div>}
        {cause != null && <div className="rec-cause">Likely cause: {cause}</div>}
        {actions && <div className="rec-actions">{actions}</div>}
      </div>
    </div>
  );
}

/** "stale · 45d" amber chip. */
export function StaleBadge({ children = "stale" }: { children?: ReactNode }) {
  return (
    <span className="stale-badge" title="Data may be out of date">
      <Icon name="clock" className="ico" />
      {children}
    </span>
  );
}

/** Lock + "needs `write:…` scope" recovery block. */
export function PermissionDenied({ scope, extra }: { scope: ReactNode; extra?: ReactNode }) {
  return (
    <div className="recovery warn" role="alert">
      <div className="rec-ico">
        <Icon name="lock" />
      </div>
      <div className="rec-body">
        <div className="rec-title">Permission required</div>
        <div className="rec-text">
          This action needs the <b>{scope}</b> scope.{" "}
          {extra ?? "Request elevated access from an administrator."}
        </div>
      </div>
    </div>
  );
}

/** DB read-only warning banner. */
export function ReadonlyBanner() {
  return (
    <Banner
      variant="warn"
      icon="alert"
      title="Database is in read-only mode"
      text="All mutations (create / update / delete / rollback) are temporarily disabled. Read-only views still work."
    />
  );
}
