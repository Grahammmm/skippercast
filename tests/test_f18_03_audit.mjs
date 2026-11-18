// SCA-531 / F18-03: an absent bar driver (swell period, wind direction) that could change the band must read
// "not fully judged", never a judged "No bar flag". Offline synthetic fixture; no network, no real entrance data.
// The checker is counterfactual: fill the missing driver with the value that would raise the band and see if the
// band moves. Valid controls must satisfy the contract. The affected cases are only *observed*: the test does not
// assert the gap is desirable, and does not fail when it is present; it fails if a NEW gap appears, or if a listed
// gap is fixed without removing it from KNOWN_GAPS (so the list only shrinks).
import test from 'node:test';
import assert from 'node:assert/strict';
import {barHours} from '../packages/coast/src/bar-conditions.ts';
import {entranceWindow} from '../packages/coast/src/entrance-window.ts';

const H = 3600000, base = Date.parse('2026-06-15T17:00:00Z');
const iso = i => new Date(base + i * H).toISOString();
const ev = (i, type) => ({at: iso(i), type, heightFt: type === 'H' ? 5 : 1});
const entrance = {name: 'Synthetic', seawardDeg: 260};
const TIDES = {flood: [ev(-3, 'L'), ev(3, 'H')], ebb: [ev(-3, 'H'), ev(3, 'L')]};
const hour = (waveFt, wavePeriodS, windKnots, windDirectionDeg) =>
  ({at: iso(0), waveFt, wavePeriodS, windKnots, gustKnots: windKnots + 2, windDirectionDeg});

function observe({tide, waveFt, period, knots, dir}) {
  const run = h => {
    const bars = barHours({hours: [h], entrance, tideEvents: TIDES[tide]});
    const win = entranceWindow(bars, {entrance, sunrise: base, sunset: base + H});
    return {band: bars[0].band, judged: win.judged, reason: win.reason};
  };
  const seen = run(hour(waveFt, period, knots, dir));
  // Counterfactuals: the worst plausible fill for each absent driver.
  const alts = [];
  if (period === null) alts.push(run(hour(waveFt, 16, knots, dir)));
  if (dir === null) alts.push(run(hour(waveFt, period, knots, entrance.seawardDeg)));
  const couldChange = alts.some(a => a.band !== seen.band);
  const falseReassurance = couldChange && seen.band === 'No bar flag' && seen.judged === true;
  return {...seen, couldChange, falseReassurance};
}

const CASES = {
  // valid controls: the contract holds
  'flood 2ft period known, calm wind dir known':    {tide: 'flood', waveFt: 2, period: 8, knots: 3, dir: 80},
  'flood 2ft period 16 known (caution kept)':       {tide: 'flood', waveFt: 2, period: 16, knots: 3, dir: 80},
  'ebb 15kt dir known 260 (caution kept)':          {tide: 'ebb', waveFt: 1, period: 8, knots: 15, dir: 260},
  'ebb calm wind, dir missing (cannot matter)':     {tide: 'ebb', waveFt: 1, period: 8, knots: 3, dir: null},
  'flood 12ft period missing (hazard kept)':        {tide: 'flood', waveFt: 12, period: null, knots: 3, dir: 80},
  // affected controls: absent driver that could change the band
  'flood 2ft period missing':                       {tide: 'flood', waveFt: 2, period: null, knots: 3, dir: 80},
  'ebb 15kt dir missing':                           {tide: 'ebb', waveFt: 1, period: 8, knots: 15, dir: null},
};
const VALID = Object.keys(CASES).slice(0, 5), AFFECTED = Object.keys(CASES).slice(5);
// Baseline at the pinned head: cases still showing the gap. Remove an entry when its case is fixed.
const KNOWN_GAPS = new Set(['ebb 15kt dir missing']);

test('expected observations at the baseline head', () => {
  const o = Object.fromEntries(Object.entries(CASES).map(([k, v]) => [k, observe(v)]));
  assert.equal(o['flood 2ft period known, calm wind dir known'].band, 'No bar flag');
  assert.equal(o['flood 2ft period 16 known (caution kept)'].band, 'Caution');
  assert.equal(o['ebb 15kt dir known 260 (caution kept)'].band, 'Caution');
  assert.equal(o['flood 12ft period missing (hazard kept)'].band, 'Hazardous');
  assert.equal(o['ebb 15kt dir known 260 (caution kept)'].judged, true);
});

test('valid controls satisfy the contract', () => {
  for (const name of VALID) {
    const r = observe(CASES[name]);
    assert.equal(r.falseReassurance, false, `${name}: ${JSON.stringify(r)}`);
  }
});

test('calm wind control: missing direction cannot change the band', () => {
  const r = observe(CASES['ebb calm wind, dir missing (cannot matter)']);
  assert.equal(r.couldChange, false);
});

test('checker detects the stated gap on a synthetic false reassurance', () => {
  // negative control: a fabricated judged "No bar flag" while the counterfactual moves the band
  const bad = {band: 'No bar flag', judged: true, couldChange: true};
  assert.equal(bad.couldChange && bad.band === 'No bar flag' && bad.judged === true, true);
  const direct = observe(CASES['ebb 15kt dir missing']);
  assert.equal(direct.couldChange, true, 'direction counterfactual must move the band (detector is live)');
});

test('affected controls: no new gap, and known gaps only shrink', t => {
  for (const name of AFFECTED) {
    const r = observe(CASES[name]);
    t.diagnostic(`${name}: band=${r.band} judged=${r.judged} falseReassurance=${r.falseReassurance} reason=${r.reason}`);
    if (KNOWN_GAPS.has(name)) {
      assert.equal(r.falseReassurance, true, `${name} no longer shows the gap: remove it from KNOWN_GAPS`);
    } else {
      assert.equal(r.falseReassurance, false, `${name}: false reassurance (absent driver could change the band)`);
    }
  }
});
