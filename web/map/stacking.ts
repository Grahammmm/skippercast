// MSKL-3: the layer kit's stacking rules as one pure function (no DOM, no fetch, no MapLibre).
// Input: the kit layers switched on, oldest first (the switch-on order), each with its data state. Output: what each one
// draws (its representations), what replaced it, the base desaturation and the opacities, from the generated tokens only
// (web/map/layers-style.gen.ts = style/layers-v1.0.0.json + style/stacking-v1.0.0.json). Rules P1–P6 are the kit's
// `stacking.precedence`, applied in that order; the caps are `stacking.caps`. No number here is a token value.
//
// Design choices the kit text leaves open (low risk, reversible; recorded in the MSKL-3 commit):
// - "Latest wins" is used wherever a cap would otherwise be exceeded (P1 fill, P4 veil, P5 explicit isoline sets), as P1 states.
// - SST fill's automatic isotherms reserve one isoline slot while SST breaks (the same lines) is not drawing.
// - A layer with no data yet, or withheld for age, draws nothing and so takes part in no rule (its row says why).
// - A preset or the user may leave out an optional part of a layer (kelp-habitat's shore lines, `OPTIONAL_PARTS`); a part a
//   P-rule governs (fills, flow, arrows, dots) is never optional: the rules decide it.
//
// Erasable syntax only: tests/test_stacking.mjs and scripts/style/export_cases/_stacking.mjs import it by type stripping.
import {SKL_LAYERS, SKL_STACKING} from './layers-stacking.gen.ts';

type Stops = readonly (readonly [number, number])[];
interface StyleLayer {
  readonly slot: string;
  readonly desaturates_base: boolean;
  readonly opacity?: unknown;
  readonly fill?: {readonly opacity?: unknown};
  readonly veil?: {readonly max_alpha?: number};
  readonly kelp?: {readonly opacity: number; readonly opacity_with_color_field: number};
  readonly others?: {readonly hide_with_color_field?: boolean};
  readonly band_edge?: {readonly hide_when_any_on?: readonly string[]};
  readonly isotherms?: unknown;
  readonly glow?: {readonly opacity?: number};
  readonly representations?: Readonly<Record<string, readonly string[]>>;
}
interface Stacking {
  readonly z_order: readonly {readonly z: number; readonly id: string; readonly members?: readonly string[]}[];
  readonly opacity_by_zoom: Readonly<Record<'color_field' | 'cloud_veil' | 'radar' | 'habitat_fill' | 'particles', Stops>>;
  readonly caps: Readonly<Record<CapClass, number>>;
  readonly veil_cap_with_field_or_radar: number;
  readonly base_desaturation_when_field_on: number;
  readonly isolines_from_zoom: number;
  readonly precedence: readonly {readonly id: string}[];
  readonly presets: Readonly<Record<string, {readonly view: string; readonly zoom: number; readonly layers: readonly {readonly layer: string; readonly as: readonly string[]}[]}>>;
}

const LAYERS = SKL_LAYERS as unknown as Readonly<Record<string, StyleLayer>>;
export const STACKING = SKL_STACKING as unknown as Stacking;

export type KitLayerId = keyof typeof SKL_LAYERS;
/** The 24 kit layers in the kit's own order (01 sst-fill … 24 ais-fleet). */
export const KIT_LAYER_IDS = Object.freeze(Object.keys(LAYERS) as KitLayerId[]);
export type CapClass = 'color_field' | 'veil' | 'isolines' | 'particles' | 'arrows_barbs';

/** What a layer can draw. Fill, flow, arrows, veils and isolines are the kit's representation words; the rest name a layer's own parts. */
export type Rep = 'fill' | 'auto isotherms' | 'isolines' | 'isotherms' | 'streamlines' | 'particles' | 'barbs' | 'arrows' | 'veil' | 'radar'
  | 'ribbon' | 'zones' | 'mpas' | 'kelp' | 'shore' | 'hatch' | 'pin' | 'chips' | 'ramps' | 'piers' | 'badges' | 'dots' | 'route' | 'track';

/** The cap class of each capped representation (`stacking.caps`). */
const CLASS: Partial<Record<Rep, CapClass>> = {
  fill: 'color_field', veil: 'veil', isolines: 'isolines', isotherms: 'isolines', 'auto isotherms': 'isolines',
  streamlines: 'particles', particles: 'particles', barbs: 'arrows_barbs', arrows: 'arrows_barbs',
};
/** A layer's parts when its tokens give no `representations.solo` and its slot alone does not name them. */
const PARTS: Partial<Record<KitLayerId, readonly Rep[]>> = {
  'subsurface-temp': ['fill', 'isotherms'], 'marine-zones-mpas': ['zones', 'mpas'], 'kelp-habitat': ['kelp', 'shore'], 'ais-fleet': ['hatch'],
  tides: ['pin'], stations: ['chips'], places: ['ramps', 'piers'], 'spots-marks': ['badges', 'dots'], 'routes-tracks': ['route', 'track'],
};
/**
 * SST breaks' live Temp contrast cells are a colour field (the kit's `glow`, in the colour-field slot) beside its isolines (fronts),
 * so a Chart that offers `fill` for it makes it compete under P1; losing the field it keeps its isolines (the kit tokens give it no
 * `fill_taken_by_other_layer`). Solo, the kit row stays isolines only.
 */
const FILL_LOSER_KEEPS: Partial<Record<KitLayerId, readonly Rep[]>> = {'sst-breaks': ['isolines']};
const BY_SLOT: Readonly<Record<string, readonly Rep[]>> = {color_field: ['fill'], isolines: ['isolines'], veil: ['veil'], radar: ['radar'], ribbon: ['ribbon']};
/** Parts a preset or the user may leave out; every other part is decided by P1–P6. */
export const OPTIONAL_PARTS: Readonly<Partial<Record<KitLayerId, readonly Rep[]>>> = Object.freeze({'kelp-habitat': ['shore'], places: ['piers'], 'routes-tracks': ['track'], 'marine-zones-mpas': ['zones']});

/** What layer `id` draws on its own (no other layer on). */
export function soloReps(id: KitLayerId): Rep[] {
  const layer = LAYERS[id];
  if (!layer) throw new RangeError(`Unknown kit layer: ${String(id)}`);
  const own = layer.representations?.solo as readonly Rep[] | undefined;
  const reps = own ?? PARTS[id] ?? BY_SLOT[layer.slot];
  if (!reps) throw new RangeError(`Kit layer ${id} has no representation for slot ${layer.slot}`);
  return [...reps];
}

/** `ready`: drawable; `stale`: drawable, readings keep their own times (stations, tides); `dated`: drawable, prints its date. */
export type KitDataState = 'ready' | 'stale' | 'dated' | 'no-data' | 'withheld';
export interface StackInput {
  readonly id: KitLayerId;
  readonly state?: KitDataState;
  /** Live implementations need not support every representation in the kit. */
  readonly available?: readonly Rep[];
  /** Optional parts left out (only `OPTIONAL_PARTS` are honoured). */
  readonly without?: readonly Rep[];
}
export type StackStatus = 'drawn' | 'replaced' | 'no-data' | 'withheld';
export interface StackedLayer {
  readonly id: KitLayerId;
  readonly status: StackStatus;
  /** What it draws, in its solo order. Empty unless `drawn`. */
  readonly reps: readonly Rep[];
  /** The layer that took its last representation (P1 fill, P3 arrows, P4 veil, P5 isolines). */
  readonly replacedBy?: KitLayerId;
  /** The second isoline set draws dashed (P5). */
  readonly dashed?: boolean;
  /** SST band edges (P6); only on sst-fill while it draws its fill. */
  readonly bandEdges?: boolean;
  readonly opacity: Readonly<Partial<Record<'fill' | 'radar' | 'veil' | 'particles' | 'kelp', number>>>;
}
export interface StackCounts {readonly color_field: number; readonly veil: number; readonly isolines: number; readonly particles: number; readonly arrows_barbs: number}
export interface Stack {
  /** One row per input, in input order. */
  readonly layers: readonly StackedLayer[];
  readonly baseDesaturation: number;
  readonly counts: StackCounts;
  /** Cap classes over their cap; empty after `resolveStack`. */
  readonly violations: readonly CapClass[];
}

/** Linear `[zoom, value]` stops, held flat beyond the ends (the kit's `stops`). */
export function stopsAt(stops: Stops, zoom: number): number {
  if (!stops.length) throw new RangeError('empty stops');
  if (zoom <= stops[0]![0]) return stops[0]![1];
  for (let i = 1; i < stops.length; i++) {
    const [z1, v1] = stops[i]!, [z0, v0] = stops[i - 1]!;
    if (zoom <= z1) return v0 + (v1 - v0) * (zoom - z0) / (z1 - z0);
  }
  return stops.at(-1)![1];
}

/** A layer may switch itself on (profile default, preset) only when it has data and is local: never sea ice, never a no-data layer. */
export const mayAutoEnable = (id: KitLayerId, state: KitDataState): boolean => id !== 'sea-ice' && state !== 'no-data';

const drawable = (s: KitDataState | undefined): boolean => s === undefined || s === 'ready' || s === 'stale' || s === 'dated';

/** Count drawn representations per cap class and list the classes over their cap. */
export function capCheck(layers: readonly Pick<StackedLayer, 'reps'>[]): {counts: StackCounts; violations: CapClass[]} {
  const counts = {color_field: 0, veil: 0, isolines: 0, particles: 0, arrows_barbs: 0};
  for (const layer of layers) for (const rep of layer.reps) { const c = CLASS[rep]; if (c) counts[c]++; }
  const violations = (Object.keys(counts) as CapClass[]).filter(c => counts[c] > STACKING.caps[c]);
  return {counts, violations};
}

/** The layers as switched on with no precedence applied (each draws its solo representations): the kit's "as drafted" check. */
export function draftStack(input: readonly StackInput[], zoom: number): Stack {
  const layers = input.map(({id, state, without}): StackedLayer => drawable(state)
    ? {id, status: 'drawn', reps: soloReps(id).filter(r => !optionalOff(id, without, r)), opacity: {}}
    : {id, status: state as StackStatus, reps: [], opacity: {}});
  return finish(layers, zoom);
}

const optionalOff = (id: KitLayerId, without: readonly Rep[] | undefined, rep: Rep) => !!without?.includes(rep) && !!OPTIONAL_PARTS[id]?.includes(rep);

interface Row {id: KitLayerId; status: StackStatus; reps: Rep[]; replacedBy?: KitLayerId; dashed?: boolean; bandEdges?: boolean; opacity: Record<string, number>}

/** P1–P6 over the switched-on layers (oldest first). */
export function resolveStack(input: readonly StackInput[], zoom: number): Stack {
  const rows: Row[] = input.map(({id, state, without, available}) => drawable(state)
    ? {id, status: 'drawn', reps: (available ?? soloReps(id)).filter(r => !optionalOff(id, without, r)), opacity: {}}
    : {id, status: state as StackStatus, reps: [], opacity: {}});
  const drawn = () => rows.filter(r => r.status === 'drawn');
  const lose = (row: Row, keep: (rep: Rep) => boolean, by: KitLayerId) => {
    row.reps = row.reps.filter(keep);
    if (!row.reps.length) { row.status = 'replaced'; row.replacedBy = by; }
  };

  // P1-fill: the latest `caps.color_field` fill layers own the slot; the others keep their non-fill fallback, or are replaced.
  const fills = drawn().filter(r => r.reps.includes('fill'));
  const owners = fills.slice(-STACKING.caps.color_field), owner = owners.at(-1);
  for (const row of fills) if (!owners.includes(row)) {
    const fallback = (LAYERS[row.id]!.representations?.fill_taken_by_other_layer as readonly Rep[] | undefined) ?? FILL_LOSER_KEEPS[row.id];
    lose(row, rep => rep !== 'fill' && !!fallback?.includes(rep), owner!.id);
  }

  // P2-particles: currents' streamlines own the particle slot; wind's particles become barbs while currents draw.
  const currents = drawn().find(r => r.id === 'currents' && r.reps.includes('streamlines'));
  const wind = drawn().find(r => r.id === 'wind');
  if (currents && wind?.reps.includes('particles')) {
    const barbs = LAYERS.wind!.representations!.particles_taken_by_currents as readonly Rep[];
    wind.reps = [...wind.reps.filter(r => r !== 'particles'), ...barbs.filter(r => !wind.reps.includes(r))];
  }

  // P3-arrows: wind barbs beat wave arrows; waves keep only their fill (if they own it).
  if (wind?.reps.includes('barbs')) for (const row of drawn()) if (row.id !== 'wind' && row.reps.includes('arrows')) lose(row, rep => rep !== 'arrows', 'wind');

  // P4-veils: one veil, the latest switched on.
  const veils = drawn().filter(r => r.reps.includes('veil'));
  const veilOwners = veils.slice(-STACKING.caps.veil);
  for (const row of veils) if (!veilOwners.includes(row)) lose(row, rep => rep !== 'veil', veilOwners.at(-1)!.id);

  // P5: reserve the automatic SST set when breaks are not among the winning explicit sets.
  const isLine = (rep: Rep) => rep === 'isolines' || rep === 'isotherms';
  const sets = drawn().filter(r => r.reps.some(isLine));
  const sst = drawn().find(r => r.id === 'sst-fill' && r.reps.includes('fill'));
  const candidates = sets.slice(-STACKING.caps.isolines);
  const auto = !!sst && zoom >= STACKING.isolines_from_zoom && !candidates.some(r => r.id === 'sst-breaks');
  const kept = auto ? sets.slice(-(STACKING.caps.isolines - 1)) : candidates;
  for (const row of sets) if (!kept.includes(row)) lose(row, rep => !isLine(rep), kept.at(-1)?.id ?? sst!.id);
  if (sst && auto) sst.reps.push('auto isotherms');
  const lineRows = drawn().filter(r => r.reps.some(rep => CLASS[rep] === 'isolines'));
  if (lineRows.length > 1) lineRows.at(-1)!.dashed = true;

  // P6-clutter: band edges hide under any isoline, particle or arrow/barb layer; a colour field hides unranked dots and dims kelp.
  const classes = new Set(drawn().flatMap(r => r.reps.map(rep => CLASS[rep])));
  if (sst) sst.bandEdges = !(LAYERS['sst-fill']!.band_edge?.hide_when_any_on ?? []).some(c => classes.has(c as CapClass));
  const field = classes.has('color_field');
  if (field && LAYERS['spots-marks']!.others?.hide_with_color_field) {
    for (const row of drawn()) if (row.id === 'spots-marks') lose(row, rep => rep !== 'dots', owner!.id);
  }
  return finish(rows, zoom);
}

function finish(rows: readonly StackedLayer[] | Row[], zoom: number): Stack {
  const list = rows as Row[];
  const drawnRows = list.filter(r => r.status === 'drawn');
  const field = drawnRows.some(r => r.reps.includes('fill'));
  const radar = drawnRows.some(r => r.reps.includes('radar'));
  for (const row of drawnRows) {
    const layer = LAYERS[row.id]!, o: Record<string, number> = {};
    const fillStops = (layer.fill?.opacity ?? layer.opacity) as Stops | undefined;
    if (row.reps.includes('fill')) o.fill = fillStops ? stopsAt(fillStops, zoom) : layer.glow!.opacity!;
    if (row.reps.includes('radar')) o.radar = stopsAt(layer.opacity as Stops, zoom);
    if (row.reps.includes('veil')) {
      o.veil = row.id === 'clouds'
        ? Math.min(stopsAt(STACKING.opacity_by_zoom.cloud_veil, zoom), field || radar ? STACKING.veil_cap_with_field_or_radar : Infinity)
        : layer.veil!.max_alpha!;
    }
    if (row.reps.includes('streamlines') || row.reps.includes('particles')) o.particles = stopsAt(STACKING.opacity_by_zoom.particles, zoom);
    if (row.reps.includes('kelp')) o.kelp = field ? layer.kelp!.opacity_with_color_field : layer.kelp!.opacity;
    row.opacity = o;
  }
  const desaturates = drawnRows.some(r => LAYERS[r.id]!.desaturates_base);
  const {counts, violations} = capCheck(drawnRows);
  const layers = list.map(r => Object.freeze({...r, reps: Object.freeze([...r.reps]), opacity: Object.freeze({...r.opacity})})) as StackedLayer[];
  return {layers, baseDesaturation: desaturates ? STACKING.base_desaturation_when_field_on : 0, counts, violations};
}

/** `<layer>:<rep>+<rep>` as the kit's preset metrics write it. */
export const stackLabel = (row: Pick<StackedLayer, 'id' | 'reps'>): string => `${row.id}:${row.reps.join('+')}`;

/** The opacity the kit's metrics report for a stack: the colour field's, else the radar's; undefined when neither draws. */
export function fieldOpacity(stack: Stack): number | undefined {
  const rows = stack.layers.filter(r => r.status === 'drawn');
  return rows.find(r => r.opacity.fill !== undefined)?.opacity.fill ?? rows.find(r => r.opacity.radar !== undefined)?.opacity.radar;
}

/**
 * A preset's switch-on order: its layers in the preset's order, with the layer the preset gives the fill switched on last
 * (P1: the latest fill wins). Optional parts the preset leaves out are passed as `without`; every other representation
 * comes from the rules, so a preset whose `as` disagrees with P1–P6 shows up in `presetCheck`.
 */
export function presetInput(name: string): StackInput[] {
  const preset = STACKING.presets[name];
  if (!preset) throw new RangeError(`Unknown preset: ${name}`);
  const entries = preset.layers.map(({layer, as}) => {
    const id = layer as KitLayerId;
    return {id, without: (OPTIONAL_PARTS[id] ?? []).filter(rep => !as.includes(rep))};
  });
  const fillAt = preset.layers.findIndex(l => l.as.includes('fill'));
  return fillAt < 0 ? entries : [...entries.filter((_, i) => i !== fillAt), entries[fillAt]!];
}

/** The preset resolved, with its rows back in the preset's own order. */
export function presetStack(name: string): Stack {
  const preset = STACKING.presets[name]!;
  const stack = resolveStack(presetInput(name), preset.zoom);
  const order = preset.layers.map(l => l.layer);
  return {...stack, layers: [...stack.layers].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))};
}
