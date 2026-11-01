// SC1537-06: the trip alerts dialog names a saved trip's area and species and
// an assessment's kind and status in plain words (web/alerts.ts). Unknown ids,
// kinds and statuses still print as written: never blank, never "undefined".
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const alerts = await import('../web/alerts.ts');

const REGION = {
  id: 'big-sur', timezone: 'America/Los_Angeles', species: ['rockfish', 'halibut'],
  forecast_points: [{id: 'sur', name: 'Point Sur'}, {id: 'lopez', name: 'Lopez Point'}],
  target_options: [{id: 'rockfish', name: 'Rockfish', group: 'Reef'}, {id: 'lingcod', name: 'Lingcod', group: 'Reef'}],
};
const trip = (over = {}) => ({id: 't', date: '2026-11-02', point: 'sur', species: 'rockfish', start_hour: 7, end_hour: 13, ...over});

test('a known area and species read by name; the saved boat is still appended', () => {
  const names = alerts.alertNames(REGION);
  assert.equal(alerts.tripLine(trip(), names), '2026-11-02 · Point Sur · Rockfish · 7:00–13:00');
  assert.equal(alerts.tripLine(trip({boat_sea: 0.7, boat_name: 'Skiff'}), names), '2026-11-02 · Point Sur · Rockfish · 7:00–13:00 · Skiff');
  assert.equal(alerts.tripLine(trip({boat_sea: 0.7, boat_name: ''}), names), '2026-11-02 · Point Sur · Rockfish · 7:00–13:00 · saved boat');
  assert.equal(alerts.tripLine(trip({boat_sea: 0, boat_name: 'Skiff'}), names), '2026-11-02 · Point Sur · Rockfish · 7:00–13:00', 'no boat without boat_sea');
});

test('an area no longer in the region file prints its raw id, never "undefined"', () => {
  const line = alerts.tripLine(trip({point: 'old-cove'}), alerts.alertNames(REGION));
  assert.equal(line, '2026-11-02 · old-cove · Rockfish · 7:00–13:00');
  assert.doesNotMatch(line, /undefined/);
});

test('a species the region lists without a target option reads as alertSpecies does (raw id); an unlisted one prints raw', () => {
  const names = alerts.alertNames(REGION);
  assert.equal(names.species.get('halibut'), alerts.alertSpecies(REGION, null).options.find(o => o.id === 'halibut').name);
  assert.equal(alerts.tripLine(trip({species: 'halibut'}), names), '2026-11-02 · Point Sur · halibut · 7:00–13:00');
  assert.equal(alerts.tripLine(trip({species: 'lingcod'}), names), '2026-11-02 · Point Sur · lingcod · 7:00–13:00', 'named but not in the region\'s species list');
  assert.equal(alerts.tripLine(trip({species: 'squid'}), names), '2026-11-02 · Point Sur · squid · 7:00–13:00');
});

test('without names the line is exactly today\'s, ids and all', () => {
  assert.equal(alerts.tripLine(trip()), '2026-11-02 · sur · rockfish · 7:00–13:00');
  assert.equal(alerts.tripLine(trip({boat_sea: 0.7})), '2026-11-02 · sur · rockfish · 7:00–13:00 · saved boat');
});

test('an id named like an object property is looked up, not inherited', () => {
  const names = alerts.alertNames(REGION);
  const line = alerts.tripLine(trip({point: 'constructor', species: '__proto__'}), names);
  assert.equal(line, '2026-11-02 · constructor · __proto__ · 7:00–13:00');
});

const KINDS = {initial: 'First assessment', update: 'Material change', retraction: 'Earlier alert withdrawn', final: 'Day-before assessment', 'missed-final': 'Day-before assessment missed'};
const STATUSES = {pending: 'sending', accepted: 'sent to your device', uncertain: 'delivery not confirmed', held: 'not delivered — read it here', 'in-app': 'shown here', delivered: 'delivered', read: 'read'};
const event = (kind, status) => ({id: 1, kind, status, message: 'm'});

test('every kind and status server/trips.ts writes maps to its frozen words', () => {
  assert.equal(alerts.eventLine(event('final', 'in-app')), 'Day-before assessment · shown here');
  for (const [kind, words] of Object.entries(KINDS)) assert.equal(alerts.eventLine(event(kind, 'read')), `${words} · read`, kind);
  for (const [status, words] of Object.entries(STATUSES)) assert.equal(alerts.eventLine(event('update', status)), `Material change · ${words}`, status);
  assert.deepEqual(Object.keys(alerts.KIND_LABEL).sort(), Object.keys(KINDS).sort(), 'no extra or missing kinds');
  assert.deepEqual(Object.keys(alerts.STATUS_LABEL).sort(), Object.keys(STATUSES).sort(), 'no extra or missing statuses');
});

test('an unknown kind or status prints as written', () => {
  assert.equal(alerts.eventLine(event('later', 'bounced')), 'later · bounced');
  assert.equal(alerts.eventLine(event('later', 'held')), 'later · not delivered — read it here');
  assert.equal(alerts.eventLine(event('Final', 'IN-APP')), 'Final · IN-APP', 'no case folding');
});

test('a kind or status named like an object property prints raw (own keys only)', () => {
  assert.equal(alerts.eventLine(event('constructor', '__proto__')), 'constructor · __proto__');
  assert.equal(alerts.eventLine(event('toString', 'hasOwnProperty')), 'toString · hasOwnProperty');
});

test('an empty region gives empty name maps and raw-id lines', () => {
  const names = alerts.alertNames({id: 'x', timezone: 'UTC', species: [], forecast_points: []});
  assert.equal(names.point.size, 0);
  assert.equal(names.species.size, 0);
  assert.equal(alerts.tripLine(trip(), names), '2026-11-02 · sur · rockfish · 7:00–13:00');
});

test('the dialog shows the names and plain assessment headings; the Mark read rule is unchanged', () => {
  const src = readFileSync(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  assert.match(src, /useMemo\(\(\) => alertNames\(region\), \[region\]\)/);
  assert.match(src, /tripLine\(t, names\)/);
  assert.match(src, /<strong>\{eventLine\(e\)\}<\/strong>/);
  assert.doesNotMatch(src, /\{e\.kind\} · \{e\.status\}/);
  assert.match(src, /aria-label=\{`Delete the trip on \$\{t\.date\} at \$\{names\.point\.get\(t\.point\) \?\? t\.point\}`\}/);
  assert.match(src, /!\['read', 'delivered'\]\.includes\(e\.status\)/);
});
