// SCFEAT-FRESH-1 (competitor matrix recommendation 7): the one update-cadence line every legend row
// carries, in one wording. The numbers are those of catalog/layer-inventory.json (update_cadence) and
// catalog/feed-health.json (feed age limits); tests/test_layer_freshness.mjs checks them against both,
// so this small table is what the page ships instead of the 480 KB inventory.
//
// A cadence is how often the source is refreshed; the age limit is how old data may be before the
// map withholds it. They are different numbers and the line names each as what it is. Where a source
// publishes no schedule the line says so rather than guessing. Nothing here is for navigation.
import {t, type Language, type StringId} from '../i18n.ts';

export interface LayerFreshness {
  /** Catalogue id of the cadence phrase. */
  cadence: StringId;
  /** Hours the map keeps showing data of this age, or null when stated in minutes / not applicable. */
  limitHours: number | null;
  limitMinutes?: number;
  /** layer-inventory.json layer ids this row's numbers come from. */
  inventory: readonly string[];
  /** Whether the inventory update_cadence text must contain limitHours (test). */
  checkInventoryLimit?: boolean;
}

/** Keyed by the legend rail entry id; 'mpas' is the protected-areas rule row. */
export const LAYER_FRESHNESS: Readonly<Record<string, LayerFreshness>> = {
  'seafloor': {cadence: 'legend.fresh.dated', limitHours: null, inventory: []},
  'currents': {cadence: 'legend.fresh.hourly', limitHours: 6, inventory: ['hfr-6km'], checkInventoryLimit: true},
  'water-temp': {cadence: 'legend.fresh.daily', limitHours: 72, inventory: ['sst-noaa-blended'], checkInventoryLimit: true},
  'sst-contrast': {cadence: 'legend.fresh.daily', limitHours: 72, inventory: ['sst-noaa-blended'], checkInventoryLimit: true},
  'sst-fronts': {cadence: 'legend.fresh.habitat', limitHours: 48, inventory: ['sst-fronts'], checkInventoryLimit: true},
  'chlorophyll': {cadence: 'legend.fresh.daily', limitHours: 96, inventory: ['chl-viirs-merged'], checkInventoryLimit: true},
  'swell': {cadence: 'legend.fresh.cycles', limitHours: 18, inventory: ['waves-gfswave-ecmwf-wam'], checkInventoryLimit: true},
  'stations': {cadence: 'legend.fresh.live', limitHours: 3, inventory: []},
  'fleet': {cadence: 'legend.fresh.dated', limitHours: null, inventory: []},
  'clouds': {cadence: 'legend.fresh.min5', limitHours: null, limitMinutes: 90, inventory: ['goes-ir']},
  'mpas': {cadence: 'legend.fresh.rules', limitHours: null, inventory: []},
};

/** "Updates: <cadence> · age limit <n>", or '' for an id without an entry. */
export function cadenceLine(id: string, lang: Language = 'en'): string {
  const f = LAYER_FRESHNESS[id];
  if (!f) return '';
  const line = t('legend.fresh.line', lang, {cadence: t(f.cadence, lang)});
  const limit = f.limitHours !== null ? `${f.limitHours} h` : f.limitMinutes !== undefined ? `${f.limitMinutes} min` : '';
  return limit ? `${line}${t('legend.fresh.limit', lang, {limit})}` : line;
}
