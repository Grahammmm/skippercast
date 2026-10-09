// Legend (FE-05, design § 6): the map's one legend, a row per layer that is
// on with its swatch (app.css paints the ramps from the cartography tokens).
// A registry layer whose source failed (web/map/chart.ts `unavailable`, FE-11)
// is named here so the gap reads as missing data, never as empty water.
import {layers} from '../state.ts';
import {unavailable} from '../map/chart.ts';
import {layerEntry} from '../map/layers.ts';
import {RAIL_ENTRIES} from './LayerRail.tsx';

export function Legend() {
  const on = RAIL_ENTRIES.filter(e => layers.value.includes(e.id));
  return (
    <section class="app-legend" aria-label="Legend">
      <span class="ui-eyebrow">Legend</span>
      {on.length ? (
        <ul>
          {on.map(e => <li key={e.id}><span class="app-swatch" data-layer={e.id} aria-hidden="true"></span>{e.label}</li>)}
        </ul>
      ) : <p class="app-empty">No layers on.</p>}
      {unavailable.value.map(id => <p key={id} class="app-empty" data-unavailable={id}>{layerEntry(id).label} unavailable.</p>)}
    </section>
  );
}
