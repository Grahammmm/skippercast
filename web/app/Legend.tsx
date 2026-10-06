// Legend (FE-05, design § 6): the map's one legend, a row per layer that is
// on with its swatch (app.css paints the ramps from the cartography tokens).
// FE-11's registry supplies the real entries and the attribution row.
import {layers} from '../state.ts';
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
    </section>
  );
}
