// F13-08 / SCA-435: offline controls for the WCOFS current read on two surfaces. Synthetic feed, no network, no live data.
//   node --test tests/test_f13_08_audit.mjs
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.fetch = () => { throw new Error('unexpected fetch'); };
const {parseConditionsForecast} = await import('../web/conditions.ts');
const {markForecast} = await import('../web/brief/mark-forecast.ts');
const {offshoreRead} = await import('../web/brief/entrance-current.ts');

const HOUR = 3_600_000, TZ = 'UTC', REGION = 'synthetic', REGIONAL = [20, -140];
const NOW = Date.parse('2026-10-20T17:20:00Z'), AT = Date.parse('2026-10-20T17:00:00Z');
const POINTS = [['north', 21, -140], ['central', ...REGIONAL], ['south', 19, -140]];
const MARK = {lat: REGIONAL[0], lon: REGIONAL[1]};
const sample = (lat = MARK.lat, lon = MARK.lon, speed = 0.4, toward = 100) => [AT / 1000, lat, lon, speed, toward, 0.5];

const feed = (sample_, {source = 'wcofs', pointId = 'central'} = {}) => ({
  region_id: REGION, retrieved: NOW - 0.3 * HOUR, requested_points: POINTS, models: {},
  currents: {source, status: 'ok', issued_at: new Date(NOW - 14 * HOUR).toISOString(), resolution_km: 4,
    points: [{point_id: pointId, samples: [sample_]}]},
});
/** What each surface shows for one feed: true when it displays a current, false when it reports a gap. */
function surfaces(f) {
  const c = parseConditionsForecast(f, REGION, REGIONAL);
  const mark = markForecast(c, REGION, MARK, AT, NOW, TZ).current;
  const entrance = offshoreRead(c, REGION, AT, NOW);
  return {mark: mark.value !== null, entrance: entrance.sample !== null};
}

test('valid WCOFS control: visible on both surfaces', () => {
  assert.deepEqual(surfaces(feed(sample())), {mark: true, entrance: true});
});

const missingSource = feed(sample());
delete missingSource.currents.source;
const NEGATIVES = {
  'wrong source (hycom)': feed(sample(), {source: 'hycom'}),
  'wrong source (empty)': feed(sample(), {source: ''}),
  'missing source': missingSource,
  'unlisted point ID': feed(sample(), {pointId: 'unlisted'}),
  'latitude 91': feed(sample(91)),
  'longitude 181': feed(sample(undefined, 181)),
  'latitude -91': feed(sample(-91)),
  'longitude -181': feed(sample(undefined, -181)),
  'non-numeric latitude': feed(sample('20')),
  'negative speed': feed(sample(undefined, undefined, -2)),
  'bearing above 360': feed(sample(undefined, undefined, undefined, 361)),
  'negative bearing': feed(sample(undefined, undefined, undefined, -1)),
};

for (const [name, f] of Object.entries(NEGATIVES)) {
  test(`${name}: a gap on both surfaces`, () => {
    assert.deepEqual(surfaces(f), {mark: false, entrance: false});
  });
}
