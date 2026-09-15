"use client";

import {
  useId,
  type CSSProperties,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "../lib/cn";

function widthStyle(width?: number): CSSProperties | undefined {
  return width ? { width } : undefined;
}

/** Uppercase field label. Associate with a control via `htmlFor`. */
export function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label className="flabel" htmlFor={htmlFor}>
      {children}
    </label>
  );
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode;
  width?: number;
  options: string[];
}

export function Select({ label, width, options, className, id, ...rest }: SelectProps) {
  const autoId = useId();
  const selectId = id ?? autoId;
  return (
    <div className="field" style={widthStyle(width)}>
      {label != null && <FieldLabel htmlFor={selectId}>{label}</FieldLabel>}
      <select id={selectId} className={cn("selectctl", className)} {...rest}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
  width?: number;
}

export function Input({ label, width, className, id, ...rest }: InputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <div className="field" style={widthStyle(width)}>
      {label != null && <FieldLabel htmlFor={inputId}>{label}</FieldLabel>}
      <input id={inputId} className={cn("inputctl", className)} autoComplete="off" {...rest} />
    </div>
  );
}

export interface SegmentedProps {
  options: string[];
  active: number;
  onChange?: (index: number) => void;
  ariaLabel?: string;
}

/** Connected segmented control; active segment = `--surface-2`/`--fg` in Mono. */
export function Segmented({ options, active, onChange, ariaLabel }: SegmentedProps) {
  return (
    <div className="seg" role="group" aria-label={ariaLabel}>
      {options.map((o, i) => (
        <button
          key={o}
          type="button"
          className={i === active ? "on" : undefined}
          aria-pressed={i === active}
          onClick={() => onChange?.(i)}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
