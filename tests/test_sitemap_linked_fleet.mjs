// RF1110-2: with the advisor off the verified-boat page answers 404 but the linked registry page stays
// indexable, so the sitemap lists it; with the advisor on the verified boat's page is the main one and
// the registry alias is suppressed. Offline: migrated node:sqlite D1, synthetic rows, a fixed clock.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = '0123456789';
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.ADVISOR_ASSETS = {'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps} = await import('../server/routes/advisor.ts');
const {sitemapXml, sitemapEntries} = await import('../server/advisor/pages/sitemap.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const NOW = Date.parse('2026-09-28T19:00:00Z');
pagesDeps.clock = () => NOW;
pagesDeps.feeds = async url => { throw Error(`no feed in this test: ${url}`); };
delete globalThis.caches;
const realFetch = globalThis.fetch;
globalThis.fetch = async url => { throw Error(`unexpected fetch: ${url}`); };
test.after(() => { globalThis.fetch = realFetch; });

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async () => new Response('site', {status: 299})};
const PUB = {PUBLIC_PAGES_ENABLED: 'true'}, ADV = {TEXT_ADVISOR_ENABLED: 'true'}, FLEET = {FLEET_ENABLED: 'true'};
const T0 = '2026-09-27T12:00:00Z';
const get = (path, env) => worker.fetch(new Request(ORIGIN + path), {ASSETS, ...env});
const locs = xml => [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1].replace(ORIGIN, ''));
const boatLocs = xml => locs(xml).filter(l => l.startsWith('/boats/'));

function seed(rows) {
  const {sql, db} = advisorDatabase();
  const operator = (id, consent, revoked = null) => sql.prepare(`INSERT INTO fleet_operators(id,region,slug,name,consent_status,consent_revoked_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)`).run(id, 'morro-bay', id, id, consent, revoked, T0, T0);
  const vessel = (id, op, {status = 'active', profile = 'listed', removal = null} = {}) => sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,port_id,status,profile_status,removal_requested_at,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'morro-bay',?,?,?,?,?,?,?)`)
    .run(id, 'morro-bay', id, id, id.toUpperCase(), op, status, profile, removal, T0, T0, T0, T0);
  const boat = (id, slug, status, vesselId) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,verified_at,fleet_vessel_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(id, slug, slug, 'morro-bay', 'morro-bay', status, status === 'verified' ? T0 : null, vesselId, T0, T0);
  rows({operator, vessel, boat});
  return {sql, db};
}
const withDb = (rows, fn) => async () => { const {sql, db} = seed(rows); try { await fn(db); } finally { sql.close(); } };

const linkedRows = ({operator, vessel, boat}) => {
  operator('op-yes', 'content-sharing');
  vessel('reg-linked', 'op-yes');
  boat('b1', 'adv-linked', 'verified', 'reg-linked');
};

dbTest('linked_registry_is_listed_when_advisor_off', withDb(linkedRows, async db => {
  const env = {...PUB, ...FLEET, DB: db};
  const xml = await (await get('/sitemap-advisor.xml', env)).text();
  assert.deepEqual(boatLocs(xml), ['/boats/reg-linked'], 'registry path once, no advisor path');
  const block = xml.split('<url>').find(b => b.includes('/boats/reg-linked</loc>'));
  assert.match(block, /<lastmod>2026-09-27<\/lastmod>/);
  assert.ok(block.includes('hreflang="en" href="https://skippercast.com/boats/reg-linked"'));
  assert.ok(block.includes('hreflang="es" href="https://skippercast.com/boats/reg-linked?lang=es"'));
  const page = await get('/boats/reg-linked', env);
  assert.equal(page.status, 200);
  assert.ok(!(await page.text()).includes('name="robots" content="noindex"'), 'the listed registry page is indexable');
  assert.equal((await get('/boats/adv-linked', env)).status, 404, 'the advisor page is off');
}));

dbTest('linked_registry_yields_to_verified_advisor_when_on', withDb(linkedRows, async db => {
  const env = {...PUB, ...ADV, ...FLEET, DB: db};
  const xml = await (await get('/sitemap-advisor.xml', env)).text();
  assert.deepEqual(boatLocs(xml), ['/boats/adv-linked'], 'advisor path once, registry alias absent');
  const page = await get('/boats/reg-linked', env);
  assert.equal(page.status, 200);
  assert.ok((await page.text()).includes('name="robots" content="noindex"'), 'registry page stays noindex');
}));

dbTest('only_verified_links_suppress_registry', withDb(({operator, vessel, boat}) => {
  operator('op-yes', 'partner');
  for (const id of ['reg-pending', 'reg-rejected', 'reg-none', 'reg-verified']) vessel(id, 'op-yes');
  boat('b-pending', 'adv-pending', 'pending', 'reg-pending');
  boat('b-rejected', 'adv-rejected', 'rejected', 'reg-rejected');
  boat('b-verified', 'adv-verified', 'verified', 'reg-verified');
}, async db => {
  for (const advisor of [true, false]) {
    const list = (await sitemapEntries(db, {fleet: true, advisor})).map(e => e.path).filter(p => p.startsWith('/boats/'));
    const expected = ['/boats/reg-none', '/boats/reg-pending', '/boats/reg-rejected', ...(advisor ? ['/boats/adv-verified'] : ['/boats/reg-verified'])].sort();
    assert.deepEqual([...list].sort(), expected, `advisor ${advisor}`);
  }
}));

dbTest('advisor_off_does_not_relax_public_or_consent_filters', withDb(({operator, vessel, boat}) => {
  operator('op-cs', 'content-sharing'); operator('op-partner', 'partner'); operator('op-unknown', 'unknown'); operator('op-revoked', 'content-sharing', T0);
  vessel('ok-cs', 'op-cs'); vessel('ok-partner', 'op-partner');
  vessel('bad-unknown', 'op-unknown'); vessel('bad-revoked', 'op-revoked');
  vessel('bad-inactive', 'op-cs', {status: 'inactive'}); vessel('bad-unlisted', 'op-cs', {profile: 'hidden'}); vessel('bad-removal', 'op-cs', {removal: T0});
  for (const id of ['ok-cs', 'bad-unknown', 'bad-revoked', 'bad-inactive', 'bad-unlisted', 'bad-removal']) boat(`b-${id}`, `adv-${id}`, 'verified', id);
}, async db => {
  const advisorOff = (await sitemapEntries(db, {fleet: true, advisor: false})).map(e => e.path).filter(p => p.startsWith('/boats/')).sort();
  assert.deepEqual(advisorOff, ['/boats/ok-cs', '/boats/ok-partner']);
  const advisorOn = (await sitemapEntries(db, {fleet: true, advisor: true})).map(e => e.path).filter(p => p.startsWith('/boats/')).sort();
  assert.deepEqual(advisorOn, ['/boats/adv-bad-inactive', '/boats/adv-bad-removal', '/boats/adv-bad-revoked', '/boats/adv-bad-unknown', '/boats/adv-bad-unlisted', '/boats/adv-ok-cs', '/boats/ok-partner']);
}));

dbTest('fleet_disabled_and_empty_database_keep_existing_entries', withDb(linkedRows, async db => {
  const xml = await sitemapXml(db, ORIGIN, {fleet: false, advisor: false});
  assert.deepEqual(boatLocs(xml), [], 'no registry path with the fleet off');
  assert.ok(locs(xml).some(l => l.startsWith('/ports/')) && locs(xml).some(l => l.startsWith('/species/')));
  assert.deepEqual(boatLocs(await sitemapXml(db, ORIGIN, {fleet: false, advisor: true})), ['/boats/adv-linked']);
  const all = locs(await sitemapXml(db, ORIGIN, {fleet: true, advisor: false}));
  assert.equal(new Set(all).size, all.length, 'every loc is unique');
  const empty = advisorDatabase();
  try { assert.deepEqual(boatLocs(await sitemapXml(empty.db, ORIGIN, {fleet: true, advisor: true})), []); } finally { empty.sql.close(); }
}));
