// Layer rail (FE-05, FE-20; design § 6, § 8 and § 9): the six rail entries as
// toggles bound to `?layers=`, each with its basis sentence in an info popover,
// then the one base choice.
// Currents (FE-15) is the one surface-current source choice, `?current=`, for
// the Chart and the terrain alike: the toggle turns the forecast on or the
// source off, and the source select picks exactly one product.
// Any other layer that draws says under its name what it shows or why it cannot
// (web/map/layers.ts railNotes; Clouds, FE-22: the newest observed frame).
// In Terrain 2D and 3D an entry none of whose layers draws there (layers.ts
// drawsIn) reads "Chart only" and is disabled, so it never toggles a hidden
// layer (FE-20); Currents draws in both, and Seafloor holds the terrain's options (FE-80).
// Charter fleet (FE-21): the public charter grounds draw while it is on; its
// option adds v1's commercial AIS 2024 cells, off by default as in v1. For an
// admin whose session v1's `fleetAccess` admits (both fleet flags on, FE-24) it
// also offers the three activity layers, off by default as in v1; for anyone
// else they are absent, not disabled.
// FE-80: in Terrain 2D and 3D the Seafloor entry holds the renderer's own options
// (FE-79's host chrome): seabed relief, water and its opacity, depth contours,
// source coverage, and reefs and species pins, which the entry's toggle also
// hides. They draw only in the terrain, so the Chart shows none of them.
// The base (§ 8, one at a time) is one select: Night (the token basemap alone),
// Chart detail (the ENC display from zoom 10) and Aerial where the region's
// package offers it (FE-23), so a link's `?base=chart` can be chosen again.
// The bases draw on the Chart only; `?base=aerial` where no aerial is offered
// shows Night, which is what draws.
import {Popover} from '../ui/Popover.tsx';
import {Rail, RailItem} from '../ui/Rail.tsx';
import {aerialOffer, flownText, type AerialBase} from '../map/aerial.ts';
import {ENC_MIN_ZOOM} from '../map/chart.ts';
import {aisOn, aisState} from '../map/commercial-ais.ts';
import {CURRENT_SOURCES, currentsState} from '../map/currents.ts';
import {ACTIVITY, ACTIVITY_ENTRY, activityAccess, activityOn, toggleActivity} from '../map/fleet.ts';
import {CHART_ONLY, drawsIn, layerEntry, railNotes} from '../map/layers.ts';
import {currentStatus, setTerrainOption, shownPresentation, terrainOptions} from '../map/stage.ts';
import {base, current, DEFAULT_CURRENT, isBase, layers, layersParam, setParams, UNSUPPORTED, type Base} from '../state.ts';
import {RAIL_ENTRIES, railOn, toggled} from './rail.ts';

export {RAIL_ENTRIES, railOn, toggled, type RailEntry} from './rail.ts';

/** Choose a surface-current source; the rail's Currents entry is on exactly when one is chosen. */
export function chooseCurrent(value: string): void {
  setParams({current: value, layers: layersParam(toggled(layers.value, 'currents', value !== 'off'))});
}

/** The Currents entry's note: the Chart's frame state, or the terrain renderer's own status line. */
const currentsNote = (): string => shownPresentation.value === 'chart' ? currentsState.value.note : currentStatus.value;

/** The one `?current=` control, shared by the Currents rail entry and the Conditions view (FE-32). */
export function CurrentSource() {
  const value = current.value;
  return (
    <label class="app-rail-source">Source
      <select value={value} onChange={event => chooseCurrent((event.currentTarget as HTMLSelectElement).value)}>
        {CURRENT_SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        {value === UNSUPPORTED ? <option value={UNSUPPORTED}>Unsupported source</option> : null}
      </select>
    </label>
  );
}

/** The Charter fleet entry's option (FE-21): v1's commercial AIS layer, off by default. */
function AisOption() {
  return (
    <label class="app-rail-option">
      <input type="checkbox" checked={aisOn.value} onChange={event => { aisOn.value = (event.currentTarget as HTMLInputElement).checked; }} />
      {layerEntry('commercial-ais').label}
    </label>
  );
}

/**
 * The Charter fleet entry's options: commercial AIS where the region has it (FE-21) and, once v1's access check has
 * answered for this viewer, the admin activity layers (FE-24). Their box takes no width of its own (app.css), so
 * wrapped options never widen the rail.
 */
function FleetOptions() {
  const ais = aisState.value.offered, admin = activityAccess.value, on = activityOn.value;
  if (!ais && !admin) return null;
  return (
    <div class="app-rail-options">
      {ais ? <AisOption /> : null}
      {admin ? ACTIVITY.map(name => (
        <label key={name} class="app-rail-option">
          <input type="checkbox" checked={on.includes(name)} onChange={event => toggleActivity(name, (event.currentTarget as HTMLInputElement).checked)} />
          {layerEntry(ACTIVITY_ENTRY[name]).label} · admin
        </label>
      )) : null}
    </div>
  );
}

/** A checkbox option under a rail entry. */
function Option({label, checked, disabled, onChange}: {label: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void}) {
  return (
    <label class="app-rail-option">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={event => onChange((event.currentTarget as HTMLInputElement).checked)} />
      {label}
    </label>
  );
}

/** A range option: its label and value above the slider, then what each end means. */
function Range({id, label, value, text, min, max, step, ends, onInput}: {
  id: string; label: string; value: number; text: string; min: number; max: number; step: number; ends?: readonly [string, string]; onInput: (value: number) => void;
}) {
  return (
    <div class="app-rail-range">
      <label for={id}>{label} <b class="ui-mono">{text}</b></label>
      <input id={id} type="range" min={min} max={max} step={step} value={value} aria-valuetext={text}
        onInput={event => onInput(Number((event.currentTarget as HTMLInputElement).value))} />
      {ends ? <span class="app-rail-ends" aria-hidden="true"><span>{ends[0]}</span><span>{ends[1]}</span></span> : null}
    </div>
  );
}

/** The terrain's options under the Seafloor entry (FE-80), with the native panel's labels and notes, in a disclosure so the rail stays short. */
export function TerrainOptions({on}: {on: boolean}) {
  const o = terrainOptions.value;
  return (
    <details class="app-rail-options app-rail-terrain">
      <summary class="app-rail-option">Terrain options</summary>
      <div class="app-rail-terrain-body">
      <Range id="terrain-relief" label="Seabed relief" value={o.relief} text={`×${o.relief}`} min={1} max={12} step={1} ends={['True scale', 'Emphasized']}
        onInput={v => setTerrainOption('relief', v)} />
      <Option label="Water & channels" checked={o.water} onChange={v => setTerrainOption('water', v)} />
      {o.water ? <Range id="terrain-water" label="Water opacity" value={o.waterOpacity} text={`${Math.round(o.waterOpacity * 100)}%`} min={0} max={0.8} step={0.05}
        onInput={v => setTerrainOption('waterOpacity', v)} /> : null}
      <p class="app-rail-hint">Illustrative +0.8 m water surface. Not a live tide.</p>
      <Option label="Depth contours · 10 / 30 / 500 ft" checked={o.contours} onChange={v => setTerrainOption('contours', v)} />
      <Option label="Source coverage" checked={o.sourceCoverage} onChange={v => setTerrainOption('sourceCoverage', v)} />
      <Option label="Reefs & species pins" checked={o.habitat && on} disabled={!on} onChange={v => setTerrainOption('habitat', v)} />
      </div>
    </details>
  );
}

/** The bases offered here: Night and Chart detail everywhere, Aerial where the region's package names one. */
export function baseOptions(offer: AerialBase | null): {value: Base; label: string}[] {
  return [{value: 'night', label: 'Night'}, {value: 'chart', label: 'Chart detail'}, ...(offer ? [{value: 'aerial' as const, label: 'Aerial'}] : [])];
}
/** The base the Chart draws for `?base=`: an aerial base no region offers leaves the token basemap alone. */
export const shownBase = (chosen: Base, offer: AerialBase | null): Base => chosen === 'aerial' && !offer ? 'night' : chosen;
/** The base's note: why it draws nothing here, the imagery's dates, or the chart's zoom gate. */
export function baseNote(shown: Base, offer: AerialBase | null, drawn: boolean): string {
  if (!drawn) return CHART_ONLY;
  if (shown === 'aerial' && offer) return flownText(offer);
  return shown === 'chart' ? `from zoom ${ENC_MIN_ZOOM}` : '';
}
const BASE_NOTE = 'app-rail-base-note';

function BaseChoice() {
  const offer = aerialOffer.value, drawn = drawsIn('base', shownPresentation.value);
  const value = shownBase(base.value, offer), note = baseNote(value, offer, drawn);
  return (
    <div class="app-rail-base">
      <label class="app-rail-source">Base
        <select value={value} disabled={!drawn} aria-describedby={note ? BASE_NOTE : undefined}
          onChange={event => { const next = (event.currentTarget as HTMLSelectElement).value; if (isBase(next)) setParams({base: next}); }}>
          {baseOptions(offer).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </label>
      <Popover iconOnly align="end" summary="Base basis">
        <p>Night: {layerEntry('basemap').basis}</p>
        <p>Chart detail: {layerEntry('chart').basis}</p>
        {offer ? <p>Aerial: {layerEntry('aerial').basis} {offer.note} Coverage checked {offer.checkedAt}. While it is on, the browser requests its tiles from USGS.</p> : null}
      </Popover>
      {note ? <span id={BASE_NOTE} class="ui-rail-note ui-mono">{note}</span> : null}
    </div>
  );
}

export function LayerRail() {
  const on = layers.value, source = current.value, shown = shownPresentation.value;
  return (
    <Rail class="app-rail" footer={<BaseChoice />}>
      {RAIL_ENTRIES.map(e => {
        const here = drawsIn(e.id, shown), active = railOn(e.id, on, source);
        return e.id === 'currents' ? (
          <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={active} basis={e.basis} disabled={!here}
            note={!here ? CHART_ONLY : active ? currentsNote() : undefined} onToggle={(_, next) => chooseCurrent(next ? DEFAULT_CURRENT : 'off')}>
            {active && here ? <CurrentSource /> : null}
          </RailItem>
        ) : (
          <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={active} basis={e.basis} disabled={!here}
            note={!here ? CHART_ONLY : e.id === 'seafloor' && shown !== 'chart' ? undefined : railNotes.value[e.id] || undefined}
            onToggle={(id, next) => setParams({layers: layersParam(toggled(layers.value, id, next))})}>
            {e.id === 'fleet' && active && here ? <FleetOptions /> : null}
            {e.id === 'seafloor' && shown !== 'chart' ? <TerrainOptions on={active} /> : null}
          </RailItem>
        );
      })}
    </Rail>
  );
}
