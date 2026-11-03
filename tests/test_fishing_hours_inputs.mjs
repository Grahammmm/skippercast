// RF1300-13: wanted time that is not a positive finite number reads no-wanted;
// an unreadable or non-positive daylight span never yields beyond-daylight.
import test from 'node:test';
import assert from 'node:assert/strict';
import {fishingHours} from '../web/brief/fishing-hours.ts';
import {planRun} from '../web/brief/run.ts';
const window = {start: '2026-10-12T07:00:00-07:00', end: '2026-10-12T12:00:00-07:00', reasons: []};
const brief = {windows: [window], alerts: [], tiles: [], missing: []};
const run = planRun(brief, {name: 'Synthetic reef', nm: 7.4}, 20, new Date('2026-10-12T05:00:00-07:00'));
const rule = {status: 'open', opensAt: null, label: 'Open', reason: 'Local rules apply.'};
const options = {wantedMin: 240, sunrise: '2026-10-12T06:52:00-07:00', sunset: '2026-10-12T17:21:00-07:00', rule};
const calc = (over = {}, r = run) => fishingHours(r, {...options, ...over});
// Fixed 180-minute run: arrive 08:00, turn back 11:00.
const run180 = {...run, arrive: '2026-10-12T08:00:00-07:00', turnBack: '2026-10-12T11:00:00-07:00'};
const noNaN = result => { for (const [k, v] of Object.entries(result)) assert.ok(!Number.isNaN(v), `field ${k} is NaN`); };
const BAD_WANTED = [NaN, Infinity, -Infinity, 0, -30, -0.5];

test('non-finite or non-positive wanted time reads no-wanted, never a NaN shortfall', () => {
  for (const wantedMin of BAD_WANTED) {
    const result = calc({wantedMin});
    assert.deepEqual(result, {kind: 'no-wanted'}, `wantedMin ${wantedMin}`);
    noNaN(result);
    assert.deepEqual(calc({wantedMin}, run180), {kind: 'no-wanted'}, `run180 wantedMin ${wantedMin}`);
    for (const status of ['unknown', 'restricted']) assert.deepEqual(calc({wantedMin, rule: {...rule, status}}), {kind: 'no-wanted'});
  }
});

test('positive finite wanted time keeps enough/short answers unchanged', () => {
  assert.deepEqual(calc({wantedMin: 120}, run180), {kind: 'enough', availableMin: 180, wantedMin: 120, spareMin: 60});
  assert.deepEqual(calc({wantedMin: 240}, run180), {kind: 'short', availableMin: 180, wantedMin: 240, shortMin: 60, endedBy: 'conditions'});
  assert.deepEqual(calc({wantedMin: 180}, run180), {kind: 'enough', availableMin: 180, wantedMin: 180, spareMin: 0});
  assert.deepEqual(calc({wantedMin: 0.5}, run180), {kind: 'enough', availableMin: 180, wantedMin: 0.5, spareMin: 179.5});
  for (const r of [calc({wantedMin: 120}, run180), calc({wantedMin: 240}, run180)]) noNaN(r);
});

test('sunset before sunrise never gives beyond-daylight and matches a missing sunset', () => {
  const swapped = {sunrise: '2026-10-12T06:52:00-07:00', sunset: '2026-10-12T04:52:00-07:00'};
  for (const wantedMin of [60, 120, 240]) {
    const result = calc({...swapped, wantedMin}, run180);
    assert.notEqual(result.kind, 'beyond-daylight');
    assert.deepEqual(result.kind, calc({sunset: null, wantedMin}, run180).kind);
    noNaN(result);
  }
  assert.deepEqual(calc({...swapped, wantedMin: 60}), calc({sunset: null, wantedMin: 60}));
  assert.deepEqual(calc({...swapped, wantedMin: 60}, run180), calc({sunset: null, wantedMin: 60}, run180));
});

test('zero or unreadable daylight skips the comparison', () => {
  const same = '2026-10-12T06:52:00-07:00';
  const zero = calc({sunrise: same, sunset: same, wantedMin: 60}, run180);
  assert.deepEqual(zero, {kind: 'enough', availableMin: 180, wantedMin: 60, spareMin: 120});
  assert.equal(calc({sunrise: same, sunset: same, wantedMin: 720}, run180).kind, 'short');
  for (const sunrise of ['garbage', '']) {
    assert.deepEqual(calc({sunrise, wantedMin: 60}, run180), {kind: 'enough', availableMin: 180, wantedMin: 60, spareMin: 120});
    assert.equal(calc({sunrise, wantedMin: 720}, run180).kind, 'short');
  }
  assert.equal(calc({sunset: 'garbage', wantedMin: 720}, run180).kind, 'short');
});

test('real daylight still yields beyond-daylight with the true span', () => {
  const day = {sunrise: '2026-10-12T07:00:00-07:00', sunset: '2026-10-12T17:00:00-07:00'};
  assert.deepEqual(calc({...day, wantedMin: 700}, run180), {kind: 'beyond-daylight', daylightMin: 600, wantedMin: 700});
  assert.deepEqual(calc({...day, wantedMin: 600}, run180), {kind: 'short', availableMin: 180, wantedMin: 600, shortMin: 420, endedBy: 'conditions'});
  assert.equal(calc({...day, wantedMin: 601}, run180).kind, 'beyond-daylight');
});

test('closed and no-time answers keep precedence over a bad wanted time', () => {
  for (const wantedMin of BAD_WANTED) {
    for (const status of ['closed', 'excluded']) assert.deepEqual(calc({wantedMin, rule: {...rule, status}}), {kind: 'closed', label: rule.label, reason: rule.reason});
    const none = calc({wantedMin}, {...run, kind: 'no-time'});
    assert.equal(none.kind, 'none');
    assert.equal(none.endedBy, 'conditions');
    assert.equal(calc({wantedMin, rule: {...rule, status: 'unknown'}}, {...run, kind: 'no-time'}).rulesUnconfirmed, true);
  }
});
