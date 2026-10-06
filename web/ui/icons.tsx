// Icon set (FE-03, docs/plans/front-end/design.md § 3 and § 6): stroke icons
// on a 24 grid, stroke 1.65, round caps and joins, drawn in currentColor so
// they take the text colour of their control. The first 31 are ported from
// fish/src/ui/icons.ts (same owner; fish/NOTICE.md); the rest are the ones
// the shell names that fish lacked (layer rail, masthead, mark card, dock).
// Glyphs are data (path d strings and circles) rendered by Preact: web/
// never sets innerHTML.

/** One glyph: path data joined into one <path>, plus optional circles. */
type Glyph = {d: string; dots?: ReadonlyArray<readonly [number, number, number, boolean?]>};

export const GLYPHS = {
  // Ported from fish
  wave: {d: 'M2 8c3-4 5 4 8 0s5 4 8 0 4 1 4 1M2 15c3-4 5 4 8 0s5 4 8 0 4 1 4 1'},
  fish: {d: 'M3 12c5-9 11-9 15 0-4 9-10 9-15 0Zm15 0 4-5v10l-4-5Z', dots: [[7.5, 10.5, 0.7, true]]},
  boat: {d: 'm3 15 9-4 9 4-4 5H7l-4-5ZM6 13V7h12v6M12 7V3M3 22c2-2 4 2 6 0s4 2 6 0 4 2 6 0'},
  shore: {d: 'M3 19c3-3 5 3 8 0s5 3 10 0M5 13 15 3M14 3h4v4M9 9l3 6M6 12l-3 3'},
  spear: {d: 'M3 9h18l-2 8h-5l-2-3-2 3H5L3 9ZM21 9V3h-4M7 9V6m10 3V6'},
  wind: {d: 'M2 7h12c5 0 5-5 1-5M2 12h17c4 0 4 7 0 7M2 17h8'},
  temperature: {d: 'M9 15V5a3 3 0 0 1 6 0v10a5 5 0 1 1-6 0ZM12 8v10'},
  tide: {d: 'M2 20h20M2 16h20M7 11V3m-3 3 3-3 3 3M17 3v8m-3-3 3 3 3-3'},
  sun: {d: 'M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2', dots: [[12, 12, 4]]},
  cloud: {d: 'M6 18a4 4 0 0 1-1-8 7 7 0 0 1 13-1 5 5 0 0 1 0 9Z'},
  layers: {d: 'm12 3 10 6-10 6L2 9l10-6ZM2 14l10 6 10-6M2 19l10 5 10-5'},
  map: {d: 'm2 5 7-3 6 3 7-3v17l-7 3-6-3-7 3V5ZM9 2v17m6-14v17'},
  chart: {d: 'M3 3v18h19M6 16l4-5 4 3 7-9'},
  history: {d: 'M3 12a9 9 0 1 0 3-7M3 3v6h6M12 7v6l4 2'},
  pin: {d: 'M19 10c0 6-7 11-7 11S5 16 5 10a7 7 0 1 1 14 0Z', dots: [[12, 10, 2]]},
  arrow: {d: 'M4 12h15m-6-6 6 6-6 6'},
  chevron: {d: 'm8 5 7 7-7 7'},
  down: {d: 'm5 8 7 7 7-7'},
  close: {d: 'm5 5 14 14M5 19 19 5'},
  play: {d: 'm8 4 12 8-12 8V4Z'},
  pause: {d: 'M8 4v16M16 4v16'},
  info: {d: 'M12 10v7M12 7h.01', dots: [[12, 12, 9]]},
  check: {d: 'm5 12 4 4L20 5'},
  compass: {d: 'm15 9-2 4-4 2 2-4 4-2Z', dots: [[12, 12, 9]]},
  current: {d: 'm2 8 5-4v8L2 8Zm5 0h15M22 17l-5-4v8l5-4Zm-5 0H2'},
  eye: {d: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z', dots: [[12, 12, 3]]},
  shield: {d: 'M12 2 3 6v7c0 5 9 9 9 9s9-4 9-9V6l-9-4Z'},
  target: {d: 'M12 1v6m0 10v6M1 12h6m10 0h6', dots: [[12, 12, 7]]},
  settings: {d: 'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6M9 15v6'},
  expand: {d: 'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5'},
  bell: {d: 'M5 17h14l-2-3V8a5 5 0 0 0-10 0v6l-2 3ZM9 20h6'},
  // Added for the v2 shell
  seafloor: {d: 'M2 6c3-3 5 3 8 0s5 3 8 0 4 1 4 1M2 20l3-6 3 4 3-7 3 5 3-3 3 7'},
  fleet: {d: 'M3 12h8l-2 4H5l-2-4Zm4 0V8m6 4h8l-2 4h-4l-2-4Zm4 0V8M2 21c2-2 4 2 6 0s4 2 6 0 4 2 6 0'},
  user: {d: 'M4 21a8 8 0 0 1 16 0', dots: [[12, 8, 4]]},
  plus: {d: 'M12 5v14M5 12h14'},
  minus: {d: 'M5 12h14'},
  up: {d: 'm5 16 7-7 7 7'},
  download: {d: 'M12 3v12m-5-5 5 5 5-5M4 21h16'},
  search: {d: 'm20 20-4-4', dots: [[11, 11, 7]]},
  menu: {d: 'M4 7h16M4 12h16M4 17h16'},
} as const satisfies Record<string, Glyph>;

export type IconName = keyof typeof GLYPHS;
export const ICON_NAMES = Object.keys(GLYPHS) as IconName[];

export type IconProps = {
  name: IconName;
  /** Rendered width and height in CSS pixels (the glyph grid is 24). */
  size?: number;
  /** Accessible name; without one the icon is decorative (aria-hidden). */
  label?: string;
  class?: string;
};

export function Icon({name, size = 20, label, class: cls}: IconProps) {
  const glyph: Glyph = GLYPHS[name];
  return (
    <svg class={cls ? `icon ${cls}` : 'icon'} viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
      stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" data-icon={name}
      role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : 'true'}>
      <path d={glyph.d} />
      {glyph.dots?.map(([cx, cy, r, filled]) => <circle cx={cx} cy={cy} r={r} fill={filled ? 'currentColor' : undefined} />)}
    </svg>
  );
}
