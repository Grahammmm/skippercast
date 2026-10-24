import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

test('Stations legend and selected card render stale clocks, provider link, key, and location gaps', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'station-ui-')), 'ui.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {Legend} from './web/app/Legend.tsx';
    export {MarkCard} from './web/app/MarkCard.tsx';
    export {stationState} from './web/map/stations.ts';
    export {stationPins} from './web/map/station-model.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://example.test/map?region=fixture&layers=stations');
  const pins = m.stationPins({region: {id: 'fixture', stations: {nearshore_buoy: '46054'}}, catalog: {stations: {}},
    feed: {region_id: 'fixture', sources: {buoy: {id: 'buoy', kind: 'observation', status: 'retained', station: '46054',
      data: {station: '46054', units: {WTMP: 'degC'}, observations: [{time: '2026-10-20T10:00:00Z', WTMP: 10}]}}}},
    now: new Date('2026-10-20T18:00:00Z'), at: new Date('2026-10-20T18:00:00Z')});
  m.stationState.value = {pins, note: '46054: location unavailable'};
  const legend = m.render(m.h(m.Legend));
  assert.match(legend, /Stations basis/);
  assert.match(legend, /Buoy observation/); assert.match(legend, /Tide prediction/);
  assert.match(legend, /Stale or unavailable/); assert.match(legend, /CDIP MOP model site: ring/);
  assert.match(legend, /Station list/); assert.match(legend, /46054: location unavailable/);
  const card = m.render(m.h(m.MarkCard, {mark: pins[0].mark}));
  assert.match(card, /Water 50.0 °F · 2026-10-20T10:00:00Z · stale \/ last good/);
  assert.match(card, /href="https:\/\/www.ndbc.noaa.gov\/station_page.php\?station=46054"/);
  assert.match(card, /Observing buoy/);
  assert.doesNotMatch(card, /Regulations: NOAA/);
});
