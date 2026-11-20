// The one bridge from the CSS tokens to JavaScript (docs/plans/front-end/design.md
// § 5, § 3A.4; FE-72). Map styles, canvas layers and the coast embed take their
// colours from a Palette read here; scripts/check_tokens.mjs rejects colour
// literals everywhere under web/ and getPropertyValue('--…') outside this file.
// Values are whatever web/tokens.css resolves to for the current theme, so a
// token change reaches the map without touching map code. Every value is a
// colour except `mpaFillOpacity` and the four `map*Opacity`/`mapContourWidth`
// controls (MGL-15), carried as their CSS text for MapLibre's `to-number`; the
// modules that draw with them validate the text (mapControl in style.ts).
import {basemapRoles} from './style.ts';
import {SKL_PALETTE_TOKENS} from './layers-style.gen.ts';

/** Palette keys and the custom property each one reads (without the leading `--`). */
export const PALETTE_TOKENS = {
  bg: 'bg', bgDeep: 'bg-deep', panel: 'panel', panel2: 'panel-2', line: 'line', text: 'text', muted: 'muted',
  mint: 'mint', blue: 'blue', coral: 'coral', amber: 'amber',
  depth0: 'depth-0', depth1: 'depth-1', depth2: 'depth-2', depth3: 'depth-3',
  depthB0: 'depth-b-0', depthB1: 'depth-b-1', depthB2: 'depth-b-2', depthB3: 'depth-b-3',
  depthB4: 'depth-b-4', depthB5: 'depth-b-5', depthB6: 'depth-b-6', depthB7: 'depth-b-7',
  depthB8: 'depth-b-8', depthB9: 'depth-b-9', depthB10: 'depth-b-10',
  sst0: 'sst-0', sst1: 'sst-1', sst2: 'sst-2', sst3: 'sst-3', sst4: 'sst-4', sst5: 'sst-5',
  current0: 'current-0', current1: 'current-1', current2: 'current-2', current3: 'current-3', current4: 'current-4', current5: 'current-5',
  swell0: 'swell-0', swell1: 'swell-1', swell2: 'swell-2', swell3: 'swell-3',
  contrast0: 'contrast-0', contrast1: 'contrast-1', contrast2: 'contrast-2',
  flow: 'flow', flowFast: 'flow-fast', mpaFill: 'mpa-fill', mpaFillOpacity: 'mpa-fill-opacity', mpaLine: 'mpa-line',
  // MGL-15: map-only roles (web/tokens.css), so the map and its legend never read the app chrome's tokens.
  mapWater: 'map-water', mapLand: 'map-land', mapPark: 'map-park', mapRoad: 'map-road', mapRoadMinor: 'map-road-minor', mapBoundary: 'map-boundary',
  mapLabel: 'map-label', mapHalo: 'map-halo', mapInk: 'map-ink', mapInkHalo: 'map-ink-halo', mapCoast: 'map-coast', mapContour: 'map-contour',
  mapContourShallow: 'map-contour-shallow', mapContourShallowHalo: 'map-contour-shallow-halo', mapContourDeep: 'map-contour-deep', mapContourDeepHalo: 'map-contour-deep-halo', mapNosurvey: 'map-nosurvey',
  mapSurveyInk: 'map-survey-ink', mapSurveyHalo: 'map-survey-halo', mapSky: 'map-sky', mapHorizon: 'map-horizon', mapFog: 'map-fog',
  mapSurveyTint1: 'map-survey-tint-1', mapSurveyTint2: 'map-survey-tint-2', mapSurveyTint5: 'map-survey-tint-5',
  habRock: 'hab-rock', habMixed: 'hab-mixed', habSoft: 'hab-soft', habKelp: 'hab-kelp', markRing: 'mark-ring',
  mapLabelOpacity: 'map-label-opacity', mapRoadOpacity: 'map-road-opacity', mapHabitatOpacity: 'map-habitat-opacity', mapContourWidth: 'map-contour-width',
  // MSK-2: G's nearshore style kit colours (web/tokens.css generated `--skn-*` block, scripts/style/gen_style.py). They sit in
  // :root only, so both themes read the same values: the kit look is theme-independent (MAP-DESIGN-LOCK § 10.1, G D3).
  sknDepth0: 'skn-depth-ns-0', sknDepth1: 'skn-depth-ns-1', sknDepth2: 'skn-depth-ns-2', sknDepth3: 'skn-depth-ns-3', sknDepth4: 'skn-depth-ns-4',
  sknDepth5: 'skn-depth-ns-5', sknDepth6: 'skn-depth-ns-6', sknDepth7: 'skn-depth-ns-7', sknDepth8: 'skn-depth-ns-8', sknDepth9: 'skn-depth-ns-9',
  sknDepth10: 'skn-depth-ns-10', sknDepth11: 'skn-depth-ns-11', sknDepth12: 'skn-depth-ns-12', sknDepth13: 'skn-depth-ns-13', sknDepth14: 'skn-depth-ns-14',
  sknContourMinor: 'skn-map-contour-ns-minor', sknContourIndex: 'skn-map-contour-ns-index', sknLabelInk: 'skn-map-label-ink', sknLabelHalo: 'skn-map-label-halo',
  sknPile: 'skn-hab-pile', sknPileEdge: 'skn-hab-pile-edge', sknPileLabel: 'skn-hab-pile-label', sknHardEdge: 'skn-hab-hard-edge',
  sknPierFill: 'skn-map-pier-fill', sknPierCasing: 'skn-map-pier-casing', sknCastArc: 'skn-map-cast-arc', sknCastArcHalo: 'skn-map-cast-arc-halo',
  sknCastArcLabel: 'skn-map-cast-arc-label',
  ...SKL_PALETTE_TOKENS,
} as const;

const BY_TOKEN: ReadonlyMap<string, PaletteKey> = new Map(Object.entries(PALETTE_TOKENS).map(([key, token]) => [token, key as PaletteKey]));
/**
 * The palette value for a generated `--skn-*` variable name, as web/map/nearshore-style.gen.ts names its colours, so map code
 * follows the generated module rather than a key written by hand. Throws for a variable this bridge does not carry.
 */
export function sknColor(p: Palette, cssVar: string): string {
  const key = cssVar.startsWith('--skn-') ? BY_TOKEN.get(cssVar.slice(2)) : undefined;
  if (!key) throw new Error(`Map palette: ${cssVar} is not bridged in PALETTE_TOKENS.`);
  return p[key];
}

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

/** Depth (shallow to deep), surface temperature (cold to warm), swell height (low to high) and current speed (slow to fast) ramps, in token order. */
export function ramps(p: Palette): {depth: string[]; sst: string[]; swell: string[]; current: string[]} {
  return {depth: [p.depth0, p.depth1, p.depth2, p.depth3], sst: [p.sst0, p.sst1, p.sst2, p.sst3, p.sst4, p.sst5], swell: [p.swell0, p.swell1, p.swell2, p.swell3],
    current: [p.current0, p.current1, p.current2, p.current3, p.current4, p.current5]};
}

/** The 3D view's sky, horizon, fog and clear colours (MAP-DESIGN-LOCK 10.2) for the coast embed's `sky` option and `setTheme`. */
export function coastSky(p: Palette): {sky: string; horizon: string; fog: string; ground: string} {
  return {sky: p.mapSky, horizon: p.mapHorizon, fog: p.mapFog, ground: p.bg};
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
    ground: p.bg, skyTop: p.bgDeep, panel: p.panel, panel2: p.panel2, line: p.line, text: p.text, muted: p.muted,
    mint: p.mint, blue: p.blue, coral: p.coral, amber: p.amber,
    water: chart.water, land: chart.land, label: chart.label,
  };
}
