// History view (FE-35, docs/plans/front-end/design.md § 10): packages/coast
// `historyView` over the coast bridge's history snapshot (/api/coast/history,
// loaded by web/coast-data.ts), mounted through CoastMarkup. Its station,
// measurement and day-range pickers write ?station=, ?metric= and ?range=
// with a history entry, so Back and Forward step through the choices. The
// snapshot is admitted only where a local report binds the region (Morro Bay
// and Cambria today, NDBC 46028 and 46215); elsewhere, or before and after a
// failed read, the view says recorded history is unavailable and why.
import {useEffect} from 'preact/hooks';
import {counties} from '../../../packages/coast/src/counties.ts';
import type {HistoryBundle, HistoryMetric} from '../../../packages/coast/src/history-types.ts';
import type {HistorySelection} from '../../../packages/coast/src/ui/history.ts';
import type {County} from '../../../packages/coast/src/types.ts';
import {coastData, coastHistory, coastStatus, type CoastSnapshot, type CoastStatus} from '../../coast-data.ts';
import {regionPlace} from '../../map/currents.ts';
import {historyMetric, historyRange, historyStation, navigate, profile, species, withParams, type UrlKey} from '../../state.ts';
import {regionInfo} from '../App.tsx';
import {CoastMarkup, isRenderableHistory, type CoastSelection} from '../CoastMarkup.tsx';

/** The measurements historyView lists, in its order; anything else falls back to its default (sea temperature). */
export const HISTORY_METRICS: readonly HistoryMetric[] = ['waterTempF', 'waveFt', 'windKnots', 'airTempF', 'gustKnots', 'periodS'];
/** The day ranges FE-42 publishes and historyView offers. */
export const HISTORY_RANGES = [7, 14, 45] as const;
const DEFAULT_RANGE = 45;

/** The view's selection from the store's raw ?station=, ?metric= and ?range=; an unlisted value takes the default. */
export function historySelection(station: string | null, metric: string | null, range: string | null): HistorySelection {
  const days = Number(range);
  return {
    station: station ?? '',
    metric: HISTORY_METRICS.find(m => m === metric) ?? 'waterTempF',
    days: (HISTORY_RANGES as readonly number[]).includes(days) ? days : DEFAULT_RANGE,
  };
}

/** The address change a picker makes: one store key, the others kept. */
export function historyPatch(choice: CoastSelection): Partial<Record<UrlKey, string>> | null {
  if (choice.name === 'history-station') return {station: choice.value};
  if (choice.name === 'history-metric') return {metric: choice.value};
  if (choice.name === 'history-days') return {range: choice.value};
  return null;
}

export type HistoryState =
  | {kind: 'ready'; bundle: HistoryBundle; county: County}
  | {kind: 'unbound' | 'loading' | 'unavailable'};

/** What the view shows for a snapshot and its status: the record, or which unavailable state. */
export function historyState(snapshot: CoastSnapshot<'history'> | null, status: CoastStatus): HistoryState {
  const bundle = snapshot?.data ?? null, county = bundle ? counties[bundle.countyId] : undefined;
  if (bundle && county && isRenderableHistory(bundle)) return {kind: 'ready', bundle, county};
  if (status === 'unbound') return {kind: 'unbound'};
  if (status === 'idle' || status === 'loading') return {kind: 'loading'};
  return {kind: 'unavailable'};
}

const NOTES: Record<Exclude<HistoryState['kind'], 'ready'>, string> = {
  unbound: 'Recorded history is unavailable for this region. SkipperCast collects buoy history only where a local coast report covers the area (Morro Bay and Cambria today).',
  loading: 'Loading recorded history…',
  unavailable: 'Recorded history is unavailable right now: the history snapshot could not be read or is out of date.',
};

/** Ask for the history snapshot for the region's place while the view is shown. */
function useHistorySnapshot(): void {
  const info = regionInfo.value, p = profile.value, target = species.value ?? '';
  useEffect(() => {
    const place = regionPlace(info, p, target);
    if (!place) return;
    coastData.setPlace(place);
    void coastData.load('history');
  }, [info, p, target]);
}

export function History({now = new Date()}: {now?: Date} = {}) {
  useHistorySnapshot();
  const state = historyState(coastHistory.value, coastStatus.value.history);
  const selection = historySelection(historyStation.value, historyMetric.value, historyRange.value);
  const choose = (choice: CoastSelection) => {
    const patch = historyPatch(choice);
    if (patch) navigate(withParams(location.href, patch));
  };
  return (
    <section class="app-history" aria-labelledby="app-history-title">
      <h2 id="app-history-title">Recorded history</h2>
      {state.kind === 'ready'
        ? <CoastMarkup renderer="historyView" args={[{county: state.county, now}, state.bundle, selection]} onSelect={choose} />
        : <p class="app-empty" role="status">{NOTES[state.kind]}</p>}
    </section>
  );
}
