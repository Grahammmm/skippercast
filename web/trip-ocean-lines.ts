// The Trip dialog's per-layer ocean coverage lines (docs/plans/offline-ocean-coverage.md D10): for a saved pack, whether Water temp and
// Currents were saved and the last moment the readers can still draw them, or why they were not saved. Read only from the pack's own
// `ocean` record (D9); it never promises that a layer will show. Erasable syntax only (tests/test_trip.mjs imports it by type stripping).
import type {PackMeta} from './trip.ts';
import {frameTime} from './map/currents.ts';
import {DEFAULT_ZONE} from './zone.ts';

export interface OceanLines {readonly water: string; readonly currents: string}
interface Layer {readonly state?: string; readonly why?: string; readonly drawable_until?: string}

const ONLY_FOR = {water: 'only for hours on or after the analysis', currents: 'only for forecast hours'} as const;
const LAYER = {water: 'sst-analysis', currents: 'wcofs-surface-forecast'} as const;

/** One layer's line from its record, at the injected `now` and in the region's zone. */
function layerLine(kind: keyof typeof LAYER, layer: Layer | undefined, now: Date, zone: string): string {
  switch (layer?.state) {
    case 'saved': {
      const until = Date.parse(layer.drawable_until ?? '');
      if (!Number.isFinite(until)) return 'saved';
      return now.getTime() < until ? `saved · not shown after ${frameTime(layer.drawable_until!, zone)} · ${ONLY_FOR[kind]}` : 'saved · past its age limit';
    }
    case 'failed': return 'not saved: failed check';
    case 'over-cap': return 'not saved: too large for this pack';
    case 'not-current': return layer.why === 'retrieval' || layer.why === 'short-window' ? 'not saved: forecast too old to show offline' : 'not saved: no current data at save time';
    case 'absent': return 'not saved: not published for this area';
    default: return 'not saved';   // cancelled, an unknown state, or a layer the record does not list
  }
}

/** The two coverage lines for a saved pack, or null for a pack saved before the ocean phase (no line is shown). */
export function oceanLines(meta: Pick<PackMeta, 'ocean'>, now: Date, zone: string = DEFAULT_ZONE): OceanLines | null {
  const ocean = meta.ocean;
  if (!ocean) return null;
  if (ocean.path === 'none') return {water: 'not published for this area', currents: 'not published for this area'};
  if (ocean.path === 'coastal-report') {
    const at = (ocean as {coastal?: {saved_at?: string} | null}).coastal?.saved_at;
    const line = at && Number.isFinite(Date.parse(at)) ? `from Coastal readings (saved ${frameTime(at, zone)})` : 'from Coastal readings (not saved)';
    return {water: line, currents: line};
  }
  const layers = ocean.layers as unknown as Record<string, Layer | undefined>;
  return {water: layerLine('water', layers[LAYER.water], now, zone), currents: layerLine('currents', layers[LAYER.currents], now, zone)};
}
