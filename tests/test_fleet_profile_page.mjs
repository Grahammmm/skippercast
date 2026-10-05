// Charter fleet public profile on /boats/<slug> (CF-33; docs/plans/charter-fleet/design.md
// § 13, § 17). Offline: the real migrations in node:sqlite, synthetic vessels, example.com
// URLs and 555-01XX phones only.
//
// Acceptance 1 is a snapshot: tests/fixtures/boat-page-snapshots/*.html are the advisor
// boat pages rendered by the code on main before CF-33 (commit "Snapshot advisor boat pages
// before CF-33"). With FLEET_ENABLED off (and with it on for a boat with no registry link)
// the page must stay byte-identical. They live outside tests/fixtures/fleet/ because the
// privacy scan there reads the JSON-LD keys ("@context", "@type") as Instagram mentions.
// Regenerate only for an intended advisor page change:
//   SNAPSHOT_WRITE=1 node --test tests/test_fleet_profile_page.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = '0123456789';
globalThis.ADVISOR_ASSETS = {'advisor/pages.css': '/assets/chat.abcdef0123.css', 'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps} = await import('../server/routes/advisor.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const ORIGIN = 'https://skippercast.com';
const NOW = Date.parse('2026-09-28T19:00:00Z');
const iso = ms => new Date(ms).toISOString();
const DAY = 86400000;
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ADVISOR = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_NUMBER: '+18055550123'};
const FLEET = {FLEET_ENABLED: 'true'};
pagesDeps.clock = () => NOW;
pagesDeps.feeds = async url => { throw Error(`no feed in this test: ${url}`); };
delete globalThis.caches;

function seedAdvisor(sql) {
  const at = iso(NOW - DAY);
  const boat = (id, slug, name, status, extra = {}) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,instagram,booking_url,phone_public,status,verified_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, slug, name, extra.landing ?? 'Gull\'s Landing', 'morro-bay', 'morro-bay', extra.instagram ?? null,
    extra.booking ?? null, extra.phone ?? null, status, status === 'verified' ? at : null, at, at);
  boat('b-sea', 'sea-example', 'Sea Example', 'verified', {instagram: 'seaexample_fishing', booking: 'https://example.com/book', phone: '+18055550188'});
  boat('b-gray', 'gray-example', 'Gray Example', 'pending');
  const report = (id, boatId, date, counts, verified, version = 1) => sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, boatId, 'morro-bay', 'morro-bay', date, 'full-day', 22, JSON.stringify(counts), 'count-text', 'published', verified, version, at, at, at);
  report('r1', 'b-sea', '2026-09-27', [{label: 'vermilion', species_key: 'rockfish', kept: 45, released: null}, {label: 'lingcod', species_key: 'lingcod', kept: 12, released: 2}], 1, 2);
  report('r2', 'b-sea', '2026-09-20', [{label: 'lingcod', species_key: 'lingcod', kept: 8, released: null}], 1);
  sql.prepare(`INSERT INTO advisor_media(id,contact_id,boat_id,kind,mime,bytes,r2_key,sha256,exif_stripped,publish_state,credit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run('m-ok', 'c1', 'b-sea', 'image', 'image/jpeg', 100, 'advisor/media/c1/m-ok.jpg', 'x', 1, 'approved', 'Sea Example', at);
}

const get = (path, env, headers = {}) => worker.fetch(new Request(ORIGIN + path, {headers}), {ASSETS, ...env});

// ---- Acceptance 1: advisor boat pages are byte-identical with FLEET_ENABLED off ----------
const SNAPSHOTS = [
  ['sea-example.en.html', '/boats/sea-example'],
  ['sea-example.es.html', '/boats/sea-example?lang=es'],
  ['gray-example.en.html', '/boats/gray-example'],
];
const snapshotUrl = name => new URL(`./fixtures/boat-page-snapshots/${name}`, import.meta.url);

dbTest('acceptance 1: with FLEET_ENABLED off an advisor boat page is byte-identical to the pre-fleet snapshot', async () => {
  const {sql, db} = advisorDatabase(); seedAdvisor(sql);
  try {
    if (process.env.SNAPSHOT_WRITE === '1') {
      mkdirSync(new URL('./fixtures/boat-page-snapshots/', import.meta.url), {recursive: true});
      for (const [name, path] of SNAPSHOTS) writeFileSync(snapshotUrl(name), await (await get(path, {...ADVISOR, DB: db})).text());
    }
    for (const [name, path] of SNAPSHOTS) {
      const expected = readFileSync(snapshotUrl(name), 'utf8');
      for (const env of [{...ADVISOR}, {...ADVISOR, FLEET_ENABLED: 'false'}, {...ADVISOR, FLEET_ENABLED: 'yes'}]) {
        const response = await get(path, {...env, DB: db});
        assert.equal(response.status, 200, path);
        assert.equal(await response.text(), expected, `${path} with ${JSON.stringify(env.FLEET_ENABLED)}`);
      }
    }
  } finally { sql.close(); }
});

// ---- Registry fixtures (synthetic) -------------------------------------------------------
const VESSEL_AT = iso(NOW - 10 * DAY);
const vessel = (sql, id, slug, name, extra = {}) => sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,port_id,vessel_class,year_built,passengers_max,length_ft,
    website,booking_url,phone_business,status,profile_status,removal_requested_at,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
  .run(id, 'CA', slug, name, name.toUpperCase().replace(/[^A-Z0-9]/g, ''), extra.operator ?? null, 'morro-bay', extra.vesselClass ?? 'inspected-party', extra.year ?? 1998,
    extra.passengers ?? 24, extra.length ?? 42, extra.website ?? `https://${slug}.example.com/`, extra.booking ?? `https://book.example.com/${slug}?trip=1`,
    extra.phone ?? '+18055550142', extra.status ?? 'active', extra.profile ?? 'listed', extra.removal ?? null, VESSEL_AT, VESSEL_AT, VESSEL_AT, VESSEL_AT);
let factN = 0;
const fact = (sql, vesselId, field, value, {source = 'https://landing.example.com/fleet', method = 'page', confidence = 0.9, rights = 'facts-only', at = iso(NOW - 5 * DAY), superseded = null} = {}) => {
  const id = `f${String(++factN).padStart(31, '0')}`;
  sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at,superseded_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, vesselId, field, JSON.stringify(value), id.slice(-16), 'test', source, method, confidence, rights, at, at, at, superseded);
  return id;
};
const operator = (sql, id, consent, revoked = null) => sql.prepare(`INSERT INTO fleet_operators(id,region,slug,name,consent_status,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)`)
  .run(id, 'CA', id, `Operator ${id}`, consent, revoked, VESSEL_AT, VESSEL_AT);
const offering = (sql, id, vesselId, name, priceCents, sourceIds, extra = {}) => sql.prepare(`INSERT INTO fleet_offerings(id,vessel_id,name,trip_type,duration_h,price_cents,price_basis,currency,departs_local,status,source_fact_ids_json,valid_to,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(id, vesselId, name, extra.tripType ?? 'full-day', extra.hours ?? 10, priceCents, 'per-person', 'USD', extra.departs ?? '05:30',
  extra.status ?? 'active', JSON.stringify(sourceIds), extra.validTo ?? null, VESSEL_AT);
const PLACE = 'https://www.google.com/maps/place/?q=place_id:ChIJexampleexample';
const SECRET = 'SECRETAISNAME';

function seedFleet(sql) {
  operator(sql, 'op-unknown', 'unknown');
  operator(sql, 'op-sharing', 'content-sharing');
  operator(sql, 'op-revoked', 'partner', iso(NOW - DAY));
  // Blue Example: the full registry profile; operator consent unknown, so noindex.
  vessel(sql, 'v-blue', 'blue-example', 'Blue Example', {operator: 'op-unknown', passengers: 24, year: 1998});
  fact(sql, 'v-blue', 'vessel_class', 'inspected-party');
  fact(sql, 'v-blue', 'length_ft', 42, {rights: 'public-record', source: 'https://records.example.gov/vessel/1'});
  fact(sql, 'v-blue', 'passengers_max', 24, {confidence: 0.5});                         // below 0.6: hidden
  fact(sql, 'v-blue', 'year_built', 1998, {rights: 'noaa-planning-only', source: 'https://noaa.example.gov/cadastre'});   // never rendered
  fact(sql, 'v-blue', 'landing', 'Pier Example Landing');
  fact(sql, 'v-blue', 'landing', 'AIS Harbor Landing', {method: 'ais', rights: 'public-domain', confidence: 0.99});   // AIS: never rendered
  fact(sql, 'v-blue', 'mmsi', '999123456', {method: 'ais', rights: 'internal-only', confidence: 0.99, source: 'https://ais.example.com/stream'});
  fact(sql, 'v-blue', 'phone_business', '+18055550142', {source: 'https://blue-example.example.com/contact'});
  fact(sql, 'v-blue', 'website', 'https://blue-example.example.com/', {source: 'https://blue-example.example.com/contact'});
  fact(sql, 'v-blue', 'booking_url', 'https://book.example.com/blue-example?trip=1', {source: 'https://blue-example.example.com/contact'});
  fact(sql, 'v-blue', 'photos[]', {url: 'https://photos.example.com/blue.jpg', attribution: 'Pier Example Landing'});
  fact(sql, 'v-blue', 'photos[]', {url: 'http://photos.example.com/plain.jpg', attribution: 'Plain'});   // not https: dropped
  fact(sql, 'v-blue', 'reputation.google_rating', 4.7, {source: PLACE, method: 'api', rights: 'api-terms', at: iso(NOW - 3 * DAY)});
  fact(sql, 'v-blue', 'reputation.google_reviews', 128, {source: PLACE, method: 'api', rights: 'api-terms', at: iso(NOW - 3 * DAY)});
  fact(sql, 'v-blue', 'reputation.review_text', 'Best trip ever, said someone', {source: PLACE, method: 'api', rights: 'api-terms'});   // never rendered
  const price = fact(sql, 'v-blue', 'trip_types[].price_usd', 145, {source: 'https://landing.example.com/rates', at: '2026-09-20T16:00:00.000Z'});
  const internal = fact(sql, 'v-blue', 'trip_types[].price_usd', 999, {rights: 'internal-only', source: 'https://internal.example.com/x'});
  offering(sql, 'o-full', 'v-blue', 'Full day rockfish', 14500, [price]);
  offering(sql, 'o-internal', 'v-blue', 'Internal only trip', 99900, [internal]);
  offering(sql, 'o-retired', 'v-blue', 'Retired trip', 5000, [price], {status: 'retired'});
  offering(sql, 'o-expired', 'v-blue', 'Expired trip', 6000, [price], {validTo: '2026-01-01'});
  sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,ais_name,first_seen_at,last_seen_at,last_seen_source,positions_30d,updated_at)
      VALUES('CA','999123456','v-blue','admin',1,'watched',?,?,?,'aisstream',4321,?)`).run(SECRET, VESSEL_AT, VESSEL_AT, VESSEL_AT);
  // Stale Example: Google numbers 40 days old, so no rating; consented operator, so indexable and in the sitemap.
  vessel(sql, 'v-stale', 'stale-example', 'Stale Example', {operator: 'op-sharing'});
  fact(sql, 'v-stale', 'reputation.google_rating', 4.2, {source: PLACE, method: 'api', rights: 'api-terms', at: iso(NOW - 40 * DAY)});
  fact(sql, 'v-stale', 'reputation.google_reviews', 50, {source: PLACE, method: 'api', rights: 'api-terms', at: iso(NOW - 40 * DAY)});
  fact(sql, 'v-stale', 'website', 'https://stale-example.example.com/');
  // Nolink Example: a fresh rating without the Google place link has no attribution, so it is not shown; consent revoked.
  vessel(sql, 'v-nolink', 'nolink-example', 'Nolink Example', {operator: 'op-revoked'});
  fact(sql, 'v-nolink', 'reputation.google_rating', 4.9, {source: 'https://ratings.example.com/x', method: 'api', rights: 'api-terms', at: iso(NOW - DAY)});
  // Every one of these must 404.
  vessel(sql, 'v-hidden', 'hidden-example', 'Hidden Example', {profile: 'hidden'});
  vessel(sql, 'v-excluded', 'excluded-example', 'Excluded Example', {status: 'excluded'});
  vessel(sql, 'v-inactive', 'inactive-example', 'Inactive Example', {status: 'inactive'});
  vessel(sql, 'v-sold', 'sold-example', 'Sold Example', {status: 'sold'});
  vessel(sql, 'v-removed', 'removed-example', 'Removed Example', {removal: iso(NOW - 2 * DAY), operator: 'op-sharing'});
  for (const id of ['v-hidden', 'v-excluded', 'v-inactive', 'v-sold', 'v-removed']) fact(sql, id, 'website', `https://${id}.example.com/`);
  // The registry vessel the team linked to the Sea Example advisor boat.
  vessel(sql, 'v-sea', 'sea-example-charters', 'Sea Example', {operator: 'op-sharing', website: 'https://sea-example.example.org/', booking: 'https://book.example.com/sea?x=1'});
  fact(sql, 'v-sea', 'booking_url', 'https://book.example.com/sea?x=1');
  fact(sql, 'v-sea', 'vessel_class', 'inspected-party');
  sql.prepare("UPDATE advisor_boats SET fleet_vessel_id='v-sea' WHERE id='b-sea'").run();
}
function seedAll() { const {sql, db} = advisorDatabase(); seedAdvisor(sql); seedFleet(sql); return {sql, db}; }
const visible = page => page.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]+>/g, ' ')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ');

dbTest('acceptance 1: with FLEET_ENABLED off a linked advisor boat is still byte-identical and registry slugs 404', async () => {
  const {sql, db} = seedAll();
  try {
    assert.equal(await (await get('/boats/sea-example', {...ADVISOR, DB: db})).text(), readFileSync(snapshotUrl('sea-example.en.html'), 'utf8'));
    for (const path of ['/boats/blue-example', '/boats/sea-example-charters']) assert.equal((await get(path, {...ADVISOR, DB: db})).status, 404, path);
    // Both flags off: the whole prefix is dark, as before.
    for (const path of ['/boats/sea-example', '/boats/blue-example']) {
      const response = await get(path, {DB: db});
      assert.equal(response.status, 404, path);
      assert.equal((await response.json()).error, 'Not found', 'the gate\'s JSON 404, not a page');
    }
  } finally { sql.close(); }
});

dbTest('the registry profile: class, landing and port, length, offerings as listed, /go/ links, business phone, photo links, Google with attribution, dated sources; noindex without consent', async () => {
  const {sql, db} = seedAll();
  try {
    const response = await get('/boats/blue-example', {...ADVISOR, ...FLEET, DB: db});
    assert.equal(response.status, 200);
    const page = await response.text(), text = visible(page);
    assert.match(page, /<title>Blue Example: charter fishing boat · SkipperCast<\/title>/);
    assert.match(page, /<meta name="robots" content="noindex">/, 'registry-only and no operator consent: noindex');
    assert.match(text, /Blue Example Pier Example Landing, Morro Bay · Morro Bay fishing report/);
    assert.match(text, /About the boat Party boat 42 ft long Google : 4\.7 out of 5 · 128 reviews/);
    assert.match(page, /<a href="https:\/\/www\.google\.com\/maps\/place\/\?q=place_id:ChIJexampleexample" rel="noopener nofollow">Google<\/a>/);
    assert.match(text, /Full day rockfish · Full day · 10 h · departs 05:30 \$145 per person, as listed on landing\.example\.com on Sep 20, 2026/);
    assert.match(page, /<a href="\/go\/blue-example\?t=booking&amp;p=profile" rel="nofollow">Booking page<\/a>/);
    assert.match(page, /<a href="\/go\/blue-example\?t=website&amp;p=profile" rel="nofollow">Boat website<\/a>/);
    assert.match(page, /<a href="tel:\+18055550142">Call \(805\) 555-0142<\/a>/);
    assert.match(page, /<a href="https:\/\/photos\.example\.com\/blue\.jpg" rel="noopener nofollow">Photo: Pier Example Landing<\/a>/);
    assert.ok(!/<img[^>]+photos\.example\.com/.test(page), 'registry photos are linked, never embedded');
    assert.match(text, /Sources Details as published by the boat.* blue-example\.example\.com, checked Sep 23, 2026 .*landing\.example\.com, checked Sep 23, 2026 .*records\.example\.gov, checked Sep 23, 2026/);
    // Acceptance 5: booking and website links go through /go/; the only direct links out are the Google attribution and the photo credit.
    for (const [, href] of page.matchAll(/href="(https?:[^"]+)"/g)) {
      const url = href.replace(/&amp;/g, '&');
      assert.ok(url.startsWith('https://skippercast.com/') || url === PLACE || url === 'https://photos.example.com/blue.jpg', `unexpected direct link ${url}`);
    }
    assert.ok(!page.includes('book.example.com') && !page.includes('href="https://blue-example.example.com/'), 'stored booking and website URLs appear only behind /go/');
    const es = visible(await (await get('/boats/blue-example?lang=es', {...ADVISOR, ...FLEET, DB: db})).text());
    assert.match(es, /Sobre el barco Barco de grupo 42 pies de eslora Google : 4\.7 de 5 · 128 reseñas/);
  } finally { sql.close(); }
});

dbTest('acceptance 3: no AIS data, no noaa-planning-only, internal-only or low-confidence fact, and never review text', async () => {
  const {sql, db} = seedAll();
  try {
    for (const path of ['/boats/blue-example', '/boats/blue-example?lang=es']) {
      const page = await (await get(path, {...ADVISOR, ...FLEET, DB: db})).text(), text = visible(page);
      for (const hidden of ['999123456', SECRET, 'AIS Harbor Landing', 'ais.example.com', '4321', 'aisstream',   // AIS
        '1998', 'noaa.example.gov',                                                                               // noaa-planning-only
        '24 passengers', '24 pasajeros',                                                                          // confidence 0.5
        'Internal only trip', '$999', 'internal.example.com',                                                     // internal-only offering source
        'Retired trip', 'Expired trip', 'Best trip ever', 'plain.jpg'])
        assert.ok(!page.includes(hidden) && !text.includes(hidden), `${hidden} must not render on ${path}`);
    }
  } finally { sql.close(); }
});

dbTest('acceptance 4: the Google rating and count render only inside the 30-day window and only with the Google link', async () => {
  const {sql, db} = seedAll();
  try {
    const stale = await (await get('/boats/stale-example', {...ADVISOR, ...FLEET, DB: db})).text();
    assert.ok(!/Google/.test(visible(stale)) && !stale.includes('4.2') && !stale.includes('50 reviews'), 'a 40-day-old rating is not shown');
    const nolink = await (await get('/boats/nolink-example', {...ADVISOR, ...FLEET, DB: db})).text();
    assert.ok(!nolink.includes('4.9') && !/Google/.test(visible(nolink)), 'no attribution link, no rating');
    // The window runs from the fact's retrieved_at: 29 days old still shows, 31 days old does not.
    sql.prepare("UPDATE fleet_vessel_facts SET retrieved_at=? WHERE vessel_id='v-stale'").run(iso(NOW - 29 * DAY));
    assert.match(visible(await (await get('/boats/stale-example', {...ADVISOR, ...FLEET, DB: db})).text()), /Google : 4\.2 out of 5 · 50 reviews/);
    sql.prepare("UPDATE fleet_vessel_facts SET retrieved_at=? WHERE vessel_id='v-stale'").run(iso(NOW - 31 * DAY));
    assert.ok(!(await (await get('/boats/stale-example', {...ADVISOR, ...FLEET, DB: db})).text()).includes('4.2'));
  } finally { sql.close(); }
});

dbTest('acceptance 2: hidden, excluded, inactive, sold and removal-requested vessels 404 on /boats/ and /go/', async () => {
  const {sql, db} = seedAll();
  try {
    for (const slug of ['hidden-example', 'excluded-example', 'inactive-example', 'sold-example', 'removed-example', 'no-such-example']) {
      const response = await get(`/boats/${slug}`, {...ADVISOR, ...FLEET, DB: db});
      assert.equal(response.status, 404, slug);
      assert.match(await response.text(), /<h1>Page not found<\/h1>/, slug);
      assert.equal((await get(`/go/${slug}?t=website&p=profile`, {...FLEET, DB: db})).status, 404, `/go/${slug}`);
    }
    // An admin unhiding a vessel keeps removal_requested_at, and the vessel stays out of public.
    sql.prepare("UPDATE fleet_vessels SET profile_status='listed' WHERE id='v-hidden'").run();
    assert.equal((await get('/boats/hidden-example', {...ADVISOR, ...FLEET, DB: db})).status, 200);
    sql.prepare("UPDATE fleet_vessels SET removal_requested_at=? WHERE id='v-hidden'").run(iso(NOW));
    assert.equal((await get('/boats/hidden-example', {...ADVISOR, ...FLEET, DB: db})).status, 404);
  } finally { sql.close(); }
});

dbTest('a linked advisor boat keeps its page and gains the registry cards, with /go/ built from the fleet vessel slug', async () => {
  const {sql, db} = seedAll();
  try {
    const page = await (await get('/boats/sea-example', {...ADVISOR, ...FLEET, DB: db})).text();
    const before = readFileSync(snapshotUrl('sea-example.en.html'), 'utf8');
    // Everything up to the end of the advisor body is unchanged; the registry cards follow it.
    const cut = before.indexOf('\n<section class="adv-cta"');
    assert.ok(cut > 0 && page.startsWith(before.slice(0, cut)), 'the advisor part of the page is unchanged');
    assert.match(page, /<a href="\/go\/sea-example-charters\?t=booking&amp;p=profile" rel="nofollow">Booking page<\/a>/);
    assert.ok(!page.includes('/go/sea-example?'), '/go/ uses the fleet vessel slug, never the advisor boat slug');
    assert.ok(!page.includes('t=website'), 'a website with no displayable fact gets no link');
    assert.match(visible(page), /About the boat Party boat/);
    // The registry vessel's own page exists but stays out of search: the advisor page is the main one.
    assert.match(await (await get('/boats/sea-example-charters', {...ADVISOR, ...FLEET, DB: db})).text(), /<meta name="robots" content="noindex">/);
    // A hidden registry vessel adds nothing to the advisor page.
    sql.prepare("UPDATE fleet_vessels SET profile_status='hidden' WHERE id='v-sea'").run();
    assert.equal(await (await get('/boats/sea-example', {...ADVISOR, ...FLEET, DB: db})).text(), before);
  } finally { sql.close(); }
});

dbTest('the gate passes with either flag: with only FLEET_ENABLED registry pages render without the advisor call to action, and advisor boats 404', async () => {
  const {sql, db} = seedAll();
  try {
    const response = await get('/boats/stale-example', {...FLEET, DB: db});
    assert.equal(response.status, 200);
    const page = await response.text();
    assert.ok(!page.includes('name="robots"'), "a consented operator's vessel is indexable");
    for (const advisorOnly of ['adv-cta', 'advisor-chat', '/qr/text.svg', '/chat.html', 'chat.0123abcdef.js', '/ports/morro-bay'])
      assert.ok(!page.includes(advisorOnly), `${advisorOnly} is an advisor feature and stays dark`);
    assert.equal((await get('/boats/sea-example', {...FLEET, DB: db})).status, 404, 'advisor boats need the advisor on');
    assert.ok(!(await (await get('/boats/no-such-example', {...FLEET, DB: db})).text()).includes('adv-cta'));
  } finally { sql.close(); }
});

dbTest('the sitemap lists registry profiles only with FLEET_ENABLED and operator consent, never linked, revoked, hidden or removed ones', async () => {
  const {sql, db} = seedAll();
  try {
    const off = await (await get('/sitemap-advisor.xml', {...ADVISOR, DB: db})).text();
    assert.ok(off.includes('/boats/sea-example<') && !off.includes('stale-example'));
    const on = await (await get('/sitemap-advisor.xml', {...ADVISOR, ...FLEET, DB: db})).text();
    assert.match(on, /\/boats\/stale-example<\/loc>\n {4}<lastmod>2026-09-18<\/lastmod>/, 'consented operator');
    for (const out of ['blue-example', 'nolink-example', 'sea-example-charters', 'removed-example', 'hidden-example'])
      assert.ok(!on.includes(`/boats/${out}<`), `${out} is not in the sitemap`);
  } finally { sql.close(); }
});

test('the shared display predicates', async () => {
  const {displayableFact, displayableLink, withinGoogleWindow, DISPLAY_RIGHTS, publicVesselSql} = await import('../server/fleet/display.ts');
  assert.deepEqual([...DISPLAY_RIGHTS].sort(), ['api-terms', 'facts-only', 'public-domain', 'public-record']);
  const ok = {rights: 'facts-only', confidence: 0.6, method: 'page'};
  assert.equal(displayableFact(ok), true);
  for (const bad of [{...ok, confidence: 0.59}, {...ok, rights: 'noaa-planning-only'}, {...ok, rights: 'internal-only'}, {...ok, method: 'ais'}, {...ok, superseded_at: '2026-09-01T00:00:00.000Z'}])
    assert.equal(displayableFact(bad), false, JSON.stringify(bad));
  const facts = [{id: 'a', field: 'website', value_json: '"https://a.example.com/"', source_url: 'https://a.example.com/', method: 'page', confidence: 0.9, rights: 'facts-only', retrieved_at: ''}];
  assert.equal(displayableLink('https://a.example.com/', 'website', facts).href, 'https://a.example.com/');
  assert.equal(displayableLink('https://b.example.com/', 'website', facts), null, 'no fact carries this URL');
  assert.equal(displayableLink('https://a.example.com/', 'booking_url', facts), null, 'a fact for another field');
  assert.equal(displayableLink('http://a.example.com/', 'website', [{...facts[0], value_json: '"http://a.example.com/"'}]), null, 'https only');
  assert.equal(displayableLink('https://a.example.com/', 'website', [{...facts[0], confidence: 0.4}]), null);
  assert.equal(withinGoogleWindow(iso(NOW - 30 * DAY + 1000), NOW), true);
  assert.equal(withinGoogleWindow(iso(NOW - 30 * DAY - 1000), NOW), false);
  assert.equal(withinGoogleWindow(iso(NOW + DAY), NOW), false);
  assert.equal(withinGoogleWindow('not a date', NOW), false);
  assert.equal(publicVesselSql('v'), "v.status='active' AND v.profile_status='listed' AND v.removal_requested_at IS NULL");
});
