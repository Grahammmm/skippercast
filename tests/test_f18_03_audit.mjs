// SCA-531 / F18-03: an absent bar driver (swell period, wind direction) that could change the band must read
// "not fully judged", never a judged "No bar flag". Offline synthetic fixture; no network, no real entrance data.
// The checker is counterfactual: fill the missing driver with the value that would raise the band and see if the
// band moves. Valid controls must satisfy the contract. The affected cases are only *observed* (diagnostics): the test
// neither asserts the gap is desirable nor fails when it is fixed. A synthetic negative control proves the detector.
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
  // independent negative control: fabricated results, no dependence on the real bar model
  const flag = r => r.couldChange && r.band === 'No bar flag' && r.judged === true;
  assert.equal(flag({band: 'No bar flag', judged: true, couldChange: true}), true, 'gap must be detected');
  assert.equal(flag({band: 'No bar flag', judged: false, couldChange: true}), false, 'not-judged is the correct outcome');
  assert.equal(flag({band: 'Caution', judged: true, couldChange: true}), false, 'known caution is kept');
  assert.equal(flag({band: 'No bar flag', judged: true, couldChange: false}), false, 'calm control cannot matter');
});

test('affected controls: baseline observation only (passes before and after a fix)', t => {
  // Read-only baseline: at the pinned head "ebb 15kt dir missing" reads judged "No bar flag" (the F18-03 gap) and
  // "flood 2ft period missing" is already not judged. Neither outcome is asserted, so a correct fix needs no edit here.
  for (const name of AFFECTED) {
    const r = observe(CASES[name]);
    t.diagnostic(`${name}: band=${r.band} judged=${r.judged} falseReassurance=${r.falseReassurance} reason=${r.reason}`);
  }
});
