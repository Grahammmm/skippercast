// SC1722-02: admit the static sources a legacy component fixture set on the raw signals as one terminal source snapshot, through the
// real controller (start, then each source settled under its own ticket). Only for component fixtures whose sources are already
// terminal; lifecycle tests drive the real producers instead (test_verdict_settled.mjs).
import {dailyFeed, regionalForecast, regionalForecastState, verdictLoad} from '../../web/brief/Brief.tsx';
import {regionInfo} from '../../web/app/region-info.ts';
export function admitBriefFixture(info = regionInfo.peek()): void {
  verdictLoad.reset();
  if (!info) return;
  const feed = dailyFeed.peek(), forecast = regionalForecast.peek(), state = regionalForecastState.peek();
  verdictLoad.start(info.id);
  const {tickets} = verdictLoad.peek()!;
  verdictLoad.settle(tickets.metadata, 'metadata', {state: 'loaded', data: info});
  verdictLoad.settle(tickets.daily, 'daily', feed ? {state: 'loaded', data: {feed, savedAt: null}} : {state: 'failed'});
  verdictLoad.settle(tickets.conditions, 'conditions', {state: 'absent'});
  verdictLoad.settle(tickets.coast, 'coast', {state: 'absent'});
  // A read still loading stays pending; a failed one is failed; otherwise the fixture's forecast (none set: no forecast to read).
  if (state.region === info.id && state.state === 'loading') return;
  verdictLoad.settle(tickets.forecast, 'forecast', state.region === info.id && state.state === 'failed' ? {state: 'failed', reason: state.reason, status: state.status}
    : forecast ? {state: 'loaded', data: {forecast, savedAt: null}} : {state: 'absent'});
}
