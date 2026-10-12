// The rail's entries (FE-05, design § 6 and § 9) in rail order with their
// basis sentences, kept apart from web/app/LayerRail.tsx so that importing
// them (the landing's layer dots are checked against them) loads no map code.
//
// Erasable syntax only.
import type {IconName} from '../ui/icons.tsx';
import {RAIL_IDS, type RailId} from '../profile.ts';
import {layerEntry} from '../map/layers.ts';

export interface RailEntry {readonly id: RailId; readonly label: string; readonly icon: IconName; readonly basis: string}

/** Rail order and copy (§ 9); the basis sentences name product, resolution and age rule. */
export const RAIL_ENTRIES: readonly RailEntry[] = [
  {id: 'seafloor', label: 'Seafloor', icon: 'seafloor', basis: layerEntry('seafloor').basis},
  {id: 'currents', label: 'Currents', icon: 'current', basis: layerEntry('currents').basis},
  {id: 'water-temp', label: 'Water temp', icon: 'temperature', basis: layerEntry('water-temp').basis},
  {id: 'swell', label: 'Swell', icon: 'wave', basis: layerEntry('swell').basis},
  {id: 'fleet', label: 'Charter fleet', icon: 'fleet', basis: 'Charter grounds and 2024 commercial AIS effort; activity is inferred from movement.'},
  {id: 'clouds', label: 'Clouds', icon: 'cloud', basis: 'GOES infrared, observed frames within 90 minutes; a loop of real frames, never a forecast.'},
];
for (const id of RAIL_IDS) if (!RAIL_ENTRIES.some(e => e.id === id)) throw new Error(`rail entry missing for ${id}`);

/** Whether rail entry `id` is on: Currents while a source is chosen (FE-15), any other entry while the rail list has it. */
export const railOn = (id: string, on: readonly string[], source: string): boolean => id === 'currents' ? source !== 'off' : on.includes(id);

/** The rail list with `id` switched `on` or off, in rail order. */
export function toggled(current: readonly string[], id: string, on: boolean): string[] {
  const set = new Set(current);
  if (on) set.add(id); else set.delete(id);
  return RAIL_ENTRIES.map(e => e.id).filter(e => set.has(e));
}
