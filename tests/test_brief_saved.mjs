// SC-PERF-INSTANT-1: the last brief that loaded is kept on the device and shown at once on the next visit,
// then replaced by the new read; a failed read keeps it and says so; an old one is amber; no store is no change.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const ID = 'monterey-point-sur', HOUR = 3_600_000;
globalThis.document = {visibilityState: 'hidden', addEventListener: () => {}};

let href, n = 0;
async function load() {
  if (!href) {
    const out = join(await mkdtemp(join(tmpdir(), 'brief-saved-')), 'brief.mjs');
    await build({
      stdin: {resolveDir: ROOT, loader: 'ts', contents: `export * from './web/brief/Brief.tsx'; export * from './web/brief/saved-brief.ts';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
      plugins: rendererPlugins,
    });
    href = pathToFileURL(out).href;
  }
  return import(`${href}?${++n}`); // a fresh module, as a fresh page load
}
test.after(() => { delete globalThis.document; });

const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => { m.set(k, String(v)); }, m}; };
const feedServer = ({daily = true, live = true} = {}) => async path => {
  path = String(path);
  if (path.startsWith('/api/daily')) return new Response('', {status: 404});
  const isDaily = path.startsWith('/feeds/data/'), id = decodeURIComponent(path.split('/')[4]);
  if (!(isDaily ? daily : live)) return new Response('', {status: 503});
  const conditions = {schema_version: 1, region_id: id, sources: {diablo: {id: 'diablo', name: 'NDBC 46042', kind: 'observation', url: '', checked_at: '2026-10-08T21:00:00Z', status: 'ok'}}};
  return new Response(JSON.stringify(isDaily ? {...montereyDaily, region_id: id} : conditions), {status: 200});
};

test('first visit: nothing saved, nothing shown, the first good read is saved', async () => {
  const m = await load(), store = memory();
  m.enableSavedBrief(store);
  assert.equal(m.showSavedBrief(ID), false);
  assert.equal(m.savedBrief.value, null);
  assert.equal(m.needsDailyLoad(ID), true);
  await m.loadDailyFeed(ID, feedServer());
  assert.equal(m.savedBrief.value, null, 'a live read shows no saved line');
  const saved = JSON.parse(store.m.get(m.SAVED_BRIEF_KEY));
  assert.equal(saved.region, ID);
  assert.equal(typeof saved.daily.at, 'number');
});

test('second visit: the saved brief is on screen before any read, then the new read replaces it', async () => {
  const first = await load(), store = memory();
  first.enableSavedBrief(store);
  await first.loadDailyFeed(ID, feedServer());
  const m = await load();
  m.enableSavedBrief(store);
  assert.equal(m.showSavedBrief(ID), true);
  assert.equal(m.dailyFeed.value.region_id, ID, 'shown with no network');
  assert.equal(m.savedBrief.value.state, 'updating');
  assert.equal(m.needsDailyLoad(ID), true, 'the new read is still made');
  await m.loadDailyFeed(ID, feedServer());
  assert.equal(m.savedBrief.value, null, 'replaced by the live read');
});

test('failed refresh: the saved brief stays and says the update failed', async () => {
  const first = await load(), store = memory();
  first.enableSavedBrief(store);
  await first.loadDailyFeed(ID, feedServer());
  const m = await load();
  m.enableSavedBrief(store);
  m.showSavedBrief(ID);
  const feed = m.dailyFeed.value;
  await m.loadDailyFeed(ID, feedServer({daily: false, live: false}));
  assert.equal(m.dailyFeed.value, feed, 'the saved feed is still shown');
  assert.equal(m.savedBrief.value.state, 'failed');
  assert.match(m.savedLine(Date.now(), Date.now(), 'failed', false, 'UTC').text, /Update failed/);
});

test('stale saved brief: amber past the freshness limit, and never calmer than live', async () => {
  const m = await load(), now = Date.now();
  const fresh = m.savedLine(now - HOUR, now, 'updating', false, 'UTC');
  const old = m.savedLine(now - (m.RUN_STALE_MS ?? 18 * HOUR) - HOUR, now, 'failed', false, 'UTC');
  assert.equal(fresh.amber, false);
  assert.equal(old.amber, true);
  assert.equal(m.savedLine(now - HOUR, now, 'updating', true, 'UTC').amber, true, 'a stale reading on screen makes it amber');
  assert.equal(m.savedLine(now + 3 * HOUR, now, 'updating', false, 'UTC').amber, true, 'a clock ahead of now is never fresh');
  assert.match(fresh.text, /^Last updated /);
});

test('stored data: validated on read, only the displayed parts and no personal data', async () => {
  const m = await load(), store = memory(), now = Date.now();
  const daily = {at: now - HOUR, data: {...montereyDaily, region_id: ID}};
  const forecast = {at: now - HOUR, data: {region: ID, retrieved: now, point: {lat: 1, lon: 2}, models: {}, extra: {trip: 'x'}}};
  assert.equal(m.writeSaved(store, ID, daily, forecast), true);
  const raw = store.m.get(m.SAVED_BRIEF_KEY);
  assert.ok(!raw.includes('"extra"'), 'only the forecast parts the brief reads are kept');
  assert.ok(m.readSaved(store, ID, now));
  assert.equal(m.readSaved(store, 'other-region', now), null);
  store.setItem(m.SAVED_BRIEF_KEY, '{not json');
  assert.equal(m.readSaved(store, ID, now), null);
  store.setItem(m.SAVED_BRIEF_KEY, JSON.stringify({v: 1, region: ID, daily: {at: now + 99 * HOUR, data: daily.data}, forecast: null}));
  assert.equal(m.readSaved(store, ID, now), null, 'a time far ahead is not trusted');
});

test('storage unavailable: no store, a throwing store and a full store change nothing', async () => {
  for (const store of [null, {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); }}]) {
    const m = await load();
    m.enableSavedBrief(store);
    assert.equal(m.showSavedBrief(ID), false);
    const feed = await m.loadDailyFeed(ID, feedServer());
    assert.equal(feed.region_id, ID, 'the brief loads as before');
    assert.equal(m.savedBrief.value, null);
  }
  const m = await load(); // never enabled: nothing is read or written
  assert.equal(m.showSavedBrief(ID), false);
});
