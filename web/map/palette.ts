// The one bridge from the CSS tokens to JavaScript (docs/plans/front-end/design.md
// § 5, § 3A.4; FE-72). Map styles, canvas layers and the coast embed take their
// colours from a Palette read here; scripts/check_tokens.mjs rejects colour
// literals everywhere under web/ and getPropertyValue('--…') outside this file.
// Values are whatever web/tokens.css resolves to for the current theme, so a
// token change reaches the map without touching map code. Every value is a
// colour except `mpaFillOpacity`, the protected-area fill's opacity (FE-19),
// carried as its CSS text for MapLibre's `to-number`.
import {basemapRoles} from './style.ts';

/** Palette keys and the custom property each one reads (without the leading `--`). */
export const PALETTE_TOKENS = {
  bg: 'bg', bgDeep: 'bg-deep', panel: 'panel', panel2: 'panel-2', line: 'line', text: 'text', muted: 'muted',
  mint: 'mint', blue: 'blue', coral: 'coral', amber: 'amber',
  depth0: 'depth-0', depth1: 'depth-1', depth2: 'depth-2', depth3: 'depth-3',
  sst0: 'sst-0', sst1: 'sst-1', sst2: 'sst-2', sst3: 'sst-3', sst4: 'sst-4', sst5: 'sst-5',
  swell0: 'swell-0', swell1: 'swell-1', swell2: 'swell-2', swell3: 'swell-3',
  flow: 'flow', flowFast: 'flow-fast', mpaFill: 'mpa-fill', mpaFillOpacity: 'mpa-fill-opacity', mpaLine: 'mpa-line',
} as const;

export type PaletteKey = keyof typeof PALETTE_TOKENS;
export type Palette = Readonly<Record<PaletteKey, string>>;
/** Returns a custom property's value by name (without `--`), or '' when it is not set. */
export type TokenReader = (name: string) => string;

/** Reads tokens from the computed style of `element` (the document root by default). */
export function cssTokenReader(element: Element = document.documentElement): TokenReader {
  const style = getComputedStyle(element);
  return name => style.getPropertyValue(`--${name}`);
}

/** Every palette colour, read through `read`. Throws when web/tokens.css is not loaded. */
export function readPalette(read: TokenReader = cssTokenReader()): Palette {
  const palette: Partial<Record<PaletteKey, string>> = {};
  const missing: string[] = [];
  for (const [key, token] of Object.entries(PALETTE_TOKENS) as [PaletteKey, string][]) {
    const value = read(token).trim();
    if (!value) missing.push(`--${token}`);
    palette[key] = value;
  }
  if (missing.length) throw new Error(`Map palette: web/tokens.css is not loaded (missing ${missing.join(', ')}).`);
  return Object.freeze(palette as Record<PaletteKey, string>);
}

/** Depth (shallow to deep), surface temperature (cold to warm) and swell height (low to high) ramps, in token order. */
export function ramps(p: Palette): {depth: string[]; sst: string[]; swell: string[]} {
  return {depth: [p.depth0, p.depth1, p.depth2, p.depth3], sst: [p.sst0, p.sst1, p.sst2, p.sst3, p.sst4, p.sst5], swell: [p.swell0, p.swell1, p.swell2, p.swell3]};
}

/**
 * Colours for the coast embed's `palette` option (§ 3A.4 item 3), keyed by the
 * `--coast-*` role names that map to a v2 token. Water, land and label match
 * the Chart basemap's day roles, so the terrain and the chart agree. Roles with
 * no v2 token (violet) are left to the embed's defaults; FE-76 types the result
 * against `CoastPalette`.
 */
export function coastPalette(p: Palette): Record<string, string> {
  const chart = basemapRoles(p, 'day');
  return {
    ground: p.bg, panel: p.panel, panel2: p.panel2, line: p.line, text: p.text, muted: p.muted,
    mint: p.mint, blue: p.blue, coral: p.coral, amber: p.amber,
    water: chart.water, land: chart.land, label: chart.label,
  };
}
