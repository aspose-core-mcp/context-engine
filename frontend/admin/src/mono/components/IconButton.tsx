import type { ButtonHTMLAttributes } from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName } from "../lib/types";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
}

/** 30×30 square ghost button for a lone icon (topbar controls, row actions). */
export function IconButton({ icon, className, type = "button", ...rest }: IconButtonProps) {
  return (
    <button type={type} className={cn("icon-btn", className)} {...rest}>
      <Icon name={icon} className="ico" />
    </button>
  );
}
