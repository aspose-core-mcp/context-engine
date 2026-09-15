import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName } from "../lib/types";

export interface BannerProps {
  title: ReactNode;
  text?: ReactNode;
  variant?: "ok" | "warn" | "info";
  /** Icon key, or `false` to omit the icon tile. Defaults to `info`. */
  icon?: IconName | false;
  actions?: ReactNode;
  /** Tag as contextual guidance so the topbar Guidance toggle can hide it. */
  guidance?: boolean;
}

/**
 * The "one banner instead of per-row prose" pattern. Hoist shared context here;
 * never repeat instructional prose per table row.
 */
export function Banner({ title, text, variant, icon, actions, guidance }: BannerProps) {
  return (
    <div className={cn("banner", variant)} {...(guidance ? { "data-guidance": "" } : {})}>
      {icon !== false && (
        <div className="b-ico">
          <Icon name={icon || "info"} />
        </div>
      )}
      <div className="b-body">
        <div className="b-title">{title}</div>
        {text != null && <div className="b-text">{text}</div>}
      </div>
      {actions && <div className="b-actions">{actions}</div>}
    </div>
  );
}
