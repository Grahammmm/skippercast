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
// layer (FE-20); Currents draws in both.
// The base (§ 8, one at a time) is one select: Night (the token basemap alone),
// Chart detail (the ENC display from zoom 10) and Aerial where the region's
// package offers it (FE-23), so a link's `?base=chart` can be chosen again.
// The bases draw on the Chart only; `?base=aerial` where no aerial is offered
// shows Night, which is what draws.
import {Popover} from '../ui/Popover.tsx';
import {Rail, RailItem} from '../ui/Rail.tsx';
import {aerialOffer, flownText, type AerialBase} from '../map/aerial.ts';
import {ENC_MIN_ZOOM} from '../map/chart.ts';
import {CURRENT_SOURCES, currentsState} from '../map/currents.ts';
import {CHART_ONLY, drawsIn, layerEntry, railNotes} from '../map/layers.ts';
import {currentStatus, shownPresentation} from '../map/stage.ts';
import {base, current, DEFAULT_CURRENT, isBase, layers, layersParam, setParams, UNSUPPORTED, type Base} from '../state.ts';
import {RAIL_ENTRIES, railOn, toggled} from './rail.ts';

export {RAIL_ENTRIES, railOn, toggled, type RailEntry} from './rail.ts';

/** Choose a surface-current source; the rail's Currents entry is on exactly when one is chosen. */
export function chooseCurrent(value: string): void {
  setParams({current: value, layers: layersParam(toggled(layers.value, 'currents', value !== 'off'))});
}

/** The Currents entry's note: the Chart's frame state, or the terrain renderer's own status line. */
const currentsNote = (): string => shownPresentation.value === 'chart' ? currentsState.value.note : currentStatus.value;

function CurrentSource() {
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
            note={!here ? CHART_ONLY : railNotes.value[e.id] || undefined}
            onToggle={(id, next) => setParams({layers: layersParam(toggled(layers.value, id, next))})} />
        );
      })}
    </Rail>
  );
}
