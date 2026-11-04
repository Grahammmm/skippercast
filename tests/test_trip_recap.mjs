// Synthetic private records only; no account or provider access.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {isDeepStrictEqual} from 'node:util';
import {tripRecaps, dateRange, catchLogEntries} from '../web/alerts.ts';
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

const logged = (id, trip_id, outcome = 'blank', count = 0, started_at = '2026-11-01T15:00:00.000Z') => ({id, trip_id, started_at, outcome, count});

test('recap_catches_match_exact_trip_id_not_day', () => {
  // Same date, misleading catch dates: only the exact trip id joins.
  const trips = [trip('a', '2026-11-01'), trip('b', '2026-11-01'), trip('c', '2026-10-30'), trip('later', '2026-11-05')];
  const entries = [logged('e1', 'a', 'fish', 3, '2026-10-30T15:00:00.000Z'), logged('e2', 'b', 'blank', 0, '2026-11-05T15:00:00.000Z'), logged('e3', 'a', 'unknown'),
    logged('e4', null), logged('e5', ''), logged('e6', 'deleted-trip', 'fish', 1), logged('e7', 'later', 'fish', 2), logged('e8', undefined)];
  const originalEntries = structuredClone(entries), originalTrips = structuredClone(trips);
  const past = tripRecaps(trips, [], [], today, entries).past;
  const byId = Object.fromEntries(past.map(r => [r.trip.id, r.catches.map(c => c.id)]));
  assert.deepEqual(byId, {a: ['e1', 'e3'], b: ['e2'], c: []});
  assert.equal(past.find(r => r.trip.id === 'a').catches[0], entries[0], 'rows keep identity and the answer\'s order');
  assert.deepEqual(tripRecaps(trips, [], [], today, entries).upcoming.map(t => t.id), ['later'], 'an upcoming trip gets no catch section');
  assert.deepEqual(entries, originalEntries);
  assert.deepEqual(trips, originalTrips);
});

test('recap_without_catches_keeps_existing_semantics', () => {
  const trips = [trip('a', '2026-11-01'), trip('b', '2026-10-31')];
  const events = [event(1, 'a', 'missed-final'), event(2, 'a', 'final')];
  const feedback = [report('2026-11-01T07:30:00Z'), report('2026-11-01T09:30:00Z')];
  const bare = tripRecaps(trips, events, feedback, today);
  for (const entries of [[], undefined]) {
    const got = tripRecaps(trips, events, feedback, today, entries);
    assert.ok(isDeepStrictEqual(got, bare), 'an empty or omitted fifth argument changes nothing');
  }
  assert.deepEqual(bare.past.map(r => r.catches), [[], []]);
  assert.equal(bare.past[0].final, events[1]);
  assert.deepEqual(bare.past[0].reports, feedback);
});

test('catchLogEntries keeps only well-formed rows, drops private fields and tolerates any answer', () => {
  const row = {id: 'x', owner: 'alice', trip_id: 't', started_at: '2026-11-01T15:00:00.000Z', outcome: 'fish', count: 2, lat: 35.1, lon: -120.9, note: 'LOGNOTE', method: 'jig', species: 'lingcod'};
  assert.deepEqual(catchLogEntries({entries: [row]}), [{id: 'x', trip_id: 't', started_at: '2026-11-01T15:00:00.000Z', outcome: 'fish', count: 2}]);
  assert.deepEqual(catchLogEntries({entries: [{...row, trip_id: undefined}, {...row, id: 'y', trip_id: ''}]}).map(e => e.trip_id), [null, null]);
  const bad = [null, 7, 'x', {}, {...row, id: 5}, {...row, started_at: null}, {...row, outcome: 'caught'}, {...row, count: '2'}, {...row, count: 1.5}, {...row, count: -1}, {...row, count: null}];
  assert.deepEqual(catchLogEntries({entries: bad}), []);
  for (const answer of [undefined, null, [], 'x', 3, {}, {entries: null}, {entries: {}}, {entries: 'x'}]) assert.deepEqual(catchLogEntries(answer), []);
  assert.deepEqual(catchLogEntries({entries: [row, null, {...row, id: 'z'}]}).map(e => e.id), ['x', 'z']);
});

test('rendered_recap_lists_fish_blank_unknown_privately', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-recap-catch-'));
  try {
    const out = join(dir, 'view.mjs');
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {SavedTrips} from './web/app/TripAlerts.tsx';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
      bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent',
      jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const {SavedTrips, render, h} = await import(pathToFileURL(out).href);
    const names = {point: new Map([['synthetic', 'Test area']]), species: new Map([['reef', 'Test species']])};
    const draw = (trips, entries, events = [], feedback = []) => render(h(SavedTrips, {recaps: tripRecaps(trips, events, feedback, today, entries), names, remove: () => () => {}}));
    const none = draw([trip('past', '2026-11-01')], []);
    assert.doesNotMatch(none, /catch log|Fish ·|Blank|Not sure/i);
    // A trip with nothing logged, a failed read and an empty read all draw the same page.
    assert.equal(draw([trip('past', '2026-11-01')], catchLogEntries(undefined)), none);
    assert.equal(draw([trip('past', '2026-11-01')], [logged('other', 'elsewhere', 'fish', 4)]), none);
    assert.equal(draw([trip('past', '2026-11-01')], [logged('f', 'past', 'fish', 3)]).replace(/<h4>Your catch log<\/h4>.*?<\/ul>/, ''), none);

    const entries = catchLogEntries({entries: [
      {...logged('f1', 'past', 'fish', 3), note: 'LOGNOTE-private', lat: 35.123456, lon: -120.654321, owner: 'OWNER-alice', species: 'lingcod', method: 'jig'},
      logged('b1', 'past', 'blank'), logged('u1', 'past', 'unknown'), logged('f2', 'past', 'fish', 1),
      logged('x1', 'future', 'fish', 9)]});
    const html = draw([trip('past', '2026-11-01'), trip('future', '2026-11-03')], entries, [event('final', 'past', 'final')], [report('2026-11-02T07:30:00Z', 8)]);
    assert.match(html, /Your comfort reports<\/h4><p>8\/10 · fishing<\/p><h4>Your catch log<\/h4><ul><li>Fish · 3 fish<\/li><li>Blank: no fish<\/li><li>Not sure<\/li><li>Fish · 1 fish<\/li><\/ul><\/details>/);
    assert.equal((html.match(/Your catch log/g) ?? []).length, 1, 'only the past trip with entries shows the section');
    assert.doesNotMatch(html, /LOGNOTE|35\.12|120\.65|OWNER-alice|lingcod|jig|Fish · 9|forecast the catch|predict|total|%/i);
    assert.match(html, /<h3>Upcoming<\/h3><p><strong>2026-11-03/, 'the upcoming row is as before');
    assert.doesNotMatch(html.slice(html.indexOf('<h3>Upcoming</h3>'), html.indexOf('<h3>Past</h3>')), /catch/i);
    // Markup in a hostile id or count cannot reach the page: ids are keys, counts numbers.
    const hostile = draw([trip('past', '2026-11-01')], catchLogEntries({entries: [{...logged('<script>x</script>', 'past', 'fish', 2)}]}));
    assert.doesNotMatch(hostile, /<script>/);
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('recap_render_says_when_older_entries_were_not_read: loading and incomplete reads are worded once under Past, a complete read adds nothing', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-recap-read-'));
  try {
    const out = join(dir, 'view.mjs');
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {SavedTrips} from './web/app/TripAlerts.tsx';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
      bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent',
      jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const {SavedTrips, render, h} = await import(pathToFileURL(out).href);
    const names = {point: new Map([['synthetic', 'Test area']]), species: new Map([['reef', 'Test species']])};
    const draw = (trips, entries, read) => render(h(SavedTrips, {recaps: tripRecaps(trips, [], [], today, entries), names, remove: () => () => {}, ...(read ? {read} : {})}));
    const oldest = [trip('newer', '2026-11-01'), trip('oldest', '2026-10-01')];
    const notRead = /Older catch-log entries were not read\. The entries shown may be incomplete\./g, reading = /Reading your catch log…/g;
    const count = (html, re) => (html.match(re) ?? []).length;

    // Entries were found only past page one, one of them started before its trip; once the pages ended nothing is said about reading.
    const found = [logged('f1', 'newer', 'fish', 2), logged('before', 'oldest', 'fish', 5, '2019-01-01T00:00:00.000Z')];
    const complete = draw(oldest, found, {loading: false, complete: true});
    assert.match(complete, /Fish · 5 fish/);
    assert.equal(count(complete, notRead) + count(complete, reading), 0);
    assert.equal(complete, draw(oldest, found), 'no read state is a complete read');

    // A read that stopped keeps what it read, says so once under Past and does not say nothing was logged.
    const stopped = draw(oldest, [found[0]], {loading: false, complete: false});
    assert.equal(count(stopped, notRead), 1);
    assert.ok(stopped.indexOf('<h3>Past</h3>') < stopped.search(notRead), 'under Past');
    assert.match(stopped, /Fish · 2 fish/);
    assert.doesNotMatch(stopped, /no catch|nothing (was )?logged|none logged/i);
    // Even a stop with nothing read (a failed first page) is worded, not drawn as an empty history.
    const none = draw(oldest, [], {loading: false, complete: false});
    assert.equal(count(none, notRead), 1);
    assert.doesNotMatch(none, /Your catch log/);

    const loading = draw(oldest, [], {loading: true, complete: false});
    assert.equal(count(loading, reading), 1);
    assert.equal(count(loading, notRead), 0);
    // Without a past trip there is no Past section to carry either line.
    assert.equal(count(draw([trip('future', '2026-11-03')], [], {loading: false, complete: false}), notRead), 0);
  } finally { await rm(dir, {recursive: true, force: true}); }
});
