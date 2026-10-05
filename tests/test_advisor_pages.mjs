// Text Advisor public pages (TA-W1; docs/plans/text-advisor/08-website.md § Public
// pages, 05 § The boat page): the escaping template (a boat named <script> renders
// inert), verified and unverified boats on the port and boat pages, the rules card
// (a stale row says "under review"), 404s for unknown ids, the edge-cache key with
// the language and the pages version (a bump is a miss), Spanish by ?lang=es and
// Accept-Language, no percentage and no "hotspot" on any page, the sitemap and
// robots.txt, the ADVISOR_ASSETS links, and the telemetry events and `s` source.
// Offline: real migrations in node:sqlite, the committed feed fixtures, a fake edge cache.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'southern-california': read('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = '0123456789';
globalThis.ADVISOR_ASSETS = {'advisor/pages.css': '/assets/chat.abcdef0123.css', 'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps, pageCacheKey} = await import('../server/routes/advisor.ts');
const {html, raw, escapeHtml, jsonLd, pageLanguage} = await import('../server/advisor/pages/render.ts');
const {withoutSelfLink, portSpeciesKeys} = await import('../server/advisor/pages/port.ts');
const {SPECIES_PAGE_KEYS, speciesPageKey, pageSafe} = await import('../server/advisor/pages/species.ts');
const {bumpPagesVersion} = await import('../server/advisor/intake/reports.ts');
const {PAGES_COPY} = await import('../web/advisor/copy.ts');
const {advisorAssetPaths} = await import('../scripts/client-build.mjs');
const {parseBatch, recordBatch, FUNNEL_EVENTS} = await import('../server/telemetry.ts');
const webTelemetry = await import('../web/telemetry.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const NOW = Date.parse('2026-09-28T19:00:00Z');   // Mon 12:00 in Morro Bay: the feed fixtures' day
const iso = ms => new Date(ms).toISOString();
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+18055550123'};
const EVIL = '<script>alert("boat")</script>';

// The intelligence fixture's hours moved into the 06:00-14:00 window of 28 Sep (as tests/test_advisor_daily.mjs does).
function intelInWindow() {
  const intel = read('./fixtures/feeds/intelligence.json');
  const delta = Date.parse('2026-09-28T14:00:00Z') / 1000 - intel.forecast.models.gfs_global.data[0].hourly.time[0];
  const walk = o => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) if (k === 'time' && Array.isArray(v) && v.every(Number.isFinite)) o[k] = v.map(x => x + delta); else walk(v);
  };
  walk(intel.forecast);
  return intel;
}
const DAILY = read('./fixtures/feeds/daily-latest.json'), INTEL = intelInWindow();
pagesDeps.clock = () => NOW;
pagesDeps.feeds = async url => {
  if (/intelligence\.json$/.test(url)) return INTEL;
  if (/latest\.json$/.test(url)) return DAILY;
  throw Error(`no fixture for ${url}`);
};

/** A fake shared edge cache (caches.default) that records what it stores. */
function fakeCache() {
  const store = new Map();
  globalThis.caches = {default: {async match(request) { const hit = store.get(request.url); return hit ? hit.clone() : undefined; },
    async put(request, response) { store.set(request.url, response.clone()); }}};
  return store;
}
const noCache = () => { delete globalThis.caches; };

function seed() {
  const {sql, db} = advisorDatabase();
  const at = iso(NOW - 86400000);
  const boat = (id, slug, name, status, extra = {}) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,booking_url,phone_public,status,verified_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, slug, name, extra.landing ?? 'Virg\'s Landing', extra.port ?? 'morro-bay', 'morro-bay', extra.instagram ?? null,
    extra.booking ?? null, extra.phone ?? null, status, status === 'verified' ? at : null, at, at);
  boat('b-rita', 'rita-g', 'Rita G', 'verified', {instagram: 'ritag_sportfishing', booking: 'https://example.com/book', phone: '+18055550188'});
  boat('b-evil', 'script-boat', EVIL, 'verified');
  boat('b-wolf', 'sea-wolf', 'Sea Wolf', 'pending');
  boat('b-gone', 'gone-boat', 'Gone Boat', 'rejected');
  const report = (id, boatId, date, counts, verified, version = 1, port = 'morro-bay') => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, boatId, 'morro-bay', port, date, 'full-day', 22, JSON.stringify(counts), 'count-text', 'published', verified, version, at, at, at);
  report('r1', 'b-rita', '2026-09-27', [{label: 'vermilion', species_key: 'rockfish', kept: 45, released: null}, {label: 'lingcod', species_key: 'lingcod', kept: 12, released: 2}], 1, 2);
  report('r2', 'b-evil', '2026-09-26', [{label: 'lingcod', species_key: 'lingcod', kept: 3, released: null}], 1);
  report('r3', 'b-wolf', '2026-09-25', [{label: 'lings', species_key: 'lingcod', kept: 7, released: null}], 0);
  report('r-old', 'b-rita', '2026-08-01', [{label: 'lingcod', species_key: 'lingcod', kept: 99, released: null}], 1);
  const rule = (id, key, label, status, due, extra = {}) => sql.prepare(`INSERT INTO advisor_rules(id,region,jurisdiction,species_key,species_label,size_min_in,bag_limit,bag_notes,season_open,season_close,source_name,source_url,reviewed_at,review_due,status,updated_by,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, '*', 'california-central', key, label, extra.size ?? null, extra.bag ?? null, extra.notes ?? null, extra.open ?? null, extra.close ?? null,
    'CDFW Ocean Sport Fishing Regulations', 'https://wildlife.ca.gov/Fishing/Ocean/Regulations', '2026-06-01', due, status, 'test', at);
  rule('rule-ling', 'lingcod', 'Lingcod', 'active', '2027-06-01', {size: 22, bag: 2, open: '04-01', close: '12-31'});
  rule('rule-rock', 'rockfish', 'Rockfish (RCG complex)', 'review', '2027-06-01', {bag: 10, notes: 'Sub-bag limits apply', open: '04-01', close: '12-31'});
  rule('rule-hal', 'halibut', 'California halibut', 'active', '2026-01-01', {size: 22, bag: 2});   // past review_due: stale
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run('m-ok', 'c1', 'b-rita', 'image', 'image/jpeg', 100, 'advisor/media/c1/m-ok.jpg', 'x', 1, 'approved', 'Rita G', at);
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run('m-private', 'c1', 'b-rita', 'image', 'image/jpeg', 100, 'advisor/media/c1/m-private.jpg', 'y', 1, 'private', 'Rita G', at);
  return {sql, db};
}
const get = (path, env, headers = {}) => worker.fetch(new Request(ORIGIN + path, {headers}), {ASSETS, ...env});
/** Visible text of a page: no scripts, styles or tags, entities decoded. */
const visible = page => page.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<style[\s\S]*?<\/style>/g, ' ').replace(/<[^>]+>/g, ' ')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ');

// ---- the template ------------------------------------------------------------------------

test('html escapes every value, joins arrays, drops null and booleans, and keeps raw() and nested html', () => {
  const name = EVIL;
  assert.equal(html`<p title="${name}">${name}</p>`.value, '<p title="&lt;script&gt;alert(&quot;boat&quot;)&lt;/script&gt;">&lt;script&gt;alert(&quot;boat&quot;)&lt;/script&gt;</p>');
  assert.equal(html`<ul>${['a', '<b>'].map(x => html`<li>${x}</li>`)}</ul>`.value, '<ul><li>a</li><li>&lt;b&gt;</li></ul>');
  assert.equal(html`${null}${undefined}${false}${true}${0}${raw('<br>')}`.value, '0<br>');
  assert.equal(escapeHtml(`'&`), '&#39;&amp;');
  assert.equal(jsonLd({name: '</script><script>x</script>'}).value, '{"name":"\\u003c/script\\u003e\\u003cscript\\u003ex\\u003c/script\\u003e"}');
});

test('the page language: ?lang wins, then the first Accept-Language range; English by default', () => {
  const u = q => new URL(`${ORIGIN}/ports/morro-bay${q}`);
  assert.equal(pageLanguage(u('?lang=es'), 'en-US'), 'es');
  assert.equal(pageLanguage(u('?lang=en'), 'es-MX'), 'en');
  assert.equal(pageLanguage(u(''), 'es-MX,es;q=0.9,en;q=0.8'), 'es');
  assert.equal(pageLanguage(u(''), 'en-US,es;q=0.5'), 'en');
  assert.equal(pageLanguage(u(''), 'fr-FR,es;q=0.7'), 'es', 'the first range that is English or Spanish');
  assert.equal(pageLanguage(u('?lang=fr'), null), 'en');
  assert.equal(pageLanguage(u(''), 'es;q=0'), 'en');
});

test('the daily answer loses its link back to the port page', () => {
  const url = 'https://skippercast.com/ports/morro-bay?s=txt';
  assert.equal(withoutSelfLink(`Morro Bay, Mon Sep 28: quiet. Full picture: ${url}`, url), 'Morro Bay, Mon Sep 28: quiet.');
  assert.equal(withoutSelfLink(`Quiet day. ${url}`, url), 'Quiet day.');
  assert.equal(withoutSelfLink('No link here.', url), 'No link here.');
});

test('every page string exists in English and Spanish, and the copy never says hotspot or a percentage', () => {
  assert.deepEqual(Object.keys(PAGES_COPY.es).sort(), Object.keys(PAGES_COPY.en).sort());
  for (const language of ['en', 'es']) {
    for (const [key, value] of Object.entries(PAGES_COPY[language])) {
      const text = typeof value === 'function' ? value('X', 'Y') : typeof value === 'object' ? Object.values(value).join(' ') : value;
      assert.doesNotMatch(String(text), /%|hot ?spot|probab/i, `${language}.${key}`);
    }
  }
  assert.equal(pageSafe('Troll the edge. Do not publish that cell as a hotspot. Watch the birds.'), 'Troll the edge. Watch the birds.');
});

// ---- the pages through the Worker --------------------------------------------------------

dbTest('the port page: today, reports (verified linked, the <script> boat inert, unverified as another boat), conditions, boats, seasons', async () => {
  noCache();
  const {db} = seed();
  const response = await get('/ports/morro-bay', {...ON, DB: db});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'text/html; charset=utf-8');
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=300');
  assert.equal(response.headers.get('Content-Language'), 'en');
  const page = await response.text(), text = visible(page);
  assert.match(page, /^<!doctype html>\n<html lang="en"/);
  assert.match(page, /<title>Morro Bay fishing report · SkipperCast<\/title>/);
  assert.match(page, /<link rel="canonical" href="https:\/\/skippercast.com\/ports\/morro-bay">/);
  assert.match(page, /<link rel="stylesheet" href="\/assets\/chat.abcdef0123.css">/);
  assert.match(page, /<script type="module" src="\/assets\/chat.0123abcdef.js"><\/script>/);
  assert.match(page, /<body class="adv-page" data-advisor-page="port" data-region="morro-bay">/);
  assert.match(page, /"@type":"Organization"/);
  assert.match(page, /"@type":"BreadcrumbList"/);
  // Escaping: the boat's name is text, never markup.
  assert.ok(!page.includes(EVIL) && !page.includes('<script>alert'), 'no raw <script> from data');
  assert.ok(page.includes('&lt;script&gt;alert(&quot;boat&quot;)&lt;/script&gt;'), 'the name is escaped');
  assert.match(page, /<a href="\/boats\/rita-g">Rita G<\/a>/);
  assert.match(page, /<a href="\/boats\/script-boat">&lt;script&gt;/);
  assert.ok(!text.includes('Sea Wolf'), 'an unverified boat is not named on the port page');
  assert.match(text, /Another boat/);
  assert.match(text, /45 vermilion, 12 lingcod \(2 released\)/);
  assert.match(text, /Sun, Sep 27 edited/, 'version > 1 is marked edited');
  assert.ok(!text.includes('99 lingcod'), 'reports older than 14 days are left out');
  // Today's answer, the window conditions and the boats list.
  assert.match(text, /Today's report Morro Bay, Mon Sep 28:/);
  assert.ok(!page.includes('ports/morro-bay?s=txt'), 'no link back to itself');
  assert.match(text, /Seas 7 ft at 17 s/);
  assert.match(text, /Ride Rough for a mid-size center console/);
  assert.match(text, /Boats out of Morro Bay <script>alert\("boat"\)<\/script> Virg's Landing Rita G Virg's Landing Species/, 'verified boats only, by name');
  // Seasons from the rules table: lingcod open, rockfish in review, halibut past due.
  assert.match(page, /href="\/species\/lingcod#rules">Lingcod<\/a> <span class="adv-state adv-state-open">Open today/);
  assert.match(page, /href="\/species\/rockfish#rules">Rockfish<\/a> <span class="adv-state adv-state-review">Under review/);
  assert.match(page, /href="\/species\/halibut#rules">[^<]+<\/a> <span class="adv-state adv-state-review">Under review/);
  assert.match(page, /href="\/species\/salmon#rules">[^<]+<\/a> <span class="adv-state adv-state-unknown">Check the rules/);
  // CTA, QR and the standard disclaimer line.
  assert.match(page, /href="sms:\+18055550123\?&amp;body=What&#39;s%20biting%20out%20of%20Morro%20Bay%3F%20%5Bvia%20web%5D" data-advisor-cta/);
  assert.match(page, /<img class="adv-cta-qr" src="\/qr\/text.svg"/);
  assert.match(text, /Planning aid · not a navigation chart\. Rules change\. Verify with CDFW and NOAA before you fish\./);
  assert.match(page, /<meta property="og:image" content="https:\/\/skippercast.com\/media\/m-ok.jpg">/, 'the port\'s latest approved photo');
  assert.deepEqual(portSpeciesKeys('morro-bay'), ['lingcod', 'rockfish', 'halibut', 'salmon', 'dungeness', 'albacore', 'bluefin']);
});

dbTest('hardening: a pending boat page shows only its name, port, the unverified badge and the note; no booking link, phone, Instagram, landing, reports or photos until verified', async () => {
  noCache();
  const {sql, db} = seed();
  sql.prepare("UPDATE advisor_boats SET booking_url='https://phish.example/login',phone_public='+18055550177',instagram='fake_boat_handle',landing='Sketchy Landing' WHERE id='b-wolf'").run();
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at) VALUES('m-wolf','c9','b-wolf','image','image/jpeg',100,'advisor/media/c9/m-wolf.jpg','z',1,'approved','Sea Wolf',?)`).run(iso(NOW - 86400000));
  const response = await get('/boats/sea-wolf', {...ON, DB: db});
  assert.equal(response.status, 200);
  const page = await response.text(), text = visible(page);
  for (const hidden of ['phish.example', 'tel:', '555-0177', 'fake_boat_handle', 'instagram.com', 'Sketchy Landing', 'm-wolf', 'lings', 'Booking page'])
    assert.ok(!page.includes(hidden) && !text.includes(hidden), `${hidden} is not on a pending boat's page`);
  assert.match(page, /<h1>Sea Wolf<\/h1>/);
  assert.match(page, /<a href="\/ports\/morro-bay">Morro Bay/);
  assert.match(page, /<span class="adv-badge adv-badge-pending">Not verified yet<\/span>/);
  assert.match(text, /This boat hasn't been confirmed yet\./);
  assert.match(page, /<meta name="robots" content="noindex">/);
  assert.ok(!/og:image/.test(page) || !page.includes('/media/m-wolf'), 'no photo as the share image either');
  const es = await (await get('/boats/sea-wolf?lang=es', {...ON, DB: db})).text();
  assert.match(visible(es), /Este barco aún no ha sido confirmado\./);
  assert.ok(!es.includes('phish.example'));
  // Never in the sitemap while pending.
  const sitemap = await (await get('/sitemap-advisor.xml', {...ON, DB: db})).text();
  assert.ok(sitemap.includes('/boats/rita-g') && !sitemap.includes('/boats/sea-wolf'));
  // Once verified, the details show.
  sql.prepare("UPDATE advisor_boats SET status='verified',verified_at=? WHERE id='b-wolf'").run(iso(NOW));
  const verified = await (await get('/boats/sea-wolf', {...ON, DB: db})).text();
  assert.match(verified, /<a href="https:\/\/phish.example\/login" rel="noopener nofollow">Booking page<\/a>/);
  assert.match(verified, /fake_boat_handle/);
});

dbTest('the boat page: verified badge, 30 days of reports, approved photos credited, booking, phone and Instagram; pending is unverified and noindex; rejected is 404', async () => {
  noCache();
  const {db} = seed();
  const rita = await (await get('/boats/rita-g', {...ON, DB: db})).text(), text = visible(rita);
  assert.match(text, /Rita G Virg's Landing, Morro Bay/);
  assert.match(rita, /<span class="adv-badge adv-badge-verified">Verified boat<\/span>/);
  assert.ok(!rita.includes('name="robots"'), 'a verified boat is indexable');
  assert.match(text, /Sun, Sep 27 edited Full day 22 45 vermilion, 12 lingcod \(2 released\)/);
  assert.ok(!text.includes('99 lingcod'), 'reports older than 30 days are left out');
  assert.match(rita, /<img src="\/media\/m-ok.jpg" alt="Photo from Rita G" loading="lazy"><figcaption>Photo: Rita G<\/figcaption>/);
  assert.ok(!rita.includes('m-private'), 'a private photo is never shown');
  assert.match(rita, /<a href="https:\/\/example.com\/book" rel="noopener nofollow">Booking page<\/a>/);
  assert.match(rita, /<a href="tel:\+18055550188">Call \(805\) 555-0188<\/a>/);
  assert.match(rita, /<a href="https:\/\/www.instagram.com\/ritag_sportfishing\/" rel="noopener nofollow">Instagram: @ritag_sportfishing<\/a>/);
  assert.match(rita, /data-advisor-page="boat" data-region="morro-bay"/);

  const evil = await (await get('/boats/script-boat', {...ON, DB: db})).text();
  assert.ok(!evil.includes(EVIL) && !evil.includes('<script>alert'), 'the <script> name renders inert');
  assert.match(evil, /<h1>&lt;script&gt;alert\(&quot;boat&quot;\)&lt;\/script&gt;<\/h1>/);
  assert.match(evil, /<title>&lt;script&gt;alert\(&quot;boat&quot;\)&lt;\/script&gt;: fish reports · SkipperCast<\/title>/);
  assert.ok(evil.includes('"name":"\\u003cscript\\u003ealert(\\"boat\\")\\u003c/script\\u003e"'), 'JSON-LD escapes it too');

  const wolf = await (await get('/boats/sea-wolf', {...ON, DB: db})).text();
  assert.match(wolf, /<span class="adv-badge adv-badge-pending">Not verified yet<\/span>/);
  assert.match(wolf, /<meta name="robots" content="noindex">/);
  assert.ok(!/lings/.test(visible(wolf)), 'hardening: a pending boat shows no reports until verified');

  for (const path of ['/boats/gone-boat', '/boats/no-such-boat', '/boats/Bad_Slug!', '/ports/atlantis', '/species/unicorn']) {
    const response = await get(path, {...ON, DB: db});
    assert.equal(response.status, 404, path);
    assert.equal(response.headers.get('Cache-Control'), 'no-store', path);
    const body = await response.text();
    assert.match(body, /<h1>Page not found<\/h1>/, path);
    assert.match(body, /<meta name="robots" content="noindex">/, path);
  }
});

dbTest('the species page: names, cues and look-alikes, the rules card at #rules with source and reviewed date, stale rows under review, recent catches, method notes', async () => {
  noCache();
  const {db} = seed();
  const ling = await (await get('/species/lingcod', {...ON, DB: db})).text(), text = visible(ling);
  assert.match(text, /English: Lingcod · Spanish: Lingcod/);
  assert.match(text, /huge head and mouth with large, sharp teeth/);
  assert.match(ling, /<a href="\/species\/cabezon">Cabezon<\/a>/);
  assert.match(ling, /<section class="adv-card" id="rules"/);
  assert.match(text, /Lingcod Minimum size 22 in Daily bag 2 per angler Season Apr 1 to Dec 31 Source CDFW Ocean Sport Fishing Regulations Reviewed Jun 1, 2026/);
  assert.match(ling, /<a href="https:\/\/wildlife.ca.gov\/Fishing\/Ocean\/Regulations" rel="noopener">/);
  assert.ok(!ling.includes('Under review'), 'an active, current rule is not under review');
  // Recent catches by date and port, verified boats only: Rita G 12 + the <script> boat 3; Sea Wolf (unverified) and the old report are left out.
  assert.match(text, /Sun, Sep 27 Morro Bay 12 2 1/);
  assert.match(text, /Sat, Sep 26 Morro Bay 3 0 1/);
  assert.ok(!/Fri, Sep 25/.test(text), 'unverified boats do not count');
  assert.match(text, /How it is fished/);

  const rock = visible(await (await get('/species/rockfish', {...ON, DB: db})).text());
  assert.match(rock, /Rockfish \(RCG complex\) Under review This rule is due for review\. Check the source before you keep a fish\./);
  const vermilion = visible(await (await get('/species/vermilion', {...ON, DB: db})).text());
  assert.match(vermilion, /Group rule: Rockfish \(RCG complex\) Under review/, 'a sub-species shows its group\'s row');
  assert.match(vermilion, /Sun, Sep 27 Morro Bay 45 0 1/, 'a line labelled vermilion counts for the vermilion page');
  const halibut = visible(await (await get('/species/halibut', {...ON, DB: db})).text());
  assert.match(halibut, /California halibut Under review/, 'past its review_due date is stale');

  // A synonym moves to the page key.
  const moved = await get('/species/california-halibut?lang=es', {...ON, DB: db});
  assert.equal(moved.status, 301);
  assert.equal(moved.headers.get('Location'), '/species/halibut?lang=es');
  assert.equal(speciesPageKey('LINGCOD'), 'lingcod');
  assert.equal(speciesPageKey('unicorn'), null);
});

dbTest('Spanish by ?lang=es or Accept-Language, with its own cache entry', async () => {
  const store = fakeCache();
  try {
    const {db} = seed();
    const es = await get('/ports/morro-bay?lang=es', {...ON, DB: db});
    assert.equal(es.headers.get('Content-Language'), 'es');
    const page = await es.text(), text = visible(page);
    assert.match(page, /<html lang="es"/);
    assert.match(page, /<link rel="canonical" href="https:\/\/skippercast.com\/ports\/morro-bay\?lang=es">/);
    assert.match(text, /Reporte de pesca de Morro Bay/);
    assert.match(text, /Otro barco/);
    assert.match(text, /Ayuda para planear · no es una carta náutica\./);
    assert.match(page, /body=%C2%BFQu%C3%A9%20est%C3%A1%20picando%20en%20Morro%20Bay%3F%20%5Bvia%20web%5D/);
    const byHeader = await get('/ports/morro-bay', {...ON, DB: db}, {'Accept-Language': 'es-MX,es;q=0.9'});
    assert.equal(byHeader.headers.get('X-SC-Cache'), 'hit', 'the same Spanish page from the cache');
    assert.equal(byHeader.headers.get('Content-Language'), 'es');
    const en = await get('/ports/morro-bay', {...ON, DB: db}, {'Accept-Language': 'en-US'});
    assert.equal(en.headers.get('X-SC-Cache'), 'miss', 'English is another entry');
    assert.equal(en.headers.get('Content-Language'), 'en');
    assert.equal(store.size, 2);
    const species = visible(await (await get('/species/lingcod?lang=es', {...ON, DB: db})).text());
    assert.match(species, /cabeza y boca enormes con dientes grandes y filosos/);
    assert.match(species, /Talla mínima 22 pulg/);
    assert.match(species, /Las notas de pesca están en inglés\./);
    const boat = visible(await (await get('/boats/rita-g?lang=es', {...ON, DB: db})).text());
    assert.match(boat, /Barco verificado/);
    assert.match(boat, /dom 27 de sep editado Día completo 22 45 vermilion, 12 lingcod \(2 liberados\)/);
  } finally { noCache(); }
});

dbTest('the cache key carries the build, the pages version and the language; a bump (publish, edit, verification) is a miss', async () => {
  const store = fakeCache();
  try {
    const {sql, db} = seed();
    const url = new URL(`${ORIGIN}/boats/rita-g?s=txt&utm=x`);
    assert.equal(pageCacheKey(url, 'en', '0').url, `${ORIGIN}/boats/rita-g?lang=en&sc-build=0123456789%3A0`);
    assert.equal(pageCacheKey(url, 'es', '7').url, `${ORIGIN}/boats/rita-g?lang=es&sc-build=0123456789%3A7`);
    const first = await get('/boats/rita-g?s=txt', {...ON, DB: db});
    assert.equal(first.headers.get('X-SC-Cache'), 'miss');
    const again = await get('/boats/rita-g?s=ig', {...ON, DB: db});
    assert.equal(again.headers.get('X-SC-Cache'), 'hit', 'the source parameter is not part of the key');
    sql.prepare("UPDATE advisor_boats SET name='Rita G II' WHERE id='b-rita'").run();
    assert.match(await (await get('/boats/rita-g', {...ON, DB: db})).text(), /<h1>Rita G<\/h1>/, 'cached until the version moves');
    await bumpPagesVersion(db, NOW);
    const fresh = await get('/boats/rita-g', {...ON, DB: db});
    assert.equal(fresh.headers.get('X-SC-Cache'), 'miss');
    assert.match(await fresh.text(), /<h1>Rita G II<\/h1>/);
    assert.ok([...store.keys()].some(k => k.endsWith('sc-build=0123456789%3A1')), 'stored under the new version');
    const missing = await get('/boats/nope', {...ON, DB: db});
    assert.equal(missing.status, 404);
    assert.ok(![...store.keys()].some(k => k.includes('/boats/nope')), '404s are not cached');
  } finally { noCache(); }
});

dbTest('no page says a percentage or "hotspot": every species page, the ports and the boats', async () => {
  noCache();
  const {db} = seed();
  const paths = [...SPECIES_PAGE_KEYS.map(k => `/species/${k}`), '/ports/morro-bay', '/ports/port-san-luis', '/boats/rita-g', '/boats/sea-wolf'];
  for (const path of paths) for (const q of ['', '?lang=es']) {
    const response = await get(path + q, {...ON, DB: db});
    assert.equal(response.status, 200, path + q);
    const text = visible(await response.text());
    assert.doesNotMatch(text, /%/, `${path}${q} has a percentage`);
    assert.doesNotMatch(text, /hot ?spot/i, `${path}${q} says hotspot`);
  }
});

dbTest('the sitemap lists active ports, every species and verified boats only; robots.txt names it while the advisor is on', async () => {
  noCache();
  const {db} = seed();
  const response = await get('/sitemap-advisor.xml', {...ON, DB: db});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'application/xml; charset=utf-8');
  assert.equal(response.headers.get('Cache-Control'), 'public, max-age=3600');
  const xml = await response.text();
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1].replace(ORIGIN, ''));
  assert.deepEqual(locs.filter(l => l.startsWith('/ports/')), ['/ports/morro-bay', '/ports/port-san-luis'], 'active regions only');
  assert.equal(locs.filter(l => l.startsWith('/species/')).length, SPECIES_PAGE_KEYS.length);
  assert.deepEqual(locs.filter(l => l.startsWith('/boats/')), ['/boats/rita-g', '/boats/script-boat'], 'verified boats only');
  assert.match(xml, /<loc>https:\/\/skippercast.com\/boats\/rita-g<\/loc>\n    <lastmod>2026-09-27<\/lastmod>/);
  assert.match(xml, /hreflang="es" href="https:\/\/skippercast.com\/species\/lingcod\?lang=es"/);

  const robots = await get('/robots.txt', {...ON, DB: db});
  assert.equal(robots.status, 200);
  assert.equal(await robots.text(), 'User-agent: *\nAllow: /\n\nSitemap: https://skippercast.com/sitemap-advisor.xml\n');
  assert.equal((await get('/robots.txt', {DB: db})).status, 299, 'dark: robots.txt is the static site\'s, as before');
  for (const path of ['/sitemap-advisor.xml', '/ports/morro-bay', '/species/lingcod', '/boats/rita-g']) assert.equal((await get(path, {DB: db})).status, 404, `${path} is gated`);
  assert.equal((await get('/ports/morro-bay', ON)).status, 503, 'no D1');
});

dbTest('without a number the call to action opens the web chat', async () => {
  noCache();
  const {db} = seed();
  const page = await (await get('/species/lingcod', {TEXT_ADVISOR_ENABLED: 'true', DB: db})).text();
  assert.match(page, /<a class="adv-button" href="\/chat.html" data-advisor-cta>Ask SkipperCast<\/a>/);
  assert.ok(!page.includes('sms:'));
});

// ---- build and telemetry -----------------------------------------------------------------

test('ADVISOR_ASSETS comes from the chat page\'s manifest entry', () => {
  assert.deepEqual(advisorAssetPaths({'chat.html': {file: 'assets/chat.1111111111.js', isEntry: true, css: ['assets/chat.2222222222.css']}}),
    {'advisor/pages.css': '/assets/chat.2222222222.css', 'advisor/chat.js': '/assets/chat.1111111111.js'});
  assert.throws(() => advisorAssetPaths({}), /chat\.html/);
  assert.match(readFileSync(new URL('../dist/chat.html', import.meta.url), 'utf8'), /<link rel="stylesheet" href="advisor\/pages.css" \/>/);
});

test('telemetry: the page events and the `s` source are accepted and written as blob5; unknown sources are rejected', async () => {
  for (const name of ['advisor_port_view', 'advisor_species_view', 'advisor_boat_view', 'advisor_cta']) assert.ok(FUNNEL_EVENTS.includes(name) && webTelemetry.FUNNEL.includes(name), name);
  const batch = parseBatch({build: '0123456789', events: [{type: 'funnel', name: 'advisor_port_view', region: 'morro-bay', source: 'txt'}, {type: 'funnel', name: 'advisor_cta', region: 'morro-bay', source: 'txt'}, {type: 'funnel', name: 'advisor_species_view'}]});
  const points = [];
  await recordBatch({ANALYTICS: {writeDataPoint: p => points.push(p)}}, batch);
  assert.deepEqual(points.map(p => p.blobs), [['client_event', 'advisor_port_view', 'morro-bay', '0123456789', 'txt'], ['client_event', 'advisor_cta', 'morro-bay', '0123456789', 'txt'], ['client_event', 'advisor_species_view', '', '0123456789']]);
  assert.throws(() => parseBatch({build: '0123456789', events: [{type: 'funnel', name: 'advisor_cta', source: 'email'}]}), /invalid telemetry/);
  assert.equal(webTelemetry.sourceFrom('https://skippercast.com/ports/morro-bay?s=qr'), 'qr');
  assert.equal(webTelemetry.sourceFrom('https://skippercast.com/ports/morro-bay?s=evil'), '');
  const sent = [];
  const t = webTelemetry.createTelemetry({send: body => { sent.push(JSON.parse(body)); return true; }, build: '0123456789', source: () => 'ig', schedule: () => {}});
  t.track('advisor_boat_view', {region: 'morro-bay'});
  t.track('advisor_cta', {region: 'morro-bay', flush: true});
  assert.deepEqual(sent[0].events, [{type: 'funnel', name: 'advisor_boat_view', region: 'morro-bay', source: 'ig'}, {type: 'funnel', name: 'advisor_cta', region: 'morro-bay', source: 'ig'}]);
});
