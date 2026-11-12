// RF1900-5: an impossible civil report date shows the existing "date unavailable" copy, never the next real day.
// Synthetic data only; the real helper and ReportsBody are bundled like tests/test_reports_zone.mjs.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reports-calendar-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {ReportsBody} from './web/app/views/Reports.tsx';
      export {reportDay} from './web/reports-copy.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [...preparedRendererPlugins, {name: 'reports-trip-renderer', setup: b => {
      b.onResolve({filter: /^\.\/map\/maplibre\.js$/}, args => ({path: args.path, external: true}));
    }}],
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const NA = {en: 'date unavailable', es: 'fecha no disponible'};
const LA = 'America/Los_Angeles', TOKYO = 'Asia/Tokyo';

test('impossible_civil_day_is_unavailable_en_es', async () => {
  const {reportDay} = await load();
  for (const lang of ['en', 'es']) {
    for (const bad of ['2026-02-29', '2026-02-30', '2026-02-31', '2026-04-31', '2026-06-31', '2026-09-31', '2026-11-31', '2026-00-10', '2026-13-01', '2026-01-00', '2026-01-32']) {
      assert.equal(reportDay(bad, lang), NA[lang], `${lang} ${bad}`);
    }
  }
});

test('leap_century_and_valid_month_ends', async () => {
  const {reportDay} = await load();
  for (const bad of ['1900-02-29', '2100-02-29']) assert.equal(reportDay(bad, 'en'), NA.en);
  const expectEn = {'2000-02-29': 'Feb 29, 2000', '2024-02-29': 'Feb 29, 2024', '2026-02-28': 'Feb 28, 2026', '2026-04-30': 'Apr 30, 2026', '2026-01-31': 'Jan 31, 2026', '2026-12-31': 'Dec 31, 2026'};
  for (const [iso, text] of Object.entries(expectEn)) assert.equal(reportDay(iso, 'en'), text);
  assert.equal(reportDay('2024-02-29', 'es'), '29 feb 2024');
});

test('civil_dates_ignore_region_zone', async () => {
  const {reportDay} = await load();
  for (const z of ['UTC', LA, TOKYO]) {
    assert.equal(reportDay('2026-02-29', 'en', z), NA.en);
    assert.equal(reportDay('2026-04-31', 'es', z), NA.es);
    assert.equal(reportDay('2026-03-01', 'en', z), 'Mar 1, 2026');
    assert.equal(reportDay('0999-12-31', 'en', z), reportDay('0999-12-31', 'en', 'UTC'));
    assert.ok(!reportDay('0999-12-31', 'en', z).includes('1999'));
  }
});

test('instant_and_missing_compatibility', async () => {
  const {reportDay} = await load();
  const AT = '2026-10-12T20:30:00Z';
  const fmt = zone => new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: zone}).format(new Date(AT));
  assert.equal(reportDay(AT, 'en', TOKYO), fmt(TOKYO));
  assert.equal(reportDay(AT, 'en'), fmt(LA));
  for (const bad of [null, undefined, '', 'nope']) assert.equal(reportDay(bad, 'en'), NA.en);
});

test('reports_body_has_no_fabricated_date', async () => {
  const {ReportsBody, render, h} = await load();
  const AT = '2026-10-12T20:30:00Z';
  const data = {
    evidence: {confidence: 'Low', reason: 'r', start: '2026-02-29', end: '2026-10-05', boats: 1, days: 1, trips: 1, generatedAt: AT,
      rows: [{date: '2026-04-31', boat: 'Bad Day Boat', catches: '1 Lingcod', where: 'x', url: null}, {date: '2026-04-30', boat: 'Good Day Boat', catches: '1 Lingcod', where: 'x', url: null}]},
    discussions: {status: 'current', checkedQueries: 1, totalQueries: 1, generatedAt: AT, candidates: []},
    watch: null,
    charters: null,
  };
  const before = JSON.stringify(data);
  const html = render(h(ReportsBody, {data, catches: null}));
  assert.equal(JSON.stringify(data), before, 'input model not mutated');
  assert.ok(html.includes(NA.en), 'fallback shown');
  assert.ok(!html.includes('Mar 1, 2026'), 'no February-29 rollover');
  assert.ok(!html.includes('May 1, 2026'), 'no April-31 rollover');
  assert.ok(html.includes('Apr 30, 2026'), 'valid sibling date kept');
  assert.ok(html.includes('Oct 5, 2026'), 'valid endpoint kept');
});
