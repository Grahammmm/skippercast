// BF-structured-data: the sitemap and robots.txt follow the public-pages switch (not only the
// advisor), list only pages that answer 200, and each indexable port and species page carries one
// WebPage JSON-LD node whose strings are the ones the page shows. Offline: node:sqlite D1, committed
// feed fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import ports from '../catalog/home-ports.json' with {type: 'json'};

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'fort-bragg-point-arena': read('../regions/fort-bragg-point-arena/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = '0123456789';
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.ADVISOR_ASSETS = {'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps, flagsVersion} = await import('../server/routes/advisor.ts');
const {layout, html, raw} = await import('../server/advisor/pages/render.ts');
const {sitemapXml, robotsTxt} = await import('../server/advisor/pages/sitemap.ts');
const {SPECIES_PAGE_KEYS} = await import('../server/advisor/pages/species.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const now = Date.parse('2026-09-28T19:00:00Z');
const daily = read('./fixtures/feeds/daily-latest.json'), intel = read('./fixtures/feeds/intelligence.json');
const delta = Date.parse('2026-09-28T14:00:00Z') / 1000 - intel.forecast.models.gfs_global.data[0].hourly.time[0];
const shift = o => {
  if (Array.isArray(o)) return o.forEach(shift);
  if (!o || typeof o !== 'object') return;
  for (const [k, v] of Object.entries(o)) if (k === 'time' && Array.isArray(v) && v.every(Number.isFinite)) o[k] = v.map(x => x + delta); else shift(v);
};
shift(intel.forecast);
for (const model of Object.values(intel.forecast.models)) if (model?.data && !model.error) model.meta = {...model.meta, last_run_initialisation_time: now / 1000};
pagesDeps.clock = () => now;
const fresh = async url => /intelligence\.json$/.test(url) ? intel : daily;
pagesDeps.feeds = fresh;
const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async () => new Response('site', {status: 299})};
const get = (path, env = {}) => worker.fetch(new Request(ORIGIN + path), {ASSETS, ...env});
const PUB = {PUBLIC_PAGES_ENABLED: 'true'}, ADV = {TEXT_ADVISOR_ENABLED: 'true'};
const T0 = '2026-09-27T12:00:00Z';
const locs = xml => [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
const entities = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const visible = page => entities(page.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' '));
const scripts = page => [...page.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map(m => JSON.parse(m[1]));
const allTypes = (v, out = new Set()) => { if (Array.isArray(v)) v.forEach(x => allTypes(x, out)); else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { if (k === '@type') out.add(x); allTypes(x, out); } return out; };
const allKeys = (v, out = new Set()) => { if (Array.isArray(v)) v.forEach(x => allKeys(x, out)); else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) { out.add(k); allKeys(x, out); } return out; };
const pageBits = page => ({title: entities(/<title>([\s\S]*?)<\/title>/.exec(page)[1]), description: entities(/<meta name="description" content="([^"]*)"/.exec(page)[1]),
  lang: /<html lang="([a-z]+)"/.exec(page)[1], canonical: entities(/<link rel="canonical" href="([^"]*)"/.exec(page)[1])});
function seed() {
  const {sql, db} = advisorDatabase();
  const boat = (id, slug, status) => sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,verified_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`).run(id, slug, slug, 'morro-bay', 'morro-bay', status, status === 'verified' ? T0 : null, T0, T0);
  boat('b1', 'sea-example', 'verified'); boat('b2', 'gray-example', 'pending');
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,version,published_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run('r1', 'b1', 'morro-bay', 'morro-bay', '2026-09-27', 'full-day', 5, '[]', 'count-text', 'published', 1, 1, T0, T0, T0);
  const operator = (id, consent) => sql.prepare(`INSERT INTO fleet_operators(id,region,slug,name,consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)`).run(id, 'morro-bay', id, id, consent, T0, T0);
  operator('op-yes', 'content-sharing'); operator('op-no', 'unknown');
  const vessel = (id, op) => sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,port_id,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'morro-bay','active','listed',?,?,?,?)`).run(id, 'morro-bay', id, id, id.toUpperCase(), op, T0, T0, T0, T0);
  vessel('fleet-yes', 'op-yes'); vessel('fleet-no', 'op-no');
  return {sql, db};
}
const withDb = fn => async () => { const {sql, db} = seed(); try { await fn(db); } finally { sql.close(); delete globalThis.caches; } };
const activePorts = ports.ports.filter(p => Object.hasOwn(globalThis.REGIONS, p.region) && globalThis.REGIONS[p.region].status === 'active').map(p => `/ports/${p.id}`);

dbTest('flag matrix: sitemap and robots.txt answer under advisor or public pages, else fall through; typos are off', withDb(async db => {
  const robots = robotsTxt(ORIGIN);
  for (const [name, env, on] of [['both off', {}, false], ['pages on', PUB, true], ['advisor on', ADV, true], ['both on', {...ADV, ...PUB}, true]]) {
    const sitemap = await get('/sitemap-advisor.xml', {...env, DB: db}), r = await get('/robots.txt', {...env, DB: db});
    assert.equal(sitemap.status, on ? 200 : 404, name); assert.equal(r.status, on ? 200 : 299, name);
    if (on) { assert.equal(await r.text(), robots, `${name}: byte for byte`); assert.match(sitemap.headers.get('content-type'), /^application\/xml/); } else assert.equal((await sitemap.json()).error, 'Not found');
  }
  for (const flag of ['yes', '1', '', 'tru', 'false']) for (const key of ['PUBLIC_PAGES_ENABLED', 'TEXT_ADVISOR_ENABLED']) {
    assert.equal((await get('/sitemap-advisor.xml', {[key]: flag, DB: db})).status, 404, `${key}=${flag}`);
    assert.equal((await get('/robots.txt', {[key]: flag, DB: db})).status, 299, `${key}=${flag}`);
  }
  assert.equal((await get('/sitemap-advisor.xml', {FLEET_ENABLED: 'true', DB: db})).status, 404, 'the fleet alone does not open the sitemap');
}));

dbTest('entries: ports of active regions and species always; boats only while the advisor is on; fleet vessels only while the fleet is on; no lastmod on ports or species', withDb(async db => {
  const text = async env => await (await get('/sitemap-advisor.xml', {...env, DB: db})).text();
  const pagesOnly = await text(PUB), list = locs(pagesOnly).map(l => l.replace(ORIGIN, ''));
  assert.ok(activePorts.length >= 2 && activePorts.length < ports.ports.length, 'a draft-region port is excluded');
  assert.deepEqual(list.filter(l => l.startsWith('/ports/')), activePorts);
  assert.ok(!list.some(l => l.includes('fort-bragg') || /ports\/(?:san-diego|crescent-city)/.test(l)), 'preview and draft regions absent');
  assert.equal(list.filter(l => l.startsWith('/species/')).length, SPECIES_PAGE_KEYS.length);
  assert.equal(list.filter(l => l.startsWith('/boats/')).length, 0, 'advisor off: no advisor boats (they would 404)');
  const withAdvisor = await text({...PUB, ...ADV}), adv = locs(withAdvisor).map(l => l.replace(ORIGIN, ''));
  assert.deepEqual(adv.filter(l => l.startsWith('/boats/')), ['/boats/sea-example'], 'verified boats only');
  assert.match(withAdvisor, /boats\/sea-example<\/loc>\n    <lastmod>2026-09-27<\/lastmod>/);
  assert.deepEqual((await text({...PUB, FLEET_ENABLED: 'true'})).match(/boats\/[a-z-]+<\/loc>/g), ['boats/fleet-yes</loc>'], 'consenting vessel only, and no advisor boat');
  const everything = await text({...PUB, ...ADV, FLEET_ENABLED: 'true'}), all = locs(everything);
  assert.equal(new Set(all).size, all.length, 'every loc is unique');
  assert.ok(all.every(l => l.startsWith('https://')) && all.length < 50000);
  assert.equal(all.length, activePorts.length + SPECIES_PAGE_KEYS.length + 2);
  assert.equal((everything.match(/hreflang="en"/g) || []).length, all.length); assert.equal((everything.match(/hreflang="es" href="[^"]+\?lang=es"/g) || []).length, all.length);
  for (const block of everything.split('<url>').slice(1)) if (/\/(?:ports|species)\//.test(block)) assert.ok(!block.includes('<lastmod>'), block);
}));

test('xml safety: a name or slug with & < " is escaped in loc and href', async () => {
  const slug = 'a&b<c"d', fake = {prepare: () => ({all: async () => ({results: [{slug, lastmod: '2026-01-01'}]})})};
  const xml = await sitemapXml(fake, ORIGIN, {advisor: true});
  assert.ok(xml.includes('/boats/a&amp;b&lt;c&quot;d</loc>') && xml.includes('href="https://skippercast.com/boats/a&amp;b&lt;c&quot;d?lang=es"'));
  assert.ok(!xml.includes('a&b') && !xml.includes('<c"d'));
  assert.ok(!(await sitemapXml(fake, ORIGIN, {advisor: false})).includes('/boats/'), 'advisor false never queries boats');
});

dbTest('cache: the public-pages flag changes the key, existing flag states keep theirs, a cached 200 is not served after the flag goes off', withDb(async db => {
  assert.equal(flagsVersion({}, 'v'), 'v'); assert.equal(flagsVersion(ADV, 'v'), 'v');
  assert.equal(flagsVersion({FLEET_ENABLED: 'true'}, 'v'), 'v:fleet-solo'); assert.equal(flagsVersion({...ADV, FLEET_ENABLED: 'true'}, 'v'), 'v:fleet');
  assert.notEqual(flagsVersion(PUB, 'v'), flagsVersion({}, 'v')); assert.notEqual(flagsVersion({...PUB, ...ADV}, 'v'), flagsVersion(ADV, 'v'));
  const store = new Map();
  globalThis.caches = {default: {async match(k) { return store.get(k.url)?.clone(); }, async put(k, v) { store.set(k.url, v.clone()); }}};
  assert.equal((await get('/sitemap-advisor.xml', {DB: db})).status, 404);
  assert.equal((await get('/sitemap-advisor.xml', {...PUB, DB: db})).status, 200); assert.equal(store.size, 1);
  assert.equal((await get('/sitemap-advisor.xml', {DB: db})).status, 404, 'off again: the cached 200 is not served');
  assert.equal((await get('/sitemap-advisor.xml', {...PUB, DB: db})).status, 200);
}));

dbTest('JSON-LD on a port page: exactly the declared types, no ratings, and every string is the page\'s own (en and es)', withDb(async db => {
  for (const [q, lang] of [['', 'en'], ['?lang=es', 'es']]) {
    const page = await (await get('/ports/morro-bay' + q, {...PUB, DB: db})).text(), nodes = scripts(page)[0], bits = pageBits(page);
    assert.equal(scripts(page).length, 1); assert.equal(nodes.length, 3);
    assert.deepEqual([...allTypes(nodes)].sort(), ['AdministrativeArea', 'BreadcrumbList', 'GeoCoordinates', 'ListItem', 'Organization', 'Place', 'WebPage', 'WebSite']);
    const keys = allKeys(nodes);
    for (const bad of ['aggregateRating', 'review', 'offers', 'dateModified', 'datePublished', 'speakable']) assert.ok(!keys.has(bad), bad);
    const web = nodes.find(n => n['@type'] === 'WebPage');
    assert.equal(bits.lang, lang); assert.equal(web.inLanguage, bits.lang); assert.equal(web.url, bits.canonical); assert.equal(web['@id'], `${bits.canonical}#webpage`);
    assert.equal(web.name, bits.title); assert.equal(web.description, bits.description);
    assert.equal(bits.canonical, lang === 'es' ? `${ORIGIN}/ports/morro-bay?lang=es` : `${ORIGIN}/ports/morro-bay`);
    assert.ok(visible(page).includes(web.about.name) && web.about.name === 'Morro Bay');
    assert.deepEqual(web.about.geo, {'@type': 'GeoCoordinates', latitude: 35.367, longitude: -120.868});
    assert.equal(web.about.containedInPlace['@type'], 'AdministrativeArea'); assert.ok(visible(page).includes(web.about.containedInPlace.name));
    assert.equal(lang === 'es', /[¿ñáéíóú]|Condiciones/.test(web.name + web.description), 'Spanish strings only on the Spanish page');
  }
}));

test('layout: geo only for finite in-range coordinates, the page node never reaches boat, missing or noindex pages, Organization and BreadcrumbList are unchanged', () => {
  const page = o => ({language: 'en', kind: 'port', path: '/ports/x', title: 'X fishing conditions · SkipperCast', description: 'D', crumbs: [{name: 'Ports', path: null}, {name: 'X', path: '/ports/x'}], body: html``, ...o});
  const site = {publicBase: ORIGIN, number: null}, ld = o => scripts(layout(page(o), site))[0];
  const node = o => ld({about: {type: 'Place', name: 'X', region: 'R', ...o}}).find(n => n['@type'] === 'WebPage');
  assert.equal(node({geo: [35.1, -120.2]}).about.geo.latitude, 35.1);
  for (const geo of [undefined, [NaN, 1], [95, 0], [0, 181], [Infinity, 0], [1]]) assert.ok(!('geo' in node({geo}).about), String(geo));
  assert.ok(!('containedInPlace' in node({region: undefined}).about));
  const base = '[{"@context":"https://schema.org","@type":"Organization","name":"SkipperCast","url":"https://skippercast.com/","logo":"https://skippercast.com/app-icon-512.png"},'
    + '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"SkipperCast","item":"https://skippercast.com/"},{"@type":"ListItem","position":2,"name":"X","item":"https://skippercast.com/ports/x"}]}';
  const about = {type: 'Place', name: 'X'};
  for (const o of [{kind: 'port'}, {kind: 'species', path: '/ports/x'}]) assert.equal(JSON.stringify(ld(o)), base + ']', 'no about: unchanged');
  for (const o of [{kind: 'boat', about}, {kind: 'missing', about}, {kind: 'port', about, noindex: true}, {kind: 'species', about, noindex: true}]) assert.equal(JSON.stringify(ld(o)), base + ']', `${o.kind} noindex=${o.noindex}: no WebPage`);
  assert.ok(JSON.stringify(ld({about})).startsWith(base + ','), 'the first two nodes are byte-identical');
});

dbTest('species page: Thing with the other language\'s name; a missing name is omitted, never empty; a synonym redirects without a node', withDb(async db => {
  for (const q of ['', '?lang=es']) {
    const page = await (await get('/species/lingcod' + q, {...PUB, DB: db})).text(), web = scripts(page)[0].find(n => n['@type'] === 'WebPage'), bits = pageBits(page);
    assert.equal(web.about['@type'], 'Thing'); assert.equal(web.url, bits.canonical); assert.equal(web.inLanguage, bits.lang); assert.equal(web.name, bits.title);
    assert.ok(visible(page).includes(web.about.name)); assert.ok(web.about.alternateName);
    assert.ok(![...allTypes(scripts(page)[0])].some(t => ['Review', 'AggregateRating', 'FAQPage', 'HowTo', 'Event', 'Product', 'Offer', 'Dataset'].includes(t)));
  }
  const es = scripts(await (await get('/species/rockfish?lang=es', {...PUB, DB: db})).text())[0].find(n => n['@type'] === 'WebPage'), en = scripts(await (await get('/species/rockfish', {...PUB, DB: db})).text())[0].find(n => n['@type'] === 'WebPage');
  assert.equal(es.about.alternateName, en.about.name); assert.equal(en.about.alternateName, es.about.name); assert.notEqual(en.about.name, es.about.name);
  const moved = await get('/species/california-halibut', {...PUB, DB: db});
  assert.equal(moved.status, 301); assert.equal(await moved.text(), '');
  const none = layout({language: 'es', kind: 'species', path: '/species/x', title: 'T', description: 'D', crumbs: [], body: html``, about: {type: 'Thing', name: 'N', alternateName: ''}}, {publicBase: ORIGIN, number: null});
  assert.ok(!('alternateName' in scripts(none)[0].find(n => n['@type'] === 'WebPage').about), 'an empty alternateName is omitted');
}));

dbTest('noindex pages carry no WebPage node: a port with no conditions, an unverified boat and a missing page', withDb(async db => {
  const types = page => [...allTypes(scripts(page)[0])];
  pagesDeps.feeds = async url => /intelligence/.test(url) ? null : daily;
  try {
    const port = await (await get('/ports/morro-bay', {...PUB, DB: db})).text();
    assert.match(port, /name="robots" content="noindex"/); assert.ok(!types(port).includes('WebPage'));
  } finally { pagesDeps.feeds = fresh; }
  const boat = await (await get('/boats/gray-example', {...ADV, DB: db})).text();
  assert.match(boat, /name="robots" content="noindex"/); assert.ok(!types(boat).includes('WebPage'));
  const missing = await get('/ports/atlantis', {...PUB, DB: db});
  assert.equal(missing.status, 404); assert.ok(!types(await missing.text()).includes('WebPage'));
  const sea = await (await get('/boats/sea-example', {...ADV, DB: db})).text();
  assert.deepEqual(types(sea).sort(), ['BreadcrumbList', 'ListItem', 'Organization'], 'a verified boat page is unchanged: no WebPage');
}));

test('escaping: a name that closes the script element leaves one JSON-LD script and parses back intact', () => {
  const evil = '</script><script>alert(1)</script>';
  for (const about of [{type: 'Place', name: evil, region: evil}, {type: 'Thing', name: evil, alternateName: evil}]) {
    const page = layout({language: 'en', kind: about.type === 'Place' ? 'port' : 'species', path: '/x', title: evil, description: evil, crumbs: [], body: html`${raw('')}`, about}, {publicBase: ORIGIN, number: null});
    assert.equal((page.match(/<script type="application\/ld\+json">/g) || []).length, 1); assert.ok(!page.includes('<script>alert(1)'));
    const web = scripts(page)[0].find(n => n['@type'] === 'WebPage');
    assert.equal(web.about.name, evil); assert.equal(web.name, evil);
  }
});
