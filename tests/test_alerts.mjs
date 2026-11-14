// #602: saved-trip alerts moved from v1's dist/trip-alerts.js into v2
// (web/alerts.ts, web/app/TripAlerts.tsx). The records already saved in D1
// must keep working, so these pin the request bodies, the species choice and
// the API helper the dialog sends. tests/test_boat.mjs covers the limits.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const alerts = await import('../web/alerts.ts');
const REGION = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));

test('a saved trip posts v1\'s body: the form, the region, the species and the boat only when one is saved', () => {
  const form = {date: '2026-10-13', point: 'central', start_hour: 7, end_hour: 13, wind_limit: 8, gust_limit: 12, sea_limit: 3};
  assert.deepEqual(alerts.tripBody(form, 'morro-bay', 'reef', null), {...form, region: 'morro-bay', species: 'reef'});
  const boat = {name: 'Skiff', sea: 0.7, wind: 0.8, chop_period: 4.2};
  assert.deepEqual(alerts.tripBody(form, 'morro-bay', 'reef', boat), {...form, region: 'morro-bay', species: 'reef', boat});
});

test('comfort feedback carries no forecast context (null, which the server stores as v1\'s omitted values were)', () => {
  assert.deepEqual(alerts.comfortBody('morro-bay', 7, 'fishing'), {region: 'morro-bay', rating: 7, phase: 'fishing', wind: null, sea: null, period: null, heading: null, point: null});
});

test('the alert species are the region\'s, named, starting on the app\'s target only when the region lists it', () => {
  const on = alerts.alertSpecies(REGION, 'halibut');
  assert.deepEqual(on.options.map(o => o.id), REGION.species);
  assert.equal(on.value, 'halibut');
  assert.equal(on.options.find(o => o.id === 'reef').name, 'Lingcod & rockfish');
  assert.ok(on.options.every(o => o.group), 'every option sits in a group');
  assert.equal(alerts.alertSpecies(REGION, 'lingcod').value, REGION.species[0], 'a coast-only target falls back to the first species');
  assert.equal(alerts.alertSpecies(REGION, null).value, REGION.species[0]);
  assert.deepEqual(alerts.alertSpecies({...REGION, target_options: undefined, species: ['x']}, null).options, [{id: 'x', name: 'x', group: 'Other'}]);
});

test('the trip date is tomorrow in the region\'s zone', () => {
  // 2026-10-12 06:30 UTC is still Oct 11 in Pacific time; tomorrow there is Oct 12.
  assert.equal(alerts.alertDate('America/Los_Angeles', Date.parse('2026-10-12T06:30:00Z')), '2026-10-12');
  assert.equal(alerts.alertDate('UTC', Date.parse('2026-10-12T06:30:00Z')), '2026-10-13');
});

test('the trip date is the next calendar day on DST nights and year ends, inside the accepted range (RF1650-10)', () => {
  const cases = [
    ['America/Los_Angeles', '2026-11-01T07:30:00Z', '2026-11-02'], // 00:30 PDT on fall-back day: not today
    ['America/Los_Angeles', '2027-03-14T07:30:00Z', '2027-03-14'], // 23:30 PST on 03-13 before spring-forward: not two days ahead
    ['America/Los_Angeles', '2026-10-15T19:00:00Z', '2026-10-16'], // ordinary day
    ['America/Los_Angeles', '2027-01-01T07:30:00Z', '2027-01-01'], // 23:30 PST on 2026-12-31: year roll-over
    ['Pacific/Honolulu', '2026-11-02T09:30:00Z', '2026-11-02'], // 23:30 HST on 11-01, no DST
  ];
  for (const [zone, at, want] of cases) {
    const now = Date.parse(at), got = alerts.alertDate(zone, now), {min, max} = alerts.dateRange(zone, now);
    assert.equal(got, want, `${zone} ${at}`);
    assert.ok(min <= got && got <= max, `${zone} ${at}: ${got} outside ${min}..${max}`);
  }
});

test('a saved trip and its feedback read as before', () => {
  assert.equal(alerts.tripLine({id: 't', date: '2026-10-13', point: 'central', species: 'reef', start_hour: 7, end_hour: 13}), 'Tue 13 Oct · central · reef · 7:00–13:00');
  assert.equal(alerts.tripLine({id: 't', date: '2026-10-13', point: 'central', species: 'reef', start_hour: 7, end_hour: 13, boat_sea: 0.7, boat_name: ''}), 'Tue 13 Oct · central · reef · 7:00–13:00 · saved boat');
  assert.equal(alerts.feedbackPhase({observed_at: '', rating: 7, context: '{"phase":"return"}'}), 'return');
  assert.equal(alerts.feedbackPhase({observed_at: '', rating: 7, context: '{'}), '', 'a bad record never breaks the list');
});

test('the API helper sends JSON to /api/ and surfaces the server\'s error', async () => {
  const calls = [];
  const ok = async (url, init) => { calls.push([url, init]); return Response.json({trips: []}); };
  assert.deepEqual(await alerts.api('trips', {method: 'POST', body: '{}'}, ok), {trips: []});
  assert.equal(calls[0][0], '/api/trips');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json');
  await assert.rejects(alerts.api('trips', {}, async () => Response.json({error: 'Sea limit out of range'}, {status: 400})), /Sea limit out of range/);
  await assert.rejects(alerts.api('trips', {}, async () => new Response('<html>', {status: 200})), /published site/);
});

test('the VAPID key decodes from base64url', () => {
  assert.deepEqual([...alerts.b64('AQID_-8')], [1, 2, 3, 255, 239]);
});

// SC1137-12: the recap reads every catch-log cursor page (readRecapCatchLog), within RECAP_PAGE_CAP, and is complete only when the last page was reached.
const log = (id, trip_id, started_at = '2026-11-01T15:00:00.000Z', extra = {}) => ({id, trip_id, started_at, outcome: 'fish', count: 1, ...extra});
const HAS = 'X-SC-Catch-Log-Has-More', NEXT = 'X-SC-Catch-Log-Next-Cursor';
/** A fake GET /api/catch-log: `pages[i]` answers the i-th request; rows `more` pages carry the next token. Records every URL asked. */
const paged = (pages, urls = []) => async (url, init) => {
  urls.push([url, init]);
  const page = pages[urls.length - 1];
  if (typeof page === 'function') return page();
  return Response.json({entries: page.rows}, {headers: {[HAS]: String(!!page.next), ...(page.next ? {[NEXT]: page.next} : {})}});
};
const rowsOf = (prefix, n, trip) => Array.from({length: n}, (_, i) => log(`${prefix}${i}`, typeof trip === 'function' ? trip(i) : trip));

test('recap_pages_zero_200_450: no entries, exactly 200 and 450 across three pages are read in full and complete at the last page', async () => {
  const none = [];
  assert.deepEqual(await alerts.readRecapCatchLog(paged([{rows: []}], none)), {entries: [], complete: true});
  assert.equal(none.length, 1);
  assert.equal(none[0][0], '/api/catch-log');
  assert.equal(none[0][1].method, undefined, 'a plain GET');

  const exact = [], two = await alerts.readRecapCatchLog(paged([{rows: rowsOf('a', 200, 't1')}], exact));
  assert.equal(two.entries.length, 200);
  assert.equal(two.complete, true);
  assert.equal(exact.length, 1, 'a full page that says no more is not followed');

  const urls = [], trips = ['t1', 't2', 't3'];
  const got = await alerts.readRecapCatchLog(paged([
    {rows: rowsOf('p1-', 200, i => trips[i % 3]), next: 'tok+/=1'},
    {rows: rowsOf('p2-', 200, i => trips[i % 3]), next: 'tok-_2'},
    {rows: rowsOf('p3-', 50, i => trips[i % 3])},
  ], urls));
  assert.deepEqual(urls.map(u => u[0]), ['/api/catch-log', '/api/catch-log?cursor=tok%2B%2F%3D1', '/api/catch-log?cursor=tok-_2']);
  assert.equal(got.entries.length, 450);
  assert.equal(got.complete, true);
  const recaps = alerts.tripRecaps(trips.map(id => ({id, date: '2026-10-01', point: 'p', species: 's', start_hour: 7, end_hour: 13})), [], [], '2026-11-02', got.entries);
  assert.deepEqual(recaps.past.map(r => r.catches.length).sort(), [148, 151, 151]);
});

test('recap_oldest_trip_predates_trip_window: an entry linked to the oldest trip but started before it, found only past page one, is joined by its trip id', async () => {
  const old = log('before-trip', 'oldest', '2019-01-01T00:00:00.000Z');
  const got = await alerts.readRecapCatchLog(paged([{rows: rowsOf('n', 200, 'newer'), next: 'c1'}, {rows: [old]}]));
  assert.equal(got.complete, true, 'the pages ended');
  const trip = id => ({id, date: id === 'oldest' ? '2026-10-01' : '2026-10-20', point: 'p', species: 's', start_hour: 7, end_hour: 13});
  const recaps = alerts.tripRecaps([trip('newer'), trip('oldest')], [], [], '2026-11-02', got.entries);
  assert.deepEqual(recaps.past.find(r => r.trip.id === 'oldest').catches.map(c => c.id), ['before-trip']);
});

test('recap_page_cap_is_honest: ten pages saying more stop incomplete with every row kept and no eleventh request; a last page on page ten is complete; empty or short pages are not completion', async () => {
  assert.equal(alerts.RECAP_PAGE_CAP, 10);
  const full = i => ({rows: rowsOf(`p${i}-`, 2, 't1'), next: `c${i}`});
  const urls = [], capped = await alerts.readRecapCatchLog(paged(Array.from({length: 11}, (_, i) => full(i)), urls));
  assert.equal(urls.length, 10);
  assert.equal(capped.entries.length, 20);
  assert.equal(capped.complete, false);

  const last = [], done = await alerts.readRecapCatchLog(paged([...Array.from({length: 9}, (_, i) => full(i)), {rows: rowsOf('z', 1, 't1')}], last));
  assert.equal(last.length, 10);
  assert.deepEqual([done.entries.length, done.complete], [19, true]);

  const short = [], gaps = await alerts.readRecapCatchLog(paged([{rows: [], next: 'a'}, {rows: rowsOf('s', 1, 't1'), next: 'b'}, {rows: []}], short));
  assert.equal(short.length, 3, 'empty and short pages that say more are followed');
  assert.deepEqual([gaps.entries.length, gaps.complete], [1, true]);
});

test('recap_second_page_failure_keeps_first: a refused, offline, broken or mis-headed second page keeps page one and reads incomplete; so does a failed first page', async () => {
  const first = {rows: [log('k1', 't1'), log('k2', 't1')], next: 'c1'};
  const bad = {
    '503': () => Response.json({error: 'down'}, {status: 503}),
    '401': () => Response.json({error: 'Sign in'}, {status: 401}),
    offline: () => { throw new Error('offline'); },
    'not JSON': () => new Response('<html>'),
    'entries not a list': () => Response.json({entries: 'x'}, {headers: {[HAS]: 'false'}}),
    'no entries': () => Response.json({}, {headers: {[HAS]: 'false'}}),
    'no has-more header': () => Response.json({entries: [log('k3', 't1')]}),
    'bad has-more header': () => Response.json({entries: [log('k3', 't1')]}, {headers: {[HAS]: 'maybe'}}),
    'more without a cursor': () => Response.json({entries: [log('k3', 't1')]}, {headers: {[HAS]: 'true'}}),
    'repeated cursor': () => Response.json({entries: [log('k3', 't1')]}, {headers: {[HAS]: 'true', [NEXT]: 'c1'}}),
  };
  for (const [name, second] of Object.entries(bad)) {
    const urls = [], got = await alerts.readRecapCatchLog(paged([first, second, {rows: [log('late', 't1')]}], urls));
    assert.equal(got.complete, false, name);
    assert.ok(got.entries.map(e => e.id).join().startsWith('k1,k2'), name);
    assert.ok(!got.entries.some(e => e.id === 'late'), `${name}: no request after the failed page`);
    assert.equal(urls.length, 2, name);
  }
  for (const name of ['503', '401', 'offline', 'not JSON', 'entries not a list', 'no entries']) assert.deepEqual(await alerts.readRecapCatchLog(paged([bad[name]])), {entries: [], complete: false}, `first page: ${name}`);
});

test('recap_bad_row_duplicate_and_private_projection: a dropped row never reads as complete, repeated ids count once and private fields do not reach the result', async () => {
  const private1 = log('d1', 't1', undefined, {note: 'LOGNOTE-private', lat: 35.123456, lon: -120.654321, owner: 'OWNER-x', species: 'lingcod', method: 'jig'});
  const got = await alerts.readRecapCatchLog(paged([{rows: [private1, log('d2', 't1')], next: 'c1'}, {rows: [log('d1', 't2'), log('d3', 't1')]}]));
  assert.deepEqual(got.entries.map(e => [e.id, e.trip_id]), [['d1', 't1'], ['d2', 't1'], ['d3', 't1']], 'first occurrence wins, page order kept');
  assert.equal(got.complete, true);
  assert.doesNotMatch(JSON.stringify(got), /LOGNOTE|35\.12|120\.65|OWNER-x|lingcod|jig/);

  const dropped = await alerts.readRecapCatchLog(paged([{rows: [log('e1', 't1'), {id: 'e2', trip_id: 't1', started_at: 'now', outcome: 'caught', count: 2}, null]}]));
  assert.deepEqual([dropped.entries.map(e => e.id), dropped.complete], [['e1'], false]);
});

test('recap_unmount_stops_chain: aborting while the second page is pending ends the read incomplete and asks for no third page', async () => {
  const ctl = new AbortController(), urls = [];
  let release;
  const second = () => new Promise(resolve => { release = () => resolve(Response.json({entries: [log('x2', 't1')]}, {headers: {[HAS]: 'true', [NEXT]: 'c2'}})); });
  const read = alerts.readRecapCatchLog(paged([{rows: [log('x1', 't1')], next: 'c1'}, second, {rows: [log('x3', 't1')]}], urls), ctl.signal);
  while (urls.length < 2) await new Promise(r => setTimeout(r, 0));
  ctl.abort();
  release();
  const got = await read;
  assert.equal(got.complete, false);
  assert.equal(urls.length, 2, 'no request after the abort');
  const before = [], pre = new AbortController();
  pre.abort();
  assert.deepEqual(await alerts.readRecapCatchLog(paged([{rows: []}], before), pre.signal), {entries: [], complete: false});
  assert.equal(before.length, 0);
});

test('upcoming_latest_event_uses_first_exact_trip_match: newest-first, trips kept apart, nothing mutated', () => {
  const ev = (id, trip_id, kind) => ({id, trip_id, kind, status: 'in-app', message: 'm'});
  const events = [ev(1, 'b', 'update'), ev(2, 'a', 'update'), ev(3, 'a', 'final'), ev(4, undefined, 'update'), ev(5, '', 'update')];
  const before = JSON.stringify(events);
  assert.equal(alerts.latestTripEvent(events, 'a').id, 2, 'the first own event wins, with no kind preference');
  assert.equal(alerts.latestTripEvent(events, 'b').id, 1);
  assert.equal(alerts.latestTripEvent(events, 'c'), null);
  assert.equal(alerts.latestTripEvent(events, ''), null);
  assert.equal(alerts.latestTripEvent([], 'a'), null);
  assert.equal(JSON.stringify(events), before);
});

test('saved_limits_are_as_stored_not_boat_or_profile', () => {
  const t = {id: 'a', date: 'd', point: 'p', species: 's', start_hour: 7, end_hour: 13, boat_sea: 0.5, wind_limit: 9, gust_limit: 14, sea_limit: 2.5};
  assert.equal(alerts.savedTripLimits(t), 'Saved limits: wind 9 kt · gust 14 kt · sea 2.5 ft');
  assert.equal(alerts.savedTripLimits({...t, wind_limit: undefined, gust_limit: NaN, sea_limit: Infinity}), 'Saved limits: wind not recorded · gust not recorded · sea not recorded');
  assert.equal(alerts.savedTripLimits({...t, sea_limit: '3'}), 'Saved limits: wind 9 kt · gust 14 kt · sea not recorded');
});

test('assessment_time_has_explicit_region_zone', () => {
  const e = {id: 1, kind: 'update', status: 'held', message: '', created_at: '2026-11-05T07:30:00Z'};
  assert.match(alerts.assessmentTime(e, 'America/Los_Angeles'), /^04 Nov 2026, 23:30 (GMT-8|PST)$/);
  assert.match(alerts.assessmentTime(e, 'UTC'), /^05 Nov 2026, 07:30 UTC$/);
  for (const created_at of [undefined, '', 'not a date', 5]) assert.equal(alerts.assessmentTime({...e, created_at}), 'Time unavailable');
});
