// RF1410-2: the mark card's WCOFS current rejects impossible samples (negative speed, a bearing outside
// 0-360, a cell off the globe) before nearest-cell selection and the regional fallback. Synthetic feeds
// through the real parser and helper; no network, no live NOAA data.
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.fetch = () => { throw new Error('unexpected fetch'); };
const {parseConditionsForecast} = await import('../web/conditions.ts');
const {distanceKm, markForecast} = await import('../web/brief/mark-forecast.ts');

const HOUR = 3_600_000, TZ = 'America/Los_Angeles';
const NOW = Date.parse('2026-10-20T17:20:00Z'), AT = Date.parse('2026-10-20T17:00:00Z');
const POINTS = [['north', 35.5, -121], ['central', 35.34, -120.965], ['south', 35.2, -120.9]];
const MARK = {lat: 35.35, lon: -120.96}, FAR = {lat: 34.3, lon: -122.6};
const NEAR = [AT / 1000, 35.35, -120.96, 0.4, 100, 0.5];   // a valid cell 0 km from MARK
const T = ms => ms / 1000;

const freeze = o => { if (o && typeof o === 'object') { Object.values(o).forEach(freeze); Object.freeze(o); } return o; };
/** A feed whose WCOFS samples are `byPoint` = {pointId: [tuples]}. */
function feed(byPoint) {
  return freeze({region_id: 'morro-bay', retrieved: NOW - 0.3 * HOUR, requested_points: POINTS, models: {},
    currents: {source: 'wcofs', status: 'ok', issued_at: new Date(NOW - 14 * HOUR).toISOString(), resolution_km: 4,
      points: Object.entries(byPoint).map(([point_id, samples]) => ({point_id, samples}))}});
}
const current = (byPoint, mark = MARK, at = AT) => {
  const f = feed(byPoint), c = parseConditionsForecast(f, 'morro-bay', [35.34, -120.965]);
  return markForecast(c, 'morro-bay', mark, at, NOW, TZ).current;
};
const FAR_VALID = [AT / 1000, 36.5, -121, 0.9, 45, 1];     // a valid sample of north, far from MARK and from the regional point
const GAP = 'no NOAA WCOFS cell sampled for Tue 10 am lies within 6 km (1.5 grid lengths) of this mark, and forecast point central has no sample then';

const BAD = {
  'negative speed': [AT / 1000, 35.35, -120.96, -2, 100, 0.5],
  'tiny negative speed': [AT / 1000, 35.35, -120.96, -0.01, 100, 0.5],
  'negative speed and bearing 999': [AT / 1000, 35.35, -120.96, -2, 999, 0.5],
  'bearing -1': [AT / 1000, 35.35, -120.96, 0.4, -1, 0.5],
  'bearing 361': [AT / 1000, 35.35, -120.96, 0.4, 361, 0.5],
  'latitude 91': [AT / 1000, 91, -120.96, 0.4, 100, 0.5],
  'latitude -91': [AT / 1000, -91, -120.96, 0.4, 100, 0.5],
  'longitude 181': [AT / 1000, 35.35, 181, 0.4, 100, 0.5],
  'longitude -181': [AT / 1000, 35.35, -181, 0.4, 100, 0.5],
  'null speed': [AT / 1000, 35.35, -120.96, null, 100, 0.5],
  'string bearing': [AT / 1000, 35.35, -120.96, 0.4, '100', 0.5],
  'NaN speed': [AT / 1000, 35.35, -120.96, NaN, 100, 0.5],
  'Infinity speed': [AT / 1000, 35.35, -120.96, Infinity, 100, 0.5],
  'too short': [AT / 1000, 35.35, -120.96, 0.4],
  'not an array': {time: AT / 1000},
  'null': null,
};

test('an impossible tuple is never shown: not as the nearest cell, not as the regional fallback', () => {
  for (const [name, bad] of Object.entries(BAD)) {
    // The bad tuple is both the regional point's only sample and the cell at the mark; a far valid sample keeps its time listed.
    const r = current({central: [bad], north: [FAR_VALID]});
    assert.equal(r.value, null, name);
    assert.equal(r.cell, null, name);
    assert.equal(r.gap, GAP, name);
    // A mark far from every cell would take the regional fallback, which must not revive the bad tuple either.
    const far = current({central: [bad], north: [FAR_VALID]}, FAR);
    assert.equal(far.value, null, `${name} (regional fallback)`);
    assert.equal(far.gap, GAP, name);
  }
});

test('a poisoned nearest cell loses to a farther valid cell at the same frame, unchanged', () => {
  const south = [AT / 1000, 35.377, -120.96, 0.7, 250, 2.9];  // about 3 km from MARK
  for (const bad of [BAD['negative speed'], BAD['bearing 361'], BAD['latitude 91']]) {
    const r = current({central: [bad], south: [south]});
    assert.equal(r.value, '0.70 kt toward 250° true');
    assert.equal(r.point, 'south');
    assert.ok(Math.abs(r.cell.km - distanceKm(MARK, {lat: 35.377, lon: -120.96})) < 1e-9);
  }
});

test('with no cell near the mark, a valid regional sample is still the fallback and a poisoned one is not', () => {
  const valid = [AT / 1000, 35.34, -120.965, 0.2, 101, 1];
  const ok = current({central: [valid], north: [FAR_VALID]}, FAR);
  assert.deepEqual([ok.point, ok.cell, ok.value], ['central', null, '0.20 kt toward 101° true']);
  const bad = current({central: [[AT / 1000, 35.34, -120.965, -0.2, 101, 1]], north: [FAR_VALID]}, FAR);
  assert.equal(bad.value, null);
});

test('bad frames are rejected before time selection; a valid frame inside 90 minutes wins, nothing is interpolated', () => {
  const good = [T(AT + HOUR), 35.35, -120.96, 0.3, 120, 0.5], bad = [T(AT), 35.35, -120.96, -0.3, 120, 0.5];
  const before = [T(AT - 2 * HOUR), 35.35, -120.96, 0.1, 80, 0.5];   // spans the selected hour but is too far to be read
  const r = current({central: [bad, before, good]});
  assert.equal(r.value, '0.30 kt toward 120° true');
  assert.equal(r.validAt, AT + HOUR);
  // The only valid frames are beyond 90 minutes of the selected hour: a gap, not the bad frame and not a far one.
  const late = current({central: [bad, before, [T(AT + 2 * HOUR), 35.35, -120.96, 0.3, 120, 0.5]]});
  assert.equal(late.value, null);
  assert.match(late.gap, /lists no hour within 90 minutes of the selected hour$/);
  // All-invalid input is a gap with a null value, never a calm current.
  const none = current({central: [BAD['negative speed'], BAD['bearing 361']], south: [BAD['latitude 91']]});
  assert.equal(none.value, null);
  assert.ok(none.gap.length > 0);
});

test('boundary values are accepted: speed 0, lat +-90, lon +-180, bearing 0 and 360; trailing fields keep their behaviour', () => {
  const cases = [
    [[AT / 1000, 35.34, -120.965, 0, 90, 1], '0.00 kt toward 90° true'],
    [[AT / 1000, 90, -120.965, 0.2, 0, 1], '0.20 kt toward 0° true'],
    [[AT / 1000, -90, -120.965, 0.2, 360, 1], '0.20 kt toward 360° true'],
    [[AT / 1000, 35.34, 180, 0.2, 10, 1], '0.20 kt toward 10° true'],
    [[AT / 1000, 35.34, -180, 0.2, 10, 1], '0.20 kt toward 10° true'],
    [[AT / 1000, 35.34, -120.965, 0.2, 10], '0.20 kt toward 10° true'],
    [[AT / 1000, 35.34, -120.965, 0.2, 10, null], '0.20 kt toward 10° true'],
  ];
  for (const [tuple, value] of cases) {
    // A far mark reads the regional point's own sample, whatever the cell's position.
    const r = current({central: [tuple]}, FAR);
    assert.deepEqual([r.value, r.point, r.cell], [value, 'central', null], JSON.stringify(tuple));
  }
});

test('a normal valid feed reads exactly as before', () => {
  const r = current({central: [NEAR], north: [FAR_VALID]});
  assert.deepEqual(r, {label: 'Current', model: 'NOAA WCOFS', grid: 'about 4 km', value: '0.40 kt toward 100° true', gap: '', point: 'central',
    cell: {lat: 35.35, lon: -120.96, km: 0}, validAt: AT, issuedAt: NOW - 14 * HOUR});
});
