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
// ds582 credit in its basis. Where the region has reef marks for the target,
// the basis also says what the marks' run-time screen checked (#489,
// web/map/habitat.ts), and a stale or unavailable check adds a visible line
// saying the marks are withheld; the row stays one line while marks show.
// Currents (FE-15) follows the source choice `?current=`; its row carries the
// drawn source's basis sentence, or why nothing draws.
// The Clouds row labels the GOES frame on screen with its acquisition time and
// age and holds or resumes the loop (FE-22, web/map/clouds.ts).
// Water temp (FE-16) gives the drawn analysis's range in whole °F, its product,
// date and age, and the basis with its error, or why nothing draws.
// Swell (FE-17) gives the drawn hour's heights, periods and direction, its fixed
// colour scale, the model with its run, age and valid hour as a model forecast,
// and the basis, or why nothing draws.
import {IconButton} from '../ui/Button.tsx';
import {current, layers} from '../state.ts';
import {chartFailed, unavailable} from '../map/chart.ts';
import {cloudHeld, cloudStamp} from '../map/clouds.ts';
import {currentsState} from '../map/currents.ts';
import {layerEntry} from '../map/layers.ts';
import {markNote, markScreen} from '../map/marks.ts';
import {CC_BY_4, CDFW_MPA_PAGE, DS582_METADATA, mpaState, shownMpaState} from '../map/mpa.ts';
import {legendKey, seafloorState, seafloorView, surveyLine} from '../map/seafloor.ts';
import {waterTempState} from '../map/sst.ts';
import {HEIGHT_SCALE, frameSummary, swellState} from '../map/swell.ts';
import {WAVE_MODEL} from '../map/forecast-grid.ts';
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
  const marks = markNote.value, withheld = !!marks && (markScreen.value.status === 'stale' || markScreen.value.status === 'unavailable');
  return (
    <li class="app-legend-mpa" data-mpa={s.status}>
      <span class="app-legend-mpa-head">
        <span class="app-swatch" data-layer="mpas" aria-hidden="true"></span>{layerEntry('mpas').label}
        <Popover iconOnly summary="Protected areas basis">
          {layerEntry('mpas').basis} {s.detail ? <>{s.detail} </> : null}Regional selection by SkipperCast from <a href={DS582_METADATA} target="_blank" rel="noopener">CDFW
          Marine Region GIS Lab, California MPAs ds582</a>, <a href={CC_BY_4} target="_blank" rel="noopener">CC BY 4.0</a>.
          {marks && !withheld ? <p data-reason="marks">{marks}</p> : null}
        </Popover>
      </span>
      {s.note ? <p class="app-mpa-note">{s.note}</p> : null}
      {withheld ? <p class="app-mpa-marks" data-reason="marks">{marks}</p> : null}
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

/** The Water temp row: the drawn analysis's range, product and age, or why nothing draws (the Chart only). */
function WaterTempRow() {
  const s = waterTempState.value, chart = shownPresentation.value === 'chart', a = chart ? s.drawn : null;
  const reason = chart ? s.reason : 'Water temp draws on the Chart.';
  return (
    <li class="app-legend-water-temp">
      <span class="app-swatch" data-layer="water-temp" aria-hidden="true"></span>Water temp
      {a ? <span class="app-legend-range ui-mono" data-range="water-temp">{a.range[0]}–{a.range[1]} °F</span> : null}
      <Popover iconOnly summary="Water temp basis">{s.basis}</Popover>
      {a ? <p class="app-legend-note ui-mono" data-stamp="water-temp">{a.product} · {a.stamp}</p> : null}
      {reason ? <p class="app-legend-note" data-reason="water-temp">{reason}</p> : null}
    </li>
  );
}

/** The Swell row: the drawn hour's reading, scale, model run and valid hour, or why nothing draws (the Chart only). */
function SwellRow() {
  const s = swellState.value, chart = shownPresentation.value === 'chart', f = chart ? s.drawn : null;
  const reason = chart ? s.reason : 'Swell draws on the Chart.';
  return (
    <li class="app-legend-swell">
      <span class="app-swatch" data-layer="swell" aria-hidden="true"></span>Swell
      <Popover iconOnly summary="Swell basis">{s.basis}</Popover>
      {f ? <p class="app-legend-note app-legend-range ui-mono" data-range="swell">{frameSummary(f)}</p> : null}
      {f ? <p class="app-legend-note ui-mono app-legend-scale" data-scale="swell">{HEIGHT_SCALE[0]} ft<span class="app-swatch" data-layer="swell" aria-hidden="true"></span><span class="app-visually-hidden"> to </span>{HEIGHT_SCALE[1]}+ ft</p> : null}
      {f ? <p class="app-legend-note ui-mono" data-stamp="swell">{WAVE_MODEL.name} model forecast · {f.stamp}</p> : null}
      {reason ? <p class="app-legend-note" data-reason="swell">{reason}</p> : null}
    </li>
  );
}

/** The Clouds row: the frame drawn now, and the loop toggle while more than one frame can play. */
export function CloudsRow({label}: {label: string}) {
  const stamp = cloudStamp.value;
  return (
    <>
      <span class="app-legend-text">{label}{stamp ? <span class="app-legend-note ui-mono">{stamp.label}</span> : null}</span>
      {stamp?.canLoop ? <IconButton icon={cloudHeld.value ? 'play' : 'pause'} label="Cloud loop" pressed={!cloudHeld.value} size="sm"
        onClick={() => { cloudHeld.value = !cloudHeld.value; }} /> : null}
    </>
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
          {on.map(e => e.id === 'seafloor' ? <SeafloorRow key={e.id} /> : e.id === 'currents' ? <CurrentsRow key={e.id} /> : e.id === 'water-temp' ? <WaterTempRow key={e.id} /> : e.id === 'swell' ? <SwellRow key={e.id} />
            : <li key={e.id}><span class="app-swatch" data-layer={e.id} aria-hidden="true"></span>{e.id === 'clouds' ? <CloudsRow label={e.label} /> : e.label}</li>)}
          {chart ? <MpaRow /> : null}
        </ul>
      ) : <p class="app-empty">No layers on.</p>}
      {unavailable.value.filter(id => id !== 'mpas').map(id => <p key={id} class="app-empty" data-unavailable={id}>{layerEntry(id).label} unavailable.</p>)}
    </section>
  );
}
