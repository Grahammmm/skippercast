// Layer rail (FE-05, design § 6 and § 9): the six rail entries as toggles
// bound to the layers signal, each with its basis sentence. FE-11's registry
// takes over the entries, notes ("no fresh frame") and legend rows; until
// then the entries are the rail ids profile.ts names, with no data behind them.
import type {IconName} from '../ui/icons.tsx';
import {Rail, RailItem} from '../ui/Rail.tsx';
import {layerEntry} from '../map/layers.ts';
import {RAIL_IDS, type RailId} from '../profile.ts';
import {layers, layersParam, setParams} from '../state.ts';

export interface RailEntry {readonly id: RailId; readonly label: string; readonly icon: IconName; readonly basis: string}

/** Rail order and copy (§ 9); the basis sentences name product, resolution and age rule. */
export const RAIL_ENTRIES: readonly RailEntry[] = [
  {id: 'seafloor', label: 'Seafloor', icon: 'seafloor', basis: layerEntry('seafloor').basis},
  {id: 'currents', label: 'Currents', icon: 'current', basis: 'WCOFS surface forecast at about 4 km, or HF radar at 6 km when observed within the hour.'},
  {id: 'water-temp', label: 'Water temp', icon: 'temperature', basis: 'MUR daily analysis, 0.01°, sampled at 0.02°, with the analysis age shown.'},
  {id: 'swell', label: 'Swell', icon: 'wave', basis: 'Model wave forecast on the region grid; nearshore sites from the CDIP MOP model.'},
  {id: 'fleet', label: 'Charter fleet', icon: 'fleet', basis: 'Charter grounds and 2024 commercial AIS effort; activity is inferred from movement.'},
  {id: 'clouds', label: 'Clouds', icon: 'cloud', basis: 'GOES infrared, observed frames within 90 minutes; a loop of real frames, never a forecast.'},
];
for (const id of RAIL_IDS) if (!RAIL_ENTRIES.some(e => e.id === id)) throw new Error(`rail entry missing for ${id}`);

/** The rail list with `id` switched `on` or off, in rail order. */
export function toggled(current: readonly string[], id: string, on: boolean): string[] {
  const set = new Set(current);
  if (on) set.add(id); else set.delete(id);
  return RAIL_ENTRIES.map(e => e.id).filter(e => set.has(e));
}

export function LayerRail() {
  const on = layers.value;
  return (
    <Rail class="app-rail">
      {RAIL_ENTRIES.map(e => (
        <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={on.includes(e.id)} basis={e.basis}
          onToggle={(id, next) => setParams({layers: layersParam(toggled(layers.value, id, next))})} />
      ))}
    </Rail>
  );
}
