// Legend (FE-05, design § 6): the map's one legend, a row per layer that is
// on with its swatch (app.css paints the ramps from the cartography tokens).
// A registry layer whose source failed (web/map/chart.ts `unavailable`, FE-11)
// is named here so the gap reads as missing data, never as empty water.
// Seafloor (FE-14) adds its key for the drawn view (terrain grade or the
// target's species fit, switchable here), the surveys and years drawn, the
// credits in its basis, and why nothing draws when the publication is held,
// updating or expired.
// Protected areas (FE-19) are always drawn on the Chart: their row says what
// the drawing covers (MpaRow), links the official rules page and carries the
// ds582 credit in its basis.
// Currents (FE-15) follows the source choice `?current=`; its row carries the
// drawn source's basis sentence, or why nothing draws.
import {current, layers} from '../state.ts';
import {chartFailed, unavailable} from '../map/chart.ts';
import {currentsState} from '../map/currents.ts';
import {layerEntry} from '../map/layers.ts';
import {CC_BY_4, CDFW_MPA_PAGE, DS582_METADATA, mpaState, shownMpaState} from '../map/mpa.ts';
import {legendKey, seafloorState, seafloorView, surveyLine} from '../map/seafloor.ts';
import {currentStatus, shownPresentation} from '../map/stage.ts';
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

/**
 * The protected areas' row: the check date, or what the drawing lacks, so a missing outline never reads as
 * open water. "Loading boundaries." until they load, "Map unavailable." without a map, and unavailable when
 * MapLibre failed to draw the checked data.
 */
export function MpaRow() {
  const s = shownMpaState(mpaState.value, {sourceFailed: unavailable.value.includes('mpas'), mapFailed: chartFailed.value});
  return (
    <li class="app-legend-mpa" data-mpa={s.status}>
      <span class="app-legend-mpa-head">
        <span class="app-swatch" data-layer="mpas" aria-hidden="true"></span>{layerEntry('mpas').label}
        <Popover iconOnly summary="Protected areas basis">
          {layerEntry('mpas').basis} {s.detail ? <>{s.detail} </> : null}Regional selection by SkipperCast from <a href={DS582_METADATA} target="_blank" rel="noopener">CDFW
          Marine Region GIS Lab, California MPAs ds582</a>, <a href={CC_BY_4} target="_blank" rel="noopener">CC BY 4.0</a>.
        </Popover>
      </span>
      {s.note ? <p class="app-mpa-note">{s.note}</p> : null}
      <a class="app-mpa-rules" href={CDFW_MPA_PAGE} target="_blank" rel="noopener">Official rules and boundaries (CDFW)</a>
    </li>
  );
}

function CurrentsRow() {
  const chart = shownPresentation.value === 'chart', state = currentsState.value, reason = chart ? state.reason : currentStatus.value;
  return (
    <li class="app-legend-currents">
      <span class="app-swatch" data-layer="currents" aria-hidden="true"></span>Currents
      <span class="app-swatch" data-layer="currents-fast" aria-hidden="true"></span>fastest fifth
      <Popover iconOnly summary="Currents basis">{chart ? state.basis : layerEntry('currents').basis}</Popover>
      {reason ? <p class="app-legend-note" data-reason="currents">{reason}</p> : null}
    </li>
  );
}

export function Legend() {
  const source = current.value, chart = shownPresentation.value === 'chart';
  const on = RAIL_ENTRIES.filter(e => e.id === 'currents' ? source !== 'off' : layers.value.includes(e.id));
  return (
    <section class="app-legend" aria-label="Legend">
      <span class="ui-eyebrow">Legend</span>
      {on.length || chart ? (
        <ul>
          {on.map(e => e.id === 'seafloor' ? <SeafloorRow key={e.id} /> : e.id === 'currents' ? <CurrentsRow key={e.id} />
            : <li key={e.id}><span class="app-swatch" data-layer={e.id} aria-hidden="true"></span>{e.label}</li>)}
          {chart ? <MpaRow /> : null}
        </ul>
      ) : <p class="app-empty">No layers on.</p>}
      {unavailable.value.filter(id => id !== 'mpas').map(id => <p key={id} class="app-empty" data-unavailable={id}>{layerEntry(id).label} unavailable.</p>)}
    </section>
  );
}
