// Backup-station labels (#554 station failover): a feed source names the
// station it read (`station`) and, only when a backup served it, the primary
// (`fallback_for`). Every surface that names a buoy or tide station must show
// the actual station, "backup for" the primary, and link to the actual
// station; feeds without these fields read exactly as before.
import test from 'node:test';
import assert from 'node:assert/strict';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {ndbcStationURL, sharedStation, sourceStation, stationText, tidePredictionURL} = await import('../web/station-label.ts');
const {buoyReadings} = await import('../web/landing/readings.ts');
const {buildRegionalBrief, regionalReport} = await import('../web/brief/model.ts');
const {buoyStation, observationsHTML, observedDock, sharedBuoy} = await import('../dist/live-conditions.js');
const {evidenceHTML} = await import('../dist/bite-evidence.js');

const NOW = Date.parse('2026-10-11T19:00:00Z');
const ago = min => new Date(NOW - min * 60000).toISOString();
// The Ventura context: nearshore 46053 with 46054 as its backup; 46054 is also the offshore primary.
const STATIONS = {nearshore_buoy: '46053', nearshore_buoy_name: 'East Santa Barbara Channel', offshore_buoy: '46054', offshore_buoy_name: 'West Santa Barbara Channel',
  tide: '9411340', tide_name: 'Santa Barbara', tide_note: 'Santa Barbara is a reference water-level station.', airport: 'KSBA', airport_name: 'Santa Barbara airport'};
const UNITS = {WVHT: 'm', DPD: 'sec', MWD: 'degT', WSPD: 'm/s', GST: 'm/s', WDIR: 'degT', WTMP: 'degC', SwH: 'm', SwP: 'sec', SwD: '-', WWH: 'm', WWP: 'sec', WWD: '-'};
const row = {time: ago(20), WVHT: 1.2, DPD: 11, MWD: 270, WSPD: 6, GST: 8, WDIR: 300, WTMP: 16, SwH: 0.9, SwP: 12, SwD: 'W', WWH: 0.4, WWP: 5, WWD: 'NW'};
const src = (name, dataStation, extra = {}) => ({name, status: 'ok', max_age_hours: 2, ...extra, data: {station: dataStation, units: UNITS, observations: [row]}});

/** A live conditions feed in one of the five cases, with the client's role aliases. */
function liveFeed(kind) {
  const near = {
    legacy: src('East Santa Barbara Channel', '46053'),
    primary: src('East Santa Barbara Channel', '46053', {station: '46053'}),
    backup: src('NOAA NDBC 46054 observations', '46054', {station: '46054', fallback_for: '46053', station_url: ndbcStationURL('46054')}),
    retained: src('NOAA NDBC 46054 observations', '46054', {station: '46054', fallback_for: '46053', status: 'retained', issue: 'NDBC 46053 and 46054 failed'}),
  }[kind === 'shared' ? 'backup' : kind];
  const spectrum = {...near, name: near.name + ' swell and wind waves'};
  const offshore = src('West Santa Barbara Channel', '46054', kind === 'legacy' ? {} : {station: '46054'});
  return {schema_version: 1, generated_at: ago(10), sources: {diablo: near, 'diablo-spectrum': spectrum, offshore}};
}
const live = kind => ({stations: STATIONS, zones: {coastal: 'PZZ650', offshore: 'PZZ673'}, buoys: liveFeed(kind), airport: null, water: undefined, alerts: {coastal: [], offshore: []}, retrieved: NOW});

test('the helper: actual station, backup for the primary, official links, shared only with a backup', () => {
  assert.deepEqual(sourceStation({station: '46054', fallback_for: '46053'}, '46053'), {id: '46054', backupFor: '46053'});
  assert.deepEqual(sourceStation({station: '46053'}, '46053'), {id: '46053', backupFor: null});
  assert.deepEqual(sourceStation({data: {station: '46054'}, fallback_for: '46053'}), {id: '46054', backupFor: '46053'}, 'a backup without station names its data station');
  assert.deepEqual(sourceStation({data: {station: '46053'}}, '46053'), {id: '46053', backupFor: null}, 'legacy: the caller\'s station');
  assert.equal(sourceStation({}, undefined), null);
  assert.equal(sourceStation({station: '<script>'}, '46053').id, '46053', 'an id that is not a station id is ignored');
  assert.equal(stationText({id: '46054', backupFor: '46053'}), '46054 (backup for 46053)');
  assert.equal(stationText({id: '46053', backupFor: null}), '46053');
  assert.equal(ndbcStationURL('46054'), 'https://www.ndbc.noaa.gov/station_page.php?station=46054');
  assert.equal(tidePredictionURL('9410166'), 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9410166');
  assert.equal(sharedStation({id: '46054', backupFor: '46053'}, {id: '46054', backupFor: null}), true);
  assert.equal(sharedStation({id: '46013', backupFor: null}, {id: '46013', backupFor: null}), false, 'a region that configures one buoy for both roles keeps its labels');
  assert.equal(sharedStation({id: '46054', backupFor: '46053'}, {id: '46025', backupFor: null}), false);
});

test('live conditions: legacy and primary keep the region name and link; a backup names and links its own station', () => {
  for (const kind of ['legacy', 'primary']) {
    const html = observationsHTML(live(kind), false, NOW);
    assert.match(html, /<h3>East Santa Barbara Channel · 46053<\/h3><a href="https:\/\/www\.ndbc\.noaa\.gov\/station_page\.php\?station=46053"/, kind);
    assert.doesNotMatch(html, /backup|Same station/, kind);
    assert.match(observedDock(live(kind), false, NOW), /East Santa Barbara Channel buoy reference/, kind);
    assert.equal(sharedBuoy(live(kind).buoys, STATIONS), false, kind);
  }
  const html = observationsHTML(live('backup'), false, NOW);
  assert.match(html, /<h3>NDBC 46054 \(backup for 46053\)<\/h3><a href="https:\/\/www\.ndbc\.noaa\.gov\/station_page\.php\?station=46054"/);
  assert.doesNotMatch(html, /East Santa Barbara Channel/, 'the primary\'s name never labels backup data');
  assert.match(html, /Spectrum from NDBC 46054 \(backup for 46053\)\./);
  assert.match(observedDock(live('backup'), false, NOW), /NDBC 46054 \(backup for 46053\) ·/);
  assert.deepEqual(buoyStation(live('backup').buoys, 'diablo', STATIONS).station, {id: '46054', backupFor: '46053'});
});

test('live conditions: a shared station is said once plainly, on both views', () => {
  const near = observationsHTML(live('shared'), false, NOW), outer = observationsHTML(live('shared'), true, NOW);
  assert.equal(sharedBuoy(live('shared').buoys, STATIONS), true);
  assert.match(near, /Same station as the offshore reading \(NDBC 46054\), not a separate measurement\./);
  assert.match(near, /Buoy 46054 \(same station as the card above\) · wind/);
  assert.match(outer, /<h3>West Santa Barbara Channel · 46054<\/h3>/, 'the offshore primary keeps its name');
  assert.match(outer, /Same station as the nearshore reading \(NDBC 46054\), not a separate measurement\./);
});

test('live conditions: a retained backup keeps its station label and its stale state', () => {
  const html = observationsHTML(live('retained'), false, NOW);
  assert.match(html, /<h3>NDBC 46054 \(backup for 46053\)<\/h3>/);
  assert.match(html, /observation-age stale">Update unavailable/);
  assert.match(html, /NDBC 46053 and 46054 failed/);
  assert.equal(observedDock(live('retained'), false, NOW), null, 'retained data is not a fresh observed dock');
});

test('landing readout: backup tiles name the actual station; shared and retained stay visible; legacy is unchanged', () => {
  const region = {stations: STATIONS};
  const read = kind => Object.fromEntries(buoyReadings(liveFeed(kind), region, NOW).map(r => [r.id, r]));
  for (const kind of ['legacy', 'primary']) {
    const r = read(kind);
    assert.equal(r.water.source, 'NDBC 46053 · 20 min', kind);
    assert.equal(r.water.basis, 'Surface water temperature measured at the East Santa Barbara Channel buoy; stale after 2 h.', kind);
    assert.doesNotMatch(r.wind.basis + r.swell.basis, /backup|Same station/, kind);
  }
  const backup = read('backup');
  assert.equal(backup.water.source, 'NDBC 46054 (backup for 46053) · 20 min');
  assert.equal(backup.swell.source, 'NDBC 46054 (backup for 46053) · 20 min');
  assert.equal(backup.wind.source, 'NDBC 46054 · 20 min');
  assert.match(backup.water.basis, /^Surface water temperature measured at NDBC buoy 46054, the backup for 46053; stale after 2 h\. Same station as the wind reading, not a separate measurement\.$/);
  assert.match(backup.swell.basis, /at NDBC buoy 46054, the backup for 46053;.* Same station as the wind reading/);
  assert.match(backup.wind.basis, /Same station as the water reading, not a separate measurement\.$/);
  assert.doesNotMatch(Object.values(backup).map(r => r.basis).join(' '), /East Santa Barbara/);
  const retained = read('retained');
  assert.equal(retained.water.source, 'NDBC 46054 (backup for 46053) · 20 min');
  assert.equal(retained.water.stale, true, 'retained data reads stale');
});

/** The Monterey daily feed with its buoy and tide in one of the cases. */
function daily(kind) {
  const feed = structuredClone(montereyDaily);
  const buoy = feed.sources['buoy-46042'], tides = feed.sources.tides;
  if (kind === 'primary') { buoy.station = '46042'; tides.station = '9413450'; }
  if (kind === 'backup' || kind === 'retained') {
    Object.assign(buoy, {station: '46092', fallback_for: '46042', name: 'NOAA NDBC 46092 observations', url: 'https://www.ndbc.noaa.gov/data/realtime2/46092.txt'});
    buoy.data.station = '46092';
    Object.assign(tides, {station: '9413616', fallback_for: '9413450', name: 'NOAA 9413616 tide predictions'});
    tides.data = {...tides.data, station: '9413616', note: 'NOAA 9413616 station-specific backup water-level predictions (MLLW).'};
    if (kind === 'retained') { buoy.status = 'retained'; tides.status = 'retained'; }
  }
  return feed;
}
const place = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
const briefNow = new Date(Date.parse(montereyForecast.fetchedAt) + 10 * 60_000);

test('regional brief: a backup buoy and tide are named as themselves and link to their official pages', () => {
  const legacy = regionalReport(daily('legacy'), montereyForecast, place), primary = regionalReport(daily('primary'), montereyForecast, place);
  for (const r of [legacy, primary]) {
    assert.equal(r.county.tideStation.name, 'NOAA Monterey reference tide predictions');
    assert.equal(r.report.sources.find(s => s.kind === 'observation').label, 'NOAA NDBC 46042 observations');
    assert.equal(r.report.sources.find(s => s.kind === 'observation').url, 'https://www.ndbc.noaa.gov/data/realtime2/46042.txt');
    assert.equal(r.buoyBackupFor, null);
  }
  const backup = regionalReport(daily('backup'), montereyForecast, place);
  assert.equal(backup.county.tideStation.name, 'NOAA 9413616 (backup for 9413450)', 'never the primary\'s "reference" name');
  assert.equal(backup.county.tideStation.url, 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9413616');
  assert.equal(backup.county.tideStation.note, 'NOAA 9413616 station-specific backup water-level predictions (MLLW).');
  const obs = backup.report.sources.find(s => s.kind === 'observation');
  assert.deepEqual([obs.label, obs.url], ['NDBC 46092 (backup for 46042)', 'https://www.ndbc.noaa.gov/station_page.php?station=46092']);
  assert.equal(backup.buoyBackupFor, '46042');
  for (const kind of ['backup', 'retained']) {
    const brief = buildRegionalBrief({daily: daily(kind), forecast: montereyForecast, place, profile: 'boat', date: '2026-10-08', now: briefNow});
    const water = brief.tiles.find(t => t.id === 'water'), tide = brief.tiles.find(t => t.id === 'tide');
    assert.notEqual(water.value, null, kind);
    assert.equal(water.source, 'NDBC 46092 (backup for 46042)', kind);
    assert.equal(water.sourceUrl, 'https://www.ndbc.noaa.gov/station_page.php?station=46092', kind);
    assert.equal(water.detail, 'buoy 46092 (backup for 46042)', kind);
    assert.match(tide.detail, /NOAA 9413616 \(backup for 9413450\)/, kind);
    assert.doesNotMatch(tide.detail, /reference/, kind);
    assert.equal(tide.sourceUrl, 'https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9413616', kind);
    if (kind === 'retained') {
      assert.equal(tide.state, 'stale', 'a retained backup tide stays stale');
      assert.equal(water.state, 'stale', 'a retained backup buoy stays stale');
    }
  }
});

test('daily evidence buoys: a backup is named and linked as itself; legacy keeps the configured names', () => {
  const base = {sources: {
    'buoy-46215': {status: 'ok', url: 'https://www.ndbc.noaa.gov/data/realtime2/46215.txt', data: {station: '46215', observations: [{time: ago(30), WVHT: 1, DPD: 10}]}},
    'buoy-46028': {status: 'ok', url: 'https://www.ndbc.noaa.gov/data/realtime2/46028.txt', data: {station: '46028', observations: [{time: ago(30), WVHT: 2, DPD: 12}]}},
  }};
  const html = data => evidenceHTML({...data, generated_at: ago(60), reports: [], status: {}}, 'reef', {name: 'Test point', latitude: 35.3, longitude: -120.9}) ?? '';
  const legacy = html(base);
  assert.match(legacy, /Diablo Canyon · 46215/);
  const backup = structuredClone(base);
  Object.assign(backup.sources['buoy-46215'], {station: '46011', fallback_for: '46215'});
  backup.sources['buoy-46215'].data.station = '46011';
  const out = html(backup);
  assert.match(out, /NDBC 46011 \(backup for 46215\)/);
  assert.doesNotMatch(out, /Diablo Canyon · 46215/);
  assert.match(out, /station_page\.php\?station=46011/);
});
