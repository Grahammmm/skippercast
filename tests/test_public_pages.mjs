// BF-port-pages: offline tests of gates, render, redirects and cache behavior.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase} from './_advisor_d1.mjs';
import aliases from '../catalog/advisor/port-aliases.json' with {type: 'json'};

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json'), 'fort-bragg-point-arena': read('../regions/fort-bragg-point-arena/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = '0123456789';
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.ADVISOR_ASSETS = {'advisor/chat.js': '/assets/chat.0123abcdef.js'};
const {default: worker} = await import('../server/index.ts');
const {pagesDeps, flagsVersion} = await import('../server/routes/advisor.ts');
const {portPageKey} = await import('../server/advisor/pages/port.ts');
const {publicPagesSettings} = await import('../server/pages-settings.ts');
const now = Date.parse('2026-09-28T19:00:00Z');
const daily = read('./fixtures/feeds/daily-latest.json');
const intel = read('./fixtures/feeds/intelligence.json');
const delta = Date.parse('2026-09-28T14:00:00Z') / 1000 - intel.forecast.models.gfs_global.data[0].hourly.time[0];
function shift(o) {
  if (Array.isArray(o)) return o.forEach(shift);
  if (!o || typeof o !== 'object') return;
  for (const [k, v] of Object.entries(o)) if (k === 'time' && Array.isArray(v) && v.every(Number.isFinite)) o[k] = v.map(x => x + delta); else shift(v);
}
shift(intel.forecast);
for (const model of Object.values(intel.forecast.models)) if (model?.data && !model.error) model.meta = {...model.meta, last_run_initialisation_time: now / 1000};
pagesDeps.clock = () => now;
const fresh = async url => /intelligence\.json$/.test(url) ? intel : daily;
pagesDeps.feeds = fresh;
const origin = 'https://skippercast.com';
const assets = {fetch: async () => new Response('site', {status: 299})};
const get = (path, env = {}) => worker.fetch(new Request(origin + path), {ASSETS: assets, ...env});
const pub = {PUBLIC_PAGES_ENABLED: 'true'};
const advisor = {TEXT_ADVISOR_ENABLED: 'true'};
function fakeCache() {
  const data = new Map();
  globalThis.caches = {default: {async match(k) { return data.get(k.url)?.clone(); }, async put(k, v) { data.set(k.url, v.clone()); }}};
  return data;
}

test('default-off gate, strict flag parsing and other advisor paths remain dark', async () => {
  const {sql, db} = advisorDatabase();
  try {
    for (const flag of [undefined, '', 'yes', '1', 'tru', 'false']) {
      assert.equal(publicPagesSettings({PUBLIC_PAGES_ENABLED: flag}).enabled, false);
      for (const path of ['/ports/morro-bay', '/species/lingcod']) {
        const r = await get(path, {DB: db, PUBLIC_PAGES_ENABLED: flag});
        assert.equal(r.status, 404, `${flag}: ${path}`);
        const payload = await r.json(); assert.equal(payload.error, 'Not found'); assert.equal(typeof payload.request_id, 'string');
      }
    }
    for (const flag of ['true', 'TRUE ']) for (const path of ['/ports/morro-bay', '/species/lingcod']) {
      assert.equal((await get(path, {DB: db, PUBLIC_PAGES_ENABLED: flag})).status, 200, path);
    }
    assert.equal((await get('/ports/morro-bay', {...advisor, DB: db})).status, 200);
    for (const path of ['/api/advisor/health', '/media/test', '/u', '/text', '/qr/text.svg', '/chat.html']) {
      assert.equal((await get(path, {...pub, DB: db})).status, 404, path);
    }
  } finally { sql.close(); }
});

test('advisor-off port and species pages omit advisor affordances; on preserves them', async () => {
  const {sql, db} = advisorDatabase();
  try {
    for (const path of ['/ports/morro-bay', '/species/lingcod']) {
      const off = await (await get(path, {...pub, DB: db})).text();
      const on = await (await get(path, {...advisor, DB: db})).text();
      for (const s of ['adv-cta', '/qr/text.svg', 'advisor-chat', 'chat.0123abcdef.js']) {
        assert.ok(!off.includes(s), `${path} off: ${s}`);
        assert.ok(on.includes(s), `${path} on: ${s}`);
      }
    }
    const moved = await get('/species/california-halibut?lang=es', {...pub, DB: db});
    assert.equal(moved.status, 301);
    assert.equal(moved.headers.get('location'), '/species/halibut?lang=es');
  } finally { sql.close(); }
});

test('search metadata, map and server HTML are localized without stronger claims', async () => {
  const {sql, db} = advisorDatabase();
  try {
    for (const [id, name, region] of [['morro-bay', 'Morro Bay', 'morro-bay'], ['noyo-harbor', 'Noyo Harbor · Fort Bragg', 'fort-bragg-point-arena']]) {
      for (const lang of ['en', 'es']) {
        const page = await (await get(`/ports/${id}?lang=${lang}`, {...pub, DB: db})).text();
        const title = lang === 'en' ? `${name} fishing conditions` : `Condiciones de pesca en ${name}`;
        assert.ok(page.includes(`<title>${title} · SkipperCast</title>`));
        assert.ok(page.includes(`<h1>${title}</h1>`));
        assert.ok(page.includes(`<link rel="canonical" href="${origin}/ports/${id}${lang === 'es' ? '?lang=es' : ''}">`));
        assert.match(page, /hreflang="en"/); assert.match(page, /hreflang="es"/);
        assert.ok(page.includes(`href="/map?region=${region}&amp;port=${id}"`));
        assert.ok(page.includes(lang === 'en' ? `Open the ${name} map` : `Abrir el mapa de ${name}`));
        const desc = page.match(/<meta name="description" content="([^"]*)">/)[1];
        assert.doesNotMatch(`${title} ${desc}`, /\b(?:go|confidence|best|bite|biting|hotspot|odds|chance)\b|%|guarantee/i);
        if (lang === 'en') assert.ok(desc.includes(`Today&#39;s wind and sea conditions, advisories and fishing seasons for ${name}, from the same sources as the SkipperCast map. Updated through the day.`));
      }
    }
  } finally { sql.close(); }
});

test('canonical aliases redirect safely, unknowns do not echo, duplicates are rejected', async () => {
  const {sql, db} = advisorDatabase();
  try {
    for (const path of ['/ports/Morro-Bay?lang=es', '/ports/morro-bay/?lang=es', '/ports/MB?lang=es', '/ports/%20Morro%20Bay%20?lang=es']) {
      const r = await get(path, {...pub, DB: db});
      assert.equal(r.status, 301, path); assert.equal(r.headers.get('location'), '/ports/morro-bay?lang=es');
      assert.equal(r.headers.get('cache-control'), 'public, max-age=86400'); assert.equal(await r.text(), '');
    }
    const blank = await get('/ports/', {...pub, DB: db});
    assert.equal(blank.status, 404); assert.match(await blank.text(), /name="robots" content="noindex"/);
    for (const id of ['%2e%2e', 'atlantis', '__proto__', 'constructor', 'x'.repeat(300), '%3Cscript%3E', 'san-diego']) {
      const r = await get('/ports/' + id, {...pub, DB: db});
      assert.equal(r.status, 404, id); const body = await r.text();
      assert.ok(!body.includes(id)); assert.match(body, /name="robots" content="noindex"/);
    }
    aliases.ports['port-san-luis'].aliases.push('MB');
    try { assert.equal(portPageKey('MB'), null); assert.equal((await get('/ports/MB', {...pub, DB: db})).status, 404); }
    finally { aliases.ports['port-san-luis'].aliases.pop(); }
  } finally { sql.close(); }
});

test('conditions present cache; feed failure and expired run are noindex and never cached', async () => {
  const {sql, db} = advisorDatabase();
  const cache = fakeCache();
  try {
    const env = {...pub, DB: db};
    const r = await get('/ports/morro-bay', env), body = await r.text();
    assert.equal(r.status, 200); assert.equal(r.headers.get('cache-control'), 'public, max-age=300');
    assert.ok(!body.includes('name="robots"')); assert.match(body, /<time datetime="2026-09-28">2026-09-28<\/time>/);
    assert.equal((await get('/ports/morro-bay', env)).headers.get('x-sc-cache'), 'hit');
    cache.clear(); pagesDeps.feeds = async url => /intelligence/.test(url) ? null : daily;
    for (let i = 0; i < 2; i++) {
      const empty = await get('/ports/morro-bay', env), html = await empty.text();
      assert.equal(empty.status, 200); assert.equal(empty.headers.get('cache-control'), 'no-store');
      assert.match(html, /name="robots" content="noindex"/); assert.match(html, /No forecast for today yet/);
      assert.equal(empty.headers.get('x-sc-cache'), 'miss'); assert.equal(cache.size, 0);
    }
    pagesDeps.feeds = async url => /intelligence/.test(url) ? {...intel, forecast: {models: {}}} : daily;
    const expired = await get('/ports/morro-bay', env);
    assert.equal(expired.headers.get('cache-control'), 'no-store'); assert.match(await expired.text(), /name="robots" content="noindex"/);
    assert.notEqual(flagsVersion(pub, '0'), flagsVersion({}, '0'));
  } finally { pagesDeps.feeds = fresh; delete globalThis.caches; sql.close(); }
});

test('missing D1 and rate limiting retain their failure responses', async () => {
  const unavailable = await get('/ports/morro-bay', pub);
  assert.equal(unavailable.status, 503); assert.equal(unavailable.headers.get('cache-control'), 'no-store');
  const {sql, db} = advisorDatabase();
  try {
    const limited = await get('/ports/morro-bay', {...pub, DB: db, PUBLIC_LIMITER: {limit: async () => ({success: false})}});
    assert.equal(limited.status, 429); assert.equal(limited.headers.get('cache-control'), 'no-store');
  } finally { sql.close(); }
});
