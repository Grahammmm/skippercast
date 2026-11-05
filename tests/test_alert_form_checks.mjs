// SC1537-07: the trip alerts form offers only today..today+7 in the region's
// zone and says in plain words, before anything is sent, when the window ends at
// or before it starts or the gust limit is below the wind limit (web/alerts.ts
// dateRange, formProblem; web/app/TripAlerts.tsx). server/trips.ts still checks.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {dateRange, formProblem} = await import('../web/alerts.ts');

const DATE = 'Choose a date from today to seven days ahead.';
const WINDOW = 'The window must end after it starts.';
const GUST = 'The gust limit cannot be lower than the wind limit.';
const RANGE = {min: '2026-10-31', max: '2026-11-07'};
const form = (over = {}) => ({date: '2026-11-02', point: 'central', start_hour: 7, end_hour: 13, wind_limit: 12, gust_limit: 16, sea_limit: 3, ...over});

test('the range starts on today in the port\'s zone, not UTC\'s, and ends seven calendar days later', () => {
  const now = Date.parse('2026-11-01T06:30:00Z');
  assert.deepEqual(dateRange('America/Los_Angeles', now), {min: '2026-10-31', max: '2026-11-07'}, 'still the evening before in Los Angeles');
  assert.deepEqual(dateRange('Pacific/Honolulu', now), {min: '2026-10-31', max: '2026-11-07'});
  assert.deepEqual(dateRange('America/New_York', now), {min: '2026-11-01', max: '2026-11-08'});
  assert.deepEqual(dateRange('UTC', Date.parse('2026-11-01T23:59:00Z')), {min: '2026-11-01', max: '2026-11-08'});
  assert.deepEqual(dateRange('Pacific/Honolulu', Date.parse('2026-11-01T09:59:00Z')), {min: '2026-10-31', max: '2026-11-07'}, '23:59 HST');
});

test('a DST week ends on the calendar day seven ahead, as the server\'s plusDays does', () => {
  // 00:30 PDT on 10-26; the clocks go back on 11-01, so now + 7×24 h would still read 11-01 locally.
  const now = Date.parse('2026-10-26T07:30:00Z');
  assert.deepEqual(dateRange('America/Los_Angeles', now), {min: '2026-10-26', max: '2026-11-02'});
  assert.equal(new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(now + 7 * 86400000)), '2026-11-01', 'the off-by-one the design avoids');
  assert.deepEqual(dateRange('America/Los_Angeles', Date.parse('2026-03-08T08:30:00Z')), {min: '2026-03-08', max: '2026-03-15'}, 'spring forward');
  assert.deepEqual(dateRange('UTC', Date.parse('2026-12-28T00:00:00Z')), {min: '2026-12-28', max: '2027-01-04'}, 'across the year');
});

test('the first and last offered days pass; one day either side is refused with the date message', () => {
  assert.equal(formProblem(form({date: RANGE.min}), RANGE), null);
  assert.equal(formProblem(form({date: RANGE.max}), RANGE), null);
  assert.equal(formProblem(form({date: '2026-10-30'}), RANGE), DATE, 'yesterday');
  assert.equal(formProblem(form({date: '2026-11-08'}), RANGE), DATE, 'eight days ahead');
  assert.equal(formProblem(form({date: '2025-11-02'}), RANGE), DATE, 'last year');
});

test('a garbage, impossible, empty or loosely written date is refused with the date message', () => {
  for (const date of ['2026-13-40', '', '2026-11-2', '2026-11-02T00:00', ' 2026-11-02', '11/02/2026', 'null', 'undefined'])
    assert.equal(formProblem(form({date}), RANGE), DATE, JSON.stringify(date));
  const yearEnd = {min: '2026-12-28', max: '2027-01-04'};
  assert.equal(formProblem(form({date: '2026-12-31'}), yearEnd), null);
  assert.equal(formProblem(form({date: '2026-13-01'}), yearEnd), DATE, 'sorts inside the range as text but is no day');
  assert.equal(formProblem(form({date: '2026-12-32'}), yearEnd), DATE);
  const feb = {min: '2026-02-25', max: '2026-03-04'};
  assert.equal(formProblem(form({date: '2026-02-30'}), feb), DATE, 'no 30 February');
  assert.equal(formProblem(form({date: '2026-02-28'}), feb), null);
});

test('a window that ends at or before it starts is refused; one hour long passes', () => {
  assert.equal(formProblem(form({start_hour: 7, end_hour: 7}), RANGE), WINDOW);
  assert.equal(formProblem(form({start_hour: 13, end_hour: 7}), RANGE), WINDOW);
  assert.equal(formProblem(form({start_hour: 7, end_hour: 8}), RANGE), null);
  assert.equal(formProblem(form({start_hour: 0, end_hour: 23}), RANGE), null);
});

test('a gust limit below the wind limit is refused; equal passes', () => {
  assert.equal(formProblem(form({wind_limit: 12, gust_limit: 11}), RANGE), GUST);
  assert.equal(formProblem(form({wind_limit: 12, gust_limit: 11.5}), RANGE), GUST);
  assert.equal(formProblem(form({wind_limit: 12, gust_limit: 12}), RANGE), null);
});

test('an empty (NaN) hour or limit never passes by a NaN comparison', () => {
  assert.equal(formProblem(form({start_hour: NaN}), RANGE), WINDOW);
  assert.equal(formProblem(form({end_hour: NaN}), RANGE), WINDOW);
  assert.equal(formProblem(form({start_hour: NaN, end_hour: NaN}), RANGE), WINDOW);
  assert.equal(formProblem(form({gust_limit: NaN}), RANGE), GUST);
  assert.equal(formProblem(form({wind_limit: NaN}), RANGE), GUST);
  assert.equal(formProblem(form({end_hour: Infinity, start_hour: Infinity}), RANGE), WINDOW);
});

test('several problems at once report only the first: date, then window, then gust', () => {
  const all = {date: '2026-11-09', start_hour: 13, end_hour: 7, wind_limit: 12, gust_limit: 10};
  assert.equal(formProblem(form(all), RANGE), DATE);
  assert.equal(formProblem(form({...all, date: '2026-11-02'}), RANGE), WINDOW);
  assert.equal(formProblem(form({...all, date: '2026-11-02', end_hour: 14}), RANGE), GUST);
});

test('the form\'s default date (tomorrow) is always inside the offered range', async () => {
  const {alertDate} = await import('../web/alerts.ts');
  for (const iso of ['2026-11-01T06:30:00Z', '2026-10-26T07:30:00Z', '2026-12-31T23:30:00Z', '2026-03-08T09:59:00Z']) {
    const now = Date.parse(iso), range = dateRange('America/Los_Angeles', now);
    assert.equal(formProblem(form({date: alertDate('America/Los_Angeles', now)}), range), null, iso);
  }
});

test('the dialog offers the range on the date input and checks before any request is sent', () => {
  const src = readFileSync(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  assert.match(src, /range = dateRange\(region\.timezone\)/, 'computed at render from the region zone');
  assert.match(src, /<input name="date" type="date" defaultValue=\{alertDate\(region\.timezone\)\} min=\{range\.min\} max=\{range\.max\} required \/>/);
  const save = src.slice(src.indexOf('const save = async'), src.indexOf('const act = '));
  const check = save.indexOf('const problem = formProblem(form, dateRange(region.timezone));');
  const stop = save.indexOf('if (problem) { setStatus(problem); return; }');
  assert.ok(check > 0 && stop > check, 'save checks the form first and stops with the message');
  assert.ok(save.indexOf("api('trips'") > stop, 'the request comes only after the check');
  assert.equal(save.match(/api\(/g)?.length, 1, 'no other request in save');
  for (const field of ['start_hour" type="number" min="0" max="22"', 'end_hour" type="number" min="1" max="23"', 'wind_limit" type="number" min="1" max="30"', 'gust_limit" type="number" min="1" max="40"'])
    assert.ok(src.includes(field), `other inputs keep their limits: ${field}`);
});

// SC1822-03: Use again fills the form from a saved trip and sends nothing.
const {reuseTrip, reusedLimits, reuseStatus, reuseLimitsNote, fillAlertForm} = await import('../web/alerts.ts');
const deepFreeze = o => { for (const v of Object.values(o)) if (v && typeof v === 'object') deepFreeze(v); return Object.freeze(o); };
const REGION = deepFreeze({id: 'central', timezone: 'America/Los_Angeles', species: ['rockfish', 'lingcod'], forecast_points: [{id: 'sur', name: 'Point Sur'}, {id: 'mry', name: 'Monterey'}]});
const SAVED = {id: 't1', region: 'central', date: '2026-10-24', point: 'mry', species: 'lingcod', start_hour: 6, end_hour: 11, wind_limit: 9, gust_limit: 14, sea_limit: 2.5};
const fakeForm = (start = {}) => {
  const controls = {};
  for (const n of ['date', 'point', 'start_hour', 'end_hour', 'wind_limit', 'gust_limit', 'sea_limit']) controls[n] = {value: start[n] ?? 'typed', focused: 0, focus() { this.focused++; }};
  return {controls, elements: {namedItem: n => controls[n] ?? null}};
};

test('reuse_upcoming_and_past_copy_exact_window: area, species, hours and limits as stored; the source is untouched', () => {
  const source = deepFreeze({...SAVED});
  assert.deepEqual(reuseTrip(source, REGION), {fields: {point: 'mry', start_hour: 6, end_hour: 11, wind_limit: 9, gust_limit: 14, sea_limit: 2.5}, species: 'lingcod', omitted: []});
  const second = deepFreeze({...SAVED, id: 't2', point: 'sur', species: 'rockfish', start_hour: 5, end_hour: 9, wind_limit: 12, gust_limit: 12, sea_limit: 4});
  const form = fakeForm();
  fillAlertForm(form, reuseTrip(source, REGION));
  fillAlertForm(form, reuseTrip(second, REGION));
  assert.deepEqual(Object.fromEntries(Object.entries(form.controls).map(([k, c]) => [k, c.value])), {date: '', point: 'sur', start_hour: '5', end_hour: '9', wind_limit: '12', gust_limit: '12', sea_limit: '4'});
  assert.equal(source.point, 'mry');
});

test('reuse_requires_new_date_and_focuses_it: the date is emptied on every reuse and focused; the old date is never copied', () => {
  const fake = fakeForm({date: '2026-11-03'});
  fillAlertForm(fake, reuseTrip(SAVED, REGION));
  assert.equal(fake.controls.date.value, '');
  assert.equal(fake.controls.date.focused, 1);
  fake.controls.date.value = '2026-11-04';
  fillAlertForm(fake, reuseTrip(SAVED, REGION));
  assert.equal(fake.controls.date.value, '');
  assert.equal(fake.controls.date.focused, 2);
  assert.notEqual(fake.controls.date.value, SAVED.date);
  assert.equal(formProblem(form({date: ''}), RANGE), DATE, 'an empty date is refused before any request');
  assert.equal(formProblem(form({date: RANGE.min}), RANGE), null);
  assert.equal(formProblem(form({date: RANGE.max}), RANGE), null);
});

test('reuse_retired_area_and_species_leave_current_choices: only what still exists is copied and the rest is named', () => {
  const retiredArea = reuseTrip({...SAVED, point: 'gone'}, REGION);
  assert.ok(!('point' in retiredArea.fields));
  assert.deepEqual(retiredArea.omitted, ['area']);
  assert.equal(retiredArea.species, 'lingcod');
  const retiredSpecies = reuseTrip({...SAVED, species: 'halibut'}, REGION);
  assert.equal(retiredSpecies.species, null);
  assert.equal(retiredSpecies.fields.point, 'mry');
  assert.deepEqual(retiredSpecies.omitted, ['species']);
  assert.deepEqual(reuseTrip({...SAVED, point: 'gone', species: 'halibut'}, REGION).omitted, ['area', 'species']);
  assert.deepEqual(reuseTrip({...SAVED, region: 'north'}, REGION).omitted, ['area'], 'the same point id from another region is not the same area');
  assert.deepEqual(reuseTrip({...SAVED, region: undefined}, REGION).omitted, ['area']);
  const named = {...REGION, species: ['rockfish'], target_options: [{id: 'lingcod', name: 'Lingcod'}]};
  assert.equal(reuseTrip(SAVED, named).species, null, 'listed only as a target option is not listed');
  const empty = reuseTrip(SAVED, {...REGION, species: [], forecast_points: []});
  assert.deepEqual(empty.omitted, ['area', 'species']);
  const form = fakeForm();
  fillAlertForm(form, retiredArea);
  assert.equal(form.controls.point.value, 'typed', 'the current area is kept, no retired option is injected');
  assert.equal(reuseStatus(['area', 'species']), 'Window copied. Choose a date, then save. Area was not copied because it is no longer offered in this region. Alert species was not copied because it is no longer listed in this region.');
  assert.equal(reuseStatus([]), 'Window copied. Choose a date, then save.');
});

test('reuse_legacy_numeric_fields_are_not_scaled_or_invented: bad numbers stay untouched and are reported', () => {
  const r = reuseTrip(deepFreeze({...SAVED, sea_limit: 0.5, wind_limit: 1, gust_limit: 40}), REGION);
  assert.deepEqual([r.fields.sea_limit, r.fields.wind_limit, r.fields.gust_limit], [0.5, 1, 40]);
  for (const bad of [{start_hour: undefined}, {start_hour: 7.5}, {end_hour: 6}, {end_hour: 24}, {start_hour: 23, end_hour: 23}, {start_hour: NaN}]) {
    const got = reuseTrip({...SAVED, ...bad}, REGION);
    assert.deepEqual(got.omitted, ['hours'], JSON.stringify(bad));
    assert.ok(!('start_hour' in got.fields) && !('end_hour' in got.fields));
  }
  for (const bad of [{wind_limit: 31}, {gust_limit: 8}, {wind_limit: null}, {gust_limit: Infinity}, {wind_limit: 9.5}]) {
    const got = reuseTrip({...SAVED, ...bad}, REGION);
    assert.deepEqual(got.omitted, ['limits'], JSON.stringify(bad));
    assert.ok(!('wind_limit' in got.fields) && !('gust_limit' in got.fields));
    assert.equal(got.fields.sea_limit, 2.5);
    assert.equal(reusedLimits(got.fields), 'some');
  }
  const noSea = reuseTrip({...SAVED, sea_limit: 2.25}, REGION);
  assert.deepEqual(noSea.omitted, ['limits']);
  assert.equal(noSea.fields.wind_limit, 9);
  const none = reuseTrip({...SAVED, wind_limit: undefined, gust_limit: undefined, sea_limit: undefined}, REGION);
  assert.equal(reusedLimits(none.fields), 'none');
  assert.deepEqual(none.omitted, ['limits']);
  assert.equal(reusedLimits(reuseTrip(SAVED, REGION).fields), 'all');
});

test('reuse_note_replaces_initial_provenance: the limits come from the saved trip and the current boat or offshore caveat stays truthful', () => {
  assert.equal(reuseLimitsNote('2026-10-24', 'all', false), 'Limits start from your saved trip on 2026-10-24; you can edit them before saving. Alerts still judge wind, gusts and offshore seas only, not surf at your launch or beach.');
  assert.equal(reuseLimitsNote('2026-10-24', 'some', true), "Some limits start from your saved trip on 2026-10-24; other limits were left unchanged. Alerts use your current boat settings, not the old trip's boat.");
  for (const note of [reuseLimitsNote('2026-10-24', 'all', true), reuseLimitsNote('2026-10-24', 'some', false)]) assert.doesNotMatch(note, /saved boat|reference 23 ft|Boat limits|your .* limits;/);
  const src = readFileSync(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  assert.match(src, /reuse && reuse\.copied !== 'none' \? reuseLimitsNote\(reuse\.date, reuse\.copied, p === 'boat'\) : p !== 'boat'/, 'the initial notes remain the fallback');
});

test('reuse_sends_nothing_until_explicit_save: filling the form makes no request and Use again has no network or storage path', async () => {
  const oldFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = (...a) => { calls.push(a); return Promise.reject(Error('no request expected')); };
  try { fillAlertForm(fakeForm(), reuseTrip(SAVED, REGION)); } finally { globalThis.fetch = oldFetch; }
  assert.equal(calls.length, 0);
  const src = readFileSync(new URL('../web/app/TripAlerts.tsx', import.meta.url), 'utf8');
  const handler = src.slice(src.indexOf('const useAgain = (trip'), src.indexOf('/** Cancel returns focus'));
  assert.ok(handler.length > 100 && !/api\(|refresh|ack\(|fetch|localStorage|sessionStorage|enablePush|location|submit|requestSubmit/.test(handler), 'Use again only fills the form');
  const save = src.slice(src.indexOf('const save = async'), src.indexOf('const act = '));
  assert.ok(save.indexOf('region.forecast_points.some') > save.indexOf('formProblem') && save.indexOf("api('trips'") > save.indexOf('region.species.includes'), 'save checks the current area and species before the one request');
  assert.match(src, /<Button type="submit" variant="primary" disabled=\{unavailable\}>Save this fishing window<\/Button>/);
});
