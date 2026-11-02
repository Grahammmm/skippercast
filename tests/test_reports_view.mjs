// FE-52: the Reports view (design § 6). The view and web/reports.ts are
// bundled with esbuild and rendered to strings over synthetic fixtures built
// here (invented boats and links, no publisher data): catch cards keep boat,
// port, trip, species and the reported / retained / released labels, eight at
// most; no publisher prose or photos reach the page; the view opens from the
// landing nav, the masthead and the mobile sheet; each section keeps v1's
// rules and fails alone.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = new Date('2026-10-08T19:00:00Z');

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reports-')), 'reports.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/app/views/Reports.tsx';
      export * from './web/reports.ts';
      export {coastMarkup, isSafeCatchState} from './web/app/CoastMarkup.tsx';
      export {Masthead, MASTHEAD_VIEWS, TAB_VIEWS, ViewNav} from './web/app/Masthead.tsx';
      export {ReportsLink} from './web/app/Mobile.tsx';
      export {NAV} from './web/landing/Landing.tsx';
      export {slo} from './packages/coast/src/counties.ts';
      export {appView} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    // Reports rendering never opens the trip dialog's deferred Chart renderer.
    plugins: [...rendererPlugins, {name: 'reports-trip-renderer', setup: b => {
      b.onResolve({filter: /^\.\/map\/maplibre\.js$/}, args => ({path: args.path, external: true}));
    }}],
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const iso = (ms) => new Date(NOW.getTime() - ms).toISOString();
const trip = (i, species) => ({id: `t${i}`, tripDate: `2026-10-0${8 - (i % 6)}`, boat: `Fixture Boat ${i}`, landing: 'Fixture Landing', anglers: i === 0 ? null : 10 + i,
  tripType: '1/2 Day AM', species, sourceUrl: `https://reports.example/${i}`, retrievedAt: iso(3_600_000)});
const report = (catches) => ({schemaVersion: 1, countyId: 'slo', generatedAt: iso(600_000), catches, catchStatus: 'Synthetic catch status.',
  catchContext: {feedUrl: 'https://feeds.example/c.json', feedGeneratedAt: iso(3_600_000), receivedAt: iso(1_800_000), windowStart: '2026-10-01', windowEnd: '2026-10-08', latestTripDate: '2026-10-08',
    rights: {scope: 'linked-factual-counts', reviewedAt: '2026-10-01', sourceCatalogUrl: 'https://skippercast.example/rights'}}});
const NINE = Array.from({length: 9}, (_, i) => trip(i, i === 0
  ? [{name: 'Lingcod', count: 4, disposition: 'released'}, {name: 'Vermilion Rockfish', count: 30, disposition: 'retained'}, {name: 'Sanddab', count: 12}]
  : [{name: 'Lingcod', count: i}]));

test('acceptance 1: catch cards keep boat, port, trip, species and the reported / retained / released labels; eight at most', async () => {
  const {coastMarkup, CatchCards, slo, render, h} = await load();
  const html = coastMarkup('catchSheet', [{report: report(NINE), county: slo, now: NOW}]);
  assert.equal((html.match(/<article class="catch-trip">/g) ?? []).length, 8, 'eight cards at most');
  assert.match(html, /Showing the latest 8 of 9 available recent reports\./);
  assert.match(html, /<h3>Fixture Boat 0<\/h3>/, 'boat');
  assert.match(html, /Fixture Landing/, 'port');
  assert.match(html, /1\/2 Day AM/, 'trip');
  assert.match(html, /Anglers unreported/);
  assert.match(html, /<dt>Lingcod <small>released<\/small><\/dt><dd>4<\/dd>/);
  assert.match(html, /<dt>Vermilion Rockfish <small>retained<\/small><\/dt><dd>30<\/dd>/);
  assert.match(html, /<dt>Sanddab<\/dt><dd>12<\/dd>/, 'an unmarked count stays reported');
  assert.match(html, /Unmarked counts mean reported; retention was not established\./);
  assert.match(html, /href="https:\/\/reports\.example\/0"/, 'each card links its dated source');
  const host = render(h(CatchCards, {state: {report: report(NINE), county: slo, now: NOW}}));
  assert.match(host, /class="app-coast-markup app-reports-catches" data-coast-theme="tokens" data-renderer="catchSheet"/);
  assert.match(render(h(CatchCards, {state: null})), /show for ports the coast report covers/);
});

test('the catchSheet guard: a non-https link or a non-numeric count is never mounted', async () => {
  const {coastMarkup, isSafeCatchState, CatchCards, slo, render, h} = await load();
  const bad = [{...trip(1, [{name: 'Lingcod', count: 1}]), sourceUrl: 'javascript:alert(1)'}];
  const odd = [{...trip(1, [{name: 'Lingcod', count: '<img src=x>'}])}];
  const str = [{...trip(1, [{name: 'Lingcod', count: 1}]), anglers: '<b>'}];
  for (const catches of [bad, odd, str]) {
    const state = {report: report(catches), county: slo, now: NOW};
    assert.equal(isSafeCatchState(state), false);
    assert.throws(() => coastMarkup('catchSheet', [state]), TypeError);
    assert.match(render(h(CatchCards, {state})), /failed a check and are not shown/);
  }
  assert.equal(isSafeCatchState({report: report(NINE), county: slo, now: NOW}), true);
});

const evidenceFeed = (over = {}) => ({schema_version: 1, region_id: 'morro-bay', generated_at: iso(3_600_000), health: {status: 'ok'}, catch_probability: null, bite_score: null,
  sources: {}, reports: [
    {date: '2026-10-07', boat: 'Fixture Boat A', port: 'Morro Bay', anglers: 12, source_url: 'https://reports.example/a', summary: 'PUBLISHER PROSE', image: 'https://img.example/a.jpg',
      catches: [{species: 'lingcod', label: 'Lingcod', count: 6}, {species: 'lingcod', label: 'Lingcod', count: 2, disposition: 'released'}]},
    {date: '2026-10-06', boat: 'Fixture Boat B', port: 'Morro Bay', ground: 'Fixture Reef', source_url: 'javascript:alert(1)', catches: [{species: 'rockfish', label: 'Rockfish', count: 40}]},
    {date: '2026-10-06', boat: 'Fixture Boat C', port: 'Morro Bay', catches: [{species: 'halibut', label: 'Halibut', count: 3}]},
  ], ...over});

test('recent evidence: v1\'s rule and rows for the target; another region or a scored feed gives none', async () => {
  const {evidenceFrom} = await load();
  const e = evidenceFrom(evidenceFeed(), 'morro-bay', 'reef', NOW.getTime());
  assert.equal(e.confidence, 'Low');
  assert.equal(e.trips, 2);
  assert.deepEqual(e.rows.map(r => [r.boat, r.catches, r.where, r.url]), [
    ['Fixture Boat A', '6 Lingcod reported · 2 Lingcod released', 'Morro Bay landing · fishing location unreported', 'https://reports.example/a'],
    ['Fixture Boat B', '40 Rockfish reported', 'Reported ground: Fixture Reef', null],
  ]);
  assert.equal(evidenceFrom(evidenceFeed(), 'monterey-point-sur', 'reef', NOW.getTime()), null);
  assert.equal(evidenceFrom(evidenceFeed({bite_score: 7}), 'morro-bay', 'reef', NOW.getTime()), null, 'a feed with a score fails v1\'s schema check');
});

test('acceptance 2: the page shows no publisher prose or photos', async () => {
  const {ReportsBody, evidenceFrom, render, h} = await load();
  const data = {
    evidence: evidenceFrom(evidenceFeed(), 'morro-bay', 'reef', NOW.getTime()),
    discussions: {status: 'current', checkedQueries: 3, totalQueries: 4, generatedAt: iso(3_600_000),
      candidates: [{url: 'https://forum.example/t/1', title: 'Fixture thread title', source: 'Fixture forum', published_at: iso(86_400_000), summary: 'PUBLISHER PROSE', image: 'https://img.example/b.jpg'}]},
    watch: {coast: 'Central', checked: true, items: [{name: 'Yellowtail', located: false, links: []}]},
    charters: {audit: '2026-09-21', more: 0, rows: [{label: 'Fixture Rock', ground: 'Fixture Rock', trips: 3, boats: 2, latest: '2026-09-17', sources: []}]},
  };
  const html = render(h(ReportsBody, {data, catches: null}));
  assert.doesNotMatch(html, /PUBLISHER PROSE|img\.example|<img|<picture/);
  for (const text of ['Recent fishing evidence', 'Recent discussions', 'Seasonal watch', 'Where local charters report fishing', 'Fixture thread title', 'Fixture Rock'])
    assert.ok(html.includes(text), text);
  assert.match(html, /not a forecast of your catch/);
  assert.match(html, /Report counts are not catch rates or a popularity ranking\./);
  assert.match(html, /href="\/feed\.xml"/, 'links the coast report feed');
  assert.doesNotMatch(html, /hotspot|probabilit|guarantee/i);
  const catchHTML = (await load()).coastMarkup('catchSheet', [{report: report(NINE), county: (await load()).slo, now: NOW}]);
  assert.doesNotMatch(catchHTML, /<img|<picture/);
});

test('acceptance 3: reachable from the landing nav, the masthead and the mobile sheet', async () => {
  const {NAV, MASTHEAD_VIEWS, TAB_VIEWS, ViewNav, Masthead, ReportsLink, render, h} = await load();
  assert.equal(NAV.find(n => n.label === 'Reports').href, '/map?region=morro-bay&view=reports');
  assert.ok(MASTHEAD_VIEWS.includes('reports'));
  assert.ok(TAB_VIEWS.includes('reports') && !TAB_VIEWS.includes('fleet') && TAB_VIEWS.length === 4, 'Reports is a tab; Fleet is not');
  const tabs = render(h(ViewNav, {icons: true, href: 'https://s.test/map?region=morro-bay'}));
  assert.match(tabs, /data-view="reports"><svg[^>]*data-icon="chart"/);
  assert.doesNotMatch(tabs, /data-view="fleet"/);
  assert.match(render(h(Masthead, {href: 'https://s.test/map?region=morro-bay'})), /data-view="fleet">Fleet</);
  assert.match(render(h(Masthead, {href: 'https://s.test/map?region=morro-bay'})), /href="https:\/\/s\.test\/map\?region=morro-bay&amp;view=reports" data-view="reports">Reports</);
  assert.match(render(h(ReportsLink, {})), /view=reports" class="app-reports-link">Reports</);
});

test('charters and the seasonal watch keep v1\'s rules', async () => {
  const {chartersFrom, watchFrom, CHARTER_LIMIT} = await load();
  const ground = (label, latest, species = ['lingcod'], precision = 'Named landmark vicinity') =>
    ({label, reported_ground: label, precision, reports: [{date: latest, boat: 'B1', species}, {date: '2026-09-01', boat: 'B2', species}]});
  const grounds = [ground('Older', '2026-09-10'), ground('Newer', '2026-09-20'), ground('Broad', '2026-09-25', ['lingcod'], 'Broad regional name'), ground('Halibut only', '2026-09-26', ['halibut']),
    ...Array.from({length: CHARTER_LIMIT}, (_, i) => ground(`Extra ${i}`, '2026-08-01'))];
  const c = chartersFrom({audit_date: '2026-09-21', grounds}, 'reef');
  assert.deepEqual(c.rows.slice(0, 2).map(r => [r.label, r.trips, r.boats, r.latest]), [['Newer', 2, 2, '2026-09-20'], ['Older', 2, 2, '2026-09-10']], 'newest first; broad names and other species left out');
  assert.equal(c.rows.length, CHARTER_LIMIT);
  assert.equal(c.more, 2);
  assert.equal(chartersFrom(null, 'reef'), null);
  const catalog = {regions: [], target_names: {yellowtail: 'Yellowtail', dorado: 'Dorado'}};
  const coast = {id: 'central', name: 'Central', watch: ['yellowtail', 'dorado']};
  const status = (completed) => ({completed_at: completed, regions: {central: {watch: [
    {target: 'yellowtail', status: 'recent-located-reports', evidence: [{url: 'https://news.example/y', date: '2026-10-01', publisher: 'Fixture News'}, {url: 'http://news.example/x', date: '2026-10-02', publisher: 'Plain'}]},
    {target: 'dorado', status: 'watch-only', evidence: []}]}}});
  const fresh = watchFrom(catalog, coast, status(iso(3_600_000)), NOW.getTime());
  assert.deepEqual(fresh.items.map(w => [w.name, w.located, w.links.length]), [['Yellowtail', true, 1], ['Dorado', false, 0]], 'https links only');
  const stale = watchFrom(catalog, coast, status(iso(72 * 3_600_000)), NOW.getTime());
  assert.deepEqual(stale.items.map(w => w.located), [false, false], 'a stale status lists the watch without located reports');
  assert.deepEqual(watchFrom(catalog, coast, null, NOW.getTime()).items.map(w => w.name), ['Yellowtail', 'Dorado']);
});

test('loadReports: each failed source leaves only its own section unavailable', async () => {
  const {loadReports, DiscussionsSection, EvidenceSection, render, h} = await load();
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    const fetchFn = async (url) => String(url).includes('/feeds/data/regions/morro-bay/') ? new Response(JSON.stringify(evidenceFeed())) : new Response('no', {status: 503});
    const data = await loadReports({region: 'morro-bay', species: 'reef', charters: 'data/charter-grounds.json', now: NOW.getTime()}, fetchFn);
    assert.equal(data.discussions.status, 'unavailable');
    assert.equal(data.evidence.trips, 2);
    assert.equal(data.watch, null);
    assert.equal(data.charters, null);
    assert.match(render(h(DiscussionsSection, {discussions: data.discussions})), /Recent discussion search is unavailable/);
    assert.match(render(h(EvidenceSection, {evidence: null})), /No catch score is assumed/);
  } finally { globalThis.fetch = original; }
});

// Attribution goes through the public mapping, not hand-injected renderer fields.
test('charter source links retain matched public trips, safe URLs and escaped labels', async () => {
  const {chartersFrom, ChartersSection, render, h} = await load();
  const valid = {date: '2026-09-17', boat: '<b>Fixture & boat</b>', species: ['lingcod'], source_url: 'https://reports.example/trip?a=1&b=2'};
  const invalid = [undefined, 'not a URL', 'http://reports.example/trip', 'javascript:alert(1)', 'https://user:secret@reports.example/trip'];
  const reports = [valid, ...invalid.map((source_url, i) => ({date: '2026-09-16', boat: `Other ${i}`, species: ['lingcod'], source_url, boat_source_url: 'https://boats.example/not-a-trip'})),
    {date: '2026-09-20', boat: 'Non-target boat', species: ['halibut'], source_url: 'https://reports.example/non-target'}];
  const ground = {label: '<img src=x> & Reef', reported_ground: '<script>ground</script>', precision: 'Named landmark vicinity', reports};
  const data = chartersFrom({audit_date: '2026-09-21', grounds: [ground, {...ground, label: 'Broad', precision: 'Broad regional name'}]}, 'reef');
  assert.equal(data.rows.length, 1);
  const row = data.rows[0];
  assert.deepEqual([row.trips, row.boats, row.latest], [6, 6, '2026-09-17']);
  assert.deepEqual(row.sources, [{date: valid.date, boat: valid.boat, url: valid.source_url}]);
  const html = render(h(ChartersSection, {charters: data}));
  assert.match(html, /6 reported trips · 6 boats · latest report Sep 17, 2026/);
  assert.match(html, /href="https:\/\/reports.example\/trip\?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">Sep 17, 2026 · &lt;b>Fixture &amp; boat&lt;\/b><\/a>/);
  assert.match(html, /&lt;img src=x> &amp; Reef/);
  assert.match(html, /&lt;script>ground&lt;\/script>/);
  assert.doesNotMatch(html, /<img|<script|Non-target|non-target|boats.example|javascript:|user:secret/);
  const absent = chartersFrom({audit_date: '2026-09-21', grounds: [{...ground, reports: reports.slice(1, 6)}]}, 'reef');
  assert.deepEqual(absent.rows[0].sources, []);
  const absentHTML = render(h(ChartersSection, {charters: absent}));
  assert.doesNotMatch(absentHTML, /<a|Source reports:/);
  assert.match(absentHTML, /5 reported trips · 5 boats · latest report Sep 16, 2026/);
});
