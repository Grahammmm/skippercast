// Synthetic private records only; no account or provider access.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {tripRecaps, dateRange} from '../web/alerts.ts';
import {DEFAULT_ZONE} from '../web/zone.ts';

const trip = (id, date) => ({id, date, point: 'synthetic', species: 'reef', start_hour: 7, end_hour: 13});
const event = (id, trip_id, kind) => ({id, trip_id, kind, status: 'in-app', message: `Synthetic ${id}`});
const report = (observed_at, rating = 7) => ({observed_at, rating, context: '{"phase":"fishing"}'});
const today = '2026-11-02';

test('Pacific yesterday, today and tomorrow split and sort without mutating inputs', () => {
  const trips = [trip('tomorrow', '2026-11-03'), trip('yesterday', '2026-11-01'), trip('older', '2026-10-31'), trip('today', today)];
  const original = trips.slice();
  // UTC Nov 3 is still Nov 2 in Pacific.
  const localToday = dateRange(DEFAULT_ZONE, Date.parse('2026-11-03T07:30:00Z')).min;
  assert.equal(localToday, today);
  const got = tripRecaps(trips, [], [], localToday);
  assert.deepEqual(got.upcoming.map(t => t.id), ['today', 'tomorrow']);
  assert.deepEqual(got.past.map(r => r.trip.id), ['yesterday', 'older']);
  assert.deepEqual(trips, original);
});

test('final beats missed-final regardless of position; latest array entry of each kind wins', () => {
  const trips = ['a', 'b', 'c'].map(id => trip(id, '2026-11-01'));
  const events = [event(1, 'a', 'final'), event(2, 'a', 'final'), event(3, 'a', 'missed-final'), event(4, 'b', 'missed-final'), event(5, 'b', 'missed-final'), event(6, 'c', 'initial')];
  const got = tripRecaps(trips, events, [], today).past;
  assert.equal(got[0].final, events[1]);
  assert.equal(got[1].final, events[4]);
  assert.equal(got[2].final, null);
  assert.equal(tripRecaps(trips, [events[2], events[0]], [], today).past[0].final, events[0]);
});

test('missing/deleted trip ids and unrelated kinds cannot supply a recap; source events remain', () => {
  const events = [event(1, undefined, 'final'), event(2, 'deleted', 'final'), event(3, 'a', 'update'), event(4, 'a', 'retraction')];
  const got = tripRecaps([trip('a', '2026-11-01')], events, [], today);
  assert.equal(got.past[0].final, null);
  assert.equal(events.length, 4);
  assert.deepEqual(tripRecaps([], events, [], today), {upcoming: [], past: []});
});

test('Pacific late-night reports stay on their trip date; DST repeated hour and invalid dates', () => {
  const feedback = [report('2026-10-31T06:30:00Z'), report('2026-10-31T07:10:00Z'),
    report('2026-11-01T07:30:00Z'), report('2026-11-01T08:30:00Z'), report('2026-11-01T09:30:00Z'),
    report('2026-11-02T07:30:00Z'), report('2026-11-02T08:10:00Z'), report('unparsable')];
  const trips = [trip('oct30', '2026-10-30'), trip('oct31', '2026-10-31'), trip('dst', '2026-11-01')];
  const got = tripRecaps(trips, [], feedback, today).past;
  assert.deepEqual(got[0].reports, feedback.slice(2, 6));
  assert.deepEqual(got[1].reports, [feedback[1]]);
  assert.deepEqual(got[2].reports, [feedback[0]]);
  assert.equal(feedback.length, 8);
});

test('rendered groups, disclosures, assessment fallback, comfort reports and unchanged delete labels', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-recap-'));
  try {
    const out = join(dir, 'view.mjs');
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {SavedTrips} from './web/app/TripAlerts.tsx';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
      bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent',
      jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const {SavedTrips, render, h} = await import(pathToFileURL(out).href);
    const names = {point: new Map([['synthetic', 'Test area']]), species: new Map([['reef', 'Test species']])};
    const draw = (trips, events = [], feedback = []) => render(h(SavedTrips, {
      recaps: tripRecaps(trips, events, feedback, today), names, remove: () => () => {},
    }));
    assert.equal(draw([]), '<div id="saved-trips"><p>No saved trips.</p></div>');
    let html = draw([trip('future', '2026-11-03')]);
    assert.match(html, /<h3>Upcoming<\/h3>/);
    assert.doesNotMatch(html, /<h3>Past<\/h3>|No saved trips/);
    html = draw([trip('past', '2026-11-01')]);
    assert.match(html, /<h3>Past<\/h3>/);
    assert.doesNotMatch(html, /<h3>Upcoming<\/h3>/);
    assert.match(html, /<details><summary>2026-11-01 · Test area · Test species · 7:00–13:00<\/summary>/);
    assert.match(html, /No day-before assessment was delivered/);
    assert.match(html, /Your own record of each trip\. Forecast assessments are what we sent before the day, not what the sea did\./);
    assert.match(html, /aria-label="Delete the trip on 2026-11-01 at Test area"/);
    assert.doesNotMatch(html, /Your comfort reports/);
    html = draw([trip('past', '2026-11-01'), trip('future', '2026-11-03')],
      [event('final', 'past', 'final'), event('orphan', 'deleted', 'final')], [report('2026-11-02T07:30:00Z', 8)]);
    assert.match(html, /<h3>Upcoming<\/h3>/);
    assert.match(html, /<h3>Past<\/h3>/);
    assert.match(html, /Day-before assessment · shown here/);
    assert.match(html, /Synthetic final/);
    assert.match(html, /Your comfort reports<\/h4><p>8\/10 · fishing/);
    assert.doesNotMatch(html, /Synthetic orphan|No day-before assessment was delivered/);
    html = draw([trip('past', '2026-11-01')], [event('missed', 'past', 'missed-final')]);
    assert.match(html, /Day-before assessment missed · shown here/);
    assert.match(html, /Synthetic missed/);
  } finally { await rm(dir, {recursive: true, force: true}); }
});
