// SC-LAUNCH-5: the public status page shows the watchdog's own per-source state.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {shellFor} from '../server/routes/assets.ts';
import {coverageGroups, coverageOf, DOCUMENTED_EXTRA, renderCoverage, renderRows, statusRows, SOURCE_COVERAGE} from '../dist/status-page.js';
import {SOURCE_NAMES} from '../dist/status-names.js';

const NOW = Date.parse('2026-11-01T20:30:00Z');
const hoursAgo = h => new Date(NOW - h * 3_600_000).toISOString().replace('.000', '');
const src = (id, kind, extra = {}) => ({id, name: `Name of ${id}`, kind, status: 'ok', max_age_hours: 36, last_success_at: hoursAgo(2), checked_at: hoursAgo(2),
  requests: [{url: 'https://internal.example/secret?token=abc', http_status: 200}], ...extra});
const regionFeed = (ago, sources = {a: src('a', 'observation', {max_age_hours: 2})}) => ({published_at: hoursAgo(ago), sources});
const index = {regions: [{id: 'morro-bay', name: 'Morro Bay'}]};
const fresh = () => ({
  conditions: regionFeed(0.3),
  index,
  regions: {'morro-bay': regionFeed(0.3)},
  data: {published_at: hoursAgo(2), schedule: {max_delay_hours: 36}, run_id: 'r-123', sources: {
    sst: src('sst', 'grid', {name: 'NOAA SST'}), tides: src('tides', 'prediction', {name: 'NOAA tide predictions'}),
    'mpa-a': src('mpa-a', 'page-watch'), 'mpa-b': src('mpa-b', 'page-watch'),
    'catches-1': src('catches-1', 'charter-reports', {reused: true, last_success_at: hoursAgo(90)}), 'catches-2': src('catches-2', 'charter-reports'),
  }},
});
const byName = rows => Object.fromEntries(rows.map(r => [r.name, r]));

test('a healthy set of feeds is inside its interval everywhere', () => {
  const rows = statusRows(fresh(), NOW);
  assert.equal(rows.length, 7);
  for (const r of rows) assert.equal(r.state, 'ok', `${r.name}: ${r.note}`);
  const live = byName(rows)['Live conditions feed'];
  assert.equal(live.expectedHours, 3);
  assert.equal(Date.parse(live.lastSuccess), Date.parse(hoursAgo(0.3)));
  assert.equal(byName(rows)['Landing reports'].note, '2 sources', 'a reused (cached older day) report is not judged by its age');
});

test('a constructed stale feed renders as stale, and so does a source the provider stopped updating', () => {
  const feeds = fresh();
  feeds.conditions = regionFeed(5);                         // past the 3 h limit of catalog/feed-health.json
  feeds.regions['morro-bay'] = regionFeed(5);
  feeds.data.sources.sst = src('sst', 'grid', {name: 'NOAA SST', status: 'stale', issue: 'ValueError: Report page/date not recognized'});
  feeds.data.sources.tides = src('tides', 'prediction', {name: 'NOAA tide predictions', last_success_at: hoursAgo(50)}); // ok status, but older than its 36 h
  feeds.data.sources['mpa-b'] = {id: 'mpa-b', kind: 'page-watch', status: 'failed', max_age_hours: 36};
  const rows = byName(statusRows(feeds, NOW));
  assert.equal(rows['Live conditions feed'].state, 'late');
  assert.equal(rows['Buoys: Morro Bay'].state, 'late');
  assert.equal(rows['NOAA SST'].state, 'degraded');
  assert.equal(rows['NOAA tide predictions'].state, 'late');
  assert.equal(rows['Fishing-rule and protected-area pages'].state, 'degraded');
  assert.match(rows['Fishing-rule and protected-area pages'].note, /1 of 2 not current \(failed\)/);
  const html = renderRows(Object.values(rows));
  assert.match(html, /class="status-late"[^>]*><th scope="row">Live conditions feed/);
  assert.match(html, /Overdue/);
  assert.match(html, /Provider data not current/);
});

test('a feed or region that cannot be read is shown as unreadable, never as fresh', () => {
  const feeds = fresh();
  feeds.conditions = null; feeds.data = null; feeds.regions['morro-bay'] = null;
  const rows = statusRows(feeds, NOW);
  assert.ok(rows.length >= 3);
  for (const r of rows) assert.equal(r.state, 'unavailable', r.name);
});

test('a degraded buoy inside a region feed marks the region, not just the feed age', () => {
  const feeds = fresh();
  feeds.regions['morro-bay'] = regionFeed(0.3, {a: src('a', 'observation'), b: src('b', 'observation', {status: 'retained'})});
  const row = byName(statusRows(feeds, NOW))['Buoys: Morro Bay'];
  assert.equal(row.state, 'degraded');
  assert.match(row.note, /1 of 2/);
});

test('the page never carries request URLs, error text, run ids or hosts from the feeds', () => {
  const feeds = fresh();
  feeds.data.sources.sst = src('sst', 'grid', {status: 'failed', issue: 'ValueError: internal detail at /' + 'srv/work'});
  const html = renderRows(statusRows(feeds, NOW)) + renderCoverage();
  for (const leak of ['internal.example', 'token=', 'ValueError', '/' + 'srv/work', 'r-123', 'https://', 'http_status']) assert.ok(!html.includes(leak), leak);
});

test('every source in catalog/sources.json is either shown, or named on the page as not shown', () => {
  const catalog = JSON.parse(readFileSync(new URL('../catalog/sources.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(SOURCE_NAMES).sort(), catalog.sources.map(s => s.id).sort(), 'dist/status-names.js is regenerated from the catalog');
  const renamed = {'noaa-gfs': 'NOAA wind forecast', 'ecmwf-ifs': 'European wind forecast', 'noaa-gfs-wave': 'NOAA wave forecast', 'ecmwf-wam': 'European wave forecast'};
  for (const s of catalog.sources) assert.equal(SOURCE_NAMES[s.id], renamed[s.id] || s.name, s.id); // model codes are method names, not page copy
  for (const id of Object.keys(SOURCE_COVERAGE)) assert.ok(SOURCE_NAMES[id], `${id} is not in the catalog`);
  const groups = coverageGroups();
  assert.equal(Object.values(groups).flat().length, catalog.sources.length + Object.keys(DOCUMENTED_EXTRA).length);
  assert.equal(coverageOf('cdip-mop'), 'scheduled-unwatched');
  const html = renderCoverage();
  assert.match(html, /freshness check does not watch it yet/);
  assert.match(html, /CDIP MOP/);
  assert.ok(!html.includes('NDBC station observations'), 'a watched source is not listed as unwatched');
});

test('/status serves the status page', () => {
  assert.equal(shellFor('/status', new URLSearchParams()), '/status.html');
  const page = readFileSync(new URL('../dist/status.html', import.meta.url), 'utf8');
  for (const id of ['status-rows', 'status-coverage', 'status-checked']) assert.ok(page.includes(`id="${id}"`), id);
});

test('a backup station standing in for its primary is degraded service, not healthy (as degraded_sources())', () => {
  const feeds = fresh();
  feeds.regions['morro-bay'] = regionFeed(0.3, {a: src('a', 'observation', {max_age_hours: 2, fallback_for: 'primary', station: '46028'})});
  feeds.data.sources['buoy-b'] = src('buoy-b', 'observation', {name: 'Backup buoy', fallback_for: 'buoy-a'});
  const rows = byName(statusRows(feeds, NOW));
  assert.equal(rows['Buoys: Morro Bay'].state, 'degraded');
  assert.match(rows['Buoys: Morro Bay'].note, /1 of 1 buoy readings not current \(backup station\)/);
  assert.equal(rows['Backup buoy'].state, 'degraded');
  assert.match(rows['Backup buoy'].note, /backup station/);
  assert.match(renderRows(Object.values(rows)), /class="status-degraded"[^>]*><th scope="row">Buoys: Morro Bay/);
});

test('a rollup shows its worst member: one overdue page beside a fresh one is overdue', () => {
  const feeds = fresh();
  feeds.data.sources['mpa-a'] = src('mpa-a', 'page-watch', {last_success_at: hoursAgo(50)}); // status ok, past its 36 h
  const rows = byName(statusRows(feeds, NOW));
  const pages = rows['Fishing-rule and protected-area pages'];
  assert.equal(pages.state, 'late');
  assert.equal(pages.note, '1 of 2 overdue');
  assert.equal(Date.parse(pages.lastSuccess), Date.parse(hoursAgo(50)));
  assert.equal(rows['Landing reports'].state, 'ok', 'a reused older landing day is still exempt from its age');
  assert.match(renderRows(Object.values(rows)), /class="status-late"[^>]*><th scope="row">Fishing-rule and protected-area pages<\/th><td>.*Overdue · 1 of 2 overdue/);
});

test('a publication or success time more than 10 minutes ahead is unreadable, as the checker says', () => {
  const feeds = fresh();
  feeds.conditions = {published_at: hoursAgo(-48)};
  feeds.regions['morro-bay'] = regionFeed(-48);
  feeds.data.sources.tides = src('tides', 'prediction', {name: 'NOAA tide predictions', last_success_at: hoursAgo(-48)});
  let rows = byName(statusRows(feeds, NOW));
  for (const name of ['Live conditions feed', 'Buoys: Morro Bay', 'NOAA tide predictions']) {
    assert.equal(rows[name].state, 'unavailable', name);
    assert.match(rows[name].note, /in the future/, name);
  }
  const html = renderRows(Object.values(rows));
  assert.match(html, /class="status-unavailable"[^>]*><th scope="row">Live conditions feed<\/th><td><time[^>]*>[^<]*<\/time><\/td>.*Cannot be read · time is in the future/);
  feeds.conditions = {published_at: hoursAgo(-5 / 60)};   // 5 min ahead: inside the tolerance
  rows = byName(statusRows(feeds, NOW));
  assert.equal(rows['Live conditions feed'].state, 'ok');
  assert.equal(rows['Live conditions feed'].ageHours, 0);
});

test('the harbor page is shown on its own row and counted as watched', () => {
  const feeds = fresh();
  feeds.data.sources.harbor = src('harbor', 'page-watch', {name: 'Morro Bay harbor information', last_success_at: hoursAgo(50)});
  const rows = byName(statusRows(feeds, NOW));
  assert.equal(rows['Morro Bay harbor information'].state, 'late');
  assert.equal(rows['Fishing-rule and protected-area pages'].state, 'ok', 'the harbor page is not a fishing-rule page');
  assert.equal(rows['Fishing-rule and protected-area pages'].note, '2 sources');
  assert.equal(coverageOf('harbor-authority'), 'watched');
  assert.ok(!renderCoverage().includes(SOURCE_NAMES['harbor-authority']), 'a watched source is not listed as not shown');
});

test('a documented service without a catalog entry (NOAA ENC charts) is named on the page', () => {
  const docs = readFileSync(new URL('../docs/data-sources.md', import.meta.url), 'utf8');
  assert.match(docs, /NOAA's ENC display service/);
  assert.equal(DOCUMENTED_EXTRA['noaa-enc-display'].coverage, 'browser-direct');
  assert.match(renderCoverage(), /Fetched by your browser from the provider; SkipperCast publishes nothing<\/h3>\n<ul>.*NOAA ENC display service/);
});

test('when the region list cannot be read, the page says regional coverage is missing', () => {
  const feeds = fresh();
  feeds.index = null; feeds.regions = {};
  const rows = statusRows(feeds, NOW);
  const regional = byName(rows)['Regional buoy feeds'];
  assert.equal(regional.state, 'unavailable');
  assert.match(regional.note, /region list could not be read/);
  assert.ok(!rows.some(r => r.name.startsWith('Buoys:')));
  assert.match(renderRows(rows), /Regional buoy feeds<\/th><td>none<\/td><td>3\.0 h<\/td><td>Cannot be read · the region list could not be read/);
});
