// RF1230-12: an impossible ISO day (V8 rolls 2026-02-30 over to 03-02) is not a
// date. answers/time.ts realDate() round-trips through toISOString, as the fleet
// calendarDate does; parseTripDate's ISO branch and calendarWeek's ?start use it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// time.ts first, before any Worker global exists.
const noGlobals = globalThis.REGIONS === undefined && globalThis.DEPLOYMENT === undefined;
const {realDate} = await import('../server/advisor/answers/time.ts');

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const conditions = await import('../server/advisor/answers/conditions.ts');
const C = await import('../server/advisor/social/calendar.ts');

const wed = Date.parse('2026-09-30T17:00:00Z');   // Wednesday 10:00 Pacific

test('realDate: time.ts imports with no Worker globals set', () => {
  assert.ok(noGlobals, 'REGIONS/DEPLOYMENT were unset when time.ts loaded');
  assert.equal(typeof realDate, 'function');
});

test('realDate: real days only, exact YYYY-MM-DD', () => {
  for (const ok of ['2026-02-28', '2028-02-29', '2026-12-31', '2026-01-01']) assert.equal(realDate(ok), true, ok);
  for (const bad of ['2026-02-29', '2026-02-30', '2026-04-31', '2026-13-01', '2026-00-10', '2026-01-00', '2026-01-32',
    '2026-1-1', '', null, undefined, 20260228, '20260228', '2026-02-28T00:00:00Z', ' 2026-02-28', '2026-02-28\n'])
    assert.equal(realDate(bad), false, JSON.stringify(bad));
});

test('parseTripDate: an impossible ISO day is not a trip date and falls through to the word rules', () => {
  const d = text => conditions.parseTripDate(text, wed);
  const bare = d('2026-02-30');
  assert.notDeepEqual(bare.dates, ['2026-02-30']);
  assert.deepEqual([bare.dates, bare.parsed], [['2026-09-30'], false], 'nothing parsed: today, parsed false');
  assert.equal(d('2026-04-31').parsed, false);
  const sat = d('2026-02-30 saturday');
  assert.deepEqual([sat.dates, sat.parsed], [['2026-10-03'], true], 'the weekday rule still answers');
  assert.deepEqual(d('2026-02-30 mañana').dates, ['2026-10-01']);
  const real = d('2026-10-05');
  assert.deepEqual([real.dates, real.parsed, real.days_ahead], [['2026-10-05'], true, 5], 'a real ISO day is unchanged');
  assert.deepEqual(d('2028-02-29').dates, ['2028-02-29'], 'a leap day is a real day');
});

const throwingDb = {prepare() { throw new Error('db must not be queried for a bad start'); }};
const emptyDb = {prepare: () => ({bind: () => ({all: async () => ({results: []})})})};

test('calendarWeek: an impossible start is a start error before any query', async () => {
  for (const start of ['2026-02-30', '2026-04-31', '2026-02-29', '2026-13-01', 'soon', '2026-3-2'])
    assert.deepEqual(await C.calendarWeek(throwingDb, start, wed), {error: 'start must be YYYY-MM-DD'}, start);
});

test('calendarWeek: a real start keeps its Monday', async () => {
  const week = await C.calendarWeek(emptyDb, '2026-03-02', wed);
  assert.deepEqual([week.start, week.end, week.days.length], ['2026-03-02', '2026-03-08', 7]);
  assert.equal((await C.calendarWeek(emptyDb, '2028-02-29', wed)).start, '2028-02-28', 'a leap day starts its Monday week');
  assert.equal((await C.calendarWeek(emptyDb, null, wed)).start, '2026-09-28', 'no start: this week');
});
