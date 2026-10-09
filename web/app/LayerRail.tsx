// Layer rail (FE-05, design § 6 and § 9): the six rail entries as toggles
// bound to the layers signal, each with its basis sentence. FE-11's registry
// takes over the entries, notes ("no fresh frame") and legend rows; until
// then the entries are the rail ids profile.ts names, with no data behind them.
// Currents (FE-15) is the one surface-current source choice, `?current=`, for
// the Chart and the terrain alike: the toggle turns the forecast on or the
// source off, and the source select picks exactly one product.
// Any other layer that draws says under its name what it shows or why it cannot
// (web/map/layers.ts railNotes; Clouds, FE-22: the newest observed frame).
// Aerial (FE-23) is a base, not a rail id: offered only where the region's
// package names one, it writes `?base=aerial` (one base at a time, § 8) and its
// note is the imagery's acquisition window.
import {Rail, RailItem} from '../ui/Rail.tsx';
import {aerialOffer, flownText, type AerialBase} from '../map/aerial.ts';
import {CURRENT_SOURCES, currentsState} from '../map/currents.ts';
import {layerEntry, railNotes} from '../map/layers.ts';
import {currentStatus, shownPresentation} from '../map/stage.ts';
import {base, current, layers, layersParam, setParams, UNSUPPORTED} from '../state.ts';
import {RAIL_ENTRIES, toggled} from './rail.ts';

export {RAIL_ENTRIES, toggled, type RailEntry} from './rail.ts';

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

/** The Aerial base: on, it replaces any other base; off, the token basemap draws alone. */
function AerialEntry({offer}: {offer: AerialBase}) {
  const entry = layerEntry('aerial');
  return (
    <RailItem id="aerial" label={entry.label} icon="map" on={base.value === 'aerial'} note={flownText(offer)}
      basis={<>{entry.basis} {offer.note} Coverage checked {offer.checkedAt}. While it is on, the browser requests its tiles from USGS.</>}
      onToggle={(_, next) => setParams({base: next ? 'aerial' : 'night'})} />
  );
}

export function LayerRail() {
  const on = layers.value, source = current.value, aerial = aerialOffer.value;
  return (
    <Rail class="app-rail">
      {RAIL_ENTRIES.map(e => e.id === 'currents' ? (
        <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={source !== 'off'} basis={e.basis} note={source !== 'off' ? currentsNote() : undefined}
          onToggle={(_, next) => chooseCurrent(next ? 'wcofs' : 'off')}>
          {source !== 'off' ? <CurrentSource /> : null}
        </RailItem>
      ) : (
        <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={on.includes(e.id)} basis={e.basis} note={railNotes.value[e.id] || undefined}
          onToggle={(id, next) => setParams({layers: layersParam(toggled(layers.value, id, next))})} />
      ))}
      {aerial ? <AerialEntry offer={aerial} /> : null}
    </Rail>
  );
}
