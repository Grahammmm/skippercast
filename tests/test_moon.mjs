import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {moonLine, moonPhase} from '../web/moon.ts';

// Instants typed from the U.S. Naval Observatory "Phases of the Moon" table for 2026 (aa.usno.navy.mil/data/MoonPhases), UT.
const NEW = ['2026-01-18T19:52Z', '2026-02-17T12:01Z', '2026-03-19T01:23Z', '2026-04-17T11:52Z', '2026-05-16T20:01Z', '2026-06-15T02:54Z', '2026-07-14T09:44Z', '2026-08-12T17:37Z'];
const FULL = ['2026-01-03T10:03Z', '2026-02-01T22:09Z', '2026-03-03T11:38Z', '2026-04-02T02:12Z', '2026-05-01T17:23Z', '2026-05-31T08:45Z', '2026-06-29T23:57Z', '2026-07-29T14:36Z'];
const HOUR = 3600000;

test('new moons: name new and fraction at most 0.02 (Meeus ch. 48 is good to about 0.005)', () => {
  for (const t of NEW) {
    const m = moonPhase(new Date(t));
    assert.equal(m.name, 'new', t);
    assert.ok(m.fraction <= 0.02, `${t} ${m.fraction}`);
  }
});

test('full moons: name full and fraction at least 0.98', () => {
  for (const t of FULL) {
    const m = moonPhase(new Date(t));
    assert.equal(m.name, 'full', t);
    assert.ok(m.fraction >= 0.98, `${t} ${m.fraction}`);
  }
});

test('quarters (USNO): last quarter 2026-01-10 15:48, first quarter 2026-01-26 04:47 and 2026-02-24 12:28', () => {
  for (const [t, name] of [['2026-01-10T15:48Z', 'last quarter'], ['2026-01-26T04:47Z', 'first quarter'], ['2026-02-24T12:28Z', 'first quarter']]) {
    const m = moonPhase(new Date(t));
    assert.equal(m.name, name, t);
    assert.ok(m.fraction >= 0.45 && m.fraction <= 0.55, `${t} ${m.fraction}`);
  }
});

test('between phases the intermediate names follow waxing and waning', () => {
  const at = (t, h) => moonPhase(new Date(Date.parse(t) + h * HOUR)).name;
  assert.equal(at('2026-02-17T12:01Z', 72), 'waxing crescent');
  assert.equal(at('2026-02-17T12:01Z', 24 * 10), 'waxing gibbous');
  assert.equal(at('2026-03-03T11:38Z', 72), 'waning gibbous');
  assert.equal(at('2026-03-03T11:38Z', 24 * 10), 'waning crescent');
  // more than a day either side of a principal phase is not that phase
  assert.notEqual(at('2026-02-17T12:01Z', 36), 'new');
  assert.notEqual(at('2026-02-17T12:01Z', -36), 'new');
  assert.equal(at('2026-02-17T12:01Z', -36), 'waning crescent');
});

test('a day crossing a phase boundary takes the name of its local noon, not UTC noon', () => {
  // New moon 2026-01-18 19:52 UT. On 2026-01-17 UTC noon is waning crescent, Los Angeles noon (20:00 UT) is new.
  assert.equal(moonPhase(new Date('2026-01-17T12:00Z')).name, 'waning crescent');
  assert.equal(moonLine('2026-01-17', 'America/Los_Angeles'), 'Moon: new, 1% lit');
  assert.equal(moonLine('2026-01-17', 'UTC'), 'Moon: waning crescent, 2% lit');
});

test('local noon follows daylight saving time', () => {
  // 2026-03-26 noon PDT is 19:00 UT: first quarter at UTC noon, waxing gibbous at local noon.
  assert.equal(moonLine('2026-03-26', 'America/Los_Angeles'), 'Moon: waxing gibbous, 61% lit');
});

test('the line reads "Moon: <name>, <n>% lit" and makes no rise, set, solunar, bite or feeding claim', () => {
  const line = moonLine('2026-02-10', 'America/Los_Angeles');
  assert.match(line, /^Moon: (new|waxing crescent|first quarter|waxing gibbous|full|waning gibbous|last quarter|waning crescent), \d{1,3}% lit$/);
  assert.equal(line, 'Moon: waning crescent, 38% lit');
  const forbidden = /rise|\bset\b|solunar|bite|feed|good fishing/i;
  assert.doesNotMatch(line, forbidden);
  const code = readFileSync(new URL('../web/moon.ts', import.meta.url), 'utf8').split('\n').filter(l => !l.trimStart().startsWith('//')).join('\n');
  assert.doesNotMatch(code, forbidden);
});

test('the Conditions view shows the line under Tide events for the dock day and feeds nothing else', () => {
  const src = readFileSync(new URL('../web/app/views/Conditions.tsx', import.meta.url), 'utf8');
  assert.equal(src.split('moonLine(').length - 1, 1);
  assert.ok(src.indexOf('Tide events') < src.indexOf('moonLine(') && src.indexOf('moonLine(') < src.indexOf('Before you go'));
  assert.match(src, /moonLine\(state\.day, tz\)/);
});
