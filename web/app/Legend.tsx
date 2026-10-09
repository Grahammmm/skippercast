// Legend (FE-05, design § 6): the map's one legend, a row per layer that is
// on with its swatch (app.css paints the ramps from the cartography tokens).
// A registry layer whose source failed (web/map/chart.ts `unavailable`, FE-11)
// is named here so the gap reads as missing data, never as empty water.
// Seafloor (FE-14) adds its key for the drawn view (terrain grade or the
// target's species fit, switchable here), the surveys and years drawn, the
// credits in its basis, and why nothing draws when the publication is held,
// updating or expired.
import {layers} from '../state.ts';
import {unavailable} from '../map/chart.ts';
import {layerEntry} from '../map/layers.ts';
import {legendKey, seafloorState, seafloorView, surveyLine} from '../map/seafloor.ts';
import {Segmented} from '../ui/Chip.tsx';
import {Popover} from '../ui/Popover.tsx';
import {RAIL_ENTRIES} from './LayerRail.tsx';

function SeafloorRow() {
  const s = seafloorState.value, ready = s.status === 'ready' && s.drawn > 0;
  return (
    <li class="app-legend-seafloor">
      <span class="app-swatch" data-layer="seafloor" aria-hidden="true"></span>Seafloor
      <Popover iconOnly summary="Seafloor basis">
        <p>{layerEntry('seafloor').basis}</p>
        {s.credits.map(credit => <p key={credit}>{credit}</p>)}
      </Popover>
      {ready ? (
        <div class="app-legend-detail">
          {s.fit ? <Segmented label="Colour seafloor by" value={s.view} onChange={v => { seafloorView.value = v; }}
            options={[{value: 'terrain', label: 'Terrain grade'}, {value: 'fit', label: `${s.fit[0]!.toUpperCase()}${s.fit.slice(1)} fit`}]} /> : null}
          <p class="app-legend-title">{s.view === 'fit' ? 'Physical habitat fit, not catch probability' : 'Terrain grade'}</p>
          <ul>{legendKey(s.view).map(([tone, label]) => <li key={tone}><span class="app-key" data-tone={tone} aria-hidden="true"></span>{label}</li>)}</ul>
          {s.surveys.length ? <p class="app-legend-note" data-surveys="seafloor">{surveyLine(s.surveys)}</p> : null}
        </div>
      ) : null}
      {s.note ? <p class="app-legend-note" data-reason="seafloor">{s.note}</p> : null}
    </li>
  );
}

export function Legend() {
  const on = RAIL_ENTRIES.filter(e => layers.value.includes(e.id));
  return (
    <section class="app-legend" aria-label="Legend">
      <span class="ui-eyebrow">Legend</span>
      {on.length ? (
        <ul>
          {on.map(e => e.id === 'seafloor' ? <SeafloorRow key={e.id} /> : <li key={e.id}><span class="app-swatch" data-layer={e.id} aria-hidden="true"></span>{e.label}</li>)}
        </ul>
      ) : <p class="app-empty">No layers on.</p>}
      {unavailable.value.map(id => <p key={id} class="app-empty" data-unavailable={id}>{layerEntry(id).label} unavailable.</p>)}
    </section>
  );
}
