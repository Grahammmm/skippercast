// FE-31: the daily brief adapter over packages/coast buildDaily (design § 10).
import test from 'node:test';
import assert from 'node:assert/strict';
import report from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {PROFILE_TABLE, PROFILES} = await import('../web/profile.ts');
const {buildBrief, buildCoastBrief, buildRegionalBrief, fleetLine, regionalReport, TILE_LIMIT_MS, LOCAL_REPORT_LINE} = await import('../web/brief/model.ts');

// Same clock as tests/test_coast_data.mjs: the fixture report is fresh ten minutes after it was assembled.
const now = new Date(Date.parse(report.generatedAt) + 10 * 60_000);
const date = '2026-10-08';
const morroContext = {regionId: 'morro-bay', point: {latitude: 35.36, longitude: -120.94}, localAreas: [{id: 'estero-bay', bounds: [-121.05, 35.32, -120.78, 35.47]}], profile: 'boat', target: 'lingcod', at: now};
const montereyPlace = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
const montereyContext = {regionId: 'monterey-point-sur', point: {latitude: 36.62, longitude: -121.9}, localAreas: [], profile: 'boat', target: 'lingcod', at: now};
const regional = {daily: montereyDaily, forecast: montereyForecast, place: montereyPlace};
const tile = (brief, id) => brief.tiles.find(t => t.id === id);

test('acceptance 1: the Morro Bay brief carries buildDaily output unchanged for the same inputs', () => {
  for (const profile of PROFILES) {
    const area = slo.areas.find(a => a.id === 'central');
    const daily = buildDaily(report, slo, area, profile, date, now);
    for (const brief of [buildCoastBrief({report, county: slo, areaId: 'central', profile, date, now}),
      buildBrief({context: {...morroContext, profile}, coast: {report, county: slo}, regional, profile, date, now})]) {
      assert.equal(brief.basis, 'coast-report');
      assert.equal(brief.headline, daily.headline);
      assert.equal(brief.deck, daily.summary);
      assert.equal(brief.status, daily.status);
      assert.equal(brief.confidence, daily.confidence);
      assert.equal(brief.label, daily.label);
      assert.deepEqual(brief.windows, daily.windows);
      assert.deepEqual(brief.alerts, daily.alerts);
      assert.deepEqual(brief.missing, daily.missing);
      assert.deepEqual([brief.tides, brief.tideEvents, brief.sunrise, brief.sunset], [daily.tides, daily.tideEvents, daily.sunrise, daily.sunset]);
      assert.deepEqual(brief.localReport, {available: true, text: LOCAL_REPORT_LINE.available});
    }
  }
});

test('Morro Bay tiles read the report: forecast wind, buoy water, MLLW tide, all fresh', () => {
  const brief = buildCoastBrief({report, county: slo, areaId: 'central', profile: 'boat', date, now});
  assert.deepEqual(brief.tiles.map(t => t.id), ['wind', 'swell', 'water', 'tide']);
  const area = slo.areas.find(a => a.id === 'central');
  const first = buildDaily(report, slo, area, 'boat', date, now).hours[0];
  assert.equal(tile(brief, 'wind').value, Number(first.windKnots.toFixed(1)));
  assert.equal(tile(brief, 'swell').value, Number(first.waveFt.toFixed(1)));
  assert.match(tile(brief, 'swell').detail, /offshore forecast/);
  assert.equal(tile(brief, 'water').value, 57.6);
  assert.match(tile(brief, 'tide').detail, /MLLW/);
  for (const t of brief.tiles) assert.equal(t.state, 'fresh', t.id);
});

test('acceptance 2: a Monterey place yields the regional brief and the unavailable local-report line', () => {
  const brief = buildBrief({context: montereyContext, coast: {report, county: slo}, regional, profile: 'boat', date, now});
  assert.equal(brief.basis, 'regional');
  assert.deepEqual(brief.localReport, {available: false, text: LOCAL_REPORT_LINE.unavailable});
  // The regional brief is buildDaily over the converted feeds, not a second model.
  const {report: converted, county, area} = regionalReport(montereyDaily, montereyForecast, montereyPlace);
  const daily = buildDaily(converted, county, area, 'boat', date, now);
  assert.equal(brief.headline, daily.headline);
  assert.equal(brief.deck, daily.summary);
  assert.deepEqual(brief.missing, daily.missing);
  assert.match(brief.headline, /kt winds/);
  // The daily feed's advisory check is hours old, so buildDaily withholds windows.
  assert.ok(brief.missing.includes('Current marine alert check unavailable'));
  assert.deepEqual(brief.windows, []);
  assert.equal(tile(brief, 'wind').state, 'fresh');
  assert.equal(tile(brief, 'water').value, Number((14.5 * 9 / 5 + 32).toFixed(1)));
  assert.equal(tile(brief, 'water').state, 'fresh');
  assert.match(tile(brief, 'tide').detail, /^next (high|low) · NOAA Monterey reference tide predictions · MLLW$/);
  assert.deepEqual(brief.fleet, {count: 2, port: 'Monterey', text: '2 boats reported from Monterey in the last 7 days', href: '/report'});
});

test('no coast report loaded at a bound place falls back to the regional brief', () => {
  const brief = buildBrief({context: morroContext, coast: null, regional, profile: 'boat', date, now});
  assert.equal(brief.basis, 'regional');
  assert.equal(brief.localReport.available, false);
});

test('acceptance 3: a tile past its limit is stale and keeps its age', () => {
  const later = new Date(now.getTime() + TILE_LIMIT_MS.water + 60 * 60_000);
  const brief = buildRegionalBrief({...regional, profile: 'boat', date, now: later});
  const water = tile(brief, 'water');
  assert.equal(water.state, 'stale');
  assert.ok(water.ageMs > water.limitMs);
  assert.equal(water.value, Number((14.5 * 9 / 5 + 32).toFixed(1)));

  const oldForecast = {...montereyForecast, issuedAt: new Date(now.getTime() - TILE_LIMIT_MS.wind - 60_000).toISOString()};
  const stale = buildRegionalBrief({...regional, forecast: oldForecast, profile: 'boat', date, now});
  assert.equal(tile(stale, 'wind').state, 'stale');
  assert.notEqual(tile(stale, 'wind').value, null);
  assert.ok(stale.missing.includes('Fresh local forecast unavailable'));

  const empty = buildRegionalBrief({...regional, forecast: null, profile: 'boat', date, now});
  assert.equal(tile(empty, 'wind').state, 'unavailable');
});

test('acceptance 4: each profile yields its § 8 caveat; shore and spear read the nearshore swell', () => {
  for (const profile of PROFILES) {
    for (const brief of [buildCoastBrief({report, county: slo, areaId: 'central', profile, date, now}), buildRegionalBrief({...regional, profile, date, now})]) {
      assert.equal(brief.caveat, PROFILE_TABLE[profile].caveat, profile);
      assert.equal(brief.profile, profile);
    }
  }
  assert.equal(tile(buildRegionalBrief({...regional, profile: 'shore', date, now}), 'swell').detail, 'No nearshore model site');
  assert.equal(tile(buildRegionalBrief({...regional, profile: 'spear', date, now}), 'swell').state, 'unavailable');
});

test('fleet line: absent with no report in seven days or no port', () => {
  assert.equal(fleetLine([{date: '2026-09-20', boat: 'A', port: 'Monterey'}], 'Monterey', 'America/Los_Angeles', now), null);
  assert.equal(fleetLine(montereyDaily.reports, '', 'America/Los_Angeles', now), null);
  assert.equal(fleetLine([{date: '2026-10-08', boat: 'A', port: 'Monterey'}], 'Monterey', 'America/Los_Angeles', now).text, '1 boat reported from Monterey in the last 7 days');
});
