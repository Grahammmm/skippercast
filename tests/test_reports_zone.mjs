// RF2115-7: Reports timestamps are shown in the matching loaded region's zone; date-only (civil) dates stay UTC.
// Synthetic data only; the real renderers are bundled like tests/test_reports_view.mjs.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reports-zone-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Reports, ReportsBody, reportsData} from './web/app/views/Reports.tsx';
      export {reportDay} from './web/reports-copy.ts';
      export {regionInfo} from './web/app/region-info.ts';
      export {region, species} from './web/state.ts';
      export {language} from './web/i18n.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [...rendererPlugins, {name: 'reports-trip-renderer', setup: b => {
      b.onResolve({filter: /^\.\/map\/maplibre\.js$/}, args => ({path: args.path, external: true}));
    }}],
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const AT = '2026-10-12T20:30:00Z'; // Oct 12 in Los Angeles, Oct 13 in Tokyo
const fmt = (lang, zone, iso) => new Intl.DateTimeFormat(lang, {month: 'short', day: 'numeric', year: 'numeric', timeZone: zone}).format(new Date(iso));
const LA = 'America/Los_Angeles', TOKYO = 'Asia/Tokyo';
const data = () => ({
  evidence: {confidence: 'Low', reason: 'r', start: '2026-10-01', end: '2026-10-05', boats: 1, days: 1, trips: 1, generatedAt: AT,
    rows: [{date: AT, boat: 'Fixture Boat', catches: '1 Lingcod', where: 'x', url: null}]},
  discussions: {status: 'current', checkedQueries: 1, totalQueries: 1, generatedAt: AT,
    candidates: [{url: 'https://d.example/1', title: 'T', source: 'S', published_at: AT}]},
  watch: null,
  charters: {audit: AT, more: 0, rows: [{label: 'L', ground: 'G', trips: 1, boats: 1, latest: AT, sources: [{date: AT, boat: 'B', url: 'https://c.example/1'}]}]},
});

test('reportDay: explicit zone, default equals Pacific, civil dates ignore the zone, bad input unavailable', async () => {
  const {reportDay} = await load();
  for (const lang of ['en', 'es']) {
    const loc = lang === 'es' ? 'es' : 'en-US';
    assert.equal(reportDay(AT, lang, TOKYO), fmt(loc, TOKYO, AT));
    assert.equal(reportDay(AT, lang, 'UTC'), fmt(loc, 'UTC', AT));
    assert.equal(reportDay(AT, lang), reportDay(AT, lang, LA));
    assert.notEqual(reportDay(AT, lang, TOKYO), reportDay(AT, lang, LA));
    for (const z of ['UTC', LA, TOKYO]) assert.equal(reportDay('2026-10-12', lang, z), reportDay('2026-10-12', lang, 'UTC'));
  }
  for (const bad of [null, undefined, '', 'nope']) assert.equal(reportDay(bad, 'en', TOKYO), reportDay(bad, 'en'));
});

test('every timestamp surface uses the zone; date-only endpoints stay fixed', async () => {
  const {ReportsBody, render, h} = await load();
  const tokyo = fmt('en-US', TOKYO, AT), la = fmt('en-US', LA, AT);
  const html = render(h(ReportsBody, {data: data(), catches: null, timeZone: TOKYO}));
  // generated (caveat), row, discussion updated + published, charter latest + source + audit: 7 timestamps
  assert.equal(html.split(tokyo).length - 1, 7);
  assert.ok(!html.includes(la));
  assert.ok(html.includes('Oct 1, 2026–Oct 5, 2026'), 'date-only endpoints stay UTC civil dates');
  const stale = data(); stale.discussions = {...stale.discussions, status: 'stale'};
  assert.ok(render(h(ReportsBody, {data: stale, catches: null, timeZone: TOKYO})).includes(`${tokyo}`));
  assert.equal(render(h(ReportsBody, {data: data(), catches: null})), render(h(ReportsBody, {data: data(), catches: null, timeZone: LA})));
});

test('Reports uses the matching region metadata only', async () => {
  const {Reports, reportsData, regionInfo, region, species, render, h} = await load();
  const tokyo = fmt('en-US', TOKYO, AT), la = fmt('en-US', LA, AT);
  region.value = 'zz-test'; species.value = 'lingcod';
  reportsData.value = {key: 'zz-test:lingcod', data: data()};
  const info = (id, timezone) => ({id, name: 'N', center: [0, 0], timezone});
  try {
    regionInfo.value = info('zz-test', TOKYO);
    assert.ok(render(h(Reports, {})).includes(tokyo));
    regionInfo.value = info('other', TOKYO);
    let html = render(h(Reports, {}));
    assert.ok(html.includes(la) && !html.includes(tokyo), 'other region metadata is ignored');
    regionInfo.value = null;
    assert.ok(render(h(Reports, {})).includes(la));
    regionInfo.value = info('zz-test', 'UTC'); // replaced metadata, same retained data
    html = render(h(Reports, {}));
    assert.ok(html.includes(fmt('en-US', 'UTC', AT)));
  } finally { regionInfo.value = null; region.value = null; species.value = null; reportsData.value = null; }
});
