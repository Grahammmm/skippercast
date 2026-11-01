// RF1740-3: a wave/swell period that is not a finite number above 0 s is
// missing in the bar (bar-conditions.ts) and shore (shore-conditions.ts)
// readings: never printed as "at -3 s", never the long-period swell, never
// raising or lowering a band.
import test from 'node:test';
import assert from 'node:assert/strict';

const {barSwell, barBand} = await import('../packages/coast/src/bar-conditions.ts');
const {surf, shoreVerdict} = await import('../packages/coast/src/shore-conditions.ts');

const flood = {stage: 'flood', midEbb: false, fraction: 0.5};
const ebb = {stage: 'ebb', midEbb: false, fraction: 0.2};
const wind = {band: 'Light', side: null, windKnots: 5, gustKnots: 8, directionDeg: null};
const tide = {phase: 'falling', heightFt: 2, veryLow: false, bonus: false};
const offshore = (wavePeriodS, extra = {}) => ({waveFt: 4, wavePeriodS, swellFt: 1, swellPeriodS: 8, ...extra});
const bar = (hour, near, tideAt = flood) => { const swell = barSwell(hour, near); return {swell, ...barBand(tideAt, swell, false)}; };
const shore = (hour, near) => { const s = surf(hour, near); return {surf: s, ...shoreVerdict(s, wind, tide, false)}; };
const noPeriodText = reasons => reasons.every(r => !/ at -?[\d.]+ s/.test(r) && !/NaN|Infinity/.test(r));

test('nearshore period 0 or -3 reads unknown: no " at ... s" in bar or shore reasons', () => {
  for (const periodS of [0, -3]) {
    const b = bar(offshore(9), {waveFt: 3, periodS});
    assert.equal(b.swell.periodS, null, `bar periodS ${periodS}`);
    assert.equal(b.swell.longPeriodS, null);
    assert.equal(b.reasons[0], '3 ft swell');
    assert.ok(noPeriodText(b.reasons), b.reasons.join(' | '));
    const s = shore(offshore(9), {waveFt: 3, periodS});
    assert.equal(s.surf.periodS, null, `shore periodS ${periodS}`);
    assert.equal(s.surf.longPeriodS, null);
    assert.ok(noPeriodText(s.reasons), s.reasons.join(' | '));
    assert.match(s.reasons[0], /^\w+ surf \(3 ft\)$/);
  }
});

test('offshore wavePeriodS -1 reads unknown; the band from height is unchanged', () => {
  for (const wavePeriodS of [-1, 0]) {
    const b = bar(offshore(wavePeriodS)), bNull = bar(offshore(null));
    assert.equal(b.swell.periodS, null);
    assert.equal(b.swell.basis, 'offshore');
    assert.equal(b.band, bNull.band);
    assert.deepEqual(b.reasons, bNull.reasons);
    assert.equal(b.reasons[0], '4 ft swell (offshore estimate)');
    const s = shore(offshore(wavePeriodS)), sNull = shore(offshore(null));
    assert.equal(s.surf.periodS, null);
    assert.equal(s.surf.band, sNull.surf.band);
    assert.equal(s.verdict, sNull.verdict);
    assert.equal(s.score, sNull.score);
    assert.ok(noPeriodText(s.reasons), s.reasons.join(' | '));
  }
});

test('a zero or negative swell period with a tall swell is never the long period; a valid 16 s partition still is', () => {
  for (const swellPeriodS of [0, -16]) {
    const hour = offshore(null, {swellFt: 6, swellPeriodS});
    const b = bar(hour, undefined, ebb);
    assert.equal(b.swell.longPeriodS, null);
    assert.ok(!b.reasons.some(r => r.startsWith('long-period')), b.reasons.join(' | '));
    assert.equal(b.band, bar(offshore(null, {swellFt: 6, swellPeriodS: null}), undefined, ebb).band);
    const s = shore(hour);
    assert.equal(s.surf.longPeriodS, null);
    assert.equal(s.surf.sneaker, false);
    assert.equal(s.surf.sneakerScore, 0);
    assert.deepEqual(s.cautions, []);
    // Nearshore path with the same bad partition: still no long period.
    assert.equal(barSwell(hour, {waveFt: 3, periodS: null}).longPeriodS, null);
    assert.equal(surf(hour, {waveFt: 3, periodS: null}).longPeriodS, null);
  }
  const good = offshore(9, {swellFt: 6, swellPeriodS: 16});
  assert.equal(barSwell(good).longPeriodS, 16);
  assert.ok(bar(good, undefined, ebb).reasons.includes('long-period swell (16 s)'));
  assert.equal(surf(good).longPeriodS, 16);
  assert.equal(surf(good).sneaker, true);
  // A bad wave period beside a valid partition does not hide it.
  assert.equal(barSwell(offshore(-20, {swellFt: 6, swellPeriodS: 16})).longPeriodS, 16);
  assert.equal(surf({waveFt: 3, wavePeriodS: 9, swellFt: 6, swellPeriodS: 16}, {waveFt: 3, periodS: -20}).longPeriodS, 16);
});

test('NaN, Infinity and "12" periods stay unknown (pinned)', () => {
  for (const p of [NaN, Infinity, -Infinity, '12']) {
    assert.equal(barSwell(offshore(9), {waveFt: 3, periodS: p}).periodS, null);
    assert.equal(barSwell(offshore(p)).periodS, null);
    assert.equal(surf(offshore(9), {waveFt: 3, periodS: p}).periodS, null);
    assert.equal(surf(offshore(p)).periodS, null);
    assert.equal(barSwell(offshore(null, {swellFt: 6, swellPeriodS: p})).longPeriodS, null);
    assert.equal(surf(offshore(null, {swellFt: 6, swellPeriodS: p})).longPeriodS, null);
  }
});

test('a valid 9 s period reads exactly as before', () => {
  assert.deepEqual(barSwell(offshore(9), {waveFt: 3, periodS: 9}), {heightFt: 3, periodS: 9, basis: 'nearshore', longPeriodS: 9});
  assert.deepEqual(barSwell(offshore(9)), {heightFt: 4, periodS: 9, basis: 'offshore', longPeriodS: 9});
  assert.equal(bar(offshore(9), {waveFt: 3, periodS: 9}).reasons[0], '3 ft at 9 s swell');
  assert.equal(bar(offshore(9)).reasons[0], '4 ft at 9 s swell (offshore estimate)');
  const s = surf(offshore(9));
  assert.equal(s.periodS, 9);
  assert.equal(s.longPeriodS, 9);
  assert.match(shore(offshore(9)).reasons[0], /^\w+ surf \(4 ft at 9 s, offshore estimate\)$/);
  assert.match(shore(offshore(9), {waveFt: 3, periodS: 9}).reasons[0], /^\w+ surf \(3 ft at 9 s\)$/);
});
