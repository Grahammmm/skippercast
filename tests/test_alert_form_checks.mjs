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
