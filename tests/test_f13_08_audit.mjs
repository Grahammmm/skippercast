// F13-08 / SCA-582: offline controls for the WCOFS current read on two surfaces. Synthetic feed, no network, no live data.
//   node --test tests/test_f13_08_audit.mjs
// The mark reader (web/brief/mark-forecast.ts currentRow) bounds-checks the cell but never reads `source`; the entrance reader
// (web/brief/entrance-current.ts offshoreRead) checks `source === 'wcofs'` but not the cell's lat/lon. Contract: a wrong source or
// an impossible cell is a gap on BOTH surfaces; a valid WCOFS control stays visible on both.
//   - The valid control is asserted (must pass).
//   - Each negative control records what each surface does. The agreement check is a `todo` while the surfaces disagree
//     (reported, never failing the run, and not an assertion that the divergence is wanted); it becomes a plain test once both gap.
//   - A detector self-check proves the harness tells "visible" from "gap".
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.fetch = () => { throw new Error('unexpected fetch'); };
const {parseConditionsForecast} = await import('../web/conditions.ts');
const {markForecast} = await import('../web/brief/mark-forecast.ts');
const {offshoreRead} = await import('../web/brief/entrance-current.ts');

const HOUR = 3_600_000, TZ = 'America/Los_Angeles', REGION = 'morro-bay', REGIONAL = [35.34, -120.965];
const NOW = Date.parse('2026-10-20T17:20:00Z'), AT = Date.parse('2026-10-20T17:00:00Z');
const POINTS = [['north', 35.5, -121], ['central', 35.34, -120.965], ['south', 35.2, -120.9]];
const MARK = {lat: 35.35, lon: -120.96};
const sample = (lat = 35.35, lon = -120.96, speed = 0.4, toward = 100) => [AT / 1000, lat, lon, speed, toward, 0.5];

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

test('detector: a feed with no usable sample is a gap on both surfaces', () => {
  assert.deepEqual(surfaces(feed(sample(), {pointId: 'unlisted'})), {mark: false, entrance: false});
  assert.deepEqual(surfaces(feed(sample(35.35, -120.96, -2))), {mark: false, entrance: false});
});

const NEGATIVES = {
  'wrong source (hycom)': feed(sample(), {source: 'hycom'}),
  'wrong source (empty)': feed(sample(), {source: ''}),
  'latitude 91': feed(sample(91, -120.96)),
  'longitude 181': feed(sample(35.35, 181)),
  'latitude -91': feed(sample(-91, -120.96)),
};

for (const [name, f] of Object.entries(NEGATIVES)) {
  const seen = surfaces(f);
  console.log(`F13-08 baseline ${name}: mark ${seen.mark ? 'SHOWS' : 'gap'}, entrance ${seen.entrance ? 'SHOWS' : 'gap'}`);
  // Passes only when both surfaces report the gap; reported as todo (non-failing) while they diverge.
  test(`${name}: a gap on both surfaces`, {todo: seen.mark || seen.entrance ? 'F13-08: surfaces disagree, see baseline' : false}, () => {
    assert.deepEqual(surfaces(f), {mark: false, entrance: false});
  });
}
