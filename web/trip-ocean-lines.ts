// The Trip dialog's per-layer ocean coverage lines (docs/plans/offline-ocean-coverage.md D10): for a saved pack, whether Water temp and
// Currents were saved and the last moment the readers can still draw them, or why they were not saved. Read only from the pack's own
// `ocean` record (D9); it never promises that a layer will show. Words come from the catalogue in the chosen language (SC0707-10);
// English output is the original text. Erasable syntax only (tests/test_trip.mjs imports it by type stripping).
import type {PackMeta} from './trip.ts';
import {frameTime} from './map/currents.ts';
import {DEFAULT_ZONE} from './zone.ts';
import {localeOf, t, type Language} from './i18n.ts';

export interface OceanLines {readonly water: string; readonly currents: string}
interface Layer {readonly state?: string; readonly why?: string; readonly drawable_until?: string}

const LAYER = {water: 'sst-analysis', currents: 'wcofs-surface-forecast'} as const;

/** The same instant in the region's zone: English keeps the dock's frame time, Spanish reads the platform's format. */
const at = (iso: string, zone: string, lang: Language): string =>
  lang === 'es' ? new Intl.DateTimeFormat(localeOf(lang), {timeZone: zone, weekday: 'short', hour: 'numeric'}).format(new Date(iso)) : frameTime(iso, zone);

/** One layer's line from its record, at the injected `now` and in the region's zone. */
function layerLine(kind: keyof typeof LAYER, layer: Layer | undefined, now: Date, zone: string, lang: Language): string {
  switch (layer?.state) {
    case 'saved': {
      const until = Date.parse(layer.drawable_until ?? '');
      if (!Number.isFinite(until)) return t('tripOcean.saved', lang);
      return now.getTime() < until ? t('tripOcean.savedUntil', lang, {at: at(layer.drawable_until!, zone, lang), scope: t(kind === 'water' ? 'tripOcean.onlyWater' : 'tripOcean.onlyCurrents', lang)}) : t('tripOcean.pastLimit', lang);
    }
    case 'failed': return t('tripOcean.failed', lang);
    case 'over-cap': return t('tripOcean.overCap', lang);
    case 'not-current': return t(layer.why === 'retrieval' || layer.why === 'short-window' ? 'tripOcean.tooOld' : 'tripOcean.noCurrent', lang);
    case 'absent': return t('tripOcean.absent', lang);
    default: return t('tripOcean.notSaved', lang);   // cancelled, an unknown state, or a layer the record does not list
  }
}

/** The two coverage lines for a saved pack, or null for a pack saved before the ocean phase (no line is shown). */
export function oceanLines(meta: Pick<PackMeta, 'ocean'>, now: Date, zone: string = DEFAULT_ZONE, lang: Language = 'en'): OceanLines | null {
  const ocean = meta.ocean;
  if (!ocean) return null;
  if (ocean.path === 'none') return {water: t('tripOcean.none', lang), currents: t('tripOcean.none', lang)};
  if (ocean.path === 'coastal-report') {
    const saved = (ocean as {coastal?: {saved_at?: string} | null}).coastal?.saved_at;
    const line = saved && Number.isFinite(Date.parse(saved)) ? t('tripOcean.coastalSaved', lang, {at: at(saved, zone, lang)}) : t('tripOcean.coastalNot', lang);
    return {water: line, currents: line};
  }
  // A persisted record can lack `layers` (older or damaged data): only a plain object counts as layer evidence, anything else is "none recorded".
  const raw: unknown = ocean.layers;
  const layers: Record<string, Layer | undefined> = raw !== null && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, Layer | undefined> : {};
  return {water: layerLine('water', layers[LAYER.water], now, zone, lang), currents: layerLine('currents', layers[LAYER.currents], now, zone, lang)};
}
