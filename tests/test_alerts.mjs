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
  assert.equal(alerts.tripLine({id: 't', date: '2026-10-13', point: 'central', species: 'reef', start_hour: 7, end_hour: 13}), '2026-10-13 · central · reef · 7:00–13:00');
  assert.equal(alerts.tripLine({id: 't', date: '2026-10-13', point: 'central', species: 'reef', start_hour: 7, end_hour: 13, boat_sea: 0.7, boat_name: ''}), '2026-10-13 · central · reef · 7:00–13:00 · saved boat');
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
