import type { ButtonHTMLAttributes } from "react";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { ButtonVariant, IconName } from "../lib/types";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Monochrome primary; danger=irreversible (red); amber=reversible-high-consequence (publish). */
  variant?: ButtonVariant;
  size?: "sm";
  icon?: IconName;
}

export function Button({
  variant = "btn-ghost",
  size,
  icon,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn("btn", variant, size === "sm" && "btn-sm", className)}
      {...rest}
    >
      {icon ? <Icon name={icon} className="ico" /> : null}
      {children}
    </button>
  );
}
