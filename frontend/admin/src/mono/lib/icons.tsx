import type { IconName } from "./types";

/**
 * Inline SVG icon set. 18×18 viewBox, currentColor stroke, 1.5 weight.
 * Each entry is the icon's inner SVG markup. Sizes by context come from CSS: 16px nav, 14px `.ico` in buttons, 13px `.chev`.
 */
const PATHS: Record<IconName, string> = {
  grid: '<rect x="2.5" y="2.5" width="5" height="5" rx="1"/><rect x="10.5" y="2.5" width="5" height="5" rx="1"/><rect x="2.5" y="10.5" width="5" height="5" rx="1"/><rect x="10.5" y="10.5" width="5" height="5" rx="1"/>',
  pulse: '<path d="M1.5 9h3l2-5 3 10 2-5h3"/>',
  shield: '<path d="M9 1.5 3 4v4.5C3 12 5.5 14.5 9 16c3.5-1.5 6-4 6-7.5V4z"/>',
  layers: '<path d="M9 2 2 5.5 9 9l7-3.5z"/><path d="M2 9.5 9 13l7-3.5"/>',
  book: '<path d="M3 3.5A1.5 1.5 0 0 1 4.5 2H15v12H4.5A1.5 1.5 0 0 0 3 15.5z"/><path d="M3 12.5h12"/>',
  upload: '<path d="M9 12V3"/><path d="m5.5 6.5 3.5-3.5 3.5 3.5"/><path d="M3 14h12"/>',
  camera: '<rect x="2" y="5" width="14" height="9.5" rx="1.5"/><circle cx="9" cy="9.7" r="2.6"/><path d="M6 5l1.2-2h3.6L12 5"/>',
  bell: '<path d="M5 7a4 4 0 0 1 8 0c0 4 1.5 5 1.5 5h-11S5 11 5 7z"/><path d="M7.5 14.5a1.6 1.6 0 0 0 3 0"/>',
  list: '<path d="M6 4.5h9M6 9h9M6 13.5h9"/><circle cx="3" cy="4.5" r="0.9"/><circle cx="3" cy="9" r="0.9"/><circle cx="3" cy="13.5" r="0.9"/>',
  bars: '<path d="M3 15V8M7.5 15V4M12 15v-5M16.5 15V6" stroke-width="1.8"/>',
  mega: '<path d="M3 7v4l8 3V4z"/><path d="M11 5.5a3 3 0 0 1 0 7"/><path d="M4 11.5 5 16"/>',
  sliders: '<path d="M3 5h7M13 5h2M3 13h2M8 13h7"/><circle cx="11.5" cy="5" r="1.6"/><circle cx="6.5" cy="13" r="1.6"/>',
  translate: '<path d="M2.5 4h6M5.5 4v.7c0 3-1.6 5.3-3 6.3M3.5 7.5c.7 1.6 2 2.7 3.5 3.3"/><path d="M9 15l3-7 3 7M10.2 12.5h3.6"/>',
  key: '<circle cx="6" cy="6" r="3"/><path d="m8.2 8.2 6.3 6.3M12 11.5l1.5-1.5M14 13.5l1.5-1.5"/>',
  history: '<path d="M3 9a6 6 0 1 1 1.8 4.3"/><path d="M3 13v-3.5h3.5"/><path d="M9 6v3.3l2.2 1.3"/>',
  database: '<ellipse cx="9" cy="4.5" rx="5.5" ry="2"/><path d="M3.5 4.5v9c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2v-9"/><path d="M3.5 9c0 1.1 2.5 2 5.5 2s5.5-.9 5.5-2"/>',
  review: '<rect x="2.5" y="2.5" width="13" height="13" rx="2"/><path d="m5.5 9 2.2 2.2L12.5 6.5"/>',
  chevron: '<path d="m4 6.5 5 5 5-5"/>',
  chevronR: '<path d="m6.5 4 5 5-5 5"/>',
  lock: '<rect x="3.5" y="7" width="11" height="7" rx="1.5"/><path d="M5.5 7V5a3.5 3.5 0 0 1 7 0v2"/>',
  search: '<circle cx="7.5" cy="7.5" r="4.5"/><path d="m11 11 3.5 3.5"/>',
  refresh: '<path d="M14 7a5.5 5.5 0 1 0 .4 4"/><path d="M14 2.5V7h-4.5"/>',
  alert: '<path d="M9 2.5 16 14.5H2z"/><path d="M9 7v3.5M9 12.7v.1"/>',
  check: '<path d="m3.5 9.5 3.5 3.5 7.5-8"/>',
  sun: '<circle cx="9" cy="9" r="3.2"/><path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.8 3.8l1.4 1.4M12.8 12.8l1.4 1.4M14.2 3.8l-1.4 1.4M5.2 12.8l-1.4 1.4"/>',
  globe: '<circle cx="9" cy="9" r="6.5"/><path d="M2.5 9h13M9 2.5c2 2 2 11 0 13M9 2.5c-2 2-2 11 0 13"/>',
  moon: '<path d="M14.5 10.5A6 6 0 0 1 7.5 3.5a6 6 0 1 0 7 7z"/>',
  arrow: '<path d="M3.5 9h11M10 4.5 14.5 9 10 13.5"/>',
  plus: '<path d="M9 3v12M3 9h12"/>',
  download: '<path d="M9 3v8M5.5 7.5 9 11l3.5-3.5M3.5 14h11"/>',
  info: '<circle cx="9" cy="9" r="6.5"/><path d="M9 8v4M9 5.6v.1"/>',
  play: '<path d="M5 3.5 14 9l-9 5.5z"/>',
  clock: '<circle cx="9" cy="9" r="6.5"/><path d="M9 5v4l2.6 1.6"/>',
  git: '<circle cx="5" cy="5" r="2"/><circle cx="5" cy="13" r="2"/><circle cx="13" cy="7" r="2"/><path d="M5 7v4M5 9a8 8 0 0 0 6-2"/>',
  x: '<path d="M4.5 4.5l9 9M13.5 4.5l-9 9"/>',
};

export interface IconProps {
  name: IconName;
  /** CSS class controls size: default `ico` (14px); `chev` (13px); bare nav uses 16px. */
  className?: string;
}

/** Renders one icon from the set as an inline `<svg>`. */
export function Icon({ name, className = "ico" }: IconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: PATHS[name] ?? "" }}
    />
  );
}
