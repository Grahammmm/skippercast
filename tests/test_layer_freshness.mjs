// SCFEAT-FRESH-1: one update-cadence line per legend row, same wording on every layer, and the
// numbers agree with catalog/layer-inventory.json and catalog/feed-health.json. Offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
const json = async p => JSON.parse(await readFile(join(root, p), 'utf8'));

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'layer-fresh-'));
  const out = join(dir, 'fresh.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export * from './web/map/freshness.ts';
    export {forecastTime} from './web/map/frames.ts';
    export {stationPins, STATION_BASIS, STATION_OBSERVATION_STALE_HOURS, STATION_PREDICTION_STALE_HOURS} from './web/map/station-model.ts';
    export {Legend} from './web/app/Legend.tsx';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return {m: await import(pathToFileURL(out).href), dir};
}

test('every layer and the rules row has one cadence line in one wording', async () => {
  const {m, dir} = await load();
  try {
    const ids = ['seafloor', 'currents', 'water-temp', 'sst-contrast', 'sst-fronts', 'chlorophyll', 'swell', 'stations', 'fleet', 'clouds', 'mpas'];
    for (const id of ids) {
      const en = m.cadenceLine(id, 'en');
      assert.match(en, /^Updates: /, id);
      assert.ok(!/UNVERIFIED|MEASURED|ESTIMATED/.test(en), `${id}: no internal labels`);
      assert.notEqual(m.cadenceLine(id, 'es'), en, `${id}: Spanish differs`);
      assert.match(m.cadenceLine(id, 'es'), /^Actualización: /, id);
    }
    assert.equal(m.cadenceLine('water-temp', 'en'), 'Updates: daily · age limit 72 h');
    assert.equal(m.cadenceLine('clouds', 'en'), 'Updates: about every 5 min · age limit 90 min');
    assert.equal(m.cadenceLine('nope', 'en'), '');
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('age limits match feed-health.json and the layer inventory', async () => {
  const {m, dir} = await load();
  try {
    const health = await json('catalog/feed-health.json');
    const inv = await json('catalog/layer-inventory.json');
    const byId = Object.fromEntries(inv.layers.map(l => [l.id, l]));
    assert.equal(m.LAYER_FRESHNESS['sst-fronts'].limitHours, health.feeds['sst-fronts'].max_age_hours);
    // Stations is not gated by the conditions-feed watchdog limit: pins keep stale readings (see the station test below).
    assert.equal(m.LAYER_FRESHNESS['stations'].limitHours, null);
    for (const [id, f] of Object.entries(m.LAYER_FRESHNESS)) {
      for (const inventoryId of f.inventory) {
        const layer = byId[inventoryId];
        assert.ok(layer, `${id}: inventory layer ${inventoryId} exists`);
        if (f.limitHours !== null && f.checkInventoryLimit) {
          const limits = [...layer.update_cadence.matchAll(/(\d+) h/g)].map(x => Number(x[1]));
          assert.ok(limits.includes(f.limitHours), `${id}: ${f.limitHours} h in "${layer.update_cadence}"`);
        }
      }
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('the legend shows the cadence line under each layer that is on', async () => {
  const {m, dir} = await load();
  try {
    m.state.configureStore({v2: true, storage: null});
    m.state.syncFromURL('https://s.test/map?region=morro-bay&presentation=chart&layers=water-temp,clouds');
    const html = m.render(m.h(m.Legend));
    assert.match(html, /data-cadence="water-temp"><p[^>]*>Updates: daily · age limit 72 h</);
    assert.match(html, /data-cadence="clouds"/);
    assert.match(html, /data-cadence="mpas"/);
    assert.ok(!html.includes('data-cadence="currents"'), 'only layers that are on');
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('swell states the gates forecastTime actually applies, not an invented age limit', async () => {
  const {m, dir} = await load();
  try {
    const g = m.LAYER_FRESHNESS.swell.forecastGate;
    assert.deepEqual(g, {runHours: 36, retrievedHours: 6});
    assert.equal(m.cadenceLine('swell', 'en'), 'Updates: every 6 to 12 h, with each model run · run at most 36 h old, retrieved within 6 h');
    assert.ok(!/18 h/.test(m.cadenceLine('swell', 'en')) && !/18 h/.test(m.cadenceLine('swell', 'es')));
    // Behaviour of the renderers' gate (swell.ts and wind.ts both call forecastTime) at the published numbers.
    const H = 3600e3, now = new Date('2026-11-07T12:00:00Z'), n = now.getTime();
    const times = [n - 30 * H, n - 24 * H, n - 12 * H, n, n + 12 * H];
    const draw = (runAge, fetchAge, at) => m.forecastTime(times, n - runAge * H, n - fetchAge * H, new Date(at), now);
    assert.equal(draw(24, 1, n - 24 * H), n - 24 * H, 'a 24 h old run, freshly retrieved, still draws (18 h would be false)');
    assert.equal(draw(g.runHours, 1, n), n, 'run exactly at the limit draws');
    assert.equal(draw(g.runHours + 1, 1, n), null, 'run past the limit is withheld');
    assert.equal(draw(1, g.retrievedHours, n), n, 'retrieval exactly at the limit draws');
    assert.equal(draw(1, g.retrievedHours + 1, n), null, 'retrieval past the limit is withheld');
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('currents do not publish one age limit for both sources', async () => {
  const {m, dir} = await load();
  try {
    assert.equal(m.cadenceLine('currents', 'en'), 'Updates: hourly · radar observation at most 6 h old; forecast run at most 36 h old');
    assert.match(m.cadenceLine('currents', 'es'), /6 h.*36 h/);
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('stations state the stale thresholds the pins apply, not the conditions-feed watchdog limit', async () => {
  const {m, dir} = await load();
  try {
    const stations = await json('catalog/station-locations.json');
    const g = m.LAYER_FRESHNESS.stations.staleGate;
    assert.deepEqual(g, {observationHours: 3, predictionHours: 36});
    assert.equal(g.observationHours, m.STATION_OBSERVATION_STALE_HOURS);
    assert.equal(g.predictionHours, m.STATION_PREDICTION_STALE_HOURS);
    assert.equal(m.cadenceLine('stations', 'en'), 'Updates: every live update · observations labelled stale after 3 h, tide predictions after 36 h; last-good values stay shown with their original times');
    assert.ok(!/age limit/.test(m.cadenceLine('stations', 'en')), 'no universal withholding limit is claimed');
    assert.match(m.cadenceLine('stations', 'es'), /^Actualización: .*3 h.*36 h/);
    assert.ok(m.STATION_BASIS.includes(`observations older than ${g.observationHours} hours`) && m.STATION_BASIS.includes(`predictions retrieved over ${g.predictionHours} hours ago`), 'the station basis states the same numbers');
    // Behaviour at the published numbers (web/map/station-model.ts), whatever the conditions feed's own limit is.
    const H = 3600e3, now = new Date('2026-11-07T12:00:00Z');
    const ago = h => new Date(+now - h * H).toISOString();
    const region = {id: 'fixture', stations: {tide: '9412553', offshore_buoy: '46054'}};
    const buoy = h => ({id: 'buoy', kind: 'observation', name: 'Buoy', url: 'https://example.test', checked_at: ago(0), status: 'ok', station: '46054',
      data: {station: '46054', units: {WTMP: 'degC'}, observations: [{time: ago(h), WTMP: 10}]}});
    const tide = h => ({id: 'tides', kind: 'prediction', name: 'Tide', url: 'https://example.test', checked_at: ago(h), status: 'ok', station: '9412553',
      data: {station: '9412553', units: 'ft', datum: 'MLLW', note: 'n', coverage_start: ago(5), coverage_end: ago(-5),
        predictions: [{time: ago(5), height_ft: -0.4, type: 'L'}, {time: ago(-0.2), height_ft: 4, type: 'H'}, {time: ago(-5), height_ft: 2, type: 'L'}]}});
    const pin = (sources, key) => m.stationPins({region, catalog: stations, feed: {region_id: 'fixture', sources}, now, at: now, zone: 'America/Los_Angeles'}).find(p => p.key === key);
    const obsAt = h => pin([buoy(h), tide(1)], 'ndbc:46054'), tideAt = h => pin([buoy(1), tide(h)], 'coops:9412553');
    assert.equal(obsAt(g.observationHours).stale, false, 'an observation exactly at the limit is fresh');
    const late = obsAt(g.observationHours + 1);
    assert.equal(late.stale, true, 'an older observation is labelled stale');
    assert.match(late.mark.reading, /Water 50\.0 °F · .* · stale/, 'the stale value is retained, not withheld');
    assert.ok(late.mark.reading.includes(ago(g.observationHours + 1)), 'the original observation time is retained');
    assert.equal(tideAt(g.predictionHours).stale, false, 'a prediction retrieved exactly at the limit is fresh');
    assert.equal(tideAt(g.observationHours + 1).stale, false, 'the 3 h observation limit does not apply to predictions');
    const old = tideAt(g.predictionHours + 1);
    assert.equal(old.stale, true, 'an older prediction retrieval is labelled stale');
    assert.match(old.mark.reading, /Tide .*ft MLLW/, 'the stale prediction value is retained');
    assert.ok(old.mark.reading.includes(ago(g.predictionHours + 1)), 'the original retrieval time is retained');
  } finally { await rm(dir, {recursive: true, force: true}); }
});
