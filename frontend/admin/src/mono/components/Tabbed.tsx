"use client";

import { useState, type ReactNode } from "react";

import { cn } from "../lib/cn";

export interface TabbedProps {
  tabs: string[];
  /** One panel per tab; only the active panel is rendered visible. */
  panels: ReactNode[];
  initial?: number;
  /** Notified when the active tab changes. */
  onChange?: (index: number) => void;
}

/** Underline tabs + real panel switching. */
export function Tabbed({ tabs, panels, initial = 0, onChange }: TabbedProps) {
  const [active, setActive] = useState(initial);
  function select(i: number) {
    setActive(i);
    onChange?.(i);
  }
  return (
    <div className="tabwrap">
      <div className="tabs" role="tablist">
        {tabs.map((label, i) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={i === active}
            className={cn("tab", i === active && "on")}
            onClick={() => select(i)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="tabpanels">
        {panels.map((panel, i) => (
          <div key={i} className="tabpanel" role="tabpanel" hidden={i !== active}>
            {panel}
          </div>
        ))}
      </div>
    </div>
  );
}

export interface TabsProps {
  tabs: string[];
  active: number;
  onChange: (index: number) => void;
}

/** Just the underline tab bar (controlled), when panels live elsewhere. */
export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((label, i) => (
        <button
          key={label}
          type="button"
          role="tab"
          aria-selected={i === active}
          className={cn("tab", i === active && "on")}
          onClick={() => onChange(i)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
