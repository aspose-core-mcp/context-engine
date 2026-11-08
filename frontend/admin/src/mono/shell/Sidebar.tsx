"use client";

import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import { NAV } from "../lib/nav";
import { useShell } from "./context";
import { usePrefs } from "./prefs";

/** Primary navigation: brand + 3 zone groups × items (lock/badge/active rail). */
export function Sidebar({ onNavigated }: { onNavigated?: () => void }) {
  const { section, navigate } = useShell();
  const { t } = usePrefs();

  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="side-brand">
        <div className="side-logo">A</div>
        <div>
          <div className="side-brand-name">ADCS</div>
          <div className="side-brand-sub">Admin console</div>
        </div>
      </div>
      <div className="side-scroll">
        {NAV.map((zone) => (
          <div className="side-group" key={zone.id}>
            <div className="side-group-label">{t(`zone.${zone.label}`, zone.label)}</div>
            {zone.items.map((item) => {
              const active = item.key === section;
              return (
                <a
                  key={item.key}
                  className={cn("side-item", item.locked && "locked", active && "active")}
                  href={`#${item.key}`}
                  data-nav={item.key}
                  aria-current={active ? "page" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(item.key);
                    onNavigated?.();
                  }}
                >
                  <Icon name={item.icon} />
                  <span>{t(`nav.${item.key}`, item.label)}</span>
                  {item.badge && <span className="badge">{item.badge}</span>}
                  {item.locked && <Icon name="lock" className="lock" />}
                </a>
              );
            })}
          </div>
        ))}
      </div>
    </aside>
  );
}
