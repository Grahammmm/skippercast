// Frame selection and the time dock's clock (FE-12, docs/plans/front-end/dev-plan.md):
// fish's frame-gate cases (tests/ocean.test.ts in the fish repository) run through
// web/map/frames.ts, the wrapper over packages/coast's selectCurrentFrame,
// selectedCurrent and cloudSource, plus the gates that wrapper adds for the cloud
// loop. Then the 169-hour horizon, the dock's time and play from web/hour.ts.
// Fixtures are synthetic. Both modules run by type stripping.
import assert from 'node:assert/strict';
import test from 'node:test';
import {chosenCurrent, cloudFrames, cloudImage, cloudTiles, currentFrame} from '../web/map/frames.ts';
import {HORIZON_HOURS, dockTime, horizonDays, nearestHour, nextHour, play} from '../web/hour.ts';

const TZ = 'America/Los_Angeles';
const NOW = new Date('2026-10-02T03:00:00Z');
const H = 3_600_000, MIN = 60_000;
const iso = ms => new Date(ms).toISOString();
const cell = {lat: 35.35, lon: -120.95, uMs: 0, vMs: 0.51, speedKnots: 1, towardDeg: 0};
const forecast = (patch = {}) => ({
  id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS', url: 'https://example.test/wcofs', fetchedAt: '2026-10-02T02:00:00Z',
  issuedAt: '2026-10-01T03:00:00Z', sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
  frames: [{validAt: '2026-10-02T03:00:00.000Z', cells: [cell]}, {validAt: '2026-10-02T06:00:00.000Z', cells: [cell]}],
  attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.', ...patch,
});
const radar = (patch = {}) => forecast({
  id: 'hfr-1', kind: 'observation', label: 'HF radar', issuedAt: null, sampleAt: '2026-10-02T02:00:00Z', nativeResolutionKm: 1,
  frames: [{validAt: '2026-10-02T02:00:00.000Z', cells: [cell]}], ...patch,
});

// [case, field, selected hour, now, expected validAt or null]
const CURRENT_GATES = [
  // fish: future selected hour uses the native forecast without aging it at the future clock.
  ['forecast: nearest native frame within 90 min', forecast(), '2026-10-02T04:00:00Z', NOW, '2026-10-02T03:00:00.000Z'],
  ['forecast: past the last frame', forecast(), '2026-10-02T07:00:00Z', NOW, null],
  ['forecast: exactly 90 min from the nearest frame', forecast({frames: [{validAt: '2026-10-02T03:00:00.000Z', cells: [cell]}, {validAt: '2026-10-02T09:00:00.000Z', cells: [cell]}]}), '2026-10-02T04:30:00Z', NOW, '2026-10-02T03:00:00.000Z'],
  ['forecast: 91 min from the nearest frame', forecast({frames: [{validAt: '2026-10-02T03:00:00.000Z', cells: [cell]}, {validAt: '2026-10-02T09:00:00.000Z', cells: [cell]}]}), '2026-10-02T04:31:00Z', NOW, null],
  ['forecast: before the first frame', forecast(), '2026-10-02T02:00:00Z', NOW, null],
  ['forecast: issued 35 h ago', forecast({issuedAt: iso(NOW - 35 * H)}), '2026-10-02T03:00:00Z', NOW, '2026-10-02T03:00:00.000Z'],
  ['forecast: issued over 36 h ago', forecast({issuedAt: iso(NOW - 36 * H - MIN)}), '2026-10-02T03:00:00Z', NOW, null],
  ['forecast: issued over 5 min ahead', forecast({issuedAt: iso(NOW.getTime() + 6 * MIN)}), '2026-10-02T03:00:00Z', NOW, null],
  ['forecast: fetched over 6 h ago (fish: a day later)', forecast(), NOW, new Date('2026-10-03T03:00:00Z'), null],
  ['forecast: a frame without cells', forecast({frames: [{validAt: '2026-10-02T03:00:00.000Z', cells: []}]}), '2026-10-02T03:00:00Z', NOW, null],
  // fish: radar serves now, never a future timeline hour.
  ['radar: now', radar(), NOW, NOW, '2026-10-02T02:00:00.000Z'],
  ['radar: a future hour', radar(), '2026-10-02T04:00:00Z', NOW, null],
  ['radar: frame 6 h old', radar({frames: [{validAt: iso(NOW - 6 * H), cells: [cell]}]}), NOW, NOW, iso(NOW - 6 * H)],
  ['radar: frame over 6 h old', radar({frames: [{validAt: iso(NOW - 6 * H - MIN), cells: [cell]}]}), NOW, NOW, null],
  ['radar: fetched over 6 h ago', radar({fetchedAt: iso(NOW - 6 * H - MIN)}), NOW, NOW, null],
  ['radar: an hour before its only frame', radar(), '2026-10-02T01:00:00Z', NOW, null],
];

test('current frame gates: forecast ±90 min and a 36 h issue, radar at most 6 h old (fish cases)', () => {
  for (const [name, field, at, now, expected] of CURRENT_GATES) {
    assert.equal(currentFrame(field, new Date(at), now)?.validAt ?? null, expected, name);
  }
});

test('the chosen source only: off, unlisted, missing or duplicated products give no frame', () => {
  const fields = [forecast(), radar()];
  assert.equal(chosenCurrent(fields, 'wcofs', new Date('2026-10-02T04:00:00Z'), NOW)?.frame.validAt, '2026-10-02T03:00:00.000Z');
  assert.equal(chosenCurrent(fields, 'hfr-1', NOW, NOW)?.field.id, 'hfr-1');
  assert.equal(chosenCurrent(fields, 'hfr-1', new Date('2026-10-02T04:00:00Z'), NOW), null, 'a future hour never falls back to the forecast');
  for (const choice of ['off', 'unsupported', 'hfr-6', '']) assert.equal(chosenCurrent(fields, choice, NOW, NOW), null, choice);
  assert.equal(chosenCurrent([forecast(), forecast()], 'wcofs', NOW, NOW), null, 'two products under one id are ambiguous');
  assert.equal(chosenCurrent(null, 'wcofs', NOW, NOW), null);
  assert.equal(chosenCurrent(fields, 'wcofs', NOW, NOW)?.expiresAt, Math.min(Date.parse('2026-10-02T02:00:00Z') + 6 * H, Date.parse('2026-10-01T03:00:00Z') + 36 * H));
});

// goes-times.json as FE-44 publishes it: about two hours of five-minute frames, newest 7 min before NOW.
const LISTED = Array.from({length: 24}, (_, i) => iso(Date.parse('2026-10-02T00:58:00Z') + i * 5 * MIN));
const image = (patch = {}) => ({
  id: 'goes-longwave', kind: 'observation', observedAt: LISTED.at(-1), fetchedAt: '2026-10-02T02:55:00Z', availableTimes: LISTED,
  layer: 'goes_longwave_imagery', url: 'https://nowcoast.noaa.gov/geoserver/observations/satellite/ows', attribution: 'NOAA / NESDIS · GOES',
  license: 'public-domain-us-gov', limitations: 'Observed frames only.', ...patch,
});

test('clouds: listed frames inside 90 minutes on today only; the window is applied to the two-hour index', () => {
  assert.equal(LISTED.at(-1), '2026-10-02T02:53:00.000Z');
  const frames = cloudFrames(image(), NOW, NOW, TZ);
  assert.equal(frames[0], '2026-10-02T01:33:00.000Z', 'the oldest kept frame is under 90 minutes old');
  assert.equal(frames.at(-1), '2026-10-02T02:53:00.000Z');
  assert.ok(frames.every(at => NOW - Date.parse(at) <= 90 * MIN), 'every frame inside the window');
  assert.equal(frames.length, 17, 'frames from 01:28 back are withheld');
  // fish: acquisition times come from metadata and expire independently.
  assert.match(cloudTiles(image(), LISTED.at(-1), NOW).tiles[0], /time=2026-10-02T02%3A53%3A00\.000Z/);
  assert.equal(cloudTiles(image(), LISTED.at(-1), new Date('2026-10-02T05:00:00Z')), null, 'over 90 minutes old');
  assert.equal(cloudTiles(image(), '2026-10-02T02:54:00Z', NOW), null, 'an unlisted time is never requested');
  assert.deepEqual(cloudFrames(image(), NOW, new Date('2026-10-02T05:00:00Z'), TZ), [], 'a stale index shows nothing');
  // The day gate: NOW is 8 pm on 1 October in Los Angeles.
  assert.equal(cloudFrames(image(), new Date('2026-10-02T06:00:00Z'), NOW, TZ).length, 17, 'a later hour of today keeps the observed loop');
  assert.deepEqual(cloudFrames(image(), new Date('2026-10-02T08:00:00Z'), NOW, TZ), [], 'withheld on a future day (1 am on 2 October)');
  assert.deepEqual(cloudFrames(image(), new Date('2026-09-30T20:00:00Z'), NOW, TZ), [], 'withheld on a past day');
  const ahead = image({availableTimes: [...LISTED, iso(NOW.getTime() + 10 * MIN)]});
  assert.ok(!cloudFrames(ahead, NOW, NOW, TZ).includes(iso(NOW.getTime() + 10 * MIN)), 'a time over five minutes ahead is withheld');
  assert.deepEqual(cloudFrames(null, NOW, NOW, TZ), []);
});

test('a GOES index is admitted only in the CloudImage shape goes-times.json publishes', () => {
  assert.equal(cloudImage(image())?.observedAt, '2026-10-02T02:53:00.000Z');
  for (const patch of [{id: 'goes-visible'}, {kind: 'forecast'}, {layer: 'other'}, {observedAt: 'latest'}, {observedAt: '2026-10-02T02:54:00Z'}, {availableTimes: []}, {availableTimes: ['current']}, {attribution: 1}, {fetchedAt: null}]) {
    assert.equal(cloudImage(image(patch)), null, JSON.stringify(patch));
  }
  for (const value of [null, [], 'goes', 1]) assert.equal(cloudImage(value), null);
});

test('the horizon is 169 whole hours by local day; a DST change day keeps every UTC hour', () => {
  const now = new Date('2026-10-05T20:17:00Z'); // Monday, 1:17 pm PDT
  const days = horizonDays(now, TZ);
  assert.equal(days.flatMap(d => d.hours).length, HORIZON_HOURS);
  assert.deepEqual(days.map(d => d.day), ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11', '2026-10-12']);
  assert.deepEqual(days.map(d => d.hours.length), [11, 24, 24, 24, 24, 24, 24, 14], 'today from 1 pm, the last day to 1 pm');
  assert.equal(days[0].hours[0], Date.parse('2026-10-05T20:00:00Z'));
  assert.equal(days.at(-1).hours.at(-1), Date.parse('2026-10-05T20:00:00Z') + 168 * H);
  // Clocks fall back at 2 am PDT on 1 November 2026: that day has 25 hours, two of them read 1 am.
  const fall = horizonDays(new Date('2026-10-29T07:00:00Z'), TZ).find(d => d.day === '2026-11-01');
  assert.equal(fall.hours.length, 25);
  assert.equal(nearestHour(fall.hours, 14, TZ), Date.parse('2026-11-01T22:00:00Z'), '2 pm PST');
});

test('the dock\'s time: ?hour= wins, a later ?day= keeps the hour of day, a stale hour is kept outside', () => {
  const now = new Date('2026-10-05T20:17:00Z');
  const t = (d, h) => dockTime(d, h, now, TZ);
  assert.deepEqual({...t(null, null), hours: t(null, null).hours.length}, {at: Date.parse('2026-10-05T20:00:00Z'), day: '2026-10-05', today: '2026-10-05', hours: 11, index: 0});
  assert.equal(t(null, '2026-10-06T21:00Z').day, '2026-10-06');
  assert.equal(t(null, '2026-10-06T21:00Z').index, 14);
  assert.equal(t('2026-10-08', '2026-10-06T21:00Z').day, '2026-10-06', 'the hour wins over a disagreeing day');
  assert.equal(t('2026-10-08', null).at, Date.parse('2026-10-08T20:00:00Z'), 'a day without an hour: the current hour of day on it');
  assert.equal(t('2026-10-20', null).at, Date.parse('2026-10-05T20:00:00Z'), 'a day outside the horizon without an hour is now');
  const stale = t(null, '2026-09-01T20:00Z');
  assert.deepEqual([stale.at, stale.index, stale.hours.length], [Date.parse('2026-09-01T20:00:00Z'), -1, 0], 'model outages and old links never reset the clock');
  assert.equal(nextHour(Date.parse('2026-10-05T20:00:00Z'), now), Date.parse('2026-10-05T21:00:00Z'));
  assert.equal(nextHour(Date.parse('2026-10-06T06:00:00Z'), now), Date.parse('2026-10-06T07:00:00Z'), 'across midnight');
  assert.equal(nextHour(Date.parse('2026-10-05T20:00:00Z') + 168 * H, now), null, 'the end of the horizon');
  assert.equal(nextHour(Date.parse('2026-09-01T20:00:00Z'), now), null);
});

/** A fake page and media query for play(), and a timer driven by hand. */
function harness({hidden = false, reduced = false} = {}) {
  const make = state => {
    const fns = new Set();
    return {...state, addEventListener: (_t, fn) => fns.add(fn), removeEventListener: (_t, fn) => fns.delete(fn), fire() { for (const fn of [...fns]) fn(); }, fns};
  };
  return {doc: make({hidden}), motion: make({matches: reduced})};
}

test('play steps hours to the end of the horizon and stops; a hidden page pauses it', async t => {
  t.mock.timers.enable({apis: ['setInterval']});
  const now = new Date('2026-10-05T20:17:00Z'), days = horizonDays(now, TZ), all = days.flatMap(d => d.hours);
  let at = all.at(-3), stops = 0;
  const step = () => { const next = nextHour(at, now); if (next === null) return false; at = next; return true; };
  const {doc, motion} = harness();
  play({step, onStop: () => stops++, doc, motion});
  t.mock.timers.tick(1000);
  assert.equal(at, all.at(-2));
  t.mock.timers.tick(1000);
  assert.equal(at, all.at(-1));
  t.mock.timers.tick(1000);
  assert.equal(stops, 1, 'stopped at the end');
  t.mock.timers.tick(5000);
  assert.equal(at, all.at(-1));
  assert.equal(doc.fns.size + motion.fns.size, 0, 'listeners released');

  at = all[0]; stops = 0;
  const page = harness();
  play({step, onStop: () => stops++, doc: page.doc, motion: page.motion});
  t.mock.timers.tick(2000);
  assert.equal(at, all[2]);
  page.doc.hidden = true; page.doc.fire();
  t.mock.timers.tick(3000);
  assert.deepEqual([at, stops], [all[2], 1], 'hidden: paused, no more steps');

  at = all[0]; stops = 0;
  const moving = harness();
  play({step, onStop: () => stops++, doc: moving.doc, motion: moving.motion});
  moving.motion.matches = true; moving.motion.fire();
  t.mock.timers.tick(3000);
  assert.deepEqual([at, stops], [all[0], 1], 'turning on reduced motion stops play');
});

test('prefers-reduced-motion never auto-plays: a press steps one hour', async t => {
  t.mock.timers.enable({apis: ['setInterval']});
  const now = new Date('2026-10-05T20:17:00Z');
  let at = Date.parse('2026-10-05T20:00:00Z'), stops = 0;
  const step = () => { at = nextHour(at, now) ?? at; return true; };
  const {doc, motion} = harness({reduced: true});
  const stop = play({step, onStop: () => stops++, doc, motion});
  t.mock.timers.tick(5000);
  assert.deepEqual([at, stops], [Date.parse('2026-10-05T21:00:00Z'), 1]);
  assert.equal(doc.fns.size, 0);
  stop();
  const hidden = harness({hidden: true});
  play({step, onStop: () => stops++, doc: hidden.doc, motion: hidden.motion});
  assert.deepEqual([at, stops], [Date.parse('2026-10-05T21:00:00Z'), 2], 'a hidden page does not start');
});
