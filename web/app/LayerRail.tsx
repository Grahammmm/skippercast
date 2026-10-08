// Layer rail (FE-05, design § 6 and § 9): the six rail entries as toggles
// bound to the layers signal, each with its basis sentence. FE-11's registry
// takes over the entries, notes ("no fresh frame") and legend rows; until
// then the entries are the rail ids profile.ts names, with no data behind them.
// Currents (FE-15) is the one surface-current source choice, `?current=`, for
// the Chart and the terrain alike: the toggle turns the forecast on or the
// source off, and the source select picks exactly one product.
import {Rail, RailItem} from '../ui/Rail.tsx';
import {CURRENT_SOURCES, currentsState} from '../map/currents.ts';
import {currentStatus, shownPresentation} from '../map/stage.ts';
import {current, layers, layersParam, setParams, UNSUPPORTED} from '../state.ts';
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

export function LayerRail() {
  const on = layers.value, source = current.value;
  return (
    <Rail class="app-rail">
      {RAIL_ENTRIES.map(e => e.id === 'currents' ? (
        <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={source !== 'off'} basis={e.basis} note={source !== 'off' ? currentsNote() : undefined}
          onToggle={(_, next) => chooseCurrent(next ? 'wcofs' : 'off')}>
          {source !== 'off' ? <CurrentSource /> : null}
        </RailItem>
      ) : (
        <RailItem key={e.id} id={e.id} label={e.label} icon={e.icon} on={on.includes(e.id)} basis={e.basis}
          onToggle={(id, next) => setParams({layers: layersParam(toggled(layers.value, id, next))})} />
      ))}
    </Rail>
  );
}
