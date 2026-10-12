// Map startup (P4-05): the startup JSON budget, measured on the v2 app at /map (FE-60 made it
// the default; FE-61 removed v1's map, its legend sheet and its deferred-screen checks).
import {readFileSync} from 'node:fs';
import {test, expect} from './fixtures.ts';
import {MAP_READY, measureStartup, formatTable, stubLiveFeeds} from '../scripts/measure_startup.mjs';

const budget = JSON.parse(readFileSync(new URL('../scripts/startup-budget.json', import.meta.url), 'utf8'))['morro-bay'];

// The app reads each committed file once and stays within the budget. The Chart's always-on
// coastline glow reads the region's shoreline in its published form (schema_version 2,
// src/skippercast/platform/shoreline.py). Live feeds get deterministic stand-ins, so the
// budgeted number (committed static files only) does not move with upstream data.
test('the v2 app reads each committed startup file once, within the budget', async ({page, pageErrors}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  await stubLiveFeeds(page, {id: 'morro-bay'});
  const result = await measureStartup(page, {path: '/map?region=morro-bay', ready: MAP_READY});
  console.log(formatTable(result));
  const repeated = result.rows.filter(r => !r.live && r.requests > 1).map(r => `${r.path} × ${r.requests}`);
  expect(repeated, 'each committed static file is requested once').toEqual([]);
  expect(result.static, `static startup JSON ${result.static} bytes; budget ${budget.max_bytes} (scripts/startup-budget.json)`).toBeLessThanOrEqual(budget.max_bytes);
  expect(pageErrors).toEqual([]);
});
