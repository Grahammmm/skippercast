// SP-17-v1 / SP1707-BOAT-HANDLE-CASE: full real Worker/page, synthetic in-memory DB.
import './fixtures/sp1707_boat_handle_case/offline-preload.mjs';
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const globals = ['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID', 'ADVISOR_ASSETS', 'caches'];
const previous = globals.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
// Same real manifest shapes as the unchanged advisor page suite; no feeds are needed.
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = '0123456789';
globalThis.ADVISOR_ASSETS = {};
delete globalThis.caches;
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
if (sqliteUnavailable) throw new Error(sqliteUnavailable); // Missing runtime is failure, never skip.
const {pagesDeps} = await import('../server/routes/advisor.ts');
const oldDeps = {...pagesDeps};
const NOW = Date.parse('2026-09-28T19:00:00Z');
pagesDeps.clock = () => NOW;
pagesDeps.feeds = async () => { throw new Error('SP1707_UNEXPECTED_FEED'); };
const {default: worker} = await import('../server/index.ts');
const fixture = read('./fixtures/sp1707_boat_handle_case/boat.json');
const blockedBinding = new Proxy({}, {get() { throw new Error('SP1707_LIVE_BINDING'); }});

after(() => {
  assert.deepEqual(globalThis.SP1707_OFFLINE.attempts, [], 'no external or model I/O');
  for (const key of Object.keys(pagesDeps)) delete pagesDeps[key];
  Object.assign(pagesDeps, oldDeps);
  for (const [key, descriptor] of previous) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

function seed(overrides = {}, details = false) {
  assert.equal(globalThis.fetch.sp1707Offline, true, 'pre-import network sentinel installed');
  const {sql, db} = advisorDatabase(); // Existing adapter applies every real committed migration.
  const row = {...fixture, ...overrides};
  const fields = ['id', 'slug', 'name', 'landing', 'port', 'region', 'instagram', 'booking_url', 'phone_public', 'status', 'verified_at', 'created_at', 'updated_at'];
  sql.prepare(`INSERT INTO advisor_boats (${fields.join(',')}) VALUES (${fields.map(() => '?').join(',')})`).run(...fields.map(key => row[key]));
  if (details) {
    sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run('sp1707-report', row.id, row.region, row.port, '2026-09-27', 'full-day', 22,
      JSON.stringify([{label: 'lingcod', species_key: 'lingcod', kept: 12, released: 2}]), 'count-text', 'published', 1, 2, row.created_at, row.created_at, row.updated_at);
    for (const [id, state] of [['sp1707-approved', 'approved'], ['sp1707-posted', 'posted'], ['sp1707-private', 'private']]) {
      sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, 'sp1707-contact', row.id, 'image', 'image/jpeg', 100, `advisor/media/sp1707/${id}.jpg`, 'synthetic', 1, state, 'Example <credit>', row.created_at);
    }
  }
  return {sql, db};
}
async function page(overrides = {}, {details = false, language = 'en', enabled = true} = {}) {
  const {sql, db} = seed(overrides, details);
  try {
    // No ambient credentials or persistent bindings: only this synthetic D1 is usable.
    const env = {DB: db, TEXT_ADVISOR_ENABLED: String(enabled), FLEET_ENABLED: 'false',
      AI: blockedBinding, ADVISOR_MEDIA: blockedBinding, ADVISOR_QUEUE: blockedBinding,
      ASSETS: blockedBinding, ANALYTICS: blockedBinding};
    const response = await worker.fetch(new Request(`https://skippercast.com/boats/${fixture.slug}${language === 'es' ? '?lang=es' : ''}`), env);
    return {status: response.status, headers: response.headers, html: await response.text()};
  } finally { sql.close(); }
}
const anchors = html => [...html.matchAll(/<a href="https:\/\/www\.instagram\.com\/([^"/]+)\/" rel="noopener nofollow">([^<]+)<\/a>/g)];
function contact(result, handle) {
  assert.equal(result.status, 200);
  const links = anchors(result.html);
  assert.equal(links.length, 1, 'exactly one Instagram anchor');
  assert.equal(links[0][1], handle, 'identity preserved in URL');
  assert.ok(links[0][2].endsWith(`@${handle}`), 'identity preserved in visible label');
  assert.match(result.html, /<section class="adv-card" aria-labelledby="book-title">/);
}

test('A1 primary regression: verified mixed-case-only contact renders', async () => {
  const result = await page();
  assert.equal(result.status, 200);
  assert.equal(anchors(result.html).length, 1, 'SP1707_A1_MIXED_CASE_ANCHOR: stored mixed-case handle must render');
  contact(result, fixture.instagram);
  assert.match(result.html, /^<!doctype html>/);
  assert.match(result.html, /adv-badge-verified/);
});

test('CONTROL healthy lowercase-only contact renders', async () => {
  contact(await page({instagram: 'seaexample_fishing'}), 'seaexample_fishing');
});

test('A2 ASCII grammar and length boundaries preserve identity and withhold invalid handles', async t => {
  assert.equal(fixture.valid_handles.at(-1).length, 30);
  assert.equal(fixture.invalid_handles[2].length, 31);
  for (const [index, handle] of fixture.valid_handles.entries()) {
    await t.test(`valid synthetic handle ${index}`, async () => {
      for (const language of ['en', 'es']) contact(await page({instagram: handle}, {language}), handle);
    });
  }
  for (const [index, handle] of fixture.invalid_handles.entries()) {
    await t.test(`invalid synthetic handle ${index}`, async () => {
      const result = await page({instagram: handle});
      assert.equal(result.status, 200);
      assert.equal(anchors(result.html).length, 0);
      assert.ok(!result.html.includes('instagram.com'));
      assert.ok(!result.html.includes('id="book-title"'), 'no empty contact section');
      assert.ok(!result.html.includes('<b>example</b>'));
    });
  }
});

test('A3 pending, rejected and disabled routes do not grant contact permission', async () => {
  const hidden = {instagram: fixture.instagram, booking_url: 'https://example.com/book', phone_public: '+18055550188'};
  const pending = await page({...hidden, status: 'pending'}, {details: true});
  const noHandle = await page({...hidden, instagram: null, status: 'pending'}, {details: true});
  assert.equal(pending.status, 200);
  assert.equal(pending.html, noHandle.html, 'a valid handle has no pending-page effect');
  assert.match(pending.html, /adv-badge-pending/);
  assert.match(pending.html, /<meta name="robots" content="noindex">/);
  for (const value of ['adv-badge-verified', 'instagram.com', 'tel:', 'example.com/book', fixture.landing, 'sp1707-report', '/media/sp1707-', '12 lingcod']) assert.ok(!pending.html.includes(value), value);
  for (const status of ['rejected']) {
    const result = await page({...hidden, status});
    assert.equal(result.status, 404);
    assert.equal(result.headers.get('Cache-Control'), 'no-store');
    assert.match(result.html, /<meta name="robots" content="noindex">/);
    assert.match(result.html, /<h1>Page not found<\/h1>/);
    assert.ok(!result.html.includes('adv-badge-verified') && !result.html.includes('instagram.com'));
  }
  assert.equal((await page(hidden, {enabled: false})).status, 404);
});

test('A4 other contacts, approved photos, escaping and reports remain unchanged', async () => {
  const extra = {name: 'Example <script>alert("boat")</script>', landing: 'Example <landing>',
    booking_url: 'https://example.com/book?a=1&b=2', phone_public: '+18055550188'};
  const mixed = await page(extra, {details: true});
  const lower = await page({...extra, instagram: fixture.instagram.toLowerCase()}, {details: true});
  contact(mixed, fixture.instagram);
  assert.equal(mixed.html.split(fixture.instagram).join(fixture.instagram.toLowerCase()), lower.html, 'entire page differs only in Instagram handle spelling');
  assert.match(mixed.html, /href="https:\/\/example.com\/book\?a=1&amp;b=2" rel="noopener nofollow">Booking page/);
  assert.match(mixed.html, /href="tel:\+18055550188">Call \(805\) 555-0188/);
  for (const id of ['approved', 'posted']) assert.ok(mixed.html.includes(`/media/sp1707-${id}.jpg`));
  assert.ok(!mixed.html.includes('sp1707-private'));
  assert.ok(mixed.html.includes('Example &lt;credit&gt;'));
  assert.ok(mixed.html.includes('&lt;script&gt;alert(&quot;boat&quot;)&lt;/script&gt;'));
  assert.ok(!mixed.html.includes('<script>alert'));
  assert.ok(mixed.html.includes('Example &lt;landing&gt;'));
  assert.match(mixed.html, /Sun, Sep 27/);
  assert.match(mixed.html, /adv-tag">edited/);
  assert.match(mixed.html, /12 lingcod \(2 released\)/);
  for (const booking_url of ['http://example.com/book', 'javascript:alert(1)', 'https://user:pass@example.com/book']) {
    const result = await page({instagram: null, booking_url, phone_public: 'invalid'});
    assert.ok(!result.html.includes('id="book-title"'), 'invalid other contacts remain withheld');
  }
});
