// Offline rendered regression for the charter research date; no map or provider calls.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

test('charter legend formats only valid date-only research dates, independent of timezone', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'legend-dates-'));
  const previousTZ = process.env.TZ;
  try {
    const out = join(dir, 'legend.mjs');
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Legend} from './web/app/Legend.tsx';
      export {groundsState, groundMark} from './web/map/charter-grounds.ts';
      export {layerEntry} from './web/map/layers.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
      jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href);
    m.state.configureStore({v2: true, storage: null});
    m.state.syncFromURL('https://s.test/map?region=morro-bay&presentation=chart&layers=fleet');
    const ground = {id: 'synthetic', label: 'Synthetic vicinity', precision: 'approximate',
      report_count: 1, boats: ['synthetic'], latest_report: '2026-09-21', depth_ft: [10, 20],
      survey_year: 2020, reported_ground: 'Synthetic', location_confidence: 'approximate', boundary_note: ''};
    for (const tz of ['UTC', 'America/Los_Angeles', 'Pacific/Kiritimati']) {
      process.env.TZ = tz;
      for (const audit of ['2026-09-21', '2024-02-29', null, '', 'invalid', '2026-02-30', '2026-09-21T00:00:00Z']) {
        for (const drawn of [0, 2]) {
          m.groundsState.value = {drawn, note: 'Synthetic source status', audit};
          const html = m.render(m.h(m.Legend));
          const row = html.match(/<li class="app-legend-fleet">(.*?)<\/li>/s)?.[1];
          assert.ok(row);
          assert.ok(row.includes(m.layerEntry('charter-grounds').basis));
          assert.ok(row.includes('Synthetic source status'));
          assert.equal(row.includes('data-layer="charter-grounds"'), drawn > 0);
          if (audit === '2026-09-21' || audit === '2024-02-29') {
            const cardDate = m.groundMark(ground, {audit_date: audit}).source.split('research checked ')[1];
            assert.ok(row.includes(`Research checked ${cardDate}.`), `${tz}: expected card date ${cardDate} in ${row}`);
          } else {
            assert.ok(!row.includes('Research checked'), `${tz}: no invented date for ${audit}`);
          }
          assert.ok(!row.includes('Invalid Date'));
        }
      }
    }
  } finally {
    if (previousTZ === undefined) delete process.env.TZ; else process.env.TZ = previousTZ;
    await rm(dir, {recursive: true, force: true});
  }
});
