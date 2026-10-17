// FE-31: the daily brief adapter over packages/coast buildDaily (design § 10).
import test from 'node:test';
import assert from 'node:assert/strict';
import report from './fixtures/coast/skippercast-report.json' with {type: 'json'};
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {buildDaily} = await import('../packages/coast/src/daily.ts');
const {slo} = await import('../packages/coast/src/counties.ts');
const {PROFILE_TABLE, PROFILES} = await import('../web/profile.ts');
const {briefFromDaily, buildBrief, buildCoastBrief, buildRegionalBrief, fleetLine, regionalReport, sourceGaps, TILE_LIMIT_MS, LOCAL_REPORT_LINE} = await import('../web/brief/model.ts');

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
      assert.equal(brief.provisional, daily.provisional);
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

test('a retained source reads as degraded: its tile is last good data, stale, with the age of that data', () => {
  const lastGood = new Date(now.getTime() - 5 * 3_600_000).toISOString();
  const retain = source => ({...source, status: 'retained', checked_at: now.toISOString(), data_retrieved_at: lastGood, last_success_at: lastGood});
  const s = montereyDaily.sources;
  const daily = {...montereyDaily, sources: {...s, tides: retain(s.tides), 'buoy-46042': retain(s['buoy-46042']), 'alerts-PZZ535': retain(s['alerts-PZZ535'])}};
  const {report: converted} = regionalReport(daily, montereyForecast, montereyPlace);
  for (const id of ['tides', 'buoy-46042', 'nws-alerts']) assert.equal(converted.sources.find(item => item.id === id).outcome, 'error', id);
  assert.equal(converted.sources.find(item => item.id === 'tides').fetchedAt, lastGood);
  const brief = buildRegionalBrief({daily, forecast: montereyForecast, place: montereyPlace, profile: 'boat', date, now});
  const tide = tile(brief, 'tide');
  assert.equal(tide.state, 'stale');
  assert.equal(tide.lastGood, true);
  assert.equal(tide.ageMs, 5 * 3_600_000);
  assert.notEqual(tide.value, null);
  assert.equal(tile(brief, 'water').lastGood, true);
  assert.equal(tile(brief, 'water').state, 'stale');
  assert.ok(brief.missing.includes('Current marine alert check unavailable'));
  // An ok source is not marked.
  assert.equal(tile(buildRegionalBrief({...regional, profile: 'boat', date, now}), 'tide').lastGood, undefined);
});

test('acceptance 4: each profile yields its § 8 caveat; shore and spear read the nearshore swell', () => {
  for (const profile of PROFILES) {
    for (const brief of [buildCoastBrief({report, county: slo, areaId: 'central', profile, date, now}), buildRegionalBrief({...regional, profile, date, now})]) {
      assert.equal(brief.caveat, PROFILE_TABLE[profile].caveat, profile);
      assert.equal(brief.profile, profile);
    }
  }
  assert.equal(tile(buildRegionalBrief({...regional, profile: 'shore', date, now}), 'swell').detail, 'No nearshore model site · moderate surf (offshore estimate)');
  assert.equal(tile(buildRegionalBrief({...regional, profile: 'spear', date, now}), 'swell').state, 'unavailable');
});

test('fleet line: absent with no report in seven days or no port', () => {
  assert.equal(fleetLine([{date: '2026-09-20', boat: 'A', port: 'Monterey'}], 'Monterey', 'America/Los_Angeles', now), null);
  assert.equal(fleetLine(montereyDaily.reports, '', 'America/Los_Angeles', now), null);
  assert.equal(fleetLine([{date: '2026-10-08', boat: 'A', port: 'Monterey'}], 'Monterey', 'America/Los_Angeles', now).text, '1 boat reported from Monterey in the last 7 days');
});

// FE-60 live check (#473): the county feed writes an advisory line for open beaches too.
const beach = (status, advisory, fetchedAt = new Date(now.getTime() - 30 * 60_000).toISOString(), outcome = 'ok') => ({...report,
  waterQuality: [{id: 'morro-rock', name: 'Morro Rock Beach', lat: 35.37, lon: -120.87, status, advisory, url: 'https://example.test/beach', areaId: 'central', fetchedAt, sampledAt: null}],
  sources: [...report.sources, {id: 'slo-beach-water-quality', label: 'SLO County beach water quality', url: 'https://example.test/beach', kind: 'observation', outcome, fetchedAt}]});

test('beach notice: an open beach with its "no advisory notes" line is no notice; an advisory, closure or warning is', () => {
  const brief = r => buildCoastBrief({report: r, county: slo, areaId: 'central', profile: 'boat', date, now});
  assert.equal(brief(beach('Beach Open', 'Beach Open · There are no advisory notes at this time.')).notice, null);
  for (const status of ['Advisory', 'Beach Closed', 'Warning']) {
    assert.deepEqual(brief(beach(status, `${status} · bacteria above state standards`)).notice,
      {name: 'Morro Rock Beach', advisory: `${status} · bacteria above state standards`, url: 'https://example.test/beach'}, status);
  }
  // As v1: only while the county source fetched cleanly within 3 h.
  assert.equal(brief(beach('Advisory', 'Advisory', new Date(now.getTime() - 4 * 3_600_000).toISOString())).notice, null);
  assert.equal(brief(beach('Advisory', 'Advisory', undefined, 'error')).notice, null);
});

test('fleet line: the daily feed\'s landing names pick the region\'s own trips, short names matching the publisher\'s ports', () => {
  const reports = [{date: '2026-10-07', boat: 'Avenger', port: 'Morro Bay'}, {date: '2026-10-06', boat: 'Flying Fish', port: 'Avila Beach'},
    {date: '2026-10-07', boat: 'Elsewhere', port: 'Santa Cruz'}, {date: '2026-10-07', boat: 'Not Avila', port: 'Avilaville'}];
  assert.deepEqual(fleetLine(reports, ['Morro Bay', 'Avila'], 'America/Los_Angeles', now),
    {count: 2, port: 'Morro Bay & Avila Beach', text: '2 boats reported from Morro Bay & Avila Beach in the last 7 days', href: '/report'});
  assert.equal(fleetLine(reports, ['Monterey', 'Carmel'], 'America/Los_Angeles', now), null, 'another region\'s landings take none of these trips');
  const daily = {...montereyDaily, landing_names: ['Morro Bay', 'Avila'], reports};
  const morro = {...montereyPlace, name: 'Morro Bay & Avila', port: undefined};
  assert.equal(buildRegionalBrief({daily, forecast: montereyForecast, place: morro, profile: 'boat', date, now}).fleet?.count, 2);
  assert.equal(buildBrief({context: morroContext, coast: {report, county: slo}, regional: {daily, forecast: montereyForecast, place: morro}, profile: 'boat', date, now}).fleet?.count, 2);
});

test('P5 gaps: each brief source that is not ok is named with its own status and the data\'s own clock, never merged or filled', () => {
  const s = montereyDaily.sources;
  const hoursAgo = h => new Date(now.getTime() - h * 3_600_000).toISOString();
  const daily = {...montereyDaily, sources: {...s,
    'buoy-46042': {...s['buoy-46042'], status: 'stale', data_retrieved_at: hoursAgo(0.1), data: {...s['buoy-46042'].data, observations: [{time: hoursAgo(4), WTMP: 14}]}},
    tides: {...s.tides, status: 'retained', data_retrieved_at: hoursAgo(30)},
    'alerts-PZZ535': {...s['alerts-PZZ535'], status: 'failed', data: null},
    // Map grids and other places' buoys report their own gaps; the brief does not list them.
    sst: {id: 'sst', name: 'SST grid', kind: 'grid', url: '', checked_at: now.toISOString(), status: 'failed'},
    'buoy-46011': {id: 'buoy-46011', name: 'NOAA NDBC 46011 observations', kind: 'observation', url: 'https://www.ndbc.noaa.gov/data/realtime2/46011.txt', checked_at: now.toISOString(), status: 'failed'},
  }};
  const gaps = sourceGaps(daily, now);
  assert.deepEqual(gaps.map(g => [g.id, g.status]), [['buoy-46042', 'stale'], ['tides', 'retained'], ['alerts-PZZ535', 'failed']]);
  assert.equal(gaps[0].text, 'NOAA NDBC 46042 observations: stale, newest reading 4 h old.', 'the observation\'s age, not the retrieval\'s');
  assert.equal(gaps[1].text, 'NOAA Monterey reference tide predictions: latest check failed; showing the last good data, retrieved 30 h ago.');
  assert.equal(gaps[2].text, 'NWS PZZ535 advisories: latest check failed; nothing earlier on hand.');
  const brief = buildRegionalBrief({daily, forecast: montereyForecast, place: montereyPlace, profile: 'boat', date, now});
  assert.deepEqual(brief.gaps, gaps);
  assert.ok(brief.missing.includes('Current marine alert check unavailable'), 'the model\'s own list still says what it could not check');
  assert.deepEqual(buildRegionalBrief({...regional, profile: 'boat', date, now}).gaps, [], 'all ok: no gaps');
});

test('P5 gaps: a stale prediction and a stale alert check read their own clocks, never the fetch that just happened', () => {
  const s = montereyDaily.sources;
  const at = h => new Date(now.getTime() + h * 3_600_000).toISOString();
  const daily = {...montereyDaily, sources: {...s,
    tides: {...s.tides, status: 'stale', data_retrieved_at: at(-0.1), data: {...s.tides.data, coverage_end: at(-3)}},
    'alerts-PZZ535': {...s['alerts-PZZ535'], status: 'stale', data_retrieved_at: at(-0.1), data: {...s['alerts-PZZ535'].data, issued_at: at(-7)}},
  }};
  assert.deepEqual(sourceGaps(daily, now).map(g => g.text), [
    'NOAA Monterey reference tide predictions: stale, coverage ended 3 h ago.',
    'NWS PZZ535 advisories: stale, issued 7 h ago.',
  ]);
});

test('P5 gaps: one line per station across aliases, spectra and the daily copy; any ok copy clears it', () => {
  const s = montereyDaily.sources, buoy = s['buoy-46042'];
  const stale = {...buoy, status: 'stale'};
  const aliases = {diablo: {...stale, id: 'diablo', name: 'Monterey Bay'}, 'diablo-spectrum': {...stale, id: 'diablo-spectrum', url: buoy.url.replace('.txt', '.spec'), data: {station: '46042'}}};
  const merged = {...montereyDaily, sources: {...aliases, ...s, 'buoy-46042': stale}};
  const gaps = sourceGaps(merged, now);
  assert.equal(gaps.length, 1);
  assert.match(gaps[0].text, /^Monterey Bay: stale/, 'the first copy, the live feed\'s, speaks for the station');
  assert.deepEqual(sourceGaps({...merged, sources: {...merged.sources, diablo: {...buoy, id: 'diablo', status: 'ok'}}}, now), [], 'the live copy behind the tile is ok');
});

test('P5 gaps: a backup is named by its own station; a backup serving ok is no gap', () => {
  const s = montereyDaily.sources;
  const backup = {...s['buoy-46042'], station: '46011', fallback_for: '46042', data: {...s['buoy-46042'].data, station: '46011'}};
  assert.deepEqual(sourceGaps({...montereyDaily, sources: {...s, 'buoy-46042': backup}}, now), []);
  const [gap] = sourceGaps({...montereyDaily, sources: {...s, 'buoy-46042': {...backup, status: 'stale'}}}, now);
  assert.match(gap.text, /^NDBC 46011 \(backup for 46042\): stale,/);
});

test('P5 gaps: the coast brief lists only the failed checks behind this area\'s tiles, not other areas\' or the regional feed\'s', () => {
  const fail = ids => ({...report, sources: report.sources.map(item => ids.includes(item.id) ? {...item, outcome: 'error'} : item)});
  const coast = r => buildCoastBrief({report: r, county: slo, areaId: 'central', profile: 'boat', date, now, daily: {...montereyDaily, sources: {...montereyDaily.sources, tides: {...montereyDaily.sources.tides, status: 'failed'}}}});
  assert.deepEqual(coast(fail(['nws-north', 'nws-south', 'ndbc-46028', 'noaa-blended-sst', 'cdfw-protected-areas', 'landing-reports'])).gaps, [], 'other areas and other layers are not this brief\'s gaps');
  assert.deepEqual(coast(fail(['coops-tide-events'])).gaps, [], 'the tide curve still answers');
  const brief = coast(fail(['nws-central', 'ndbc-46215', 'coops-tides', 'coops-tide-events', 'nws-alerts']));
  assert.deepEqual(brief.gaps.map(g => g.id), ['nws-central', 'ndbc-46215', 'nws-alerts', 'coops-tides']);
  assert.match(brief.gaps[0].text, /^NWS · Morro Bay & Point Estero: latest check failed; last fetched \d+ (min|h|d) ago\.$/);
});


test('provisional uses the local calendar across UTC midnight and the local day boundary', () => {
  const area = slo.areas.find(a => a.id === 'central');
  for (const [clock, dates] of [
    ['2026-10-09T00:30:00Z', ['2026-10-08', '2026-10-09', '2026-10-10']],
    ['2026-10-09T06:59:59Z', ['2026-10-08', '2026-10-09', '2026-10-10']],
    ['2026-10-09T07:00:00Z', ['2026-10-09', '2026-10-10', '2026-10-11']],
  ]) {
    for (const [index, day] of dates.entries()) {
      const daily = buildDaily(report, slo, area, 'boat', day, new Date(clock));
      assert.equal(daily.provisional, index === 2, `${clock}: ${day}`);
      assert.equal(daily.label, index === 0 ? 'Today' : index === 1 ? 'Tomorrow' : daily.label);
    }
  }
});

test('briefFromDaily follows the explicit provisional flag despite contradictory confidence copy', () => {
  const area = slo.areas.find(a => a.id === 'central');
  for (const [day, expected, confidence] of [
    ['2026-10-08', false, 'Low · provisional'],
    ['2026-10-10', true, 'Low · local checks required'],
  ]) {
    const daily = buildDaily(report, slo, area, 'boat', day, new Date('2026-10-08T19:00:00Z'));
    assert.equal(daily.provisional, expected);
    const brief = briefFromDaily({...daily, confidence}, 'coast-report', {report, county: slo, area, profile: 'boat', now});
    assert.equal(brief.provisional, expected);
    assert.equal(brief.confidence, confidence);
  }
});

test('coast and regional adapters preserve provisional and model parity for every profile and outlook day', () => {
  const clock = new Date('2026-10-08T19:00:00Z');
  const coastArea = slo.areas.find(a => a.id === 'central');
  const converted = regionalReport(montereyDaily, montereyForecast, montereyPlace);
  for (const profile of PROFILES) {
    for (const [day, expected] of [['2026-10-08', false], ['2026-10-09', false], ['2026-10-10', true]]) {
      for (const [daily, briefs] of [
        [buildDaily(report, slo, coastArea, profile, day, clock), [
          buildCoastBrief({report, county: slo, areaId: 'central', profile, date: day, now: clock}),
          buildBrief({context: {...morroContext, profile}, coast: {report, county: slo}, regional, profile, date: day, now: clock}),
        ]],
        [buildDaily(converted.report, converted.county, converted.area, profile, day, clock), [
          buildRegionalBrief({...regional, profile, date: day, now: clock}),
          buildBrief({context: {...montereyContext, profile}, coast: {report, county: slo}, regional, profile, date: day, now: clock}),
        ]],
      ]) {
        assert.equal(daily.provisional, expected);
        for (const brief of briefs) {
          assert.equal(brief.provisional, daily.provisional);
          assert.equal(brief.headline, daily.headline);
          assert.equal(brief.deck, daily.summary);
          for (const key of ['label', 'status', 'confidence', 'windows', 'alerts', 'missing', 'tides', 'tideEvents', 'sunrise', 'sunset']) {
            assert.deepEqual(brief[key], daily[key], `${profile}: ${day}: ${brief.basis}: ${key}`);
          }
        }
      }
    }
  }
});
