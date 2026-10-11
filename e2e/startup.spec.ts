// Map startup (P4-05): the startup JSON budget. FE-61 measures the v2 app at
// /map; v1's legend sheet and its deferred-screen checks went with the v1 shell.
import {readFileSync} from 'node:fs';
import {test, expect} from './fixtures.ts';
import {measureStartup, formatTable, stubLiveFeeds} from '../scripts/measure_startup.mjs';

const budget = JSON.parse(readFileSync(new URL('../scripts/startup-budget.json', import.meta.url), 'utf8'))['morro-bay'];

test('Morro Bay startup JSON from committed files stays within its budget', async ({page, pageErrors}, info) => {
  test.skip(info.project.name !== 'phone', 'measured once, at phone size');
  // Live feeds get deterministic stand-ins, so the budgeted number (committed
  // static files only) does not move with upstream data.
  await stubLiveFeeds(page, {id: 'morro-bay'});
  const result = await measureStartup(page, {path: '/map?region=morro-bay'});
  console.log(formatTable(result));
  expect(result.static, `static startup JSON ${result.static} bytes; budget ${budget.max_bytes} (scripts/startup-budget.json)`).toBeLessThanOrEqual(budget.max_bytes);
  expect(pageErrors).toEqual([]);
});
