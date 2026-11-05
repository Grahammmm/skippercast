// The rail's entries (FE-05, design § 6 and § 9) in rail order with their
// basis sentences, kept apart from web/app/LayerRail.tsx so that importing
// them (the landing's layer dots are checked against them) loads no map code.
//
// Erasable syntax only.
import type {IconName} from '../ui/icons.tsx';
import {t, type Language} from '../i18n.ts';
import {RAIL_IDS, type RailId} from '../profile.ts';
import {layerCopy} from '../map/layers.ts';

export interface RailEntry {readonly id: RailId; readonly label: string; readonly icon: IconName; readonly basis: string}

/** The rail's entries in `lang`, in rail order (§ 9); the basis sentences name product, resolution and age rule. Swell + wind joins both registry bases. */
export function railEntries(lang: Language = 'en'): readonly RailEntry[] {
  const c = (id: string) => layerCopy(id, lang);
  return [
    {id: 'seafloor', label: c('seafloor').label, icon: 'seafloor', basis: c('seafloor').basis},
    {id: 'currents', label: c('currents').label, icon: 'current', basis: c('currents').basis},
    {id: 'water-temp', label: c('water-temp').label, icon: 'temperature', basis: c('water-temp').basis},
    {id: 'sst-contrast', label: c('sst-contrast').label, icon: 'temperature', basis: c('sst-contrast').basis},
    {id: 'sst-fronts', label: c('sst-fronts').label, icon: 'temperature', basis: c('sst-fronts').basis},
    {id: 'chlorophyll', label: c('chlorophyll').label, icon: 'map', basis: c('chlorophyll').basis},
    {id: 'swell', label: t('rail.swell.label', lang), icon: 'wave', basis: `${c('swell').basis} ${c('wind').basis}`},
    {id: 'stations', label: c('stations').label, icon: 'target', basis: c('stations').basis},
    {id: 'fleet', label: t('rail.fleet.label', lang), icon: 'fleet', basis: t('rail.fleet.basis', lang)},
    {id: 'clouds', label: c('clouds').label, icon: 'cloud', basis: c('clouds').basis},
  ];
}

/** The English list, kept as the compatibility export (the landing's layer dots and the tests read it). */
export const RAIL_ENTRIES: readonly RailEntry[] = railEntries('en');
for (const id of RAIL_IDS) if (!RAIL_ENTRIES.some(e => e.id === id)) throw new Error(`rail entry missing for ${id}`);

/** Whether rail entry `id` is on: Currents while a source is chosen (FE-15), any other entry while the rail list has it. */
export const railOn = (id: string, on: readonly string[], source: string): boolean => id === 'currents' ? source !== 'off' : on.includes(id);

/** The rail list with `id` switched `on` or off, in rail order. */
export function toggled(current: readonly string[], id: string, on: boolean): string[] {
  const set = new Set(current);
  if (on) set.add(id); else set.delete(id);
  return RAIL_ENTRIES.map(e => e.id).filter(e => set.has(e));
}
