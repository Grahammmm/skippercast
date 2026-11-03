// RF1050-1: the fleet Coverage/AIS health copy prints only real, non-negative figures.
// A negative age (clock skew) or a non-finite duration or share is the existing dash, and
// 59.5-59.99 s reads "1 min" rather than a rounded-up "60 s". Every other value is unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';

const {duration, percent, FLEET_COVERAGE_COPY} = await import('../web/admin/fleet-coverage-copy.ts');
const DASH = '—';

test('duration: negative and non-finite seconds are a dash; zero is "0 s"', () => {
  for (const s of [-1, -0.4, -59.6, -3600, NaN, Infinity, -Infinity, null, undefined]) {
    assert.equal(duration(s), DASH, String(s));
  }
  assert.equal(duration(0), '0 s');
  assert.equal(duration(-0), '0 s');
});

test('duration: the seconds/minutes boundary never prints "60 s"', () => {
  assert.equal(duration(59.4), '59 s');
  assert.equal(duration(59.49), '59 s');
  assert.equal(duration(59.5), '1 min');
  assert.equal(duration(59.99), '1 min');
  assert.equal(duration(60), '1 min');
  for (let s = 0; s < 60; s += 0.01) assert.notEqual(duration(s), '60 s', String(s));
});

test('duration: golden table unchanged', () => {
  const golden = {0.4: '0 s', 45: '45 s', 59: '59 s', 119: '1 min', 720: '12 min', 3599: '59 min', 3600: '1 h',
    11100: '3 h 5 min', 172799: '47 h 59 min', 172800: '2 d', 187200: '2 d 4 h'};
  for (const [s, want] of Object.entries(golden)) assert.equal(duration(Number(s)), want, s);
});

test('duration: every finite s >= 0 outside 59.5-60 prints what it printed before', () => {
  const before = s => {   // the pre-RF1050-1 body for finite s
    if (s < 60) return `${Math.round(s)} s`;
    const m = Math.floor(s / 60), h = Math.floor(m / 60);
    if (m < 60) return `${m} min`;
    if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
    return h % 24 ? `${Math.floor(h / 24)} d ${h % 24} h` : `${Math.floor(h / 24)} d`;
  };
  let diffs = 0;
  for (let s = 0; s < 400000; s += s < 200 ? 0.25 : 59.75) if (!(s >= 59.5 && s < 60) && duration(s) !== before(s)) diffs++;
  assert.equal(diffs, 0);
});

test('percent: NaN and ±Infinity are a dash; finite shares unchanged', () => {
  for (const p of [NaN, Infinity, -Infinity, null, undefined]) assert.equal(percent(p), DASH, String(p));
  assert.equal(percent(0), '0%');
  assert.equal(percent(12.5), '12.5%');
  assert.equal(percent(100), '100%');
  assert.equal(percent(-3), '-3%', 'negative finite percents are out of scope and unchanged');
});

test('copy helpers built on percent never print NaN% or Infinity%', () => {
  assert.equal(FLEET_COVERAGE_COPY.countOf(3, NaN), `3 (${DASH})`);
  assert.equal(FLEET_COVERAGE_COPY.countOf(3, Infinity), `3 (${DASH})`);
  assert.equal(FLEET_COVERAGE_COPY.countOf(3, 50), '3 (50%)');
  assert.equal(FLEET_COVERAGE_COPY.uptimeLine(NaN, 0, 0), `${DASH} (0 of 0 h)`);
});
