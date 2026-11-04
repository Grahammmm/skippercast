// SC1322-09: the status page shows the Morro Bay coast feeds' own source clocks, against the limits the Worker uses.
import assert from 'node:assert/strict';
import test from 'node:test';
import health from '../catalog/feed-health.json' with {type: 'json'};
import {coastRows, coverageOf, renderCoverage, renderRows, statusRows} from '../dist/status-page.js';
import {SOURCE_NAMES} from '../dist/status-names.js';

globalThis.REGIONS ??= {};
globalThis.DEPLOYMENT ??= {allowed_origins: ['https://skippercast.com']};
const {FEEDS, FEED_SOURCES} = await import('../server/coast-data.ts');
const NOW = Date.parse('2026-11-01T20:30:00Z');
const HOUR = 3_600_000;
const ago = h => new Date(NOW - h * HOUR).toISOString();
const leaky = {url: 'https://internal.example/wms?token=abc', error: 'TypeError: fetch failed at /srv/work', runId: 'run-9876'};
const fresh = () => ({
  ocean: {schemaVersion: 1, generatedAt: ago(0.5), sources: [
    {id: 'noaa-wcofs', status: 'ok', fetchedAt: ago(1)}, {id: 'noaa-hfr-thredds', status: 'ok', fetchedAt: ago(1)},
    {id: 'noaa-goes-nowcoast', status: 'ok', fetchedAt: ago(0.5)}]},
  nearshore: {schema_version: 1, generated_at: ago(0.5), sources: [{id: 'cdip-SL345', outcome: 'ok', fetchedAt: ago(1)}]},
  'water-quality': {schemaVersion: 1, generatedAt: ago(0.5), sources: [{id: 'slo-beach-water-quality', outcome: 'ok', fetchedAt: ago(2)}]},
  history: {schemaVersion: 1, generatedAt: ago(5 * 24)},
});
const NAMES = ['noaa-wcofs', 'noaa-goes-nowcoast', 'cdip-mop', 'slo-beach-water-quality', 'ndbc-history'].map(id => SOURCE_NAMES[id]);
const byName = rows => Object.fromEntries(rows.map(r => [r.name, r]));

test('all four feeds fresh: five ok rows in their own group; history 5 days old is inside its 192 h', () => {
  const rows = coastRows(fresh(), NOW);
  assert.deepEqual(rows.map(r => r.name), NAMES, 'one row per source, no row for noaa-hfr-thredds');
  for (const r of rows) {
    assert.equal(r.state, 'ok', `${r.name}: ${r.note}`);
    assert.equal(r.group, 'Morro Bay coast feeds');
  }
  assert.equal(byName(rows)[SOURCE_NAMES['ndbc-history']].expectedHours, 192);
  assert.equal(byName(rows)[SOURCE_NAMES['noaa-wcofs']].expectedHours, 3);
  assert.equal(Date.parse(byName(rows)[SOURCE_NAMES['slo-beach-water-quality']].lastSuccess), Date.parse(ago(2)));
  const all = statusRows({conditions: null, data: null, index: null, regions: {}, coast: fresh()}, NOW);
  assert.deepEqual(all.filter(r => r.group === 'Morro Bay coast feeds').map(r => r.name), NAMES, 'statusRows carries the group');
  assert.equal(statusRows({conditions: null, data: null, index: null, regions: {}}, NOW).filter(r => r.group === 'Morro Bay coast feeds').length, 0,
    'no coast argument, no coast rows');
});

test('history 9 days old is overdue; a source past 3 h is overdue', () => {
  const feeds = fresh();
  feeds.history.generatedAt = ago(9 * 24);
  feeds['water-quality'].sources[0].fetchedAt = ago(3.5);
  const rows = byName(coastRows(feeds, NOW));
  assert.equal(rows[SOURCE_NAMES['ndbc-history']].state, 'late');
  assert.equal(rows[SOURCE_NAMES['slo-beach-water-quality']].state, 'late');
  assert.equal(rows[SOURCE_NAMES['noaa-wcofs']].state, 'ok');
});

test('a source the feed reports as error is degraded; its neighbour in the same feed is unaffected', () => {
  const feeds = fresh();
  feeds.ocean.sources[0] = {id: 'noaa-wcofs', status: 'error', fetchedAt: ago(1), ...leaky};
  feeds['water-quality'].sources[0].outcome = 'pending';
  const rows = byName(coastRows(feeds, NOW));
  assert.equal(rows[SOURCE_NAMES['noaa-wcofs']].state, 'degraded');
  assert.equal(rows[SOURCE_NAMES['noaa-wcofs']].note, 'error');
  assert.equal(rows[SOURCE_NAMES['noaa-goes-nowcoast']].state, 'ok');
  assert.equal(rows[SOURCE_NAMES['slo-beach-water-quality']].state, 'degraded');
  assert.equal(rows[SOURCE_NAMES['slo-beach-water-quality']].note, 'pending');
});

test('several CDIP sites roll up into one CDIP MOP row, judged by the worst', () => {
  const feeds = fresh();
  feeds.nearshore.sources = [{id: 'cdip-SL345', outcome: 'ok', fetchedAt: ago(1)}, {id: 'cdip-SL400', outcome: 'ok', fetchedAt: ago(4)}];
  let rows = coastRows(feeds, NOW).filter(r => r.name === SOURCE_NAMES['cdip-mop']);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, 'late');
  assert.equal(rows[0].note, '1 of 2 overdue');
  assert.equal(Date.parse(rows[0].lastSuccess), Date.parse(ago(4)));
  feeds.nearshore.sources[1] = {id: 'cdip-SL400', outcome: 'error', fetchedAt: ago(1)};
  rows = coastRows(feeds, NOW).filter(r => r.name === SOURCE_NAMES['cdip-mop']);
  assert.equal(rows[0].state, 'degraded');
  assert.equal(rows[0].note, '1 of 2 not current (error)');
});

test('a feed that failed to load makes its rows unreadable only; a missing source says so', () => {
  const feeds = fresh();
  feeds.ocean = null;
  feeds['water-quality'].sources = [{id: 'nws-alerts', outcome: 'ok', fetchedAt: ago(1)}];
  const rows = byName(coastRows(feeds, NOW));
  for (const id of ['noaa-wcofs', 'noaa-goes-nowcoast']) {
    assert.equal(rows[SOURCE_NAMES[id]].state, 'unavailable', id);
    assert.equal(rows[SOURCE_NAMES[id]].lastSuccess, null, id);
  }
  assert.equal(rows[SOURCE_NAMES['cdip-mop']].state, 'ok');
  assert.equal(rows[SOURCE_NAMES['ndbc-history']].state, 'ok');
  assert.equal(rows[SOURCE_NAMES['slo-beach-water-quality']].state, 'unavailable');
  assert.equal(rows[SOURCE_NAMES['slo-beach-water-quality']].note, 'not in the feed');
  const gone = coastRows({ocean: null, nearshore: 'text', 'water-quality': [], history: {}}, NOW);
  for (const r of gone) assert.equal(r.state, 'unavailable', r.name);
});

test('a source time 20 minutes in the future is unreadable, not fresh', () => {
  const feeds = fresh();
  feeds.ocean.sources[2].fetchedAt = ago(-20 / 60);
  feeds.history.generatedAt = ago(-20 / 60);
  const rows = byName(coastRows(feeds, NOW));
  for (const id of ['noaa-goes-nowcoast', 'ndbc-history']) {
    assert.equal(rows[SOURCE_NAMES[id]].state, 'unavailable', id);
    assert.match(rows[SOURCE_NAMES[id]].note, /time is in the future/, id);
  }
});

test('the rendered rows carry no request URL, error text or run id from the coast feeds', () => {
  const feeds = fresh();
  feeds.ocean.sources[0] = {id: 'noaa-wcofs', status: 'TypeError: fetch failed at https://internal.example/x', fetchedAt: ago(1), ...leaky};
  feeds.nearshore = {...feeds.nearshore, ...leaky, sources: [{id: 'cdip-SL345', outcome: 'error', fetchedAt: ago(1), ...leaky},
    {id: 'cdip-SL400', outcome: 'https://internal.example/run-9876', fetchedAt: ago(1)}]};
  feeds.history = {...feeds.history, ...leaky};
  const rows = coastRows(feeds, NOW);
  assert.equal(byName(rows)[SOURCE_NAMES['noaa-wcofs']].note, 'unknown');
  const html = renderRows(rows) + renderCoverage();
  for (const leak of ['http', 'internal.example', 'token=', 'TypeError', '/srv/work', 'run-9876']) assert.ok(!html.includes(leak), leak);
});

test('the five coast sources are watched; the GEFS rows stay unwatched', () => {
  for (const id of ['noaa-wcofs', 'noaa-goes-nowcoast', 'cdip-mop', 'slo-beach-water-quality', 'ndbc-history']) assert.equal(coverageOf(id), 'watched', id);
  for (const id of ['noaa-gefs-members', 'noaa-gefs-wave-prob']) assert.equal(coverageOf(id), 'scheduled-unwatched', id);
  const html = renderCoverage();
  for (const id of ['noaa-wcofs', 'cdip-mop', 'ndbc-history']) assert.ok(!html.includes(SOURCE_NAMES[id]), id);
  assert.ok(html.includes(SOURCE_NAMES['noaa-gefs-wave-prob']));
});

test('one set of limits: the Worker reads its coast age limits and keys from catalog/feed-health.json', () => {
  assert.deepEqual(Object.keys(health.coast).sort(), ['history', 'nearshore', 'ocean', 'water-quality']);
  const expected = {ocean: 3, nearshore: 3, 'water-quality': 3, history: 192};   // no limit value changes
  for (const [name, config] of Object.entries(health.coast)) {
    assert.equal(config.max_age_hours, expected[name], name);
    assert.equal(FEEDS[name].maxAge, config.max_age_hours * HOUR, name);
    assert.equal(FEEDS[name].key, config.path, name);
    // The page's sources are the Worker's FEED_SOURCES, less noaa-hfr-thredds (out of scope here).
    assert.deepEqual(config.sources, FEED_SOURCES[name].filter(id => id !== 'noaa-hfr-thredds'), name);
  }
  assert.ok(FEED_SOURCES.ocean.includes('noaa-hfr-thredds'));
});
